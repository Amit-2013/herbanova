"""billing: debit notes, document sequences and movement details

Revision ID: a1f2b3c4d5e6
Revises: d46763330c70
Create Date: 2026-10-21 09:30:00.000000

Module Phase 4 completes billing:

- `document_sequences` holds the locked counter that makes invoice, credit-note
  and debit-note numbers consecutive and unique per financial year (AUD-034);
- `debit_notes` and `debit_note_lines` correct an invoice upwards (AUD-035);
- an invoice records the delivery challan and e-way bill details of the
  movement after issue (FR-14);
- the seeded roles receive the billing permissions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f2b3c4d5e6'
down_revision: Union[str, None] = 'd46763330c70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_sequences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doc_type', sa.String(length=20), nullable=False),
        sa.Column('financial_year', sa.String(length=9), nullable=False),
        sa.Column('last_number', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('doc_type', 'financial_year', name='uq_document_sequence'),
    )

    op.create_table(
        'debit_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('debit_note_number', sa.String(length=16), nullable=False),
        sa.Column('financial_year', sa.String(length=9), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('sales_order_id', sa.Integer(), nullable=False),
        sa.Column('distributor_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('note_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(length=300), nullable=False),
        sa.Column('gross_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('taxable_value', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('cgst_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('sgst_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('igst_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('cess_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('tax_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('grand_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('issued_by', sa.Integer(), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.CheckConstraint("status IN ('issued','cancelled')", name='ck_debit_note_status'),
        sa.ForeignKeyConstraint(['distributor_id'], ['distributors.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id']),
        sa.ForeignKeyConstraint(['issued_by'], ['users.id']),
        sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('debit_note_number', 'financial_year', name='uq_debit_note_number_fy'),
    )
    op.create_index(op.f('ix_debit_notes_debit_note_number'), 'debit_notes',
                    ['debit_note_number'], unique=False)

    op.create_table(
        'debit_note_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('debit_note_id', sa.Integer(), nullable=False),
        sa.Column('invoice_line_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('sku', sa.String(length=40), nullable=False),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('qty', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('taxable_value', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('cgst_amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('sgst_amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('igst_amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('cess_amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('line_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.CheckConstraint('qty > 0', name='ck_debit_note_line_qty_positive'),
        sa.ForeignKeyConstraint(['debit_note_id'], ['debit_notes.id']),
        sa.ForeignKeyConstraint(['invoice_line_id'], ['invoice_lines.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.add_column('invoices', sa.Column('delivery_challan_number', sa.String(length=30), nullable=True))
    op.add_column('invoices', sa.Column('vehicle_number', sa.String(length=20), nullable=True))
    op.add_column('invoices', sa.Column('transporter_name', sa.String(length=120), nullable=True))
    op.add_column('invoices', sa.Column('eway_bill_number', sa.String(length=30), nullable=True))
    op.add_column('invoices', sa.Column('eway_bill_date', sa.Date(), nullable=True))

    # ------------------------------------------------------- seeded role rights
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb ||
                              '["invoice:write","invoice:cancel","note:write"]'::jsonb)::json
         WHERE name = 'admin'
           AND NOT permissions::jsonb @> '["note:write"]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb || '["invoice:write","note:write"]'::jsonb)::json
         WHERE name = 'sales'
           AND NOT permissions::jsonb @> '["note:write"]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb || '["invoice:write"]'::jsonb)::json
         WHERE name = 'inventory'
           AND NOT permissions::jsonb @> '["invoice:write"]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
           SET permissions = (permissions::jsonb - 'invoice:write' - 'invoice:cancel'
                              - 'note:write')::json
         WHERE name = 'admin'
        """
    )
    for role_name in ("sales", "inventory"):
        op.execute(
            f"""
            UPDATE roles
               SET permissions = (permissions::jsonb - 'invoice:write' - 'note:write')::json
             WHERE name = '{role_name}'
            """
        )

    for column in ('eway_bill_date', 'eway_bill_number', 'transporter_name',
                   'vehicle_number', 'delivery_challan_number'):
        op.drop_column('invoices', column)

    op.drop_table('debit_note_lines')
    op.drop_index(op.f('ix_debit_notes_debit_note_number'), table_name='debit_notes')
    op.drop_table('debit_notes')
    op.drop_table('document_sequences')
