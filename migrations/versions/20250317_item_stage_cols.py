"""add items_presupuesto stage columns (etapa_id, origen)"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202503170001"
down_revision = "202503160001"
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
            text("SELECT to_regclass('app.items_presupuesto')")
        ).scalar()
    else:
        from sqlalchemy import inspect
        insp = inspect(conn)
        table_exists = 'items_presupuesto' in insp.get_table_names()

    if not table_exists:
        return

    # Get existing columns
    from sqlalchemy import inspect
    insp = inspect(conn)
    columns = {c["name"] for c in insp.get_columns("items_presupuesto")}

    # Add etapa_id column
    if "etapa_id" not in columns:
        conn.execute(text("ALTER TABLE items_presupuesto ADD COLUMN etapa_id INTEGER"))

    # Add origen column
    if "origen" not in columns:
        coltype = "VARCHAR(20)" if is_pg else "VARCHAR(20)"
        conn.execute(text(f"ALTER TABLE items_presupuesto ADD COLUMN origen {coltype} DEFAULT 'manual'"))

    # Update defaults
    conn.execute(text("UPDATE items_presupuesto SET origen = COALESCE(NULLIF(origen, ''), 'manual')"))


def downgrade() -> None:
    pass
