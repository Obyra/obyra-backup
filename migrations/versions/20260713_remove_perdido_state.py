# -*- coding: utf-8 -*-
"""Eliminar estado 'perdido' muerto de presupuestos

Revision ID: 202607130002
Revises: 202607130001
Create Date: 2026-07-13

El estado 'perdido' era una feature a medio construir: las columnas
perdido_motivo/perdido_fecha nunca se poblaban (no había endpoint que las
seteara — el JS apuntaba a /perder que devuelve 404). Se elimina.

  1. Los presupuestos que hubieran quedado en estado='perdido' (vía el
     cambiar_estado genérico) se migran a 'rechazado', que es el estado
     "real" equivalente.
  2. Se dropean las columnas perdido_motivo y perdido_fecha.

Idempotente (checkea existencia) para convivir con runtime_migrations.py.
"""
from alembic import op
import sqlalchemy as sa


revision = '202607130002'
down_revision = '202607130001'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1) Migrar cualquier presupuesto 'perdido' -> 'rechazado' antes de dropear.
    op.execute("UPDATE presupuestos SET estado = 'rechazado' WHERE estado = 'perdido'")

    # 2) Dropear las columnas muertas.
    cols = [c['name'] for c in insp.get_columns('presupuestos')]
    if 'perdido_motivo' in cols:
        op.drop_column('presupuestos', 'perdido_motivo')
    if 'perdido_fecha' in cols:
        op.drop_column('presupuestos', 'perdido_fecha')


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c['name'] for c in insp.get_columns('presupuestos')]
    if 'perdido_motivo' not in cols:
        op.add_column('presupuestos', sa.Column('perdido_motivo', sa.Text(), nullable=True))
    if 'perdido_fecha' not in cols:
        op.add_column('presupuestos', sa.Column('perdido_fecha', sa.DateTime(), nullable=True))
