"""
Servicio de precios para la calculadora IA.
Carga los precios desde el archivo JSON generado por el importador de Excel.
"""

import os
import json
from decimal import Decimal
from typing import Dict, List, Optional, Any
from datetime import datetime

# Cache de datos
_PRECIOS_CACHE: Dict[str, Any] = {}
_CACHE_TIMESTAMP: Optional[datetime] = None
_CACHE_TTL_SECONDS = 3600  # 1 hora


def _get_data_path() -> str:
    """Obtiene la ruta al archivo de datos."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'data', 'calculadora_ia_datos.json')


def cargar_datos_calculadora() -> Dict[str, Any]:
    """Carga los datos del JSON de la calculadora."""
    global _PRECIOS_CACHE, _CACHE_TIMESTAMP

    # Verificar cache
    now = datetime.utcnow()
    if _PRECIOS_CACHE and _CACHE_TIMESTAMP:
        if (now - _CACHE_TIMESTAMP).total_seconds() < _CACHE_TTL_SECONDS:
            return _PRECIOS_CACHE

    # Cargar archivo
    data_path = _get_data_path()
    if not os.path.exists(data_path):
        return {}

    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            _PRECIOS_CACHE = data
            _CACHE_TIMESTAMP = now
            return data
    except Exception as e:
        print(f"Error cargando datos calculadora: {e}")
        return {}


def _normalizar_tipo(tipo: str) -> str:
    """Normaliza el nombre del tipo de construcción para manejar acentos."""
    tipo_lower = tipo.lower().strip()
    if 'econ' in tipo_lower:
        return 'Económica'
    elif 'prem' in tipo_lower:
        return 'Premium'
    else:
        return 'Estándar'


def obtener_precios_por_tipo(tipo_construccion: str) -> Dict[str, List[Dict]]:
    """
    Obtiene todos los precios para un tipo de construcción.

    Args:
        tipo_construccion: 'Económica', 'Estándar' o 'Premium'

    Returns:
        Diccionario con categorías y sus artículos
    """
    data = cargar_datos_calculadora()
    if not data:
        return {}

    tipos = data.get('tipos_construccion', {})

    # Intentar primero con el nombre tal cual
    tipo_data = tipos.get(tipo_construccion, {})
    if tipo_data:
        return tipo_data.get('categorias', {})

    # Intentar normalizando el tipo
    tipo_normalizado = _normalizar_tipo(tipo_construccion)
    tipo_data = tipos.get(tipo_normalizado, {})
    if tipo_data:
        return tipo_data.get('categorias', {})

    # Buscar por coincidencia parcial
    tipo_lower = tipo_construccion.lower()
    for tipo_key, tipo_val in tipos.items():
        if tipo_lower in tipo_key.lower():
            return tipo_val.get('categorias', {})

    return {}


def obtener_precio_articulo(
    categoria: str,
    nombre_articulo: str,
    tipo_construccion: str = 'Estándar'
) -> Optional[float]:
    """
    Busca el precio de un artículo específico.

    Args:
        categoria: Nombre de la categoría (puede ser parcial)
        nombre_articulo: Nombre del artículo (puede ser parcial)
        tipo_construccion: 'Económica', 'Estándar' o 'Premium'

    Returns:
        Precio en USD o None si no se encuentra
    """
    categorias = obtener_precios_por_tipo(tipo_construccion)

    # Buscar categoría
    categoria_lower = categoria.lower()
    for cat_key, articulos in categorias.items():
        if categoria_lower in cat_key.lower():
            # Buscar artículo
            nombre_lower = nombre_articulo.lower()
            for art in articulos:
                if nombre_lower in art.get('nombre', '').lower():
                    precio = art.get('precio_usd')
                    if precio is not None:
                        return precio

    return None


def buscar_articulos(
    termino: str,
    tipo_construccion: str = 'Estándar',
    solo_con_precio: bool = True,
    limite: int = 20
) -> List[Dict]:
    """
    Busca artículos por término de búsqueda.

    Args:
        termino: Texto a buscar en nombre o categoría
        tipo_construccion: Tipo de construcción
        solo_con_precio: Si True, solo retorna artículos con precio
        limite: Máximo de resultados

    Returns:
        Lista de artículos encontrados
    """
    categorias = obtener_precios_por_tipo(tipo_construccion)
    resultados = []
    termino_lower = termino.lower()

    for cat_key, articulos in categorias.items():
        for art in articulos:
            nombre = art.get('nombre', '')
            if termino_lower in nombre.lower() or termino_lower in cat_key.lower():
                if solo_con_precio and art.get('precio_usd') is None:
                    continue

                resultados.append({
                    'nombre': nombre,
                    'categoria': cat_key,
                    'precio_usd': art.get('precio_usd'),
                    'unidad': art.get('unidad', 'unidad'),
                    'subcategoria': art.get('subcategoria', ''),
                })

                if len(resultados) >= limite:
                    return resultados

    return resultados


def obtener_precios_categoria(
    categoria: str,
    tipo_construccion: str = 'Estándar',
    solo_con_precio: bool = True
) -> List[Dict]:
    """
    Obtiene todos los artículos de una categoría.

    Args:
        categoria: Nombre de la categoría (búsqueda parcial)
        tipo_construccion: Tipo de construcción
        solo_con_precio: Si True, solo retorna artículos con precio

    Returns:
        Lista de artículos de la categoría
    """
    categorias = obtener_precios_por_tipo(tipo_construccion)
    resultados = []
    categoria_lower = categoria.lower()

    for cat_key, articulos in categorias.items():
        if categoria_lower in cat_key.lower():
            for art in articulos:
                if solo_con_precio and art.get('precio_usd') is None:
                    continue

                resultados.append({
                    'nombre': art.get('nombre'),
                    'categoria': cat_key,
                    'precio_usd': art.get('precio_usd'),
                    'unidad': art.get('unidad', 'unidad'),
                })

    return resultados


def calcular_precio_material_por_m2(
    material_key: str,
    tipo_construccion: str,
    coeficiente_por_m2: float
) -> Dict[str, Any]:
    """
    Calcula el precio de un material por m² basado en los datos reales.

    Args:
        material_key: Clave del material (ej: 'cemento', 'hierro_8')
        tipo_construccion: Tipo de construcción
        coeficiente_por_m2: Coeficiente de uso por m²

    Returns:
        Diccionario con precio, unidad y detalles
    """
    # Mapeo de material_key a términos de búsqueda
    MATERIAL_SEARCH = {
        'cemento': 'cemento portland',
        'hierro_8': 'hierro 8mm',
        'hierro_10': 'hierro 10mm',
        'hierro_12': 'hierro 12mm',
        'arena': 'arena gruesa',
        'piedra': 'piedra partida',
        'ladrillos': 'ladrillo',
        'cal': 'cal hidratada',
        'ceramicos': 'ceramico',
        'porcelanato': 'porcelanato',
        'azulejos': 'azulejo',
        'cables_electricos': 'cable',
        'caños_agua': 'caño agua',
        'caños_cloacas': 'caño cloaca',
        'membrana': 'membrana',
        'pintura': 'pintura interior',
        'pintura_exterior': 'pintura exterior',
        'yeso': 'yeso',
        'aislacion_termica': 'aislacion',
        'madera_estructural': 'madera',
        'vidrios': 'vidrio',
        'aberturas_metal': 'abertura',
    }

    termino = MATERIAL_SEARCH.get(material_key, material_key.replace('_', ' '))

    # Buscar artículo
    articulos = buscar_articulos(termino, tipo_construccion, solo_con_precio=True, limite=5)

    if not articulos:
        return {
            'encontrado': False,
            'material_key': material_key,
            'precio_unitario_usd': None,
            'coeficiente': coeficiente_por_m2,
        }

    # Tomar el primer resultado con precio
    art = articulos[0]
    precio = art.get('precio_usd')

    return {
        'encontrado': True,
        'material_key': material_key,
        'nombre': art.get('nombre'),
        'categoria': art.get('categoria'),
        'precio_unitario_usd': precio,
        'unidad': art.get('unidad'),
        'coeficiente': coeficiente_por_m2,
        'costo_por_m2_usd': precio * coeficiente_por_m2 if precio else None,
    }


def obtener_estadisticas() -> Dict[str, Any]:
    """Obtiene estadísticas de los datos cargados."""
    data = cargar_datos_calculadora()
    if not data:
        return {'error': 'No se pudieron cargar los datos'}

    stats = data.get('estadisticas', {})
    tipos = data.get('tipos_construccion', {})

    # Contar artículos por tipo
    articulos_por_tipo = {}
    for tipo, tipo_data in tipos.items():
        categorias = tipo_data.get('categorias', {})
        total = sum(len(arts) for arts in categorias.values())
        articulos_por_tipo[tipo] = total

    return {
        'version': data.get('version'),
        'fecha_actualizacion': data.get('fecha_actualizacion'),
        'moneda': data.get('moneda'),
        'total_archivos': stats.get('total_archivos', 0),
        'total_articulos': stats.get('total_articulos', 0),
        'articulos_con_precio': stats.get('articulos_con_precio', 0),
        'categorias_unicas': stats.get('categorias_unicas', 0),
        'articulos_por_tipo': articulos_por_tipo,
    }


def obtener_categorias_disponibles(tipo_construccion: str = 'Estándar') -> List[str]:
    """Obtiene lista de categorías disponibles."""
    categorias = obtener_precios_por_tipo(tipo_construccion)
    return sorted(categorias.keys())


# Función para integrar con la calculadora IA existente
def enriquecer_item_con_precio_real(
    item: Dict,
    tipo_construccion: str,
    tipo_cambio_usd: float = 1100.0
) -> Dict:
    """
    Enriquece un item de la calculadora con precio real de los datos Excel.

    Args:
        item: Item del cálculo de la calculadora IA
        tipo_construccion: Tipo de construcción
        tipo_cambio_usd: Tipo de cambio USD/ARS

    Returns:
        Item enriquecido con precio real si está disponible
    """
    material_key = item.get('material_key')
    descripcion = item.get('descripcion', '')

    if not material_key and not descripcion:
        return item

    # Buscar por material_key o descripción
    termino = material_key.replace('_', ' ') if material_key else descripcion[:30]
    articulos = buscar_articulos(termino, tipo_construccion, solo_con_precio=True, limite=3)

    if articulos:
        art = articulos[0]
        precio_usd = art.get('precio_usd')

        if precio_usd:
            item['precio_real_usd'] = precio_usd
            item['precio_real_ars'] = precio_usd * tipo_cambio_usd
            item['fuente_precio'] = 'excel_importado'
            item['articulo_encontrado'] = art.get('nombre')

    return item


# =====================================================================
# NUEVAS FUNCIONES - Consulta directa a BD (items_inventario)
# =====================================================================

def obtener_items_etapa_bd(
    etapa_nombre: str,
    tipo_construccion: str = 'Estándar',
    org_id: int = 2,
    solo_con_precio: bool = False
) -> List[Dict]:
    """
    Obtiene items de una etapa desde la BD filtrados por tipo de construcción.

    Args:
        etapa_nombre: Nombre de la etapa (ej: 'Etapa Excavación')
        tipo_construccion: 'Económica', 'Estándar' o 'Premium'
        org_id: ID de la organización
        solo_con_precio: Si True, solo retorna items con precio > 0

    Returns:
        Lista de items con sus datos
    """
    try:
        from flask import current_app
        from extensions import db
        from models.inventory import ItemInventario, InventoryCategory

        # Determinar el filtro de tipo
        tipo_lower = tipo_construccion.lower()

        # Obtener la categoría principal (etapa)
        etapa = InventoryCategory.query.filter(
            InventoryCategory.company_id == org_id,
            InventoryCategory.nombre.ilike(f'%{etapa_nombre}%'),
            InventoryCategory.parent_id == None
        ).first()

        if not etapa:
            return []

        # Obtener subcategorías de esta etapa
        subcategorias = InventoryCategory.query.filter_by(
            company_id=org_id,
            parent_id=etapa.id,
            is_active=True
        ).all()

        subcat_ids = [s.id for s in subcategorias]

        if not subcat_ids:
            return []

        # Query base
        query = ItemInventario.query.filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.categoria_id.in_(subcat_ids),
            ItemInventario.activo == True
        )

        # Filtrar por tipo de construcción
        if 'econ' in tipo_lower:
            query = query.filter(ItemInventario.aplica_economica == True)
        elif 'prem' in tipo_lower:
            query = query.filter(ItemInventario.aplica_premium == True)
        else:  # Estándar por defecto
            query = query.filter(ItemInventario.aplica_estandar == True)

        # Filtrar solo con precio si se solicita
        if solo_con_precio:
            query = query.filter(ItemInventario.precio_promedio_usd > 0)

        items = query.order_by(ItemInventario.nombre).all()

        resultado = []
        for item in items:
            resultado.append({
                'id': item.id,
                'codigo': item.codigo,
                'nombre': item.nombre,
                'descripcion': item.descripcion,
                'unidad': item.unidad,
                'precio_usd': float(item.precio_promedio_usd or 0),
                'categoria': item.categoria.nombre if item.categoria else None,
                'etapa': etapa_nombre,
                'aplica_economica': item.aplica_economica,
                'aplica_estandar': item.aplica_estandar,
                'aplica_premium': item.aplica_premium,
            })

        return resultado

    except Exception as e:
        print(f"Error obteniendo items de etapa: {e}")
        return []


def calcular_costo_etapa_bd(
    etapa_nombre: str,
    m2_construccion: float,
    tipo_construccion: str = 'Estándar',
    org_id: int = 2
) -> Dict[str, Any]:
    """
    Calcula el costo estimado de una etapa basado en los items del inventario.

    Args:
        etapa_nombre: Nombre de la etapa
        m2_construccion: Metros cuadrados a construir
        tipo_construccion: Tipo de construcción
        org_id: ID de la organización

    Returns:
        Diccionario con el cálculo de la etapa
    """
    items = obtener_items_etapa_bd(
        etapa_nombre,
        tipo_construccion,
        org_id,
        solo_con_precio=True
    )

    if not items:
        return {
            'etapa': etapa_nombre,
            'tipo_construccion': tipo_construccion,
            'm2': m2_construccion,
            'items_encontrados': 0,
            'costo_total_usd': 0,
            'detalle': [],
            'mensaje': 'No se encontraron items con precio para esta etapa'
        }

    # Agrupar items por subcategoría
    items_por_categoria = {}
    for item in items:
        cat = item['categoria'] or 'Sin categoría'
        if cat not in items_por_categoria:
            items_por_categoria[cat] = []
        items_por_categoria[cat].append(item)

    # Calcular costo (simplificado - se puede mejorar con coeficientes por m2)
    costo_total_usd = 0
    detalle = []

    for cat, cat_items in items_por_categoria.items():
        cat_costo = sum(i['precio_usd'] for i in cat_items if i['precio_usd'])
        costo_total_usd += cat_costo
        detalle.append({
            'subcategoria': cat,
            'items': len(cat_items),
            'costo_referencia_usd': cat_costo
        })

    return {
        'etapa': etapa_nombre,
        'tipo_construccion': tipo_construccion,
        'm2': m2_construccion,
        'items_encontrados': len(items),
        'costo_referencia_total_usd': costo_total_usd,
        'detalle_categorias': detalle,
        'items': items
    }


def obtener_resumen_etapas_bd(org_id: int = 2) -> List[Dict]:
    """
    Obtiene un resumen de todas las etapas disponibles con conteo de items.

    Args:
        org_id: ID de la organización

    Returns:
        Lista de etapas con estadísticas
    """
    try:
        from models.inventory import ItemInventario, InventoryCategory

        # Obtener categorías principales (etapas)
        etapas = InventoryCategory.query.filter(
            InventoryCategory.company_id == org_id,
            InventoryCategory.parent_id == None,
            InventoryCategory.is_active == True
        ).order_by(InventoryCategory.sort_order, InventoryCategory.nombre).all()

        resultado = []
        for etapa in etapas:
            # Contar subcategorías
            subcats = InventoryCategory.query.filter_by(
                company_id=org_id,
                parent_id=etapa.id,
                is_active=True
            ).all()

            subcat_ids = [s.id for s in subcats]

            # Contar items por tipo
            if subcat_ids:
                total_items = ItemInventario.query.filter(
                    ItemInventario.organizacion_id == org_id,
                    ItemInventario.categoria_id.in_(subcat_ids),
                    ItemInventario.activo == True
                ).count()

                items_economica = ItemInventario.query.filter(
                    ItemInventario.organizacion_id == org_id,
                    ItemInventario.categoria_id.in_(subcat_ids),
                    ItemInventario.activo == True,
                    ItemInventario.aplica_economica == True
                ).count()

                items_estandar = ItemInventario.query.filter(
                    ItemInventario.organizacion_id == org_id,
                    ItemInventario.categoria_id.in_(subcat_ids),
                    ItemInventario.activo == True,
                    ItemInventario.aplica_estandar == True
                ).count()

                items_premium = ItemInventario.query.filter(
                    ItemInventario.organizacion_id == org_id,
                    ItemInventario.categoria_id.in_(subcat_ids),
                    ItemInventario.activo == True,
                    ItemInventario.aplica_premium == True
                ).count()

                items_con_precio = ItemInventario.query.filter(
                    ItemInventario.organizacion_id == org_id,
                    ItemInventario.categoria_id.in_(subcat_ids),
                    ItemInventario.activo == True,
                    ItemInventario.precio_promedio_usd > 0
                ).count()
            else:
                total_items = items_economica = items_estandar = items_premium = items_con_precio = 0

            resultado.append({
                'id': etapa.id,
                'nombre': etapa.nombre,
                'subcategorias': len(subcats),
                'total_items': total_items,
                'items_economica': items_economica,
                'items_estandar': items_estandar,
                'items_premium': items_premium,
                'items_con_precio': items_con_precio
            })

        return resultado

    except Exception as e:
        print(f"Error obteniendo resumen de etapas: {e}")
        return []
