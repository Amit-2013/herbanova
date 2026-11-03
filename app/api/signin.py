"""Sign-in page content: public read routes and Administrator management.

The sign-in screen has no session, so it reads `/api/public/sign-in` and the
banner images below it. Only active rows are returned, and a legal document is
readable only once its text has been published. Nothing here invents a notice,
a phone number or a policy: an empty table means the screen shows that there is
nothing yet.

Everything is written from the Administrator panel in Settings. Each write is
audited, and an uploaded banner is stored under `var/signin_banners` and served
through the public image route only, never from the static mount.
"""
import io
import re
import secrets
from datetime import date
from pathlib import Path

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request, UploadFile)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.limiter import limiter
from ..core.rbac import require_admin
from ..models.signin import LegalDocument, SignInBanner, SignInContact, SignInNotice
from ..models.tax import CompanyProfile
from ..services.audit import audit

router = APIRouter(prefix="/api/public/sign-in", tags=["sign-in"])
admin_router = APIRouter(prefix="/api/admin/sign-in", tags=["sign-in administration"])

BANNER_DIR = Path(__file__).resolve().parents[2] / "var" / "signin_banners"
BANNER_TYPES = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
                "WEBP": ("webp", "image/webp")}
MAX_BANNER_BYTES = 2_000_000
LEGAL_KEYS = ("privacy", "terms")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

admin_only = require_admin("user:manage")


# ------------------------------------------------------------------ helpers
def _company(db: Session) -> dict:
    profile = db.scalars(select(CompanyProfile).order_by(CompanyProfile.id)).first()
    return {"name": profile.legal_name if profile else None,
            "trade_name": profile.trade_name if profile else None}


def _legal_state(doc: LegalDocument) -> dict:
    """A document is readable only when it is published and has text."""
    readable = bool(doc.published and (doc.body or "").strip())
    return {"key": doc.key, "title": doc.title, "published": readable,
            "body": doc.body if readable else None}


def _check_text(value: str | None, field: str, limit: int, required: bool) -> str | None:
    text = (value or "").strip()
    if required and not text:
        raise HTTPException(422, f"{field} is required")
    if len(text) > limit:
        raise HTTPException(422, f"{field} must be at most {limit} characters")
    return text or None


def _check_link(value: str | None) -> str | None:
    """Only an absolute http(s) address or a site-relative path is allowed.

    The value becomes an href on the public page, so `javascript:` must never
    reach it.
    """
    link = (value or "").strip()
    if not link:
        return None
    if len(link) > 500:
        raise HTTPException(422, "The link must be at most 500 characters")
    relative = link.startswith("/") and not link.startswith("//")
    if not relative and not re.match(r"^https?://", link, re.IGNORECASE):
        raise HTTPException(422, "A banner link must start with http://, https:// or /")
    return link


def _check_contact(label: str | None, detail: str | None, phone: str | None,
                   email: str | None) -> tuple[str, str | None, str | None, str | None]:
    name = _check_text(label, "The box label", 60, True)
    detail = _check_text(detail, "The contact detail", 160, False)
    phone = _check_text(phone, "The phone number", 40, False)
    email = _check_text(email, "The email address", 160, False)
    if email and not EMAIL_RE.match(email):
        raise HTTPException(422, f"Enter a valid email address for {name}")
    if not (detail or phone or email):
        raise HTTPException(422, "Add a detail, a phone number or an email address")
    return name, detail, phone, email


def _check_image(data: bytes) -> str:
    if len(data) > MAX_BANNER_BYTES:
        raise HTTPException(413, "The banner must be 2 MB or smaller")
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            fmt = image.format
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError,
            ValueError):
        raise HTTPException(422, "Upload a JPEG, PNG or WebP image")
    if fmt not in BANNER_TYPES:
        raise HTTPException(422, "Upload a JPEG, PNG or WebP image")
    return fmt


def _write_banner(data: bytes, fmt: str) -> str:
    ext = BANNER_TYPES[fmt][0]
    name = f"banner_{secrets.token_hex(8)}.{ext}"
    BANNER_DIR.mkdir(parents=True, exist_ok=True)
    (BANNER_DIR / name).write_bytes(data)
    return name


def _media_type(name: str) -> str:
    return {".jpg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp"}.get(Path(name).suffix.lower(), "application/octet-stream")


def _banner_admin(row: SignInBanner) -> dict:
    return {"id": row.id, "title": row.title, "link_url": row.link_url,
            "sort_order": row.sort_order, "active": row.active,
            "image_url": f"/api/admin/sign-in/banners/{row.id}/image"}


def _notice_admin(row: SignInNotice) -> dict:
    return {"id": row.id, "title": row.title, "body": row.body,
            "date": row.notice_date.isoformat(), "active": row.active}


def _contact_admin(row: SignInContact) -> dict:
    return {"id": row.id, "label": row.label, "detail": row.detail,
            "phone": row.phone, "email": row.email, "sort_order": row.sort_order,
            "active": row.active}


# ------------------------------------------------------------------ public
@router.get("")
@limiter.limit("60/minute")
def public_content(request: Request, db: Session = Depends(get_db)):
    banners = db.scalars(
        select(SignInBanner).where(SignInBanner.active.is_(True))
        .order_by(SignInBanner.sort_order, SignInBanner.id)).all()
    notices = db.scalars(
        select(SignInNotice).where(SignInNotice.active.is_(True))
        .order_by(SignInNotice.notice_date.desc(), SignInNotice.id.desc())
        .limit(5)).all()
    contacts = db.scalars(
        select(SignInContact).where(SignInContact.active.is_(True))
        .order_by(SignInContact.sort_order, SignInContact.id)).all()
    legal = db.scalars(select(LegalDocument).order_by(LegalDocument.key)).all()
    return {
        "company": _company(db),
        "banners": [{"id": row.id, "title": row.title, "link_url": row.link_url,
                     "image_url": f"/api/public/sign-in/banners/{row.id}/image"}
                    for row in banners],
        "notices": [{"id": row.id, "title": row.title, "body": row.body,
                     "date": row.notice_date.isoformat()} for row in notices],
        "contacts": [{"id": row.id, "label": row.label, "detail": row.detail,
                      "phone": row.phone, "email": row.email} for row in contacts],
        "legal": [{"key": row.key, "title": row.title,
                   "published": bool(row.published and (row.body or "").strip())}
                  for row in legal],
    }


@router.get("/banners/{banner_id}/image")
@limiter.limit("240/minute")
def public_banner_image(banner_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(SignInBanner, banner_id)
    if not row or not row.active:
        raise HTTPException(404, "Banner not found")
    path = BANNER_DIR / Path(row.image_path).name
    if not path.exists():
        raise HTTPException(404, "Banner image is missing")
    return FileResponse(path, media_type=_media_type(path.name),
                        headers={"Cache-Control": "public, no-cache"})


@router.get("/legal/{key}")
@limiter.limit("60/minute")
def public_legal(key: str, request: Request, db: Session = Depends(get_db)):
    if key not in LEGAL_KEYS:
        raise HTTPException(404, "Unknown document")
    doc = db.get(LegalDocument, key)
    if doc is None:
        return {"key": key, "title": None, "published": False, "body": None}
    return _legal_state(doc)


# ------------------------------------------------------------------ administration
@admin_router.get("")
def admin_content(db: Session = Depends(get_db), _=Depends(admin_only)):
    return {
        "banners": [_banner_admin(row) for row in db.scalars(
            select(SignInBanner).order_by(SignInBanner.sort_order, SignInBanner.id)).all()],
        "notices": [_notice_admin(row) for row in db.scalars(
            select(SignInNotice).order_by(SignInNotice.notice_date.desc(),
                                          SignInNotice.id.desc())).all()],
        "contacts": [_contact_admin(row) for row in db.scalars(
            select(SignInContact).order_by(SignInContact.sort_order,
                                           SignInContact.id)).all()],
        "legal": [{"key": row.key, "title": row.title, "body": row.body,
                   "published": row.published}
                  for row in db.scalars(select(LegalDocument).order_by(LegalDocument.key)).all()],
    }


@admin_router.get("/banners/{banner_id}/image")
def admin_banner_image(banner_id: int, db: Session = Depends(get_db),
                       _=Depends(admin_only)):
    row = db.get(SignInBanner, banner_id)
    if not row:
        raise HTTPException(404, "Banner not found")
    path = BANNER_DIR / Path(row.image_path).name
    if not path.exists():
        raise HTTPException(404, "Banner image is missing")
    return FileResponse(path, media_type=_media_type(path.name),
                        headers={"Cache-Control": "no-store"})


@admin_router.post("/banners", status_code=201)
async def create_banner(file: UploadFile = File(...), title: str = Form(...),
                        link_url: str = Form(""), sort_order: int = Form(0),
                        active: bool = Form(True), db: Session = Depends(get_db),
                        actor=Depends(admin_only)):
    clean_title = _check_text(title, "The banner title", 120, True)
    clean_link = _check_link(link_url)
    data = await file.read(MAX_BANNER_BYTES + 1)
    fmt = _check_image(data)
    name = _write_banner(data, fmt)
    row = SignInBanner(title=clean_title, image_path=name, link_url=clean_link,
                       sort_order=sort_order, active=active, created_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, actor.id, "signin.banner.create", f"signin_banner:{row.id}",
          {"title": row.title, "format": fmt, "active": row.active})
    db.commit()
    return _banner_admin(row)


class BannerPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    link_url: str | None = Field(default=None, max_length=500)
    sort_order: int | None = None
    active: bool | None = None


@admin_router.patch("/banners/{banner_id}")
def update_banner(banner_id: int, body: BannerPatch, db: Session = Depends(get_db),
                  actor=Depends(admin_only)):
    row = db.get(SignInBanner, banner_id)
    if not row:
        raise HTTPException(404, "Banner not found")
    fields = body.model_dump(exclude_unset=True)
    if "title" in fields:
        row.title = _check_text(fields["title"], "The banner title", 120, True)
    if "link_url" in fields:
        row.link_url = _check_link(fields["link_url"])
    if "sort_order" in fields:
        row.sort_order = fields["sort_order"]
    if "active" in fields:
        row.active = fields["active"]
    audit(db, actor.id, "signin.banner.update", f"signin_banner:{row.id}",
          {k: fields[k] for k in fields if k != "link_url"} | {"link_set": bool(row.link_url)})
    db.commit()
    return _banner_admin(row)


@admin_router.post("/banners/{banner_id}/image")
async def replace_banner_image(banner_id: int, file: UploadFile = File(...),
                               db: Session = Depends(get_db), actor=Depends(admin_only)):
    row = db.get(SignInBanner, banner_id)
    if not row:
        raise HTTPException(404, "Banner not found")
    data = await file.read(MAX_BANNER_BYTES + 1)
    fmt = _check_image(data)
    old = row.image_path
    row.image_path = _write_banner(data, fmt)
    if old and old != row.image_path:
        (BANNER_DIR / Path(old).name).unlink(missing_ok=True)
    audit(db, actor.id, "signin.banner.image", f"signin_banner:{row.id}", {"format": fmt})
    db.commit()
    return _banner_admin(row)


@admin_router.delete("/banners/{banner_id}")
def delete_banner(banner_id: int, db: Session = Depends(get_db),
                  actor=Depends(admin_only)):
    row = db.get(SignInBanner, banner_id)
    if not row:
        raise HTTPException(404, "Banner not found")
    (BANNER_DIR / Path(row.image_path).name).unlink(missing_ok=True)
    audit(db, actor.id, "signin.banner.delete", f"signin_banner:{row.id}",
          {"title": row.title})
    db.delete(row)
    db.commit()
    return {"deleted": banner_id}


class NoticeIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str | None = Field(default=None, max_length=2000)
    notice_date: date
    active: bool = True

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The notice title is required")
        return value


class NoticePatch(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    body: str | None = Field(default=None, max_length=2000)
    notice_date: date | None = None
    active: bool | None = None


@admin_router.post("/notices", status_code=201)
def create_notice(body: NoticeIn, db: Session = Depends(get_db),
                  actor=Depends(admin_only)):
    row = SignInNotice(title=body.title, body=_check_text(body.body, "The notice text", 2000, False),
                       notice_date=body.notice_date, active=body.active,
                       created_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, actor.id, "signin.notice.create", f"signin_notice:{row.id}",
          {"title": row.title, "date": row.notice_date.isoformat()})
    db.commit()
    return _notice_admin(row)


@admin_router.patch("/notices/{notice_id}")
def update_notice(notice_id: int, body: NoticePatch, db: Session = Depends(get_db),
                  actor=Depends(admin_only)):
    row = db.get(SignInNotice, notice_id)
    if not row:
        raise HTTPException(404, "Notice not found")
    fields = body.model_dump(exclude_unset=True)
    if "title" in fields:
        title = _check_text(fields["title"], "The notice title", 160, True)
        row.title = title
    if "body" in fields:
        row.body = _check_text(fields["body"], "The notice text", 2000, False)
    if "notice_date" in fields:
        if fields["notice_date"] is None:
            raise HTTPException(422, "A notice needs a date")
        row.notice_date = fields["notice_date"]
    if "active" in fields:
        row.active = fields["active"]
    audit(db, actor.id, "signin.notice.update", f"signin_notice:{row.id}",
          {k: (v.isoformat() if isinstance(v, date) else v) for k, v in fields.items()})
    db.commit()
    return _notice_admin(row)


@admin_router.delete("/notices/{notice_id}")
def delete_notice(notice_id: int, db: Session = Depends(get_db),
                  actor=Depends(admin_only)):
    row = db.get(SignInNotice, notice_id)
    if not row:
        raise HTTPException(404, "Notice not found")
    audit(db, actor.id, "signin.notice.delete", f"signin_notice:{row.id}",
          {"title": row.title})
    db.delete(row)
    db.commit()
    return {"deleted": notice_id}


class ContactIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    detail: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)
    sort_order: int = 0
    active: bool = True


class ContactPatch(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    detail: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)
    sort_order: int | None = None
    active: bool | None = None


@admin_router.post("/contacts", status_code=201)
def create_contact(body: ContactIn, db: Session = Depends(get_db),
                   actor=Depends(admin_only)):
    label, detail, phone, email = _check_contact(body.label, body.detail, body.phone,
                                                body.email)
    row = SignInContact(label=label, detail=detail, phone=phone, email=email,
                        sort_order=body.sort_order, active=body.active)
    db.add(row)
    db.flush()
    audit(db, actor.id, "signin.contact.create", f"signin_contact:{row.id}",
          {"label": row.label})
    db.commit()
    return _contact_admin(row)


@admin_router.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactPatch, db: Session = Depends(get_db),
                   actor=Depends(admin_only)):
    row = db.get(SignInContact, contact_id)
    if not row:
        raise HTTPException(404, "Contact box not found")
    fields = body.model_dump(exclude_unset=True)
    merged = {"label": fields.get("label", row.label),
              "detail": fields.get("detail", row.detail),
              "phone": fields.get("phone", row.phone),
              "email": fields.get("email", row.email)}
    label, detail, phone, email = _check_contact(**merged)
    row.label, row.detail, row.phone, row.email = label, detail, phone, email
    if "sort_order" in fields:
        row.sort_order = fields["sort_order"]
    if "active" in fields:
        row.active = fields["active"]
    audit(db, actor.id, "signin.contact.update", f"signin_contact:{row.id}",
          {"label": row.label, "fields": sorted(fields)})
    db.commit()
    return _contact_admin(row)


@admin_router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, db: Session = Depends(get_db),
                   actor=Depends(admin_only)):
    row = db.get(SignInContact, contact_id)
    if not row:
        raise HTTPException(404, "Contact box not found")
    audit(db, actor.id, "signin.contact.delete", f"signin_contact:{row.id}",
          {"label": row.label})
    db.delete(row)
    db.commit()
    return {"deleted": contact_id}


class LegalPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    body: str | None = Field(default=None, max_length=20_000)
    published: bool | None = None


@admin_router.patch("/legal/{key}")
def update_legal(key: str, body: LegalPatch, db: Session = Depends(get_db),
                 actor=Depends(admin_only)):
    if key not in LEGAL_KEYS:
        raise HTTPException(404, "Unknown document")
    row = db.get(LegalDocument, key)
    if row is None:
        raise HTTPException(404, "Unknown document")
    fields = body.model_dump(exclude_unset=True)
    if "title" in fields:
        row.title = _check_text(fields["title"], "The document title", 120, True)
    if "body" in fields:
        row.body = _check_text(fields["body"], "The document text", 20_000, False)
    if "published" in fields:
        row.published = fields["published"]
    if row.published and not (row.body or "").strip():
        db.rollback()
        raise HTTPException(422, "Write the document text before publishing it")
    row.updated_by = actor.id
    audit(db, actor.id, "signin.legal.update", f"legal_document:{key}",
          {"published": row.published, "characters": len(row.body or "")})
    db.commit()
    return _legal_state(row)
