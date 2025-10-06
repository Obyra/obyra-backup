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
        "nombre": "Materiales de Obra",
        "children": [
            {
                "nombre": "Cementos y aglomerantes",
                "children": [
                    {"nombre": "Cemento Portland"},
                    {"nombre": "Cemento de alta resistencia"},
                    {"nombre": "Cemento blanco"},
                    {"nombre": "Cal aérea"},
                    {"nombre": "Cal hidráulica"},
                    {"nombre": "Yeso para construcción"},
                    {"nombre": "Morteros premezclados"},
                    {"nombre": "Adhesivos cementicios"},
                ],
            },
            {
                "nombre": "Áridos",
                "children": [
                    {"nombre": "Arena fina"},
                    {"nombre": "Arena gruesa"},
                    {"nombre": "Piedra partida"},
                    {"nombre": "Ripio y estabilizado granular"},
                    {"nombre": "Tosca y rellenos"},
                    {"nombre": "Áridos livianos"},
                ],
            },
            {
                "nombre": "Mampostería",
                "children": [
                    {"nombre": "Ladrillos cerámicos comunes"},
                    {"nombre": "Ladrillos huecos portantes"},
                    {"nombre": "Bloques de hormigón"},
                    {"nombre": "Bloques HCCA / retak"},
                    {"nombre": "Paneles premoldeados"},
                    {"nombre": "Placas EPS"},
                ],
            },
            {
                "nombre": "Acero y estructuras",
                "children": [
                    {"nombre": "Barras corrugadas"},
                    {"nombre": "Mallas electrosoldadas"},
                    {"nombre": "Perfiles laminados"},
                    {"nombre": "Perfiles conformados"},
                    {"nombre": "Accesorios y anclajes"},
                ],
            },
            {
                "nombre": "Impermeabilización y aislación",
                "children": [
                    {"nombre": "Membranas asfálticas"},
                    {"nombre": "Membranas líquidas"},
                    {"nombre": "Selladores poliuretánicos"},
                    {"nombre": "Espumas de poliuretano"},
                    {"nombre": "Barreras de vapor"},
                    {"nombre": "Aislaciones termoacústicas"},
                ],
            },
            {
                "nombre": "Terminaciones y revestimientos",
                "children": [
                    {"nombre": "Revoques tradicionales"},
                    {"nombre": "Revestimientos plásticos"},
                    {"nombre": "Pinturas"},
                    {"nombre": "Cerámicos y porcelanatos"},
                    {"nombre": "Pastinas y fragües"},
                    {"nombre": "Revestimientos vinílicos"},
                ],
            },
            {
                "nombre": "Maderas y derivados",
                "children": [
                    {"nombre": "Tablas y tirantes"},
                    {"nombre": "Fenólicos"},
                    {"nombre": "OSB"},
                    {"nombre": "MDF"},
                    {"nombre": "Decks y exteriores"},
                    {"nombre": "Molduras y zócalos"},
                ],
            },
            {
                "nombre": "Plásticos y PVC",
                "children": [
                    {"nombre": "Caños de presión"},
                    {"nombre": "Caños de desagüe"},
                    {"nombre": "Accesorios hidráulicos"},
                    {"nombre": "Planchas de polietileno"},
                    {"nombre": "Geomembranas"},
                ],
            },
            {
                "nombre": "Vidrios y carpinterías",
                "children": [
                    {"nombre": "DVH y termopaneles"},
                    {"nombre": "Marcos de aluminio"},
                    {"nombre": "Marcos de PVC"},
                    {"nombre": "Hojas y paños vidriados"},
                    {"nombre": "Herrajes y cierres"},
                    {"nombre": "Burletes y sellos"},
                ],
            },
        ],
    },
    {
        "nombre": "Instalaciones",
        "children": [
            {
                "nombre": "Instalaciones eléctricas",
                "children": [
                    {"nombre": "Conductores de baja tensión"},
                    {"nombre": "Bandejas y cañerías"},
                    {"nombre": "Tableros y protecciones"},
                    {"nombre": "Iluminación LED"},
                    {"nombre": "Tomacorrientes y fichas"},
                    {"nombre": "Sistemas de puesta a tierra"},
                ],
            },
            {
                "nombre": "Instalaciones sanitarias",
                "children": [
                    {"nombre": "Cañerías de agua fría/caliente"},
                    {"nombre": "Cañerías de desagüe"},
                    {"nombre": "Bombas y presurizadoras"},
                    {"nombre": "Válvulas y llaves"},
                    {"nombre": "Tanques y cisternas"},
                ],
            },
            {
                "nombre": "Instalaciones de gas",
                "children": [
                    {"nombre": "Cañerías de acero"},
                    {"nombre": "Cañerías de cobre"},
                    {"nombre": "Reguladores y medidores"},
                    {"nombre": "Artefactos y quemadores"},
                ],
            },
            {
                "nombre": "Climatización",
                "children": [
                    {"nombre": "Equipos tipo split"},
                    {"nombre": "Sistemas VRF"},
                    {"nombre": "Conductos y difusores"},
                    {"nombre": "Calefacción hidrónica"},
                    {"nombre": "Ventiladores industriales"},
                ],
            },
            {
                "nombre": "Sistemas especiales",
                "children": [
                    {"nombre": "Domótica y BMS"},
                    {"nombre": "Alarmas y control de acceso"},
                    {"nombre": "CCTV"},
                    {"nombre": "Redes de datos"},
                    {"nombre": "Detección de incendio"},
                    {"nombre": "Sonorización y megafonía"},
                ],
            },
        ],
    },
    {
        "nombre": "Maquinarias y Equipos",
        "children": [
            {
                "nombre": "Maquinaria pesada",
                "children": [
                    {"nombre": "Retroexcavadoras"},
                    {"nombre": "Autoelevadores"},
                    {"nombre": "Grúas y elevadores"},
                    {"nombre": "Bombas de hormigón"},
                    {"nombre": "Compresores industriales"},
                ],
            },
            {
                "nombre": "Herramientas eléctricas",
                "children": [
                    {"nombre": "Taladros y atornilladores"},
                    {"nombre": "Amoladoras"},
                    {"nombre": "Sierras eléctricas"},
                    {"nombre": "Mezcladoras"},
                    {"nombre": "Vibradores de hormigón"},
                    {"nombre": "Martillos demoledores"},
                ],
            },
            {
                "nombre": "Herramientas manuales",
                "children": [
                    {"nombre": "Palas y picos"},
                    {"nombre": "Mazas y martillos"},
                    {"nombre": "Llaves y criques"},
                    {"nombre": "Destornilladores"},
                    {"nombre": "Niveles manuales"},
                ],
            },
            {
                "nombre": "Equipos de medición y control",
                "children": [
                    {"nombre": "Niveles láser"},
                    {"nombre": "Estaciones totales"},
                    {"nombre": "Medidores de humedad"},
                    {"nombre": "Detectores de gas"},
                    {"nombre": "Calibradores y micrómetros"},
                ],
            },
            {
                "nombre": "Vehículos y transporte interno",
                "children": [
                    {"nombre": "Camiones y utilitarios"},
                    {"nombre": "Pick-ups"},
                    {"nombre": "Carretillas"},
                    {"nombre": "Zorras hidráulicas"},
                    {"nombre": "Plataformas modulares"},
                ],
            },
        ],
    },
    {
        "nombre": "Sistemas de Encofrado y Andamiaje",
        "children": [
            {
                "nombre": "Vigas H20",
                "children": [
                    {"nombre": "Vigas H20 estándar"},
                    {"nombre": "Vigas H20 reforzadas"},
                    {"nombre": "Vigas H20 accesorios"},
                ],
            },
            {
                "nombre": "Puntales metálicos",
                "children": [
                    {"nombre": "Puntales telescópicos"},
                    {"nombre": "Puntales de alta carga"},
                    {"nombre": "Puntales repuestos"},
                ],
            },
            {
                "nombre": "Barras DW y tuercas",
                "children": [
                    {"nombre": "Barras DW"},
                    {"nombre": "Tuercas mariposa"},
                    {"nombre": "Placas y arandelas"},
                ],
            },
            {
                "nombre": "Horquillas, trípodes y crucetas",
                "children": [
                    {"nombre": "Horquillas"},
                    {"nombre": "Trípodes"},
                    {"nombre": "Crucetas niveladoras"},
                ],
            },
            {
                "nombre": "Paneles fenólicos y metálicos",
                "children": [
                    {"nombre": "Paneles fenólicos"},
                    {"nombre": "Paneles de aluminio"},
                    {"nombre": "Paneles de acero"},
                    {"nombre": "Revestimientos fenólicos"},
                ],
            },
            {
                "nombre": "Tensores, abrazaderas y pernos",
                "children": [
                    {"nombre": "Tensores"},
                    {"nombre": "Abrazaderas"},
                    {"nombre": "Pernos cónicos"},
                ],
            },
            {
                "nombre": "Andamios y accesorios",
                "children": [
                    {"nombre": "Andamios tubulares"},
                    {"nombre": "Andamios multidireccionales"},
                    {"nombre": "Plataformas colgantes"},
                    {"nombre": "Ruedas y estabilizadores"},
                ],
            },
            {
                "nombre": "Sistemas trepantes y modulares",
                "children": [
                    {"nombre": "Sistemas trepantes"},
                    {"nombre": "Encofrado deslizante"},
                    {"nombre": "Encofrado modular"},
                    {"nombre": "Accesorios trepantes"},
                ],
            },
            {
                "nombre": "Moldes para columnas y losas",
                "children": [
                    {"nombre": "Moldes para columnas circulares"},
                    {"nombre": "Moldes para columnas rectangulares"},
                    {"nombre": "Encofrado de losas"},
                    {"nombre": "Accesorios de moldes"},
                ],
            },
        ],
    },
    {
        "nombre": "Seguridad e Higiene",
        "children": [
            {
                "nombre": "Equipos de protección personal",
                "children": [
                    {"nombre": "Cascos"},
                    {"nombre": "Chalecos"},
                    {"nombre": "Guantes"},
                    {"nombre": "Calzado"},
                    {"nombre": "Arneses"},
                ],
            },
            {
                "nombre": "Señalización y barreras",
                "children": [
                    {"nombre": "Conos y vallas"},
                    {"nombre": "Cintas perimetrales"},
                    {"nombre": "Cartelería"},
                ],
            },
            {
                "nombre": "Extintores y contra incendio",
                "children": [
                    {"nombre": "Extintores"},
                    {"nombre": "Gabinetes y mangueras"},
                    {"nombre": "Detectores de humo"},
                ],
            },
            {
                "nombre": "Botiquines y primeros auxilios",
                "children": [
                    {"nombre": "Botiquines"},
                    {"nombre": "Insumos de curación"},
                    {"nombre": "Desfibriladores"},
                ],
            },
            {
                "nombre": "Equipos de rescate y evacuación",
                "children": [
                    {"nombre": "Camillas"},
                    {"nombre": "Sistemas de descenso"},
                    {"nombre": "Equipos de rescate vertical"},
                ],
            },
            {
                "nombre": "Kits de emergencia",
                "children": [
                    {"nombre": "Derrames"},
                    {"nombre": "Derrames químicos"},
                    {"nombre": "Control ambiental"},
                ],
            },
        ],
    },
    {
        "nombre": "Logística y Depósito",
        "children": [
            {
                "nombre": "Pallets, cajas y contenedores",
                "children": [
                    {"nombre": "Pallets"},
                    {"nombre": "Cajas plásticas"},
                    {"nombre": "Contenedores metálicos"},
                ],
            },
            {
                "nombre": "Lonas y coberturas",
                "children": [
                    {"nombre": "Lonas pesadas"},
                    {"nombre": "Cubiertas térmicas"},
                    {"nombre": "Fundas impermeables"},
                ],
            },
            {
                "nombre": "Cintas y embalajes",
                "children": [
                    {"nombre": "Cintas de señalización"},
                    {"nombre": "Stretch film"},
                    {"nombre": "Fajas y zunchos"},
                ],
            },
            {
                "nombre": "Elementos de elevación y amarre",
                "children": [
                    {"nombre": "Eslingas"},
                    {"nombre": "Grilletes"},
                    {"nombre": "Tensores"},
                ],
            },
            {
                "nombre": "Control de accesos",
                "children": [
                    {"nombre": "Torniquetes"},
                    {"nombre": "Molinetes"},
                    {"nombre": "Credenciales"},
                ],
            },
            {
                "nombre": "Equipamiento de depósito",
                "children": [
                    {"nombre": "Estanterías y racks"},
                    {"nombre": "Sistemas RFID"},
                    {"nombre": "Equipos de etiquetado"},
                ],
            },
        ],
    },
    {
        "nombre": "Administrativo y Oficina de Obra",
        "children": [
            {
                "nombre": "Papelería y suministros",
                "children": [
                    {"nombre": "Papel e impresos"},
                    {"nombre": "Artículos de escritura"},
                    {"nombre": "Organización y archivo"},
                ],
            },
            {
                "nombre": "Electrónica y comunicaciones",
                "children": [
                    {"nombre": "Celulares"},
                    {"nombre": "Tablets"},
                    {"nombre": "Notebooks e impresoras"},
                ],
            },
            {
                "nombre": "Mobiliario y equipamiento",
                "children": [
                    {"nombre": "Puestos operativos"},
                    {"nombre": "Sillas ergonómicas"},
                    {"nombre": "Guardado y lockers"},
                ],
            },
            {
                "nombre": "Software y licencias",
                "children": [
                    {"nombre": "Gestión de obra"},
                    {"nombre": "Diseño y BIM"},
                    {"nombre": "Productividad y ofimática"},
                ],
            },
            {
                "nombre": "Uniformes y merchandising",
                "children": [
                    {"nombre": "Uniformes administrativos"},
                    {"nombre": "Uniformes operativos"},
                    {"nombre": "Merchandising corporativo"},
                ],
            },
        ],
    },
    {
        "nombre": "Consumibles e Insumos",
        "children": [
            {
                "nombre": "Combustibles y lubricantes",
                "children": [
                    {"nombre": "Combustibles líquidos"},
                    {"nombre": "Lubricantes"},
                    {"nombre": "Grasas"},
                ],
            },
            {
                "nombre": "Insumos de limpieza",
                "children": [
                    {"nombre": "Detergentes"},
                    {"nombre": "Desinfectantes"},
                    {"nombre": "Elementos de limpieza"},
                ],
            },
            {
                "nombre": "Herramientas descartables",
                "children": [
                    {"nombre": "Cuchillas"},
                    {"nombre": "Brochas y rodillos"},
                    {"nombre": "Discos y lijas"},
                ],
            },
            {
                "nombre": "Baterías, lámparas y cables auxiliares",
                "children": [
                    {"nombre": "Baterías"},
                    {"nombre": "Lámparas"},
                    {"nombre": "Cables provisionales"},
                ],
            },
            {
                "nombre": "Gas envasado y fluidos",
                "children": [
                    {"nombre": "Gas envasado"},
                    {"nombre": "Agua potable"},
                    {"nombre": "Fluidos especiales"},
                ],
            },
            {
                "nombre": "Adhesivos y selladores puntuales",
                "children": [
                    {"nombre": "Adhesivos epoxi"},
                    {"nombre": "Selladores químicos"},
                    {"nombre": "Espumas temporales"},
                ],
            },
            {
                "nombre": "Repuestos varios",
                "children": [
                    {"nombre": "Cuchillas y insertos"},
                    {"nombre": "Correas y transmisiones"},
                    {"nombre": "Motores y bobinados"},
                ],
            },
        ],
    },
    {
        "nombre": "Categorías funcionales transversales",
        "children": [
            {"nombre": "Obra base / núcleo"},
            {"nombre": "Estructura"},
            {"nombre": "Terminaciones"},
            {"nombre": "Mantenimiento / post-venta"},
            {"nombre": "Repuestos / reciclado"},
            {
                "nombre": "Desperdicio clasificado",
                "children": [
                    {"nombre": "Recuperable"},
                    {"nombre": "No recuperable"},
                    {"nombre": "Reutilizable"},
                ],
            },
            {"nombre": "Reservas por proyecto / centro de costos"},
        ],
    },
]


def _get_or_create_category(
    *,
    company_id: int,
    nombre: str,
    parent: Optional[InventoryCategory],
    sort_order: int,
) -> Tuple[InventoryCategory, str]:
    """Obtiene o crea una categoría para la organización dada."""

    existing = InventoryCategory.query.filter_by(
        company_id=company_id,
        nombre=nombre,
        parent_id=parent.id if parent else None,
    ).first()

    if existing:
        status = 'existing'
        if not getattr(existing, 'is_active', True):
            existing.is_active = True
            status = 'reactivated'

        if getattr(existing, 'sort_order', sort_order) != sort_order:
            existing.sort_order = sort_order

        return existing, status

    categoria = InventoryCategory(
        company_id=company_id,
        nombre=nombre,
        parent_id=parent.id if parent else None,
        sort_order=sort_order,
        is_active=True,
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
) -> int:
    if stats is None:
        stats = defaultdict(int)

    categoria, status = _get_or_create_category(
        company_id=company_id,
        nombre=data["nombre"],
        parent=parent,
        sort_order=position,
    )

    stats[status] = stats.get(status, 0) + 1

    current_path = f"{path} > {categoria.nombre}".strip(" >")
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
        )
    return total_created


def seed_inventory_categories_for_company(
    company: Organizacion,
    *,
    verbose: bool = False,
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
    parser.add_argument('--org', help='ID, slug, token o nombre de la organización destino')
    parser.add_argument('--all', action='store_true', help='Sembrar todas las organizaciones')
    parser.add_argument('--quiet', action='store_true', help='Oculta el detalle por categoría')

    args = parser.parse_args(argv)

    if args.org and args.all:
        parser.error('Usa --org o --all, pero no ambos.')

    verbose = not args.quiet

    from app import app

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
