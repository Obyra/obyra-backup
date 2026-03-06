"""
Servicio de consulta de precios de MercadoLibre Argentina.
Busca precios promedio de materiales de construccion en MercadoLibre
para usar como referencia en la calculadora de presupuestos.

Nota: MercadoLibre requiere un access_token para su API.
Configurar ML_ACCESS_TOKEN en variables de entorno o .env.
Sin token, el servicio funciona pero sin datos de ML.
"""
import requests
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

# Cache en archivo para evitar consultas repetitivas
CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'cache_mercadolibre.json')
CACHE_DURACION_HORAS = 24

# Token de MercadoLibre (opcional, configurar en .env)
ML_ACCESS_TOKEN = os.environ.get('ML_ACCESS_TOKEN', '')

# Materiales de construccion comunes con sus queries de busqueda
MATERIALES_ML = {
    'MAT-CEMENTO': {
        'query': 'cemento portland 50kg',
        'unidad': 'bolsa',
        'categoria': 'MLA1574',  # Construcción
    },
    'MAT-CAL': {
        'query': 'cal hidratada 25kg construccion',
        'unidad': 'bolsa',
        'categoria': 'MLA1574',
    },
    'MAT-ARENA': {
        'query': 'arena gruesa construccion m3',
        'unidad': 'm3',
        'categoria': 'MLA1574',
    },
    'MAT-PIEDRA': {
        'query': 'piedra partida 6-20 construccion',
        'unidad': 'm3',
        'categoria': 'MLA1574',
    },
    'MAT-HIERRO8': {
        'query': 'hierro construccion 8mm barra 12m',
        'unidad': 'barra',
        'categoria': 'MLA1574',
    },
    'MAT-HIERRO10': {
        'query': 'hierro construccion 10mm barra 12m',
        'unidad': 'barra',
        'categoria': 'MLA1574',
    },
    'MAT-HIERRO12': {
        'query': 'hierro construccion 12mm barra 12m',
        'unidad': 'barra',
        'categoria': 'MLA1574',
    },
    'MAT-LADRILLO': {
        'query': 'ladrillo ceramico hueco 8x18x33',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-LADRILLO-HUECO': {
        'query': 'ladrillo ceramico hueco 8x18x33',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-BLOQUE-HORM': {
        'query': 'bloque hormigon 20x20x40',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-MALLA-SIMA': {
        'query': 'malla sima 15x15 4.2mm',
        'unidad': 'm2',
        'categoria': 'MLA1574',
    },
    'MAT-IMPER': {
        'query': 'membrana asfaltica 4mm con aluminio',
        'unidad': 'rollo 10m2',
        'categoria': 'MLA1574',
    },
    'MAT-PINTURA-INT': {
        'query': 'pintura latex interior 20 litros',
        'unidad': '20L',
        'categoria': 'MLA1574',
    },
    'MAT-PINTURA-EXT': {
        'query': 'pintura latex exterior 20 litros',
        'unidad': '20L',
        'categoria': 'MLA1574',
    },
    'MAT-PORCELLANATO': {
        'query': 'porcellanato 60x60 primera calidad',
        'unidad': 'm2',
        'categoria': 'MLA1574',
    },
    'MAT-CERAMICO-REV': {
        'query': 'ceramico revestimiento pared 30x45',
        'unidad': 'm2',
        'categoria': 'MLA1574',
    },
    'MAT-CABLE': {
        'query': 'cable unipolar 2.5mm rollo 100m',
        'unidad': 'rollo 100m',
        'categoria': 'MLA1574',
    },
    'MAT-CANO-AGUA': {
        'query': 'caño termofusion 20mm x metro',
        'unidad': 'ml',
        'categoria': 'MLA1574',
    },
    'MAT-DURLOCK': {
        'query': 'placa durlock standard 1.20x2.40',
        'unidad': 'placa',
        'categoria': 'MLA1574',
    },
    'MAT-PUERTA-PLACA': {
        'query': 'puerta placa 70x200 marco chapa',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-VENTANA-ALU': {
        'query': 'ventana aluminio herrero 150x110',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-ADHESIVO': {
        'query': 'adhesivo ceramico klaukol 30kg',
        'unidad': 'bolsa 30kg',
        'categoria': 'MLA1574',
    },
    'MAT-SANITARIO': {
        'query': 'inodoro deposito mochila ferrum',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-GRIFERIA': {
        'query': 'griferia monocomando lavatorio baño',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-TERMOTANQUE': {
        'query': 'termotanque electrico 50 litros',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-TANQUE-AGUA': {
        'query': 'tanque agua tricapa 1000 litros',
        'unidad': 'unidad',
        'categoria': 'MLA1574',
    },
    'MAT-HORMIGON': {
        'query': 'hormigon elaborado h21 m3',
        'unidad': 'm3',
        'categoria': 'MLA1574',
    },
}


def _cargar_cache() -> dict:
    """Carga el cache de precios de ML."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Error cargando cache ML: {e}")
    return {}


def _guardar_cache(cache: dict):
    """Guarda el cache de precios."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Error guardando cache ML: {e}")


def _cache_valido(entrada: dict) -> bool:
    """Verifica si una entrada del cache es valida."""
    if not entrada or 'timestamp' not in entrada:
        return False
    try:
        ts = datetime.fromisoformat(entrada['timestamp'])
        return datetime.now() - ts < timedelta(hours=CACHE_DURACION_HORAS)
    except Exception:
        return False


def buscar_precio_mercadolibre(query: str, limit: int = 10) -> Optional[Dict]:
    """
    Busca productos en MercadoLibre Argentina y calcula precio promedio.

    Args:
        query: Termino de busqueda
        limit: Cantidad maxima de resultados

    Returns:
        Dict con precio_promedio, precio_min, precio_max, resultados
        o None si no hay resultados
    """
    try:
        url = "https://api.mercadolibre.com/sites/MLA/search"
        params = {
            "q": query,
            "limit": limit,
        }
        headers = {
            "User-Agent": "OBYRA-App/1.0",
            "Accept": "application/json",
        }
        if ML_ACCESS_TOKEN:
            headers["Authorization"] = f"Bearer {ML_ACCESS_TOKEN}"

        resp = requests.get(url, params=params, headers=headers, timeout=10)

        if resp.status_code == 403:
            logger.info("MercadoLibre API requiere token. Configurar ML_ACCESS_TOKEN.")
            return None

        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        precios = []
        for r in results:
            precio = r.get("price")
            if precio and precio > 0:
                # Filtrar precios absurdos (por ejemplo, precios por centavo o millones)
                precios.append(precio)

        if not precios:
            return None

        # Eliminar outliers (precios fuera de 2 desviaciones estandar)
        if len(precios) >= 4:
            avg = sum(precios) / len(precios)
            std = (sum((p - avg) ** 2 for p in precios) / len(precios)) ** 0.5
            if std > 0:
                precios = [p for p in precios if abs(p - avg) < 2 * std]

        if not precios:
            return None

        return {
            "query": query,
            "precio_promedio": round(sum(precios) / len(precios), 2),
            "precio_min": min(precios),
            "precio_max": max(precios),
            "resultados": len(precios),
            "timestamp": datetime.now().isoformat(),
        }

    except requests.exceptions.RequestException as e:
        logger.warning(f"Error consultando MercadoLibre para '{query}': {e}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado en busqueda ML '{query}': {e}")
        return None


def obtener_precio_material_ml(codigo_material: str, forzar: bool = False) -> Optional[Dict]:
    """
    Obtiene el precio de un material desde MercadoLibre, usando cache.

    Args:
        codigo_material: Codigo del material (ej: 'MAT-CEMENTO')
        forzar: Si True, ignora el cache

    Returns:
        Dict con precio promedio y detalles, o None
    """
    config = MATERIALES_ML.get(codigo_material)
    if not config:
        return None

    # Verificar cache
    if not forzar:
        cache = _cargar_cache()
        entrada = cache.get(codigo_material)
        if _cache_valido(entrada):
            return entrada

    # Buscar en ML
    resultado = buscar_precio_mercadolibre(config['query'])
    if resultado:
        resultado['codigo'] = codigo_material
        resultado['unidad_busqueda'] = config['unidad']

        # Guardar en cache
        cache = _cargar_cache()
        cache[codigo_material] = resultado
        _guardar_cache(cache)

    return resultado


def actualizar_todos_los_precios(forzar: bool = False) -> Dict[str, any]:
    """
    Actualiza precios de todos los materiales definidos desde MercadoLibre.

    Args:
        forzar: Si True, actualiza todos aunque el cache sea valido

    Returns:
        Resumen de la actualizacion
    """
    actualizados = 0
    errores = 0
    resultados = {}

    for codigo in MATERIALES_ML:
        resultado = obtener_precio_material_ml(codigo, forzar=forzar)
        if resultado:
            actualizados += 1
            resultados[codigo] = {
                'precio_promedio': resultado['precio_promedio'],
                'unidad': resultado.get('unidad_busqueda', ''),
                'resultados': resultado['resultados'],
            }
        else:
            errores += 1
            resultados[codigo] = {'error': 'Sin resultados'}

    return {
        'total': len(MATERIALES_ML),
        'actualizados': actualizados,
        'errores': errores,
        'timestamp': datetime.now().isoformat(),
        'detalle': resultados,
    }


def obtener_precios_ml_como_referencia() -> Dict[str, float]:
    """
    Retorna un diccionario codigo -> precio_promedio con los precios
    de MercadoLibre en cache. Util para inyectar en la calculadora.

    Returns:
        Dict[str, float] con codigos de material y precios
    """
    cache = _cargar_cache()
    precios = {}
    for codigo, entrada in cache.items():
        if _cache_valido(entrada) and 'precio_promedio' in entrada:
            precios[codigo] = entrada['precio_promedio']
    return precios
