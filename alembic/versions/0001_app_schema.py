"""Crea esquema base app si no existe"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_app_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS app")
