"""Blueprint de Obras - gestion de proyectos de construccion."""
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort, make_response)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import json
import os
import requests
from extensions import db
from extensions import limiter
from sqlalchemy import text, func
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import selectinload
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
from services.permissions import validate_obra_ownership, validate_tarea_ownership, get_org_id
from services.plan_service import require_active_subscription
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

def calcular_costo_materiales(obra_id):
    """Calcula el costo real de materiales consumidos desde UsoInventario."""
    from decimal import Decimal
    resultado = db.session.query(
        db.func.coalesce(
            db.func.sum(
                UsoInventario.cantidad_usada *
                db.func.coalesce(UsoInventario.precio_unitario_al_uso, 0)
            ), 0
        )
    ).filter(UsoInventario.obra_id == obra_id).scalar()
    return Decimal(str(resultado or 0))


obras_bp = Blueprint('obras', __name__)

_COORD_PRECISION = Decimal('0.00000001')


def _to_coord_decimal(value):
    """Normaliza coordenadas geograficas a Decimal con 8 decimales."""
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

# Ciudades principales de Argentina para sugerencias rapidas
CIUDADES_ARGENTINA = [
    {'nombre': 'Buenos Aires, CABA', 'provincia': 'Ciudad Autonoma de Buenos Aires'},
    {'nombre': 'Cordoba', 'provincia': 'Cordoba'},
    {'nombre': 'Rosario', 'provincia': 'Santa Fe'},
    {'nombre': 'Mendoza', 'provincia': 'Mendoza'},
    {'nombre': 'La Plata', 'provincia': 'Buenos Aires'},
    {'nombre': 'San Miguel de Tucuman', 'provincia': 'Tucuman'},
    {'nombre': 'Mar del Plata', 'provincia': 'Buenos Aires'},
    {'nombre': 'Salta', 'provincia': 'Salta'},
    {'nombre': 'Santa Fe', 'provincia': 'Santa Fe'},
    {'nombre': 'San Juan', 'provincia': 'San Juan'},
    {'nombre': 'Resistencia', 'provincia': 'Chaco'},
    {'nombre': 'Neuquen', 'provincia': 'Neuquen'},
    {'nombre': 'Corrientes', 'provincia': 'Corrientes'},
    {'nombre': 'Posadas', 'provincia': 'Misiones'},
    {'nombre': 'San Salvador de Jujuy', 'provincia': 'Jujuy'},
    {'nombre': 'Bahia Blanca', 'provincia': 'Buenos Aires'},
    {'nombre': 'Parana', 'provincia': 'Entre Rios'},
    {'nombre': 'Formosa', 'provincia': 'Formosa'},
    {'nombre': 'San Luis', 'provincia': 'San Luis'},
    {'nombre': 'La Rioja', 'provincia': 'La Rioja'},
    {'nombre': 'Catamarca', 'provincia': 'Catamarca'},
    {'nombre': 'Rio Gallegos', 'provincia': 'Santa Cruz'},
    {'nombre': 'Ushuaia', 'provincia': 'Tierra del Fuego'},
    {'nombre': 'Rawson', 'provincia': 'Chubut'},
    {'nombre': 'Viedma', 'provincia': 'Rio Negro'},
    {'nombre': 'Santa Rosa', 'provincia': 'La Pampa'},
    # Localidades populares del GBA
    {'nombre': 'Quilmes', 'provincia': 'Buenos Aires'},
    {'nombre': 'Lanus', 'provincia': 'Buenos Aires'},
    {'nombre': 'Avellaneda', 'provincia': 'Buenos Aires'},
    {'nombre': 'Lomas de Zamora', 'provincia': 'Buenos Aires'},
    {'nombre': 'San Isidro', 'provincia': 'Buenos Aires'},
    {'nombre': 'Vicente Lopez', 'provincia': 'Buenos Aires'},
    {'nombre': 'Tigre', 'provincia': 'Buenos Aires'},
    {'nombre': 'Pilar', 'provincia': 'Buenos Aires'},
    {'nombre': 'Moron', 'provincia': 'Buenos Aires'},
    {'nombre': 'San Martin', 'provincia': 'Buenos Aires'},
    {'nombre': 'Tres de Febrero', 'provincia': 'Buenos Aires'},
    {'nombre': 'Merlo', 'provincia': 'Buenos Aires'},
    {'nombre': 'Moreno', 'provincia': 'Buenos Aires'},
    {'nombre': 'Florencio Varela', 'provincia': 'Buenos Aires'},
    {'nombre': 'Berazategui', 'provincia': 'Buenos Aires'},
]

# Cache simple para busquedas (evita llamadas repetidas a Nominatim)
_address_cache = {}
_cache_max_size = 100

def _get_cached_results(query):
    """Obtiene resultados del cache si existen"""
    return _address_cache.get(query.lower())

def _set_cached_results(query, results):
    """Guarda resultados en cache"""
    if len(_address_cache) >= _cache_max_size:
        # Eliminar la entrada mas antigua (FIFO simple)
        oldest_key = next(iter(_address_cache))
        del _address_cache[oldest_key]
    _address_cache[query.lower()] = results

def _parse_address_query(query):
    """Parsea la query para detectar calle, numero y ciudad"""
    import re

    result = {
        'street': None,
        'number': None,
        'city': None,
        'original': query
    }

    number_match = re.search(r'\b(\d{2,5})\b', query)
    if number_match:
        result['number'] = number_match.group(1)
        query_without_number = query.replace(number_match.group(1), '').strip()
    else:
        query_without_number = query

    if ',' in query_without_number:
        parts = query_without_number.split(',')
        result['street'] = parts[0].strip()
        result['city'] = parts[1].strip() if len(parts) > 1 else None
    else:
        result['street'] = query_without_number.strip()

    return result

def _format_result(item, query_lower):
    """Formatea un resultado de Nominatim para mejor visualizacion"""
    addr = item.get('address', {})

    parts = []

    road = addr.get('road', '')
    house_number = addr.get('house_number', '')
    if road:
        if house_number:
            parts.append(f"{road} {house_number}")
        else:
            parts.append(road)

    suburb = addr.get('suburb', '') or addr.get('neighbourhood', '')
    if suburb and suburb not in parts:
        parts.append(suburb)

    city = addr.get('city', '') or addr.get('town', '') or addr.get('village', '') or addr.get('municipality', '')
    if city and city not in parts:
        parts.append(city)

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


# ==== Metricas y utilidades ====

def resumen_tarea(t):
    """Calcular metricas de una tarea a prueba de nulos"""
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
    """Helper para conversion segura a Decimal"""
    if x is None:
        return Decimal('0')
    return x if isinstance(x, Decimal) else Decimal(str(x))


def seed_tareas_para_etapa(nueva_etapa, auto_commit=True, slug=None):
    """
    Crea tareas predefinidas en una etapa automaticamente.
    Usa el catalogo de tareas_predefinidas.py (tareas reales de obra).
    Idempotente: no crea duplicados si ya existen tareas.
    """
    from tareas_predefinidas import obtener_tareas_por_etapa

    # Si la etapa ya tiene tareas, no crear mas
    tareas_existentes = TareaEtapa.query.filter_by(etapa_id=nueva_etapa.id).count()
    if tareas_existentes > 0:
        return 0

    nombre_etapa = nueva_etapa.nombre
    tareas_predefinidas = obtener_tareas_por_etapa(nombre_etapa)

    if not tareas_predefinidas:
        return 0

    creadas = 0
    for tarea_def in tareas_predefinidas:
        # Saltar tareas opcionales
        if tarea_def.get('si_aplica'):
            continue

        tarea = TareaEtapa(
            etapa_id=nueva_etapa.id,
            nombre=tarea_def['nombre'],
            estado='pendiente',
            horas_estimadas=tarea_def.get('horas', 0),
            unidad='un' if tarea_def.get('aplica_cantidad') is False else 'h',
        )
        db.session.add(tarea)
        creadas += 1

    if auto_commit and creadas > 0:
        db.session.flush()

    return creadas


def geolocalizar_direccion(direccion):
    """Geolocaliza una direccion usando OpenStreetMap Nominatim API"""
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
        # Sin cantidad planificada: si hay algun avance aprobado, considerar 100%
        if ejecutado > 0:
            tarea.porcentaje_avance = 100
        else:
            tarea.porcentaje_avance = 0
    else:
        tarea.porcentaje_avance = min(100, round((ejecutado / meta) * 100, 2))

    # Auto-cambiar estado segun porcentaje de avance
    if tarea.porcentaje_avance >= 100 and tarea.estado != 'completada':
        tarea.estado = 'completada'
        tarea.fecha_fin_real = datetime.utcnow()
        current_app.logger.info(f"Tarea {tarea.id} '{tarea.nombre}' auto-completada al alcanzar 100%")
    elif tarea.porcentaje_avance > 0 and tarea.estado == 'pendiente':
        tarea.estado = 'en_curso'
        if not tarea.fecha_inicio_real:
            tarea.fecha_inicio_real = datetime.utcnow()
        current_app.logger.info(f"Tarea {tarea.id} '{tarea.nombre}' auto-iniciada al registrar avance")

        # Aprobar automaticamente todos los avances pendientes de esta tarea
        avances_pendientes = [a for a in tarea.avances if a.status == 'pendiente']
        for avance in avances_pendientes:
            avance.status = 'aprobado'
            current_app.logger.info(f"Avance {avance.id} auto-aprobado al completar tarea {tarea.id}")

    # Auto-actualizar estado de la etapa segun sus tareas
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

        # Sincronizar estado de la obra segun sus etapas
        obra = etapa.obra
        if obra:
            sincronizar_estado_obra(obra)

    db.session.commit()
    return float(tarea.porcentaje_avance or 0)

def pct_etapa(etapa):
    """Progreso de etapa = % de tareas completadas (logica binaria).
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
    """Sincroniza obra.estado segun el estado de sus etapas."""
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


# === DISTRIBUCION INTELIGENTE DE DATOS ETAPA -> TAREAS ===

def distribuir_datos_etapa_a_tareas(etapa_id, forzar=False):
    """Distribuye horas, cantidad, unidad, fechas y rendimiento de la etapa a sus tareas."""
    from datetime import timedelta
    from tareas_predefinidas import obtener_tareas_por_etapa

    etapa = EtapaObra.query.get(etapa_id)
    if not etapa:
        return 0

    cantidad_etapa = float(etapa.cantidad_total_planificada or 0)
    unidad_etapa = etapa.unidad_medida or 'm2'
    # Solo usar fechas reales si la etapa ya arranco
    if etapa.estado in ('en_curso', 'finalizada'):
        inicio_etapa = etapa.fecha_inicio_real or etapa.fecha_inicio_estimada
        fin_etapa = etapa.fecha_fin_real or etapa.fecha_fin_estimada
    else:
        inicio_etapa = etapa.fecha_inicio_estimada
        fin_etapa = etapa.fecha_fin_estimada

    tareas = etapa.tareas.order_by(TareaEtapa.id).all()
    if not tareas:
        return 0

    # --- PASO 1: Asignar horas proporcionales desde catalogo ---
    catalogo = obtener_tareas_por_etapa(etapa.nombre)
    catalogo_map = {}
    for t_cat in catalogo:
        catalogo_map[t_cat['nombre'].lower().strip()] = t_cat

    for tarea in tareas:
        # Respetar ediciones manuales del usuario: no sobrescribir horas
        # ni descripcion desde el catálogo de tareas predefinidas.
        if getattr(tarea, 'editado_manual', False):
            continue
        key = tarea.nombre.lower().strip()
        info_cat = catalogo_map.get(key)
        if info_cat:
            horas_catalogo = info_cat.get('horas', 1)
            if not tarea.horas_estimadas:
                tarea.horas_estimadas = horas_catalogo
            if not tarea.descripcion or tarea.descripcion == 'Creada via wizard':
                tarea.descripcion = info_cat.get('descripcion', '')
        elif not tarea.horas_estimadas:
            tarea.horas_estimadas = 1

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

    # --- PASO 2: Decidir que tareas necesitan distribucion ---
    # Excluir SIEMPRE tareas editadas manualmente (incluso cuando forzar=True).
    # El flag editado_manual es la fuente de verdad: si el usuario editó unidad,
    # cantidad u horas, su input manda por encima de la heurística automática.
    if forzar:
        tareas_a_procesar = [t for t in tareas if not getattr(t, 'editado_manual', False)]
    else:
        tareas_a_procesar = [
            t for t in tareas
            if not getattr(t, 'editado_manual', False)
            and (not t.cantidad_planificada or float(t.cantidad_planificada or 0) == 0)
        ]

    if not tareas_a_procesar:
        db.session.flush()
        return len(tareas)

    # --- PASO 3: Clasificar tareas (fisicas vs administrativas) ---
    _KEYWORDS_NO_CANTIDAD = {
        'gestion', 'gestion', 'permisos', 'habilitacion', 'habilitacion',
        'tramites', 'tramites',
        'plan de seguridad', 'documentacion', 'documentacion',
        'confeccion', 'confeccion', 'checklist', 'manual de usuario',
        'entrega de documentacion', 'despiece por piso',
        'registro fotografico', 'registro fotografico',
        'relevamiento topografico', 'relevamiento topografico',
        'verificacion', 'verificacion',
        'control de calidad', 'control de compactacion', 'control de compactacion',
        'control de deformaciones', 'control de resistencia', 'control de juntas',
        'prueba de', 'pruebas y puesta', 'pruebas de presion',
        'medicion y verificacion', 'medicion y verificacion',
        'inspeccion final', 'inspeccion final', 'revision y retoques', 'revision y retoques',
        'estudio de suelos', 'estudio de nivel',
        'cartel de obra', 'configuracion domotica', 'configuracion domotica',
        'clasificacion de escombros', 'clasificacion de escombros',
    }

    def _tarea_aplica_cantidad(tarea, catalogo_map):
        """Determina si una tarea consume cantidad fisica (m2, ml, etc.)."""
        key = tarea.nombre.lower().strip()
        info_cat = catalogo_map.get(key)
        if info_cat and info_cat.get('aplica_cantidad') is False:
            return False
        for kw in _KEYWORDS_NO_CANTIDAD:
            if kw in key:
                return False
        return True

    tareas_fisicas = [t for t in tareas_a_procesar if _tarea_aplica_cantidad(t, catalogo_map)]
    tareas_admin = [t for t in tareas_a_procesar if not _tarea_aplica_cantidad(t, catalogo_map)]

    # --- PASO 4: Distribucion proporcional ---
    total_horas_todas = sum(float(t.horas_estimadas or 1) for t in tareas_a_procesar)
    if total_horas_todas <= 0:
        total_horas_todas = len(tareas_a_procesar)

    total_horas_fisicas = sum(float(t.horas_estimadas or 1) for t in tareas_fisicas)
    if total_horas_fisicas <= 0:
        total_horas_fisicas = 1

    dias_etapa = 0
    if inicio_etapa and fin_etapa:
        dias_etapa = max(1, (fin_etapa - inicio_etapa).days)

    actualizadas = 0

    HORAS_JORNAL = 8

    fechas_tareas = []
    if inicio_etapa and fin_etapa and dias_etapa > 0:
        dia_actual = 0
        horas_restantes_dia = HORAS_JORNAL

        for tarea in tareas_a_procesar:
            horas_t = float(tarea.horas_estimadas or 1)

            if horas_restantes_dia <= 0:
                dia_actual += 1
                horas_restantes_dia = HORAS_JORNAL

            f_ini = inicio_etapa + timedelta(days=dia_actual)

            if horas_t <= horas_restantes_dia:
                dias_tarea = 0
                horas_restantes_dia -= horas_t
            else:
                horas_pendientes = horas_t - horas_restantes_dia
                dias_extra = int(horas_pendientes // HORAS_JORNAL)
                if horas_pendientes % HORAS_JORNAL > 0:
                    dias_extra += 1
                dias_tarea = dias_extra
                horas_restantes_dia = HORAS_JORNAL - (horas_pendientes % HORAS_JORNAL)
                if horas_restantes_dia == HORAS_JORNAL:
                    horas_restantes_dia = 0

            f_fin = f_ini + timedelta(days=dias_tarea)

            if f_ini > fin_etapa:
                f_ini = fin_etapa
            if f_fin > fin_etapa:
                f_fin = fin_etapa

            fechas_tareas.append((f_ini, f_fin))

            if horas_restantes_dia <= 0:
                dia_actual += dias_tarea + 1
                horas_restantes_dia = HORAS_JORNAL
            else:
                dia_actual += dias_tarea

    for i, tarea in enumerate(tareas_a_procesar):
        horas_tarea = float(tarea.horas_estimadas or 1)
        es_fisica = tarea in tareas_fisicas

        if cantidad_etapa > 0 and es_fisica and unidad_etapa not in ('h', 'dia', 'dia'):
            proporcion_cant = horas_tarea / total_horas_fisicas
            cant = round(cantidad_etapa * proporcion_cant)
            cant = max(1, cant)
            tarea.cantidad_planificada = cant
            tarea.objetivo = cant
            tarea.unidad = unidad_etapa
        else:
            tarea.cantidad_planificada = max(1, round(horas_tarea))
            tarea.objetivo = tarea.cantidad_planificada
            tarea.unidad = 'h'

        if horas_tarea > 0 and float(tarea.cantidad_planificada or 0) > 0 and tarea.unidad not in ('h', 'dia', 'dia', 'gl', 'global'):
            tarea.rendimiento = round(float(tarea.cantidad_planificada) / horas_tarea, 1)
        else:
            tarea.rendimiento = None

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


# === ETAPAS ENCADENADAS -- PROPAGACION DE FECHAS ===

def propagar_fechas_etapas(obra_id, force_cascade=False, skip_etapa_id=None):
    """Propaga fechas entre etapas usando dependencias y niveles."""
    from services.dependency_service import propagar_fechas_obra
    from datetime import timedelta

    etapas_modificadas = propagar_fechas_obra(
        obra_id, force_cascade=force_cascade, skip_etapa_id=skip_etapa_id
    )

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
    """Desplaza fechas de tareas no completadas de una etapa por delta dias."""
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
    "m2": "m2", "m\u00b2": "m2", "M2": "m2", "metro2": "m2",
    "m3": "m3", "m\u00b3": "m3", "M3": "m3", "metro3": "m3",
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


def parse_date(s):
    """Parsea fechas en multiples formatos."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


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


# Import sub-modules to register routes
from obras import core, tareas, materiales, certificaciones, etapas, wizard, remitos, equipos, escalas, admin
