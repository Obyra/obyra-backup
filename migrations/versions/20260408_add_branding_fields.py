"""add nombre_fantasia and color_primario to organizaciones

Revision ID: 202604080004
Revises: 202604080003
Create Date: 2026-04-08

Agrega campos de branding a la tabla organizaciones:
- nombre_fantasia: nombre comercial (puede diferir del nombre legal)
- color_primario: color hex corporativo (#RRGGBB)

logo_url ya existe, no se duplica.

Idempotente: usa ADD COLUMN IF NOT EXISTS.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202604080004"
down_revision = "202604080003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] Migración solo soportada en PostgreSQL")
        return

    print("[BRANDING] Agregando campos de branding a organizaciones...")

    try:
        conn.execute(text("""
            ALTER TABLE organizaciones
            ADD COLUMN IF NOT EXISTS nombre_fantasia VARCHAR(200);
        """))
        print("[OK] nombre_fantasia agregado")
    except Exception as e:
        print(f"[ERROR] nombre_fantasia: {e}")

    try:
        conn.execute(text("""
            ALTER TABLE organizaciones
            ADD COLUMN IF NOT EXISTS color_primario VARCHAR(7);
        """))
        print("[OK] color_primario agregado")
    except Exception as e:
        print(f"[ERROR] color_primario: {e}")

    print("[BRANDING] Migración completada")


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return

    try:
        conn.execute(text("ALTER TABLE organizaciones DROP COLUMN IF EXISTS nombre_fantasia;"))
        conn.execute(text("ALTER TABLE organizaciones DROP COLUMN IF EXISTS color_primario;"))
        print("[OK] Columnas eliminadas")
    except Exception as e:
        print(f"[ERROR] {e}")
