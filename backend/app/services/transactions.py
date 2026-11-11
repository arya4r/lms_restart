"""Transactions uploaded against RPS loans. Each one is applied to the RPS rows in date order:
- a late charge is added to an instalment still unpaid after the grace period (product grace
  days, due on the 5th and grace 5 means a payment after the 10th), once per instalment;
- the amount then goes to dues already due on the payment date: interest, then principal,
  then charges, oldest instalment first;
- money left over is held as excess (HOLD), and used on the next transaction.
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import Loan, RpsRow, RpsTransaction
from .loan_service import audit
from ..logs import log as lms_log
from .m2p_import import ALIASES, RowError, _date, _num, _norm

ZERO = Decimal("0")
TXN_ALIASES = {
    "date": ["txn_date", "transaction_date", "payment_date", "receipt_date", "value_date", "date"],
    "amount": ["amount", "txn_amount", "payment_amount", "receipt_amount"],
    "mode": ["mode", "payment_mode", "channel"],
    "reference": ["utr", "reference", "txn_id", "transaction_id", "reference_no"],
}


def _outstanding(r: RpsRow, kind: str) -> Decimal:
    if kind == "interest":
        return (r.interest_component or ZERO) - (r.interest_paid or ZERO)
    if kind == "principal":
        return (r.principal_component or ZERO) - (r.principal_paid or ZERO)
    # "charge": a late charge this app added
    return (r.actual_charge or ZERO) - (r.actual_charge_paid or ZERO)


def _emi_outstanding(r: RpsRow) -> Decimal:
    return _outstanding(r, "interest") + _outstanding(r, "principal")


CHARGES_FROM = date(2026, 4, 5)  # late charges apply to instalments due on or after this date


def levy_late_charges(rows, loan: Loan, as_of, grace: int, fee: Decimal) -> int:
    """A late charge for each instalment due on or after CHARGES_FROM that is still unpaid
    (interest or principal) more than `grace` days after its due date, once per instalment.
    Returns how many were added. 3-wheeler lease (L3) loans carry no late charge."""
    if fee <= 0 or loan.interest_method == "LEASE_3W":
        return 0
    added = 0
    for r in rows:
        if (r.due_date and r.due_date >= CHARGES_FROM and r.actual_charge is None
                and (as_of - r.due_date).days > grace and _emi_outstanding(r) > 0):
            r.actual_charge = fee
            added += 1
    return added


def apply_payment(rows, loan: Loan, txn_date, amount: Decimal, excess: Decimal):
    """Applies one payment to a list of RPS rows (ORM rows or copies). Returns (excess held,
    amount applied to interest, principal and late charges).

    Order: interest, then principal, then late charges (HEAD_WISE: each across all overdue
    instalments; INSTALLMENT_WISE: instalment by instalment). An instalment still unpaid when this
    payment arrives, more than the grace days late, gets a late charge, once. A charge is paid
    only after the overdue EMIs are paid. Old M2P charges are not paid by new repayments.
    """
    prod = loan.product
    fee = prod.late_fee if prod else ZERO
    grace = prod.grace_days if prod else 0
    # an instalment still unpaid when this payment arrives, more than the grace days late, is charged
    levy_late_charges(rows, loan, txn_date, grace, fee)
    pool = amount + excess
    due_rows = [r for r in rows if r.due_date and r.due_date <= txn_date]
    attr = {"interest": "interest_paid", "principal": "principal_paid", "charge": "actual_charge_paid"}
    applied = {"interest": ZERO, "principal": ZERO, "charge": ZERO}

    def pay(r, kind):
        nonlocal pool
        due = _outstanding(r, kind)
        if due <= 0 or pool <= 0:
            return
        amt = min(due, pool)
        setattr(r, attr[kind], (getattr(r, attr[kind]) or ZERO) + amt)
        pool -= amt
        applied[kind] += amt

    # each instalment in turn, oldest first: interest, then principal; charges only after all
    # the overdue EMIs are paid
    for r in due_rows:
        pay(r, "interest")
        pay(r, "principal")
    for r in due_rows:
        pay(r, "charge")
    for r in due_rows:
        if r.paid_date is None and _emi_outstanding(r) <= 0:
            r.paid_date = txn_date
    return pool, applied


def apply_to_rps(db: Session, loan: Loan, txn_date, amount: Decimal):
    """Applies one payment to the loan's RPS rows in the database. Returns (excess held, amount
    applied to interest, principal and late charges)."""
    rows = db.query(RpsRow).filter(RpsRow.loan_number == loan.loan_number) \
        .order_by(RpsRow.due_date, RpsRow.installment_no).all()
    return apply_payment(rows, loan, txn_date, amount, loan.excess_amount or ZERO)


_CHECK_FIELDS = ("installment_no", "due_date", "interest_component", "principal_component", "interest_paid",
                 "principal_paid", "paid_date", "penalty_due", "penalty_paid", "penalty_waived",
                 "actual_charge", "actual_charge_paid")
_COPY_FIELDS = ("installment_no", "due_date", "interest_component", "principal_component",
                "penalty_due", "penalty_paid", "penalty_waived", "emi_amount", "closing_balance", "source")


def state_as_of(db: Session, loan: Loan, as_of: date):
    """The loan's state on a date: the RPS as uploaded, then the payments dated on or before the
    date applied in date order, then late charges that are unpaid past the grace days on that date.
    Works on copies, so nothing is written. Returns (rows, excess held)."""
    from types import SimpleNamespace
    prod = loan.product
    fee = prod.late_fee if prod else ZERO
    grace = prod.grace_days if prod else 0
    rows = db.query(RpsRow).filter(RpsRow.loan_number == loan.loan_number) \
        .order_by(RpsRow.due_date, RpsRow.installment_no).all()
    sim = []
    for r in rows:
        c = SimpleNamespace(**{f: getattr(r, f) for f in _COPY_FIELDS})
        c.interest_paid = r.base_interest_paid
        c.principal_paid = r.base_principal_paid
        c.paid_date = r.base_paid_date
        c.actual_charge = None
        c.actual_charge_paid = None
        sim.append(c)
    txns = db.query(RpsTransaction).filter(RpsTransaction.loan_number == loan.loan_number,
                                           RpsTransaction.txn_date <= as_of) \
        .order_by(RpsTransaction.txn_date, RpsTransaction.id).all()
    excess = ZERO
    for t in txns:
        excess, _ = apply_payment(sim, loan, t.txn_date, t.amount, excess)
    levy_late_charges(sim, loan, as_of, grace, fee)
    return sim, excess


def _chunks(items, size=1000):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# every column of an RPS row, except the id (the database assigns it) and created_at (its default)
_RPS_COLUMNS = [c.name for c in RpsRow.__table__.columns if c.name not in ("id", "created_at")]


def import_transactions(db: Session, csv_bytes, dry_run: bool = True, user: str | None = None,
                        progress=None) -> dict:
    """Payments applied to the RPS in date order. Works on copies in memory: a check writes nothing;
    an import then writes in bulk, once: the RPS rows of the affected loans, the payments, and each
    loan's excess."""
    from types import SimpleNamespace
    from sqlalchemy import case, insert, update

    report = {"dry_run": dry_run, "read": 0, "applied": 0, "duplicates": 0, "errors": [],
              "excess": {}}

    def err(row, msg):
        report["errors"].append({"file": "transactions.csv", "row": row, "message": msg})

    from .m2p_import import _decode, _delimiter
    text = _decode(csv_bytes)
    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(text))
    if not reader.fieldnames:
        err(1, "The file is empty")
        return _finish(db, report, dry_run, user)
    keys = {_norm(h): h for h in reader.fieldnames}

    def col(names):
        return next((keys[a] for a in names if a in keys), None)

    loan_col = col(ALIASES["loan_id"])
    if not loan_col:
        err(1, "No loan account number column found")
        return _finish(db, report, dry_run, user)
    cols = {k: col(v) for k, v in TXN_ALIASES.items()}
    if not cols["date"] or not cols["amount"]:
        err(1, "Needs a date column and an amount column")
        return _finish(db, report, dry_run, user)

    parsed = []
    for n, raw in enumerate(reader, start=2):
        if not any((v or "").strip() for v in raw.values()):
            continue
        report["read"] += 1
        g = lambda k: (raw.get(cols[k]) or "").strip() if cols[k] else ""
        lid = (raw.get(loan_col) or "").strip()
        try:
            if not lid:
                raise RowError("loan account number is missing")
            txn_date = _date(g("date"), "date")
            amount = _num(g("amount"), "amount")
            if amount <= 0:
                raise RowError("amount must be positive")
        except RowError as e:
            err(n, f"{lid or '?'}: {e}")
            continue
        parsed.append((txn_date, n, lid, amount, g("mode") or None, g("reference") or None))

    lms_log.info("transactions: %d payments read", len(parsed))
    if progress:
        progress(0, len(parsed), "reading loans and RPS")
    loans = {l.loan_number: l for l in db.query(Loan).filter(
        Loan.loan_number.in_({p[2] for p in parsed})).all()} if parsed else {}
    # payments already stored, and the RPS rows of these loans: read once
    stored = {(t.loan_number, t.txn_date, t.amount, t.reference) for t in
              db.query(RpsTransaction).filter(RpsTransaction.loan_number.in_(set(loans))).all()} if loans else set()
    rows_by_loan: dict[str, list] = {}
    if loans:
        for r in db.query(RpsRow).filter(RpsRow.loan_number.in_(set(loans))) \
                .order_by(RpsRow.due_date, RpsRow.installment_no).all():
            rows_by_loan.setdefault(r.loan_number, []).append(
                SimpleNamespace(**{c: getattr(r, c) for c in _RPS_COLUMNS}))
    lms_log.info("transactions: %d loans and %d RPS rows read", len(loans), sum(len(v) for v in rows_by_loan.values()))

    excess_now = {lid: (ln.excess_amount or ZERO) for lid, ln in loans.items()}
    seen: set = set()
    pay_rows: list[dict] = []
    ordered = sorted(parsed, key=lambda p: (p[0], p[1]))
    for i, (txn_date, n, lid, amount, mode, ref) in enumerate(ordered, start=1):
        if progress and i % 100 == 0:
            progress(i, len(ordered), "applying payments")
        loan = loans.get(lid)
        if not loan:
            err(n, f"{lid}: no loan with this account number in the loan master")
            continue
        key = (lid, txn_date, amount, ref)
        if key in seen or key in stored:
            report["duplicates"] += 1
            continue
        seen.add(key)
        excess, applied = apply_payment(rows_by_loan.get(lid, []), loan, txn_date, amount,
                                        excess_now.get(lid, ZERO))
        excess_now[lid] = excess
        pay_rows.append(dict(loan_number=lid, txn_date=txn_date, amount=amount, mode=mode, reference=ref,
                             created_by=user, interest_applied=applied["interest"],
                             principal_applied=applied["principal"], charges_applied=applied["charge"],
                             excess_held=excess))
        report["applied"] += 1
        report["excess"][lid] = str(excess)

    if not dry_run and pay_rows:
        if progress:
            progress(len(ordered), len(ordered), "writing payments and RPS")
        touched = sorted({p["loan_number"] for p in pay_rows})
        # late charges as of today, so the stored charges match the quote and the position
        today = date.today()
        for lid in touched:
            ln = loans[lid]
            prod = ln.product
            if prod:
                levy_late_charges(rows_by_loan.get(lid, []), ln, today, prod.grace_days or 0,
                                  prod.late_fee or ZERO)
        # 1. the RPS rows of the loans that had payments, replaced
        for chunk in _chunks(touched, 500):
            db.query(RpsRow).filter(RpsRow.loan_number.in_(chunk)).delete(synchronize_session=False)
        final = [{c: getattr(cp, c) for c in _RPS_COLUMNS} for lid in touched for cp in rows_by_loan.get(lid, [])]
        for chunk in _chunks(final):
            db.execute(insert(RpsRow).values(chunk))
        lms_log.info("transactions: %d RPS rows written for %d loans", len(final), len(touched))
        # 2. the payments
        for chunk in _chunks(pay_rows):
            db.execute(insert(RpsTransaction).values(chunk))
        # 3. the excess of each loan, in one statement per batch
        changed = {lid: excess_now[lid] for lid in touched if excess_now.get(lid) != (loans[lid].excess_amount or ZERO)}
        for chunk in _chunks(list(changed), 500):
            db.execute(update(Loan).where(Loan.loan_number.in_(chunk)).values(
                excess_amount=case({k: changed[k] for k in chunk}, value=Loan.loan_number)))
        lms_log.info("transactions: %d payments written", len(pay_rows))
    return _finish(db, report, dry_run, user)


def _finish(db: Session, report: dict, dry_run: bool, user: str | None) -> dict:
    if dry_run:
        db.rollback()
    else:
        audit(db, user, "TRANSACTIONS_IMPORT", "system", "rps_transactions",
              {"applied": report["applied"], "duplicates": report["duplicates"]})
        db.commit()
    return report
