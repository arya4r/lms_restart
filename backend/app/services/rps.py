"""RPS generated from the EMI shared in the loan master.

Each month: interest = opening principal x IRR / 12 (rounded to paise); principal = EMI - interest.
The final month pays off the remaining principal, and its interest is whatever makes that
month's total equal to the shared EMI. So the rounding and the small difference between the
computed and shared figures all land in the final due, and every due is the same EMI.
"""
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from ..engine.schedule import r2
from ..models import Loan


def generate_rows(loan: Loan) -> tuple[list[dict], list[str]]:
    """Returns (rows, warnings). Raises ValueError when the EMI cannot be used."""
    if not loan.emi_amount or loan.emi_amount <= 0:
        raise ValueError("EMI amount is missing in the loan master")
    if not loan.first_due_date or not loan.tenure_months:
        raise ValueError("first repayment date or tenure is missing")
    emi = Decimal(loan.emi_amount)
    monthly = Decimal(loan.annual_rate) / Decimal(1200)
    balance = Decimal(loan.principal)
    tenure = loan.tenure_months
    rows, warnings = [], []
    for k in range(1, tenure + 1):
        due = loan.first_due_date + relativedelta(months=k - 1)
        computed_interest = r2(balance * monthly)
        if k < tenure:
            interest = computed_interest
            principal = emi - interest
            if principal <= 0:
                raise ValueError(f"EMI {emi} does not cover the interest in month {k}")
            if principal > balance:
                raise ValueError(f"EMI {emi} is too large for the balance in month {k}")
        else:
            principal = balance
            interest = emi - principal
            if interest < 0:
                raise ValueError(f"the final month's principal {principal} is more than the EMI {emi}")
            if abs(interest - computed_interest) > Decimal("1"):
                warnings.append(f"final due carries {interest - computed_interest} of rounding "
                                f"or difference (interest {interest} against {computed_interest} calculated)")
        rows.append({"installment_no": k, "due_date": due, "emi_amount": emi,
                     "principal_component": r2(principal), "interest_component": r2(interest)})
        balance -= principal
    return rows, warnings
