from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import json
import os
import requests
import logging
from app import db
from extensions import limiter, csrf
from sqlalchemy import text, func
from sqlalchemy.exc import ProgrammingError
from utils.pagination import Pagination
from utils import safe_int
from models import (
    Obra,
    EtapaObra,
    EtapaDependencia,
    TareaEtapa,
    AsignacionObra,
    Usuario,
    CertificacionAvance,
    TareaResponsables,
    ObraMiembro,
    TareaMiembro,
    TareaAvance,
    TareaAdjunto,
    TareaAvanceFoto,
    WorkCertification,
    WorkPayment,
    Cliente,
    ItemPresupuesto,
    ItemInventario,
    UsoInventario,
)
from etapas_predefinidas import obtener_etapas_disponibles, crear_etapas_para_obra
from tareas_predefinidas import (
    TAREAS_POR_ETAPA,
    obtener_tareas_por_etapa,
    slugify_nombre_etapa,
)
from calculadora_ia import (
    calcular_superficie_etapa,
    obtener_factores_todas_etapas,
    FACTORES_SUPERFICIE_ETAPA,
)
from geocoding import normalizar_direccion_argentina
from services.geocoding_service import resolve as resolve_geocode
from roles_construccion import obtener_roles_por_categoria, obtener_nombre_rol
from services.memberships import get_current_org_id, get_current_membership
from services.obras_filters import (obras_visibles_clause,
                                    obra_tiene_presupuesto_confirmado)
from services.certifications import (
    approved_entries,
    build_pending_entries,
    certification_totals,
    create_certification,
    pending_percentage,
    register_payment,
    resolve_budget_context,
)
from services import wizard_budgeting
from services.project_shared_service import ProjectSharedService
from utils.security_logger import log_data_modification, log_data_deletion

obras_bp = Blueprint('obras', __name__)

_COORD_PRECISION = Decimal('0.00000001')


def _to_coord_decimal(value):
    """Normaliza coordenadas geográficas a Decimal con 8 decimales."""
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(_COORD_PRECISION)
    except (InvalidOperation, ValueError, TypeError):
        return None


# ==== Helpers de roles/permiso - Delegados al servicio compartido ====

# Funciones auxiliares
_parse_date = ProjectSharedService.parse_date
_get_roles_usuario = ProjectSharedService.get_roles_usuario
is_admin = ProjectSharedService.is_admin
is_pm_global = ProjectSharedService.is_pm_global

# Funciones de permisos
can_manage_obra = ProjectSharedService.can_manage_obra
can_log_avance = ProjectSharedService.can_log_avance
es_miembro_obra = ProjectSharedService.es_miembro_obra


# ==== Error handlers JSON-aware ====

@obras_bp.errorhandler(404)
def handle_404(error):
    if request.path.startswith("/obras/api/"):
        return jsonify({"ok": False, "error": "Not found"}), 404
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'ok': False, 'error': 'Recurso no encontrado'}), 404
    raise error

@obras_bp.errorhandler(500)
def handle_500(error):
    if request.path.startswith("/obras/api/"):
        return jsonify({"ok": False, "error": "Internal server error"}), 500
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500
    raise error

@obras_bp.errorhandler(401)
def handle_401(error):
    if request.path.startswith("/obras/api/"):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 401
    raise error

@obras_bp.errorhandler(403)
def handle_403(error):
    if request.path.startswith("/obras/api/"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    raise error


# ==== API endpoints ====

# Ciudades principales de Argentina para sugerencias rápidas
CIUDADES_ARGENTINA = [
    {'nombre': 'Buenos Aires, CABA', 'provincia': 'Ciudad Autónoma de Buenos Aires'},
    {'nombre': 'Córdoba', 'provincia': 'Córdoba'},
    {'nombre': 'Rosario', 'provincia': 'Santa Fe'},
    {'nombre': 'Mendoza', 'provincia': 'Mendoza'},
    {'nombre': 'La Plata', 'provincia': 'Buenos Aires'},
    {'nombre': 'San Miguel de Tucumán', 'provincia': 'Tucumán'},
    {'nombre': 'Mar del Plata', 'provincia': 'Buenos Aires'},
    {'nombre': 'Salta', 'provincia': 'Salta'},
    {'nombre': 'Santa Fe', 'provincia': 'Santa Fe'},
    {'nombre': 'San Juan', 'provincia': 'San Juan'},
    {'nombre': 'Resistencia', 'provincia': 'Chaco'},
    {'nombre': 'Neuquén', 'provincia': 'Neuquén'},
    {'nombre': 'Corrientes', 'provincia': 'Corrientes'},
    {'nombre': 'Posadas', 'provincia': 'Misiones'},
    {'nombre': 'San Salvador de Jujuy', 'provincia': 'Jujuy'},
    {'nombre': 'Bahía Blanca', 'provincia': 'Buenos Aires'},
    {'nombre': 'Paraná', 'provincia': 'Entre Ríos'},
    {'nombre': 'Formosa', 'provincia': 'Formosa'},
    {'nombre': 'San Luis', 'provincia': 'San Luis'},
    {'nombre': 'La Rioja', 'provincia': 'La Rioja'},
    {'nombre': 'Catamarca', 'provincia': 'Catamarca'},
    {'nombre': 'Río Gallegos', 'provincia': 'Santa Cruz'},
    {'nombre': 'Ushuaia', 'provincia': 'Tierra del Fuego'},
    {'nombre': 'Rawson', 'provincia': 'Chubut'},
    {'nombre': 'Viedma', 'provincia': 'Río Negro'},
    {'nombre': 'Santa Rosa', 'provincia': 'La Pampa'},
    # Localidades populares del GBA
    {'nombre': 'Quilmes', 'provincia': 'Buenos Aires'},
    {'nombre': 'Lanús', 'provincia': 'Buenos Aires'},
    {'nombre': 'Avellaneda', 'provincia': 'Buenos Aires'},
    {'nombre': 'Lomas de Zamora', 'provincia': 'Buenos Aires'},
    {'nombre': 'San Isidro', 'provincia': 'Buenos Aires'},
    {'nombre': 'Vicente López', 'provincia': 'Buenos Aires'},
    {'nombre': 'Tigre', 'provincia': 'Buenos Aires'},
    {'nombre': 'Pilar', 'provincia': 'Buenos Aires'},
    {'nombre': 'Morón', 'provincia': 'Buenos Aires'},
    {'nombre': 'San Martín', 'provincia': 'Buenos Aires'},
    {'nombre': 'Tres de Febrero', 'provincia': 'Buenos Aires'},
    {'nombre': 'Merlo', 'provincia': 'Buenos Aires'},
    {'nombre': 'Moreno', 'provincia': 'Buenos Aires'},
    {'nombre': 'Florencio Varela', 'provincia': 'Buenos Aires'},
    {'nombre': 'Berazategui', 'provincia': 'Buenos Aires'},
]

# Cache simple para búsquedas (evita llamadas repetidas a Nominatim)
_address_cache = {}
_cache_max_size = 100

def _get_cached_results(query):
    """Obtiene resultados del cache si existen"""
    return _address_cache.get(query.lower())

def _set_cached_results(query, results):
    """Guarda resultados en cache"""
    if len(_address_cache) >= _cache_max_size:
        # Eliminar la entrada más antigua (FIFO simple)
        oldest_key = next(iter(_address_cache))
        del _address_cache[oldest_key]
    _address_cache[query.lower()] = results

def _parse_address_query(query):
    """Parsea la query para detectar calle, número y ciudad"""
    import re

    # Patrones comunes de direcciones argentinas
    # "Av. Corrientes 1234, Buenos Aires"
    # "Calle 7 número 1234, La Plata"
    # "San Martín 500, Córdoba"

    result = {
        'street': None,
        'number': None,
        'city': None,
        'original': query
    }

    # Detectar número de calle (3-5 dígitos)
    number_match = re.search(r'\b(\d{2,5})\b', query)
    if number_match:
        result['number'] = number_match.group(1)
        # Remover el número para obtener la calle
        query_without_number = query.replace(number_match.group(1), '').strip()
    else:
        query_without_number = query

    # Detectar ciudad si hay coma
    if ',' in query_without_number:
        parts = query_without_number.split(',')
        result['street'] = parts[0].strip()
        result['city'] = parts[1].strip() if len(parts) > 1 else None
    else:
        result['street'] = query_without_number.strip()

    return result

def _format_result(item, query_lower):
    """Formatea un resultado de Nominatim para mejor visualización"""
    addr = item.get('address', {})

    # Construir dirección formateada
    parts = []

    # Calle y número
    road = addr.get('road', '')
    house_number = addr.get('house_number', '')
    if road:
        if house_number:
            parts.append(f"{road} {house_number}")
        else:
            parts.append(road)

    # Barrio/Localidad
    suburb = addr.get('suburb', '') or addr.get('neighbourhood', '')
    if suburb and suburb not in parts:
        parts.append(suburb)

    # Ciudad
    city = addr.get('city', '') or addr.get('town', '') or addr.get('village', '') or addr.get('municipality', '')
    if city and city not in parts:
        parts.append(city)

    # Provincia
    state = addr.get('state', '')
    if state and state not in parts:
        parts.append(state)

    formatted = ', '.join(parts) if parts else item.get('display_name', '')

    return {
        'display_name': item.get('display_name', ''),
        'formatted_address': formatted,
        'lat': item.get('lat'),
        'lon': item.get('lon'),
        'place_id': item.get('place_id'),
        'type': item.get('type'),
        'address': addr,
        'relevance': item.get('relevance', 0)
    }

@obras_bp.route('/api/buscar-direcciones', methods=['GET'])
@login_required
def buscar_direcciones():
    """API endpoint para buscar direcciones usando Google Maps (con fallback a Nominatim)"""
    from services.geocoding_service import search as geocoding_search

    query = request.args.get('q', '').strip()

    if not query:
        return jsonify({'ok': False, 'error': 'Query is required'}), 400

    if len(query) < 3:
        return jsonify({'ok': True, 'results': []})

    # Verificar cache primero
    cached = _get_cached_results(query)
    if cached:
        return jsonify({'ok': True, 'results': cached, 'cached': True})

    try:
        # Usar el servicio de geocoding mejorado (Google Maps con detección de localidades GBA)
        geocode_results = geocoding_search(query, limit=10)

        if not geocode_results:
            return jsonify({'ok': True, 'results': []})

        # Formatear resultados para compatibilidad con el frontend
        formatted_results = []
        for result in geocode_results:
            formatted = {
                'display_name': result.get('display_name', ''),
                'formatted_address': result.get('display_name', ''),
                'lat': result.get('lat'),
                'lon': result.get('lng'),
                'place_id': result.get('place_id'),
                'provider': result.get('provider', 'google'),
                'relevance': 100,  # Los resultados de Google ya vienen ordenados por relevancia
            }
            formatted_results.append(formatted)

        # Guardar en cache
        if formatted_results:
            _set_cached_results(query, formatted_results)

        return jsonify({'ok': True, 'results': formatted_results})

    except Exception as e:
        current_app.logger.error(f"Error searching addresses: {str(e)}")
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500


@obras_bp.route('/api/ciudades-argentina', methods=['GET'])
@login_required
def ciudades_argentina():
    """API endpoint para obtener ciudades de Argentina (para autocompletado rápido)"""
    query = request.args.get('q', '').strip().lower()

    if not query or len(query) < 2:
        return jsonify({'ok': True, 'results': CIUDADES_ARGENTINA[:10]})

    # Filtrar ciudades que coinciden
    matches = [c for c in CIUDADES_ARGENTINA if query in c['nombre'].lower() or query in c['provincia'].lower()]

    return jsonify({'ok': True, 'results': matches[:10]})


# ==== Métricas y utilidades ====

def resumen_tarea(t):
    """Calcular métricas de una tarea a prueba de nulos"""
    plan = float(t.cantidad_planificada or 0)

    ejec = float(
        db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
        .filter(TareaAvance.tarea_id == t.id, TareaAvance.status == 'aprobado')
        .scalar() or 0
    )

    pct = min((ejec/plan*100.0), 100.0) if plan > 0 else 0.0
    restante = max(plan - ejec, 0.0)

    atrasada = bool(t.fecha_fin_plan and date.today() > t.fecha_fin_plan and restante > 0)

    return {
        'plan': plan,
        'ejec': ejec,
        'pct': pct,
        'restante': restante,
        'atrasada': atrasada
    }

def D(x):
    """Helper para conversión segura a Decimal"""
    if x is None:
        return Decimal('0')
    return x if isinstance(x, Decimal) else Decimal(str(x))


def seed_tareas_para_etapa(nueva_etapa, auto_commit=True, slug=None):
    """
    Función idempotente para crear tareas predefinidas en una etapa.

    DESHABILITADA: Las tareas ahora solo se crean mediante el Wizard.
    Los materiales y mano de obra vienen del presupuesto confirmado,
    no como tareas en etapas.
    """
    # NO crear tareas automáticamente del catálogo
    # Las tareas deben venir del wizard de configuración de obra
    return 0


# ==== Rutas principales ====

@obras_bp.route("/obras")
@login_required
def obras_root():
    return redirect(url_for("obras.lista"))

@obras_bp.route('/')
@login_required
def lista():
    # Operarios pueden acceder para ver sus obras asignadas
    roles = _get_roles_usuario(current_user)
    if not getattr(current_user, 'puede_acceder_modulo', lambda _ : False)('obras') and 'operario' not in roles:
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    estado = request.args.get('estado', '')
    buscar = (request.args.get('buscar', '') or '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)

    chequear_admin = getattr(current_user, 'tiene_rol', None)
    puede_ver_borradores = bool(callable(chequear_admin) and current_user.tiene_rol('admin'))
    if not puede_ver_borradores:
        puede_ver_borradores = any(r in _get_roles_usuario(current_user) for r in ['administrador', 'admin'])

    mostrar_borradores = puede_ver_borradores and request.args.get('mostrar_borradores') == '1'

    obras = None
    if org_id:
        query = Obra.query.filter(Obra.organizacion_id == org_id)

        if not mostrar_borradores:
            query = query.filter(obras_visibles_clause(Obra))

        if estado:
            query = query.filter(Obra.estado == estado)

        if buscar:
            query = query.filter(
                db.or_(
                    Obra.nombre.contains(buscar),
                    Obra.cliente.contains(buscar),
                    Obra.direccion.contains(buscar)
                )
            )

        # OPTIMIZACIÓN: No hacer geocodificación síncrona aquí
        # La geocodificación se hace automáticamente cuando el usuario
        # hace clic en "Información del Clima" (lazy loading)

        # Sincronizar estado de obras que tienen etapas en curso pero siguen en planificación
        obras_planif = query.filter(Obra.estado == 'planificacion').all() if not estado else []
        if not estado:
            # Solo sincronizar si no hay filtro de estado (evitar queries extras)
            obras_planif = Obra.query.filter(
                Obra.organizacion_id == org_id,
                Obra.estado == 'planificacion'
            ).all()
        sync_changed = False
        for o in obras_planif:
            estado_antes = o.estado
            sincronizar_estado_obra(o)
            if o.estado != estado_antes:
                sync_changed = True
        if sync_changed:
            db.session.commit()

        obras = query.order_by(Obra.fecha_creacion.desc()).paginate(page=page, per_page=per_page, error_out=False)
    else:
        flash('Selecciona una organización para ver tus obras.', 'warning')
        # Crear objeto de paginación vacío
        obras = Pagination(None, page, per_page, 0, [])

    return render_template(
        'obras/lista.html',
        obras=obras,
        estado=estado,
        buscar=buscar,
        mostrar_borradores=mostrar_borradores,
        puede_ver_borradores=puede_ver_borradores,
        google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''),
    )

@obras_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def verificar_limite_obras(org_id):
    """Verifica si la organización puede crear más obras según su plan."""
    from models import Organizacion
    org = Organizacion.query.get(org_id)
    if not org:
        return False, "No se encontró la organización."
    limite = org.max_obras or 1
    cantidad_actual = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.estado != 'cancelada'
    ).count()
    if cantidad_actual >= limite:
        return False, f"Has alcanzado el límite de {limite} obras de tu plan. Para crear más obras, mejorá tu plan."
    return True, f"Obras: {cantidad_actual}/{limite}"


def crear():
    if not getattr(current_user, 'puede_acceder_modulo', lambda _ : False)('obras'):
        flash('No tienes permisos para crear obras.', 'danger')
        return redirect(url_for('obras.lista'))

    # Verificar límite de obras del plan
    org_id = get_current_org_id()
    puede_crear, mensaje_obras = verificar_limite_obras(org_id)
    if not puede_crear:
        flash(mensaje_obras, 'warning')
        return redirect(url_for('obras.lista'))

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')  # FIX: antes no existía la variable
        direccion = request.form.get('direccion')
        cliente_id = request.form.get('cliente_id')  # ID del cliente seleccionado
        cliente = request.form.get('cliente')
        telefono_cliente = request.form.get('telefono_cliente')
        email_cliente = request.form.get('email_cliente')
        fecha_inicio = request.form.get('fecha_inicio')
        fecha_fin_estimada = request.form.get('fecha_fin_estimada')
        presupuesto_total = request.form.get('presupuesto_total')

        if not all([nombre, cliente]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            return render_template('obras/crear.html')

        fecha_inicio_obj = None
        fecha_fin_estimada_obj = None

        if fecha_inicio:
            try:
                fecha_inicio_obj = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
            except ValueError:
                flash('Formato de fecha de inicio inválido.', 'danger')
                return render_template('obras/crear.html')

        if fecha_fin_estimada:
            try:
                fecha_fin_estimada_obj = datetime.strptime(fecha_fin_estimada, '%Y-%m-%d').date()
            except ValueError:
                flash('Formato de fecha de fin estimada inválido.', 'danger')
                return render_template('obras/crear.html')

        if fecha_inicio_obj and fecha_fin_estimada_obj and fecha_fin_estimada_obj <= fecha_inicio_obj:
            flash('La fecha de fin debe ser posterior a la fecha de inicio.', 'danger')
            return render_template('obras/crear.html')

        geocode_payload = None
        latitud, longitud = None, None
        direccion_normalizada = None
        if direccion:
            direccion_normalizada = normalizar_direccion_argentina(direccion)
            geocode_payload = resolve_geocode(direccion_normalizada)
            if geocode_payload:
                latitud = _to_coord_decimal(geocode_payload.get('lat'))
                longitud = _to_coord_decimal(geocode_payload.get('lng'))

        nueva_obra = Obra(
            nombre=nombre,
            descripcion=descripcion,
            direccion=direccion,
            direccion_normalizada=direccion_normalizada,
            latitud=latitud,
            longitud=longitud,
            cliente_id=int(cliente_id) if cliente_id else None,  # Relación con tabla clientes
            cliente=cliente,
            telefono_cliente=telefono_cliente,
            email_cliente=email_cliente,
            fecha_inicio=fecha_inicio_obj,
            fecha_fin_estimada=fecha_fin_estimada_obj,
            presupuesto_total=float(presupuesto_total) if presupuesto_total else 0,
            estado='planificacion',
            organizacion_id=current_user.organizacion_id
        )

        if geocode_payload:
            nueva_obra.geocode_place_id = geocode_payload.get('place_id')
            nueva_obra.geocode_provider = geocode_payload.get('provider')
            nueva_obra.geocode_status = geocode_payload.get('status') or 'ok'
            nueva_obra.geocode_raw = json.dumps(geocode_payload.get('raw')) if geocode_payload.get('raw') else None
            nueva_obra.geocode_actualizado = datetime.utcnow()

        try:
            db.session.add(nueva_obra)
            db.session.commit()
            log_data_modification('Obra', nueva_obra.id, 'Creada', current_user.email)
            current_app.logger.info(f'Obra creada: {nueva_obra.id} - {nombre} por usuario {current_user.email}')
            flash(f'Obra "{nombre}" creada exitosamente.', 'success')
            return redirect(url_for('obras.detalle', id=nueva_obra.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear la obra: {str(e)}', 'danger')
            current_app.logger.exception("Error creating obra")

    # Obtener lista de clientes activos de la organización
    org_id = get_current_org_id()
    clientes = []
    if org_id:
        clientes = Cliente.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).order_by(Cliente.nombre, Cliente.apellido).all()

    return render_template('obras/crear.html', clientes=clientes)

@obras_bp.route('/<int:id>')
@login_required
def detalle(id):
    roles = _get_roles_usuario(current_user)
    if not getattr(current_user, 'puede_acceder_modulo', lambda _ : False)('obras') and 'operario' not in roles:
        flash('No tienes permisos para ver obras.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    if 'operario' in roles and not es_miembro_obra(id, current_user.id):
        flash('No tienes permisos para ver esta obra.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        abort(404)

    obra = Obra.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
    if not obra_tiene_presupuesto_confirmado(obra):
        abort(404)
    etapas = obra.etapas.order_by(EtapaObra.orden).all()

    # Auto-actualizar estado de etapas según fecha de inicio
    hoy = date.today()
    etapas_actualizadas = False
    for etapa in etapas:
        if etapa.estado == 'pendiente' and etapa.fecha_inicio_estimada and etapa.fecha_inicio_estimada <= hoy:
            etapa.estado = 'en_curso'
            etapas_actualizadas = True
    if etapas_actualizadas:
        sincronizar_estado_obra(obra)
        db.session.commit()

    # Pre-cargar todas las tareas de todas las etapas en UN solo query
    etapa_ids = [e.id for e in etapas]
    todas_tareas = []
    tareas_por_etapa = {}
    if etapa_ids:
        todas_tareas = TareaEtapa.query.filter(TareaEtapa.etapa_id.in_(etapa_ids)).all()
        for t in todas_tareas:
            tareas_por_etapa.setdefault(t.etapa_id, []).append(t)

    # Auto-distribuir cantidad/unidad/fechas/horas de etapa a tareas sin datos
    from tareas_predefinidas import obtener_tareas_por_etapa as _obt_tareas_cat
    datos_distribuidos = False
    for etapa in etapas:
        tareas_etapa = tareas_por_etapa.get(etapa.id, [])
        if not tareas_etapa:
            continue

        # Verificar si alguna tarea tiene horas incorrectas comparando con catálogo
        catalogo = _obt_tareas_cat(etapa.nombre)
        cat_map = {t['nombre'].lower().strip(): t for t in catalogo}
        horas_mal = False
        for t in tareas_etapa:
            key = t.nombre.lower().strip()
            info = cat_map.get(key)
            if info and float(t.horas_estimadas or 0) != float(info.get('horas', 0)):
                horas_mal = True
                break

        sin_cantidad = any(not t.cantidad_planificada or float(t.cantidad_planificada or 0) == 0 for t in tareas_etapa)

        # Detectar cantidades mal distribuidas (todas iguales con >1 tarea)
        cant_set = set(float(t.cantidad_planificada or 0) for t in tareas_etapa)
        cant_mal = len(cant_set) <= 1 and len(tareas_etapa) > 1 and any(float(t.cantidad_planificada or 0) > 0 for t in tareas_etapa)

        # Detectar fechas desincronizadas con la etapa
        if etapa.estado in ('en_curso', 'finalizada'):
            inicio_etapa = etapa.fecha_inicio_real or etapa.fecha_inicio_estimada
            fin_etapa = etapa.fecha_fin_real or etapa.fecha_fin_estimada
        else:
            inicio_etapa = etapa.fecha_inicio_estimada
            fin_etapa = etapa.fecha_fin_estimada
        fechas_mal = False
        if inicio_etapa and fin_etapa:
            for t in tareas_etapa:
                f_ini = t.fecha_inicio_plan
                f_fin = t.fecha_fin_plan
                if f_ini and f_ini < inicio_etapa:
                    fechas_mal = True; break
                if f_fin and f_fin > fin_etapa:
                    fechas_mal = True; break
                if not f_ini or not f_fin:
                    fechas_mal = True; break

        necesita_forzar = horas_mal or cant_mal or fechas_mal
        if sin_cantidad or horas_mal or cant_mal or fechas_mal:
            try:
                distribuir_datos_etapa_a_tareas(etapa.id, forzar=necesita_forzar)
                datos_distribuidos = True
            except Exception as e:
                import traceback
                current_app.logger.error(f"Error distribuyendo etapa {etapa.id} ({etapa.nombre}): {e}\n{traceback.format_exc()}")

    if datos_distribuidos:
        db.session.commit()
        # Refrescar datos
        todas_tareas = TareaEtapa.query.filter(TareaEtapa.etapa_id.in_(etapa_ids)).all()
        tareas_por_etapa = {}
        for t in todas_tareas:
            tareas_por_etapa.setdefault(t.etapa_id, []).append(t)

    # Limpiar fechas reales de etapas pendientes (no deberían tener)
    for etapa in etapas:
        if etapa.estado == 'pendiente' and (etapa.fecha_inicio_real or etapa.fecha_fin_real):
            etapa.fecha_inicio_real = None
            etapa.fecha_fin_real = None
            db.session.flush()

    # Sync directo: fechas y cantidades redondas
    fechas_sync = False
    for etapa in etapas:
        # Fechas del cronograma: solo usar reales si la etapa arrancó
        if etapa.estado in ('en_curso', 'finalizada'):
            inicio = etapa.fecha_inicio_real or etapa.fecha_inicio_estimada
            fin = etapa.fecha_fin_real or etapa.fecha_fin_estimada
        else:
            inicio = etapa.fecha_inicio_estimada
            fin = etapa.fecha_fin_estimada
        tareas_etapa = tareas_por_etapa.get(etapa.id, [])
        if not tareas_etapa:
            continue

        for t in tareas_etapa:
            # Sync fechas con cronograma
            if inicio and fin:
                if len(tareas_etapa) == 1:
                    # Una sola tarea: exactamente las fechas de la etapa
                    if t.fecha_inicio_plan != inicio or t.fecha_fin_plan != fin:
                        t.fecha_inicio_plan = inicio
                        t.fecha_fin_plan = fin
                        t.fecha_inicio_estimada = inicio
                        t.fecha_fin_estimada = fin
                        fechas_sync = True
                else:
                    # Múltiples: ajustar si están fuera del rango
                    if not t.fecha_inicio_plan or t.fecha_inicio_plan < inicio:
                        t.fecha_inicio_plan = inicio
                        t.fecha_inicio_estimada = inicio
                        fechas_sync = True
                    if not t.fecha_fin_plan or t.fecha_fin_plan > fin:
                        t.fecha_fin_plan = fin
                        t.fecha_fin_estimada = fin
                        fechas_sync = True

            # Redondear cantidades a enteros
            if t.cantidad_planificada:
                cant_redondeada = round(float(t.cantidad_planificada))
                if cant_redondeada < 1:
                    cant_redondeada = 1
                if float(t.cantidad_planificada) != float(cant_redondeada):
                    t.cantidad_planificada = cant_redondeada
                    if t.objetivo:
                        t.objetivo = cant_redondeada
                    fechas_sync = True

    if fechas_sync:
        db.session.commit()
        todas_tareas = TareaEtapa.query.filter(TareaEtapa.etapa_id.in_(etapa_ids)).all()
        tareas_por_etapa = {}
        for t in todas_tareas:
            tareas_por_etapa.setdefault(t.etapa_id, []).append(t)

    # Auto-sync: recalcular tareas con avances aprobados que aún figuran como pendientes
    tareas_desync = [t for t in todas_tareas if t.estado == 'pendiente' and any(a.status == 'aprobado' for a in t.avances)]
    if tareas_desync:
        for t in tareas_desync:
            recalc_tarea_pct(t.id)
        # Refrescar datos después del recálculo
        todas_tareas = TareaEtapa.query.filter(TareaEtapa.etapa_id.in_(etapa_ids)).all()
        tareas_por_etapa = {}
        for t in todas_tareas:
            tareas_por_etapa.setdefault(t.etapa_id, []).append(t)

    # Calcular porcentaje de avance por etapa (tareas completadas / total tareas)
    etapas_con_avance = {}
    for etapa in etapas:
        tareas = tareas_por_etapa.get(etapa.id, [])
        if not tareas:
            etapas_con_avance[etapa.id] = 0
            continue
        completadas = sum(1 for t in tareas if t.estado in ('completada', 'finalizada'))
        etapas_con_avance[etapa.id] = round((completadas / len(tareas)) * 100, 2)

    # Calcular porcentaje total de la obra (promedio de etapas)
    if etapas:
        porcentaje_obra = round(sum(etapas_con_avance.get(e.id, 0) for e in etapas) / len(etapas), 2)
    else:
        porcentaje_obra = 0

    asignaciones = obra.asignaciones.filter_by(activo=True).all()
    usuarios_disponibles = Usuario.query.filter(
        Usuario.activo == True,
        Usuario.organizacion_id == org_id,
        Usuario.is_super_admin.is_(False)
    ).all()
    etapas_disponibles = obtener_etapas_disponibles()

    # Usar asignaciones como miembros para Equipo Asignado (AsignacionObra tiene los usuarios asignados)
    miembros = asignaciones  # Las asignaciones ya incluyen usuario, rol_en_obra, etapa_id y fecha

    # Obtener TODOS los operarios de la organización para el selector de responsables
    # (no solo los asignados a esta obra)
    todos_operarios = Usuario.query.filter(
        Usuario.activo == True,
        Usuario.organizacion_id == org_id,
        Usuario.is_super_admin.is_(False),
        db.or_(
            Usuario.rol == 'operario',
            Usuario.role == 'operario',
            Usuario.rol == 'jefe_obra',
            Usuario.role == 'pm'
        )
    ).order_by(Usuario.nombre, Usuario.apellido).all()

    responsables = [
        {
            'usuario': {
                'id': u.id,
                'nombre_completo': u.nombre_completo,
                'rol': u.rol
            },
            'rol_en_obra': 'operario'  # Rol por defecto
        }
        for u in todos_operarios
    ]

    responsables_query = responsables

    from tareas_predefinidas import TAREAS_POR_ETAPA

    cert_resumen = certification_totals(obra)
    cert_recientes = (
        obra.work_certifications.filter_by(estado='aprobada')
        .order_by(WorkCertification.approved_at.desc().nullslast(), WorkCertification.created_at.desc())
        .limit(3)
        .all()
    )

    # Obtener el presupuesto asociado y sus items (materiales/mano de obra)
    presupuesto = obra.presupuestos.filter_by(confirmado_como_obra=True).first()
    items_presupuesto = []
    if presupuesto:
        items_presupuesto = presupuesto.items.order_by(ItemPresupuesto.id.asc()).all()

    # Calcular avances de mano de obra por etapa — UN solo query agregado
    avances_mano_obra = {}
    if etapa_ids:
        from sqlalchemy import func as sa_func, case
        horas_por_etapa = (
            db.session.query(
                EtapaObra.id,
                sa_func.coalesce(sa_func.sum(
                    case(
                        (TareaAvance.horas_trabajadas.isnot(None), TareaAvance.horas_trabajadas),
                        else_=sa_func.coalesce(TareaAvance.horas, 0)
                    )
                ), 0).label('total_horas')
            )
            .join(TareaEtapa, TareaEtapa.etapa_id == EtapaObra.id)
            .join(TareaAvance, TareaAvance.tarea_id == TareaEtapa.id)
            .filter(
                EtapaObra.id.in_(etapa_ids),
                TareaAvance.status.in_(['aprobado', 'pendiente'])
            )
            .group_by(EtapaObra.id)
            .all()
        )
        horas_map = {row[0]: float(row[1] or 0) for row in horas_por_etapa}
    else:
        horas_map = {}

    for etapa in etapas:
        h = horas_map.get(etapa.id, 0)
        j = round(h / 8, 2)
        avances_mano_obra[etapa.id] = {
            'horas_ejecutadas': h,
            'jornales_ejecutados': j,
            'etapa_nombre': etapa.nombre
        }

    # Obtener cuadrillas tipo para mostrar composición en vista MO
    cuadrillas_por_etapa = {}
    try:
        from models.budgets import CuadrillaTipo
        import unicodedata
        tipo_obra_actual = getattr(obra, 'tipo_obra', 'estandar') or 'estandar'
        cuadrillas = CuadrillaTipo.query.filter_by(
            organizacion_id=obra.organizacion_id,
            tipo_obra=tipo_obra_actual,
            activo=True,
        ).all()

        def _normalizar(s):
            """Quita acentos, lowercase, para matching flexible."""
            s = s.lower().strip()
            nfkd = unicodedata.normalize('NFKD', s)
            return ''.join(c for c in nfkd if not unicodedata.combining(c))

        # Mapeo: etapa_tipo → cuadrilla info
        for c in cuadrillas:
            info = {
                'nombre': c.nombre,
                'personas': c.cantidad_personas,
                'rendimiento': float(c.rendimiento_diario or 0),
                'unidad': c.unidad_rendimiento,
                'costo_diario': float(c.costo_diario),
                'miembros': [
                    {'rol': m.rol, 'cantidad': float(m.cantidad),
                     'jornal': float(m.jornal_override or (m.escala.jornal if m.escala else 0))}
                    for m in c.miembros
                ],
                'miembros_texto': ', '.join(
                    f"{int(m.cantidad) if m.cantidad == int(m.cantidad) else float(m.cantidad)}x {m.rol}" if float(m.cantidad) != 1 else m.rol
                    for m in c.miembros
                ),
            }
            # Guardar por etapa_tipo y por nombre normalizado
            cuadrillas_por_etapa[c.etapa_tipo] = info
            cuadrillas_por_etapa[_normalizar(c.etapa_tipo)] = info

        # Mapeo adicional: nombres comunes de etapas → etapa_tipo
        ETAPA_ALIASES = {
            'excavacion': 'excavacion', 'movimiento de suelos': 'excavacion',
            'fundaciones': 'fundaciones', 'fundacion': 'fundaciones',
            'estructura': 'estructura', 'hormigon armado': 'estructura',
            'mamposteria': 'mamposteria', 'albanileria': 'mamposteria',
            'instalacion electrica': 'instalacion_electrica', 'electrica': 'instalacion_electrica',
            'instalacion sanitaria': 'instalacion_sanitaria', 'sanitaria': 'instalacion_sanitaria',
            'revoques': 'revoques', 'revoque': 'revoques',
            'pintura': 'pintura', 'pinturas': 'pintura',
            'pisos': 'pisos', 'piso': 'pisos', 'solados': 'pisos',
            'techos': 'techos', 'techo': 'techos', 'cubierta': 'techos',
        }
        for alias, etapa_tipo in ETAPA_ALIASES.items():
            if etapa_tipo in cuadrillas_por_etapa:
                cuadrillas_por_etapa[alias] = cuadrillas_por_etapa[etapa_tipo]
    except Exception:
        db.session.rollback()

    # Obtener stock transferido a esta obra (desde inventario) — con eager load del item
    stock_transferido = {}
    stock_transferido_por_nombre = {}
    stock_transferido_lista = []
    try:
        from models.inventory import StockObra, ItemInventario as InvItem
        from sqlalchemy.orm import joinedload
        stock_obra_items = StockObra.query.options(joinedload(StockObra.item)).filter_by(obra_id=obra.id).all()
        for stock in stock_obra_items:
            stock_data = {
                'cantidad_disponible': float(stock.cantidad_disponible or 0),
                'cantidad_consumida': float(stock.cantidad_consumida or 0),
                'item_nombre': stock.item.nombre if stock.item else '',
                'item_nombre_lower': stock.item.nombre.lower() if stock.item and stock.item.nombre else '',
                'item_codigo': stock.item.codigo if stock.item else '',
                'unidad': stock.item.unidad if stock.item else ''
            }
            stock_transferido[stock.item_inventario_id] = stock_data
            stock_transferido_lista.append(stock_data)
            if stock.item and stock.item.nombre:
                stock_transferido_por_nombre[stock.item.nombre.lower()] = stock_data
    except Exception:
        db.session.rollback()

    # Calcular costos desglosados para el panel de progreso
    from sqlalchemy import func

    # 1. Costo de materiales consumidos (desde uso_inventario)
    costo_materiales = db.session.query(
        db.func.coalesce(
            db.func.sum(
                UsoInventario.cantidad_usada *
                db.func.coalesce(UsoInventario.precio_unitario_al_uso, ItemInventario.precio_promedio)
            ), 0
        )
    ).join(ItemInventario, UsoInventario.item_id == ItemInventario.id
    ).filter(UsoInventario.obra_id == obra.id).scalar() or Decimal('0')

    # 2. Costo de mano de obra desde liquidaciones pagadas (costo REAL)
    from models.templates import LiquidacionMO as LiqMO, LiquidacionMOItem
    costo_mo_pagado = db.session.query(
        func.coalesce(func.sum(LiquidacionMOItem.monto), 0)
    ).join(LiqMO).filter(
        LiqMO.obra_id == obra.id,
        LiquidacionMOItem.estado == 'pagado'
    ).scalar() or Decimal('0')

    horas_pagadas = db.session.query(
        func.coalesce(func.sum(LiquidacionMOItem.horas_liquidadas), 0)
    ).join(LiqMO).filter(
        LiqMO.obra_id == obra.id,
        LiquidacionMOItem.estado == 'pagado'
    ).scalar() or Decimal('0')

    costo_mano_obra = Decimal(str(costo_mo_pagado))
    horas_trabajadas = Decimal(str(horas_pagadas))
    costo_hora = (costo_mano_obra / horas_trabajadas).quantize(Decimal('1')) if horas_trabajadas > 0 else Decimal('0')

    # 3. Costo de maquinaria desde uso aprobado (horas × costo_hora del equipo)
    costo_maquinaria = Decimal('0')
    horas_maquinaria = Decimal('0')
    try:
        from models.equipment import EquipmentUsage, Equipment
        maq_data = db.session.query(
            func.coalesce(func.sum(EquipmentUsage.horas * Equipment.costo_hora), 0),
            func.coalesce(func.sum(EquipmentUsage.horas), 0)
        ).join(Equipment).filter(
            EquipmentUsage.project_id == obra.id,
            EquipmentUsage.estado == 'aprobado'
        ).first()
        if maq_data:
            costo_maquinaria = Decimal(str(maq_data[0] or 0))
            horas_maquinaria = Decimal(str(maq_data[1] or 0))
    except Exception:
        db.session.rollback()

    # Datos para el template
    # Actualizar costo_real de la obra con datos reales (materiales + MO + maquinaria)
    costo_real_calc = float(Decimal(str(costo_materiales)) + costo_mano_obra + costo_maquinaria)
    if obra.costo_real != costo_real_calc:
        obra.costo_real = costo_real_calc
        db.session.commit()

    costos_desglosados = {
        'materiales': float(costo_materiales),
        'mano_obra': float(costo_mano_obra),
        'horas_trabajadas': float(horas_trabajadas),
        'costo_hora': float(costo_hora),
        'maquinaria': float(costo_maquinaria),
        'horas_maquinaria': float(horas_maquinaria),
        'total': costo_real_calc
    }

    # Detectar desfase en fechas de etapas (para banner de recalcular)
    hay_desfase_fechas = False
    for i in range(1, len(etapas)):
        ant = etapas[i - 1]
        act = etapas[i]
        if (ant.fecha_fin_estimada and act.fecha_inicio_estimada
                and ant.fecha_fin_estimada >= act.fecha_inicio_estimada
                and act.estado != 'finalizada'):
            hay_desfase_fechas = True
            break

    # Cargar datos de tablas nuevas de forma segura (pueden no existir en prod)
    remitos_count = 0
    remitos_list = []
    ordenes_compra_list = []
    requerimientos_list = []
    try:
        remitos_count = obra.remitos.count() if hasattr(obra, 'remitos') else 0
        remitos_list = obra.remitos.order_by(None).all() if remitos_count > 0 else []
    except Exception:
        db.session.rollback()
    try:
        ordenes_compra_list = list(obra.ordenes_compra) if hasattr(obra, 'ordenes_compra') else []
    except Exception:
        db.session.rollback()
    try:
        requerimientos_list = list(obra.requerimientos_compra) if hasattr(obra, 'requerimientos_compra') else []
    except Exception:
        db.session.rollback()

    return render_template('obras/detalle.html',
                         obra=obra,
                         etapas=etapas,
                         remitos_count=remitos_count,
                         remitos_list=remitos_list,
                         ordenes_compra_list=ordenes_compra_list,
                         requerimientos_list=requerimientos_list,
                         hay_desfase_fechas=hay_desfase_fechas,
                         etapas_con_avance=etapas_con_avance,
                         porcentaje_obra=porcentaje_obra,
                         asignaciones=asignaciones,
                         usuarios_disponibles=usuarios_disponibles,
                         miembros=miembros,
                         responsables=responsables_query,
                         responsables_json=responsables,
                         etapas_disponibles=etapas_disponibles,
                         roles_por_categoria=obtener_roles_por_categoria(),
                         TAREAS_POR_ETAPA=TAREAS_POR_ETAPA,
                         can_manage=can_manage_obra(obra),
                         current_user_id=current_user.id,
                         certificaciones_resumen=cert_resumen,
                         certificaciones_recientes=cert_recientes,
                         presupuesto=presupuesto,
                         items_presupuesto=items_presupuesto,
                         avances_mano_obra=avances_mano_obra,
                         cuadrillas_por_etapa=cuadrillas_por_etapa,
                         stock_transferido=stock_transferido,
                         stock_transferido_por_nombre=stock_transferido_por_nombre,
                         stock_transferido_lista=stock_transferido_lista,
                         costos_desglosados=costos_desglosados,
                         wizard_budget_flag=current_app.config.get('WIZARD_BUDGET_BREAKDOWN_ENABLED', False),
                         wizard_budget_shadow=current_app.config.get('WIZARD_BUDGET_SHADOW_MODE', False))

@obras_bp.route('/<int:id>/editar', methods=['POST'])
@login_required
def editar(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para editar obras.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    obra = Obra.query.get_or_404(id)

    nuevo_estado = request.form.get('estado', obra.estado)
    if nuevo_estado == 'pausada' and not obra.puede_ser_pausada_por(current_user):
        flash('No tienes permisos para pausar esta obra.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    obra.nombre = request.form.get('nombre', obra.nombre)
    obra.descripcion = request.form.get('descripcion', obra.descripcion)
    nueva_direccion = request.form.get('direccion', obra.direccion)
    obra.estado = nuevo_estado
    obra.cliente = request.form.get('cliente', obra.cliente)
    obra.telefono_cliente = request.form.get('telefono_cliente', obra.telefono_cliente)
    obra.email_cliente = request.form.get('email_cliente', obra.email_cliente)

    if nueva_direccion != obra.direccion:
        obra.direccion = nueva_direccion
        if nueva_direccion:
            coords = geolocalizar_direccion(nueva_direccion)
            if coords:
                obra.latitud, obra.longitud = coords
    obra.estado = request.form.get('estado', obra.estado)
    obra.progreso = safe_int(request.form.get('progreso', obra.progreso), default=obra.progreso)

    fecha_inicio = request.form.get('fecha_inicio')
    if fecha_inicio:
        try:
            obra.fecha_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
        except ValueError:
            pass

    fecha_fin_estimada = request.form.get('fecha_fin_estimada')
    if fecha_fin_estimada:
        try:
            obra.fecha_fin_estimada = datetime.strptime(fecha_fin_estimada, '%Y-%m-%d').date()
        except ValueError:
            pass

    presupuesto_total = request.form.get('presupuesto_total')
    if presupuesto_total:
        try:
            obra.presupuesto_total = float(presupuesto_total)
        except ValueError:
            pass

    try:
        db.session.commit()
        log_data_modification('Obra', obra.id, 'Actualizada', current_user.email)
        current_app.logger.info(f'Obra actualizada: {obra.id} - {obra.nombre} por usuario {current_user.email}')
        flash('Obra actualizada exitosamente.', 'success')
    except Exception:
        db.session.rollback()
        flash('Error al actualizar la obra.', 'danger')

    return redirect(url_for('obras.detalle', id=id))


def geolocalizar_direccion(direccion):
    """Geolocaliza una dirección usando OpenStreetMap Nominatim API"""
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {'q': f"{direccion}, Argentina", 'format': 'json', 'limit': 1, 'addressdetails': 1}
        headers = {'User-Agent': 'OBYRA-IA-Construction-Management'}
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data:
                lat = float(data[0]['lat'])
                lon = float(data[0]['lon'])
                return (lat, lon)
    except Exception as e:
        current_app.logger.warning(f"Error geolocalizando {direccion}: {str(e)}")
    return None


@obras_bp.route('/<int:id>/actualizar-coordenadas', methods=['POST'])
@login_required
def actualizar_coordenadas(id):
    """Actualiza las coordenadas de una obra (usado por geocodificación automática del clima)"""
    obra = Obra.query.get_or_404(id)

    # Verificar permisos básicos (que el usuario tenga acceso a la obra)
    if not obra.es_visible_para(current_user):
        return jsonify({'error': 'No tienes permisos para modificar esta obra'}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Datos no proporcionados'}), 400

        latitud = data.get('latitud')
        longitud = data.get('longitud')

        if latitud is None or longitud is None:
            return jsonify({'error': 'Coordenadas incompletas'}), 400

        # Validar que sean coordenadas válidas
        try:
            latitud = float(latitud)
            longitud = float(longitud)
            if not (-90 <= latitud <= 90) or not (-180 <= longitud <= 180):
                raise ValueError("Coordenadas fuera de rango")
        except (TypeError, ValueError) as e:
            return jsonify({'error': f'Coordenadas inválidas: {str(e)}'}), 400

        # Solo actualizar si no tenía coordenadas (no sobrescribir datos existentes)
        if obra.latitud is None or obra.longitud is None:
            obra.latitud = latitud
            obra.longitud = longitud
            obra.geocode_status = 'ok'
            obra.geocode_provider = 'auto_clima'
            db.session.commit()
            current_app.logger.info(f'Coordenadas actualizadas para obra {id}: {latitud}, {longitud}')
            return jsonify({'success': True, 'message': 'Coordenadas actualizadas'})
        else:
            return jsonify({'success': True, 'message': 'La obra ya tiene coordenadas'})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error al actualizar coordenadas de obra {id}: {str(e)}')
        return jsonify({'error': 'Error interno'}), 500


@obras_bp.route('/<int:id>/agregar_etapas', methods=['POST'])
@login_required
def agregar_etapas(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para gestionar etapas.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    obra = Obra.query.get_or_404(id)
    etapas_json = request.form.getlist('etapas[]')

    if not etapas_json:
        flash('Selecciona al menos una etapa.', 'warning')
        return redirect(url_for('obras.detalle', id=id))

    try:
        etapas_creadas = 0

        for etapa_json in etapas_json:
            try:
                etapa_data = json.loads(etapa_json)
                nombre = etapa_data.get('nombre', '').strip()
                descripcion = etapa_data.get('descripcion', '').strip()
                orden = int(etapa_data.get('orden', 1))

                if not nombre:
                    continue

                existe = EtapaObra.query.filter_by(obra_id=obra.id, nombre=nombre).first()
                if existe:
                    continue

                nueva_etapa = EtapaObra(
                    obra_id=obra.id,
                    nombre=nombre,
                    descripcion=descripcion,
                    orden=orden,
                    estado='pendiente'
                )

                db.session.add(nueva_etapa)
                db.session.flush()

                slug_normalizado = slugify_nombre_etapa(nombre)
                seed_tareas_para_etapa(nueva_etapa, slug=slug_normalizado)

                tareas_adicionales = etapa_data.get('tareas', [])
                for tarea_data in tareas_adicionales:
                    nombre_tarea = tarea_data.get('nombre', '').strip()
                    if nombre_tarea:
                        nueva_tarea = TareaEtapa(
                            etapa_id=nueva_etapa.id,
                            nombre=nombre_tarea,
                            descripcion=f"Tarea personalizada para {nombre}",
                            estado='pendiente'
                        )
                        db.session.add(nueva_tarea)

                etapas_creadas += 1

            except (json.JSONDecodeError, ValueError):
                continue

        if etapas_creadas > 0:
            db.session.commit()
            flash(f'Se agregaron {etapas_creadas} etapas con sus tareas correspondientes a la obra.', 'success')
        else:
            flash('No se agregaron etapas nuevas. Las etapas seleccionadas ya existen en esta obra.', 'info')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al agregar etapas: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/<int:obra_id>/asignar_usuario', methods=['POST'])
@login_required
def asignar_usuario(obra_id):
    """Asignar usuarios a obra (form tradicional + AJAX)"""
    if not is_admin():
        flash('Solo administradores pueden asignar usuarios', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    is_ajax = request.headers.get('Content-Type') == 'application/json' or 'XMLHttpRequest' in str(request.headers.get('X-Requested-With', ''))

    try:
        user_ids = request.form.getlist('user_ids[]')
        if not user_ids:
            uid = request.form.get('usuario_id')
            if uid:
                user_ids = [uid]

        if not user_ids:
            if is_ajax:
                return jsonify({"ok": False, "error": "Seleccioná al menos un usuario"}), 400
            else:
                flash('Seleccioná al menos un usuario', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))

        # Convertir user_ids a integers
        try:
            user_ids_int = [int(uid) for uid in user_ids]
        except (ValueError, TypeError):
            if is_ajax:
                return jsonify({"ok": False, "error": "IDs de usuario inválidos"}), 400
            else:
                flash('IDs de usuario inválidos', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))

        usuarios = Usuario.query.filter(Usuario.id.in_(user_ids_int)).all()
        if not usuarios:
            if is_ajax:
                return jsonify({"ok": False, "error": "Usuarios inválidos"}), 400
            else:
                flash('Usuarios inválidos', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))

        rol_en_obra = request.form.get('rol') or 'operario'
        etapa_id = request.form.get('etapa_id') or None

        creados = 0
        ya_existian = 0
        for uid in user_ids_int:
            try:
                result = db.session.execute(
                    text("""
                    INSERT INTO obra_miembros (obra_id, usuario_id, rol_en_obra, etapa_id)
                    VALUES (:o, :u, :rol, :etapa)
                    ON CONFLICT (obra_id, usuario_id) DO NOTHING
                    """), {"o": obra_id, "u": uid, "rol": rol_en_obra, "etapa": etapa_id}
                )
                if result.rowcount == 0:
                    ya_existian += 1
                else:
                    creados += 1
            except Exception:
                current_app.logger.exception(f"Error inserting user {uid}")
                db.session.rollback()
                if is_ajax:
                    return jsonify({"ok": False, "error": "Error asignando usuario"}), 500
                else:
                    flash('Error asignando usuario', 'danger')
                    return redirect(url_for('obras.detalle', id=obra_id))

        db.session.commit()

        if is_ajax:
            return jsonify({"ok": True, "creados": creados, "ya_existian": ya_existian})
        else:
            if creados > 0:
                flash(f'✅ Se asignaron {creados} usuarios a la obra', 'success')
            if ya_existian > 0:
                flash(f'ℹ️ {ya_existian} usuarios ya estaban asignados', 'info')
            return redirect(url_for('obras.detalle', id=obra_id))

    except Exception as e:
        current_app.logger.exception("obra_miembros insert error obra_id=%s", obra_id)
        db.session.rollback()

        if is_ajax:
            if isinstance(e, ProgrammingError):
                return jsonify({"ok": False, "error": "Error de esquema de base de datos"}), 500
            return jsonify({"ok": False, "error": f"Error interno: {str(e)}"}), 500
        else:
            flash(f'Error al asignar usuarios: {str(e)}', 'danger')
            return redirect(url_for('obras.detalle', id=obra_id))


@obras_bp.route('/<int:id>/etapa', methods=['POST'])
@login_required
def agregar_etapa(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para agregar etapas.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    obra = Obra.query.get_or_404(id)
    nombre = request.form.get('nombre')
    descripcion = request.form.get('descripcion')

    if not nombre:
        flash('El nombre de la etapa es obligatorio.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    ultimo_orden = db.session.query(db.func.max(EtapaObra.orden)).filter_by(obra_id=id).scalar() or 0

    nueva_etapa = EtapaObra(
        obra_id=id,
        nombre=nombre,
        descripcion=descripcion,
        orden=ultimo_orden + 1
    )

    try:
        db.session.add(nueva_etapa)
        db.session.flush()

        slug_normalizado = slugify_nombre_etapa(nombre)
        seed_tareas_para_etapa(nueva_etapa, slug=slug_normalizado)

        db.session.commit()
        flash(f'Etapa "{nombre}" agregada exitosamente con tareas predefinidas.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("ERROR al crear etapa")
        flash('Error al agregar la etapa.', 'danger')

    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route("/tareas/crear", methods=['POST'])
@login_required
def crear_tareas():
    """Crear una o múltiples tareas (con o sin sugeridas)."""
    try:
        obra_id = request.form.get("obra_id", type=int)
        obra = Obra.query.get_or_404(obra_id)

        if not can_manage_obra(obra):
            return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403
        etapa_id = request.form.get("etapa_id", type=int)
        horas = request.form.get("horas_estimadas", type=float)
        resp_id = request.form.get("responsable_id", type=int) or None
        fi = parse_date(request.form.get("fecha_inicio_plan"))
        ff = parse_date(request.form.get("fecha_fin_plan"))
        cantidad_total = request.form.get("cantidad_total", type=float) or None

        sugeridas = request.form.getlist("sugeridas[]")

        if not etapa_id:
            return jsonify(ok=False, error="Falta el ID de etapa"), 400

        etapa = EtapaObra.query.get_or_404(etapa_id)
        if etapa.obra.organizacion_id != current_user.organizacion_id:
            return jsonify(ok=False, error="Sin permisos"), 403

        # Si hay responsable, asegurarse de que esté asignado a la obra
        if resp_id:
            from models.projects import AsignacionObra
            asignacion_existente = AsignacionObra.query.filter_by(
                obra_id=obra_id,
                usuario_id=resp_id,
                activo=True
            ).first()

            if not asignacion_existente:
                # Crear asignación automáticamente
                nueva_asignacion = AsignacionObra(
                    obra_id=obra_id,
                    usuario_id=resp_id,
                    rol_en_obra='operario',
                    activo=True
                )
                db.session.add(nueva_asignacion)
                current_app.logger.info(f"Operario ID {resp_id} asignado automáticamente a obra ID {obra_id}")

        if not sugeridas:
            nombre = request.form.get("nombre", "").strip()
            if not nombre:
                return jsonify(ok=False, error="Falta el nombre"), 400

            VALID_UNITS = {'m2', 'ml', 'm3', 'un', 'h', 'kg'}
            unidad_input = request.form.get("unidad", "un").lower()
            unidad = unidad_input if unidad_input in VALID_UNITS else "un"

            t = TareaEtapa(
                etapa_id=etapa_id,
                nombre=nombre,
                responsable_id=resp_id,
                horas_estimadas=horas,
                fecha_inicio_plan=fi,
                fecha_fin_plan=ff,
                unidad=unidad,
                cantidad_planificada=cantidad_total,
                objetivo=cantidad_total  # También seteamos objetivo para cálculo de avance
            )
            db.session.add(t)
            db.session.commit()
            return jsonify(ok=True, created=1)

        created = 0
        for sid in sugeridas:
            try:
                index = int(sid)
                nombre_etapa = etapa.nombre
                tareas_disponibles = TAREAS_POR_ETAPA.get(nombre_etapa, [])

                if index >= len(tareas_disponibles):
                    continue

                tarea_data = tareas_disponibles[index]

                if isinstance(tarea_data, str):
                    nombre_tarea = tarea_data
                    tarea_unidad = "un"
                elif isinstance(tarea_data, dict):
                    nombre_tarea = tarea_data.get("nombre", "")
                    tarea_unidad = tarea_data.get("unidad", "un")
                else:
                    continue

                if not nombre_tarea:
                    continue

                t = TareaEtapa(
                    etapa_id=etapa_id,
                    nombre=nombre_tarea,
                    responsable_id=resp_id,
                    horas_estimadas=horas,
                    fecha_inicio_plan=fi,
                    fecha_fin_plan=ff,
                    unidad=tarea_unidad,
                    cantidad_planificada=cantidad_total,
                    objetivo=cantidad_total
                )
                db.session.add(t)
                created += 1

            except (ValueError, IndexError):
                continue

        if created == 0:
            db.session.rollback()
            return jsonify(ok=False, error="No se pudo crear ninguna tarea"), 400

        db.session.commit()
        return jsonify(ok=True, created=created)

    except Exception as e:
        current_app.logger.exception("Error en crear_tareas")
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


def parse_date(s):
    """Parsea fechas en múltiples formatos."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


@obras_bp.route("/asignar-usuarios", methods=['POST'])
def asignar_usuarios():
    """Asignar usuarios a múltiples tareas - Always returns JSON"""
    try:
        if not current_user.is_authenticated:
            return jsonify(ok=False, error="Usuario no autenticado"), 401

        try:
            tarea_ids = request.form.getlist('tarea_ids[]')
            user_ids = request.form.getlist('user_ids[]')
            cuota = request.form.get('cuota_objetivo', type=int)
            current_app.logger.info(f"asignar_usuarios user={current_user.id} tareas={tarea_ids} users={user_ids} cuota={cuota}")
        except Exception as e:
            current_app.logger.exception("Error parsing form data")
            return jsonify(ok=False, error=f"Error parsing request: {str(e)}"), 400

        if not tarea_ids or not user_ids:
            return jsonify(ok=False, error='Faltan tareas o usuarios'), 400

        primera_tarea = TareaEtapa.query.get(int(tarea_ids[0]))
        if not primera_tarea:
            return jsonify(ok=False, error="Tarea no encontrada"), 404

        obra = primera_tarea.etapa.obra
        if not can_manage_obra(obra):
            return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403

        # Validar usuarios - convertir a int primero
        user_ids_int = []
        for uid in user_ids:
            try:
                user_ids_int.append(int(uid))
            except (ValueError, TypeError):
                return jsonify(ok=False, error=f"ID de usuario inválido: {uid}"), 400

        # Verificar que todos los usuarios existen y pertenecen a la organización
        usuarios = Usuario.query.filter(Usuario.id.in_(user_ids_int)).all()
        if len(usuarios) != len(user_ids_int):
            return jsonify(ok=False, error="Uno o más usuarios no existen"), 404

        for user in usuarios:
            if user.organizacion_id != current_user.organizacion_id:
                return jsonify(ok=False, error=f"Usuario {user.id} no pertenece a la organización"), 403

        asignaciones_creadas = 0

        for tid in tarea_ids:
            tarea = TareaEtapa.query.get(int(tid))
            if not tarea or tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
                current_app.logger.warning(f"Skipping invalid task {tid}")
                continue

            obra_id = tarea.etapa.obra_id

            for uid in set(user_ids_int):
                existing = TareaMiembro.query.filter_by(tarea_id=int(tid), user_id=uid).first()
                if not existing:
                    nueva_asignacion = TareaMiembro(
                        tarea_id=int(tid),
                        user_id=uid,
                        cuota_objetivo=cuota
                    )
                    db.session.add(nueva_asignacion)
                    asignaciones_creadas += 1
                else:
                    existing.cuota_objetivo = cuota

                # También agregar a ObraMiembro si no existe (para que aparezca en "Equipo Asignado")
                existing_obra_miembro = ObraMiembro.query.filter_by(obra_id=obra_id, usuario_id=uid).first()
                if not existing_obra_miembro:
                    usuario = Usuario.query.get(uid)
                    rol_obra = usuario.rol if usuario else 'operario'
                    nuevo_miembro_obra = ObraMiembro(
                        obra_id=obra_id,
                        usuario_id=uid,
                        rol_en_obra=rol_obra,
                        etapa_id=tarea.etapa_id
                    )
                    db.session.add(nuevo_miembro_obra)
                    current_app.logger.info(f"Usuario {uid} agregado a equipo de obra {obra_id}")

        db.session.commit()
        return jsonify(ok=True, creados=asignaciones_creadas)

    except Exception:
        try:
            db.session.rollback()
            current_app.logger.exception('Unexpected error in asignar_usuarios')
        except Exception:
            pass
        return jsonify(ok=False, error="Error interno del servidor"), 500


# === PERCENTAGE CALCULATION FUNCTIONS ===

def suma_ejecutado(tarea_id):
    from sqlalchemy import func
    total = db.session.query(func.coalesce(func.sum(TareaAvance.cantidad), 0)).filter_by(tarea_id=tarea_id, status='aprobado').scalar()
    return float(total or 0)

def recalc_tarea_pct(tarea_id):
    tarea = TareaEtapa.query.get(tarea_id)
    if not tarea:
        return 0

    meta = float(tarea.cantidad_planificada or 0)
    ejecutado = suma_ejecutado(tarea_id)
    if meta <= 0:
        # Sin cantidad planificada: si hay algún avance aprobado, considerar 100%
        if ejecutado > 0:
            tarea.porcentaje_avance = 100
        else:
            tarea.porcentaje_avance = 0
    else:
        tarea.porcentaje_avance = min(100, round((ejecutado / meta) * 100, 2))

    # Auto-cambiar estado según porcentaje de avance
    if tarea.porcentaje_avance >= 100 and tarea.estado != 'completada':
        tarea.estado = 'completada'
        tarea.fecha_fin_real = datetime.utcnow()
        current_app.logger.info(f"Tarea {tarea.id} '{tarea.nombre}' auto-completada al alcanzar 100%")
    elif tarea.porcentaje_avance > 0 and tarea.estado == 'pendiente':
        tarea.estado = 'en_curso'
        if not tarea.fecha_inicio_real:
            tarea.fecha_inicio_real = datetime.utcnow()
        current_app.logger.info(f"Tarea {tarea.id} '{tarea.nombre}' auto-iniciada al registrar avance")

        # Aprobar automáticamente todos los avances pendientes de esta tarea
        avances_pendientes = [a for a in tarea.avances if a.status == 'pendiente']
        for avance in avances_pendientes:
            avance.status = 'aprobado'
            current_app.logger.info(f"Avance {avance.id} auto-aprobado al completar tarea {tarea.id}")

    # Auto-actualizar estado de la etapa según sus tareas
    etapa = tarea.etapa
    if etapa:
        todas_tareas = etapa.tareas.all() if hasattr(etapa.tareas, 'all') else (etapa.tareas or [])
        if todas_tareas:
            todas_completadas = all(t.estado in ('completada', 'cancelada') for t in todas_tareas)
            alguna_en_curso = any(t.estado in ('en_curso', 'completada') for t in todas_tareas)

            if todas_completadas and etapa.estado != 'finalizada':
                etapa.estado = 'finalizada'
                etapa.progreso = 100
                if not etapa.fecha_fin_real:
                    from datetime import date as date_class
                    etapa.fecha_fin_real = date_class.today()
                current_app.logger.info(f"Etapa {etapa.id} '{etapa.nombre}' auto-finalizada (todas las tareas completadas)")
            elif alguna_en_curso and etapa.estado == 'pendiente':
                etapa.estado = 'en_curso'
                if not etapa.fecha_inicio_real:
                    from datetime import date as date_class
                    etapa.fecha_inicio_real = date_class.today()
                current_app.logger.info(f"Etapa {etapa.id} '{etapa.nombre}' auto-iniciada (tarea en curso)")

            # Actualizar progreso de la etapa (% tareas completadas)
            etapa.progreso = pct_etapa(etapa)

        # Sincronizar estado de la obra según sus etapas
        obra = etapa.obra
        if obra:
            sincronizar_estado_obra(obra)

    db.session.commit()
    return float(tarea.porcentaje_avance or 0)

def pct_etapa(etapa):
    """Progreso de etapa = % de tareas completadas (lógica binaria).
    Cada tarea cuenta como 0% o 100% (done/not done).
    """
    tareas = etapa.tareas.all() if hasattr(etapa.tareas, 'all') else etapa.tareas
    if not tareas:
        return 0

    total = len(tareas)
    completadas = sum(1 for t in tareas if t.estado in ('completada', 'finalizada'))
    return round((completadas / total) * 100, 2)

def pct_obra(obra):
    """Progreso de obra = promedio simple de progreso de sus etapas."""
    etapas = obra.etapas.all() if hasattr(obra.etapas, 'all') else obra.etapas
    if not etapas:
        return 0

    etapa_pcts = [pct_etapa(e) for e in etapas]
    return round(sum(etapa_pcts) / len(etapa_pcts), 2)


def sincronizar_estado_obra(obra):
    """Sincroniza obra.estado según el estado de sus etapas.
    - Si alguna etapa está en_curso → obra en_curso
    - Si todas finalizadas → obra finalizada
    - Si no hay etapas en curso ni finalizadas → mantener estado actual
    No toca obras pausadas o canceladas (estados manuales).
    """
    if obra.estado in ('pausada', 'cancelada'):
        return
    etapas = obra.etapas.all() if hasattr(obra.etapas, 'all') else obra.etapas
    if not etapas:
        return
    estados = [e.estado for e in etapas]
    todas_finalizadas = all(e == 'finalizada' for e in estados)
    alguna_en_curso = any(e in ('en_curso',) for e in estados)
    alguna_finalizada = any(e == 'finalizada' for e in estados)

    if todas_finalizadas:
        obra.estado = 'finalizada'
        if not obra.fecha_fin_real:
            obra.fecha_fin_real = date.today()
    elif alguna_en_curso or alguna_finalizada:
        if obra.estado == 'planificacion':
            obra.estado = 'en_curso'


# === DISTRIBUCIÓN INTELIGENTE DE DATOS ETAPA → TAREAS ===

def distribuir_datos_etapa_a_tareas(etapa_id, forzar=False):
    """Distribuye horas, cantidad, unidad, fechas y rendimiento de la etapa a sus tareas.

    Lógica de arquitecto:
    - Horas por tarea = según catálogo predefinido (si existe), o distribución equitativa
    - Cantidad por tarea = proporcional a sus horas vs total horas de la etapa
    - Unidad = heredada de la etapa
    - Fechas = distribuidas secuencialmente dentro del rango de la etapa
    - Rendimiento = cantidad_tarea / horas_tarea

    Args:
        etapa_id: ID de la etapa
        forzar: Si True, sobreescribe datos existentes
    """
    from datetime import timedelta
    from tareas_predefinidas import obtener_tareas_por_etapa

    etapa = EtapaObra.query.get(etapa_id)
    if not etapa:
        return 0

    cantidad_etapa = float(etapa.cantidad_total_planificada or 0)
    unidad_etapa = etapa.unidad_medida or 'm2'
    # Solo usar fechas reales si la etapa ya arrancó
    if etapa.estado in ('en_curso', 'finalizada'):
        inicio_etapa = etapa.fecha_inicio_real or etapa.fecha_inicio_estimada
        fin_etapa = etapa.fecha_fin_real or etapa.fecha_fin_estimada
    else:
        inicio_etapa = etapa.fecha_inicio_estimada
        fin_etapa = etapa.fecha_fin_estimada

    tareas = etapa.tareas.order_by(TareaEtapa.id).all()
    if not tareas:
        return 0

    # --- PASO 1: Asignar horas proporcionales desde catálogo ---
    # Primero obtener las proporciones del catálogo, luego escalar
    # para que la suma de horas de tareas = horas reales de la etapa
    catalogo = obtener_tareas_por_etapa(etapa.nombre)
    catalogo_map = {}
    for t_cat in catalogo:
        catalogo_map[t_cat['nombre'].lower().strip()] = t_cat

    # Asignar horas del catálogo como referencia de proporciones
    for tarea in tareas:
        key = tarea.nombre.lower().strip()
        info_cat = catalogo_map.get(key)
        if info_cat:
            horas_catalogo = info_cat.get('horas', 1)
            if not tarea.horas_estimadas:
                tarea.horas_estimadas = horas_catalogo
            # Completar descripción si falta
            if not tarea.descripcion or tarea.descripcion == 'Creada via wizard':
                tarea.descripcion = info_cat.get('descripcion', '')
        elif not tarea.horas_estimadas:
            tarea.horas_estimadas = 1  # fallback mínimo

    # Escalar horas proporcionalmente para que la suma = horas de la etapa
    # Horas de la etapa = días × 9h/jornal (jornada laboral estándar)
    HORAS_JORNAL_ESCALA = 8
    horas_etapa_total = None
    if inicio_etapa and fin_etapa:
        dias = max(1, (fin_etapa - inicio_etapa).days + 1)
        horas_etapa_total = dias * HORAS_JORNAL_ESCALA

    suma_horas_catalogo = sum(float(t.horas_estimadas or 1) for t in tareas)
    if horas_etapa_total and suma_horas_catalogo > 0 and suma_horas_catalogo != horas_etapa_total:
        factor = horas_etapa_total / suma_horas_catalogo
        for tarea in tareas:
            horas_orig = float(tarea.horas_estimadas or 1)
            horas_nueva = max(1, round(horas_orig * factor))
            tarea.horas_estimadas = horas_nueva

    # --- PASO 2: Decidir qué tareas necesitan distribución ---
    if forzar:
        tareas_a_procesar = tareas
    else:
        tareas_a_procesar = [t for t in tareas if not t.cantidad_planificada or float(t.cantidad_planificada or 0) == 0]

    if not tareas_a_procesar:
        # Guardar correcciones de horas del PASO 1
        db.session.flush()
        return len(tareas)

    # --- PASO 3: Clasificar tareas (físicas vs administrativas) ---
    # Palabras clave que indican tareas de gestión/control (no consumen m²)
    _KEYWORDS_NO_CANTIDAD = {
        # Gestión y permisos
        'gestión', 'gestion', 'permisos', 'habilitación', 'habilitacion',
        'trámites', 'tramites',
        # Planes y documentación
        'plan de seguridad', 'documentación', 'documentacion',
        'confección', 'confeccion', 'checklist', 'manual de usuario',
        'entrega de documentación', 'despiece por piso',
        # Registros y relevamientos
        'registro fotográfico', 'registro fotografico',
        'relevamiento topográfico', 'relevamiento topografico',
        # Verificaciones y controles
        'verificación', 'verificacion',
        'control de calidad', 'control de compactación', 'control de compactacion',
        'control de deformaciones', 'control de resistencia', 'control de juntas',
        # Pruebas y ensayos
        'prueba de', 'pruebas y puesta', 'pruebas de presión',
        'medición y verificación', 'medicion y verificacion',
        # Inspecciones (solo "inspección final", no "trampas de inspección")
        'inspección final', 'inspeccion final', 'revisión y retoques', 'revision y retoques',
        # Estudios
        'estudio de suelos', 'estudio de nivel',
        # Tareas específicas sin m²
        'cartel de obra', 'configuración domótica', 'configuracion domotica',
        'clasificación de escombros', 'clasificacion de escombros',
    }

    def _tarea_aplica_cantidad(tarea, catalogo_map):
        """Determina si una tarea consume cantidad física (m², ml, etc.)."""
        key = tarea.nombre.lower().strip()
        info_cat = catalogo_map.get(key)
        # Si el catálogo dice explícitamente que no aplica
        if info_cat and info_cat.get('aplica_cantidad') is False:
            return False
        # Detección por nombre
        for kw in _KEYWORDS_NO_CANTIDAD:
            if kw in key:
                return False
        return True

    tareas_fisicas = [t for t in tareas_a_procesar if _tarea_aplica_cantidad(t, catalogo_map)]
    tareas_admin = [t for t in tareas_a_procesar if not _tarea_aplica_cantidad(t, catalogo_map)]

    # --- PASO 4: Distribución proporcional ---
    # Horas: proporcional sobre TODAS las tareas
    total_horas_todas = sum(float(t.horas_estimadas or 1) for t in tareas_a_procesar)
    if total_horas_todas <= 0:
        total_horas_todas = len(tareas_a_procesar)

    # Cantidad: proporcional sobre solo tareas FÍSICAS
    total_horas_fisicas = sum(float(t.horas_estimadas or 1) for t in tareas_fisicas)
    if total_horas_fisicas <= 0:
        total_horas_fisicas = 1

    # Duración de la etapa en días
    dias_etapa = 0
    if inicio_etapa and fin_etapa:
        dias_etapa = max(1, (fin_etapa - inicio_etapa).days)

    actualizadas = 0

    # --- Pre-calcular fechas por tarea usando jornal de 9 horas ---
    # Lógica: un día de obra = 9 horas. Tareas se agrupan en el mismo día
    # si caben en las horas restantes del jornal. Se encadenan secuencialmente.
    HORAS_JORNAL = 8

    fechas_tareas = []  # lista de (f_ini, f_fin) por tarea
    if inicio_etapa and fin_etapa and dias_etapa > 0:
        dia_actual = 0
        horas_restantes_dia = HORAS_JORNAL

        for tarea in tareas_a_procesar:
            horas_t = float(tarea.horas_estimadas or 1)

            # ¿Cabe en el día actual?
            if horas_restantes_dia <= 0:
                # Día lleno, avanzar al siguiente
                dia_actual += 1
                horas_restantes_dia = HORAS_JORNAL

            f_ini = inicio_etapa + timedelta(days=dia_actual)

            # Calcular cuántos días necesita esta tarea
            if horas_t <= horas_restantes_dia:
                # Cabe en el día actual
                dias_tarea = 0  # mismo día (f_ini == f_fin)
                horas_restantes_dia -= horas_t
            else:
                # Necesita más de un día
                horas_pendientes = horas_t - horas_restantes_dia
                dias_extra = int(horas_pendientes // HORAS_JORNAL)
                if horas_pendientes % HORAS_JORNAL > 0:
                    dias_extra += 1
                dias_tarea = dias_extra  # días adicionales después del inicio
                horas_restantes_dia = HORAS_JORNAL - (horas_pendientes % HORAS_JORNAL)
                if horas_restantes_dia == HORAS_JORNAL:
                    horas_restantes_dia = 0  # terminó justo al final del último día

            f_fin = f_ini + timedelta(days=dias_tarea)

            # Seguridad: nunca exceder la etapa
            if f_ini > fin_etapa:
                f_ini = fin_etapa
            if f_fin > fin_etapa:
                f_fin = fin_etapa

            fechas_tareas.append((f_ini, f_fin))

            # Si la tarea ocupó días completos, avanzar al día siguiente
            if horas_restantes_dia <= 0:
                dia_actual += dias_tarea + 1
                horas_restantes_dia = HORAS_JORNAL
            else:
                dia_actual += dias_tarea

    for i, tarea in enumerate(tareas_a_procesar):
        horas_tarea = float(tarea.horas_estimadas or 1)
        es_fisica = tarea in tareas_fisicas

        # Cantidad: solo para tareas físicas, proporcional a sus horas
        if cantidad_etapa > 0 and es_fisica and unidad_etapa not in ('h', 'día', 'dia'):
            proporcion_cant = horas_tarea / total_horas_fisicas
            cant = round(cantidad_etapa * proporcion_cant)  # entero
            cant = max(1, cant)
            tarea.cantidad_planificada = cant
            tarea.objetivo = cant
            tarea.unidad = unidad_etapa
        else:
            # Meta basada en horas reales de la tarea
            tarea.cantidad_planificada = max(1, round(horas_tarea))
            tarea.objetivo = tarea.cantidad_planificada
            tarea.unidad = 'h'

        # Rendimiento: cantidad por hora (solo para unidades físicas como m², ml, etc.)
        if horas_tarea > 0 and float(tarea.cantidad_planificada or 0) > 0 and tarea.unidad not in ('h', 'día', 'dia', 'gl', 'global'):
            tarea.rendimiento = round(float(tarea.cantidad_planificada) / horas_tarea, 1)
        else:
            tarea.rendimiento = None

        # Fechas: encadenar secuencialmente usando jornal de 9h
        if fechas_tareas and i < len(fechas_tareas):
            f_ini, f_fin = fechas_tareas[i]

            if forzar or not tarea.fecha_inicio_plan:
                tarea.fecha_inicio_plan = f_ini
            if forzar or not tarea.fecha_fin_plan:
                tarea.fecha_fin_plan = f_fin
            if forzar or not tarea.fecha_inicio_estimada:
                tarea.fecha_inicio_estimada = f_ini
            if forzar or not tarea.fecha_fin_estimada:
                tarea.fecha_fin_estimada = f_fin

        actualizadas += 1

    if actualizadas:
        db.session.flush()

    return actualizadas


# === ETAPAS ENCADENADAS — PROPAGACIÓN DE FECHAS ===

def propagar_fechas_etapas(obra_id):
    """Propaga fechas entre etapas usando dependencias y niveles.

    Algoritmo:
    1. Usa dependencias explícitas (tabla etapa_dependencias) si existen.
    2. Si no, deriva del nivel_encadenamiento (nivel N depende de nivel N-1).
    3. Si no tiene nivel ni dependencias, fallback secuencial por orden.
    4. Orden topológico. Para cada etapa:
       - Skip si fechas_manuales == True
       - Skip si estado == 'finalizada'
       - inicio_más_temprano = max(pred.fin_efectivo + 1 + lag)
       - Solo desplaza hacia adelante, preservando duración.
    Retorna dict con shifted_count y details.
    """
    from services.dependency_service import propagar_fechas_obra
    from datetime import timedelta

    etapas_modificadas = propagar_fechas_obra(obra_id)

    details = []
    for etapa in etapas_modificadas:
        details.append({
            'etapa': etapa.nombre,
            'new_inicio': str(etapa.fecha_inicio_estimada),
            'new_fin': str(etapa.fecha_fin_estimada),
        })

        # Re-distribuir fechas de tareas secuencialmente dentro del nuevo rango
        distribuir_datos_etapa_a_tareas(etapa.id, forzar=True)

    return {'shifted_count': len(etapas_modificadas), 'details': details}


def _propagar_fechas_tareas(etapa, delta):
    """Desplaza fechas de tareas no completadas de una etapa por delta días."""
    tareas = etapa.tareas.filter(
        TareaEtapa.estado.notin_(['completada', 'cancelada'])
    ).all()

    for t in tareas:
        if t.fecha_inicio_plan:
            t.fecha_inicio_plan = t.fecha_inicio_plan + delta
        if t.fecha_fin_plan:
            t.fecha_fin_plan = t.fecha_fin_plan + delta
        if t.fecha_inicio_estimada:
            t.fecha_inicio_estimada = t.fecha_inicio_estimada + delta
        if t.fecha_fin_estimada:
            t.fecha_fin_estimada = t.fecha_fin_estimada + delta
        if t.fecha_inicio:
            t.fecha_inicio = t.fecha_inicio + delta
        if t.fecha_fin:
            t.fecha_fin = t.fecha_fin + delta


UNIT_MAP = {
    "m2": "m2", "m²": "m2", "M2": "m2", "metro2": "m2",
    "m3": "m3", "m³": "m3", "M3": "m3", "metro3": "m3",
    "ml": "ml", "m": "ml", "metro": "ml",
    "u": "un", "un": "un", "unidad": "un", "uni": "un", "unidades": "un",
    "kg": "kg", "kilo": "kg", "kilos": "kg",
    "h": "h", "hr": "h", "hora": "h", "horas": "h", "hs": "h",
    "lt": "lt", "l": "lt", "lts": "lt", "litro": "lt", "litros": "lt"
}

def normalize_unit(unit):
    if not unit or not str(unit).strip():
        return "un"
    unit_clean = str(unit).strip().lower()
    return UNIT_MAP.get(unit_clean, unit_clean)


@obras_bp.route("/tareas/<int:tarea_id>/avances", methods=['POST'])
@csrf.exempt
@login_required
def crear_avance(tarea_id):
    """Registrar avance con fotos (operarios desde dashboard)."""
    try:
        return _crear_avance_impl(tarea_id)
    except Exception as e:
        db.session.rollback()
        import traceback
        tb = traceback.format_exc()
        current_app.logger.error(f"Error en crear_avance: {tb}")
        return jsonify(ok=False, error=f"Error interno: {str(e)}"), 500


def _crear_avance_impl(tarea_id):
    from werkzeug.utils import secure_filename
    from pathlib import Path

    tarea = TareaEtapa.query.get_or_404(tarea_id)

    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'operario', 'administrador', 'tecnico', 'project_manager'}):
        return jsonify(ok=False, error="⛔ Solo usuarios con rol de operario, PM o administrador pueden registrar avances. Contactá a tu administrador para cambiar tu rol."), 403

    if 'operario' in roles:
        is_responsible = tarea.responsable_id == current_user.id
        is_assigned = TareaMiembro.query.filter_by(tarea_id=tarea.id, user_id=current_user.id).first()
        if not (is_responsible or is_assigned):
            return jsonify(ok=False, error="⛔ No estás asignado a esta tarea. Pedí al PM o administrador que te asigne para poder registrar avances."), 403

    if not can_log_avance(tarea):
        return jsonify(ok=False, error="⛔ No podés registrar avances en esta tarea. Verificá que la tarea esté en estado activo."), 403

    cantidad_str = str(request.form.get("cantidad", "")).replace(",", ".")
    try:
        cantidad = float(cantidad_str)
        if cantidad <= 0:
            return jsonify(ok=False, error="❌ La cantidad debe ser mayor a 0. Ingresá un valor positivo para el avance."), 400
    except (ValueError, TypeError):
        return jsonify(ok=False, error="❌ Cantidad inválida. Ingresá un número válido (ej: 10 o 10.5)."), 400

    # Usar la unidad seleccionada por el usuario, con fallback a la de la tarea
    unidad_form = request.form.get("unidad_ingresada", "").strip()
    unidad = normalize_unit(unidad_form) if unidad_form else normalize_unit(tarea.unidad)

    # Validar que no se exceda la cantidad planificada
    # Solo validar si la unidad ingresada coincide con la planificada
    plan = float(tarea.cantidad_planificada or 0)
    unidad_tarea = normalize_unit(tarea.unidad) if tarea.unidad else ''
    misma_unidad = (unidad == unidad_tarea) or not unidad_form
    if plan > 0 and misma_unidad:
        ejecutado = float(
            db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
            .filter(TareaAvance.tarea_id == tarea.id, TareaAvance.status == 'aprobado')
            .scalar() or 0
        )
        disponible = plan - ejecutado
        if disponible <= 0:
            return jsonify(ok=False, error=f"❌ Esta tarea ya alcanzó el 100% de avance ({plan} {tarea.unidad}). No se pueden registrar más avances."), 400
        if cantidad > disponible:
            return jsonify(ok=False, error=f"❌ La cantidad ({cantidad}) supera lo restante ({disponible:.2f} {tarea.unidad}). Máximo permitido: {disponible:.2f}."), 400
    horas = request.form.get("horas", type=float)
    notas = request.form.get("notas", "")

    # Si admin/PM especifica un operario_id, usar ese como user_id del avance
    avance_user_id = current_user.id
    operario_id = request.form.get("operario_id", type=int)
    if operario_id and roles & {'admin', 'pm', 'administrador', 'tecnico', 'project_manager'}:
        # Validar que el operario sea miembro de la obra (no solo de la tarea)
        obra = tarea.etapa.obra
        is_obra_member = AsignacionObra.query.filter_by(obra_id=obra.id, usuario_id=operario_id).first()
        is_resp = tarea.responsable_id == operario_id
        is_task_member = TareaMiembro.query.filter_by(tarea_id=tarea.id, user_id=operario_id).first()
        if is_resp or is_task_member or is_obra_member:
            avance_user_id = operario_id

    av = TareaAvance(
        tarea_id=tarea.id,
        user_id=avance_user_id,
        cantidad=cantidad,
        unidad=unidad,
        horas=horas,
        notas=notas,
        cantidad_ingresada=cantidad,
        unidad_ingresada=unidad_form or unidad
    )

    # Admin/PM/Técnico: avances se auto-aprueban siempre
    # Operarios: avances quedan pendientes de aprobación
    if roles & {'admin', 'pm', 'administrador', 'tecnico', 'project_manager'}:
        av.status = "aprobado"
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()
    else:
        av.status = "pendiente"

    db.session.add(av)

    if not tarea.fecha_inicio_real and av.status == "aprobado":
        tarea.fecha_inicio_real = datetime.utcnow()

    uploaded_files = request.files.getlist("fotos")
    for f in uploaded_files:
        if f.filename:
            fname = secure_filename(f.filename)
            base = Path(current_app.static_folder) / "uploads" / "obras" / str(tarea.etapa.obra_id) / "tareas" / str(tarea.id)
            base.mkdir(parents=True, exist_ok=True)
            file_path = base / fname
            f.save(file_path)

            adjunto = TareaAdjunto(
                tarea_id=tarea.id,
                avance_id=av.id,
                uploaded_by=current_user.id,
                path=f"/static/uploads/obras/{tarea.etapa.obra_id}/tareas/{tarea.id}/{fname}"
            )
            db.session.add(adjunto)

    # Procesar materiales consumidos y descontar del stock DE LA OBRA
    from models.inventory import StockObra, MovimientoStockObra

    material_ids = request.form.getlist("material_id[]")
    material_cantidades = request.form.getlist("material_cantidad[]")
    obra_id = tarea.etapa.obra_id

    if material_ids and len(material_ids) > 0:
        for i, material_id_str in enumerate(material_ids):
            if not material_id_str or material_id_str == '':
                continue

            try:
                material_id = int(material_id_str)
                cantidad_consumida = Decimal(str(material_cantidades[i])) if i < len(material_cantidades) else Decimal("0")

                if cantidad_consumida <= 0:
                    continue

                item = ItemInventario.query.get(material_id)
                if not item:
                    db.session.rollback()
                    return jsonify(ok=False, error=f"Material ID {material_id} no encontrado en inventario."), 400

                stock_obra = StockObra.query.filter_by(
                    obra_id=obra_id,
                    item_inventario_id=material_id
                ).first()

                if stock_obra and float(stock_obra.cantidad_disponible or 0) > 0:
                    disponible_obra = Decimal(str(stock_obra.cantidad_disponible or 0))

                    if disponible_obra >= cantidad_consumida:
                        stock_obra.cantidad_disponible = float(disponible_obra - cantidad_consumida)
                        stock_obra.cantidad_consumida = float(
                            Decimal(str(stock_obra.cantidad_consumida or 0)) + cantidad_consumida
                        )
                        stock_obra.fecha_ultimo_uso = datetime.utcnow()

                        movimiento = MovimientoStockObra(
                            stock_obra_id=stock_obra.id,
                            tipo='consumo',
                            cantidad=float(cantidad_consumida),
                            usuario_id=current_user.id,
                            observaciones=f"Consumido en avance de tarea: {tarea.nombre} (ID:{tarea.id})",
                            precio_unitario=float(item.precio_promedio or 0)
                        )
                        db.session.add(movimiento)
                    else:
                        stock_obra.cantidad_disponible = 0
                        stock_obra.cantidad_consumida = float(
                            Decimal(str(stock_obra.cantidad_consumida or 0)) + disponible_obra
                        )
                        stock_obra.fecha_ultimo_uso = datetime.utcnow()

                        movimiento = MovimientoStockObra(
                            stock_obra_id=stock_obra.id,
                            tipo='consumo',
                            cantidad=float(disponible_obra),
                            usuario_id=current_user.id,
                            observaciones=f"Consumido en avance de tarea: {tarea.nombre} (ID:{tarea.id}, parcial)",
                            precio_unitario=float(item.precio_promedio or 0)
                        )
                        db.session.add(movimiento)

                precio_unitario = float(item.precio_promedio or 0)
                uso = UsoInventario(
                    obra_id=obra_id,
                    item_id=item.id,
                    cantidad_usada=cantidad_consumida,
                    fecha_uso=datetime.utcnow().date(),
                    usuario_id=current_user.id,
                    observaciones=f"Consumido en avance de tarea: {tarea.nombre}",
                    precio_unitario_al_uso=precio_unitario,
                    moneda='ARS'
                )
                db.session.add(uso)

            except (ValueError, IndexError) as e:
                db.session.rollback()
                return jsonify(ok=False, error=f"Error procesando material: {str(e)}"), 400

    db.session.commit()

    # Recalcular porcentaje de avance de la tarea
    nuevo_pct = recalc_tarea_pct(tarea_id)

    # Recalcular progreso general de la OBRA
    obra = tarea.etapa.obra
    obra.calcular_progreso_automatico()

    # Calcular y actualizar el costo real de la obra
    costo_materiales = db.session.query(
        db.func.coalesce(
            db.func.sum(
                UsoInventario.cantidad_usada *
                db.func.coalesce(UsoInventario.precio_unitario_al_uso, ItemInventario.precio_promedio)
            ), 0
        )
    ).join(ItemInventario, UsoInventario.item_id == ItemInventario.id
    ).filter(UsoInventario.obra_id == obra.id).scalar() or Decimal('0')

    # Costo MO = suma de liquidaciones (lo realmente liquidado, no estimado)
    from models import LiquidacionMO
    costo_mano_obra = db.session.query(
        db.func.coalesce(db.func.sum(LiquidacionMO.monto_total), 0)
    ).filter(LiquidacionMO.obra_id == obra.id).scalar() or Decimal('0')

    obra.costo_real = Decimal(str(costo_materiales)) + Decimal(str(costo_mano_obra))

    db.session.commit()

    return jsonify(
        ok=True,
        mensaje="Avance registrado y materiales descontados del stock",
        porcentaje_avance=nuevo_pct,
        estado=tarea.estado,
        cantidad_planificada=float(tarea.cantidad_planificada or 0),
        cantidad_ejecutada=suma_ejecutado(tarea_id)
    )



@obras_bp.route("/api/tareas/<int:tarea_id>/avances", methods=['POST'])
@login_required
def api_crear_avance_fotos(tarea_id):
    """Create progress entry with multiple photos - specification compliant"""
    return ProjectSharedService.api_crear_avance_fotos(tarea_id, normalize_unit, recalc_tarea_pct)


@obras_bp.route("/tareas/<int:tarea_id>/complete", methods=['POST'])
@login_required
def completar_tarea(tarea_id):
    """Completar tarea - solo si restante = 0"""
    from models import resumen_tarea as _rt

    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra

    if not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403

    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403

    try:
        m = _rt(tarea)
        if m["restante"] > 0:
            return jsonify(ok=False, error="Aún faltan cantidades"), 400

        tarea.estado = "completada"
        tarea.fecha_fin_real = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en completar_tarea")
        return jsonify(ok=False, error="Error interno"), 500


def _serialize_tarea_detalle(tarea):
    """Construye el payload detallado de una tarea para API y vistas"""
    obra = tarea.etapa.obra if tarea.etapa else None

    def _format_date(dt):
        return dt.strftime('%d/%m/%Y') if dt else None

    def _format_datetime(dt):
        return dt.isoformat() if dt else None

    def _to_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    avances = sorted(
        list(tarea.avances),
        key=lambda a: a.created_at or datetime.min,
        reverse=True,
    )

    aprobados = [a for a in avances if a.status == 'aprobado']

    fechas_reales = [a.fecha for a in aprobados if a.fecha]
    if not fechas_reales:
        fechas_reales = [a.fecha for a in avances if a.fecha]

    fecha_inicio_real = min(fechas_reales) if fechas_reales else None
    fecha_fin_real = max(fechas_reales) if fechas_reales else None
    duracion_real_dias = None
    if fecha_inicio_real and fecha_fin_real:
        try:
            duracion_real_dias = (fecha_fin_real - fecha_inicio_real).days + 1
        except Exception:
            duracion_real_dias = None

    def _safe_sum(iterable):
        total = 0.0
        for a in iterable:
            v = _to_float(a.cantidad if a.cantidad is not None else a.cantidad_ingresada)
            if v is not None:
                total += v
        return total

    cantidad_plan = _to_float(tarea.cantidad_planificada) or 0.0
    cantidad_ejecutada = _safe_sum(aprobados)

    cantidad_restante = 0.0
    if cantidad_plan > 0:
        cantidad_restante = max(cantidad_plan - cantidad_ejecutada, 0.0)

    status_labels = {'aprobado': 'Aprobado', 'pendiente': 'Pendiente', 'rechazado': 'Rechazado'}

    avances_data = []
    for avance in avances:
        avances_data.append({
            'id': avance.id,
            'fecha': _format_date(avance.fecha) or _format_date(avance.created_at.date() if avance.created_at else None),
            'fecha_iso': avance.fecha.isoformat() if avance.fecha else None,
            'creado_en': _format_datetime(avance.created_at),
            'cantidad': _to_float(avance.cantidad if avance.cantidad is not None else avance.cantidad_ingresada),
            'unidad': avance.unidad or tarea.unidad,
            'horas': _to_float(avance.horas or getattr(avance, 'horas_trabajadas', None)),
            'notas': avance.notas or '',
            'status': avance.status or 'pendiente',
            'status_label': status_labels.get(avance.status, (avance.status or 'Registrado').title()),
            'usuario': getattr(avance.usuario, 'nombre_completo', None),
            'fotos': [
                {
                    'id': foto.id,
                    'url': url_for('serve_media', relpath=foto.file_path),
                    'created_at': _format_datetime(foto.created_at),
                }
                for foto in sorted(
                    list(avance.fotos),
                    key=lambda f: f.created_at or avance.created_at or datetime.min,
                    reverse=True,
                )
            ]
        })

    fotos_data = []
    total_fotos = 0
    for avance in avances:
        for foto in sorted(
            list(avance.fotos),
            key=lambda f: f.created_at or avance.created_at or datetime.min,
            reverse=True,
        ):
            total_fotos += 1
            fotos_data.append({
                'id': foto.id,
                'avance_id': avance.id,
                'url': url_for('serve_media', relpath=foto.file_path),
                'thumbnail_url': url_for('serve_media', relpath=foto.file_path),
                'status': avance.status,
                'status_label': status_labels.get(avance.status, (avance.status or 'Registrado').title()),
                'fecha': _format_date(avance.fecha) or _format_date(foto.created_at.date() if foto.created_at else None),
                'fecha_iso': avance.fecha.isoformat() if avance.fecha else None,
                'capturado_en': _format_datetime(foto.created_at),
                'registrado_en': _format_datetime(avance.created_at),
                'subido_por': getattr(avance.usuario, 'nombre_completo', None),
                'cantidad': _to_float(avance.cantidad if avance.cantidad is not None else avance.cantidad_ingresada),
                'unidad': avance.unidad or tarea.unidad,
                'notas': avance.notas or '',
            })

    payload = {
        'ok': True,
        'tarea': {
            'id': tarea.id,
            'nombre': tarea.nombre,
            'descripcion': tarea.descripcion,
            'estado': tarea.estado,
            'etapa': tarea.etapa.nombre if tarea.etapa else None,
            'obra': obra.nombre if obra else None,
            'obra_id': obra.id if obra else None,
            'unidad': tarea.unidad,
            'cantidad_planificada': cantidad_plan,
            'cantidad_ejecutada': cantidad_ejecutada,
            'cantidad_restante': cantidad_restante,
            'fecha_inicio_plan': _format_datetime(tarea.fecha_inicio_plan),
            'fecha_fin_plan': _format_datetime(tarea.fecha_fin_plan),
            'fecha_inicio_plan_label': _format_date(tarea.fecha_inicio_plan),
            'fecha_fin_plan_label': _format_date(tarea.fecha_fin_plan),
            'fecha_inicio_real': _format_datetime(fecha_inicio_real),
            'fecha_fin_real': _format_datetime(fecha_fin_real),
            'fecha_inicio_real_label': _format_date(fecha_inicio_real),
            'fecha_fin_real_label': _format_date(fecha_fin_real),
            'duracion_real_dias': duracion_real_dias,
            'total_avances': len(avances),
            'total_fotos': total_fotos,
            'responsable': getattr(tarea.responsable, 'nombre_completo', None),
            'ultimo_registro': _format_datetime(avances[0].created_at) if avances else None,
        },
        'avances': avances_data,
        'fotos': fotos_data,
    }
    return payload


@obras_bp.route('/mis-tareas')
@login_required
def mis_tareas():
    from collections import OrderedDict
    from sqlalchemy import or_

    # Buscar tareas donde el usuario sea:
    # 1. Responsable (responsable_id)
    # 2. Miembro asignado (TareaMiembro)
    q_responsable = (
        db.session.query(TareaEtapa)
        .join(EtapaObra, EtapaObra.id == TareaEtapa.etapa_id)
        .join(Obra, Obra.id == EtapaObra.obra_id)
        .filter(TareaEtapa.responsable_id == current_user.id)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
    )

    q_miembro = (
        db.session.query(TareaEtapa)
        .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
        .join(EtapaObra, EtapaObra.id == TareaEtapa.etapa_id)
        .join(Obra, Obra.id == EtapaObra.obra_id)
        .filter(TareaMiembro.user_id == current_user.id)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
    )

    # Unir ambas consultas y eliminar duplicados
    tareas = q_responsable.union(q_miembro).order_by(TareaEtapa.id.desc()).all()
    current_app.logger.info(
        "mis_tareas user=%s unidades=%s",
        current_user.id,
        [(t.id, t.unidad, t.rendimiento) for t in tareas],
    )

    estados = OrderedDict([
        ('pendiente', {'label': 'Pendientes', 'icon': 'far fa-circle'}),
        ('en_curso', {'label': 'En curso', 'icon': 'fas fa-play-circle'}),
        ('completada', {'label': 'Finalizadas', 'icon': 'fas fa-check-circle'}),
    ])

    tareas_por_estado = {clave: [] for clave in estados.keys()}
    for tarea in tareas:
        estado_normalizado = (tarea.estado or 'pendiente').lower()
        if estado_normalizado not in tareas_por_estado:
            estado_normalizado = 'pendiente'
        tareas_por_estado[estado_normalizado].append(tarea)

    resumen_estados = {clave: len(valor) for clave, valor in tareas_por_estado.items()}

    return render_template(
        'obras/mis_tareas.html',
        tareas=tareas,
        tareas_por_estado=tareas_por_estado,
        estados=estados,
        resumen_estados=resumen_estados,
    )


@obras_bp.route('/mis-tareas/<int:tarea_id>')
@login_required
def mis_tareas_detalle(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra if tarea.etapa else None

    if not obra or obra.organizacion_id != current_user.organizacion_id:
        flash('No tienes permisos para ver esta tarea.', 'danger')
        return redirect(url_for('obras.mis_tareas'))

    es_responsable = tarea.responsable_id == current_user.id
    es_miembro = any(mi.user_id == current_user.id for mi in tarea.miembros)

    if not (es_responsable or es_miembro or can_manage_obra(obra)):
        flash('No tienes permisos para ver esta tarea.', 'danger')
        return redirect(url_for('obras.mis_tareas'))

    payload = _serialize_tarea_detalle(tarea)

    # Los operarios NO ven la sección de actualizar estado manualmente
    # El estado se actualiza automáticamente al registrar avances
    roles = ProjectSharedService.get_roles_usuario(current_user)
    es_operario = 'operario' in roles
    puede_actualizar_estado = (es_responsable or es_miembro) and not es_operario

    return render_template(
        'obras/mis_tareas_detalle.html',
        tarea=tarea,
        obra=obra,
        detalle=payload['tarea'],
        avances=payload['avances'],
        puede_actualizar_estado=puede_actualizar_estado,
    )


@obras_bp.route('/api/mis-tareas/<int:tarea_id>/estado', methods=['POST'])
@login_required
def api_mis_tareas_estado(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra if tarea.etapa else None

    if not obra or obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    es_responsable = tarea.responsable_id == current_user.id
    es_miembro = any(mi.user_id == current_user.id for mi in tarea.miembros)

    if not (es_responsable or es_miembro or can_manage_obra(obra)):
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    data = request.get_json(silent=True) or {}
    nuevo_estado = (data.get('estado') or '').lower()
    estados_validos = {'pendiente', 'en_curso', 'completada'}

    if nuevo_estado not in estados_validos:
        return jsonify({'ok': False, 'error': 'Estado no válido'}), 400

    try:
        cambio_realizado = tarea.estado != nuevo_estado
        tarea.estado = nuevo_estado

        ahora = datetime.utcnow()
        if nuevo_estado == 'en_curso' and tarea.fecha_inicio_real is None:
            tarea.fecha_inicio_real = ahora
        if nuevo_estado == 'completada':
            if tarea.fecha_inicio_real is None:
                tarea.fecha_inicio_real = ahora
            tarea.fecha_fin_real = ahora

        db.session.commit()
        payload = _serialize_tarea_detalle(tarea)
        return jsonify({
            'ok': True,
            'cambio': cambio_realizado,
            'tarea': payload['tarea'],
        })
    except Exception as exc:
        current_app.logger.exception('Error actualizando estado de tarea %s: %s', tarea_id, exc)
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'No se pudo actualizar la tarea'}), 500


@obras_bp.route('/api/tareas/<int:tarea_id>/avances-pendientes')
@login_required
def obtener_avances_pendientes(tarea_id):
    """API endpoint para obtener avances pendientes de una tarea con fotos"""
    from utils.permissions import is_admin_or_pm

    if not is_admin_or_pm(current_user):
        return jsonify(ok=False, error="Sin permisos"), 403

    tarea = TareaEtapa.query.get_or_404(tarea_id)

    # Verificar pertenencia a la organización usando membresía activa o fallback
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if tarea.etapa.obra.organizacion_id != org_id:
        return jsonify(ok=False, error="Sin permiso"), 403

    # Recalcular porcentaje de la tarea (por si hay avances que no se reflejaron)
    recalc_tarea_pct(tarea_id)

    try:
        avances_pendientes = (
            TareaAvance.query
            .filter_by(tarea_id=tarea_id, status='pendiente')
            .order_by(TareaAvance.created_at.desc())
            .all()
        )

        avances_data = []
        for avance in avances_pendientes:
            fotos = []
            for foto in avance.fotos:
                fotos.append({
                    'id': foto.id,
                    'url': f"/media/{foto.file_path}",
                    'thumbnail_url': f"/media/{foto.file_path}",
                    'width': foto.width,
                    'height': foto.height,
                    'mime_type': foto.mime_type
                })

            avances_data.append({
                'id': avance.id,
                'cantidad': float(avance.cantidad),
                'unidad': avance.unidad,
                'horas': float(avance.horas or 0),
                'notas': avance.notas or '',
                'fecha': avance.created_at.strftime('%d/%m/%Y %H:%M'),
                'operario': {
                    'id': avance.usuario.id,
                    'nombre': avance.usuario.nombre_completo
                },
                'fotos': fotos,
                'fotos_count': len(fotos)
            })

        # Historial de avances aprobados
        avances_aprobados = (
            TareaAvance.query
            .filter_by(tarea_id=tarea_id, status='aprobado')
            .order_by(TareaAvance.created_at.desc())
            .all()
        )
        historial = []
        for av in avances_aprobados:
            fotos_h = []
            for foto in av.fotos:
                fotos_h.append({
                    'id': foto.id,
                    'url': f"/media/{foto.file_path}",
                    'thumbnail_url': f"/media/{foto.file_path}",
                })
            historial.append({
                'id': av.id,
                'cantidad': float(av.cantidad),
                'unidad': av.unidad,
                'horas': float(av.horas or 0),
                'notas': av.notas or '',
                'fecha': av.created_at.strftime('%d/%m/%Y %H:%M'),
                'operario': av.usuario.nombre_completo if av.usuario else 'N/A',
                'aprobado_por': av.confirmado_por.nombre_completo if av.confirmado_por else 'Auto',
                'fotos': fotos_h,
            })

        # Obtener miembros para el selector de operario
        # Mostrar TODOS los miembros de la obra (responsable primero, luego resto)
        miembros_data = []
        seen_ids = set()

        # Primero el responsable de la tarea (si existe)
        if tarea.responsable:
            miembros_data.append({'id': tarea.responsable.id, 'nombre': tarea.responsable.nombre_completo})
            seen_ids.add(tarea.responsable.id)

        # Miembros asignados a la tarea
        for m in tarea.miembros:
            if m.usuario and m.user_id not in seen_ids:
                miembros_data.append({'id': m.usuario.id, 'nombre': m.usuario.nombre_completo})
                seen_ids.add(m.user_id)

        # Todos los miembros de la obra (siempre, no solo como fallback)
        obra = tarea.etapa.obra
        for asig in obra.asignaciones:
            if asig.usuario and asig.usuario.id not in seen_ids:
                miembros_data.append({'id': asig.usuario.id, 'nombre': asig.usuario.nombre_completo})
                seen_ids.add(asig.usuario.id)

        # Siempre incluir al usuario actual como opción
        if current_user.id not in seen_ids:
            miembros_data.append({'id': current_user.id, 'nombre': current_user.nombre_completo})
            seen_ids.add(current_user.id)

        # Info de progreso
        plan = float(tarea.cantidad_planificada or 0)
        ejecutado = suma_ejecutado(tarea_id)

        return jsonify({
            'ok': True,
            'tarea': {
                'id': tarea.id,
                'nombre': tarea.nombre,
                'unidad': tarea.unidad,
                'cantidad_planificada': plan,
                'ejecutado': ejecutado,
                'porcentaje': float(tarea.porcentaje_avance or 0),
                'estado': tarea.estado,
            },
            'avances': avances_data,
            'total': len(avances_data),
            'historial': historial,
            'miembros': miembros_data,
            'responsable_id': tarea.responsable_id
        })

    except Exception as e:
        current_app.logger.exception("Error al obtener avances pendientes")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route('/api/tareas/<int:tarea_id>/galeria')
@login_required
def api_tarea_galeria(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra if tarea.etapa else None

    if not obra or obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    puede_ver = False
    if can_manage_obra(obra):
        puede_ver = True
    elif tarea.responsable_id == current_user.id:
        puede_ver = True
    else:
        for miembro in tarea.miembros:
            if miembro.user_id == current_user.id:
                puede_ver = True
                break

    if not puede_ver:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    return jsonify(_serialize_tarea_detalle(tarea))


@obras_bp.route('/etapa/<int:id>/tarea', methods=['POST'])
@login_required
def agregar_tarea(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para agregar tareas.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    etapa = EtapaObra.query.get_or_404(id)

    horas_estimadas = request.form.get('horas_estimadas')
    responsable_id = request.form.get('responsable_id')
    fecha_inicio_plan = request.form.get('fecha_inicio_plan')
    fecha_fin_plan = request.form.get('fecha_fin_plan')

    fecha_inicio_plan_date = None
    fecha_fin_plan_date = None
    if fecha_inicio_plan:
        try:
            fecha_inicio_plan_date = datetime.strptime(fecha_inicio_plan, '%Y-%m-%d').date()
        except ValueError:
            pass
    if fecha_fin_plan:
        try:
            fecha_fin_plan_date = datetime.strptime(fecha_fin_plan, '%Y-%m-%d').date()
        except ValueError:
            pass

    tareas_sugeridas = []
    form_keys = list(request.form.keys())
    for key in form_keys:
        if key.startswith('sugeridas[') and key.endswith('][nombre]'):
            index = key.split('[')[1].split(']')[0]
            nombre_sugerida = request.form.get(f'sugeridas[{index}][nombre]')
            descripcion_sugerida = request.form.get(f'sugeridas[{index}][descripcion]', '')
            if nombre_sugerida:
                tareas_sugeridas.append({
                    'nombre': nombre_sugerida,
                    'descripcion': descripcion_sugerida
                })

    if tareas_sugeridas:
        tareas_creadas = 0
        try:
            for tarea_data in tareas_sugeridas:
                nueva_tarea = TareaEtapa(
                    etapa_id=id,
                    nombre=tarea_data['nombre'],
                    descripcion=tarea_data['descripcion'],
                    horas_estimadas=float(horas_estimadas) if horas_estimadas else None,
                    responsable_id=int(responsable_id) if responsable_id else None,
                    fecha_inicio_plan=fecha_inicio_plan_date,
                    fecha_fin_plan=fecha_fin_plan_date
                )
                db.session.add(nueva_tarea)
                tareas_creadas += 1

            db.session.commit()
            return jsonify({'ok': True, 'created': tareas_creadas})
        except Exception:
            db.session.rollback()
            return jsonify({'ok': False, 'error': 'Error al crear las tareas múltiples'})

    else:
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')

        if not nombre:
            flash('El nombre de la tarea es obligatorio.', 'danger')
            return redirect(url_for('obras.detalle', id=etapa.obra_id))

        nueva_tarea = TareaEtapa(
            etapa_id=id,
            nombre=nombre,
            descripcion=descripcion,
            horas_estimadas=float(horas_estimadas) if horas_estimadas else None,
            responsable_id=int(responsable_id) if responsable_id else None,
            fecha_inicio_plan=fecha_inicio_plan_date,
            fecha_fin_plan=fecha_fin_plan_date
        )

        try:
            db.session.add(nueva_tarea)
            db.session.commit()
            flash(f'Tarea "{nombre}" agregada exitosamente.', 'success')
        except Exception:
            db.session.rollback()
            flash('Error al agregar la tarea.', 'danger')

        return redirect(url_for('obras.detalle', id=etapa.obra_id))


@obras_bp.route('/admin/backfill_tareas', methods=['POST'])
@login_required
def admin_backfill_tareas():
    if not current_user.is_super_admin:
        flash('No tienes permisos para ejecutar el backfill.', 'danger')
        return redirect(url_for('obras.lista'))

    try:
        etapas_procesadas = 0
        tareas_creadas_total = 0

        etapas = EtapaObra.query.all()

        for etapa in etapas:
            tareas_existentes = TareaEtapa.query.filter_by(etapa_id=etapa.id).count()
            if tareas_existentes < 5:
                tareas_nuevas = seed_tareas_para_etapa(etapa)
                tareas_creadas_total += tareas_nuevas
                etapas_procesadas += 1

        db.session.commit()

        flash(f'Backfill completado: {etapas_procesadas} etapas procesadas, {tareas_creadas_total} tareas creadas.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("ERROR en backfill")
        flash(f'Error en backfill: {str(e)}', 'danger')

    return redirect(url_for('obras.lista'))


@obras_bp.route('/etapas/<int:etapa_id>/tareas')
@login_required
def api_listar_tareas(etapa_id):
    etapa = EtapaObra.query.get_or_404(etapa_id)

    if etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    if is_pm_global():
        # Solo mostrar tareas que fueron realmente seleccionadas por el usuario desde el wizard
        # Estas tareas tienen responsable O fechas planificadas (no materiales con solo cantidad)
        q = (TareaEtapa.query
             .filter(TareaEtapa.etapa_id == etapa_id)
             .filter(
                 db.or_(
                     TareaEtapa.responsable_id.isnot(None),
                     TareaEtapa.fecha_inicio_plan.isnot(None),
                     TareaEtapa.fecha_fin_plan.isnot(None)
                 )
             )
             .options(db.joinedload(TareaEtapa.miembros).joinedload(TareaMiembro.usuario)))
    else:
        if not es_miembro_obra(etapa.obra_id, current_user.id):
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        q = (TareaEtapa.query
             .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
             .filter(TareaEtapa.etapa_id == etapa_id,
                     TareaMiembro.user_id == current_user.id)
             .filter(
                 db.or_(
                     TareaEtapa.responsable_id.isnot(None),
                     TareaEtapa.fecha_inicio_plan.isnot(None),
                     TareaEtapa.fecha_fin_plan.isnot(None)
                 )
             )
             .options(db.joinedload(TareaEtapa.miembros).joinedload(TareaMiembro.usuario)))

    try:
        tareas = q.order_by(TareaEtapa.id.asc()).all()
        html = render_template('obras/_tareas_lista.html', tareas=tareas)
        return jsonify({'ok': True, 'html': html})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error al cargar tareas: {str(e)}'}), 500


@obras_bp.route('/api/obras/<int:obra_id>/reservar-materiales', methods=['POST'])
@login_required
def api_reservar_materiales(obra_id):
    """
    Genera reservas de stock en inventario para los materiales del presupuesto de la obra.
    Solo procesa materiales que estén VINCULADOS a items del inventario.
    Si no hay stock suficiente, genera alertas de compra.
    """
    try:
        from models.inventory import ItemInventario, ReservaStock

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        # Obtener presupuesto confirmado
        presupuesto = obra.presupuestos.filter_by(confirmado_como_obra=True).first()
        if not presupuesto:
            return jsonify({'ok': False, 'error': 'Esta obra no tiene presupuesto confirmado'}), 400

        # Obtener materiales del presupuesto
        materiales = [item for item in presupuesto.items if item.tipo == 'material']

        if not materiales:
            return jsonify({'ok': False, 'error': 'No hay materiales en el presupuesto'}), 400

        reservas_creadas = []
        alertas_compra = []
        materiales_sin_vincular = []

        for material in materiales:
            # Solo procesar materiales que estén VINCULADOS a un item del inventario
            if not material.item_inventario_id:
                materiales_sin_vincular.append({
                    'descripcion': material.descripcion,
                    'cantidad': float(material.cantidad),
                    'unidad': material.unidad
                })
                continue

            # Obtener el item del inventario vinculado
            item_inv = ItemInventario.query.get(material.item_inventario_id)
            if not item_inv:
                materiales_sin_vincular.append({
                    'descripcion': material.descripcion,
                    'cantidad': float(material.cantidad),
                    'unidad': material.unidad
                })
                continue

            current_app.logger.info(f"✅ Procesando material '{material.descripcion}' vinculado a '{item_inv.nombre}'")

            # Calcular stock disponible (stock actual - reservas activas)
            stock_actual = float(item_inv.stock_actual or 0)

            # Obtener reservas activas para este item
            reservas_activas = ReservaStock.query.filter_by(
                item_inventario_id=item_inv.id,
                estado='activa'
            ).all()
            stock_reservado = sum(float(r.cantidad) for r in reservas_activas)
            stock_disponible = stock_actual - stock_reservado

            cantidad_necesaria = float(material.cantidad)

            # Verificar si ya existe una reserva para este material en esta obra
            reserva_existente = ReservaStock.query.filter_by(
                item_inventario_id=item_inv.id,
                obra_id=obra.id,
                estado='activa'
            ).first()

            if reserva_existente:
                # Ya existe reserva, actualizar cantidad si es necesario
                reservas_creadas.append({
                    'material': item_inv.nombre,
                    'cantidad': float(reserva_existente.cantidad),
                    'unidad': item_inv.unidad,
                    'nota': 'Ya reservado'
                })
                continue

            if stock_disponible >= cantidad_necesaria:
                # Hay stock suficiente, crear reserva
                reserva = ReservaStock(
                    item_inventario_id=item_inv.id,
                    obra_id=obra.id,
                    cantidad=cantidad_necesaria,
                    estado='activa',
                    usuario_id=current_user.id
                )
                db.session.add(reserva)
                reservas_creadas.append({
                    'material': item_inv.nombre,
                    'cantidad': cantidad_necesaria,
                    'unidad': item_inv.unidad
                })
            else:
                # No hay stock suficiente, generar alerta
                alertas_compra.append({
                    'material': item_inv.nombre,
                    'cantidad_necesaria': cantidad_necesaria,
                    'stock_disponible': max(0, stock_disponible),
                    'faltante': cantidad_necesaria - max(0, stock_disponible),
                    'unidad': item_inv.unidad
                })

        db.session.commit()

        return jsonify({
            'ok': True,
            'reservas_creadas': len(reservas_creadas),
            'alertas_compra': len(alertas_compra),
            'materiales_sin_match': len(materiales_sin_vincular),
            'detalle': {
                'reservas': reservas_creadas,
                'alertas': alertas_compra,
                'sin_match': materiales_sin_vincular
            }
        })

    except Exception as e:
        current_app.logger.exception(f"Error al reservar materiales: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/reservas', methods=['GET'])
@login_required
def api_obtener_reservas(obra_id):
    """
    Obtiene las reservas de stock activas para una obra.
    """
    try:
        from models.inventory import ReservaStock, ItemInventario

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        reservas = ReservaStock.query.filter_by(
            obra_id=obra_id
        ).join(ItemInventario).all()

        reservas_data = []
        for r in reservas:
            reservas_data.append({
                'id': r.id,
                'item_id': r.item_inventario_id,
                'item_nombre': r.item.nombre,
                'item_codigo': r.item.codigo,
                'cantidad': float(r.cantidad),
                'unidad': r.item.unidad,
                'estado': r.estado,
                'fecha': r.fecha_reserva.strftime('%d/%m/%Y %H:%M') if r.fecha_reserva else None
            })

        return jsonify({
            'ok': True,
            'reservas': reservas_data,
            'total_activas': len([r for r in reservas_data if r['estado'] == 'activa']),
            'total_consumidas': len([r for r in reservas_data if r['estado'] == 'consumida'])
        })

    except Exception as e:
        current_app.logger.exception(f"Error al obtener reservas: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/analizar-materiales', methods=['GET'])
@login_required
def api_analizar_materiales(obra_id):
    """
    Analiza TODOS los materiales del presupuesto contra el inventario.
    Clasifica cada material en: con_stock, stock_parcial, sin_stock.
    Usado por el modal unificado de Gestión de Materiales.
    """
    try:
        from models.inventory import ItemInventario, ReservaStock

        obra = Obra.query.get_or_404(obra_id)
        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        presupuesto = obra.presupuestos.filter_by(confirmado_como_obra=True).first()
        if not presupuesto:
            return jsonify({'ok': False, 'error': 'Esta obra no tiene presupuesto confirmado'}), 400

        materiales = [item for item in presupuesto.items if item.tipo == 'material']
        if not materiales:
            return jsonify({'ok': False, 'error': 'No hay materiales en el presupuesto'}), 400

        # Obtener cantidades ya pedidas en requerimientos de compra activos
        ya_pedido_por_item = {}  # item_inventario_id -> cantidad total pedida
        ya_pedido_por_desc = {}  # descripcion (lower) -> cantidad total pedida
        try:
            from models.inventory import RequerimientoCompra, RequerimientoCompraItem
            reqs = RequerimientoCompra.query.filter(
                RequerimientoCompra.obra_id == obra.id,
                RequerimientoCompra.estado.notin_(['cancelado', 'rechazado'])
            ).all()
            for req in reqs:
                for item in req.items:
                    cant = float(item.cantidad or 0)
                    if item.item_inventario_id:
                        ya_pedido_por_item[item.item_inventario_id] = ya_pedido_por_item.get(item.item_inventario_id, 0) + cant
                    if item.descripcion:
                        key = item.descripcion.lower().strip()
                        ya_pedido_por_desc[key] = ya_pedido_por_desc.get(key, 0) + cant
        except Exception:
            db.session.rollback()

        con_stock = []
        stock_parcial = []
        sin_stock = []
        sin_vincular = []

        for material in materiales:
            cantidad_necesaria = float(material.cantidad or 0)
            if cantidad_necesaria <= 0:
                continue

            if not material.item_inventario_id:
                sin_vincular.append({
                    'descripcion': material.descripcion,
                    'cantidad': cantidad_necesaria,
                    'unidad': material.unidad or 'unidad',
                    'codigo': material.codigo or ''
                })
                continue

            item_inv = ItemInventario.query.get(material.item_inventario_id)
            if not item_inv:
                sin_vincular.append({
                    'descripcion': material.descripcion,
                    'cantidad': cantidad_necesaria,
                    'unidad': material.unidad or 'unidad',
                    'codigo': material.codigo or ''
                })
                continue

            # Calcular stock disponible (stock actual - reservas activas de OTRAS obras)
            stock_actual = float(item_inv.stock_actual or 0)
            reservas_activas = ReservaStock.query.filter_by(
                item_inventario_id=item_inv.id,
                estado='activa'
            ).all()
            stock_reservado = sum(float(r.cantidad) for r in reservas_activas)

            # Reserva existente para ESTA obra
            reserva_esta_obra = next(
                (r for r in reservas_activas if r.obra_id == obra.id), None
            )
            ya_reservado = float(reserva_esta_obra.cantidad) if reserva_esta_obra else 0

            # Stock disponible = actual - reservado por otros
            stock_disponible = stock_actual - stock_reservado + ya_reservado

            # Cantidad ya pedida en requerimientos
            cant_pedida = ya_pedido_por_item.get(item_inv.id, 0) or ya_pedido_por_desc.get(item_inv.nombre.lower().strip(), 0)

            item_data = {
                'item_inventario_id': item_inv.id,
                'descripcion': item_inv.nombre,
                'codigo': item_inv.codigo or '',
                'unidad': item_inv.unidad or 'unidad',
                'cantidad_necesaria': cantidad_necesaria,
                'stock_disponible': max(0, stock_disponible),
                'ya_reservado': ya_reservado,
                'ya_pedido': cant_pedida > 0,
                'cantidad_pedida': cant_pedida,
            }

            if ya_reservado >= cantidad_necesaria:
                item_data['estado'] = 'ya_reservado'
                con_stock.append(item_data)
            elif stock_disponible >= cantidad_necesaria:
                item_data['estado'] = 'disponible'
                item_data['a_reservar'] = cantidad_necesaria
                con_stock.append(item_data)
            elif stock_disponible > 0:
                item_data['estado'] = 'parcial'
                item_data['a_reservar'] = stock_disponible
                item_data['faltante'] = cantidad_necesaria - stock_disponible
                stock_parcial.append(item_data)
            else:
                item_data['estado'] = 'sin_stock'
                item_data['faltante'] = cantidad_necesaria
                sin_stock.append(item_data)

        return jsonify({
            'ok': True,
            'obra_nombre': obra.nombre,
            'con_stock': con_stock,
            'stock_parcial': stock_parcial,
            'sin_stock': sin_stock,
            'sin_vincular': sin_vincular,
            'resumen': {
                'total_materiales': len(con_stock) + len(stock_parcial) + len(sin_stock) + len(sin_vincular),
                'con_stock': len(con_stock),
                'parcial': len(stock_parcial),
                'sin_stock': len(sin_stock),
                'sin_vincular': len(sin_vincular)
            }
        })

    except Exception as e:
        current_app.logger.exception(f"Error al analizar materiales: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/gestionar-materiales', methods=['POST'])
@login_required
def api_gestionar_materiales(obra_id):
    """
    Endpoint unificado: reserva stock + crea solicitud de compra en un solo paso.
    Recibe:
    - reservar: [{item_inventario_id, cantidad}] — items a reservar
    - comprar: [{item_inventario_id, descripcion, cantidad, unidad, ...}] — items a solicitar
    - motivo, prioridad, fecha_necesidad — datos de la solicitud de compra
    """
    try:
        from models.inventory import (
            ItemInventario, ReservaStock,
            RequerimientoCompra, RequerimientoCompraItem
        )

        obra = Obra.query.get_or_404(obra_id)
        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        items_reservar = data.get('reservar', [])
        items_comprar = data.get('comprar', [])
        motivo = data.get('motivo', 'Falta de material en obra')
        prioridad = data.get('prioridad', 'normal')
        fecha_necesidad_str = data.get('fecha_necesidad')

        reservas_resultado = []
        compra_resultado = None

        # ── 1. Crear reservas ──
        for item_data in items_reservar:
            item_inv_id = item_data.get('item_inventario_id')
            cantidad = float(item_data.get('cantidad', 0))
            if not item_inv_id or cantidad <= 0:
                continue

            item_inv = ItemInventario.query.get(item_inv_id)
            if not item_inv:
                continue

            # Verificar si ya existe reserva para esta obra
            reserva_existente = ReservaStock.query.filter_by(
                item_inventario_id=item_inv.id,
                obra_id=obra.id,
                estado='activa'
            ).first()

            if reserva_existente:
                # Actualizar cantidad si la nueva es mayor
                if cantidad > float(reserva_existente.cantidad):
                    reserva_existente.cantidad = cantidad
                reservas_resultado.append({
                    'material': item_inv.nombre,
                    'cantidad': float(reserva_existente.cantidad),
                    'unidad': item_inv.unidad,
                    'accion': 'actualizada'
                })
            else:
                # Verificar stock disponible
                stock_actual = float(item_inv.stock_actual or 0)
                reservas_otros = ReservaStock.query.filter(
                    ReservaStock.item_inventario_id == item_inv.id,
                    ReservaStock.estado == 'activa',
                    ReservaStock.obra_id != obra.id
                ).all()
                stock_reservado_otros = sum(float(r.cantidad) for r in reservas_otros)
                stock_libre = stock_actual - stock_reservado_otros

                cantidad_real = min(cantidad, max(0, stock_libre))
                if cantidad_real > 0:
                    reserva = ReservaStock(
                        item_inventario_id=item_inv.id,
                        obra_id=obra.id,
                        cantidad=cantidad_real,
                        estado='activa',
                        usuario_id=current_user.id
                    )
                    db.session.add(reserva)
                    reservas_resultado.append({
                        'material': item_inv.nombre,
                        'cantidad': cantidad_real,
                        'unidad': item_inv.unidad,
                        'accion': 'creada'
                    })

        # ── 2. Crear solicitud de compra (si hay items) ──
        if items_comprar:
            from datetime import datetime as dt
            org_id = current_user.organizacion_id

            requerimiento = RequerimientoCompra(
                numero=RequerimientoCompra.generar_numero(org_id),
                organizacion_id=org_id,
                obra_id=obra.id,
                solicitante_id=current_user.id,
                motivo=motivo,
                prioridad=prioridad,
                fecha_necesidad=dt.strptime(fecha_necesidad_str, '%Y-%m-%d').date() if fecha_necesidad_str else None
            )
            db.session.add(requerimiento)
            db.session.flush()

            for item_data in items_comprar:
                item = RequerimientoCompraItem(
                    requerimiento_id=requerimiento.id,
                    item_inventario_id=item_data.get('item_inventario_id') or None,
                    descripcion=item_data.get('descripcion', ''),
                    codigo=item_data.get('codigo', ''),
                    cantidad=float(item_data.get('cantidad', 1)),
                    unidad=item_data.get('unidad', 'unidad'),
                    cantidad_planificada=float(item_data.get('cantidad_planificada', 0)),
                    cantidad_actual_obra=float(item_data.get('cantidad_actual_obra', 0)),
                    tipo=item_data.get('tipo', 'material')
                )
                db.session.add(item)

            compra_resultado = {
                'requerimiento_id': requerimiento.id,
                'numero': requerimiento.numero,
                'items_count': len(items_comprar)
            }

        db.session.commit()

        # Notificar si se creó solicitud de compra
        if compra_resultado:
            try:
                from blueprint_requerimientos import _notificar_nuevo_requerimiento
                req = RequerimientoCompra.query.get(compra_resultado['requerimiento_id'])
                if req:
                    _notificar_nuevo_requerimiento(req)
            except Exception as notify_err:
                current_app.logger.warning(f"Error al notificar: {notify_err}")

        return jsonify({
            'ok': True,
            'reservas': {
                'count': len(reservas_resultado),
                'detalle': reservas_resultado
            },
            'compra': compra_resultado,
            'message': _build_result_message(reservas_resultado, compra_resultado)
        })

    except Exception as e:
        current_app.logger.exception(f"Error en gestionar-materiales: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


def _build_result_message(reservas, compra):
    """Construye mensaje de resumen para el usuario."""
    parts = []
    if reservas:
        parts.append(f'{len(reservas)} material(es) reservado(s)')
    if compra:
        parts.append(f'Solicitud de compra {compra["numero"]} creada con {compra["items_count"]} item(s)')
    return ' | '.join(parts) if parts else 'No se realizaron acciones'


@obras_bp.route('/api/obras/<int:obra_id>/consumir-material', methods=['POST'])
@login_required
def api_consumir_material(obra_id):
    """
    Consume material de una reserva activa.
    - Descuenta del stock real (ItemInventario.stock_actual)
    - Marca la reserva como 'consumida' (total) o reduce cantidad (parcial)
    - Registra el uso en UsoInventario
    """
    try:
        from models.inventory import ReservaStock, ItemInventario, UsoInventario, MovimientoInventario
        from decimal import Decimal
        from datetime import datetime

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        reserva_id = data.get('reserva_id')
        cantidad_consumir = float(data.get('cantidad', 0))
        observaciones = data.get('observaciones', '')

        if not reserva_id or cantidad_consumir <= 0:
            return jsonify({'ok': False, 'error': 'Reserva y cantidad son requeridos'}), 400

        # Obtener reserva
        reserva = ReservaStock.query.get(reserva_id)
        if not reserva or reserva.obra_id != obra_id:
            return jsonify({'ok': False, 'error': 'Reserva no encontrada'}), 404

        if reserva.estado != 'activa':
            return jsonify({'ok': False, 'error': f'La reserva no está activa (estado: {reserva.estado})'}), 400

        cantidad_reservada = float(reserva.cantidad)
        if cantidad_consumir > cantidad_reservada:
            return jsonify({
                'ok': False,
                'error': f'No puedes consumir más de lo reservado ({cantidad_reservada} {reserva.item.unidad})'
            }), 400

        item = reserva.item  # ItemInventario

        # Verificar stock disponible
        stock_actual = float(item.stock_actual or 0)
        if stock_actual < cantidad_consumir:
            return jsonify({
                'ok': False,
                'error': f'No hay stock físico suficiente de {item.nombre} (disponible: {stock_actual})'
            }), 400

        # Descontar del stock físico
        item.stock_actual = float(Decimal(str(stock_actual)) - Decimal(str(cantidad_consumir)))

        # Registrar movimiento de egreso
        movimiento = MovimientoInventario(
            item_id=item.id,
            tipo='salida',
            cantidad=cantidad_consumir,
            motivo=f'Consumo en obra: {obra.nombre}',
            observaciones=observaciones or f'Consumido de reserva #{reserva_id}',
            usuario_id=current_user.id
        )
        db.session.add(movimiento)

        # Actualizar reserva
        if cantidad_consumir >= cantidad_reservada:
            # Consumo total
            reserva.estado = 'consumida'
            reserva.fecha_consumo = datetime.utcnow()
        else:
            # Consumo parcial - reducir cantidad reservada
            reserva.cantidad = float(Decimal(str(cantidad_reservada)) - Decimal(str(cantidad_consumir)))

        # Registrar uso en obra (para historial y costos)
        uso = UsoInventario(
            obra_id=obra_id,
            item_id=item.id,
            cantidad_usada=cantidad_consumir,
            observaciones=observaciones or f'Consumido de reserva #{reserva_id}',
            usuario_id=current_user.id,
            precio_unitario_al_uso=item.precio_promedio,
            moneda='ARS'
        )
        db.session.add(uso)

        db.session.commit()

        # Verificar si queda stock bajo
        stock_restante = float(item.stock_actual or 0)
        stock_minimo = float(item.stock_minimo or 0)
        alerta_stock_bajo = stock_restante <= stock_minimo

        return jsonify({
            'ok': True,
            'mensaje': f'Consumidos {cantidad_consumir} {item.unidad} de {item.nombre}',
            'reserva_estado': reserva.estado,
            'stock_restante': stock_restante,
            'alerta_stock_bajo': alerta_stock_bajo
        })

    except Exception as e:
        current_app.logger.exception(f"Error al consumir material: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/liberar-reserva', methods=['POST'])
@login_required
def api_liberar_reserva(obra_id):
    """
    Libera una reserva activa (devuelve el stock al disponible).
    """
    try:
        from models.inventory import ReservaStock

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        reserva_id = data.get('reserva_id')

        if not reserva_id:
            return jsonify({'ok': False, 'error': 'ID de reserva requerido'}), 400

        reserva = ReservaStock.query.get(reserva_id)
        if not reserva or reserva.obra_id != obra_id:
            return jsonify({'ok': False, 'error': 'Reserva no encontrada'}), 404

        if reserva.estado != 'activa':
            return jsonify({'ok': False, 'error': 'Solo se pueden liberar reservas activas'}), 400

        reserva.estado = 'cancelada'
        db.session.commit()

        return jsonify({
            'ok': True,
            'mensaje': f'Reserva de {reserva.item.nombre} liberada exitosamente'
        })

    except Exception as e:
        current_app.logger.exception(f"Error al liberar reserva: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ========== STOCK EN OBRA (Inventario Local) ==========

@obras_bp.route('/api/obras/<int:obra_id>/stock-obra', methods=['GET'])
@login_required
def api_obtener_stock_obra(obra_id):
    """
    Obtiene el stock físico presente en una obra.
    """
    try:
        from models.inventory import StockObra, ItemInventario

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        stock_items = StockObra.query.filter_by(obra_id=obra_id).all()

        stock_data = []
        for s in stock_items:
            stock_data.append({
                'id': s.id,
                'item_inventario_id': s.item_inventario_id,
                'item_nombre': s.item.nombre,
                'item_codigo': s.item.codigo,
                'unidad': s.item.unidad,
                'cantidad_disponible': float(s.cantidad_disponible or 0),
                'cantidad_consumida': float(s.cantidad_consumida or 0),
                'fecha_ultimo_traslado': s.fecha_ultimo_traslado.isoformat() if s.fecha_ultimo_traslado else None,
                'fecha_ultimo_uso': s.fecha_ultimo_uso.isoformat() if s.fecha_ultimo_uso else None
            })

        return jsonify({
            'ok': True,
            'stock': stock_data,
            'total_items': len(stock_data)
        })

    except Exception as e:
        current_app.logger.exception(f"Error al obtener stock de obra: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/usar-stock', methods=['POST'])
@login_required
def api_usar_stock_obra(obra_id):
    """
    Registra el uso/consumo de material del stock de la obra.
    Descuenta del stock de obra y registra el costo.
    """
    try:
        from models.inventory import StockObra, MovimientoStockObra
        from decimal import Decimal
        from datetime import datetime

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        stock_obra_id = data.get('stock_obra_id')
        cantidad = float(data.get('cantidad', 0))
        observaciones = data.get('observaciones', '')

        if not stock_obra_id or cantidad <= 0:
            return jsonify({'ok': False, 'error': 'Stock y cantidad son requeridos'}), 400

        # Obtener stock de obra
        stock_obra = StockObra.query.get(stock_obra_id)
        if not stock_obra or stock_obra.obra_id != obra_id:
            return jsonify({'ok': False, 'error': 'Stock no encontrado'}), 404

        # Verificar stock disponible
        disponible = float(stock_obra.cantidad_disponible or 0)
        if cantidad > disponible:
            return jsonify({
                'ok': False,
                'error': f'Stock insuficiente. Disponible: {disponible} {stock_obra.item.unidad}'
            }), 400

        # Actualizar stock de obra
        stock_obra.cantidad_disponible = float(
            Decimal(str(disponible)) - Decimal(str(cantidad))
        )
        stock_obra.cantidad_consumida = float(
            Decimal(str(stock_obra.cantidad_consumida or 0)) + Decimal(str(cantidad))
        )
        stock_obra.fecha_ultimo_uso = datetime.utcnow()

        # Registrar movimiento de consumo
        movimiento = MovimientoStockObra(
            stock_obra_id=stock_obra.id,
            tipo='consumo',
            cantidad=cantidad,
            fecha=datetime.utcnow(),
            usuario_id=current_user.id,
            observaciones=observaciones,
            precio_unitario=stock_obra.item.precio_promedio,
            moneda='ARS'
        )
        db.session.add(movimiento)

        db.session.commit()

        return jsonify({
            'ok': True,
            'mensaje': f'Se registró el uso de {cantidad} {stock_obra.item.unidad} de {stock_obra.item.nombre}',
            'stock_restante': float(stock_obra.cantidad_disponible),
            'costo_registrado': float(movimiento.precio_unitario or 0) * cantidad if movimiento.precio_unitario else 0
        })

    except Exception as e:
        current_app.logger.exception(f"Error al registrar uso de stock: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/tareas/<int:tarea_id>/curva-s')
@login_required
def api_curva_s_tarea(tarea_id):
    """API para obtener datos de curva S (PV/EV/AC) de una tarea"""
    from evm_utils import curva_s_tarea

    tarea = TareaEtapa.query.get_or_404(tarea_id)

    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    if 'operario' in _get_roles_usuario(current_user):
        es_miembro = TareaMiembro.query.filter_by(
            tarea_id=tarea_id,
            user_id=current_user.id
        ).first()
        if not es_miembro:
            return jsonify({'ok': False, 'error': 'Sin permisos para esta tarea'}), 403

    desde_str = request.args.get('desde')
    hasta_str = request.args.get('hasta')

    desde = hasta = None
    try:
        if desde_str:
            desde = datetime.strptime(desde_str, '%Y-%m-%d').date()
        if hasta_str:
            hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'ok': False, 'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}), 400

    try:
        curve_data = curva_s_tarea(tarea_id, desde, hasta)

        task_info = {
            'id': tarea.id,
            'nombre': tarea.nombre,
            'fecha_inicio': getattr(tarea, 'fecha_inicio', None).isoformat() if getattr(tarea, 'fecha_inicio', None) else None,
            'fecha_fin': getattr(tarea, 'fecha_fin', None).isoformat() if getattr(tarea, 'fecha_fin', None) else None,
            'presupuesto_mo': float(getattr(tarea, 'presupuesto_mo', 0) or 0),
            'unidad': tarea.unidad,
            'pct_completado': round(getattr(tarea, 'pct_completado', 0) or 0, 2)
        }

        return jsonify({
            'ok': True,
            'tarea': task_info,
            'curva_s': curve_data,
            'fecha_consulta': datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error al calcular curva S: {str(e)}'}), 500


@obras_bp.route('/tareas/eliminar/<int:tarea_id>', methods=['POST'])
@csrf.exempt
@login_required
@limiter.limit("20 per minute")
def eliminar_tarea(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra

    if not can_manage_obra(obra):
        return jsonify({'success': False, 'error': 'Sin permisos para gestionar esta obra'}), 403

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if obra.organizacion_id != org_id:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    try:
        # Limpiar registros relacionados que no tienen cascade automático
        from models.utils import RegistroTiempo
        from models.templates import WorkCertificationItem
        RegistroTiempo.query.filter_by(tarea_id=tarea_id).delete()
        WorkCertificationItem.query.filter_by(tarea_id=tarea_id).delete()
        TareaResponsables.query.filter_by(tarea_id=tarea_id).delete()

        db.session.delete(tarea)
        obra.calcular_progreso_automatico()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error al eliminar tarea %d", tarea_id)
        return jsonify({'success': False, 'error': 'Error al eliminar la tarea. Intente nuevamente.'}), 500


@obras_bp.route('/api/tareas/bulk_delete', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def api_tareas_bulk_delete():
    data = request.get_json()
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'error': 'No se proporcionaron IDs', 'ok': False}), 400

    primera_tarea = TareaEtapa.query.get(ids[0])
    if not primera_tarea:
        return jsonify({'error': 'Tarea no encontrada', 'ok': False}), 404

    obra = primera_tarea.etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'error': 'Sin permisos para gestionar esta obra', 'ok': False}), 403

    data = request.get_json() or {}
    ids = data.get("ids") or []

    if not ids:
        return jsonify({'error': 'IDs requeridos', 'ok': False}), 400

    try:
        task_ids = []
        for task_id in ids:
            try:
                task_ids.append(int(task_id))
            except (ValueError, TypeError):
                continue

        if not task_ids:
            return jsonify({'error': 'IDs inválidos', 'ok': False}), 400

        tareas = TareaEtapa.query.filter(TareaEtapa.id.in_(task_ids)).all()

        if not tareas:
            return jsonify({'error': 'No se encontraron tareas', 'ok': False}), 404

        obras_a_actualizar = set()
        for tarea in tareas:
            try:
                if tarea.etapa and tarea.etapa.obra and tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
                    return jsonify({'error': 'Sin permisos para algunas tareas', 'ok': False}), 403
                if tarea.etapa and tarea.etapa.obra:
                    obras_a_actualizar.add(tarea.etapa.obra)
            except AttributeError as e:
                current_app.logger.warning(f"Error accediendo a relaciones de tarea {tarea.id}: {str(e)}")
                continue

        deleted = 0
        for tarea in tareas:
            try:
                db.session.delete(tarea)
                deleted += 1
            except Exception as e:
                current_app.logger.warning(f"Error eliminando tarea {tarea.id}: {str(e)}")
                continue

        for obra in obras_a_actualizar:
            try:
                obra.calcular_progreso_automatico()
            except Exception as e:
                current_app.logger.warning(f"Error recalculando progreso para obra {obra.id}: {str(e)}")
                continue

        db.session.commit()
        return jsonify({'ok': True, 'deleted': deleted})

    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor', 'ok': False}), 500


@obras_bp.route('/api/etapas/bulk_delete', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def api_etapas_bulk_delete():
    data = request.get_json()
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'error': 'No se proporcionaron IDs', 'ok': False}), 400

    primera_etapa = EtapaObra.query.get(ids[0])
    if not primera_etapa:
        return jsonify({'error': 'Etapa no encontrada', 'ok': False}), 404

    obra = primera_etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'error': 'Sin permisos para gestionar esta obra', 'ok': False}), 403

    data = request.get_json() or {}
    ids = data.get("ids") or []

    if not ids:
        return jsonify({'error': 'IDs requeridos', 'ok': False}), 400

    try:
        etapas = EtapaObra.query.filter(EtapaObra.id.in_(ids)).all()

        obras_a_actualizar = set()
        for etapa in etapas:
            if etapa.obra.organizacion_id != current_user.organizacion_id:
                return jsonify({'error': 'Sin permisos para algunas etapas', 'ok': False}), 403
            obras_a_actualizar.add(etapa.obra)

        deleted = 0
        for etapa in etapas:
            db.session.delete(etapa)
            deleted += 1

        for obra in obras_a_actualizar:
            obra.calcular_progreso_automatico()

        db.session.commit()
        return jsonify({'ok': True, 'deleted': deleted})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e), 'ok': False}), 500


@obras_bp.route('/geocodificar-todas', methods=['POST'])
@login_required
@limiter.limit("2 per hour")
def geocodificar_todas():
    if not is_admin():
        flash('Solo los administradores pueden ejecutar esta acción.', 'danger')
        return redirect(url_for('obras.lista'))

    try:
        from geocoding import geocodificar_obras_existentes
        exitosas, fallidas = geocodificar_obras_existentes()

        if exitosas > 0:
            flash(f'Geocodificación completada: {exitosas} obras actualizadas, {fallidas} fallaron.', 'success')
        else:
            flash('No se pudieron geocodificar las obras. Verifica las direcciones.', 'warning')

    except Exception as e:
        flash(f'Error en la geocodificación: {str(e)}', 'danger')

    return redirect(url_for('obras.lista'))


@obras_bp.route('/eliminar/<int:obra_id>', methods=['POST'])
@csrf.exempt
@login_required
@limiter.limit("10 per minute")
def eliminar_obra(obra_id):
    roles = _get_roles_usuario(current_user)
    if not (current_user.is_super_admin or 'administrador' in roles or 'admin' in roles):
        flash('No tienes permisos para eliminar obras.', 'danger')
        return redirect(url_for('obras.lista'))

    obra = Obra.query.filter_by(id=obra_id, organizacion_id=current_user.organizacion_id).first_or_404()
    nombre_obra = obra.nombre

    try:
        # Desasociar presupuestos de la obra pero mantenerlos ocultos
        # NO revertir confirmado_como_obra para que no vuelvan a aparecer en el módulo de presupuestos
        from models.budgets import Presupuesto
        presupuestos_asociados = Presupuesto.query.filter_by(obra_id=obra_id).all()
        for presupuesto in presupuestos_asociados:
            # Mantener confirmado_como_obra = True para que siga oculto
            # Solo desasociar la obra
            presupuesto.obra_id = None
            # Mantener el estado como 'confirmado' para que no aparezca en la lista de presupuestos

        # Eliminar todas las relaciones con la obra en orden inverso de dependencias

        # 1. Primero, desasociar items_presupuesto que referencian a las etapas de esta obra
        from models.budgets import ItemPresupuesto
        for etapa in obra.etapas:
            # Poner etapa_id = NULL en items que referencian esta etapa
            ItemPresupuesto.query.filter_by(etapa_id=etapa.id).update({ItemPresupuesto.etapa_id: None})

        # Helper: verificar si una tabla existe antes de intentar borrar
        def _tabla_existe(nombre_tabla):
            r = db.session.execute(db.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name = :tbl)"
            ), {"tbl": nombre_tabla})
            return r.scalar()

        # 2. Eliminar dependencias de tareas y luego las tareas de cada etapa
        for etapa in obra.etapas:
            tareas_etapa = TareaEtapa.query.filter_by(etapa_id=etapa.id).all()
            for tarea in tareas_etapa:
                for sub_table in ['tarea_miembros', 'tarea_avances']:
                    if _tabla_existe(sub_table):
                        db.session.execute(db.text(f"DELETE FROM {sub_table} WHERE tarea_id = :tid"), {"tid": tarea.id})
            TareaEtapa.query.filter_by(etapa_id=etapa.id).delete()

        # 3. Eliminar etapas
        EtapaObra.query.filter_by(obra_id=obra_id).delete()

        # 4. Eliminar asignaciones
        AsignacionObra.query.filter_by(obra_id=obra_id).delete()

        # 5. Eliminar otras relaciones — solo si la tabla existe en la BD
        # Formato: (tabla, condicion_sql, [tablas_requeridas_en_subquery])
        # IMPORTANTE: tablas hijas ANTES que sus padres
        _optional_deletes = [
            # --- Hijos de ordenes_compra (OC) ---
            ("historial_precios_proveedor",
             "orden_compra_id IN (SELECT id FROM ordenes_compra WHERE obra_id = :obra_id)",
             ["ordenes_compra"]),
            ("movimientos_caja",
             "orden_compra_id IN (SELECT id FROM ordenes_compra WHERE obra_id = :obra_id)",
             ["ordenes_compra"]),
            ("recepcion_oc_items",
             "recepcion_id IN (SELECT r.id FROM recepciones_oc r JOIN ordenes_compra oc ON r.orden_compra_id = oc.id WHERE oc.obra_id = :obra_id)",
             ["recepciones_oc", "ordenes_compra"]),
            ("recepciones_oc",
             "orden_compra_id IN (SELECT id FROM ordenes_compra WHERE obra_id = :obra_id)",
             ["ordenes_compra"]),
            ("orden_compra_items",
             "orden_compra_id IN (SELECT id FROM ordenes_compra WHERE obra_id = :obra_id)",
             ["ordenes_compra"]),
            ("ordenes_compra", "obra_id = :obra_id"),
            # --- Hijos de requerimientos_compra (RC) ---
            ("cotizacion_proveedor_items",
             "cotizacion_id IN (SELECT c.id FROM cotizaciones_proveedor c JOIN requerimientos_compra rc ON c.requerimiento_id = rc.id WHERE rc.obra_id = :obra_id)",
             ["cotizaciones_proveedor", "requerimientos_compra"]),
            ("cotizaciones_proveedor",
             "requerimiento_id IN (SELECT id FROM requerimientos_compra WHERE obra_id = :obra_id)",
             ["requerimientos_compra"]),
            ("requerimiento_compra_items",
             "requerimiento_id IN (SELECT id FROM requerimientos_compra WHERE obra_id = :obra_id)",
             ["requerimientos_compra"]),
            ("requerimientos_compra", "obra_id = :obra_id"),
            # --- Hijos de checklists_seguridad ---
            ("items_checklist", "checklist_id IN (SELECT id FROM checklists_seguridad WHERE obra_id = :obra_id)", ["checklists_seguridad"]),
            # --- Hijos de documentos_obra ---
            ("versiones_documento", "documento_id IN (SELECT id FROM documentos_obra WHERE obra_id = :obra_id)", ["documentos_obra"]),
            ("permisos_documento", "documento_id IN (SELECT id FROM documentos_obra WHERE obra_id = :obra_id)", ["documentos_obra"]),
            # --- Hijos de work_certifications ---
            ("work_certification_items", "certificacion_id IN (SELECT id FROM work_certifications WHERE obra_id = :obra_id)", ["work_certifications"]),
            # --- Tablas padre con obra_id directo ---
            ("fichadas", "obra_id = :obra_id"),
            ("work_payments", "obra_id = :obra_id"),
            ("work_certifications", "obra_id = :obra_id"),
            ("certificaciones_avance", "obra_id = :obra_id"),
            ("documentos_obra", "obra_id = :obra_id"),
            ("incidentes_seguridad", "obra_id = :obra_id"),
            ("checklists_seguridad", "obra_id = :obra_id"),
            ("auditorias_seguridad", "obra_id = :obra_id"),
            ("configuraciones_inteligentes", "obra_id = :obra_id"),
            ("obra_miembros", "obra_id = :obra_id"),
            ("uso_inventario", "obra_id = :obra_id"),
            ("events", "project_id = :obra_id"),
            ("equipment_assignment", "project_id = :obra_id"),
            ("equipment_usage", "project_id = :obra_id"),
            ("stock_movement", "project_id = :obra_id"),
            ("stock_reservation", "project_id = :obra_id"),
            # --- stock_obra y sus hijos ---
            ("movimientos_stock_obra", "stock_obra_id IN (SELECT id FROM stock_obra WHERE obra_id = :obra_id)", ["stock_obra"]),
            ("stock_obra", "obra_id = :obra_id"),
        ]
        for entry in _optional_deletes:
            table, condition = entry[0], entry[1]
            deps = entry[2] if len(entry) > 2 else []
            if _tabla_existe(table) and all(_tabla_existe(d) for d in deps):
                db.session.execute(db.text(f"DELETE FROM {table} WHERE {condition}"), {"obra_id": obra_id})

        # 6. Finalmente eliminar la obra
        db.session.delete(obra)
        db.session.commit()

        log_data_deletion('Obra', obra_id, current_user.email)
        current_app.logger.warning(f'Obra eliminada: {obra_id} - {nombre_obra} por usuario {current_user.email}')

        flash(f'La obra "{nombre_obra}" ha sido eliminada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error al eliminar obra {obra_id}: {str(e)}', exc_info=True)
        flash(f'Error al eliminar la obra: {str(e)}', 'danger')

    return redirect(url_for('obras.lista'))


@obras_bp.route('/super-admin/reiniciar-sistema', methods=['POST'])
@login_required
@limiter.limit("1 per minute")
def reiniciar_sistema():
    if not current_user.is_super_admin:
        flash('No tienes permisos para reiniciar el sistema.', 'danger')
        return redirect(url_for('obras.lista'))

    try:
        AsignacionObra.query.delete()
        TareaEtapa.query.delete()
        EtapaObra.query.delete()
        Obra.query.delete()

        db.session.commit()
        flash('Sistema reiniciado exitosamente. Todas las obras han sido eliminadas.', 'success')
    except Exception:
        db.session.rollback()
        flash('Error al reiniciar el sistema. Inténtalo nuevamente.', 'danger')

    return redirect(url_for('obras.lista'))


# ==== CERTIFICACIONES ====

@obras_bp.route('/<int:id>/certificar_avance', methods=['POST'])
@login_required
def certificar_avance(id):
    """Compat wrapper: crea certificación usando el flujo 2.0."""
    obra = Obra.query.get_or_404(id)

    membership = get_current_membership()
    if not membership or membership.org_id != obra.organizacion_id or membership.role not in ('admin', 'project_manager'):
        flash('No tienes permisos para certificar avances.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    porcentaje_avance = request.form.get('porcentaje_avance') or request.form.get('porcentaje')
    if not porcentaje_avance:
        flash('El porcentaje de avance es obligatorio.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    periodo_desde = _parse_date(request.form.get('periodo_desde'))
    periodo_hasta = _parse_date(request.form.get('periodo_hasta'))
    notas = request.form.get('notas')

    try:
        porcentaje = Decimal(str(porcentaje_avance).replace(',', '.'))
        cert = create_certification(
            obra,
            current_user,
            porcentaje,
            periodo=(periodo_desde, periodo_hasta),
            notas=notas,
            aprobar=True,
        )
        db.session.commit()
        flash(
            f'Se registró la certificación #{cert.id} por {porcentaje}% correctamente.',
            'success',
        )
    except Exception as exc:
        db.session.rollback()
        flash(f'Error al registrar certificación: {exc}', 'danger')

    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/<int:id>/actualizar_progreso', methods=['POST'])
@login_required
def actualizar_progreso_automatico(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para actualizar el progreso.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    obra = Obra.query.get_or_404(id)

    try:
        progreso_anterior = obra.progreso
        tareas_completadas = 0

        # 1. Recalcular porcentaje de todas las tareas de esta obra
        for etapa in obra.etapas:
            for tarea in etapa.tareas:
                recalc_tarea_pct(tarea.id)
                if tarea.estado == 'completada':
                    tareas_completadas += 1

        # 2. Recalcular progreso general de la obra
        nuevo_progreso = obra.calcular_progreso_automatico()

        # 3. Calcular y actualizar costo real
        from sqlalchemy import func

        # Costo de materiales
        costo_materiales = db.session.query(
            db.func.coalesce(
                db.func.sum(
                    UsoInventario.cantidad_usada *
                    db.func.coalesce(UsoInventario.precio_unitario_al_uso, ItemInventario.precio_promedio)
                ), 0
            )
        ).join(ItemInventario, UsoInventario.item_id == ItemInventario.id
        ).filter(UsoInventario.obra_id == obra.id).scalar() or Decimal('0')

        # Costo MO = suma de liquidaciones (lo realmente liquidado)
        from models import LiquidacionMO
        costo_mano_obra = db.session.query(
            db.func.coalesce(db.func.sum(LiquidacionMO.monto_total), 0)
        ).filter(LiquidacionMO.obra_id == obra.id).scalar() or Decimal('0')

        obra.costo_real = Decimal(str(costo_materiales)) + Decimal(str(costo_mano_obra))

        db.session.commit()

        flash(
            f'Progreso actualizado de {progreso_anterior}% a {nuevo_progreso}%. '
            f'{tareas_completadas} tareas completadas. '
            f'Costo real: ${float(obra.costo_real):,.2f}',
            'success'
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error actualizando progreso obra {id}")
        flash(f'Error al actualizar progreso: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/tarea/<int:id>/actualizar_estado', methods=['POST'])
@login_required
def actualizar_estado_tarea(id):
    tarea = TareaEtapa.query.get_or_404(id)
    obra = tarea.etapa.obra

    is_admin_like = is_admin() or ('tecnico' in _get_roles_usuario(current_user))
    is_responsible = tarea.responsable_id == current_user.id

    asignado = db.session.query(TareaResponsables.id)\
        .filter_by(tarea_id=tarea.id, user_id=current_user.id).first()

    if not (is_admin_like or is_responsible or asignado):
        flash('No tienes permisos para actualizar esta tarea.', 'danger')
        return redirect(url_for('obras.detalle', id=obra.id))

    nuevo_estado = request.form.get('estado')
    porcentaje_avance = request.form.get('porcentaje_avance')

    if nuevo_estado not in ['pendiente', 'en_curso', 'completada', 'cancelada']:
        flash('Estado no válido.', 'danger')
        return redirect(url_for('obras.detalle', id=obra.id))

    try:
        tarea.estado = nuevo_estado

        if porcentaje_avance:
            tarea.porcentaje_avance = Decimal(str(porcentaje_avance).replace(',', '.'))

        if nuevo_estado == 'completada':
            tarea.porcentaje_avance = Decimal('100')
            tarea.fecha_fin_real = date.today()
        elif nuevo_estado == 'en_curso' and not tarea.fecha_inicio_real:
            tarea.fecha_inicio_real = date.today()

        # Sincronizar estado de etapa según tareas
        etapa = tarea.etapa
        if etapa:
            todas_tareas = etapa.tareas.all() if hasattr(etapa.tareas, 'all') else (etapa.tareas or [])
            if todas_tareas:
                todas_completadas = all(t.estado in ('completada', 'cancelada') for t in todas_tareas)
                alguna_en_curso = any(t.estado in ('en_curso', 'completada') for t in todas_tareas)
                if todas_completadas and etapa.estado != 'finalizada':
                    etapa.estado = 'finalizada'
                    etapa.progreso = 100
                    if not etapa.fecha_fin_real:
                        etapa.fecha_fin_real = date.today()
                elif alguna_en_curso and etapa.estado == 'pendiente':
                    etapa.estado = 'en_curso'
                    if not etapa.fecha_inicio_real:
                        etapa.fecha_inicio_real = date.today()

        obra.calcular_progreso_automatico()
        sincronizar_estado_obra(obra)

        db.session.commit()
        flash('Estado de tarea actualizado exitosamente.', 'success')

    except ValueError:
        flash('Porcentaje de avance no válido.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar tarea: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=obra.id))


@obras_bp.route('/api/tareas/<int:tarea_id>/editar-datos', methods=['POST'])
@login_required
def api_editar_datos_tarea(tarea_id):
    """Editar horas, cantidad, unidad, rendimiento y fechas de una tarea."""
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra

    if not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permisos"), 403

    try:
        data = request.get_json() or request.form

        # Horas estimadas
        if 'horas_estimadas' in data and data['horas_estimadas'] is not None:
            tarea.horas_estimadas = float(str(data['horas_estimadas']).replace(',', '.'))

        # Cantidad planificada
        if 'cantidad_planificada' in data and data['cantidad_planificada'] is not None:
            tarea.cantidad_planificada = float(str(data['cantidad_planificada']).replace(',', '.'))
            tarea.objetivo = tarea.cantidad_planificada

        # Unidad
        if 'unidad' in data and data['unidad']:
            tarea.unidad = data['unidad'].strip()

        # Rendimiento
        if 'rendimiento' in data and data['rendimiento'] is not None:
            tarea.rendimiento = float(str(data['rendimiento']).replace(',', '.'))
        elif tarea.horas_estimadas and float(tarea.horas_estimadas) > 0 and tarea.cantidad_planificada:
            # Auto-calcular rendimiento
            tarea.rendimiento = round(float(tarea.cantidad_planificada) / float(tarea.horas_estimadas), 2)

        # Fechas
        if 'fecha_inicio' in data and data['fecha_inicio']:
            from datetime import datetime as dt
            f = dt.strptime(data['fecha_inicio'], '%Y-%m-%d').date()
            tarea.fecha_inicio_plan = f
            tarea.fecha_inicio_estimada = f
        if 'fecha_fin' in data and data['fecha_fin']:
            from datetime import datetime as dt
            f = dt.strptime(data['fecha_fin'], '%Y-%m-%d').date()
            tarea.fecha_fin_plan = f
            tarea.fecha_fin_estimada = f

        db.session.commit()

        return jsonify(
            ok=True,
            tarea={
                'id': tarea.id,
                'horas_estimadas': float(tarea.horas_estimadas or 0),
                'cantidad_planificada': float(tarea.cantidad_planificada or 0),
                'unidad': tarea.unidad,
                'rendimiento': float(tarea.rendimiento or 0),
            }
        )

    except (ValueError, TypeError) as e:
        return jsonify(ok=False, error=f"Valor inválido: {str(e)}"), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error al editar datos de tarea")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route('/tareas/<int:tarea_id>/asignar', methods=['POST'])
@login_required
def tarea_asignar(tarea_id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        return jsonify(ok=False, error="Sin permiso"), 403

    tarea = TareaEtapa.query.get_or_404(tarea_id)

    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403

    data = request.get_json(force=True) or {}
    user_ids = list({int(x) for x in data.get("user_ids", [])})

    try:
        TareaResponsables.query.filter_by(tarea_id=tarea.id).delete()

        for uid in user_ids:
            usuario = Usuario.query.filter_by(id=uid, organizacion_id=current_user.organizacion_id).first()
            if usuario:
                asignacion = TareaResponsables(tarea_id=tarea.id, user_id=uid)
                db.session.add(asignacion)

        db.session.commit()
        return jsonify(ok=True, count=len(user_ids))

    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:id>/certificaciones', methods=['GET', 'POST'])
@login_required
def historial_certificaciones(id):
    """Historial de certificaciones de una obra"""
    return ProjectSharedService.historial_certificaciones(
        id,
        'obras',
        create_certification,
        certification_totals,
        build_pending_entries,
        approved_entries,
        pending_percentage,
        resolve_budget_context,
        register_payment
    )


# ============================================================
# LIQUIDACIÓN MANO DE OBRA (CERTIFICACIÓN UNIFICADA)
# ============================================================

@obras_bp.route('/<int:obra_id>/certificacion-unificada/preview')
@login_required
def certificacion_unificada_preview(obra_id):
    """API: preview unificado etapas + operarios para un período."""
    from services.liquidacion_mo import generar_preview_unificado
    desde = request.args.get('desde')
    hasta = request.args.get('hasta')
    if not desde or not hasta:
        return jsonify(ok=False, error='Debe indicar período desde/hasta'), 400
    try:
        desde_date = date.fromisoformat(desde)
        hasta_date = date.fromisoformat(hasta)
    except ValueError:
        return jsonify(ok=False, error='Formato de fecha inválido (YYYY-MM-DD)'), 400

    try:
        data = generar_preview_unificado(obra_id, desde_date, hasta_date)
        return jsonify(ok=True, **data)
    except Exception as e:
        current_app.logger.exception("Error en preview unificado")
        return jsonify(ok=True, etapas=[], operarios_sin_etapa=[],
                       tarifa_default=0, ya_certificado_ars=0,
                       presupuesto_total=0, total_certificable=0)


@obras_bp.route('/<int:obra_id>/liquidacion-mo/preview')
@login_required
def liquidacion_mo_preview(obra_id):
    """API: preview de liquidación para un período (legacy)."""
    from services.liquidacion_mo import generar_preview_liquidacion
    desde = request.args.get('desde')
    hasta = request.args.get('hasta')
    if not desde or not hasta:
        return jsonify(ok=False, error='Debe indicar período desde/hasta'), 400
    try:
        desde_date = date.fromisoformat(desde)
        hasta_date = date.fromisoformat(hasta)
    except ValueError:
        return jsonify(ok=False, error='Formato de fecha inválido (YYYY-MM-DD)'), 400

    items = generar_preview_liquidacion(obra_id, desde_date, hasta_date)
    return jsonify(ok=True, items=items)


@obras_bp.route('/<int:obra_id>/liquidacion-mo', methods=['POST'])
@csrf.exempt
@login_required
def crear_liquidacion_mo(obra_id):
    """Crear una liquidación de mano de obra."""
    from services.liquidacion_mo import crear_liquidacion
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'administrador', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos para crear liquidaciones'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos inválidos'), 400

    try:
        desde = date.fromisoformat(data['periodo_desde'])
        hasta = date.fromisoformat(data['periodo_hasta'])
        items_data = data.get('items', [])
        if not items_data:
            return jsonify(ok=False, error='Debe incluir al menos un operario'), 400

        liq = crear_liquidacion(obra_id, desde, hasta, items_data, notas=data.get('notas'))
        return jsonify(ok=True, liquidacion_id=liq.id, monto_total=float(liq.monto_total))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error creando liquidación MO")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:obra_id>/liquidacion-mo/confirmar-y-pagar', methods=['POST'])
@csrf.exempt
@login_required
def confirmar_y_pagar_liquidacion(obra_id):
    """Crea liquidación + marca como pagado + actualiza costo_real en un solo paso."""
    from services.liquidacion_mo import crear_liquidacion, registrar_pago_item
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'administrador', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos inválidos'), 400

    try:
        desde = date.fromisoformat(data['periodo_desde'])
        hasta = date.fromisoformat(data['periodo_hasta'])
        items_data = data.get('items', [])
        metodo_pago = data.get('metodo_pago', 'transferencia')
        if not items_data:
            return jsonify(ok=False, error='Debe incluir al menos un operario'), 400

        # 1. Crear liquidación (sin commit aún)
        liq = crear_liquidacion(obra_id, desde, hasta, items_data, notas=data.get('notas'), commit=False)
        db.session.flush()

        # 2. Marcar cada item como pagado y actualizar costo_real
        for item in liq.items.all():
            item.estado = 'pagado'
            item.metodo_pago = metodo_pago
            item.fecha_pago = date.today()
            item.pagado_por_id = current_user.id
            item.pagado_at = datetime.utcnow()

        liq.estado = 'pagado'

        # 3. Recalcular costo_real de la obra
        from services.liquidacion_mo import _decimal
        from models.templates import LiquidacionMOItem, LiquidacionMO as LiqMO
        obra = Obra.query.get(obra_id)

        costo_mo_pagado = _decimal(
            db.session.query(db.func.coalesce(db.func.sum(LiquidacionMOItem.monto), 0))
            .join(LiqMO)
            .filter(LiqMO.obra_id == obra_id, LiquidacionMOItem.estado == 'pagado')
            .scalar()
        ) + _decimal(liq.monto_total)  # sumar la nueva liquidación

        from models import UsoInventario
        costo_materiales = _decimal(
            db.session.query(
                db.func.coalesce(db.func.sum(
                    UsoInventario.cantidad_usada * db.func.coalesce(UsoInventario.precio_unitario_al_uso, 0)
                ), 0)
            ).filter(UsoInventario.obra_id == obra_id).scalar()
        )
        obra.costo_real = float(costo_materiales + costo_mo_pagado)

        db.session.commit()
        return jsonify(
            ok=True,
            liquidacion_id=liq.id,
            monto_total=float(liq.monto_total),
            costo_real_obra=obra.costo_real,
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error en confirmar y pagar liquidación MO")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/liquidacion-mo/item/<int:item_id>/recibo-pdf')
@login_required
def recibo_liquidacion_pdf(item_id):
    """Genera PDF de recibo de pago de un item de liquidación."""
    from models.templates import LiquidacionMOItem
    try:
        from weasyprint import HTML
    except ImportError:
        flash('La exportacion a PDF no esta disponible.', 'warning')
        return redirect(request.referrer or url_for('index'))

    item = LiquidacionMOItem.query.get_or_404(item_id)
    liq = item.liquidacion
    obra = liq.obra
    org = obra.organizacion if hasattr(obra, 'organizacion') else None

    html_content = render_template('obras/recibo_liquidacion_pdf.html',
        item=item,
        liquidacion=liq,
        obra=obra,
        organizacion=org,
        fecha_generacion=datetime.now().strftime('%d/%m/%Y %H:%M'),
    )

    import io
    pdf_buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)

    nombre_op = item.operario.nombre_completo if item.operario else 'operario'
    nombre_safe = nombre_op.replace(' ', '_')[:30]
    filename = f"recibo_{nombre_safe}_{liq.periodo_desde.strftime('%Y%m%d')}.pdf"

    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)


@obras_bp.route('/liquidacion-mo/<int:liq_id>/recibo-pdf')
@login_required
def recibo_liquidacion_completa_pdf(liq_id):
    """Genera PDF de recibo de toda una liquidación (todos los operarios)."""
    from models.templates import LiquidacionMO as LiqMO
    try:
        from weasyprint import HTML
    except ImportError:
        flash('La exportacion a PDF no esta disponible.', 'warning')
        return redirect(request.referrer or url_for('index'))

    liq = LiqMO.query.get_or_404(liq_id)
    obra = liq.obra
    org = obra.organizacion if hasattr(obra, 'organizacion') else None
    items = liq.items.all()

    html_content = render_template('obras/recibo_liquidacion_pdf.html',
        item=None,
        items=items,
        liquidacion=liq,
        obra=obra,
        organizacion=org,
        fecha_generacion=datetime.now().strftime('%d/%m/%Y %H:%M'),
    )

    import io
    pdf_buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)

    filename = f"liquidacion_{liq.periodo_desde.strftime('%Y%m%d')}_{liq.periodo_hasta.strftime('%Y%m%d')}.pdf"
    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)


@obras_bp.route('/liquidacion-mo/item/<int:item_id>/pagar', methods=['POST'])
@csrf.exempt
@login_required
def pagar_liquidacion_mo_item(item_id):
    """Registrar pago de un item de liquidación."""
    from services.liquidacion_mo import registrar_pago_item
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'administrador', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True) or {}
    try:
        metodo = data.get('metodo_pago', 'transferencia')
        fecha = date.fromisoformat(data['fecha_pago']) if data.get('fecha_pago') else date.today()
        comprobante = data.get('comprobante_url')
        notas = data.get('notas')

        item = registrar_pago_item(item_id, metodo, fecha, comprobante, notas)
        return jsonify(ok=True, estado=item.estado, liquidacion_estado=item.liquidacion.estado)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error registrando pago liquidación MO")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:obra_id>/liquidacion-mo/historial')
@login_required
def liquidacion_mo_historial(obra_id):
    """API: obtener historial de liquidaciones de una obra."""
    try:
        from services.liquidacion_mo import obtener_liquidaciones_obra
        liquidaciones = obtener_liquidaciones_obra(obra_id)
        result = []
        for liq in liquidaciones:
            items = []
            for item in liq.items.all():
                items.append({
                    'id': item.id,
                    'operario_id': item.operario_id,
                    'operario_nombre': item.operario.nombre_completo if item.operario else 'N/A',
                    'horas_avance': float(item.horas_avance or 0),
                    'horas_fichadas': float(item.horas_fichadas or 0),
                    'horas_liquidadas': float(item.horas_liquidadas or 0),
                    'tarifa_hora': float(item.tarifa_hora or 0),
                    'monto': float(item.monto or 0),
                    'estado': item.estado,
                    'metodo_pago': item.metodo_pago,
                    'fecha_pago': item.fecha_pago.isoformat() if item.fecha_pago else None,
                    'comprobante_url': item.comprobante_url,
                })
            result.append({
                'id': liq.id,
                'periodo_desde': liq.periodo_desde.isoformat(),
                'periodo_hasta': liq.periodo_hasta.isoformat(),
                'estado': liq.estado,
                'monto_total': float(liq.monto_total or 0),
                'notas': liq.notas,
                'created_at': liq.created_at.isoformat() if liq.created_at else None,
                'created_by': liq.created_by.nombre_completo if liq.created_by else 'N/A',
                'items': items,
            })
        return jsonify(ok=True, liquidaciones=result)
    except Exception as e:
        # Si la tabla no existe, crearla automáticamente
        if 'liquidaciones_mo' in str(e).lower() or 'relation' in str(e).lower():
            try:
                db.session.rollback()
                db.create_all()
                db.session.commit()
                current_app.logger.info("Tablas de liquidación MO creadas automáticamente")
                return jsonify(ok=True, liquidaciones=[])
            except Exception:
                pass
        db.session.rollback()
        current_app.logger.exception("Error en historial liquidación MO")
        return jsonify(ok=True, liquidaciones=[])


@obras_bp.route('/certificacion/<int:id>/desactivar', methods=['POST'])
@login_required
def desactivar_certificacion(id):
    roles = _get_roles_usuario(current_user)
    if 'administrador' not in roles and 'admin' not in roles:
        flash('Solo los administradores pueden desactivar certificaciones.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    certificacion = CertificacionAvance.query.get_or_404(id)
    obra = certificacion.obra

    try:
        certificacion.activa = False
        obra.costo_real -= certificacion.costo_certificado
        obra.calcular_progreso_automatico()
        db.session.commit()
        flash('Certificación desactivada exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al desactivar certificación: {str(e)}', 'danger')

    return redirect(url_for('obras.historial_certificaciones', id=obra.id))


@obras_bp.route('/certificaciones/<int:cert_id>/pagos', methods=['POST'])
@login_required
def registrar_pago_certificacion(cert_id):
    certificacion = WorkCertification.query.get_or_404(cert_id)
    obra = certificacion.obra

    membership = get_current_membership()
    if not membership or membership.org_id != obra.organizacion_id or membership.role not in ('admin', 'project_manager'):
        error_msg = 'No tienes permisos para registrar pagos.'
        if request.is_json:
            return jsonify(ok=False, error=error_msg), 403
        flash(error_msg, 'danger')
        return redirect(url_for('obras.historial_certificaciones', id=obra.id))

    data = request.get_json(silent=True) or request.form
    monto_raw = data.get('monto')
    metodo = data.get('metodo') or data.get('metodo_pago')
    if not monto_raw or not metodo:
        msg = 'Debe indicar monto y método de pago.'
        if request.is_json:
            return jsonify(ok=False, error=msg), 400
        flash(msg, 'danger')
        return redirect(url_for('obras.historial_certificaciones', id=obra.id))

    moneda = (data.get('moneda') or 'ARS').upper()
    notas = data.get('notas')
    tc_usd = data.get('tc_usd') or data.get('tc_usd_pago')
    fecha_pago = _parse_date(data.get('fecha_pago'))
    operario_id = data.get('operario_id') or data.get('usuario_id')
    try:
        operario_id = int(operario_id) if operario_id else None
    except (TypeError, ValueError):
        operario_id = None

    try:
        monto = Decimal(str(monto_raw).replace(',', '.'))
        payment = register_payment(
            certificacion,
            obra,
            current_user,
            monto=monto,
            metodo=metodo,
            moneda=moneda,
            fecha=fecha_pago,
            tc_usd=Decimal(str(tc_usd).replace(',', '.')) if tc_usd else None,
            notas=notas,
            operario_id=operario_id,
            comprobante_url=data.get('comprobante_url'),
        )
        db.session.commit()
        payload = {'ok': True, 'pago_id': payment.id, 'certificacion_id': certificacion.id}
        if request.is_json:
            return jsonify(payload)
        flash('Pago registrado correctamente.', 'success')
    except Exception as exc:
        db.session.rollback()
        if request.is_json:
            return jsonify(ok=False, error=str(exc)), 400
        flash(f'Error al registrar el pago: {exc}', 'danger')

    return redirect(url_for('obras.historial_certificaciones', id=obra.id))


@obras_bp.route('/<int:obra_id>/etapas/<int:etapa_id>/eliminar', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def eliminar_etapa(obra_id, etapa_id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para eliminar etapas.', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    obra = Obra.query.filter_by(id=obra_id, organizacion_id=current_user.organizacion_id).first_or_404()
    etapa = EtapaObra.query.filter_by(id=etapa_id, obra_id=obra_id).first_or_404()

    try:
        nombre_etapa = etapa.nombre
        db.session.delete(etapa)
        obra.calcular_progreso_automatico()
        db.session.commit()
        flash(f'Etapa "{nombre_etapa}" eliminada exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar etapa: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=obra_id))


@obras_bp.route('/etapa/<int:etapa_id>/cambiar_estado', methods=['POST'])
@login_required
def cambiar_estado_etapa(etapa_id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para cambiar el estado de etapas.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    etapa = EtapaObra.query.get_or_404(etapa_id)
    nuevo_estado = request.form.get('estado')

    estados_validos = ['pendiente', 'en_curso', 'pausada', 'finalizada']
    if nuevo_estado not in estados_validos:
        flash('Estado no válido.', 'danger')
        return redirect(url_for('obras.detalle', id=etapa.obra_id))

    try:
        estado_anterior = etapa.estado
        etapa.estado = nuevo_estado

        if nuevo_estado == 'finalizada':
            for tarea in etapa.tareas.filter_by(estado='pendiente'):
                tarea.estado = 'completada'
            # Registrar fecha de finalización real
            if not etapa.fecha_fin_real:
                etapa.fecha_fin_real = date.today()

        etapa.obra.calcular_progreso_automatico()
        sincronizar_estado_obra(etapa.obra)

        db.session.commit()

        # Propagar fechas a etapas sucesoras (dependencias + niveles)
        if nuevo_estado == 'finalizada':
            result = propagar_fechas_etapas(etapa.obra_id)
            if result['shifted_count'] > 0:
                db.session.commit()
                nombres = ', '.join(d['etapa'] for d in result['details'][:3])
                extra = f' y {result["shifted_count"] - 3} más' if result['shifted_count'] > 3 else ''
                flash(f'Se actualizaron fechas de: {nombres}{extra}', 'info')

        flash(f'Estado de etapa "{etapa.nombre}" cambiado de "{estado_anterior}" a "{nuevo_estado}".', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar estado: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=etapa.obra_id))


@obras_bp.route('/<int:id>/propagar_fechas', methods=['POST'])
@login_required
def propagar_fechas(id):
    """Recalcular fechas de etapas encadenadas manualmente."""
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para ajustar fechas.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    obra = Obra.query.get_or_404(id)
    try:
        result = propagar_fechas_etapas(obra.id)
        if result['shifted_count'] > 0:
            db.session.commit()
            flash(f'Se ajustaron las fechas de {result["shifted_count"]} etapa(s).', 'success')
        else:
            flash('No fue necesario ajustar fechas.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al propagar fechas: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=id))


# ===== ENDPOINTS PARA DEPENDENCIAS Y GANTT =====

@obras_bp.route('/etapas/<int:etapa_id>/editar_fechas', methods=['POST'])
@csrf.exempt
@login_required
def editar_fechas_etapa(etapa_id):
    """Editar fechas de una etapa manualmente (admin/técnico)."""
    etapa = EtapaObra.query.get_or_404(etapa_id)
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        return jsonify({'error': 'Sin permisos'}), 403

    data = request.get_json(silent=True) or {}

    try:
        # Capturar las fechas que el usuario quiere (valores puros)
        fecha_inicio_usuario = date.fromisoformat(data['fecha_inicio']) if data.get('fecha_inicio') else None
        fecha_fin_usuario = date.fromisoformat(data['fecha_fin']) if data.get('fecha_fin') else None

        if 'nivel' in data:
            etapa.nivel_encadenamiento = int(data['nivel']) if data['nivel'] is not None else None

        if data.get('forzar_inicio') and etapa.estado == 'pendiente':
            etapa.estado = 'en_curso'
            if not etapa.fecha_inicio_real:
                etapa.fecha_inicio_real = date.today()

        # Aplicar fechas
        if fecha_inicio_usuario:
            etapa.fecha_inicio_estimada = fecha_inicio_usuario
        if fecha_fin_usuario:
            etapa.fecha_fin_estimada = fecha_fin_usuario

        # Respetar la elección del usuario sobre bloquear fechas
        bloquear = data.get('bloquear_fechas')
        if bloquear is not None:
            etapa.fechas_manuales = bool(bloquear)

        # Temporalmente bloquear para que la propagación no pise las fechas
        etapa.fechas_manuales = True

        db.session.commit()

        # Propagar fechas a etapas SUCESORAS solamente
        from services.dependency_service import generar_dependencias_desde_niveles
        deps_creadas = generar_dependencias_desde_niveles(etapa.obra_id)
        if deps_creadas:
            db.session.commit()

        result = propagar_fechas_etapas(etapa.obra_id)
        propagadas = result['shifted_count']
        if propagadas > 0:
            db.session.commit()

        # SQL DIRECTO: forzar las fechas del usuario en BD, sin pasar por SQLAlchemy
        # Esto garantiza que ningún proceso intermedio pueda pisar los valores
        # Ahora restaurar el valor real de fechas_manuales que el usuario eligió
        usuario_quiere_bloquear = bool(bloquear) if bloquear is not None else True
        if fecha_inicio_usuario or fecha_fin_usuario:
            sets = []
            params = {"eid": etapa_id}
            if fecha_inicio_usuario:
                sets.append("fecha_inicio_estimada = :fi")
                params["fi"] = fecha_inicio_usuario
            if fecha_fin_usuario:
                sets.append("fecha_fin_estimada = :ff")
                params["ff"] = fecha_fin_usuario
            sets.append("fechas_manuales = :fm")
            params["fm"] = usuario_quiere_bloquear
            db.session.execute(
                db.text(f"UPDATE etapas_obra SET {', '.join(sets)} WHERE id = :eid"),
                params
            )
            db.session.commit()
            # Refrescar el objeto SA para que refleje los valores reales de BD
            db.session.expire(etapa)

        # Redistribuir fechas de tareas dentro de esta etapa
        distribuir_datos_etapa_a_tareas(etapa_id, forzar=True)
        db.session.commit()

        # Leer valores finales directo de BD para la respuesta
        row = db.session.execute(
            db.text("SELECT fecha_inicio_estimada, fecha_fin_estimada, estado, fechas_manuales FROM etapas_obra WHERE id = :eid"),
            {"eid": etapa_id}
        ).fetchone()

        return jsonify({
            'ok': True,
            'fecha_inicio': str(row[0]) if row[0] else None,
            'fecha_fin': str(row[1]) if row[1] else None,
            'estado': row[2],
            'fechas_manuales': row[3],
            'propagadas': propagadas,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@obras_bp.route('/etapas/<int:etapa_id>/nivel', methods=['POST'])
@csrf.exempt
@login_required
def cambiar_nivel_etapa(etapa_id):
    """Cambiar nivel de encadenamiento de una etapa."""
    etapa = EtapaObra.query.get_or_404(etapa_id)
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        return jsonify({'error': 'Sin permisos'}), 403

    data = request.get_json(silent=True) or {}
    nivel = data.get('nivel')

    try:
        etapa.nivel_encadenamiento = int(nivel) if nivel is not None else None
        db.session.commit()

        # Recalcular dependencias y fechas
        from services.dependency_service import generar_dependencias_desde_niveles
        generar_dependencias_desde_niveles(etapa.obra_id)
        result = propagar_fechas_etapas(etapa.obra_id)
        db.session.commit()

        return jsonify({
            'ok': True,
            'nivel': etapa.nivel_encadenamiento,
            'shifted': result['shifted_count'],
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@obras_bp.route('/<int:id>/gantt-data')
@login_required
def gantt_data(id):
    """Retorna datos de etapas en formato compatible con frappe-gantt."""
    obra = Obra.query.get_or_404(id)
    etapas = (
        EtapaObra.query
        .filter_by(obra_id=id)
        .order_by(EtapaObra.nivel_encadenamiento.asc().nullslast(), EtapaObra.orden)
        .all()
    )

    # Cargar dependencias
    etapa_ids = [e.id for e in etapas]
    deps = EtapaDependencia.query.filter(
        EtapaDependencia.etapa_id.in_(etapa_ids)
    ).all() if etapa_ids else []

    deps_map = {}
    for d in deps:
        deps_map.setdefault(d.etapa_id, []).append(str(d.depende_de_id))

    # Estado → clase CSS para frappe-gantt
    estado_class = {
        'pendiente': 'gantt-pendiente',
        'en_curso': 'gantt-en-curso',
        'finalizada': 'gantt-finalizada',
    }

    tasks = []
    for e in etapas:
        # Solo usar fechas reales si la etapa ya arrancó
        if e.estado in ('en_curso', 'finalizada'):
            inicio = e.fecha_inicio_real or e.fecha_inicio_estimada
            fin = e.fecha_fin_real or e.fecha_fin_estimada
        else:
            inicio = e.fecha_inicio_estimada
            fin = e.fecha_fin_estimada

        # Si la etapa no tiene fechas, calcular desde sus tareas
        if not inicio or not fin:
            tareas = e.tareas.all() if hasattr(e.tareas, 'all') else (e.tareas or [])
            fechas_inicio = [t.fecha_inicio or t.fecha_inicio_plan or t.fecha_inicio_estimada for t in tareas if (t.fecha_inicio or t.fecha_inicio_plan or t.fecha_inicio_estimada)]
            fechas_fin = [t.fecha_fin or t.fecha_fin_plan or t.fecha_fin_estimada for t in tareas if (t.fecha_fin or t.fecha_fin_plan or t.fecha_fin_estimada)]
            if not inicio and fechas_inicio:
                inicio = min(fechas_inicio)
            if not fin and fechas_fin:
                fin = max(fechas_fin)

        if not inicio or not fin:
            continue

        # Calcular progreso: tareas completadas / total tareas (lógica binaria)
        if e.estado == 'finalizada':
            progress = 100
        else:
            progress = pct_etapa(e)

        tasks.append({
            'id': str(e.id),
            'name': e.nombre,
            'start': inicio.strftime('%Y-%m-%d'),
            'end': fin.strftime('%Y-%m-%d'),
            'progress': progress,
            'dependencies': ','.join(deps_map.get(e.id, [])),
            'custom_class': estado_class.get(e.estado, ''),
            'nivel': e.nivel_encadenamiento,
            'estado': e.estado,
            'fechas_manuales': e.fechas_manuales or False,
            'es_opcional': e.es_opcional or False,
        })

    response = jsonify(tasks)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


# ===== ENDPOINTS PARA SISTEMA DE APROBACIONES =====

@obras_bp.route("/avances/<int:avance_id>/aprobar", methods=['POST'])
@csrf.exempt
@login_required
def aprobar_avance(avance_id):
    from utils.permissions import can_approve_avance

    av = TareaAvance.query.get_or_404(avance_id)

    if not can_approve_avance(current_user, av):
        return jsonify(ok=False, error="Sin permiso"), 403

    if av.status == "aprobado":
        return jsonify(ok=True)

    # Validar que al aprobar no se exceda el 100% planificado
    tarea = TareaEtapa.query.get(av.tarea_id)
    plan = float(tarea.cantidad_planificada or 0) if tarea else 0
    if plan > 0:
        ya_aprobado = float(
            db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
            .filter(TareaAvance.tarea_id == av.tarea_id, TareaAvance.status == 'aprobado')
            .scalar() or 0
        )
        if ya_aprobado + float(av.cantidad) > plan:
            disponible = plan - ya_aprobado
            return jsonify(ok=False, error=f"No se puede aprobar: la cantidad ({float(av.cantidad)}) supera lo restante ({disponible:.2f}). Use 'Corregir' para ajustar la cantidad."), 400

    try:
        av.status = "aprobado"
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()

        t = tarea
        if t and not t.fecha_inicio_real:
            t.fecha_inicio_real = datetime.utcnow()

        db.session.commit()

        # Recalcular porcentaje y auto-completar si llega al 100%
        if av.tarea_id:
            recalc_tarea_pct(av.tarea_id)

        return jsonify(ok=True)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en aprobar_avance")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route("/avances/<int:avance_id>/rechazar", methods=['POST'])
@csrf.exempt
@login_required
def rechazar_avance(avance_id):
    from utils.permissions import can_approve_avance

    av = TareaAvance.query.get_or_404(avance_id)

    if not can_approve_avance(current_user, av):
        return jsonify(ok=False, error="Sin permiso"), 403

    try:
        av.status = "rechazado"
        av.reject_reason = request.form.get("motivo")
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()

        db.session.commit()

        # Recalcular porcentaje tras rechazar
        if av.tarea_id:
            recalc_tarea_pct(av.tarea_id)

        return jsonify(ok=True)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en rechazar_avance")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route("/avances/<int:avance_id>/corregir", methods=['POST'])
@csrf.exempt
@login_required
def corregir_avance(avance_id):
    """Corregir la cantidad de un avance y aprobarlo."""
    from utils.permissions import can_approve_avance

    av = TareaAvance.query.get_or_404(avance_id)

    if not can_approve_avance(current_user, av):
        return jsonify(ok=False, error="Sin permiso"), 403

    cantidad_str = request.form.get("cantidad_corregida", "").replace(",", ".")
    motivo = request.form.get("motivo", "")

    try:
        cantidad_corregida = float(cantidad_str)
        if cantidad_corregida < 0:
            return jsonify(ok=False, error="La cantidad no puede ser negativa"), 400
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Cantidad inválida"), 400

    # Validar que la corrección no exceda la cantidad planificada
    tarea = TareaEtapa.query.get(av.tarea_id)
    plan = float(tarea.cantidad_planificada or 0) if tarea else 0
    if plan > 0:
        otros_aprobados = float(
            db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
            .filter(TareaAvance.tarea_id == av.tarea_id, TareaAvance.status == 'aprobado', TareaAvance.id != av.id)
            .scalar() or 0
        )
        disponible = plan - otros_aprobados
        if cantidad_corregida > disponible:
            return jsonify(ok=False, error=f"La cantidad corregida ({cantidad_corregida}) supera lo disponible ({disponible:.2f}). Máximo: {disponible:.2f}."), 400

    try:
        # Guardar cantidad original para registro
        cantidad_original = float(av.cantidad)

        # Corregir la cantidad y aprobar
        av.cantidad = cantidad_corregida
        av.status = "aprobado"
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()
        av.reject_reason = f"Corregido por admin: {cantidad_original} -> {cantidad_corregida}. {motivo}"

        t = TareaEtapa.query.get(av.tarea_id)
        if t and not t.fecha_inicio_real:
            t.fecha_inicio_real = datetime.utcnow()

        db.session.commit()

        # Recalcular porcentaje y auto-completar si llega al 100%
        if av.tarea_id:
            recalc_tarea_pct(av.tarea_id)

        current_app.logger.info(
            "Avance %d corregido: %s -> %s por %s",
            avance_id, cantidad_original, cantidad_corregida, current_user.email
        )
        return jsonify(ok=True)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en corregir_avance")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route('/<int:obra_id>/wizard/tareas', methods=['POST'])
@login_required
def wizard_crear_tareas(obra_id):
    """Wizard: creación masiva de tareas/miembros en un paso."""
    return ProjectSharedService.wizard_crear_tareas(obra_id)


# ==== Wizard: catálogos ====

@obras_bp.route('/api/catalogo/etapas', methods=['GET'])
@login_required
def get_catalogo_etapas():
    try:
        catalogo = obtener_etapas_disponibles()
        response = jsonify({"ok": True, "etapas_catalogo": catalogo})
        response.headers['Content-Type'] = 'application/json'
        return response, 200
    except Exception as e:
        current_app.logger.exception("API Error obteniendo catálogo de etapas")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400


@obras_bp.route('/api/wizard-tareas/etapas', methods=['GET'])
@login_required
def get_wizard_etapas():
    try:
        obra_id = request.args.get('obra_id', type=int)
        if not obra_id:
            response = jsonify({"ok": False, "error": "obra_id es requerido"})
            response.headers['Content-Type'] = 'application/json'
            return response, 400

        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403

        catalogo = obtener_etapas_disponibles()

        etapas_creadas = EtapaObra.query.filter_by(obra_id=obra_id).order_by(EtapaObra.orden).all()
        etapas_creadas_data = [{"id": e.id, "slug": None, "nombre": e.nombre} for e in etapas_creadas]

        for etapa_creada in etapas_creadas_data:
            etapa_catalogo = next((c for c in catalogo if c['nombre'] == etapa_creada['nombre']), None)
            if etapa_catalogo:
                etapa_creada['slug'] = etapa_catalogo['slug']

        # Las etapas ya fueron creadas automáticamente al confirmar el presupuesto
        # Ahora el wizard solo sirve para agregar tareas adicionales a las etapas existentes
        # Por lo tanto, NO necesitamos pre-seleccionar nada, solo mostrar las etapas ya creadas
        etapas_preseleccionadas = []

        response = jsonify({
            "ok": True,
            "etapas_catalogo": catalogo,
            "etapas_creadas": etapas_creadas_data,
            "etapas_preseleccionadas": etapas_preseleccionadas
        })
        response.headers['Content-Type'] = 'application/json'
        return response, 200

    except Exception as e:
        current_app.logger.exception("API Error obteniendo etapas para wizard")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400


@obras_bp.route('/api/calcular-superficie-etapa', methods=['POST'])
@login_required
def api_calcular_superficie_etapa():
    """
    Calcula la superficie real de trabajo para una etapa específica.

    Recibe:
    - obra_id: ID de la obra (para obtener superficie cubierta)
    - etapa_slug: Identificador de la etapa (ej: 'revoque-grueso')
    - superficie_cubierta: (opcional) Si no se pasa, se obtiene de la obra

    Retorna:
    - superficie_calculada: m², m³, ml o unidades según corresponda
    - unidad: Unidad de medida
    - factor: Factor aplicado
    - descripcion: Explicación del cálculo
    """
    try:
        data = request.get_json(silent=True) or {}

        obra_id = data.get('obra_id')
        etapa_slug = data.get('etapa_slug', '').strip()
        superficie_cubierta = data.get('superficie_cubierta')

        # Validaciones
        if not etapa_slug:
            return jsonify({"ok": False, "error": "etapa_slug es requerido"}), 400

        # Si no se pasó superficie, obtenerla de la obra
        if superficie_cubierta is None and obra_id:
            obra = Obra.query.get(obra_id)
            if obra and obra.superficie_cubierta:
                superficie_cubierta = float(obra.superficie_cubierta)
            else:
                return jsonify({
                    "ok": False,
                    "error": "No se pudo obtener la superficie cubierta de la obra"
                }), 400
        elif superficie_cubierta is None:
            return jsonify({
                "ok": False,
                "error": "Se requiere obra_id o superficie_cubierta"
            }), 400

        # Calcular superficie para la etapa
        resultado = calcular_superficie_etapa(float(superficie_cubierta), etapa_slug)

        return jsonify({
            "ok": True,
            "etapa_slug": etapa_slug,
            "superficie_cubierta_obra": superficie_cubierta,
            **resultado
        }), 200

    except Exception as e:
        current_app.logger.exception("Error en api_calcular_superficie_etapa")
        return jsonify({"ok": False, "error": str(e)}), 500


@obras_bp.route('/api/factores-superficie', methods=['GET'])
@login_required
def api_get_factores_superficie():
    """
    Devuelve todos los factores de superficie disponibles.
    Útil para mostrar una tabla de referencia al usuario.
    """
    try:
        obra_id = request.args.get('obra_id', type=int)
        superficie_cubierta = request.args.get('superficie', type=float)

        # Si se pasa obra_id, obtener superficie de la obra
        if obra_id and not superficie_cubierta:
            obra = Obra.query.get(obra_id)
            if obra and obra.superficie_cubierta:
                superficie_cubierta = float(obra.superficie_cubierta)

        # Si hay superficie, calcular todas las etapas
        if superficie_cubierta:
            resultado = obtener_factores_todas_etapas(superficie_cubierta)
            return jsonify({
                "ok": True,
                "superficie_cubierta": superficie_cubierta,
                "factores": resultado
            }), 200

        # Si no hay superficie, devolver solo los factores base
        factores_base = {}
        for slug, config in FACTORES_SUPERFICIE_ETAPA.items():
            factores_base[slug] = {
                'nombre': slug.replace('-', ' ').title(),
                'factor': config['factor'],
                'unidad': config['unidad_default'],
                'descripcion': config['descripcion'],
                'notas': config.get('notas', '')
            }

        return jsonify({
            "ok": True,
            "factores": factores_base
        }), 200

    except Exception as e:
        current_app.logger.exception("Error en api_get_factores_superficie")
        return jsonify({"ok": False, "error": str(e)}), 500


@obras_bp.route('/api/wizard-tareas/tareas', methods=['POST','GET'])
@login_required
def wizard_tareas_catalogo():
    try:
        if request.method == 'POST' and request.is_json:
            data = request.get_json(silent=True) or {}
            obra_id = data.get('obra_id')
            etapas  = data.get('etapas')
        else:
            obra_id = request.args.get('obra_id', type=int)
            etapas  = request.args.getlist('etapas')

        if not obra_id or not etapas:
            response = jsonify({'ok': False, 'error': 'obra_id y etapas son requeridos'})
            response.headers['Content-Type'] = 'application/json'
            return response, 400

        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403

        from tareas_predefinidas import obtener_tareas_por_etapa
        from etapas_predefinidas import obtener_etapas_disponibles

        catalogo_etapas = obtener_etapas_disponibles()
        slug_to_nombre = {e['slug']: e['nombre'] for e in catalogo_etapas}

        resp = []
        for slug in etapas:
            nombre_etapa = slug_to_nombre.get(slug)
            if nombre_etapa:
                tareas_etapa = obtener_tareas_por_etapa(nombre_etapa)
                for idx, tarea in enumerate(tareas_etapa):
                    resp.append({
                        'id': f'{slug}-{idx+1}',
                        'nombre': tarea['nombre'],
                        'descripcion': tarea.get('descripcion', ''),
                        'etapa_slug': slug,
                        'horas': tarea.get('horas', 0)
                    })

        resp.sort(key=lambda t: (t['etapa_slug'], t['nombre']))

        response = jsonify({'ok': True, 'tareas_catalogo': resp})
        response.headers['Content-Type'] = 'application/json'
        return response, 200

    except Exception as e:
        current_app.logger.error(f"Error en wizard_tareas_endpoint: {e}")
        response = jsonify({"ok": False, "error": "Error interno del servidor"})
        response.headers['Content-Type'] = 'application/json'
        return response, 500


@obras_bp.route('/api/wizard-tareas/opciones')
@login_required
def wizard_tareas_opciones():
    """Paso 3 del wizard: devuelve unidades sugeridas y equipo de la obra."""
    try:
        obra_id = request.args.get('obra_id', type=int)
        if not obra_id:
            response = jsonify({"ok": False, "error": "obra_id requerido"})
            response.headers['Content-Type'] = 'application/json'
            return response, 400

        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403

        # Unidades base para construcción
        unidades = ['m2', 'ml', 'm3', 'un', 'kg', 'h']

        usuarios = []
        try:
            query_result = (db.session.query(Usuario.id, Usuario.nombre, Usuario.apellido, ObraMiembro.rol_en_obra)
                           .join(ObraMiembro, ObraMiembro.usuario_id == Usuario.id)
                           .filter(ObraMiembro.obra_id == obra_id)
                           .filter(Usuario.activo == True)
                           .order_by(ObraMiembro.rol_en_obra)  # Ordenar por rol
                           .all())

            for user_id, nombre, apellido, rol in query_result:
                nombre_completo = f"{(nombre or '').strip()} {(apellido or '').strip()}".strip() or "Sin nombre"
                rol_display = rol or 'Sin rol'
                # Incluir el rol en el nombre para que sea más claro
                nombre_con_rol = f"{nombre_completo} ({rol_display})"
                usuarios.append({
                    'id': user_id,
                    'nombre': nombre_con_rol,
                    'rol': rol_display
                })
        except Exception as e:
            current_app.logger.warning(f"Error al obtener equipo de obra {obra_id}: {e}")

        return jsonify({"ok": True, "unidades": unidades, "usuarios": usuarios}), 200

    except Exception as e:
        current_app.logger.exception("API Error wizard_tareas_opciones")
        return jsonify({"ok": False, "error": str(e)}), 400


@obras_bp.route('/api/wizard-tareas/budget-preview', methods=['POST'])
@login_required
def wizard_budget_preview():
    """
    Endpoint stub para preview de presupuesto en wizard
    Esta funcionalidad requiere integración con presupuestos
    """
    current_app.logger.warning("Intento de usar /api/wizard-tareas/budget-preview - funcionalidad no implementada")

    # Devolver una respuesta básica para que el wizard pueda continuar
    return jsonify({
        'ok': True,
        'total_estimado': 0,
        'mensaje': 'La estimación de presupuesto no está disponible. Continúa con la creación de tareas.'
    }), 200


@obras_bp.route('/api/wizard-tareas/create', methods=['POST'])
@login_required
def wizard_create_tasks():
    """
    Creación masiva de tareas desde wizard
    """
    try:
        data = request.get_json() or {}
        obra_id = data.get('obra_id')
        tareas_data = data.get('tareas', [])
        evitar_duplicados = data.get('evitar_duplicados', True)

        if not obra_id:
            return jsonify({'ok': False, 'error': 'obra_id requerido'}), 400

        if not tareas_data:
            return jsonify({'ok': False, 'error': 'No hay tareas para crear'}), 400

        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({'ok': False, 'error': 'Sin permisos para gestionar esta obra'}), 403

        # Agrupar tareas por etapa
        tareas_por_etapa = {}
        for tarea in tareas_data:
            etapa_key = tarea.get('etapa_slug') or tarea.get('etapa_nombre', '')
            if not etapa_key:
                continue
            if etapa_key not in tareas_por_etapa:
                tareas_por_etapa[etapa_key] = {
                    'nombre': tarea.get('etapa_nombre', etapa_key),
                    'slug': tarea.get('etapa_slug'),
                    'tareas': []
                }
            tareas_por_etapa[etapa_key]['tareas'].append(tarea)

        created_count = 0
        skipped_count = 0
        etapas_created = 0

        for etapa_key, etapa_info in tareas_por_etapa.items():
            # Buscar o crear etapa
            etapa = EtapaObra.query.filter_by(
                obra_id=obra_id,
                nombre=etapa_info['nombre']
            ).first()

            if not etapa:
                ultimo_orden = db.session.query(db.func.max(EtapaObra.orden)).filter_by(obra_id=obra_id).scalar() or 0
                etapa = EtapaObra(
                    obra_id=obra_id,
                    nombre=etapa_info['nombre'],
                    descripcion=f"Etapa creada desde wizard",
                    orden=ultimo_orden + 1
                )
                db.session.add(etapa)
                db.session.flush()  # Para obtener el ID
                etapas_created += 1

            # Crear tareas en esta etapa
            for tarea_data in etapa_info['tareas']:
                nombre_tarea = tarea_data.get('nombre', '').strip()
                if not nombre_tarea:
                    continue

                # Verificar duplicados si es necesario
                if evitar_duplicados:
                    existe = TareaEtapa.query.filter_by(
                        etapa_id=etapa.id,
                        nombre=nombre_tarea
                    ).first()
                    if existe:
                        skipped_count += 1
                        continue

                # Parsear fechas
                fecha_inicio = parse_date(tarea_data.get('fecha_inicio'))
                fecha_fin = parse_date(tarea_data.get('fecha_fin'))

                # Validar unidad
                VALID_UNITS = {'m2', 'ml', 'm3', 'un', 'h', 'kg'}
                unidad = tarea_data.get('unidad', 'h').lower()
                if unidad not in VALID_UNITS:
                    unidad = 'h'

                # Crear tarea
                nueva_tarea = TareaEtapa(
                    etapa_id=etapa.id,
                    nombre=nombre_tarea,
                    horas_estimadas=tarea_data.get('horas'),
                    cantidad_planificada=tarea_data.get('cantidad'),
                    unidad=unidad,
                    fecha_inicio_plan=fecha_inicio,
                    fecha_fin_plan=fecha_fin,
                    prioridad=tarea_data.get('prioridad', 'media'),
                    responsable_id=tarea_data.get('asignado_usuario_id')
                )
                db.session.add(nueva_tarea)
                db.session.flush()  # Para obtener el ID

                # Asignar usuario si viene
                asignado_id = tarea_data.get('asignado_usuario_id')
                if asignado_id:
                    try:
                        asignacion = TareaMiembro(
                            tarea_id=nueva_tarea.id,
                            user_id=int(asignado_id)
                        )
                        db.session.add(asignacion)
                    except Exception as e:
                        current_app.logger.warning(f"No se pudo asignar usuario {asignado_id} a tarea: {e}")

                created_count += 1

        db.session.commit()

        # Asignar niveles de encadenamiento si se crearon etapas nuevas
        if etapas_created > 0:
            try:
                from services.dependency_service import asignar_niveles_por_defecto
                asignar_niveles_por_defecto(obra_id)
                db.session.commit()
            except Exception as e_dep:
                current_app.logger.warning(f"No se pudieron asignar niveles: {e_dep}")

        return jsonify({
            'ok': True,
            'creadas': created_count,
            'omitidas': skipped_count,
            'etapas_creadas': etapas_created,
            'mensaje': f'Se crearon {created_count} tareas en {etapas_created} etapas. {skipped_count} tareas omitidas por duplicados.'
        }), 200

    except Exception as e:
        current_app.logger.exception("Error en wizard_create_tasks")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================
# ESCALA SALARIAL UOCRA + CUADRILLAS TIPO
# ============================================================
# REMITOS
# ============================================================

@obras_bp.route('/<int:obra_id>/remitos', methods=['POST'])
@csrf.exempt
@login_required
def crear_remito(obra_id):
    """Crear un remito manualmente."""
    from models.inventory import Remito, RemitoItem
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador', 'pm', 'project_manager', 'jefe_obra'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos inválidos'), 400

    try:
        remito = Remito(
            organizacion_id=current_user.organizacion_id,
            obra_id=obra_id,
            numero_remito=data['numero_remito'],
            proveedor=data['proveedor'],
            fecha=date.fromisoformat(data['fecha']),
            estado=data.get('estado', 'recibido'),
            requerimiento_id=int(data['requerimiento_id']) if data.get('requerimiento_id') else None,
            recibido_por_id=int(data['recibido_por_id']) if data.get('recibido_por_id') else current_user.id,
            notas=data.get('notas'),
            created_by_id=current_user.id,
        )
        db.session.add(remito)
        db.session.flush()

        for item_data in data.get('items', []):
            item = RemitoItem(
                remito_id=remito.id,
                descripcion=item_data['descripcion'],
                cantidad=item_data['cantidad'],
                unidad=item_data.get('unidad', 'u'),
                observacion=item_data.get('observacion'),
            )
            db.session.add(item)

        db.session.commit()
        return jsonify(ok=True, id=remito.id)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error creando remito")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:obra_id>/remitos/<int:remito_id>')
@login_required
def ver_remito(obra_id, remito_id):
    """API: obtener detalle de un remito."""
    from models.inventory import Remito
    remito = Remito.query.get_or_404(remito_id)
    return jsonify(ok=True, remito={
        'id': remito.id,
        'numero_remito': remito.numero_remito,
        'proveedor': remito.proveedor,
        'fecha': remito.fecha.strftime('%d/%m/%Y') if remito.fecha else None,
        'estado': remito.estado,
        'estado_display': remito.estado_display,
        'estado_color': remito.estado_color,
        'notas': remito.notas,
        'recibido_por': remito.recibido_por.nombre_completo if remito.recibido_por else None,
        'requerimiento_numero': remito.requerimiento.numero if remito.requerimiento else None,
        'items': [{
            'descripcion': i.descripcion,
            'cantidad': float(i.cantidad),
            'unidad': i.unidad,
            'observacion': i.observacion,
        } for i in remito.items],
    })


@obras_bp.route('/<int:obra_id>/remitos/<int:remito_id>', methods=['DELETE'])
@csrf.exempt
@login_required
def eliminar_remito(obra_id, remito_id):
    """Eliminar un remito."""
    from models.inventory import Remito
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador', 'pm', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    remito = Remito.query.get_or_404(remito_id)
    try:
        db.session.delete(remito)
        db.session.commit()
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


# ============================================================
# ESCALA SALARIAL UOCRA + CUADRILLAS TIPO
# ============================================================

@obras_bp.route('/escala-salarial')
@login_required
def escala_salarial():
    """Página de gestión de escala salarial UOCRA y cuadrillas."""
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador', 'pm', 'project_manager'}):
        flash('Sin permisos para esta sección', 'warning')
        return redirect(url_for('obras.listar'))

    org_id = current_user.organizacion_id
    if not org_id:
        flash('No tenés una organización asignada', 'warning')
        return redirect(url_for('obras.listar'))

    # Asegurar que las tablas existan
    try:
        db.create_all()
    except Exception:
        pass

    # Seed datos por defecto si no existen
    try:
        from services.cuadrillas_service import seed_escala_salarial, seed_cuadrillas_default
        seed_escala_salarial(org_id)
        seed_cuadrillas_default(org_id)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error seeding escala/cuadrillas: %s", e)

    return render_template('obras/escala_salarial.html')


@obras_bp.route('/escala-salarial/api')
@login_required
def escala_salarial_api():
    """API: obtener escala salarial vigente."""
    try:
        from services.cuadrillas_service import obtener_escala_vigente
        org_id = current_user.organizacion_id
        if not org_id:
            return jsonify(ok=True, items=[])
        escalas = obtener_escala_vigente(org_id)
        return jsonify(ok=True, items=[{
            'id': e.id,
            'categoria': e.categoria,
            'descripcion': e.descripcion,
            'jornal': float(e.jornal),
            'tarifa_hora': float(e.tarifa_hora or 0),
            'vigencia_desde': e.vigencia_desde.isoformat() if e.vigencia_desde else None,
        } for e in escalas])
    except Exception as e:
        current_app.logger.exception("Error en escala_salarial_api")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/escala-salarial/api', methods=['POST'])
@csrf.exempt
@login_required
def escala_salarial_actualizar():
    """API: actualizar escala salarial."""
    from services.cuadrillas_service import actualizar_escala
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True)
    if not data or 'items' not in data:
        return jsonify(ok=False, error='Datos inválidos'), 400

    try:
        vigencia = data.get('vigencia_desde')
        vigencia_date = date.fromisoformat(vigencia) if vigencia else None
        actualizar_escala(current_user.organizacion_id, data['items'], vigencia_date)
        return jsonify(ok=True, mensaje='Escala salarial actualizada')
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/cuadrillas/api')
@login_required
def cuadrillas_api():
    """API: obtener cuadrillas tipo de la organización."""
    from models.budgets import CuadrillaTipo
    org_id = current_user.organizacion_id
    tipo_obra = request.args.get('tipo_obra')
    etapa_tipo = request.args.get('etapa_tipo')

    query = CuadrillaTipo.query.filter_by(organizacion_id=org_id, activo=True)
    if tipo_obra:
        query = query.filter_by(tipo_obra=tipo_obra)
    if etapa_tipo:
        query = query.filter_by(etapa_tipo=etapa_tipo)

    cuadrillas = query.order_by(CuadrillaTipo.etapa_tipo, CuadrillaTipo.tipo_obra).all()

    return jsonify(ok=True, items=[{
        'id': c.id,
        'nombre': c.nombre,
        'etapa_tipo': c.etapa_tipo,
        'tipo_obra': c.tipo_obra,
        'rendimiento_diario': float(c.rendimiento_diario or 0),
        'unidad_rendimiento': c.unidad_rendimiento,
        'costo_diario': float(c.costo_diario),
        'cantidad_personas': c.cantidad_personas,
        'miembros': [{
            'id': m.id,
            'rol': m.rol,
            'cantidad': float(m.cantidad),
            'jornal': float(m.jornal_override or (m.escala.jornal if m.escala else 0)),
            'categoria': m.escala.categoria if m.escala else None,
            'descripcion_categoria': m.escala.descripcion if m.escala else None,
        } for m in c.miembros]
    } for c in cuadrillas])


@obras_bp.route('/cuadrillas/api', methods=['POST'])
@csrf.exempt
@login_required
def cuadrillas_guardar():
    """API: crear o actualizar una cuadrilla tipo."""
    from models.budgets import CuadrillaTipo, MiembroCuadrilla, EscalaSalarialUOCRA
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador', 'pm', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos inválidos'), 400

    org_id = current_user.organizacion_id

    try:
        cuadrilla_id = data.get('id')
        if cuadrilla_id:
            cuadrilla = CuadrillaTipo.query.get(cuadrilla_id)
            if not cuadrilla or cuadrilla.organizacion_id != org_id:
                return jsonify(ok=False, error='Cuadrilla no encontrada'), 404
        else:
            cuadrilla = CuadrillaTipo(organizacion_id=org_id)
            db.session.add(cuadrilla)

        cuadrilla.nombre = data.get('nombre', cuadrilla.nombre)
        cuadrilla.etapa_tipo = data.get('etapa_tipo', cuadrilla.etapa_tipo)
        cuadrilla.tipo_obra = data.get('tipo_obra', cuadrilla.tipo_obra)
        cuadrilla.rendimiento_diario = Decimal(str(data.get('rendimiento_diario', cuadrilla.rendimiento_diario or 0)))
        cuadrilla.unidad_rendimiento = data.get('unidad_rendimiento', cuadrilla.unidad_rendimiento)

        # Actualizar miembros si se envían
        if 'miembros' in data:
            # Borrar miembros existentes
            MiembroCuadrilla.query.filter_by(cuadrilla_id=cuadrilla.id).delete() if cuadrilla.id else None
            db.session.flush()

            for m_data in data['miembros']:
                escala = None
                if m_data.get('categoria'):
                    escala = EscalaSalarialUOCRA.query.filter_by(
                        organizacion_id=org_id,
                        categoria=m_data['categoria'],
                        activo=True,
                    ).first()

                miembro = MiembroCuadrilla(
                    cuadrilla_id=cuadrilla.id,
                    escala_id=escala.id if escala else None,
                    rol=m_data['rol'],
                    cantidad=Decimal(str(m_data.get('cantidad', 1))),
                    jornal_override=Decimal(str(m_data['jornal_override'])) if m_data.get('jornal_override') else None,
                )
                db.session.add(miembro)

        db.session.commit()
        return jsonify(ok=True, id=cuadrilla.id, mensaje='Cuadrilla guardada')
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


# =============================================================================
# MOVIMIENTOS DE EQUIPOS - Despacho / Traslado / Devolución
# =============================================================================

@obras_bp.route('/equipos/movimientos', methods=['GET'])
@login_required
def equipos_movimientos():
    """Panel de ubicación y movimientos de equipos"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id

    equipos = Equipment.query.filter_by(company_id=org_id).order_by(Equipment.nombre).all()
    obras = Obra.query.filter_by(organizacion_id=org_id, estado='en_curso').order_by(Obra.nombre).all()

    # Últimos movimientos
    movimientos = EquipmentMovement.query.filter_by(company_id=org_id)\
        .order_by(EquipmentMovement.fecha_movimiento.desc()).limit(50).all()

    return render_template('obras/equipos_movimientos.html',
                           equipos=equipos, obras=obras, movimientos=movimientos)


@obras_bp.route('/equipos/<int:equipo_id>/despachar', methods=['POST'])
@login_required
def despachar_equipo(equipo_id):
    """Despacho: Depósito → Obra"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id
    equipo = Equipment.query.filter_by(id=equipo_id, company_id=org_id).first_or_404()

    if equipo.ubicacion_tipo != 'deposito':
        return jsonify(ok=False, error='El equipo no está en depósito'), 400

    destino_obra_id = request.form.get('destino_obra_id', type=int)
    if not destino_obra_id:
        return jsonify(ok=False, error='Debe indicar la obra destino'), 400

    obra_destino = Obra.query.filter_by(id=destino_obra_id, organizacion_id=org_id).first()
    if not obra_destino:
        return jsonify(ok=False, error='Obra destino no encontrada'), 404

    try:
        mov = EquipmentMovement(
            equipment_id=equipo.id,
            company_id=org_id,
            tipo='despacho',
            origen_tipo='deposito',
            origen_obra_id=None,
            destino_tipo='obra',
            destino_obra_id=destino_obra_id,
            despachado_por=current_user.id,
            notas=request.form.get('notas', ''),
            costo_transporte=request.form.get('costo_transporte', 0, type=float),
            estado='recibido'
        )
        db.session.add(mov)

        # Actualizar ubicación del equipo
        equipo.ubicacion_tipo = 'obra'
        equipo.ubicacion_obra_id = destino_obra_id

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" despachado a {obra_destino.nombre}', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/<int:equipo_id>/trasladar', methods=['POST'])
@login_required
def trasladar_equipo(equipo_id):
    """Traslado: Obra → Obra"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id
    equipo = Equipment.query.filter_by(id=equipo_id, company_id=org_id).first_or_404()

    if equipo.ubicacion_tipo != 'obra':
        return jsonify(ok=False, error='El equipo no está en una obra'), 400

    destino_obra_id = request.form.get('destino_obra_id', type=int)
    if not destino_obra_id:
        return jsonify(ok=False, error='Debe indicar la obra destino'), 400

    if destino_obra_id == equipo.ubicacion_obra_id:
        return jsonify(ok=False, error='El equipo ya está en esa obra'), 400

    obra_destino = Obra.query.filter_by(id=destino_obra_id, organizacion_id=org_id).first()
    if not obra_destino:
        return jsonify(ok=False, error='Obra destino no encontrada'), 404

    try:
        mov = EquipmentMovement(
            equipment_id=equipo.id,
            company_id=org_id,
            tipo='traslado',
            origen_tipo='obra',
            origen_obra_id=equipo.ubicacion_obra_id,
            destino_tipo='obra',
            destino_obra_id=destino_obra_id,
            despachado_por=current_user.id,
            notas=request.form.get('notas', ''),
            costo_transporte=request.form.get('costo_transporte', 0, type=float),
            estado='recibido'
        )
        db.session.add(mov)

        equipo.ubicacion_tipo = 'obra'
        equipo.ubicacion_obra_id = destino_obra_id

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" trasladado a {obra_destino.nombre}', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/<int:equipo_id>/devolver', methods=['POST'])
@login_required
def devolver_equipo(equipo_id):
    """Devolución: Obra → Depósito"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id
    equipo = Equipment.query.filter_by(id=equipo_id, company_id=org_id).first_or_404()

    if equipo.ubicacion_tipo != 'obra':
        return jsonify(ok=False, error='El equipo ya está en depósito'), 400

    try:
        mov = EquipmentMovement(
            equipment_id=equipo.id,
            company_id=org_id,
            tipo='devolucion',
            origen_tipo='obra',
            origen_obra_id=equipo.ubicacion_obra_id,
            destino_tipo='deposito',
            destino_obra_id=None,
            despachado_por=current_user.id,
            notas=request.form.get('notas', ''),
            costo_transporte=request.form.get('costo_transporte', 0, type=float),
            estado='recibido'
        )
        db.session.add(mov)

        equipo.ubicacion_tipo = 'deposito'
        equipo.ubicacion_obra_id = None

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" devuelto al depósito', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/ubicaciones-json', methods=['GET'])
@login_required
def equipos_ubicaciones_json():
    """API: ubicación actual de todos los equipos"""
    from models.equipment import Equipment
    org_id = current_user.organizacion_id
    equipos = Equipment.query.filter_by(company_id=org_id, estado='activo').all()

    result = []
    for eq in equipos:
        result.append({
            'id': eq.id,
            'nombre': eq.nombre,
            'codigo': eq.codigo,
            'tipo': eq.tipo,
            'ubicacion_tipo': eq.ubicacion_tipo,
            'ubicacion_obra_id': eq.ubicacion_obra_id,
            'ubicacion_obra_nombre': eq.ubicacion_obra.nombre if eq.ubicacion_obra else None,
            'costo_hora': float(eq.costo_hora) if eq.costo_hora else 0,
            'estado': eq.estado,
        })

    return jsonify(ok=True, equipos=result)
