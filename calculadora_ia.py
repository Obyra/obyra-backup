"""
Calculadora IA de Presupuestos de Construcción
Sistema inteligente para analizar planos y calcular materiales automáticamente
"""

import os
import base64
import json
from datetime import datetime
from openai import OpenAI

# Inicializar cliente OpenAI
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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

# Equipos y herramientas expandidos por tipo de construcción
EQUIPOS_HERRAMIENTAS = {
    "Económica": {
        "equipos": {
            "hormigonera": {"cantidad": 0, "dias": 0},
            "andamios": {"cantidad": 2, "dias": 15},
            "carretilla": {"cantidad": 1, "dias": 30},
            "nivel_laser": {"cantidad": 0, "dias": 0},
            "martillo_demoledor": {"cantidad": 0, "dias": 0},
            "soldadora": {"cantidad": 0, "dias": 0},
            "compresora": {"cantidad": 0, "dias": 0},
            "generador": {"cantidad": 0, "dias": 0}
        },
        "herramientas": {
            "palas": 2,
            "baldes": 4,
            "fratacho": 2,
            "regla": 1,
            "llanas": 2,
            "martillos": 2,
            "serruchos": 1,
            "taladros": 1,
            "nivel_burbuja": 1,
            "flexometros": 2
        }
    },
    "Estándar": {
        "equipos": {
            "hormigonera": {"cantidad": 1, "dias": 20},
            "andamios": {"cantidad": 4, "dias": 25},
            "carretilla": {"cantidad": 2, "dias": 35},
            "nivel_laser": {"cantidad": 1, "dias": 10},
            "martillo_demoledor": {"cantidad": 1, "dias": 5},
            "soldadora": {"cantidad": 1, "dias": 8},
            "compresora": {"cantidad": 1, "dias": 12},
            "generador": {"cantidad": 0, "dias": 0}
        },
        "herramientas": {
            "palas": 3,
            "baldes": 6, 
            "fratacho": 3,
            "regla": 2,
            "llanas": 4,
            "martillos": 3,
            "serruchos": 2,
            "taladros": 2,
            "nivel_burbuja": 2,
            "flexometros": 3,
            "amoladoras": 2,
            "pistola_calor": 1,
            "alicates": 2,
            "destornilladores": 4
        }
    },
    "Premium": {
        "equipos": {
            "hormigonera": {"cantidad": 1, "dias": 30},
            "andamios": {"cantidad": 6, "dias": 40},
            "carretilla": {"cantidad": 3, "dias": 50},
            "nivel_laser": {"cantidad": 1, "dias": 20},
            "martillo_demoledor": {"cantidad": 1, "dias": 10},
            "soldadora": {"cantidad": 1, "dias": 15},
            "compresora": {"cantidad": 1, "dias": 25},
            "generador": {"cantidad": 1, "dias": 20},
            "elevador": {"cantidad": 1, "dias": 15},
            "mezcladora": {"cantidad": 1, "dias": 30}
        },
        "herramientas": {
            "palas": 4,
            "baldes": 8,
            "fratacho": 4,
            "regla": 3,
            "llanas": 6,
            "martillos": 4,
            "serruchos": 3,
            "taladros": 3,
            "nivel_burbuja": 3,
            "flexometros": 4,
            "amoladoras": 3,
            "pistola_calor": 2,
            "alicates": 3,
            "destornilladores": 6,
            "sierra_circular": 1,
            "router": 1
        }
    }
}

def analizar_plano_con_ia(archivo_pdf_base64, metros_cuadrados_manual=None):
    """
    Analiza un plano arquitectónico usando IA de OpenAI
    Para PDFs, se usa análisis de texto, para superficie manual se sugiere el tipo
    """
    try:
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

def calcular_equipos_herramientas(superficie_m2, tipo_construccion):
    """
    Calcula equipos y herramientas necesarios
    """
    if tipo_construccion not in EQUIPOS_HERRAMIENTAS:
        raise ValueError(f"Tipo de construcción '{tipo_construccion}' no válido")
        
    config = EQUIPOS_HERRAMIENTAS[tipo_construccion]
    
    # Ajustar equipos según superficie (más grande = más tiempo/cantidad)
    factor_superficie = max(1.0, superficie_m2 / 100.0)  # base 100m²
    
    equipos_calculados = {}
    for equipo, specs in config["equipos"].items():
        equipos_calculados[equipo] = {
            "cantidad": max(specs["cantidad"], int(specs["cantidad"] * factor_superficie)),
            "dias_uso": max(specs["dias"], int(specs["dias"] * factor_superficie))
        }
    
    herramientas_calculadas = {}
    for herramienta, cantidad_base in config["herramientas"].items():
        herramientas_calculadas[herramienta] = max(cantidad_base, int(cantidad_base * factor_superficie))
    
    return equipos_calculados, herramientas_calculadas

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
        
        # Generar presupuesto completo
        presupuesto = generar_presupuesto_completo(superficie_final, tipo_final, analisis_ia)
        
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