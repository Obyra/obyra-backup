"""Seed default role permissions."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_seed_role_permissions"
down_revision = "0002_add_inventory_category_columns"
branch_labels = None
depends_on = None


DEFAULT_PERMISSIONS = {
    "administrador": {
        "obras": {"view": True, "edit": True},
        "presupuestos": {"view": True, "edit": True},
        "equipos": {"view": True, "edit": True},
        "inventario": {"view": True, "edit": True},
        "marketplaces": {"view": True, "edit": True},
        "reportes": {"view": True, "edit": True},
        "documentos": {"view": True, "edit": True},
    },
    "tecnico": {
        "obras": {"view": True, "edit": True},
        "presupuestos": {"view": True, "edit": True},
        "inventario": {"view": True, "edit": True},
        "marketplaces": {"view": True, "edit": False},
        "reportes": {"view": True, "edit": False},
        "documentos": {"view": True, "edit": True},
    },
    "operario": {
        "obras": {"view": True, "edit": False},
        "inventario": {"view": True, "edit": False},
        "marketplaces": {"view": True, "edit": False},
        "documentos": {"view": True, "edit": False},
    },
    "jefe_obra": {
        "obras": {"view": True, "edit": True},
        "presupuestos": {"view": True, "edit": True},
        "equipos": {"view": True, "edit": False},
        "inventario": {"view": True, "edit": True},
        "marketplaces": {"view": True, "edit": True},
        "reportes": {"view": True, "edit": False},
        "documentos": {"view": True, "edit": True},
    },
    "compras": {
        "inventario": {"view": True, "edit": True},
        "marketplaces": {"view": True, "edit": True},
        "presupuestos": {"view": True, "edit": False},
        "reportes": {"view": True, "edit": False},
    },
}


def upgrade() -> None:
    statement = sa.text(
        """
        INSERT INTO role_modules (role, module, can_view, can_edit)
        VALUES (:role, :module, :can_view, :can_edit)
        ON CONFLICT (role, module)
        DO UPDATE SET can_view = EXCLUDED.can_view, can_edit = EXCLUDED.can_edit
        """
    )

    for role, modules in DEFAULT_PERMISSIONS.items():
        for module, perms in modules.items():
            op.execute(
                statement,
                {
                    "role": role,
                    "module": module,
                    "can_view": perms["view"],
                    "can_edit": perms["edit"],
                },
            )


def downgrade() -> None:
    
    for role in DEFAULT_PERMISSIONS:
        op.execute(
            sa.text("DELETE FROM role_modules WHERE role = :role"),
            {"role": role},
        )

