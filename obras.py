from flask import (
    Blueprint, render_template, request, flash, redirect,
    url_for, jsonify, current_app, abort
)
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import json
import logging
import requests
from app import db
from sqlalchemy import text, func, and_, or_
from sqlalchemy.exc import ProgrammingError
from models import (
    Obra,
    EtapaObra,
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
)
from etapas_predefinidas import obtener_etapas_disponibles, crear_etapas_para_obra
from tareas_predefinidas import (
    TAREAS_POR_ETAPA,
    obtener_tareas_por_etapa,
    slugify_nombre_etapa,
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

obras_bp = Blueprint('obras', __name__)

_COORD_PRECISION = Decimal('0.00000001')

# === Helpers generales ===

def _user_role():
    """Devuelve el rol del usuario actual tolerando 'role' y 'rol'."""
    return getattr(current_user, 'role', None) or getattr(current_user, 'rol', '') or ''

def is_admin():
    """Admin global."""
    return _user_role() in ('admin', 'administrador', 'superadmin')

def is_pm_global():
    """Admin o PM global."""
    return _user_role() in ('admin', 'pm', 'administrador', 'project_manager', 'tecnico')

def _to_coord_decimal(value):
    """Normaliza coordenadas geográficas a Decimal con 8 decimales."""
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(_COORD_PRECISION)
    except (InvalidOperation, ValueError, TypeError):
        return None

def _parse_date(value):
    if not value:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None

# Mantener compat
parse_date = _parse_date

# === Error handlers JSON-friendly ===

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

# === Helpers de permisos ===

def can_manage_obra(obra):
    """Puede gestionar la obra (crear/editar/elim etapas y tareas)."""
    if is_admin() or is_pm_global():
        return True
    miembro = ObraMiembro.query.filter_by(
        obra_id=obra.id, usuario_id=current_user.id, rol_en_obra='pm'
    ).first()
    return miembro is not None

def can_log_avance(tarea):
    """Puede registrar avances en una tarea."""
    if is_admin() or _user_role() in ('pm', 'tecnico', 'administrador'):
        return True
    if tarea.responsable_id == current_user.id:
        return True
    miembro = TareaMiembro.query.filter_by(
        tarea_id=tarea.id, user_id=current_user.id
    ).first()
    return miembro is not None

def es_miembro_obra(obra_id, user_id):
    """Verificar si el usuario es miembro de la obra (cualquier rol)."""
    if is_pm_global():
        return True
    miembro = db.session.query(ObraMiembro.id).filter_by(
        obra_id=obra_id, usuario_id=user_id
    ).first()
    if miembro:
        return True
    tiene_tareas = (
        db.session.query(TareaMiembro.id)
        .join(TareaEtapa, TareaMiembro.tarea_id == TareaEtapa.id)
        .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
        .filter(EtapaObra.obra_id == obra_id, TareaMiembro.user_id == user_id)
        .first()
    )
    return tiene_tareas is not None

def resumen_tarea(t):
    """Calcular métricas de una tarea a prueba de nulos."""
    plan = float(t.cantidad_planificada or 0)
    ejec = float(
        db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
        .filter(TareaAvance.tarea_id == t.id, TareaAvance.status == 'aprobado')
        .scalar() or 0
    )
    pct = (ejec / plan * 100.0) if plan > 0 else 0.0
    restante = max(plan - ejec, 0.0)
    atrasada = bool(t.fecha_fin_plan and date.today() > t.fecha_fin_plan and restante > 0)
    return {'plan': plan, 'ejec': ejec, 'pct': pct, 'restante': restante, 'atrasada': atrasada}

def D(x):
    if x is None:
        return Decimal('0')
    return x if isinstance(x, Decimal) else Decimal(str(x))

def seed_tareas_para_etapa(nueva_etapa, auto_commit=True, slug=None):
    """Idempotente: crea tareas predefinidas en una etapa."""
    try:
        slug_normalizado = slugify_nombre_etapa(slug or nueva_etapa.nombre)
        tareas = obtener_tareas_por_etapa(nueva_etapa.nombre, slug_normalizado)
        tareas_creadas = 0
        for t in tareas:
            if isinstance(t, str):
                nombre_tarea, descripcion_tarea, horas_tarea = t, "", 0
            elif isinstance(t, dict):
                nombre_tarea = t.get("nombre", "")
                descripcion_tarea = t.get("descripcion", "")
                horas_tarea = t.get("horas", 0)
            else:
                current_app.logger.warning("Formato de tarea no reconocido: %r", t)
                continue
            if not nombre_tarea:
                continue
            ya = TareaEtapa.query.filter_by(etapa_id=nueva_etapa.id, nombre=nombre_tarea).first()
            if ya:
                continue
            nueva_tarea = TareaEtapa(
                etapa_id=nueva_etapa.id,
                nombre=nombre_tarea,
                descripcion=descripcion_tarea,
                horas_estimadas=horas_tarea,
                estado="pendiente"
            )
            db.session.add(nueva_tarea)
            tareas_creadas += 1
        if auto_commit:
            db.session.commit()
        return tareas_creadas
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("ERROR en seed_tareas_para_etapa: %s", e)
        return 0

# === Rutas ===

@obras_bp.route('/')
@login_required
def lista():
    # Operarios pueden acceder para ver sus obras asignadas
    if not current_user.puede_acceder_modulo('obras') and _user_role() != 'operario':
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    estado = request.args.get('estado', '')
    buscar = (request.args.get('buscar', '') or '').strip()

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)

    chequear_admin = getattr(current_user, 'tiene_rol', None)
    puede_ver_borradores = bool(callable(chequear_admin) and current_user.tiene_rol('admin'))
    if not puede_ver_borradores:
        puede_ver_borradores = _user_role() in ['administrador', 'admin']

    mostrar_borradores = puede_ver_borradores and request.args.get('mostrar_borradores') == '1'

    obras = []
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

        obras = query.order_by(Obra.fecha_creacion.desc()).all()

        geocoded = False
        for obra in obras:
            if (obra.latitud is not None and obra.longitud is not None) or not obra.direccion:
                continue
            status = (obra.geocode_status or '').lower()
            if status == 'fail':
                continue
            try:
                resolved = resolve_geocode(obra.direccion)
            except Exception as exc:
                current_app.logger.warning(
                    'No se pudo geocodificar la obra %s (%s): %s', obra.id, obra.direccion, exc
                )
                obra.geocode_status = 'fail'
                geocoded = True
                continue
            if not resolved:
                obra.geocode_status = 'fail'
                geocoded = True
                continue

            lat_decimal = _to_coord_decimal(resolved.get('lat'))
            lng_decimal = _to_coord_decimal(resolved.get('lng'))
            if lat_decimal is not None and lng_decimal is not None:
                obra.latitud = lat_decimal
                obra.longitud = lng_decimal

            obra.direccion_normalizada = resolved.get('normalized') or obra.direccion_normalizada
            obra.geocode_place_id = resolved.get('place_id') or obra.geocode_place_id
            obra.geocode_provider = resolved.get('provider') or obra.geocode_provider
            obra.geocode_status = resolved.get('status') or 'ok'
            raw_payload = resolved.get('raw')
            if raw_payload:
                try:
                    obra.geocode_raw = json.dumps(raw_payload)
                except (TypeError, ValueError):
                    current_app.logger.debug('No se pudo serializar geocode_raw para la obra %s', obra.id)
            obra.geocode_actualizado = datetime.utcnow()
            geocoded = True

        if geocoded:
            try:
                db.session.commit()
            except Exception as exc:
                current_app.logger.warning('No se pudieron guardar las coordenadas de obras: %s', exc)
                db.session.rollback()
    else:
        flash('Selecciona una organización para ver tus obras.', 'warning')

    return render_template(
        'obras/lista.html',
        obras=obras,
        estado=estado,
        buscar=buscar,
        mostrar_borradores=mostrar_borradores,
        puede_ver_borradores=puede_ver_borradores,
    )

@obras_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    if not current_user.puede_acceder_modulo('obras'):
        flash('No tienes permisos para crear obras.', 'danger')
        return redirect(url_for('obras.lista'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')  # FIX: antes no estaba definido
        direccion = request.form.get('direccion')
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
                latitud = geocode_payload.get('lat')
                longitud = geocode_payload.get('lng')

        nueva_obra = Obra(
            nombre=nombre,
            descripcion=descripcion,
            direccion=direccion,
            direccion_normalizada=direccion_normalizada,
            latitud=latitud,
            longitud=longitud,
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
            flash(f'Obra "{nombre}" creada exitosamente.', 'success')
            return redirect(url_for('obras.detalle', id=nueva_obra.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear la obra: {str(e)}', 'danger')
            current_app.logger.exception("Error creating obra")
    
    return render_template('obras/crear.html')

@obras_bp.route('/<int:id>')
@login_required
def detalle(id):
    # Operarios pueden acceder si son miembros de la obra
    if not current_user.puede_acceder_modulo('obras') and _user_role() != 'operario':
        flash('No tienes permisos para ver obras.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    if _user_role() == 'operario' and not es_miembro_obra(id, current_user.id):
        flash('No tienes permisos para ver esta obra.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        abort(404)

    obra = Obra.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
    if not obra_tiene_presupuesto_confirmado(obra):
        abort(404)

    etapas = obra.etapas.order_by(EtapaObra.orden).all()
    asignaciones = obra.asignaciones.filter_by(activo=True).all()
    usuarios_disponibles = Usuario.query.filter_by(activo=True, organizacion_id=org_id).all()
    etapas_disponibles = obtener_etapas_disponibles()
    
    miembros = (ObraMiembro.query
                .filter_by(obra_id=obra.id)
                .join(Usuario, ObraMiembro.usuario_id == Usuario.id)
                .order_by(Usuario.nombre.asc())
                .all())
    
    responsables_query = (ObraMiembro.query
                         .filter_by(obra_id=obra.id)
                         .join(Usuario)
                         .all())
    
    responsables = [
        {
            'usuario': {
                'id': r.usuario.id,
                'nombre_completo': r.usuario.nombre_completo,
                'rol': _user_role()
            },
            'rol_en_obra': r.rol_en_obra
        }
        for r in responsables_query
    ]

    cert_resumen = certification_totals(obra)
    cert_recientes = (
        obra.work_certifications.filter_by(estado='aprobada')
        .order_by(WorkCertification.approved_at.desc().nullslast(), WorkCertification.created_at.desc())
        .limit(3)
        .all()
    )

    return render_template(
        'obras/detalle.html',
        obra=obra,
        etapas=etapas,
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
        wizard_budget_flag=current_app.config.get('WIZARD_BUDGET_BREAKDOWN_ENABLED', False),
        wizard_budget_shadow=current_app.config.get('WIZARD_BUDGET_SHADOW_MODE', False)
    )

@obras_bp.route('/<int:id>/editar', methods=['POST'])
@login_required
def editar(id):
    if _user_role() not in ['administrador', 'tecnico', 'admin']:
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
    obra.progreso = int(request.form.get('progreso', obra.progreso or 0))
    
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
        current_app.logger.warning("Error geolocalizando %s: %s", direccion, e)
    return None

@obras_bp.route('/<int:id>/agregar_etapas', methods=['POST'])
@login_required
def agregar_etapas(id):
    if _user_role() not in ['administrador', 'tecnico', 'admin']:
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
                nombre = (etapa_data.get('nombre') or '').strip()
                descripcion = (etapa_data.get('descripcion') or '').strip()
                orden = int(etapa_data.get('orden') or 1)
                if not nombre:
                    continue
                existe = EtapaObra.query.filter_by(obra_id=obra.id, nombre=nombre).first()
                if existe:
                    continue
                nueva_etapa = EtapaObra(
                    obra_id=obra.id, nombre=nombre, descripcion=descripcion,
                    orden=orden, estado='pendiente'
                )
                db.session.add(nueva_etapa)
                db.session.flush()
                slug_normalizado = slugify_nombre_etapa(nombre)
                seed_tareas_para_etapa(nueva_etapa, slug=slug_normalizado)
                tareas_adicionales = etapa_data.get('tareas', [])
                for tarea_data in tareas_adicionales:
                    nombre_tarea = (tarea_data.get('nombre') or '').strip()
                    if nombre_tarea:
                        db.session.add(TareaEtapa(
                            etapa_id=nueva_etapa.id,
                            nombre=nombre_tarea,
                            descripcion=f"Tarea personalizada para {nombre}",
                            estado='pendiente'
                        ))
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
    """Asignar usuarios a obra - soporta formulario y AJAX."""
    if _user_role() not in ('admin', 'administrador'):
        flash('Solo administradores pueden asignar usuarios', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    # Detección AJAX robusta
    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        'application/json' in (request.headers.get('Content-Type') or '') or
        request.is_json
    )
    try:
        user_ids = request.form.getlist('user_ids[]')
        if not user_ids:
            uid = request.form.get('usuario_id')
            if uid:
                user_ids = [uid]
        if not user_ids:
            if is_ajax:
                return jsonify({"ok": False, "error": "Seleccioná al menos un usuario"}), 400
            flash('Seleccioná al menos un usuario', 'danger')
            return redirect(url_for('obras.detalle', id=obra_id))

        usuarios = Usuario.query.filter(Usuario.id.in_(user_ids)).all()
        if not usuarios:
            if is_ajax:
                return jsonify({"ok": False, "error": "Usuarios inválidos"}), 400
            flash('Usuarios inválidos', 'danger')
            return redirect(url_for('obras.detalle', id=obra_id))

        rol_en_obra = request.form.get('rol') or 'operario'
        etapa_id = request.form.get('etapa_id') or None
        
        creados = 0
        ya_existian = 0
        for uid in user_ids:
            try:
                result = db.session.execute(
                    text("""
                    INSERT INTO obra_miembros (obra_id, usuario_id, rol_en_obra, etapa_id)
                    VALUES (:o, :u, :rol, :etapa)
                    ON CONFLICT (obra_id, usuario_id) DO NOTHING
                    """),
                    {"o": obra_id, "u": int(uid), "rol": rol_en_obra, "etapa": etapa_id}
                )
                if getattr(result, "rowcount", 0) == 0:
                    ya_existian += 1
                else:
                    creados += 1
            except Exception:
                current_app.logger.exception("Error inserting user %s", uid)
                db.session.rollback()
                if is_ajax:
                    return jsonify({"ok": False, "error": "Error asignando usuario"}), 500
                flash('Error asignando usuario', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))
        db.session.commit()
        if is_ajax:
            return jsonify({"ok": True, "creados": creados, "ya_existian": ya_existian})
        if creados > 0:
            flash(f'✅ Se asignaron {creados} usuarios a la obra', 'success')
        if ya_existian > 0:
            flash(f'ℹ️ {ya_existian} usuarios ya estaban asignados', 'info')
        return redirect(url_for('obras.detalle', id=obra_id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("obra_miembros insert error obra_id=%s", obra_id)
        if is_ajax:
            if isinstance(e, ProgrammingError):
                return jsonify({"ok": False, "error": "Error de esquema de base de datos"}), 500
            return jsonify({"ok": False, "error": f"Error interno: {str(e)}"}), 500
        flash(f'Error al asignar usuarios: {str(e)}', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

@obras_bp.route('/<int:id>/etapa', methods=['POST'])
@login_required
def agregar_etapa(id):
    if _user_role() not in ['administrador', 'tecnico', 'admin']:
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
        obra_id=id, nombre=nombre, descripcion=descripcion, orden=ultimo_orden + 1
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
        sugeridas = request.form.getlist("sugeridas[]")

        if not etapa_id:
            return jsonify(ok=False, error="Falta el ID de etapa"), 400

        etapa = EtapaObra.query.get_or_404(etapa_id)
        if etapa.obra.organizacion_id != current_user.organizacion_id:
            return jsonify(ok=False, error="Sin permisos"), 403

        if not sugeridas:
            nombre = (request.form.get("nombre") or "").strip()
            if not nombre:
                return jsonify(ok=False, error="Falta el nombre"), 400
            VALID_UNITS = {'m2', 'ml', 'm3', 'un', 'h', 'kg'}
            unidad_input = (request.form.get("unidad") or "un").lower()
            unidad = unidad_input if unidad_input in VALID_UNITS else "un"
            t = TareaEtapa(
                etapa_id=etapa_id,
                nombre=nombre,
                responsable_id=resp_id,
                horas_estimadas=horas,
                fecha_inicio_plan=fi,
                fecha_fin_plan=ff,
                unidad=unidad
            )
            db.session.add(t)
            db.session.commit()
            return jsonify(ok=True, created=1)

        created = 0
        tareas_disponibles = TAREAS_POR_ETAPA.get(etapa.nombre, [])
        for sid in sugeridas:
            try:
                index = int(sid)
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
                    unidad=tarea_unidad
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
        current_app.logger.exception("Error en crear_tareas: %s", e)
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

def normalize_unit(unit):
    UNIT_MAP = {
        "m2": "m2", "m²": "m2", "M2": "m2", "metro2": "m2",
        "m3": "m3", "m³": "m3", "M3": "m3", "metro3": "m3", 
        "ml": "ml", "m": "ml", "metro": "ml",
        "u": "un", "un": "un", "unidad": "un", "uni": "un", "unidades": "un",
        "kg": "kg", "kilo": "kg", "kilos": "kg",
        "h": "h", "hr": "h", "hora": "h", "horas": "h", "hs": "h",
        "lt": "lt", "l": "lt", "lts": "lt", "litro": "lt", "litros": "lt"
    }
    if not unit or not str(unit).strip():
        return "un"
    unit_clean = str(unit).strip().lower()
    return UNIT_MAP.get(unit_clean, unit_clean)

@obras_bp.route("/tareas/<int:tarea_id>/avances", methods=['POST'])
@login_required
def crear_avance(tarea_id):
    from werkzeug.utils import secure_filename
    from pathlib import Path
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    role = _user_role()
    if role not in ["admin", "pm", "operario", "tecnico", "administrador"]:
        return jsonify(ok=False, error="Solo operarios pueden registrar avances"), 403
    if role == "operario":
        is_responsible = tarea.responsable_id == current_user.id
        is_assigned = TareaMiembro.query.filter_by(tarea_id=tarea.id, user_id=current_user.id).first()
        if not (is_responsible or is_assigned):
            return jsonify(ok=False, error="No estás asignado a esta tarea"), 403
    if not can_log_avance(tarea):
        return jsonify(ok=False, error="Sin permisos para registrar avances en esta tarea"), 403
    
    cantidad_str = str(request.form.get("cantidad", "")).replace(",", ".")
    try:
        cantidad = float(cantidad_str)
        if cantidad <= 0:
            return jsonify(ok=False, error="La cantidad debe ser mayor a 0"), 400
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Cantidad inválida"), 400
    
    unidad = normalize_unit(tarea.unidad)
    horas = request.form.get("horas", type=float)
    notas = request.form.get("notas", "")

    try:
        av = TareaAvance(
            tarea_id=tarea.id, 
            user_id=current_user.id, 
            cantidad=cantidad,
            unidad=unidad,
            horas=horas,
            notas=notas,
            cantidad_ingresada=cantidad,
            unidad_ingresada=unidad
        )
        if role in ("admin", "pm", "tecnico", "administrador"):
            av.status = "aprobado"
            av.confirmed_by = current_user.id
            av.confirmed_at = datetime.utcnow()
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

        db.session.commit()
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error en crear_avance: %s", e)
        return jsonify(ok=False, error="Error interno"), 500

@obras_bp.route("/api/tareas/<int:tarea_id>/avances", methods=['POST'])
@login_required
def api_crear_avance_fotos(tarea_id):
    from werkzeug.utils import secure_filename
    from pathlib import Path
    import uuid
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    if not can_log_avance(tarea):
        return jsonify(ok=False, error="Sin permisos para registrar avance en esta tarea"), 403
    
    if _user_role() == 'operario':
        from_dashboard = request.headers.get('X-From-Dashboard') == '1'
        if not from_dashboard:
            return jsonify(ok=False, error="Los operarios solo pueden registrar avances desde su dashboard"), 403
    
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403
    
    cantidad_str = str(request.form.get("cantidad_ingresada", "")).replace(",", ".")
    try:
        cantidad = float(cantidad_str)
        if cantidad <= 0:
            return jsonify(ok=False, error="La cantidad debe ser mayor a 0"), 400
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Cantidad inválida"), 400
    
    unidad_servidor = normalize_unit(tarea.unidad)
    horas_trabajadas = request.form.get("horas_trabajadas", type=float)
    notas = request.form.get("nota", "")

    try:
        avance = TareaAvance(
            tarea_id=tarea.id, 
            user_id=current_user.id, 
            cantidad=cantidad,
            unidad=unidad_servidor,
            horas=horas_trabajadas,
            notas=notas,
            cantidad_ingresada=cantidad,
            unidad_ingresada=unidad_servidor,
            horas_trabajadas=horas_trabajadas
        )
        if _user_role() in ['administrador', 'tecnico', 'admin', 'pm']:
            avance.status = "aprobado"
            avance.confirmed_by = current_user.id
            avance.confirmed_at = datetime.utcnow()
        db.session.add(avance)
        db.session.flush()
        if not tarea.fecha_inicio_real and avance.status == "aprobado": 
            tarea.fecha_inicio_real = datetime.utcnow()

        media_base = Path(current_app.instance_path) / "media"
        media_base.mkdir(exist_ok=True)
        uploaded_files = request.files.getlist("fotos")
        for foto_file in uploaded_files:
            if foto_file.filename:
                extension = Path(foto_file.filename).suffix.lower()
                unique_name = f"{uuid.uuid4()}{extension}"
                avance_dir = media_base / "avances" / str(avance.id)
                avance_dir.mkdir(parents=True, exist_ok=True)
                file_path = avance_dir / unique_name
                foto_file.save(file_path)
                width, height = None, None
                try:
                    from PIL import Image
                    with Image.open(file_path) as img:
                        width, height = img.size
                except Exception:
                    pass
                relative_path = f"avances/{avance.id}/{unique_name}"
                foto = TareaAvanceFoto(
                    avance_id=avance.id,
                    file_path=relative_path,
                    mime_type=foto_file.content_type,
                    width=width,
                    height=height
                )
                db.session.add(foto)

        db.session.commit()
        recalc_tarea_pct(tarea.id)
        return jsonify(ok=True, avance_id=avance.id, porcentaje_actualizado=tarea.porcentaje_avance)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error creating progress with photos: %s", e)
        return jsonify(ok=False, error="Error interno del servidor"), 500

def suma_ejecutado(tarea_id):
    total = db.session.query(func.coalesce(func.sum(TareaAvance.cantidad_ingresada), 0)).filter_by(tarea_id=tarea_id).scalar()
    return float(total or 0)

def recalc_tarea_pct(tarea_id):
    tarea = TareaEtapa.query.get(tarea_id)
    if not tarea:
        return 0
    meta = float(tarea.cantidad_planificada or 0)
    if meta <= 0:
        tarea.porcentaje_avance = 0
    else:
        ejecutado = suma_ejecutado(tarea_id)
        tarea.porcentaje_avance = min(100, round((ejecutado / meta) * 100, 2))
    db.session.commit()
    return float(tarea.porcentaje_avance or 0)

def pct_etapa(etapa):
    tareas = etapa.tareas.all() if hasattr(etapa.tareas, 'all') else etapa.tareas
    if not tareas:
        return 0
    total_meta = sum((float(t.cantidad_planificada or 0) for t in tareas))
    if total_meta <= 0:
        return round(sum((float(t.porcentaje_avance or 0) for t in tareas)) / max(len(tareas), 1), 2)
    weighted_sum = sum((float(t.cantidad_planificada or 0) * float(t.porcentaje_avance or 0) / 100 for t in tareas))
    return round((weighted_sum / total_meta) * 100, 2)

def pct_obra(obra):
    etapas = obra.etapas.all() if hasattr(obra.etapas, 'all') else obra.etapas
    if not etapas:
        return 0
    total_meta = 0
    total_ejecutado = 0
    for etapa in etapas:
        etapa_meta = sum((float(t.cantidad_planificada or 0) for t in etapa.tareas))
        etapa_pct = pct_etapa(etapa)
        total_meta += etapa_meta
        total_ejecutado += etapa_meta * (etapa_pct / 100)
    if total_meta > 0:
        return round((total_ejecutado / total_meta) * 100, 2)
    etapa_pcts = [pct_etapa(e) for e in etapas]
    return round(sum(etapa_pcts) / max(len(etapa_pcts), 1), 2)

@obras_bp.route("/tareas/<int:tarea_id>/complete", methods=['POST'])
@login_required
def completar_tarea(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra
    if not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403
    try:
        m = resumen_tarea(tarea)
        if m["restante"] > 0: 
            return jsonify(ok=False, error="Aún faltan cantidades"), 400
        tarea.estado = "completada"
        tarea.fecha_fin_real = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error en completar_tarea: %s", e)
        return jsonify(ok=False, error="Error interno"), 500

def _serialize_tarea_detalle(tarea):
    obra = tarea.etapa.obra if tarea.etapa else None
    def _format_date(dt): return dt.strftime('%d/%m/%Y') if dt else None
    def _format_datetime(dt): return dt.isoformat() if dt else None
    def _to_float(value):
        if value is None: return None
        try: return float(value)
        except (TypeError, ValueError): return None

    avances = sorted(list(tarea.avances), key=lambda a: a.created_at or datetime.min, reverse=True)
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

    cantidad_plan = _to_float(tarea.cantidad_planificada)
    cantidad_ejecutada = sum(
        _to_float(a.cantidad) if a.cantidad is not None else _to_float(a.cantidad_ingresada)
        for a in aprobados
    ) or 0.0

    cantidad_restante = None
    if cantidad_plan is not None:
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
                for foto in sorted(list(avance.fotos), key=lambda f: f.created_at or avance.created_at or datetime.min, reverse=True)
            ]
        })

    fotos_data = []
    total_fotos = 0
    for avance in avances:
        for foto in sorted(list(avance.fotos), key=lambda f: f.created_at or avance.created_at or datetime.min, reverse=True):
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
    q = (
        db.session.query(TareaEtapa)
        .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
        .join(EtapaObra, EtapaObra.id == TareaEtapa.etapa_id)
        .join(Obra, Obra.id == EtapaObra.obra_id)
        .filter(TareaMiembro.user_id == current_user.id)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
        .order_by(Obra.nombre, EtapaObra.orden, TareaEtapa.id.desc())
    )
    tareas = q.all()
    current_app.logger.info("mis_tareas user=%s", current_user.id)

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
    puede_actualizar_estado = es_responsable or es_miembro

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
        return jsonify({'ok': True, 'cambio': cambio_realizado, 'tarea': payload['tarea']})
    except Exception as exc:
        current_app.logger.exception('Error actualizando estado de tarea %s: %s', tarea_id, exc)
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'No se pudo actualizar la tarea'}), 500

@obras_bp.route('/api/tareas/<int:tarea_id>/avances-pendientes')
@login_required
def obtener_avances_pendientes(tarea_id):
    # Solo admin/PM pueden ver avances pendientes
    if not is_pm_global():
        return jsonify(ok=False, error="Sin permisos"), 403
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403
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
                'operario': {'id': avance.usuario.id, 'nombre': avance.usuario.nombre_completo},
                'fotos': fotos,
                'fotos_count': len(fotos)
            })
        return jsonify({
            'ok': True,
            'tarea': {'id': tarea.id, 'nombre': tarea.nombre, 'unidad': tarea.unidad},
            'avances': avances_data,
            'total': len(avances_data)
        })
    except Exception as e:
        current_app.logger.exception("Error al obtener avances pendientes: %s", e)
        return jsonify(ok=False, error="Error interno"), 500

@obras_bp.route('/api/tareas/<int:tarea_id>/galeria')
@login_required
def api_tarea_galeria(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra if tarea.etapa else None
    if not obra or obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    puede_ver = False
    if can_manage_obra(obra) or tarea.responsable_id == current_user.id:
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
    if _user_role() not in ['administrador', 'tecnico', 'admin']:
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
        try: fecha_inicio_plan_date = datetime.strptime(fecha_inicio_plan, '%Y-%m-%d').date()
        except ValueError: pass
    if fecha_fin_plan:
        try: fecha_fin_plan_date = datetime.strptime(fecha_fin_plan, '%Y-%m-%d').date()
        except ValueError: pass
    
    tareas_sugeridas = []
    for key in list(request.form.keys()):
        if key.startswith('sugeridas[') and key.endswith('][nombre]'):
            index = key.split('[')[1].split(']')[0]
            nombre_sugerida = request.form.get(f'sugeridas[{index}][nombre]')
            descripcion_sugerida = request.form.get(f'sugeridas[{index}][descripcion]', '')
            if nombre_sugerida:
                tareas_sugeridas.append({'nombre': nombre_sugerida, 'descripcion': descripcion_sugerida})
    
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
    if current_user.email not in ['brenda@gmail.com', 'admin@obyra.com']:
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
        q = (TareaEtapa.query
             .filter(TareaEtapa.etapa_id == etapa_id)
             .options(db.joinedload(TareaEtapa.miembros).joinedload(TareaMiembro.usuario)))
    else:
        if not es_miembro_obra(etapa.obra_id, current_user.id):
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
        q = (TareaEtapa.query
             .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
             .filter(TareaEtapa.etapa_id == etapa_id, TareaMiembro.user_id == current_user.id)
             .options(db.joinedload(TareaEtapa.miembros).joinedload(TareaMiembro.usuario)))
    try:
        tareas = q.order_by(TareaEtapa.id.asc()).all()
        html = render_template('obras/_tareas_lista.html', tareas=tareas)
        return jsonify({'ok': True, 'html': html})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error al cargar tareas: {str(e)}'}), 500

@obras_bp.route('/api/tareas/<int:tarea_id>/curva-s')
@login_required
def api_curva_s_tarea(tarea_id):
    from evm_utils import curva_s_tarea
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    if _user_role() == 'operario':
        es_miembro = TareaMiembro.query.filter_by(tarea_id=tarea_id, user_id=current_user.id).first()
        if not es_miembro:
            return jsonify({'ok': False, 'error': 'Sin permisos para esta tarea'}), 403
    desde_str = request.args.get('desde')
    hasta_str = request.args.get('hasta')
    desde = hasta = None
    try:
        if desde_str: desde = datetime.strptime(desde_str, '%Y-%m-%d').date()
        if hasta_str: hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'ok': False, 'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}), 400
    try:
        curve_data = curva_s_tarea(tarea_id, desde, hasta)
        task_info = {
            'id': tarea.id,
            'nombre': tarea.nombre,
            'fecha_inicio': tarea.fecha_inicio_plan.isoformat() if tarea.fecha_inicio_plan else None,
            'fecha_fin': tarea.fecha_fin_plan.isoformat() if tarea.fecha_fin_plan else None,
            'presupuesto_mo': float(tarea.presupuesto_mo) if getattr(tarea, 'presupuesto_mo', None) else 0,
            'unidad': tarea.unidad,
            'pct_completado': round(float(tarea.porcentaje_avance or 0), 2)
        }
        return jsonify({'ok': True, 'tarea': task_info, 'curva_s': curve_data, 'fecha_consulta': datetime.now().isoformat()})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error al calcular curva S: {str(e)}'}), 500

@obras_bp.route('/tareas/eliminar/<int:tarea_id>', methods=['POST'])
@login_required
def eliminar_tarea(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'success': False, 'error': 'Sin permisos para gestionar esta obra'}), 403
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403
    try:
        db.session.delete(tarea)
        obra.calcular_progreso_automatico()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@obras_bp.route('/api/tareas/bulk_delete', methods=['POST'])
@login_required  
def api_tareas_bulk_delete():
    data = request.get_json() or {}
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'error': 'No se proporcionaron IDs', 'ok': False}), 400
    primera_tarea = TareaEtapa.query.get(ids[0])
    if not primera_tarea:
        return jsonify({'error': 'Tarea no encontrada', 'ok': False}), 404
    obra = primera_tarea.etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'error': 'Sin permisos para gestionar esta obra', 'ok': False}), 403
    try:
        task_ids = []
        for task_id in ids:
            try: task_ids.append(int(task_id))
            except (ValueError, TypeError): continue
        if not task_ids:
            return jsonify({'error': 'IDs inválidos', 'ok': False}), 400
        tareas = TareaEtapa.query.filter(TareaEtapa.id.in_(task_ids)).all()
        if not tareas:
            return jsonify({'error': 'No se encontraron tareas', 'ok': False}), 404
        obras_a_actualizar = set()
        for tarea in tareas:
            if tarea.etapa and tarea.etapa.obra and tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
                return jsonify({'error': 'Sin permisos para algunas tareas', 'ok': False}), 403
            if tarea.etapa and tarea.etapa.obra:
                obras_a_actualizar.add(tarea.etapa.obra)
        deleted = 0
        for tarea in tareas:
            db.session.delete(tarea)
            deleted += 1
        for obra in obras_a_actualizar:
            try:
                obra.calcular_progreso_automatico()
            except Exception as e:
                current_app.logger.warning("Error recalculando progreso obra %s: %s", obra.id, e)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': deleted})
    except Exception as e:
        current_app.logger.exception("Error en tareas_bulk_delete: %s", e)
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor', 'ok': False}), 500

@obras_bp.route('/api/etapas/bulk_delete', methods=['POST'])
@login_required
def api_etapas_bulk_delete():
    data = request.get_json() or {}
    ids = data.get('ids', [])
    if not ids:
        return jsonify({'error': 'No se proporcionaron IDs', 'ok': False}), 400
    primera_etapa = EtapaObra.query.get(ids[0])
    if not primera_etapa:
        return jsonify({'error': 'Etapa no encontrada', 'ok': False}), 404
    obra = primera_etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'error': 'Sin permisos para gestionar esta obra', 'ok': False}), 403
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
def geocodificar_todas():
    if _user_role() != 'administrador' and not is_admin():
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
@login_required
def eliminar_obra(obra_id):
    if current_user.email not in ['brenda@gmail.com', 'admin@obyra.com']:
        flash('No tienes permisos para eliminar obras.', 'danger')
        return redirect(url_for('obras.lista'))
    obra = Obra.query.filter_by(id=obra_id, organizacion_id=current_user.organizacion_id).first_or_404()
    nombre_obra = obra.nombre
    try:
        AsignacionObra.query.filter_by(obra_id=obra_id).delete()
        for etapa in obra.etapas:
            TareaEtapa.query.filter_by(etapa_id=etapa.id).delete()
        EtapaObra.query.filter_by(obra_id=obra_id).delete()
        db.session.delete(obra)
        db.session.commit()
        flash(f'La obra "{nombre_obra}" ha sido eliminada exitosamente.', 'success')
    except Exception:
        db.session.rollback()
        flash('Error al eliminar la obra. Inténtalo nuevamente.', 'danger')
    return redirect(url_for('obras.lista'))

@obras_bp.route('/super-admin/reiniciar-sistema', methods=['POST'])
@login_required
def reiniciar_sistema():
    if current_user.email not in ['brenda@gmail.com', 'admin@obyra.com']:
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

@obras_bp.route('/<int:id>/certificar_avance', methods=['POST'])
@login_required
def certificar_avance(id):
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
            obra, current_user, porcentaje,
            periodo=(periodo_desde, periodo_hasta),
            notas=notas, aprobar=True,
        )
        db.session.commit()
        flash(f'Se registró la certificación #{cert.id} por {porcentaje}% correctamente.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Error al registrar certificación: {exc}', 'danger')
    return redirect(url_for('obras.detalle', id=id))

@obras_bp.route('/<int:id>/actualizar_progreso', methods=['POST'])
@login_required
def actualizar_progreso_automatico(id):
    if _user_role() not in ['administrador', 'tecnico', 'admin']:
        flash('No tienes permisos para actualizar el progreso.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    obra = Obra.query.get_or_404(id)
    try:
        progreso_anterior = obra.progreso or 0
        nuevo_progreso = obra.calcular_progreso_automatico()
        db.session.commit()
        flash(f'Progreso actualizado de {progreso_anterior}% a {nuevo_progreso}%.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar progreso: {str(e)}', 'danger')
    return redirect(url_for('obras.detalle', id=id))

@obras_bp.route('/tarea/<int:id>/actualizar_estado', methods=['POST'])
@login_required
def actualizar_estado_tarea(id):
    tarea = TareaEtapa.query.get_or_404(id)
    obra = tarea.etapa.obra
    is_admin_like = getattr(current_user, 'is_admin', False) or _user_role() in ['administrador', 'tecnico', 'admin', 'pm']
    is_responsible = tarea.responsable_id == current_user.id
    asignado = db.session.query(TareaResponsables.id).filter_by(tarea_id=tarea.id, user_id=current_user.id).first()
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
        obra.calcular_progreso_automatico()
        db.session.commit()
        flash('Estado de tarea actualizado exitosamente.', 'success')
    except ValueError:
        flash('Porcentaje de avance no válido.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar tarea: {str(e)}', 'danger')
    return redirect(url_for('obras.detalle', id=obra.id))

@obras_bp.route('/tareas/<int:tarea_id>/asignar', methods=['POST'])
@login_required
def tarea_asignar(tarea_id):
    if _user_role() not in ['administrador', 'tecnico', 'admin']:
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
                db.session.add(TareaResponsables(tarea_id=tarea.id, user_id=uid))
        db.session.commit()
        return jsonify(ok=True, count=len(user_ids))
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

@obras_bp.route('/<int:id>/certificaciones', methods=['GET', 'POST'])
@login_required
def historial_certificaciones(id):
    obra = Obra.query.filter_by(id=id, organizacion_id=get_current_org_id()).first_or_404()
    membership = get_current_membership()

    if request.method == 'POST':
        payload = request.get_json(silent=True) or request.form
        if not membership or membership.role not in ('admin', 'project_manager'):
            error_msg = 'No tienes permisos para crear certificaciones.'
            if request.is_json:
                return jsonify(ok=False, error=error_msg), 403
            flash(error_msg, 'danger')
            return redirect(url_for('obras.historial_certificaciones', id=id))

        cert_id = payload.get('certificacion_id')
        periodo = (_parse_date(payload.get('periodo_desde')), _parse_date(payload.get('periodo_hasta')))
        aprobar_flag = str(payload.get('aprobar', 'true')).lower() in {'1', 'true', 'yes', 'y', 'on'}
        notas = payload.get('notas')

        try:
            if cert_id:
                cert = WorkCertification.query.get_or_404(int(cert_id))
                if cert.obra_id != obra.id:
                    abort(404)
                if payload.get('porcentaje'):
                    cert.porcentaje_avance = Decimal(str(payload['porcentaje']).replace(',', '.'))
                if aprobar_flag and cert.estado != 'aprobada':
                    cert.marcar_aprobada(current_user)
                if periodo[0] or periodo[1]:
                    cert.periodo_desde, cert.periodo_hasta = periodo
                if notas is not None:
                    cert.notas = notas
                db.session.commit()
                response = {'ok': True, 'certificacion_id': cert.id, 'estado': cert.estado}
                if request.is_json:
                    return jsonify(response)
                flash('Certificación actualizada correctamente.', 'success')
                return redirect(url_for('obras.historial_certificaciones', id=id))

            porcentaje_raw = payload.get('porcentaje') or payload.get('porcentaje_avance')
            if not porcentaje_raw:
                raise ValueError('Debes indicar el porcentaje de avance a certificar.')

            porcentaje = Decimal(str(porcentaje_raw).replace(',', '.'))
            cert = create_certification(
                obra, current_user, porcentaje,
                periodo=periodo, notas=notas, aprobar=aprobar_flag,
                fuente=payload.get('fuente', 'tareas'),
            )
            db.session.commit()
            response = {'ok': True, 'certificacion_id': cert.id, 'estado': cert.estado}
            if request.is_json:
                return jsonify(response)
            flash('Certificación creada correctamente.', 'success')
            return redirect(url_for('obras.historial_certificaciones', id=id))
        except Exception as exc:
            db.session.rollback()
            if request.is_json:
                return jsonify(ok=False, error=str(exc)), 400
            flash(f'Error al crear la certificación: {exc}', 'danger')
            return redirect(url_for('obras.historial_certificaciones', id=id))

    resumen = certification_totals(obra)
    pendientes = build_pending_entries(obra)
    aprobadas = approved_entries(obra)
    pct_aprobado, pct_borrador, pct_sugerido = pending_percentage(obra)
    context = resolve_budget_context(obra)
    puede_aprobar = membership and membership.role in ('admin', 'project_manager')

    if request.args.get('format') == 'json':
        return jsonify(
            ok=True,
            resumen={k: str(v) for k, v in resumen.items()},
            pendientes=[
                {**row, 'porcentaje': str(row['porcentaje']), 'monto_ars': str(row['monto_ars']), 'monto_usd': str(row['monto_usd'])}
                for row in pendientes
            ],
            aprobadas=[
                {**row,
                 'porcentaje': str(row['porcentaje']),
                 'monto_ars': str(row['monto_ars']),
                 'monto_usd': str(row['monto_usd']),
                 'pagado_ars': str(row['pagado_ars']),
                 'pagado_usd': str(row['pagado_usd']),
                 'saldo_ars': str(row['saldo_ars']),
                 'saldo_usd': str(row['saldo_usd'])}
                for row in aprobadas
            ],
            porcentajes={'aprobado': str(pct_aprobado), 'borrador': str(pct_borrador), 'sugerido': str(pct_sugerido)},
        )

    return render_template(
        'obras/certificaciones.html',
        obra=obra,
        pendientes=pendientes,
        certificaciones_aprobadas=aprobadas,
        resumen=resumen,
        porcentajes=(pct_aprobado, pct_borrador, pct_sugerido),
        puede_aprobar=bool(puede_aprobar),
        contexto=context,
    )

@obras_bp.route('/certificacion/<int:id>/desactivar', methods=['POST'])
@login_required
def desactivar_certificacion(id):
    if _user_role() not in ('administrador', 'admin'):
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
    except Exception:
        db.session.rollback()
        flash('Error al desactivar certificación.', 'danger')
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
            certificacion, obra, current_user,
            monto=monto, metodo=metodo, moneda=moneda, fecha=fecha_pago,
            tc_usd=Decimal(str(tc_usd).replace(',', '.')) if tc_usd else None,
            notas=notas, operario_id=operario_id, comprobante_url=data.get('comprobante_url'),
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
def eliminar_etapa(obra_id, etapa_id):
    if _user_role() not in ['administrador', 'tecnico', 'admin']:
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
    if _user_role() not in ['administrador', 'tecnico', 'admin']:
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
        etapa.obra.calcular_progreso_automatico()
        db.session.commit()
        flash(f'Estado de etapa "{etapa.nombre}" cambiado de "{estado_anterior}" a "{nuevo_estado}".', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar estado: {str(e)}', 'danger')
    return redirect(url_for('obras.detalle', id=etapa.obra_id))

@obras_bp.route("/avances/<int:avance_id>/aprobar", methods=['POST'])
@login_required
def aprobar_avance(avance_id):
    av = TareaAvance.query.get_or_404(avance_id)
    obra = av.tarea.etapa.obra if av.tarea and av.tarea.etapa else None
    if not obra or not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permiso"), 403
    if av.status == "aprobado":
        return jsonify(ok=True)
    try:
        av.status = "aprobado"
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()
        t = TareaEtapa.query.get(av.tarea_id)
        if t and not t.fecha_inicio_real:
            t.fecha_inicio_real = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error en aprobar_avance: %s", e)
        return jsonify(ok=False, error="Error interno"), 500

@obras_bp.route("/avances/<int:avance_id>/rechazar", methods=['POST'])
@login_required
def rechazar_avance(avance_id):
    av = TareaAvance.query.get_or_404(avance_id)
    obra = av.tarea.etapa.obra if av.tarea and av.tarea.etapa else None
    if not obra or not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permiso"), 403
    try:
        av.status = "rechazado"
        av.reject_reason = request.form.get("motivo")
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error en rechazar_avance: %s", e)
        return jsonify(ok=False, error="Error interno"), 500

@obras_bp.route('/<int:obra_id>/wizard/tareas', methods=['POST'])
@login_required
def wizard_crear_tareas(obra_id):
    obra = Obra.query.get_or_404(obra_id)
    if not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403
    try:
        data = request.get_json()
        if not data:
            return jsonify(ok=False, error="JSON requerido"), 400
        etapas_data = data.get('etapas', [])
        evitar_duplicados = data.get('evitar_duplicados', True)
        if not etapas_data:
            return jsonify(ok=False, error="Se requiere al menos una etapa"), 400
        creadas = ya_existian = asignaciones_creadas = 0
        db.session.begin()
        for etapa_data in etapas_data:
            etapa_id = etapa_data.get('etapa_id')
            tareas_data = etapa_data.get('tareas', [])
            etapa = EtapaObra.query.filter_by(id=etapa_id, obra_id=obra_id).first()
            if not etapa:
                db.session.rollback()
                return jsonify(ok=False, error=f"Etapa {etapa_id} no existe en esta obra"), 400
            for tarea_data in tareas_data:
                nombre = tarea_data.get('nombre')
                inicio = tarea_data.get('inicio')
                fin = tarea_data.get('fin')
                horas_estimadas = tarea_data.get('horas_estimadas')
                unidad = tarea_data.get('unidad', 'h')
                responsable_id = tarea_data.get('responsable_id')
                if not nombre:
                    db.session.rollback()
                    return jsonify(ok=False, error="Nombre de tarea requerido"), 400
                if responsable_id:
                    miembro = ObraMiembro.query.filter_by(obra_id=obra_id, usuario_id=responsable_id).first()
                    if not miembro:
                        db.session.rollback()
                        return jsonify(ok=False, error=f"Usuario {responsable_id} no es miembro de esta obra"), 400
                fecha_inicio_plan = _parse_date(inicio)
                fecha_fin_plan = _parse_date(fin)
                tarea_existente = None
                if evitar_duplicados:
                    tarea_existente = TareaEtapa.query.filter_by(etapa_id=etapa_id, nombre=nombre).first()
                if tarea_existente:
                    ya_existian += 1
                    tarea = tarea_existente
                    if fecha_inicio_plan: tarea.fecha_inicio_plan = fecha_inicio_plan
                    if fecha_fin_plan: tarea.fecha_fin_plan = fecha_fin_plan
                    if horas_estimadas: tarea.horas_estimadas = horas_estimadas
                    if unidad: tarea.unidad = unidad
                    if responsable_id: tarea.responsable_id = responsable_id
                else:
                    tarea = TareaEtapa(
                        etapa_id=etapa_id, nombre=nombre, descripcion="Creada via wizard",
                        estado='pendiente', fecha_inicio_plan=fecha_inicio_plan,
                        fecha_fin_plan=fecha_fin_plan, horas_estimadas=horas_estimadas,
                        unidad=unidad, responsable_id=responsable_id
                    )
                    db.session.add(tarea)
                    db.session.flush()
                    creadas += 1
                if responsable_id:
                    asignacion_existente = TareaMiembro.query.filter_by(
                        tarea_id=tarea.id, user_id=responsable_id
                    ).first()
                    if not asignacion_existente:
                        db.session.add(TareaMiembro(tarea_id=tarea.id, user_id=responsable_id, cuota_objetivo=None))
                        asignaciones_creadas += 1
        db.session.commit()
        return jsonify(ok=True, creadas=creadas, ya_existian=ya_existian, asignaciones_creadas=asignaciones_creadas)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("WIZARD: Error creando tareas")
        return jsonify(ok=False, error=f"Error interno: {str(e)}"), 500

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
        response = jsonify({"ok": True, "etapas_catalogo": catalogo, "etapas_creadas": etapas_creadas_data})
        response.headers['Content-Type'] = 'application/json'
        return response, 200
    except Exception as e:
        current_app.logger.exception("API Error obteniendo etapas para wizard")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400

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

        from etapas_predefinidas import obtener_etapas_disponibles
        catalogo_etapas = obtener_etapas_disponibles()
        slug_to_nombre = {e['slug']: e['nombre'] for e in catalogo_etapas}
        
        resp = []
        for slug in etapas:
            nombre_etapa = slug_to_nombre.get(slug)
            if nombre_etapa:
                tareas_etapa = obtener_tareas_por_etapa(nombre_etapa)
                for idx, tarea in enumerate(tareas_etapa):
                    nombre = tarea['nombre'] if isinstance(tarea, dict) else str(tarea)
                    desc = (tarea.get('descripcion') if isinstance(tarea, dict) else '') or ''
                    horas = (tarea.get('horas') if isinstance(tarea, dict) else 0) or 0
                    resp.append({'id': f'{slug}-{idx+1}', 'nombre': nombre, 'descripcion': desc, 'etapa_slug': slug, 'horas': horas})
        resp.sort(key=lambda t: (t['etapa_slug'], t['nombre']))
        response = jsonify({'ok': True, 'tareas_catalogo': resp})
        response.headers['Content-Type'] = 'application/json'
        return response, 200
    except Exception as e:
        current_app.logger.exception("Error en wizard_tareas_catalogo: %s", e)
        response = jsonify({"ok": False, "error": "Error interno del servidor"})
        response.headers['Content-Type'] = 'application/json'
        return response, 500

@obras_bp.route('/api/wizard-tareas/opciones')
@login_required  
def wizard_tareas_opciones():
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

        unidades = ['m2', 'm', 'm3', 'u', 'kg', 'h']
        usuarios = []
        try:
            query_result = (db.session.query(Usuario.id, Usuario.nombre, Usuario.apellido, ObraMiembro.rol_en_obra)
                           .join(ObraMiembro, ObraMiembro.usuario_id == Usuario.id)
                           .filter(ObraMiembro.obra_id == obra_id)
                           .filter(Usuario.activo == True)
                           .all())
            for user_id, nombre, apellido, rol in query_result:
                nombre_completo = f"{nombre} {apellido}".strip()
                usuarios.append({'id': user_id, 'nombre': nombre_completo, 'rol': rol or 'Sin rol'})
        except Exception as e:
            current_app.logger.warning("Error equipo obra %s: %s", obra_id, e)
            usuarios = []

        variant_payload = wizard_budgeting.get_stage_variant_payload()
        feature_flags = wizard_budgeting.get_feature_flags()
        currency = (current_app.config.get('DEFAULT_CURRENCY') if current_app else None) or 'ARS'

        response = jsonify({
            'ok': True,
            'unidades': unidades,
            'usuarios': usuarios,
            'feature_flags': feature_flags,
            'variants': variant_payload.get('variants', {}),
            'coefficients': variant_payload.get('coefficients', {}),
            'currency': currency,
        })
        response.headers['Content-Type'] = 'application/json'
        return response, 200
    except Exception as e:
        current_app.logger.exception("API Error obteniendo tareas para wizard")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400

@obras_bp.route('/api/obras/<int:obra_id>/etapas/bulk_from_catalog', methods=['POST'])
@login_required
def bulk_create_etapas_from_catalog(obra_id):
    try:
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403
        data = request.get_json() or {}
        catalogo_ids = data.get("catalogo_ids", [])
        if not catalogo_ids:
            response = jsonify({"ok": False, "error": "Se requiere al menos un ID del catálogo"})
            response.headers['Content-Type'] = 'application/json'
            return response, 400
        from etapas_predefinidas import crear_etapas_desde_catalogo
        try:
            creadas, existentes = crear_etapas_desde_catalogo(obra_id, catalogo_ids)
            for etapa_data in creadas:
                etapa = EtapaObra.query.get(etapa_data['id'])
                if etapa:
                    seed_tareas_para_etapa(etapa, auto_commit=False)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        all_etapas = creadas + existentes
        etapa_ids = [int(e['id'] if isinstance(e, dict) else e.id) for e in all_etapas]
        response = jsonify({"ok": True, "etapa_ids": etapa_ids, "creadas": creadas, "existentes": existentes})
        response.headers['Content-Type'] = 'application/json'
        return response, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("API Error creando etapas desde catálogo para obra %s", obra_id)
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400

@obras_bp.route('/<int:obra_id>/etapas', methods=['GET'])
@login_required
def get_obra_etapas(obra_id):
    try:
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({"error": "Sin permisos"}), 403
        etapas = EtapaObra.query.filter_by(obra_id=obra_id).order_by(EtapaObra.orden).all()
        return jsonify({"etapas": [{"id": e.id, "nombre": e.nombre} for e in etapas]})
    except Exception as e:
        current_app.logger.exception("Error obteniendo etapas obra %s", obra_id)
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

@obras_bp.route('/api/etapas/<int:obra_id>/refresh', methods=['GET'])
@login_required
def get_obra_etapas_full(obra_id):
    try:
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({"ok": False, "error": "Sin permisos"}), 403
        etapas = obra.etapas.order_by(EtapaObra.orden).all()
        can_manage = can_manage_obra(obra)
        etapas_data = [{"id": e.id, "nombre": e.nombre, "descripcion": e.descripcion, "orden": e.orden, "estado": e.estado} for e in etapas]
        return jsonify({"ok": True, "etapas": etapas_data, "can_manage": can_manage, "has_etapas": len(etapas_data) > 0})
    except Exception as e:
        current_app.logger.exception("Error obteniendo etapas completas obra %s", obra_id)
        return jsonify({"ok": False, "error": f"Error interno: {str(e)}"}), 500

@obras_bp.route('/api/dashboard/alerts')
@login_required  
def dashboard_alerts():
    """API: Get dashboard alerts (overdue, due today, upcoming tasks, pending approvals)."""
    try:
        today = date.today()
        next_week = today + timedelta(days=7)
        base_query = (
            TareaEtapa.query
            .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
            .join(Obra, EtapaObra.obra_id == Obra.id)
            .filter(Obra.organizacion_id == current_user.organizacion_id)
        )
        active_tasks = base_query.filter(or_(TareaEtapa.estado == 'en_curso', TareaEtapa.estado == 'pendiente'))

        overdue_count = active_tasks.filter(
            and_(TareaEtapa.fecha_fin_plan.isnot(None), TareaEtapa.fecha_fin_plan < today)
        ).count()

        due_today_count = active_tasks.filter(TareaEtapa.fecha_fin_plan == today).count()

        upcoming_count = active_tasks.filter(
            and_(TareaEtapa.fecha_fin_plan.isnot(None),
                 TareaEtapa.fecha_fin_plan > today,
                 TareaEtapa.fecha_fin_plan <= next_week)
        ).count()

        pending_avances = 0
        if _user_role() in ['admin', 'pm', 'administrador', 'tecnico', 'project_manager']:
            pending_avances = (
                TareaAvance.query
                .join(TareaEtapa, TareaAvance.tarea_id == TareaEtapa.id)
                .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
                .join(Obra, EtapaObra.obra_id == Obra.id)
                .filter(Obra.organizacion_id == current_user.organizacion_id)
                .filter(TareaAvance.status == 'pendiente')
                .count()
            )

        return jsonify({
            'ok': True,
            'alerts': {
                'overdue': overdue_count,
                'due_today': due_today_count,
                'upcoming_week': upcoming_count,
                'pending_avances': pending_avances
            }
        })
    except Exception as e:
        current_app.logger.exception("Error en dashboard_alerts: %s", e)
        return jsonify({'ok': False, 'error': 'Error interno'}), 500

