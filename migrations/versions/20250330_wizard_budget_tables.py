"""create wizard_stage_variants and wizard_stage_coefficients tables"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202503300001"
down_revision = "202503210002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Set search_path for PostgreSQL
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    # Create wizard_stage_variants table
    if is_pg:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS wizard_stage_variants (
                id SERIAL PRIMARY KEY,
                stage_slug VARCHAR(80) NOT NULL,
                variant_key VARCHAR(80) NOT NULL,
                nombre VARCHAR(120) NOT NULL,
                descripcion VARCHAR(255),
                is_default BOOLEAN DEFAULT FALSE,
                metadata JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_wizard_stage_variant UNIQUE(stage_slug, variant_key)
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS wizard_stage_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stage_slug TEXT NOT NULL,
                variant_key TEXT NOT NULL,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                is_default INTEGER DEFAULT 0,
                metadata TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stage_slug, variant_key)
            )
        """))

    # Create wizard_stage_coefficients table
    if is_pg:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS wizard_stage_coefficients (
                id SERIAL PRIMARY KEY,
                stage_slug VARCHAR(80) NOT NULL,
                variant_id INTEGER REFERENCES wizard_stage_variants(id) ON DELETE CASCADE,
                unit VARCHAR(20) NOT NULL DEFAULT 'u',
                quantity_metric VARCHAR(50) NOT NULL DEFAULT 'cantidad',
                materials_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                labor_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                equipment_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                currency VARCHAR(3) NOT NULL DEFAULT 'ARS',
                source VARCHAR(80),
                notes VARCHAR(255),
                is_baseline BOOLEAN DEFAULT FALSE,
                metadata JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_wizard_stage_coeff_variant UNIQUE(stage_slug, variant_id)
            )
        """))
    else:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS wizard_stage_coefficients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stage_slug TEXT NOT NULL,
                variant_id INTEGER REFERENCES wizard_stage_variants(id) ON DELETE CASCADE,
                unit TEXT NOT NULL DEFAULT 'u',
                quantity_metric TEXT NOT NULL DEFAULT 'cantidad',
                materials_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                labor_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                equipment_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'ARS',
                source TEXT,
                notes TEXT,
                is_baseline INTEGER DEFAULT 0,
                metadata TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stage_slug, variant_id)
            )
        """))


def downgrade() -> None:
    pass
