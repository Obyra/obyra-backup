"""precio_observado: tabla append-only de precios observados (Etapa 1 base IA)

Revision ID: 202605050001
Revises: 202604290001
Create Date: 2026-05-05

Crea tabla `precio_observado` para capturar precios crudos provenientes de
Excel importados con precios > 0 (Etapa 1) y, mas adelante, de listas
propias, OCs completadas y cotizaciones de proveedor.

Es append-only por diseno: cada observacion es un registro inmutable con
trazabilidad completa al archivo / presupuesto / item de origen.

NO modifica el calculo de precios actual — solo agrega capacidad de captura.

Idempotente: usa CREATE TABLE IF NOT EXISTS y CREATE INDEX IF NOT EXISTS.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202605050001"
down_revision = "202604290001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] Migracion solo soportada en PostgreSQL")
        return

    print("[PRECIO_OBSERVADO] Iniciando migracion...")

    # ============================================================
    # Tabla precio_observado
    # ============================================================
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS precio_observado (
                id BIGSERIAL PRIMARY KEY,
                organizacion_id INTEGER NOT NULL
                    REFERENCES organizaciones(id) ON DELETE CASCADE,

                origen_tipo VARCHAR(30) NOT NULL,
                origen_archivo_id INTEGER
                    REFERENCES presupuesto_archivo(id) ON DELETE SET NULL,
                origen_presupuesto_id INTEGER
                    REFERENCES presupuestos(id) ON DELETE SET NULL,
                origen_item_presupuesto_id INTEGER
                    REFERENCES items_presupuesto(id) ON DELETE SET NULL,

                descripcion TEXT NOT NULL,
                descripcion_normalizada VARCHAR(300) NOT NULL,
                unidad VARCHAR(20) NOT NULL,
                rubro_nombre VARCHAR(100),
                tipo_recurso VARCHAR(20) NOT NULL DEFAULT 'item_completo',

                precio_unitario NUMERIC(15, 2) NOT NULL,
                moneda VARCHAR(3) NOT NULL DEFAULT 'ARS',

                fecha_observado DATE NOT NULL,

                valido BOOLEAN NOT NULL DEFAULT TRUE,
                notas TEXT,

                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("[OK] precio_observado creada")
    except Exception as e:
        print(f"[ERROR] precio_observado: {e}")
        raise

    # Constraint UNIQUE para deduplicacion en re-import del mismo archivo.
    # Postgres no compara NULLs como iguales en UNIQUE: la tupla (org, archivo,
    # item, tipo) solo aplica cuando los 4 estan completos — perfecto para el
    # caso 'excel_pliego'. Para futuros origen_tipo='lista_propia' donde
    # archivo_id sera NULL, este constraint no aplica (lo que es correcto).
    try:
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_precio_obs_archivo_item_tipo
                ON precio_observado(
                    organizacion_id,
                    origen_archivo_id,
                    origen_item_presupuesto_id,
                    tipo_recurso
                )
                WHERE origen_archivo_id IS NOT NULL
                  AND origen_item_presupuesto_id IS NOT NULL;
        """))
        print("[OK] uq_precio_obs_archivo_item_tipo (parcial)")
    except Exception as e:
        print(f"[ERROR] uq_precio_obs_archivo_item_tipo: {e}")

    # Indices de busqueda
    indices = [
        ("ix_precio_obs_org_desc_unidad",
         "(organizacion_id, descripcion_normalizada, unidad)"),
        ("ix_precio_obs_org_rubro",
         "(organizacion_id, rubro_nombre)"),
        ("ix_precio_obs_fecha",
         "(fecha_observado)"),
        ("ix_precio_obs_archivo",
         "(origen_archivo_id)"),
        ("ix_precio_obs_origen_tipo",
         "(origen_tipo)"),
        ("ix_precio_obs_org",
         "(organizacion_id)"),
    ]
    for name, cols in indices:
        try:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON precio_observado{cols};"
            ))
            print(f"[OK] {name}")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    print("[PRECIO_OBSERVADO] Migracion completada.")


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return
    try:
        conn.execute(text("DROP TABLE IF EXISTS precio_observado CASCADE;"))
        print("[OK] precio_observado eliminada")
    except Exception as e:
        print(f"[ERROR] downgrade precio_observado: {e}")
