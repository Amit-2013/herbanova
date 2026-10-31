"""Scheduled email reports: recipient list, schedules and the delivery log.

A delivery row is the durable record of one attempt to send one pack for one
slot. `run_key` is unique, so two workers racing for the same slot cannot both
insert it: the loser's insert fails and it moves on. That is the whole duplicate
protection, and it survives a restart because it lives in the database.

The recipient list is deliberately separate from `users`: the Managing Director
has no login, and an employee's email is not automatically consent to receive
financial reports.
"""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer,
                        String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base

GROUPS = ("md", "admin", "extra")
FIELDS = ("to", "cc", "bcc")
FREQUENCIES = ("daily", "weekdays", "weekly", "monthly", "custom")
MONTH_RULES = ("day", "last_day", "first_working_day")
HOLIDAY_RULES = ("shift", "skip")
STATUSES = ("queued", "sending", "sent", "retry", "failed", "skipped")
TRIGGERS = ("scheduled", "manual", "test", "resend")


class EmailRecipient(Base):
    __tablename__ = "email_recipients"
    __table_args__ = (
        UniqueConstraint("email", name="uq_email_recipients_email"),
        UniqueConstraint("unsubscribe_token", name="uq_email_recipients_token"),
        CheckConstraint("group_key IN ('md','admin','extra')", name="ck_email_recipients_group"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254))          # stored lower-case
    name: Mapped[str | None] = mapped_column(String(120))
    group_key: Mapped[str] = mapped_column(String(10), default="extra", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Only `extra` recipients may use this; MD and Administrator mail is
    # mandatory and is removed only by an Administrator.
    unsubscribe_token: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(),
                                                 onupdate=func.now())


class EmailSchedule(Base):
    __tablename__ = "email_schedules"
    __table_args__ = (
        CheckConstraint("frequency IN ('daily','weekdays','weekly','monthly','custom')",
                        name="ck_email_schedules_frequency"),
        CheckConstraint("holiday_rule IN ('shift','skip')",
                        name="ck_email_schedules_holiday"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    pack_key: Mapped[str] = mapped_column(String(30), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    frequency: Mapped[str] = mapped_column(String(20))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    # ISO weekdays, 0 = Monday. Used by `weekdays` and `weekly`.
    weekdays: Mapped[list] = mapped_column(JSON, default=list)
    # Monthly: `month_rule` decides between a numbered day and the month edge.
    month_day: Mapped[int | None] = mapped_column(Integer)
    month_rule: Mapped[str | None] = mapped_column(String(20))
    # Local "HH:MM" slots; a schedule may send more than once a day.
    times: Mapped[list] = mapped_column(JSON, default=list)
    custom_cron: Mapped[str | None] = mapped_column(String(120))
    holiday_rule: Mapped[str] = mapped_column(String(10), default="shift")
    include_attachments: Mapped[bool] = mapped_column(Boolean, default=True)
    include_accounts: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_reports: Mapped[list] = mapped_column(JSON, default=list)
    # Recipient groups ("md", "admin", "extra") included at send time, so a new
    # Administrator is covered without editing every schedule.
    groups: Mapped[list] = mapped_column(JSON, default=list)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(),
                                                 onupdate=func.now())

    recipients = relationship("EmailScheduleRecipient", lazy="selectin",
                              cascade="all, delete-orphan",
                              back_populates="schedule")


class EmailScheduleRecipient(Base):
    __tablename__ = "email_schedule_recipients"
    __table_args__ = (
        UniqueConstraint("schedule_id", "recipient_id", "field",
                         name="uq_email_schedule_recipients"),
        CheckConstraint("field IN ('to','cc','bcc')", name="ck_email_schedule_recipients_field"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("email_schedules.id",
                                                        ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("email_recipients.id",
                                                         ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(3), default="to")

    schedule = relationship("EmailSchedule", back_populates="recipients")
    recipient = relationship("EmailRecipient", lazy="selectin")


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_email_deliveries_run_key"),
        CheckConstraint("status IN ('queued','sending','sent','retry','failed','skipped')",
                        name="ck_email_deliveries_status"),
        CheckConstraint("trigger IN ('scheduled','manual','test','resend')",
                        name="ck_email_deliveries_trigger"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_key: Mapped[str] = mapped_column(String(80))
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("email_schedules.id",
                                                               ondelete="SET NULL"),
                                                    index=True)
    pack_key: Mapped[str] = mapped_column(String(30))
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled")
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    mode: Mapped[str] = mapped_column(String(8), default="test")
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    subject: Mapped[str | None] = mapped_column(String(250))
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    attachment_bytes: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    schedule = relationship("EmailSchedule", lazy="selectin")
