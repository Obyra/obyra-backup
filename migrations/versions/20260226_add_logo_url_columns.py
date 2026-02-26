"""add logo_url columns to organizaciones and proveedores

Revision ID: 202602260001
Revises: 202601200001
Create Date: 2026-02-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "202602260001"
down_revision = "202601200001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar logo_url a organizaciones (si no existe)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'organizaciones' AND column_name = 'logo_url'"
    ))
    if result.fetchone() is None:
        op.add_column('organizaciones', sa.Column('logo_url', sa.String(500), nullable=True))

    # Agregar logo_url a proveedores (si no existe)
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'proveedores' AND column_name = 'logo_url'"
    ))
    if result.fetchone() is None:
        op.add_column('proveedores', sa.Column('logo_url', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('proveedores', 'logo_url')
    op.drop_column('organizaciones', 'logo_url')
