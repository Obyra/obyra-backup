"""Utilities to load and seed inventory categories for the active organization."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from extensions import db
from models import InventoryCategory, Organizacion
from seed_inventory_categories import seed_inventory_categories_for_company


def get_active_categories(company_id: int) -> List[InventoryCategory]:
    """Return ordered active categories for the given organization."""

    return (
        InventoryCategory.query
        .filter(
            InventoryCategory.company_id == company_id,
            InventoryCategory.is_active.is_(True),
        )
        .order_by(InventoryCategory.sort_order, InventoryCategory.nombre)
        .all()
    )


def ensure_categories_for_company(
    company: Organizacion,
) -> Tuple[List[InventoryCategory], Dict[str, int], bool]:
    """Ensure the organization has categories, auto-seeding if needed."""

    stats: Dict[str, int] = {"created": 0, "existing": 0, "reactivated": 0}
    auto_seeded = False

    categorias = get_active_categories(company.id)
    if categorias:
        return categorias, stats, auto_seeded

    stats = seed_inventory_categories_for_company(company)
    if stats.get("created") or stats.get("reactivated"):
        db.session.commit()
        categorias = get_active_categories(company.id)
        auto_seeded = True
    else:
        categorias = []

    return categorias, stats, auto_seeded


def ensure_categories_for_company_id(
    company_id: Optional[int],
) -> Tuple[List[InventoryCategory], Dict[str, int], bool, Optional[Organizacion]]:
    """Helper that resolves the organization and seeds categories if needed."""

    if not company_id:
        return [], {"created": 0, "existing": 0, "reactivated": 0}, False, None

    company = Organizacion.query.get(company_id)
    if not company:
        return [], {"created": 0, "existing": 0, "reactivated": 0}, False, None

    categorias, stats, auto_seeded = ensure_categories_for_company(company)
    return categorias, stats, auto_seeded, company
