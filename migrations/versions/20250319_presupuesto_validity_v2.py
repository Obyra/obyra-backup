"""add presupuesto validity columns (vigencia_dias, fecha_vigencia, vigencia_bloqueada)"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa
from datetime import date, timedelta

revision = "202503190001"
down_revision = "202503170001"
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

    # Add vigencia_dias column
    if "vigencia_dias" not in columns:
        conn.execute(text("ALTER TABLE presupuestos ADD COLUMN vigencia_dias INTEGER DEFAULT 30"))

    # Add fecha_vigencia column
    if "fecha_vigencia" not in columns:
        conn.execute(text("ALTER TABLE presupuestos ADD COLUMN fecha_vigencia DATE"))

    # Add vigencia_bloqueada column
    if "vigencia_bloqueada" not in columns:
        if is_pg:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN vigencia_bloqueada BOOLEAN DEFAULT FALSE"))
        else:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN vigencia_bloqueada INTEGER DEFAULT 0"))

    # Backfill fecha_vigencia based on fecha + vigencia_dias
    coalesce_literal = "FALSE" if is_pg else "0"
    rows = conn.execute(text(
        f"SELECT id, fecha, vigencia_dias, COALESCE(vigencia_bloqueada, {coalesce_literal}) FROM presupuestos"
    )).fetchall()

    for presupuesto_id, fecha_valor, vigencia_valor, bloqueada in rows:
        # Calculate vigencia_dias (clamp between 1 and 180)
        dias = vigencia_valor if vigencia_valor and vigencia_valor > 0 else 30
        dias = 1 if dias < 1 else (180 if dias > 180 else dias)

        # Calculate base date
        if not fecha_valor:
            fecha_base = date.today()
        elif isinstance(fecha_valor, str):
            try:
                fecha_base = date.fromisoformat(fecha_valor)
            except ValueError:
                fecha_base = date.today()
        else:
            fecha_base = fecha_valor

        # Calculate fecha_vigencia
        fecha_vig = fecha_base + timedelta(days=dias)
        bloqueada_flag = bool(bloqueada)
        if not is_pg:
            bloqueada_flag = 1 if bloqueada_flag else 0

        # Update row
        if is_pg:
            conn.execute(
                text("UPDATE presupuestos SET vigencia_dias = :dias, fecha_vigencia = :fecha_vig, vigencia_bloqueada = :bloqueada WHERE id = :pid"),
                {"dias": dias, "fecha_vig": fecha_vig, "bloqueada": bloqueada_flag, "pid": presupuesto_id}
            )
        else:
            conn.execute(
                text("UPDATE presupuestos SET vigencia_dias = :dias, fecha_vigencia = :fecha_vig, vigencia_bloqueada = :bloqueada WHERE id = :pid"),
                {"dias": dias, "fecha_vig": fecha_vig, "bloqueada": bloqueada_flag, "pid": presupuesto_id}
            )


def downgrade() -> None:
    pass
