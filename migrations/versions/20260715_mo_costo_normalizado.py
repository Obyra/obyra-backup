# -*- coding: utf-8 -*-
"""Fase 2.0 IA presupuestos: costo MO normalizado

Revision ID: 202607150002
Revises: 202607150001
Create Date: 2026-07-15

Modelo normalizado de costo empresa de mano de obra:
  1. CategoriaJornal.valor_hora_convenio (input canonico de la paritaria).
  2. estructura_recargos_mo + recargo_mo_linea: recargos parametrizados por
     lineas (presentismo, F931, UOCRA, comida, ...), compartidos por todas las
     categorias, editables en un lugar. Cada linea declara su base/periodicidad.
  3. indice_actualizacion: serie ICAC/ICP/ICC para reindexar presupuestos viejos.

Idempotente (IF NOT EXISTS) para convivir con runtime_migrations.py.
"""
from alembic import op


revision = '202607150002'
down_revision = '202607150001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE categorias_jornal ADD COLUMN IF NOT EXISTS valor_hora_convenio NUMERIC(15,2)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS estructura_recargos_mo (
            id SERIAL PRIMARY KEY,
            organizacion_id INTEGER REFERENCES organizaciones(id) ON DELETE CASCADE,
            nombre VARCHAR(120) NOT NULL DEFAULT 'Estructura de recargos',
            zona VARCHAR(40) NOT NULL DEFAULT 'CABA',
            vigencia_desde DATE NOT NULL DEFAULT CURRENT_DATE,
            vigencia_hasta DATE,
            horas_mensuales INTEGER NOT NULL DEFAULT 176,
            horas_por_dia INTEGER NOT NULL DEFAULT 8,
            fuente VARCHAR(60) NOT NULL DEFAULT 'manual',
            notas TEXT,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_erm_org_zona ON estructura_recargos_mo(organizacion_id, zona)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_erm_vigencia ON estructura_recargos_mo(vigencia_desde, vigencia_hasta)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_erm_activo ON estructura_recargos_mo(activo)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS recargo_mo_linea (
            id SERIAL PRIMARY KEY,
            estructura_id INTEGER NOT NULL
                REFERENCES estructura_recargos_mo(id) ON DELETE CASCADE,
            orden INTEGER NOT NULL DEFAULT 0,
            concepto VARCHAR(80) NOT NULL,
            grupo VARCHAR(30) NOT NULL,
            tipo_calculo VARCHAR(20) NOT NULL,
            valor NUMERIC(14,4) NOT NULL DEFAULT 0,
            notas VARCHAR(200),
            activo BOOLEAN NOT NULL DEFAULT TRUE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_rml_estructura ON recargo_mo_linea(estructura_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS indice_actualizacion (
            id SERIAL PRIMARY KEY,
            organizacion_id INTEGER REFERENCES organizaciones(id) ON DELETE CASCADE,
            tipo VARCHAR(10) NOT NULL,
            capitulo VARCHAR(30) NOT NULL DEFAULT 'general',
            periodo VARCHAR(7) NOT NULL,
            valor_indice NUMERIC(16,4) NOT NULL,
            fuente VARCHAR(60) NOT NULL DEFAULT 'manual',
            notas TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_indice_org_tipo_cap_periodo
            ON indice_actualizacion(COALESCE(organizacion_id, 0), tipo, capitulo, periodo)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_indice_tipo_cap ON indice_actualizacion(tipo, capitulo)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS recargo_mo_linea")
    op.execute("DROP TABLE IF EXISTS estructura_recargos_mo")
    op.execute("DROP TABLE IF EXISTS indice_actualizacion")
    op.execute("ALTER TABLE categorias_jornal DROP COLUMN IF EXISTS valor_hora_convenio")
