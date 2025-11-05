"""add audit columns to tarea_avances (cantidad_ingresada, unidad_ingresada)"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202509100001"
down_revision = "202509010001"
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
            text("SELECT to_regclass('app.tarea_avances')")
        ).scalar()
    else:
        from sqlalchemy import inspect
        insp = inspect(conn)
        table_exists = 'tarea_avances' in insp.get_table_names()

    if not table_exists:
        return

    # Get existing columns
    from sqlalchemy import inspect
    insp = inspect(conn)
    columns = {c["name"] for c in insp.get_columns("tarea_avances")}

    # Add cantidad_ingresada column
    if "cantidad_ingresada" not in columns:
        conn.execute(text("ALTER TABLE tarea_avances ADD COLUMN cantidad_ingresada NUMERIC"))

    # Add unidad_ingresada column
    if "unidad_ingresada" not in columns:
        coltype = "VARCHAR(10)" if is_pg else "VARCHAR(10)"
        conn.execute(text(f"ALTER TABLE tarea_avances ADD COLUMN unidad_ingresada {coltype}"))


def downgrade() -> None:
    pass
