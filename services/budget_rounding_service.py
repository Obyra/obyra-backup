"""
Servicio de Integración: Motor de Redondeo con Presupuestos

Integra el motor de redondeo de compras con la calculadora IA,
agregando soporte para precios duales USD/ARS y presentaciones de inventario.
"""

from typing import List, Dict, Optional, Any
from decimal import Decimal, ROUND_HALF_UP
import json
import logging

from services.purchase_rounding import (
    round_to_purchase,
    round_item_for_purchase,
    RoundingResult
)


# Presentaciones por defecto para materiales comunes
DEFAULT_PRESENTACIONES = {
    # Pinturas y líquidos
    'pintura': [
        {'size': 20, 'name': 'Balde 20L'},
        {'size': 10, 'name': 'Balde 10L'},
        {'size': 4, 'name': 'Balde 4L'},
        {'size': 1, 'name': 'Litro'}
    ],
    'pintura_exterior': [
        {'size': 20, 'name': 'Balde 20L'},
        {'size': 10, 'name': 'Balde 10L'},
        {'size': 4, 'name': 'Balde 4L'}
    ],
    'sellador': [
        {'size': 20, 'name': 'Balde 20L'},
        {'size': 10, 'name': 'Balde 10L'},
        {'size': 4, 'name': 'Balde 4L'},
        {'size': 1, 'name': 'Litro'}
    ],
    'membrana': [
        {'size': 40, 'name': 'Rollo 40m²'},
        {'size': 10, 'name': 'Rollo 10m²'}
    ],

    # Cemento y morteros
    'cemento': [
        {'size': 50, 'name': 'Bolsa 50kg'},
        {'size': 40, 'name': 'Bolsa 40kg'}
    ],
    'cal': [
        {'size': 25, 'name': 'Bolsa 25kg'},
        {'size': 20, 'name': 'Bolsa 20kg'}
    ],
    'yeso': [
        {'size': 40, 'name': 'Bolsa 40kg'},
        {'size': 25, 'name': 'Bolsa 25kg'}
    ],

    # Áridos
    'arena': [
        {'size': 1, 'name': 'm³'}  # Se vende por m³
    ],
    'piedra': [
        {'size': 1, 'name': 'm³'}
    ],

    # Hierros
    'hierro_8': [
        {'size': 12, 'name': 'Barra 12m (6kg)'}
    ],
    'hierro_10': [
        {'size': 12, 'name': 'Barra 12m (9kg)'}
    ],
    'hierro_12': [
        {'size': 12, 'name': 'Barra 12m (13kg)'}
    ],

    # Ladrillos
    'ladrillos': [
        {'size': 576, 'name': 'Pallet 576u'},
        {'size': 192, 'name': 'Medio pallet 192u'},
        {'size': 1, 'name': 'Unidad'}
    ],

    # Cerámicos y porcelanato
    'ceramicos': [
        {'size': 2, 'name': 'Caja 2m²'},
        {'size': 1.5, 'name': 'Caja 1.5m²'}
    ],
    'porcelanato': [
        {'size': 1.44, 'name': 'Caja 1.44m²'},
        {'size': 1.2, 'name': 'Caja 1.2m²'}
    ],
    'azulejos': [
        {'size': 1.5, 'name': 'Caja 1.5m²'},
        {'size': 1, 'name': 'Caja 1m²'}
    ],

    # Instalaciones
    'cables_electricos': [
        {'size': 100, 'name': 'Rollo 100m'},
        {'size': 50, 'name': 'Rollo 50m'},
        {'size': 25, 'name': 'Rollo 25m'}
    ],
    'caños_agua': [
        {'size': 6, 'name': 'Caño 6m'},
        {'size': 4, 'name': 'Caño 4m'}
    ],
    'caños_cloacas': [
        {'size': 4, 'name': 'Caño 4m'},
        {'size': 3, 'name': 'Caño 3m'}
    ],

    # Aislación
    'aislacion_termica': [
        {'size': 18, 'name': 'Rollo 18m²'},
        {'size': 12, 'name': 'Rollo 12m²'}
    ],

    # Vidrios y aberturas (unidades)
    'vidrios': [
        {'size': 1, 'name': 'm²'}
    ],
    'aberturas_metal': [
        {'size': 1, 'name': 'Unidad'}
    ],

    # Madera
    'madera_estructural': [
        {'size': 1, 'name': 'm³'}
    ],

    # Techos
    'chapas': [
        {'size': 1, 'name': 'm² (chapa)'}
    ],
    'tejas': [
        {'size': 1, 'name': 'm² (tejas)'}
    ]
}


# Unidades base por material
UNIDADES_BASE = {
    'pintura': 'lts',
    'pintura_exterior': 'lts',
    'sellador': 'lts',
    'membrana': 'm²',
    'cemento': 'bolsa',
    'cal': 'kg',
    'yeso': 'kg',
    'arena': 'm³',
    'piedra': 'm³',
    'hierro_8': 'kg',
    'hierro_10': 'kg',
    'hierro_12': 'kg',
    'ladrillos': 'unidad',
    'ceramicos': 'm²',
    'porcelanato': 'm²',
    'azulejos': 'm²',
    'cables_electricos': 'ml',
    'caños_agua': 'ml',
    'caños_cloacas': 'ml',
    'aislacion_termica': 'm²',
    'vidrios': 'm²',
    'aberturas_metal': 'unidad',
    'madera_estructural': 'm³',
    'chapas': 'm²',
    'tejas': 'm²'
}


def get_presentaciones_for_material(material_key: str) -> List[Dict]:
    """
    Obtiene las presentaciones configuradas para un material.
    Primero busca en el inventario, luego usa defaults.
    """
    return DEFAULT_PRESENTACIONES.get(material_key, [{'size': 1, 'name': 'Unidad'}])


def get_unidad_base(material_key: str) -> str:
    """Obtiene la unidad base para un material."""
    return UNIDADES_BASE.get(material_key, 'unidad')


def round_budget_items(
    items: List[Dict],
    include_surplus: bool = True
) -> List[Dict]:
    """
    Aplica redondeo de compra a una lista de items de presupuesto.

    Args:
        items: Lista de items con cantidad, material_key, etc.
        include_surplus: Si incluir información de sobrante

    Returns:
        Lista de items con información de redondeo agregada
    """
    rounded_items = []

    for item in items:
        # Solo redondear materiales (no mano de obra ni equipos)
        if item.get('tipo') != 'material':
            rounded_items.append(item)
            continue

        material_key = item.get('material_key')
        cantidad_neta = item.get('cantidad', 0)

        if not material_key or cantidad_neta <= 0:
            rounded_items.append(item)
            continue

        # Obtener presentaciones
        presentaciones = get_presentaciones_for_material(material_key)
        unidad_base = get_unidad_base(material_key)

        # Aplicar redondeo
        result = round_item_for_purchase(
            articulo_id=None,
            descripcion=item.get('descripcion', ''),
            required_qty=cantidad_neta,
            unidad_base=unidad_base,
            presentaciones=presentaciones
        )

        # Agregar información de redondeo al item
        item_rounded = item.copy()
        item_rounded['cantidad_neta'] = cantidad_neta
        item_rounded['cantidad'] = result.total_compra_qty  # Cantidad a comprar
        item_rounded['cantidad_compra'] = result.total_compra_qty
        item_rounded['packs'] = result.packs_seleccionados
        item_rounded['detalle_packs'] = result.detalle_packs

        if include_surplus:
            item_rounded['sobrante'] = result.sobrante_qty

        # Recalcular subtotal con cantidad redondeada
        precio_unit = item.get('precio_unit', 0)
        item_rounded['subtotal'] = round(result.total_compra_qty * precio_unit, 2)

        rounded_items.append(item_rounded)

    return rounded_items


def round_etapa_items(etapa: Dict, include_surplus: bool = True) -> Dict:
    """
    Aplica redondeo a todos los items de una etapa.

    Args:
        etapa: Diccionario de etapa con 'items'
        include_surplus: Si incluir información de sobrante

    Returns:
        Etapa con items redondeados
    """
    if 'items' not in etapa:
        return etapa

    etapa_result = etapa.copy()
    etapa_result['items'] = round_budget_items(etapa['items'], include_surplus)

    # Recalcular subtotales
    subtotal_materiales = 0
    subtotal_mano_obra = 0
    subtotal_equipos = 0

    for item in etapa_result['items']:
        subtotal = item.get('subtotal', 0)
        tipo = item.get('tipo')

        if tipo == 'material':
            subtotal_materiales += subtotal
        elif tipo == 'mano_obra':
            subtotal_mano_obra += subtotal
        elif tipo == 'equipo':
            subtotal_equipos += subtotal

    etapa_result['subtotal_materiales'] = round(subtotal_materiales, 2)
    etapa_result['subtotal_mano_obra'] = round(subtotal_mano_obra, 2)
    etapa_result['subtotal_equipos'] = round(subtotal_equipos, 2)
    etapa_result['subtotal_total'] = round(
        subtotal_materiales + subtotal_mano_obra + subtotal_equipos, 2
    )

    return etapa_result


def apply_rounding_to_budget(
    etapas: List[Dict],
    include_surplus: bool = True
) -> Dict:
    """
    Aplica redondeo a todas las etapas de un presupuesto.

    Args:
        etapas: Lista de etapas calculadas
        include_surplus: Si incluir información de sobrante

    Returns:
        Dict con etapas redondeadas y totales actualizados
    """
    etapas_rounded = []
    total_general = 0
    total_sobrante = 0

    for etapa in etapas:
        etapa_rounded = round_etapa_items(etapa, include_surplus)
        etapas_rounded.append(etapa_rounded)
        total_general += etapa_rounded.get('subtotal_total', 0)

        # Sumar sobrantes de materiales
        if include_surplus:
            for item in etapa_rounded.get('items', []):
                if item.get('tipo') == 'material':
                    total_sobrante += item.get('sobrante', 0)

    result = {
        'etapas': etapas_rounded,
        'total_parcial': round(total_general, 2),
        'total_sobrante_estimado': round(total_sobrante, 2),
        'redondeo_aplicado': True
    }

    return result


def convert_to_dual_currency(
    items: List[Dict],
    fx_rate: float,
    base_currency: str = 'ARS'
) -> List[Dict]:
    """
    Agrega precios en moneda alternativa a los items.

    Args:
        items: Lista de items con precios
        fx_rate: Tipo de cambio (ARS/USD)
        base_currency: Moneda base de los precios actuales

    Returns:
        Items con precios en ambas monedas
    """
    if not fx_rate or fx_rate <= 0:
        return items

    items_dual = []

    for item in items:
        item_dual = item.copy()
        precio = item.get('precio_unit', 0)
        subtotal = item.get('subtotal', 0)

        if base_currency == 'ARS':
            # Agregar precio en USD
            item_dual['precio_unit_ars'] = precio
            item_dual['precio_unit_usd'] = round(precio / fx_rate, 2)
            item_dual['subtotal_ars'] = subtotal
            item_dual['subtotal_usd'] = round(subtotal / fx_rate, 2)
        else:
            # Base es USD, agregar ARS
            item_dual['precio_unit_usd'] = precio
            item_dual['precio_unit_ars'] = round(precio * fx_rate, 2)
            item_dual['subtotal_usd'] = subtotal
            item_dual['subtotal_ars'] = round(subtotal * fx_rate, 2)

        items_dual.append(item_dual)

    return items_dual


def apply_dual_currency_to_etapas(
    etapas: List[Dict],
    fx_rate: float,
    base_currency: str = 'ARS'
) -> List[Dict]:
    """
    Aplica conversión dual de moneda a todas las etapas.
    """
    etapas_dual = []

    for etapa in etapas:
        etapa_dual = etapa.copy()

        if 'items' in etapa:
            etapa_dual['items'] = convert_to_dual_currency(
                etapa['items'], fx_rate, base_currency
            )

        # Agregar subtotales en ambas monedas
        if base_currency == 'ARS':
            etapa_dual['subtotal_materiales_ars'] = etapa.get('subtotal_materiales', 0)
            etapa_dual['subtotal_materiales_usd'] = round(
                etapa.get('subtotal_materiales', 0) / fx_rate, 2
            )
            etapa_dual['subtotal_mano_obra_ars'] = etapa.get('subtotal_mano_obra', 0)
            etapa_dual['subtotal_mano_obra_usd'] = round(
                etapa.get('subtotal_mano_obra', 0) / fx_rate, 2
            )
            etapa_dual['subtotal_equipos_ars'] = etapa.get('subtotal_equipos', 0)
            etapa_dual['subtotal_equipos_usd'] = round(
                etapa.get('subtotal_equipos', 0) / fx_rate, 2
            )
            etapa_dual['subtotal_total_ars'] = etapa.get('subtotal_total', 0)
            etapa_dual['subtotal_total_usd'] = round(
                etapa.get('subtotal_total', 0) / fx_rate, 2
            )
        else:
            etapa_dual['subtotal_materiales_usd'] = etapa.get('subtotal_materiales', 0)
            etapa_dual['subtotal_materiales_ars'] = round(
                etapa.get('subtotal_materiales', 0) * fx_rate, 2
            )
            etapa_dual['subtotal_mano_obra_usd'] = etapa.get('subtotal_mano_obra', 0)
            etapa_dual['subtotal_mano_obra_ars'] = round(
                etapa.get('subtotal_mano_obra', 0) * fx_rate, 2
            )
            etapa_dual['subtotal_equipos_usd'] = etapa.get('subtotal_equipos', 0)
            etapa_dual['subtotal_equipos_ars'] = round(
                etapa.get('subtotal_equipos', 0) * fx_rate, 2
            )
            etapa_dual['subtotal_total_usd'] = etapa.get('subtotal_total', 0)
            etapa_dual['subtotal_total_ars'] = round(
                etapa.get('subtotal_total', 0) * fx_rate, 2
            )

        etapas_dual.append(etapa_dual)

    return etapas_dual


def process_budget_with_rounding_and_dual_currency(
    etapas: List[Dict],
    fx_rate: Optional[float] = None,
    base_currency: str = 'ARS',
    apply_rounding: bool = True,
    include_surplus: bool = True
) -> Dict:
    """
    Procesa un presupuesto completo aplicando redondeo y conversión dual de moneda.

    Args:
        etapas: Lista de etapas calculadas
        fx_rate: Tipo de cambio (None para no convertir)
        base_currency: Moneda base ('ARS' o 'USD')
        apply_rounding: Si aplicar redondeo de compras
        include_surplus: Si incluir información de sobrante

    Returns:
        Dict con presupuesto procesado
    """
    result_etapas = etapas

    # 1. Aplicar redondeo si está habilitado
    if apply_rounding:
        rounding_result = apply_rounding_to_budget(result_etapas, include_surplus)
        result_etapas = rounding_result['etapas']

    # 2. Aplicar conversión dual de moneda si hay tipo de cambio
    if fx_rate and fx_rate > 0:
        result_etapas = apply_dual_currency_to_etapas(
            result_etapas, fx_rate, base_currency
        )

    # 3. Calcular totales finales
    total_ars = sum(e.get('subtotal_total_ars', e.get('subtotal_total', 0)) for e in result_etapas)
    total_usd = sum(e.get('subtotal_total_usd', 0) for e in result_etapas) if fx_rate else None

    result = {
        'ok': True,
        'etapas': result_etapas,
        'total_parcial_ars': round(total_ars, 2),
        'moneda_base': base_currency,
        'redondeo_aplicado': apply_rounding
    }

    if fx_rate and fx_rate > 0:
        result['total_parcial_usd'] = round(total_usd, 2) if total_usd else None
        result['tipo_cambio'] = fx_rate

    if apply_rounding and include_surplus:
        total_sobrante = sum(
            item.get('sobrante', 0)
            for etapa in result_etapas
            for item in etapa.get('items', [])
            if item.get('tipo') == 'material'
        )
        result['total_sobrante_estimado'] = round(total_sobrante, 2)

    return result


def generate_purchase_list_from_budget(etapas: List[Dict]) -> Dict:
    """
    Genera una lista de compras consolidada desde las etapas del presupuesto.
    Agrupa items por material y presenta cantidades totales a comprar.

    Returns:
        Dict con lista de compras agrupada por categoría
    """
    materiales_consolidados = {}

    for etapa in etapas:
        for item in etapa.get('items', []):
            if item.get('tipo') != 'material':
                continue

            material_key = item.get('material_key') or item.get('codigo', '')

            if material_key not in materiales_consolidados:
                materiales_consolidados[material_key] = {
                    'descripcion': item.get('descripcion', ''),
                    'unidad': item.get('unidad', 'unidad'),
                    'cantidad_neta_total': 0,
                    'cantidad_compra_total': 0,
                    'sobrante_total': 0,
                    'subtotal_ars': 0,
                    'subtotal_usd': 0,
                    'detalle_packs': '',
                    'etapas': []
                }

            mat = materiales_consolidados[material_key]
            mat['cantidad_neta_total'] += item.get('cantidad_neta', item.get('cantidad', 0))
            mat['cantidad_compra_total'] += item.get('cantidad_compra', item.get('cantidad', 0))
            mat['sobrante_total'] += item.get('sobrante', 0)
            mat['subtotal_ars'] += item.get('subtotal_ars', item.get('subtotal', 0))
            mat['subtotal_usd'] += item.get('subtotal_usd', 0)
            mat['etapas'].append(etapa.get('nombre', etapa.get('slug', '')))

    # Aplicar redondeo a cantidades consolidadas
    for key, mat in materiales_consolidados.items():
        presentaciones = get_presentaciones_for_material(key)
        unidad_base = get_unidad_base(key)

        result = round_item_for_purchase(
            articulo_id=None,
            descripcion=mat['descripcion'],
            required_qty=mat['cantidad_neta_total'],
            unidad_base=unidad_base,
            presentaciones=presentaciones
        )

        mat['cantidad_compra_redondeada'] = result.total_compra_qty
        mat['packs_consolidados'] = result.packs_seleccionados
        mat['detalle_packs'] = result.detalle_packs
        mat['sobrante_final'] = result.sobrante_qty

    # Agrupar por categoría
    categorias = {
        'Pinturas y Terminaciones': [],
        'Cementos y Morteros': [],
        'Áridos': [],
        'Hierros': [],
        'Ladrillos y Bloques': [],
        'Cerámicos y Revestimientos': [],
        'Instalaciones': [],
        'Aislación': [],
        'Otros': []
    }

    categoria_mapping = {
        'pintura': 'Pinturas y Terminaciones',
        'pintura_exterior': 'Pinturas y Terminaciones',
        'sellador': 'Pinturas y Terminaciones',
        'membrana': 'Pinturas y Terminaciones',
        'cemento': 'Cementos y Morteros',
        'cal': 'Cementos y Morteros',
        'yeso': 'Cementos y Morteros',
        'arena': 'Áridos',
        'piedra': 'Áridos',
        'hierro_8': 'Hierros',
        'hierro_10': 'Hierros',
        'hierro_12': 'Hierros',
        'ladrillos': 'Ladrillos y Bloques',
        'ceramicos': 'Cerámicos y Revestimientos',
        'porcelanato': 'Cerámicos y Revestimientos',
        'azulejos': 'Cerámicos y Revestimientos',
        'cables_electricos': 'Instalaciones',
        'caños_agua': 'Instalaciones',
        'caños_cloacas': 'Instalaciones',
        'aislacion_termica': 'Aislación'
    }

    for key, mat in materiales_consolidados.items():
        cat = categoria_mapping.get(key, 'Otros')
        categorias[cat].append({
            'material_key': key,
            **mat
        })

    # Eliminar categorías vacías
    categorias = {k: v for k, v in categorias.items() if v}

    # Calcular totales
    total_ars = sum(m.get('subtotal_ars', 0) for mats in categorias.values() for m in mats)
    total_usd = sum(m.get('subtotal_usd', 0) for mats in categorias.values() for m in mats)

    return {
        'categorias': categorias,
        'total_materiales_ars': round(total_ars, 2),
        'total_materiales_usd': round(total_usd, 2) if total_usd > 0 else None,
        'cantidad_items': sum(len(mats) for mats in categorias.values())
    }
