# -*- coding: utf-8 -*-
"""provider_price_list: organizacion_id nullable (base global) + unique COALESCE

Revision ID: 202607150001
Revises: 202607130002
Create Date: 2026-07-15

Fase 1 IA presupuestos — base de precios global:
  1. `organizacion_id` pasa a NULLABLE. NULL = base global OBYRA (accesible por
     todas las orgs via el fallback de precio_recurso_service; los precios de
     una org pisan la global).
  2. El indice UNIQUE se recrea con COALESCE(organizacion_id, 0) para que las
     filas globales (org NULL) deduped entre si (antes usaba organizacion_id
     directo, y Postgres trata cada NULL como distinto -> permitiria duplicados).

No mueve datos: la migracion de filas existentes a NULL se hace aparte (por
org, contra la base cargada), para no tocar listas propias org-especificas.
Idempotente.
"""
from alembic import op


revision = '202607150001'
down_revision = '202607130002'
branch_labels = None
depends_on = None


def upgrade():
    # 1) organizacion_id nullable
    op.execute("ALTER TABLE provider_price_list ALTER COLUMN organizacion_id DROP NOT NULL")

    # 2) recrear el UNIQUE con COALESCE(organizacion_id, 0)
    op.execute("DROP INDEX IF EXISTS uq_ppl_org_prov_desc_un_zona_modalidad")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ppl_org_prov_desc_un_zona_modalidad
            ON provider_price_list(
                COALESCE(organizacion_id, 0),
                COALESCE(proveedor_id, 0),
                descripcion_normalizada,
                unidad,
                COALESCE(zona, ''),
                COALESCE(modalidad, 'compra')
            )
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_ppl_org_prov_desc_un_zona_modalidad")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ppl_org_prov_desc_un_zona_modalidad
            ON provider_price_list(
                organizacion_id, COALESCE(proveedor_id, 0),
                descripcion_normalizada, unidad,
                COALESCE(zona, ''), COALESCE(modalidad, 'compra')
            )
    """)
    # NOTA: no se re-agrega NOT NULL en downgrade (podria haber filas globales).
