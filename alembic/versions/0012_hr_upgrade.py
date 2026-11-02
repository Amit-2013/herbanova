"""HR upgrade: documents, assets, notifications, letters, period locks, saved
views, import batches, and the columns the new rules need.

Everything is additive. Existing rows keep working because every new column has
a server default. The only seeded content is three empty letter templates built
from placeholders; they contain no employee data.

Revision ID: 0012_hr_upgrade
Revises: 0011_email_reports
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_hr_upgrade"
down_revision: Union[str, None] = "0011_email_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEMPLATES = (
    ("OFFER", "Offer letter", "offer",
     "Dear {employee_name},\n\nWe are pleased to offer you the position of "
     "{designation} in the {department} department at {company_name}. "
     "Your joining date is {joining_date}. This offer is subject to the "
     "company's policies and to the documents requested by Human Resources.\n\n"
     "Please sign and return a copy of this letter to confirm your acceptance.\n\n"
     "For {company_name}\n\nAuthorised signatory"),
    ("APPOINTMENT", "Appointment letter", "appointment",
     "Dear {employee_name},\n\nWith reference to your acceptance of our offer, "
     "we confirm your appointment as {designation} in the {department} "
     "department at {company_name} with effect from {joining_date}. Your "
     "employment is governed by the company's policies in force from time to "
     "time.\n\nFor {company_name}\n\nAuthorised signatory"),
    ("EXPERIENCE", "Experience letter", "experience",
     "To whom it may concern\n\nThis is to certify that {employee_name} ({code}) "
     "was employed with {company_name} as {designation} in the {department} "
     "department from {joining_date} to {exit_date}.\n\nDuring this period "
     "their conduct and performance were found to be satisfactory.\n\nWe wish "
     "them success in future endeavours.\n\nFor {company_name}\n\n"
     "Authorised signatory"),
    ("RELIEVING", "Relieving letter", "relieving",
     "This is to confirm that {employee_name} ({code}) has been relieved of "
     "duties at {company_name} with effect from {exit_date} after completing "
     "the notice period. Company property has been returned and the full and "
     "final settlement will be processed as per company policy.\n\n"
     "For {company_name}\n\nAuthorised signatory"),
)


def upgrade() -> None:
    op.add_column("employees", sa.Column("probation_end_date", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("confirmation_date", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("notice_period_days", sa.Integer(), nullable=True))
    op.add_column("employees", sa.Column("exit_reason", sa.String(200), nullable=True))

    op.add_column("hr_leave_types", sa.Column("encashable", sa.Boolean(), nullable=False,
                                               server_default=sa.text("false")))
    op.add_column("hr_leave_types", sa.Column("max_carry_forward", sa.Numeric(6, 1),
                                               nullable=False, server_default="0"))
    op.add_column("hr_leave_types", sa.Column("half_day_allowed", sa.Boolean(),
                                               nullable=False, server_default=sa.text("true")))

    op.add_column("hr_leave_applications", sa.Column("portion", sa.String(12), nullable=False,
                                                     server_default="full"))
    op.create_check_constraint("ck_hr_leave_portion", "hr_leave_applications",
                               "portion IN ('full','first_half','second_half')")

    op.add_column("hr_attendance", sa.Column("overtime_minutes", sa.Integer(), nullable=False,
                                             server_default="0"))

    op.add_column("hr_salary_components", sa.Column("statutory_head", sa.String(20),
                                                    nullable=True))
    op.create_check_constraint("ck_hr_component_statutory_head", "hr_salary_components",
                               "statutory_head IS NULL OR statutory_head IN ('pf','esi','pt','tds')")

    op.create_table(
        "hr_employee_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("doc_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("number", sa.String(60), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("file_path", sa.String(300), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active','expired','replaced')",
                           name="ck_hr_document_status"),
    )
    op.create_index("ix_hr_employee_documents_employee", "hr_employee_documents",
                    ["employee_id"])
    op.create_index("ix_hr_employee_documents_expiry", "hr_employee_documents",
                    ["expires_on"])

    op.create_table(
        "hr_employee_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("serial_no", sa.String(80), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("returned_on", sa.Date(), nullable=True),
        sa.Column("condition_note", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_hr_employee_assets_employee", "hr_employee_assets", ["employee_id"])

    op.create_table(
        "hr_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column("link", sa.String(200), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_hr_notifications_user", "hr_notifications", ["user_id"])
    op.create_index("ix_hr_notifications_read", "hr_notifications", ["read_at"])

    op.create_table(
        "hr_announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(1000), nullable=False),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "hr_letter_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="uq_hr_letter_template_code"),
        sa.CheckConstraint("kind IN ('offer','appointment','experience','relieving')",
                           name="ck_hr_letter_kind"),
    )

    op.create_table(
        "hr_period_locks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(12), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("locked_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("unlocked_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlock_reason", sa.String(300), nullable=True),
        sa.UniqueConstraint("scope", "year", "month", name="uq_hr_period_lock"),
        sa.CheckConstraint("scope IN ('attendance','payroll')",
                           name="ck_hr_period_lock_scope"),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_hr_period_lock_month"),
    )

    op.create_table(
        "hr_saved_filters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("view", sa.String(30), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "view", "name", name="uq_hr_saved_filter"),
    )

    op.create_table(
        "hr_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="employee"),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="committed"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.CheckConstraint("status IN ('committed','undone')",
                           name="ck_hr_import_status"),
    )

    templates = sa.table(
        "hr_letter_templates",
        sa.column("code", sa.String), sa.column("name", sa.String),
        sa.column("kind", sa.String), sa.column("body", sa.Text))
    op.bulk_insert(templates, [
        {"code": code, "name": name, "kind": kind, "body": body}
        for code, name, kind, body in TEMPLATES
    ])


def downgrade() -> None:
    op.drop_table("hr_import_batches")
    op.drop_table("hr_saved_filters")
    op.drop_table("hr_period_locks")
    op.drop_table("hr_letter_templates")
    op.drop_table("hr_announcements")
    op.drop_index("ix_hr_notifications_read", table_name="hr_notifications")
    op.drop_index("ix_hr_notifications_user", table_name="hr_notifications")
    op.drop_table("hr_notifications")
    op.drop_index("ix_hr_employee_assets_employee", table_name="hr_employee_assets")
    op.drop_table("hr_employee_assets")
    op.drop_index("ix_hr_employee_documents_expiry", table_name="hr_employee_documents")
    op.drop_index("ix_hr_employee_documents_employee", table_name="hr_employee_documents")
    op.drop_table("hr_employee_documents")

    op.drop_constraint("ck_hr_component_statutory_head", "hr_salary_components",
                       type_="check")
    op.drop_column("hr_salary_components", "statutory_head")
    op.drop_column("hr_attendance", "overtime_minutes")
    op.drop_constraint("ck_hr_leave_portion", "hr_leave_applications", type_="check")
    op.drop_column("hr_leave_applications", "portion")
    op.drop_column("hr_leave_types", "half_day_allowed")
    op.drop_column("hr_leave_types", "max_carry_forward")
    op.drop_column("hr_leave_types", "encashable")
    op.drop_column("employees", "exit_reason")
    op.drop_column("employees", "notice_period_days")
    op.drop_column("employees", "confirmation_date")
    op.drop_column("employees", "probation_end_date")
