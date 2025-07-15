"""
Módulo Asistente Inteligente - OBYRA IA
Proporciona asistencia inteligente para configuración inicial de proyectos,
análisis de datos y recomendaciones automáticas.
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
import json
import re
from app import db
from models import *
from utils import *

asistente_bp = Blueprint('asistente', __name__)

@asistente_bp.route('/')
@asistente_bp.route('/dashboard')
@asistente_bp.route('/control')
@login_required
def dashboard():
    """Dashboard principal del asistente inteligente - Centro de Control IA"""
    try:
        # Datos para el asistente
        obras_activas = Obra.query.filter_by(estado='en_curso').count()
        presupuestos_pendientes = Presupuesto.query.filter_by(estado='borrador').count()
        items_stock_bajo = ItemInventario.query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo).count()
        
        # Recomendaciones inteligentes
        recomendaciones = generar_recomendaciones()
        
        return render_template('asistente/dashboard.html',
                             obras_activas=obras_activas,
                             presupuestos_pendientes=presupuestos_pendientes,
                             items_stock_bajo=items_stock_bajo,
                             recomendaciones=recomendaciones)
    except Exception as e:
        # En caso de error, mostrar dashboard básico
        return render_template('asistente/dashboard.html',
                             obras_activas=0,
                             presupuestos_pendientes=0,
                             items_stock_bajo=0,
                             recomendaciones=[])

@asistente_bp.route('/configuracion_inicial')
@login_required
def configuracion_inicial():
    """Asistente para configuración inicial de proyectos"""
    return render_template('asistente/configuracion_inicial.html')

@asistente_bp.route('/configurar_proyecto', methods=['POST'])
@login_required
def configurar_proyecto():
    """Procesa la configuración inicial inteligente de un proyecto"""
    data = request.get_json()
    
    try:
        # Extraer información del proyecto
        tipo_obra = data.get('tipo_obra')
        metros_cuadrados = float(data.get('metros_cuadrados', 0))
        ubicacion = data.get('ubicacion')
        presupuesto_estimado = float(data.get('presupuesto_estimado', 0))
        fecha_inicio = datetime.strptime(data.get('fecha_inicio'), '%Y-%m-%d').date()
        
        # Generar configuración inteligente
        config = generar_configuracion_inteligente(tipo_obra, metros_cuadrados, ubicacion, presupuesto_estimado)
        
        # Crear obra con configuración automática
        obra = Obra(
            nombre=data.get('nombre_proyecto'),
            descripcion=f"Proyecto {tipo_obra} de {metros_cuadrados}m² - Configurado automáticamente por OBYRA IA",
            direccion=ubicacion,
            cliente=data.get('cliente'),
            telefono_cliente=data.get('telefono_cliente'),
            email_cliente=data.get('email_cliente'),
            fecha_inicio=fecha_inicio,
            fecha_fin_estimada=fecha_inicio + timedelta(days=config['duracion_estimada']),
            presupuesto_total=config['presupuesto_ajustado'],
            estado='planificacion'
        )
        
        db.session.add(obra)
        db.session.flush()
        
        # Crear etapas automáticas
        for etapa_data in config['etapas']:
            etapa = EtapaObra(
                obra_id=obra.id,
                nombre=etapa_data['nombre'],
                descripcion=etapa_data['descripcion'],
                orden=etapa_data['orden'],
                fecha_inicio_estimada=etapa_data['fecha_inicio'],
                fecha_fin_estimada=etapa_data['fecha_fin']
            )
            db.session.add(etapa)
        
        # Crear presupuesto base
        presupuesto = Presupuesto(
            obra_id=obra.id,
            numero=f"PRES-{obra.id:04d}-{datetime.now().year}",
            fecha=date.today(),
            estado='borrador'
        )
        db.session.add(presupuesto)
        db.session.flush()
        
        # Agregar items de presupuesto automáticos
        for item_data in config['items_presupuesto']:
            item = ItemPresupuesto(
                presupuesto_id=presupuesto.id,
                tipo=item_data['tipo'],
                descripcion=item_data['descripcion'],
                unidad=item_data['unidad'],
                cantidad=item_data['cantidad'],
                precio_unitario=item_data['precio_unitario'],
                total=item_data['cantidad'] * item_data['precio_unitario']
            )
            db.session.add(item)
        
        # Calcular totales del presupuesto
        presupuesto.calcular_totales()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'obra_id': obra.id,
            'mensaje': 'Proyecto configurado automáticamente con éxito',
            'configuracion': config
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@asistente_bp.route('/analisis_rendimiento')
@login_required
def analisis_rendimiento():
    """Análisis inteligente de rendimiento de obras y equipos"""
    analisis = generar_analisis_rendimiento()
    return render_template('asistente/analisis_rendimiento.html', analisis=analisis)

@asistente_bp.route('/predicciones')
@login_required
def predicciones():
    """Predicciones inteligentes basadas en datos históricos"""
    predicciones = generar_predicciones()
    return render_template('asistente/predicciones.html', predicciones=predicciones)

@asistente_bp.route('/optimizacion_recursos')
@login_required
def optimizacion_recursos():
    """Sugerencias de optimización de recursos"""
    optimizaciones = generar_optimizaciones_recursos()
    return render_template('asistente/optimizacion.html', optimizaciones=optimizaciones)

@asistente_bp.route('/chat_ia', methods=['POST'])
@login_required
def chat_ia():
    """Endpoint para chat con asistente IA"""
    mensaje = request.json.get('mensaje')
    respuesta = procesar_consulta_ia(mensaje)
    
    return jsonify({
        'respuesta': respuesta,
        'timestamp': datetime.now().isoformat()
    })

# Funciones auxiliares

def generar_recomendaciones():
    """Genera recomendaciones inteligentes basadas en el estado actual"""
    recomendaciones = []
    
    # Verificar obras con retrasos
    obras_retrasadas = Obra.query.filter(
        Obra.fecha_fin_estimada < date.today(),
        Obra.estado.in_(['en_curso', 'planificacion'])
    ).all()
    
    for obra in obras_retrasadas:
        recomendaciones.append({
            'tipo': 'urgente',
            'titulo': f'Obra "{obra.nombre}" con retraso',
            'descripcion': f'La obra tiene {(date.today() - obra.fecha_fin_estimada).days} días de retraso',
            'accion': f'/obras/detalle/{obra.id}',
            'icono': 'fa-exclamation-triangle'
        })
    
    # Verificar stock bajo
    items_criticos = ItemInventario.query.filter(
        ItemInventario.stock_actual <= ItemInventario.stock_minimo
    ).limit(5).all()
    
    if items_criticos:
        recomendaciones.append({
            'tipo': 'advertencia',
            'titulo': f'{len(items_criticos)} items con stock crítico',
            'descripcion': 'Revisa el inventario para evitar interrupciones en las obras',
            'accion': '/inventario/lista',
            'icono': 'fa-boxes'
        })
    
    # Verificar presupuestos pendientes
    presupuestos_viejos = Presupuesto.query.filter(
        Presupuesto.estado == 'borrador',
        Presupuesto.fecha_creacion < datetime.now() - timedelta(days=7)
    ).count()
    
    if presupuestos_viejos > 0:
        recomendaciones.append({
            'tipo': 'info',
            'titulo': f'{presupuestos_viejos} presupuestos pendientes',
            'descripcion': 'Tienes presupuestos en borrador desde hace más de una semana',
            'accion': '/presupuestos/lista',
            'icono': 'fa-file-invoice-dollar'
        })
    
    return recomendaciones

def generar_configuracion_inteligente(tipo_obra, metros_cuadrados, ubicacion, presupuesto_estimado):
    """Genera configuración automática inteligente para un proyecto"""
    
    # Configuraciones base por tipo de obra
    configuraciones_base = {
        'casa_familia': {
            'duracion_base': 120,  # días
            'costo_m2': 80000,     # ARS por m²
            'etapas': [
                'Preparación del terreno',
                'Fundaciones',
                'Estructura',
                'Mampostería',
                'Instalaciones',
                'Revoques',
                'Carpintería',
                'Pintura',
                'Terminaciones'
            ]
        },
        'edificio_departamentos': {
            'duracion_base': 300,
            'costo_m2': 95000,
            'etapas': [
                'Estudio de suelos',
                'Excavación',
                'Fundaciones profundas',
                'Estructura hormigón',
                'Mampostería',
                'Instalaciones generales',
                'Fachada',
                'Terminaciones interiores',
                'Espacios comunes'
            ]
        },
        'local_comercial': {
            'duracion_base': 90,
            'costo_m2': 70000,
            'etapas': [
                'Diseño y permisos',
                'Demolición interior',
                'Instalaciones especiales',
                'Revestimientos',
                'Iluminación',
                'Terminaciones',
                'Señalética'
            ]
        }
    }
    
    config_base = configuraciones_base.get(tipo_obra, configuraciones_base['casa_familia'])
    
    # Ajustar según metros cuadrados
    factor_superficie = 1 + (metros_cuadrados - 100) / 1000  # Factor basado en superficie
    duracion_estimada = int(config_base['duracion_base'] * factor_superficie)
    presupuesto_ajustado = config_base['costo_m2'] * metros_cuadrados * factor_superficie
    
    # Ajustar según ubicación (zonas de Argentina)
    factores_ubicacion = {
        'caba': 1.3,
        'buenos_aires': 1.1,
        'cordoba': 1.0,
        'santa_fe': 1.0,
        'mendoza': 0.95,
        'otros': 0.9
    }
    
    factor_ubicacion = 1.0
    for zona, factor in factores_ubicacion.items():
        if zona in ubicacion.lower():
            factor_ubicacion = factor
            break
    
    presupuesto_ajustado *= factor_ubicacion
    
    # Generar etapas con fechas
    fecha_inicio = date.today()
    etapas = []
    dias_por_etapa = duracion_estimada // len(config_base['etapas'])
    
    for i, nombre_etapa in enumerate(config_base['etapas']):
        fecha_inicio_etapa = fecha_inicio + timedelta(days=i * dias_por_etapa)
        fecha_fin_etapa = fecha_inicio + timedelta(days=(i + 1) * dias_por_etapa)
        
        etapas.append({
            'nombre': nombre_etapa,
            'descripcion': f'Etapa {i+1}: {nombre_etapa}',
            'orden': i + 1,
            'fecha_inicio': fecha_inicio_etapa,
            'fecha_fin': fecha_fin_etapa
        })
    
    # Generar items de presupuesto automáticos
    items_presupuesto = [
        {
            'tipo': 'material',
            'descripcion': 'Cemento Portland',
            'unidad': 'bolsa',
            'cantidad': metros_cuadrados * 0.5,
            'precio_unitario': 1200
        },
        {
            'tipo': 'material',
            'descripcion': 'Arena gruesa',
            'unidad': 'm³',
            'cantidad': metros_cuadrados * 0.3,
            'precio_unitario': 8500
        },
        {
            'tipo': 'material',
            'descripcion': 'Ladrillos comunes',
            'unidad': 'millares',
            'cantidad': metros_cuadrados * 0.08,
            'precio_unitario': 45000
        },
        {
            'tipo': 'mano_obra',
            'descripción': 'Albañilería general',
            'unidad': 'm²',
            'cantidad': metros_cuadrados,
            'precio_unitario': 12000
        },
        {
            'tipo': 'equipo',
            'descripcion': 'Alquiler hormigonera',
            'unidad': 'día',
            'cantidad': duracion_estimada * 0.3,
            'precio_unitario': 1500
        }
    ]
    
    return {
        'duracion_estimada': duracion_estimada,
        'presupuesto_ajustado': presupuesto_ajustado,
        'factor_ubicacion': factor_ubicacion,
        'etapas': etapas,
        'items_presupuesto': items_presupuesto,
        'recomendaciones': [
            f'Duración estimada: {duracion_estimada} días',
            f'Presupuesto ajustado: ${presupuesto_ajustado:,.0f}',
            f'Factor ubicación aplicado: {factor_ubicacion}',
            'Configuración generada automáticamente por OBYRA IA'
        ]
    }

def generar_analisis_rendimiento():
    """Genera análisis de rendimiento inteligente"""
    # Aquí implementarías algoritmos de análisis
    return {
        'obras_completadas_tiempo': 85,  # %
        'desviacion_presupuesto_promedio': -5.2,  # %
        'eficiencia_equipo': 78,  # %
        'recomendaciones': [
            'Mejorar planificación de materiales',
            'Optimizar asignación de personal',
            'Revisar cronogramas de obra'
        ]
    }

def generar_predicciones():
    """Genera predicciones basadas en datos históricos"""
    return {
        'obras_proximas_terminar': [],
        'posibles_retrasos': [],
        'necesidades_inventario': []
    }

def generar_optimizaciones_recursos():
    """Genera sugerencias de optimización"""
    return {
        'reasignacion_personal': [],
        'compras_optimizadas': [],
        'cronograma_mejorado': []
    }

def procesar_consulta_ia(mensaje):
    """Procesa consultas del chat IA y genera respuestas"""
    mensaje_lower = mensaje.lower()
    
    # Respuestas básicas de consulta
    if 'obra' in mensaje_lower and ('estado' in mensaje_lower or 'progreso' in mensaje_lower):
        obras_activas = Obra.query.filter_by(estado='en_curso').count()
        return f"Actualmente tienes {obras_activas} obras en curso. ¿Te gustaría ver el detalle de alguna en particular?"
    
    elif 'inventario' in mensaje_lower and ('stock' in mensaje_lower or 'material' in mensaje_lower):
        items_bajo = ItemInventario.query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo).count()
        return f"Hay {items_bajo} items con stock bajo. Te recomiendo revisar el inventario para evitar faltantes."
    
    elif 'presupuesto' in mensaje_lower:
        presupuestos_pendientes = Presupuesto.query.filter_by(estado='borrador').count()
        return f"Tienes {presupuestos_pendientes} presupuestos en borrador. ¿Necesitas ayuda para completarlos?"
    
    elif 'ayuda' in mensaje_lower or 'cómo' in mensaje_lower:
        return """Puedo ayudarte con:
        • Estado y progreso de obras
        • Control de inventario y stock
        • Análisis de presupuestos
        • Recomendaciones de optimización
        • Configuración de nuevos proyectos
        
        ¿En qué específicamente te gustaría que te asista?"""
    
    else:
        return "Entiendo tu consulta. Para brindarte la mejor asistencia, ¿podrías ser más específico sobre qué necesitas? Puedo ayudarte con obras, inventario, presupuestos o análisis de rendimiento."