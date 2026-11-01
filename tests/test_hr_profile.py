"""Profile tabs: photo, documents, assets and history."""
import io
from datetime import date, timedelta
from uuid import uuid4

from PIL import Image


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (31, 107, 74)).save(buf, format="PNG")
    return buf.getvalue()


def test_photo_upload_and_authenticated_read(client, world):
    staff_id = client.employee_ids["staff"]
    # Other tests link this employee to a manager; this case needs no chain.
    client.as_user("admin").patch(f"/api/hr/employees/{staff_id}",
                                  json={"manager_id": None})
    staff = client.as_user("staff")
    upload = staff.post(f"/api/hr/employees/{staff_id}/photo",
                        files={"file": ("photo.png", _png(), "image/png")})
    assert upload.status_code == 200, upload.text
    assert upload.json()["has_photo"] is True

    got = staff.get(f"/api/hr/employees/{staff_id}/photo")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"

    # A manager outside the chain cannot read it.
    client.as_user("manager")
    assert client.get(f"/api/hr/employees/{staff_id}/photo").status_code == 403

    # Non-images are refused before anything is stored.
    staff = client.as_user("staff")
    bad = staff.post(f"/api/hr/employees/{staff_id}/photo",
                     files={"file": ("notes.txt", b"not an image", "text/plain")})
    assert bad.status_code == 422

    removed = staff.delete(f"/api/hr/employees/{staff_id}/photo")
    assert removed.status_code == 200
    assert staff.get(f"/api/hr/employees/{staff_id}/photo").status_code == 404


def test_documents_keep_numbers_confidential(client, world):
    admin = client.as_user("admin")
    staff_id = client.employee_ids["staff"]
    manager_id = client.employee_ids["manager"]
    admin.patch(f"/api/hr/employees/{staff_id}", json={"manager_id": manager_id})
    added = admin.post(f"/api/hr/employees/{staff_id}/documents", json={
        "doc_type": "passport", "title": "Passport", "number": "P1234567",
        "issued_on": (date.today() - timedelta(days=1000)).isoformat(),
        "expires_on": (date.today() + timedelta(days=200)).isoformat()})
    assert added.status_code == 201, added.text
    assert added.json()["number"] == "P1234567"

    client.as_user("manager")
    rows = client.get(f"/api/hr/employees/{staff_id}/documents").json()
    assert rows[0]["number_masked"] is True
    assert rows[0]["number"].endswith("4567")
    assert "P1234567" not in str(rows)

    client.as_user("hr_manager")
    rows = client.get(f"/api/hr/employees/{staff_id}/documents").json()
    assert rows[0]["number"] == "P1234567"

    # Expiry before issue is refused.
    admin = client.as_user("admin")
    bad = admin.post(f"/api/hr/employees/{staff_id}/documents", json={
        "doc_type": "visa", "title": "Visa",
        "issued_on": date.today().isoformat(),
        "expires_on": (date.today() - timedelta(days=1)).isoformat()})
    assert bad.status_code == 422


def test_assets_can_be_issued_and_returned_once(client, world):
    admin = client.as_user("admin")
    staff_id = client.employee_ids["staff"]
    issued = admin.post(f"/api/hr/employees/{staff_id}/assets", json={
        "asset_type": "laptop", "name": "ThinkPad", "serial_no": "SN-1",
        "issued_on": (date.today() - timedelta(days=30)).isoformat()})
    assert issued.status_code == 201, issued.text
    asset_id = issued.json()["id"]

    rows = admin.get(f"/api/hr/employees/{staff_id}/assets").json()
    assert any(a["id"] == asset_id and a["returned_on"] is None for a in rows)

    early = admin.post(f"/api/hr/assets/{asset_id}/return", json={
        "returned_on": (date.today() - timedelta(days=60)).isoformat()})
    assert early.status_code == 422
    done = admin.post(f"/api/hr/assets/{asset_id}/return", json={
        "returned_on": date.today().isoformat(), "condition_note": "Good"})
    assert done.status_code == 200, done.text
    assert done.json()["returned_on"] == date.today().isoformat()
    assert admin.post(f"/api/hr/assets/{asset_id}/return", json={
        "returned_on": date.today().isoformat()}).status_code == 409


def test_profile_bundles_tabs_and_history(client, world):
    admin = client.as_user("admin")
    staff_id = client.employee_ids["staff"]
    admin.patch(f"/api/hr/employees/{staff_id}", json={"designation": "Profile Test"})
    admin.post(f"/api/hr/employees/{staff_id}/documents", json={
        "doc_type": "id", "title": "Company ID"})

    profile = admin.get(f"/api/hr/employees/{staff_id}/profile").json()
    assert profile["employee"]["id"] == staff_id
    assert profile["documents"][0]["title"] == "Company ID"
    assert isinstance(profile["assets"], list)
    assert any(h["action"] == "employee.update" for h in profile["history"])
    assert profile["can_edit"] is True

    # The employee sees their own profile bundle, and only that one.
    staff = client.as_user("staff")
    own = staff.get(f"/api/hr/employees/{staff_id}/profile")
    assert own.status_code == 200
    assert own.json()["can_edit"] is False
    other = staff.get(f"/api/hr/employees/{client.employee_ids['manager']}/profile")
    assert other.status_code == 403