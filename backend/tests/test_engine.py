from datetime import date
from decimal import Decimal as D

from app.engine.schedule import generate_schedule, emi_amount
from app.engine.apportion import (InstDue, ChargeDue, apportion, dpd, dpd_bucket,
                                  HEAD_WISE, INSTALLMENT_WISE, HOLD, ADVANCE)


def test_emi_standard():
    # 1,00,000 at 12% for 12 months -> 8884.88
    assert emi_amount(100000, 12, 12) == D("8884.88")


def test_reducing_schedule_closes_to_zero():
    rows = generate_schedule(100000, 12, 12, date(2026, 5, 10))
    assert len(rows) == 12
    assert sum(r.principal for r in rows) == D("100000.00")
    assert rows[-1].closing_balance == 0
    assert rows[0].interest == D("1000.00")
    assert rows[0].due_date == date(2026, 6, 10)
    assert all(r.emi == D("8884.88") for r in rows[:-1])


def test_month_end_dates_do_not_drift():
    rows = generate_schedule(50000, 18, 4, date(2026, 1, 1), first_due_date=date(2026, 1, 31))
    assert [r.due_date for r in rows] == [date(2026, 1, 31), date(2026, 2, 28),
                                         date(2026, 3, 31), date(2026, 4, 30)]


def test_broken_period_interest():
    rows = generate_schedule(100000, 12, 12, date(2026, 5, 20), first_due_date=date(2026, 7, 5))
    # 46 days ACT/365
    assert rows[0].interest == D("1512.33")
    assert sum(r.principal for r in rows) == D("100000.00")


def test_flat_schedule():
    rows = generate_schedule(120000, 10, 12, date(2026, 5, 1), method="FLAT")
    assert sum(r.interest for r in rows) == D("12000.00")
    assert sum(r.principal for r in rows) == D("120000.00")


def test_zero_rate():
    rows = generate_schedule(1000, 0, 3, date(2026, 5, 1))
    assert sum(r.principal for r in rows) == D("1000.00")
    assert all(r.interest == 0 for r in rows)


def _insts():
    return [
        InstDue(1, 1, date(2026, 6, 10), D("1000"), D("7884.88")),
        InstDue(2, 2, date(2026, 7, 10), D("921.15"), D("7963.73")),
        InstDue(3, 3, date(2026, 8, 10), D("841.51"), D("8043.37")),
    ]


def test_head_wise_interest_first_across_instalments():
    insts = _insts()
    charges = [ChargeDue(9, date(2026, 6, 15), D("500"))]
    res = apportion(D("2500"), date(2026, 7, 20), insts, charges, HEAD_WISE, HOLD)
    t = res.total_by_component()
    assert t["INTEREST"] == D("1921.15")          # both instalments' interest
    assert t["PRINCIPAL"] == D("578.85")          # rest to oldest principal
    assert t["CHARGE"] == 0
    assert insts[0].principal_os == D("7306.03")
    assert insts[1].principal_os == D("7963.73")


def test_installment_wise_clears_oldest_first():
    insts = _insts()
    res = apportion(D("9000"), date(2026, 7, 20), insts, [], INSTALLMENT_WISE, HOLD)
    assert insts[0].interest_os == 0 and insts[0].principal_os == 0
    assert insts[1].interest_os == D("806.03")


def test_charges_last_and_excess_held():
    insts = _insts()
    charges = [ChargeDue(9, date(2026, 6, 15), D("500"))]
    res = apportion(D("20000"), date(2026, 7, 20), insts, charges, HEAD_WISE, HOLD)
    t = res.total_by_component()
    assert t["CHARGE"] == D("500")
    assert res.excess == D("20000") - D("1921.15") - D("15848.61") - D("500")
    assert insts[2].interest_os == D("841.51")     # future instalment untouched


def test_future_charge_not_collected():
    insts = _insts()
    charges = [ChargeDue(9, date(2026, 8, 1), D("500"))]
    res = apportion(D("20000"), date(2026, 7, 20), insts, charges, HEAD_WISE, HOLD)
    assert res.total_by_component()["CHARGE"] == 0


def test_advance_mode_prepays_future():
    insts = _insts()
    res = apportion(D("20000"), date(2026, 7, 20), insts, [], HEAD_WISE, ADVANCE)
    # 17769.76 clears the two due EMIs; 2230.24 goes to instalment 3
    assert insts[2].interest_os == 0
    assert insts[2].principal_os == D("6654.64")
    assert res.excess == 0


def test_dpd():
    insts = _insts()
    assert dpd(insts, date(2026, 7, 20)) == 40
    insts[0].interest_os = insts[0].principal_os = D("0")
    assert dpd(insts, date(2026, 7, 20)) == 10
    assert dpd_bucket(10) == "SMA-0 (1-30)"
    assert dpd_bucket(91) == "NPA (90+)"
