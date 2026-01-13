"""create security tables for seguridad_cumplimiento module

Revision ID: 202601130001
Revises: 202601070001
Create Date: 2026-01-13

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = '202601130001'
down_revision = '202601070001'  # after etapa_nombre
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Detectar si estamos en Railway (sin schema "app")
    import os
    is_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None or \
                 os.getenv("RAILWAY_PROJECT_ID") is not None

    # Set search_path for PostgreSQL
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg and not is_railway:
        # Solo en local con schema app
        conn.execute(text("SET search_path TO app, public"))

    # Check if tables already exist
    from sqlalchemy import inspect
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    # 1. Crear tabla protocolos_seguridad
    if 'protocolos_seguridad' not in existing_tables:
        op.create_table(
            'protocolos_seguridad',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('nombre', sa.String(length=200), nullable=False),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.Column('categoria', sa.String(length=50), nullable=False),
            sa.Column('obligatorio', sa.Boolean(), nullable=True, server_default='true'),
            sa.Column('frecuencia_revision', sa.Integer(), nullable=True, server_default='30'),
            sa.Column('fecha_creacion', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('activo', sa.Boolean(), nullable=True, server_default='true'),
            sa.Column('normativa_referencia', sa.String(length=200), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

    # 2. Crear tabla checklists_seguridad
    if 'checklists_seguridad' not in existing_tables:
        op.create_table(
            'checklists_seguridad',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('obra_id', sa.Integer(), nullable=False),
            sa.Column('protocolo_id', sa.Integer(), nullable=False),
            sa.Column('fecha_inspeccion', sa.Date(), nullable=False),
            sa.Column('inspector_id', sa.Integer(), nullable=False),
            sa.Column('estado', sa.String(length=20), nullable=True, server_default='pendiente'),
            sa.Column('puntuacion', sa.Integer(), nullable=True),
            sa.Column('observaciones', sa.Text(), nullable=True),
            sa.Column('acciones_correctivas', sa.Text(), nullable=True),
            sa.Column('fecha_completado', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['obra_id'], ['obras.id'], ),
            sa.ForeignKeyConstraint(['protocolo_id'], ['protocolos_seguridad.id'], ),
            sa.ForeignKeyConstraint(['inspector_id'], ['usuarios.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    # 3. Crear tabla items_checklist
    if 'items_checklist' not in existing_tables:
        op.create_table(
            'items_checklist',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('checklist_id', sa.Integer(), nullable=False),
            sa.Column('descripcion', sa.String(length=300), nullable=False),
            sa.Column('conforme', sa.Boolean(), nullable=True),
            sa.Column('observacion', sa.Text(), nullable=True),
            sa.Column('criticidad', sa.String(length=20), nullable=True, server_default='media'),
            sa.ForeignKeyConstraint(['checklist_id'], ['checklists_seguridad.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    # 4. Crear tabla incidentes_seguridad
    if 'incidentes_seguridad' not in existing_tables:
        op.create_table(
            'incidentes_seguridad',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('obra_id', sa.Integer(), nullable=False),
            sa.Column('fecha_incidente', sa.DateTime(), nullable=False),
            sa.Column('tipo_incidente', sa.String(length=50), nullable=False),
            sa.Column('gravedad', sa.String(length=20), nullable=False),
            sa.Column('descripcion', sa.Text(), nullable=False),
            sa.Column('ubicacion_exacta', sa.String(length=200), nullable=True),
            sa.Column('persona_afectada', sa.String(length=100), nullable=True),
            sa.Column('testigos', sa.Text(), nullable=True),
            sa.Column('primeros_auxilios', sa.Boolean(), nullable=True, server_default='false'),
            sa.Column('atencion_medica', sa.Boolean(), nullable=True, server_default='false'),
            sa.Column('dias_perdidos', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('causa_raiz', sa.Text(), nullable=True),
            sa.Column('acciones_inmediatas', sa.Text(), nullable=True),
            sa.Column('acciones_preventivas', sa.Text(), nullable=True),
            sa.Column('responsable_id', sa.Integer(), nullable=False),
            sa.Column('estado', sa.String(length=20), nullable=True, server_default='abierto'),
            sa.Column('fecha_cierre', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['obra_id'], ['obras.id'], ),
            sa.ForeignKeyConstraint(['responsable_id'], ['usuarios.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    # 5. Crear tabla certificaciones_personal
    if 'certificaciones_personal' not in existing_tables:
        op.create_table(
            'certificaciones_personal',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('usuario_id', sa.Integer(), nullable=False),
            sa.Column('tipo_certificacion', sa.String(length=100), nullable=False),
            sa.Column('entidad_emisora', sa.String(length=200), nullable=False),
            sa.Column('numero_certificado', sa.String(length=50), nullable=True),
            sa.Column('fecha_emision', sa.Date(), nullable=False),
            sa.Column('fecha_vencimiento', sa.Date(), nullable=True),
            sa.Column('archivo_certificado', sa.String(length=500), nullable=True),
            sa.Column('activo', sa.Boolean(), nullable=True, server_default='true'),
            sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    # 6. Crear tabla auditorias_seguridad
    if 'auditorias_seguridad' not in existing_tables:
        op.create_table(
            'auditorias_seguridad',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('obra_id', sa.Integer(), nullable=False),
            sa.Column('fecha_auditoria', sa.Date(), nullable=False),
            sa.Column('auditor_externo', sa.String(length=200), nullable=True),
            sa.Column('tipo_auditoria', sa.String(length=50), nullable=False),
            sa.Column('puntuacion_general', sa.Integer(), nullable=True),
            sa.Column('hallazgos_criticos', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('hallazgos_mayores', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('hallazgos_menores', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('informe_path', sa.String(length=500), nullable=True),
            sa.Column('plan_accion_path', sa.String(length=500), nullable=True),
            sa.Column('fecha_seguimiento', sa.Date(), nullable=True),
            sa.Column('estado', sa.String(length=20), nullable=True, server_default='programada'),
            sa.ForeignKeyConstraint(['obra_id'], ['obras.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    # Crear índices para mejorar performance
    if 'checklists_seguridad' in existing_tables or 'checklists_seguridad' not in existing_tables:
        try:
            op.create_index('ix_checklists_obra', 'checklists_seguridad', ['obra_id'])
            op.create_index('ix_checklists_estado', 'checklists_seguridad', ['estado'])
        except:
            pass  # Índices ya existen

    if 'incidentes_seguridad' in existing_tables or 'incidentes_seguridad' not in existing_tables:
        try:
            op.create_index('ix_incidentes_obra', 'incidentes_seguridad', ['obra_id'])
            op.create_index('ix_incidentes_fecha', 'incidentes_seguridad', ['fecha_incidente'])
            op.create_index('ix_incidentes_estado', 'incidentes_seguridad', ['estado'])
        except:
            pass  # Índices ya existen

    print("✅ Tablas de seguridad creadas exitosamente")


def downgrade() -> None:
    """Eliminar tablas de seguridad (solo si es necesario)"""
    op.drop_index('ix_incidentes_estado', table_name='incidentes_seguridad', if_exists=True)
    op.drop_index('ix_incidentes_fecha', table_name='incidentes_seguridad', if_exists=True)
    op.drop_index('ix_incidentes_obra', table_name='incidentes_seguridad', if_exists=True)
    op.drop_index('ix_checklists_estado', table_name='checklists_seguridad', if_exists=True)
    op.drop_index('ix_checklists_obra', table_name='checklists_seguridad', if_exists=True)

    op.drop_table('auditorias_seguridad', if_exists=True)
    op.drop_table('certificaciones_personal', if_exists=True)
    op.drop_table('incidentes_seguridad', if_exists=True)
    op.drop_table('items_checklist', if_exists=True)
    op.drop_table('checklists_seguridad', if_exists=True)
    op.drop_table('protocolos_seguridad', if_exists=True)
