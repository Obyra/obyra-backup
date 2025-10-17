"""Ensure inventory_category has sort_order and status flags."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '0002_add_inventory_category_columns'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    try:
        columns = {column['name'] for column in inspector.get_columns('inventory_category')}
    except Exception:  # pragma: no cover - table missing
        columns = set()

    if 'sort_order' not in columns:
        op.add_column('inventory_category', sa.Column('sort_order', sa.Integer(), nullable=True))
        op.execute('UPDATE inventory_category SET sort_order = 0 WHERE sort_order IS NULL')
        op.alter_column('inventory_category', 'sort_order', nullable=False, server_default=sa.text('0'))
    else:
        op.alter_column('inventory_category', 'sort_order', server_default=sa.text('0'))

    if 'is_active' not in columns:
        op.add_column('inventory_category', sa.Column('is_active', sa.Boolean(), nullable=True))
        op.execute('UPDATE inventory_category SET is_active = TRUE WHERE is_active IS NULL')
        op.alter_column('inventory_category', 'is_active', nullable=False, server_default=sa.true())
    else:
        op.alter_column('inventory_category', 'is_active', server_default=sa.true())

    if 'is_global' not in columns:
        op.add_column('inventory_category', sa.Column('is_global', sa.Boolean(), nullable=True))
        op.execute('UPDATE inventory_category SET is_global = FALSE WHERE is_global IS NULL')
        op.alter_column('inventory_category', 'is_global', nullable=False, server_default=sa.false())
    else:
        op.alter_column('inventory_category', 'is_global', server_default=sa.false())


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    try:
        columns = {column['name'] for column in inspector.get_columns('inventory_category')}
    except Exception:  # pragma: no cover - table missing
        columns = set()

    if 'is_global' in columns:
        op.drop_column('inventory_category', 'is_global')
    if 'is_active' in columns:
        op.drop_column('inventory_category', 'is_active')
    if 'sort_order' in columns:
        op.drop_column('inventory_category', 'sort_order')
