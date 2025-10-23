#!/usr/bin/env python3
"""Seed de categorías de inventario predefinidas.

Este script crea una estructura jerárquica completa de categorías para el
módulo de inventario a fin de que los usuarios cuenten con un catálogo listo
al dar de alta ítems nuevos. Puede ejecutarse múltiples veces sin duplicar
registros.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from app.extensions import db
from models import InventoryCategory, Organizacion
from sqlalchemy import func, or_

ROOT_CATEGORY_NAMES: List[str] = [
    "Materiales de Obra",
    "Instalaciones",
    "Maquinarias y Equipos",
    "Sistemas de Encofrado y Andamiaje",
    "Seguridad e Higiene",
    "Administrativo y Oficina de Obra",
    "Consumibles e Insumos",
    "Logística y Depósito",
    "Otros",
]

DEFAULT_CATEGORY_TREE: List[Dict[str, object]] = [
    {"nombre": name} for name in ROOT_CATEGORY_NAMES
]


def _normalize_category_name(nombre: Optional[str]) -> str:
    """Return a casefolded identifier for comparisons."""

    if not nombre:
        return ""
    return nombre.strip().casefold()


def _enforce_root_only_catalog(
    company_id: int,
    *,
    mark_global: bool = False,
    stats: Optional[Dict[str, int]] = None,
) -> None:
    """Deactivate nested categories and keep only the approved root set active."""

    allowed: Dict[str, int] = {
        _normalize_category_name(name): index
        for index, name in enumerate(ROOT_CATEGORY_NAMES)
    }

    scope_filter = or_(
        InventoryCategory.company_id == company_id,
        InventoryCategory.is_global.is_(True),
    )

    (
        InventoryCategory.query
        .filter(scope_filter, InventoryCategory.parent_id.isnot(None))
        .update({InventoryCategory.is_active: False}, synchronize_session=False)
    )

    root_categories = (
        InventoryCategory.query
        .filter(scope_filter, InventoryCategory.parent_id.is_(None))
        .all()
    )

    seen: set[str] = set()
    for categoria in root_categories:
        normalized = _normalize_category_name(categoria.nombre)
        if normalized in allowed:
            categoria.is_active = True
            categoria.sort_order = allowed[normalized]
            if mark_global:
                categoria.is_global = True
            seen.add(normalized)
        else:
            categoria.is_active = False
            if mark_global:
                categoria.is_global = False

    for normalized, index in allowed.items():
        if normalized in seen:
            continue

        nombre = ROOT_CATEGORY_NAMES[index]
        nueva_categoria = InventoryCategory(
            company_id=company_id,
            nombre=nombre,
            parent_id=None,
            sort_order=index,
            is_active=True,
            is_global=mark_global,
        )
        db.session.add(nueva_categoria)
        db.session.flush()
        if stats is not None:
            stats['created'] = stats.get('created', 0) + 1


def _get_or_create_category(
    *,
    company_id: int,
    nombre: str,
    parent: Optional[InventoryCategory],
    sort_order: int,
    mark_global: bool = False,
) -> Tuple[InventoryCategory, str]:
    """Obtiene o crea una categoría para la organización dada."""

    filters = [
        InventoryCategory.nombre == nombre,
        InventoryCategory.parent_id == (parent.id if parent else None),
    ]

    if mark_global:
        filters.append(InventoryCategory.is_global.is_(True))
    else:
        filters.append(InventoryCategory.company_id == company_id)

    existing = InventoryCategory.query.filter(*filters).first()

    if existing:
        status = 'existing'
        if not getattr(existing, 'is_active', True):
            existing.is_active = True
            status = 'reactivated'

        if mark_global and not getattr(existing, 'is_global', False):
            existing.is_global = True

        if getattr(existing, 'sort_order', sort_order) != sort_order:
            existing.sort_order = sort_order

        return existing, status

    categoria = InventoryCategory(
        company_id=company_id,
        nombre=nombre,
        parent_id=parent.id if parent else None,
        sort_order=sort_order,
        is_active=True,
        is_global=mark_global,
    )
    db.session.add(categoria)
    db.session.flush()
    return categoria, 'created'


def _seed_category_branch(
    company_id: int,
    data: Dict[str, object],
    parent: Optional[InventoryCategory] = None,
    *,
    depth: int = 0,
    position: int = 0,
    path: str = "",
    stats: Optional[Dict[str, int]] = None,
    verbose: bool = False,
    mark_global: bool = False,
) -> int:
    if stats is None:
        stats = defaultdict(int)

    categoria, status = _get_or_create_category(
        company_id=company_id,
        nombre=data["nombre"],
        parent=parent,
        sort_order=position,
        mark_global=mark_global,
    )

    stats[status] = stats.get(status, 0) + 1

    separator = " \u2192 " if path else ""
    current_path = f"{path}{separator}{categoria.nombre}".strip()
    if verbose:
        indent = "  " * depth
        print(f"{indent}- {current_path} [{status}]")

    total_created = 1 if status == 'created' else 0
    for idx, child in enumerate(data.get("children", []) or []):
        total_created += _seed_category_branch(
            company_id,
            child,
            categoria,
            depth=depth + 1,
            position=idx,
            path=current_path,
            stats=stats,
            verbose=verbose,
            mark_global=mark_global,
        )
    return total_created


def seed_inventory_categories_for_company(
    company: Organizacion,
    *,
    verbose: bool = False,
    mark_global: bool = False,
) -> Dict[str, int]:
    """Crea la estructura completa de categorías para la organización dada."""

    stats: Dict[str, int] = defaultdict(int)
    for index, categoria in enumerate(DEFAULT_CATEGORY_TREE):
        _seed_category_branch(
            company.id,
            categoria,
            position=index,
            stats=stats,
            verbose=verbose,
            mark_global=mark_global,
        )

    _enforce_root_only_catalog(company.id, mark_global=mark_global, stats=stats)

    # Aseguramos que todas las claves existan aunque no se hayan utilizado
    for key in ("created", "existing", "reactivated"):
        stats.setdefault(key, 0)

    return dict(stats)


def seed_inventory_categories_for_all(*, verbose: bool = False) -> Dict[int, Dict[str, int]]:
    """Genera las categorías para todas las organizaciones registradas."""

    organizaciones = Organizacion.query.all()
    if not organizaciones:
        print("❌ No se encontraron organizaciones. Crea una antes de correr el seed.")
        return {}

    resultados: Dict[int, Dict[str, int]] = {}
    for organizacion in organizaciones:
        stats = seed_inventory_categories_for_company(organizacion, verbose=verbose)
        resultados[organizacion.id] = stats
        if verbose:
            print(
                "\n📂 Resumen:",
                f"creadas={stats['created']}",
                f"existentes={stats['existing']}",
                f"reactivadas={stats['reactivated']}",
            )

    db.session.commit()

    return resultados


def _resolve_organization(identifier: str) -> Optional[Organizacion]:
    """Obtiene una organización por id, slug o nombre."""

    identifier = identifier.strip()
    if identifier.isdigit():
        return Organizacion.query.get(int(identifier))

    if hasattr(Organizacion, 'slug'):
        org = Organizacion.query.filter_by(slug=identifier).first()
        if org:
            return org

    by_token = Organizacion.query.filter_by(token_invitacion=identifier).first()
    if by_token:
        return by_token

    lowered = identifier.lower()
    return (
        Organizacion.query
        .filter(func.lower(Organizacion.nombre) == lowered)
        .first()
    )


def _print_seed_summary(nombre: str, stats: Dict[str, int]) -> None:
    """Imprime un resumen compacto del seed para una organización."""

    created = stats.get('created', 0)
    existing = stats.get('existing', 0)
    reactivated = stats.get('reactivated', 0)
    print(
        f"🏗️  {nombre}: created={created}, existing={existing}, reactivated={reactivated}"
    )


def main(argv: Optional[List[str]] = None) -> int:
    """Punto de entrada CLI."""

    parser = argparse.ArgumentParser(description='Seed de categorías de inventario')
    parser.add_argument('--org', help='ID, slug, token o nombre de la organización destino')
    parser.add_argument('--all', action='store_true', help='Sembrar todas las organizaciones')
    parser.add_argument('--quiet', action='store_true', help='Oculta el detalle por categoría')

    args = parser.parse_args(argv)

    if args.org and args.all:
        parser.error('Usa --org o --all, pero no ambos.')

    verbose = not args.quiet

    from app import create_app
    app = create_app()

    with app.app_context():
        if args.all or not args.org:
            resultados = seed_inventory_categories_for_all(verbose=verbose)
            if not resultados:
                return 1

            total_creadas = sum(stats.get('created', 0) for stats in resultados.values())
            if not verbose:
                for org_id, stats in resultados.items():
                    organizacion = Organizacion.query.get(org_id)
                    if organizacion:
                        _print_seed_summary(organizacion.nombre, stats)
            print(f"\n✅ Seed finalizado. Categorías nuevas: {total_creadas}")
            return 0

        organizacion = _resolve_organization(args.org)
        if not organizacion:
            print(f"❌ No se encontró la organización '{args.org}'.")
            return 1

        stats = seed_inventory_categories_for_company(organizacion, verbose=verbose)
        db.session.commit()

        if not verbose:
            _print_seed_summary(organizacion.nombre, stats)
        else:
            print("\n📂 Resumen final:")
            _print_seed_summary(organizacion.nombre, stats)

    return 0


if __name__ == "__main__":
    sys.exit(main())
