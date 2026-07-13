# -*- coding: utf-8 -*-
"""Fase 1 roles personalizados: role_modules.org_id + tabla custom_roles

Revision ID: 202607130001
Revises: 202605060002
Create Date: 2026-07-13

Cambios:
  1. role_modules gana org_id (FK a organizaciones, ON DELETE CASCADE) y su
     UNIQUE pasa de (role, module) a (org_id, role, module). Los permisos por
     rol dejan de ser globales y pasan a ser por organización.
  2. Nueva tabla custom_roles: roles definibles por cada org.
  3. Data: se replican las filas globales de role_modules a cada org y se
     seedean los 4 roles base (admin/pm/tecnico/operario) en custom_roles.

Nota: se usa Integer (no UUID) porque organizaciones.id es Integer en OBYRA.
Idempotente (checkea existencia) para convivir con runtime_migrations.py.
"""
from alembic import op
import sqlalchemy as sa


revision = '202607130001'
down_revision = '202605060002'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    role_module_cols = [c['name'] for c in insp.get_columns('role_modules')]
    if 'org_id' not in role_module_cols:
        # 1) columna nullable primero (para poder backfillear)
        op.add_column('role_modules', sa.Column('org_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'fk_role_modules_org', 'role_modules', 'organizaciones',
            ['org_id'], ['id'], ondelete='CASCADE',
        )
        op.create_index('ix_role_modules_org_id', 'role_modules', ['org_id'])

        # 2) drop UNIQUE viejo (role, module) si existe
        uniques = [uc['name'] for uc in insp.get_unique_constraints('role_modules')]
        if 'unique_role_module' in uniques:
            op.drop_constraint('unique_role_module', 'role_modules', type_='unique')

        # 3) backfill: replicar cada fila global a TODAS las orgs, luego borrar globales
        op.execute("""
            INSERT INTO role_modules (role, module, can_view, can_edit, org_id)
            SELECT rm.role, rm.module, rm.can_view, rm.can_edit, o.id
            FROM role_modules rm
            CROSS JOIN organizaciones o
            WHERE rm.org_id IS NULL
        """)
        op.execute("DELETE FROM role_modules WHERE org_id IS NULL")

        # 4) NOT NULL + UNIQUE nuevo (org_id, role, module)
        op.alter_column('role_modules', 'org_id', existing_type=sa.Integer(), nullable=False)
        op.create_unique_constraint(
            'uq_role_module_org', 'role_modules', ['org_id', 'role', 'module']
        )

    # 5) tabla custom_roles
    if not insp.has_table('custom_roles'):
        op.create_table(
            'custom_roles',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('org_id', sa.Integer(),
                      sa.ForeignKey('organizaciones.id', ondelete='CASCADE'), nullable=False),
            sa.Column('nombre', sa.String(length=50), nullable=False),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint('org_id', 'nombre', name='uq_custom_role_org_nombre'),
        )
        op.create_index('ix_custom_roles_org_id', 'custom_roles', ['org_id'])

    # 6) seed de los 4 roles base por organización (idempotente)
    op.execute("""
        INSERT INTO custom_roles (org_id, nombre, descripcion, activo, created_at, updated_at)
        SELECT o.id, r.nombre, r.descripcion, TRUE, NOW(), NOW()
        FROM organizaciones o
        CROSS JOIN (VALUES
            ('admin', 'Administrador'),
            ('pm', 'Project Manager'),
            ('tecnico', 'Técnico'),
            ('operario', 'Operario')
        ) AS r(nombre, descripcion)
        ON CONFLICT (org_id, nombre) DO NOTHING
    """)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('custom_roles'):
        op.drop_table('custom_roles')

    role_module_cols = [c['name'] for c in insp.get_columns('role_modules')]
    if 'org_id' in role_module_cols:
        uniques = [uc['name'] for uc in insp.get_unique_constraints('role_modules')]
        if 'uq_role_module_org' in uniques:
            op.drop_constraint('uq_role_module_org', 'role_modules', type_='unique')
        try:
            op.drop_constraint('fk_role_modules_org', 'role_modules', type_='foreignkey')
        except Exception:
            pass
        try:
            op.drop_index('ix_role_modules_org_id', table_name='role_modules')
        except Exception:
            pass
        op.drop_column('role_modules', 'org_id')
        op.create_unique_constraint('unique_role_module', 'role_modules', ['role', 'module'])
