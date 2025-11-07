"""add clientes table and cliente_id to presupuestos

Revision ID: 20251107_add_clientes
Revises: 20251102_add_super_admin_flag
Create Date: 2025-11-07 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '202511070001'
down_revision = '202511020001'
branch_labels = None
depends_on = None


def upgrade():
    # Crear tabla clientes
    op.create_table('clientes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organizacion_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('apellido', sa.String(length=100), nullable=False),
        sa.Column('tipo_documento', sa.String(length=10), nullable=False, server_default='DNI'),
        sa.Column('numero_documento', sa.String(length=20), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('telefono', sa.String(length=20), nullable=True),
        sa.Column('telefono_alternativo', sa.String(length=20), nullable=True),
        sa.Column('direccion', sa.String(length=200), nullable=True),
        sa.Column('ciudad', sa.String(length=100), nullable=True),
        sa.Column('provincia', sa.String(length=100), nullable=True),
        sa.Column('codigo_postal', sa.String(length=10), nullable=True),
        sa.Column('empresa', sa.String(length=150), nullable=True),
        sa.Column('notas', sa.Text(), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('fecha_creacion', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.Column('fecha_modificacion', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['organizacion_id'], ['organizaciones.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Crear índices para mejorar el rendimiento
    op.create_index(op.f('ix_clientes_organizacion_id'), 'clientes', ['organizacion_id'], unique=False)
    op.create_index(op.f('ix_clientes_email'), 'clientes', ['email'], unique=False)
    op.create_index(op.f('ix_clientes_numero_documento'), 'clientes', ['numero_documento'], unique=False)

    # Agregar columna cliente_id a presupuestos
    op.add_column('presupuestos', sa.Column('cliente_id', sa.Integer(), nullable=True))
    op.create_foreign_key('presupuestos_cliente_id_fkey', 'presupuestos', 'clientes', ['cliente_id'], ['id'])
    op.create_index(op.f('ix_presupuestos_cliente_id'), 'presupuestos', ['cliente_id'], unique=False)

    # Agregar columna cliente_id a obras
    op.add_column('obras', sa.Column('cliente_id', sa.Integer(), nullable=True))
    op.create_foreign_key('obras_cliente_id_fkey', 'obras', 'clientes', ['cliente_id'], ['id'])
    op.create_index(op.f('ix_obras_cliente_id'), 'obras', ['cliente_id'], unique=False)


def downgrade():
    # Remover relación de obras
    op.drop_index(op.f('ix_obras_cliente_id'), table_name='obras')
    op.drop_constraint('obras_cliente_id_fkey', 'obras', type_='foreignkey')
    op.drop_column('obras', 'cliente_id')

    # Remover relación de presupuestos
    op.drop_index(op.f('ix_presupuestos_cliente_id'), table_name='presupuestos')
    op.drop_constraint('presupuestos_cliente_id_fkey', 'presupuestos', type_='foreignkey')
    op.drop_column('presupuestos', 'cliente_id')

    # Remover tabla clientes
    op.drop_index(op.f('ix_clientes_numero_documento'), table_name='clientes')
    op.drop_index(op.f('ix_clientes_email'), table_name='clientes')
    op.drop_index(op.f('ix_clientes_organizacion_id'), table_name='clientes')
    op.drop_table('clientes')
