"""Etapa editable de presupuesto + flexibilidad en items

Revision ID: 202605060001
Revises: 202605050002
Create Date: 2026-05-06

Habilita gestión flexible del módulo presupuestos (Etapa 1):

1. Tabla nueva `presupuesto_etapa`: por presupuesto, una fila por etapa.
   Reemplaza el string suelto `items_presupuesto.etapa_nombre` por una FK
   normalizada — pero mantiene `etapa_nombre` como cache denormalizado
   para compatibilidad legacy y queries simples.

2. Columnas nuevas en `items_presupuesto`:
   - etapa_presupuesto_id (FK a presupuesto_etapa, nullable)
   - orden (int, default 0)
   - excluido (bool, default false) — soft-hide para que no cuente en totales
   - editado_at, editado_por_user_id — auditoría liviana de ediciones

3. Backfill: por cada presupuesto existente, agrupa los `etapa_nombre`
   distintos (con normalización trim+collapse-spaces), crea filas en
   `presupuesto_etapa` con `orden` por aparición, y popula la FK en cada
   item.

Idempotente: ADD COLUMN IF NOT EXISTS, CREATE TABLE IF NOT EXISTS,
ON CONFLICT DO NOTHING para el backfill.

Aditivo: filas viejas siguen funcionando con etapa_presupuesto_id NULL
durante la transicion. El backfill resuelve los presupuestos existentes
en un solo run.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202605060001"
down_revision = "202605050002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] presupuesto_etapa: solo soportado en PostgreSQL")
        return

    print("[ETAPA_EDITABLE] Iniciando migracion...")

    # ============================================================
    # 1. Tabla presupuesto_etapa
    # ============================================================
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS presupuesto_etapa (
                id BIGSERIAL PRIMARY KEY,
                presupuesto_id INTEGER NOT NULL
                    REFERENCES presupuestos(id) ON DELETE CASCADE,
                nombre VARCHAR(150) NOT NULL,
                orden INTEGER NOT NULL DEFAULT 0,
                oculto BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("[OK] presupuesto_etapa creada")
    except Exception as e:
        print(f"[ERROR] presupuesto_etapa: {e}")
        raise

    # UNIQUE (presupuesto_id, nombre) — una etapa con ese nombre por presupuesto
    try:
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_presupuesto_etapa_pres_nombre
                ON presupuesto_etapa(presupuesto_id, nombre);
        """))
        print("[OK] uq_presupuesto_etapa_pres_nombre")
    except Exception as e:
        print(f"[ERROR] uq_presupuesto_etapa_pres_nombre: {e}")

    for name, cols in [
        ("ix_presupuesto_etapa_pres", "(presupuesto_id)"),
        ("ix_presupuesto_etapa_orden", "(presupuesto_id, orden)"),
        ("ix_presupuesto_etapa_oculto", "(oculto)"),
    ]:
        try:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON presupuesto_etapa{cols};"
            ))
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    # ============================================================
    # 2. items_presupuesto: nuevas columnas
    # ============================================================
    columnas = [
        ("etapa_presupuesto_id",
         "BIGINT REFERENCES presupuesto_etapa(id) ON DELETE SET NULL"),
        ("orden", "INTEGER NOT NULL DEFAULT 0"),
        ("excluido", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("editado_at", "TIMESTAMP"),
        ("editado_por_user_id",
         "INTEGER REFERENCES usuarios(id) ON DELETE SET NULL"),
    ]
    for col, ddl in columnas:
        try:
            conn.execute(text(
                f"ALTER TABLE items_presupuesto ADD COLUMN IF NOT EXISTS {col} {ddl};"
            ))
            print(f"[OK] items_presupuesto.{col}")
        except Exception as e:
            print(f"[ERROR] items_presupuesto.{col}: {e}")

    for name, cols in [
        ("ix_items_pres_etapa_pres", "(etapa_presupuesto_id)"),
        ("ix_items_pres_excluido", "(excluido)"),
        ("ix_items_pres_orden", "(presupuesto_id, etapa_presupuesto_id, orden)"),
    ]:
        try:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON items_presupuesto{cols};"
            ))
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    # ============================================================
    # 3. BACKFILL — crear etapas a partir de etapa_nombre legacy
    # ============================================================
    # Estrategia: por cada presupuesto, agrupar etapa_nombre distintos
    # normalizados (trim + collapse spaces), crear filas en presupuesto_etapa
    # ordenadas por la primera aparicion del item con ese nombre.
    try:
        conn.execute(text("""
            INSERT INTO presupuesto_etapa (presupuesto_id, nombre, orden, oculto, created_at, updated_at)
            SELECT
                ip.presupuesto_id,
                TRIM(REGEXP_REPLACE(ip.etapa_nombre, '\\s+', ' ', 'g')) AS nombre_norm,
                ROW_NUMBER() OVER (
                    PARTITION BY ip.presupuesto_id
                    ORDER BY MIN(ip.id)
                ) AS orden,
                FALSE,
                NOW(),
                NOW()
            FROM items_presupuesto ip
            WHERE ip.etapa_nombre IS NOT NULL
              AND TRIM(ip.etapa_nombre) <> ''
              AND ip.etapa_presupuesto_id IS NULL
            GROUP BY ip.presupuesto_id, TRIM(REGEXP_REPLACE(ip.etapa_nombre, '\\s+', ' ', 'g'))
            ON CONFLICT (presupuesto_id, nombre) DO NOTHING;
        """))
        # rowcount no es preciso con ON CONFLICT, asi que contamos por separado
        n_etapas = conn.execute(text(
            "SELECT COUNT(*) FROM presupuesto_etapa"
        )).scalar() or 0
        print(f"[OK] backfill presupuesto_etapa: {n_etapas} filas totales en tabla")
    except Exception as e:
        print(f"[ERROR] backfill presupuesto_etapa: {e}")

    # Poblar etapa_presupuesto_id en items existentes
    try:
        result = conn.execute(text("""
            UPDATE items_presupuesto i
            SET etapa_presupuesto_id = e.id
            FROM presupuesto_etapa e
            WHERE i.presupuesto_id = e.presupuesto_id
              AND TRIM(REGEXP_REPLACE(COALESCE(i.etapa_nombre, ''), '\\s+', ' ', 'g')) = e.nombre
              AND i.etapa_presupuesto_id IS NULL
              AND i.etapa_nombre IS NOT NULL
              AND TRIM(i.etapa_nombre) <> '';
        """))
        rc = getattr(result, 'rowcount', 0) or 0
        print(f"[OK] backfill items_presupuesto.etapa_presupuesto_id: {rc} items vinculados")
    except Exception as e:
        print(f"[ERROR] backfill items_presupuesto.etapa_presupuesto_id: {e}")

    print("[ETAPA_EDITABLE] Migracion completada.")


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return
    for ix in (
        "ix_items_pres_etapa_pres", "ix_items_pres_excluido", "ix_items_pres_orden",
    ):
        try:
            conn.execute(text(f"DROP INDEX IF EXISTS {ix};"))
        except Exception as e:
            print(f"[ERROR] drop {ix}: {e}")
    for col in ("etapa_presupuesto_id", "orden", "excluido", "editado_at", "editado_por_user_id"):
        try:
            conn.execute(text(f"ALTER TABLE items_presupuesto DROP COLUMN IF EXISTS {col};"))
        except Exception as e:
            print(f"[ERROR] drop items_presupuesto.{col}: {e}")
    try:
        conn.execute(text("DROP TABLE IF EXISTS presupuesto_etapa CASCADE;"))
    except Exception as e:
        print(f"[ERROR] drop presupuesto_etapa: {e}")
