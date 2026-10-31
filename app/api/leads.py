"""Leads and follow-ups: owner, next follow-up date, append-only activity history.

Rules enforced here (not in the screen):
  - every open lead has one owner; only the owner or an administrator may change it
  - a new lead needs a follow-up date (today or later) and a phone or an email
  - phone/email duplicates are refused (same last 10 digits / same address)
  - after a call, email or meeting you must set the next follow-up, or clear it on purpose
  - won/lost close the lead and clear its follow-up; lost needs a reason; only an admin reopens
  - history rows are only ever added
Audit entries (and so Telegram messages) carry lead numbers, statuses and dates only,
never names, phone numbers or e-mail addresses.
"""
import re
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.pagination import page_params, paginate
from ..core.rbac import ROLE_PERMS, require, role_permissions
from ..models.core import Lead, LeadActivity, User
from ..services.audit import audit

router = APIRouter(prefix="/api/leads", tags=["leads"])

Source = Literal["referral", "website", "event", "cold_call", "distributor", "social", "other"]
OPEN, CLOSED = ("new", "contacted", "qualified"), ("won", "lost")
TRANSITIONS = {"new": {"contacted", "qualified", "lost"}, "contacted": {"qualified", "lost"},
               "qualified": {"contacted", "won", "lost"}}
MAX_DAYS_AHEAD = 730
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------- validation helpers
def _blank(v):
    v = (v or "").strip()
    return v or None


def _phone_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    if re.search(r"[^\d\s+\-().]", raw):
        raise ValueError("phone may contain only digits, spaces and + - ( )")
    digits = re.sub(r"\D", "", raw)
    if not 7 <= len(digits) <= 15:
        raise ValueError("phone must have 7 to 15 digits")
    return digits[-10:]


def _email_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    if not EMAIL_RE.match(raw):
        raise ValueError("email address is not valid")
    return raw.lower()


def _check_date(d: date, current: date | None = None) -> date:
    """A follow-up cannot be set in the past (an unchanged overdue date is left alone)."""
    today = date.today()
    if d != current and d < today:
        raise HTTPException(422, "Follow-up date cannot be in the past")
    if d > today + timedelta(days=MAX_DAYS_AHEAD):
        raise HTTPException(422, "Follow-up date is too far ahead (2 years at most)")
    return d


# ---------------------------------------------------------------- schemas
class ContactMixin(BaseModel):
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=150)

    @field_validator("phone", "email", mode="before")
    @classmethod
    def strip_blank(cls, v): return _blank(v) if isinstance(v, str) or v is None else v

    @field_validator("phone")
    @classmethod
    def chk_phone(cls, v):
        _phone_key(v); return v

    @field_validator("email")
    @classmethod
    def chk_email(cls, v):
        _email_key(v); return v


class LeadIn(ContactMixin):
    name: str = Field(min_length=2, max_length=150)
    company: str | None = Field(default=None, max_length=150)
    source: Source
    owner_id: int | None = None
    next_follow_up: date
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def has_contact(self):
        if not self.phone and not self.email:
            raise ValueError("enter a phone number or an email address")
        return self


class LeadEditIn(ContactMixin):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    company: str | None = Field(default=None, max_length=150)
    source: Source | None = None


class ActivityIn(BaseModel):
    kind: Literal["note", "call", "email", "meeting"]
    summary: str = Field(min_length=3, max_length=500)
    next_follow_up: date | None = None
    clear_follow_up: bool = False

    @model_validator(mode="after")
    def not_both(self):
        if self.next_follow_up and self.clear_follow_up:
            raise ValueError("set a follow-up date or clear it, not both")
        return self


class StatusIn(BaseModel):
    status: Literal["contacted", "qualified", "won", "lost"]
    reason: str | None = Field(default=None, max_length=300)
    next_follow_up: date | None = None          # needed only when an admin reopens a closed lead


class FollowUpIn(BaseModel):
    next_follow_up: date | None = None          # null clears it, and then a reason is needed
    reason: str | None = Field(default=None, max_length=300)


class OwnerIn(BaseModel):
    owner_id: int
    reason: str = Field(min_length=3, max_length=300)


class ActivityOut(BaseModel):
    id: int
    kind: str
    summary: str
    actor: str
    created_at: datetime | None


class LeadOut(BaseModel):
    id: int
    lead_no: str
    name: str
    company: str | None
    phone: str | None
    email: str | None
    source: str
    status: str
    owner_id: int
    owner: str
    next_follow_up: date | None
    follow_up_state: str                 # overdue | today | upcoming | none | closed
    days_overdue: int | None
    closed_reason: str | None
    last_remark: str | None
    created_at: datetime | None
    last_activity_at: datetime | None


class LeadDetail(LeadOut):
    activities: list[ActivityOut]


class OwnerOut(BaseModel):
    id: int
    username: str
    role: str


# ---------------------------------------------------------------- helpers
def _state(l: Lead, today: date) -> tuple[str, int | None]:
    if l.status in CLOSED:
        return "closed", None
    if l.next_follow_up is None:
        return "none", None
    if l.next_follow_up < today:
        return "overdue", (today - l.next_follow_up).days
    return ("today" if l.next_follow_up == today else "upcoming"), None


def _build(db: Session, leads: list[Lead]) -> list[LeadOut]:
    if not leads:
        return []
    ids = [l.id for l in leads]
    owners = {u.id: u.username for u in db.scalars(select(User).where(
        User.id.in_({l.owner_id for l in leads}))).all()}
    last = dict(db.execute(select(LeadActivity.lead_id, func.max(LeadActivity.created_at))
                           .where(LeadActivity.lead_id.in_(ids)).group_by(LeadActivity.lead_id)).all())
    remarks = {}
    for lead_id, summary in db.execute(select(LeadActivity.lead_id, LeadActivity.summary)
                                       .where(LeadActivity.lead_id.in_(ids))
                                       .order_by(LeadActivity.id.desc())).all():
        remarks.setdefault(lead_id, summary)
    today, out = date.today(), []
    for l in leads:
        st, od = _state(l, today)
        out.append(LeadOut(
            id=l.id, lead_no=l.lead_no, name=l.name, company=l.company, phone=l.phone, email=l.email,
            source=l.source, status=l.status, owner_id=l.owner_id, owner=owners.get(l.owner_id, "?"),
            next_follow_up=l.next_follow_up, follow_up_state=st, days_overdue=od,
            closed_reason=l.closed_reason, last_remark=remarks.get(l.id),
            created_at=l.created_at, last_activity_at=last.get(l.id)))
    return out


def _detail(db: Session, lead: Lead) -> LeadDetail:
    base = _build(db, [lead])[0]
    acts = db.execute(select(LeadActivity, User.username).join(User, User.id == LeadActivity.actor_id)
                      .where(LeadActivity.lead_id == lead.id)
                      .order_by(LeadActivity.id.desc())).all()
    return LeadDetail(**base.model_dump(), activities=[
        ActivityOut(id=a.id, kind=a.kind, summary=a.summary, actor=u, created_at=a.created_at) for a, u in acts])


def _log(db: Session, lead: Lead, actor_id: int, kind: str, summary: str) -> None:
    db.add(LeadActivity(lead_id=lead.id, kind=kind, summary=summary, actor_id=actor_id))


def _locked(db: Session, lead_id: int) -> Lead:
    lead = db.scalars(select(Lead).where(Lead.id == lead_id).with_for_update()).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


def _can_change(db: Session, user: User, lead: Lead) -> None:
    if "lead:assign" in role_permissions(db, user) or lead.owner_id == user.id:
        return
    owner = db.get(User, lead.owner_id)
    raise HTTPException(403, f"This lead belongs to {owner.username if owner else 'another user'}; "
                             f"only the owner or an administrator can change it")


def _valid_owner(db: Session, owner_id: int) -> User:
    u = db.get(User, owner_id)
    if not u or not u.is_active or "lead:write" not in role_permissions(db, u):
        raise HTTPException(422, "The owner must be an active sales or admin user")
    return u


def _duplicate(db: Session, phone_key, email_key, exclude_id: int | None = None) -> None:
    conds = []
    if phone_key:
        conds.append(Lead.phone_key == phone_key)
    if email_key:
        conds.append(Lead.email_key == email_key)
    if not conds:
        return
    q = select(Lead).where(or_(*conds))
    if exclude_id:
        q = q.where(Lead.id != exclude_id)
    hit = db.scalars(q).first()
    if hit:
        what = "phone number" if phone_key and hit.phone_key == phone_key else "email address"
        raise HTTPException(409, f"A lead with this {what} already exists ({hit.lead_no}). Open that lead instead.")


def _set_follow_up(db: Session, lead: Lead, new: date | None, actor_id: int, why: str | None = None) -> bool:
    old = lead.next_follow_up
    if old == new:
        return False
    lead.next_follow_up = new
    _log(db, lead, actor_id, "follow_up_change",
         f"Next follow-up {old.isoformat() if old else 'none'} to {new.isoformat() if new else 'none'}"
         + (f": {why}" if why else ""))
    return True


# ---------------------------------------------------------------- reads
@router.get("/owners", response_model=list[OwnerOut])
def list_owners(db: Session = Depends(get_db), _=Depends(require("lead:read"))):
    rows = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username)).all()
    return [OwnerOut(id=u.id, username=u.username, role=u.role) for u in rows
            if "lead:write" in role_permissions(db, u)]


@router.get("", response_model=list[LeadOut])
def list_leads(response: Response, owner: str | None = None, status: str | None = None,
               source: str | None = None, from_date: date | None = None,
               to_date: date | None = None,
               due: Literal["overdue", "today", "week", "none"] | None = None, q: str | None = None,
               paging=Depends(page_params), db: Session = Depends(get_db),
               user=Depends(require("lead:read"))):
    today = date.today()
    page, page_size = paging
    stmt = select(Lead)
    if owner:
        oid = user.id if owner == "me" else int(owner) if owner.isdigit() else None
        if oid is None:
            raise HTTPException(422, "owner must be 'me' or a user id")
        stmt = stmt.where(Lead.owner_id == oid)
    if status == "open":
        stmt = stmt.where(Lead.status.in_(OPEN))
    elif status == "closed":
        stmt = stmt.where(Lead.status.in_(CLOSED))
    elif status:
        stmt = stmt.where(Lead.status == status)
    if source:
        stmt = stmt.where(Lead.source == source)
    if from_date:
        stmt = stmt.where(func.date(Lead.created_at) >= from_date)
    if to_date:
        stmt = stmt.where(func.date(Lead.created_at) <= to_date)
    if due:
        stmt = stmt.where(Lead.status.in_(OPEN))
        stmt = {"overdue": stmt.where(Lead.next_follow_up < today),
                "today": stmt.where(Lead.next_follow_up == today),
                "week": stmt.where(Lead.next_follow_up >= today, Lead.next_follow_up <= today + timedelta(days=7)),
                "none": stmt.where(Lead.next_follow_up.is_(None))}[due]
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Lead.name.ilike(like), Lead.company.ilike(like), Lead.lead_no.ilike(like),
                              Lead.phone.ilike(like), Lead.email.ilike(like)))
    stmt = stmt.order_by(case((Lead.status.in_(CLOSED), 1), else_=0),
                         Lead.next_follow_up.asc().nulls_last(), Lead.id.desc())
    return _build(db, paginate(db, stmt, response, page, page_size))


@router.get("/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: int, db: Session = Depends(get_db), _=Depends(require("lead:read"))):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return _detail(db, lead)


# ---------------------------------------------------------------- create / edit
@router.post("", response_model=LeadDetail, status_code=201)
def create_lead(body: LeadIn, db: Session = Depends(get_db), user=Depends(require("lead:write"))):
    owner_id = body.owner_id or user.id
    if owner_id != user.id and "lead:assign" not in role_permissions(db, user):
        raise HTTPException(403, "Only an administrator can assign a lead to someone else")
    owner = _valid_owner(db, owner_id)
    _check_date(body.next_follow_up)
    pk, ek = _phone_key(body.phone), _email_key(body.email)
    _duplicate(db, pk, ek)
    lead = Lead(lead_no=f"LD-{datetime.now():%Y%m%d}-{uuid4().hex[:6].upper()}", name=body.name.strip(),
                company=_blank(body.company), phone=body.phone, email=body.email, phone_key=pk, email_key=ek,
                source=body.source, status="new", owner_id=owner.id, next_follow_up=body.next_follow_up,
                created_by=user.id)
    db.add(lead)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A lead with this phone number or email address already exists")
    _log(db, lead, user.id, "created", f"Lead created for {owner.username} from {body.source}; "
                                       f"first follow-up {body.next_follow_up.isoformat()}")
    if _blank(body.note):
        _log(db, lead, user.id, "note", body.note.strip())
    audit(db, user.id, "lead.create", f"lead:{lead.id}",
          {"lead_no": lead.lead_no, "owner": owner.username, "source": body.source,
           "next_follow_up": body.next_follow_up.isoformat()})
    db.commit()
    return _detail(db, lead)


@router.patch("/{lead_id}", response_model=LeadDetail)
def edit_lead(lead_id: int, body: LeadEditIn, db: Session = Depends(get_db),
              user=Depends(require("lead:write"))):
    lead = _locked(db, lead_id)
    _can_change(db, user, lead)
    sent = body.model_fields_set
    phone = body.phone if "phone" in sent else lead.phone
    email = body.email if "email" in sent else lead.email
    if not phone and not email:
        raise HTTPException(422, "A lead needs a phone number or an email address")
    pk, ek = _phone_key(phone), _email_key(email)
    _duplicate(db, pk, ek, exclude_id=lead.id)
    changed = []
    for f, v in (("name", body.name.strip() if body.name else None),
                 ("company", _blank(body.company)), ("source", body.source)):
        if f in sent and v != getattr(lead, f) and (v is not None or f == "company"):
            setattr(lead, f, v); changed.append(f)
    if phone != lead.phone:
        lead.phone, lead.phone_key = phone, pk; changed.append("phone")
    if email != lead.email:
        lead.email, lead.email_key = email, ek; changed.append("email")
    if not changed:
        raise HTTPException(409, "Nothing changed")
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A lead with this phone number or email address already exists")
    _log(db, lead, user.id, "updated", "Details changed: " + ", ".join(changed))
    audit(db, user.id, "lead.update", f"lead:{lead.id}", {"lead_no": lead.lead_no, "fields": ", ".join(changed)})
    db.commit()
    return _detail(db, lead)


# ---------------------------------------------------------------- activity history
@router.post("/{lead_id}/activities", response_model=LeadDetail, status_code=201)
def add_activity(lead_id: int, body: ActivityIn, db: Session = Depends(get_db),
                 user=Depends(require("lead:write"))):
    lead = _locked(db, lead_id)
    _can_change(db, user, lead)
    closed = lead.status in CLOSED
    contact = body.kind != "note"
    if closed and (contact or body.next_follow_up or body.clear_follow_up):
        raise HTTPException(409, "This lead is closed. Only notes can be added; ask an administrator to reopen it")
    if contact and not body.next_follow_up and not body.clear_follow_up:
        raise HTTPException(422, "Say what happens next: set the next follow-up date, or choose 'no follow-up needed'")
    if body.next_follow_up:
        _check_date(body.next_follow_up, lead.next_follow_up)
    _log(db, lead, user.id, body.kind, body.summary.strip())
    if contact and lead.status == "new":
        lead.status = "contacted"
        _log(db, lead, user.id, "status_change", "Status new to contacted (first contact logged)")
    if body.next_follow_up:
        _set_follow_up(db, lead, body.next_follow_up, user.id)
    elif body.clear_follow_up:
        _set_follow_up(db, lead, None, user.id, "no follow-up needed")
    audit(db, user.id, "lead.activity", f"lead:{lead.id}",
          {"lead_no": lead.lead_no, "kind": body.kind, "status": lead.status,
           "next_follow_up": lead.next_follow_up.isoformat() if lead.next_follow_up else "none"})
    db.commit()
    return _detail(db, lead)


# ---------------------------------------------------------------- status, follow-up, owner
@router.post("/{lead_id}/status", response_model=LeadDetail)
def change_status(lead_id: int, body: StatusIn, db: Session = Depends(get_db),
                  user=Depends(require("lead:write"))):
    lead = _locked(db, lead_id)
    _can_change(db, user, lead)
    cur, new, reason = lead.status, body.status, _blank(body.reason)
    reopen = cur in CLOSED
    if reopen and new in CLOSED:
        raise HTTPException(409, f"Lead is already {cur}")
    if reopen:
        if "lead:assign" not in role_permissions(db, user):
            raise HTTPException(403, "Only an administrator can reopen a closed lead")
        if new != "contacted":
            raise HTTPException(422, "A closed lead can only be reopened as 'contacted'")
        if not reason or len(reason) < 3:
            raise HTTPException(422, "Give a reason for reopening the lead")
        if not body.next_follow_up:
            raise HTTPException(422, "Set a follow-up date when reopening a lead")
        _check_date(body.next_follow_up)
    elif new == cur:
        raise HTTPException(409, f"Lead is already {cur}")
    elif new not in TRANSITIONS[cur]:
        raise HTTPException(409, f"A lead cannot move from {cur} to {new}")
    if new == "lost" and (not reason or len(reason) < 3):
        raise HTTPException(422, "Give the reason the lead was lost")
    had_follow_up = lead.next_follow_up is not None
    lead.status = new
    if new in CLOSED:
        lead.next_follow_up, lead.closed_reason = None, reason
    elif reopen:
        lead.closed_reason, lead.next_follow_up = None, body.next_follow_up
    _log(db, lead, user.id, "status_change",
         f"Status {cur} to {new}" + (f": {reason}" if reason else "")
         + (" (scheduled follow-up cleared)" if new in CLOSED and had_follow_up else ""))
    audit(db, user.id, "lead.status", f"lead:{lead.id}", {"lead_no": lead.lead_no, "from": cur, "to": new})
    db.commit()
    return _detail(db, lead)


@router.post("/{lead_id}/follow-up", response_model=LeadDetail)
def reschedule(lead_id: int, body: FollowUpIn, db: Session = Depends(get_db),
               user=Depends(require("lead:write"))):
    lead = _locked(db, lead_id)
    _can_change(db, user, lead)
    if lead.status in CLOSED:
        raise HTTPException(409, "A closed lead has no follow-up")
    why = _blank(body.reason)
    if body.next_follow_up is None and (not why or len(why) < 3):
        raise HTTPException(422, "Give a reason for clearing the follow-up")
    if body.next_follow_up:
        _check_date(body.next_follow_up, lead.next_follow_up)
    if not _set_follow_up(db, lead, body.next_follow_up, user.id, why):
        raise HTTPException(409, "That is already the follow-up date")
    audit(db, user.id, "lead.followup", f"lead:{lead.id}",
          {"lead_no": lead.lead_no, "next_follow_up": body.next_follow_up.isoformat() if body.next_follow_up else "none"})
    db.commit()
    return _detail(db, lead)


@router.post("/{lead_id}/owner", response_model=LeadDetail)
def reassign(lead_id: int, body: OwnerIn, db: Session = Depends(get_db),
             user=Depends(require("lead:assign"))):
    lead = _locked(db, lead_id)
    new = _valid_owner(db, body.owner_id)
    if new.id == lead.owner_id:
        raise HTTPException(409, "That user already owns this lead")
    old = db.get(User, lead.owner_id)
    lead.owner_id = new.id
    _log(db, lead, user.id, "owner_change",
         f"Owner {old.username if old else '?'} to {new.username}: {body.reason.strip()}")
    audit(db, user.id, "lead.owner", f"lead:{lead.id}",
          {"lead_no": lead.lead_no, "from": old.username if old else "?", "to": new.username})
    db.commit()
    return _detail(db, lead)