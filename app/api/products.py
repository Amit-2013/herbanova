"""Product master.

The HSN is what the GST rate master is keyed by, so a new product must carry
one. Products created before this rule stay readable: the list flags them as
missing an HSN instead of hiding them, and the HSN can be added on edit.
"""
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.pagination import page_params, paginate, sort_clause
from ..core.rbac import require
from ..models.core import Product
from ..services.audit import audit

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductIn(BaseModel):
    sku: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    pack_size: str = Field(min_length=1, max_length=40)
    mrp: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    hsn: str = Field(pattern=r"^[0-9]{4,8}$")
    uqc: str | None = Field(default=None, max_length=3)
    category: str | None = Field(default=None, max_length=60)
    brand: str | None = Field(default=None, max_length=60)
    reorder_level: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)

    @field_validator("sku")
    @classmethod
    def norm(cls, v): return v.strip().upper()

    @field_validator("hsn")
    @classmethod
    def hsn_digits(cls, v): return v.strip()

    @field_validator("uqc")
    @classmethod
    def uqc_norm(cls, v): return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("category", "brand")
    @classmethod
    def label_norm(cls, v): return v.strip() if isinstance(v, str) and v.strip() else None


class ProductPatch(BaseModel):
    """A product may be corrected; the SKU is fixed because other records use it."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    pack_size: str | None = Field(default=None, min_length=1, max_length=40)
    mrp: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    status: str | None = Field(default=None, max_length=20)
    hsn: str | None = Field(default=None, pattern=r"^[0-9]{4,8}$")
    uqc: str | None = Field(default=None, max_length=3)
    category: str | None = Field(default=None, max_length=60)
    brand: str | None = Field(default=None, max_length=60)
    reorder_level: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)

    @field_validator("hsn")
    @classmethod
    def hsn_digits(cls, v): return v.strip() if isinstance(v, str) and v.strip() else None

    @field_validator("uqc")
    @classmethod
    def uqc_norm(cls, v): return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("category", "brand")
    @classmethod
    def label_norm(cls, v): return v.strip() if isinstance(v, str) and v.strip() else None


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    pack_size: str
    mrp: Decimal
    status: str
    hsn: str | None
    uqc: str | None
    category: str | None = None
    brand: str | None = None
    reorder_level: Decimal | None = None
    model_config = {"from_attributes": True}


@router.get("", response_model=list[ProductOut])
def list_products(response: Response, q: str | None = None,
                  status: str | None = None,
                  sort: str | None = None,
                  direction: Literal["asc", "desc"] = "asc",
                  paging=Depends(page_params), db: Session = Depends(get_db),
                  _=Depends(require("product:read"))):
    page, page_size = paging
    stmt = select(Product)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Product.sku.ilike(like), Product.name.ilike(like),
                              Product.hsn.ilike(like), Product.category.ilike(like),
                              Product.brand.ilike(like)))
    if status:
        stmt = stmt.where(Product.status == status)
    # Only the columns a header offers are sortable; SKU keeps every page disjoint.
    stmt = stmt.order_by(sort_clause(sort, {
        "sku": Product.sku, "name": Product.name, "hsn": Product.hsn, "mrp": Product.mrp,
        "category": Product.category, "brand": Product.brand,
        "reorder_level": Product.reorder_level,
        "status": Product.status}, Product.sku, direction), Product.sku)
    return paginate(db, stmt, response, page, page_size)


@router.get("/catalog")
def catalog_values(db: Session = Depends(get_db), _=Depends(require("product:read"))):
    """Distinct grouping values already in the master, for the form's suggestions.

    Reading them back keeps the vocabulary consistent without inventing a fixed
    list of categories or brands.
    """
    def distinct(column):
        return sorted(v for v in db.scalars(select(column).distinct()).all() if v)
    return {"categories": distinct(Product.category), "brands": distinct(Product.brand)}


@router.get("/options")
def product_options(db: Session = Depends(get_db), _=Depends(require("product:read"))):
    """Small selector payload; never the whole product master."""
    rows = db.scalars(select(Product).where(Product.status == "active")
                      .order_by(Product.sku)).all()
    return [{"id": p.id, "sku": p.sku, "name": p.name, "hsn": p.hsn,
             "pack_size": p.pack_size, "mrp": p.mrp} for p in rows]


@router.post("", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, db: Session = Depends(get_db),
                   user=Depends(require("product:write"))):
    p = Product(**body.model_dump())
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "SKU already exists")
    audit(db, user.id, "product.create", f"product:{p.id}", body.model_dump(mode="json"))
    db.commit()
    return p


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, body: ProductPatch, db: Session = Depends(get_db),
                   user=Depends(require("product:write"))):
    """Correct a product. Every change is recorded in the audit trail."""
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in ("active", "discontinued"):
        raise HTTPException(422, "status must be active or discontinued")
    changes = {}
    for key, value in data.items():
        current = getattr(p, key)
        if current != value:
            changes[key] = {"old": str(current) if current is not None else None,
                            "new": str(value) if value is not None else None}
            setattr(p, key, value)
    if not changes:
        raise HTTPException(422, "Nothing to change")
    audit(db, user.id, "product.update", f"product:{p.id}", changes)
    db.commit()
    return p
