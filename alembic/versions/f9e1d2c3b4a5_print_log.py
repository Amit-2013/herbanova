"""print log and print permission (Module Phase 5)

Revision ID: f9e1d2c3b4a5
Revises: e5f6a7b8c9d0
Create Date: 2026-10-21 11:20:00.000000

Every print of a tax document is recorded: who printed it, when (IST), which
copy set it was and the SHA-256 of the exact bytes served. The hash is what a
later verification checks against, so a printed page can be proved to match the
locked database record (AUD-037).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9e1d2c3b4a5'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'print_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('document_type', sa.String(20), nullable=False),  # invoice|credit_note|debit_note
        # Not a foreign key on purpose: one log row covers all three document
        # types, and every one of them has lines. Lines outlive their document
        # in practice (documents are immutable), so the reference is stable.
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('document_number', sa.String(16), nullable=False),
        sa.Column('copy_designation', sa.String(20), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('printed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('printed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "document_type IN ('invoice','credit_note','debit_note')",
            name='ck_print_log_document_type'),
        sa.CheckConstraint(
            "copy_designation IN ('ORIGINAL','DUPLICATE','TRIPLICATE')",
            name='ck_print_log_copy'),
    )
    op.create_index('ix_print_logs_document', 'print_logs', ['document_type', 'document_id'])
    op.create_index('ix_print_logs_sha256', 'print_logs', ['sha256'])

    # The roles were seeded by the Phase 1 migration and extended by Phases 2-4;
    # give them the print right this module adds, without touching any other
    # permission. Viewer never prints.
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb || '["print:document"]'::jsonb)::json
         WHERE name IN ('admin', 'sales', 'inventory')
           AND NOT permissions::jsonb @> '["print:document"]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb - 'print:document')::json
         WHERE name IN ('admin', 'sales', 'inventory')
        """
    )
    op.drop_index('ix_print_logs_sha256', table_name='print_logs')
    op.drop_index('ix_print_logs_document', table_name='print_logs')
    op.drop_table('print_logs')
