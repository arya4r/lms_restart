from __future__ import annotations

import json

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, condecimal
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, selectinload

from .auth import current_user, can_write, admin_only, reports_access, verify_password, make_token, hash_password, forget_user
from .db import get_db
from .engine.apportion import dpd_bucket
from .engine.schedule import generate_schedule
from .models import (User, LoanProduct, Customer, Loan, Installment, Charge, Repayment,
                     Allocation, AuditLog, RpsRow, RpsTransaction)
from .services import loan_service as svc
from .services import exports, master_fields, rps as rps_service, transactions as transactions_service
from .services.transactions import state_as_of, levy_late_charges
from .services.m2p_import import (import_m2p, import_loan_master, import_rps, import_schedule,
                                 import_receipts, import_charges, DEFAULT_CUTOFF)

router = APIRouter(prefix="/api")
Amount = condecimal(gt=0, max_digits=18, decimal_places=2)


def _404(obj, what):
    if not obj:
        raise HTTPException(404, f"{what} not found")
    return obj


def _run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except svc.LmsError as e:
        raise HTTPException(400, str(e))


def _loan(db: Session, loan_id: int) -> Loan:
    loan = db.get(Loan, loan_id, options=[selectinload(Loan.installments),
                                          selectinload(Loan.charges), selectinload(Loan.repayments),
                                          selectinload(Loan.customer), selectinload(Loan.product)])
    return _404(loan, "Loan")


# ------------------------------------------------------------------ auth

class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == body.username, User.active.is_(True)).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Wrong username or password")
    return {"token": make_token(u), "user": {"username": u.username, "role": u.role,
                                             "full_name": u.full_name}}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"username": user.username, "role": user.role, "full_name": user.full_name}


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    full_name: str = ""
    password: str = Field(min_length=8)
    role: Literal["ADMIN", "OPS", "REPORTER", "VIEWER"] = "VIEWER"


@router.get("/users")
def list_users(db: Session = Depends(get_db), _=Depends(admin_only)):
    return [{"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
             "active": u.active} for u in db.query(User).order_by(User.id)]


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: Literal["ADMIN", "OPS", "REPORTER", "VIEWER"] | None = None
    active: bool | None = None
    password: str | None = Field(None, min_length=8)


@router.put("/users/{uid}")
def update_user(uid: int, body: UserUpdate, db: Session = Depends(get_db), admin=Depends(admin_only)):
    u = _404(db.get(User, uid), "User")
    if u.username == admin.username and body.active is False:
        raise HTTPException(400, "You can't deactivate your own account")
    changes = body.model_dump(exclude_none=True)
    if "password" in changes:
        u.password_hash = hash_password(changes.pop("password"))
        changes["password"] = "changed"
    for k, v in changes.items():
        setattr(u, k, v)
    svc.audit(db, admin.username, "UPDATE_USER", "user", u.username, changes)
    db.commit()
    forget_user(u.username)
    return {"id": u.id, "username": u.username, "role": u.role, "active": u.active}


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), admin=Depends(admin_only)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "Username already exists")
    u = User(username=body.username, full_name=body.full_name, role=body.role,
             password_hash=hash_password(body.password))
    db.add(u)
    svc.audit(db, admin.username, "CREATE_USER", "user", body.username, {"role": body.role})
    db.commit()
    return {"id": u.id}


# ------------------------------------------------------------------ products

class ProductIn(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str
    interest_method: Literal["REDUCING", "FLAT"] = "REDUCING"
    default_rate: condecimal(ge=0, le=100) = Decimal("0")
    min_tenure: int = Field(1, ge=1)
    max_tenure: int = Field(60, ge=1, le=600)
    min_amount: condecimal(ge=0) = Decimal("0")
    max_amount: condecimal(gt=0) = Decimal("100000000")
    apportion_mode: Literal["HEAD_WISE", "INSTALLMENT_WISE"] = "HEAD_WISE"
    excess_mode: Literal["HOLD", "ADVANCE"] = "HOLD"
    late_fee: condecimal(ge=0) = Decimal("0")
    grace_days: int = Field(0, ge=0)
    bounce_charge: condecimal(ge=0) = Decimal("0")
    foreclosure_fee_pct: condecimal(ge=0, le=100) = Decimal("0")
    processing_fee_pct: condecimal(ge=0, le=100) = Decimal("0")
    active: bool = True


def _product_out(p: LoanProduct):
    return {c: (str(v) if isinstance(v, Decimal) else v) for c in ProductIn.model_fields
            for v in [getattr(p, c)]} | {"id": p.id}


@router.get("/products")
def list_products(db: Session = Depends(get_db), _=Depends(current_user)):
    return [_product_out(p) for p in db.query(LoanProduct).order_by(LoanProduct.code)]


@router.post("/products")
def create_product(body: ProductIn, db: Session = Depends(get_db), user=Depends(admin_only)):
    if db.query(LoanProduct).filter(LoanProduct.code == body.code).first():
        raise HTTPException(400, "Product code already exists")
    p = LoanProduct(**body.model_dump())
    db.add(p)
    svc.audit(db, user.username, "CREATE_PRODUCT", "product", body.code, body.model_dump())
    db.commit()
    return _product_out(p)


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductIn, db: Session = Depends(get_db),
                   user=Depends(admin_only)):
    p = _404(db.get(LoanProduct, pid), "Product")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    svc.audit(db, user.username, "UPDATE_PRODUCT", "product", p.code, body.model_dump())
    db.commit()
    return _product_out(p)


# ------------------------------------------------------------------ customers

class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    mobile: str | None = Field(None, max_length=20)
    email: str | None = None
    pan: str | None = Field(None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    address: str | None = None
    external_ref: str | None = None


def _cust_out(c: Customer):
    return {"id": c.id, "name": c.name, "mobile": c.mobile, "email": c.email, "pan": c.pan,
            "address": c.address, "external_ref": c.external_ref}


@router.get("/customers")
def list_customers(q: str = "", limit: int = Query(50, le=200), offset: int = 0,
                   db: Session = Depends(get_db), _=Depends(current_user)):
    query = db.query(Customer)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Customer.name.like(like), Customer.mobile.like(like),
                                 Customer.pan.like(like), Customer.external_ref.like(like)))
    total = query.count()
    rows = query.order_by(Customer.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_cust_out(c) for c in rows]}


@router.post("/customers")
def create_customer(body: CustomerIn, db: Session = Depends(get_db), user=Depends(can_write)):
    c = Customer(**body.model_dump())
    db.add(c)
    db.flush()
    svc.audit(db, user.username, "CREATE_CUSTOMER", "customer", c.id, body.model_dump())
    db.commit()
    return _cust_out(c)


@router.get("/customers/{cid}")
def get_customer(cid: int, db: Session = Depends(get_db), _=Depends(current_user)):
    c = _404(db.get(Customer, cid), "Customer")
    latest = max(c.loans, key=lambda l: l.id, default=None)
    client = master_fields.client_groups(json.loads(latest.details or "{}")) if latest else {}
    return _cust_out(c) | {"client_groups": client, "loans": [{"id": l.id, "loan_number": l.loan_number,
                                      "principal": str(l.principal), "status": l.status,
                                      "source": l.source, "disbursal_date": l.disbursal_date.isoformat(),
                                      "emi_amount": str(l.emi_amount), "tenure_months": l.tenure_months,
                                      "last_due_date": l.last_due_date.isoformat() if l.last_due_date else None}
                                     for l in c.loans]}


# ------------------------------------------------------------------ loans

def _loan_out(loan: Loan, with_summary=True):
    details = json.loads(loan.details or "{}")
    d = {"id": loan.id, "loan_number": loan.loan_number, "source": loan.source,
         "external_loan_id": loan.external_loan_id, "customer_id": loan.customer_id,
         "customer_name": loan.customer.name if loan.customer else None,
         "customer_mobile": loan.customer.mobile if loan.customer else None,
         "product_code": loan.product.code if loan.product else None,
         "principal": str(loan.principal), "annual_rate": str(loan.annual_rate),
         "tenure_months": loan.tenure_months, "interest_method": loan.interest_method,
         "disbursal_date": loan.disbursal_date.isoformat(),
         "first_due_date": loan.first_due_date.isoformat(), "emi_amount": str(loan.emi_amount),
         "processing_fee": str(loan.processing_fee), "apportion_mode": loan.apportion_mode,
         "loan_amount": str(loan.loan_amount) if loan.loan_amount is not None else None,
         "last_due_date": loan.last_due_date.isoformat() if loan.last_due_date else None,
         "stamp_duty": str(loan.stamp_duty or 0), "document_charges": str(loan.document_charges or 0),
         "insurance_amount": str(loan.insurance_amount or 0), "rsa_charge": str(loan.rsa_charge or 0),
         "bounce_charge": str(loan.bounce_charge or 0),
         "excess_mode": loan.excess_mode, "status": loan.status,
         "migration_cutoff": loan.migration_cutoff.isoformat() if loan.migration_cutoff else None,
         "closed_date": loan.closed_date.isoformat() if loan.closed_date else None}
    groups = master_fields.loan_groups(details)
    if loan.insurance_amount is not None:
        groups.setdefault("Loan", {})["Insurance amount"] = str(loan.insurance_amount)
    d["details_groups"] = groups
    if with_summary:
        d["summary"] = svc.loan_summary(loan)
    return d


class SchedulePreviewIn(BaseModel):
    product_id: int
    principal: Amount
    annual_rate: condecimal(ge=0, le=100) | None = None
    tenure_months: int = Field(ge=1, le=600)
    disbursal_date: date
    first_due_date: date | None = None


@router.post("/loans/preview-schedule")
def preview_schedule(body: SchedulePreviewIn, db: Session = Depends(get_db),
                     _=Depends(current_user)):
    p = _404(db.get(LoanProduct, body.product_id), "Product")
    rate = body.annual_rate if body.annual_rate is not None else p.default_rate
    try:
        rows = generate_schedule(body.principal, rate, body.tenure_months, body.disbursal_date,
                                 body.first_due_date, p.interest_method)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"rate": str(rate), "method": p.interest_method,
            "total_interest": str(sum(r.interest for r in rows)),
            "total_payable": str(sum(r.emi for r in rows)),
            "processing_fee": str((body.principal * p.processing_fee_pct / 100)
                                  .quantize(Decimal("0.01"))),
            "rows": [r.as_dict() for r in rows]}


class LoanIn(SchedulePreviewIn):
    customer_id: int


@router.post("/loans")
def create_loan(body: LoanIn, db: Session = Depends(get_db), user=Depends(can_write)):
    loan = _run(svc.book_loan, db, customer_id=body.customer_id, product_id=body.product_id,
                principal=body.principal, annual_rate=body.annual_rate,
                tenure_months=body.tenure_months, disbursal_date=body.disbursal_date,
                first_due_date=body.first_due_date, user=user.username)
    db.commit()
    return _loan_out(_loan(db, loan.id))


@router.get("/loans")
def list_loans(q: str = "", status: str = "", source: str = "",
               limit: int = Query(50, le=200), offset: int = 0,
               db: Session = Depends(get_db), _=Depends(current_user)):
    query = db.query(Loan).join(Customer)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Loan.loan_number.like(like), Customer.name.like(like),
                                 Customer.mobile.like(like), Loan.external_loan_id.like(like)))
    if status:
        query = query.filter(Loan.status == status)
    if source:
        query = query.filter(Loan.source == source)
    total = query.count()
    rows = (query.options(selectinload(Loan.installments), selectinload(Loan.charges),
                          selectinload(Loan.repayments), selectinload(Loan.customer),
                          selectinload(Loan.product))
            .order_by(Loan.id.desc()).offset(offset).limit(limit).all())
    return {"total": total, "items": [_loan_out(l) for l in rows]}


@router.get("/loans/{loan_id}")
def get_loan(loan_id: int, db: Session = Depends(get_db), _=Depends(current_user)):
    return _loan_out(_loan(db, loan_id))


@router.get("/loans/{loan_id}/schedule")
def get_schedule(loan_id: int, db: Session = Depends(get_db), _=Depends(current_user)):
    loan = _loan(db, loan_id)
    today = date.today()
    out = []
    for i in loan.installments:
        st = i.status
        some_paid = (i.principal_paid + i.interest_paid) > 0
        if st == "DUE" and i.due_date < today:
            st = "PARTLY PAID" if some_paid else "OVERDUE"
        elif st == "DUE" and i.due_date == today:
            st = "PARTLY PAID" if some_paid else "DUE TODAY"
        elif st == "DUE" and some_paid:
            st = "ADVANCE PAID"
        out.append({"id": i.id, "installment_no": i.installment_no,
                    "due_date": i.due_date.isoformat(), "opening_balance": str(i.opening_balance),
                    "principal_due": str(i.principal_due), "interest_due": str(i.interest_due),
                    "emi": str(i.principal_due + i.interest_due),
                    "principal_paid": str(i.principal_paid), "interest_paid": str(i.interest_paid),
                    "outstanding": str(i.principal_os + i.interest_os),
                    "migrated_paid": str(i.opening_principal_paid + i.opening_interest_paid),
                    "status": st})
    return out


@router.get("/loans/{loan_id}/repayments")
def get_repayments(loan_id: int, db: Session = Depends(get_db), _=Depends(current_user)):
    loan = _loan(db, loan_id)
    inst_no = {i.id: i.installment_no for i in loan.installments}
    ctype = {c.id: c.charge_type for c in loan.charges}
    allocs = db.query(Allocation).filter(Allocation.loan_id == loan.id).all()
    by_rep: dict = {}
    for a in allocs:
        by_rep.setdefault(a.repayment_id, []).append(a)
    out = []
    for r in sorted(loan.repayments, key=lambda r: (r.payment_date, r.id), reverse=True):
        lines = by_rep.get(r.id, [])
        t = {"INTEREST": Decimal("0.00"), "PRINCIPAL": Decimal("0.00"), "CHARGE": Decimal("0.00")}
        for a in lines:
            t[a.component] += a.amount
        out.append({"id": r.id, "payment_date": r.payment_date.isoformat(),
                    "amount": str(r.amount), "mode": r.mode, "reference": r.reference,
                    "status": r.status, "purpose": r.purpose, "historical": r.is_historical,
                    "reversal_reason": r.reversal_reason, "created_by": r.created_by,
                    "interest": str(t["INTEREST"]), "principal": str(t["PRINCIPAL"]),
                    "charges": str(t["CHARGE"]),
                    "allocations": [{"component": a.component, "amount": str(a.amount),
                                     "applied_date": a.applied_date.isoformat(),
                                     "from_excess": a.from_excess,
                                     "target": f"EMI {inst_no.get(a.installment_id)}"
                                     if a.installment_id else
                                     f"{ctype.get(a.charge_id)} #{a.charge_id}"}
                                    for a in sorted(lines, key=lambda a: a.id or 0)]})
    return out


@router.get("/loans/{loan_id}/charges")
def get_charges(loan_id: int, db: Session = Depends(get_db), _=Depends(current_user)):
    loan = _loan(db, loan_id)
    return [{"id": c.id, "charge_type": c.charge_type, "charge_date": c.charge_date.isoformat(),
             "amount": str(c.amount), "paid": str(c.paid), "waived": str(c.waived),
             "outstanding": str(c.outstanding), "description": c.description}
            for c in loan.charges]


class PaymentIn(BaseModel):
    amount: Amount
    payment_date: date
    mode: Literal["NEFT", "RTGS", "IMPS", "UPI", "NACH", "CASH", "CHEQUE", "OTHER"] = "NEFT"
    reference: str | None = Field(None, max_length=64)


@router.post("/loans/{loan_id}/repayments/preview")
def preview_payment(loan_id: int, body: PaymentIn, db: Session = Depends(get_db),
                    _=Depends(current_user)):
    return _run(svc.preview_payment, _loan(db, loan_id), body.amount, body.payment_date)


@router.post("/loans/{loan_id}/repayments")
def post_payment(loan_id: int, body: PaymentIn, db: Session = Depends(get_db),
                 user=Depends(can_write)):
    loan = _loan(db, loan_id)
    rep = _run(svc.post_repayment, db, loan, body.amount, body.payment_date, body.mode,
               body.reference, user.username)
    db.commit()
    return {"repayment_id": rep.id, "loan": _loan_out(_loan(db, loan_id))}


class ReverseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)
    bounce: bool = False


@router.post("/repayments/{rep_id}/reverse")
def reverse_payment(rep_id: int, body: ReverseIn, db: Session = Depends(get_db),
                    user=Depends(can_write)):
    rep = _404(db.get(Repayment, rep_id), "Payment")
    _run(svc.reverse_repayment, db, rep, body.reason, body.bounce, user.username)
    db.commit()
    return {"ok": True}


class ChargeIn(BaseModel):
    charge_type: str = Field(min_length=2, max_length=24)
    amount: Amount
    charge_date: date
    description: str | None = None


@router.post("/loans/{loan_id}/charges")
def create_charge(loan_id: int, body: ChargeIn, db: Session = Depends(get_db),
                  user=Depends(can_write)):
    loan = _loan(db, loan_id)
    c = _run(svc.add_charge, db, loan, body.charge_type, body.amount, body.charge_date,
             body.description, user.username)
    db.commit()
    return {"id": c.id}


class WaiveIn(BaseModel):
    amount: Amount
    reason: str = Field(min_length=3)


@router.post("/charges/{charge_id}/waive")
def waive(charge_id: int, body: WaiveIn, db: Session = Depends(get_db), user=Depends(admin_only)):
    c = _404(db.get(Charge, charge_id), "Charge")
    _run(svc.waive_charge, db, c, body.amount, body.reason, user.username)
    db.commit()
    return {"ok": True}


@router.get("/loans/{loan_id}/foreclosure-quote")
def fc_quote(loan_id: int, on: date | None = None, db: Session = Depends(get_db),
             _=Depends(current_user)):
    return svc.foreclosure_quote(_loan(db, loan_id), on or date.today())


class ForecloseIn(PaymentIn):
    pass


@router.post("/loans/{loan_id}/foreclose")
def do_foreclose(loan_id: int, body: ForecloseIn, db: Session = Depends(get_db),
                 user=Depends(can_write)):
    loan = _loan(db, loan_id)
    res = _run(svc.foreclose, db, loan, body.payment_date, body.amount, body.mode,
               body.reference, user.username)
    db.commit()
    return res


# ------------------------------------------------------------------ operations

@router.post("/eod/late-fees")
def eod_late_fees(as_of: date | None = None, db: Session = Depends(get_db),
                  user=Depends(admin_only)):
    res = svc.run_late_fees(db, as_of, user.username)
    db.commit()
    return res


@router.post("/import/m2p")
async def m2p_import(loans: UploadFile = File(...), schedule: UploadFile = File(...),
                     receipts: UploadFile | None = File(None),
                     charges: UploadFile | None = File(None),
                     cutoff: date = Form(DEFAULT_CUTOFF), dry_run: bool = Form(True),
                     db: Session = Depends(get_db), user=Depends(admin_only)):
    return import_m2p(db, await loans.read(), await schedule.read(),
                      await receipts.read() if receipts else None,
                      await charges.read() if charges else None,
                      cutoff=cutoff, dry_run=dry_run, user=user.username)


@router.post("/import/loan-master")
async def loan_master_import(loans: UploadFile = File(...), dry_run: bool = Form(True),
                             db: Session = Depends(get_db), user=Depends(admin_only)):
    return import_loan_master(db, await loans.read(), dry_run=dry_run, user=user.username)


@router.post("/import/transactions")
async def transactions_import(transactions: UploadFile = File(...), dry_run: bool = Form(True),
                              db: Session = Depends(get_db), user=Depends(admin_only)):
    return transactions_service.import_transactions(db, await transactions.read(), dry_run=dry_run,
                                                    user=user.username)


@router.post("/import/rps")
async def rps_import(rps: UploadFile = File(...), dry_run: bool = Form(True),
                     db: Session = Depends(get_db), user=Depends(admin_only)):
    return import_rps(db, await rps.read(), dry_run=dry_run, user=user.username)


@router.post("/import/schedule")
async def schedule_import(schedule: UploadFile = File(...), cutoff: date = Form(DEFAULT_CUTOFF),
                          dry_run: bool = Form(True), db: Session = Depends(get_db),
                          user=Depends(admin_only)):
    return import_schedule(db, await schedule.read(), cutoff=cutoff, dry_run=dry_run,
                           user=user.username)


@router.post("/import/receipts")
async def receipts_import(receipts: UploadFile = File(...), cutoff: date = Form(DEFAULT_CUTOFF),
                          dry_run: bool = Form(True), db: Session = Depends(get_db),
                          user=Depends(admin_only)):
    return import_receipts(db, await receipts.read(), cutoff=cutoff, dry_run=dry_run,
                           user=user.username)


@router.post("/import/charges")
async def charges_import(charges: UploadFile = File(...), cutoff: date = Form(DEFAULT_CUTOFF),
                         dry_run: bool = Form(True), db: Session = Depends(get_db),
                         user=Depends(admin_only)):
    return import_charges(db, await charges.read(), cutoff=cutoff, dry_run=dry_run,
                          user=user.username)


# ------------------------------------------------------------------ exports and clean-up

def _csv_response(text: str, filename: str):
    return Response(content=text, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/columns")
def export_columns(db: Session = Depends(get_db), _=Depends(reports_access)):
    return {"loan_master": [{"key": k, "label": v} for k, v in exports.loan_master_columns(db)],
            "rps": [{"key": k, "label": v} for k, v in exports.RPS_COLUMNS]}


@router.get("/export/loan-master")
def export_loan_master(columns: str = Query(..., min_length=1), db: Session = Depends(get_db),
                       _=Depends(reports_access)):
    try:
        text = exports.loan_master_csv(db, [c for c in columns.split(",") if c])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _csv_response(text, "loan_master.csv")


@router.get("/export/rps")
def export_rps(columns: str = Query(..., min_length=1), db: Session = Depends(get_db),
               _=Depends(reports_access)):
    try:
        text = exports.rps_csv(db, [c for c in columns.split(",") if c])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _csv_response(text, "rps.csv")


class ClearIn(BaseModel):
    confirm: str


CLEAR_PHRASE = "DELETE ALL LOAN DATA"


@router.post("/admin/clear-loan-data")
def clear_loan_data(body: ClearIn, db: Session = Depends(get_db), user=Depends(admin_only)):
    """Testing aid: removes every loan, its schedule, payments, charges, RPS rows and customers.
    Users, products and the audit log are kept. Needs the exact confirmation phrase."""
    if body.confirm != CLEAR_PHRASE:
        raise HTTPException(400, f"Type {CLEAR_PHRASE} to confirm")
    counts = {}
    for name, model in [("allocations", Allocation), ("charges", Charge), ("repayments", Repayment),
                        ("installments", Installment), ("rps_rows", RpsRow), ("loans", Loan),
                        ("customers", Customer)]:
        counts[name] = db.query(model).delete(synchronize_session=False)
    svc.audit(db, user.username, "CLEAR_LOAN_DATA", "system", "all", counts)
    db.commit()
    return counts


class RpsGenerateIn(BaseModel):
    loan_numbers: list[str] | None = None
    replace: bool = False


@router.post("/rps/generate")
def rps_generate(body: RpsGenerateIn, db: Session = Depends(get_db), user=Depends(can_write)):
    """Generates the RPS for loans from their shared EMI. Loans that already have RPS rows are
    skipped unless replace is true (uploaded rows are then replaced too)."""
    q = db.query(Loan)
    if body.loan_numbers:
        q = q.filter(Loan.loan_number.in_(body.loan_numbers))
    result = {"loans_generated": 0, "rows": 0, "skipped": [], "errors": [], "warnings": []}
    for loan in q.order_by(Loan.id).all():
        exists = db.query(RpsRow.id).filter(RpsRow.loan_number == loan.loan_number).first() is not None
        if exists and not body.replace:
            result["skipped"].append(loan.loan_number)
            continue
        try:
            rows, warnings = rps_service.generate_rows(loan)
        except ValueError as e:
            result["errors"].append({"loan_id": loan.loan_number, "message": str(e)})
            continue
        db.query(RpsRow).filter(RpsRow.loan_number == loan.loan_number).delete(synchronize_session=False)
        for r in rows:
            db.add(RpsRow(loan_number=loan.loan_number, row_no=r["installment_no"],
                          installment_no=r["installment_no"], due_date=r["due_date"],
                          emi_amount=r["emi_amount"], principal_component=r["principal_component"],
                          interest_component=r["interest_component"], source="GENERATED",
                          payload=json.dumps({"generated": True}, default=str), created_by=user.username))
        result["loans_generated"] += 1
        result["rows"] += len(rows)
        result["warnings"] += [{"loan_id": loan.loan_number, "message": w} for w in warnings]
    svc.audit(db, user.username, "RPS_GENERATE", "system", "rps",
              {"loans": result["loans_generated"], "rows": result["rows"]})
    db.commit()
    return result


def _product_fee(loan: Loan):
    prod = loan.product
    return (prod.late_fee, prod.grace_days) if prod else (Decimal("0"), 0)


def _late_charge_figures(rows, today) -> dict:
    z = Decimal("0")
    charged = sum((r.actual_charge or z for r in rows), z)
    paid = sum((r.actual_charge_paid or z for r in rows), z)
    overdue = sum(((r.actual_charge or z) - (r.actual_charge_paid or z) for r in rows
                   if r.due_date and r.due_date <= today), z)
    return {"charged": str(charged), "paid": str(paid), "waived": "0",
            "outstanding": str(charged - paid), "overdue": str(overdue)}


@router.get("/loans/{lid}/position")
def loan_position(lid: int, as_of: date | None = Query(None), db: Session = Depends(get_db),
                  _=Depends(current_user)):
    """Charged, paid, outstanding and overdue for principal, interest, penalties and disbursement
    charges. Principal, interest and penalties come from the RPS. Overdue means unpaid on a due
    date that has passed. Disbursement charges have no paid figure yet: payments are not uploaded."""
    loan = _404(db.get(Loan, lid), "Loan")
    today = as_of or date.today()  # overdue and DPD are worked out as of this date
    rows, excess = state_as_of(db, loan, today)
    z = Decimal("0")

    def line(due_key, paid_key, waived_key=None):
        charged = paid = waived = overdue = z
        for r in rows:
            due = getattr(r, due_key) or z
            done = getattr(r, paid_key) or z
            w = (getattr(r, waived_key) or z) if waived_key else z
            charged += due
            paid += done
            waived += w
            if r.due_date and r.due_date <= today:
                overdue += due - done - w
        return charged, paid, waived, charged - paid - waived, overdue

    def out(charged, paid, waived, outstanding, overdue):
        return {"charged": str(charged), "paid": str(paid), "waived": str(waived),
                "outstanding": str(outstanding), "overdue": str(overdue)}

    p = line("principal_component", "principal_paid")
    i = line("interest_component", "interest_paid")
    old = line("penalty_due", "penalty_paid", "penalty_waived")
    # late charges this app adds for instalments overdue more than the grace days
    late = _late_charge_figures(rows, today)
    disb = (loan.processing_fee or z) + (loan.stamp_duty or z) + (loan.document_charges or z) \
        + (loan.insurance_amount or z) + (loan.rsa_charge or z)
    # DPD: days since the earliest due date with an unpaid EMI (0 when nothing is overdue)
    def unpaid(r):
        # EMI only (principal and interest); unpaid charges do not make the loan overdue for DPD
        return ((r.principal_component or z) - (r.principal_paid or z)
                + (r.interest_component or z) - (r.interest_paid or z))
    # DPD counts the due date itself: 5 Apr to 30 Apr is 26 days
    overdue_dues = [r.due_date for r in rows if r.due_date and r.due_date <= today and unpaid(r) > 0]
    dpd = (today - min(overdue_dues)).days + 1 if overdue_dues else 0
    return {
        "as_of": today.isoformat(),
        "dpd": dpd,
        "dpd_bucket": dpd_bucket(dpd),
        "oldest_unpaid_due": min(overdue_dues).isoformat() if overdue_dues else None,
        "principal": out(*p),
        "interest": out(*i),
        "late_charges": late,
        "old_charges": out(*old),
        "disbursement_charges": {"charged": str(disb), "paid": None, "waived": None,
                                 "outstanding": None, "overdue": None},
        "excess": str(excess),
        "has_rps": bool(rows),
    }


@router.get("/loans/{lid}/foreclosure")
def foreclosure_quote(lid: int, as_of: date | None = Query(None), db: Session = Depends(get_db),
                      _=Depends(current_user)):
    """Foreclosure quote as of a date:
    principal outstanding (all unpaid principal); interest = unpaid interest of instalments due
    before this month, plus this month's instalment interest (half before the 20th, full from the
    20th); foreclosure charges (2% of principal outstanding if disbursed on or before June 2025,
    otherwise 5%); GST 18% on those charges; bounce charges = the loan's bounce charge plus the
    unpaid late charges on instalments due on or before the date; less excess. The fee is 0."""
    from decimal import ROUND_HALF_UP
    loan = _404(db.get(Loan, lid), "Loan")
    today = as_of or date.today()
    rows, excess = state_as_of(db, loan, today)
    z = Decimal("0")

    def q(x):
        return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    month_start = today.replace(day=1)
    pos = sum((max((r.principal_component or z) - (r.principal_paid or z), z) for r in rows), z)
    earlier = sum((max((r.interest_component or z) - (r.interest_paid or z), z)
                   for r in rows if r.due_date and r.due_date < month_start), z)
    this_month = sum((max((r.interest_component or z) - (r.interest_paid or z), z)
                      for r in rows if r.due_date and month_start <= r.due_date <= today), z)
    if today.day >= 20:
        share, share_note = Decimal("1"), "full month from the 20th"
    else:
        share, share_note = Decimal("0.5"), "half month, before the 20th"
    interest = earlier + this_month * share
    late = _late_charge_figures(rows, today)
    late_unpaid = Decimal(late["overdue"])
    fcl_pct = Decimal("2") if loan.disbursal_date <= date(2025, 6, 30) else Decimal("5")
    fcl = pos * fcl_pct / Decimal(100)
    gst = fcl * Decimal("0.18")
    bounce = (loan.bounce_charge or z) + late_unpaid
    total = pos + interest + fcl + gst + bounce - excess
    return {
        "as_of": today.isoformat(),
        "principal_outstanding": str(q(pos)),
        "interest": str(q(interest)),
        "interest_note": f"unpaid interest before {month_start.strftime('%b %Y')} plus {share_note}",
        "fcl_percent": str(fcl_pct),
        "fcl_charges": str(q(fcl)),
        "gst": str(q(gst)),
        "fcl_amount": str(Decimal(pos + interest + fcl + gst).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "bounce_charges": str(q(bounce)),
        "excess": str(q(excess)),
        "foreclosure_fee": "0.00",
        "total": str(Decimal(total).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "refund_due": str(q(-total)) if total < 0 else "0.00",
    }


@router.post("/jobs/import/{kind}")
async def start_import_job(kind: str, file: UploadFile = File(...), dry_run: bool = Form(True),
                           db: Session = Depends(get_db), user=Depends(admin_only)):
    """Starts an import in the background and returns a job id. The page reads its progress from
    /jobs/{id}."""
    from .services import jobs
    from .services.m2p_import import import_loan_master as _loan_master, import_rps as _rps
    from .services.transactions import import_transactions as _transactions
    fns = {"loan-master": _loan_master, "rps": _rps, "transactions": _transactions}
    if kind not in fns:
        raise HTTPException(404, "Unknown import")
    try:
        jid = jobs.start(kind, fns[kind], await file.read(), dry_run=dry_run, user=user.username)
    except jobs.JobBusy:
        raise HTTPException(409, "An import of this type is already running. Wait for it to finish.")
    return {"job_id": jid}


@router.get("/jobs/{jid}")
def job_status(jid: str, _=Depends(admin_only)):
    from .services import jobs
    job = jobs.get(jid)
    if job is None:
        raise HTTPException(404, "No such job (it may have finished long ago)")
    return job


@router.get("/loans/{lid}/foreclosure.pdf")
def foreclosure_pdf(lid: int, as_of: date | None = Query(None), db: Session = Depends(get_db),
                    _=Depends(current_user)):
    """The foreclosure quote as a PDF, with the same figures as the quote on the loan page."""
    from .services.reports import fcl_pdf
    loan = _404(db.get(Loan, lid), "Loan")
    q = foreclosure_quote(lid, as_of, db, None)
    quote_date = date.fromisoformat(q["as_of"])
    data = fcl_pdf(loan, loan.customer, q, quote_date)
    filename = f"FCL{loan.loan_number}{quote_date.isoformat()}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/templates/{name}")
def download_template(name: str, _=Depends(current_user)):
    """A blank example file for an upload: loan_master, rps or transactions."""
    from pathlib import Path
    if name not in {"loan_master", "rps", "transactions"}:
        raise HTTPException(404, "Unknown template")
    ext = "tsv" if name == "loan_master" else "csv"  # the loan master is tab-separated
    path = Path(__file__).resolve().parent.parent / "sample_data" / "templates" / f"{name}_template.{ext}"
    media = "text/tab-separated-values" if ext == "tsv" else "text/csv"
    return Response(content=path.read_bytes(), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}_template.{ext}"'})


@router.get("/reports/dues.xlsx")
def dues_report(as_of: date | None = Query(None), db: Session = Depends(get_db), _=Depends(reports_access)):
    """Dues as of a date, one row per loan, with a totals row. Figures come from the loan page."""
    from .services.reports import DUES_COLUMNS, dues_xlsx
    from decimal import Decimal as D
    today = as_of or date.today()
    rows = []
    for loan in db.query(Loan).order_by(Loan.loan_number).all():
        pos = loan_position(loan.id, today, db, None)
        p, i, late = pos["principal"], pos["interest"], pos["late_charges"]
        overdue_total = D(p["overdue"]) + D(i["overdue"]) + D(late["overdue"])
        outstanding_total = D(p["outstanding"]) + D(i["outstanding"]) + D(late["outstanding"])
        rows.append({
            "Account number": loan.loan_number,
            "Customer name": loan.customer.name if loan.customer else "",
            "Mobile number": (loan.customer.mobile or "") if loan.customer else "",
            "Principal outstanding": D(p["outstanding"]), "Interest outstanding": D(i["outstanding"]),
            "Overdue principal": D(p["overdue"]), "Overdue interest": D(i["overdue"]),
            "Charges due (unpaid actual charges)": D(late["outstanding"]),
            "Total overdue": overdue_total, "Total outstanding": outstanding_total,
            "DPD": pos["dpd"], "DPD bucket": pos["dpd_bucket"], "Excess held": D(pos["excess"]),
        })
    data = dues_xlsx(rows, today)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="dues_{today.isoformat()}.xlsx"'})


@router.get("/loans/{lid}/transactions")
def loan_transactions(lid: int, db: Session = Depends(get_db), _=Depends(current_user)):
    loan = _404(db.get(Loan, lid), "Loan")
    rows = (db.query(RpsTransaction).filter(RpsTransaction.loan_number == loan.loan_number)
            .order_by(RpsTransaction.txn_date, RpsTransaction.id).all())
    return [{"id": t.id, "txn_date": t.txn_date.isoformat(), "amount": str(t.amount),
             "mode": t.mode, "reference": t.reference,
             "interest_applied": str(t.interest_applied or 0), "principal_applied": str(t.principal_applied or 0),
             "charges_applied": str(t.charges_applied or 0), "excess_held": str(t.excess_held or 0)}
            for t in rows]


@router.get("/loans/{lid}/rps")
def loan_rps(lid: int, db: Session = Depends(get_db), _=Depends(current_user)):
    loan = _404(db.get(Loan, lid), "Loan")
    # the state today, the same figures the position and quote use
    rows, _ = state_as_of(db, loan, date.today())
    def amt(v):
        return str(v) if v is not None else None
    return [{"installment_no": r.installment_no,
             "due_date": r.due_date.isoformat() if r.due_date else None,
             "paid_date": r.paid_date.isoformat() if r.paid_date else None,
             "emi": amt(r.emi_amount), "principal_due": amt(r.principal_component),
             "principal_paid": amt(r.principal_paid), "interest_due": amt(r.interest_component),
             "interest_paid": amt(r.interest_paid), "closing_balance": amt(r.closing_balance),
             "penalty_due": amt(r.penalty_due), "penalty_paid": amt(r.penalty_paid),
             "penalty_waived": amt(r.penalty_waived), "late_charge": amt(r.actual_charge),
             "late_charge_paid": amt(r.actual_charge_paid), "source": r.source} for r in rows]


@router.get("/reports/portfolio")
def portfolio(db: Session = Depends(get_db), _=Depends(current_user)):
    today = date.today()
    loans = (db.query(Loan).options(selectinload(Loan.installments), selectinload(Loan.charges),
                                    selectinload(Loan.repayments)).all())
    buckets = {b: {"count": 0, "pos": Decimal(0)} for b in
               ["Current", "SMA-0 (1-30)", "SMA-1 (31-60)", "SMA-2 (61-90)", "NPA (90+)"]}
    by_source = {}
    status_count = {}
    pos_total = overdue_total = Decimal(0)
    for l in loans:
        status_count[l.status] = status_count.get(l.status, 0) + 1
        if l.status != "ACTIVE":
            continue
        s = svc.loan_summary(l, today)
        pos = Decimal(s["principal_outstanding"])
        b = buckets[dpd_bucket(s["dpd"])]
        b["count"] += 1
        b["pos"] += pos
        pos_total += pos
        overdue_total += Decimal(s["total_overdue"])
        src = by_source.setdefault(l.source, {"count": 0, "pos": Decimal(0)})
        src["count"] += 1
        src["pos"] += pos
    month_start = today.replace(day=1)
    coll = (db.query(func.coalesce(func.sum(Repayment.amount), 0))
            .filter(Repayment.status == "POSTED", Repayment.payment_date >= month_start)).scalar()
    due_month = (db.query(func.coalesce(func.sum(Installment.principal_due + Installment.interest_due), 0))
                 .join(Loan).filter(Loan.status == "ACTIVE", Installment.status != "CANCELLED",
                                    Installment.due_date >= month_start,
                                    Installment.due_date <= today)).scalar()
    last_upload = db.query(func.max(RpsTransaction.created_at)).scalar()
    last_payment = db.query(func.max(RpsTransaction.txn_date)).scalar()
    loans_imported = db.query(func.count(Loan.id)).filter(Loan.external_loan_id.isnot(None)).scalar()
    rps_imported = db.query(func.count(RpsRow.id)).scalar()
    return {"as_of": today.isoformat(), "active_loans": status_count.get("ACTIVE", 0),
            "last_transaction_upload": last_upload.date().isoformat() if last_upload else None,
            "last_transaction_payment_date": last_payment.isoformat() if last_payment else None,
            "loans_imported": loans_imported, "rps_rows_imported": rps_imported,
            "status_count": status_count, "principal_outstanding": str(pos_total),
            "total_overdue": str(overdue_total), "collections_this_month": str(coll),
            "demand_this_month": str(due_month),
            "dpd_buckets": [{"bucket": k, "count": v["count"], "pos": str(v["pos"])}
                            for k, v in buckets.items()],
            "by_source": [{"source": k, "count": v["count"], "pos": str(v["pos"])}
                          for k, v in by_source.items()]}


@router.get("/audit")
def audit_log(limit: int = Query(100, le=500), db: Session = Depends(get_db),
              _=Depends(admin_only)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"at": a.at.isoformat() if a.at else None, "user": a.username, "action": a.action,
             "entity": a.entity, "entity_id": a.entity_id, "detail": a.detail} for a in rows]
