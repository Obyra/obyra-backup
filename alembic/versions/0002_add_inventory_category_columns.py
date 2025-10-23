"""Ensure inventory_category has sort_order and status flags."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


TABLE_NAME = "inventory_category"


def _ensure_table_in_app(inspector, bind) -> bool:
    if inspector.has_table(TABLE_NAME, schema="app"):
        return True

    if inspector.has_table(TABLE_NAME, schema="public"):
        op.execute(f"ALTER TABLE public.{TABLE_NAME} SET SCHEMA app")
        return True

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("app.inventory_category.id")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_global", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("TIMEZONE('utc', now())")),
        sa.ForeignKeyConstraint(["company_id"], ["app.organizaciones.id"]),
        schema="app",
    )
    return True

# revision identifiers, used by Alembic.
revision = '0002_add_inventory_category_columns'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    _ensure_table_in_app(inspector, bind)
    inspector = inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns(TABLE_NAME, schema="app")
    }

    if 'sort_order' not in columns:
        op.add_column(TABLE_NAME, sa.Column('sort_order', sa.Integer(), nullable=True), schema='app')
        op.execute('UPDATE app.inventory_category SET sort_order = 0 WHERE sort_order IS NULL')
        op.alter_column('inventory_category', 'sort_order', nullable=False, server_default=sa.text('0'), schema='app')
    else:
        op.alter_column('inventory_category', 'sort_order', server_default=sa.text('0'), schema='app')

    if 'is_active' not in columns:
        op.add_column(TABLE_NAME, sa.Column('is_active', sa.Boolean(), nullable=True), schema='app')
        op.execute('UPDATE app.inventory_category SET is_active = TRUE WHERE is_active IS NULL')
        op.alter_column('inventory_category', 'is_active', nullable=False, server_default=sa.true(), schema='app')
    else:
        op.alter_column('inventory_category', 'is_active', server_default=sa.true(), schema='app')

    if 'is_global' not in columns:
        op.add_column(TABLE_NAME, sa.Column('is_global', sa.Boolean(), nullable=True), schema='app')
        op.execute('UPDATE app.inventory_category SET is_global = FALSE WHERE is_global IS NULL')
        op.alter_column('inventory_category', 'is_global', nullable=False, server_default=sa.false(), schema='app')
    else:
        op.alter_column('inventory_category', 'is_global', server_default=sa.false(), schema='app')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table(TABLE_NAME, schema='app'):
        return

    columns = {
        column['name']
        for column in inspector.get_columns(TABLE_NAME, schema='app')
    }

    if 'is_global' in columns:
        op.drop_column('inventory_category', 'is_global', schema='app')
    if 'is_active' in columns:
        op.drop_column('inventory_category', 'is_active', schema='app')
    if 'sort_order' in columns:
        op.drop_column('inventory_category', 'sort_order', schema='app')
