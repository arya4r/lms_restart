"""Clear the test loans: the sample M2P book and the demo customers from seed_demo.py.

Test loans, preview (deletes nothing):   python scripts/clear_test_loans.py
Test loans, delete:                     python scripts/clear_test_loans.py --yes
Every imported loan, preview:           python scripts/clear_test_loans.py --imported
Every imported loan, delete:            python scripts/clear_test_loans.py --imported --yes

Run it from the backend folder with the same DATABASE_URL the app uses.
Deleting is permanent.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, DATABASE_URL  # noqa: E402
from app.models import Loan, Customer, Allocation, LoanDocument  # noqa: E402
from app.services.m2p_import import _read  # noqa: E402
from app.services.loan_service import audit  # noqa: E402

DEMO_CUSTOMERS = {"Priya Nair", "Suresh Gowda", "Lakshmi Reddy"}


def main() -> None:
    confirm = "--yes" in sys.argv
    imported_only = "--imported" in sys.argv
    sample_ids = {r["loan_id"] for r in _read((ROOT / "sample_data/m2p/loans.csv").read_text())}
    db = SessionLocal()
    print("Database:", DATABASE_URL)
    try:
        if imported_only:
            # every loan created by an importer (loan master, schedule-backed or post-cutoff)
            targets = [l for l in db.query(Loan).all() if l.external_loan_id]
        else:
            targets = [l for l in db.query(Loan).all()
                       if (l.source == "M2P" and l.external_loan_id in sample_ids)
                       or (l.source == "NATIVE" and l.customer.name in DEMO_CUSTOMERS)]
        for l in targets:
            print(f"{l.loan_number:<18} {str(l.external_loan_id or ''):<16} {l.customer.name:<18} "
                  f"{l.source:<7} {l.status:<9} {l.principal}")
        print(f"\n{len(targets)} loans match.")
        if not confirm:
            print("Preview only. Run again with --yes to delete them.")
            return

        ids = [l.id for l in targets]
        customer_ids = {l.customer_id for l in targets}
        db.query(Allocation).filter(Allocation.loan_id.in_(ids)).delete(synchronize_session=False)
        db.query(LoanDocument).filter(LoanDocument.loan_id.in_(ids)).delete(synchronize_session=False)
        for l in targets:
            db.delete(l)  # instalments, charges and repayments cascade
        db.flush()
        removed_customers = 0
        for cid in customer_ids:
            if db.query(Loan).filter(Loan.customer_id == cid).count() == 0:
                cust = db.get(Customer, cid)
                if cust:
                    db.delete(cust)
                    removed_customers += 1
        audit(db, "clear_test_loans", "CLEAR_TEST_LOANS", "system", None,
              {"loans": len(ids), "customers": removed_customers})
        db.commit()
        print(f"Deleted {len(ids)} loans and {removed_customers} customers with no other loans.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
