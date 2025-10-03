"""
Calculadora IA de Presupuestos de Construcción
Sistema inteligente para analizar planos y calcular materiales automáticamente
"""

import os
import base64
import json
import math
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, Optional
from unicodedata import normalize
try:  # La librería openai es opcional en entornos locales/lightweight
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - se ejecuta sólo sin dependencia
    OpenAI = None  # type: ignore[assignment]
    client = None  # type: ignore[assignment]
    OPENAI_AVAILABLE = False
else:
    # Inicializar cliente OpenAI sólo cuando la librería esté instalada
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    OPENAI_AVAILABLE = True

from services.cac.cac_service import CACContext, get_cac_context
from services.exchange.base import ExchangeRateSnapshot

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
        "cables_electricos": 8,     # metros por m²
        "caños_agua": 4,           # metros por m²
        "caños_cloacas": 2,        # metros por m²
        "chapas": 0.15,            # m² por m² (techos)
        "tejas": 0.12,             # m² por m² (alt. a chapas)
        "aislacion_termica": 0.8,   # m² por m²
        "yeso": 0.5,               # kg por m² (terminaciones)
        "madera_estructural": 0.05, # m³ por m²
        "vidrios": 0.08,           # m² por m² (ventanas)
        "aberturas_metal": 0.06,   # m² por m² (puertas/ventanas)
        
        # Impermeabilización y terminaciones
        "membrana": 0.8,           # m² por m²
        "pintura": 0.1,            # litros por m²
        "pintura_exterior": 0.08,   # litros por m²
        "sellador": 0.02,          # litros por m²
        
        "factor_precio": 1.0       # factor multiplicador base
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
        "porcelanato": 0.3,        # Incluido parcialmente
        "azulejos": 0.8,           # Más baños
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
        
        "factor_precio": 1.3
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
        "ceramicos": 0.5,          # Menos cerámicos
        "porcelanato": 1.2,        # Más porcelanato
        "azulejos": 1.2,           # Todos los baños
        "cables_electricos": 15,   # Más puntos eléctricos
        "caños_agua": 8,           # Mejores instalaciones
        "caños_cloacas": 4,
        "chapas": 0.1,             # Menos chapas
        "tejas": 0.25,             # Más tejas premium
        "aislacion_termica": 1.8,   # Mejor aislación
        "yeso": 1.2,               # Mejores terminaciones
        "madera_estructural": 0.12,
        "vidrios": 0.18,           # DVH, templados
        "aberturas_metal": 0.15,   # Mejores aberturas
        
        # Terminaciones premium
        "membrana": 1.5,
        "pintura": 0.18,
        "pintura_exterior": 0.15,
        "sellador": 0.05,
        
        "factor_precio": 1.8
    }
}

DECIMAL_ZERO = Decimal('0')
CURRENCY_QUANT = Decimal('0.01')
QUANTITY_QUANT = Decimal('0.001')
_CAC_CONTEXT_CACHE: Dict[str, Any] = {'context': None, 'timestamp': None}


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

# Sistema exhaustivo de cálculo por etapas de construcción con maquinaria completa
ETAPAS_CONSTRUCCION = {
    "Económica": {
        # Etapa 1: Cimentación y estructura (trabajo manual intensivo)
        "cimentacion_estructura": {
            "materiales_etapa": ["cemento", "hierro_8", "hierro_10", "arena", "piedra"],
            "maquinaria": {
                # NIVEL ECONÓMICO: TODO MANUAL, SIN MAQUINARIA PESADA
                "hormigonera_trompo_manual": {"cantidad": 1, "dias": 25},  # Trompo manual 160L
                "carretilla_manual": {"cantidad": 4, "dias": 30},
                "cortadora_hierro_manual": {"cantidad": 1, "dias": 20},  # Cortadora manual de mesa
                "dobladora_hierro_manual": {"cantidad": 1, "dias": 20},  # Dobladora manual
                "andamios_tubulares": {"cantidad": 15, "dias": 35}  # Andamios básicos
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
        # Etapa 2: Albañilería (métodos tradicionales)
        "albanileria": {
            "materiales_etapa": ["ladrillos", "cal", "arena", "cemento"],
            "maquinaria": {
                # NIVEL ECONÓMICO: HERRAMIENTAS BÁSICAS MANUALES
                "mezcladora_manual_80L": {"cantidad": 1, "dias": 35},  # Mezcladora manual
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
        # Etapa 3: Terminaciones
        "terminaciones": {
            "materiales_etapa": ["pintura", "yeso", "ceramicos", "azulejos"],
            "maquinaria": {
                # NIVEL ECONÓMICO: SIN MÁQUINAS, TODO MANUAL
                "escalera_extensible": {"cantidad": 1, "dias": 25},
                "caballete_trabajo": {"cantidad": 4, "dias": 25}
            },
            "herramientas": {
                "rodillos_pintura_18cm": {"cantidad": 8, "dias": 25},
                "pinceles_1_pulgada": {"cantidad": 6, "dias": 25},
                "pinceles_2_pulgadas": {"cantidad": 4, "dias": 25},
                "pinceles_detalle": {"cantidad": 8, "dias": 25},
                "bandejas_pintura": {"cantidad": 6, "dias": 25},
                "espatulas_masilla": {"cantidad": 4, "dias": 20},
                "llana_dentada_6mm": {"cantidad": 2, "dias": 15},
                "llana_dentada_8mm": {"cantidad": 2, "dias": 15},
                "cortadora_ceramico_manual": {"cantidad": 1, "dias": 12},
                "regla_cortaceramico": {"cantidad": 1, "dias": 12},
                "esponja_limpieza": {"cantidad": 12, "dias": 15},
                "nivel_pequeno_20cm": {"cantidad": 4, "dias": 20}
            }
        }
    },
    "Estándar": {
        # Etapa 1: Cimentación con maquinaria eléctrica básica
        "cimentacion_estructura": {
            "materiales_etapa": ["cemento", "hierro_8", "hierro_10", "hierro_12", "arena", "piedra"],
            "maquinaria": {
                # NIVEL ESTÁNDAR: MAQUINARIA ELÉCTRICA BÁSICA
                "minicargadora": {"cantidad": 1, "dias": 15},  # Minicargadora para excavación
                "hormigonera_electrica_300L": {"cantidad": 1, "dias": 25},  # Hormigonera eléctrica
                "cortadora_hierro_electrica": {"cantidad": 1, "dias": 20},  # Cortadora eléctrica
                "dobladora_hierro_electrica": {"cantidad": 1, "dias": 20},  # Dobladora eléctrica
                "atadora_hierro_electrica": {"cantidad": 1, "dias": 15},  # Atadora eléctrica de hierro
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
        # Etapa 2: Albañilería con herramientas eléctricas
        "albanileria": {
            "materiales_etapa": ["ladrillos", "cal", "arena", "cemento"],
            "maquinaria": {
                # NIVEL ESTÁNDAR: MÁQUINAS ELÉCTRICAS INTERMEDIAS
                "mezcladora_electrica_200L": {"cantidad": 1, "dias": 30},  # Mezcladora eléctrica
                "cortadora_ladrillo_electrica": {"cantidad": 1, "dias": 25},  # Cortadora eléctrica
                "elevador_materiales_electrico": {"cantidad": 1, "dias": 30},  # Elevador eléctrico
                "bomba_mortero_electrica": {"cantidad": 1, "dias": 20},  # Bomba de mortero
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
        # Etapa 3: Terminaciones con equipos semiautomáticos
        "terminaciones": {
            "materiales_etapa": ["pintura", "pintura_exterior", "yeso", "ceramicos", "azulejos"],
            "maquinaria": {
                # NIVEL ESTÁNDAR: EQUIPOS ELÉCTRICOS DE TERMINACIÓN
                "compresora_pintura": {"cantidad": 1, "dias": 20},  # Compresora para pintura
                "lijadora_pared_electrica": {"cantidad": 1, "dias": 15},  # Lijadora de pared
                "cortadora_ceramicos_electrica": {"cantidad": 1, "dias": 15},  # Cortadora eléctrica
                "proyectora_yeso": {"cantidad": 1, "dias": 12},  # Proyectora de yeso
                "pulidora_pisos": {"cantidad": 1, "dias": 10}  # Pulidora eléctrica
            },
            "herramientas": {
                "pistola_pintura_electrica": {"cantidad": 2, "dias": 20},
                "lijadora_orbital": {"cantidad": 2, "dias": 15},
                "taladro_mezclador": {"cantidad": 1, "dias": 15},
                "nivel_laser_pequeno": {"cantidad": 2, "dias": 20},
                "aspiradora_seco_humedo": {"cantidad": 1, "dias": 20},
                "esmeril_angular": {"cantidad": 1, "dias": 15},
                "caladora_profesional": {"cantidad": 1, "dias": 10}
            }
        }
    },
    "Premium": {
        # Etapa 1: Cimentación con maquinaria de alta tecnología y velocidad
        "cimentacion_estructura": {
            "materiales_etapa": ["cemento", "hierro_8", "hierro_10", "hierro_12", "arena", "piedra"],
            "maquinaria": {
                # NIVEL PREMIUM: MAQUINARIA DE ALTA VELOCIDAD Y AUTOMATIZACIÓN
                "excavadora_hidraulica_CAT": {"cantidad": 1, "dias": 8},  # Excavadora de alta gama
                "bomba_hormigon_autopropulsada": {"cantidad": 1, "dias": 10},  # Bomba autopropulsada
                "grua_torre_computarizada": {"cantidad": 1, "dias": 40},  # Grúa con control computarizado
                "planta_hormigon_automatica": {"cantidad": 1, "dias": 12},  # Planta automática móvil
                "montacargas_telescopico": {"cantidad": 2, "dias": 35},  # Montacargas telescópicos
                "compactadora_vibratoria": {"cantidad": 1, "dias": 8},  # Compactadora de alta frecuencia
                "cortadora_hierro_CNC": {"cantidad": 1, "dias": 15},  # Cortadora CNC automática
                "dobladora_hierro_automatica": {"cantidad": 1, "dias": 15},  # Dobladora automática
                "atadora_hierro_robotica": {"cantidad": 1, "dias": 12}  # Atadora robótica
            },
            "herramientas": {
                "estacion_total_GPS": {"cantidad": 1, "dias": 20},  # Topografía GPS de precisión
                "vibrador_alta_frecuencia": {"cantidad": 3, "dias": 15},
                "martillo_hidraulico": {"cantidad": 1, "dias": 10},
                "nivel_laser_3D": {"cantidad": 2, "dias": 20},
                "drone_supervision": {"cantidad": 1, "dias": 40},  # Drone para monitoreo
                "soldadora_robotica": {"cantidad": 1, "dias": 15}
            }
        },
        # Etapa 2: Albañilería automatizada con robots
        "albanileria": {
            "materiales_etapa": ["ladrillos", "cal", "arena", "cemento"],
            "maquinaria": {
                # NIVEL PREMIUM: ROBOTS Y AUTOMATIZACIÓN COMPLETA
                "robot_albanil_SAM": {"cantidad": 1, "dias": 20},  # Robot albañil automático
                "montacargas_materiales": {"cantidad": 2, "dias": 30},  # Montacargas de materiales
                "mezcladora_robotizada_500L": {"cantidad": 1, "dias": 25},  # Mezcladora robótica
                "bomba_mortero_automatica": {"cantidad": 1, "dias": 15},  # Bomba automática
                "cortadora_laser_materiales": {"cantidad": 1, "dias": 12},  # Cortadora láser
                "elevador_tijera_autopropulsado": {"cantidad": 2, "dias": 30},  # Elevadores autopropulsados
                "sistema_transporte_automatico": {"cantidad": 1, "dias": 25}  # Sistema de transporte
            },
            "herramientas": {
                "andamios_autoelevables": {"cantidad": 4, "dias": 30},
                "sistema_control_calidad": {"cantidad": 1, "dias": 35},  # Sistema de control de calidad
                "martillo_neumatico_profesional": {"cantidad": 2, "dias": 20},
                "nivel_laser_rotativo_premium": {"cantidad": 2, "dias": 35},
                "aspiradora_industrial_robotica": {"cantidad": 1, "dias": 25},
                "soldadora_automatica_MIG": {"cantidad": 1, "dias": 15}
            }
        },
        # Etapa 3: Terminaciones robotizadas y de alta velocidad
        "terminaciones": {
            "materiales_etapa": ["pintura", "pintura_exterior", "yeso", "porcelanato", "azulejos"],
            "maquinaria": {
                # NIVEL PREMIUM: TERMINACIONES ROBOTIZADAS Y VELOCES
                "robot_pintura_automatico": {"cantidad": 1, "dias": 10},  # Robot de pintura
                "sistema_proyeccion_yeso_robotico": {"cantidad": 1, "dias": 8},  # Proyección robótica
                "cortadora_porcelanato_CNC": {"cantidad": 1, "dias": 10},  # Cortadora CNC porcelanato
                "pulidora_pisos_robotica": {"cantidad": 1, "dias": 8},  # Pulidora robótica
                "montacargas_terminaciones": {"cantidad": 1, "dias": 20},  # Montacargas especializado
                "lijadora_pared_automatica": {"cantidad": 1, "dias": 6},  # Lijadora automática
                "sistema_ventilacion_controlado": {"cantidad": 1, "dias": 20}  # Sistema de ventilación
            },
            "herramientas": {
                "pistola_pintura_electrostatica": {"cantidad": 2, "dias": 12},  # Pintura electrostática
                "medidor_laser_3D": {"cantidad": 2, "dias": 15},  # Medición 3D
                "sistema_control_humedad": {"cantidad": 1, "dias": 15},  # Control de humedad
                "aspiradora_HEPA_profesional": {"cantidad": 1, "dias": 15},  # Aspiradora HEPA
                "cepillo_pulidora_diamante": {"cantidad": 2, "dias": 10},  # Pulidora de diamante
                "nivel_laser_autonivelante": {"cantidad": 3, "dias": 20},  # Nivel autonivelante
                "compresor_silencioso_premium": {"cantidad": 1, "dias": 15}  # Compresor premium
            }
        }
    }
}

def analizar_plano_con_ia(archivo_pdf_base64, metros_cuadrados_manual=None):
    """
    Analiza un plano arquitectónico usando IA de OpenAI
    Para PDFs, se usa análisis de texto, para superficie manual se sugiere el tipo
    """
    try:
        if not client:  # OpenAI no disponible → devolver un resultado estimado
            superficie_fallback = (
                float(metros_cuadrados_manual) if metros_cuadrados_manual else 100.0
            )
            return {
                "superficie_total_m2": superficie_fallback,
                "tipo_construccion_sugerido": "Estándar",
                "observaciones": (
                    "OpenAI no está instalado o configurado. Se devolvió una estimación "
                    "basada en los datos proporcionados."
                ),
                "confianza_analisis": 0.2 if not metros_cuadrados_manual else 0.6,
                "superficie_origen": "manual" if metros_cuadrados_manual else "estimado",
                "openai_disponible": False,
            }

        # Si hay superficie manual, hacer análisis inteligente sin imagen
        if metros_cuadrados_manual:
            superficie_float = float(metros_cuadrados_manual)
            
            # el modelo gpt-4o es el más reciente lanzado en mayo 2024
            # no cambiar a menos que el usuario lo solicite específicamente
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """Eres un arquitecto y calculista experto en construcción argentina. 
                        Basándote en la superficie proporcionada, sugiere el tipo de construcción más apropiado.
                        Responde en formato JSON con las siguientes claves:
                        - superficie_total_m2: número (superficie proporcionada)
                        - tipo_construccion_sugerido: string ("Económica", "Estándar" o "Premium")
                        - observaciones: string (recomendaciones técnicas)
                        - confianza_analisis: número del 0 al 1"""
                    },
                    {
                        "role": "user",
                        "content": f"Para una construcción de {superficie_float}m², sugiere el tipo de construcción más apropiado y proporciona recomendaciones técnicas para Argentina."
                    }
                ],
                response_format={"type": "json_object"},
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            if content:
                resultado = json.loads(content)
                resultado['superficie_total_m2'] = superficie_float
                resultado['superficie_origen'] = 'manual'
                return resultado
        
        # Si no hay superficie manual, usar análisis básico
        print("Análisis de PDF directo no disponible - usando superficie manual si está disponible")
        return {
            "superficie_total_m2": float(metros_cuadrados_manual) if metros_cuadrados_manual else 100.0,
            "tipo_construccion_sugerido": "Estándar",
            "observaciones": "Análisis basado en superficie proporcionada. PDF cargado correctamente pero requiere superficie manual.",
            "confianza_analisis": 0.8 if metros_cuadrados_manual else 0.3,
            "superficie_origen": "manual" if metros_cuadrados_manual else "estimado"
        }
        
    except Exception as e:
        print(f"Error en análisis IA: {e}")
        # Fallback con datos manuales si falla la IA
        return {
            "superficie_total_m2": float(metros_cuadrados_manual) if metros_cuadrados_manual else 100.0,
            "tipo_construccion_sugerido": "Estándar",
            "observaciones": f"Error en análisis: {str(e)}. Usando superficie manual proporcionada.",
            "confianza_analisis": 0.5,
            "superficie_origen": "manual_fallback"
        }

def calcular_materiales(superficie_m2, tipo_construccion):
    """
    Calcula la cantidad de materiales necesarios
    """
    if tipo_construccion not in COEFICIENTES_CONSTRUCCION:
        raise ValueError(f"Tipo de construcción '{tipo_construccion}' no válido")
        
    coef = COEFICIENTES_CONSTRUCCION[tipo_construccion]
    
    materiales = {}
    for material, coef_por_m2 in coef.items():
        if material != "factor_precio":
            cantidad = superficie_m2 * coef_por_m2
            materiales[material] = round(cantidad, 2)
    
    return materiales

def calcular_por_etapas(superficie_m2, tipo_construccion):
    """
    Calcula materiales, maquinaria y herramientas por etapas de construcción
    """
    if tipo_construccion not in ETAPAS_CONSTRUCCION:
        raise ValueError(f"Tipo de construcción '{tipo_construccion}' no válido")
    
    etapas_config = ETAPAS_CONSTRUCCION[tipo_construccion]
    
    # FACTOR DE ESCALA MÁS REALISTA: Solo aumentar levemente para obras grandes
    if superficie_m2 <= 100:
        factor_cantidad = 1.0
        factor_dias = 1.0
    elif superficie_m2 <= 200:
        factor_cantidad = 1.0  # No aumentar cantidad
        factor_dias = 1.2      # Solo aumentar días 20%
    elif superficie_m2 <= 500:
        factor_cantidad = 1.0  # No aumentar cantidad para maquinaria
        factor_dias = 1.5      # Aumentar días 50%
    else:
        factor_cantidad = 1.0  # Cantidad máxima fija
        factor_dias = 2.0      # Doblar días para obras muy grandes
    
    resultado_etapas = {}
    maquinaria_total = {}
    herramientas_total = {}
    
    for etapa_nombre, etapa_data in etapas_config.items():
        # Calcular materiales para esta etapa
        materiales_etapa = {}
        coef = COEFICIENTES_CONSTRUCCION[tipo_construccion]
        
        for material in etapa_data["materiales_etapa"]:
            if material in coef:
                cantidad = superficie_m2 * coef[material]
                if cantidad > 0:
                    materiales_etapa[material] = round(cantidad, 2)
        
        # Calcular maquinaria para esta etapa CON CANTIDADES REALISTAS
        maquinaria_etapa = {}
        for maquina, specs in etapa_data["maquinaria"].items():
            if specs["cantidad"] > 0:
                # Las cantidades se mantienen fijas, solo los días aumentan
                cantidad_final = specs["cantidad"]
                dias_final = int(specs["dias"] * factor_dias)
                
                maquinaria_etapa[maquina] = {
                    "cantidad": cantidad_final,
                    "dias": dias_final
                }
                
                # Sumar al total general
                if maquina not in maquinaria_total:
                    maquinaria_total[maquina] = {"cantidad": 0, "dias_total": 0}
                maquinaria_total[maquina]["cantidad"] = max(maquinaria_total[maquina]["cantidad"], cantidad_final)
                maquinaria_total[maquina]["dias_total"] += dias_final
        
        # Calcular herramientas para esta etapa
        herramientas_etapa = {}
        for herramienta, specs in etapa_data["herramientas"].items():
            if specs["cantidad"] > 0:
                # Para herramientas pequeñas, sí puede aumentar levemente la cantidad
                cantidad_herramienta = specs["cantidad"]
                if superficie_m2 > 300:
                    cantidad_herramienta = int(specs["cantidad"] * 1.2)  # 20% más para obras grandes
                
                dias_herramienta = int(specs["dias"] * factor_dias)
                
                herramientas_etapa[herramienta] = {
                    "cantidad": cantidad_herramienta,
                    "dias": dias_herramienta
                }
                
                # Sumar al total general
                if herramienta not in herramientas_total:
                    herramientas_total[herramienta] = {"cantidad": 0, "dias_total": 0}
                herramientas_total[herramienta]["cantidad"] = max(herramientas_total[herramienta]["cantidad"], cantidad_herramienta)
                herramientas_total[herramienta]["dias_total"] += dias_herramienta
        
        # Guardar resultado de la etapa
        resultado_etapas[etapa_nombre] = {
            "materiales": materiales_etapa,
            "maquinaria": maquinaria_etapa,
            "herramientas": herramientas_etapa
        }
    
    return resultado_etapas, maquinaria_total, herramientas_total

def calcular_equipos_herramientas(superficie_m2, tipo_construccion):
    """
    Calcula equipos y herramientas necesarios (función compatible con código existente)
    """
    _, maquinaria_total, herramientas_total = calcular_por_etapas(superficie_m2, tipo_construccion)
    
    # Convertir formato para compatibilidad
    equipos_calculados = {}
    for maquina, data in maquinaria_total.items():
        equipos_calculados[maquina] = {
            "cantidad": data["cantidad"],
            "dias_uso": data["dias_total"]
        }
    
    herramientas_calculadas = {}
    for herramienta, data in herramientas_total.items():
        herramientas_calculadas[herramienta] = data["cantidad"]

    return equipos_calculados, herramientas_calculadas


# --- Nueva lógica de etapas IA determinísticas ---

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
}

ETAPA_REGLAS_BASE = {
    'excavacion': {
        'nombre': 'Excavación',
        'materiales': [
            {'codigo': 'MAT-ARENA', 'material_key': 'arena', 'descripcion': 'Arena gruesa para estabilización', 'unidad': 'm³', 'coef_por_m2': 0.04},
            {'codigo': 'MAT-PIEDRA', 'material_key': 'piedra', 'descripcion': 'Piedra partida 3/4"', 'unidad': 'm³', 'coef_por_m2': 0.03}
        ],
        'mano_obra': [
            {'codigo': 'MO-MOVSUE', 'descripcion': 'Cuadrilla movimiento de suelos', 'unidad': 'jornal', 'coef_por_m2': 0.06}
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
            {'codigo': 'MO-FUND', 'descripcion': 'Cuadrilla de fundaciones', 'unidad': 'jornal', 'coef_por_m2': 0.065}
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
            {'codigo': 'MO-ESTR', 'descripcion': 'Cuadrilla de estructura', 'unidad': 'jornal', 'coef_por_m2': 0.075}
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
            {'codigo': 'MO-MAMPO', 'descripcion': 'Oficial + ayudante de albañilería', 'unidad': 'jornal', 'coef_por_m2': 0.07}
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
            {'codigo': 'MO-TECH', 'descripcion': 'Equipo montaje de cubiertas', 'unidad': 'jornal', 'coef_por_m2': 0.055}
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
            {'codigo': 'MO-ELEC', 'descripcion': 'Electricista matriculado + ayudante', 'unidad': 'jornal', 'coef_por_m2': 0.045}
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
            {'codigo': 'MO-SANIT', 'descripcion': 'Instalador sanitario', 'unidad': 'jornal', 'coef_por_m2': 0.042}
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
            {'codigo': 'MO-GAS', 'descripcion': 'Gasista matriculado', 'unidad': 'jornal', 'coef_por_m2': 0.028}
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
            {'codigo': 'MO-REV', 'descripcion': 'Oficial revocador', 'unidad': 'jornal', 'coef_por_m2': 0.05}
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
            {'codigo': 'MO-REV', 'descripcion': 'Terminación de yeseros', 'unidad': 'jornal', 'coef_por_m2': 0.038}
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
            {'codigo': 'MO-PISOS', 'descripcion': 'Colocador especializado', 'unidad': 'jornal', 'coef_por_m2': 0.05}
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
            {'codigo': 'MO-CARP', 'descripcion': 'Carpintero instalador', 'unidad': 'jornal', 'coef_por_m2': 0.04}
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
            {'codigo': 'MO-PINT', 'descripcion': 'Equipo de pintores', 'unidad': 'jornal', 'coef_por_m2': 0.045}
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
            {'codigo': 'MO-SERV', 'descripcion': 'Técnicos especializados', 'unidad': 'jornal', 'coef_por_m2': 0.03}
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
            {'codigo': 'MO-LIM', 'descripcion': 'Equipo de limpieza profesional', 'unidad': 'jornal', 'coef_por_m2': 0.02}
        ],
        'equipos': [],
        'notas': 'Limpieza fina, sellado y entrega de obra.'
    },
}

STAGE_CALC_CACHE = {}


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


def _precio_referencia(codigo: str, cac_context: CACContext) -> Decimal:
    base = _to_decimal(PRECIO_REFERENCIA.get(codigo), '0')
    return _quantize_currency(base * cac_context.multiplier)


def _redondear(valor: Decimal, ndigits: int = 2) -> Decimal:
    quant = Decimal('1').scaleb(-ndigits)
    return valor.quantize(quant, rounding=ROUND_HALF_UP)


def calcular_etapa_por_reglas(
    etapa_slug,
    superficie_m2,
    tipo_construccion,
    contexto=None,
    etiqueta=None,
    etapa_id=None,
    currency: str = 'ARS',
    fx_rate: Optional[Decimal] = None,
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
        cantidad = _quantize_quantity(superficie_dec * coef * multiplicador_dec)
        precio = _precio_referencia(material['codigo'], cac_context)
        precio_moneda = _convert_currency(precio, currency, tasa)
        subtotal_materiales += _quantize_currency(cantidad * precio_moneda)
        items.append({
            'tipo': 'material',
            'codigo': material['codigo'],
            'descripcion': material['descripcion'],
            'unidad': material.get('unidad', 'unidades'),
            'cantidad': float(cantidad),
            'precio_unit': float(precio_moneda),
            'precio_unit_ars': float(precio),
            'origen': 'ia',
            'just': 'Coeficiente por m² ajustado por tipología',
            'material_key': material.get('material_key'),
            'moneda': currency,
            'subtotal': float(_quantize_currency(cantidad * precio_moneda)),
        })

    for mano_obra in reglas.get('mano_obra', []):
        coef = _to_decimal(mano_obra['coef_por_m2'], '0')
        cantidad = superficie_dec * coef * multiplicador_dec
        cantidad = _quantize_quantity(max(_to_decimal(1, '1'), cantidad))
        precio = _precio_referencia(mano_obra['codigo'], cac_context)
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
            'just': 'Escala de jornales por m²',
            'moneda': currency,
            'subtotal': float(_quantize_currency(cantidad * precio_moneda)),
        })

    for equipo in reglas.get('equipos', []):
        dias_por_m2 = _to_decimal(equipo.get('dias_por_m2', 0), '0')
        base = superficie_dec * dias_por_m2 * multiplicador_dec
        dias_min = _to_decimal(equipo.get('min_dias', 0), '0')
        dias = base if base > dias_min else dias_min
        dias = _quantize_quantity(dias if dias > DECIMAL_ZERO else base)
        precio = _precio_referencia(equipo['codigo'], cac_context)
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
            'valor': float(cac_context.value),
            'periodo': cac_context.period.isoformat(),
            'multiplicador': float(cac_context.multiplier),
            'proveedor': cac_context.provider,
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


def generar_presupuesto_completo(superficie_m2, tipo_construccion, analisis_ia=None):
    """
    Genera un presupuesto completo con materiales, equipos y herramientas
    """
    try:
        # Calcular componentes
        materiales = calcular_materiales(superficie_m2, tipo_construccion)
        equipos, herramientas = calcular_equipos_herramientas(superficie_m2, tipo_construccion)
        
        # Generar resumen con IA
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
                            "content": f"""
                            Basado en este proyecto de construcción:
                            - Superficie: {superficie_m2}m²
                            - Tipo: {tipo_construccion}
                            - Materiales calculados: {json.dumps(materiales, indent=2)}
                            
                            Proporciona 3 recomendaciones técnicas breves para optimizar este presupuesto.
                            """
                        }
                    ],
                    max_tokens=300
                )
                resumen_ia = response.choices[0].message.content
            except:
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
    Convierte un archivo PDF a base64 para análisis IA
    """
    try:
        contenido = archivo_pdf.read()
        base64_encoded = base64.b64encode(contenido).decode('utf-8')
        return base64_encoded
    except Exception as e:
        raise Exception(f"Error procesando PDF: {str(e)}")

# Función principal para uso desde Flask
def procesar_presupuesto_ia(archivo_pdf=None, metros_cuadrados_manual=None, tipo_construccion_forzado=None):
    """
    Función principal que procesa un presupuesto completo con IA
    """
    try:
        # Análisis del plano si se proporciona
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
        
        # Usar tipo forzado si se especifica
        tipo_final = tipo_construccion_forzado if tipo_construccion_forzado else tipo_sugerido
        
        # Generar presupuesto con sistema de etapas
        etapas_resultado, maquinaria_total, herramientas_total = calcular_por_etapas(superficie_final, tipo_final)
        materiales_totales = calcular_materiales(superficie_final, tipo_final)
        
        # Formatear para compatibilidad
        equipos_totales = {}
        for maquina, data in maquinaria_total.items():
            equipos_totales[maquina] = {
                "cantidad": data["cantidad"],
                "dias": data["dias_total"]
            }
        
        herramientas_totales = {}
        for herramienta, data in herramientas_total.items():
            herramientas_totales[herramienta] = data["cantidad"]
        
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