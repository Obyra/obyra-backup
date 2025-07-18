"""
Módulo Asistente Inteligente - OBYRA IA
Proporciona asistencia inteligente para configuración inicial de proyectos,
análisis de datos y recomendaciones automáticas.
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from decimal import Decimal
import json
import re
from app import db
from models import *
from utils import *

asistente_bp = Blueprint('asistente', __name__)

@asistente_bp.route('/inicio')
@login_required
def inicio():
    """Página de inicio del asistente IA con imagen corporativa"""
    return render_template('asistente/inicio.html')

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
        config = generar_configuracion_inteligente(tipo_obra, metros_cuadrados, ubicacion, presupuesto_estimado, data)
        
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
            presupuesto_total=Decimal(str(config['presupuesto_ajustado'])),
            estado='planificacion'
        )
        
        db.session.add(obra)
        db.session.flush()
        
        # Crear configuración inteligente
        configuracion = ConfiguracionInteligente(
            obra_id=obra.id,
            plantilla_id=config.get('plantilla_id', 1),
            factor_complejidad_aplicado=Decimal(str(config.get('factor_ubicacion', 1.0))),
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
            cantidad = Decimal(str(item_data['cantidad']))
            precio_unitario = Decimal(str(item_data['precio_unitario']))
            item = ItemPresupuesto(
                presupuesto_id=presupuesto.id,
                tipo=item_data['tipo'],
                descripcion=item_data['descripcion'],
                unidad=item_data['unidad'],
                cantidad=cantidad,
                precio_unitario=precio_unitario,
                total=cantidad * precio_unitario
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

def generar_configuracion_inteligente(tipo_obra, metros_cuadrados, ubicacion, presupuesto_estimado, data=None):
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
    
    # Detectar provincia desde ubicación o provincia_detectada
    provincia_detectada = ''
    if data:
        provincia_detectada = data.get('provincia_detectada', '')
    
    factor_ubicacion = factores_ubicacion.get(provincia_detectada, 1.0)
    
    # Si no hay provincia detectada, usar ubicación texto
    if not provincia_detectada:
        ubicacion_lower = ubicacion.lower()
        for zona, factor in factores_ubicacion.items():
            if zona in ubicacion_lower:
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
    """Procesa consultas del chat IA y genera respuestas inteligentes"""
    mensaje_lower = mensaje.lower()
    
    try:
        # Consultas sobre obras y estado
        if any(palabra in mensaje_lower for palabra in ['obra', 'proyecto', 'construcción']):
            if any(palabra in mensaje_lower for palabra in ['estado', 'progreso', 'avance']):
                obras = Obra.query.all()
                if not obras:
                    return "No tienes obras registradas aún. ¿Te ayudo a crear tu primer proyecto con configuración automática?"
                
                estados = {}
                for obra in obras:
                    estados[obra.estado] = estados.get(obra.estado, 0) + 1
                
                respuesta = f"📊 **Estado de tus obras ({len(obras)} total):**\n"
                for estado, cantidad in estados.items():
                    emoji = {'planificacion': '📋', 'en_curso': '🚧', 'pausada': '⏸️', 'finalizada': '✅', 'cancelada': '❌'}.get(estado, '📝')
                    respuesta += f"• {emoji} {estado.title()}: {cantidad} obra{'s' if cantidad > 1 else ''}\n"
                
                obras_activas = [o for o in obras if o.estado == 'en_curso']
                if obras_activas:
                    respuesta += f"\n🔥 **Obras activas más importantes:**\n"
                    for obra in obras_activas[:3]:
                        dias_transcurridos = (datetime.now().date() - obra.fecha_inicio).days if obra.fecha_inicio else 0
                        respuesta += f"• {obra.nombre} - {dias_transcurridos} días en curso\n"
                
                return respuesta
            
            elif any(palabra in mensaje_lower for palabra in ['crear', 'nuevo', 'empezar']):
                return "🏗️ ¡Perfecto! Te ayudo a crear un nuevo proyecto. Usa la **Configuración Inicial Inteligente** desde el menú principal. El sistema:\n\n• Detecta automáticamente materiales necesarios\n• Calcula costos por ubicación\n• Genera cronograma optimizado\n• Crea presupuesto detallado\n\n¿Qué tipo de obra planeas? (Casa, Edificio, Galpón Industrial, etc.)"
        
        # Consultas sobre inventario y materiales
        elif any(palabra in mensaje_lower for palabra in ['inventario', 'stock', 'material', 'herramienta']):
            # Detectar si pide cálculo específico de materiales
            if any(palabra in mensaje_lower for palabra in ['necesito', 'calcular', 'casa', '100m', 'cuánto', 'cuántos']):
                return generar_calculo_materiales_basico(mensaje_lower)
            
            items = ItemInventario.query.all()
            if not items:
                return "No tienes items en inventario aún. Te recomiendo agregar materiales desde el módulo de Inventario para un mejor control.\n\n💡 **¿Necesitas calcular materiales?** Puedo ayudarte a calcular cantidades necesarias para cualquier tipo de construcción. Solo pregúntame algo como '¿Qué materiales necesito para una casa de 100m²?'"
            
            items_bajo = [item for item in items if item.stock_actual <= item.stock_minimo]
            items_criticos = [item for item in items_bajo if item.stock_actual == 0]
            
            respuesta = f"📦 **Estado del Inventario ({len(items)} items total):**\n"
            respuesta += f"• ✅ En stock normal: {len(items) - len(items_bajo)} items\n"
            respuesta += f"• ⚠️ Stock bajo: {len(items_bajo)} items\n"
            respuesta += f"• 🚨 Sin stock: {len(items_criticos)} items\n"
            
            if items_criticos:
                respuesta += f"\n🚨 **URGENTE - Items agotados:**\n"
                for item in items_criticos[:5]:
                    respuesta += f"• {item.nombre} - Stock: 0 {item.unidad}\n"
            
            if items_bajo and not items_criticos:
                respuesta += f"\n⚠️ **Items con stock bajo:**\n"
                for item in items_bajo[:5]:
                    respuesta += f"• {item.nombre} - Stock: {item.stock_actual}/{item.stock_minimo} {item.unidad}\n"
            
            return respuesta
        
        # Consultas sobre presupuestos y costos
        elif any(palabra in mensaje_lower for palabra in ['presupuesto', 'costo', 'precio', 'cotización']):
            presupuestos = Presupuesto.query.all()
            if not presupuestos:
                return "No tienes presupuestos creados. ¿Te ayudo a generar uno usando la **Calculadora Inteligente de Materiales**? Calcula automáticamente cantidades y precios actualizados."
            
            estados = {}
            total_valor = 0
            for presupuesto in presupuestos:
                estados[presupuesto.estado] = estados.get(presupuesto.estado, 0) + 1
                if presupuesto.total:
                    total_valor += presupuesto.total
            
            respuesta = f"💰 **Estado de Presupuestos ({len(presupuestos)} total):**\n"
            for estado, cantidad in estados.items():
                emoji = {'borrador': '📝', 'enviado': '📤', 'aprobado': '✅', 'rechazado': '❌'}.get(estado, '📋')
                respuesta += f"• {emoji} {estado.title()}: {cantidad}\n"
            
            respuesta += f"\n💵 **Valor total en presupuestos:** ${total_valor:,.0f} ARS\n"
            
            borradores = [p for p in presupuestos if p.estado == 'borrador']
            if borradores:
                respuesta += f"\n📝 **Presupuestos en borrador que puedes completar:**\n"
                for presupuesto in borradores[:3]:
                    respuesta += f"• {presupuesto.nombre_proyecto or 'Sin nombre'}\n"
            
            return respuesta
        
        # Consultas sobre optimización y consejos
        elif any(palabra in mensaje_lower for palabra in ['optimizar', 'mejorar', 'ahorrar', 'reducir']):
            return "🎯 **Sugerencias de Optimización:**\n\n• **Usa materiales alternativos:** La cotizadora sugiere opciones más económicas\n• **Compra por volumen:** Negocia descuentos para múltiples obras\n• **Planifica entregas:** Evita costos de almacenamiento innecesarios\n• **Revisa proveedores:** Compara precios en diferentes zonas\n• **Control de desperdicios:** Calcula 5-10% extra según material\n\n¿En qué proyecto específico necesitas optimizar costos?"
        
        # Consultas sobre rendimiento y equipos
        elif any(palabra in mensaje_lower for palabra in ['equipo', 'rendimiento', 'productividad', 'personal']):
            usuarios = Usuario.query.filter_by(activo=True).count()
            return f"👥 **Gestión de Equipos:**\n\n• Personal activo: {usuarios} usuarios\n• Usa el módulo **Performance Tracking** para:\n  - Seguimiento de tareas por usuario\n  - Métricas de productividad\n  - Asignación optimizada de recursos\n  - Reportes de rendimiento\n\n¿Necesitas analizar el rendimiento de algún equipo específico?"
        
        # Consultas sobre ayuda y funcionalidades
        elif any(palabra in mensaje_lower for palabra in ['ayuda', 'cómo', 'funciona', 'usar']):
            return """🤖 **¿Cómo puedo ayudarte?**

**Preguntas que puedo responder:**
• Estado de obras y proyectos
• Inventario y control de stock
• Análisis de presupuestos y costos
• Sugerencias de optimización
• Configuración de nuevos proyectos
• Rendimiento de equipos

**Ejemplos de consultas:**
• "¿Cuál es el estado de mis obras?"
• "¿Qué materiales tienen stock bajo?"
• "¿Cuánto valor tengo en presupuestos?"
• "¿Cómo optimizar costos de mi proyecto?"
• "¿Cómo crear un nuevo proyecto?"

¡Pregúntame cualquier cosa específica sobre tu construcción!"""
        
        # Respuesta por defecto más inteligente
        else:
            # Intentar detectar palabras clave específicas
            if any(palabra in mensaje_lower for palabra in ['cemento', 'hierro', 'ladrillo', 'arena', 'cal', 'materiales']):
                # Detectar si pide cálculo específico
                if any(palabra in mensaje_lower for palabra in ['necesito', 'calcular', 'casa', '100m', 'cuánto', 'cuántos']):
                    return generar_calculo_materiales_basico(mensaje_lower)
                else:
                    return "🧱 Mencionaste materiales de construcción. ¿Necesitas:\n• Verificar stock actual?\n• Calcular cantidades para un proyecto?\n• Comparar precios de proveedores?\n• Generar orden de compra?\n\nPuedo ayudarte con cualquiera de estas tareas."
            
            elif any(palabra in mensaje_lower for palabra in ['tiempo', 'cronograma', 'plazo', 'duración']):
                return "⏰ Sobre planificación temporal:\n• La configuración automática calcula duración según tipo de obra\n• Puedes ajustar cronogramas en cada proyecto\n• El sistema considera factores de complejidad\n\n¿Necesitas revisar el cronograma de algún proyecto específico?"
            
            else:
                # Generar respuesta inteligente basada en el estado actual
                obras_count = Obra.query.count()
                items_count = ItemInventario.query.count()
                presupuestos_count = Presupuesto.query.count()
                
                return f"🎯 **Estado actual de tu sistema:**\n• {obras_count} obra{'s' if obras_count != 1 else ''} registrada{'s' if obras_count != 1 else ''}\n• {items_count} item{'s' if items_count != 1 else ''} en inventario\n• {presupuestos_count} presupuesto{'s' if presupuestos_count != 1 else ''} creado{'s' if presupuestos_count != 1 else ''}\n\n¿En qué área específica necesitas ayuda? Puedo asistirte con obras, inventario, presupuestos o configurar nuevos proyectos."
    
    except Exception as e:
        return f"⚠️ Hubo un problema procesando tu consulta. Por favor, intenta reformular tu pregunta o contacta soporte técnico. Error: {str(e)[:100]}"


def generar_calculo_materiales_basico(mensaje_lower=""):
    """Genera cálculo básico de materiales para construcción"""
    
    # Detectar tipo de obra y superficie
    superficie = 100  # Default
    tipo_obra = "casa"
    
    # Buscar números en el mensaje para superficie
    import re
    numeros = re.findall(r'\d+', mensaje_lower)
    if numeros:
        superficie = int(numeros[0])
    
    # Detectar tipo de obra
    if any(palabra in mensaje_lower for palabra in ['edificio', 'departamento']):
        tipo_obra = "edificio"
    elif any(palabra in mensaje_lower for palabra in ['galpón', 'galpon', 'industrial']):
        tipo_obra = "galpon"
    elif any(palabra in mensaje_lower for palabra in ['local', 'comercial']):
        tipo_obra = "local"
    
    # Cálculos básicos por m²
    calculos = {
        'casa': {
            'cemento': 7,  # bolsas por m²
            'arena': 0.5,  # m³ por m²
            'piedra': 0.3,  # m³ por m²
            'hierro': 25,  # kg por m²
            'ladrillo': 120,  # unidades por m²
            'cal': 2,  # bolsas por m²
            'membrana': 1.1,  # m² por m²
            'ceramica': 1.1,  # m² por m²
        },
        'edificio': {
            'cemento': 12,
            'arena': 0.7,
            'piedra': 0.5,
            'hierro': 45,
            'ladrillo': 100,
            'cal': 3,
            'membrana': 1.1,
            'ceramica': 1.0,
        },
        'galpon': {
            'cemento': 5,
            'arena': 0.3,
            'piedra': 0.2,
            'hierro': 35,
            'ladrillo': 0,  # Construcción seca
            'cal': 1,
            'membrana': 1.2,
            'ceramica': 0,
        }
    }
    
    config = calculos.get(tipo_obra, calculos['casa'])
    
    # Calcular cantidades
    materiales = {}
    for material, factor in config.items():
        if factor > 0:
            materiales[material] = round(superficie * factor, 1)
    
    # Precios estimados (pueden variar)
    precios_base = {
        'cemento': 8500,    # por bolsa
        'arena': 25000,     # por m³
        'piedra': 30000,    # por m³
        'hierro': 1200,     # por kg
        'ladrillo': 450,    # por unidad
        'cal': 3500,        # por bolsa
        'membrana': 8500,   # por m²
        'ceramica': 4500,   # por m²
    }
    
    # Generar respuesta
    respuesta = f"🏗️ **Cálculo de materiales para {tipo_obra} de {superficie}m²:**\n\n"
    respuesta += "📋 **Lista de materiales principales:**\n"
    
    total_estimado = 0
    
    for material, cantidad in materiales.items():
        if cantidad > 0:
            precio_unit = precios_base.get(material, 0)
            subtotal = cantidad * precio_unit
            total_estimado += subtotal
            
            # Formatear unidades
            unidad = {'cemento': 'bolsas', 'cal': 'bolsas', 'arena': 'm³', 'piedra': 'm³', 
                     'hierro': 'kg', 'ladrillo': 'unid', 'membrana': 'm²', 'ceramica': 'm²'}.get(material, 'unid')
            
            respuesta += f"• **{material.title()}:** {cantidad:g} {unidad} - ${subtotal:,.0f}\n"
    
    respuesta += f"\n💰 **Costo estimado total:** ${total_estimado:,.0f} ARS\n"
    respuesta += f"💡 **Costo por m²:** ${total_estimado/superficie:,.0f} ARS\n\n"
    
    respuesta += "⚠️ **Importante:**\n"
    respuesta += "• Precios orientativos del mercado argentino\n"
    respuesta += "• Agregar 10-15% para desperdicios\n"
    respuesta += "• Verificar disponibilidad local\n"
    respuesta += "• Considerar flete y descarga\n\n"
    
    respuesta += f"🎯 **¿Necesitas más detalles?**\n"
    respuesta += "• Usa la **Calculadora Inteligente** para cotización exacta\n"
    respuesta += "• Crea un proyecto con **Configuración Automática**\n"
    respuesta += "• Consulta proveedores en tu zona"
    
    return respuesta