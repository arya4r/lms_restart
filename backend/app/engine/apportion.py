"""Payment apportionment (the waterfall).

Default policy: Interest -> Principal -> Charges, oldest dues first.

Two modes, chosen per product (and copied onto each loan):
  HEAD_WISE        all overdue interest (oldest first), then all overdue principal,
                   then charges. This is the literal Interest->Principal->Charges order.
  INSTALLMENT_WISE oldest instalment first: its interest, then its principal; then the
                   next instalment; charges after all instalments.

What happens to money left over after every due is cleared (excess_mode):
  HOLD     kept as excess on the loan and auto-adjusted on the next due date
  ADVANCE  applied immediately to future instalments (interest then principal)

The engine is pure: it takes outstanding amounts and returns allocations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")

HEAD_WISE = "HEAD_WISE"
INSTALLMENT_WISE = "INSTALLMENT_WISE"
HOLD = "HOLD"
ADVANCE = "ADVANCE"


@dataclass
class InstDue:
    id: int
    installment_no: int
    due_date: date
    interest_os: Decimal
    principal_os: Decimal


@dataclass
class ChargeDue:
    id: int
    charge_date: date
    outstanding: Decimal
    charge_type: str = "OTHER"


@dataclass
class Allocation:
    target: str          # "INSTALLMENT" or "CHARGE"
    target_id: int
    component: str       # "INTEREST", "PRINCIPAL", "CHARGE"
    amount: Decimal


@dataclass
class ApportionResult:
    allocations: list[Allocation] = field(default_factory=list)
    excess: Decimal = ZERO

    def total_by_component(self) -> dict[str, Decimal]:
        out = {"INTEREST": ZERO, "PRINCIPAL": ZERO, "CHARGE": ZERO}
        for a in self.allocations:
            out[a.component] += a.amount
        return out


def _buckets(installments, charges, as_of, mode):
    due = sorted([i for i in installments if i.due_date <= as_of],
                 key=lambda i: (i.due_date, i.installment_no))
    ch = sorted([c for c in charges if c.charge_date <= as_of],
                key=lambda c: (c.charge_date, c.id))
    out = []
    if mode == HEAD_WISE:
        out += [(i, "INTEREST") for i in due]
        out += [(i, "PRINCIPAL") for i in due]
    elif mode == INSTALLMENT_WISE:
        for i in due:
            out += [(i, "INTEREST"), (i, "PRINCIPAL")]
    else:
        raise ValueError(f"unknown apportion mode {mode}")
    out += [(c, "CHARGE") for c in ch]
    return out


def _take(bucket, comp, remaining, result: ApportionResult) -> Decimal:
    if comp == "CHARGE":
        os_ = bucket.outstanding
    elif comp == "INTEREST":
        os_ = bucket.interest_os
    else:
        os_ = bucket.principal_os
    amt = min(os_, remaining)
    if amt <= 0:
        return remaining
    if comp == "CHARGE":
        bucket.outstanding -= amt
        result.allocations.append(Allocation("CHARGE", bucket.id, "CHARGE", amt))
    elif comp == "INTEREST":
        bucket.interest_os -= amt
        result.allocations.append(Allocation("INSTALLMENT", bucket.id, "INTEREST", amt))
    else:
        bucket.principal_os -= amt
        result.allocations.append(Allocation("INSTALLMENT", bucket.id, "PRINCIPAL", amt))
    return remaining - amt


def apportion(amount, as_of: date, installments: list[InstDue], charges: list[ChargeDue],
              mode: str = HEAD_WISE, excess_mode: str = HOLD) -> ApportionResult:
    """Allocate `amount` received on `as_of`. Mutates the outstanding fields of the
    passed objects so callers can chain several payments."""
    remaining = Decimal(amount)
    if remaining < 0:
        raise ValueError("amount cannot be negative")
    result = ApportionResult()

    for bucket, comp in _buckets(installments, charges, as_of, mode):
        if remaining <= 0:
            break
        remaining = _take(bucket, comp, remaining, result)

    if remaining > 0 and excess_mode == ADVANCE:
        future = sorted([i for i in installments if i.due_date > as_of],
                        key=lambda i: (i.due_date, i.installment_no))
        for i in future:
            for comp in ("INTEREST", "PRINCIPAL"):
                if remaining <= 0:
                    break
                remaining = _take(i, comp, remaining, result)

    result.excess = remaining
    return result


def dpd(installments: list[InstDue], as_of: date) -> int:
    """Days past due of the oldest instalment that still has interest or principal unpaid."""
    overdue = [i for i in installments
               if i.due_date < as_of and (i.interest_os > 0 or i.principal_os > 0)]
    if not overdue:
        return 0
    oldest = min(overdue, key=lambda i: (i.due_date, i.installment_no))
    return (as_of - oldest.due_date).days


def dpd_bucket(days: int) -> str:
    if days <= 0:
        return "Current"
    if days <= 30:
        return "SMA-0 (1-30)"
    if days <= 60:
        return "SMA-1 (31-60)"
    if days <= 90:
        return "SMA-2 (61-90)"
    return "NPA (90+)"
