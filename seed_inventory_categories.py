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

from extensions import db
from models import InventoryCategory, Organizacion
from sqlalchemy import func

DEFAULT_CATEGORY_TREE: List[Dict[str, object]] = [
    {
        "nombre": "Materiales",
        "children": [
            {"nombre": "Cementos y aglomerantes"},
            {"nombre": "Áridos"},
            {"nombre": "Aceros y armaduras"},
            {"nombre": "Aditivos y químicos para hormigón"},
            {"nombre": "Maderas y tableros"},
            {"nombre": "Plásticos y PVC"},
            {"nombre": "Pinturas y revestimientos"},
            {"nombre": "Impermeabilización y selladores"},
        ],
    },
    {
        "nombre": "Sistemas de Encofrado",
        "children": [
            {"nombre": "Vigas H20 (Peri/Hünnebeck compatibles)"},
            {"nombre": "Puntales metálicos"},
            {"nombre": "Barras/Tuercas DW (Dywidag)"},
            {"nombre": "Paneles y chapas"},
            {"nombre": "Accesorios de encofrado"},
            {"nombre": "Tornapuntas y estabilizadores"},
        ],
    },
    {
        "nombre": "Herramientas",
        "children": [
            {"nombre": "Manuales"},
            {"nombre": "Eléctricas"},
            {"nombre": "Medición y trazado"},
            {"nombre": "Corte"},
            {"nombre": "Fijación"},
            {"nombre": "Neumáticas"},
        ],
    },
    {
        "nombre": "Maquinarias",
        "children": [
            {"nombre": "Andamios y plataformas"},
            {"nombre": "Excavadoras"},
            {"nombre": "Retroexcavadoras"},
            {"nombre": "Autoelevadores"},
            {"nombre": "Plumas y grúas"},
            {"nombre": "Hormigoneras y bombeo"},
        ],
    },
    {
        "nombre": "Seguridad",
        "children": [
            {"nombre": "Elementos de protección personal (EPP)"},
            {"nombre": "Señalización"},
            {"nombre": "Perímetro y cerramientos"},
            {"nombre": "Trabajo en altura"},
            {"nombre": "Control de acceso"},
        ],
    },
    {
        "nombre": "Consumibles",
        "children": [
            {"nombre": "Discos de corte y desbaste"},
            {"nombre": "Brocas"},
            {"nombre": "Tornillos"},
            {"nombre": "Clavos y fijaciones"},
            {"nombre": "Químicos y adhesivos"},
            {"nombre": "Lubricantes y grasas"},
        ],
    },
    {
        "nombre": "Logística y Depósitos",
        "children": [
            {"nombre": "Transporte interno"},
            {"nombre": "Equipamiento de depósito"},
            {"nombre": "Embalajes y contenedores"},
            {"nombre": "Sistemas de inventario"},
        ],
    },
    {
        "nombre": "Oficina e IT",
        "children": [
            {"nombre": "Computadoras y periféricos"},
            {"nombre": "Redes y comunicación"},
            {"nombre": "Impresión y planos"},
            {"nombre": "Software y licencias"},
        ],
    },
    {
        "nombre": "Categorías transversales KPI",
        "children": [
            {"nombre": "Desperdicio"},
            {"nombre": "Merma"},
            {"nombre": "Reproceso"},
            {"nombre": "Eficiencia operativa"},
        ],
    },
]

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
    parser.add_argument(
        '--global',
        dest='seed_global',
        action='store_true',
        help='Sembrar el catálogo global compartido',
    )
    parser.add_argument(
        '--org',
        dest='orgs',
        action='append',
        help='ID, slug, token o nombre de la organización destino (puede repetirse)',
    )
    parser.add_argument('--quiet', action='store_true', help='Oculta el detalle por categoría')

    args = parser.parse_args(argv)

    verbose = not args.quiet
    org_identifiers = args.orgs or []
    should_seed_global = args.seed_global or not org_identifiers
    fallback_identifier = org_identifiers[0] if (args.seed_global and org_identifiers) else None

    from app import app

    with app.app_context():
        if should_seed_global:
            fallback_org: Optional[Organizacion]
            if fallback_identifier:
                fallback_org = _resolve_organization(fallback_identifier)
                if not fallback_org:
                    print(f"❌ No se encontró la organización '{fallback_identifier}' para el catálogo global.")
                    return 1
            else:
                fallback_org = Organizacion.query.order_by(Organizacion.id.asc()).first()
                if not fallback_org:
                    print('❌ No se encontraron organizaciones. Crea una antes de sembrar el catálogo global.')
                    return 1

            stats = seed_inventory_categories_for_company(
                fallback_org,
                verbose=verbose,
                mark_global=True,
            )
            db.session.commit()

            if verbose:
                print('\n🌐 Catálogo global inicializado:')
            _print_seed_summary(fallback_org.nombre if fallback_org else 'Global', stats)

        exit_code = 0
        for identifier in org_identifiers:
            organizacion = _resolve_organization(identifier)
            if not organizacion:
                print(f"❌ No se encontró la organización '{identifier}'.")
                exit_code = 1
                continue

            stats = seed_inventory_categories_for_company(organizacion, verbose=verbose)
            db.session.commit()

            if verbose:
                print('\n📂 Resumen final:')
            _print_seed_summary(organizacion.nombre, stats)

        return exit_code


if __name__ == "__main__":
    sys.exit(main())
