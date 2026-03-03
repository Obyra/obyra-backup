"""Blueprint de Fichadas — ingreso/egreso con geolocalización"""

import json as _json
import math
import os
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, date, timedelta
from flask import (Blueprint, render_template, request, jsonify,
                   flash, redirect, url_for, current_app)
from flask_login import login_required, current_user
from extensions import db, csrf
from models import Obra, ObraMiembro, AsignacionObra, Fichada, Usuario

fichadas_bp = Blueprint('fichadas', __name__, url_prefix='/fichadas')


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def calcular_distancia_metros(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos coordenadas GPS (Haversine)."""
    R = 6_371_000  # Radio de la Tierra en metros
    rad = math.radians
    dlat = rad(lat2 - lat1)
    dlon = rad(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rad(lat1)) * math.cos(rad(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _es_admin(usuario):
    """Verifica si el usuario es admin o super_admin."""
    if getattr(usuario, 'is_super_admin', False):
        return True
    rol = getattr(usuario, 'role', '') or getattr(usuario, 'rol', '') or ''
    return rol.lower() in ('admin', 'administrador')


def _geocodificar_direccion(direccion):
    """Geocodifica una dirección. Usa Google Geocoding API si hay key, sino Nominatim."""
    if not direccion:
        return None, None

    google_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')

    # Intentar con Google Maps Geocoding API primero (más preciso)
    if google_key:
        try:
            url = 'https://maps.googleapis.com/maps/api/geocode/json?' + urllib.parse.urlencode({
                'address': direccion, 'key': google_key
            })
            req = urllib.request.Request(url, headers={'User-Agent': 'OBYRA/1.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = _json.loads(response.read())
                if data.get('status') == 'OK' and data.get('results'):
                    loc = data['results'][0]['geometry']['location']
                    return float(loc['lat']), float(loc['lng'])
        except Exception:
            pass

    # Fallback: Nominatim (OpenStreetMap)
    try:
        url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode({
            'q': direccion, 'format': 'json', 'limit': 1
        })
        req = urllib.request.Request(url, headers={'User-Agent': 'OBYRA/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = _json.loads(response.read())
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
    except Exception:
        pass

    return None, None


def _obras_asignadas(usuario):
    """Devuelve las obras activas asignadas al usuario.

    Admin/super_admin ven todas las obras activas de su organización.
    Operarios/PMs solo ven las obras donde están asignados.
    """
    org_id = getattr(usuario, 'organizacion_id', None)
    if not org_id:
        return []

    # Admin/super_admin: todas las obras activas de la organización
    if _es_admin(usuario):
        return (Obra.query
                .filter(Obra.organizacion_id == org_id,
                        Obra.estado.in_(['en_curso', 'planificacion']))
                .order_by(Obra.nombre)
                .all())

    # Buscar por ObraMiembro
    obra_ids = {m.obra_id for m in
                ObraMiembro.query.filter_by(usuario_id=usuario.id).all()}

    # También buscar por AsignacionObra
    obra_ids |= {a.obra_id for a in
                 AsignacionObra.query.filter_by(
                     usuario_id=usuario.id, activo=True).all()}

    if not obra_ids:
        return []

    return (Obra.query
            .filter(Obra.id.in_(obra_ids),
                    Obra.organizacion_id == org_id,
                    Obra.estado.in_(['en_curso', 'planificacion']))
            .order_by(Obra.nombre)
            .all())


def _ultima_fichada_hoy(usuario_id, obra_id):
    """Última fichada del día del usuario en una obra."""
    hoy = date.today()
    return (Fichada.query
            .filter(Fichada.usuario_id == usuario_id,
                    Fichada.obra_id == obra_id,
                    db.func.date(Fichada.fecha_hora) == hoy)
            .order_by(Fichada.fecha_hora.desc())
            .first())


def _fichadas_hoy(usuario_id, obra_id):
    """Todas las fichadas de hoy del usuario en una obra."""
    hoy = date.today()
    return (Fichada.query
            .filter(Fichada.usuario_id == usuario_id,
                    Fichada.obra_id == obra_id,
                    db.func.date(Fichada.fecha_hora) == hoy)
            .order_by(Fichada.fecha_hora.asc())
            .all())


def _calcular_horas_dia(fichadas_lista):
    """Calcula horas trabajadas de una lista de fichadas del mismo día.

    Empareja ingreso→egreso y suma las duraciones.
    Returns: (total_segundos, pares, en_obra)
      - total_segundos: int, total de segundos trabajados
      - pares: list of (ingreso_fichada, egreso_fichada, duracion_timedelta)
      - en_obra: bool, True si la última fichada es ingreso (aún en obra)
    """
    fichadas_ord = sorted(fichadas_lista, key=lambda f: f.fecha_hora)
    pares = []
    total_seg = 0
    en_obra = False

    i = 0
    while i < len(fichadas_ord):
        f = fichadas_ord[i]
        if f.tipo == 'ingreso':
            # Buscar el siguiente egreso
            egreso = None
            for j in range(i + 1, len(fichadas_ord)):
                if fichadas_ord[j].tipo == 'egreso':
                    egreso = fichadas_ord[j]
                    i = j + 1
                    break
            if egreso:
                dur = egreso.fecha_hora - f.fecha_hora
                pares.append((f, egreso, dur))
                total_seg += int(dur.total_seconds())
            else:
                # Ingreso sin egreso: aún en obra
                en_obra = True
                i += 1
        else:
            # Egreso suelto (sin ingreso previo), ignorar
            i += 1

    return total_seg, pares, en_obra


def _formatear_horas(total_segundos):
    """Formatea segundos a 'Xh Ym'."""
    horas = total_segundos // 3600
    minutos = (total_segundos % 3600) // 60
    if horas > 0:
        return f'{horas}h {minutos:02d}m'
    return f'{minutos}m'


def calcular_resumen_horas(obra_id, desde=None, hasta=None, usuario_id=None):
    """Calcula resumen de horas trabajadas por operario en una obra.

    Returns: list of dicts, one per user:
      [{
        'usuario': Usuario,
        'dias': [{
            'fecha': date,
            'horas_str': '8h 30m',
            'total_segundos': 30600,
            'pares': [...],
            'en_obra': False,
        }],
        'total_segundos': int,
        'total_horas_str': '42h 15m',
      }]
    """
    query = (Fichada.query
             .filter(Fichada.obra_id == obra_id)
             .order_by(Fichada.fecha_hora.asc()))

    if usuario_id:
        query = query.filter(Fichada.usuario_id == usuario_id)
    if desde:
        if isinstance(desde, str):
            desde = datetime.strptime(desde, '%Y-%m-%d').date()
        query = query.filter(db.func.date(Fichada.fecha_hora) >= desde)
    if hasta:
        if isinstance(hasta, str):
            hasta = datetime.strptime(hasta, '%Y-%m-%d').date()
        query = query.filter(db.func.date(Fichada.fecha_hora) <= hasta)

    fichadas = query.all()
    if not fichadas:
        return []

    # Agrupar por usuario y fecha
    por_usuario = defaultdict(lambda: defaultdict(list))
    for f in fichadas:
        dia = f.fecha_hora.date()
        por_usuario[f.usuario_id][dia].append(f)

    resultado = []
    for uid, dias_dict in por_usuario.items():
        usuario = Usuario.query.get(uid)
        if not usuario:
            continue
        dias = []
        total_seg_usuario = 0
        for dia in sorted(dias_dict.keys()):
            seg, pares, en_obra = _calcular_horas_dia(dias_dict[dia])
            total_seg_usuario += seg
            dias.append({
                'fecha': dia,
                'horas_str': _formatear_horas(seg) if seg > 0 else ('En obra' if en_obra else '0m'),
                'total_segundos': seg,
                'pares': pares,
                'en_obra': en_obra,
            })
        resultado.append({
            'usuario': usuario,
            'dias': dias,
            'total_segundos': total_seg_usuario,
            'total_horas_str': _formatear_horas(total_seg_usuario),
        })

    # Ordenar por total de horas descendente
    resultado.sort(key=lambda r: r['total_segundos'], reverse=True)
    return resultado


# ---------------------------------------------------------------------------
# Rutas de vista
# ---------------------------------------------------------------------------

@fichadas_bp.route('/')
@login_required
def index():
    """Página principal: muestra obras asignadas con estado de fichada."""
    obras = _obras_asignadas(current_user)
    obras_info = []
    for obra in obras:
        ultima = _ultima_fichada_hoy(current_user.id, obra.id)
        proximo_tipo = 'ingreso'
        if ultima and ultima.tipo == 'ingreso':
            proximo_tipo = 'egreso'
        obras_info.append({
            'obra': obra,
            'ultima_fichada': ultima,
            'proximo_tipo': proximo_tipo,
        })
    return render_template('fichadas/index.html', obras_info=obras_info)


@fichadas_bp.route('/fichar/<int:obra_id>')
@login_required
def fichar(obra_id):
    """Página mobile-first para fichar ingreso/egreso."""
    obra = Obra.query.get_or_404(obra_id)

    # Verificar que el usuario está asignado (admin/super_admin acceden a todas)
    if not _es_admin(current_user):
        es_miembro = (ObraMiembro.query.filter_by(
                          obra_id=obra_id, usuario_id=current_user.id).first()
                      or AsignacionObra.query.filter_by(
                          obra_id=obra_id, usuario_id=current_user.id,
                          activo=True).first())
        if not es_miembro:
            flash('No estás asignado a esta obra.', 'danger')
            return redirect(url_for('fichadas.index'))

    # Auto-geocodificar si la obra tiene dirección pero no coordenadas
    if not obra.latitud and obra.direccion:
        lat, lng = _geocodificar_direccion(obra.direccion)
        if lat and lng:
            obra.latitud = lat
            obra.longitud = lng
            try:
                db.session.commit()
                current_app.logger.info(
                    f'Obra {obra.id} geocodificada: {lat}, {lng}')
            except Exception:
                db.session.rollback()

    ultima = _ultima_fichada_hoy(current_user.id, obra_id)
    proximo_tipo = 'ingreso'
    if ultima and ultima.tipo == 'ingreso':
        proximo_tipo = 'egreso'

    fichadas_del_dia = _fichadas_hoy(current_user.id, obra_id)

    # Calcular horas trabajadas hoy
    horas_hoy = None
    if fichadas_del_dia:
        seg, _, en_obra = _calcular_horas_dia(fichadas_del_dia)
        if seg > 0:
            horas_hoy = _formatear_horas(seg)
        elif en_obra:
            horas_hoy = 'En obra'

    return render_template('fichadas/fichar.html',
                           obra=obra,
                           proximo_tipo=proximo_tipo,
                           fichadas_del_dia=fichadas_del_dia,
                           horas_hoy=horas_hoy,
                           es_admin=_es_admin(current_user),
                           google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@fichadas_bp.route('/api/fichar', methods=['POST'])
@csrf.exempt
@login_required
def api_fichar():
    """Registra una fichada de ingreso o egreso."""
    data = request.get_json(silent=True) or {}

    obra_id = data.get('obra_id')
    tipo = data.get('tipo')  # 'ingreso' o 'egreso'
    lat = data.get('latitud')
    lng = data.get('longitud')
    precision = data.get('precision_gps')

    if not obra_id or tipo not in ('ingreso', 'egreso'):
        return jsonify({'ok': False, 'error': 'Datos incompletos'}), 400

    obra = Obra.query.get(obra_id)
    if not obra:
        return jsonify({'ok': False, 'error': 'Obra no encontrada'}), 404

    # Verificar asignación (admin/super_admin acceden a todas)
    if not _es_admin(current_user):
        es_miembro = (ObraMiembro.query.filter_by(
                          obra_id=obra_id, usuario_id=current_user.id).first()
                      or AsignacionObra.query.filter_by(
                          obra_id=obra_id, usuario_id=current_user.id,
                          activo=True).first())
        if not es_miembro:
            return jsonify({'ok': False, 'error': 'No estás asignado a esta obra'}), 403

    # Calcular distancia si hay coordenadas de ambos
    distancia = None
    dentro_rango = False
    radio = obra.radio_fichada_metros or 100
    es_admin = _es_admin(current_user)

    tiene_gps = lat is not None and lng is not None
    tiene_coords_obra = obra.latitud is not None and obra.longitud is not None

    if not tiene_gps:
        if not es_admin:
            return jsonify({'ok': False, 'error': 'No se pudo obtener tu ubicación GPS. Habilitá la geolocalización en tu navegador.'}), 400
        # Admin sin GPS: permitir fichar sin validación de distancia
    elif not tiene_coords_obra:
        if not es_admin:
            return jsonify({'ok': False, 'error': 'La obra no tiene coordenadas configuradas. Contactá al administrador.'}), 400
        # Admin con GPS pero obra sin coords: permitir fichar
    else:
        # Ambos tienen coordenadas: calcular distancia
        distancia = calcular_distancia_metros(
            float(lat), float(lng),
            float(obra.latitud), float(obra.longitud))
        dentro_rango = distancia <= radio

        # Operarios: deben estar dentro del rango. Admins: pueden fichar desde cualquier lugar.
        if not dentro_rango and not es_admin:
            return jsonify({
                'ok': False,
                'error': f'Estás a {round(distancia)}m de la obra. Necesitás estar dentro de {radio}m para fichar.',
                'distancia_metros': round(distancia, 1),
                'radio_metros': radio,
            }), 403

    # Para admins fuera de rango, marcar dentro_rango como False pero permitir
    if es_admin and distancia is not None and not dentro_rango:
        dentro_rango = False

    fichada = Fichada(
        usuario_id=current_user.id,
        obra_id=obra_id,
        tipo=tipo,
        fecha_hora=datetime.utcnow(),
        latitud=lat,
        longitud=lng,
        precision_gps=precision,
        distancia_obra=round(distancia, 2) if distancia is not None else None,
        dentro_rango=dentro_rango,
        ip_address=request.remote_addr,
        user_agent=str(request.user_agent)[:300],
    )
    db.session.add(fichada)
    db.session.commit()

    return jsonify({
        'ok': True,
        'fichada': {
            'id': fichada.id,
            'tipo': fichada.tipo,
            'fecha_hora': fichada.fecha_hora.strftime('%H:%M:%S'),
            'distancia_metros': round(distancia, 1) if distancia is not None else None,
            'dentro_rango': dentro_rango,
            'radio_metros': radio,
        }
    })


@fichadas_bp.route('/api/guardar_coords', methods=['POST'])
@csrf.exempt
@login_required
def api_guardar_coords():
    """Guarda coordenadas geocodificadas de una obra (solo admins)."""
    if not _es_admin(current_user):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    data = request.get_json(silent=True) or {}
    obra_id = data.get('obra_id')
    lat = data.get('latitud')
    lng = data.get('longitud')

    if not obra_id or lat is None or lng is None:
        return jsonify({'ok': False, 'error': 'Datos incompletos'}), 400

    obra = Obra.query.get(obra_id)
    if not obra:
        return jsonify({'ok': False, 'error': 'Obra no encontrada'}), 404

    # Solo guardar si la obra no tiene coords todavía
    if not obra.latitud:
        obra.latitud = float(lat)
        obra.longitud = float(lng)
        db.session.commit()

    return jsonify({'ok': True})


@fichadas_bp.route('/api/estado/<int:obra_id>')
@login_required
def api_estado(obra_id):
    """Estado actual de fichada del usuario en una obra."""
    ultima = _ultima_fichada_hoy(current_user.id, obra_id)
    proximo = 'ingreso'
    if ultima and ultima.tipo == 'ingreso':
        proximo = 'egreso'
    return jsonify({
        'ok': True,
        'proximo_tipo': proximo,
        'ultima': {
            'tipo': ultima.tipo,
            'hora': ultima.fecha_hora.strftime('%H:%M'),
            'dentro_rango': ultima.dentro_rango,
        } if ultima else None
    })


@fichadas_bp.route('/historial')
@login_required
def historial():
    """Historial de fichadas (PM/Admin ven todos, operarios solo las suyas)."""
    from services.permissions import ROLE_HIERARCHY
    roles = {getattr(current_user, 'rol', ''), getattr(current_user, 'role', '')}
    es_admin_o_pm = any(ROLE_HIERARCHY.get(r, 0) >= 4 for r in roles if r)

    org_id = getattr(current_user, 'organizacion_id', None)

    # Filtros
    obra_id = request.args.get('obra_id', type=int)
    usuario_id = request.args.get('usuario_id', type=int)
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    page = request.args.get('page', 1, type=int)

    query = (Fichada.query
             .join(Obra, Fichada.obra_id == Obra.id)
             .filter(Obra.organizacion_id == org_id))

    if not es_admin_o_pm:
        query = query.filter(Fichada.usuario_id == current_user.id)
    elif usuario_id:
        query = query.filter(Fichada.usuario_id == usuario_id)

    if obra_id:
        query = query.filter(Fichada.obra_id == obra_id)
    if fecha_desde:
        query = query.filter(Fichada.fecha_hora >= fecha_desde)
    if fecha_hasta:
        query = query.filter(Fichada.fecha_hora <= fecha_hasta + ' 23:59:59')

    fichadas = (query
                .order_by(Fichada.fecha_hora.desc())
                .paginate(page=page, per_page=50, error_out=False))

    # Datos para filtros
    obras = (Obra.query
             .filter_by(organizacion_id=org_id)
             .order_by(Obra.nombre).all()) if es_admin_o_pm else _obras_asignadas(current_user)

    usuarios = []
    if es_admin_o_pm:
        usuarios = (Usuario.query
                    .filter_by(organizacion_id=org_id, activo=True)
                    .order_by(Usuario.nombre).all())

    # Calcular resumen de horas si hay filtro de obra
    resumen_horas = []
    if obra_id:
        resumen_horas = calcular_resumen_horas(
            obra_id, desde=fecha_desde, hasta=fecha_hasta,
            usuario_id=usuario_id if not es_admin_o_pm else usuario_id)

    return render_template('fichadas/historial.html',
                           fichadas=fichadas,
                           obras=obras,
                           usuarios=usuarios,
                           es_admin_o_pm=es_admin_o_pm,
                           resumen_horas=resumen_horas,
                           filtros={
                               'obra_id': obra_id,
                               'usuario_id': usuario_id,
                               'fecha_desde': fecha_desde,
                               'fecha_hasta': fecha_hasta,
                           })
