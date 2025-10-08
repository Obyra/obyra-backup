"""Utilities to load and seed inventory categories for the active organization."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from flask import current_app, render_template, render_template_string
from sqlalchemy import func, or_

from extensions import db
from models import InventoryCategory, Organizacion
from seed_inventory_categories import seed_inventory_categories_for_company

SUPERADMIN_ROLE_NAMES = {"superadmin", "super_admin"}


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


def is_superadmin(user: object) -> bool:
    """Return True when the given user has superadmin privileges."""

    if not user:
        return False

    role_candidates = {
        (getattr(user, "rol", "") or "").strip().lower(),
        (getattr(user, "role", "") or "").strip().lower(),
    }

    roles_attr = getattr(user, "roles", None)
    if isinstance(roles_attr, (list, tuple, set)):
        for entry in roles_attr:
            try:
                role_candidates.add((str(entry) or "").strip().lower())
            except Exception:  # pragma: no cover - defensive guard
                continue

    if any(role in SUPERADMIN_ROLE_NAMES for role in role_candidates):
        return True

    explicit_flag = getattr(user, "is_superadmin", None)
    if isinstance(explicit_flag, bool):
        return explicit_flag
    if callable(explicit_flag):
        try:
            return bool(explicit_flag())
        except Exception:  # pragma: no cover - defensive guard
            return False

    return False


def user_can_manage_inventory_categories(user: object) -> bool:
    """Return True when the user can manage the global inventory catalogue."""

    return is_superadmin(user)


def _query_active_categories(company_id: Optional[int]) -> List[InventoryCategory]:
    """Return active categories visible for the given company."""

    base_query = InventoryCategory.query.filter(InventoryCategory.is_active.is_(True))

    if company_id:
        base_query = base_query.filter(
            or_(
                InventoryCategory.company_id == company_id,
                InventoryCategory.is_global.is_(True),
            )
        )
    else:
        base_query = base_query.filter(InventoryCategory.is_global.is_(True))

    ordered = base_query.order_by(
        func.coalesce(InventoryCategory.sort_order, 0),
        InventoryCategory.nombre,
        InventoryCategory.id,
    )

    return _sort_categories(ordered.all())


def get_active_categories(company_id: int) -> List[InventoryCategory]:
    """Return ordered active global categories (company id kept for compatibility)."""

    return _query_active_categories(company_id)


def get_global_categories() -> List[InventoryCategory]:
    """Return ordered active categories shared across all organizations."""

    return _query_active_categories(None)


def get_active_category_options(company_id: int) -> List[InventoryCategory]:
    """Return active categories, auto-seeding when the catalogue is empty."""

    categorias, _, _, _ = ensure_categories_for_company_id(company_id)
    return _sort_categories(categorias)


def ensure_categories_for_company(
    company: Organizacion,
) -> Tuple[List[InventoryCategory], Dict[str, int], bool]:
    """Ensure the organization has categories, auto-seeding if needed."""

    if not company:
        return [], {"created": 0, "existing": 0, "reactivated": 0}, False

    categorias = _query_active_categories(company.id)
    if categorias:
        return categorias, {"created": 0, "existing": len(categorias), "reactivated": 0}, False

    global_categories, stats, auto_seeded = ensure_global_categories(
        fallback_company=company
    )
    if global_categories:
        return global_categories, stats, auto_seeded

    stats = seed_inventory_categories_for_company(company, mark_global=False)
    auto_seeded = bool(stats.get("created") or stats.get("reactivated"))

    if auto_seeded:
        db.session.commit()

    categorias = _query_active_categories(company.id)
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


def ensure_global_categories(
    *,
    fallback_company: Optional[Organizacion] = None,
) -> Tuple[List[InventoryCategory], Dict[str, int], bool]:
    """Ensure the global catalogue exists, optionally seeding it."""

    stats: Dict[str, int] = {"created": 0, "existing": 0, "reactivated": 0}
    auto_seeded = False

    categorias = get_global_categories()
    if categorias:
        stats['existing'] = len(categorias)
        return categorias, stats, auto_seeded

    company = fallback_company
    if company is None:
        company = Organizacion.query.order_by(Organizacion.id.asc()).first()

    if not company:
        return [], stats, auto_seeded

    stats = seed_inventory_categories_for_company(company, mark_global=True)

    pending_changes = bool(db.session.new) or bool(db.session.dirty)
    should_commit = (
        pending_changes
        or bool(stats.get("created"))
        or bool(stats.get("reactivated"))
    )

    if should_commit:
        db.session.commit()

    categorias = get_global_categories()
    stats['existing'] = len(categorias)
    auto_seeded = bool(
        stats.get("created")
        or stats.get("reactivated")
        or should_commit
    )

    return _sort_categories(categorias), stats, auto_seeded


def serialize_category(categoria: InventoryCategory) -> Dict[str, object]:
    """Serialize a category for dropdown/API consumption."""

    full_path = categoria.full_path or categoria.nombre or ""

    return {
        "id": categoria.id,
        "name": categoria.nombre,
        "full_path": full_path,
        "is_active": bool(categoria.is_active),
        "parent_id": categoria.parent_id,
    }


def get_active_category_payload(company_id: int) -> List[Dict[str, object]]:
    """Convenience helper returning serialized active categories."""

    categorias, _, _, _ = ensure_categories_for_company_id(company_id)
    return [serialize_category(categoria) for categoria in categorias]


_FALLBACK_CATEGORY_TEMPLATE = """
{% extends "base.html" %}

{% block title %}Catálogo de categorías - Inventario{% endblock %}

{% block content %}
<div class="container py-4">
    <div class="d-flex justify-content-between align-items-center mb-4 flex-wrap gap-2">
        <div>
            <h1 class="h3 mb-1">Catálogo de categorías</h1>
            {% if company %}
            <p class="text-muted small mb-0">Organización activa: <strong>{{ company.nombre }}</strong></p>
            {% endif %}
        </div>
        <div class="d-flex gap-2">
            <a href="{{ url_for('inventario.lista') }}" class="btn btn-outline-secondary btn-sm">
                <i class="fas fa-arrow-left me-1"></i>Volver al inventario
            </a>
            {% if not categorias %}
            <form method="post" action="{{ url_for('inventario.crear_categoria') }}">
                <button type="submit" class="btn btn-primary btn-sm">
                    <i class="fas fa-seedling me-1"></i>Sembrar catálogo
                </button>
            </form>
            {% endif %}
        </div>
    </div>

    {% if auto_seeded %}
    <div class="alert alert-success">
        <i class="fas fa-magic me-1"></i>Se generó automáticamente la estructura inicial de categorías para esta organización.
    </div>
    {% endif %}

    <div class="row g-4">
        <div class="col-lg-4">
            <div class="card shadow-sm h-100">
                <div class="card-body">
                    <h2 class="h6 text-uppercase text-muted">Resumen</h2>
                    <dl class="row small mb-0">
                        <dt class="col-7">Categorías activas</dt>
                        <dd class="col-5 text-end fw-semibold">{{ categorias|length }}</dd>
                        <dt class="col-7">Creadas en la siembra</dt>
                        <dd class="col-5 text-end">{{ seed_stats.created }}</dd>
                        <dt class="col-7">Existentes conservadas</dt>
                        <dd class="col-5 text-end">{{ seed_stats.existing }}</dd>
                        <dt class="col-7">Reactivadas</dt>
                        <dd class="col-5 text-end">{{ seed_stats.reactivated }}</dd>
                    </dl>
                </div>
            </div>
        </div>
        <div class="col-lg-8">
            <div class="card shadow-sm">
                <div class="card-header bg-white d-flex justify-content-between align-items-center">
                    <span><i class="fas fa-sitemap me-1"></i>Estructura jerárquica</span>
                    <span class="badge bg-light text-muted">{{ categorias|length }} categorías</span>
                </div>
                <div class="card-body">
                    {% if categorias %}
                    <ul class="list-group list-group-flush">
                        {% for categoria in categorias %}
                        <li class="list-group-item">
                            <strong>{{ categoria.nombre }}</strong>
                            {% if categoria.full_path and categoria.full_path != categoria.nombre %}
                            <div class="text-muted small">{{ categoria.full_path }}</div>
                            {% endif %}
                        </li>
                        {% endfor %}
                    </ul>
                    {% else %}
                    <div class="text-center text-muted py-5">
                        <i class="fas fa-layer-group fa-2x mb-3"></i>
                        <p class="mb-1">Todavía no hay categorías cargadas.</p>
                        <p class="small mb-0">Usá “Sembrar catálogo” para generar la jerarquía recomendada.</p>
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""


def render_category_catalog(context: Dict[str, object]) -> str:
    """Render the category catalogue template with a robust fallback."""

    template_name = "inventario/categorias.html"

    try:
        # Confirm template availability before rendering. If it is missing we
        # fall back to an inline representation so the route never 500s.
        current_app.jinja_env.get_or_select_template(template_name)
        return render_template(template_name, **context)
    except Exception as exc:
        if current_app:
            current_app.logger.warning(
                "Falling back to inline inventory category template: %s", exc
            )
        return render_template_string(_FALLBACK_CATEGORY_TEMPLATE, **context)
