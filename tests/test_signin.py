"""Sign-in page content: public reads and Administrator-managed writes.

These tests drive the API, not the screen. They cover what the page may show
without a session, what it must not show, and every refusal an Administrator
can hit while editing banners, notices, contact boxes and the legal pages.
"""
import io
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app.api import signin as signin_api
from app.core.db import SessionLocal
from app.models.core import AuditLog


@pytest.fixture(autouse=True)
def _banners_in_tmp(tmp_path, monkeypatch):
    """Never write a test banner into the real var/signin_banners."""
    monkeypatch.setattr(signin_api, "BANNER_DIR", tmp_path / "banners")


def _png(colour: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _suffix() -> str:
    return uuid4().hex[:6].upper()


def _audit(action: str, record: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).where(
            AuditLog.action == action, AuditLog.record == record)
            .order_by(AuditLog.id)).all()
        return [r.changes or {} for r in rows]


# ------------------------------------------------------------------- public
def test_the_public_page_never_invents_content(client, world):
    page = client.get("/api/public/sign-in")
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["company"]["name"] == "Herbanova Test Co"
    # The seeded legal rows exist so the footer links resolve, but neither is
    # readable until an Administrator writes and publishes it.
    legal = {doc["key"]: doc for doc in body["legal"]}
    assert set(legal) == {"privacy", "terms"}
    for doc in legal.values():
        assert doc["title"]
    for doc in body["banners"] + body["notices"] + body["contacts"]:
        assert "title" not in doc or doc["title"]


def test_unpublished_legal_text_is_not_returned(client):
    with SessionLocal() as db:
        from app.models.signin import LegalDocument
        doc = db.get(LegalDocument, "privacy")
        doc.body = "Internal draft that must not be public."
        doc.published = False
        db.commit()
    try:
        res = client.get("/api/public/sign-in/legal/privacy")
        assert res.status_code == 200
        assert res.json()["published"] is False
        assert res.json()["body"] is None
        assert client.get("/api/public/sign-in/legal/nope").status_code == 404
    finally:
        with SessionLocal() as db:
            from app.models.signin import LegalDocument
            doc = db.get(LegalDocument, "privacy")
            doc.body = None
            doc.published = False
            db.commit()


# ------------------------------------------------------------------ banners
def test_banner_upload_replacement_deactivation_and_delete(client):
    admin = client.as_user("admin")
    title = f"Promotion {_suffix()}"
    created = admin.post("/api/admin/sign-in/banners",
                         files={"file": ("promo.png", _png(), "image/png")},
                         data={"title": title, "link_url": "/ui/#/products",
                               "sort_order": "3", "active": "true"})
    assert created.status_code == 201, created.text
    banner = created.json()
    banner_id = banner["id"]
    assert banner["title"] == title
    assert banner["link_url"] == "/ui/#/products"
    assert banner["sort_order"] == 3
    assert _audit("signin.banner.create", f"signin_banner:{banner_id}")

    page = client.get("/api/public/sign-in").json()
    assert any(b["id"] == banner_id for b in page["banners"])

    image = client.get(f"/api/public/sign-in/banners/{banner_id}/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == _png()

    replaced = admin.post(f"/api/admin/sign-in/banners/{banner_id}/image",
                          files={"file": ("new.png", _png("black"), "image/png")})
    assert replaced.status_code == 200, replaced.text
    assert client.get(f"/api/public/sign-in/banners/{banner_id}/image").content == _png("black")
    assert _audit("signin.banner.image", f"signin_banner:{banner_id}")

    off = admin.patch(f"/api/admin/sign-in/banners/{banner_id}", json={"active": False})
    assert off.status_code == 200, off.text
    assert off.json()["active"] is False
    assert not any(b["id"] == banner_id
                   for b in client.get("/api/public/sign-in").json()["banners"])
    assert client.get(f"/api/public/sign-in/banners/{banner_id}/image").status_code == 404

    deleted = admin.delete(f"/api/admin/sign-in/banners/{banner_id}")
    assert deleted.status_code == 200
    assert admin.get(f"/api/admin/sign-in/banners/{banner_id}/image").status_code == 404
    assert _audit("signin.banner.delete", f"signin_banner:{banner_id}")


def test_banner_upload_refusals(client):
    admin = client.as_user("admin")
    bad_type = admin.post("/api/admin/sign-in/banners",
                          files={"file": ("note.txt", b"not an image", "text/plain")},
                          data={"title": "Bad"})
    assert bad_type.status_code == 422
    oversized = admin.post("/api/admin/sign-in/banners",
                           files={"file": ("big.png", b"x" * 2_000_001, "image/png")},
                           data={"title": "Big"})
    assert oversized.status_code == 413
    for link in ("javascript:alert(1)", "//evil.example", "ftp://example.com/a"):
        res = admin.post("/api/admin/sign-in/banners",
                         files={"file": ("promo.png", _png(), "image/png")},
                         data={"title": "Bad link", "link_url": link})
        assert res.status_code == 422, link
    no_title = admin.post("/api/admin/sign-in/banners",
                          files={"file": ("promo.png", _png(), "image/png")},
                          data={"title": "   "})
    assert no_title.status_code == 422


# ------------------------------------------------------------------ notices
def test_notice_crud_and_public_order(client):
    admin = client.as_user("admin")
    title = f"Stock count {_suffix()}"
    created = admin.post("/api/admin/sign-in/notices", json={
        "title": title, "body": "Warehouse closed on Saturday.",
        "notice_date": "2026-11-01", "active": True})
    assert created.status_code == 201, created.text
    notice = created.json()
    assert notice["date"] == "2026-11-01"
    assert _audit("signin.notice.create", f"signin_notice:{notice['id']}")

    page = client.get("/api/public/sign-in").json()
    assert any(n["id"] == notice["id"] and n["date"] == "2026-11-01"
               for n in page["notices"])

    updated = admin.patch(f"/api/admin/sign-in/notices/{notice['id']}",
                          json={"title": title + " revised", "active": False})
    assert updated.status_code == 200, updated.text
    assert updated.json()["active"] is False
    assert not any(n["id"] == notice["id"]
                   for n in client.get("/api/public/sign-in").json()["notices"])

    deleted = admin.delete(f"/api/admin/sign-in/notices/{notice['id']}")
    assert deleted.status_code == 200
    assert admin.delete(f"/api/admin/sign-in/notices/{notice['id']}").status_code == 404


# ----------------------------------------------------------------- contacts
def test_contact_boxes_are_validated_and_editable(client):
    admin = client.as_user("admin")
    label = f"Sales {_suffix()}"
    created = admin.post("/api/admin/sign-in/contacts", json={
        "label": label, "detail": "North region", "phone": "+91 90000 00000",
        "email": "sales@example.com", "sort_order": 1})
    assert created.status_code == 201, created.text
    contact = created.json()
    assert _audit("signin.contact.create", f"signin_contact:{contact['id']}")

    page = client.get("/api/public/sign-in").json()
    assert any(c["label"] == label for c in page["contacts"])

    assert admin.post("/api/admin/sign-in/contacts", json={
        "label": "Empty box"}).status_code == 422
    assert admin.post("/api/admin/sign-in/contacts", json={
        "label": "Bad email", "email": "not-an-address"}).status_code == 422
    assert admin.patch(f"/api/admin/sign-in/contacts/{contact['id']}",
                       json={"email": "broken"}).status_code == 422

    updated = admin.patch(f"/api/admin/sign-in/contacts/{contact['id']}",
                          json={"phone": "+91 91111 11111", "detail": "All regions"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["phone"] == "+91 91111 11111"

    assert admin.delete(f"/api/admin/sign-in/contacts/{contact['id']}").status_code == 200


# -------------------------------------------------------------------- legal
def test_legal_text_must_be_written_before_it_is_published(client):
    admin = client.as_user("admin")
    admin.patch("/api/admin/sign-in/legal/privacy", json={"body": None, "published": False})

    refused = admin.patch("/api/admin/sign-in/legal/privacy", json={"published": True})
    assert refused.status_code == 422
    assert "Write the document text" in refused.text

    saved = admin.patch("/api/admin/sign-in/legal/privacy", json={
        "body": "How this installation handles personal data.", "published": True})
    assert saved.status_code == 200, saved.text
    assert saved.json()["published"] is True
    assert _audit("signin.legal.update", "legal_document:privacy")

    public = client.get("/api/public/sign-in/legal/privacy").json()
    assert public["published"] is True
    assert public["body"] == "How this installation handles personal data."

    blank_title = admin.patch("/api/admin/sign-in/legal/privacy", json={"title": " "})
    assert blank_title.status_code == 422

    withdrawn = admin.patch("/api/admin/sign-in/legal/privacy",
                            json={"published": False, "body": None})
    assert withdrawn.status_code == 200
    assert client.get("/api/public/sign-in/legal/privacy").json()["body"] is None
    assert admin.patch("/api/admin/sign-in/legal/other",
                       json={"published": False}).status_code == 404


# -------------------------------------------------------------- permissions
def test_only_the_administrator_manages_sign_in_content(client):
    sales = client.as_user("sales")
    assert sales.get("/api/admin/sign-in").status_code == 403
    assert sales.post("/api/admin/sign-in/notices", json={
        "title": "Nope", "notice_date": "2026-11-01"}).status_code == 403
    assert sales.post("/api/admin/sign-in/contacts", json={
        "label": "Nope", "phone": "1"}).status_code == 403
    assert sales.patch("/api/admin/sign-in/legal/privacy", json={
        "published": False}).status_code == 403
    # The public page stays readable without a session.
    client.cookies.clear()
    assert client.get("/api/public/sign-in").status_code == 200
