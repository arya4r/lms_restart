"""3-wheeler lease (L3): booking one loan, and bulk import from the L3 CSV layout.

Stored in the normal loan tables and as GENERATED rows in rps_rows (which the loan position,
DPD, late charges and foreclosure read). The advance EMI is row 0, already paid on disbursal,
so the payment logic needs no special case. Rows are numbered in order: 0 = advance, then the
BPI (if any), then EMIs; the master sheet's own EMI number is kept in each RPS row's payload.
"""
import csv
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import insert
from sqlalchemy.orm import Session

from ..engine import lease3w as L
from ..models import Customer, Installment, Loan, LoanProduct, RpsRow
from .loan_service import LmsError, audit

ALIASES = {
    "lan": ["id", "loanid", "lan", "lanid"],
    "name": ["customername", "name"],
    "mobile": ["customermobile", "mobile"],
    "dealer": ["dealername", "dealer"],
    "disb": ["dateofdisbursement", "disbursementdate", "deliverydate", "paymentdate"],
    "status": ["status"],
    "vehicle": ["vehiclevalue", "invoicevalue"],
    "insurance": ["insuranace", "insurance", "insuranceamount"],
    "rto": ["rtocharges", "rto"],
    "kazam": ["kazamearthing", "earthingkazam", "kazam"],
    "misc": ["miscexp", "misc", "miscexpenses"],
    "hsrp": ["hsrpfornumberplate", "hsrp"],
    "scheme": ["schemediscountdp", "schemediscount", "creditnote"],
}
BATCH = 1000
GROUP = 50          # loans saved per commit during a bulk import
MONEY_KEYS = ("vehicle", "insurance", "rto", "kazam", "misc", "hsrp", "scheme")


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def ensure_product(db: Session) -> LoanProduct:
    """The L3 product, created on first use. L3 loans carry no late charge and no foreclosure
    (both are also blocked in code for LEASE_3W loans, whatever the product settings say)."""
    p = db.query(LoanProduct).filter(LoanProduct.code == L.PRODUCT_CODE).first()
    if p:
        return p
    p = LoanProduct(code=L.PRODUCT_CODE, name="3-wheeler lease (L3)", interest_method="LEASE_3W",
                    default_rate=Decimal("0"), min_tenure=L.TENURE, max_tenure=L.TENURE,
                    min_amount=Decimal("0"), max_amount=Decimal("10000000"),
                    apportion_mode="HEAD_WISE", excess_mode="HOLD", late_fee=Decimal("0"),
                    grace_days=0, processing_fee_pct=Decimal("0.75"), active=True)
    db.add(p)
    db.flush()
    return p


def _parse_date(s: str, dayfirst=True) -> date:
    s = str(s).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    for fmt in (("%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y") if dayfirst
                else ("%m-%d-%Y", "%m/%d/%Y")):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unrecognised date '{s}'")


def _money(s) -> Decimal:
    t = str(s).replace(",", "").strip()
    if t in ("", "-", "nan", "None"):
        return Decimal("0")
    try:
        return Decimal(t)
    except InvalidOperation:
        raise ValueError(f"not a number '{s}'")


def _inputs_from_form(f: dict) -> dict:
    out = {k: _money(f.get(k, 0)) for k in MONEY_KEYS}
    if out["vehicle"] <= 0:
        raise LmsError("Vehicle value is required")
    return out


def _schedule(inputs: dict, disb: date):
    deal = L.calc_deal(**inputs)
    branch, rows, adj = L.build_schedule(disb, deal)
    return deal, branch, rows, adj


def preview(inputs: dict, disb: date) -> dict:
    deal, branch, rows, adj = _schedule(inputs, disb)
    return {
        "branch": branch,
        "deal": {"loan": str(deal.loan), "gst_ic": str(deal.ic), "security_deposit": str(deal.sd),
                 "processing_fee": str(deal.pf.quantize(Decimal("0.01"))),
                 "net_outflow": str(deal.net), "emi": str(deal.emi),
                 "roi_annual_pct": str((deal.roi * 100).quantize(Decimal("0.0001"))),
                 "lines": [{"head": l["head"], "value": str(l["value"]), "gst": str(l["gst"]),
                            "total": str(l["total"]), "ic": str(l["ic"])} for l in deal.lines]},
        "adjustment": str(adj),
        "rows": [{"kind": r.kind, "installment_no": r.no, "due_date": r.due.isoformat(),
                  "days": r.days, "opening_balance": None if r.opening is None else str(r.opening),
                  "interest": str(r.interest), "principal": str(r.principal),
                  "emi": str(r.emi), "closing_balance": None if r.closing is None else str(r.closing)}
                 for r in rows],
    }


def _rows_for(lan: str, rows, disb: date, user: str | None):
    """Installment and RPS row values for one loan (installments without loan_id yet)."""
    insts, rps = [], []
    bal_before_bpi = rows[0].closing + rows[0].principal
    for n, r in enumerate(rows):
        is_adv = r.kind == "ADVANCE"
        paid = r.principal if is_adv else None
        insts.append(dict(
            installment_no=n, due_date=r.due, opening_balance=r.opening or Decimal("0"),
            principal_due=r.principal, interest_due=r.interest,
            opening_principal_paid=r.principal if is_adv else Decimal("0"),
            opening_interest_paid=Decimal("0"),
            principal_paid=r.principal if is_adv else Decimal("0"), interest_paid=Decimal("0"),
            status="PAID" if is_adv else "DUE"))
        rps.append(dict(
            loan_number=lan, row_no=n, installment_no=n, due_date=r.due, emi_amount=r.emi,
            principal_component=r.principal, interest_component=r.interest,
            closing_balance=r.closing if r.closing is not None else bal_before_bpi,
            principal_paid=paid, interest_paid=Decimal("0") if is_adv else None,
            paid_date=disb if is_adv else None,
            base_principal_paid=paid, base_interest_paid=Decimal("0") if is_adv else None,
            base_paid_date=disb if is_adv else None, source="GENERATED",
            payload=json.dumps({"generated": True, "product": L.PRODUCT_CODE, "kind": r.kind,
                                "sheet_no": r.no, "days": r.days}, default=str),
            created_by=user))
        if r.closing is not None:
            bal_before_bpi = r.closing
    return insts, rps


def _loan_values(lan, customer_id, product, deal, branch, rows, disb, dealer, user) -> dict:
    opening = rows[0].closing + rows[0].principal           # ROUNDUP(net outflow)
    return dict(
        loan_number=lan, external_loan_id=lan, source="NATIVE", customer_id=customer_id,
        product_id=product.id, principal=opening,
        annual_rate=(deal.roi * 100).quantize(Decimal("0.0001")), tenure_months=L.TENURE,
        interest_method="LEASE_3W", disbursal_date=disb,
        first_due_date=next(r.due for r in rows if r.kind != "ADVANCE"), emi_amount=deal.emi,
        processing_fee=deal.pf.quantize(Decimal("0.01")), apportion_mode=product.apportion_mode,
        excess_mode=product.excess_mode, status="ACTIVE", excess_amount=Decimal("0"),
        opening_excess=Decimal("0"), loan_amount=deal.loan.quantize(Decimal("0.01")),
        details=json.dumps({"dealer": dealer, "branch": branch, "lan": lan}, default=str),
        created_by=user)


def _insert_many(db: Session, model, values: list[dict], chunk: int = BATCH):
    """Multi-row INSERTs, `chunk` rows per statement (one round trip each to the database)."""
    for i in range(0, len(values), chunk):
        # Core table insert (not ORM bulk): keeps NULL columns, so every row has the same
        # columns and the whole chunk goes as one multi-row INSERT
        db.execute(insert(model.__table__), values[i:i + chunk])


def _book(db: Session, *, lan: str, name: str, mobile: str, dealer: str, inputs: dict,
          disb: date, user: str | None) -> Loan:
    product = ensure_product(db)
    deal, branch, rows, _ = _schedule(inputs, disb)
    customer = db.query(Customer).filter(Customer.external_ref == f"L3:{lan}").first()
    if not customer:
        customer = Customer(external_ref=f"L3:{lan}", name=name or lan, mobile=mobile or None)
        db.add(customer)
        db.flush()
    loan = Loan(**_loan_values(lan, customer.id, product, deal, branch, rows, disb, dealer, user))
    db.add(loan)
    db.flush()
    insts, rps = _rows_for(lan, rows, disb, user)
    _insert_many(db, Installment, [dict(d, loan_id=loan.id) for d in insts])
    _insert_many(db, RpsRow, rps)
    audit(db, user, "BOOK_LEASE_3W", "loan", lan, {"loan": deal.loan, "emi": deal.emi, "branch": branch})
    return loan


def book_one(db: Session, *, lan: str, name: str, mobile: str, dealer: str, form: dict,
             disb: date, user: str | None) -> Loan:
    if not lan.strip():
        raise LmsError("Loan ID is required")
    if db.query(Loan).filter(Loan.loan_number == lan).first():
        raise LmsError(f"Loan {lan} already exists")
    inputs = _inputs_from_form(form)
    return _book(db, lan=lan, name=name, mobile=mobile, dealer=dealer, inputs=inputs, disb=disb,
                 user=user)


# ------------------------------------------------------------------ bulk import

def _read_rows(raw: bytes):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    cmap = {_norm(h): h for h in headers}

    def col(key):
        for a in ALIASES[key]:
            if a in cmap:
                return cmap[a]
        return None
    missing = [k for k in ("lan", "vehicle", "insurance", "scheme") if col(k) is None]
    if missing:
        raise LmsError(f"Required columns not found: {', '.join(missing)}")
    return reader, col


def _existing(db: Session, column, values: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(values), BATCH):
        found |= {v for (v,) in db.query(column).filter(column.in_(values[i:i + BATCH])).all()}
    return found


def _write_group(db: Session, part: list[dict], product, user: str | None) -> None:
    """Customers, loans, installments and RPS rows for a group of loans, as multi-row INSERTs."""
    refs = [f"L3:{p['lan']}" for p in part]
    have = _existing(db, Customer.external_ref, refs)
    _insert_many(db, Customer, [dict(external_ref=f"L3:{p['lan']}", name=(p["name"] or p["lan"])[:160],
                                     mobile=p["mobile"] or None)
                                for p in part if f"L3:{p['lan']}" not in have])
    cust_id = dict(db.query(Customer.external_ref, Customer.id).filter(Customer.external_ref.in_(refs)).all())
    _insert_many(db, Loan, [_loan_values(p["lan"], cust_id[f"L3:{p['lan']}"], product, p["deal"],
                                         p["branch"], p["rows"], p["disb"], p["dealer"], user)
                            for p in part])
    lans = [p["lan"] for p in part]
    loan_id = dict(db.query(Loan.loan_number, Loan.id).filter(Loan.loan_number.in_(lans)).all())
    insts, rps = [], []
    for p in part:
        li, lr = _rows_for(p["lan"], p["rows"], p["disb"], user)
        insts += [dict(d, loan_id=loan_id[p["lan"]]) for d in li]
        rps += lr
    _insert_many(db, Installment, insts)
    _insert_many(db, RpsRow, rps)


def check_or_import(db: Session, raw: bytes, *, dry_run: bool, user: str | None, progress=None) -> dict:
    reader, col = _read_rows(raw)
    seen: set[str] = set()
    errors, parsed, skipped = [], [], 0
    for n, row in enumerate(reader, start=2):
        lan = (row.get(col("lan")) or "").strip()
        if not lan and not (row.get(col("vehicle")) or "").strip():
            continue                                    # blank / sub-header row
        if col("status") and (row.get(col("status")) or "").strip().lower() == "reverted":
            skipped += 1
            continue
        if col("disb") and not (row.get(col("disb")) or "").strip():
            skipped += 1                                 # not disbursed yet
            continue
        try:
            if not lan:
                raise ValueError("Loan ID is blank")
            if len(lan) > 40:
                raise ValueError("Loan ID is longer than 40 characters")
            if lan in seen:
                raise ValueError(f"duplicate Loan ID {lan} in this file")
            seen.add(lan)
            form = {k: row.get(col(k)) if col(k) else 0 for k in MONEY_KEYS}
            inputs = _inputs_from_form(form)
            disb = _parse_date(row.get(col("disb")) or "")
            deal, branch, rows, _ = _schedule(inputs, disb)
            parsed.append(dict(lan=lan, name=(row.get(col("name")) or "").strip(),
                               mobile=(row.get(col("mobile")) or "").strip()[:20],
                               dealer=(row.get(col("dealer")) or "").strip(), disb=disb,
                               deal=deal, branch=branch, rows=rows))
        except (ValueError, LmsError) as e:
            errors.append({"line": n, "loan_id": lan, "error": str(e)})

    # loans already in the LMS are skipped, never regenerated (one query per 1,000 IDs)
    exists = _existing(db, Loan.loan_number, [p["lan"] for p in parsed])
    todo = [p for p in parsed if p["lan"] not in exists]
    skipped += len(parsed) - len(todo)
    total_loan = sum((p["deal"].loan for p in todo), Decimal("0"))

    imported = 0
    if not dry_run and todo:
        product = ensure_product(db)
        if progress:
            progress(0, len(todo), f"0 imported, {len(todo)} pending")
        # saved GROUP loans at a time, so the imported count is always what is really in the database
        for g in range(0, len(todo), GROUP):
            part = todo[g:g + GROUP]
            _write_group(db, part, product, user)
            db.commit()
            imported += len(part)
            if progress:
                progress(imported, len(todo), f"{imported} imported, {len(todo) - imported} pending")
        audit(db, user, "BULK_LEASE_3W", "loan", f"{imported} loans",
              {"loans": imported, "total_loan": total_loan})
        db.commit()
    return {"dry_run": dry_run, "to_book": len(todo), "imported": imported,
            "pending": len(todo) - imported if not dry_run else len(todo), "skipped": skipped,
            "total_loan_amount": str(total_loan.quantize(Decimal("0.01"))),
            "error_count": len(errors), "errors": errors[:200]}
