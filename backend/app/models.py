from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (String, Integer, Numeric, Date, DateTime, ForeignKey, Boolean,
                        Text, UniqueConstraint, Index, LargeBinary, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Money = Numeric(18, 2)
Rate = Numeric(9, 4)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="OPS")  # ADMIN / OPS / VIEWER
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LoanProduct(Base):
    __tablename__ = "loan_products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    interest_method: Mapped[str] = mapped_column(String(16), default="REDUCING")
    default_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("0"))
    min_tenure: Mapped[int] = mapped_column(Integer, default=1)
    max_tenure: Mapped[int] = mapped_column(Integer, default=60)
    min_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    max_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("100000000"))
    apportion_mode: Mapped[str] = mapped_column(String(20), default="HEAD_WISE")
    excess_mode: Mapped[str] = mapped_column(String(16), default="HOLD")
    late_fee: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    grace_days: Mapped[int] = mapped_column(Integer, default=0)
    bounce_charge: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    foreclosure_fee_pct: Mapped[Decimal] = mapped_column(Rate, default=Decimal("0"))
    processing_fee_pct: Mapped[Decimal] = mapped_column(Rate, default=Decimal("0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    loans: Mapped[list["Loan"]] = relationship(back_populates="customer")


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (Index("ix_loans_status", "status"), Index("ix_loans_source", "source"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_number: Mapped[str] = mapped_column(String(40), unique=True)
    source: Mapped[str] = mapped_column(String(10), default="NATIVE")  # NATIVE / M2P
    external_loan_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("loan_products.id"), nullable=True)
    principal: Mapped[Decimal] = mapped_column(Money)
    annual_rate: Mapped[Decimal] = mapped_column(Rate)
    tenure_months: Mapped[int] = mapped_column(Integer)
    interest_method: Mapped[str] = mapped_column(String(16), default="REDUCING")
    disbursal_date: Mapped[date] = mapped_column(Date)
    first_due_date: Mapped[date] = mapped_column(Date)
    emi_amount: Mapped[Decimal] = mapped_column(Money)
    processing_fee: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    apportion_mode: Mapped[str] = mapped_column(String(20), default="HEAD_WISE")
    excess_mode: Mapped[str] = mapped_column(String(16), default="HOLD")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE/CLOSED/FORECLOSED/WRITTEN_OFF
    excess_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    opening_excess: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    migration_cutoff: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # static loan master parameters (as shared in the loan master file)
    loan_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    last_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stamp_duty: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    document_charges: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    insurance_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    rsa_charge: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    bounce_charge: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # every loan master column, as uploaded (JSON)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer: Mapped[Customer] = relationship(back_populates="loans")
    product: Mapped[LoanProduct | None] = relationship()
    installments: Mapped[list["Installment"]] = relationship(
        back_populates="loan", order_by="Installment.installment_no", cascade="all, delete-orphan")
    charges: Mapped[list["Charge"]] = relationship(
        back_populates="loan", order_by="Charge.charge_date", cascade="all, delete-orphan")
    repayments: Mapped[list["Repayment"]] = relationship(
        back_populates="loan", order_by="Repayment.payment_date", cascade="all, delete-orphan")


class Installment(Base):
    __tablename__ = "installments"
    __table_args__ = (UniqueConstraint("loan_id", "installment_no"), Index("ix_inst_due", "due_date"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    installment_no: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    opening_balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    principal_due: Mapped[Decimal] = mapped_column(Money)
    interest_due: Mapped[Decimal] = mapped_column(Money)
    # paid as at migration cutoff (M2P loans); 0 for native loans
    opening_principal_paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    opening_interest_paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    # derived by replaying allocations on top of the opening amounts
    principal_paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    interest_paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(12), default="DUE")  # DUE / PAID / CANCELLED

    loan: Mapped[Loan] = relationship(back_populates="installments")

    @property
    def principal_os(self) -> Decimal:
        return self.principal_due - self.principal_paid

    @property
    def interest_os(self) -> Decimal:
        return self.interest_due - self.interest_paid


class Charge(Base):
    __tablename__ = "charges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    installment_id: Mapped[int | None] = mapped_column(ForeignKey("installments.id"), nullable=True)
    charge_type: Mapped[str] = mapped_column(String(24))  # LATE_FEE/BOUNCE/FORECLOSURE/OTHER/...
    charge_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    opening_paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    paid: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    waived: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    loan: Mapped[Loan] = relationship(back_populates="charges")

    @property
    def outstanding(self) -> Decimal:
        return self.amount - self.paid - self.waived


class Repayment(Base):
    __tablename__ = "repayments"
    __table_args__ = (Index("ix_rep_date", "payment_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    amount: Mapped[Decimal] = mapped_column(Money)
    payment_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(16), default="NEFT")
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="POSTED")  # POSTED / REVERSED
    # historical M2P receipts: their effect is already inside the opening paid amounts,
    # so they are shown in history but never re-apportioned
    is_historical: Mapped[bool] = mapped_column(Boolean, default=False)
    purpose: Mapped[str] = mapped_column(String(16), default="REPAYMENT")  # REPAYMENT / FORECLOSURE
    reversal_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    loan: Mapped[Loan] = relationship(back_populates="repayments")
    allocations: Mapped[list["Allocation"]] = relationship(
        back_populates="repayment", cascade="all, delete-orphan")


class Allocation(Base):
    __tablename__ = "allocations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    repayment_id: Mapped[int | None] = mapped_column(ForeignKey("repayments.id"), nullable=True)
    installment_id: Mapped[int | None] = mapped_column(ForeignKey("installments.id"), nullable=True)
    charge_id: Mapped[int | None] = mapped_column(ForeignKey("charges.id"), nullable=True)
    component: Mapped[str] = mapped_column(String(12))  # INTEREST / PRINCIPAL / CHARGE
    amount: Mapped[Decimal] = mapped_column(Money)
    applied_date: Mapped[date] = mapped_column(Date)
    from_excess: Mapped[bool] = mapped_column(Boolean, default=False)

    repayment: Mapped[Repayment | None] = relationship(back_populates="allocations")


class RpsRow(Base):
    """One row of an uploaded RPS file, stored as-is for book keeping (nothing is recalculated)."""
    __tablename__ = "rps_rows"
    __table_args__ = (Index("ix_rps_rows_loan", "loan_number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_number: Mapped[str] = mapped_column(String(40))
    row_no: Mapped[int] = mapped_column(Integer)
    installment_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    emi_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    principal_component: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    interest_component: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    principal_paid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    interest_paid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    penalty_due: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    penalty_paid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    penalty_waived: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    # late charges this app adds (overdue more than the grace days); old M2P charges stay in penalty_*
    actual_charge: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    actual_charge_paid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    # the paid state as uploaded in the RPS file, before any payment in this app: a past date is
    # rebuilt from these, then the payments dated on or before that date are applied
    base_principal_paid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    base_interest_paid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    base_paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(12), default="UPLOADED")  # UPLOADED / GENERATED
    payload: Mapped[str] = mapped_column(Text)  # JSON of the row's columns as uploaded
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RpsTransaction(Base):
    """A payment uploaded against a loan's RPS. Applied to the RPS rows in date order:
    interest, then principal, then charges, for dues already due on the payment date."""
    __tablename__ = "rps_transactions"
    __table_args__ = (Index("ix_rps_txn_loan", "loan_number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_number: Mapped[str] = mapped_column(String(40))
    txn_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interest_applied: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    principal_applied: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    charges_applied: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    excess_held: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(48))
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class LoanDocument(Base):
    """A file uploaded against a loan (KYC, invoice, agreements, delivery photos ...).
    Kept in the database so it survives moving the app to another server."""
    __tablename__ = "loan_documents"
    __table_args__ = (Index("ix_loan_docs_loan", "loan_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # plain column, no FOREIGN KEY: the RDS app user has no REFERENCES privilege on GFL_DWH.loans
    loan_id: Mapped[int] = mapped_column(Integer)
    doc_type: Mapped[str] = mapped_column(String(32))        # see services/documents.py DOC_TYPES
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)  # name for "Other" documents
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary(length=16_777_215))  # MEDIUMBLOB on MySQL
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
