"""create work certification and payment tables"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202509010001"
down_revision = "202503300001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Set search_path for PostgreSQL
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    # Create work_certifications table
    if is_pg:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS work_certifications (
                id SERIAL PRIMARY KEY,
                obra_id INTEGER NOT NULL,
                organizacion_id INTEGER NOT NULL,
                periodo_desde DATE,
                periodo_hasta DATE,
                porcentaje_avance NUMERIC(7,3) DEFAULT 0,
                monto_certificado_ars NUMERIC(15,2) DEFAULT 0,
                monto_certificado_usd NUMERIC(15,2) DEFAULT 0,
                moneda_base VARCHAR(3) DEFAULT 'ARS',
                tc_usd NUMERIC(12,4),
                indice_cac NUMERIC(12,4),
                estado VARCHAR(20) DEFAULT 'borrador',
                notas TEXT,
                created_by_id INTEGER,
                approved_by_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS work_certifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                obra_id INTEGER NOT NULL,
                organizacion_id INTEGER NOT NULL,
                periodo_desde DATE,
                periodo_hasta DATE,
                porcentaje_avance NUMERIC DEFAULT 0,
                monto_certificado_ars NUMERIC DEFAULT 0,
                monto_certificado_usd NUMERIC DEFAULT 0,
                moneda_base TEXT DEFAULT 'ARS',
                tc_usd NUMERIC,
                indice_cac NUMERIC,
                estado TEXT DEFAULT 'borrador',
                notas TEXT,
                created_by_id INTEGER,
                approved_by_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                approved_at DATETIME
            )
        """))

    # Create index on work_certifications
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_work_certifications_obra_estado
        ON work_certifications(obra_id, estado)
    """))

    # Create work_certification_items table
    if is_pg:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS work_certification_items (
                id SERIAL PRIMARY KEY,
                certificacion_id INTEGER NOT NULL,
                etapa_id INTEGER,
                tarea_id INTEGER,
                porcentaje_aplicado NUMERIC(7,3) DEFAULT 0,
                monto_ars NUMERIC(15,2) DEFAULT 0,
                monto_usd NUMERIC(15,2) DEFAULT 0,
                fuente_avance VARCHAR(20) DEFAULT 'manual',
                resumen_avance TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS work_certification_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                certificacion_id INTEGER NOT NULL,
                etapa_id INTEGER,
                tarea_id INTEGER,
                porcentaje_aplicado NUMERIC DEFAULT 0,
                monto_ars NUMERIC DEFAULT 0,
                monto_usd NUMERIC DEFAULT 0,
                fuente_avance TEXT DEFAULT 'manual',
                resumen_avance TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

    # Create index on work_certification_items
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_work_certification_items_certificacion
        ON work_certification_items(certificacion_id)
    """))

    # Create work_payments table
    if is_pg:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS work_payments (
                id SERIAL PRIMARY KEY,
                certificacion_id INTEGER,
                obra_id INTEGER NOT NULL,
                organizacion_id INTEGER NOT NULL,
                operario_id INTEGER,
                metodo_pago VARCHAR(30) NOT NULL,
                moneda VARCHAR(3) DEFAULT 'ARS',
                monto NUMERIC(15,2) NOT NULL,
                tc_usd_pago NUMERIC(12,4),
                fecha_pago DATE DEFAULT CURRENT_DATE,
                comprobante_url TEXT,
                notas TEXT,
                estado VARCHAR(20) DEFAULT 'pendiente',
                created_by_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS work_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                certificacion_id INTEGER,
                obra_id INTEGER NOT NULL,
                organizacion_id INTEGER NOT NULL,
                operario_id INTEGER,
                metodo_pago TEXT NOT NULL,
                moneda TEXT DEFAULT 'ARS',
                monto NUMERIC NOT NULL,
                tc_usd_pago NUMERIC,
                fecha_pago DATE DEFAULT CURRENT_DATE,
                comprobante_url TEXT,
                notas TEXT,
                estado TEXT DEFAULT 'pendiente',
                created_by_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

    # Create indexes on work_payments
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_work_payments_certificacion
        ON work_payments(certificacion_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_work_payments_estado
        ON work_payments(estado)
    """))


def downgrade() -> None:
    pass
