"""Herramientas para el cálculo integral del presupuestador del wizard."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, Iterable, List, Optional, Tuple

from flask import current_app
from sqlalchemy.orm import joinedload

from etapas_predefinidas import obtener_etapas_disponibles
from models import WizardStageCoefficient, WizardStageVariant


# Valores baseline iniciales (ARS por unidad) para cada etapa estándar del catálogo.
DEFAULT_STAGE_BASELINES: Dict[str, Dict[str, str]] = {
    "excavacion": {
        "unit": "m3",
        "materials": "12000",
        "labor": "8000",
        "equipment": "6000",
        "variant_key": "baseline",
        "variant_name": "Terreno estándar",
        "description": "Excavación sin napa ni suelos especiales.",
    },
    "fundaciones": {
        "unit": "m3",
        "materials": "25000",
        "labor": "15000",
        "equipment": "9000",
        "variant_key": "baseline",
        "variant_name": "Hormigón armado",
        "description": "Cimentación corrida estándar.",
    },
    "estructura": {
        "unit": "m3",
        "materials": "32000",
        "labor": "21000",
        "equipment": "12000",
        "variant_key": "baseline",
        "variant_name": "Hormigón armado",
        "description": "Estructura de hormigón tradicional.",
    },
    "mamposteria": {
        "unit": "m2",
        "materials": "18000",
        "labor": "14000",
        "equipment": "4000",
        "variant_key": "baseline",
        "variant_name": "Ladrillo común",
        "description": "Mampostería de ladrillo portante estándar.",
    },
    "techos": {
        "unit": "m2",
        "materials": "22000",
        "labor": "16000",
        "equipment": "7000",
        "variant_key": "baseline",
        "variant_name": "Loseta tradicional",
        "description": "Cubierta inclinada de teja cerámica.",
    },
    "instalaciones-electricas": {
        "unit": "m2",
        "materials": "15000",
        "labor": "20000",
        "equipment": "5000",
        "variant_key": "baseline",
        "variant_name": "Vivienda estándar",
        "description": "Cableado embutido monofásico básico.",
    },
    "instalaciones-sanitarias": {
        "unit": "m2",
        "materials": "17000",
        "labor": "19000",
        "equipment": "4000",
        "variant_key": "baseline",
        "variant_name": "Red interna completa",
        "description": "Instalación sanitaria en vivienda unifamiliar.",
    },
    "instalaciones-gas": {
        "unit": "m2",
        "materials": "14000",
        "labor": "16000",
        "equipment": "3000",
        "variant_key": "baseline",
        "variant_name": "Instalación doméstica",
        "description": "Gas natural interior para vivienda.",
    },
    "revoque-grueso": {
        "unit": "m2",
        "materials": "11000",
        "labor": "9000",
        "equipment": "2000",
        "variant_key": "baseline",
        "variant_name": "Mortero tradicional",
        "description": "Revoque grueso interior/exterior estándar.",
    },
    "revoque-fino": {
        "unit": "m2",
        "materials": "9000",
        "labor": "8000",
        "equipment": "1500",
        "variant_key": "baseline",
        "variant_name": "Yeso estándar",
        "description": "Revoque fino alisado para pintura.",
    },
    "pisos": {
        "unit": "m2",
        "materials": "20000",
        "labor": "12000",
        "equipment": "6000",
        "variant_key": "baseline",
        "variant_name": "Cerámico esmaltado",
        "description": "Colocación de cerámica estándar.",
    },
    "carpinteria": {
        "unit": "m2",
        "materials": "15000",
        "labor": "11000",
        "equipment": "5000",
        "variant_key": "baseline",
        "variant_name": "Madera estándar",
        "description": "Carpintería exterior e interior básica.",
    },
    "pintura": {
        "unit": "m2",
        "materials": "8000",
        "labor": "7000",
        "equipment": "1000",
        "variant_key": "baseline",
        "variant_name": "Látex interior/exterior",
        "description": "Pintura al látex en dos manos.",
    },
    "instalaciones-complementarias": {
        "unit": "m2",
        "materials": "12000",
        "labor": "10000",
        "equipment": "4000",
        "variant_key": "baseline",
        "variant_name": "Climatización básica",
        "description": "Instalaciones complementarias estándar.",
    },
    "limpieza-final": {
        "unit": "m2",
        "materials": "4000",
        "labor": "6000",
        "equipment": "1000",
        "variant_key": "baseline",
        "variant_name": "Entrega llave en mano",
        "description": "Limpieza final de obra completa.",
    },
}


@dataclass(frozen=True)
class ResolvedCoefficient:
    stage_slug: str
    unit: str
    materials: Decimal
    labor: Decimal
    equipment: Decimal
    currency: str
    variant_key: str
    variant_name: str
    estimated: bool
    source: str
    notes: Optional[str] = None


def _to_decimal(value: Optional[object], default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _quantize(value: Decimal) -> Decimal:
    try:
        return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value


def _stage_catalog() -> Dict[str, Dict[str, object]]:
    catalog = {}
    for etapa in obtener_etapas_disponibles():
        slug = etapa.get('slug') or etapa.get('nombre')
        if slug:
            catalog[str(slug).strip().lower()] = etapa
    return catalog


def get_feature_flags() -> Dict[str, bool]:
    """Expose feature flags for frontend consumers."""

    enabled = bool(current_app.config.get('WIZARD_BUDGET_BREAKDOWN_ENABLED'))
    shadow = bool(current_app.config.get('WIZARD_BUDGET_SHADOW_MODE'))
    return {
        'wizard_budget_v2': enabled,
        'wizard_budget_shadow_mode': shadow,
    }


def _load_coefficients(stage_slugs: Iterable[str]) -> Tuple[Dict[Tuple[str, Optional[str]], WizardStageCoefficient], Dict[str, WizardStageCoefficient]]:
    """Fetch coefficients for the requested slugs and return lookup dictionaries."""

    slugs = {slug for slug in stage_slugs if slug}
    if not slugs:
        return {}, {}

    query = (
        WizardStageCoefficient.query.options(joinedload(WizardStageCoefficient.variant))
        .filter(WizardStageCoefficient.stage_slug.in_(slugs))
    )

    by_variant: Dict[Tuple[str, Optional[str]], WizardStageCoefficient] = {}
    baseline: Dict[str, WizardStageCoefficient] = {}

    for coeff in query:
        variant_key = coeff.variant.variant_key if coeff.variant else None
        by_variant[(coeff.stage_slug, variant_key)] = coeff
        if coeff.is_baseline or coeff.variant is None:
            baseline.setdefault(coeff.stage_slug, coeff)

    return by_variant, baseline


def _resolve_default_coefficient(stage_slug: str) -> Optional[ResolvedCoefficient]:
    data = DEFAULT_STAGE_BASELINES.get(stage_slug)
    if not data:
        return None

    return ResolvedCoefficient(
        stage_slug=stage_slug,
        unit=data.get('unit') or 'u',
        materials=_to_decimal(data.get('materials')),
        labor=_to_decimal(data.get('labor')),
        equipment=_to_decimal(data.get('equipment')),
        currency='ARS',
        variant_key=data.get('variant_key') or 'baseline',
        variant_name=data.get('variant_name') or 'Baseline',
        estimated=True,
        source='baseline-default',
        notes=data.get('description'),
    )


def _resolve_coefficient(
    stage_slug: str,
    variant_key: Optional[str],
    coeff_cache: Dict[Tuple[str, Optional[str]], WizardStageCoefficient],
    baseline_cache: Dict[str, WizardStageCoefficient],
) -> Tuple[ResolvedCoefficient, bool]:
    """Return the coefficient for a stage and whether it required a fallback."""

    normalized_variant = (variant_key or '').strip() or None

    # Variant-specific coefficient
    if normalized_variant is not None:
        record = coeff_cache.get((stage_slug, normalized_variant))
        if record:
            return _to_resolved(record, estimated=False), False

    # Baseline coefficient stored in DB
    baseline_record = baseline_cache.get(stage_slug)
    if baseline_record:
        # Estimated if a specific variant was requested but fallback happened
        estimated = normalized_variant is not None and normalized_variant != (
            baseline_record.variant.variant_key if baseline_record.variant else None
        )
        return _to_resolved(baseline_record, estimated=estimated), estimated

    # Default hard-coded baseline
    default_coeff = _resolve_default_coefficient(stage_slug)
    if default_coeff:
        return default_coeff, True

    # Last resort: zero values to avoid breaking the flow
    zero_coeff = ResolvedCoefficient(
        stage_slug=stage_slug,
        unit='u',
        materials=Decimal('0'),
        labor=Decimal('0'),
        equipment=Decimal('0'),
        currency='ARS',
        variant_key=normalized_variant or 'baseline',
        variant_name='Sin datos',
        estimated=True,
        source='fallback-zero',
    )
    return zero_coeff, True


def _to_resolved(record: WizardStageCoefficient, *, estimated: bool) -> ResolvedCoefficient:
    variant_key = record.variant.variant_key if record.variant else 'baseline'
    variant_name = record.variant.nombre if record.variant else 'Baseline'
    return ResolvedCoefficient(
        stage_slug=record.stage_slug,
        unit=record.unit or 'u',
        materials=_to_decimal(record.materials_per_unit),
        labor=_to_decimal(record.labor_per_unit),
        equipment=_to_decimal(record.equipment_per_unit),
        currency=(record.currency or 'ARS').upper(),
        variant_key=variant_key,
        variant_name=variant_name,
        estimated=estimated,
        source=record.source or ('baseline-db' if record.is_baseline else 'variant-db'),
        notes=record.notes,
    )


def calculate_budget_breakdown(tasks: Iterable[Dict[str, object]]) -> Dict[str, object]:
    """Aggregate quantities and compute the breakdown per etapa."""

    stage_map: Dict[str, Dict[str, object]] = {}

    catalog = _stage_catalog()

    for task in tasks:
        slug = str(task.get('etapa_slug') or '').strip().lower()
        catalog_id = task.get('catalogo_id') or task.get('etapa_id')

        if not slug and catalog_id is not None:
            for etapa in catalog.values():
                if etapa.get('id') == catalog_id:
                    slug = str(etapa.get('slug') or etapa.get('nombre') or '').strip().lower()
                    break

        if not slug:
            continue

        quantity = _to_decimal(task.get('cantidad'), default='1')
        if quantity <= 0:
            quantity = Decimal('1')
        unit = (task.get('unidad') or '').strip() or 'u'
        variant_key = (task.get('variant_key') or task.get('variant') or '').strip() or None

        bucket = stage_map.setdefault(
            slug,
            {
                'quantity': Decimal('0'),
                'unit': unit,
                'variant_key': variant_key,
                'tasks': [],
                'mixed_units': False,
            },
        )

        bucket['quantity'] += quantity
        if bucket['unit'] != unit:
            bucket['mixed_units'] = True
            bucket['unit'] = ''

        if not bucket['variant_key'] and variant_key:
            bucket['variant_key'] = variant_key

        bucket['tasks'].append(task)

    if not stage_map:
        return {
            'stages': [],
            'totals': {
                'materials': '0',
                'labor': '0',
                'equipment': '0',
                'total': '0',
                'currency': 'ARS',
                'quantity': None,
                'unit': None,
            },
            'metadata': {
                'estimated_count': 0,
                'feature_enabled': bool(current_app.config.get('WIZARD_BUDGET_BREAKDOWN_ENABLED')),
                'shadow_mode': bool(current_app.config.get('WIZARD_BUDGET_SHADOW_MODE')),
            },
        }

    coeff_cache, baseline_cache = _load_coefficients(stage_map.keys())

    slug_to_name = {str((etapa.get('slug') or etapa.get('nombre') or '')).strip().lower(): etapa.get('nombre') for etapa in catalog.values()}

    stages: List[Dict[str, object]] = []
    total_materials = Decimal('0')
    total_labor = Decimal('0')
    total_equipment = Decimal('0')
    currency = 'ARS'
    estimated_count = 0

    for slug, data in stage_map.items():
        variant_key = data.get('variant_key')
        resolved, fallback_used = _resolve_coefficient(slug, variant_key, coeff_cache, baseline_cache)

        quantity = _quantize(data['quantity']) if isinstance(data['quantity'], Decimal) else _to_decimal(data['quantity'])
        unit = data.get('unit') or resolved.unit

        materials_total = _quantize(resolved.materials * quantity)
        labor_total = _quantize(resolved.labor * quantity)
        equipment_total = _quantize(resolved.equipment * quantity)
        stage_total = _quantize(materials_total + labor_total + equipment_total)

        currency = resolved.currency or currency

        mixed_units = bool(data.get('mixed_units'))
        is_estimated = resolved.estimated or fallback_used or mixed_units
        if is_estimated:
            estimated_count += 1
            if current_app:
                current_app.logger.info(
                    "🧮 WIZARD PRESUPUESTO: etapa %s usa valores baseline estimados (variant=%s)",
                    slug,
                    variant_key or resolved.variant_key,
                )

        stages.append(
            {
                'stage_slug': slug,
                'stage_name': slug_to_name.get(slug, slug.title()),
                'variant_key': resolved.variant_key,
                'variant_name': resolved.variant_name,
                'unit': unit,
                'quantity': str(quantity),
                'materials': str(materials_total),
                'labor': str(labor_total),
                'equipment': str(equipment_total),
                'total': str(stage_total),
                'currency': resolved.currency,
                'estimated': is_estimated,
                'source': resolved.source,
                'notes': resolved.notes,
            }
        )

        total_materials += materials_total
        total_labor += labor_total
        total_equipment += equipment_total

    totals = {
        'materials': str(_quantize(total_materials)),
        'labor': str(_quantize(total_labor)),
        'equipment': str(_quantize(total_equipment)),
        'total': str(_quantize(total_materials + total_labor + total_equipment)),
        'currency': currency,
        'quantity': None,
        'unit': None,
    }

    metadata = {
        'estimated_count': estimated_count,
        'feature_enabled': bool(current_app.config.get('WIZARD_BUDGET_BREAKDOWN_ENABLED')),
        'shadow_mode': bool(current_app.config.get('WIZARD_BUDGET_SHADOW_MODE')),
    }

    return {
        'stages': stages,
        'totals': totals,
        'metadata': metadata,
    }


def get_stage_variant_payload() -> Dict[str, Dict[str, object]]:
    """Return serialized variants and baseline coefficients for the wizard frontend."""

    variants_query = WizardStageVariant.query.order_by(
        WizardStageVariant.stage_slug.asc(),
        WizardStageVariant.is_default.desc(),
        WizardStageVariant.nombre.asc(),
    ).all()

    variants: Dict[str, List[Dict[str, object]]] = {}

    for variant in variants_query:
        payload = {
            'variant_key': variant.variant_key,
            'key': variant.variant_key,
            'nombre': variant.nombre,
            'name': variant.nombre,
            'descripcion': variant.descripcion,
            'description': variant.descripcion,
            'is_default': bool(variant.is_default),
            'metadata': variant.meta,
        }
        variants.setdefault(variant.stage_slug, []).append(payload)

    coeff_query = WizardStageCoefficient.query.options(joinedload(WizardStageCoefficient.variant)).all()
    coefficients: Dict[str, Dict[str, object]] = {}

    for coeff in coeff_query:
        stage_slug = coeff.stage_slug
        if stage_slug not in coefficients or coeff.is_baseline or coeff.variant is None:
            variant = coeff.variant
            coefficients[stage_slug] = {
                'unit': coeff.unit,
                'currency': (coeff.currency or 'ARS').upper(),
                'materials': str(_to_decimal(coeff.materials_per_unit)),
                'labor': str(_to_decimal(coeff.labor_per_unit)),
                'equipment': str(_to_decimal(coeff.equipment_per_unit)),
                'is_baseline': bool(coeff.is_baseline or variant is None),
                'default_variant_key': variant.variant_key if variant else 'baseline',
                'variant_name': variant.nombre if variant else 'Baseline',
                'description': variant.descripcion if variant else coeff.notes,
                'estimated': False,
            }

    # Ensure we have at least baseline entries using defaults
    for slug, defaults in DEFAULT_STAGE_BASELINES.items():
        stage_variants = variants.setdefault(slug, [])
        baseline_key = defaults.get('variant_key', 'baseline')
        if not any(v.get('variant_key') == baseline_key or v.get('key') == baseline_key for v in stage_variants):
            stage_variants.append(
                {
                    'variant_key': baseline_key,
                    'key': baseline_key,
                    'nombre': defaults.get('variant_name', 'Baseline'),
                    'name': defaults.get('variant_name', 'Baseline'),
                    'descripcion': defaults.get('description'),
                    'description': defaults.get('description'),
                    'is_default': True,
                    'metadata': {},
                }
            )
        coefficients.setdefault(slug, {
            'unit': defaults.get('unit', 'u'),
            'currency': 'ARS',
            'materials': defaults.get('materials', '0'),
            'labor': defaults.get('labor', '0'),
            'equipment': defaults.get('equipment', '0'),
            'is_baseline': True,
            'default_variant_key': defaults.get('variant_key', 'baseline'),
            'variant_name': defaults.get('variant_name', 'Baseline'),
            'description': defaults.get('description'),
            'estimated': True,
        })

    return {
        'variants': variants,
        'coefficients': coefficients,
    }


def seed_default_coefficients_if_needed() -> None:
    """Populate baseline coefficients if the tables are empty."""

    if WizardStageCoefficient.query.first():
        return

    catalog = _stage_catalog()

    for slug, defaults in DEFAULT_STAGE_BASELINES.items():
        variant = WizardStageVariant(
            stage_slug=slug,
            variant_key=defaults.get('variant_key', 'baseline'),
            nombre=defaults.get('variant_name', 'Baseline'),
            descripcion=defaults.get('description'),
            is_default=True,
        )
        coeff = WizardStageCoefficient(
            stage_slug=slug,
            variant=variant,
            unit=defaults.get('unit', 'u'),
            materials_per_unit=_to_decimal(defaults.get('materials')),
            labor_per_unit=_to_decimal(defaults.get('labor')),
            equipment_per_unit=_to_decimal(defaults.get('equipment')),
            currency='ARS',
            is_baseline=True,
            source='seed-baseline',
            notes=defaults.get('description'),
        )

        nombre_etapa = catalog.get(slug, {}).get('nombre')
        if current_app:
            current_app.logger.info(
                "⚙️ Seed presupuestador wizard: baseline para '%s' (%s)",
                nombre_etapa or slug,
                slug,
            )

        WizardStageVariant.query.session.add(variant)
        WizardStageCoefficient.query.session.add(coeff)

    WizardStageCoefficient.query.session.commit()
