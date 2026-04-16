"""merge heads para dev local

Junta las dos ramas divergentes de migraciones Alembic
(202511020002 + 202604080004) que impedían `flask db upgrade` de correr
con error: "Multiple head revisions are present for given argument 'head'".

No hace cambios de schema — solo unifica el grafo de migraciones.
"""

revision = '1ba7383dd08f'
down_revision = ('202511020002', '202604080004')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
