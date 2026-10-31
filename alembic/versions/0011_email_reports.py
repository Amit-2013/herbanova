"""Scheduled email reports: recipients, schedules, schedule recipients, deliveries.

Four additive tables. Nothing existing is altered except one role key: the
Administrator gains `accounts:reports`, the additive gate for the Accounts
dashboard and its email block. No existing permission is removed or re-scoped.

`email_deliveries.run_key` is unique. It is the duplicate guard: whoever inserts
the row for a slot owns that send, and a second worker (or a restart) loses the
race instead of sending again.

Revision ID: 0011_email_reports
Revises: 0010_comparison_indexes
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_email_reports"
down_revision: Union[str, None] = "0010_comparison_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACCOUNTS_REPORTS = "accounts:reports"


def _grant_accounts_reports(add: bool) -> None:
    bind = op.get_bind()
    roles = sa.table("roles", sa.column("name", sa.String),
                     sa.column("permissions", sa.JSON))
    row = bind.execute(sa.select(roles.c.permissions)
                       .where(roles.c.name == "admin")).first()
    if row is None:
        return
    current = list(row[0] or [])
    if add:
        if ACCOUNTS_REPORTS not in current:
            current.append(ACCOUNTS_REPORTS)
    else:
        current = [k for k in current if k != ACCOUNTS_REPORTS]
    bind.execute(roles.update().where(roles.c.name == "admin")
                 .values(permissions=current))


def upgrade() -> None:
    op.create_table(
        "email_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("group_key", sa.String(10), nullable=False, server_default="extra"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("unsubscribe_token", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_email_recipients_email"),
        sa.UniqueConstraint("unsubscribe_token", name="uq_email_recipients_token"),
        sa.CheckConstraint("group_key IN ('md','admin','extra')",
                           name="ck_email_recipients_group"),
    )
    op.create_index("ix_email_recipients_group_key", "email_recipients", ["group_key"])

    op.create_table(
        "email_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("pack_key", sa.String(30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("weekdays", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("month_day", sa.Integer(), nullable=True),
        sa.Column("month_rule", sa.String(20), nullable=True),
        sa.Column("times", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("custom_cron", sa.String(120), nullable=True),
        sa.Column("holiday_rule", sa.String(10), nullable=False, server_default="shift"),
        sa.Column("include_attachments", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("include_accounts", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("custom_reports", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("groups", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("frequency IN ('daily','weekdays','weekly','monthly','custom')",
                           name="ck_email_schedules_frequency"),
        sa.CheckConstraint("holiday_rule IN ('shift','skip')",
                           name="ck_email_schedules_holiday"),
    )
    op.create_index("ix_email_schedules_pack_key", "email_schedules", ["pack_key"])
    op.create_index("ix_email_schedules_enabled", "email_schedules", ["enabled"])
    op.create_index("ix_email_schedules_next_run_at", "email_schedules", ["next_run_at"])

    op.create_table(
        "email_schedule_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schedule_id", sa.Integer(),
                  sa.ForeignKey("email_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.Integer(),
                  sa.ForeignKey("email_recipients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field", sa.String(3), nullable=False, server_default="to"),
        sa.UniqueConstraint("schedule_id", "recipient_id", "field",
                            name="uq_email_schedule_recipients"),
        sa.CheckConstraint("field IN ('to','cc','bcc')",
                           name="ck_email_schedule_recipients_field"),
    )
    op.create_index("ix_email_schedule_recipients_schedule_id",
                    "email_schedule_recipients", ["schedule_id"])
    op.create_index("ix_email_schedule_recipients_recipient_id",
                    "email_schedule_recipients", ["recipient_id"])

    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_key", sa.String(80), nullable=False),
        sa.Column("schedule_id", sa.Integer(),
                  sa.ForeignKey("email_schedules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pack_key", sa.String(30), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("mode", sa.String(8), nullable=False, server_default="test"),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("subject", sa.String(250), nullable=True),
        sa.Column("recipients", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("attachment_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_key", name="uq_email_deliveries_run_key"),
        sa.CheckConstraint("status IN ('queued','sending','sent','retry','failed','skipped')",
                           name="ck_email_deliveries_status"),
        sa.CheckConstraint("trigger IN ('scheduled','manual','test','resend')",
                           name="ck_email_deliveries_trigger"),
    )
    op.create_index("ix_email_deliveries_schedule_id", "email_deliveries", ["schedule_id"])
    op.create_index("ix_email_deliveries_status", "email_deliveries", ["status"])

    _grant_accounts_reports(add=True)


def downgrade() -> None:
    _grant_accounts_reports(add=False)
    op.drop_index("ix_email_deliveries_status", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_schedule_id", table_name="email_deliveries")
    op.drop_table("email_deliveries")
    op.drop_index("ix_email_schedule_recipients_recipient_id",
                  table_name="email_schedule_recipients")
    op.drop_index("ix_email_schedule_recipients_schedule_id",
                  table_name="email_schedule_recipients")
    op.drop_table("email_schedule_recipients")
    op.drop_index("ix_email_schedules_next_run_at", table_name="email_schedules")
    op.drop_index("ix_email_schedules_enabled", table_name="email_schedules")
    op.drop_index("ix_email_schedules_pack_key", table_name="email_schedules")
    op.drop_table("email_schedules")
    op.drop_index("ix_email_recipients_group_key", table_name="email_recipients")
    op.drop_table("email_recipients")
