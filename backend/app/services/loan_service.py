"""Loan lifecycle: booking, payment posting, reversal, charges, foreclosure, EOD.

Design rule: instalment and charge "paid" columns are never edited by hand.
They are rebuilt by `replay()`, which starts from the opening (migrated) amounts
and re-applies every live payment in date order through the apportionment engine.
That makes back-dated payments and reversals exact: change the inputs, replay.
"""
from __future__ import annotations

import json
import uuid
from collections import deque
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from ..engine.apportion import InstDue, ChargeDue, apportion, dpd, dpd_bucket, HOLD
from ..engine.schedule import generate_schedule, r2
from ..models import (Loan, Installment, Charge, Repayment, Allocation, LoanProduct,
                      Customer, AuditLog)

ZERO = Decimal("0.00")


class LmsError(ValueError):
    pass


def audit(db: Session, user: str | None, action: str, entity: str, entity_id, detail=None):
    db.add(AuditLog(username=user, action=action, entity=entity, entity_id=str(entity_id),
                    detail=json.dumps(detail, default=str) if detail is not None else None))


def live_installments(loan: Loan) -> list[Installment]:
    return [i for i in loan.installments if i.status != "CANCELLED"]


# --------------------------------------------------------------------------- booking

def book_loan(db: Session, *, customer_id: int, product_id: int, principal, annual_rate=None,
              tenure_months: int, disbursal_date: date, first_due_date: date | None = None,
              user: str | None = None) -> Loan:
    product = db.get(LoanProduct, product_id)
    if not product or not product.active:
        raise LmsError("Loan product not found or inactive")
    customer = db.get(Customer, customer_id)
    if not customer:
        raise LmsError("Customer not found")
    principal = r2(principal)
    rate = Decimal(str(annual_rate)) if annual_rate is not None else product.default_rate
    if not (product.min_amount <= principal <= product.max_amount):
        raise LmsError(f"Amount must be between {product.min_amount} and {product.max_amount}")
    if not (product.min_tenure <= tenure_months <= product.max_tenure):
        raise LmsError(f"Tenure must be between {product.min_tenure} and {product.max_tenure} months")

    rows = generate_schedule(principal, rate, tenure_months, disbursal_date, first_due_date,
                             product.interest_method)
    loan = Loan(
        loan_number="TMP-" + uuid.uuid4().hex[:12], source="NATIVE", customer_id=customer.id,
        product_id=product.id, principal=principal, annual_rate=rate, tenure_months=tenure_months,
        interest_method=product.interest_method, disbursal_date=disbursal_date,
        # EMI from instalment 2 so a broken-period first instalment doesn't skew it
        first_due_date=rows[0].due_date, emi_amount=rows[1].emi if len(rows) > 1 else rows[0].emi,
        processing_fee=r2(principal * product.processing_fee_pct / 100),
        apportion_mode=product.apportion_mode, excess_mode=product.excess_mode,
        status="ACTIVE", created_by=user,
    )
    db.add(loan)
    db.flush()
    loan.loan_number = f"LN{disbursal_date:%y%m}{loan.id:06d}"
    for r in rows:
        db.add(Installment(loan_id=loan.id, installment_no=r.installment_no, due_date=r.due_date,
                           opening_balance=r.opening_balance, principal_due=r.principal,
                           interest_due=r.interest))
    db.flush()
    db.refresh(loan)
    audit(db, user, "BOOK_LOAN", "loan", loan.loan_number,
          {"principal": principal, "rate": rate, "tenure": tenure_months})
    return loan


# --------------------------------------------------------------------------- replay

def replay(db: Session, loan: Loan, as_of: date | None = None) -> None:
    as_of = as_of or date.today()
    insts = live_installments(loan)
    charges = list(loan.charges)

    for i in insts:
        i.principal_paid = i.opening_principal_paid
        i.interest_paid = i.opening_interest_paid
    for c in charges:
        c.paid = c.opening_paid
    db.query(Allocation).filter(Allocation.loan_id == loan.id).delete(synchronize_session=False)
    for r in loan.repayments:
        db.expire(r, ["allocations"])
    db.flush()

    idues = {i.id: InstDue(i.id, i.installment_no, i.due_date, i.interest_os, i.principal_os)
             for i in insts}
    cdues = {c.id: ChargeDue(c.id, c.charge_date, c.outstanding, c.charge_type) for c in charges}

    payments = sorted([r for r in loan.repayments if r.status == "POSTED" and not r.is_historical],
                      key=lambda r: (r.payment_date, r.id or 0))
    start = loan.migration_cutoff or loan.disbursal_date
    last_event = max([as_of] + [p.payment_date for p in payments])
    event_dates = sorted({d for d in [i.due_date for i in insts] + [c.charge_date for c in charges]
                          if start < d <= last_event})
    timeline = [(d, 0, None) for d in event_dates] + [(p.payment_date, 1, p) for p in payments]
    timeline.sort(key=lambda t: (t[0], t[1], (t[2].id or 0) if t[2] else 0))

    pool: deque = deque()
    if loan.opening_excess and loan.opening_excess > 0:
        pool.append([None, Decimal(loan.opening_excess)])
    new_allocs: list[Allocation] = []

    def apply(amount, d, rep_id, from_excess):
        res = apportion(amount, d, list(idues.values()), list(cdues.values()),
                        loan.apportion_mode, HOLD if from_excess else loan.excess_mode)
        for a in res.allocations:
            new_allocs.append(Allocation(
                loan_id=loan.id, repayment_id=rep_id,
                installment_id=a.target_id if a.target == "INSTALLMENT" else None,
                charge_id=a.target_id if a.target == "CHARGE" else None,
                component=a.component, amount=a.amount, applied_date=d, from_excess=from_excess))
        return res.excess

    last_payment_date = None
    for d, kind, p in timeline:
        if kind == 0:
            if not pool:
                continue
            nxt: deque = deque()
            while pool:
                rid, amt = pool.popleft()
                left = apply(amt, d, rid, True)
                if left > 0:
                    nxt.append([rid, left])
            pool = nxt
        else:
            last_payment_date = d
            left = apply(p.amount, d, p.id, False)
            if left > 0:
                pool.append([p.id, left])

    db.add_all(new_allocs)
    for i in insts:
        dd = idues[i.id]
        i.interest_paid = i.interest_due - dd.interest_os
        i.principal_paid = i.principal_due - dd.principal_os
        i.status = "PAID" if dd.interest_os == 0 and dd.principal_os == 0 else "DUE"
    for c in charges:
        c.paid = c.amount - c.waived - cdues[c.id].outstanding
    loan.excess_amount = sum((amt for _, amt in pool), ZERO)

    # a loan with no instalments (loan master import) has nothing to clear, so it stays open
    all_clear = bool(insts) and all(i.status == "PAID" for i in insts) \
        and all(c.outstanding == 0 for c in charges)
    if loan.status == "ACTIVE" and all_clear:
        loan.status = "CLOSED"
        loan.closed_date = last_payment_date or as_of
    elif loan.status == "CLOSED" and not all_clear:
        loan.status = "ACTIVE"
        loan.closed_date = None
    db.flush()


# --------------------------------------------------------------------------- payments

def _check_open(loan: Loan):
    if loan.status in ("FORECLOSED", "WRITTEN_OFF"):
        raise LmsError(f"Loan is {loan.status}; payments are not allowed")


def preview_payment(loan: Loan, amount, payment_date: date) -> dict:
    """What the waterfall would do with this payment, without saving anything."""
    amount = r2(amount)
    if amount <= 0:
        raise LmsError("Amount must be positive")
    idues = [InstDue(i.id, i.installment_no, i.due_date, i.interest_os, i.principal_os)
             for i in live_installments(loan)]
    cdues = [ChargeDue(c.id, c.charge_date, c.outstanding, c.charge_type) for c in loan.charges]
    res = apportion(amount, payment_date, idues, cdues,
                    loan.apportion_mode, loan.excess_mode)
    no = {i.id: i.installment_no for i in loan.installments}
    ctype = {c.id: c.charge_type for c in loan.charges}
    lines = [{"component": a.component,
              "target": f"EMI {no[a.target_id]}" if a.target == "INSTALLMENT"
              else f"{ctype[a.target_id]} #{a.target_id}",
              "amount": str(a.amount)} for a in res.allocations]
    t = res.total_by_component()
    return {"amount": str(amount), "excess_already_held": str(loan.excess_amount),
            "interest": str(t["INTEREST"]), "principal": str(t["PRINCIPAL"]),
            "charges": str(t["CHARGE"]), "excess": str(res.excess), "lines": lines,
            "mode": loan.apportion_mode, "excess_mode": loan.excess_mode}


def post_repayment(db: Session, loan: Loan, amount, payment_date: date, mode: str = "NEFT",
                   reference: str | None = None, user: str | None = None,
                   purpose: str = "REPAYMENT") -> Repayment:
    _check_open(loan)
    amount = r2(amount)
    if amount <= 0:
        raise LmsError("Amount must be positive")
    if loan.migration_cutoff and payment_date <= loan.migration_cutoff:
        raise LmsError(f"Payments on or before the migration cutoff ({loan.migration_cutoff}) "
                       "belong in the M2P history")
    if payment_date < loan.disbursal_date:
        raise LmsError("Payment date is before disbursal")
    if payment_date > date.today():
        raise LmsError("Payment date cannot be in the future")
    if reference:
        dup = db.query(Repayment).filter(Repayment.loan_id == loan.id,
                                         Repayment.reference == reference,
                                         Repayment.status == "POSTED").first()
        if dup:
            raise LmsError(f"Reference {reference} already posted on this loan")
    rep = Repayment(loan_id=loan.id, amount=amount, payment_date=payment_date, mode=mode,
                    reference=reference, created_by=user, purpose=purpose)
    db.add(rep)
    db.flush()
    db.refresh(loan)
    replay(db, loan)
    audit(db, user, "POST_PAYMENT", "loan", loan.loan_number,
          {"repayment_id": rep.id, "amount": amount, "date": payment_date})
    return rep


def reverse_repayment(db: Session, rep: Repayment, reason: str, bounce: bool = False,
                      user: str | None = None) -> Repayment:
    if rep.status != "POSTED":
        raise LmsError("Payment is already reversed")
    if rep.is_historical:
        raise LmsError("Migrated M2P receipts cannot be reversed here")
    if rep.purpose == "FORECLOSURE":
        raise LmsError("Foreclosure payments can't be reversed from the screen; "
                       "raise it with an admin")
    loan = rep.loan
    rep.status = "REVERSED"
    rep.reversal_reason = reason
    rep.reversed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if bounce and loan.product and loan.product.bounce_charge > 0:
        db.add(Charge(loan_id=loan.id, charge_type="BOUNCE", charge_date=rep.payment_date,
                      amount=loan.product.bounce_charge,
                      description=f"Bounce of payment {rep.reference or rep.id}"))
    db.flush()
    db.refresh(loan)
    replay(db, loan)
    audit(db, user, "REVERSE_PAYMENT", "loan", loan.loan_number,
          {"repayment_id": rep.id, "reason": reason, "bounce": bounce})
    return rep


# --------------------------------------------------------------------------- charges

def add_charge(db: Session, loan: Loan, charge_type: str, amount, charge_date: date,
               description: str | None = None, user: str | None = None) -> Charge:
    _check_open(loan)
    amount = r2(amount)
    if amount <= 0:
        raise LmsError("Charge amount must be positive")
    c = Charge(loan_id=loan.id, charge_type=charge_type.upper(), charge_date=charge_date,
               amount=amount, description=description)
    db.add(c)
    db.flush()
    db.refresh(loan)
    replay(db, loan)
    audit(db, user, "ADD_CHARGE", "loan", loan.loan_number, {"type": charge_type, "amount": amount})
    return c


def waive_charge(db: Session, charge: Charge, amount, reason: str, user: str | None = None):
    amount = r2(amount)
    if amount <= 0 or amount > charge.amount - charge.waived:
        raise LmsError("Waiver must be positive and not more than the unwaived charge")
    charge.waived += amount
    loan = charge.loan
    db.flush()
    replay(db, loan)
    audit(db, user, "WAIVE_CHARGE", "loan", loan.loan_number,
          {"charge_id": charge.id, "amount": amount, "reason": reason})
    return charge


def run_late_fees(db: Session, as_of: date | None = None, user: str | None = None) -> dict:
    """EOD: levy the product's late fee once per instalment overdue beyond grace days."""
    as_of = as_of or date.today()
    created = 0
    loans = db.query(Loan).filter(Loan.status == "ACTIVE").all()
    for loan in loans:
        p = loan.product
        if not p or p.late_fee <= 0:
            continue
        levied = {c.installment_id for c in loan.charges if c.charge_type == "LATE_FEE"}
        start = loan.migration_cutoff or loan.disbursal_date
        changed = False
        for i in live_installments(loan):
            if i.id in levied or i.due_date <= start:
                continue
            if (as_of - i.due_date).days > p.grace_days and (i.interest_os > 0 or i.principal_os > 0):
                db.add(Charge(loan_id=loan.id, installment_id=i.id, charge_type="LATE_FEE",
                              charge_date=as_of, amount=p.late_fee,
                              description=f"Late payment charge, EMI {i.installment_no}"))
                created += 1
                changed = True
        if changed:
            db.flush()
            db.refresh(loan)
            replay(db, loan, as_of)
    audit(db, user, "EOD_LATE_FEES", "system", as_of.isoformat(), {"created": created})
    return {"as_of": as_of.isoformat(), "late_fees_created": created}


# --------------------------------------------------------------------------- foreclosure

def foreclosure_quote(loan: Loan, fc_date: date) -> dict:
    insts = live_installments(loan)
    due = [i for i in insts if i.due_date <= fc_date]
    future = [i for i in insts if i.due_date > fc_date]
    overdue_int = sum((i.interest_os for i in due), ZERO)
    overdue_prin = sum((i.principal_os for i in due), ZERO)
    future_prin = sum((i.principal_os for i in future), ZERO)
    advance_int = sum((i.interest_paid - i.opening_interest_paid for i in future), ZERO)
    last_due = max([i.due_date for i in due], default=loan.disbursal_date)
    days = max((fc_date - last_due).days, 0)
    accrued = r2(future_prin * loan.annual_rate / 100 * days / 365)
    charges_os = sum((c.outstanding for c in loan.charges if c.charge_date <= fc_date), ZERO)
    pct = loan.product.foreclosure_fee_pct if loan.product else ZERO
    fee = r2(future_prin * pct / 100)
    credit = loan.excess_amount + advance_int
    total = overdue_int + overdue_prin + future_prin + accrued + charges_os + fee - credit
    return {k: str(v) for k, v in {
        "foreclosure_date": fc_date, "overdue_interest": overdue_int,
        "overdue_principal": overdue_prin, "principal_outstanding": future_prin,
        "accrued_interest": accrued, "accrued_days": days, "charges_outstanding": charges_os,
        "foreclosure_fee": fee, "foreclosure_fee_pct": pct, "less_excess_and_advance": credit,
        "total_payable": max(total, ZERO)}.items()}


def foreclose(db: Session, loan: Loan, fc_date: date, amount, mode="NEFT", reference=None,
              user: str | None = None) -> dict:
    if loan.status != "ACTIVE":
        raise LmsError(f"Only active loans can be foreclosed (loan is {loan.status})")
    if fc_date > date.today():
        raise LmsError("Foreclosure date cannot be in the future")
    if loan.migration_cutoff and fc_date <= loan.migration_cutoff:
        raise LmsError("Foreclosure date must be after the migration cutoff")
    q = foreclosure_quote(loan, fc_date)
    amount = r2(amount)
    if amount < Decimal(q["total_payable"]):
        raise LmsError(f"Amount {amount} is less than the foreclosure amount {q['total_payable']}")

    future = sorted([i for i in live_installments(loan) if i.due_date > fc_date],
                    key=lambda i: i.installment_no)
    if future:
        head = future[0]
        head.principal_due = sum((i.principal_due for i in future), ZERO)
        head.opening_principal_paid = sum((i.opening_principal_paid for i in future), ZERO)
        head.interest_due = Decimal(q["accrued_interest"]) + \
            sum((i.opening_interest_paid for i in future), ZERO)
        head.opening_interest_paid = sum((i.opening_interest_paid for i in future), ZERO)
        head.due_date = fc_date
        for i in future[1:]:
            i.status = "CANCELLED"
    fee = Decimal(q["foreclosure_fee"])
    if fee > 0:
        db.add(Charge(loan_id=loan.id, charge_type="FORECLOSURE", charge_date=fc_date, amount=fee,
                      description="Foreclosure charge"))
    rep = Repayment(loan_id=loan.id, amount=amount, payment_date=fc_date, mode=mode,
                    reference=reference, created_by=user, purpose="FORECLOSURE")
    db.add(rep)
    db.flush()
    db.refresh(loan)
    replay(db, loan)
    loan.status = "FORECLOSED"
    loan.closed_date = fc_date
    db.flush()
    audit(db, user, "FORECLOSE", "loan", loan.loan_number, {"quote": q, "amount": amount})
    return {"quote": q, "repayment_id": rep.id, "refund_due": str(loan.excess_amount)}


# --------------------------------------------------------------------------- summary

def loan_summary(loan: Loan, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    insts = live_installments(loan)
    idues = [InstDue(i.id, i.installment_no, i.due_date, i.interest_os, i.principal_os)
             for i in insts]
    due = [i for i in insts if i.due_date <= as_of]
    nxt = next((i for i in sorted(insts, key=lambda i: i.due_date)
                if i.due_date > as_of and i.status != "PAID"), None)
    days = dpd(idues, as_of) if loan.status == "ACTIVE" else 0
    posted = [r for r in loan.repayments if r.status == "POSTED"]
    return {
        "principal_outstanding": str(sum((i.principal_os for i in insts), ZERO)),
        "overdue_interest": str(sum((i.interest_os for i in due), ZERO)),
        "overdue_principal": str(sum((i.principal_os for i in due), ZERO)),
        "charges_outstanding": str(sum((c.outstanding for c in loan.charges), ZERO)),
        "excess_amount": str(loan.excess_amount),
        "total_overdue": str(sum((i.interest_os + i.principal_os for i in due), ZERO)
                             + sum((c.outstanding for c in loan.charges
                                    if c.charge_date <= as_of), ZERO)),
        "interest_collected": str(sum((i.interest_paid for i in insts), ZERO)),
        "principal_collected": str(sum((i.principal_paid for i in insts), ZERO)),
        "total_received": str(sum((r.amount for r in posted), ZERO)),
        "paid_installments": sum(1 for i in insts if i.status == "PAID"),
        "total_installments": len(insts),
        "next_due_date": nxt.due_date.isoformat() if nxt else None,
        "next_due_amount": str(nxt.interest_os + nxt.principal_os) if nxt else None,
        "dpd": days,
        "dpd_bucket": dpd_bucket(days) if loan.status == "ACTIVE" else loan.status.title(),
    }
