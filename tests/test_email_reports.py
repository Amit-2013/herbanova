"""Scheduled reports: pack figures, email content, test mode and the worker.

The worker tests are the executable form of three promises:
  * a slot is sent once, even if two workers or a restart race for it;
  * a transient failure is retried three times with increasing delay;
  * a failure that retrying cannot fix stops at once and alerts.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.core import User
from app.models.email import (EmailDelivery, EmailRecipient, EmailSchedule,
                              EmailScheduleRecipient)
from app.services import email_render, email_worker, mailer, report_packs
from test_dashboard_v2 import _invoice

UTC = timezone.utc
TODAY = date.today()


# --- packs -----------------------------------------------------------------

def test_period_rules_are_fixed_by_the_pack_and_the_run_date():
    assert report_packs.period_for("daily", date(2026, 11, 5))["from"] \
        == report_packs.period_for("daily", date(2026, 11, 5))["to"] == date(2026, 11, 4)
    week = report_packs.period_for("weekly", date(2026, 11, 5))
    assert (week["from"], week["to"]) == (date(2026, 10, 29), date(2026, 11, 4))
    # Monthly on the first week reports the completed month, later it is MTD.
    assert report_packs.period_for("monthly_md", date(2026, 11, 5))["from"] == date(2026, 10, 1)
    assert report_packs.period_for("monthly_md", date(2026, 11, 5))["to"] == date(2026, 10, 31)
    assert report_packs.period_for("monthly_md", date(2026, 11, 20))["to"] == date(2026, 11, 20)


def test_pack_figures_match_the_dashboard_for_the_same_dates(client, world):
    day = TODAY - timedelta(days=1)
    grand = Decimal("4321.00")
    _invoice(world, day, grand)

    with SessionLocal() as db:
        data = report_packs.build(db, "daily", day, day)
    dash = client.as_user("admin").get(
        "/api/dashboard", params={"from_date": day.isoformat(), "to_date": day.isoformat()})
    assert dash.status_code == 200, dash.text
    sales_kpi = next(k for k in data["kpis"] if k["key"] == "sales")
    dash_sales = dash.json()["sales_vs_purchases"]["sales_total"]
    assert Decimal(str(sales_kpi["value"])) == Decimal(str(dash_sales))
    assert sales_kpi["display"] == report_packs._inr(Decimal(str(dash_sales)))


def test_missing_inputs_are_marked_and_never_invented(client, world):
    # A month with no payroll period at all, so the gaps are the subject of the
    # test rather than whatever the current month happens to hold.
    day = date(2001, 2, 15)
    with SessionLocal() as db:
        data = report_packs.build(db, "daily", day, day)
    # Cost is captured, so gross profit is printed (partial or complete);
    # net profit still has no input for expenses and payroll.
    gross = next(k for k in data["kpis"] if k["key"] == "gross_margin")
    assert gross["available"] is True
    assert gross["display"].startswith("₹")
    assert not gross["gap"]
    net = next(k for k in data["kpis"] if k["key"] == "net_profit")
    assert net["available"] is False
    assert net["display"] == "No data yet"
    assert net["gap"]
    codes = {gap["code"] for gap in data["gaps"]}
    assert {"GAP-P02", "GAP-P03"} <= codes
    assert not {"GAP-A01", "GAP-A02"} & codes
    assert data["accounts"]["trial_balance"]["balanced"] is True


# --- rendering -------------------------------------------------------------

def _pack(db, day):
    data = report_packs.build(db, "daily", day, day)
    data["include_attachments"] = True
    attachments = report_packs.build_attachments(db, data, "daily")
    return data, attachments


def test_html_and_plain_text_carry_the_same_figures_and_the_test_marker(world):
    day = TODAY - timedelta(days=1)
    _invoice(world, day, Decimal("2500.00"))
    with SessionLocal() as db:
        data, attachments = _pack(db, day)
        rendered = email_render.render(data, attachments, mode="test",
                                       test_recipient="admin@example.test",
                                       real_recipients=3, owner="admin")
    assert "TEST MODE" in rendered["html"]
    assert "admin@example.test" in rendered["text"]
    assert rendered["subject"].startswith("[TEST] HERBANOVA |")
    assert "Sales" in rendered["subject"]
    sales = next(k for k in data["kpis"] if k["key"] == "sales")
    assert sales["display"] in rendered["text"]
    # Cost is captured now: gross profit is printed (partial while the invoice
    # has no issue), and net profit still says No data yet rather than guessing.
    assert "Gross profit" in rendered["text"]
    assert "Net profit: No data yet" in rendered["text"]
    assert "cid:sales_chart" in rendered["html"]                    # inline PNG chart
    assert "The same figures are in the table below" in rendered["html"]
    assert "View full dashboard" in rendered["html"]
    # Table-based, no scripts, no remote images.
    assert "<script" not in rendered["html"].lower()
    assert 'src="http' not in rendered["html"]


def test_attachments_are_named_for_the_reader_and_fit_the_budget(world):
    day = TODAY - timedelta(days=1)
    with SessionLocal() as db:
        data, attachments = _pack(db, day)
    kinds = {a["kind"] for a in attachments}
    assert {"summary", "detail"} <= kinds
    for item in attachments:
        assert item["filename"].startswith("HERBANOVA_")
        assert len(item["bytes"]) > 0
    assert sum(len(a["bytes"]) for a in attachments) <= settings.email_max_bytes


def test_accounts_block_and_gaps_appear_in_the_email(client, world):
    day = TODAY - timedelta(days=1)
    with SessionLocal() as db:
        data, attachments = _pack(db, day)
        rendered = email_render.render(data, attachments, mode="live")
    assert "Accounts" in rendered["html"]
    assert "Trial balance" in rendered["html"]
    assert "closing balance is on the balance sheet" in rendered["html"]
    assert "No data yet" in rendered["html"]


def _stray_table_blocks(html: str) -> list[str]:
    """Elements a browser would hoist out of a table because they are not rows."""
    from html.parser import HTMLParser

    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}
    allowed = {"tr", "thead", "tbody", "tfoot", "caption", "colgroup", "col"}
    stray: list[str] = []
    stack: list[str] = []

    class Strict(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if stack and stack[-1] == "table" and tag not in allowed | void:
                stray.append(tag)
            if tag not in void:
                stack.append(tag)

        def handle_startendtag(self, tag, attrs):
            if stack and stack[-1] == "table" and tag not in allowed:
                stray.append(tag)

        def handle_endtag(self, tag):
            if tag in void:
                return
            if tag in stack:
                while stack and stack.pop() != tag:
                    pass

    Strict().feed(html)
    return stray


def test_every_email_block_sits_inside_a_table_row(world):
    """A div or heading placed directly in a table is hoisted by the browser and
    by some mail clients, which had moved the Accounts heading above the header."""
    day = TODAY - timedelta(days=1)
    with SessionLocal() as db:
        data, attachments = _pack(db, day)
    rendered = email_render.render(data, attachments, mode="preview")
    assert _stray_table_blocks(rendered["html"]) == []


# --- recipients and test mode ---------------------------------------------

def test_test_mode_redirects_to_one_address_and_fails_closed(world, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "test")
    monkeypatch.setattr(settings, "email_send_enabled", False)
    monkeypatch.setattr(settings, "email_test_recipient", "admin@example.test")
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule())
        people = mailer.resolve(db, schedule_obj)
        assert people["redirected"] is True
        assert people["to"] == ["admin@example.test"]
        db.rollback()

    monkeypatch.setattr(settings, "email_test_recipient", "")
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule())
        # No administrator employee email in this fixture, so nothing may be sent.
        with pytest.raises(mailer.MailError):
            mailer.resolve(db, schedule_obj)
        db.rollback()


def test_live_mode_refuses_a_schedule_without_recipients(world, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "live")
    monkeypatch.setattr(settings, "email_send_enabled", True)
    with SessionLocal() as db:
        schedule_obj = _schedule()
        db.add(schedule_obj)
        db.flush()
        with pytest.raises(mailer.MailError, match="no active recipients"):
            mailer.resolve(db, schedule_obj)
        db.rollback()


def test_live_mode_uses_explicit_and_group_recipients(world, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "live")
    monkeypatch.setattr(settings, "email_send_enabled", True)
    suffix = uuid4().hex[:6]
    with SessionLocal() as db:
        md = EmailRecipient(email=f"md-{suffix}@example.test", group_key="md",
                            active=True, unsubscribe_token=uuid4().hex)
        cc = EmailRecipient(email=f"cc-{suffix}@example.test", group_key="extra",
                            active=True, unsubscribe_token=uuid4().hex)
        gone = EmailRecipient(email=f"gone-{suffix}@example.test", group_key="md",
                              active=False, unsubscribe_token=uuid4().hex)
        db.add_all([md, cc, gone])
        db.flush()
        schedule_obj = _add(db, _schedule(groups=["md"]))
        db.add(EmailScheduleRecipient(schedule_id=schedule_obj.id, recipient_id=cc.id,
                                      field="cc"))
        db.flush()
        people = mailer.resolve(db, schedule_obj)
        assert people["redirected"] is False
        assert md.email in people["to"]
        assert cc.email in people["cc"]
        assert gone.email not in people["to"] + people["cc"] + people["bcc"]
        db.rollback()


# --- worker ----------------------------------------------------------------

def _schedule(**overrides):
    suffix = uuid4().hex[:6]
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "admin"))
        values = dict(name=f"Test schedule {suffix}", pack_key="daily", enabled=True,
                      frequency="daily", timezone="Asia/Kolkata", weekdays=[],
                      month_day=None, month_rule=None, times=["09:00"], custom_cron=None,
                      holiday_rule="shift", include_attachments=False,
                      include_accounts=True, custom_reports=[], groups=[],
                      next_run_at=None, created_by=actor.id)
        values.update(overrides)
        return EmailSchedule(**values)


def _add(db, schedule_obj):
    db.add(schedule_obj)
    db.flush()
    return schedule_obj


def test_a_slot_is_enqueued_once_and_the_next_run_moves_past_it(world, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "test")
    monkeypatch.setattr(settings, "email_send_enabled", False)
    slot = datetime(2026, 11, 2, 3, 30, tzinfo=UTC)         # Monday 09:00 IST
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule(next_run_at=slot))
        db.commit()
        schedule_id = schedule_obj.id

        assert email_worker.enqueue_due(db, slot + timedelta(seconds=1)) == 1
        assert email_worker.enqueue_due(db, slot + timedelta(seconds=2)) == 0
        rows = db.scalars(select(EmailDelivery).where(
            EmailDelivery.schedule_id == schedule_id)).all()
        assert len(rows) == 1
        assert rows[0].run_key == f"schedule:{schedule_id}:20261102T033000Z"
        db.refresh(schedule_obj)
        assert schedule_obj.next_run_at == slot + timedelta(days=1)
        db.delete(schedule_obj)
        db.commit()


def test_a_schedule_with_no_next_run_is_committed_even_when_nothing_is_due(world):
    """The backfill itself must be committed, not only a slot that fired."""
    slot = datetime(2026, 11, 2, 3, 30, tzinfo=UTC)         # Monday 09:00 IST
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule(next_run_at=None))
        db.commit()
        schedule_id = schedule_obj.id
        assert email_worker.enqueue_due(db, slot) == 0
        db.expire_all()
        stored = db.get(EmailSchedule, schedule_id)
        assert stored.next_run_at == slot + timedelta(days=1)
        db.delete(stored)
        db.commit()


def test_two_workers_cannot_create_the_same_delivery(world):
    slot = datetime(2026, 11, 2, 3, 30, tzinfo=UTC)
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule())
        first, made_first = email_worker.create_delivery(db, schedule_obj, slot)
        second, made_second = email_worker.create_delivery(db, schedule_obj, slot)
        assert made_first is True and made_second is False
        assert first is second
        db.rollback()


def _claimed_delivery(monkeypatch, schedule_obj, trigger="manual"):
    monkeypatch.setattr(settings, "email_mode", "test")
    monkeypatch.setattr(settings, "email_send_enabled", False)
    monkeypatch.setattr(settings, "email_test_recipient", "admin@example.test")
    with SessionLocal() as db:
        delivery, _ = email_worker.create_delivery(db, schedule_obj, datetime.now(UTC),
                                                   trigger)
        db.commit()
        return delivery.id


def test_a_send_records_the_delivery_and_the_audit_row(world, monkeypatch):
    sent = {}

    def fake_send(db, schedule_obj, rendered, people):
        sent["subject"] = rendered["subject"]
        sent["people"] = people
        sent["html"] = rendered["html"]
        return {"size": len(rendered["html"].encode()), "to": 1, "cc": 0, "bcc": 0}

    monkeypatch.setattr(mailer, "send", fake_send)
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule())
        db.commit()
        delivery_id = _claimed_delivery(monkeypatch, schedule_obj)
        email_worker.process_due(db, datetime.now(UTC))
        delivery = db.get(EmailDelivery, delivery_id)
        assert delivery.status == "sent"
        assert delivery.mode == "test"
        assert delivery.recipient_count == 1
        assert delivery.recipients == ["admin@example.test"]
        assert delivery.period_from is not None
        assert sent["people"]["to"] == ["admin@example.test"]
        db.delete(schedule_obj)
        db.commit()


def test_a_transient_failure_is_retried_then_fails_after_four_attempts(world, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "test")
    monkeypatch.setattr(settings, "email_send_enabled", False)
    monkeypatch.setattr(settings, "email_test_recipient", "admin@example.test")
    alerts = []
    monkeypatch.setattr(email_worker.telegram, "notify_text", alerts.append)

    def broken(*args, **kwargs):
        raise mailer.MailError("SMTP delivery failed: ConnectionRefusedError: refused")

    monkeypatch.setattr(mailer, "send", broken)
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule())
        db.commit()
        now = datetime.now(UTC)
        delivery, _ = email_worker.create_delivery(db, schedule_obj, now, "manual")
        db.commit()

        states = []
        for attempt in range(4):
            email_worker.process_due(db, now)
            db.refresh(delivery)
            states.append((delivery.status, delivery.attempts, delivery.next_attempt_at))
            now += timedelta(minutes=60)                # past every retry delay
        assert [s[0] for s in states] == ["retry", "retry", "retry", "failed"]
        assert [s[1] for s in states] == [1, 2, 3, 4]
        assert states[0][2] is not None
        assert len(alerts) == 1                         # one alert, at the end
        db.delete(schedule_obj)
        db.commit()


def test_a_permanent_failure_stops_at_once(world, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "test")
    monkeypatch.setattr(settings, "email_send_enabled", False)
    alerts = []
    monkeypatch.setattr(email_worker.telegram, "notify_text", alerts.append)

    def no_address(*args, **kwargs):
        raise mailer.MailError("SMTP is not configured (SMTP_HOST and SMTP_FROM are required).")

    monkeypatch.setattr(mailer, "send", no_address)
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule())
        db.commit()
        delivery, _ = email_worker.create_delivery(db, schedule_obj, datetime.now(UTC),
                                                   "manual")
        db.commit()
        email_worker.process_due(db, datetime.now(UTC))
        db.refresh(delivery)
        assert delivery.status == "failed"
        assert delivery.attempts == 1
        assert len(alerts) == 1
        db.delete(schedule_obj)
        db.commit()


def test_a_paused_schedule_is_skipped_not_sent(world, monkeypatch):
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule(enabled=False))
        db.commit()
        delivery, _ = email_worker.create_delivery(db, schedule_obj, datetime.now(UTC),
                                                   "scheduled")
        db.commit()
        email_worker.process_due(db, datetime.now(UTC))
        db.refresh(delivery)
        assert delivery.status == "skipped"
        db.delete(schedule_obj)
        db.commit()


def test_a_stale_claim_is_released(world):
    with SessionLocal() as db:
        schedule_obj = _add(db, _schedule())
        db.commit()
        delivery, _ = email_worker.create_delivery(db, schedule_obj, datetime.now(UTC))
        delivery.status = "sending"
        delivery.started_at = datetime.now(UTC) - timedelta(minutes=45)
        db.commit()
        assert email_worker.recover_stale(db) == 1
        db.refresh(delivery)
        assert delivery.status == "retry"
        db.delete(schedule_obj)
        db.commit()
