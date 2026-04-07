"""create cierres_obra and actas_entrega tables

Revision ID: 202604080003
Revises: 202604080002
Create Date: 2026-04-08

Crea las tablas para el módulo de Cierre Formal de Obra:
- cierres_obra: registro del proceso de cierre
- actas_entrega: actas firmadas por el cliente

Idempotente: usa CREATE TABLE IF NOT EXISTS.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "202604080003"
down_revision = "202604080002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crear tablas de cierre de obra."""
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        print("[SKIP] Migración solo soportada en PostgreSQL")
        return

    print("[CIERRE_OBRA] Creando tablas...")

    # Tabla cierres_obra
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cierres_obra (
                id SERIAL PRIMARY KEY,
                obra_id INTEGER NOT NULL REFERENCES obras(id),
                organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                estado VARCHAR(20) NOT NULL DEFAULT 'borrador',
                fecha_inicio_cierre TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_cierre_definitivo TIMESTAMP,
                fecha_anulacion TIMESTAMP,
                iniciado_por_id INTEGER NOT NULL REFERENCES usuarios(id),
                cerrado_por_id INTEGER REFERENCES usuarios(id),
                anulado_por_id INTEGER REFERENCES usuarios(id),
                checklist_data TEXT,
                observaciones TEXT,
                motivo_anulacion TEXT,
                presupuesto_inicial NUMERIC(15,2),
                monto_certificado NUMERIC(15,2),
                monto_cobrado NUMERIC(15,2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        # Índices
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cierres_obra_obra_id ON cierres_obra(obra_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cierres_obra_org_id ON cierres_obra(organizacion_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cierres_obra_iniciado_por ON cierres_obra(iniciado_por_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cierre_obra_org ON cierres_obra(organizacion_id, estado);"))
        print("[OK] cierres_obra creada")
    except Exception as e:
        print(f"[ERROR] cierres_obra: {e}")

    # Tabla actas_entrega
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS actas_entrega (
                id SERIAL PRIMARY KEY,
                cierre_id INTEGER NOT NULL REFERENCES cierres_obra(id),
                obra_id INTEGER NOT NULL REFERENCES obras(id),
                organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                tipo VARCHAR(20) NOT NULL DEFAULT 'definitiva',
                fecha_acta DATE NOT NULL,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                recibido_por_nombre VARCHAR(200) NOT NULL,
                recibido_por_dni VARCHAR(20),
                recibido_por_cargo VARCHAR(100),
                firmado BOOLEAN DEFAULT FALSE,
                fecha_firma TIMESTAMP,
                firma_imagen_path VARCHAR(500),
                descripcion TEXT,
                observaciones_cliente TEXT,
                observaciones_internas TEXT,
                items_entregados TEXT,
                plazo_garantia_meses INTEGER,
                fecha_inicio_garantia DATE,
                creado_por_id INTEGER NOT NULL REFERENCES usuarios(id)
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_actas_entrega_cierre ON actas_entrega(cierre_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_actas_entrega_obra ON actas_entrega(obra_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_actas_entrega_org ON actas_entrega(organizacion_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_actas_entrega_creado_por ON actas_entrega(creado_por_id);"))
        print("[OK] actas_entrega creada")
    except Exception as e:
        print(f"[ERROR] actas_entrega: {e}")

    print("[CIERRE_OBRA] Migración completada")


def downgrade() -> None:
    """Eliminar tablas de cierre de obra."""
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if not is_pg:
        return

    print("[CIERRE_OBRA] Eliminando tablas...")
    try:
        conn.execute(text("DROP TABLE IF EXISTS actas_entrega CASCADE;"))
        print("[OK] actas_entrega eliminada")
    except Exception as e:
        print(f"[ERROR] actas_entrega: {e}")

    try:
        conn.execute(text("DROP TABLE IF EXISTS cierres_obra CASCADE;"))
        print("[OK] cierres_obra eliminada")
    except Exception as e:
        print(f"[ERROR] cierres_obra: {e}")
