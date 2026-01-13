"""add etapa_nombre column to items_presupuesto and backfill from ia_payload"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa
import json

revision = "202601070001"
down_revision = "20251201_webhooks"  # after processed_webhooks
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

    # Check if table exists before altering
    if is_pg:
        # Buscar en el schema correcto según el ambiente
        if is_railway:
            # Railway usa public
            table_exists = conn.execute(
                text("SELECT to_regclass('public.items_presupuesto')")
            ).scalar()
        else:
            # Local usa app
            table_exists = conn.execute(
                text("SELECT to_regclass('app.items_presupuesto')")
            ).scalar()
    else:
        from sqlalchemy import inspect
        insp = inspect(conn)
        table_exists = 'items_presupuesto' in insp.get_table_names()

    if not table_exists:
        return

    # Get existing columns
    from sqlalchemy import inspect
    insp = inspect(conn)
    columns = {c["name"] for c in insp.get_columns("items_presupuesto")}

    # Add etapa_nombre column
    if "etapa_nombre" not in columns:
        coltype = "VARCHAR(100)" if is_pg else "VARCHAR(100)"
        conn.execute(text(f"ALTER TABLE items_presupuesto ADD COLUMN etapa_nombre {coltype}"))

    # Backfill etapa_nombre from ia_payload in datos_proyecto
    # Get all presupuestos with datos_proyecto containing ia_payload
    result = conn.execute(text("""
        SELECT p.id, p.datos_proyecto
        FROM presupuestos p
        WHERE p.datos_proyecto IS NOT NULL
        AND p.datos_proyecto LIKE '%ia_payload%'
    """))

    for row in result:
        presupuesto_id = row[0]
        datos_proyecto = row[1]

        try:
            datos = json.loads(datos_proyecto) if isinstance(datos_proyecto, str) else datos_proyecto
            ia_payload = datos.get('ia_payload', {})
            etapas = ia_payload.get('etapas', [])

            # Get moneda from ia_payload
            moneda_ia = ia_payload.get('moneda', 'ARS')

            # Build a mapping of descripcion -> etapa_nombre and prices for this presupuesto
            for etapa in etapas:
                etapa_nombre = etapa.get('nombre', 'Sin Etapa')
                items = etapa.get('items', [])

                for item in items:
                    descripcion = item.get('descripcion', '')
                    if descripcion:
                        # Get USD prices from item
                        precio_unit = item.get('precio_unit', 0)
                        subtotal = item.get('subtotal', 0)

                        # If moneda is USD, precio_unit is already in USD
                        if moneda_ia == 'USD':
                            price_unit_usd = precio_unit
                            total_usd = subtotal
                        else:
                            # For ARS, we don't have USD values in ia_payload
                            price_unit_usd = None
                            total_usd = None

                        # Update items that match this presupuesto and descripcion
                        if price_unit_usd is not None:
                            conn.execute(text("""
                                UPDATE items_presupuesto
                                SET etapa_nombre = :etapa_nombre,
                                    price_unit_currency = :price_unit_usd,
                                    total_currency = :total_usd
                                WHERE presupuesto_id = :presupuesto_id
                                AND descripcion = :descripcion
                                AND etapa_nombre IS NULL
                            """), {
                                'etapa_nombre': etapa_nombre,
                                'presupuesto_id': presupuesto_id,
                                'descripcion': descripcion,
                                'price_unit_usd': price_unit_usd,
                                'total_usd': total_usd
                            })
                        else:
                            conn.execute(text("""
                                UPDATE items_presupuesto
                                SET etapa_nombre = :etapa_nombre
                                WHERE presupuesto_id = :presupuesto_id
                                AND descripcion = :descripcion
                                AND etapa_nombre IS NULL
                            """), {
                                'etapa_nombre': etapa_nombre,
                                'presupuesto_id': presupuesto_id,
                                'descripcion': descripcion
                            })
        except (json.JSONDecodeError, TypeError, AttributeError):
            # Skip if JSON is invalid
            continue


def downgrade() -> None:
    pass
