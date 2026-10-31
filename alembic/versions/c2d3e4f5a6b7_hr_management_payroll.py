"""HR management: employee profile, attendance, leave, OD, payroll

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-30 12:00:00.000000

Additive only. Existing employees keep their rows; the new columns are nullable.
Payroll rates are seeded as zero and configured by the Administrator, so no
statutory rate is hardcoded.
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HR_ROLES = {
    "employee": ["hr:read", "hr:attendance_self", "approval:read"],
    "reporting_manager": ["hr:read", "hr:attendance_self", "hr:attendance_manage",
                          "hr:leave_approve", "approval:read"],
    "hr_manager": ["hr:read", "hr:write", "hr:attendance_self", "hr:attendance_manage",
                   "hr:leave_approve", "hr:reports", "hr:confidential", "approval:read"],
    "payroll_officer": ["hr:read", "hr:payroll_prepare", "hr:confidential", "hr:reports",
                        "approval:read"],
}


def _money():
    return sa.Numeric(14, 2)


def upgrade() -> None:
    op.create_table(
        "hr_branches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(300)),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.create_index("ix_hr_branches_code", "hr_branches", ["code"])

    op.create_table(
        "hr_departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.create_table(
        "hr_shifts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("start_time", sa.Time(), nullable=False, server_default="09:00"),
        sa.Column("end_time", sa.Time(), nullable=False, server_default="18:00"),
        sa.Column("grace_minutes", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("full_day_hours", sa.Numeric(6, 2), nullable=False, server_default="8"),
        sa.Column("half_day_hours", sa.Numeric(6, 2), nullable=False, server_default="4"),
        sa.Column("weekly_offs", sa.JSON(), nullable=False, server_default=json.dumps([5, 6])),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.create_table(
        "hr_work_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("hr_branches.id")),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(300)),
        sa.Column("latitude", sa.Numeric(9, 6)),
        sa.Column("longitude", sa.Numeric(9, 6)),
        sa.Column("geofence_radius_m", sa.Integer(), server_default="200"),
        sa.Column("attendance_mode", sa.String(10), nullable=False, server_default="office"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.CheckConstraint("latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
                           name="ck_hr_lat"),
        sa.CheckConstraint("longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
                           name="ck_hr_lon"),
        sa.CheckConstraint("geofence_radius_m IS NULL OR geofence_radius_m > 0",
                           name="ck_hr_radius"),
        sa.CheckConstraint("attendance_mode IN ('office','gps','both')", name="ck_hr_mode"),
    )
    op.create_index("ix_hr_work_locations_code", "hr_work_locations", ["code"])
    op.create_table(
        "hr_holidays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("hr_branches.id")),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("hr_work_locations.id")),
        sa.UniqueConstraint("date", "name", name="uq_hr_holiday"),
    )
    op.create_index("ix_hr_holidays_date", "hr_holidays", ["date"])

    emp = "employees"
    for name, typ in [
        ("branch_id", sa.Integer()), ("office_id", sa.Integer()),
        ("department_id", sa.Integer()), ("shift_id", sa.Integer()),
        ("employment_type", sa.String(30)), ("work_schedule", sa.String(80)),
        ("date_of_exit", sa.Date()), ("photo_path", sa.String(300)),
        ("address", sa.String(300)), ("emergency_name", sa.String(120)),
        ("emergency_phone", sa.String(40)), ("bank_name", sa.String(120)),
        ("bank_account_no", sa.String(30)), ("bank_ifsc", sa.String(11)),
        ("pan", sa.String(10)), ("uan", sa.String(20)), ("esi_no", sa.String(20)),
        ("attendance_policy", sa.String(80)), ("leave_policy", sa.String(80)),
    ]:
        op.add_column(emp, sa.Column(name, typ, nullable=True))
    for name, target in [("branch_id", "hr_branches"), ("office_id", "hr_work_locations"),
                         ("department_id", "hr_departments"), ("shift_id", "hr_shifts")]:
        op.create_foreign_key(f"fk_employees_{name}", emp, target, [name], ["id"])
    op.add_column(emp, sa.Column("hr_admin_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_employees_hr_admin", emp, emp, ["hr_admin_id"], ["id"])

    op.create_table(
        "hr_attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="present"),
        sa.Column("check_in", sa.DateTime(timezone=True)),
        sa.Column("check_out", sa.DateTime(timezone=True)),
        sa.Column("office_id", sa.Integer(), sa.ForeignKey("hr_work_locations.id")),
        sa.Column("source", sa.String(10), nullable=False, server_default="web"),
        sa.Column("latitude", sa.Numeric(9, 6)),
        sa.Column("longitude", sa.Numeric(9, 6)),
        sa.Column("geofence_result", sa.String(12), nullable=False, server_default="na"),
        sa.Column("late_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("early_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worked_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remarks", sa.String(300)),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.UniqueConstraint("employee_id", "date", name="uq_hr_attendance_employee_date"),
        sa.CheckConstraint(
            "status IN ('present','absent','half_day','weekly_off','holiday','paid_leave',"
            "'unpaid_leave','od','late','early_departure','correction_pending')",
            name="ck_hr_attendance_status"),
        sa.CheckConstraint("source IN ('web','office','gps','manual','system')",
                           name="ck_hr_attendance_source"),
        sa.CheckConstraint("geofence_result IN ('inside','outside','unavailable','manual','na')",
                           name="ck_hr_geofence_result"),
    )
    op.create_index("ix_hr_attendance_employee", "hr_attendance", ["employee_id"])
    op.create_index("ix_hr_attendance_date", "hr_attendance", ["date"])

    op.create_table(
        "hr_attendance_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attendance_id", sa.Integer(), sa.ForeignKey("hr_attendance.id"),
                  nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("old_status", sa.String(20)),
        sa.Column("new_status", sa.String(20)),
        sa.Column("old_check_in", sa.DateTime(timezone=True)),
        sa.Column("new_check_in", sa.DateTime(timezone=True)),
        sa.Column("old_check_out", sa.DateTime(timezone=True)),
        sa.Column("new_check_out", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("remarks", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
    )
    op.create_index("ix_hr_attendance_corrections_employee", "hr_attendance_corrections",
                    ["employee_id"])
    op.create_index("ix_hr_attendance_corrections_attendance", "hr_attendance_corrections",
                    ["attendance_id"])

    op.create_table(
        "hr_leave_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="paid"),
        sa.Column("requires_document", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("default_days", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("carry_forward", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("kind IN ('paid','unpaid')", name="ck_hr_leave_kind"),
    )
    op.create_table(
        "hr_leave_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("leave_type_id", sa.Integer(), sa.ForeignKey("hr_leave_types.id"),
                  nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("entitled", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("used", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("pending", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("carried", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.UniqueConstraint("employee_id", "leave_type_id", "year",
                            name="uq_hr_leave_balance"),
    )
    op.create_index("ix_hr_leave_balances_employee", "hr_leave_balances", ["employee_id"])
    op.create_table(
        "hr_leave_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("leave_type_id", sa.Integer(), sa.ForeignKey("hr_leave_types.id"),
                  nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("days", sa.Numeric(6, 1), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("document", sa.String(300)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("remarks", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint("status IN ('pending','approved','rejected','cancelled')",
                           name="ck_hr_leave_status"),
        sa.CheckConstraint("date_to >= date_from", name="ck_hr_leave_dates"),
    )
    op.create_index("ix_hr_leave_applications_employee", "hr_leave_applications",
                    ["employee_id"])

    op.create_table(
        "hr_od_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("duration", sa.String(20), nullable=False, server_default="full_day"),
        sa.Column("visit_type", sa.String(40), nullable=False),
        sa.Column("purpose", sa.String(300), nullable=False),
        sa.Column("party_type", sa.String(20)),
        sa.Column("party_name", sa.String(150)),
        sa.Column("worksite", sa.String(150)),
        sa.Column("destination", sa.String(200)),
        sa.Column("manager_id", sa.Integer(), sa.ForeignKey("employees.id")),
        sa.Column("document", sa.String(300)),
        sa.Column("remarks", sa.String(300)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("regularisation", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_remarks", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint("status IN ('pending','approved','rejected','cancelled')",
                           name="ck_hr_od_status"),
    )
    op.create_index("ix_hr_od_requests_employee", "hr_od_requests", ["employee_id"])
    op.create_index("ix_hr_od_requests_date", "hr_od_requests", ["date"])

    op.create_table(
        "hr_approval_workflows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_type", sa.String(30), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approver_role", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("request_type", "level", name="uq_hr_workflow"),
    )

    op.create_table(
        "hr_salary_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("calc_type", sa.String(20), nullable=False, server_default="fixed"),
        sa.Column("default_rate", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("taxable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("statutory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("kind IN ('earning','deduction')", name="ck_hr_component_kind"),
        sa.CheckConstraint("calc_type IN ('fixed','percent_basic','percent_gross')",
                           name="ck_hr_component_calc"),
    )
    op.create_table(
        "hr_salary_structures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("payment_mode", sa.String(20), nullable=False, server_default="bank"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
    )
    op.create_index("ix_hr_salary_structures_employee", "hr_salary_structures",
                    ["employee_id"])
    op.create_table(
        "hr_salary_structure_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("structure_id", sa.Integer(),
                  sa.ForeignKey("hr_salary_structures.id"), nullable=False),
        sa.Column("component_id", sa.Integer(),
                  sa.ForeignKey("hr_salary_components.id"), nullable=False),
        sa.Column("amount", _money(), nullable=False, server_default="0"),
        sa.Column("percent", sa.Numeric(6, 2)),
        sa.UniqueConstraint("structure_id", "component_id", name="uq_hr_structure_component"),
    )

    op.create_table(
        "hr_payroll_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("prepared_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("prepared_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.String(300)),
        sa.UniqueConstraint("year", "month", name="uq_hr_payroll_period"),
        sa.CheckConstraint("status IN ('draft','under_review','approved','processed','paid')",
                           name="ck_hr_payroll_period_status"),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_hr_payroll_month"),
    )
    op.create_table(
        "hr_payroll_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period_id", sa.Integer(), sa.ForeignKey("hr_payroll_periods.id"),
                  nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("working_days", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("payable_days", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("present_days", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("paid_leave_days", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("lop_days", sa.Numeric(6, 1), nullable=False, server_default="0"),
        sa.Column("gross", _money(), nullable=False, server_default="0"),
        sa.Column("deductions", _money(), nullable=False, server_default="0"),
        sa.Column("net", _money(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("note", sa.String(300)),
        sa.UniqueConstraint("period_id", "employee_id", name="uq_hr_payroll_entry"),
    )
    op.create_index("ix_hr_payroll_entries_employee", "hr_payroll_entries", ["employee_id"])
    op.create_table(
        "hr_payroll_entry_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("hr_payroll_entries.id"),
                  nullable=False),
        sa.Column("component_id", sa.Integer(), sa.ForeignKey("hr_salary_components.id")),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("amount", _money(), nullable=False, server_default="0"),
        sa.Column("basis", sa.String(200)),
    )
    op.create_table(
        "hr_payroll_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period_id", sa.Integer(), sa.ForeignKey("hr_payroll_periods.id"),
                  nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id")),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("old_net", _money()),
        sa.Column("new_net", _money()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
    )

    # ---- seed configurable rows (idempotent; no rates are assumed)
    bind = op.get_bind()
    roles = sa.table("roles", sa.column("name", sa.String), sa.column("display_name", sa.String),
                     sa.column("is_system", sa.Boolean), sa.column("permissions", sa.JSON))
    labels = {"employee": "Employee", "reporting_manager": "Reporting Manager",
              "hr_manager": "HR Manager", "payroll_officer": "Payroll Officer"}
    for name, perms in HR_ROLES.items():
        found = bind.execute(sa.select(roles.c.name).where(roles.c.name == name)).first()
        if found is None:
            bind.execute(roles.insert().values(name=name, display_name=labels[name],
                                               is_system=True, permissions=perms))

    leave_types = sa.table("hr_leave_types", sa.column("code", sa.String),
                           sa.column("name", sa.String), sa.column("kind", sa.String),
                           sa.column("default_days", sa.Numeric(6, 1)))
    for code, name, kind, days in [("CL", "Casual Leave", "paid", 12), ("SL", "Sick Leave", "paid", 8),
                                   ("EL", "Earned / Privilege Leave", "paid", 15),
                                   ("COMP_OFF", "Compensatory Off", "paid", 0),
                                   ("LWP", "Unpaid Leave", "unpaid", 0)]:
        if not bind.execute(sa.select(leave_types.c.code).where(leave_types.c.code == code)).first():
            bind.execute(leave_types.insert().values(code=code, name=name, kind=kind,
                                                     default_days=days))

    workflows = sa.table("hr_approval_workflows", sa.column("request_type", sa.String),
                         sa.column("level", sa.Integer), sa.column("approver_role", sa.String),
                         sa.column("active", sa.Boolean))
    for rtype, role in [("hr_leave", "reporting_manager"), ("hr_od", "reporting_manager"),
                        ("hr_attendance_correction", "hr_manager"),
                        ("hr_geofence_exception", "hr_manager"),
                        ("hr_payroll", "admin"), ("hr_salary_revision", "admin")]:
        if not bind.execute(sa.select(workflows.c.request_type)
                            .where(workflows.c.request_type == rtype)).first():
            bind.execute(workflows.insert().values(request_type=rtype, level=1,
                                                   approver_role=role, active=True))

    comps = sa.table("hr_salary_components", sa.column("code", sa.String),
                     sa.column("name", sa.String), sa.column("kind", sa.String),
                     sa.column("calc_type", sa.String), sa.column("statutory", sa.Boolean),
                     sa.column("sort_order", sa.Integer))
    for code, name, kind, calc, statutory, order in [
        ("BASIC", "Basic salary", "earning", "fixed", False, 10),
        ("HRA", "House rent allowance", "earning", "fixed", False, 20),
        ("CONVEYANCE", "Conveyance", "earning", "fixed", False, 30),
        ("OTHER_ALLOW", "Other allowances", "earning", "fixed", False, 40),
        ("INCENTIVE", "Incentive / commission", "earning", "fixed", False, 50),
        ("OVERTIME", "Overtime", "earning", "fixed", False, 60),
        ("PF", "Provident fund", "deduction", "percent_basic", True, 70),
        ("ESI", "Employee state insurance", "deduction", "percent_gross", True, 80),
        ("TDS", "Tax deducted at source", "deduction", "percent_gross", True, 90),
        ("PROF_TAX", "Professional tax", "deduction", "fixed", True, 100),
        ("OTHER_DED", "Other deductions", "deduction", "fixed", False, 110),
    ]:
        if not bind.execute(sa.select(comps.c.code).where(comps.c.code == code)).first():
            bind.execute(comps.insert().values(code=code, name=name, kind=kind, calc_type=calc,
                                               statutory=statutory, sort_order=order))


def downgrade() -> None:
    for name in ("ix_hr_payroll_entries_employee", "ix_hr_salary_structures_employee",
                 "ix_hr_od_requests_date", "ix_hr_od_requests_employee",
                 "ix_hr_leave_applications_employee", "ix_hr_leave_balances_employee",
                 "ix_hr_attendance_corrections_attendance",
                 "ix_hr_attendance_corrections_employee", "ix_hr_attendance_date",
                 "ix_hr_attendance_employee", "ix_hr_holidays_date",
                 "ix_hr_work_locations_code", "ix_hr_branches_code"):
        op.drop_index(name)
    op.drop_table("hr_payroll_corrections")
    op.drop_table("hr_payroll_entry_lines")
    op.drop_table("hr_payroll_entries")
    op.drop_table("hr_payroll_periods")
    op.drop_table("hr_salary_structure_lines")
    op.drop_table("hr_salary_structures")
    op.drop_table("hr_salary_components")
    op.drop_table("hr_approval_workflows")
    op.drop_table("hr_od_requests")
    op.drop_table("hr_leave_applications")
    op.drop_table("hr_leave_balances")
    op.drop_table("hr_leave_types")
    op.drop_table("hr_attendance_corrections")
    op.drop_table("hr_attendance")
    for name in ("branch_id", "office_id", "department_id", "shift_id", "hr_admin_id",
                 "employment_type", "work_schedule", "date_of_exit", "photo_path", "address",
                 "emergency_name", "emergency_phone", "bank_name", "bank_account_no",
                 "bank_ifsc", "pan", "uan", "esi_no", "attendance_policy", "leave_policy"):
        op.drop_column("employees", name)
    op.drop_table("hr_holidays")
    op.drop_table("hr_work_locations")
    op.drop_table("hr_shifts")
    op.drop_table("hr_departments")
    op.drop_table("hr_branches")
