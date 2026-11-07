"""Generate sample M2P export files (the template format for the real migration).

python scripts/make_sample_m2p.py sample_data/m2p
"""
import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.engine.schedule import generate_schedule  # noqa: E402

CUTOFF = date(2026, 4, 30)
out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_data/m2p")
out.mkdir(parents=True, exist_ok=True)

loans = [
    # id, cust, name, mobile, pan, product, principal, rate, tenure, disb, paid_upto_inst, status
    ("M2P100001", "C9001", "Ravi Kumar", "9845012345", "ABCPK1234F", "PL-STD", 300000, 16, 24,
     date(2025, 6, 5), "all", "ACTIVE"),
    ("M2P100002", "C9002", "Anita Sharma", "9900112233", "BCDPS2345G", "PL-STD", 150000, 20, 18,
     date(2025, 9, 12), 4, "ACTIVE"),          # stopped paying after EMI 4 -> overdue
    ("M2P100003", "C9003", "Mohammed Irfan", "9123456780", "CDEPI3456H", "PL-STD", 50000, 18, 6,
     date(2025, 8, 1), "all", "CLOSED"),
]

with open(out / "loans.csv", "w", newline="") as fl, \
        open(out / "schedule.csv", "w", newline="") as fs, \
        open(out / "receipts.csv", "w", newline="") as fr, \
        open(out / "charges.csv", "w", newline="") as fc:
    wl, ws, wr, wc = csv.writer(fl), csv.writer(fs), csv.writer(fr), csv.writer(fc)
    wl.writerow(["Loan Account Number", "Customer ID", "Customer Name", "Mobile", "PAN",
                 "Product Code", "Loan Amount", "ROI", "Tenure", "Interest Type",
                 "Disbursement Date", "First EMI Date", "EMI Amount", "Loan Status"])
    ws.writerow(["Loan Account Number", "Installment No", "Due Date", "Principal Component",
                 "Interest Component", "Principal Paid", "Interest Paid"])
    wr.writerow(["Loan Account Number", "Receipt Date", "Receipt Amount", "Payment Mode", "UTR"])
    wc.writerow(["Loan Account Number", "Charge Type", "Charge Date", "Amount", "Paid Amount",
                 "Waived Amount"])
    for lid, cid, name, mob, pan, prod, amt, rate, ten, disb, upto, status in loans:
        rows = generate_schedule(amt, rate, ten, disb)
        wl.writerow([lid, cid, name, mob, pan, prod, amt, rate, ten, "Reducing",
                     disb.strftime("%d-%m-%Y"), rows[0].due_date.strftime("%d-%m-%Y"),
                     rows[1].emi, status])
        for r in rows:
            paid = r.due_date <= CUTOFF and (upto == "all" or r.installment_no <= upto)
            if status == "CLOSED":
                paid = True
            ws.writerow([lid, r.installment_no, r.due_date.strftime("%d-%m-%Y"), r.principal,
                         r.interest, r.principal if paid else 0, r.interest if paid else 0])
            if paid:
                wr.writerow([lid, min(r.due_date, CUTOFF).strftime("%d-%m-%Y"), r.emi, "NACH",
                             f"UTR{lid[-3:]}{r.installment_no:03d}"])
        if lid == "M2P100002":
            wc.writerow([lid, "Late Fee", "05-03-2026", 500, 0, 0])
            wc.writerow([lid, "Bounce", "15-02-2026", 590, 590, 0])
            wr.writerow([lid, "20-02-2026", 590, "UPI", "UTR002BNC"])
        if lid == "M2P100001":
            # a receipt after cutoff in the export: posted through the new waterfall
            wr.writerow([lid, "05-05-2026", rows[1].emi, "NACH", "UTR001POST"])
print("written to", out)
