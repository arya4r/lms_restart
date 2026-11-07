"""Repayment schedule generation.

All money is Decimal, rounded to 2 places with ROUND_HALF_UP.
Supports monthly reducing-balance EMI and flat-rate schedules, with
broken-period interest (BPI) on the first instalment when the first due
date is not exactly one month after disbursal.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta

TWO = Decimal("0.01")
ZERO = Decimal("0")


def r2(x) -> Decimal:
    return Decimal(x).quantize(TWO, rounding=ROUND_HALF_UP)


@dataclass
class ScheduleRow:
    installment_no: int
    due_date: date
    opening_balance: Decimal
    principal: Decimal
    interest: Decimal
    emi: Decimal
    closing_balance: Decimal

    def as_dict(self):
        d = asdict(self)
        d["due_date"] = self.due_date.isoformat()
        for k in ("opening_balance", "principal", "interest", "emi", "closing_balance"):
            d[k] = str(d[k])
        return d


def emi_amount(principal, annual_rate, tenure: int) -> Decimal:
    principal = Decimal(principal)
    annual_rate = Decimal(annual_rate)
    if tenure <= 0:
        raise ValueError("tenure must be positive")
    if annual_rate == 0:
        return r2(principal / tenure)
    r = annual_rate / Decimal(1200)
    f = (1 + r) ** tenure
    return r2(principal * r * f / (f - 1))


def generate_schedule(
    principal,
    annual_rate,
    tenure: int,
    disbursal_date: date,
    first_due_date: date | None = None,
    method: str = "REDUCING",
    bpi: bool = True,
) -> list[ScheduleRow]:
    """Build a monthly schedule.

    method: REDUCING (EMI on reducing balance) or FLAT (interest on original principal).
    bpi: when the first due date isn't one month after disbursal, charge first-period
         interest on actual days (ACT/365) instead of a standard month.
    """
    principal = r2(principal)
    rate = Decimal(annual_rate)
    if principal <= 0:
        raise ValueError("principal must be positive")
    if rate < 0:
        raise ValueError("rate cannot be negative")
    if first_due_date is None:
        first_due_date = disbursal_date + relativedelta(months=1)
    if first_due_date <= disbursal_date:
        raise ValueError("first due date must be after disbursal date")

    standard_first = disbursal_date + relativedelta(months=1)
    broken_days = (first_due_date - disbursal_date).days
    use_bpi = bpi and first_due_date != standard_first

    rows: list[ScheduleRow] = []
    bal = principal
    method = method.upper()

    if method == "FLAT":
        total_interest = r2(principal * rate / 100 * Decimal(tenure) / 12)
        p_each = r2(principal / tenure)
        i_each = r2(total_interest / tenure)
        for k in range(1, tenure + 1):
            due = first_due_date + relativedelta(months=k - 1)
            p = p_each if k < tenure else bal
            i = i_each if k < tenure else total_interest - i_each * (tenure - 1)
            if k == 1 and use_bpi:
                i = r2(principal * rate / 100 * broken_days / 365)
            closing = bal - p
            rows.append(ScheduleRow(k, due, bal, p, i, p + i, closing))
            bal = closing
        return rows

    if method != "REDUCING":
        raise ValueError(f"unknown interest method {method}")

    emi = emi_amount(principal, rate, tenure)
    r = rate / Decimal(1200)
    for k in range(1, tenure + 1):
        due = first_due_date + relativedelta(months=k - 1)
        std_interest = r2(bal * r)
        p = emi - std_interest if k < tenure else bal
        if p > bal:
            p = bal
        if p < 0:
            p = ZERO
        interest = std_interest
        if k == 1 and use_bpi:
            interest = r2(bal * rate / 100 * broken_days / 365)
        closing = bal - p
        rows.append(ScheduleRow(k, due, bal, p, interest, p + interest, closing))
        bal = closing
    return rows
