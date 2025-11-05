"""create exchange rates, cac indices, pricing indices tables and add currency columns"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa
from datetime import date, datetime

revision = "202503210001"
down_revision = "202503200001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Set search_path for PostgreSQL
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    from sqlalchemy import inspect
    insp = inspect(conn)

    # Create exchange_rates table
    if is_pg:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id SERIAL PRIMARY KEY,
                provider VARCHAR(50) NOT NULL,
                base_currency VARCHAR(3) NOT NULL DEFAULT 'ARS',
                quote_currency VARCHAR(3) NOT NULL DEFAULT 'USD',
                rate NUMERIC(18,6) NOT NULL,
                as_of_date DATE NOT NULL DEFAULT CURRENT_DATE,
                fetched_at TIMESTAMP NOT NULL DEFAULT NOW(),
                source_url VARCHAR(255),
                notes VARCHAR(255),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_exchange_rate_daily UNIQUE(provider, base_currency, quote_currency, as_of_date)
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                base_currency TEXT NOT NULL DEFAULT 'ARS',
                quote_currency TEXT NOT NULL DEFAULT 'USD',
                rate NUMERIC(18,6) NOT NULL,
                as_of_date DATE NOT NULL DEFAULT CURRENT_DATE,
                fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                source_url TEXT,
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, base_currency, quote_currency, as_of_date)
            )
        """))

    # Create cac_indices table
    if is_pg:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cac_indices (
                id SERIAL PRIMARY KEY,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                value NUMERIC(12,2) NOT NULL,
                provider VARCHAR(50) NOT NULL,
                source_url VARCHAR(255),
                fetched_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_cac_index_period_provider UNIQUE(year, month, provider)
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cac_indices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                value NUMERIC(12,2) NOT NULL,
                provider TEXT NOT NULL,
                source_url TEXT,
                fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(year, month, provider)
            )
        """))

    # Create pricing_indices table
    if is_pg:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pricing_indices (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                value NUMERIC(18,6) NOT NULL,
                valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
                notes VARCHAR(255),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_pricing_indices_name_valid_from UNIQUE(name, valid_from)
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pricing_indices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value NUMERIC(18,6) NOT NULL,
                valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, valid_from)
            )
        """))

    # Add currency columns to presupuestos if table exists
    if is_pg:
        presup_exists = conn.execute(text("SELECT to_regclass('app.presupuestos')")).scalar()
    else:
        presup_exists = 'presupuestos' in insp.get_table_names()

    if presup_exists:
        pcols = {c["name"] for c in insp.get_columns("presupuestos")}

        if "currency" not in pcols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN currency VARCHAR(3) DEFAULT 'ARS'"))
        if "exchange_rate_id" not in pcols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN exchange_rate_id INTEGER"))
        if "exchange_rate_value" not in pcols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN exchange_rate_value NUMERIC(18,6)"))
        if "exchange_rate_provider" not in pcols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN exchange_rate_provider VARCHAR(50)"))
        if "exchange_rate_fetched_at" not in pcols:
            coltype = "TIMESTAMP" if is_pg else "DATETIME"
            conn.execute(text(f"ALTER TABLE presupuestos ADD COLUMN exchange_rate_fetched_at {coltype}"))
        if "exchange_rate_as_of" not in pcols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN exchange_rate_as_of DATE"))
        if "tasa_usd_venta" not in pcols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN tasa_usd_venta NUMERIC(10,4)"))
        if "indice_cac_valor" not in pcols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN indice_cac_valor NUMERIC(12,2)"))
        if "indice_cac_fecha" not in pcols:
            conn.execute(text("ALTER TABLE presupuestos ADD COLUMN indice_cac_fecha DATE"))

        conn.execute(text("UPDATE presupuestos SET currency = COALESCE(NULLIF(currency, ''), 'ARS')"))

    # Add currency columns to items_presupuesto if table exists
    if is_pg:
        items_exists = conn.execute(text("SELECT to_regclass('app.items_presupuesto')")).scalar()
    else:
        items_exists = 'items_presupuesto' in insp.get_table_names()

    if items_exists:
        icols = {c["name"] for c in insp.get_columns("items_presupuesto")}

        if "currency" not in icols:
            conn.execute(text("ALTER TABLE items_presupuesto ADD COLUMN currency VARCHAR(3) DEFAULT 'ARS'"))
        if "price_unit_currency" not in icols:
            conn.execute(text("ALTER TABLE items_presupuesto ADD COLUMN price_unit_currency NUMERIC(15,2)"))
        if "total_currency" not in icols:
            conn.execute(text("ALTER TABLE items_presupuesto ADD COLUMN total_currency NUMERIC(15,2)"))
        if "price_unit_ars" not in icols:
            conn.execute(text("ALTER TABLE items_presupuesto ADD COLUMN price_unit_ars NUMERIC(15,2)"))
        if "total_ars" not in icols:
            conn.execute(text("ALTER TABLE items_presupuesto ADD COLUMN total_ars NUMERIC(15,2)"))

        conn.execute(text("UPDATE items_presupuesto SET currency = COALESCE(NULLIF(currency, ''), 'ARS')"))
        conn.execute(text("""
            UPDATE items_presupuesto
            SET price_unit_currency = COALESCE(price_unit_currency, precio_unitario),
                total_currency = COALESCE(total_currency, total)
        """))

    # Add currency columns to catalog tables (materiales, mano_obra, equipos)
    for t in ("materiales", "mano_obra", "equipos"):
        if is_pg:
            t_exists = conn.execute(text(f"SELECT to_regclass('app.{t}')")).scalar()
        else:
            t_exists = t in insp.get_table_names()

        if t_exists:
            ccols = {c["name"] for c in insp.get_columns(t)}
            currency_sql = "VARCHAR(3) DEFAULT 'ARS'" if is_pg else "TEXT DEFAULT 'ARS'"

            if "currency_code" not in ccols:
                conn.execute(text(f"ALTER TABLE {t} ADD COLUMN currency_code {currency_sql}"))
            if "fx_rate" not in ccols:
                conn.execute(text(f"ALTER TABLE {t} ADD COLUMN fx_rate NUMERIC(18,6)"))
            if "fx_source" not in ccols:
                fx_source_sql = "VARCHAR(100)" if is_pg else "TEXT"
                conn.execute(text(f"ALTER TABLE {t} ADD COLUMN fx_source {fx_source_sql}"))
            if "fx_date" not in ccols:
                conn.execute(text(f"ALTER TABLE {t} ADD COLUMN fx_date DATE"))

    # Seed initial CAC value
    exists_cac = conn.execute(text("SELECT COUNT(1) FROM pricing_indices WHERE name = 'CAC'")).scalar()
    if not exists_cac:
        now = datetime.utcnow()
        if is_pg:
            conn.execute(
                text("INSERT INTO pricing_indices (name, value, valid_from, notes, created_at, updated_at) VALUES (:name, :value, :valid_from, :notes, :created_at, :updated_at)"),
                {"name": "CAC", "value": 1.0, "valid_from": date.today(), "notes": "Valor inicial CAC", "created_at": now, "updated_at": now}
            )
        else:
            conn.execute(
                text("INSERT INTO pricing_indices (name, value, valid_from, notes, created_at, updated_at) VALUES (:name, :value, :valid_from, :notes, :created_at, :updated_at)"),
                {"name": "CAC", "value": 1.0, "valid_from": date.today(), "notes": "Valor inicial CAC", "created_at": now, "updated_at": now}
            )


def downgrade() -> None:
    pass
