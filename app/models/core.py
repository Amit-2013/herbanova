from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (String, Numeric, Integer, ForeignKey, DateTime, Date, Boolean, Index,
                        UniqueConstraint, CheckConstraint, JSON, text, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..core.db import Base

MONEY = Numeric(14, 2)   # never float for money
QTY = Numeric(14, 3)
RATE = Numeric(5, 2)


class User(Base):
    """Login account. Role name is kept for history/audit display; authorisation
    resolves through role_id -> Role.permissions (Module Phase 1), falling back to
    the fixed baseline sets when role_id is unset.

    Session revocation: every JWT carries the user's token_version; bumping it
    (password change, admin reset, deactivation) invalidates every older token.
    """
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    # lower-case login id; derived from username on every insert so no code path can forget it
    username_key: Mapped[str | None] = mapped_column(
        String(64), unique=True,
        default=lambda ctx: (ctx.get_current_parameters().get("username") or "").strip().lower() or None)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))                        # display/legacy copy of the role name
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"))  # source of truth for permissions
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reset_password_secondary_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secondary_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The second secret for the guarded database reset. It is deliberately
    # separate from the login and secondary passwords and is never returned.
    reset_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reset_key_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    db_reset_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    db_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Google Authenticator (TOTP) for the Administrator roles. The secret is
    # sealed with APP_SECRET; recovery codes are argon2 hashes and single-use.
    totp_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_last_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    totp_failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    totp_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_recovery_hashes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    role_rel = relationship("Role", foreign_keys=[role_id], lazy="selectin")

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("mrp >= 0", name="ck_mrp_nonneg"),
                      # digits-only is checked by the API (the database check stays
                      # portable so the model can also be created in SQLite)
                      CheckConstraint("hsn IS NULL OR length(hsn) BETWEEN 4 AND 8",
                                      name="ck_product_hsn"),
                      CheckConstraint("reorder_level IS NULL OR reorder_level >= 0",
                                      name="ck_products_reorder_nonneg"),
                      # Names match the migration-created indexes (schema parity).
                      Index("ix_products_status", "status"),
                      Index("ix_products_hsn", "hsn"),
                      Index("ix_products_category", "category"),
                      Index("ix_products_brand", "brand"))
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    pack_size: Mapped[str] = mapped_column(String(40))
    mrp: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Module Phase 3: tax particulars. The HSN is what the rate master is keyed
    # by, and the UQC is what an invoice must print, so both stay optional until
    # the business enters them (no code assumes a rate or a unit).
    hsn: Mapped[str | None] = mapped_column(String(8))
    uqc: Mapped[str | None] = mapped_column(String(3))
    # Grouping and replenishment. Every value is entered by the user: a blank
    # category is reported as uncategorised and a blank reorder level as "not
    # set", never as zero or as an invented grouping.
    category: Mapped[str | None] = mapped_column(String(60))
    brand: Mapped[str | None] = mapped_column(String(60))
    reorder_level: Mapped[Decimal | None] = mapped_column(QTY)

class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # NULL means capacity is not configured; it never means zero.
    capacity_units: Mapped[int | None] = mapped_column(nullable=True)
    capacity_note: Mapped[str | None] = mapped_column(String(40), nullable=True)

class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", "batch_no"),
        CheckConstraint("on_hand >= 0", name="ck_no_negative_stock"),  # DB-level oversell guard
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    batch_no: Mapped[str] = mapped_column(String(40))
    expiry: Mapped[date | None] = mapped_column(Date)
    owner: Mapped[str] = mapped_column(String(20), default="HERBANOVA")  # or MANUFACTURER
    on_hand: Mapped[Decimal] = mapped_column(QTY, default=0)

class StockMovement(Base):
    """Append-only ledger. Corrections = new reversing rows, never UPDATE/DELETE.

    `unit_cost` is the cost captured when the row was written: the purchase
    order rate for a receipt, the product's weighted average for an issue or a
    transfer, and the original issue cost for a return. NULL means the cost was
    not known at the time; an issue in that state carries `cost_source`
    'partial' and its invoice is not presented with a clean cost of goods.
    `invoice_id` attributes an issue or return to the invoice it serves, so a
    sales order with more than one invoice gets a separate cost for each.
    """
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("batch_id", "movement_type", "ref_type", "ref_id",
                         name="uq_movement_idempotency"),  # blocks duplicate receipt posting
        Index("ix_stock_movements_batch_created", "batch_id", "created_at"),
        Index("ix_stock_movements_invoice", "invoice_id"),
        CheckConstraint(
            "cost_source IS NULL OR cost_source IN "
            "('po_receipt','weighted_average','partial','return','uncosted','foc')",
            name="ck_stock_movement_cost_source"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    movement_type: Mapped[str] = mapped_column(String(20))  # receipt|issue|transfer|adjust|return|reversal
    qty_delta: Mapped[Decimal] = mapped_column(QTY)
    ref_type: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[str] = mapped_column(String(40))
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    cost_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PurchaseOrder(Base):
    """Procurement header. Since Module Phase 2 it links to a Supplier record and
    can be received in parts (D8): open -> partially_received -> received, or
    cancelled before any goods arrive. Each receipt posts 'receipt' movements
    keyed to its goods receipt note."""
    __tablename__ = "purchase_orders"
    __table_args__ = (Index("ix_purchase_orders_status_created", "status", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    supplier: Mapped[str] = mapped_column(String(120))          # display snapshot of the supplier name
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|partially_received|received|cancelled
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="po", lazy="selectin", cascade="all, delete-orphan")
    supplier_rel = relationship("Supplier", back_populates="purchase_orders", lazy="selectin")

class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("po_id", "product_id", name="uq_po_line_product"),
        CheckConstraint("qty > 0", name="ck_po_line_qty_positive"),   # never order zero/negative
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_po_line_cost_nonneg"),
        # A line is priced, or it says why it is not. Never neither.
        CheckConstraint("unit_cost IS NOT NULL OR rate_remark IS NOT NULL",
                        name="ck_po_line_cost_or_remark"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    # Null means the cost is not known yet; rate_remark then explains why.
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    rate_remark: Mapped[str | None] = mapped_column(String(30))
    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")

class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    record: Mapped[str] = mapped_column(String(80))
    changes: Mapped[dict | None] = mapped_column(JSON)   # never include secrets
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- sales, credit, approvals

class Distributor(Base):
    __tablename__ = "distributors"
    __table_args__ = (CheckConstraint("credit_limit >= 0", name="ck_credit_limit_nonneg"),
                      CheckConstraint("registration_type IN ('regular','composition','unregistered')",
                                      name="ck_distributor_registration_type"),
                      CheckConstraint("state_code IS NULL OR length(state_code) = 2",
                                      name="ck_distributor_state_code"),
                      CheckConstraint("payment_terms_days IS NULL OR payment_terms_days >= 0",
                                      name="ck_distributor_payment_terms"))
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    territory: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="active")   # active | blocked
    # One vocabulary with the screen and the supplier master (COR-001): the
    # retired "on_hold" value is refused by the API, and no row stores it.
    credit_limit: Mapped[Decimal] = mapped_column(MONEY, default=0)
    # Module Phase 3: the buyer's tax identity. The state code is the place of
    # supply that decides CGST+SGST versus IGST, so it is validated against the
    # GSTIN when one is given.
    gstin: Mapped[str | None] = mapped_column(String(15), unique=True)
    pan: Mapped[str | None] = mapped_column(String(10))
    state_code: Mapped[str | None] = mapped_column(String(2))
    registration_type: Mapped[str] = mapped_column(String(20), default="unregistered")
    billing_address: Mapped[str | None] = mapped_column(String(300))
    shipping_address: Mapped[str | None] = mapped_column(String(300))
    # Module Phase 3 (FR-07 / G-07): contact details, the distributor group a
    # discount slab can target, and the agreed payment terms.
    contact_person: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(150))
    group_name: Mapped[str | None] = mapped_column(String(60))
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)

class SalesOrder(Base):
    """draft -> (pending_approval) -> approved -> dispatched; or cancelled / rejected."""
    __tablename__ = "sales_orders"
    __table_args__ = (Index("ix_sales_orders_status_created", "status", "created_at"),
                      Index("ix_sales_orders_created_at", "created_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    so_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    distributor_id: Mapped[int] = mapped_column(ForeignKey("distributors.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    dispatched_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Stamped when the order becomes approved, whether the checks passed outright
    # or an approver decided it. Null on orders approved before this column.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The date promised to the buyer. Null means no promise was recorded, so no
    # lateness is claimed for that order.
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    lines: Mapped[list["SalesOrderLine"]] = relationship(
        back_populates="order", lazy="selectin", cascade="all, delete-orphan")

class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_so_line_product"),
        CheckConstraint("qty > 0", name="ck_so_line_qty_positive"),
        CheckConstraint("unit_price >= 0", name="ck_so_line_price_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    order: Mapped[SalesOrder] = relationship(back_populates="lines")

class ApprovalRequest(Base):
    """Decision needs a different person from the requester (and, for orders, the
    creator). Since Module Phase 2 only one request may be PENDING per record:
    decided requests stay as history, so a supplier bank-detail change can be
    requested again later without losing the earlier decision."""
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("uq_approval_pending", "record_type", "record_id", unique=True,
              postgresql_where=text("status = 'pending'")),
        Index("ix_approval_status_type", "status", "record_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(30))
    record_id: Mapped[int] = mapped_column()
    reasons: Mapped[list] = mapped_column(JSON)                 # ["credit_limit", "discount"]
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected|withdrawn|cancelled
    # The central approvals queue is generic: record_type names the category
    # (sales_order, invoice_post_billing, hr_leave, hr_od, hr_payroll, ...) and
    # these fields let every category render the same columns.
    request_no: Mapped[str | None] = mapped_column(String(40), index=True)
    document_number: Mapped[str | None] = mapped_column(String(40))
    subject: Mapped[str | None] = mapped_column(String(200))
    requested_dates: Mapped[str | None] = mapped_column(String(80))
    pending_approver_role: Mapped[str | None] = mapped_column(String(40))
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(300))
    detail: Mapped[dict | None] = mapped_column(JSON)


# ---------------------------------------------------------------- leads and follow-ups

class Lead(Base):
    """A prospect with one owner and (while open) a next follow-up date.
    new -> contacted -> qualified -> won | lost. Closed leads have no follow-up."""
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("phone_key", name="uq_lead_phone"),      # same phone cannot be entered twice
        UniqueConstraint("email_key", name="uq_lead_email"),
        CheckConstraint("phone_key IS NOT NULL OR email_key IS NOT NULL", name="ck_lead_has_contact"),
        Index("ix_leads_owner_followup", "owner_id", "next_follow_up"),
        Index("ix_leads_status_followup", "status", "next_follow_up"),
        Index("ix_leads_created_at", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    company: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(150))
    phone_key: Mapped[str | None] = mapped_column(String(20))    # last 10 digits, for duplicate checks
    email_key: Mapped[str | None] = mapped_column(String(150))   # lower-case
    source: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="new")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    next_follow_up: Mapped[date | None] = mapped_column(Date)
    closed_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

class LeadActivity(Base):
    """Append-only history. There is deliberately no update or delete endpoint."""
    __tablename__ = "lead_activities"
    __table_args__ = (Index("ix_lead_activities_lead_created", "lead_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))   # created|note|call|email|meeting|status_change|follow_up_change|owner_change|updated
    summary: Mapped[str] = mapped_column(String(600))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- billing (Module Phase 4)


class Invoice(Base):
    """A tax invoice issued at dispatch. Immutable once created.

    Stores a frozen snapshot of seller, buyer, lines and tax so later master
    changes cannot alter an issued document (FR-14)."""
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("invoice_number", "financial_year", name="uq_invoice_number_fy"),
        CheckConstraint("status IN ('issued','cancelled')", name="ck_invoice_status"),
        CheckConstraint("payment_terms_days IS NULL OR payment_terms_days >= 0",
                        name="ck_invoice_payment_terms"),
        Index("ix_invoices_invoice_date", "invoice_date"),
        Index("ix_invoices_due_date", "due_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(16), index=True)
    financial_year: Mapped[str] = mapped_column(String(9))  # e.g. 2026-27
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    distributor_id: Mapped[int] = mapped_column(ForeignKey("distributors.id"))
    status: Mapped[str] = mapped_column(String(20), default="issued")
    invoice_date: Mapped[date] = mapped_column(Date)
    place_of_supply_state_code: Mapped[str] = mapped_column(String(2))
    place_of_supply_kind: Mapped[str] = mapped_column(String(10))  # intra|inter
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    # seller snapshot
    seller_legal_name: Mapped[str] = mapped_column(String(200))
    seller_gstin: Mapped[str | None] = mapped_column(String(15))
    seller_pan: Mapped[str | None] = mapped_column(String(10))
    seller_state_code: Mapped[str | None] = mapped_column(String(2))
    seller_address_line1: Mapped[str | None] = mapped_column(String(200))
    seller_address_line2: Mapped[str | None] = mapped_column(String(200))
    seller_city: Mapped[str | None] = mapped_column(String(100))
    seller_pincode: Mapped[str | None] = mapped_column(String(6))
    # buyer snapshot
    buyer_name: Mapped[str] = mapped_column(String(150))
    buyer_gstin: Mapped[str | None] = mapped_column(String(15))
    buyer_pan: Mapped[str | None] = mapped_column(String(10))
    buyer_state_code: Mapped[str | None] = mapped_column(String(2))
    buyer_address_line1: Mapped[str | None] = mapped_column(String(300))
    buyer_address_line2: Mapped[str | None] = mapped_column(String(300))
    # totals
    gross_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    discount_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    igst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cess_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    tax_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    round_off: Mapped[Decimal] = mapped_column(MONEY, default=0)
    grand_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    amount_in_words: Mapped[str | None] = mapped_column(String(300))
    copy_designation: Mapped[str] = mapped_column(String(20), default="ORIGINAL")
    notes: Mapped[list | None] = mapped_column(JSON)
    # Delivery challan and e-way bill details (FR-14). These describe the
    # movement of the goods rather than the value of the supply, so they are
    # recorded after issue and are not part of the frozen financial snapshot.
    delivery_challan_number: Mapped[str | None] = mapped_column(String(30))
    vehicle_number: Mapped[str | None] = mapped_column(String(20))
    transporter_name: Mapped[str | None] = mapped_column(String(120))
    eway_bill_number: Mapped[str | None] = mapped_column(String(30))
    eway_bill_date: Mapped[date | None] = mapped_column(Date)
    # Payment terms are copied from the distributor when the invoice is issued,
    # not read from the master later, so a term change cannot rewrite the due
    # date of a document already sent to the buyer (GAP-A04).
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    due_date: Mapped[date | None] = mapped_column(Date)
    issued_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", lazy="selectin", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_invoice_line_qty_positive"),
        CheckConstraint("unit_price >= 0", name="ck_invoice_line_price_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    sku: Mapped[str] = mapped_column(String(40))
    product_name: Mapped[str] = mapped_column(String(200))
    hsn: Mapped[str | None] = mapped_column(String(8))
    uqc: Mapped[str | None] = mapped_column(String(3))
    qty: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    mrp: Mapped[Decimal] = mapped_column(MONEY)
    discount_percent: Mapped[Decimal] = mapped_column(RATE)
    discount_amount: Mapped[Decimal] = mapped_column(MONEY)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY)
    cgst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    sgst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    igst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    cess_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    igst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cess_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    expiry: Mapped[date | None] = mapped_column(Date)
    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class CreditNote(Base):
    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint("credit_note_number", "financial_year", name="uq_credit_note_number_fy"),
        CheckConstraint("status IN ('issued','cancelled')", name="ck_credit_note_status"),
        Index("ix_credit_notes_note_date", "note_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_number: Mapped[str] = mapped_column(String(16), index=True)
    financial_year: Mapped[str] = mapped_column(String(9))
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    distributor_id: Mapped[int] = mapped_column(ForeignKey("distributors.id"))
    status: Mapped[str] = mapped_column(String(20), default="issued")
    note_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(300))
    # A sales return puts the goods back into the same batches they left from,
    # in the same warehouse they were issued to (Module Phase 4). Null means a
    # pure money correction that moves no stock.
    return_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    gross_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    discount_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    igst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cess_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    tax_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    round_off: Mapped[Decimal] = mapped_column(MONEY, default=0)
    grand_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    issued_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["CreditNoteLine"]] = relationship(
        back_populates="credit_note", lazy="selectin", cascade="all, delete-orphan")


class CreditNoteLine(Base):
    __tablename__ = "credit_note_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_credit_note_line_qty_positive"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("credit_notes.id"))
    invoice_line_id: Mapped[int] = mapped_column(ForeignKey("invoice_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    sku: Mapped[str] = mapped_column(String(40))
    product_name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[Decimal] = mapped_column(QTY)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY)
    cgst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    igst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cess_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    credit_note: Mapped[CreditNote] = relationship(back_populates="lines")


class DebitNote(Base):
    """A debit note raises what the buyer owes under an issued invoice
    (section 34 of the CGST Act). It is linked to the original invoice, cannot
    exceed that invoice, and is immutable once issued."""
    __tablename__ = "debit_notes"
    __table_args__ = (
        UniqueConstraint("debit_note_number", "financial_year", name="uq_debit_note_number_fy"),
        CheckConstraint("status IN ('issued','cancelled')", name="ck_debit_note_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    debit_note_number: Mapped[str] = mapped_column(String(16), index=True)
    financial_year: Mapped[str] = mapped_column(String(9))
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    distributor_id: Mapped[int] = mapped_column(ForeignKey("distributors.id"))
    status: Mapped[str] = mapped_column(String(20), default="issued")
    note_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(300))
    gross_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    igst_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cess_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    tax_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    grand_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    issued_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["DebitNoteLine"]] = relationship(
        back_populates="debit_note", lazy="selectin", cascade="all, delete-orphan")


class DebitNoteLine(Base):
    __tablename__ = "debit_note_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_debit_note_line_qty_positive"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    debit_note_id: Mapped[int] = mapped_column(ForeignKey("debit_notes.id"))
    invoice_line_id: Mapped[int] = mapped_column(ForeignKey("invoice_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    sku: Mapped[str] = mapped_column(String(40))
    product_name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[Decimal] = mapped_column(QTY)
    taxable_value: Mapped[Decimal] = mapped_column(MONEY)
    cgst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    igst_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    cess_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    debit_note: Mapped[DebitNote] = relationship(back_populates="lines")


class DocumentSequence(Base):
    """The last number issued for a document type in a financial year.

    Invoice and note numbers must be consecutive and unique per financial year
    (FR-14). The row is locked before it is incremented, so two dispatches at
    the same moment queue for the next number instead of colliding, and a gap
    can only come from a cancelled document, whose number is never reused."""
    __tablename__ = "document_sequences"
    __table_args__ = (
        UniqueConstraint("doc_type", "financial_year", name="uq_document_sequence"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(20))
    financial_year: Mapped[str] = mapped_column(String(9))
    last_number: Mapped[int] = mapped_column(Integer, default=0)


class PrintLog(Base):
    """One row per PDF served (Module Phase 5).

    The SHA-256 is of the exact bytes handed to the browser, so a later
    verification can prove a printed page matches the locked record. Copies are
    the sets a goods invoice is issued in: ORIGINAL for the recipient,
    DUPLICATE for the transporter, TRIPLICATE for the supplier."""
    __tablename__ = "print_logs"
    __table_args__ = (
        CheckConstraint("document_type IN ('invoice','credit_note','debit_note')",
                        name="ck_print_log_document_type"),
        CheckConstraint("copy_designation IN ('ORIGINAL','DUPLICATE','TRIPLICATE')",
                        name="ck_print_log_copy"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    document_type: Mapped[str] = mapped_column(String(20), index=True)
    document_id: Mapped[int] = mapped_column(Integer)
    document_number: Mapped[str] = mapped_column(String(16))
    copy_designation: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    printed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    printed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
