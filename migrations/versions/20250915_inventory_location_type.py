"""add tipo column to warehouse"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202509150001"
down_revision = "202509120001"
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
            text("SELECT to_regclass('app.warehouse')")
        ).scalar()
    else:
        from sqlalchemy import inspect
        insp = inspect(conn)
        table_exists = 'warehouse' in insp.get_table_names()

    if not table_exists:
        return

    # Get existing columns
    from sqlalchemy import inspect
    insp = inspect(conn)
    columns = {c["name"] for c in insp.get_columns("warehouse")}

    # Add tipo column
    if "tipo" not in columns:
        coltype = "VARCHAR(20)" if is_pg else "TEXT"
        conn.execute(text(f"ALTER TABLE warehouse ADD COLUMN tipo {coltype} DEFAULT 'deposito'"))

    # Update defaults
    conn.execute(text("UPDATE warehouse SET tipo = COALESCE(NULLIF(tipo, ''), 'deposito')"))


def downgrade() -> None:
    pass
