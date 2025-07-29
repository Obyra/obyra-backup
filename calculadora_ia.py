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

# Coeficientes de construcción por tipo y m²
COEFICIENTES_CONSTRUCCION = {
    "Económica": {
        "ladrillos": 55,      # unidades por m²
        "cemento": 0.25,      # bolsas por m²
        "cal": 3,             # kg por m²
        "arena": 0.03,        # m³ por m²
        "piedra": 0.02,       # m³ por m²
        "hierro_8": 2.5,      # kg por m²
        "hierro_10": 1.8,     # kg por m²
        "hierro_12": 1.2,     # kg por m²
        "membrana": 0.8,      # m² por m²
        "pintura": 0.1,       # litros por m²
        "factor_precio": 1.0   # factor multiplicador base
    },
    "Estándar": {
        "ladrillos": 60,
        "cemento": 0.3,
        "cal": 4,
        "arena": 0.035,
        "piedra": 0.025,
        "hierro_8": 3.5,
        "hierro_10": 2.2,
        "hierro_12": 1.5,
        "membrana": 1.1,
        "pintura": 0.13,
        "factor_precio": 1.3
    },
    "Premium": {
        "ladrillos": 65,
        "cemento": 0.35,
        "cal": 5,
        "arena": 0.04,
        "piedra": 0.03,
        "hierro_8": 4,
        "hierro_10": 2.8,
        "hierro_12": 2,
        "membrana": 1.5,
        "pintura": 0.18,
        "factor_precio": 1.8
    }
}

# Equipos y herramientas por tipo de construcción
EQUIPOS_HERRAMIENTAS = {
    "Económica": {
        "equipos": {
            "hormigonera": {"cantidad": 0, "dias": 0},
            "andamios": {"modulos": 2, "dias": 15},
            "carretilla": {"cantidad": 1, "dias": 30},
            "nivel_laser": {"cantidad": 0, "dias": 0}
        },
        "herramientas": {
            "palas": 2,
            "baldes": 4,
            "fratacho": 2,
            "regla": 1
        }
    },
    "Estándar": {
        "equipos": {
            "hormigonera": {"cantidad": 1, "dias": 20},
            "andamios": {"modulos": 4, "dias": 25},
            "carretilla": {"cantidad": 2, "dias": 35},
            "nivel_laser": {"cantidad": 0, "dias": 0}
        },
        "herramientas": {
            "palas": 3,
            "baldes": 6,
            "fratacho": 3,
            "regla": 2
        }
    },
    "Premium": {
        "equipos": {
            "hormigonera": {"cantidad": 1, "dias": 30},
            "andamios": {"modulos": 6, "dias": 40},
            "carretilla": {"cantidad": 3, "dias": 45},
            "nivel_laser": {"cantidad": 1, "dias": 10}
        },
        "herramientas": {
            "palas": 4,
            "baldes": 8,
            "fratacho": 4,
            "regla": 2
        }
    }
}

def analizar_plano_con_ia(archivo_pdf_base64, metros_cuadrados_manual=None):
    """
    Analiza un plano arquitectónico usando IA de OpenAI
    """
    try:
        # el modelo gpt-4o es el más reciente lanzado en mayo 2024
        # no cambiar a menos que el usuario lo solicite específicamente
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """Eres un arquitecto y calculista experto en construcción argentina. 
                    Analiza planos arquitectónicos y extrae información técnica precisa.
                    Responde en formato JSON con las siguientes claves:
                    - superficie_total_m2: número (superficie total construida)
                    - tipo_construccion_sugerido: string ("Económica", "Estándar" o "Premium")
                    - observaciones: string (detalles técnicos relevantes)
                    - confianza_analisis: número del 0 al 1 (qué tan confiable es el análisis)"""
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Analiza este plano arquitectónico. {'Superficie manual indicada: ' + str(metros_cuadrados_manual) + 'm²' if metros_cuadrados_manual else 'Calcula automáticamente la superficie total.'}"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:application/pdf;base64,{archivo_pdf_base64}"
                            }
                        }
                    ]
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=1000
        )
        
        content = response.choices[0].message.content
        if content:
            resultado = json.loads(content)
        else:
            raise Exception("No se recibió respuesta de la IA")
        
        # Si se proporcionó superficie manual, usarla como principal
        if metros_cuadrados_manual:
            resultado['superficie_total_m2'] = float(metros_cuadrados_manual)
            resultado['superficie_origen'] = 'manual'
        else:
            resultado['superficie_origen'] = 'ia_analisis'
            
        return resultado
        
    except Exception as e:
        print(f"Error en análisis IA: {e}")
        # Fallback con datos manuales si falla la IA
        return {
            "superficie_total_m2": float(metros_cuadrados_manual) if metros_cuadrados_manual else 100.0,
            "tipo_construccion_sugerido": "Estándar",
            "observaciones": f"Error en análisis automático: {str(e)}. Usando datos manuales.",
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