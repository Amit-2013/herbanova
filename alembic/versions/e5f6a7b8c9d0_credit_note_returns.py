"""credit note returns: record where returned goods went back

Revision ID: e5f6a7b8c9d0
Revises: a1f2b3c4d5e6
Create Date: 2026-10-21 10:15:00.000000

A credit note that records a sales return puts the credited quantities back
into the batches they were issued from (Module Phase 4). The note records the
warehouse the goods went back to; a null value means the note is a pure money
correction (a rate difference or a rebate) that moves no stock.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'a1f2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('credit_notes',
                  sa.Column('return_warehouse_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_credit_notes_return_warehouse', 'credit_notes',
                          'warehouses', ['return_warehouse_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_credit_notes_return_warehouse', 'credit_notes',
                       type_='foreignkey')
    op.drop_column('credit_notes', 'return_warehouse_id')
