"""Loan documents: the slots offered when booking a loan, and storing / reading the files."""
from __future__ import annotations

from sqlalchemy.orm import Session, defer

from ..models import Loan, LoanDocument
from .loan_service import LmsError, audit

# (code, label) in the order shown on the booking form. OTHER can be used any number of times.
DOC_TYPES = [
    ("CHALLAN", "Challan"),
    ("VEHICLE_INVOICE", "Vehicle invoice"),
    ("INSURANCE", "Insurance copy"),
    ("AADHAAR", "Aadhaar"),
    ("PAN", "PAN"),
    ("DRIVING_LICENCE", "Driving licence"),
    ("LLR", "Learner's licence (LLR)"),
    ("DEBIT_NOTE", "Debit note"),
    ("CREDIT_NOTE", "Credit note"),
    ("LOAN_AGREEMENT", "Loan agreement"),
    ("VAS_AGREEMENT", "VAS agreement"),
    ("TRIPARTITE_AGREEMENT", "Tripartite agreement"),
    ("RTO_FORM", "RTO form"),
    ("DELIVERY_PHOTO", "Delivery photo"),
    ("ODOMETER", "Odometer photo"),
    ("OTHER", "Other document"),
]
DOC_LABELS = dict(DOC_TYPES)
MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
           ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic"}


def _ext(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def doc_out(d: LoanDocument) -> dict:
    return {"id": d.id, "loan_id": d.loan_id, "doc_type": d.doc_type,
            "doc_label": d.label if d.doc_type == "OTHER" and d.label else DOC_LABELS.get(d.doc_type, d.doc_type),
            "file_name": d.file_name, "content_type": d.content_type, "size_bytes": d.size_bytes,
            "uploaded_by": d.uploaded_by,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None}


def save(db: Session, loan: Loan, *, doc_type: str, label: str | None, file_name: str,
         data: bytes, user: str | None) -> LoanDocument:
    if doc_type not in DOC_LABELS:
        raise LmsError(f"Unknown document type {doc_type}")
    label = (label or "").strip() or None
    if doc_type == "OTHER" and not label:
        raise LmsError("Give the other document a name")
    ext = _ext(file_name or "")
    if ext not in ALLOWED:
        raise LmsError(f"{file_name}: only PDF, JPG, PNG, WEBP or HEIC files can be uploaded")
    if not data:
        raise LmsError(f"{file_name} is empty")
    if len(data) > MAX_BYTES:
        raise LmsError(f"{file_name} is larger than 10 MB")
    d = LoanDocument(loan_id=loan.id, doc_type=doc_type, label=label if doc_type == "OTHER" else None,
                     file_name=file_name[-255:], content_type=ALLOWED[ext], size_bytes=len(data),
                     content=data, uploaded_by=user)
    db.add(d)
    db.flush()
    audit(db, user, "UPLOAD_DOCUMENT", "loan", loan.loan_number,
          {"doc_type": doc_type, "file": d.file_name, "bytes": len(data)})
    return d


def list_for(db: Session, loan_id: int) -> list[dict]:
    rows = (db.query(LoanDocument).options(defer(LoanDocument.content))
            .filter(LoanDocument.loan_id == loan_id).order_by(LoanDocument.id).all())
    return [doc_out(d) for d in rows]
