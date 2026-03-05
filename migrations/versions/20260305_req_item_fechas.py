"""add fecha_pedido and fecha_entrega_aprox to requerimiento_compra_items

Revision ID: 202603050001
Revises: 202602260002
Create Date: 2026-03-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "202603050001"
down_revision = "202602260002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Set lock_timeout so we fail fast instead of hanging if the table is locked
    conn.execute(sa.text("SET lock_timeout = '5s'"))

    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'requerimiento_compra_items' AND column_name = 'fecha_pedido'"
    ))
    if result.fetchone() is None:
        op.add_column('requerimiento_compra_items', sa.Column('fecha_pedido', sa.Date(), nullable=True))

    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'requerimiento_compra_items' AND column_name = 'fecha_entrega_aprox'"
    ))
    if result.fetchone() is None:
        op.add_column('requerimiento_compra_items', sa.Column('fecha_entrega_aprox', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('requerimiento_compra_items', 'fecha_entrega_aprox')
    op.drop_column('requerimiento_compra_items', 'fecha_pedido')
