"""create events table and add missing columns for Railway

Revision ID: 202602260002
Revises: 202602260001
Create Date: 2026-02-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "202602260002"
down_revision = "202602260001"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name):
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = :t"
    ), {"t": table_name})
    return result.fetchone() is not None


def _column_exists(conn, table_name, column_name):
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table_name, "c": column_name})
    return result.fetchone() is not None


def _enum_exists(conn, enum_name):
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_type WHERE typname = :n"
    ), {"n": enum_name})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Crear tabla events (si no existe) ──
    if not _table_exists(conn, 'events'):
        # Crear enums si no existen
        if not _enum_exists(conn, 'event_type'):
            conn.execute(sa.text(
                "CREATE TYPE event_type AS ENUM "
                "('alert','milestone','delay','cost_overrun','stock_low',"
                "'status_change','budget_created','inventory_alert','custom')"
            ))
        if not _enum_exists(conn, 'event_severity'):
            conn.execute(sa.text(
                "CREATE TYPE event_severity AS ENUM "
                "('baja','media','alta','critica')"
            ))

        op.create_table(
            'events',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('company_id', sa.Integer,
                       sa.ForeignKey('organizaciones.id'), nullable=False),
            sa.Column('project_id', sa.Integer,
                       sa.ForeignKey('obras.id'), nullable=True),
            sa.Column('user_id', sa.Integer,
                       sa.ForeignKey('usuarios.id'), nullable=True),
            sa.Column('type', sa.Enum(
                'alert', 'milestone', 'delay', 'cost_overrun', 'stock_low',
                'status_change', 'budget_created', 'inventory_alert', 'custom',
                name='event_type', create_type=False
            ), nullable=False),
            sa.Column('severity', sa.Enum(
                'baja', 'media', 'alta', 'critica',
                name='event_severity', create_type=False
            ), nullable=True),
            sa.Column('title', sa.Text, nullable=False),
            sa.Column('description', sa.Text, nullable=True),
            sa.Column('meta', sa.JSON, nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=False,
                       server_default=sa.text('NOW()')),
            sa.Column('created_by', sa.Integer,
                       sa.ForeignKey('usuarios.id'), nullable=True),
        )
        op.create_index('idx_events_company_created', 'events',
                        ['company_id', 'created_at'])
        op.create_index('idx_events_project', 'events', ['project_id'])
        op.create_index('idx_events_type', 'events', ['type'])

    # ── 2. Agregar confirmado_como_obra a presupuestos (si no existe) ──
    if not _column_exists(conn, 'presupuestos', 'confirmado_como_obra'):
        op.add_column('presupuestos',
                      sa.Column('confirmado_como_obra', sa.Boolean,
                                server_default=sa.text('false'), nullable=True))


def downgrade() -> None:
    op.drop_column('presupuestos', 'confirmado_como_obra')
    op.drop_index('idx_events_type', table_name='events')
    op.drop_index('idx_events_project', table_name='events')
    op.drop_index('idx_events_company_created', table_name='events')
    op.drop_table('events')
    op.execute("DROP TYPE IF EXISTS event_severity")
    op.execute("DROP TYPE IF EXISTS event_type")
