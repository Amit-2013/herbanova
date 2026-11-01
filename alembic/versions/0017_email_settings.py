"""SMTP settings and the test-email outbox.

Two tables, no seed row. Until an Administrator saves the form the environment
(`SMTP_*`, `EMAIL_*`) remains authoritative, so applying this migration changes
no behaviour. The outbox keeps every test message, dry run or delivered.

Rollback drops both tables; the application then falls back to the environment
for SMTP and the test screen reports that no message has been recorded.

Revision ID: 0017_email_settings
Revises: 0016_feature_flags
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_email_settings"
down_revision: Union[str, None] = "0016_feature_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mode", sa.String(length=10), nullable=False,
                  server_default="test"),
        sa.Column("host", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("security", sa.String(length=10), nullable=False,
                  server_default="starttls"),
        sa.Column("username", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("password_enc", sa.Text(), nullable=True),
        sa.Column("from_address", sa.String(length=254), nullable=False,
                  server_default=""),
        sa.Column("reply_to", sa.String(length=254), nullable=False, server_default=""),
        sa.Column("test_to", sa.String(length=254), nullable=False, server_default=""),
        sa.Column("test_cc", sa.String(length=254), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.CheckConstraint("id = 1", name="ck_email_settings_singleton"),
        sa.CheckConstraint("mode IN ('test','live')", name="ck_email_settings_mode"),
        sa.CheckConstraint("security IN ('none','starttls','ssl')",
                           name="ck_email_settings_security"),
    )
    op.create_table(
        "email_test_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_type", sa.String(length=20), nullable=False),
        sa.Column("to_addresses", sa.Text(), nullable=False),
        sa.Column("cc_addresses", sa.Text(), nullable=False, server_default=""),
        sa.Column("subject", sa.String(length=250), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "message_type IN ('test','hr_notice','report_notice','custom')",
            name="ck_email_test_messages_type"),
        sa.CheckConstraint("status IN ('captured','sent','failed')",
                           name="ck_email_test_messages_status"),
        sa.CheckConstraint("mode IN ('dry_run','smtp')",
                           name="ck_email_test_messages_mode"),
    )
    op.create_index("ix_email_test_messages_created_at", "email_test_messages",
                    ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_email_test_messages_created_at",
                  table_name="email_test_messages")
    op.drop_table("email_test_messages")
    op.drop_table("email_settings")
