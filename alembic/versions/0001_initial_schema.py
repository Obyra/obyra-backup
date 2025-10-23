"""Initial database schema."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from alembic import op

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.extensions import db  # noqa: E402


MODEL_MODULES = ("models",)

for module in MODEL_MODULES:
    importlib.import_module(module)

# revision identifiers, used by Alembic.
revision = '0001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables defined in SQLAlchemy metadata."""

    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    bind = op.get_bind()
    db.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Drop all tables created by this migration."""

    bind = op.get_bind()
    db.metadata.drop_all(bind=bind, checkfirst=True)
