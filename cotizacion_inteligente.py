"""
Módulo de Presupuesto Estimado Automático - OBYRA IA
Sistema avanzado de presupuestación con cálculos automáticos de materiales,
análisis inteligente de costos y estimación por IA.
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
import json
import math
from app import db
from models import *
from utils import *

cotizacion_bp = Blueprint('cotizacion', __name__)

@cotizacion_bp.route('/')
@login_required
def dashboard():
    """Dashboard del módulo de cotización inteligente"""
    # Estadísticas de cotizaciones
    total_cotizaciones = Presupuesto.query.count()
    cotizaciones_aprobadas = Presupuesto.query.filter_by(estado='aprobado').count()
    tasa_conversion = (cotizaciones_aprobadas / total_cotizaciones * 100) if total_cotizaciones > 0 else 0
    
    # Cotizaciones recientes
    cotizaciones_recientes = Presupuesto.query.order_by(Presupuesto.fecha_creacion.desc()).limit(5).all()
    
    return render_template('cotizacion/dashboard.html',
                         total_cotizaciones=total_cotizaciones,
                         cotizaciones_aprobadas=cotizaciones_aprobadas,
                         tasa_conversion=tasa_conversion,
                         cotizaciones_recientes=cotizaciones_recientes)

@cotizacion_bp.route('/calculadora_inteligente')
@cotizacion_bp.route('/calculadora')
@login_required
def calculadora_inteligente():
    """Calculadora inteligente de materiales y costos"""
    # Precios base de materiales (actualizables)
    precios_base = obtener_precios_base_materiales()
    tipos_obra = obtener_tipos_obra_disponibles()
    
    return render_template('cotizacion/calculadora.html',
                         precios_base=precios_base,
                         tipos_obra=tipos_obra)

@cotizacion_bp.route('/calcular_materiales', methods=['POST'])
@login_required
def calcular_materiales():
    """Calcula automáticamente materiales necesarios según tipo de obra"""
    data = request.get_json()
    
    try:
        tipo_obra = data.get('tipo_obra')
        metros_cuadrados = float(data.get('metros_cuadrados', 0))
        calidad = data.get('calidad', 'estandar')  # economica, estandar, premium
        ubicacion = data.get('ubicacion', 'otros')
        
        # Calcular materiales automáticamente
        calculo = calcular_materiales_automatico(tipo_obra, metros_cuadrados, calidad, ubicacion)
        
        # Guardar datos en la sesión para el flujo completo
        from flask import session
        session['presupuesto_datos'] = {
            'tipo_obra': tipo_obra,
            'metros_cuadrados': metros_cuadrados,
            'calidad': calidad,
            'ubicacion': ubicacion,
            'calculo': calculo,
            'paso_actual': 2
        }
        
        return jsonify({
            'success': True,
            'calculo': calculo,
            'siguiente_paso': url_for('cotizacion.paso_revision')
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@cotizacion_bp.route('/paso-revision')
@login_required
def paso_revision():
    """Paso 3: Revisión del presupuesto calculado por IA"""
    from flask import session
    datos = session.get('presupuesto_datos')
    
    if not datos:
        flash('No hay datos de presupuesto para revisar. Comience el proceso nuevamente.', 'warning')
        return redirect(url_for('cotizacion.calculadora_inteligente'))
    
    return render_template('cotizacion/revision.html', datos=datos)

@cotizacion_bp.route('/generar-pdf')
@login_required
def generar_pdf():
    """Genera PDF del presupuesto final"""
    from flask import session
    datos = session.get('presupuesto_datos')
    
    if not datos:
        return jsonify({'success': False, 'error': 'No hay datos para generar PDF'}), 400
    
    try:
        # Generar PDF
        pdf_filename = crear_pdf_presupuesto(datos, current_user)
        pdf_url = url_for('static', filename=f'pdfs/{pdf_filename}', _external=True)
        
        # Limpiar sesión
        session.pop('presupuesto_datos', None)
        
        return jsonify({
            'success': True,
            'pdf_url': pdf_url,
            'mensaje': 'PDF generado correctamente'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@cotizacion_bp.route('/optimizar_presupuesto', methods=['POST'])
@login_required
def optimizar_presupuesto():
    """Optimiza un presupuesto existente con sugerencias inteligentes"""
    presupuesto_id = request.json.get('presupuesto_id')
    
    try:
        presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
        optimizaciones = generar_optimizaciones_presupuesto(presupuesto)
        
        return jsonify({
            'success': True,
            'optimizaciones': optimizaciones
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@cotizacion_bp.route('/analisis_competencia')
@login_required
def analisis_competencia():
    """Análisis de precios de competencia y posicionamiento"""
    analisis = generar_analisis_competencia()
    return render_template('cotizacion/analisis_competencia.html', analisis=analisis)

@cotizacion_bp.route('/plantillas_cotizacion')
@login_required
def plantillas_cotizacion():
    """Plantillas predefinidas para diferentes tipos de obra"""
    plantillas = obtener_plantillas_cotizacion()
    return render_template('cotizacion/plantillas.html', plantillas=plantillas)

@cotizacion_bp.route('/crear_desde_plantilla/<int:plantilla_id>')
@login_required
def crear_desde_plantilla(plantilla_id):
    """Crea una cotización desde una plantilla predefinida"""
    plantilla = obtener_plantilla_por_id(plantilla_id)
    return render_template('cotizacion/crear_desde_plantilla.html', plantilla=plantilla)

@cotizacion_bp.route('/seguimiento_precios')
@login_required
def seguimiento_precios():
    """Seguimiento de variación de precios de materiales"""
    variaciones = obtener_variaciones_precios()
    return render_template('cotizacion/seguimiento_precios.html', variaciones=variaciones)

# Funciones auxiliares

def obtener_precios_base_materiales():
    """Obtiene precios base actualizados de materiales"""
    return {
        'cemento_portland': {'precio': 1200, 'unidad': 'bolsa', 'actualizacion': '2025-01-01'},
        'arena_gruesa': {'precio': 8500, 'unidad': 'm³', 'actualizacion': '2025-01-01'},
        'arena_fina': {'precio': 9200, 'unidad': 'm³', 'actualizacion': '2025-01-01'},
        'grava': {'precio': 7800, 'unidad': 'm³', 'actualizacion': '2025-01-01'},
        'ladrillos_comunes': {'precio': 45000, 'unidad': 'millares', 'actualizacion': '2025-01-01'},
        'ladrillos_huecos': {'precio': 52000, 'unidad': 'millares', 'actualizacion': '2025-01-01'},
        'hierro_construccion': {'precio': 950000, 'unidad': 'tonelada', 'actualizacion': '2025-01-01'},
        'pintura_latex': {'precio': 8500, 'unidad': 'litro', 'actualizacion': '2025-01-01'},
        'ceramico_piso': {'precio': 850, 'unidad': 'm²', 'actualizacion': '2025-01-01'},
        'mano_obra_albañil': {'precio': 15000, 'unidad': 'día', 'actualizacion': '2025-01-01'},
        'mano_obra_plomero': {'precio': 18000, 'unidad': 'día', 'actualizacion': '2025-01-01'},
        'mano_obra_electricista': {'precio': 17000, 'unidad': 'día', 'actualizacion': '2025-01-01'}
    }

def obtener_tipos_obra_disponibles():
    """Obtiene tipos de obra disponibles para cálculo automático"""
    return [
        {
            'id': 'casa_familia',
            'nombre': 'Casa Unifamiliar',
            'descripcion': 'Vivienda unifamiliar de construcción tradicional'
        },
        {
            'id': 'duplex',
            'nombre': 'Dúplex',
            'descripcion': 'Vivienda de dos plantas con estructura independiente'
        },
        {
            'id': 'edificio_departamentos',
            'nombre': 'Edificio de Departamentos',
            'descripcion': 'Edificio residencial multifamiliar'
        },
        {
            'id': 'edificio_3_5_pisos',
            'nombre': 'Edificio 3-5 Pisos',
            'descripcion': 'Edificio de mediana altura con estructura de hormigón'
        },
        {
            'id': 'edificio_6_10_pisos',
            'nombre': 'Edificio 6-10 Pisos',
            'descripcion': 'Edificio de altura media con estructura reforzada'
        },
        {
            'id': 'edificio_11_15_pisos',
            'nombre': 'Edificio 11-15 Pisos',
            'descripcion': 'Edificio de gran altura con estructura especial'
        },
        {
            'id': 'local_comercial',
            'nombre': 'Local Comercial',
            'descripcion': 'Espacio comercial para negocio'
        },
        {
            'id': 'galpon_industrial',
            'nombre': 'Galpón Industrial',
            'descripcion': 'Nave industrial para depósito o producción'
        },
        {
            'id': 'nave_industrial',
            'nombre': 'Nave Industrial',
            'descripcion': 'Estructura industrial de gran envergadura'
        },
        {
            'id': 'centro_comercial',
            'nombre': 'Centro Comercial',
            'descripcion': 'Complejo comercial de múltiples locales'
        },
        {
            'id': 'reforma_ampliacion',
            'nombre': 'Reforma/Ampliación',
            'descripcion': 'Modificación de estructura existente'
        },
        {
            'id': 'renovacion_completa',
            'nombre': 'Renovación Completa',
            'descripcion': 'Remodelación total de edificio existente'
        }
    ]

def calcular_materiales_automatico(tipo_obra, metros_cuadrados, calidad, ubicacion):
    """Calcula automáticamente materiales necesarios"""
    
    # Coeficientes por tipo de obra
    coeficientes = {
        'casa_familia': {
            'cemento': 0.5,      # bolsas por m²
            'arena_gruesa': 0.3,  # m³ por m²
            'arena_fina': 0.15,   # m³ por m²
            'ladrillos': 0.08,    # millares por m²
            'hierro': 0.035,      # toneladas por m²
            'pintura': 0.25,      # litros por m²
            'ceramico': 0.7,      # m² por m² (solo en algunos ambientes)
            'mano_obra_dias': 0.8 # días de trabajo por m²
        },
        'edificio_departamentos': {
            'cemento': 0.8,
            'arena_gruesa': 0.45,
            'arena_fina': 0.2,
            'ladrillos': 0.12,
            'hierro': 0.055,
            'pintura': 0.3,
            'ceramico': 0.9,
            'mano_obra_dias': 1.2
        },
        'local_comercial': {
            'cemento': 0.3,
            'arena_gruesa': 0.2,
            'arena_fina': 0.1,
            'ladrillos': 0.05,
            'hierro': 0.02,
            'pintura': 0.35,
            'ceramico': 1.0,
            'mano_obra_dias': 0.6
        },
        'edificio_3_5_pisos': {
            'cemento': 0.9,
            'arena_gruesa': 0.5,
            'arena_fina': 0.25,
            'ladrillos': 0.14,
            'hierro': 0.065,
            'pintura': 0.32,
            'ceramico': 0.8,
            'mano_obra_dias': 1.4
        },
        'edificio_6_10_pisos': {
            'cemento': 1.1,
            'arena_gruesa': 0.6,
            'arena_fina': 0.3,
            'ladrillos': 0.16,
            'hierro': 0.08,
            'pintura': 0.35,
            'ceramico': 0.85,
            'mano_obra_dias': 1.6
        },
        'edificio_11_15_pisos': {
            'cemento': 1.3,
            'arena_gruesa': 0.7,
            'arena_fina': 0.35,
            'ladrillos': 0.18,
            'hierro': 0.1,
            'pintura': 0.4,
            'ceramico': 0.9,
            'mano_obra_dias': 1.8
        },
        'nave_industrial': {
            'cemento': 0.6,
            'arena_gruesa': 0.35,
            'arena_fina': 0.18,
            'ladrillos': 0.04,
            'hierro': 0.075,
            'pintura': 0.15,
            'ceramico': 0.3,
            'mano_obra_dias': 1.0
        },
        'centro_comercial': {
            'cemento': 0.7,
            'arena_gruesa': 0.4,
            'arena_fina': 0.2,
            'ladrillos': 0.08,
            'hierro': 0.045,
            'pintura': 0.45,
            'ceramico': 1.2,
            'mano_obra_dias': 1.1
        },
        'renovacion_completa': {
            'cemento': 0.4,
            'arena_gruesa': 0.25,
            'arena_fina': 0.12,
            'ladrillos': 0.06,
            'hierro': 0.025,
            'pintura': 0.5,
            'ceramico': 0.9,
            'mano_obra_dias': 0.9
        }
    }
    
    coef = coeficientes.get(tipo_obra, coeficientes['casa_familia'])
    
    # Factores de calidad
    factores_calidad = {
        'economica': 0.85,
        'estandar': 1.0,
        'premium': 1.35
    }
    
    factor_calidad = factores_calidad.get(calidad, 1.0)
    
    # Factores por ubicación
    factores_ubicacion = {
        'caba': 1.25,
        'buenos_aires': 1.1,
        'cordoba': 1.0,
        'santa_fe': 1.0,
        'mendoza': 0.95,
        'otros': 0.9
    }
    
    factor_ubicacion = factores_ubicacion.get(ubicacion, 1.0)
    
    # Obtener precios actuales
    precios = obtener_precios_base_materiales()
    
    # Calcular cantidades y costos
    materiales_calculados = []
    total_materiales = 0
    total_mano_obra = 0
    
    # Cemento
    cantidad_cemento = metros_cuadrados * coef['cemento'] * factor_calidad
    costo_cemento = cantidad_cemento * precios['cemento_portland']['precio'] * factor_ubicacion
    materiales_calculados.append({
        'material': 'Cemento Portland',
        'cantidad': round(cantidad_cemento, 1),
        'unidad': 'bolsas',
        'precio_unitario': precios['cemento_portland']['precio'] * factor_ubicacion,
        'total': costo_cemento
    })
    total_materiales += costo_cemento
    
    # Arena gruesa
    cantidad_arena_gruesa = metros_cuadrados * coef['arena_gruesa'] * factor_calidad
    costo_arena_gruesa = cantidad_arena_gruesa * precios['arena_gruesa']['precio'] * factor_ubicacion
    materiales_calculados.append({
        'material': 'Arena gruesa',
        'cantidad': round(cantidad_arena_gruesa, 2),
        'unidad': 'm³',
        'precio_unitario': precios['arena_gruesa']['precio'] * factor_ubicacion,
        'total': costo_arena_gruesa
    })
    total_materiales += costo_arena_gruesa
    
    # Arena fina
    cantidad_arena_fina = metros_cuadrados * coef['arena_fina'] * factor_calidad
    costo_arena_fina = cantidad_arena_fina * precios['arena_fina']['precio'] * factor_ubicacion
    materiales_calculados.append({
        'material': 'Arena fina',
        'cantidad': round(cantidad_arena_fina, 2),
        'unidad': 'm³',
        'precio_unitario': precios['arena_fina']['precio'] * factor_ubicacion,
        'total': costo_arena_fina
    })
    total_materiales += costo_arena_fina
    
    # Ladrillos
    cantidad_ladrillos = metros_cuadrados * coef['ladrillos'] * factor_calidad
    costo_ladrillos = cantidad_ladrillos * precios['ladrillos_comunes']['precio'] * factor_ubicacion
    materiales_calculados.append({
        'material': 'Ladrillos comunes',
        'cantidad': round(cantidad_ladrillos, 3),
        'unidad': 'millares',
        'precio_unitario': precios['ladrillos_comunes']['precio'] * factor_ubicacion,
        'total': costo_ladrillos
    })
    total_materiales += costo_ladrillos
    
    # Hierro
    cantidad_hierro = metros_cuadrados * coef['hierro'] * factor_calidad
    costo_hierro = cantidad_hierro * precios['hierro_construccion']['precio'] * factor_ubicacion
    materiales_calculados.append({
        'material': 'Hierro de construcción',
        'cantidad': round(cantidad_hierro, 3),
        'unidad': 'toneladas',
        'precio_unitario': precios['hierro_construccion']['precio'] * factor_ubicacion,
        'total': costo_hierro
    })
    total_materiales += costo_hierro
    
    # Pintura
    cantidad_pintura = metros_cuadrados * coef['pintura'] * factor_calidad
    costo_pintura = cantidad_pintura * precios['pintura_latex']['precio'] * factor_ubicacion
    materiales_calculados.append({
        'material': 'Pintura látex',
        'cantidad': round(cantidad_pintura, 1),
        'unidad': 'litros',
        'precio_unitario': precios['pintura_latex']['precio'] * factor_ubicacion,
        'total': costo_pintura
    })
    total_materiales += costo_pintura
    
    # Cerámico
    cantidad_ceramico = metros_cuadrados * coef['ceramico'] * factor_calidad
    costo_ceramico = cantidad_ceramico * precios['ceramico_piso']['precio'] * factor_ubicacion
    materiales_calculados.append({
        'material': 'Cerámico para piso',
        'cantidad': round(cantidad_ceramico, 1),
        'unidad': 'm²',
        'precio_unitario': precios['ceramico_piso']['precio'] * factor_ubicacion,
        'total': costo_ceramico
    })
    total_materiales += costo_ceramico
    
    # Mano de obra
    dias_albañil = metros_cuadrados * coef['mano_obra_dias'] * factor_calidad
    costo_albañil = dias_albañil * precios['mano_obra_albañil']['precio'] * factor_ubicacion
    
    dias_plomero = metros_cuadrados * 0.1 * factor_calidad  # Estimación para plomería
    costo_plomero = dias_plomero * precios['mano_obra_plomero']['precio'] * factor_ubicacion
    
    dias_electricista = metros_cuadrados * 0.08 * factor_calidad  # Estimación para electricidad
    costo_electricista = dias_electricista * precios['mano_obra_electricista']['precio'] * factor_ubicacion
    
    mano_obra = [
        {
            'tipo': 'Albañilería',
            'dias': round(dias_albañil, 1),
            'precio_dia': precios['mano_obra_albañil']['precio'] * factor_ubicacion,
            'total': costo_albañil
        },
        {
            'tipo': 'Plomería',
            'dias': round(dias_plomero, 1),
            'precio_dia': precios['mano_obra_plomero']['precio'] * factor_ubicacion,
            'total': costo_plomero
        },
        {
            'tipo': 'Electricidad',
            'dias': round(dias_electricista, 1),
            'precio_dia': precios['mano_obra_electricista']['precio'] * factor_ubicacion,
            'total': costo_electricista
        }
    ]
    
    total_mano_obra = costo_albañil + costo_plomero + costo_electricista
    
    # Totales y márgenes
    subtotal = total_materiales + total_mano_obra
    gastos_generales = subtotal * 0.15  # 15% gastos generales
    ganancia = subtotal * 0.25  # 25% ganancia
    subtotal_con_gastos = subtotal + gastos_generales + ganancia
    iva = subtotal_con_gastos * 0.21  # 21% IVA
    total_final = subtotal_con_gastos + iva
    
    return {
        'materiales': materiales_calculados,
        'mano_obra': mano_obra,
        'total_materiales': total_materiales,
        'total_mano_obra': total_mano_obra,
        'total_general': total_final,
        'resumen': {
            'total_materiales': total_materiales,
            'total_mano_obra': total_mano_obra,
            'subtotal': subtotal,
            'gastos_generales': gastos_generales,
            'ganancia': ganancia,
            'subtotal_con_gastos': subtotal_con_gastos,
            'iva': iva,
            'total_final': total_final
        },
        'factores_aplicados': {
            'tipo_obra': tipo_obra,
            'calidad': calidad,
            'factor_calidad': factor_calidad,
            'ubicacion': ubicacion,
            'factor_ubicacion': factor_ubicacion
        },
        'recomendaciones': [
            f"Para {tipo_obra.replace('_', ' ')}, se recomienda usar materiales de calidad {calidad}",
            f"El presupuesto está calculado para {metros_cuadrados} m² con factor de ubicación aplicado",
            "Considere un 10-15% adicional para imprevistos",
            "Verifique precios de materiales locales antes de comprar"
        ]
    }

def generar_optimizaciones_presupuesto(presupuesto):
    """Genera sugerencias de optimización para un presupuesto"""
    optimizaciones = []
    
    # Analizar items del presupuesto
    items = presupuesto.items.all()
    
    # Buscar items con precios altos
    for item in items:
        if item.precio_unitario > obtener_precio_mercado_promedio(item.descripcion) * 1.15:
            optimizaciones.append({
                'tipo': 'precio_alto',
                'item': item.descripcion,
                'precio_actual': item.precio_unitario,
                'precio_sugerido': obtener_precio_mercado_promedio(item.descripcion),
                'ahorro_potencial': (item.precio_unitario - obtener_precio_mercado_promedio(item.descripcion)) * item.cantidad
            })
    
    # Sugerir materiales alternativos
    optimizaciones.extend(sugerir_materiales_alternativos(items))
    
    # Optimizaciones de cantidad
    optimizaciones.extend(optimizar_cantidades(items))
    
    return optimizaciones

def generar_analisis_competencia():
    """Genera análisis de competencia y posicionamiento"""
    return {
        'posicion_mercado': 'Competitivo',
        'precio_promedio_m2': 85000,
        'nuestro_promedio_m2': 82000,
        'ventaja_competitiva': -3.5,  # % por debajo del mercado
        'areas_mejora': [
            'Reducir tiempos de entrega',
            'Mejorar acabados premium',
            'Ampliar servicios postventa'
        ]
    }

def obtener_plantillas_cotizacion():
    """Obtiene plantillas predefinidas"""
    return [
        {
            'id': 1,
            'nombre': 'Casa Económica 80m²',
            'descripcion': 'Plantilla para casa económica de 80m²',
            'tipo_obra': 'casa_familia',
            'metros_cuadrados': 80
        },
        {
            'id': 2,
            'nombre': 'Casa Estándar 120m²',
            'descripcion': 'Plantilla para casa estándar de 120m²',
            'tipo_obra': 'casa_familia',
            'metros_cuadrados': 120
        }
    ]

def obtener_variaciones_precios():
    """Obtiene variaciones de precios de materiales"""
    return {
        'cemento': {'variacion_mensual': 3.2, 'tendencia': 'alza'},
        'hierro': {'variacion_mensual': -1.8, 'tendencia': 'baja'},
        'ladrillos': {'variacion_mensual': 2.1, 'tendencia': 'alza'}
    }

def obtener_precio_mercado_promedio(material):
    """Obtiene precio promedio de mercado para un material"""
    # Aquí se conectaría con APIs de precios o bases de datos
    precios_referencia = {
        'cemento portland': 1200,
        'arena gruesa': 8500,
        'ladrillos comunes': 45000
    }
    return precios_referencia.get(material.lower(), 1000)

def sugerir_materiales_alternativos(items):
    """Sugiere materiales alternativos más económicos"""
    sugerencias = []
    
    for item in items:
        if 'ladrillo común' in item.descripcion.lower():
            sugerencias.append({
                'tipo': 'material_alternativo',
                'item_original': item.descripcion,
                'alternativa': 'Bloque de hormigón',
                'ahorro_estimado': item.total * 0.15,
                'ventajas': ['Menor costo', 'Mayor aislamiento'],
                'desventajas': ['Menos tradicional']
            })
    
    return sugerencias

def optimizar_cantidades(items):
    """Optimiza cantidades basado en experiencia"""
    optimizaciones = []
    
    for item in items:
        if item.tipo == 'material' and item.cantidad > obtener_cantidad_tipica(item.descripcion) * 1.2:
            optimizaciones.append({
                'tipo': 'cantidad_excesiva',
                'item': item.descripcion,
                'cantidad_actual': item.cantidad,
                'cantidad_sugerida': obtener_cantidad_tipica(item.descripcion),
                'ahorro_potencial': (item.cantidad - obtener_cantidad_tipica(item.descripcion)) * item.precio_unitario
            })
    
    return optimizaciones

def crear_pdf_presupuesto(datos, usuario):
    """Crea un PDF del presupuesto calculado"""
    import os
    from datetime import datetime
    
    try:
        # Crear directorio si no existe
        os.makedirs('static/pdfs', exist_ok=True)
        
        # Nombre del archivo
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'presupuesto_{usuario.id}_{timestamp}.pdf'
        
        # Por ahora, crear un archivo de texto como placeholder
        # En producción, se usaría ReportLab para generar PDF real
        filepath = f'static/pdfs/{filename}'
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("PRESUPUESTO ESTIMADO AUTOMÁTICO - OBYRA IA\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Tipo de obra: {datos['tipo_obra'].replace('_', ' ').title()}\n")
            f.write(f"Superficie: {datos['metros_cuadrados']} m²\n")
            f.write(f"Calidad: {datos['calidad'].title()}\n")
            f.write(f"Ubicación: {datos['ubicacion'].replace('_', ' ').title()}\n")
            f.write(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n")
            
            calculo = datos['calculo']
            f.write("RESUMEN FINANCIERO:\n")
            f.write(f"Total Materiales: ${calculo['total_materiales']:,.0f}\n")
            f.write(f"Total Mano de Obra: ${calculo['total_mano_obra']:,.0f}\n")
            f.write(f"TOTAL GENERAL: ${calculo['total_general']:,.0f}\n\n")
            
            f.write("MATERIALES DETALLADOS:\n")
            for mat in calculo['materiales']:
                f.write(f"- {mat['material']}: {mat['cantidad']} {mat['unidad']} x ${mat['precio_unitario']:,.0f} = ${mat['total']:,.0f}\n")
            
            f.write("\nRECOMENDACIONES:\n")
            for rec in calculo['recomendaciones']:
                f.write(f"• {rec}\n")
        
        return filename
        
    except Exception as e:
        raise Exception(f"Error generando PDF: {str(e)}")

def obtener_cantidad_tipica(material):
    """Obtiene cantidad típica para un material por m²"""
    cantidades_tipicas = {
        'cemento portland': 0.5,
        'arena gruesa': 0.3,
        'ladrillos comunes': 0.08
    }
    return cantidades_tipicas.get(material.lower(), 1)

def obtener_plantilla_por_id(plantilla_id):
    """Obtiene una plantilla específica por ID"""
    plantillas = obtener_plantillas_cotizacion()
    return next((p for p in plantillas if p['id'] == plantilla_id), None)

def generar_recomendaciones_calculo(tipo_obra, metros_cuadrados, total_final):
    """Genera recomendaciones específicas para el cálculo"""
    recomendaciones = []
    
    # Recomendación por tamaño
    if metros_cuadrados < 80:
        recomendaciones.append("Considera optimizar el diseño para maximizar el uso del espacio")
    elif metros_cuadrados > 200:
        recomendaciones.append("Para obras grandes, evalúa descuentos por volumen en materiales")
    
    # Recomendación por presupuesto
    if total_final > 10000000:  # 10M ARS
        recomendaciones.append("Considera financiamiento en etapas para manejar el flujo de caja")
    
    # Recomendación por tipo de obra
    if tipo_obra == 'edificio_departamentos':
        recomendaciones.append("Verifica normativas municipales para edificios de altura")
    
    recomendaciones.append("Agrega un 10% adicional para imprevistos")
    recomendaciones.append("Los precios son estimativos y sujetos a variación del mercado")
    
    return recomendaciones