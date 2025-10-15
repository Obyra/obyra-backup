"""Initial schema bootstrap"""

from alembic import op
import sqlalchemy as sa  # noqa: F401 - required by Alembic for type reflection

from extensions import db

# Ensure all model metadata is registered before creating the schema.
import models  # noqa: F401
import models_inventario  # noqa: F401
import models_marketplace  # noqa: F401
from models import Presupuesto  # noqa: F401


# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    db.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    db.metadata.drop_all(bind=bind)
