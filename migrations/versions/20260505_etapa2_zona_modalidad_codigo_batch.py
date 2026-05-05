"""Etapa 2 base IA: zona, modalidad, codigo_proveedor, import_batch

Revision ID: 202605050002
Revises: 202605050001
Create Date: 2026-05-05

Schema preparado para importer unificado de fuentes de precios (Etapa 3+).

Cambios:
1. provider_price_list:
   - Nuevas columnas: zona, modalidad, codigo_proveedor, import_batch_id.
   - Reemplaza UNIQUE uq_ppl_org_prov_desc_un por
     uq_ppl_org_prov_desc_un_zona_modalidad (incluye zona y modalidad,
     usando COALESCE para tratar NULL como literal vacio).
2. precio_observado:
   - Nuevas columnas: zona, modalidad, codigo_proveedor, import_batch_id.
3. import_batch (tabla nueva): traza cada import (lista propia, lista
   proveedor, etc) con checksum, contadores y soporte para "deshacer".

Idempotente: ADD COLUMN IF NOT EXISTS, CREATE TABLE IF NOT EXISTS,
CREATE INDEX IF NOT EXISTS. El swap de UNIQUE usa DO$$ con check de
pg_constraint para evitar errores en reruns.

Aditivo y backward-compatible: filas existentes quedan con los nuevos
campos en NULL/default. El UNIQUE nuevo COALESCE-a a strings literales,
asi NULL se trata como '' y todos los registros viejos siguen siendo
unicos por (org, proveedor_id, desc_norm, unidad).
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202605050002"
down_revision = "202605050001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] Etapa 2 schema base IA: solo soportado en PostgreSQL")
        return

    print("[ETAPA2] Iniciando migracion...")

    # ============================================================
    # 1. Tabla import_batch (nueva)
    # ============================================================
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS import_batch (
                id BIGSERIAL PRIMARY KEY,
                organizacion_id INTEGER NOT NULL
                    REFERENCES organizaciones(id) ON DELETE CASCADE,
                perfil VARCHAR(40) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                checksum_sha256 VARCHAR(64),
                user_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
                total_input INTEGER NOT NULL DEFAULT 0,
                total_inserted INTEGER NOT NULL DEFAULT 0,
                total_updated INTEGER NOT NULL DEFAULT 0,
                total_invalid INTEGER NOT NULL DEFAULT 0,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                estado VARCHAR(20) NOT NULL DEFAULT 'en_curso',
                deshecho_at TIMESTAMP,
                undo_motivo TEXT,
                metadata_json JSONB
            );
        """))
        print("[OK] import_batch creada")
    except Exception as e:
        print(f"[ERROR] import_batch: {e}")
        raise

    # UNIQUE parcial: mismo archivo no se puede importar dos veces si el
    # batch anterior NO fue deshecho. Si lo deshacemos, libera el slot.
    try:
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_import_batch_org_checksum
                ON import_batch(organizacion_id, checksum_sha256)
                WHERE checksum_sha256 IS NOT NULL AND deshecho_at IS NULL;
        """))
        print("[OK] uq_import_batch_org_checksum (parcial)")
    except Exception as e:
        print(f"[ERROR] uq_import_batch_org_checksum: {e}")

    for name, cols in [
        ("ix_import_batch_org", "(organizacion_id)"),
        ("ix_import_batch_perfil", "(perfil)"),
        ("ix_import_batch_estado", "(estado)"),
        ("ix_import_batch_started", "(started_at)"),
    ]:
        try:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON import_batch{cols};"
            ))
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    # ============================================================
    # 2. provider_price_list: nuevas columnas
    # ============================================================
    columnas_ppl = [
        ("zona", "VARCHAR(40)"),
        ("modalidad", "VARCHAR(30)"),
        ("codigo_proveedor", "VARCHAR(60)"),
        ("import_batch_id", "BIGINT REFERENCES import_batch(id) ON DELETE SET NULL"),
    ]
    for col, ddl in columnas_ppl:
        try:
            conn.execute(text(
                f"ALTER TABLE provider_price_list ADD COLUMN IF NOT EXISTS {col} {ddl};"
            ))
            print(f"[OK] provider_price_list.{col}")
        except Exception as e:
            print(f"[ERROR] provider_price_list.{col}: {e}")

    # ============================================================
    # 3. provider_price_list: reemplazar UNIQUE incluyendo zona y modalidad
    # ============================================================
    # Usamos COALESCE para tratar NULL como string vacio. Asi:
    #  - Filas existentes (zona=NULL, modalidad=NULL) siguen siendo unicas
    #    por (org, proveedor, desc_norm, unidad, '', '').
    #  - Nuevas filas con zona='CABA' vs zona='GBA' coexisten para misma desc.
    try:
        conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_ppl_org_prov_desc_un'
                ) THEN
                    ALTER TABLE provider_price_list
                        DROP CONSTRAINT uq_ppl_org_prov_desc_un;
                END IF;
            END$$;
        """))
        print("[OK] uq_ppl_org_prov_desc_un eliminado (si existia)")
    except Exception as e:
        print(f"[ERROR] drop uq_ppl_org_prov_desc_un: {e}")

    # UNIQUE expression-based con COALESCE. Postgres soporta UNIQUE INDEX sobre
    # expresiones; el resultado es equivalente a un constraint pero evita el
    # comportamiento de NULLs como distintos.
    try:
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ppl_org_prov_desc_un_zona_modalidad
                ON provider_price_list(
                    organizacion_id,
                    COALESCE(proveedor_id, 0),
                    descripcion_normalizada,
                    unidad,
                    COALESCE(zona, ''),
                    COALESCE(modalidad, 'compra')
                );
        """))
        print("[OK] uq_ppl_org_prov_desc_un_zona_modalidad creado")
    except Exception as e:
        print(f"[ERROR] uq_ppl_org_prov_desc_un_zona_modalidad: {e}")
        raise

    # Indices auxiliares
    for name, cols in [
        ("ix_ppl_org_zona", "(organizacion_id, zona)"),
        ("ix_ppl_org_modalidad", "(organizacion_id, modalidad)"),
        ("ix_ppl_codigo_proveedor",
         "(organizacion_id, proveedor_id, codigo_proveedor)"),
        ("ix_ppl_import_batch", "(import_batch_id)"),
    ]:
        try:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON provider_price_list{cols};"
            ))
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    # ============================================================
    # 4. precio_observado: nuevas columnas
    # ============================================================
    columnas_obs = [
        ("zona", "VARCHAR(40)"),
        ("modalidad", "VARCHAR(30)"),
        ("codigo_proveedor", "VARCHAR(60)"),
        ("import_batch_id", "BIGINT REFERENCES import_batch(id) ON DELETE SET NULL"),
    ]
    for col, ddl in columnas_obs:
        try:
            conn.execute(text(
                f"ALTER TABLE precio_observado ADD COLUMN IF NOT EXISTS {col} {ddl};"
            ))
            print(f"[OK] precio_observado.{col}")
        except Exception as e:
            print(f"[ERROR] precio_observado.{col}: {e}")

    for name, cols in [
        ("ix_precio_obs_zona", "(organizacion_id, zona)"),
        ("ix_precio_obs_modalidad", "(organizacion_id, modalidad)"),
        ("ix_precio_obs_import_batch", "(import_batch_id)"),
    ]:
        try:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON precio_observado{cols};"
            ))
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    print("[ETAPA2] Migracion completada.")


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return

    # Drop indexes auxiliares de precio_observado
    for ix in (
        "ix_precio_obs_zona", "ix_precio_obs_modalidad",
        "ix_precio_obs_import_batch",
    ):
        try:
            conn.execute(text(f"DROP INDEX IF EXISTS {ix};"))
        except Exception as e:
            print(f"[ERROR] drop {ix}: {e}")

    # Drop columnas precio_observado
    for col in ("zona", "modalidad", "codigo_proveedor", "import_batch_id"):
        try:
            conn.execute(text(f"ALTER TABLE precio_observado DROP COLUMN IF EXISTS {col};"))
        except Exception as e:
            print(f"[ERROR] drop precio_observado.{col}: {e}")

    # Drop indexes provider_price_list
    for ix in (
        "ix_ppl_org_zona", "ix_ppl_org_modalidad",
        "ix_ppl_codigo_proveedor", "ix_ppl_import_batch",
        "uq_ppl_org_prov_desc_un_zona_modalidad",
    ):
        try:
            conn.execute(text(f"DROP INDEX IF EXISTS {ix};"))
        except Exception as e:
            print(f"[ERROR] drop {ix}: {e}")

    # Restaurar UNIQUE viejo
    try:
        conn.execute(text("""
            ALTER TABLE provider_price_list
                ADD CONSTRAINT uq_ppl_org_prov_desc_un
                UNIQUE (organizacion_id, proveedor_id, descripcion_normalizada, unidad);
        """))
    except Exception as e:
        print(f"[ERROR] restore uq_ppl_org_prov_desc_un: {e}")

    # Drop columnas provider_price_list
    for col in ("zona", "modalidad", "codigo_proveedor", "import_batch_id"):
        try:
            conn.execute(text(f"ALTER TABLE provider_price_list DROP COLUMN IF EXISTS {col};"))
        except Exception as e:
            print(f"[ERROR] drop provider_price_list.{col}: {e}")

    # Drop import_batch
    try:
        conn.execute(text("DROP TABLE IF EXISTS import_batch CASCADE;"))
    except Exception as e:
        print(f"[ERROR] drop import_batch: {e}")
