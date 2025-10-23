"""Seed estructural de permisos de roles (plantilla).

Copiar y adaptar antes de ejecutar en entornos productivos.
El seed es idempotente y sólo afecta al esquema ``app``.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_seed_role_permissions"
down_revision = "0001_initial_baseline"
branch_labels = None
depends_on = None


SEED_SQL = """
DO $$
BEGIN
    IF to_regclass('app.role_permissions') IS NULL THEN
        RAISE NOTICE 'Tabla app.role_permissions no existe. Seed omitido.';
        RETURN;
    END IF;

    INSERT INTO app.role_permissions (role, permission, created_at)
    VALUES
        ('admin', 'inventory.manage', NOW()),
        ('admin', 'suppliers.read', NOW()),
        ('operator', 'inventory.read', NOW())
    ON CONFLICT (role, permission) DO UPDATE
        SET permission = EXCLUDED.permission;
END$$;
"""


REVERT_SQL = """
DO $$
BEGIN
    IF to_regclass('app.role_permissions') IS NULL THEN
        RAISE NOTICE 'Tabla app.role_permissions no existe. Rollback omitido.';
        RETURN;
    END IF;

    DELETE FROM app.role_permissions
    WHERE (role, permission) IN (
        ('admin', 'inventory.manage'),
        ('admin', 'suppliers.read'),
        ('operator', 'inventory.read')
    );
END$$;
"""


def upgrade() -> None:
    op.execute(SEED_SQL)


def downgrade() -> None:
    op.execute(REVERT_SQL)
