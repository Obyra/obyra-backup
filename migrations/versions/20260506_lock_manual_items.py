"""Lock manual de items: precio_locked + cantidad_locked

Revision ID: 202605060002
Revises: 202605060001
Create Date: 2026-05-06

Cuando el usuario edita manualmente precio o cantidad de un item, marcamos
el flag correspondiente para que la Calculadora IA no lo sobrescriba en
re-estimaciones. La cantidad_locked es preventiva para Chandias futuro
(formulas que recalculen cantidades por m2).

Idempotente: ADD COLUMN IF NOT EXISTS. Aditivo, sin riesgo de regresion.
Default false en filas existentes.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202605060002"
down_revision = "202605060001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] lock manual: solo PostgreSQL")
        return

    print("[LOCK_MANUAL] Iniciando migracion...")
    for col, ddl in [
        ("precio_locked", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("cantidad_locked", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ]:
        try:
            conn.execute(text(
                f"ALTER TABLE items_presupuesto ADD COLUMN IF NOT EXISTS {col} {ddl};"
            ))
            print(f"[OK] items_presupuesto.{col}")
        except Exception as e:
            print(f"[ERROR] items_presupuesto.{col}: {e}")

    for name, cols in [
        ("ix_items_pres_precio_locked", "(precio_locked) WHERE precio_locked = TRUE"),
        ("ix_items_pres_cantidad_locked", "(cantidad_locked) WHERE cantidad_locked = TRUE"),
    ]:
        try:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON items_presupuesto{cols};"
            ))
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    print("[LOCK_MANUAL] Migracion completada.")


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return
    for ix in ("ix_items_pres_precio_locked", "ix_items_pres_cantidad_locked"):
        try:
            conn.execute(text(f"DROP INDEX IF EXISTS {ix};"))
        except Exception as e:
            print(f"[ERROR] drop {ix}: {e}")
    for col in ("precio_locked", "cantidad_locked"):
        try:
            conn.execute(text(f"ALTER TABLE items_presupuesto DROP COLUMN IF EXISTS {col};"))
        except Exception as e:
            print(f"[ERROR] drop items_presupuesto.{col}: {e}")
