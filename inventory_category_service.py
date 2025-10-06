"""Utilities to load and seed inventory categories for the active organization."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from sqlalchemy import func

from extensions import db
from models import InventoryCategory, Organizacion
from seed_inventory_categories import seed_inventory_categories_for_company


def _sort_categories(categorias: List[InventoryCategory]) -> List[InventoryCategory]:
    """Return categories ordered by hierarchy-friendly path."""

    if not categorias:
        return []

    # `full_path` already walks the parent chain, so we can rely on it for
    # deterministic ordering inside dropdowns and reports. As a safety net we
    # fall back to the primary key to avoid unstable ordering when names repeat.
    def _path_key(categoria: InventoryCategory) -> str:
        path = categoria.full_path or categoria.nombre or ""
        return path.casefold()

    return sorted(
        categorias,
        key=lambda categoria: (
            _path_key(categoria),
            categoria.id or 0,
        ),
    )


def get_active_categories(company_id: int) -> List[InventoryCategory]:
    """Return ordered active categories for the given organization."""

    sort_expr = [func.coalesce(InventoryCategory.sort_order, 0), InventoryCategory.nombre]

    categorias = (
        InventoryCategory.query
        .filter(
            InventoryCategory.company_id == company_id,
            InventoryCategory.is_active.is_(True),
        )
        .order_by(*sort_expr)
        .all()
    )

    return _sort_categories(categorias)


def get_active_category_options(company_id: int) -> List[InventoryCategory]:
    """Return active categories, auto-seeding when the catalogue is empty."""

    categorias, _, _, _ = ensure_categories_for_company_id(company_id)
    if categorias:
        return _sort_categories(categorias)

    return get_active_categories(company_id)


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

    pending_changes = bool(db.session.new) or bool(db.session.dirty)
    if pending_changes:
        db.session.commit()

    categorias = get_active_categories(company.id)
    auto_seeded = bool(stats.get("created") or stats.get("reactivated") or pending_changes)

    return _sort_categories(categorias), stats, auto_seeded


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


def serialize_category(categoria: InventoryCategory) -> Dict[str, object]:
    """Serialize a category for dropdown/API consumption."""

    return {
        "id": categoria.id,
        "nombre": categoria.nombre,
        "full_path": categoria.full_path,
        "parent_id": categoria.parent_id,
        "sort_order": categoria.sort_order,
    }


def get_active_category_payload(company_id: int) -> List[Dict[str, object]]:
    """Convenience helper returning serialized active categories."""

    categorias = get_active_category_options(company_id)
    return [serialize_category(categoria) for categoria in categorias]
