"""add geocoding columns to obras and presupuestos"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202503200001"
down_revision = "202503190001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Set search_path for PostgreSQL
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    from sqlalchemy import inspect
    insp = inspect(conn)

    # Check if obras table exists
    if is_pg:
        obras_exists = conn.execute(text("SELECT to_regclass('app.obras')")).scalar()
    else:
        obras_exists = 'obras' in insp.get_table_names()

    if obras_exists:
        obras_cols = {c["name"] for c in insp.get_columns("obras")}

        if "direccion_normalizada" not in obras_cols:
            conn.execute(text("ALTER TABLE obras ADD COLUMN direccion_normalizada TEXT"))
        if "geocode_place_id" not in obras_cols:
            conn.execute(text("ALTER TABLE obras ADD COLUMN geocode_place_id TEXT"))
        if "geocode_provider" not in obras_cols:
            conn.execute(text("ALTER TABLE obras ADD COLUMN geocode_provider TEXT"))
        if "geocode_status" not in obras_cols:
            conn.execute(text("ALTER TABLE obras ADD COLUMN geocode_status TEXT DEFAULT 'pending'"))
        if "geocode_raw" not in obras_cols:
            conn.execute(text("ALTER TABLE obras ADD COLUMN geocode_raw TEXT"))
        if "geocode_actualizado" not in obras_cols:
            coltype = "TIMESTAMP" if is_pg else "DATETIME"
            conn.execute(text(f"ALTER TABLE obras ADD COLUMN geocode_actualizado {coltype}"))

        conn.execute(text("UPDATE obras SET geocode_status = COALESCE(NULLIF(geocode_status, ''), 'pending')"))

    # Check if presupuestos table exists
    if is_pg:
        presup_exists = conn.execute(text("SELECT to_regclass('app.presupuestos')")).scalar()
    else:
        presup_exists = 'presupuestos' in insp.get_table_names()

    if presup_exists:
        presup_cols = {c["name"] for c in insp.get_columns("presupuestos")}

        if "ubicacion_texto" not in presup_cols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN ubicacion_texto TEXT"))
        if "ubicacion_normalizada" not in presup_cols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN ubicacion_normalizada TEXT"))
        if "geo_latitud" not in presup_cols:
            coltype = "NUMERIC(10,8)" if is_pg else "NUMERIC"
            conn.execute(text(f"ALTER TABLE presupuestos ADD COLUMN geo_latitud {coltype}"))
        if "geo_longitud" not in presup_cols:
            coltype = "NUMERIC(11,8)" if is_pg else "NUMERIC"
            conn.execute(text(f"ALTER TABLE presupuestos ADD COLUMN geo_longitud {coltype}"))
        if "geocode_place_id" not in presup_cols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN geocode_place_id TEXT"))
        if "geocode_provider" not in presup_cols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN geocode_provider TEXT"))
        if "geocode_status" not in presup_cols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN geocode_status TEXT DEFAULT 'pending'"))
        if "geocode_raw" not in presup_cols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN geocode_raw TEXT"))
        if "geocode_actualizado" not in presup_cols:
            coltype = "TIMESTAMP" if is_pg else "DATETIME"
            conn.execute(text(f"ALTER TABLE presupuestos ADD COLUMN geocode_actualizado {coltype}"))

        conn.execute(text("UPDATE presupuestos SET geocode_status = COALESCE(NULLIF(geocode_status, ''), 'pending')"))


def downgrade() -> None:
    pass
