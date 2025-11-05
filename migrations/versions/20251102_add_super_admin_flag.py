"""add is_super_admin flag to usuarios table"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

revision = "202511020001"
down_revision = "202509150001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Set search_path for PostgreSQL
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    # Check if usuarios table exists
    if is_pg:
        table_exists = conn.execute(
            text("SELECT to_regclass('app.usuarios') IS NOT NULL")
        ).scalar()
    else:
        from sqlalchemy import inspect
        insp = inspect(conn)
        table_exists = 'usuarios' in insp.get_table_names()

    if not table_exists:
        return

    # Get existing columns
    from sqlalchemy import inspect
    insp = inspect(conn)
    columns = {c["name"] for c in insp.get_columns("usuarios")}

    # Add is_super_admin column if it doesn't exist
    if "is_super_admin" not in columns:
        if is_pg:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN is_super_admin BOOLEAN NOT NULL DEFAULT FALSE"))
        else:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN is_super_admin INTEGER NOT NULL DEFAULT 0"))

    # Set is_super_admin=TRUE for hardcoded admin emails
    # This ensures backward compatibility during migration
    admin_emails = ['brenda@gmail.com', 'admin@obyra.com', 'obyra.servicios@gmail.com']
    for email in admin_emails:
        if is_pg:
            conn.execute(
                text("UPDATE usuarios SET is_super_admin = TRUE WHERE email = :email"),
                {"email": email}
            )
        else:
            conn.execute(
                text("UPDATE usuarios SET is_super_admin = 1 WHERE email = :email"),
                {"email": email}
            )


def downgrade() -> None:
    """Downgrade removes the is_super_admin column"""
    conn = op.get_bind()

    is_pg = conn.engine.url.get_backend_name() == 'postgresql'
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    # Check if usuarios table exists
    if is_pg:
        table_exists = conn.execute(
            text("SELECT to_regclass('app.usuarios') IS NOT NULL")
        ).scalar()
    else:
        from sqlalchemy import inspect
        insp = inspect(conn)
        table_exists = 'usuarios' in insp.get_table_names()

    if not table_exists:
        return

    # Get existing columns
    from sqlalchemy import inspect
    insp = inspect(conn)
    columns = {c["name"] for c in insp.get_columns("usuarios")}

    # Drop is_super_admin column if it exists
    if "is_super_admin" in columns:
        conn.execute(text("ALTER TABLE usuarios DROP COLUMN is_super_admin"))
