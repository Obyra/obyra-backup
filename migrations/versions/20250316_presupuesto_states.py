"""add presupuesto state columns (estado, perdido_motivo, perdido_fecha, deleted_at)"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202503160001"
down_revision = "20251028_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Set search_path for PostgreSQL
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    # Check if table exists before altering
    if is_pg:
        table_exists = conn.execute(
            text("SELECT to_regclass('app.presupuestos')")
        ).scalar()
    else:
        from sqlalchemy import inspect
        insp = inspect(conn)
        table_exists = 'presupuestos' in insp.get_table_names()

    if not table_exists:
        return

    # Get existing columns
    from sqlalchemy import inspect
    insp = inspect(conn)
    columns = {c["name"] for c in insp.get_columns("presupuestos")}

    # Add estado column
    if "estado" not in columns:
        coltype = "VARCHAR(20)" if is_pg else "TEXT"
        conn.execute(text(f"ALTER TABLE presupuestos ADD COLUMN estado {coltype} DEFAULT 'borrador'"))

    # Add perdido_motivo column
    if "perdido_motivo" not in columns:
        conn.execute(text("ALTER TABLE presupuestos ADD COLUMN perdido_motivo TEXT"))

    # Add perdido_fecha column
    if "perdido_fecha" not in columns:
        coltype = "TIMESTAMP" if is_pg else "DATETIME"
        conn.execute(text(f"ALTER TABLE presupuestos ADD COLUMN perdido_fecha {coltype}"))

    # Add deleted_at column
    if "deleted_at" not in columns:
        coltype = "TIMESTAMP" if is_pg else "DATETIME"
        conn.execute(text(f"ALTER TABLE presupuestos ADD COLUMN deleted_at {coltype}"))

    # Backfill estado based on confirmado_como_obra
    conn.execute(text("""
        UPDATE presupuestos
        SET estado = CASE
            WHEN confirmado_como_obra = 1 OR confirmado_como_obra = TRUE THEN 'confirmado'
            ELSE 'borrador'
        END
        WHERE estado IS NULL OR estado = ''
    """))


def downgrade() -> None:
    pass
