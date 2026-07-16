# -*- coding: utf-8 -*-
"""Fase 2.5 IA presupuestos: aprendizaje por org (mapeo_item_aprendido)

Revision ID: 202607160001
Revises: 202607150002
Create Date: 2026-07-16

Idempotente (IF NOT EXISTS) para convivir con runtime_migrations.py.
"""
from alembic import op


revision = '202607160001'
down_revision = '202607150002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS mapeo_item_aprendido (
            id SERIAL PRIMARY KEY,
            organizacion_id INTEGER NOT NULL
                REFERENCES organizaciones(id) ON DELETE CASCADE,
            texto_normalizado VARCHAR(300) NOT NULL,
            texto_original VARCHAR(400),
            regla_id VARCHAR(80),
            nivel VARCHAR(20) NOT NULL DEFAULT 'estandar',
            tratamiento VARCHAR(20) NOT NULL DEFAULT 'apu',
            veces_usado INTEGER NOT NULL DEFAULT 0,
            created_by_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mapeo_org_texto
            ON mapeo_item_aprendido(organizacion_id, texto_normalizado)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mapeo_org ON mapeo_item_aprendido(organizacion_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS mapeo_item_aprendido")
