"""add missing FK indices for performance

Revision ID: 202604080002
Revises: 202604080001
Create Date: 2026-04-08

Agrega índices a Foreign Keys que no tenían índice. Esto mejora dramáticamente
la performance de:
- JOINs entre tablas
- DELETE en tablas padre (PostgreSQL debe escanear las tablas hijas)
- Filtros por columnas FK

Los índices se crean con IF NOT EXISTS, así que es 100% idempotente.
Si ya existen (de migraciones previas o creados manualmente), no se duplican.

PostgreSQL con CREATE INDEX IF NOT EXISTS no bloquea writes
(usa CREATE INDEX que sí bloquea, pero solo brevemente para tablas tenant-scoped).

Para tablas grandes en producción, considerar usar CREATE INDEX CONCURRENTLY,
pero eso requiere ejecutarse fuera de transacción (no compatible con Alembic auto).
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202604080002"
down_revision = "202604080001"
branch_labels = None
depends_on = None


# Lista de índices a crear: (table, column, index_name)
# Solo los más críticos para queries frecuentes y DELETE
INDICES = [
    # ── Presupuestos
    ('presupuestos', 'obra_id', 'ix_presupuestos_obra_id'),
    ('presupuestos', 'cliente_id', 'ix_presupuestos_cliente_id'),
    ('items_presupuesto', 'presupuesto_id', 'ix_items_presupuesto_pres_id'),
    ('items_presupuesto', 'etapa_id', 'ix_items_presupuesto_etapa_id'),
    ('items_presupuesto', 'item_inventario_id', 'ix_items_presupuesto_item_inv'),

    # ── Tareas y avances (alto volumen)
    ('tareas_etapa', 'etapa_id', 'ix_tareas_etapa_etapa_id'),
    ('tareas_etapa', 'responsable_id', 'ix_tareas_etapa_responsable'),
    ('tareas_etapa', 'item_presupuesto_id', 'ix_tareas_etapa_item_pres'),
    ('tarea_avances', 'tarea_id', 'ix_tarea_avances_tarea_id'),
    ('tarea_avances', 'user_id', 'ix_tarea_avances_user_id'),
    ('tarea_avances', 'confirmed_by', 'ix_tarea_avances_confirmed_by'),
    ('tarea_avances', 'certificacion_id', 'ix_tarea_avances_cert_id'),
    ('tarea_adjuntos', 'tarea_id', 'ix_tarea_adjuntos_tarea_id'),
    ('tarea_adjuntos', 'avance_id', 'ix_tarea_adjuntos_avance_id'),
    ('tarea_adjuntos', 'uploaded_by', 'ix_tarea_adjuntos_uploaded_by'),
    ('tarea_miembros', 'tarea_id', 'ix_tarea_miembros_tarea_id'),
    ('tarea_miembros', 'user_id', 'ix_tarea_miembros_user_id'),
    ('tarea_responsables', 'tarea_id', 'ix_tarea_responsables_tarea_id'),
    ('tarea_responsables', 'user_id', 'ix_tarea_responsables_user_id'),

    # ── Asignaciones de obra
    ('asignaciones_obra', 'obra_id', 'ix_asignaciones_obra_obra_id'),
    ('asignaciones_obra', 'usuario_id', 'ix_asignaciones_obra_user_id'),
    ('obra_miembros', 'obra_id', 'ix_obra_miembros_obra_id'),
    ('obra_miembros', 'usuario_id', 'ix_obra_miembros_user_id'),

    # ── Fichadas (alto volumen, 2/día/operario)
    ('fichadas', 'usuario_id', 'ix_fichadas_usuario_id'),

    # ── Inventario (movimientos)
    ('movimientos_inventario', 'item_id', 'ix_movimientos_inv_item_id'),
    ('uso_inventario', 'obra_id', 'ix_uso_inventario_obra_id'),
    ('uso_inventario', 'item_id', 'ix_uso_inventario_item_id'),

    # ── Notificaciones
    ('notificaciones', 'usuario_id', 'ix_notificaciones_usuario_id'),
    ('notificaciones', 'organizacion_id', 'ix_notificaciones_org_id'),

    # ── Equipment
    ('equipment_assignment', 'equipment_id', 'ix_equipment_assign_eq_id'),
    ('equipment_assignment', 'project_id', 'ix_equipment_assign_proj_id'),
    ('equipment_usage', 'equipment_id', 'ix_equipment_usage_eq_id'),
    ('equipment_usage', 'project_id', 'ix_equipment_usage_proj_id'),
    ('maintenance_task', 'equipment_id', 'ix_maintenance_eq_id'),

    # ── Auth y memberships
    ('usuarios', 'organizacion_id', 'ix_usuarios_org_id'),
    ('usuarios', 'primary_org_id', 'ix_usuarios_primary_org_id'),

    # ── Stock (sistema nuevo)
    ('stock_ubicacion', 'location_id', 'ix_stock_ubicacion_loc_id'),
    ('stock_ubicacion', 'item_inventario_id', 'ix_stock_ubicacion_item_id'),
    ('stock', 'item_id', 'ix_stock_item_id'),
    ('stock', 'warehouse_id', 'ix_stock_warehouse_id'),

    # ── Niveles de presupuesto
    ('niveles_presupuesto', 'presupuesto_id', 'ix_niveles_pres_pres_id'),

    # ── Memberships
    ('org_memberships', 'invited_by', 'ix_org_memberships_invited_by'),
]


def upgrade() -> None:
    """Crear índices faltantes (idempotente con IF NOT EXISTS)."""
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] Índices solo se crean en PostgreSQL")
        return

    print(f"[INDICES] Creando {len(INDICES)} índices (con IF NOT EXISTS)...")

    created = 0
    skipped_missing = 0
    errors = 0

    for table, column, index_name in INDICES:
        # Verificar que la tabla existe
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
        ), {'t': table}).fetchone()

        if not exists:
            print(f"[SKIP] Tabla no existe: {table}")
            skipped_missing += 1
            continue

        # Verificar que la columna existe
        col_exists = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"
        ), {'t': table, 'c': column}).fetchone()

        if not col_exists:
            print(f"[SKIP] Columna no existe: {table}.{column}")
            skipped_missing += 1
            continue

        try:
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column});'
            ))
            print(f"[OK] {index_name}")
            created += 1
        except Exception as e:
            print(f"[ERROR] {index_name}: {e}")
            errors += 1

    print(f"[INDICES] Completado: {created} creados, {skipped_missing} skipped, {errors} errores")


def downgrade() -> None:
    """Eliminar los índices creados (rollback)."""
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return

    for table, column, index_name in INDICES:
        try:
            conn.execute(text(f'DROP INDEX IF EXISTS {index_name};'))
        except Exception as e:
            print(f"[WARN] No se pudo eliminar {index_name}: {e}")
