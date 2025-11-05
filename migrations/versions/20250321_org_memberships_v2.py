"""create org_memberships table and add primary_org_id to usuarios"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202503210002"
down_revision = "202503210001"
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
    tables = set(insp.get_table_names())

    # Add primary_org_id to usuarios if table exists
    if "usuarios" in tables:
        usuario_columns = {c["name"] for c in insp.get_columns("usuarios")}
        if "primary_org_id" not in usuario_columns:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN primary_org_id INTEGER"))

        # Backfill from organizacion_id
        conn.execute(text("""
            UPDATE usuarios
            SET primary_org_id = organizacion_id
            WHERE primary_org_id IS NULL AND organizacion_id IS NOT NULL
        """))

    # Create org_memberships table
    if "org_memberships" not in tables:
        if is_pg:
            conn.execute(text("""
                CREATE TABLE org_memberships (
                    id SERIAL PRIMARY KEY,
                    org_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'operario',
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    archived BOOLEAN NOT NULL DEFAULT FALSE,
                    archived_at TIMESTAMP,
                    invited_by INTEGER,
                    invited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accepted_at TIMESTAMP,
                    CONSTRAINT uq_membership_org_user UNIQUE (org_id, user_id)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE org_memberships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'operario',
                    status TEXT NOT NULL DEFAULT 'pending',
                    archived INTEGER NOT NULL DEFAULT 0,
                    archived_at DATETIME,
                    invited_by INTEGER,
                    invited_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    accepted_at DATETIME,
                    UNIQUE (org_id, user_id)
                )
            """))

    # Create indexes
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_membership_user ON org_memberships(user_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_membership_org ON org_memberships(org_id)"))

    # Backfill org_memberships from usuarios
    if "usuarios" in tables:
        if is_pg:
            conn.execute(text("""
                INSERT INTO org_memberships (org_id, user_id, role, status, archived, invited_at, accepted_at)
                SELECT u.organizacion_id,
                       u.id,
                       CASE WHEN u.rol IN ('administrador','admin','administrador_general') THEN 'admin' ELSE 'operario' END,
                       CASE WHEN u.activo IS NULL OR u.activo = TRUE THEN 'active' ELSE 'inactive' END,
                       FALSE,
                       CURRENT_TIMESTAMP,
                       CASE WHEN u.activo IS NULL OR u.activo = TRUE THEN CURRENT_TIMESTAMP ELSE NULL END
                FROM usuarios u
                WHERE u.organizacion_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM org_memberships m WHERE m.org_id = u.organizacion_id AND m.user_id = u.id
                  )
            """))
        else:
            conn.execute(text("""
                INSERT INTO org_memberships (org_id, user_id, role, status, archived, invited_at, accepted_at)
                SELECT u.organizacion_id,
                       u.id,
                       CASE WHEN u.rol IN ('administrador','admin','administrador_general') THEN 'admin' ELSE 'operario' END,
                       CASE WHEN u.activo IS NULL OR u.activo = 1 THEN 'active' ELSE 'inactive' END,
                       0,
                       CURRENT_TIMESTAMP,
                       CASE WHEN u.activo IS NULL OR u.activo = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
                FROM usuarios u
                WHERE u.organizacion_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM org_memberships m WHERE m.org_id = u.organizacion_id AND m.user_id = u.id
                  )
            """))


def downgrade() -> None:
    pass
