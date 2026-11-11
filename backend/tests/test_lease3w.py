"""3-wheeler lease (L3): engine values taken from the master RPS workbook, plus API booking."""
import os
import tempfile
from datetime import date
from decimal import Decimal as D
from pathlib import Path

_db = Path(tempfile.mkdtemp()) / "lease.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db}")
os.environ.setdefault("ADMIN_PASSWORD", "Admin@12345")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.engine import lease3w as L  # noqa: E402
from app.main import app  # noqa: E402

# GRFL/MLM/D023 in All_Loans_RPS_final_v3.xlsx (disbursed 2 Sep 2026, Branch A)
D023 = dict(vehicle=357369, insurance=8480, rto=5500, misc=2704, hsrp=279, kazam=6300, scheme=38000)


def _deal(inp):
    return L.calc_deal(**{k: D(str(v)) for k, v in inp.items()})


def test_deal_matches_master():
    d = _deal(D023)
    assert d.loan.quantize(D("0.001")) == D("360500.446")
    assert d.ic.quantize(D("0.001")) == D("8029.463")
    assert d.sd.quantize(D("0.00001")) == D("39655.04906")
    assert d.net.quantize(D("0.00001")) == D("312815.93394")
    assert d.emi == D("11230")


def test_schedule_matches_master_rows():
    branch, rows, adj = L.build_schedule(date(2026, 9, 2), _deal(D023))
    assert branch == "A"
    assert rows[0].kind == "ADVANCE" and rows[0].opening == D("312816")
    bpi = rows[1]
    assert bpi.kind == "BPI" and bpi.due == date(2026, 10, 10) and bpi.interest == D("1403")
    emi1 = rows[2]
    assert (emi1.no, emi1.days, emi1.interest, emi1.principal, emi1.closing) == \
        (1, 38, D("4676"), D("6554"), D("295032"))
    last = rows[-1]
    assert (last.no, last.interest, last.principal, last.closing) == (35, D("175"), D("11055"), D("0"))
    assert adj == D("4")                                  # last-row rounding, as in the master
    assert sum(r.principal for r in rows) == D("312816")  # balance closes to zero


def test_branch_b_and_c_dates():
    _, rows_b, _ = L.build_schedule(date(2026, 9, 15), _deal(D023))
    assert rows_b[1].kind == "EMI" and rows_b[1].due == date(2026, 10, 10)
    _, rows_c, _ = L.build_schedule(date(2026, 9, 25), _deal(D023))
    assert rows_c[1].kind == "BPI" and rows_c[1].due == date(2026, 10, 10)
    assert rows_c[2].due == date(2026, 11, 10)


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        tok = client.post("/api/auth/login", json={"username": "admin",
                                                    "password": "Admin@12345"}).json()["token"]
        client.headers["Authorization"] = f"Bearer {tok}"
        yield client


def test_api_preview_and_book_single(c):
    body = dict(D023, disbursal_date="2026-09-02", lan="GRFL/MLM/D023",
                customer_name="Test Borrower", customer_mobile="9999999999", dealer="Test Dealer")
    prev = c.post("/api/lease3w/preview", json=body).json()
    assert prev["branch"] == "A" and prev["deal"]["emi"] == "11230"
    r = c.post("/api/lease3w/loans", json=body)
    assert r.status_code == 200, r.text
    loan = r.json()
    assert float(loan["emi_amount"]) == 11230 and loan["tenure_months"] == 36
    again = c.post("/api/lease3w/loans", json=body)
    assert again.status_code == 400


def test_old_booking_refuses_lease_product(c):
    c.post("/api/lease3w/loans", json=dict(D023, disbursal_date="2026-09-02", lan="T-OLD-1",
                                          customer_name="X"))
    products = c.get("/api/products").json()
    lease = next(p for p in products if p["code"] == "L3_3W")
    r = c.post("/api/loans", json={"customer_id": 1, "product_id": lease["id"], "principal": 1000,
                                   "tenure_months": 36, "disbursal_date": "2026-09-02"})
    assert r.status_code == 400


def test_bulk_check_then_import(c):
    csv_text = (
        "Sno,ID,Customer Name,Dealer Name,Customer Mobile,Disbursement Date,Vehicle Value,"
        "Insuranace,RTO charges,Kazam Earthing,Misc exp.,HSRP - For Number Plate,"
        "Scheme discount (DP),Status\n"
        "1,BULK/1,Asha,Dealer A,9000000001,02-09-2026,357368.57,8480,5500,6300,2704,279,38000,\n"
        "2,BULK/2,Ravi,Dealer A,9000000002,15-09-2026,357368.57,8480,5500,6300,2704,279,38000,Reverted\n"
        "3,BULK/3,Meena,Dealer B,9000000003,,357368.57,8480,5500,6300,2704,279,38000,\n"
    ).encode()
    chk = c.post("/api/lease3w/import", files={"file": ("l3.csv", csv_text, "text/csv")},
                 data={"dry_run": "true"}).json()
    assert chk["to_book"] == 1 and chk["skipped"] == 2 and chk["error_count"] == 0
    imp = c.post("/api/lease3w/import", files={"file": ("l3.csv", csv_text, "text/csv")},
                 data={"dry_run": "false"}).json()
    assert imp["to_book"] == 1
    again = c.post("/api/lease3w/import", files={"file": ("l3.csv", csv_text, "text/csv")},
                   data={"dry_run": "false"}).json()
    assert again["to_book"] == 0 and again["skipped"] >= 1


def test_position_reads_generated_rps(c):
    body = dict(D023, disbursal_date="2026-09-02", lan="POS/L3/1", customer_name="Position Check")
    loan = c.post("/api/lease3w/loans", json=body).json()
    p = c.get(f"/api/loans/{loan['id']}/position", params={"as_of": "2026-09-05"}).json()
    assert p["has_rps"] is True
    assert D(p["principal"]["charged"]) == D("312816")      # ROUNDUP(net outflow)
    assert D(p["principal"]["paid"]) == D("11230")          # advance EMI, paid on disbursal
    assert D(p["interest"]["charged"]) == D("92867")        # total interest in the master sheet
    assert p["dpd"] == 0
    # a later RPS regeneration must not overwrite the L3 schedule
    r = c.post("/api/rps/generate", json={"loan_numbers": ["POS/L3/1"], "replace": True}).json()
    assert "POS/L3/1" in r["skipped"]


def test_no_late_charge_and_no_foreclosure(c):
    body = dict(D023, disbursal_date="2026-09-02", lan="NOFEE/L3/1", customer_name="No Fee Check")
    loan = c.post("/api/lease3w/loans", json=body).json()
    lid = loan["id"]
    # 10 Oct dues are well past grace by 10 Nov, but L3 loans carry no late charge
    p = c.get(f"/api/loans/{lid}/position", params={"as_of": "2026-11-10"}).json()
    assert p["dpd"] > 5
    assert D(p["late_charges"]["charged"]) == 0
    c.post("/api/eod/late-fees", params={"as_of": "2026-11-10"})
    assert c.get(f"/api/loans/{lid}/charges").json() == []
    # and no foreclosure: quote, PDF and closing are all refused
    for path in (f"/api/loans/{lid}/foreclosure", f"/api/loans/{lid}/foreclosure.pdf",
                 f"/api/loans/{lid}/foreclosure-quote"):
        r = c.get(path, params={"as_of": "2026-11-10"})
        assert r.status_code == 400 and "not offered" in r.text, path
    r = c.post(f"/api/loans/{lid}/foreclose", json={"amount": 1000, "payment_date": "2026-11-10"})
    assert r.status_code == 400


def test_loan_documents_upload_list_open_delete(c):
    loan = c.post("/api/lease3w/loans", json=dict(D023, disbursal_date="2026-09-02", lan="DOC/L3/1",
                                                 customer_name="Docs Check")).json()
    lid = loan["id"]
    types = [t["code"] for t in c.get("/api/documents/types").json()]
    assert types[:3] == ["CHALLAN", "VEHICLE_INVOICE", "INSURANCE"] and types[-1] == "OTHER"
    assert len(types) == 16
    pdf = b"%PDF-1.4 test aadhaar"
    r = c.post(f"/api/loans/{lid}/documents", data={"doc_type": "AADHAAR"},
               files={"file": ("aadhaar.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["doc_label"] == "Aadhaar"
    # other documents need a name; unsupported files and unknown types are refused
    assert c.post(f"/api/loans/{lid}/documents", data={"doc_type": "OTHER"},
                  files={"file": ("x.pdf", pdf, "application/pdf")}).status_code == 400
    assert c.post(f"/api/loans/{lid}/documents", data={"doc_type": "PAN"},
                  files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    assert c.post(f"/api/loans/{lid}/documents", data={"doc_type": "NOPE"},
                  files={"file": ("x.pdf", pdf, "application/pdf")}).status_code == 400
    big = b"0" * (10 * 1024 * 1024 + 1)
    assert c.post(f"/api/loans/{lid}/documents", data={"doc_type": "PAN"},
                  files={"file": ("big.pdf", big, "application/pdf")}).status_code == 400
    r = c.post(f"/api/loans/{lid}/documents", data={"doc_type": "OTHER", "label": "Guarantor letter"},
               files={"file": ("g.jpg", b"\xff\xd8\xff jpg", "image/jpeg")})
    assert r.json()["doc_label"] == "Guarantor letter"
    docs = c.get(f"/api/loans/{lid}/documents").json()
    assert [d["doc_type"] for d in docs] == ["AADHAAR", "OTHER"] and "content" not in docs[0]
    f = c.get(f"/api/documents/{docs[0]['id']}/file")
    assert f.status_code == 200 and f.content == pdf and f.headers["content-type"] == "application/pdf"
    assert c.delete(f"/api/documents/{docs[1]['id']}").status_code == 200
    assert len(c.get(f"/api/loans/{lid}/documents").json()) == 1


def test_loans_search_by_product(c):
    c.post("/api/lease3w/loans", json=dict(D023, disbursal_date="2026-09-02", lan="PROD/L3/1",
                                          customer_name="Product Filter"))
    lease = next(p for p in c.get("/api/products").json() if p["code"] == "L3_3W")
    r = c.get("/api/loans", params={"product_id": lease["id"], "limit": 200}).json()
    assert r["total"] >= 1 and all(l["product_code"] == "L3_3W" for l in r["items"])
    other = c.get("/api/loans", params={"product_id": 999999}).json()
    assert other["total"] == 0


def test_bulk_import_job_reports_imported_and_pending(c):
    import time
    head = ("ID,Customer Name,Disbursement Date,Vehicle Value,Insuranace,RTO charges,Kazam Earthing,"
            "Misc exp.,HSRP - For Number Plate,Scheme discount (DP)\n")
    body = "".join(f"JOB/{i},Cust {i},02-09-2026,357369,8480,5500,6300,2704,279,38000\n" for i in range(120))
    raw = (head + body).encode()
    jid = c.post("/api/lease3w/import-job", files={"file": ("l3.csv", raw, "text/csv")}).json()["job_id"]
    seen = []
    for _ in range(200):
        j = c.get(f"/api/lease3w/jobs/{jid}").json()
        seen.append((j["done"], j["total"]))
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done", j
    assert j["result"]["imported"] == 120 and j["result"]["pending"] == 0
    assert j["total"] == 120 and j["done"] == 120 and j["percent"] == 100
    assert "120 imported, 0 pending" in j["step"]
    # imported in groups of 50, committed as it goes
    loans = c.get("/api/loans", params={"q": "JOB/", "limit": 200}).json()
    assert loans["total"] == 120
