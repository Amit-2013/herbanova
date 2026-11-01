"""Branch- and office-based attendance rules, and the HR person responsible for
a branch or office.

Additive only: two nullable columns and one new table. No existing row changes
meaning, and every employee keeps today's behaviour (attendance required,
self-service allowed) until a rule says otherwise.

Revision ID: 0018_attendance_rules
Revises: 0017_email_settings
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_attendance_rules"
down_revision: Union[str, None] = "0017_email_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hr_branches", sa.Column("hr_admin_id", sa.Integer(),
                                           sa.ForeignKey("employees.id"), nullable=True))
    op.add_column("hr_work_locations", sa.Column("hr_admin_id", sa.Integer(),
                                                 sa.ForeignKey("employees.id"), nullable=True))

    op.create_table(
        "hr_attendance_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("hr_branches.id"), nullable=True),
        sa.Column("office_id", sa.Integer(), sa.ForeignKey("hr_work_locations.id"),
                  nullable=True),
        sa.Column("designation", sa.String(80), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("self_service", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("hr_shifts.id"), nullable=True),
        sa.Column("attendance_mode", sa.String(10), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("attendance_mode IS NULL OR attendance_mode IN ('office','gps','both')",
                           name="ck_hr_attendance_rule_mode"),
        sa.CheckConstraint("effective_to IS NULL OR effective_from IS NULL "
                           "OR effective_to >= effective_from",
                           name="ck_hr_attendance_rule_dates"),
    )
    op.create_index("ix_hr_attendance_rules_branch", "hr_attendance_rules", ["branch_id"])
    op.create_index("ix_hr_attendance_rules_office", "hr_attendance_rules", ["office_id"])
    op.create_index("ix_hr_attendance_rules_employee", "hr_attendance_rules", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_hr_attendance_rules_employee", table_name="hr_attendance_rules")
    op.drop_index("ix_hr_attendance_rules_office", table_name="hr_attendance_rules")
    op.drop_index("ix_hr_attendance_rules_branch", table_name="hr_attendance_rules")
    op.drop_table("hr_attendance_rules")
    op.drop_column("hr_work_locations", "hr_admin_id")
    op.drop_column("hr_branches", "hr_admin_id")
