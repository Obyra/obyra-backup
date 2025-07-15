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
        
        # Inicializar plantillas si no existen
        inicializar_plantillas_proyecto()
        
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
        
        # Crear configuración inteligente
        configuracion = ConfiguracionInteligente(
            obra_id=obra.id,
            plantilla_id=config.get('plantilla_id', 1),
            factor_complejidad_aplicado=config.get('factor_ubicacion', 1.0),
            ajustes_ubicacion={'ubicacion': ubicacion, 'factor': config.get('factor_ubicacion', 1.0)},
            recomendaciones_ia=config.get('recomendaciones', []),
            configurado_por_id=current_user.id
        )
        db.session.add(configuracion)
        
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
            db.session.flush()
            
            # Crear tareas para cada etapa
            if 'tareas' in etapa_data:
                for tarea_data in etapa_data['tareas']:
                    tarea = TareaEtapa(
                        etapa_id=etapa.id,
                        nombre=tarea_data['nombre'],
                        descripcion=tarea_data['descripcion'],
                        orden=tarea_data['orden'],
                        horas_estimadas=tarea_data['duracion_horas'],
                        requiere_especialista=tarea_data.get('requiere_especialista', False),
                        tipo_especialista=tarea_data.get('tipo_especialista'),
                        es_critica=tarea_data.get('es_critica', False)
                    )
                    db.session.add(tarea)
        
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
        'casa_unifamiliar': {
            'duracion_base': 120,  # días
            'costo_m2': 85000,     # ARS por m²
            'etapas': [
                {'nombre': 'Preparación del terreno', 'descripcion': 'Limpieza, nivelación y replanteo', 'orden': 1, 'duracion': 7, 'fecha_inicio': date.today(), 'fecha_fin': date.today() + timedelta(days=7)},
                {'nombre': 'Fundaciones', 'descripcion': 'Excavación y fundaciones', 'orden': 2, 'duracion': 14, 'fecha_inicio': date.today() + timedelta(days=8), 'fecha_fin': date.today() + timedelta(days=21)},
                {'nombre': 'Estructura', 'descripcion': 'Muros, losas y columnas', 'orden': 3, 'duracion': 30, 'fecha_inicio': date.today() + timedelta(days=22), 'fecha_fin': date.today() + timedelta(days=51)},
                {'nombre': 'Instalaciones', 'descripcion': 'Plomería, electricidad y gas', 'orden': 4, 'duracion': 21, 'fecha_inicio': date.today() + timedelta(days=52), 'fecha_fin': date.today() + timedelta(days=72)},
                {'nombre': 'Terminaciones', 'descripcion': 'Revoques, pisos y pintura', 'orden': 5, 'duracion': 28, 'fecha_inicio': date.today() + timedelta(days=73), 'fecha_fin': date.today() + timedelta(days=100)},
                {'nombre': 'Detalles finales', 'descripcion': 'Limpieza y entrega', 'orden': 6, 'duracion': 20, 'fecha_inicio': date.today() + timedelta(days=101), 'fecha_fin': date.today() + timedelta(days=120)}
            ]
        },
        'galpon_industrial': {
            'duracion_base': 180,
            'costo_m2': 95000,
            'etapas': [
                {'nombre': 'Documentación técnica', 'descripcion': 'Planos y permisos industriales', 'orden': 1, 'duracion': 30, 'fecha_inicio': date.today(), 'fecha_fin': date.today() + timedelta(days=30)},
                {'nombre': 'Preparación del terreno', 'descripcion': 'Nivelación y compactación', 'orden': 2, 'duracion': 15, 'fecha_inicio': date.today() + timedelta(days=31), 'fecha_fin': date.today() + timedelta(days=45)},
                {'nombre': 'Fundaciones industriales', 'descripcion': 'Zapatas y vigas de fundación', 'orden': 3, 'duracion': 25, 'fecha_inicio': date.today() + timedelta(days=46), 'fecha_fin': date.today() + timedelta(days=70)},
                {'nombre': 'Estructura metálica', 'descripcion': 'Columnas, vigas y cerchas', 'orden': 4, 'duracion': 40, 'fecha_inicio': date.today() + timedelta(days=71), 'fecha_fin': date.today() + timedelta(days=110)},
                {'nombre': 'Cerramiento y cubierta', 'descripcion': 'Chapas, membrana y aislación', 'orden': 5, 'duracion': 35, 'fecha_inicio': date.today() + timedelta(days=111), 'fecha_fin': date.today() + timedelta(days=145)},
                {'nombre': 'Instalaciones industriales', 'descripcion': 'Eléctrica industrial y servicios', 'orden': 6, 'duracion': 25, 'fecha_inicio': date.today() + timedelta(days=146), 'fecha_fin': date.today() + timedelta(days=170)},
                {'nombre': 'Terminaciones', 'descripcion': 'Pisos industriales y acabados', 'orden': 7, 'duracion': 10, 'fecha_inicio': date.today() + timedelta(days=171), 'fecha_fin': date.today() + timedelta(days=180)}
            ]
        },
        'edificio_3_5_pisos': {
            'duracion_base': 300,
            'costo_m2': 115000,
            'etapas': [
                {'nombre': 'Proyecto y permisos', 'descripcion': 'Documentación técnica y aprobaciones', 'orden': 1, 'duracion': 35, 'fecha_inicio': date.today(), 'fecha_fin': date.today() + timedelta(days=35)},
                {'nombre': 'Excavación y fundaciones', 'descripcion': 'Movimiento de suelos y fundaciones', 'orden': 2, 'duracion': 25, 'fecha_inicio': date.today() + timedelta(days=36), 'fecha_fin': date.today() + timedelta(days=60)},
                {'nombre': 'Estructura hormigón armado', 'descripcion': 'Columnas, vigas y losas', 'orden': 3, 'duracion': 120, 'fecha_inicio': date.today() + timedelta(days=61), 'fecha_fin': date.today() + timedelta(days=180)},
                {'nombre': 'Mampostería', 'descripcion': 'Muros divisorios y cerramientos', 'orden': 4, 'duracion': 50, 'fecha_inicio': date.today() + timedelta(days=181), 'fecha_fin': date.today() + timedelta(days=230)},
                {'nombre': 'Instalaciones', 'descripcion': 'Sistemas eléctricos y sanitarios', 'orden': 5, 'duracion': 35, 'fecha_inicio': date.today() + timedelta(days=231), 'fecha_fin': date.today() + timedelta(days=265)},
                {'nombre': 'Terminaciones', 'descripcion': 'Revoques, pisos y pintura', 'orden': 6, 'duracion': 30, 'fecha_inicio': date.today() + timedelta(days=266), 'fecha_fin': date.today() + timedelta(days=295)},
                {'nombre': 'Habilitaciones', 'descripcion': 'Inspecciones y entrega', 'orden': 7, 'duracion': 5, 'fecha_inicio': date.today() + timedelta(days=296), 'fecha_fin': date.today() + timedelta(days=300)}
            ]
        },
        'edificio_6_10_pisos': {
            'duracion_base': 450,
            'costo_m2': 125000,
            'etapas': [
                {'nombre': 'Proyecto y permisos', 'descripcion': 'Documentación completa y aprobaciones', 'orden': 1, 'duracion': 60, 'fecha_inicio': date.today(), 'fecha_fin': date.today() + timedelta(days=60)},
                {'nombre': 'Excavación profunda', 'descripcion': 'Excavación y fundaciones profundas', 'orden': 2, 'duracion': 40, 'fecha_inicio': date.today() + timedelta(days=61), 'fecha_fin': date.today() + timedelta(days=100)},
                {'nombre': 'Estructura principal', 'descripcion': 'Estructura completa de hormigón armado', 'orden': 3, 'duracion': 200, 'fecha_inicio': date.today() + timedelta(days=101), 'fecha_fin': date.today() + timedelta(days=300)},
                {'nombre': 'Mampostería y cerramientos', 'descripcion': 'Muros y fachadas', 'orden': 4, 'duracion': 80, 'fecha_inicio': date.today() + timedelta(days=301), 'fecha_fin': date.today() + timedelta(days=380)},
                {'nombre': 'Instalaciones complejas', 'descripcion': 'Sistemas completos del edificio', 'orden': 5, 'duracion': 50, 'fecha_inicio': date.today() + timedelta(days=381), 'fecha_fin': date.today() + timedelta(days=430)},
                {'nombre': 'Terminaciones y habilitación', 'descripcion': 'Acabados finales e inspecciones', 'orden': 6, 'duracion': 20, 'fecha_inicio': date.today() + timedelta(days=431), 'fecha_fin': date.today() + timedelta(days=450)}
            ]
        },
        'edificio_11_15_pisos': {
            'duracion_base': 600,
            'costo_m2': 135000,
            'etapas': [
                {'nombre': 'Proyecto ejecutivo', 'descripcion': 'Documentación completa y permisos especiales', 'orden': 1, 'duracion': 90, 'fecha_inicio': date.today(), 'fecha_fin': date.today() + timedelta(days=90)},
                {'nombre': 'Fundaciones especiales', 'descripcion': 'Excavación profunda y fundaciones especiales', 'orden': 2, 'duracion': 60, 'fecha_inicio': date.today() + timedelta(days=91), 'fecha_fin': date.today() + timedelta(days=150)},
                {'nombre': 'Estructura en altura', 'descripcion': 'Estructura completa con grúa torre', 'orden': 3, 'duracion': 300, 'fecha_inicio': date.today() + timedelta(days=151), 'fecha_fin': date.today() + timedelta(days=450)},
                {'nombre': 'Fachada integral', 'descripcion': 'Sistema de fachada completo', 'orden': 4, 'duracion': 80, 'fecha_inicio': date.today() + timedelta(days=451), 'fecha_fin': date.today() + timedelta(days=530)},
                {'nombre': 'Instalaciones especiales', 'descripcion': 'Ascensores y sistemas complejos', 'orden': 5, 'duracion': 45, 'fecha_inicio': date.today() + timedelta(days=531), 'fecha_fin': date.today() + timedelta(days=575)},
                {'nombre': 'Habilitación final', 'descripcion': 'Inspecciones y entrega de obra', 'orden': 6, 'duracion': 25, 'fecha_inicio': date.today() + timedelta(days=576), 'fecha_fin': date.today() + timedelta(days=600)}
            ]
        },
        'renovacion_completa': {
            'duracion_base': 90,
            'costo_m2': 65000,
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
    
    config_base = configuraciones_base.get(tipo_obra, configuraciones_base['casa_unifamiliar'])
    
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
    
    # Generar items de presupuesto básicos
    items_presupuesto = [
        {'tipo': 'material', 'descripcion': 'Cemento Portland', 'unidad': 'kg', 'cantidad': metros_cuadrados * 45, 'precio_unitario': 850 * factor_ubicacion},
        {'tipo': 'material', 'descripcion': 'Hierro construcción', 'unidad': 'kg', 'cantidad': metros_cuadrados * 35, 'precio_unitario': 1200 * factor_ubicacion},
        {'tipo': 'material', 'descripcion': 'Ladrillo común', 'unidad': 'u', 'cantidad': metros_cuadrados * 120, 'precio_unitario': 85 * factor_ubicacion},
        {'tipo': 'mano_obra', 'descripcion': 'Oficial albañil', 'unidad': 'hora', 'cantidad': metros_cuadrados * 8, 'precio_unitario': 2500 * factor_ubicacion},
        {'tipo': 'mano_obra', 'descripcion': 'Ayudante', 'unidad': 'hora', 'cantidad': metros_cuadrados * 6, 'precio_unitario': 1800 * factor_ubicacion}
    ]
    
    # Generar recomendaciones específicas
    recomendaciones = []
    if tipo_obra in ['edificio_6_10_pisos', 'edificio_11_15_pisos']:
        recomendaciones.append({
            'tipo': 'normativa',
            'titulo': 'Estudio de suelos obligatorio',
            'descripcion': 'Para edificios de altura se requiere estudio geotécnico',
            'prioridad': 'critica'
        })
    
    if metros_cuadrados > 500:
        recomendaciones.append({
            'tipo': 'logistica',
            'titulo': 'Gestión de materiales',
            'descripcion': 'Considerar depósito temporal en obra',
            'prioridad': 'alta'
        })
    
    return {
        'duracion_estimada': duracion_estimada,
        'presupuesto_ajustado': round(presupuesto_ajustado, 2),
        'factor_ubicacion': factor_ubicacion,
        'etapas': config_base['etapas'],
        'items_presupuesto': items_presupuesto,
        'recomendaciones': recomendaciones
    }
    
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

def generar_tareas_etapa(etapa_plantilla, metros_cuadrados):
    """Genera tareas específicas para una etapa según la plantilla"""
    tareas = []
    for tarea_plantilla in etapa_plantilla.tareas_plantilla:
        # Ajustar duración por tamaño del proyecto
        factor_tamaño = 1 + (metros_cuadrados / 100) * 0.1
        duracion_ajustada = tarea_plantilla.duracion_horas * factor_tamaño
        
        tareas.append({
            'nombre': tarea_plantilla.nombre,
            'descripcion': tarea_plantilla.descripcion,
            'orden': tarea_plantilla.orden,
            'duracion_horas': round(duracion_ajustada, 2),
            'requiere_especialista': tarea_plantilla.requiere_especialista,
            'tipo_especialista': tarea_plantilla.tipo_especialista,
            'es_critica': tarea_plantilla.es_critica
        })
    return tareas


def obtener_factor_ubicacion(ubicacion):
    """Calcula factor de ajuste por ubicación geográfica"""
    # Factores base por región (ejemplo Argentina)
    factores_ubicacion = {
        'caba': 1.3,  # Capital Federal
        'buenos_aires': 1.1,  # Gran Buenos Aires
        'cordoba': 1.0,  # Córdoba
        'rosario': 1.05,  # Rosario
        'mendoza': 0.95,  # Mendoza
        'tucuman': 0.9,  # Tucumán
        'salta': 0.85,  # Salta
        'default': 1.0
    }
    
    ubicacion_lower = ubicacion.lower()
    for region, factor in factores_ubicacion.items():
        if region in ubicacion_lower:
            return factor
    
    return factores_ubicacion['default']


def generar_recomendaciones_proyecto(tipo_obra, metros_cuadrados, ubicacion, presupuesto):
    """Genera recomendaciones inteligentes específicas del proyecto"""
    recomendaciones = []
    
    # Recomendaciones por tipo de obra
    if tipo_obra == 'edificio_5_pisos':
        recomendaciones.extend([
            {
                'tipo': 'normativa',
                'titulo': 'Código de Edificación',
                'descripcion': 'Verificar cumplimiento del código de edificación local para edificios de más de 4 pisos',
                'prioridad': 'alta',
                'categoria': 'legal'
            },
            {
                'tipo': 'estructura',
                'titulo': 'Estudio de Suelos',
                'descripcion': 'Realizar estudio geotécnico obligatorio para fundaciones profundas',
                'prioridad': 'critica',
                'categoria': 'tecnica'
            }
        ])
    
    # Recomendaciones por tamaño
    if metros_cuadrados > 500:
        recomendaciones.append({
            'tipo': 'logistica',
            'titulo': 'Gestión de Materiales',
            'descripcion': 'Considerar almacén temporal en obra para gestión eficiente de materiales',
            'prioridad': 'media',
            'categoria': 'logistica'
        })
    
    # Recomendaciones por presupuesto
    if presupuesto > 50000000:  # $50M ARS
        recomendaciones.append({
            'tipo': 'financiero',
            'titulo': 'Gestión Financiera',
            'descripcion': 'Implementar control de flujo de caja semanal para proyecto de alta inversión',
            'prioridad': 'alta',
            'categoria': 'financiera'
        })
    
    # Recomendaciones por ubicación
    if 'caba' in ubicacion.lower():
        recomendaciones.append({
            'tipo': 'urbano',
            'titulo': 'Permisos CABA',
            'descripcion': 'Gestionar permisos de obra y ocupación de vía pública con antelación',
            'prioridad': 'alta',
            'categoria': 'administrativa'
        })
    
    return recomendaciones


def obtener_proveedores_ubicacion(ubicacion):
    """Obtiene proveedores sugeridos según la ubicación"""
    # Base de datos básica de proveedores por región
    proveedores = {
        'materiales_estructura': [
            {'nombre': 'Loma Negra', 'categoria': 'cemento', 'cobertura': 'nacional'},
            {'nombre': 'Acindar', 'categoria': 'hierro', 'cobertura': 'nacional'},
            {'nombre': 'Aluar', 'categoria': 'aluminio', 'cobertura': 'nacional'}
        ],
        'materiales_terminacion': [
            {'nombre': 'Cerro Negro', 'categoria': 'cerámicos', 'cobertura': 'nacional'},
            {'nombre': 'FV', 'categoria': 'sanitarios', 'cobertura': 'nacional'},
            {'nombre': 'Klaukol', 'categoria': 'adhesivos', 'cobertura': 'nacional'}
        ]
    }
    
    return proveedores


def obtener_maquinaria_sugerida(tipo_obra, metros_cuadrados):
    """Sugiere maquinaria necesaria según tipo y tamaño de obra"""
    maquinaria = []
    
    if tipo_obra == 'edificio_5_pisos':
        maquinaria.extend([
            {'tipo': 'Grúa torre', 'capacidad': '8-12 ton', 'duracion_estimada': '8-10 meses'},
            {'tipo': 'Hormigonera', 'capacidad': '500L', 'duracion_estimada': '6 meses'},
            {'tipo': 'Montacargas', 'capacidad': '1000kg', 'duracion_estimada': '10 meses'}
        ])
    elif tipo_obra == 'casa_unifamiliar':
        maquinaria.extend([
            {'tipo': 'Hormigonera', 'capacidad': '350L', 'duracion_estimada': '3 meses'},
            {'tipo': 'Andamios', 'tipo': 'tubular', 'duracion_estimada': '4 meses'}
        ])
    
    if metros_cuadrados > 300:
        maquinaria.append({
            'tipo': 'Compresor', 'capacidad': '200L', 'duracion_estimada': '2 meses'
        })
    
    return maquinaria


def inicializar_plantillas_proyecto():
    """Inicializa plantillas base de proyecto si no existen"""
    try:
        # Verificar si ya existen plantillas
        if PlantillaProyecto.query.count() > 0:
            return True
        
        # Crear plantilla para casa unifamiliar
        plantilla_casa = PlantillaProyecto(
            tipo_obra='casa_unifamiliar',
            nombre='Casa Unifamiliar Estándar',
            descripcion='Plantilla para casas unifamiliares de 80-200 m²',
            duracion_base_dias=120,
            metros_cuadrados_min=80,
            metros_cuadrados_max=200,
            costo_base_m2=85000,
            factor_complejidad=1.0
        )
        db.session.add(plantilla_casa)
        db.session.flush()
        
        # Etapas para casa unifamiliar
        etapas_casa = [
            {'nombre': 'Preparación del terreno', 'descripcion': 'Limpieza, nivelación y replanteo', 'orden': 1, 'duracion': 7, 'porcentaje': 5},
            {'nombre': 'Fundaciones', 'descripcion': 'Excavación y fundaciones', 'orden': 2, 'duracion': 14, 'porcentaje': 15},
            {'nombre': 'Estructura', 'descripcion': 'Muros, losas y columnas', 'orden': 3, 'duracion': 30, 'porcentaje': 30},
            {'nombre': 'Techos', 'descripcion': 'Estructura de techo y cubierta', 'orden': 4, 'duracion': 14, 'porcentaje': 15},
            {'nombre': 'Instalaciones', 'descripcion': 'Plomería, electricidad y gas', 'orden': 5, 'duracion': 21, 'porcentaje': 20},
            {'nombre': 'Terminaciones', 'descripcion': 'Revoques, pisos y pintura', 'orden': 6, 'duracion': 28, 'porcentaje': 12},
            {'nombre': 'Detalles finales', 'descripcion': 'Limpieza y entrega', 'orden': 7, 'duracion': 6, 'porcentaje': 3}
        ]
        
        for etapa_data in etapas_casa:
            etapa = EtapaPlantilla(
                plantilla_id=plantilla_casa.id,
                nombre=etapa_data['nombre'],
                descripcion=etapa_data['descripcion'],
                orden=etapa_data['orden'],
                duracion_dias=etapa_data['duracion'],
                porcentaje_presupuesto=etapa_data['porcentaje'],
                es_critica=etapa_data['orden'] in [2, 3, 5]  # Fundaciones, estructura e instalaciones críticas
            )
            db.session.add(etapa)
        
        # Materiales básicos para casa unifamiliar
        materiales_casa = [
            {'categoria': 'estructura', 'material': 'Cemento Portland', 'unidad': 'kg', 'cantidad_m2': 45, 'precio_base': 850},
            {'categoria': 'estructura', 'material': 'Hierro construcción', 'unidad': 'kg', 'cantidad_m2': 35, 'precio_base': 1200},
            {'categoria': 'albañileria', 'material': 'Ladrillo común', 'unidad': 'u', 'cantidad_m2': 120, 'precio_base': 85},
            {'categoria': 'terminaciones', 'material': 'Cerámica piso', 'unidad': 'm2', 'cantidad_m2': 1.1, 'precio_base': 2500},
            {'categoria': 'instalaciones', 'material': 'Caño PVC sanitario', 'unidad': 'm', 'cantidad_m2': 3, 'precio_base': 450}
        ]
        
        for material_data in materiales_casa:
            material = ItemMaterialPlantilla(
                plantilla_id=plantilla_casa.id,
                categoria=material_data['categoria'],
                material=material_data['material'],
                unidad=material_data['unidad'],
                cantidad_por_m2=material_data['cantidad_m2'],
                precio_unitario_base=material_data['precio_base'],
                es_critico=material_data['categoria'] in ['estructura', 'instalaciones']
            )
            db.session.add(material)
        
        db.session.commit()
        return True
        
    except Exception as e:
        db.session.rollback()
        return False


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