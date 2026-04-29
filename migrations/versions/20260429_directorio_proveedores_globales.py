"""directorio de proveedores globales: zonas, scope global/tenant, contactos por tenant

Revision ID: 202604290001
Revises: 202604080004
Create Date: 2026-04-29

Soporta el directorio curado por OBYRA visible a todos los tenants:

1. Crea tabla `zonas` (catalogo normalizado de zonas geograficas).
2. En `proveedores_oc`:
   - Hace nullable `organizacion_id` (NULL => proveedor global)
   - Agrega `scope` ('tenant'|'global'), `external_key` (UNIQUE para globales)
   - Agrega `categoria`, `subcategoria`, `tier`, `zona_id`, `ubicacion_detalle`,
     `cobertura`, `web`, `tipo_alianza`
3. Crea tabla `contactos_proveedor` (1:N: cada tenant agrega sus propios
   contactos sobre proveedores globales o propios).

Idempotente: usa CREATE TABLE IF NOT EXISTS y ADD COLUMN IF NOT EXISTS.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202604290001"
down_revision = "202604080004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] Migracion solo soportada en PostgreSQL")
        return

    print("[DIR_PROVEEDORES] Iniciando migracion...")

    # ============================================================
    # 1. Tabla zonas
    # ============================================================
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS zonas (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(120) NOT NULL,
                slug VARCHAR(140) NOT NULL UNIQUE,
                provincia VARCHAR(100),
                activa BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_zonas_provincia ON zonas(provincia);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_zonas_activa ON zonas(activa);"))
        print("[OK] zonas creada")
    except Exception as e:
        print(f"[ERROR] zonas: {e}")

    # ============================================================
    # 2. proveedores_oc: nuevas columnas + organizacion_id nullable
    # ============================================================
    try:
        # organizacion_id nullable (NULL = proveedor global)
        conn.execute(text("ALTER TABLE proveedores_oc ALTER COLUMN organizacion_id DROP NOT NULL;"))
        print("[OK] proveedores_oc.organizacion_id ahora nullable")
    except Exception as e:
        print(f"[ERROR] proveedores_oc.organizacion_id nullable: {e}")

    columnas_nuevas = [
        ("scope", "VARCHAR(20) NOT NULL DEFAULT 'tenant'"),
        ("external_key", "VARCHAR(160)"),
        ("categoria", "VARCHAR(120)"),
        ("subcategoria", "VARCHAR(160)"),
        ("tier", "VARCHAR(20)"),
        ("zona_id", "INTEGER REFERENCES zonas(id) ON DELETE SET NULL"),
        ("ubicacion_detalle", "VARCHAR(255)"),
        ("cobertura", "VARCHAR(255)"),
        ("web", "VARCHAR(300)"),
        ("tipo_alianza", "VARCHAR(80)"),
    ]
    for col, ddl in columnas_nuevas:
        try:
            conn.execute(text(f"ALTER TABLE proveedores_oc ADD COLUMN IF NOT EXISTS {col} {ddl};"))
            print(f"[OK] proveedores_oc.{col}")
        except Exception as e:
            print(f"[ERROR] proveedores_oc.{col}: {e}")

    # CHECK constraint en scope (idempotente)
    try:
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_proveedores_oc_scope'
                ) THEN
                    ALTER TABLE proveedores_oc
                        ADD CONSTRAINT ck_proveedores_oc_scope
                        CHECK (scope IN ('tenant', 'global'));
                END IF;
            END$$;
        """))
        print("[OK] check constraint scope")
    except Exception as e:
        print(f"[ERROR] check constraint scope: {e}")

    # UNIQUE parcial sobre external_key SOLO cuando scope='global'
    # (permite que tenants usen el mismo nombre sin colisionar entre si)
    try:
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_proveedores_oc_external_key_global
                ON proveedores_oc(external_key)
                WHERE scope = 'global' AND external_key IS NOT NULL;
        """))
        print("[OK] unique index external_key (parcial scope=global)")
    except Exception as e:
        print(f"[ERROR] unique index external_key: {e}")

    # Indices auxiliares para filtros
    try:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proveedores_oc_scope ON proveedores_oc(scope);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proveedores_oc_zona_id ON proveedores_oc(zona_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proveedores_oc_categoria ON proveedores_oc(categoria);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_proveedores_oc_tier ON proveedores_oc(tier);"))
        print("[OK] indices auxiliares proveedores_oc")
    except Exception as e:
        print(f"[ERROR] indices auxiliares: {e}")

    # ============================================================
    # 3. Tabla contactos_proveedor
    # ============================================================
    # organizacion_id nullable solo cuando proveedor es global y el contacto
    # fue cargado por el superadmin como contacto "del catalogo".
    # En la practica los tenants siempre van a setear organizacion_id.
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contactos_proveedor (
                id SERIAL PRIMARY KEY,
                proveedor_id INTEGER NOT NULL REFERENCES proveedores_oc(id) ON DELETE CASCADE,
                organizacion_id INTEGER REFERENCES organizaciones(id) ON DELETE CASCADE,
                nombre VARCHAR(200) NOT NULL,
                cargo VARCHAR(120),
                email VARCHAR(200),
                telefono VARCHAR(50),
                whatsapp VARCHAR(50),
                notas TEXT,
                principal BOOLEAN NOT NULL DEFAULT FALSE,
                activo BOOLEAN NOT NULL DEFAULT TRUE,
                created_by_id INTEGER REFERENCES usuarios(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_contactos_proveedor_prov ON contactos_proveedor(proveedor_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_contactos_proveedor_org ON contactos_proveedor(organizacion_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_contactos_proveedor_activo ON contactos_proveedor(activo);"))
        print("[OK] contactos_proveedor creada")
    except Exception as e:
        print(f"[ERROR] contactos_proveedor: {e}")

    print("[DIR_PROVEEDORES] Migracion completada")


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return

    print("[DIR_PROVEEDORES] Rollback...")

    try:
        conn.execute(text("DROP TABLE IF EXISTS contactos_proveedor CASCADE;"))
        print("[OK] contactos_proveedor eliminada")
    except Exception as e:
        print(f"[ERROR] {e}")

    try:
        conn.execute(text("DROP INDEX IF EXISTS uq_proveedores_oc_external_key_global;"))
        conn.execute(text("DROP INDEX IF EXISTS ix_proveedores_oc_scope;"))
        conn.execute(text("DROP INDEX IF EXISTS ix_proveedores_oc_zona_id;"))
        conn.execute(text("DROP INDEX IF EXISTS ix_proveedores_oc_categoria;"))
        conn.execute(text("DROP INDEX IF EXISTS ix_proveedores_oc_tier;"))
    except Exception as e:
        print(f"[ERROR] indices: {e}")

    try:
        conn.execute(text("ALTER TABLE proveedores_oc DROP CONSTRAINT IF EXISTS ck_proveedores_oc_scope;"))
    except Exception as e:
        print(f"[ERROR] check constraint: {e}")

    columnas = [
        "tipo_alianza", "web", "cobertura", "ubicacion_detalle",
        "zona_id", "tier", "subcategoria", "categoria",
        "external_key", "scope",
    ]
    for col in columnas:
        try:
            conn.execute(text(f"ALTER TABLE proveedores_oc DROP COLUMN IF EXISTS {col};"))
        except Exception as e:
            print(f"[ERROR] drop {col}: {e}")

    # No revertimos el NOT NULL porque puede haber globales con organizacion_id NULL.
    # Si se necesita rollback completo, hay que migrar antes los globales a algun tenant.

    try:
        conn.execute(text("DROP TABLE IF EXISTS zonas CASCADE;"))
        print("[OK] zonas eliminada")
    except Exception as e:
        print(f"[ERROR] zonas: {e}")
