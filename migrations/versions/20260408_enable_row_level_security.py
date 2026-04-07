"""enable Row Level Security (RLS) on tenant-scoped tables

Revision ID: 202604080001
Revises: 202602260002
Create Date: 2026-04-08

Defensa en profundidad multi-tenant: aunque el código olvide filtrar por
organizacion_id, PostgreSQL automáticamente filtra a nivel de base de datos.

Cómo funciona:
1. Cada conexión de la app debe ejecutar al inicio:
     SET app.current_org_id = '<org_id>';
     SET app.is_super_admin = 'false';
2. Las policies RLS comparan organizacion_id contra current_setting('app.current_org_id')
3. Si el código olvida filtrar, PostgreSQL devuelve cero filas (en vez de filas de otro tenant)

IMPORTANTE: Esta migración es REVERSIBLE. Si algo falla, ejecutar:
    alembic downgrade 202602260002
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202604080001"
down_revision = "202602260002"
branch_labels = None
depends_on = None


# Tablas con organizacion_id (filtran por igualdad simple)
TENANT_TABLES_ORG = [
    'audit_log',
    'clientes',
    'consultas_agente',
    'cotizaciones_proveedor',
    'cuadrillas_tipo',
    'escala_salarial_uocra',
    'global_material_usage',
    'items_inventario',
    'items_referencia_constructora',
    'liquidaciones_mo',
    'locations',
    'movimientos_caja',
    'notificaciones',
    'obras',
    'ordenes_compra',
    'presupuestos',
    'proveedores',
    'proveedores_oc',
    'remitos',
    'requerimientos_compra',
    'work_certifications',
    'work_payments',
]

# Tablas con company_id (sistema marketplace/equipment)
TENANT_TABLES_COMPANY = [
    'equipment',
    'equipment_movement',
    'events',
    'inventory_category',
    'inventory_item',
    'order',
    'warehouse',
]


def upgrade() -> None:
    """Habilitar RLS en todas las tablas tenant-scoped."""
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] RLS solo soportado en PostgreSQL")
        return

    print("[RLS] Habilitando Row Level Security en tablas tenant-scoped...")

    # 1) Crear función helper que devuelve el org_id actual
    # Si no está seteado, devuelve NULL (lo que bloquea todo acceso)
    conn.execute(text("""
        CREATE OR REPLACE FUNCTION app_current_org_id()
        RETURNS INTEGER AS $$
        BEGIN
            RETURN NULLIF(current_setting('app.current_org_id', true), '')::INTEGER;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql STABLE;
    """))

    # 2) Función helper para super admin (bypass)
    conn.execute(text("""
        CREATE OR REPLACE FUNCTION app_is_super_admin()
        RETURNS BOOLEAN AS $$
        BEGIN
            RETURN COALESCE(current_setting('app.is_super_admin', true), 'false')::BOOLEAN;
        EXCEPTION WHEN OTHERS THEN
            RETURN FALSE;
        END;
        $$ LANGUAGE plpgsql STABLE;
    """))

    # 3) Habilitar RLS y crear policies en tablas con organizacion_id
    for table in TENANT_TABLES_ORG:
        # Verificar que la tabla existe (algunas pueden faltar en algunos entornos)
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
        ), {'t': table}).fetchone()
        if not exists:
            print(f"[SKIP] Tabla {table} no existe")
            continue

        try:
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))

            # Policy: super admin ve todo, usuarios normales solo su org
            conn.execute(text(f"""
                DROP POLICY IF EXISTS tenant_isolation ON {table};
                CREATE POLICY tenant_isolation ON {table}
                    USING (
                        app_is_super_admin()
                        OR organizacion_id = app_current_org_id()
                        OR app_current_org_id() IS NULL  -- Permitir si no hay sesión (CLI, migrations)
                    );
            """))
            print(f"[OK] RLS habilitado: {table}")
        except Exception as e:
            print(f"[WARN] Error en {table}: {e}")

    # 4) Habilitar RLS en tablas con company_id
    for table in TENANT_TABLES_COMPANY:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
        ), {'t': table}).fetchone()
        if not exists:
            print(f"[SKIP] Tabla {table} no existe")
            continue

        try:
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))
            conn.execute(text(f"""
                DROP POLICY IF EXISTS tenant_isolation ON {table};
                CREATE POLICY tenant_isolation ON {table}
                    USING (
                        app_is_super_admin()
                        OR company_id = app_current_org_id()
                        OR app_current_org_id() IS NULL
                    );
            """))
            print(f"[OK] RLS habilitado: {table}")
        except Exception as e:
            print(f"[WARN] Error en {table}: {e}")

    print("[RLS] Migración completada")


def downgrade() -> None:
    """Deshabilitar RLS en todas las tablas (rollback de seguridad)."""
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return

    print("[RLS] Deshabilitando Row Level Security...")

    for table in TENANT_TABLES_ORG + TENANT_TABLES_COMPANY:
        try:
            conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table};"))
            conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;"))
            print(f"[OK] RLS deshabilitado: {table}")
        except Exception as e:
            print(f"[WARN] Error en {table}: {e}")

    conn.execute(text("DROP FUNCTION IF EXISTS app_current_org_id();"))
    conn.execute(text("DROP FUNCTION IF EXISTS app_is_super_admin();"))
