"""Command line jobs, e.g. for a daily cron / EventBridge scheduled task:

python -m app.cli late-fees            # levy late fees as of today
python -m app.cli late-fees 2026-10-15
"""
import sys
from datetime import date

from .db import SessionLocal, Base, engine
from .services.loan_service import run_late_fees


def main(argv):
    if not argv or argv[0] != "late-fees":
        print(__doc__)
        return 1
    Base.metadata.create_all(engine)
    as_of = date.fromisoformat(argv[1]) if len(argv) > 1 else date.today()
    with SessionLocal() as db:
        print(run_late_fees(db, as_of, user="eod-job"))
        db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
