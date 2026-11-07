"""Load demo data through the API: the sample M2P book plus a few new loans with payments.

python scripts/seed_demo.py http://localhost:8000 admin 'Admin@12345'
"""
import sys
from pathlib import Path

import httpx

base, user, pw = (sys.argv[1:4] + [None] * 3)[:3]
base = base or "http://localhost:8000"
c = httpx.Client(base_url=base + "/api", timeout=60)
tok = c.post("/auth/login", json={"username": user or "admin", "password": pw or "Admin@12345"}).json()["token"]
c.headers["Authorization"] = f"Bearer {tok}"

sample = Path(__file__).resolve().parent.parent / "sample_data" / "m2p"
files = {n: (f"{n}.csv", (sample / f"{n}.csv").read_bytes(), "text/csv")
         for n in ("loans", "schedule", "receipts", "charges")}
r = c.post("/import/m2p", files=files, data={"dry_run": "false"}).json()
print("M2P import:", r["loans_imported"], "loans,", len(r["errors"]), "errors")

prod = c.get("/products").json()[0]["id"]
book = [("Priya Nair", "9886011223", "EFGPN4567J", 200000, 16, 18, "2026-05-15",
         [(13000, "2026-06-15"), (13000, "2026-07-15"), (6000, "2026-08-16"), (20000, "2026-09-20")]),
        ("Suresh Gowda", "9740098765", "FGHPG5678K", 75000, 19, 12, "2026-07-01",
         [(6900, "2026-08-01"), (10000, "2026-09-03")]),
        ("Lakshmi Reddy", "9008877665", "GHIPR6789L", 500000, 14, 36, "2026-02-10",
         [(17100, d) for d in ("2026-03-10", "2026-04-10", "2026-05-10", "2026-06-10",
                               "2026-07-10", "2026-08-10", "2026-09-10", "2026-10-10")])]
for name, mob, pan, amt, rate, ten, disb, pays in book:
    cust = c.post("/customers", json={"name": name, "mobile": mob, "pan": pan}).json()
    loan = c.post("/loans", json={"customer_id": cust["id"], "product_id": prod, "principal": amt,
                                  "annual_rate": rate, "tenure_months": ten,
                                  "disbursal_date": disb}).json()
    for amount, d in pays:
        x = c.post(f"/loans/{loan['id']}/repayments",
                   json={"amount": amount, "payment_date": d, "mode": "UPI"})
        x.raise_for_status()
    print("booked", loan["loan_number"], name)
print(c.post("/eod/late-fees").json())
