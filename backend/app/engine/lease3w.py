"""3-wheeler lease (L3): deal maths and repayment schedule.

Ported from the RPS generator the master book was built with (lease_rps_v3.py), so the LMS
gives the same numbers. Money is Decimal.

- Loan (ORP) = ex-showroom incl. 5% GST + insurance + (RTO + misc + HSRP) + Kazam
  - credit note incl. 5% GST.
- GST IC = half the GST on the ex-showroom and credit-note lines; deducted from the outflow.
- Security deposit = 11% of loan. Net outflow = loan - GST IC - security deposit.
- EMI = ROUNDUP(loan x 31.15 / 1000). Tenure is 36 EMIs including the advance EMI.
- The schedule opens at ROUNDUP(net outflow); the advance EMI comes off it on disbursal.
- Interest rate = monthly IRR of (-(net - EMI), then EMI x 35), x 12.
- Branch A (disbursed up to the pay day): BPI to the pay day, EMI 1 on next month's pay day.
- Branch B (after the pay day, before the cutoff day): EMI 1 on next month's pay day, actual days.
- Branch C (cutoff day or later): BPI to next month's pay day, EMI 1 the month after.
- EMIs 2 onward: flat 30/360 interest on the balance. The last EMI absorbs rounding.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta

PRODUCT_CODE = "L3_3W"
TENURE = 36                  # EMIs including the advance EMI
PTPM = Decimal("31.15")      # EMI per Rs 1,000 of loan
GST = Decimal("0.05")
SD_RATE = Decimal("0.11")
PF_RATE = Decimal("0.0075")
PAY_DAY = 10
CUTOFF_DAY = 21
PLUG_TOL = Decimal("10")     # leftovers up to this go into interest on the last EMI
TWO = Decimal("0.01")


def rupee(x) -> Decimal:
    """Interest is rounded to whole rupees (half up), as in the master RPS."""
    return Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def roundup(x) -> Decimal:
    """Excel ROUNDUP(x, 0) for positive numbers."""
    return Decimal(x).quantize(Decimal("1E-9")).to_integral_value(rounding=ROUND_CEILING)


def _monthly_irr(cfs: list[float]) -> float:
    f = lambda r: sum(cf / (1 + r) ** i for i, cf in enumerate(cfs))
    lo, hi = -0.99, 1.0
    for _ in range(300):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@dataclass
class Deal:
    loan: Decimal        # ORP incl. GST: the amount the dealer is paid
    ic: Decimal          # GST input credit, deducted from the outflow
    sd: Decimal          # security deposit
    pf: Decimal          # processing fee (0.75% of loan)
    net: Decimal         # net outflow
    emi: Decimal
    roi: Decimal         # annual rate as a fraction (monthly IRR x 12)
    lines: list          # ORP breakdown for display


@dataclass
class Row:
    kind: str            # ADVANCE / BPI / EMI
    no: int | None       # EMI number (advance 0, EMIs 1..35), as in the master sheet
    due: date
    days: int | None
    opening: Decimal | None
    interest: Decimal
    principal: Decimal
    emi: Decimal
    closing: Decimal | None


def _line(head, value, gst_pct, ic=False):
    gst = value * gst_pct
    return {"head": head, "value": value, "gst": gst, "total": value + gst,
            "ic": gst / 2 if ic else Decimal(0)}


def calc_deal(vehicle, insurance, rto, misc, hsrp, kazam, scheme) -> Deal:
    vehicle, insurance, rto, misc, hsrp, kazam, scheme = (
        Decimal(str(x)) for x in (vehicle, insurance, rto, misc, hsrp, kazam, scheme))
    cn = -(abs(scheme) * 100 / 105).quantize(TWO, rounding=ROUND_HALF_UP)
    lines = [
        _line("Ex-showroom (discounted)", vehicle, GST, ic=True),
        _line("Insurance", insurance, Decimal(0)),
        _line("Registration (RTO + misc + HSRP)", rto + misc + hsrp, Decimal(0)),
        _line("Kazam earthing", kazam, Decimal(0)),
        _line("Credit note", cn, GST, ic=True),
    ]
    loan = sum(l["total"] for l in lines)
    ic = sum(l["ic"] for l in lines)
    sd = loan * SD_RATE
    net = loan - ic - sd
    emi = roundup(loan * PTPM / 1000)
    m = _monthly_irr([float(-net + emi)] + [float(emi)] * (TENURE - 1))
    roi = Decimal(repr(m * 12))
    return Deal(loan=loan, ic=ic, sd=sd, pf=loan * PF_RATE, net=net, emi=emi, roi=roi, lines=lines)


def _add(d: date, months: int) -> date:
    return d + relativedelta(months=months)


def build_schedule(disb: date, deal: Deal, pay_day: int = PAY_DAY, cutoff_day: int = CUTOFF_DAY):
    """Returns (branch, rows, adjustment). Rows are ADVANCE, optional BPI, then EMIs."""
    emi, roi = deal.emi, deal.roi
    opening = roundup(deal.net)
    rows = [Row("ADVANCE", 0, disb, 0, opening, Decimal(0), emi, emi, opening - emi)]
    bal = opening - emi
    this_pay = date(disb.year, disb.month, pay_day)

    if disb.day <= pay_day:                       # Branch A
        branch = "A"
        bpi_days = (this_pay - disb).days + 1
        bpi_date = _add(this_pay, 1)              # as in the master sheet
        emi1 = bpi_date
        emi1_days = 30
    elif disb.day < cutoff_day:                   # Branch B
        branch = "B"
        bpi_days = None
        emi1 = _add(this_pay, 1)
        emi1_days = (emi1 - disb).days + 1
    else:                                         # Branch C
        branch = "C"
        bpi_date = _add(this_pay, 1)
        bpi_days = (bpi_date - disb).days + 1
        emi1 = _add(bpi_date, 1)
        emi1_days = 30

    if bpi_days is not None:
        bpi = rupee(Decimal(bpi_days) / 360 * bal * roi)
        rows.append(Row("BPI", None, bpi_date, None, None, bpi, Decimal(0), bpi, None))

    days1 = emi1_days if branch == "B" else (emi1 - disb).days
    intr1 = rupee(Decimal(emi1_days) / 360 * bal * roi)
    principal1 = emi - intr1
    rows.append(Row("EMI", 1, emi1, days1, bal, intr1, principal1, emi, bal - principal1))
    bal -= principal1
    prev = emi1

    adjustment = Decimal(0)
    for i in range(1, TENURE - 1):                # EMIs 2..35
        due = _add(emi1, i)
        act_days = (due - prev).days
        natural = rupee(Decimal(30) / 360 * bal * roi)
        pay = emi
        no = i + 1
        if no == TENURE - 1:                      # last EMI closes the balance
            principal = bal
            if abs(bal - (emi - natural)) <= PLUG_TOL:
                intr = emi - principal
                adjustment = intr - natural
            else:
                intr = natural
                pay = principal + intr
                adjustment = pay - emi
        else:
            intr = natural
            principal = emi - intr
        rows.append(Row("EMI", no, due, act_days, bal, intr, principal, pay, bal - principal))
        bal -= principal
        prev = due
    return branch, rows, adjustment
