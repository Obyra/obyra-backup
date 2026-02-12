"""add composite performance indices for dashboard queries

Revision ID: 202601200001
Revises: 20260113_create_security_tables
Create Date: 2026-01-20
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "202601200001"
down_revision = "202601130001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Agrega índices COMPUESTOS para las queries más frecuentes del dashboard.

    Estos índices optimizan queries que filtran por múltiples columnas simultáneamente,
    como las del dashboard que siempre filtran por organizacion_id + estado.
    """
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] Índices compuestos solo soportados en PostgreSQL")
        return

    conn.execute(text("SET search_path TO app, public"))

    def index_exists(index_name: str) -> bool:
        result = conn.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = :index_name"),
            {"index_name": index_name}
        ).scalar()
        return result is not None

    def table_exists(table_name: str) -> bool:
        result = conn.execute(
            text("SELECT to_regclass(:table_name) IS NOT NULL"),
            {"table_name": f"app.{table_name}"}
        ).scalar()
        return result is True

    # Índices compuestos para queries frecuentes
    composite_indices = [
        # Dashboard: obras por org + estado (query más frecuente)
        ('obras', 'organizacion_id, estado', 'idx_obras_org_estado'),
        # Dashboard: presupuestos por org + estado
        ('presupuestos', 'organizacion_id, estado', 'idx_presupuestos_org_estado'),
        # Dashboard: presupuestos vencidos
        ('presupuestos', 'organizacion_id, fecha_vigencia', 'idx_presupuestos_org_vigencia'),
        # Inventario: items activos por org (búsqueda de materiales)
        ('item_inventario', 'organizacion_id, activo', 'idx_inventario_org_activo'),
        # Usuarios activos por org
        ('usuarios', 'organizacion_id, activo', 'idx_usuarios_org_activo'),
        # Eventos por org ordenados por fecha
        ('events', 'company_id, created_at DESC', 'idx_events_company_created'),
    ]

    print("[MIGRATION] Creando índices compuestos de performance...")

    for table, columns, idx_name in composite_indices:
        if not table_exists(table):
            print(f"  [SKIP] Tabla {table} no existe")
            continue

        if index_exists(idx_name):
            print(f"  [SKIP] Índice {idx_name} ya existe")
            continue

        try:
            conn.execute(text(f"CREATE INDEX {idx_name} ON {table}({columns})"))
            print(f"  [OK] {idx_name} creado en {table}({columns})")
        except Exception as e:
            print(f"  [WARN] No se pudo crear {idx_name}: {e}")

    # Índice parcial para presupuestos no eliminados (muy usado en dashboard)
    partial_idx = "idx_presupuestos_activos_vigencia"
    if table_exists('presupuestos') and not index_exists(partial_idx):
        try:
            conn.execute(text(f"""
                CREATE INDEX {partial_idx} ON presupuestos(organizacion_id, fecha_vigencia)
                WHERE deleted_at IS NULL
            """))
            print(f"  [OK] {partial_idx} (parcial) creado")
        except Exception as e:
            print(f"  [WARN] No se pudo crear índice parcial: {e}")

    # ANALYZE para actualizar estadísticas del planificador
    print("[MIGRATION] Actualizando estadísticas del planificador...")
    for table in ['obras', 'presupuestos', 'item_inventario', 'usuarios']:
        if table_exists(table):
            try:
                conn.execute(text(f"ANALYZE {table}"))
            except Exception:
                pass

    print("[OK] Índices compuestos creados exitosamente")


def downgrade() -> None:
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return

    conn.execute(text("SET search_path TO app, public"))

    indices_to_drop = [
        'idx_obras_org_estado',
        'idx_presupuestos_org_estado',
        'idx_presupuestos_org_vigencia',
        'idx_inventario_org_activo',
        'idx_usuarios_org_activo',
        'idx_events_company_created',
        'idx_presupuestos_activos_vigencia',
    ]

    for idx_name in indices_to_drop:
        try:
            conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        except Exception:
            pass
