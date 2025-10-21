"""Initial database schema."""

from __future__ import annotations

from alembic import op

from app import create_app
app = create_app()
from app.extensions import db

# revision identifiers, used by Alembic.
revision = '0001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables defined in SQLAlchemy metadata."""

    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    with app.app_context():
        bind = op.get_bind()
        db.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Drop all tables created by this migration."""

    with app.app_context():
        bind = op.get_bind()
        db.metadata.drop_all(bind=bind, checkfirst=True)
