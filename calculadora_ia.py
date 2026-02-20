"""
Calculadora IA de Presupuestos de Construcción
Sistema inteligente para analizar planos y calcular materiales automáticamente
"""

import os
import base64
import json
import logging
import math
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, Optional
from unicodedata import normalize

# --- OpenAI opcional (se usa sólo si está instalada y hay API key) ---
try:
    from openai import OpenAI  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - se ejecuta sólo sin dependencia
    OpenAI = None  # type: ignore[assignment]
    client = None  # type: ignore[assignment]
    OPENAI_AVAILABLE = False
else:
    _openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if _openai_api_key:
        client = OpenAI(api_key=_openai_api_key)
        OPENAI_AVAILABLE = True
    else:
        client = None
        OPENAI_AVAILABLE = False
        logging.warning(
            "OPENAI_API_KEY no configurada; la calculadora IA se deshabilitará hasta definirla."
        )

# Contexto CAC y tipo de cambio (requeridos por el sistema de etapas)
from services.cac.cac_service import CACContext, get_cac_context
from services.exchange.base import ExchangeRateSnapshot

# ----------------- Coeficientes y constantes -----------------

# Coeficientes de construcción expandidos por tipo y m² - Estilo Togal.AI
COEFICIENTES_CONSTRUCCION = {
    "Económica": {
        # Materiales estructurales
        "ladrillos": 55,           # unidades por m²
        "cemento": 0.25,           # bolsas por m²
        "cal": 3,                  # kg por m²
        "arena": 0.03,             # m³ por m²
        "piedra": 0.02,            # m³ por m²
        "hierro_8": 2.5,           # kg por m²
        "hierro_10": 1.8,          # kg por m²
        "hierro_12": 1.2,          # kg por m²

        # Nuevos materiales de construcción
        "ceramicos": 1.05,         # m² por m² (con desperdicio)
        "porcelanato": 0,          # No incluido en económica
        "azulejos": 0.5,           # m² por m² (solo baños)
        "cables_electricos": 8,    # metros por m²
        "caños_agua": 4,           # metros por m²
        "caños_cloacas": 2,        # metros por m²
        "chapas": 0.15,            # m² por m² (techos)
        "tejas": 0.12,             # m² por m² (alt. a chapas)
        "aislacion_termica": 0.8,  # m² por m²
        "yeso": 0.5,               # kg por m² (terminaciones)
        "madera_estructural": 0.05,# m³ por m²
        "vidrios": 0.08,           # m² por m² (ventanas)
        "aberturas_metal": 0.06,   # m² por m² (puertas/ventanas)

        # Impermeabilización y terminaciones
        "membrana": 0.8,           # m² por m²
        "pintura": 0.1,            # litros por m²
        "pintura_exterior": 0.08,  # litros por m²
        "sellador": 0.02,          # litros por m²

        "factor_precio": 1.0
    },
    "Estándar": {
        # Materiales estructurales
        "ladrillos": 60,
        "cemento": 0.3,
        "cal": 4,
        "arena": 0.035,
        "piedra": 0.025,
        "hierro_8": 3.5,
        "hierro_10": 2.2,
        "hierro_12": 1.5,

        # Materiales mejorados
        "ceramicos": 1.1,
        "porcelanato": 0.3,
        "azulejos": 0.8,
        "cables_electricos": 12,
        "caños_agua": 6,
        "caños_cloacas": 3,
        "chapas": 0.2,
        "tejas": 0.15,
        "aislacion_termica": 1.2,
        "yeso": 0.8,
        "madera_estructural": 0.08,
        "vidrios": 0.12,
        "aberturas_metal": 0.1,

        # Terminaciones estándar
        "membrana": 1.1,
        "pintura": 0.13,
        "pintura_exterior": 0.1,
        "sellador": 0.03,

        # Factor basado en investigación mercado 2025: US$1600 vs US$1300 = 1.23x
        "factor_precio": 1.23
    },
    "Premium": {
        # Materiales estructurales premium
        "ladrillos": 65,
        "cemento": 0.35,
        "cal": 5,
        "arena": 0.04,
        "piedra": 0.03,
        "hierro_8": 4,
        "hierro_10": 2.8,
        "hierro_12": 2,

        # Materiales premium
        "ceramicos": 0.5,
        "porcelanato": 1.2,
        "azulejos": 1.2,
        "cables_electricos": 15,
        "caños_agua": 8,
        "caños_cloacas": 4,
        "chapas": 0.1,
        "tejas": 0.25,
        "aislacion_termica": 1.8,
        "yeso": 1.2,
        "madera_estructural": 0.12,
        "vidrios": 0.18,
        "aberturas_metal": 0.15,

        # Terminaciones premium
        "membrana": 1.5,
        "pintura": 0.18,
        "pintura_exterior": 0.15,
        "sellador": 0.05,

        # Factor basado en investigación mercado 2025: US$2000 vs US$1300 = 1.54x
        "factor_precio": 1.54
    }
}

DECIMAL_ZERO = Decimal('0')
CURRENCY_QUANT = Decimal('0.01')
QUANTITY_QUANT = Decimal('0.001')
_CAC_CONTEXT_CACHE: Dict[str, Any] = {'context': None, 'timestamp': None}

# ----------------- Helpers numéricos -----------------

def _to_decimal(value: Any, default: str = '0') -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _quantize_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)


def _quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_QUANT, rounding=ROUND_HALF_UP)


def _get_cac_context_cached() -> CACContext:
    """Obtiene y cachea el contexto CAC vigente."""
    now = datetime.utcnow()
    cache_context = _CAC_CONTEXT_CACHE.get('context')
    cache_timestamp = _CAC_CONTEXT_CACHE.get('timestamp')

    if cache_context and cache_timestamp and (now - cache_timestamp).total_seconds() < 3600:
        return cache_context

    context = get_cac_context()
    _CAC_CONTEXT_CACHE['context'] = context
    _CAC_CONTEXT_CACHE['timestamp'] = now
    return context


def _convert_currency(amount: Decimal, currency: str, fx_rate: Optional[Decimal]) -> Decimal:
    currency = (currency or 'ARS').upper()
    if currency == 'USD':
        if not fx_rate or fx_rate <= DECIMAL_ZERO:
            raise ValueError('Tipo de cambio inválido para la conversión a USD.')
        return _quantize_currency(amount / fx_rate)
    return _quantize_currency(amount)

# ----------------- Sistema por etapas (materiales / equipos / herramientas) -----------------

ETAPAS_CONSTRUCCION = {
    "Económica": {
        "cimentacion_estructura": {
            "materiales_etapa": ["cemento", "hierro_8", "hierro_10", "arena", "piedra"],
            "maquinaria": {
                "hormigonera_trompo_manual": {"cantidad": 1, "dias": 25},
                "carretilla_manual": {"cantidad": 4, "dias": 30},
                "cortadora_hierro_manual": {"cantidad": 1, "dias": 20},
                "dobladora_hierro_manual": {"cantidad": 1, "dias": 20},
                "andamios_tubulares": {"cantidad": 15, "dias": 35}
            },
            "herramientas": {
                "palas_punta": {"cantidad": 6, "dias": 25},
                "palas_ancha": {"cantidad": 4, "dias": 25},
                "picos": {"cantidad": 4, "dias": 25},
                "baldes_goma": {"cantidad": 12, "dias": 30},
                "mangueras": {"cantidad": 2, "dias": 30},
                "nivel_burbuja_60cm": {"cantidad": 3, "dias": 35},
                "plomada": {"cantidad": 2, "dias": 35},
                "martillo_goma": {"cantidad": 3, "dias": 30},
                "sierra_manual_hierro": {"cantidad": 2, "dias": 20}
            }
        },
        "albanileria": {
            "materiales_etapa": ["ladrillos", "cal", "arena", "cemento"],
            "maquinaria": {
                "mezcladora_manual_80L": {"cantidad": 1, "dias": 35},
                "escalera_tijera": {"cantidad": 2, "dias": 30},
                "carretilla_albanil": {"cantidad": 3, "dias": 35}
            },
            "herramientas": {
                "llanas_acero_inox": {"cantidad": 6, "dias": 35},
                "fratacho_madera": {"cantidad": 6, "dias": 35},
                "regla_aluminio_2m": {"cantidad": 3, "dias": 35},
                "escuadra_albanil": {"cantidad": 2, "dias": 35},
                "hilo_nylon": {"cantidad": 15, "dias": 35},
                "nivel_burbuja_40cm": {"cantidad": 4, "dias": 35},
                "balde_goma_15L": {"cantidad": 8, "dias": 35},
                "cortafrio": {"cantidad": 3, "dias": 30},
                "cucharas_albanil": {"cantidad": 4, "dias": 35},
                "esponja_goma": {"cantidad": 10, "dias": 30}
            }
        },
        "terminaciones": {
            "materiales_etapa": ["pintura", "yeso", "ceramicos", "azulejos"],
            "maquinaria": {
                "escalera_extensible": {"cantidad": 1, "dias": 25},
                "caballete_trabajo": {"cantidad": 4, "dias": 25}
            },
            "herramientas": {
                "rodillos_pintura_18cm": {"cantidad": 8, "dias": 25},
                "rodillos_pintura_10cm": {"cantidad": 6, "dias": 25},
                "pinceles_1_pulgada": {"cantidad": 6, "dias": 25},
                "pinceles_2_pulgadas": {"cantidad": 4, "dias": 25},
                "pinceles_3_pulgadas": {"cantidad": 3, "dias": 25},
                "pinceles_detalle": {"cantidad": 8, "dias": 25},
                "bandejas_pintura": {"cantidad": 6, "dias": 25},
                "espatulas_masilla": {"cantidad": 4, "dias": 20},
                "llana_dentada_6mm": {"cantidad": 2, "dias": 15},
                "llana_dentada_8mm": {"cantidad": 2, "dias": 15},
                "cortadora_ceramico_manual": {"cantidad": 1, "dias": 12},
                "regla_cortaceramico": {"cantidad": 1, "dias": 12},
                "esponja_limpieza": {"cantidad": 12, "dias": 15},
                "trapos_limpieza": {"cantidad": 20, "dias": 25},
                "baldes_limpieza": {"cantidad": 6, "dias": 25},
                "cepillos_limpieza": {"cantidad": 4, "dias": 20},
                "nivel_pequeno_20cm": {"cantidad": 4, "dias": 20}
            }
        }
    },
    "Estándar": {
        "cimentacion_estructura": {
            "materiales_etapa": ["cemento", "hierro_8", "hierro_10", "hierro_12", "arena", "piedra"],
            "maquinaria": {
                "minicargadora": {"cantidad": 1, "dias": 15},
                "hormigonera_electrica_300L": {"cantidad": 1, "dias": 25},
                "cortadora_hierro_electrica": {"cantidad": 1, "dias": 20},
                "dobladora_hierro_electrica": {"cantidad": 1, "dias": 20},
                "atadora_hierro_electrica": {"cantidad": 1, "dias": 15},
                "andamios_modulares": {"cantidad": 20, "dias": 35},
                "vibrador_hormigon_electrico": {"cantidad": 2, "dias": 20}
            },
            "herramientas": {
                "taladro_percutor": {"cantidad": 2, "dias": 25},
                "amoladora_grande": {"cantidad": 2, "dias": 30},
                "nivel_laser_basico": {"cantidad": 1, "dias": 35},
                "carretilla_motorizada": {"cantidad": 2, "dias": 30},
                "sierra_circular": {"cantidad": 1, "dias": 20},
                "soldadora_inverter": {"cantidad": 1, "dias": 15},
                "compresor_aire": {"cantidad": 1, "dias": 25}
            }
        },
        "albanileria": {
            "materiales_etapa": ["ladrillos", "cal", "arena", "cemento"],
            "maquinaria": {
                "mezcladora_electrica_200L": {"cantidad": 1, "dias": 30},
                "cortadora_ladrillo_electrica": {"cantidad": 1, "dias": 25},
                "elevador_materiales_electrico": {"cantidad": 1, "dias": 30},
                "bomba_mortero_electrica": {"cantidad": 1, "dias": 20},
                "andamios_electricos": {"cantidad": 25, "dias": 35}
            },
            "herramientas": {
                "taladro_profesional": {"cantidad": 3, "dias": 30},
                "amoladora_albanil": {"cantidad": 3, "dias": 30},
                "sierra_sable": {"cantidad": 2, "dias": 25},
                "nivel_laser_rotativo": {"cantidad": 1, "dias": 35},
                "pistola_calor": {"cantidad": 1, "dias": 20},
                "martillo_demoledor": {"cantidad": 1, "dias": 15},
                "aspiradora_industrial": {"cantidad": 1, "dias": 25}
            }
        },
        "terminaciones": {
            "materiales_etapa": ["pintura", "pintura_exterior", "yeso", "ceramicos", "azulejos"],
            "maquinaria": {
                "compresora_pintura": {"cantidad": 1, "dias": 20},
                "lijadora_pared_electrica": {"cantidad": 1, "dias": 15},
                "cortadora_ceramicos_electrica": {"cantidad": 1, "dias": 15},
                "proyectora_yeso": {"cantidad": 1, "dias": 12},
                "pulidora_pisos": {"cantidad": 1, "dias": 10}
            },
            "herramientas": {
                "pistola_pintura_electrica": {"cantidad": 2, "dias": 20},
                "rodillos_pintura_23cm": {"cantidad": 10, "dias": 20},
                "rodillos_pintura_15cm": {"cantidad": 8, "dias": 20},
                "rodillos_textura": {"cantidad": 4, "dias": 15},
                "pinceles_profesionales_1": {"cantidad": 8, "dias": 20},
                "pinceles_profesionales_2": {"cantidad": 6, "dias": 20},
                "pinceles_profesionales_3": {"cantidad": 4, "dias": 20},
                "pinceles_angulares": {"cantidad": 6, "dias": 18},
                "bandejas_pintura_profesional": {"cantidad": 8, "dias": 20},
                "lijadora_orbital": {"cantidad": 2, "dias": 15},
                "taladro_mezclador": {"cantidad": 1, "dias": 15},
                "nivel_laser_pequeno": {"cantidad": 2, "dias": 20},
                "aspiradora_seco_humedo": {"cantidad": 1, "dias": 20},
                "esmeril_angular": {"cantidad": 1, "dias": 15},
                "caladora_profesional": {"cantidad": 1, "dias": 10},
                "esponjas_limpieza_prof": {"cantidad": 15, "dias": 18},
                "trapos_microfibra": {"cantidad": 25, "dias": 20},
                "baldes_profesionales": {"cantidad": 8, "dias": 20},
                "cepillos_limpieza_prof": {"cantidad": 6, "dias": 18}
            }
        }
    },
    "Premium": {
        "cimentacion_estructura": {
            "materiales_etapa": ["cemento", "hierro_8", "hierro_10", "hierro_12", "arena", "piedra"],
            "maquinaria": {
                "excavadora_hidraulica_CAT": {"cantidad": 1, "dias": 8},
                "bomba_hormigon_autopropulsada": {"cantidad": 1, "dias": 10},
                "grua_torre_computarizada": {"cantidad": 1, "dias": 40},
                "planta_hormigon_automatica": {"cantidad": 1, "dias": 12},
                "montacargas_telescopico": {"cantidad": 2, "dias": 35},
                "compactadora_vibratoria": {"cantidad": 1, "dias": 8},
                "cortadora_hierro_CNC": {"cantidad": 1, "dias": 15},
                "dobladora_hierro_automatica": {"cantidad": 1, "dias": 15},
                "atadora_hierro_robotica": {"cantidad": 1, "dias": 12}
            },
            "herramientas": {
                "estacion_total_GPS": {"cantidad": 1, "dias": 20},
                "vibrador_alta_frecuencia": {"cantidad": 3, "dias": 15},
                "martillo_hidraulico": {"cantidad": 1, "dias": 10},
                "nivel_laser_3D": {"cantidad": 2, "dias": 20},
                "drone_supervision": {"cantidad": 1, "dias": 40},
                "soldadora_robotica": {"cantidad": 1, "dias": 15}
            }
        },
        "albanileria": {
            "materiales_etapa": ["ladrillos", "cal", "arena", "cemento"],
            "maquinaria": {
                "robot_albanil_SAM": {"cantidad": 1, "dias": 20},
                "montacargas_materiales": {"cantidad": 2, "dias": 30},
                "mezcladora_robotizada_500L": {"cantidad": 1, "dias": 25},
                "bomba_mortero_automatica": {"cantidad": 1, "dias": 15},
                "cortadora_laser_materiales": {"cantidad": 1, "dias": 12},
                "elevador_tijera_autopropulsado": {"cantidad": 2, "dias": 30},
                "sistema_transporte_automatico": {"cantidad": 1, "dias": 25}
            },
            "herramientas": {
                "andamios_autoelevables": {"cantidad": 4, "dias": 30},
                "sistema_control_calidad": {"cantidad": 1, "dias": 35},
                "martillo_neumatico_profesional": {"cantidad": 2, "dias": 20},
                "nivel_laser_rotativo_premium": {"cantidad": 2, "dias": 35},
                "aspiradora_industrial_robotica": {"cantidad": 1, "dias": 25},
                "soldadora_automatica_MIG": {"cantidad": 1, "dias": 15}
            }
        },
        "terminaciones": {
            "materiales_etapa": ["pintura", "pintura_exterior", "yeso", "porcelanato", "azulejos"],
            "maquinaria": {
                "robot_pintura_automatico": {"cantidad": 1, "dias": 10},
                "maquina_proyectora_pintura_airless": {"cantidad": 1, "dias": 12},
                "sistema_proyeccion_yeso_robotico": {"cantidad": 1, "dias": 8},
                "cortadora_porcelanato_CNC": {"cantidad": 1, "dias": 10},
                "pulidora_pisos_robotica": {"cantidad": 1, "dias": 8},
                "montacargas_terminaciones": {"cantidad": 1, "dias": 20},
                "lijadora_pared_automatica": {"cantidad": 1, "dias": 6},
                "sistema_ventilacion_controlado": {"cantidad": 1, "dias": 20}
            },
            "herramientas": {
                "pistola_pintura_electrostatica": {"cantidad": 2, "dias": 12},
                "rodillos_premium_25cm": {"cantidad": 12, "dias": 15},
                "rodillos_microf fibra": {"cantidad": 10, "dias": 15},
                "pinceles_premium_profesional": {"cantidad": 12, "dias": 15},
                "pinceles_detalle_premium": {"cantidad": 8, "dias": 15},
                "brochas_premium": {"cantidad": 6, "dias": 15},
                "bandejas_pintura_premium": {"cantidad": 10, "dias": 15},
                "medidor_laser_3D": {"cantidad": 2, "dias": 15},
                "sistema_control_humedad": {"cantidad": 1, "dias": 15},
                "aspiradora_HEPA_profesional": {"cantidad": 1, "dias": 15},
                "cepillo_pulidora_diamante": {"cantidad": 2, "dias": 10},
                "nivel_laser_autonivelante": {"cantidad": 3, "dias": 20},
                "compresor_silencioso_premium": {"cantidad": 1, "dias": 15},
                "esponjas_premium": {"cantidad": 20, "dias": 15},
                "trapos_profesionales_premium": {"cantidad": 30, "dias": 15},
                "kit_limpieza_profesional": {"cantidad": 3, "dias": 15},
                "baldes_premium_graduados": {"cantidad": 10, "dias": 15}
            }
        }
    }
}

# ----------------- Cálculo por etapas "determinístico" con CAC -----------------

TIPO_MULTIPLICADOR = {
    'economica': 0.85,
    'económica': 0.85,
    'estandar': 1.0,
    'estándar': 1.0,
    'premium': 1.18,
}

PRECIO_REFERENCIA = {
    'MAT-ARENA': 12500.0,
    'MAT-PIEDRA': 18200.0,
    'MAT-CEMENTO': 8500.0,
    'MAT-HIERRO8': 2200.0,
    'MAT-HORMIGON': 23000.0,
    'MAT-LADRILLO': 320.0,
    'MAT-YESO': 5100.0,
    'MAT-AISLACION': 17800.0,
    'MAT-MADERA': 21500.0,
    'MAT-CABLE': 9800.0,
    'MAT-CAÑO-AGUA': 7600.0,
    'MAT-CAÑO-GAS': 8200.0,
    'MAT-CAÑO-CLOACA': 6900.0,
    'MAT-REVESTIMIENTO': 18500.0,
    'MAT-PINTURA-INT': 8600.0,
    'MAT-PINTURA-EXT': 9200.0,
    'MAT-SELLADOR': 5400.0,
    'MAT-LIMPIEZA': 3500.0,
    'MAT-ABERTURAS': 48000.0,
    'MAT-VIDRIO': 31000.0,
    'MAT-IMPER': 15700.0,
    'MO-MOVSUE': 42000.0,
    'MO-FUND': 44500.0,
    'MO-ESTR': 46000.0,
    'MO-MAMPO': 43500.0,
    'MO-TECH': 45200.0,
    'MO-ELEC': 47200.0,
    'MO-SANIT': 46800.0,
    'MO-GAS': 47800.0,
    'MO-REV': 41000.0,
    'MO-PISOS': 42500.0,
    'MO-CARP': 48800.0,
    'MO-PINT': 40500.0,
    'MO-SERV': 39800.0,
    'MO-LIM': 32000.0,
    'EQ-RETRO': 95000.0,
    'EQ-HORMIG': 58000.0,
    'EQ-ANDAMIOS': 27000.0,
    'EQ-PLUMA': 112000.0,
    'EQ-MEZCLADORA': 36000.0,
    'EQ-ANDAMIOS-LIV': 19000.0,
    'EQ-ELEVADOR': 78500.0,
    'EQ-HIDROLAVADORA': 15500.0,
    # Nuevos precios para etapas agregadas
    'MAT-OBRADOR': 45000.0,
    'MAT-MEMBRANA-IMP': 15700.0,
    'MAT-HIDROFUGO': 9800.0,
    'MAT-DURLOCK': 14200.0,
    'MAT-PERFIL-STEEL': 11500.0,
    'MAT-CONDUCTO-VENT': 8200.0,
    'MAT-REJILLA-VENT': 4800.0,
    'MAT-PLACA-YESO-CR': 13800.0,
    'MAT-PERFILERIA-CR': 7600.0,
    'MAT-YESO-PROY': 6200.0,
    'MAT-CONTRAPISO': 9500.0,
    'MAT-CARPETA': 7800.0,
    'MAT-CERAMICO-REV': 19200.0,
    'MAT-ADHESIVO': 6500.0,
    'MAT-GRIFERIA': 38000.0,
    'MAT-SANITARIO': 52000.0,
    'MAT-ACCESORIOS': 12000.0,
    'MO-PRELIM': 38000.0,
    'MO-DEMOL': 44000.0,
    'MO-APUNT': 46000.0,
    'MO-BOMBEO': 48000.0,
    'MO-SECO': 45000.0,
    'MO-VENT': 43000.0,
    'MO-IMP': 44500.0,
    'MO-CIELORRASO': 43000.0,
    'MO-YESERO': 42000.0,
    'MO-CONTRAPISO': 41000.0,
    'MO-REVESTIMIENTO': 43500.0,
    'MO-PROVISIONES': 44000.0,
    'EQ-DEMOLICION': 85000.0,
    'EQ-APUNTALAMIENTO': 32000.0,
    'EQ-BOMBEO': 65000.0,
    'EQ-ATORNILLADOR': 8500.0,
    'MAT-HIERRO-ESTRUC': 2800.0,
    'MAT-REJAS': 42000.0,
    'MAT-INCENDIO': 35000.0,
    'MAT-ALARMA': 28000.0,
    'MO-SEG': 45000.0,
    'MO-HERR': 48000.0,
    'EQ-SEGURIDAD': 22000.0,
    'EQ-SOLDADORA': 18000.0,
}

# ================================================================================
# FACTORES DE CONVERSIÓN DE SUPERFICIE POR ETAPA
# ================================================================================
# Estos factores convierten la superficie cubierta (m² de construcción) a la
# superficie real de trabajo para cada etapa.
#
# Ejemplo: Una casa de 500m² cubiertos tiene aproximadamente:
# - 800m² de revoque (paredes internas + externas = factor 1.6)
# - 900m² de pintura (paredes + cielorrasos = factor 1.8)
# - 500m² de contrapiso (igual a superficie = factor 1.0)
#
# Factores calculados según estándares de arquitectura argentina:
# - Altura de paredes estándar: 2.6m a 2.8m
# - Relación perímetro/superficie: aprox 0.4 a 0.6 según forma
# - Se considera construcción típica rectangular con tabiques internos
# ================================================================================

FACTORES_SUPERFICIE_ETAPA = {
    # Etapas donde la superficie = superficie cubierta
    'excavacion': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Igual a superficie cubierta',
        'notas': 'Movimiento de suelos en planta'
    },
    'fundaciones': {
        'factor': 0.25,  # Solo área de zapatas y vigas (~25% del área)
        'unidad_default': 'm³',
        'descripcion': 'Volumen de fundación (aprox 25% del área × profundidad)',
        'notas': 'Zapatas corridas y aisladas'
    },
    'estructura': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Igual a superficie cubierta',
        'notas': 'Columnas, vigas y losas'
    },
    'mamposteria': {
        'factor': 1.4,  # Perímetro × altura + tabiques internos
        'unidad_default': 'm²',
        'descripcion': 'Superficie de muros (perímetro × altura + tabiques)',
        'notas': 'Factor 1.4 considera muros perimetrales + divisorios internos'
    },
    'techos': {
        'factor': 1.1,  # Superficie + pendientes
        'unidad_default': 'm²',
        'descripcion': 'Superficie de cubierta (incluye pendientes)',
        'notas': 'Techos inclinados agregan ~10%'
    },
    'instalaciones-electricas': {
        'factor': 1.0,
        'unidad_default': 'puntos',
        'descripcion': 'Basado en superficie cubierta',
        'notas': 'Aprox 1 punto cada 4m² en zonas habitables'
    },
    'instalaciones-sanitarias': {
        'factor': 0.15,  # Solo áreas húmedas (~15% de la superficie)
        'unidad_default': 'm²',
        'descripcion': 'Superficie de áreas húmedas (baños, cocina, lavadero)',
        'notas': 'Típicamente 15% de la superficie total'
    },
    'instalaciones-gas': {
        'factor': 0.1,  # Solo cocina y calefactores
        'unidad_default': 'ml',
        'descripcion': 'Metros lineales de cañería',
        'notas': 'Depende de cantidad de artefactos'
    },
    'revoque-grueso': {
        'factor': 1.6,  # Paredes internas + externas (ambas caras)
        'unidad_default': 'm²',
        'descripcion': 'Superficie de paredes a revocar',
        'notas': 'Incluye ambas caras de muros + tabiques internos'
    },
    'revoque-fino': {
        'factor': 1.6,  # Similar a revoque grueso
        'unidad_default': 'm²',
        'descripcion': 'Superficie de terminación fina',
        'notas': 'Generalmente igual al revoque grueso'
    },
    'contrapiso': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Igual a superficie cubierta',
        'notas': 'Carpeta de nivelación en toda la planta'
    },
    'carpeta': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Igual a superficie cubierta',
        'notas': 'Carpeta de cemento alisado'
    },
    'pisos': {
        'factor': 1.05,  # Superficie + desperdicio por cortes
        'unidad_default': 'm²',
        'descripcion': 'Superficie + 5% desperdicio por cortes',
        'notas': 'Cerámicos, porcelanato o similar'
    },
    'ceramicos': {
        'factor': 0.2,  # Solo áreas húmedas (paredes)
        'unidad_default': 'm²',
        'descripcion': 'Revestimiento de paredes en áreas húmedas',
        'notas': 'Baños y cocina hasta 1.8m de altura'
    },
    'cielorrasos': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Igual a superficie cubierta',
        'notas': 'Yeso o durlock en toda la planta'
    },
    'carpinteria': {
        'factor': 0.08,  # Superficie de aberturas (~8% del área)
        'unidad_default': 'm²',
        'descripcion': 'Superficie de aberturas',
        'notas': 'Puertas y ventanas (aprox 8% del área construida)'
    },
    'pintura': {
        'factor': 1.8,  # Paredes + cielorrasos
        'unidad_default': 'm²',
        'descripcion': 'Superficie total a pintar (paredes + cielorrasos)',
        'notas': 'Incluye paredes internas y cielorrasos'
    },
    'pintura-exterior': {
        'factor': 0.5,  # Solo fachadas externas
        'unidad_default': 'm²',
        'descripcion': 'Superficie de fachadas exteriores',
        'notas': 'Perímetro externo × altura'
    },
    'instalaciones-complementarias': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Basado en superficie cubierta',
        'notas': 'AA, calefacción, domótica'
    },
    'limpieza-final': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Igual a superficie cubierta',
        'notas': 'Limpieza de toda la obra'
    },
    # Etapas nuevas
    'preliminares-obrador': {
        'factor': 1.0,
        'unidad_default': 'global',
        'descripcion': 'Basado en superficie cubierta',
        'notas': 'Obrador, cerco, replanteo y servicios provisorios'
    },
    'demoliciones': {
        'factor': 0.3,
        'unidad_default': 'm²',
        'descripcion': 'Superficie a demoler (aprox 30% del área)',
        'notas': 'Demoliciones parciales, picados y retiro'
    },
    'movimiento-de-suelos': {
        'factor': 1.2,
        'unidad_default': 'm²',
        'descripcion': 'Superficie + bordes de excavación',
        'notas': 'Excavación masiva con taludes'
    },
    'apuntalamientos': {
        'factor': 0.4,
        'unidad_default': 'ml',
        'descripcion': 'Metros lineales de medianeras a apuntalar',
        'notas': 'Depende de cantidad de linderos'
    },
    'depresion-de-napa': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Superficie de platea a deprimir',
        'notas': 'Depende de nivel freático'
    },
    'construccion-en-seco': {
        'factor': 0.4,
        'unidad_default': 'm²',
        'descripcion': 'Tabiques de placas de yeso (aprox 40% del área)',
        'notas': 'Tabiques interiores no portantes'
    },
    'ventilaciones-conductos': {
        'factor': 0.1,
        'unidad_default': 'ml',
        'descripcion': 'Metros de conductos (aprox 10% del área)',
        'notas': 'Ventilación natural y extracción mecánica'
    },
    'impermeabilizaciones-aislaciones': {
        'factor': 1.2,
        'unidad_default': 'm²',
        'descripcion': 'Superficie a impermeabilizar/aislar',
        'notas': 'Techos + subsuelos + muros enterrados'
    },
    'yeseria-enlucidos': {
        'factor': 1.6,
        'unidad_default': 'm²',
        'descripcion': 'Superficie de paredes + cielorrasos a enlucir',
        'notas': 'Similar a revoque fino'
    },
    'contrapisos-carpetas': {
        'factor': 1.0,
        'unidad_default': 'm²',
        'descripcion': 'Igual a superficie cubierta',
        'notas': 'Contrapiso + carpeta en toda la planta'
    },
    'revestimientos': {
        'factor': 0.35,
        'unidad_default': 'm²',
        'descripcion': 'Superficie de áreas húmedas + fachadas',
        'notas': 'Cerámicos en baños/cocinas y revestimiento exterior'
    },
    'provisiones-colocaciones': {
        'factor': 1.0,
        'unidad_default': 'unidades',
        'descripcion': 'Basado en superficie cubierta',
        'notas': 'Griferías, sanitarios y accesorios'
    },
    # Aliases comunes
    'albanileria': {
        'factor': 1.4,
        'unidad_default': 'm²',
        'descripcion': 'Superficie de muros',
        'notas': 'Alias de mampostería'
    },
    'terminaciones': {
        'factor': 1.5,
        'unidad_default': 'm²',
        'descripcion': 'Promedio de terminaciones varias',
        'notas': 'Incluye varios rubros de terminación'
    },
}


def calcular_superficie_etapa(superficie_cubierta: float, etapa_slug: str) -> dict:
    """
    Calcula la superficie real de trabajo para una etapa específica.

    Args:
        superficie_cubierta: Metros cuadrados de construcción cubierta
        etapa_slug: Identificador de la etapa (ej: 'revoque-grueso')

    Returns:
        dict con:
        - superficie_calculada: m², m³, ml o unidades según corresponda
        - unidad: Unidad de medida
        - factor: Factor aplicado
        - descripcion: Explicación del cálculo
    """
    # Normalizar slug
    slug_normalizado = etapa_slug.lower().strip()

    # Buscar en factores definidos
    if slug_normalizado in FACTORES_SUPERFICIE_ETAPA:
        config = FACTORES_SUPERFICIE_ETAPA[slug_normalizado]
        superficie_calculada = superficie_cubierta * config['factor']
        return {
            'superficie_calculada': round(superficie_calculada, 2),
            'unidad': config['unidad_default'],
            'factor': config['factor'],
            'descripcion': config['descripcion'],
            'notas': config['notas'],
            'metodo': 'factor_definido'
        }

    # Buscar por coincidencia parcial
    for key, config in FACTORES_SUPERFICIE_ETAPA.items():
        if key in slug_normalizado or slug_normalizado in key:
            superficie_calculada = superficie_cubierta * config['factor']
            return {
                'superficie_calculada': round(superficie_calculada, 2),
                'unidad': config['unidad_default'],
                'factor': config['factor'],
                'descripcion': config['descripcion'],
                'notas': f"Coincidencia con '{key}': {config['notas']}",
                'metodo': 'coincidencia_parcial'
            }

    # Default: usar superficie cubierta sin modificar
    return {
        'superficie_calculada': round(superficie_cubierta, 2),
        'unidad': 'm²',
        'factor': 1.0,
        'descripcion': 'Sin factor específico, se usa superficie cubierta',
        'notas': 'Etapa no tiene factor definido',
        'metodo': 'default'
    }


def obtener_factores_todas_etapas(superficie_cubierta: float) -> dict:
    """
    Calcula la superficie de todas las etapas para una obra dada.
    Útil para mostrar al usuario un resumen de superficies por etapa.
    """
    resultado = {}
    for slug, config in FACTORES_SUPERFICIE_ETAPA.items():
        superficie_calc = superficie_cubierta * config['factor']
        resultado[slug] = {
            'nombre': slug.replace('-', ' ').title(),
            'superficie': round(superficie_calc, 2),
            'unidad': config['unidad_default'],
            'factor': config['factor'],
            'descripcion': config['descripcion']
        }
    return resultado


ETAPA_REGLAS_BASE = {
    'excavacion': {
        'nombre': 'Excavación',
        'materiales': [
            {'codigo': 'MAT-ARENA', 'material_key': 'arena', 'descripcion': 'Arena gruesa para estabilización', 'unidad': 'm³', 'coef_por_m2': 0.04},
            {'codigo': 'MAT-PIEDRA', 'material_key': 'piedra', 'descripcion': 'Piedra partida 3/4"', 'unidad': 'm³', 'coef_por_m2': 0.03}
        ],
        'mano_obra': [
            {'codigo': 'MO-MOVSUE', 'descripcion': 'Cuadrilla movimiento de suelos', 'unidad': 'jornal', 'coef_por_m2': 0.18}
        ],
        'equipos': [
            {'codigo': 'EQ-RETRO', 'descripcion': 'Retroexcavadora con operador', 'unidad': 'día', 'dias_por_m2': 0.008, 'min_dias': 1}
        ],
        'notas': 'Movimiento de suelos, replanteo y perfilado del terreno.'
    },
    'fundaciones': {
        'nombre': 'Fundaciones',
        'materiales': [
            {'codigo': 'MAT-CEMENTO', 'material_key': 'cemento', 'descripcion': 'Bolsas de cemento Portland', 'unidad': 'bolsa', 'coef_por_m2': 0.32},
            {'codigo': 'MAT-HIERRO8', 'material_key': 'hierro_8', 'descripcion': 'Barra de acero 8mm', 'unidad': 'kg', 'coef_por_m2': 2.9},
            {'codigo': 'MAT-HORMIGON', 'material_key': 'hormigon', 'descripcion': 'Hormigón elaborado H21', 'unidad': 'm³', 'coef_por_m2': 0.12}
        ],
        'mano_obra': [
            {'codigo': 'MO-FUND', 'descripcion': 'Cuadrilla de fundaciones', 'unidad': 'jornal', 'coef_por_m2': 0.22}
        ],
        'equipos': [
            {'codigo': 'EQ-HORMIG', 'descripcion': 'Hormigonera o bomba de hormigón', 'unidad': 'día', 'dias_por_m2': 0.004, 'min_dias': 1}
        ],
        'notas': 'Zapatas, vigas de fundación y hormigonados primarios.'
    },
    'estructura': {
        'nombre': 'Estructura',
        'materiales': [
            {'codigo': 'MAT-HIERRO8', 'material_key': 'hierro_8', 'descripcion': 'Acero para armaduras', 'unidad': 'kg', 'coef_por_m2': 3.6},
            {'codigo': 'MAT-HORMIGON', 'material_key': 'hormigon', 'descripcion': 'Hormigón elaborado estructural', 'unidad': 'm³', 'coef_por_m2': 0.15},
            {'codigo': 'MAT-MADERA', 'material_key': 'madera_estructural', 'descripcion': 'Madera para encofrado', 'unidad': 'm³', 'coef_por_m2': 0.06}
        ],
        'mano_obra': [
            {'codigo': 'MO-ESTR', 'descripcion': 'Cuadrilla de estructura', 'unidad': 'jornal', 'coef_por_m2': 0.28}
        ],
        'equipos': [
            {'codigo': 'EQ-PLUMA', 'descripcion': 'Grúa/pluma o elevador', 'unidad': 'día', 'dias_por_m2': 0.003, 'min_dias': 1}
        ],
        'notas': 'Elevación de columnas, losas y vigas principales.'
    },
    'mamposteria': {
        'nombre': 'Mampostería',
        'materiales': [
            {'codigo': 'MAT-LADRILLO', 'material_key': 'ladrillos', 'descripcion': 'Ladrillos cerámicos portantes', 'unidad': 'unidades', 'coef_por_m2': 55},
            {'codigo': 'MAT-CEMENTO', 'material_key': 'cemento', 'descripcion': 'Cemento para mortero', 'unidad': 'bolsa', 'coef_por_m2': 0.26}
        ],
        'mano_obra': [
            {'codigo': 'MO-MAMPO', 'descripcion': 'Oficial + ayudante de albañilería', 'unidad': 'jornal', 'coef_por_m2': 0.25}
        ],
        'equipos': [
            {'codigo': 'EQ-ANDAMIOS', 'descripcion': 'Andamios tubulares', 'unidad': 'día', 'dias_por_m2': 0.0045, 'min_dias': 2}
        ],
        'notas': 'Levantamiento de muros exteriores e interiores.'
    },
    'techos': {
        'nombre': 'Techos y Cubiertas',
        'materiales': [
            {'codigo': 'MAT-AISLACION', 'material_key': 'aislacion_termica', 'descripcion': 'Paneles de aislación térmica', 'unidad': 'm²', 'coef_por_m2': 1.1},
            {'codigo': 'MAT-IMPER', 'material_key': 'membrana', 'descripcion': 'Membrana asfáltica', 'unidad': 'm²', 'coef_por_m2': 1.05}
        ],
        'mano_obra': [
            {'codigo': 'MO-TECH', 'descripcion': 'Equipo montaje de cubiertas', 'unidad': 'jornal', 'coef_por_m2': 0.20}
        ],
        'equipos': [
            {'codigo': 'EQ-ANDAMIOS-LIV', 'descripcion': 'Andamios y líneas de vida', 'unidad': 'día', 'dias_por_m2': 0.0035, 'min_dias': 2}
        ],
        'notas': 'Estructura de techos, aislaciones y terminaciones impermeables.'
    },
    'instalaciones-electricas': {
        'nombre': 'Instalaciones Eléctricas',
        'materiales': [
            {'codigo': 'MAT-CABLE', 'material_key': 'cables_electricos', 'descripcion': 'Cableado y conductores', 'unidad': 'm', 'coef_por_m2': 12},
            {'codigo': 'MAT-ABERTURAS', 'material_key': 'aberturas_metal', 'descripcion': 'Tableros y cajas de distribución', 'unidad': 'unidades', 'coef_por_m2': 0.12}
        ],
        'mano_obra': [
            {'codigo': 'MO-ELEC', 'descripcion': 'Electricista matriculado + ayudante', 'unidad': 'jornal', 'coef_por_m2': 0.16}
        ],
        'equipos': [
            {'codigo': 'EQ-MEZCLADORA', 'descripcion': 'Herramienta eléctrica especializada', 'unidad': 'día', 'dias_por_m2': 0.002, 'min_dias': 1}
        ],
        'notas': 'Canalizaciones, cableado y tableros seccionales.'
    },
    'instalaciones-sanitarias': {
        'nombre': 'Instalaciones Sanitarias',
        'materiales': [
            {'codigo': 'MAT-CAÑO-AGUA', 'material_key': 'caños_agua', 'descripcion': 'Caños de agua y accesorios', 'unidad': 'm', 'coef_por_m2': 5.5},
            {'codigo': 'MAT-CAÑO-CLOACA', 'material_key': 'caños_cloacas', 'descripcion': 'Desagües cloacales y pluviales', 'unidad': 'm', 'coef_por_m2': 3.2}
        ],
        'mano_obra': [
            {'codigo': 'MO-SANIT', 'descripcion': 'Instalador sanitario', 'unidad': 'jornal', 'coef_por_m2': 0.15}
        ],
        'equipos': [
            {'codigo': 'EQ-MEZCLADORA', 'descripcion': 'Herramientas rotativas y prensado', 'unidad': 'día', 'dias_por_m2': 0.0015, 'min_dias': 1}
        ],
        'notas': 'Redes de agua fría/caliente y desagües interiores.'
    },
    'instalaciones-gas': {
        'nombre': 'Instalaciones de Gas',
        'materiales': [
            {'codigo': 'MAT-CAÑO-GAS', 'material_key': 'caños_gas', 'descripcion': 'Caños de gas y conexiones', 'unidad': 'm', 'coef_por_m2': 2.2}
        ],
        'mano_obra': [
            {'codigo': 'MO-GAS', 'descripcion': 'Gasista matriculado', 'unidad': 'jornal', 'coef_por_m2': 0.12}
        ],
        'equipos': [
            {'codigo': 'EQ-MEZCLADORA', 'descripcion': 'Herramientas de calibración y prueba', 'unidad': 'día', 'dias_por_m2': 0.001, 'min_dias': 1}
        ],
        'notas': 'Colocación de cañerías, pruebas y certificaciones.'
    },
    'revoque-grueso': {
        'nombre': 'Revoque Grueso',
        'materiales': [
            {'codigo': 'MAT-CEMENTO', 'material_key': 'cemento', 'descripcion': 'Cemento para revoque', 'unidad': 'bolsa', 'coef_por_m2': 0.22},
            {'codigo': 'MAT-ARENA', 'material_key': 'arena', 'descripcion': 'Arena fina seleccionada', 'unidad': 'm³', 'coef_por_m2': 0.055}
        ],
        'mano_obra': [
            {'codigo': 'MO-REV', 'descripcion': 'Oficial revocador', 'unidad': 'jornal', 'coef_por_m2': 0.19}
        ],
        'equipos': [
            {'codigo': 'EQ-ANDAMIOS', 'descripcion': 'Andamios y fratasadoras', 'unidad': 'día', 'dias_por_m2': 0.003, 'min_dias': 1}
        ],
        'notas': 'Aplicación de base gruesa y nivelación.'
    },
    'revoque-fino': {
        'nombre': 'Revoque Fino',
        'materiales': [
            {'codigo': 'MAT-YESO', 'material_key': 'yeso', 'descripcion': 'Yeso de terminación', 'unidad': 'kg', 'coef_por_m2': 3.4}
        ],
        'mano_obra': [
            {'codigo': 'MO-REV', 'descripcion': 'Terminación de yeseros', 'unidad': 'jornal', 'coef_por_m2': 0.15}
        ],
        'equipos': [],
        'notas': 'Alisado y terminación fina interior.'
    },
    'pisos': {
        'nombre': 'Pisos y Revestimientos',
        'materiales': [
            {'codigo': 'MAT-REVESTIMIENTO', 'material_key': 'porcelanato', 'descripcion': 'Revestimiento cerámico/porcelanato', 'unidad': 'm²', 'coef_por_m2': 1.05}
        ],
        'mano_obra': [
            {'codigo': 'MO-PISOS', 'descripcion': 'Colocador especializado', 'unidad': 'jornal', 'coef_por_m2': 0.18}
        ],
        'equipos': [],
        'notas': 'Colocación de pisos y zócalos principales.'
    },
    'carpinteria': {
        'nombre': 'Carpintería y Aberturas',
        'materiales': [
            {'codigo': 'MAT-ABERTURAS', 'material_key': 'aberturas_metal', 'descripcion': 'Puertas y ventanas metálicas/madera', 'unidad': 'unidades', 'coef_por_m2': 0.09},
            {'codigo': 'MAT-VIDRIO', 'material_key': 'vidrios', 'descripcion': 'DVH / vidrio templado', 'unidad': 'm²', 'coef_por_m2': 0.14}
        ],
        'mano_obra': [
            {'codigo': 'MO-CARP', 'descripcion': 'Carpintero instalador', 'unidad': 'jornal', 'coef_por_m2': 0.14}
        ],
        'equipos': [
            {'codigo': 'EQ-ELEVADOR', 'descripcion': 'Elevador/ventosas para cristales', 'unidad': 'día', 'dias_por_m2': 0.0025, 'min_dias': 1}
        ],
        'notas': 'Colocación de carpinterías exteriores e interiores.'
    },
    'pintura': {
        'nombre': 'Pintura',
        'materiales': [
            {'codigo': 'MAT-PINTURA-INT', 'material_key': 'pintura', 'descripcion': 'Pintura interior lavable', 'unidad': 'litros', 'coef_por_m2': 0.14},
            {'codigo': 'MAT-PINTURA-EXT', 'material_key': 'pintura_exterior', 'descripcion': 'Revestimiento exterior acrílico', 'unidad': 'litros', 'coef_por_m2': 0.11},
            {'codigo': 'MAT-SELLADOR', 'material_key': 'sellador', 'descripcion': 'Sellador acrílico', 'unidad': 'litros', 'coef_por_m2': 0.04}
        ],
        'mano_obra': [
            {'codigo': 'MO-PINT', 'descripcion': 'Equipo de pintores', 'unidad': 'jornal', 'coef_por_m2': 0.16}
        ],
        'equipos': [
            {'codigo': 'EQ-HIDROLAVADORA', 'descripcion': 'Hidrolavadora y compresor', 'unidad': 'día', 'dias_por_m2': 0.002, 'min_dias': 1}
        ],
        'notas': 'Preparación de superficies y aplicación de terminaciones.'
    },
    'instalaciones-complementarias': {
        'nombre': 'Instalaciones Complementarias',
        'materiales': [
            {'codigo': 'MAT-AISLACION', 'material_key': 'aislacion_termica', 'descripcion': 'Aislación adicional HVAC', 'unidad': 'm²', 'coef_por_m2': 0.4}
        ],
        'mano_obra': [
            {'codigo': 'MO-SERV', 'descripcion': 'Técnicos especializados', 'unidad': 'jornal', 'coef_por_m2': 0.12}
        ],
        'equipos': [],
        'notas': 'Climatización, domótica y sistemas especiales.'
    },
    'limpieza-final': {
        'nombre': 'Limpieza Final y Puesta en Marcha',
        'materiales': [
            {'codigo': 'MAT-LIMPIEZA', 'material_key': 'limpieza', 'descripcion': 'Insumos de limpieza y protección', 'unidad': 'kit', 'coef_por_m2': 0.015}
        ],
        'mano_obra': [
            {'codigo': 'MO-LIM', 'descripcion': 'Equipo de limpieza profesional', 'unidad': 'jornal', 'coef_por_m2': 0.08}
        ],
        'equipos': [],
        'notas': 'Limpieza fina, sellado y entrega de obra.'
    },
    'seguridad': {
        'nombre': 'Seguridad',
        'materiales': [
            {'codigo': 'MAT-INCENDIO', 'material_key': 'sistema_incendio', 'descripcion': 'Sistema contra incendio (extintores, mangueras)', 'unidad': 'global', 'coef_por_m2': 0.008},
            {'codigo': 'MAT-ALARMA', 'material_key': 'alarma', 'descripcion': 'Sistema de alarmas y detección', 'unidad': 'global', 'coef_por_m2': 0.006}
        ],
        'mano_obra': [
            {'codigo': 'MO-SEG', 'descripcion': 'Técnico instalador de seguridad', 'unidad': 'jornal', 'coef_por_m2': 0.10}
        ],
        'equipos': [
            {'codigo': 'EQ-SEGURIDAD', 'descripcion': 'Herramientas especializadas seguridad', 'unidad': 'día', 'dias_por_m2': 0.002, 'min_dias': 1}
        ],
        'notas': 'Equipos contra incendio, alarmas, detectores y maquinaria de edificio.'
    },
    'herreria-de-obra': {
        'nombre': 'Herrería de Obra',
        'materiales': [
            {'codigo': 'MAT-HIERRO-ESTRUC', 'material_key': 'hierro_estructural', 'descripcion': 'Perfiles y estructuras metálicas', 'unidad': 'kg', 'coef_por_m2': 2.5},
            {'codigo': 'MAT-REJAS', 'material_key': 'rejas', 'descripcion': 'Rejas, portones y barandas', 'unidad': 'm²', 'coef_por_m2': 0.15}
        ],
        'mano_obra': [
            {'codigo': 'MO-HERR', 'descripcion': 'Herrero especializado', 'unidad': 'jornal', 'coef_por_m2': 0.14}
        ],
        'equipos': [
            {'codigo': 'EQ-SOLDADORA', 'descripcion': 'Soldadora y amoladora', 'unidad': 'día', 'dias_por_m2': 0.003, 'min_dias': 1}
        ],
        'notas': 'Rejas, portones, barandas, escaleras metálicas y estructuras de herrería.'
    },
    # =============================================
    # Etapas nuevas (IDs 16-28)
    # =============================================
    'preliminares-obrador': {
        'nombre': 'Preliminares y Obrador',
        'materiales': [
            {'codigo': 'MAT-OBRADOR', 'material_key': 'obrador', 'descripcion': 'Obrador provisorio (contenedor, baños, cerco)', 'unidad': 'global', 'coef_por_m2': 0.008},
            {'codigo': 'MAT-MADERA', 'material_key': 'madera_estructural', 'descripcion': 'Madera para cercos y protecciones', 'unidad': 'm³', 'coef_por_m2': 0.01},
        ],
        'mano_obra': [
            {'codigo': 'MO-PRELIM', 'descripcion': 'Cuadrilla de armado de obrador', 'unidad': 'jornal', 'coef_por_m2': 0.10}
        ],
        'equipos': [
            {'codigo': 'EQ-RETRO', 'descripcion': 'Retroexcavadora para limpieza de terreno', 'unidad': 'día', 'dias_por_m2': 0.003, 'min_dias': 1}
        ],
        'notas': 'Permisos, obrador, cerco de obra, replanteo y servicios provisorios.'
    },
    'demoliciones': {
        'nombre': 'Demoliciones',
        'materiales': [],
        'mano_obra': [
            {'codigo': 'MO-DEMOL', 'descripcion': 'Cuadrilla de demolición', 'unidad': 'jornal', 'coef_por_m2': 0.15}
        ],
        'equipos': [
            {'codigo': 'EQ-DEMOLICION', 'descripcion': 'Martillo neumático y miniretro', 'unidad': 'día', 'dias_por_m2': 0.006, 'min_dias': 1}
        ],
        'notas': 'Demolición de estructuras existentes, retiro de escombros y volquetes.'
    },
    'movimiento-de-suelos': {
        'nombre': 'Movimiento de Suelos',
        'materiales': [
            {'codigo': 'MAT-ARENA', 'material_key': 'arena', 'descripcion': 'Arena para relleno y compactación', 'unidad': 'm³', 'coef_por_m2': 0.06},
            {'codigo': 'MAT-PIEDRA', 'material_key': 'piedra', 'descripcion': 'Tosca / suelo seleccionado para relleno', 'unidad': 'm³', 'coef_por_m2': 0.04},
        ],
        'mano_obra': [
            {'codigo': 'MO-MOVSUE', 'descripcion': 'Cuadrilla movimiento de suelos', 'unidad': 'jornal', 'coef_por_m2': 0.20}
        ],
        'equipos': [
            {'codigo': 'EQ-RETRO', 'descripcion': 'Retroexcavadora con operador', 'unidad': 'día', 'dias_por_m2': 0.010, 'min_dias': 1}
        ],
        'notas': 'Excavación masiva, perfilado, rellenos y compactación mecánica.'
    },
    'apuntalamientos': {
        'nombre': 'Apuntalamientos',
        'materiales': [
            {'codigo': 'MAT-MADERA', 'material_key': 'madera_estructural', 'descripcion': 'Madera para puntales y tablestacas', 'unidad': 'm³', 'coef_por_m2': 0.03},
        ],
        'mano_obra': [
            {'codigo': 'MO-APUNT', 'descripcion': 'Cuadrilla de apuntalamiento', 'unidad': 'jornal', 'coef_por_m2': 0.12}
        ],
        'equipos': [
            {'codigo': 'EQ-APUNTALAMIENTO', 'descripcion': 'Puntales metálicos telescópicos', 'unidad': 'día', 'dias_por_m2': 0.005, 'min_dias': 2}
        ],
        'notas': 'Sostenimiento provisorio de medianeras, tabiques y estructuras linderas.'
    },
    'depresion-de-napa': {
        'nombre': 'Depresión de Napa / Bombeo',
        'materiales': [],
        'mano_obra': [
            {'codigo': 'MO-BOMBEO', 'descripcion': 'Operación de equipos de bombeo', 'unidad': 'jornal', 'coef_por_m2': 0.08}
        ],
        'equipos': [
            {'codigo': 'EQ-BOMBEO', 'descripcion': 'Equipo de wellpoints y bombas sumergibles', 'unidad': 'día', 'dias_por_m2': 0.012, 'min_dias': 5}
        ],
        'notas': 'Instalación de pozos, bombas y mantenimiento para control de nivel freático.'
    },
    'construccion-en-seco': {
        'nombre': 'Construcción en Seco',
        'materiales': [
            {'codigo': 'MAT-DURLOCK', 'material_key': 'durlock', 'descripcion': 'Placas de yeso (Durlock/Knauf)', 'unidad': 'm²', 'coef_por_m2': 0.45},
            {'codigo': 'MAT-PERFIL-STEEL', 'material_key': 'perfileria_steel', 'descripcion': 'Perfilería galvanizada (montantes y soleras)', 'unidad': 'ml', 'coef_por_m2': 1.8},
        ],
        'mano_obra': [
            {'codigo': 'MO-SECO', 'descripcion': 'Oficial especializado en drywall', 'unidad': 'jornal', 'coef_por_m2': 0.16}
        ],
        'equipos': [
            {'codigo': 'EQ-ATORNILLADOR', 'descripcion': 'Atornillador y herramientas de corte', 'unidad': 'día', 'dias_por_m2': 0.003, 'min_dias': 1}
        ],
        'notas': 'Tabiques y cielorrasos de placas de yeso, steel framing.'
    },
    'ventilaciones-conductos': {
        'nombre': 'Ventilaciones y Conductos',
        'materiales': [
            {'codigo': 'MAT-CONDUCTO-VENT', 'material_key': 'conducto_vent', 'descripcion': 'Conductos de chapa galvanizada / PVC', 'unidad': 'ml', 'coef_por_m2': 0.8},
            {'codigo': 'MAT-REJILLA-VENT', 'material_key': 'rejilla_vent', 'descripcion': 'Rejillas, sombrerete y accesorios', 'unidad': 'unidades', 'coef_por_m2': 0.06},
        ],
        'mano_obra': [
            {'codigo': 'MO-VENT', 'descripcion': 'Instalador de ventilación', 'unidad': 'jornal', 'coef_por_m2': 0.10}
        ],
        'equipos': [],
        'notas': 'Conductos de ventilación natural, extracción mecánica y tiro balanceado.'
    },
    'impermeabilizaciones-aislaciones': {
        'nombre': 'Impermeabilizaciones y Aislaciones',
        'materiales': [
            {'codigo': 'MAT-MEMBRANA-IMP', 'material_key': 'membrana', 'descripcion': 'Membrana asfáltica con aluminio', 'unidad': 'm²', 'coef_por_m2': 0.9},
            {'codigo': 'MAT-HIDROFUGO', 'material_key': 'hidrofugo', 'descripcion': 'Hidrófugo cementicio / pintura asfáltica', 'unidad': 'litros', 'coef_por_m2': 0.25},
            {'codigo': 'MAT-AISLACION', 'material_key': 'aislacion_termica', 'descripcion': 'Aislación térmica EPS / lana de vidrio', 'unidad': 'm²', 'coef_por_m2': 0.85},
        ],
        'mano_obra': [
            {'codigo': 'MO-IMP', 'descripcion': 'Oficial aplicador de membranas', 'unidad': 'jornal', 'coef_por_m2': 0.14}
        ],
        'equipos': [],
        'notas': 'Membranas en techos, hidrófugos en muros y fundaciones, aislación térmica/acústica.'
    },
    'cielorrasos': {
        'nombre': 'Cielorrasos',
        'materiales': [
            {'codigo': 'MAT-PLACA-YESO-CR', 'material_key': 'placa_yeso_cr', 'descripcion': 'Placas de yeso para cielorraso', 'unidad': 'm²', 'coef_por_m2': 1.05},
            {'codigo': 'MAT-PERFILERIA-CR', 'material_key': 'perfileria_cr', 'descripcion': 'Perfilería suspendida (omega, varillas)', 'unidad': 'ml', 'coef_por_m2': 2.2},
        ],
        'mano_obra': [
            {'codigo': 'MO-CIELORRASO', 'descripcion': 'Oficial cielorrasista', 'unidad': 'jornal', 'coef_por_m2': 0.17}
        ],
        'equipos': [
            {'codigo': 'EQ-ANDAMIOS-LIV', 'descripcion': 'Andamios y escaleras', 'unidad': 'día', 'dias_por_m2': 0.003, 'min_dias': 1}
        ],
        'notas': 'Cielorrasos aplicados de yeso, suspendidos de Durlock y desmontables.'
    },
    'yeseria-enlucidos': {
        'nombre': 'Yesería y Enlucidos',
        'materiales': [
            {'codigo': 'MAT-YESO-PROY', 'material_key': 'yeso_proyectado', 'descripcion': 'Yeso proyectado / enlucido de yeso', 'unidad': 'kg', 'coef_por_m2': 4.5},
        ],
        'mano_obra': [
            {'codigo': 'MO-YESERO', 'descripcion': 'Yesero proyectista', 'unidad': 'jornal', 'coef_por_m2': 0.14}
        ],
        'equipos': [
            {'codigo': 'EQ-MEZCLADORA', 'descripcion': 'Proyectora de yeso', 'unidad': 'día', 'dias_por_m2': 0.002, 'min_dias': 1}
        ],
        'notas': 'Enlucido de yeso proyectado en paredes y cielorrasos, cantoneras.'
    },
    'contrapisos-carpetas': {
        'nombre': 'Contrapisos y Carpetas',
        'materiales': [
            {'codigo': 'MAT-CONTRAPISO', 'material_key': 'contrapiso', 'descripcion': 'Hormigón pobre para contrapiso', 'unidad': 'm³', 'coef_por_m2': 0.08},
            {'codigo': 'MAT-CARPETA', 'material_key': 'carpeta', 'descripcion': 'Mortero para carpeta de nivelación', 'unidad': 'm³', 'coef_por_m2': 0.03},
            {'codigo': 'MAT-ARENA', 'material_key': 'arena', 'descripcion': 'Arena para mezcla', 'unidad': 'm³', 'coef_por_m2': 0.04},
        ],
        'mano_obra': [
            {'codigo': 'MO-CONTRAPISO', 'descripcion': 'Oficial albañil + ayudante', 'unidad': 'jornal', 'coef_por_m2': 0.18}
        ],
        'equipos': [
            {'codigo': 'EQ-MEZCLADORA', 'descripcion': 'Mezcladora / hormigonera', 'unidad': 'día', 'dias_por_m2': 0.003, 'min_dias': 1}
        ],
        'notas': 'Contrapiso de hormigón, carpeta de cemento alisado con pendientes.'
    },
    'revestimientos': {
        'nombre': 'Revestimientos',
        'materiales': [
            {'codigo': 'MAT-CERAMICO-REV', 'material_key': 'ceramico_rev', 'descripcion': 'Cerámico / porcellanato para revestimiento', 'unidad': 'm²', 'coef_por_m2': 0.35},
            {'codigo': 'MAT-ADHESIVO', 'material_key': 'adhesivo', 'descripcion': 'Adhesivo cementicio para colocación', 'unidad': 'kg', 'coef_por_m2': 1.8},
        ],
        'mano_obra': [
            {'codigo': 'MO-REVESTIMIENTO', 'descripcion': 'Colocador de revestimientos', 'unidad': 'jornal', 'coef_por_m2': 0.16}
        ],
        'equipos': [],
        'notas': 'Revestimientos cerámicos, porcellanato, piedra en fachadas y áreas húmedas.'
    },
    'provisiones-colocaciones': {
        'nombre': 'Provisiones y Colocaciones',
        'materiales': [
            {'codigo': 'MAT-GRIFERIA', 'material_key': 'griferia', 'descripcion': 'Griferías (cocina, baños)', 'unidad': 'unidades', 'coef_por_m2': 0.025},
            {'codigo': 'MAT-SANITARIO', 'material_key': 'sanitario', 'descripcion': 'Artefactos sanitarios (inodoro, bidet, lavatorio)', 'unidad': 'unidades', 'coef_por_m2': 0.02},
            {'codigo': 'MAT-ACCESORIOS', 'material_key': 'accesorios', 'descripcion': 'Accesorios de baño y cocina', 'unidad': 'unidades', 'coef_por_m2': 0.04},
        ],
        'mano_obra': [
            {'codigo': 'MO-PROVISIONES', 'descripcion': 'Oficial instalador', 'unidad': 'jornal', 'coef_por_m2': 0.12}
        ],
        'equipos': [],
        'notas': 'Provisión y colocación de griferías, sanitarios, mesadas, perfiles y herrajes.'
    },
}

STAGE_CALC_CACHE: Dict[str, Any] = {}

# ----------------- Funciones base -----------------

def slugify_etapa(nombre):
    if not nombre:
        return ''
    ascii_text = normalize('NFKD', str(nombre)).encode('ascii', 'ignore').decode('ascii')
    slug = ''.join(ch if ch.isalnum() else '-' for ch in ascii_text.lower())
    slug = '-'.join(filter(None, slug.split('-')))
    return slug


def obtener_multiplicador_tipo(tipo):
    if not tipo:
        return 1.0, 'Estándar'
    clave = str(tipo).strip()
    clave_norm = clave.lower()
    if clave_norm in TIPO_MULTIPLICADOR:
        return TIPO_MULTIPLICADOR[clave_norm], clave.title()
    return 1.0, clave.title()


def _precio_referencia(codigo: str, cac_context: CACContext, org_id: Optional[int] = None) -> Decimal:
    """
    Obtiene el precio de referencia, intentando primero consultar el inventario real
    de la organización, y si no está disponible, usa los precios de referencia hardcodeados.
    """
    # Intentar obtener precio real del inventario
    if org_id:
        try:
            from models import ItemInventario
            from extensions import db

            # Mapeo de códigos a búsquedas en inventario
            busquedas_inventario = {
                'MAT-CEMENTO': ['cemento', 'portland'],
                'MAT-ARENA': ['arena'],
                'MAT-PIEDRA': ['piedra', 'canto rodado'],
                'MAT-LADRILLO': ['ladrillo', 'ladrillos'],
                'MAT-HIERRO8': ['hierro 8', 'hierro', 'varilla 8'],
                'MAT-PINTURA-INT': ['pintura interior', 'pintura lavable', 'latex interior'],
                'MAT-PINTURA-EXT': ['pintura exterior', 'revestimiento', 'acrilico exterior'],
                'MAT-SELLADOR': ['sellador', 'fijador', 'imprimacion'],
                'MAT-YESO': ['yeso', 'enduido'],
                'MAT-CABLE': ['cable', 'cable electrico'],
                'MAT-CAÑO-AGUA': ['caño agua', 'caño pvc', 'tuberia agua'],
                'MAT-CAÑO-GAS': ['caño gas', 'tuberia gas'],
                'MAT-CAÑO-CLOACA': ['caño cloaca', 'caño desague', 'tuberia cloaca'],
            }

            if codigo in busquedas_inventario:
                terminos = busquedas_inventario[codigo]
                for termino in terminos:
                    # Buscar en inventario (case-insensitive)
                    item = ItemInventario.query.filter(
                        ItemInventario.organizacion_id == org_id,
                        ItemInventario.nombre.ilike(f'%{termino}%')
                    ).first()

                    if item and item.precio_unitario:
                        precio_real = _to_decimal(item.precio_unitario, '0')
                        if precio_real > DECIMAL_ZERO:
                            logging.info(f"📦 Usando precio real del inventario para {codigo}: {item.nombre} = ${precio_real}")
                            return _quantize_currency(precio_real * cac_context.multiplier)
        except Exception as e:
            logging.warning(f"No se pudo consultar inventario para {codigo}: {e}")

    # Fallback: usar precio de referencia hardcodeado
    base = _to_decimal(PRECIO_REFERENCIA.get(codigo), '0')
    return _quantize_currency(base * cac_context.multiplier)


def _redondear(valor: Decimal, ndigits: int = 2) -> Decimal:
    quant = Decimal('1').scaleb(-ndigits)
    return valor.quantize(quant, rounding=ROUND_HALF_UP)


def analizar_plano_con_ia(archivo_pdf_base64, metros_cuadrados_manual=None):
    """
    Analiza un plano arquitectónico usando IA de OpenAI.
    Para PDFs, se usa análisis textual; si hay superficie manual se sugiere tipología.
    """
    if client is None:
        raise RuntimeError(
            "OPENAI_API_KEY no configurada. Configurala para habilitar el análisis con IA."
        )

    try:
        # Si hay superficie manual, hacer análisis simple por texto
        if metros_cuadrados_manual:
            superficie_float = float(metros_cuadrados_manual)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un arquitecto y calculista experto en construcción argentina. "
                            "Basándote en la superficie proporcionada, sugiere el tipo de construcción más apropiado. "
                            "Responde en formato JSON con: superficie_total_m2, tipo_construccion_sugerido "
                            "(Económica|Estándar|Premium), observaciones, confianza_analisis (0..1)."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Para una construcción de {superficie_float}m², sugiere el tipo más apropiado "
                            "y recomendaciones técnicas para Argentina."
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                max_tokens=500,
            )
            content = response.choices[0].message.content
            if content:
                resultado = json.loads(content)
                resultado['superficie_total_m2'] = superficie_float
                resultado['superficie_origen'] = 'manual'
                resultado['openai_disponible'] = True
                return resultado

        # Sin superficie manual → devolvemos estimación guiada
        return {
            "superficie_total_m2": float(metros_cuadrados_manual) if metros_cuadrados_manual else 100.0,
            "tipo_construccion_sugerido": "Estándar",
            "observaciones": "Análisis basado en superficie proporcionada. PDF cargado pero se requiere superficie manual.",
            "confianza_analisis": 0.8 if metros_cuadrados_manual else 0.3,
            "superficie_origen": "manual" if metros_cuadrados_manual else "estimado",
            "openai_disponible": True,
        }

    except Exception as e:
        logging.exception("Error en análisis IA")
        # Fallback con datos manuales si falla la IA
        return {
            "superficie_total_m2": float(metros_cuadrados_manual) if metros_cuadrados_manual else 100.0,
            "tipo_construccion_sugerido": "Estándar",
            "observaciones": f"Error en análisis: {str(e)}. Usando superficie manual proporcionada.",
            "confianza_analisis": 0.5,
            "superficie_origen": "manual_fallback",
            "openai_disponible": OPENAI_AVAILABLE,
        }


def calcular_materiales(superficie_m2, tipo_construccion):
    """
    Calcula la cantidad de materiales necesarios.
    Aplica 10% de desperdicio y redondea hacia arriba a números enteros.
    """
    if tipo_construccion not in COEFICIENTES_CONSTRUCCION:
        raise ValueError(f"Tipo de construcción '{tipo_construccion}' no válido")

    coef = COEFICIENTES_CONSTRUCCION[tipo_construccion]
    materiales = {}
    for material, coef_por_m2 in coef.items():
        if material != "factor_precio":
            cantidad = superficie_m2 * coef_por_m2
            # Aplicar 10% de desperdicio y redondear hacia arriba
            cantidad_con_desperdicio = cantidad * 1.10
            materiales[material] = math.ceil(cantidad_con_desperdicio)

    return materiales


def calcular_por_etapas(superficie_m2, tipo_construccion):
    """
    Calcula materiales, maquinaria y herramientas por etapas de construcción.
    """
    if tipo_construccion not in ETAPAS_CONSTRUCCION:
        raise ValueError(f"Tipo de construcción '{tipo_construccion}' no válido")

    etapas_config = ETAPAS_CONSTRUCCION[tipo_construccion]

    # Escala de días (cantidades fijas de maquinaria)
    if superficie_m2 <= 100:
        factor_dias = 1.0
    elif superficie_m2 <= 200:
        factor_dias = 1.2
    elif superficie_m2 <= 500:
        factor_dias = 1.5
    else:
        factor_dias = 2.0

    resultado_etapas = {}
    maquinaria_total: Dict[str, Dict[str, int]] = {}
    herramientas_total: Dict[str, Dict[str, int]] = {}

    for etapa_nombre, etapa_data in etapas_config.items():
        # Materiales (con 10% desperdicio y redondeado a enteros)
        materiales_etapa = {}
        coef = COEFICIENTES_CONSTRUCCION[tipo_construccion]
        for material in etapa_data["materiales_etapa"]:
            if material in coef:
                cantidad = superficie_m2 * coef[material]
                if cantidad > 0:
                    # Aplicar 10% de desperdicio y redondear hacia arriba
                    cantidad_con_desperdicio = cantidad * 1.10
                    materiales_etapa[material] = math.ceil(cantidad_con_desperdicio)

        # Maquinaria (cantidad fija, sólo varían días)
        maquinaria_etapa = {}
        for maquina, specs in etapa_data["maquinaria"].items():
            if specs["cantidad"] > 0:
                cantidad_final = specs["cantidad"]
                dias_final = int(specs["dias"] * factor_dias)
                maquinaria_etapa[maquina] = {"cantidad": cantidad_final, "dias": dias_final}

                if maquina not in maquinaria_total:
                    maquinaria_total[maquina] = {"cantidad": 0, "dias_total": 0}
                maquinaria_total[maquina]["cantidad"] = max(maquinaria_total[maquina]["cantidad"], cantidad_final)
                maquinaria_total[maquina]["dias_total"] += dias_final

        # Herramientas (puede aumentar 20% para obras > 300 m²)
        herramientas_etapa = {}
        for herramienta, specs in etapa_data["herramientas"].items():
            if specs["cantidad"] > 0:
                cantidad_herr = specs["cantidad"]
                if superficie_m2 > 300:
                    cantidad_herr = int(specs["cantidad"] * 1.2)

                dias_herr = int(specs["dias"] * factor_dias)
                herramientas_etapa[herramienta] = {"cantidad": cantidad_herr, "dias": dias_herr}

                if herramienta not in herramientas_total:
                    herramientas_total[herramienta] = {"cantidad": 0, "dias_total": 0}
                herramientas_total[herramienta]["cantidad"] = max(herramientas_total[herramienta]["cantidad"], cantidad_herr)
                herramientas_total[herramienta]["dias_total"] += dias_herr

        resultado_etapas[etapa_nombre] = {
            "materiales": materiales_etapa,
            "maquinaria": maquinaria_etapa,
            "herramientas": herramientas_etapa,
        }

    return resultado_etapas, maquinaria_total, herramientas_total


def calcular_equipos_herramientas(superficie_m2, tipo_construccion):
    """
    Calcula equipos y herramientas necesarios (compatibilidad con código existente).
    """
    _, maquinaria_total, herramientas_total = calcular_por_etapas(superficie_m2, tipo_construccion)

    equipos_calculados = {m: {"cantidad": d["cantidad"], "dias_uso": d["dias_total"]} for m, d in maquinaria_total.items()}
    herramientas_calculadas = {h: d["cantidad"] for h, d in herramientas_total.items()}

    return equipos_calculados, herramientas_calculadas


def calcular_etapa_por_reglas(
    etapa_slug,
    superficie_m2,
    tipo_construccion,
    contexto=None,
    etiqueta=None,
    etapa_id=None,
    currency: str = 'ARS',
    fx_rate: Optional[Decimal] = None,
    aplicar_desperdicio: bool = True,
    org_id: Optional[int] = None,
):
    reglas = ETAPA_REGLAS_BASE.get(etapa_slug)
    nombre = etiqueta or (reglas['nombre'] if reglas else etapa_slug.replace('-', ' ').title())

    if not reglas:
        return {
            'slug': etapa_slug,
            'nombre': nombre,
            'etapa_id': etapa_id,
            'items': [],
            'subtotal_materiales': 0.0,
            'subtotal_mano_obra': 0.0,
            'subtotal_equipos': 0.0,
            'subtotal_total': 0.0,
            'confianza': 0.25,
            'notas': f'No hay reglas configuradas para la etapa {nombre}.',
            'metodo': 'sin_reglas',
        }

    superficie_dec = _quantize_quantity(_to_decimal(superficie_m2, '0'))
    multiplicador, tipo_legible = obtener_multiplicador_tipo(tipo_construccion)
    multiplicador_dec = _to_decimal(multiplicador, '1')
    items = []
    subtotal_materiales = DECIMAL_ZERO
    subtotal_mano_obra = DECIMAL_ZERO
    subtotal_equipos = DECIMAL_ZERO
    currency = (currency or 'ARS').upper()
    tasa = fx_rate if currency != 'ARS' else None
    cac_context = _get_cac_context_cached()

    for material in reglas.get('materiales', []):
        coef = _to_decimal(material['coef_por_m2'], '0')
        cantidad_base = superficie_dec * coef * multiplicador_dec
        # Si desperdicio está habilitado, sumar 10% a la cantidad base
        if aplicar_desperdicio:
            cantidad_con_desperdicio = float(cantidad_base) * 1.10
            cantidad_final = Decimal(str(math.ceil(cantidad_con_desperdicio)))
            justificacion = 'Coeficiente por m² + 10% desperdicio incluido'
        else:
            cantidad_final = Decimal(str(math.ceil(float(cantidad_base))))
            justificacion = 'Coeficiente por m² (cantidad neta)'

        precio = _precio_referencia(material['codigo'], cac_context, org_id)
        precio_moneda = _convert_currency(precio, currency, tasa)

        # Item con cantidad (incluye desperdicio si está habilitado)
        subtotal = _quantize_currency(cantidad_final * precio_moneda)
        subtotal_materiales += subtotal
        items.append({
            'tipo': 'material',
            'codigo': material['codigo'],
            'descripcion': material['descripcion'],
            'unidad': material.get('unidad', 'unidades'),
            'cantidad': float(cantidad_final),
            'precio_unit': float(precio_moneda),
            'precio_unit_ars': float(precio),
            'origen': 'ia',
            'just': justificacion,
            'material_key': material.get('material_key'),
            'moneda': currency,
            'subtotal': float(subtotal),
        })

    for mano_obra in reglas.get('mano_obra', []):
        coef = _to_decimal(mano_obra['coef_por_m2'], '0')
        cantidad_base = superficie_dec * coef * multiplicador_dec

        # Aplicar margen extra si está habilitado
        if aplicar_desperdicio:
            cantidad_con_extra = float(cantidad_base) * 1.10
            cantidad = Decimal(str(max(1, math.ceil(cantidad_con_extra))))
            justificacion = 'Escala de jornales por m² + 10% margen'
        else:
            cantidad = Decimal(str(max(1, math.ceil(float(cantidad_base)))))
            justificacion = 'Escala de jornales por m² (sin margen)'

        precio = _precio_referencia(mano_obra['codigo'], cac_context, org_id)
        precio_moneda = _convert_currency(precio, currency, tasa)
        subtotal_mano_obra += _quantize_currency(cantidad * precio_moneda)
        items.append({
            'tipo': 'mano_obra',
            'codigo': mano_obra['codigo'],
            'descripcion': mano_obra['descripcion'],
            'unidad': mano_obra.get('unidad', 'jornal'),
            'cantidad': float(cantidad),
            'precio_unit': float(precio_moneda),
            'precio_unit_ars': float(precio),
            'origen': 'ia',
            'just': justificacion,
            'moneda': currency,
            'subtotal': float(_quantize_currency(cantidad * precio_moneda)),
        })

    for equipo in reglas.get('equipos', []):
        dias_por_m2 = _to_decimal(equipo.get('dias_por_m2', 0), '0')
        base = superficie_dec * dias_por_m2 * multiplicador_dec
        dias_min = _to_decimal(equipo.get('min_dias', 0), '0')
        dias = base if base > dias_min else dias_min
        dias = dias if dias > DECIMAL_ZERO else base
        # Redondear días de equipos siempre hacia arriba (2.25 -> 3)
        dias = Decimal(str(math.ceil(float(dias))))
        precio = _precio_referencia(equipo['codigo'], cac_context, org_id)
        precio_moneda = _convert_currency(precio, currency, tasa)
        subtotal_equipos += _quantize_currency(dias * precio_moneda)
        items.append({
            'tipo': 'equipo',
            'codigo': equipo['codigo'],
            'descripcion': equipo['descripcion'],
            'unidad': equipo.get('unidad', 'día'),
            'cantidad': float(dias),
            'precio_unit': float(precio_moneda),
            'precio_unit_ars': float(precio),
            'origen': 'ia',
            'just': 'Dimensionamiento de apoyo mecánico por superficie',
            'moneda': currency,
            'subtotal': float(_quantize_currency(dias * precio_moneda)),
        })

    # Agregar herramientas y maquinaria adicional de ETAPAS_CONSTRUCCION según tipo
    # Mapear etapa_slug a nombre de etapa en ETAPAS_CONSTRUCCION
    etapa_mapping = {
        'pintura': 'terminaciones',
        'terminaciones': 'terminaciones',
        'cimentacion': 'cimentacion_estructura',
        'fundaciones': 'cimentacion_estructura',
        'estructura': 'cimentacion_estructura',
        'mamposteria': 'albanileria',
        'albanileria': 'albanileria'
    }

    etapa_key = etapa_mapping.get(etapa_slug.lower())
    if etapa_key and tipo_construccion in ETAPAS_CONSTRUCCION:
        etapas_config = ETAPAS_CONSTRUCCION[tipo_construccion]
        if etapa_key in etapas_config:
            etapa_data = etapas_config[etapa_key]

            # Escala de días según superficie
            if superficie_dec <= Decimal('100'):
                factor_dias = Decimal('1.0')
            elif superficie_dec <= Decimal('200'):
                factor_dias = Decimal('1.2')
            elif superficie_dec <= Decimal('500'):
                factor_dias = Decimal('1.5')
            else:
                factor_dias = Decimal('2.0')

            # Agregar maquinaria adicional
            for maquina, specs in etapa_data.get('maquinaria', {}).items():
                cantidad = specs['cantidad']
                dias = int(Decimal(str(specs['dias'])) * factor_dias)
                # Precio estimado para maquinaria (40-60% del precio de equipos estándar)
                precio_base = _precio_referencia('EQ-MEZCLADORA', cac_context, org_id)
                precio_moneda = _convert_currency(precio_base * Decimal('0.5'), currency, tasa)
                subtotal_equipos += _quantize_currency(Decimal(str(dias)) * precio_moneda)
                items.append({
                    'tipo': 'equipo',
                    'codigo': f'EQ-{maquina[:20].upper()}',
                    'descripcion': maquina.replace('_', ' ').title(),
                    'unidad': 'día',
                    'cantidad': float(dias),
                    'precio_unit': float(precio_moneda),
                    'precio_unit_ars': float(precio_base * Decimal('0.5')),
                    'origen': 'ia',
                    'just': f'Maquinaria {tipo_legible}',
                    'moneda': currency,
                    'subtotal': float(_quantize_currency(Decimal(str(dias)) * precio_moneda)),
                })

            # Agregar herramientas
            for herramienta, specs in etapa_data.get('herramientas', {}).items():
                cantidad_herr = specs['cantidad']
                if superficie_dec > Decimal('300'):
                    cantidad_herr = int(cantidad_herr * 1.2)
                dias_herr = int(Decimal(str(specs['dias'])) * factor_dias)
                # Precio estimado para herramientas (menor que maquinaria)
                precio_base_herr = _precio_referencia('EQ-MEZCLADORA', cac_context, org_id) * Decimal('0.15')
                precio_moneda_herr = _convert_currency(precio_base_herr, currency, tasa)
                costo_herr = Decimal(str(cantidad_herr)) * precio_moneda_herr
                subtotal_equipos += _quantize_currency(costo_herr)
                items.append({
                    'tipo': 'equipo',
                    'codigo': f'HERR-{herramienta[:15].upper()}',
                    'descripcion': herramienta.replace('_', ' ').title(),
                    'unidad': 'unidades',
                    'cantidad': float(cantidad_herr),
                    'precio_unit': float(precio_moneda_herr),
                    'precio_unit_ars': float(precio_base_herr),
                    'origen': 'ia',
                    'just': f'Herramientas {tipo_legible}',
                    'moneda': currency,
                    'subtotal': float(_quantize_currency(costo_herr)),
                })

    subtotal_total = subtotal_materiales + subtotal_mano_obra + subtotal_equipos
    confianza = min(0.6 + 0.03 * len(items), 0.9)

    return {
        'slug': etapa_slug,
        'nombre': nombre,
        'etapa_id': etapa_id,
        'items': items,
        'subtotal_materiales': float(_quantize_currency(subtotal_materiales)),
        'subtotal_mano_obra': float(_quantize_currency(subtotal_mano_obra)),
        'subtotal_equipos': float(_quantize_currency(subtotal_equipos)),
        'subtotal_total': float(_quantize_currency(subtotal_total)),
        'confianza': float(_redondear(Decimal(str(confianza)), 2)),
        'notas': f"Cálculo determinístico para etapa {nombre} ({tipo_legible}). {reglas.get('notas', '')}",
        'metodo': 'reglas',
        'moneda': currency,
        'cac': {
            'valor': float(_get_cac_context_cached().value),
            'periodo': _get_cac_context_cached().period.isoformat(),
            'multiplicador': float(_get_cac_context_cached().multiplier),
            'proveedor': _get_cac_context_cached().provider,
        },
    }


def calcular_etapas_seleccionadas(
    etapas_payload,
    superficie_m2,
    tipo_calculo='Estándar',
    contexto=None,
    presupuesto_id=None,
    currency: str = 'ARS',
    fx_snapshot: Optional[ExchangeRateSnapshot] = None,
    aplicar_desperdicio: bool = True,
    org_id: Optional[int] = None,
):
    if superficie_m2 is None:
        raise ValueError('superficie_m2 es obligatoria')

    superficie_decimal = _quantize_quantity(_to_decimal(superficie_m2, '0'))
    if superficie_decimal <= DECIMAL_ZERO:
        raise ValueError('superficie_m2 debe ser mayor a cero')

    etapas_payload = etapas_payload or []
    etapa_identificadores = []
    for etapa in etapas_payload:
        if isinstance(etapa, dict):
            nombre = etapa.get('nombre')
            slug = etapa.get('slug') or slugify_etapa(nombre)
            etapa_identificadores.append({'slug': slug, 'nombre': nombre, 'id': etapa.get('id')})
        else:
            slug = slugify_etapa(etapa)
            etapa_identificadores.append({'slug': slug, 'nombre': etapa, 'id': None})

    if not etapa_identificadores:
        raise ValueError('Debes seleccionar al menos una etapa para calcular')

    currency = (currency or 'ARS').upper()
    fx_rate = fx_snapshot.value if fx_snapshot else None

    cache_key = json.dumps({
        'presupuesto_id': str(presupuesto_id) if presupuesto_id else None,
        'slugs': [e['slug'] for e in etapa_identificadores],
        'superficie': float(superficie_decimal),
        'tipo': tipo_calculo,
        'contexto': contexto or {},
        'currency': currency,
        'fx_rate': str(fx_rate) if fx_rate else None,
    }, sort_keys=True)

    if cache_key in STAGE_CALC_CACHE:
        return deepcopy(STAGE_CALC_CACHE[cache_key])

    etapas_resultado = []
    total_parcial = DECIMAL_ZERO
    cac_context = _get_cac_context_cached()

    for etapa in etapa_identificadores:
        resultado = calcular_etapa_por_reglas(
            etapa['slug'],
            superficie_decimal,
            tipo_calculo,
            contexto=contexto,
            etiqueta=etapa.get('nombre'),
            etapa_id=etapa.get('id'),
            currency=currency,
            fx_rate=fx_rate,
            aplicar_desperdicio=aplicar_desperdicio,
            org_id=org_id,
        )
        etapas_resultado.append(resultado)
        total_parcial += _to_decimal(resultado.get('subtotal_total'), '0')

    respuesta = {
        'ok': True,
        'etapas': etapas_resultado,
        'total_parcial': float(_quantize_currency(total_parcial)),
        'moneda': currency,
        'metodo': 'reglas',
        'presupuesto_id': presupuesto_id,
        'tipo_cambio': None,
    }

    if fx_snapshot:
        respuesta['tipo_cambio'] = {
            'valor': float(_to_decimal(fx_snapshot.value, '0')),
            'proveedor': fx_snapshot.provider,
            'base_currency': fx_snapshot.base_currency,
            'quote_currency': fx_snapshot.quote_currency,
            'fetched_at': fx_snapshot.fetched_at.isoformat(),
            'as_of': fx_snapshot.as_of_date.isoformat(),
        }

    respuesta['cac'] = {
        'valor': float(cac_context.value),
        'periodo': cac_context.period.isoformat(),
        'multiplicador': float(cac_context.multiplier),
        'proveedor': cac_context.provider,
    }

    STAGE_CALC_CACHE[cache_key] = deepcopy(respuesta)
    return respuesta

# ----------------- Orquestadores de presupuesto -----------------

def generar_presupuesto_completo(superficie_m2, tipo_construccion, analisis_ia=None):
    """
    Genera un presupuesto completo con materiales, equipos y herramientas.
    """
    try:
        materiales = calcular_materiales(superficie_m2, tipo_construccion)
        equipos, herramientas = calcular_equipos_herramientas(superficie_m2, tipo_construccion)

        resumen_ia = None
        if analisis_ia and client:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "system",
                            "content": "Eres un experto en construcción. Genera recomendaciones técnicas breves y profesionales."
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Basado en este proyecto:\n"
                                f"- Superficie: {superficie_m2}m²\n"
                                f"- Tipo: {tipo_construccion}\n"
                                f"- Materiales calculados: {json.dumps(materiales, indent=2)}\n\n"
                                "Proporciona 3 recomendaciones técnicas breves para optimizar el presupuesto."
                            )
                        }
                    ],
                    max_tokens=300
                )
                resumen_ia = response.choices[0].message.content
            except Exception:
                resumen_ia = "Recomendaciones IA no disponibles en este momento."

        presupuesto = {
            "metadata": {
                "superficie_m2": superficie_m2,
                "tipo_construccion": tipo_construccion,
                "fecha_calculo": datetime.now().isoformat(),
                "factor_precio": COEFICIENTES_CONSTRUCCION[tipo_construccion]["factor_precio"]
            },
            "materiales": materiales,
            "equipos": equipos,
            "herramientas": herramientas,
            "analisis_ia": analisis_ia,
            "recomendaciones_ia": resumen_ia
        }

        return presupuesto

    except Exception as e:
        raise Exception(f"Error generando presupuesto: {str(e)}")


def convertir_pdf_a_base64(archivo_pdf):
    """
    Convierte un archivo PDF a base64 para análisis IA.
    """
    try:
        contenido = archivo_pdf.read()
        base64_encoded = base64.b64encode(contenido).decode('utf-8')
        return base64_encoded
    except Exception as e:
        raise Exception(f"Error procesando PDF: {str(e)}")


def procesar_presupuesto_ia(archivo_pdf=None, metros_cuadrados_manual=None, tipo_construccion_forzado=None):
    """
    Función principal que procesa un presupuesto completo con IA.
    """
    try:
        analisis_ia = None
        if archivo_pdf:
            pdf_base64 = convertir_pdf_a_base64(archivo_pdf)
            analisis_ia = analizar_plano_con_ia(pdf_base64, metros_cuadrados_manual)
            superficie_final = analisis_ia['superficie_total_m2']
            tipo_sugerido = analisis_ia['tipo_construccion_sugerido']
        else:
            superficie_final = float(metros_cuadrados_manual) if metros_cuadrados_manual else 100.0
            tipo_sugerido = "Estándar"
            analisis_ia = {
                "superficie_total_m2": superficie_final,
                "tipo_construccion_sugerido": tipo_sugerido,
                "observaciones": "Cálculo manual sin análisis de plano",
                "confianza_analisis": 1.0,
                "superficie_origen": "manual"
            }

        tipo_final = tipo_construccion_forzado if tipo_construccion_forzado else tipo_sugerido

        # Sistema de etapas
        etapas_resultado, maquinaria_total, herramientas_total = calcular_por_etapas(superficie_final, tipo_final)
        materiales_totales = calcular_materiales(superficie_final, tipo_final)

        # Compatibilidad
        equipos_totales = {m: {"cantidad": d["cantidad"], "dias": d["dias_total"]} for m, d in maquinaria_total.items()}
        herramientas_totales = {h: d["cantidad"] for h, d in herramientas_total.items()}

        coef = COEFICIENTES_CONSTRUCCION[tipo_final]

        presupuesto = {
            "metadata": {
                "superficie_m2": superficie_final,
                "tipo_construccion": tipo_final,
                "fecha_calculo": datetime.now().isoformat(),
                "factor_precio": coef["factor_precio"],
                "metodo_calculo": "etapas_profesional"
            },
            "materiales": materiales_totales,
            "equipos": equipos_totales,
            "herramientas": herramientas_totales,
            "etapas": etapas_resultado,
            "resumen_maquinaria": {
                "total_maquinas": len(maquinaria_total),
                "total_dias_maquinaria": sum(data["dias_total"] for data in maquinaria_total.values()),
                "nivel_tecnologia": {
                    "Económica": "Manual/Básico",
                    "Estándar": "Intermedio/Eléctrico",
                    "Premium": "Avanzado/Robotizado"
                }[tipo_final]
            },
            "analisis_ia": analisis_ia
        }

        return {
            "exito": True,
            "presupuesto": presupuesto,
            "superficie_calculada": superficie_final,
            "tipo_usado": tipo_final
        }

    except Exception as e:
        return {
            "exito": False,
            "error": str(e),
            "superficie_calculada": metros_cuadrados_manual or 0,
            "tipo_usado": tipo_construccion_forzado or "Estándar"
        }
