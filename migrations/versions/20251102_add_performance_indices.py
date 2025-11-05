"""add performance indices for frequently queried columns"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202511020002"
down_revision = "202511020001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Agrega índices en columnas frecuentemente consultadas para mejorar performance.

    Índices a crear:
    1. usuarios.email - Login y búsquedas de usuarios
    2. usuarios.organizacion_id - Filtrado por organización
    3. obras.organizacion_id - Filtrado por organización
    4. obras.estado - Filtrado por estado de obra
    5. presupuestos.organizacion_id - Filtrado por organización
    6. presupuestos.estado - Filtrado por estado
    7. item_inventario.organizacion_id - Filtrado por organización
    8. item_inventario.categoria_id - Filtrado por categoría
    9. documentos.obra_id - Documentos por obra
    10. documentos.tipo_documento_id - Documentos por tipo
    """
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    # Lista de índices a crear (tabla, columna, nombre_indice)
    indices = [
        ('usuarios', 'email', 'idx_usuarios_email'),
        ('usuarios', 'organizacion_id', 'idx_usuarios_org_id'),
        ('usuarios', 'activo', 'idx_usuarios_activo'),
        ('obras', 'organizacion_id', 'idx_obras_org_id'),
        ('obras', 'estado', 'idx_obras_estado'),
        ('obras', 'fecha_inicio', 'idx_obras_fecha_inicio'),
        ('presupuestos', 'organizacion_id', 'idx_presupuestos_org_id'),
        ('presupuestos', 'estado', 'idx_presupuestos_estado'),
        ('item_inventario', 'organizacion_id', 'idx_inventario_org_id'),
        ('item_inventario', 'categoria_id', 'idx_inventario_categoria'),
        ('item_inventario', 'activo', 'idx_inventario_activo'),
    ]

    # Verificar tablas opcionales y agregar índices si existen
    optional_indices = [
        ('documentos', 'obra_id', 'idx_documentos_obra_id'),
        ('documentos', 'tipo_documento_id', 'idx_documentos_tipo'),
        ('documentos', 'estado', 'idx_documentos_estado'),
        ('proveedores', 'organizacion_id', 'idx_proveedores_org_id'),
        ('checklists_seguridad', 'obra_id', 'idx_checklists_obra_id'),
        ('checklists_seguridad', 'estado', 'idx_checklists_estado'),
    ]

    def index_exists(table_name: str, index_name: str) -> bool:
        """Verifica si un índice ya existe en PostgreSQL"""
        result = conn.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE indexname = :index_name"
            ),
            {"index_name": index_name}
        ).scalar()
        return result is not None

    def table_exists(table_name: str) -> bool:
        """Verifica si una tabla existe en PostgreSQL"""
        result = conn.execute(
            text("SELECT to_regclass(:table_name) IS NOT NULL"),
            {"table_name": f"app.{table_name}"}
        ).scalar()
        return result is True

    def create_index(table_name: str, column_name: str, index_name: str):
        """Crea un índice si no existe"""
        if not table_exists(table_name):
            print(f"[SKIP] Tabla {table_name} no existe")
            return

        if index_exists(table_name, index_name):
            print(f"[SKIP] Índice {index_name} ya existe")
            return

        try:
            conn.execute(
                text(f"CREATE INDEX {index_name} ON {table_name}({column_name})")
            )
            print(f"[OK] Índice {index_name} creado en {table_name}.{column_name}")
        except Exception as e:
            print(f"[WARN] No se pudo crear índice {index_name}: {e}")

    # Crear índices críticos
    print("[MIGRATION] Creando índices de performance...")
    for table, column, idx_name in indices:
        create_index(table, column, idx_name)

    # Crear índices opcionales (solo si las tablas existen)
    print("[MIGRATION] Creando índices opcionales...")
    for table, column, idx_name in optional_indices:
        create_index(table, column, idx_name)

    print("[OK] Índices de performance creados exitosamente")


def downgrade() -> None:
    """Elimina los índices creados"""
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    indices_to_drop = [
        'idx_usuarios_email',
        'idx_usuarios_org_id',
        'idx_usuarios_activo',
        'idx_obras_org_id',
        'idx_obras_estado',
        'idx_obras_fecha_inicio',
        'idx_presupuestos_org_id',
        'idx_presupuestos_estado',
        'idx_inventario_org_id',
        'idx_inventario_categoria',
        'idx_inventario_activo',
        'idx_documentos_obra_id',
        'idx_documentos_tipo',
        'idx_documentos_estado',
        'idx_proveedores_org_id',
        'idx_checklists_obra_id',
        'idx_checklists_estado',
    ]

    for idx_name in indices_to_drop:
        try:
            conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
            print(f"[OK] Índice {idx_name} eliminado")
        except Exception as e:
            print(f"[WARN] No se pudo eliminar índice {idx_name}: {e}")
