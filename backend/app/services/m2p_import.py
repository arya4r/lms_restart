"""M2P migration import.

Takes the M2P exports as CSV and loads loans exactly as they stood on the
migration cutoff (default 30 Apr 2026):

  loans.csv      one row per loan (customer details inline)
  schedule.csv   one row per instalment, with interest/principal paid as at cutoff
  receipts.csv   (optional) payment history; receipts on/before cutoff are stored as
                 history only, receipts after cutoff are posted through the NEW waterfall
  charges.csv    (optional) charges with amount paid/waived as at cutoff

Column names are matched through ALIASES, so an M2P export with slightly different
headers usually works as-is; add a header to the alias list if one is not recognised.
Always run with dry_run=True first: everything is validated and reconciled, then rolled back.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import insert
from sqlalchemy.orm import Session

from dateutil.relativedelta import relativedelta

from ..engine.schedule import r2, emi_amount
from ..models import Loan, Installment, Charge, Repayment, LoanProduct, Customer, RpsRow
from .loan_service import replay, audit, book_loan, LmsError
from ..logs import log as lms_log

ZERO = Decimal("0.00")
DEFAULT_CUTOFF = date(2026, 4, 30)

# late charge and grace period for products the import creates: ₹600 after 5 days past due
DEFAULT_LATE_FEE = Decimal("600")
DEFAULT_GRACE_DAYS = 5

ALIASES = {
    "loan_id": ["nbfclan", "loan_id", "account_no", "loan_account_number", "loan_account_no", "loanaccountno", "loanaccountnumber", "lan",
                "loan_no", "loan_number", "account_number", "loan_ref"],
    "customer_id": ["clientid", "customer_id", "cust_id", "customerid", "borrower_id", "entity_id"],
    "customer_name": ["customer_name", "customername", "clientname", "borrower_name", "name", "full_name"],
    "mobile": ["mobile", "mobile_number", "leadmobilenumber", "phone", "contact_number"],
    "email": ["email", "email_id", "customeremailid"],
    "pan": ["pan", "pan_number", "pan_no"],
    "address": ["address", "customer_address", "currentaddress"],
    "product_code": ["product_code", "product", "product_id", "scheme_code", "loan_product", "productname"],
    "principal": ["totalprinciple", "principal_amount", "principal", "principle_amount", "principal_amt",
                  "principal_loan_amount"],
    "loan_amount": ["loanamount", "loan_amount", "approvedloanamount", "sanctioned_amount", "disbursed_amount",
                    "disbursal_amount"],
    "last_due_date": ["lastrepaymentdate", "last_due_date", "last_emi_date", "last_repayment_date", "maturity_date",
                      "last_installment_date"],
    "processing_fee": ["procfees", "processing_fee", "processing_fees", "processing_charges", "pf"],
    "stamp_duty": ["stampduty", "stamp_duty", "stamp_charges", "stamp_duty_charges"],
    "document_charges": ["doccharges", "document_charges", "documentation_charges", "doc_charges", "document_charge"],
    "insurance_amount": ["insurance_amount", "insurance", "insurance_premium", "insurance_charges"],
    "rsa_charge": ["rsa", "rsa_charge", "rsa_charges", "road_safety", "road_safety_charge"],
    "bounce_charge": ["bounce_charge", "bounce_charges", "bounce", "cheque_bounce_charge"],
    "annual_rate": ["annual_rate", "interest_rate", "roi", "rate_of_interest"],
    "irr": ["irr"],
    "tenure_months": ["tenure_months", "tenure", "no_of_installments", "loan_tenure", "banktenure"],
    "interest_method": ["interest_method", "interest_type", "repayment_type"],
    "disbursal_date": ["disbursal_date", "disbursement_date", "loan_start_date", "booking_date",
                        "loandisbursaldate"],
    "first_due_date": ["first_due_date", "first_emi_date", "emi_start_date", "firstrepaymentdate"],
    "emi_amount": ["emiamount", "emi_amount", "emi", "installment_amount", "bankemi"],
    "status": ["status", "loan_status", "loanstatus"],
    "system_tag": ["system"],
    "excess_amount": ["excess_amount", "excess", "unadjusted_amount", "advance_amount"],
    # schedule
    "installment_no": ["installment_no", "installment_number", "emi_no", "inst_no", "seq"],
    "due_date": ["due_date", "emi_due_date", "installment_date"],
    "principal_due": ["principal_due", "principal_component", "principal_amount", "principal"],
    "interest_due": ["interest_due", "interest_component", "interest_amount", "interest"],
    "principal_paid": ["principal_paid", "paid_principal", "principal_received"],
    "interest_paid": ["interest_paid", "paid_interest", "interest_received"],
    # receipts
    "txn_date": ["txn_date", "payment_date", "receipt_date", "value_date", "transaction_date"],
    "amount": ["amount", "receipt_amount", "payment_amount", "txn_amount"],
    "mode": ["mode", "payment_mode", "channel"],
    "reference": ["reference", "utr", "txn_id", "transaction_id", "receipt_no", "reference_no"],
    # charges
    "charge_type": ["charge_type", "fee_type", "charge_name"],
    "charge_date": ["charge_date", "levied_date", "fee_date", "date"],
    "paid": ["paid", "paid_amount", "amount_paid"],
    "waived": ["waived", "waiver_amount", "waived_amount"],
}

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%Y/%m/%d",
                "%d-%b-%y", "%m/%d/%Y")
STATUS_MAP = {"ACTIVE": "ACTIVE", "LIVE": "ACTIVE", "OPEN": "ACTIVE", "DISBURSED": "ACTIVE",
              "CLOSED": "CLOSED", "SETTLED": "CLOSED", "FORECLOSED": "FORECLOSED",
              "PRECLOSED": "FORECLOSED", "WRITTEN_OFF": "WRITTEN_OFF", "WRITTENOFF": "WRITTEN_OFF",
              "FORECLOSURECLOSED": "FORECLOSED", "OVERPAID": "ACTIVE"}


class RowError(ValueError):
    pass


def _norm(h: str) -> str:
    return h.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "")


def _decode(content: bytes | str) -> str:
    """UTF-8 when it is UTF-8; otherwise the Windows encoding that Excel saves in (which has
    non-breaking spaces and accented letters that UTF-8 rejects)."""
    if isinstance(content, str):
        return content
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _delimiter(text: str) -> str:
    """Tab-separated files (the loan master template) and comma-separated files are both read."""
    first = text.split("\n", 1)[0]
    return "\t" if first.count("\t") > first.count(",") else ","


def _read(content: bytes | str) -> list[dict]:
    text = _decode(content)
    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(text))
    if not reader.fieldnames:
        return []
    header = {_norm(h): h for h in reader.fieldnames}
    mapping = {}
    for field, aliases in ALIASES.items():
        for a in aliases:
            if a in header:
                mapping[field] = header[a]
                break
    rows = []
    for raw in reader:
        if not any((v or "").strip() for v in raw.values()):
            continue
        row = {f: (raw.get(src) or "").strip() for f, src in mapping.items()}
        row["__raw__"] = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        rows.append(row)
    return rows


def _date(v: str, field: str, required=True) -> date | None:
    if not v:
        if required:
            raise RowError(f"{field} is missing")
        return None
    v = v.split(" ")[0] if len(v) > 11 and ":" in v else v
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    raise RowError(f"{field} '{v}' is not a recognised date")


# text that means "no value" in M2P-style exports
BLANK_MARKERS = {"", "-", "na", "n/a", "null", "not there", "nil"}


def _num(v: str, field: str, required=True, default=ZERO) -> Decimal:
    if v is None or v.strip().lower() in BLANK_MARKERS:
        if required:
            raise RowError(f"{field} is missing")
        return default
    try:
        return Decimal(v.replace(",", "").replace("₹", "").replace("INR", "").strip())
    except InvalidOperation:
        raise RowError(f"{field} '{v}' is not a number")


def import_m2p(db: Session, loans_csv, schedule_csv, receipts_csv=None, charges_csv=None,
               cutoff: date = DEFAULT_CUTOFF, dry_run: bool = True, user: str | None = None) -> dict:
    report = {"dry_run": dry_run, "cutoff": cutoff.isoformat(), "loans_read": 0,
              "loans_imported": 0, "installments": 0, "receipts_history": 0,
              "receipts_post_cutoff": 0, "charges": 0, "errors": [], "warnings": [],
              "reconciliation": []}

    def err(file, row, msg):
        report["errors"].append({"file": file, "row": row, "message": msg})

    def warn(loan_id, msg):
        report["warnings"].append({"loan_id": loan_id, "message": msg})

    loan_rows = _read(loans_csv)
    sched_rows = _read(schedule_csv)
    rec_rows = _read(receipts_csv) if receipts_csv else []
    chg_rows = _read(charges_csv) if charges_csv else []
    report["loans_read"] = len(loan_rows)

    if loan_rows and "loan_id" not in loan_rows[0]:
        err("loans.csv", 1, "No loan id column found")
        return report

    sched_by, rec_by, chg_by = {}, {}, {}
    for n, r in enumerate(sched_rows, start=2):
        sched_by.setdefault(r.get("loan_id"), []).append((n, r))
    for n, r in enumerate(rec_rows, start=2):
        rec_by.setdefault(r.get("loan_id"), []).append((n, r))
    for n, r in enumerate(chg_rows, start=2):
        chg_by.setdefault(r.get("loan_id"), []).append((n, r))

    products = {p.code: p for p in db.query(LoanProduct).all()}
    known_ids = {lid for (lid,) in db.query(Loan.external_loan_id)
                 .filter(Loan.external_loan_id.isnot(None))}
    seen = set()

    for n, r in enumerate(loan_rows, start=2):
        lid = r.get("loan_id")
        try:
            if not lid:
                raise RowError("loan id is missing")
            if lid in seen:
                raise RowError("duplicate loan id in file")
            seen.add(lid)
            if lid in known_ids:
                raise RowError("already imported (skipped)")
            principal = _num(r.get("principal") or r.get("loan_amount"), "principal")
            rate = _num(r.get("annual_rate"), "annual_rate")
            tenure = int(_num(r.get("tenure_months"), "tenure_months"))
            disb = _date(r.get("disbursal_date"), "disbursal_date")
            if disb > cutoff:
                raise RowError(f"disbursed after cutoff {cutoff}; book it as a new loan instead")
            method = (r.get("interest_method") or "REDUCING").upper()
            method = "FLAT" if "FLAT" in method else "REDUCING"
            status = STATUS_MAP.get((r.get("status") or "ACTIVE").upper().replace(" ", "_"))
            if not status:
                raise RowError(f"unknown status '{r.get('status')}'")
            if not sched_by.get(lid):
                raise RowError("no schedule rows in schedule.csv")

            # schedule
            insts = []
            for sn, s in sched_by[lid]:
                try:
                    pd_, id_ = _num(s.get("principal_due"), "principal_due"), \
                        _num(s.get("interest_due"), "interest_due")
                    pp = _num(s.get("principal_paid"), "principal_paid", required=False)
                    ip = _num(s.get("interest_paid"), "interest_paid", required=False)
                    if pp > pd_ or ip > id_:
                        raise RowError("paid is more than due")
                    insts.append(dict(no=int(_num(s.get("installment_no"), "installment_no")),
                                      due=_date(s.get("due_date"), "due_date"),
                                      pd=r2(pd_), id=r2(id_), pp=r2(pp), ip=r2(ip)))
                except RowError as e:
                    raise RowError(f"schedule.csv row {sn}: {e}")
            insts.sort(key=lambda x: x["no"])
            if len({i["no"] for i in insts}) != len(insts):
                raise RowError("duplicate instalment numbers in schedule")
            sched_principal = sum((i["pd"] for i in insts), ZERO)

            # charges
            charges = []
            for cn, c in chg_by.get(lid, []):
                try:
                    amt = _num(c.get("amount"), "amount")
                    paid = _num(c.get("paid"), "paid", required=False)
                    waived = _num(c.get("waived"), "waived", required=False)
                    if paid + waived > amt:
                        raise RowError("paid + waived is more than the charge")
                    charges.append(dict(type=(c.get("charge_type") or "OTHER").upper()
                                        .replace(" ", "_")[:24],
                                        date=_date(c.get("charge_date"), "charge_date"),
                                        amt=r2(amt), paid=r2(paid), waived=r2(waived)))
                except RowError as e:
                    raise RowError(f"charges.csv row {cn}: {e}")

            # receipts
            receipts = []
            for rn, x in rec_by.get(lid, []):
                try:
                    receipts.append(dict(date=_date(x.get("txn_date"), "txn_date"),
                                         amt=r2(_num(x.get("amount"), "amount")),
                                         mode=(x.get("mode") or "M2P")[:16],
                                         ref=(x.get("reference") or None)))
                except RowError as e:
                    raise RowError(f"receipts.csv row {rn}: {e}")
        except RowError as e:
            err("loans.csv", n, f"{lid or '?'}: {e}")
            continue

        # ---- create
        cust = None
        if r.get("customer_id"):
            cust = db.query(Customer).filter(Customer.external_ref == r["customer_id"]).first()
        if not cust:
            cust = Customer(external_ref=r.get("customer_id") or None,
                            name=r.get("customer_name") or "Unknown",
                            mobile=r.get("mobile") or None, email=r.get("email") or None,
                            pan=(r.get("pan") or None), address=r.get("address") or None)
            db.add(cust)
            db.flush()

        code = r.get("product_code") or "M2P-DEFAULT"
        prod = products.get(code)
        if not prod:
            prod = LoanProduct(code=code, name=f"{code} (migrated from M2P)",
                               interest_method=method, default_rate=rate, max_tenure=600,
                               apportion_mode="HEAD_WISE", excess_mode="HOLD",
                               late_fee=DEFAULT_LATE_FEE, grace_days=DEFAULT_GRACE_DAYS)
            db.add(prod)
            db.flush()
            products[code] = prod

        emi = _num(r.get("emi_amount"), "emi_amount", required=False,
                   default=insts[min(1, len(insts) - 1)]["pd"] + insts[min(1, len(insts) - 1)]["id"])
        opening_excess = r2(_num(r.get("excess_amount"), "excess_amount", required=False))
        loan = Loan(loan_number=lid, external_loan_id=lid, source="M2P", customer_id=cust.id,
                    product_id=prod.id, principal=r2(principal), annual_rate=rate,
                    tenure_months=tenure, interest_method=method, disbursal_date=disb,
                    first_due_date=_date(r.get("first_due_date"), "first_due_date", False)
                    or insts[0]["due"], emi_amount=r2(emi),
                    apportion_mode=prod.apportion_mode, excess_mode=prod.excess_mode,
                    status=status, opening_excess=opening_excess, migration_cutoff=cutoff,
                    created_by=user)
        if status != "ACTIVE":
            loan.closed_date = max((x["date"] for x in receipts if x["date"] <= cutoff),
                                   default=cutoff)
        db.add(loan)
        db.flush()
        bal = r2(principal)
        for i in insts:
            db.add(Installment(loan_id=loan.id, installment_no=i["no"], due_date=i["due"],
                               opening_balance=bal, principal_due=i["pd"], interest_due=i["id"],
                               opening_principal_paid=i["pp"], opening_interest_paid=i["ip"],
                               principal_paid=i["pp"], interest_paid=i["ip"]))
            bal -= i["pd"]
        for c in charges:
            db.add(Charge(loan_id=loan.id, charge_type=c["type"], charge_date=c["date"],
                          amount=c["amt"], opening_paid=c["paid"], paid=c["paid"],
                          waived=c["waived"], description="Migrated from M2P"))
        hist_total = ZERO
        for x in receipts:
            historical = x["date"] <= cutoff
            db.add(Repayment(loan_id=loan.id, amount=x["amt"], payment_date=x["date"],
                             mode=x["mode"], reference=x["ref"], is_historical=historical,
                             created_by=user))
            if historical:
                hist_total += x["amt"]
                report["receipts_history"] += 1
            else:
                report["receipts_post_cutoff"] += 1
        db.flush()
        db.refresh(loan)
        replay(db, loan)

        appropriated = sum((i["pp"] + i["ip"] for i in insts), ZERO) + \
            sum((c["paid"] for c in charges), ZERO) + opening_excess
        if receipts:
            diff = hist_total - appropriated
            report["reconciliation"].append({"loan_id": lid, "receipts_till_cutoff": str(hist_total),
                                             "appropriated_in_m2p": str(appropriated),
                                             "difference": str(diff)})
        report["loans_imported"] += 1
        report["installments"] += len(insts)
        report["charges"] += len(charges)


    if dry_run:
        db.rollback()
    else:
        audit(db, user, "M2P_IMPORT", "system", cutoff.isoformat(),
              {k: report[k] for k in ("loans_imported", "installments", "charges",
                                      "receipts_history", "receipts_post_cutoff")})
        db.commit()
    report["reconciliation"] = report["reconciliation"][:500]
    return report



def _chunks(items, size=500):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def import_loan_master(db: Session, loans_csv, dry_run: bool = True, user: str | None = None,
                       progress=None) -> dict:
    """Loan master only, stored as it is in the file. No cut-off, no repayment schedule.
    Static parameters kept: loan amount, principal, disbursal, first and last repayment dates,
    EMI as shared, the charges (processing fee, stamp duty, document charges, insurance, RSA,
    bounce) and the client's details. Customers are matched by ClientId. A customer already in the
    book is updated from the file. Customers and loans are written in bulk, so the number of database
    calls does not grow with the number of rows. Only rows that cannot be saved are reported."""
    report = _single_report(dry_run)
    report["customers_new"] = 0
    report["mobiles_already_in_system"] = []

    def err(row, msg):
        report["errors"].append({"file": "loans.csv", "row": row, "message": msg})

    rows = _read(loans_csv)
    report["loans_read"] = len(rows)
    if rows and "loan_id" not in rows[0]:
        err(1, "No loan id column found")
        return report
    lms_log.info("loan master: %d rows read, dry_run=%s", len(rows), dry_run)
    if progress:
        progress(0, len(rows))

    # reads, once for the whole file
    mobiles = {r["mobile"] for r in rows if r.get("mobile")}
    if mobiles:
        known = db.query(Customer.mobile).filter(Customer.mobile.in_(mobiles)).distinct().all()
        report["mobiles_already_in_system"] = sorted(m for (m,) in known)
    products = {p.code: p for p in db.query(LoanProduct).all()}
    known_ids = {lid for (lid,) in db.query(Loan.external_loan_id).filter(Loan.external_loan_id.isnot(None))}
    loan_numbers = {ln for (ln,) in db.query(Loan.loan_number)}
    client_ids = {r["customer_id"] for r in rows if r.get("customer_id")}
    customers_by_ref = {}
    if client_ids:
        for c in db.query(Customer).filter(Customer.external_ref.in_(client_ids)):
            customers_by_ref[c.external_ref] = c
    lms_log.info("loan master: reference data read (%d customers, %d loans known)",
                 len(customers_by_ref), len(loan_numbers))

    seen = set()
    new_customers: dict[str, dict] = {}   # ClientId -> customer row to insert
    loan_rows: list[dict] = []            # loan rows to insert, customer resolved below
    new_products: list[LoanProduct] = []

    for n, r in enumerate(rows, start=2):
        lid = r.get("loan_id")
        try:
            if not lid:
                raise RowError("loan id is missing")
            if lid in seen:
                raise RowError("duplicate loan id in file")
            seen.add(lid)
            if lid in known_ids or lid in loan_numbers:
                raise RowError(f"loan account {lid} is already present in the system, so it was not uploaded again")
            loan_amount = _num(r.get("loan_amount") or r.get("principal"), "loan_amount")
            principal = _num(r.get("principal") or r.get("loan_amount"), "principal")
            if principal <= 0:
                raise RowError("principal must be positive")
            # interest rate is taken from the IRR column; ROI is used only when IRR is blank
            rate = _num(r.get("irr"), "irr", required=False) or \
                _num(r.get("annual_rate"), "annual_rate", required=False)
            if rate <= 0:
                raise RowError("annual rate is missing")
            tenure = int(_num(r.get("tenure_months"), "tenure_months"))
            if tenure <= 0:
                raise RowError("tenure must be positive")
            disb = _date(r.get("disbursal_date"), "disbursal_date")
            fd_raw = r.get("first_due_date") or ""
            if fd_raw.startswith("0000"):
                fd_raw = ""
            first_due = _date(fd_raw, "first_due_date", False) or disb + relativedelta(months=1)
            if first_due <= disb:
                raise RowError("first due date is not after disbursal")
            last_due = _date(r.get("last_due_date"), "last_due_date", False) \
                or first_due + relativedelta(months=tenure - 1)
            if last_due < first_due:
                raise RowError("last repayment date is before the first repayment date")
            calc_emi = emi_amount(principal, rate, tenure)
            emi = _num(r.get("emi_amount"), "emi_amount", required=False, default=calc_emi)
            charges = {k: _num(r.get(k), k, required=False) for k in
                       ("processing_fee", "stamp_duty", "document_charges", "insurance_amount",
                        "rsa_charge", "bounce_charge")}
            raw_row = r.get("__raw__", {})
            raw_status = r.get("status") or "ACTIVE"
            source_tag = (r.get("system_tag") or "M2P").upper()[:10]
            status = STATUS_MAP.get(raw_status.upper().replace(" ", "_"))
            if not status:
                raise RowError(f"unknown status '{raw_status}'")
        except RowError as e:
            err(n, f"{lid or '?'}: {e}")
            continue

        # customer: by ClientId; an existing one is updated, a new one is inserted in bulk below
        ref = r.get("customer_id") or None
        details = {"name": r.get("customer_name") or None, "mobile": r.get("mobile") or None,
                   "email": r.get("email") or None, "pan": r.get("pan") or None,
                   "address": r.get("address") or None}
        existing = customers_by_ref.get(ref) if ref else None
        if existing is not None:
            if not dry_run:
                for k, v in details.items():
                    if v:
                        setattr(existing, k, v)
            customer_id, customer_ref = (existing.id if not dry_run else None), None
        elif ref:
            if ref not in new_customers:
                new_customers[ref] = {**details, "external_ref": ref, "name": details["name"] or "Unknown"}
                report["customers_new"] += 1
            customer_id, customer_ref = None, ref
        else:
            # a row with no ClientId: its own customer (rare, so inserted one at a time)
            c = Customer(external_ref=None, **{**details, "name": details["name"] or "Unknown"})
            report["customers_new"] += 1
            if not dry_run:
                db.add(c)
                db.flush()
                customer_id, customer_ref = c.id, None
            else:
                customer_id, customer_ref = None, None

        code = r.get("product_code") or "M2P-DEFAULT"
        prod = products.get(code)
        if not prod:
            prod = LoanProduct(code=code, name=f"{code} (imported loan master)",
                               interest_method="REDUCING", default_rate=rate, max_tenure=600,
                               apportion_mode="HEAD_WISE", excess_mode="HOLD",
                               late_fee=DEFAULT_LATE_FEE, grace_days=DEFAULT_GRACE_DAYS)
            if not dry_run:
                db.add(prod)
                db.flush()  # the product needs its id before its loans are written
            products[code] = prod
            new_products.append(prod)

        loan_rows.append({
            "loan_number": lid, "external_loan_id": lid, "source": source_tag,
            "customer_id": customer_id, "_customer_ref": customer_ref,
            "product_id": prod.id if not dry_run else None, "principal": r2(principal), "annual_rate": rate,
            "tenure_months": tenure, "interest_method": "REDUCING", "disbursal_date": disb,
            "first_due_date": first_due, "emi_amount": r2(emi),
            "apportion_mode": prod.apportion_mode, "excess_mode": prod.excess_mode,
            "status": status, "created_by": user, "details": json.dumps(raw_row),
            "loan_amount": r2(loan_amount), "last_due_date": last_due,
            **{k: r2(v) for k, v in charges.items()},
        })
        report["loans_imported"] += 1
        if progress and n % 200 == 0:
            progress(n - 1, len(rows))

    lms_log.info("loan master: %d customers to add, %d loans to add", len(new_customers), len(loan_rows))
    if dry_run:
        # a check writes nothing: the counts above come from validation in memory
        lms_log.info("loan master: check finished, %d loans, %d errors (nothing written)",
                     report["loans_imported"], len(report["errors"]))
        report["check_only"] = True
        report["customers_to_add"] = len(new_customers)
        report["loans_to_add"] = len(loan_rows)
        return _finish_single(db, report, dry_run, user, "LOAN_MASTER_IMPORT")
    try:
        # 1. new customers, in bulk; then their ids, in one query per batch
        ref_ids = {}
        customer_list = list(new_customers.values())
        for chunk in _chunks(customer_list):
            db.execute(insert(Customer).values(chunk))
        refs = list(new_customers)
        for chunk in _chunks(refs):
            for ref_, cid in db.query(Customer.external_ref, Customer.id).filter(Customer.external_ref.in_(chunk)):
                ref_ids[ref_] = cid
        lms_log.info("loan master: customers written")
        # 2. loans, in bulk
        for lr in loan_rows:
            if lr["_customer_ref"] is not None:
                lr["customer_id"] = ref_ids[lr["_customer_ref"]]
            del lr["_customer_ref"]
        for i, chunk in enumerate(_chunks(loan_rows), start=1):
            db.execute(insert(Loan).values(chunk))
            lms_log.info("loan master: %d of %d loans written", min(i * 500, len(loan_rows)), len(loan_rows))
        db.flush()
    except Exception as e:  # nothing from this upload is kept if the database refuses any part
        db.rollback()
        report["loans_imported"] = 0
        report["customers_new"] = 0
        err(0, f"the upload could not be saved, nothing was imported: {e.__class__.__name__}: {str(e)[:200]}")
        return report

    lms_log.info("loan master: finished, %d loans, %d errors", report["loans_imported"], len(report["errors"]))
    return _finish_single(db, report, dry_run, user, "LOAN_MASTER_IMPORT")


RPS_ALIASES = {
    "installment_no": ["installment_no", "installment_number", "instalment_no", "emi_no", "installment",
                       "period", "sr_no", "seq"],
    "due_date": ["due_date", "emi_due_date", "installment_date", "schedule_date", "date"],
    "paid_date": ["emi_paid_date", "paid_date", "payment_date"],
    "emi_amount": ["emi_amount", "emi", "installment_amount", "instalment_amount", "total_due"],
    "closing_balance": ["closing_balance_after_due", "closing_balance", "outstanding_after_due"],
    "penalty_due": ["penalty_due", "penalties_due", "late_fee_due"],
    "penalty_paid": ["penalty_paid", "penalties_paid", "late_fee_paid"],
    "penalty_waived": ["penalties_waived", "penalties_waied", "penalty_waived", "penalties_waiver"],
}


def import_rps(db: Session, rps_csv, dry_run: bool = True, user: str | None = None, progress=None) -> dict:
    """RPS rows stored as uploaded, against loans already in the loan master. Nothing is
    generated or recalculated. Re-uploading a loan replaces its earlier RPS rows.
    Reads the M2P layout (account_no, installment, Date, EMI paid Date, closing balance, principal
    and interest due and paid, penalty due, paid and waived, EMI). A blank paid date or paid
    amount means not paid as of the export. Checks that only warn: months against the loan's
    tenure, each EMI against the loan master, and principal due plus interest due against EMI."""
    report = _single_report(dry_run)
    report["rps_read"] = 0
    report["rps_imported"] = 0

    def err(row, msg):
        report["errors"].append({"file": "rps.csv", "row": row, "message": msg})

    def warn(loan_id, msg):
        report["warnings"].append({"loan_id": loan_id, "message": msg})

    text = _decode(rps_csv)
    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(text))
    if not reader.fieldnames:
        err(1, "The file is empty")
        return _finish_rps(db, report, dry_run, user)
    keys = {_norm(h): h for h in reader.fieldnames}

    def col(names):
        return next((keys[a] for a in names if a in keys), None)

    cols = {
        "loan": col(ALIASES["loan_id"]),
        "inst": col(RPS_ALIASES["installment_no"]),
        "due": col(RPS_ALIASES["due_date"]),
        "paid_date": col(RPS_ALIASES["paid_date"]),
        "emi": col(RPS_ALIASES["emi_amount"]),
        "closing": col(RPS_ALIASES["closing_balance"]),
        "prin_due": col(ALIASES["principal_due"]),
        "prin_paid": col(ALIASES["principal_paid"]),
        "int_due": col(ALIASES["interest_due"]),
        "int_paid": col(ALIASES["interest_paid"]),
        "pen_due": col(RPS_ALIASES["penalty_due"]),
        "pen_paid": col(RPS_ALIASES["penalty_paid"]),
        "pen_waived": col(RPS_ALIASES["penalty_waived"]),
    }
    if not cols["loan"]:
        err(1, "No loan account number column found")
        return _finish_rps(db, report, dry_run, user)

    by_loan: dict[str, list] = {}
    for n, raw in enumerate(reader, start=2):
        if not any((v or "").strip() for v in raw.values()):
            continue
        report["rps_read"] += 1
        lid = (raw.get(cols["loan"]) or "").strip()
        val = lambda key: (raw.get(cols[key]) or "").strip() if cols[key] else ""
        try:
            if not lid:
                raise RowError("loan account number is missing")
            inst_no = int(_num(val("inst"), "installment_no", required=False,
                               default=Decimal(len(by_loan.get(lid, [])) + 1)))
            row = {
                "n": n, "inst": inst_no,
                "due": _date(val("due"), "due_date", False),
                "paid_date": _date(val("paid_date"), "EMI paid date", False),
                "emi": _num(val("emi"), "emi_amount", required=False, default=None) if cols["emi"] else None,
            }
            for key in ("closing", "prin_due", "prin_paid", "int_due", "int_paid",
                        "pen_due", "pen_paid", "pen_waived"):
                row[key] = _num(val(key), key, required=False, default=None) if cols[key] else None
        except RowError as e:
            err(n, f"{lid or '?'}: {e}")
            continue
        row["payload"] = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        by_loan.setdefault(lid, []).append(row)

    loans = {ln.loan_number: ln for ln in db.query(Loan).filter(Loan.loan_number.in_(list(by_loan)))} if by_loan else {}
    # clear the earlier RPS of every loan in the file, in batches
    replace = [lid for lid in by_loan if lid in loans]
    lms_log.info("rps: %d loans, %d rows in the file", len(by_loan), sum(len(v) for v in by_loan.values()))
    if progress:
        progress(0, sum(len(v) for v in by_loan.values()), "clearing earlier RPS of these loans")
    if not dry_run:  # a check writes nothing
        for i in range(0, len(replace), 500):
            db.query(RpsRow).filter(RpsRow.loan_number.in_(replace[i:i + 500])).delete(synchronize_session=False)
    rps_rows_out: list[dict] = []  # written in bulk below, not one save per row
    total_items = sum(len(v) for v in by_loan.values())
    written = 0
    if progress:
        progress(0, total_items)
    for lid, items in by_loan.items():
        written += len(items)
        if progress:
            progress(written, total_items)
        loan = loans.get(lid)
        if not loan:
            for row in items:
                err(row["n"], f"{lid}: no loan with this account number in the loan master")
            continue
        for row in items:
            amt = lambda k: r2(row[k]) if row[k] is not None else None
            if not dry_run:
                rps_rows_out.append(dict(loan_number=lid, row_no=row["n"], installment_no=row["inst"],
                              due_date=row["due"], emi_amount=amt("emi"),
                              principal_component=amt("prin_due"), interest_component=amt("int_due"),
                              paid_date=row["paid_date"], closing_balance=amt("closing"),
                              principal_paid=amt("prin_paid"), interest_paid=amt("int_paid"),
                              base_principal_paid=amt("prin_paid"), base_interest_paid=amt("int_paid"),
                              base_paid_date=row["paid_date"],
                              penalty_due=amt("pen_due"), penalty_paid=amt("pen_paid"),
                              penalty_waived=amt("pen_waived"), source="UPLOADED",
                              payload=json.dumps(row["payload"]), created_by=user))
            report["rps_imported"] += 1
        if len(items) != loan.tenure_months:
            warn(lid, f"RPS has {len(items)} months; the loan's tenure is {loan.tenure_months} months")
        off = [row["inst"] for row in items if row["emi"] is not None and abs(row["emi"] - loan.emi_amount) > 1]
        if off:
            warn(lid, f"EMI differs from the loan master ({loan.emi_amount}) in {len(off)} month(s)")
        split = [row["n"] for row in items
                 if row["emi"] is not None and row["prin_due"] is not None and row["int_due"] is not None
                 and abs(row["emi"] - row["prin_due"] - row["int_due"]) > 1]
        if split:
            warn(lid, f"principal due + interest due differs from EMI in {len(split)} row(s) (file row {split[0]})")

    if progress:
        progress(len(rps_rows_out), len(rps_rows_out), "writing RPS rows")
    for i, chunk in enumerate(_chunks(rps_rows_out, 1000), start=1):
        db.execute(insert(RpsRow).values(chunk))  # one multi-row INSERT per batch
        lms_log.info("rps: %d of %d rows written", min(i * 1000, len(rps_rows_out)), len(rps_rows_out))

    return _finish_rps(db, report, dry_run, user)


def _finish_rps(db: Session, report: dict, dry_run: bool, user: str | None) -> dict:
    if dry_run:
        db.rollback()
    else:
        audit(db, user, "RPS_IMPORT", "system", "rps", {"rps_imported": report["rps_imported"]})
        db.commit()
    return report


def import_schedule(db: Session, schedule_csv, cutoff: date = DEFAULT_CUTOFF, dry_run: bool = True,
                    user: str | None = None) -> dict:
    """Repayment schedule for loans already loaded from the loan master. Each loan's instalments
    come in with their dues and the amounts paid as on the cutoff. The loan is then replayed, so
    receipts after the cutoff go through the waterfall. Loans that already have a schedule are skipped."""
    report = {"dry_run": dry_run, "cutoff": cutoff.isoformat(), "loans_read": 0,
              "loans_imported": 0, "installments": 0, "receipts_history": 0,
              "receipts_post_cutoff": 0, "charges": 0, "errors": [], "warnings": [],
              "reconciliation": []}

    def err(row, msg):
        report["errors"].append({"file": "schedule.csv", "row": row, "message": msg})

    def warn(loan_id, msg):
        report["warnings"].append({"loan_id": loan_id, "message": msg})

    rows = _read(schedule_csv)
    if rows and "loan_id" not in rows[0]:
        err(1, "No loan id column found")
        return report

    by_loan: dict = {}
    for n, r in enumerate(rows, start=2):
        by_loan.setdefault(r.get("loan_id") or "", []).append((n, r))
    report["loans_read"] = len(by_loan)

    for lid, items in by_loan.items():
        first_row = items[0][0]
        if not lid:
            err(first_row, "loan id is missing")
            continue
        loan = db.query(Loan).filter(Loan.external_loan_id == lid).first()
        if not loan:
            err(first_row, f"{lid}: loan not found; import the loan master first")
            continue
        if loan.installments:
            err(first_row, f"{lid}: already has a repayment schedule (skipped)")
            continue

        sp = db.begin_nested()
        try:
            insts = []
            for sn, s_row in items:
                try:
                    pd_ = _num(s_row.get("principal_due"), "principal_due")
                    id_ = _num(s_row.get("interest_due"), "interest_due")
                    pp = _num(s_row.get("principal_paid"), "principal_paid", required=False)
                    ip = _num(s_row.get("interest_paid"), "interest_paid", required=False)
                    if pp > pd_ or ip > id_:
                        raise RowError("paid is more than due")
                    insts.append(dict(no=int(_num(s_row.get("installment_no"), "installment_no")),
                                      due=_date(s_row.get("due_date"), "due_date"),
                                      pd=r2(pd_), id=r2(id_), pp=r2(pp), ip=r2(ip)))
                except RowError as e:
                    raise RowError(f"row {sn}: {e}")
            insts.sort(key=lambda x: x["no"])
            if len({i["no"] for i in insts}) != len(insts):
                raise RowError("duplicate instalment numbers")

            bal = r2(loan.principal)
            for i in insts:
                db.add(Installment(loan_id=loan.id, installment_no=i["no"], due_date=i["due"],
                                   opening_balance=bal, principal_due=i["pd"], interest_due=i["id"],
                                   opening_principal_paid=i["pp"], opening_interest_paid=i["ip"],
                                   principal_paid=i["pp"], interest_paid=i["ip"]))
                bal -= i["pd"]
            db.flush()
            db.refresh(loan)
            replay(db, loan)
            sp.commit()
        except RowError as e:
            sp.rollback()
            err(first_row, f"{lid}: {e}")
            continue

        report["loans_imported"] += 1
        report["installments"] += len(insts)

    if dry_run:
        db.rollback()
    else:
        audit(db, user, "M2P_SCHEDULE_IMPORT", "system", cutoff.isoformat(),
              {"loans_imported": report["loans_imported"], "installments": report["installments"]})
        db.commit()
    return report


def _raw_amount(raw: dict, name: str, default=ZERO):
    """An amount from a raw loan master column; blank, '-' or unreadable gives the default."""
    v = (raw.get(name) or "").replace(",", "").strip()
    if not v or v == "-":
        return default
    try:
        return Decimal(v)
    except InvalidOperation:
        return default


def _single_report(dry_run: bool, cutoff: date | None = None) -> dict:
    return {"dry_run": dry_run, "cutoff": cutoff.isoformat() if cutoff else None, "loans_read": 0,
            "loans_imported": 0, "installments": 0, "receipts_history": 0,
            "receipts_post_cutoff": 0, "charges": 0, "errors": [], "warnings": [],
            "reconciliation": []}


def _finish_single(db: Session, report: dict, dry_run: bool, user: str | None, action: str) -> dict:
    if dry_run:
        db.rollback()
    else:
        audit(db, user, action, "system", report["cutoff"] or "loan_master",
              {k: report[k] for k in ("loans_imported", "installments", "receipts_history",
                                      "receipts_post_cutoff", "charges")})
        db.commit()
    return report


def import_charges(db: Session, charges_csv, cutoff: date = DEFAULT_CUTOFF, dry_run: bool = True,
                   user: str | None = None) -> dict:
    """Charges for loans already loaded from the loan master. Needs the loans, nothing else.
    Each charge comes in with the amount paid and waived as on the cutoff."""
    report = _single_report(dry_run, cutoff)

    def err(row, msg):
        report["errors"].append({"file": "charges.csv", "row": row, "message": msg})

    rows = _read(charges_csv)
    report["loans_read"] = len({r.get("loan_id") for r in rows})
    if rows and "loan_id" not in rows[0]:
        err(1, "No loan id column found")
        return report

    touched = {}
    for n, r in enumerate(rows, start=2):
        lid = r.get("loan_id") or ""
        try:
            if not lid:
                raise RowError("loan id is missing")
            loan = db.query(Loan).filter(Loan.external_loan_id == lid).first()
            if not loan:
                raise RowError("loan not found; import the loan master first")
            ctype = (r.get("charge_type") or "OTHER").upper().replace(" ", "_")[:24]
            cdate = _date(r.get("charge_date"), "charge_date")
            amt = r2(_num(r.get("amount"), "amount"))
            paid = r2(_num(r.get("paid"), "paid", required=False))
            waived = r2(_num(r.get("waived"), "waived", required=False))
            if paid + waived > amt:
                raise RowError("paid + waived is more than the charge")
            dup = db.query(Charge).filter(Charge.loan_id == loan.id, Charge.charge_type == ctype,
                                          Charge.charge_date == cdate, Charge.amount == amt).first()
            if dup:
                raise RowError("already imported (skipped)")
        except RowError as e:
            err(n, f"{lid or '?'}: {e}")
            continue
        db.add(Charge(loan_id=loan.id, charge_type=ctype, charge_date=cdate, amount=amt,
                      opening_paid=paid, paid=paid, waived=waived, description="Imported from M2P"))
        touched[loan.id] = loan
        report["charges"] += 1

    for loan in touched.values():
        db.flush()
        db.refresh(loan)
        replay(db, loan)
    return _finish_single(db, report, dry_run, user, "M2P_CHARGES_IMPORT")


def import_receipts(db: Session, receipts_csv, cutoff: date = DEFAULT_CUTOFF, dry_run: bool = True,
                    user: str | None = None) -> dict:
    """Receipts for loans already loaded. Needs the loans AND their repayment schedules, because
    replaying a loan needs its instalments. Receipts on or before the cutoff are kept as history;
    later ones go through the waterfall. Each loan is reconciled against M2P's appropriation."""
    report = _single_report(dry_run, cutoff)

    def err(row, msg):
        report["errors"].append({"file": "receipts.csv", "row": row, "message": msg})

    def warn(loan_id, msg):
        report["warnings"].append({"loan_id": loan_id, "message": msg})

    rows = _read(receipts_csv)
    report["loans_read"] = len({r.get("loan_id") for r in rows})
    if rows and "loan_id" not in rows[0]:
        err(1, "No loan id column found")
        return report

    touched = {}
    for n, r in enumerate(rows, start=2):
        lid = r.get("loan_id") or ""
        try:
            if not lid:
                raise RowError("loan id is missing")
            loan = db.query(Loan).filter(Loan.external_loan_id == lid).first()
            if not loan:
                raise RowError("loan not found; import the loan master first")
            if not loan.installments:
                raise RowError("repayment schedule not imported yet; import the schedule first")
            rdate = _date(r.get("txn_date"), "txn_date")
            amt = r2(_num(r.get("amount"), "amount"))
            if amt <= 0:
                raise RowError("amount must be positive")
            mode = (r.get("mode") or "M2P")[:16]
            ref = r.get("reference") or None
            dup = db.query(Repayment).filter(Repayment.loan_id == loan.id,
                                             Repayment.payment_date == rdate,
                                             Repayment.amount == amt,
                                             Repayment.reference == ref).first()
            if dup:
                raise RowError("already imported (skipped)")
        except RowError as e:
            err(n, f"{lid or '?'}: {e}")
            continue
        historical = rdate <= cutoff
        db.add(Repayment(loan_id=loan.id, amount=amt, payment_date=rdate, mode=mode, reference=ref,
                         is_historical=historical, created_by=user))
        touched[loan.id] = loan
        if historical:
            report["receipts_history"] += 1
        else:
            report["receipts_post_cutoff"] += 1

    for loan in touched.values():
        db.flush()
        db.refresh(loan)
        hist_total = sum((x.amount for x in loan.repayments if x.is_historical and x.status == "POSTED"),
                         ZERO)
        appropriated = sum((i.opening_principal_paid + i.opening_interest_paid for i in loan.installments),
                           ZERO) + sum((c.opening_paid for c in loan.charges), ZERO) + loan.opening_excess
        if hist_total:
            diff = hist_total - appropriated
            report["reconciliation"].append({"loan_id": loan.external_loan_id,
                                             "receipts_till_cutoff": str(hist_total),
                                             "appropriated_in_m2p": str(appropriated),
                                             "difference": str(diff)})
        replay(db, loan)
    return _finish_single(db, report, dry_run, user, "M2P_RECEIPTS_IMPORT")
