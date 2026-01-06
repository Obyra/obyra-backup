"""
Calculadora IA Mejorada - Integración con Inventario
Sistema de cálculo de presupuestos basado en los 11,480+ items del inventario.
Incluye coeficientes reales de construcción argentina y precios de mercado.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# COEFICIENTES DE CONSTRUCCIÓN POR M² - BASADOS EN DATOS REALES ARGENTINA
# ============================================================================

# Coeficientes de rendimiento por m² construido para cada etapa
# Fuentes: CAC, UOCRA, experiencia de obra argentina
COEFICIENTES_ETAPA = {
    'excavacion': {
        'nombre': 'Excavación y Movimiento de Suelos',
        'slug': 'excavacion',
        'orden': 1,
        'porcentaje_obra': 3.5,  # % del costo total de obra
        'coef_m2': {
            'Económica': {
                'materiales': 0.015,  # Factor multiplicador base
                'mano_obra_hs': 0.8,  # Horas hombre por m²
                'equipos_dias': 0.02,  # Días de equipo por m²
            },
            'Estándar': {
                'materiales': 0.018,
                'mano_obra_hs': 0.6,
                'equipos_dias': 0.015,
            },
            'Premium': {
                'materiales': 0.022,
                'mano_obra_hs': 0.5,
                'equipos_dias': 0.012,
            }
        },
        'items_principales': ['arena', 'piedra', 'ripio', 'tosca'],
    },
    'fundaciones': {
        'nombre': 'Fundaciones',
        'slug': 'fundaciones',
        'orden': 2,
        'porcentaje_obra': 8.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.12,
                'mano_obra_hs': 2.5,
                'equipos_dias': 0.04,
            },
            'Estándar': {
                'materiales': 0.15,
                'mano_obra_hs': 2.2,
                'equipos_dias': 0.035,
            },
            'Premium': {
                'materiales': 0.18,
                'mano_obra_hs': 2.0,
                'equipos_dias': 0.03,
            }
        },
        'items_principales': ['cemento', 'hierro', 'hormigón', 'encofrado'],
    },
    'estructura': {
        'nombre': 'Estructura',
        'slug': 'estructura',
        'orden': 3,
        'porcentaje_obra': 18.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.22,
                'mano_obra_hs': 4.5,
                'equipos_dias': 0.06,
            },
            'Estándar': {
                'materiales': 0.28,
                'mano_obra_hs': 4.0,
                'equipos_dias': 0.05,
            },
            'Premium': {
                'materiales': 0.35,
                'mano_obra_hs': 3.5,
                'equipos_dias': 0.045,
            }
        },
        'items_principales': ['hierro', 'cemento', 'hormigón', 'encofrado', 'columnas'],
    },
    'mamposteria': {
        'nombre': 'Mampostería',
        'slug': 'mamposteria',
        'orden': 4,
        'porcentaje_obra': 12.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.18,
                'mano_obra_hs': 3.5,
                'equipos_dias': 0.025,
            },
            'Estándar': {
                'materiales': 0.22,
                'mano_obra_hs': 3.2,
                'equipos_dias': 0.022,
            },
            'Premium': {
                'materiales': 0.28,
                'mano_obra_hs': 3.0,
                'equipos_dias': 0.02,
            }
        },
        'items_principales': ['ladrillo', 'bloque', 'mortero', 'cemento', 'cal'],
    },
    'techos': {
        'nombre': 'Techos e Impermeabilización',
        'slug': 'techos',
        'orden': 5,
        'porcentaje_obra': 10.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.15,
                'mano_obra_hs': 2.8,
                'equipos_dias': 0.035,
            },
            'Estándar': {
                'materiales': 0.20,
                'mano_obra_hs': 2.5,
                'equipos_dias': 0.03,
            },
            'Premium': {
                'materiales': 0.28,
                'mano_obra_hs': 2.2,
                'equipos_dias': 0.025,
            }
        },
        'items_principales': ['membrana', 'aislación', 'chapa', 'teja', 'viga'],
    },
    'instalaciones-electricas': {
        'nombre': 'Instalaciones Eléctricas',
        'slug': 'instalaciones-electricas',
        'orden': 6,
        'porcentaje_obra': 7.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.10,
                'mano_obra_hs': 2.0,
                'equipos_dias': 0.01,
            },
            'Estándar': {
                'materiales': 0.14,
                'mano_obra_hs': 2.5,
                'equipos_dias': 0.012,
            },
            'Premium': {
                'materiales': 0.20,
                'mano_obra_hs': 3.0,
                'equipos_dias': 0.015,
            }
        },
        'items_principales': ['cable', 'tablero', 'caja', 'interruptor', 'toma'],
    },
    'instalaciones-sanitarias': {
        'nombre': 'Instalaciones Sanitarias',
        'slug': 'instalaciones-sanitarias',
        'orden': 7,
        'porcentaje_obra': 6.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.08,
                'mano_obra_hs': 1.8,
                'equipos_dias': 0.01,
            },
            'Estándar': {
                'materiales': 0.12,
                'mano_obra_hs': 2.2,
                'equipos_dias': 0.012,
            },
            'Premium': {
                'materiales': 0.18,
                'mano_obra_hs': 2.8,
                'equipos_dias': 0.015,
            }
        },
        'items_principales': ['caño', 'conexión', 'válvula', 'grifería', 'sanitario'],
    },
    'instalaciones-gas': {
        'nombre': 'Instalaciones de Gas',
        'slug': 'instalaciones-gas',
        'orden': 8,
        'porcentaje_obra': 3.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.04,
                'mano_obra_hs': 0.8,
                'equipos_dias': 0.005,
            },
            'Estándar': {
                'materiales': 0.06,
                'mano_obra_hs': 1.0,
                'equipos_dias': 0.006,
            },
            'Premium': {
                'materiales': 0.08,
                'mano_obra_hs': 1.2,
                'equipos_dias': 0.008,
            }
        },
        'items_principales': ['caño', 'válvula', 'regulador', 'flexible', 'medidor'],
    },
    'revoque-grueso': {
        'nombre': 'Revoque Grueso',
        'slug': 'revoque-grueso',
        'orden': 9,
        'porcentaje_obra': 4.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.06,
                'mano_obra_hs': 1.5,
                'equipos_dias': 0.008,
            },
            'Estándar': {
                'materiales': 0.08,
                'mano_obra_hs': 1.3,
                'equipos_dias': 0.007,
            },
            'Premium': {
                'materiales': 0.10,
                'mano_obra_hs': 1.1,
                'equipos_dias': 0.006,
            }
        },
        'items_principales': ['cemento', 'cal', 'arena', 'hidrófugo'],
    },
    'revoque-fino': {
        'nombre': 'Revoque Fino',
        'slug': 'revoque-fino',
        'orden': 10,
        'porcentaje_obra': 3.5,
        'coef_m2': {
            'Económica': {
                'materiales': 0.05,
                'mano_obra_hs': 1.2,
                'equipos_dias': 0.005,
            },
            'Estándar': {
                'materiales': 0.07,
                'mano_obra_hs': 1.0,
                'equipos_dias': 0.004,
            },
            'Premium': {
                'materiales': 0.09,
                'mano_obra_hs': 0.9,
                'equipos_dias': 0.004,
            }
        },
        'items_principales': ['yeso', 'enduido', 'masilla', 'malla'],
    },
    'pisos': {
        'nombre': 'Pisos y Revestimientos',
        'slug': 'pisos',
        'orden': 11,
        'porcentaje_obra': 8.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.12,
                'mano_obra_hs': 2.0,
                'equipos_dias': 0.015,
            },
            'Estándar': {
                'materiales': 0.18,
                'mano_obra_hs': 2.5,
                'equipos_dias': 0.018,
            },
            'Premium': {
                'materiales': 0.28,
                'mano_obra_hs': 3.0,
                'equipos_dias': 0.022,
            }
        },
        'items_principales': ['cerámico', 'porcelanato', 'pegamento', 'pastina'],
    },
    'carpinteria': {
        'nombre': 'Carpintería y Aberturas',
        'slug': 'carpinteria',
        'orden': 12,
        'porcentaje_obra': 7.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.10,
                'mano_obra_hs': 1.5,
                'equipos_dias': 0.01,
            },
            'Estándar': {
                'materiales': 0.15,
                'mano_obra_hs': 2.0,
                'equipos_dias': 0.012,
            },
            'Premium': {
                'materiales': 0.25,
                'mano_obra_hs': 2.5,
                'equipos_dias': 0.015,
            }
        },
        'items_principales': ['puerta', 'ventana', 'marco', 'vidrio', 'herraje'],
    },
    'pintura': {
        'nombre': 'Pintura',
        'slug': 'pintura',
        'orden': 13,
        'porcentaje_obra': 4.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.06,
                'mano_obra_hs': 1.0,
                'equipos_dias': 0.005,
            },
            'Estándar': {
                'materiales': 0.08,
                'mano_obra_hs': 1.2,
                'equipos_dias': 0.006,
            },
            'Premium': {
                'materiales': 0.12,
                'mano_obra_hs': 1.5,
                'equipos_dias': 0.008,
            }
        },
        'items_principales': ['pintura', 'látex', 'esmalte', 'sellador', 'fijador'],
    },
    'herreria-de-obra': {
        'nombre': 'Herrería de Obra',
        'slug': 'herreria-de-obra',
        'orden': 14,
        'porcentaje_obra': 3.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.04,
                'mano_obra_hs': 0.8,
                'equipos_dias': 0.008,
            },
            'Estándar': {
                'materiales': 0.06,
                'mano_obra_hs': 1.0,
                'equipos_dias': 0.01,
            },
            'Premium': {
                'materiales': 0.10,
                'mano_obra_hs': 1.5,
                'equipos_dias': 0.015,
            }
        },
        'items_principales': ['reja', 'portón', 'baranda', 'perfil', 'hierro'],
    },
    'seguridad': {
        'nombre': 'Seguridad',
        'slug': 'seguridad',
        'orden': 15,
        'porcentaje_obra': 2.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.02,
                'mano_obra_hs': 0.4,
                'equipos_dias': 0.003,
            },
            'Estándar': {
                'materiales': 0.04,
                'mano_obra_hs': 0.6,
                'equipos_dias': 0.005,
            },
            'Premium': {
                'materiales': 0.08,
                'mano_obra_hs': 1.0,
                'equipos_dias': 0.01,
            }
        },
        'items_principales': ['extintor', 'detector', 'alarma', 'rociador', 'señalización'],
    },
    'instalaciones-complementarias': {
        'nombre': 'Instalaciones Complementarias',
        'slug': 'instalaciones-complementarias',
        'orden': 16,
        'porcentaje_obra': 3.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.03,
                'mano_obra_hs': 0.5,
                'equipos_dias': 0.005,
            },
            'Estándar': {
                'materiales': 0.06,
                'mano_obra_hs': 0.8,
                'equipos_dias': 0.008,
            },
            'Premium': {
                'materiales': 0.12,
                'mano_obra_hs': 1.5,
                'equipos_dias': 0.015,
            }
        },
        'items_principales': ['aire', 'calefacción', 'split', 'conducto', 'termostato'],
    },
    'limpieza-final': {
        'nombre': 'Limpieza Final',
        'slug': 'limpieza-final',
        'orden': 17,
        'porcentaje_obra': 1.0,
        'coef_m2': {
            'Económica': {
                'materiales': 0.01,
                'mano_obra_hs': 0.3,
                'equipos_dias': 0.002,
            },
            'Estándar': {
                'materiales': 0.015,
                'mano_obra_hs': 0.4,
                'equipos_dias': 0.003,
            },
            'Premium': {
                'materiales': 0.02,
                'mano_obra_hs': 0.5,
                'equipos_dias': 0.005,
            }
        },
        'items_principales': ['limpieza', 'desinfección', 'protección', 'retiro'],
    },
}

# Mapeo de prefijos de código a slugs de etapa
PREFIJO_A_ETAPA = {
    'EXC': 'excavacion',
    'FUN': 'fundaciones',
    'EST': 'estructura',
    'MAM': 'mamposteria',
    'TEC': 'techos',
    'ELE': 'instalaciones-electricas',
    'SAN': 'instalaciones-sanitarias',
    'GAS': 'instalaciones-gas',
    'RGR': 'revoque-grueso',
    'RFI': 'revoque-fino',
    'PIS': 'pisos',
    'CAR': 'carpinteria',
    'PIN': 'pintura',
    'HER': 'herreria-de-obra',
    'SEG': 'seguridad',
    'COM': 'instalaciones-complementarias',
    'LIM': 'limpieza-final',
}

# Precios de mano de obra por hora (en ARS) - Referencia UOCRA 2025
PRECIOS_MANO_OBRA = {
    'oficial': 3500,      # Oficial especializado
    'medio_oficial': 2800, # Medio oficial
    'ayudante': 2200,     # Ayudante
    'promedio': 2800,     # Promedio ponderado
}

# Precios de equipos por día (en ARS) - Valores por defecto
PRECIOS_EQUIPOS = {
    'basico': 15000,      # Herramientas básicas
    'intermedio': 35000,  # Equipos medianos
    'pesado': 85000,      # Maquinaria pesada
    'promedio': 28000,    # Promedio
}


def obtener_equipos_leiten_por_etapa(etapa_slug: str, limite: int = 10) -> List[Dict[str, Any]]:
    """
    Obtiene equipos de Leiten para una etapa específica.

    Args:
        etapa_slug: Slug de la etapa de construcción
        limite: Máximo de equipos a retornar

    Returns:
        Lista de equipos con precios de alquiler/venta
    """
    try:
        from models.equipment import EquipoProveedor

        equipos = EquipoProveedor.query.filter(
            EquipoProveedor.activo == True,
            EquipoProveedor.proveedor == 'leiten',
            EquipoProveedor.etapa_construccion == etapa_slug
        ).limit(limite).all()

        return [e.to_dict() for e in equipos]

    except Exception as e:
        logger.warning(f"Error obteniendo equipos Leiten: {e}")
        return []


def calcular_costo_equipos_leiten(
    etapa_slug: str,
    dias_estimados: float,
    tipo_cambio_usd: float = 1200.0
) -> Dict[str, Any]:
    """
    Calcula el costo de equipos usando precios reales de Leiten.

    Args:
        etapa_slug: Slug de la etapa
        dias_estimados: Días de uso estimado
        tipo_cambio_usd: Tipo de cambio

    Returns:
        Diccionario con costos de equipos
    """
    equipos = obtener_equipos_leiten_por_etapa(etapa_slug, limite=5)

    if not equipos:
        # Si no hay equipos Leiten, usar valores por defecto
        return {
            'fuente': 'default',
            'equipos': [],
            'costo_alquiler_usd': dias_estimados * (PRECIOS_EQUIPOS['promedio'] / tipo_cambio_usd) / 28 * dias_estimados,
            'costo_alquiler_ars': dias_estimados * PRECIOS_EQUIPOS['promedio'] / 28 * dias_estimados,
        }

    # Calcular costo basado en equipos Leiten
    total_alquiler_usd = 0
    equipos_detalle = []

    for equipo in equipos:
        if equipo.get('precio_alquiler_usd'):
            # Precio por 28 días, calcular proporción
            precio_diario = equipo['precio_alquiler_usd'] / 28
            costo_equipo = precio_diario * dias_estimados

            total_alquiler_usd += costo_equipo

            equipos_detalle.append({
                'nombre': equipo['nombre'],
                'marca': equipo.get('marca'),
                'precio_alquiler_28d_usd': equipo['precio_alquiler_usd'],
                'precio_diario_usd': round(precio_diario, 2),
                'dias_uso': dias_estimados,
                'costo_total_usd': round(costo_equipo, 2),
            })

    # Si no hay equipos con precio de alquiler, usar venta como referencia
    if total_alquiler_usd == 0:
        for equipo in equipos:
            if equipo.get('precio_venta_usd'):
                # Estimar alquiler como 5% del valor de venta mensual
                precio_mensual_estimado = equipo['precio_venta_usd'] * 0.05
                precio_diario = precio_mensual_estimado / 28
                costo_equipo = precio_diario * dias_estimados

                total_alquiler_usd += costo_equipo

                equipos_detalle.append({
                    'nombre': equipo['nombre'],
                    'marca': equipo.get('marca'),
                    'precio_venta_usd': equipo['precio_venta_usd'],
                    'precio_diario_estimado_usd': round(precio_diario, 2),
                    'dias_uso': dias_estimados,
                    'costo_total_usd': round(costo_equipo, 2),
                    'nota': 'Precio estimado basado en valor de venta'
                })

    return {
        'fuente': 'leiten',
        'equipos': equipos_detalle,
        'cantidad_equipos': len(equipos_detalle),
        'costo_alquiler_usd': round(total_alquiler_usd, 2),
        'costo_alquiler_ars': round(total_alquiler_usd * tipo_cambio_usd, 2),
    }


def obtener_items_etapa_desde_bd(
    etapa_slug: str,
    tipo_construccion: str = 'Estándar',
    org_id: int = 2,
    limite: int = 50
) -> List[Dict[str, Any]]:
    """
    Obtiene los items de inventario para una etapa específica.

    Args:
        etapa_slug: Slug de la etapa (ej: 'excavacion', 'fundaciones')
        tipo_construccion: 'Económica', 'Estándar' o 'Premium'
        org_id: ID de la organización
        limite: Máximo de items a retornar

    Returns:
        Lista de items con sus datos
    """
    from flask import current_app
    from models.inventory import ItemInventario
    from extensions import db

    # Obtener prefijo de código para la etapa
    prefijo = None
    for pref, slug in PREFIJO_A_ETAPA.items():
        if slug == etapa_slug:
            prefijo = pref
            break

    if not prefijo:
        logger.warning(f"No se encontró prefijo para etapa: {etapa_slug}")
        return []

    # Determinar campo de filtro según tipo de construcción
    tipo_norm = tipo_construccion.lower().replace('á', 'a').replace('é', 'e')

    try:
        query = ItemInventario.query.filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.codigo.like(f'{prefijo}-%'),
            ItemInventario.activo == True
        )

        # Filtrar por tipo de construcción
        if 'econ' in tipo_norm:
            query = query.filter(ItemInventario.aplica_economica == True)
        elif 'prem' in tipo_norm:
            query = query.filter(ItemInventario.aplica_premium == True)
        else:
            query = query.filter(ItemInventario.aplica_estandar == True)

        items = query.limit(limite).all()

        resultado = []
        for item in items:
            # Extraer precio USD de descripción si existe
            precio_usd = None
            if item.descripcion and 'USD' in item.descripcion:
                try:
                    import re
                    match = re.search(r'\$?([\d.]+)', item.descripcion)
                    if match:
                        precio_usd = float(match.group(1))
                except:
                    pass

            resultado.append({
                'id': item.id,
                'codigo': item.codigo,
                'nombre': item.nombre,
                'unidad': item.unidad,
                'precio_usd': precio_usd,
                'categoria_id': item.categoria_id,
            })

        return resultado

    except Exception as e:
        logger.error(f"Error obteniendo items de BD: {e}")
        return []


def contar_items_etapa(etapa_slug: str, tipo_construccion: str = 'Estándar', org_id: int = 2) -> Dict[str, int]:
    """
    Cuenta los items disponibles para una etapa.
    """
    from models.inventory import ItemInventario
    from extensions import db

    prefijo = None
    for pref, slug in PREFIJO_A_ETAPA.items():
        if slug == etapa_slug:
            prefijo = pref
            break

    if not prefijo:
        return {'total': 0, 'con_precio': 0}

    tipo_norm = tipo_construccion.lower().replace('á', 'a').replace('é', 'e')

    try:
        query = ItemInventario.query.filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.codigo.like(f'{prefijo}-%'),
            ItemInventario.activo == True
        )

        if 'econ' in tipo_norm:
            query = query.filter(ItemInventario.aplica_economica == True)
        elif 'prem' in tipo_norm:
            query = query.filter(ItemInventario.aplica_premium == True)
        else:
            query = query.filter(ItemInventario.aplica_estandar == True)

        total = query.count()
        con_precio = query.filter(ItemInventario.descripcion.like('%USD%')).count()

        return {'total': total, 'con_precio': con_precio}

    except Exception as e:
        logger.error(f"Error contando items: {e}")
        return {'total': 0, 'con_precio': 0}


def calcular_etapa_mejorada(
    etapa_slug: str,
    metros_cuadrados: float,
    tipo_construccion: str = 'Estándar',
    org_id: int = 2,
    tipo_cambio_usd: float = 1200.0,
    incluir_items_detalle: bool = False
) -> Dict[str, Any]:
    """
    Calcula el presupuesto para una etapa usando los items del inventario.

    Args:
        etapa_slug: Slug de la etapa
        metros_cuadrados: Superficie a calcular
        tipo_construccion: Tipo de construcción
        org_id: ID organización
        tipo_cambio_usd: Tipo de cambio USD a ARS
        incluir_items_detalle: Si incluir lista detallada de items

    Returns:
        Diccionario con el cálculo de la etapa
    """
    config_etapa = COEFICIENTES_ETAPA.get(etapa_slug)
    if not config_etapa:
        return {
            'error': f'Etapa no encontrada: {etapa_slug}',
            'etapa_slug': etapa_slug,
        }

    # Normalizar tipo de construcción
    tipo_norm = tipo_construccion
    tipo_key = tipo_construccion
    if 'econ' in tipo_construccion.lower():
        tipo_key = 'Económica'
    elif 'prem' in tipo_construccion.lower():
        tipo_key = 'Premium'
    else:
        tipo_key = 'Estándar'

    coef = config_etapa['coef_m2'].get(tipo_key, config_etapa['coef_m2']['Estándar'])

    # Obtener items del inventario
    items_bd = obtener_items_etapa_desde_bd(etapa_slug, tipo_key, org_id, limite=100)
    conteo = contar_items_etapa(etapa_slug, tipo_key, org_id)

    # Calcular costos base usando el porcentaje de obra de la etapa
    # El costo total de construcción en Argentina ronda USD 800-1500/m² según tipo
    # Usamos el porcentaje de cada etapa para distribuir ese costo

    # Costo base por m² según tipo de construcción (en USD)
    COSTO_M2_BASE = {
        'Económica': 650,
        'Estándar': 950,
        'Premium': 1400,
    }

    costo_m2_total = COSTO_M2_BASE.get(tipo_key, 950)

    # El costo de materiales es ~60% del costo total de la etapa
    porcentaje_etapa = config_etapa['porcentaje_obra'] / 100
    costo_etapa_usd = metros_cuadrados * costo_m2_total * porcentaje_etapa
    costo_materiales_base = costo_etapa_usd * 0.60 * tipo_cambio_usd  # 60% materiales

    # Si hay items con precio en el inventario, ajustar según datos reales
    items_con_precio = [i for i in items_bd if i.get('precio_usd')]
    if items_con_precio and len(items_con_precio) > 5:
        # Calcular costo estimado basado en precios reales del inventario
        precio_promedio_usd = sum(i['precio_usd'] for i in items_con_precio) / len(items_con_precio)
        # Estimamos que se usan ~20 items promedio por etapa
        items_estimados = min(20, conteo['total'] * 0.1)  # 10% de items disponibles
        costo_materiales_estimado = precio_promedio_usd * items_estimados * tipo_cambio_usd
        # Usar el mayor entre el cálculo base y el estimado
        costo_materiales_base = max(costo_materiales_base * 0.8, costo_materiales_estimado)

    # Mano de obra
    horas_totales = metros_cuadrados * coef['mano_obra_hs']
    costo_mano_obra = horas_totales * PRECIOS_MANO_OBRA['promedio']

    # Equipos - Intentar usar precios de Leiten
    dias_equipo = metros_cuadrados * coef['equipos_dias']
    dias_equipo = max(dias_equipo, 1)  # Mínimo 1 día

    # Obtener costos de equipos de Leiten si están disponibles
    equipos_leiten = calcular_costo_equipos_leiten(etapa_slug, dias_equipo, tipo_cambio_usd)

    if equipos_leiten['fuente'] == 'leiten' and equipos_leiten['costo_alquiler_ars'] > 0:
        costo_equipos = equipos_leiten['costo_alquiler_ars']
        equipos_detalle = equipos_leiten['equipos']
        fuente_equipos = 'leiten'
    else:
        costo_equipos = dias_equipo * PRECIOS_EQUIPOS['promedio']
        equipos_detalle = []
        fuente_equipos = 'estimado'

    # Subtotal
    subtotal_ars = costo_materiales_base + costo_mano_obra + costo_equipos
    subtotal_usd = subtotal_ars / tipo_cambio_usd

    resultado = {
        'etapa_slug': etapa_slug,
        'etapa_nombre': config_etapa['nombre'],
        'orden': config_etapa['orden'],
        'metros_cuadrados': metros_cuadrados,
        'tipo_construccion': tipo_key,
        'porcentaje_obra': config_etapa['porcentaje_obra'],

        # Desglose
        'materiales': {
            'items_disponibles': conteo['total'],
            'items_con_precio': conteo['con_precio'],
            'costo_ars': round(costo_materiales_base, 2),
            'costo_usd': round(costo_materiales_base / tipo_cambio_usd, 2),
        },
        'mano_obra': {
            'horas_estimadas': round(horas_totales, 1),
            'costo_hora': PRECIOS_MANO_OBRA['promedio'],
            'costo_ars': round(costo_mano_obra, 2),
            'costo_usd': round(costo_mano_obra / tipo_cambio_usd, 2),
        },
        'equipos': {
            'dias_estimados': round(dias_equipo, 1),
            'fuente': fuente_equipos,
            'costo_ars': round(costo_equipos, 2),
            'costo_usd': round(costo_equipos / tipo_cambio_usd, 2),
            'detalle_leiten': equipos_detalle if fuente_equipos == 'leiten' else None,
        },

        # Totales
        'subtotal_ars': round(subtotal_ars, 2),
        'subtotal_usd': round(subtotal_usd, 2),

        'tipo_cambio': tipo_cambio_usd,
        'fecha_calculo': datetime.now().isoformat(),
    }

    if incluir_items_detalle:
        resultado['items_detalle'] = items_bd[:20]  # Máximo 20 items de ejemplo

    return resultado


def calcular_presupuesto_completo(
    metros_cuadrados: float,
    tipo_construccion: str = 'Estándar',
    etapas_seleccionadas: Optional[List[str]] = None,
    org_id: int = 2,
    tipo_cambio_usd: float = 1200.0
) -> Dict[str, Any]:
    """
    Calcula el presupuesto completo para todas las etapas seleccionadas.

    Args:
        metros_cuadrados: Superficie total
        tipo_construccion: Tipo de construcción
        etapas_seleccionadas: Lista de slugs de etapas (None = todas)
        org_id: ID organización
        tipo_cambio_usd: Tipo de cambio

    Returns:
        Presupuesto completo con todas las etapas
    """
    if etapas_seleccionadas is None:
        etapas_seleccionadas = list(COEFICIENTES_ETAPA.keys())

    etapas_resultado = []
    total_materiales_ars = 0
    total_mano_obra_ars = 0
    total_equipos_ars = 0
    total_items = 0

    for etapa_slug in etapas_seleccionadas:
        calculo = calcular_etapa_mejorada(
            etapa_slug=etapa_slug,
            metros_cuadrados=metros_cuadrados,
            tipo_construccion=tipo_construccion,
            org_id=org_id,
            tipo_cambio_usd=tipo_cambio_usd,
            incluir_items_detalle=False
        )

        if 'error' not in calculo:
            etapas_resultado.append(calculo)
            total_materiales_ars += calculo['materiales']['costo_ars']
            total_mano_obra_ars += calculo['mano_obra']['costo_ars']
            total_equipos_ars += calculo['equipos']['costo_ars']
            total_items += calculo['materiales']['items_disponibles']

    # Ordenar por orden de etapa
    etapas_resultado.sort(key=lambda x: x.get('orden', 99))

    subtotal_ars = total_materiales_ars + total_mano_obra_ars + total_equipos_ars

    # Gastos generales y beneficio (típico en construcción argentina)
    gastos_generales = subtotal_ars * 0.08  # 8%
    beneficio = subtotal_ars * 0.10  # 10%
    iva = (subtotal_ars + gastos_generales + beneficio) * 0.21  # 21%

    total_ars = subtotal_ars + gastos_generales + beneficio + iva
    total_usd = total_ars / tipo_cambio_usd

    # Costo por m²
    costo_m2_ars = total_ars / metros_cuadrados if metros_cuadrados > 0 else 0
    costo_m2_usd = total_usd / metros_cuadrados if metros_cuadrados > 0 else 0

    return {
        'resumen': {
            'metros_cuadrados': metros_cuadrados,
            'tipo_construccion': tipo_construccion,
            'cantidad_etapas': len(etapas_resultado),
            'total_items_inventario': total_items,
            'fecha_calculo': datetime.now().isoformat(),
        },
        'etapas': etapas_resultado,
        'totales': {
            'materiales': {
                'ars': round(total_materiales_ars, 2),
                'usd': round(total_materiales_ars / tipo_cambio_usd, 2),
            },
            'mano_obra': {
                'ars': round(total_mano_obra_ars, 2),
                'usd': round(total_mano_obra_ars / tipo_cambio_usd, 2),
            },
            'equipos': {
                'ars': round(total_equipos_ars, 2),
                'usd': round(total_equipos_ars / tipo_cambio_usd, 2),
            },
            'subtotal': {
                'ars': round(subtotal_ars, 2),
                'usd': round(subtotal_ars / tipo_cambio_usd, 2),
            },
            'gastos_generales': {
                'porcentaje': 8,
                'ars': round(gastos_generales, 2),
                'usd': round(gastos_generales / tipo_cambio_usd, 2),
            },
            'beneficio': {
                'porcentaje': 10,
                'ars': round(beneficio, 2),
                'usd': round(beneficio / tipo_cambio_usd, 2),
            },
            'iva': {
                'porcentaje': 21,
                'ars': round(iva, 2),
                'usd': round(iva / tipo_cambio_usd, 2),
            },
            'total': {
                'ars': round(total_ars, 2),
                'usd': round(total_usd, 2),
            },
            'costo_m2': {
                'ars': round(costo_m2_ars, 2),
                'usd': round(costo_m2_usd, 2),
            },
        },
        'tipo_cambio_usado': tipo_cambio_usd,
        'notas': [
            f'Cálculo basado en {total_items} items del inventario',
            'Precios de mano de obra según convenio UOCRA 2025',
            'Incluye 8% gastos generales y 10% beneficio',
            'IVA 21% sobre subtotal + gastos + beneficio',
        ],
    }


def obtener_resumen_etapas() -> List[Dict[str, Any]]:
    """
    Obtiene un resumen de todas las etapas disponibles.
    """
    resumen = []
    for slug, config in COEFICIENTES_ETAPA.items():
        conteo = contar_items_etapa(slug, 'Estándar', 2)
        resumen.append({
            'slug': slug,
            'nombre': config['nombre'],
            'orden': config['orden'],
            'porcentaje_obra': config['porcentaje_obra'],
            'items_disponibles': conteo['total'],
            'items_con_precio': conteo['con_precio'],
        })

    resumen.sort(key=lambda x: x['orden'])
    return resumen
