"""Column-selectable CSV exports for the loan master and RPS. The caller picks the columns;
the file has them in the order picked."""
import csv
import io
import json
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import Loan, RpsRow

LOAN_MASTER_COLUMNS = [
    ("loan_number", "Loan account number"), ("customer_external_ref", "Customer ID"),
    ("customer_name", "Customer name"), ("mobile", "Mobile"), ("email", "Email"), ("pan", "PAN"),
    ("address", "Address"), ("product_code", "Product code"), ("source", "Source"),
    ("loan_amount", "Loan amount"), ("principal", "Principal amount"), ("annual_rate", "ROI (%)"),
    ("tenure_months", "Tenure (months)"), ("disbursal_date", "Disbursement date"),
    ("first_due_date", "First repayment date"), ("last_due_date", "Last repayment date"),
    ("emi_amount", "EMI amount"), ("processing_fee", "Processing fee"), ("stamp_duty", "Stamp duty"),
    ("document_charges", "Document charges"), ("insurance_amount", "Insurance amount"),
    ("rsa_charge", "RSA (road safety)"), ("bounce_charge", "Bounce charges"), ("status", "Loan status"),
]

RPS_COLUMNS = [
    ("loan_number", "Loan account number"), ("installment_no", "Installment no"),
    ("due_date", "Due date"), ("emi_amount", "EMI amount"),
    ("principal_component", "Principal component"), ("interest_component", "Interest component"),
]


def _s(v):
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _loan_row(loan: Loan) -> dict:
    c = loan.customer
    return {
        "loan_number": loan.loan_number,
        "customer_external_ref": c.external_ref if c else None,
        "customer_name": c.name if c else None,
        "mobile": c.mobile if c else None, "email": c.email if c else None,
        "pan": c.pan if c else None, "address": c.address if c else None,
        "product_code": loan.product.code if loan.product else None,
        "source": loan.source, "loan_amount": loan.loan_amount, "principal": loan.principal,
        "annual_rate": loan.annual_rate, "tenure_months": loan.tenure_months,
        "disbursal_date": loan.disbursal_date, "first_due_date": loan.first_due_date,
        "last_due_date": loan.last_due_date, "emi_amount": loan.emi_amount,
        "processing_fee": loan.processing_fee, "stamp_duty": loan.stamp_duty,
        "document_charges": loan.document_charges, "insurance_amount": loan.insurance_amount,
        "rsa_charge": loan.rsa_charge, "bounce_charge": loan.bounce_charge, "status": loan.status,
    }


def _check(selected, available):
    if not selected:
        raise ValueError("Pick at least one column")
    unknown = [k for k in selected if k not in dict(available)]
    if unknown:
        raise ValueError(f"Unknown column(s): {', '.join(unknown)}")


def loan_master_columns(db: Session) -> list[tuple[str, str]]:
    """The fixed columns, then every column that appeared in an uploaded loan master (as raw:<name>)."""
    headers, seen = [], set()
    for (d,) in db.query(Loan.details).filter(Loan.details.isnot(None)):
        for k in json.loads(d):
            if k not in seen:
                seen.add(k)
                headers.append(k)
    return LOAN_MASTER_COLUMNS + [(f"raw:{h}", h) for h in headers]


def loan_master_csv(db: Session, selected: list[str]) -> str:
    available = loan_master_columns(db)
    _check(selected, available)
    rows = []
    for loan in db.query(Loan).order_by(Loan.id).all():
        row = _loan_row(loan)
        raw = json.loads(loan.details or "{}")
        for k in selected:
            if k.startswith("raw:"):
                row[k] = raw.get(k[4:], "")
        rows.append(row)
    return _to_csv(selected, dict(available), rows)


def rps_csv(db: Session, selected: list[str]) -> str:
    _check(selected, RPS_COLUMNS)
    rows = [{"loan_number": r.loan_number, "installment_no": r.installment_no, "due_date": r.due_date,
             "emi_amount": r.emi_amount, "principal_component": r.principal_component,
             "interest_component": r.interest_component}
            for r in db.query(RpsRow).order_by(RpsRow.loan_number, RpsRow.row_no).all()]
    return _to_csv(selected, dict(RPS_COLUMNS), rows)


def _to_csv(selected, labels: dict, rows) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([labels[k] for k in selected])
    for r in rows:
        w.writerow([_s(r.get(k)) for k in selected])
    return out.getvalue()
