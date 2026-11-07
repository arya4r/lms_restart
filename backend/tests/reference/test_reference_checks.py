"""Reference checks against a real migrated database.

These need the database that holds the reference loans, so they are skipped unless
REFERENCE_DATABASE_URL is set. The database and its credentials stay outside git.

Run:
    REFERENCE_DATABASE_URL=mysql+pymysql://user:pw@host:3306/lms \
    REFERENCE_ADMIN_PASSWORD=... \
    python -m pytest tests/reference -v

Each check is a figure the business has signed off:
  GFLE2W100009242 as of 8 Nov 2026: FCL amount 69,131, charges 4,200, total 73,331, DPD 65
  GFLE2W100009242 as of 30 Apr 2026: DPD 26
"""
import os
from decimal import Decimal as D

import pytest

REF_URL = os.getenv("REFERENCE_DATABASE_URL")
if not REF_URL:
    pytest.skip("REFERENCE_DATABASE_URL not set: reference checks need the migrated database",
                allow_module_level=True)

# Point the app at the reference database before it is imported. This process runs only these tests.
os.environ["DATABASE_URL"] = REF_URL
os.environ.setdefault("JWT_SECRET", "reference-run-only-secret-0123456789abcdef")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

LOAN = "GFLE2W100009242"
ADMIN_PASSWORD = os.getenv("REFERENCE_ADMIN_PASSWORD")


@pytest.fixture(scope="module")
def client():
    if not ADMIN_PASSWORD:
        pytest.skip("REFERENCE_ADMIN_PASSWORD not set")
    with TestClient(app) as c:
        tok = c.post("/api/auth/login", json={"username": os.getenv("REFERENCE_ADMIN_USER", "admin"),
                                              "password": ADMIN_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        yield c


@pytest.fixture(scope="module")
def loan_id(client):
    res = client.get("/api/loans", params={"q": LOAN, "limit": 200}).json()
    matches = [l for l in res["items"] if l.get("loan_number") == LOAN]
    assert len(matches) == 1, f"expected one loan {LOAN}, found {len(matches)}"
    return matches[0]["id"]


def _money(s) -> D:
    return D(str(s))


def test_fcl_total_on_8_nov_2026(client, loan_id):
    q = client.get(f"/api/loans/{loan_id}/foreclosure", params={"as_of": "2026-11-08"}).json()
    assert _money(q["fcl_amount"]) == D("69131")
    assert _money(q["total"]) == D("73331")
    # the charges figure is the part of the total that is not the FCL amount
    assert _money(q["total"]) - _money(q["fcl_amount"]) == D("4200")


def test_dpd_on_8_nov_2026(client, loan_id):
    pos = client.get(f"/api/loans/{loan_id}/position", params={"as_of": "2026-11-08"}).json()
    assert pos["dpd"] == 65


def test_dpd_on_30_apr_2026(client, loan_id):
    pos = client.get(f"/api/loans/{loan_id}/position", params={"as_of": "2026-04-30"}).json()
    assert pos["dpd"] == 26
