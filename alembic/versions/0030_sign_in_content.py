"""Sign-in page content: banners, notices, help-line contacts and legal pages.

Additive only: four new tables and two seeded legal rows. Nothing existing is
altered.

- `sign_in_banners` holds one uploaded image per promotion. The file name is
  stored, never a path, so the API controls the directory the image is served
  from.
- `sign_in_notices` carries the date and title the sign-in screen shows below
  the banner.
- `sign_in_contacts` holds the help-line boxes (Sales, Service, Customer
  Support); an Administrator edits the values, and the page shows an empty box
  rather than inventing a number.
- `legal_documents` is addressed by key (`privacy`, `terms`). The two rows are
  inserted unpublished with a null body so the footer links always resolve;
  each one stays "Not published yet" until an Administrator writes its text.

The downgrade drops the four tables. A banner image file left on disk is not
deleted here: removing a file is an operator action, not a schema rollback.

Revision ID: 0030_sign_in_content
Revises: 0029_totp
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_sign_in_content"
down_revision: Union[str, None] = "0029_totp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGAL_ROWS = (
    {"key": "privacy", "title": "Privacy Policy", "published": False},
    {"key": "terms", "title": "Terms & Conditions", "published": False},
)


def upgrade() -> None:
    op.create_table(
        "sign_in_banners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("image_path", sa.String(length=120), nullable=False),
        sa.Column("link_url", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_sign_in_banners_sort_order", "sign_in_banners", ["sort_order"])
    op.create_index("ix_sign_in_banners_active", "sign_in_banners", ["active"])

    op.create_table(
        "sign_in_notices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("notice_date", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_sign_in_notices_notice_date", "sign_in_notices", ["notice_date"])
    op.create_index("ix_sign_in_notices_active", "sign_in_notices", ["active"])

    op.create_table(
        "sign_in_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("detail", sa.String(length=160), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("email", sa.String(length=160), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_sign_in_contacts_sort_order", "sign_in_contacts", ["sort_order"])
    op.create_index("ix_sign_in_contacts_active", "sign_in_contacts", ["active"])

    op.create_table(
        "legal_documents",
        sa.Column("key", sa.String(length=20), primary_key=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    table = sa.table("legal_documents",
                     sa.column("key", sa.String), sa.column("title", sa.String),
                     sa.column("published", sa.Boolean))
    op.bulk_insert(table, [dict(row) for row in LEGAL_ROWS])


def downgrade() -> None:
    op.drop_table("legal_documents")
    op.drop_index("ix_sign_in_contacts_active", table_name="sign_in_contacts")
    op.drop_index("ix_sign_in_contacts_sort_order", table_name="sign_in_contacts")
    op.drop_table("sign_in_contacts")
    op.drop_index("ix_sign_in_notices_active", table_name="sign_in_notices")
    op.drop_index("ix_sign_in_notices_notice_date", table_name="sign_in_notices")
    op.drop_table("sign_in_notices")
    op.drop_index("ix_sign_in_banners_active", table_name="sign_in_banners")
    op.drop_index("ix_sign_in_banners_sort_order", table_name="sign_in_banners")
    op.drop_table("sign_in_banners")
