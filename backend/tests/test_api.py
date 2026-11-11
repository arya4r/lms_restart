import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

_db = Path(tempfile.mkdtemp()) / "test.db"
# set TEST_DATABASE_URL=mysql+pymysql://lms:lms@localhost:3306/lms_test to run against MySQL
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_db}")
os.environ["ADMIN_PASSWORD"] = "Admin@12345"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "m2p"


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        tok = client.post("/api/auth/login", json={"username": "admin",
                                                    "password": "Admin@12345"}).json()["token"]
        client.headers["Authorization"] = f"Bearer {tok}"
        yield client


def test_auth_required():
    with TestClient(app) as anon:
        assert anon.get("/api/loans").status_code == 401
        assert anon.post("/api/auth/login", json={"username": "admin",
                                                  "password": "x"}).status_code == 401


def _book(c, principal=100000, tenure=12, disb=date(2026, 3, 10)):
    prod = next(p for p in c.get("/api/products").json() if p["interest_method"] != "LEASE_3W")
    cust = c.post("/api/customers", json={"name": "Test Borrower", "mobile": "9000000001",
                                          "pan": "ABCDE1234F"}).json()
    r = c.post("/api/loans", json={"customer_id": cust["id"], "product_id": prod["id"],
                                   "principal": principal, "annual_rate": 12,
                                   "tenure_months": tenure, "disbursal_date": disb.isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


def test_book_loan_and_schedule(c):
    loan = _book(c)
    assert loan["loan_number"].startswith("LN2603")
    assert loan["emi_amount"] == "8884.88"
    sched = c.get(f"/api/loans/{loan['id']}/schedule").json()
    assert len(sched) == 12
    assert sum(D(s["principal_due"]) for s in sched) == D("100000")
    # dues 10 Apr .. 10 Oct passed and unpaid -> overdue since 10 Apr
    assert loan["summary"]["dpd"] == (date.today() - date(2026, 4, 10)).days


def test_waterfall_head_wise(c):
    loan = _book(c)
    lid = loan["id"]
    # 2 EMIs due by 20 May; pay 2500 -> all interest of both, rest to oldest principal
    prev = c.post(f"/api/loans/{lid}/repayments/preview",
                  json={"amount": 2500, "payment_date": "2026-05-20"}).json()
    assert prev["interest"] == "1921.15" and prev["principal"] == "578.85"
    r = c.post(f"/api/loans/{lid}/repayments",
               json={"amount": 2500, "payment_date": "2026-05-20", "reference": "UTR1"})
    assert r.status_code == 200, r.text
    reps = c.get(f"/api/loans/{lid}/repayments").json()
    assert reps[0]["interest"] == "1921.15"
    # duplicate reference rejected
    r = c.post(f"/api/loans/{lid}/repayments",
               json={"amount": 10, "payment_date": "2026-05-21", "reference": "UTR1"})
    assert r.status_code == 400


def test_backdated_payment_replays_in_order(c):
    loan = _book(c)
    lid = loan["id"]
    c.post(f"/api/loans/{lid}/repayments", json={"amount": 8884.88, "payment_date": "2026-06-01"})
    # back-dated payment slots in before the first one
    c.post(f"/api/loans/{lid}/repayments", json={"amount": 1000, "payment_date": "2026-04-15"})
    reps = {r["payment_date"]: r for r in c.get(f"/api/loans/{lid}/repayments").json()}
    assert reps["2026-04-15"]["interest"] == "1000.00"   # EMI1 interest
    assert reps["2026-06-01"]["interest"] == "921.15"    # EMI2 interest; EMI1 int already paid


def test_excess_held_then_auto_adjusted(c):
    loan = _book(c)
    lid = loan["id"]
    # pay EMI1 + 3000 extra on 10 Apr; extra is held and adjusts on 10 May
    c.post(f"/api/loans/{lid}/repayments",
           json={"amount": 11884.88, "payment_date": "2026-04-10"})
    reps = c.get(f"/api/loans/{lid}/repayments").json()
    allocs = reps[0]["allocations"]
    from_excess = [a for a in allocs if a["from_excess"]]
    assert from_excess and from_excess[0]["applied_date"] == "2026-05-10"
    assert sum(D(a["amount"]) for a in from_excess) == D("3000.00")
    assert c.get(f"/api/loans/{lid}").json()["summary"]["excess_amount"] == "0.00"


def test_reverse_with_bounce(c):
    loan = _book(c)
    lid = loan["id"]
    rep = c.post(f"/api/loans/{lid}/repayments",
                 json={"amount": 8884.88, "payment_date": "2026-04-10"}).json()["repayment_id"]
    assert c.post(f"/api/repayments/{rep}/reverse",
                  json={"reason": "NACH bounce", "bounce": True}).status_code == 200
    charges = c.get(f"/api/loans/{lid}/charges").json()
    assert charges[0]["charge_type"] == "BOUNCE" and charges[0]["amount"] == "590.00"
    s = c.get(f"/api/loans/{lid}").json()["summary"]
    assert s["interest_collected"] == "0.00"
    assert c.post(f"/api/repayments/{rep}/reverse", json={"reason": "again"}).status_code == 400


def test_charges_paid_last(c):
    loan = _book(c)
    lid = loan["id"]
    c.post(f"/api/loans/{lid}/charges", json={"charge_type": "OTHER", "amount": 500,
                                              "charge_date": "2026-04-01"})
    c.post(f"/api/loans/{lid}/repayments", json={"amount": 9000, "payment_date": "2026-04-12"})
    rep = c.get(f"/api/loans/{lid}/repayments").json()[0]
    assert rep["interest"] == "1000.00" and rep["principal"] == "7884.88"
    assert rep["charges"] == "115.12"


def test_late_fee_eod(c):
    loan = _book(c, disb=date(2026, 8, 1))
    r = c.post("/api/eod/late-fees", params={"as_of": date.today().isoformat()}).json()
    assert r["late_fees_created"] >= 2
    ch = c.get(f"/api/loans/{loan['id']}/charges").json()
    assert all(x["charge_type"] == "LATE_FEE" and x["amount"] == "500.00" for x in ch)
    # re-running does not double-charge
    again = c.post("/api/eod/late-fees", params={"as_of": date.today().isoformat()}).json()
    assert again["late_fees_created"] == 0


def test_full_payment_closes_loan(c):
    loan = _book(c, principal=30000, tenure=3, disb=date(2026, 5, 1))
    lid = loan["id"]
    total = sum(D(s["emi"]) for s in c.get(f"/api/loans/{lid}/schedule").json())
    c.post(f"/api/loans/{lid}/repayments", json={"amount": str(total), "payment_date": "2026-08-05"})
    l2 = c.get(f"/api/loans/{lid}").json()
    assert l2["status"] == "CLOSED" and l2["closed_date"] == "2026-08-05"


def test_foreclosure(c):
    loan = _book(c, disb=date(2026, 6, 1))
    lid = loan["id"]
    fc_date = date(2026, 9, 15)
    c.post(f"/api/loans/{lid}/repayments", json={"amount": 8884.88 * 3, "payment_date": "2026-09-02"})
    q = c.get(f"/api/loans/{lid}/foreclosure-quote", params={"on": fc_date.isoformat()}).json()
    assert q["accrued_days"] == "14"
    assert D(q["foreclosure_fee"]) == (D(q["principal_outstanding"]) * D("0.04")).quantize(D("0.01"))
    low = c.post(f"/api/loans/{lid}/foreclose",
                 json={"amount": "100", "payment_date": fc_date.isoformat()})
    assert low.status_code == 400
    r = c.post(f"/api/loans/{lid}/foreclose",
               json={"amount": q["total_payable"], "payment_date": fc_date.isoformat()})
    assert r.status_code == 200, r.text
    l2 = c.get(f"/api/loans/{lid}").json()
    assert l2["status"] == "FORECLOSED"
    assert l2["summary"]["principal_outstanding"] == "0.00"
    assert D(r.json()["refund_due"]) == 0
    sched = c.get(f"/api/loans/{lid}/schedule").json()
    assert sum(1 for s in sched if s["status"] == "CANCELLED") == 8


def test_m2p_import_dry_run_then_commit(c):
    files = lambda: {n: (f"{n}.csv", (SAMPLE / f"{n}.csv").read_bytes(), "text/csv")
                     for n in ("loans", "schedule", "receipts", "charges")}
    dry = c.post("/api/import/m2p", files=files(), data={"dry_run": "true"}).json()
    assert dry["errors"] == [], dry["errors"]
    assert dry["loans_imported"] == 3
    assert c.get("/api/loans", params={"source": "M2P"}).json()["total"] == 0  # rolled back

    real = c.post("/api/import/m2p", files=files(), data={"dry_run": "false"}).json()
    assert real["loans_imported"] == 3 and real["receipts_post_cutoff"] == 1
    assert all(D(x["difference"]) == 0 for x in real["reconciliation"]), real["reconciliation"]

    loans = {l["loan_number"]: l for l in
             c.get("/api/loans", params={"source": "M2P"}).json()["items"]}
    assert loans["M2P100003"]["status"] == "CLOSED"
    a = loans["M2P100002"]
    assert a["summary"]["dpd"] > 90 and a["summary"]["charges_outstanding"] == "500.00"
    # post-cutoff M2P receipt went through the new waterfall
    reps = c.get(f"/api/loans/{loans['M2P100001']['id']}/repayments").json()
    live = [r for r in reps if not r["historical"]]
    assert len(live) == 1 and D(live[0]["interest"]) > 0

    # payment on or before cutoff is refused; after cutoff uses Interest->Principal->Charges
    bad = c.post(f"/api/loans/{a['id']}/repayments",
                 json={"amount": 1000, "payment_date": "2026-04-30"})
    assert bad.status_code == 400
    ok = c.post(f"/api/loans/{a['id']}/repayments",
                json={"amount": 5000, "payment_date": "2026-05-15"})
    assert ok.status_code == 200
    rep = [r for r in c.get(f"/api/loans/{a['id']}/repayments").json() if not r["historical"]][0]
    # 4 unpaid EMIs carry more than 5000 of interest, so head-wise takes it all as interest
    assert rep["interest"] == "5000.00" and rep["principal"] == "0.00" and rep["charges"] == "0.00"

    # re-import is rejected per loan
    again = c.post("/api/import/m2p", files=files(), data={"dry_run": "true"}).json()
    assert len(again["errors"]) == 3


def test_portfolio_report(c):
    r = c.get("/api/reports/portfolio").json()
    assert r["active_loans"] > 0
    assert {b["bucket"] for b in r["dpd_buckets"]} >= {"Current", "NPA (90+)"}
    assert {s["source"] for s in r["by_source"]} == {"NATIVE", "M2P"}
