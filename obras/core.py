"""Obras -- Core CRUD routes (lista, detalle, crear, editar, etc.)."""
from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
import json
import os
from extensions import db
from extensions import limiter
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import selectinload
from utils.pagination import Pagination
from utils import safe_int
from models import (
    Obra, EtapaObra, TareaEtapa, AsignacionObra, Usuario,
    WorkCertification, Cliente, ItemPresupuesto, ItemInventario,
    UsoInventario, ObraMiembro, TareaMiembro, TareaAvance,
)
from etapas_predefinidas import obtener_etapas_disponibles
from tareas_predefinidas import TAREAS_POR_ETAPA, slugify_nombre_etapa
from geocoding import normalizar_direccion_argentina
from services.geocoding_service import resolve as resolve_geocode
from roles_construccion import obtener_roles_por_categoria
from services.memberships import get_current_org_id
from services.permissions import validate_obra_ownership, get_org_id
from services.plan_service import require_active_subscription
from services.obras_filters import (obras_visibles_clause,
                                    obra_tiene_presupuesto_confirmado)
from services.certifications import certification_totals
from services.project_shared_service import ProjectSharedService
from utils.security_logger import log_data_modification, log_data_deletion

from obras import (
    obras_bp, _to_coord_decimal, _get_roles_usuario, is_admin,
    can_manage_obra, es_miembro_obra, _get_cached_results, _set_cached_results,
    CIUDADES_ARGENTINA, geolocalizar_direccion, seed_tareas_para_etapa,
    calcular_costo_materiales, sincronizar_estado_obra, distribuir_datos_etapa_a_tareas,
    recalc_tarea_pct, pct_etapa, _parse_date,
)


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
        # Usar el servicio de geocoding mejorado (Google Maps con deteccion de localidades GBA)
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
                'relevance': 100,
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
    """API endpoint para obtener ciudades de Argentina (para autocompletado rapido)"""
    query = request.args.get('q', '').strip().lower()

    if not query or len(query) < 2:
        return jsonify({'ok': True, 'results': CIUDADES_ARGENTINA[:10]})

    # Filtrar ciudades que coinciden
    matches = [c for c in CIUDADES_ARGENTINA if query in c['nombre'].lower() or query in c['provincia'].lower()]

    return jsonify({'ok': True, 'results': matches[:10]})


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
        flash('No tienes permisos para acceder a este modulo.', 'danger')
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
        query = Obra.query.filter(
            Obra.organizacion_id == org_id,
            Obra.estado != 'cancelada',
            Obra.deleted_at.is_(None)
        )

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

        # Sincronizar estado de obras que tienen etapas en curso pero siguen en planificacion
        obras_planif = query.filter(Obra.estado == 'planificacion').all() if not estado else []
        if not estado:
            obras_planif = Obra.query.filter(
                Obra.organizacion_id == org_id,
                Obra.estado == 'planificacion',
                Obra.deleted_at.is_(None)
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
        flash('Selecciona una organizacion para ver tus obras.', 'warning')
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
@require_active_subscription
def verificar_limite_obras(org_id, lock=False):
    """Verifica si la organizacion puede crear mas obras segun su plan.
    Si lock=True, usa SELECT FOR UPDATE para evitar race conditions."""
    from models import Organizacion
    if lock:
        org = Organizacion.query.filter_by(id=org_id).with_for_update().first()
    else:
        org = Organizacion.query.get(org_id)
    if not org:
        return False, "No se encontro la organizacion."
    limite = org.max_obras or 1
    cantidad_actual = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.estado != 'cancelada',
        Obra.deleted_at.is_(None)
    ).count()
    if cantidad_actual >= limite:
        return False, f"Has alcanzado el limite de {limite} obras de tu plan. Para crear mas obras, mejora tu plan."
    return True, f"Obras: {cantidad_actual}/{limite}"


def crear():
    if not getattr(current_user, 'puede_acceder_modulo', lambda _ : False)('obras'):
        flash('No tienes permisos para crear obras.', 'danger')
        return redirect(url_for('obras.lista'))

    # Verificar limite de obras del plan
    org_id = get_current_org_id()
    # En POST usar lock transaccional para evitar race conditions
    use_lock = request.method == 'POST'
    puede_crear, mensaje_obras = verificar_limite_obras(org_id, lock=use_lock)
    if not puede_crear:
        flash(mensaje_obras, 'warning')
        return redirect(url_for('obras.lista'))

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        direccion = request.form.get('direccion')
        cliente_id = request.form.get('cliente_id')
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
                flash('Formato de fecha de inicio invalido.', 'danger')
                return render_template('obras/crear.html')

        if fecha_fin_estimada:
            try:
                fecha_fin_estimada_obj = datetime.strptime(fecha_fin_estimada, '%Y-%m-%d').date()
            except ValueError:
                flash('Formato de fecha de fin estimada invalido.', 'danger')
                return render_template('obras/crear.html')

        if fecha_inicio_obj and fecha_fin_estimada_obj and fecha_fin_estimada_obj <= fecha_inicio_obj:
            flash('La fecha de fin debe ser posterior a la fecha de inicio.', 'danger')
            return render_template('obras/crear.html')

        geocode_payload = None
        latitud, longitud = None, None
        direccion_normalizada = None

        # Usar coordenadas del frontend si las tiene (mas precisas, el usuario las vio en el mapa)
        geo_lat = request.form.get('geo_lat')
        geo_lng = request.form.get('geo_lng')
        if geo_lat and geo_lng:
            try:
                latitud = _to_coord_decimal(float(geo_lat))
                longitud = _to_coord_decimal(float(geo_lng))
            except (ValueError, TypeError):
                latitud, longitud = None, None

        if direccion:
            direccion_normalizada = normalizar_direccion_argentina(direccion)
            # Solo geocodificar si no tenemos coords del frontend
            if latitud is None or longitud is None:
                geocode_payload = resolve_geocode(direccion_normalizada)
                if geocode_payload:
                    latitud = _to_coord_decimal(geocode_payload.get('lat'))
                    longitud = _to_coord_decimal(geocode_payload.get('lng'))
            else:
                # Tenemos coords del frontend, armar payload minimo
                geocode_payload = {'provider': 'frontend', 'status': 'ok'}

        nueva_obra = Obra(
            nombre=nombre,
            descripcion=descripcion,
            direccion=direccion,
            direccion_normalizada=direccion_normalizada,
            latitud=latitud,
            longitud=longitud,
            cliente_id=int(cliente_id) if cliente_id else None,
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
            try:
                from models.audit import registrar_audit
                registrar_audit('crear', 'obra', nueva_obra.id, f'Obra creada: {nombre}')
                db.session.commit()
            except Exception:
                pass
            log_data_modification('Obra', nueva_obra.id, 'Creada', current_user.email)
            current_app.logger.info(f'Obra creada: {nueva_obra.id} - {nombre} por usuario {current_user.email}')
            flash(f'Obra "{nombre}" creada exitosamente.', 'success')
            return redirect(url_for('obras.detalle', id=nueva_obra.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear la obra: {str(e)}', 'danger')
            current_app.logger.exception("Error creating obra")

    # Obtener lista de clientes activos de la organizacion
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

    # Auto-actualizar estado de etapas segun fecha de inicio
    hoy = date.today()
    etapas_actualizadas = False
    for etapa in etapas:
        if etapa.estado == 'pendiente' and etapa.fecha_inicio_estimada and etapa.fecha_inicio_estimada <= hoy:
            etapa.estado = 'en_curso'
            etapas_actualizadas = True
    if etapas_actualizadas:
        sincronizar_estado_obra(obra)
        db.session.commit()

    # Pre-cargar todas las tareas de todas las etapas en UN solo query (con avances eager-loaded)
    etapa_ids = [e.id for e in etapas]
    todas_tareas = []
    tareas_por_etapa = {}

    def _cargar_tareas(etapa_ids):
        """Carga tareas + avances + miembros + responsable en pocas queries (selectin)."""
        tareas = TareaEtapa.query.options(
            selectinload(TareaEtapa.avances),
            selectinload(TareaEtapa.miembros),
        ).filter(TareaEtapa.etapa_id.in_(etapa_ids)).all() if etapa_ids else []
        por_etapa = {}
        for t in tareas:
            por_etapa.setdefault(t.etapa_id, []).append(t)
        return tareas, por_etapa

    if etapa_ids:
        todas_tareas, tareas_por_etapa = _cargar_tareas(etapa_ids)

    # Auto-distribuir cantidad/unidad/fechas/horas de etapa a tareas sin datos
    from tareas_predefinidas import obtener_tareas_por_etapa as _obt_tareas_cat
    datos_distribuidos = False
    for etapa in etapas:
        tareas_etapa = tareas_por_etapa.get(etapa.id, [])
        if not tareas_etapa:
            continue

        # Verificar si alguna tarea tiene horas incorrectas comparando con catalogo
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
        todas_tareas, tareas_por_etapa = _cargar_tareas(etapa_ids)

    # Limpiar fechas reales de etapas pendientes (no deberian tener)
    for etapa in etapas:
        if etapa.estado == 'pendiente' and (etapa.fecha_inicio_real or etapa.fecha_fin_real):
            etapa.fecha_inicio_real = None
            etapa.fecha_fin_real = None
            db.session.flush()

    # Sync directo: fechas y cantidades redondas
    fechas_sync = False
    for etapa in etapas:
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
            if inicio and fin:
                if len(tareas_etapa) == 1:
                    if t.fecha_inicio_plan != inicio or t.fecha_fin_plan != fin:
                        t.fecha_inicio_plan = inicio
                        t.fecha_fin_plan = fin
                        t.fecha_inicio_estimada = inicio
                        t.fecha_fin_estimada = fin
                        fechas_sync = True
                else:
                    if not t.fecha_inicio_plan or t.fecha_inicio_plan < inicio:
                        t.fecha_inicio_plan = inicio
                        t.fecha_inicio_estimada = inicio
                        fechas_sync = True
                    if not t.fecha_fin_plan or t.fecha_fin_plan > fin:
                        t.fecha_fin_plan = fin
                        t.fecha_fin_estimada = fin
                        fechas_sync = True

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
        todas_tareas, tareas_por_etapa = _cargar_tareas(etapa_ids)

    # Auto-sync: recalcular tareas con avances aprobados que aun figuran como pendientes
    tareas_desync = [t for t in todas_tareas if t.estado == 'pendiente' and any(a.status == 'aprobado' for a in t.avances)]
    if tareas_desync:
        for t in tareas_desync:
            recalc_tarea_pct(t.id)
        todas_tareas, tareas_por_etapa = _cargar_tareas(etapa_ids)

    # Calcular porcentaje de avance por etapa
    etapas_con_avance = {}
    for etapa in etapas:
        tareas = tareas_por_etapa.get(etapa.id, [])
        if not tareas:
            etapas_con_avance[etapa.id] = 0
            continue
        completadas = sum(1 for t in tareas if t.estado in ('completada', 'finalizada'))
        etapas_con_avance[etapa.id] = round((completadas / len(tareas)) * 100, 2)

    # Calcular porcentaje total de la obra
    if etapas:
        porcentaje_obra = round(sum(etapas_con_avance.get(e.id, 0) for e in etapas) / len(etapas), 2)
    else:
        porcentaje_obra = 0

    asignaciones = obra.asignaciones.filter_by(activo=True).all()

    # Tambien incluir ObraMiembros (creados desde asignar-usuarios)
    obra_miembros_extra = ObraMiembro.query.filter_by(obra_id=obra.id).all()
    asig_user_ids = {a.usuario_id for a in asignaciones}
    for om in obra_miembros_extra:
        if om.usuario_id not in asig_user_ids:
            nueva_asig = AsignacionObra(
                obra_id=obra.id,
                usuario_id=om.usuario_id,
                rol_en_obra=om.rol_en_obra or 'operario',
                etapa_id=om.etapa_id,
                activo=True
            )
            db.session.add(nueva_asig)
            asignaciones.append(nueva_asig)
            asig_user_ids.add(om.usuario_id)
    if obra_miembros_extra:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Solo usuarios con membresia activa en esta organizacion
    from models.core import OrgMembership
    usuarios_ids_sub = db.session.query(OrgMembership.user_id).filter(
        OrgMembership.org_id == org_id,
        OrgMembership.status == 'active',
        db.or_(OrgMembership.archived.is_(False), OrgMembership.archived.is_(None))
    ).subquery()
    usuarios_disponibles = Usuario.query.filter(
        Usuario.id.in_(usuarios_ids_sub),
        Usuario.is_super_admin.isnot(True)
    ).order_by(Usuario.nombre, Usuario.apellido).all()
    etapas_disponibles = obtener_etapas_disponibles()

    miembros = asignaciones

    # Obtener operarios con membresia activa para el selector de responsable en tareas
    todos_operarios = Usuario.query.filter(
        Usuario.id.in_(usuarios_ids_sub),
        Usuario.is_super_admin.isnot(True)
    ).order_by(Usuario.nombre, Usuario.apellido).all()

    responsables = [
        {
            'usuario': {
                'id': u.id,
                'nombre_completo': u.nombre_completo,
                'rol': u.rol
            },
            'rol_en_obra': 'operario'
        }
        for u in todos_operarios
    ]

    responsables_query = responsables

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
    _materiales_etapas = {}
    _materiales_cantidad = {}
    if presupuesto:
        items_presupuesto = ItemPresupuesto.query.options(
            selectinload(ItemPresupuesto.etapa),
            selectinload(ItemPresupuesto.item_inventario),
        ).filter_by(presupuesto_id=presupuesto.id).order_by(ItemPresupuesto.id.asc()).all()
        try:
            _consolidados = {}
            _items_consolidados = []
            for item in items_presupuesto:
                if item.tipo != 'material':
                    _items_consolidados.append(item)
                    continue
                if item.item_inventario_id:
                    key = ('inv', item.item_inventario_id)
                else:
                    key = ('desc', (item.descripcion or '').strip().lower())
                etapa_nombre = ''
                try:
                    etapa_nombre = item.etapa.nombre if item.etapa else ''
                except Exception:
                    pass
                if key in _consolidados:
                    _consolidados[key]['cantidad'] += float(item.cantidad or 0)
                    if etapa_nombre:
                        _consolidados[key]['etapas'].append(etapa_nombre)
                else:
                    _consolidados[key] = {
                        'item': item,
                        'cantidad': float(item.cantidad or 0),
                        'etapas': [etapa_nombre] if etapa_nombre else [],
                    }
            for data in _consolidados.values():
                itm = data['item']
                _materiales_etapas[itm.id] = data['etapas']
                _materiales_cantidad[itm.id] = data['cantidad']
                _items_consolidados.append(itm)
            items_presupuesto = _items_consolidados
        except Exception:
            pass

    # Calcular avances de mano de obra por etapa
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

    # Obtener cuadrillas tipo para mostrar composicion en vista MO
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
            cuadrillas_por_etapa[c.etapa_tipo] = info
            cuadrillas_por_etapa[_normalizar(c.etapa_tipo)] = info

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

    # Obtener stock transferido a esta obra
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

    costo_materiales = calcular_costo_materiales(obra.id)

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

    # Detectar desfase en fechas de etapas
    hay_desfase_fechas = False
    for i in range(1, len(etapas)):
        ant = etapas[i - 1]
        act = etapas[i]
        if (ant.fecha_fin_estimada and act.fecha_inicio_estimada
                and ant.fecha_fin_estimada >= act.fecha_inicio_estimada
                and act.estado != 'finalizada'):
            hay_desfase_fechas = True
            break

    # Cargar datos de tablas nuevas de forma segura
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

    # Equipos en esta obra + movimientos pendientes de recepcion
    equipos_en_obra = []
    movimientos_pendientes = []
    try:
        from models.equipment import Equipment, EquipmentMovement
        from sqlalchemy.orm import joinedload
        equipos_en_obra = Equipment.query.filter_by(
            company_id=obra.organizacion_id,
            ubicacion_tipo='obra',
            ubicacion_obra_id=obra.id
        ).filter(Equipment.estado != 'baja').all()
        movimientos_pendientes = EquipmentMovement.query.options(
            joinedload(EquipmentMovement.equipment)
        ).filter_by(
            company_id=obra.organizacion_id,
            destino_obra_id=obra.id,
            estado='en_transito'
        ).order_by(EquipmentMovement.fecha_movimiento.desc()).all()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error cargando equipos en obra {obra.id}: {e}")
        flash(f'Error al cargar maquinaria: {e}', 'warning')

    return render_template('obras/detalle.html',
                         obra=obra,
                         etapas=etapas,
                         remitos_count=remitos_count,
                         remitos_list=remitos_list,
                         ordenes_compra_list=ordenes_compra_list,
                         today=date.today(),
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
                         todos_operarios=todos_operarios,
                         can_manage=can_manage_obra(obra),
                         current_user_id=current_user.id,
                         certificaciones_resumen=cert_resumen,
                         certificaciones_recientes=cert_recientes,
                         presupuesto=presupuesto,
                         items_presupuesto=items_presupuesto,
                         materiales_etapas=_materiales_etapas,
                         materiales_cantidad=_materiales_cantidad,
                         avances_mano_obra=avances_mano_obra,
                         cuadrillas_por_etapa=cuadrillas_por_etapa,
                         stock_transferido=stock_transferido,
                         stock_transferido_por_nombre=stock_transferido_por_nombre,
                         stock_transferido_lista=stock_transferido_lista,
                         costos_desglosados=costos_desglosados,
                         equipos_en_obra=equipos_en_obra,
                         movimientos_pendientes=movimientos_pendientes,
                         wizard_budget_flag=current_app.config.get('WIZARD_BUDGET_BREAKDOWN_ENABLED', False),
                         wizard_budget_shadow=current_app.config.get('WIZARD_BUDGET_SHADOW_MODE', False))

@obras_bp.route('/<int:id>/editar', methods=['POST'])
@login_required
def editar(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para editar obras.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

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


@obras_bp.route('/<int:id>/actualizar-coordenadas', methods=['POST'])
@login_required
def actualizar_coordenadas(id):
    """Actualiza las coordenadas de una obra (usado por geocodificacion automatica del clima)"""
    obra = Obra.query.filter_by(id=id, organizacion_id=get_current_org_id()).first_or_404()

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

        try:
            latitud = float(latitud)
            longitud = float(longitud)
            if not (-90 <= latitud <= 90) or not (-180 <= longitud <= 180):
                raise ValueError("Coordenadas fuera de rango")
        except (TypeError, ValueError) as e:
            return jsonify({'error': f'Coordenadas invalidas: {str(e)}'}), 400

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

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
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
                return jsonify({"ok": False, "error": "Selecciona al menos un usuario"}), 400
            else:
                flash('Selecciona al menos un usuario', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))

        try:
            user_ids_int = [int(uid) for uid in user_ids]
        except (ValueError, TypeError):
            if is_ajax:
                return jsonify({"ok": False, "error": "IDs de usuario invalidos"}), 400
            else:
                flash('IDs de usuario invalidos', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))

        usuarios = Usuario.query.filter(Usuario.id.in_(user_ids_int)).all()
        if not usuarios:
            if is_ajax:
                return jsonify({"ok": False, "error": "Usuarios invalidos"}), 400
            else:
                flash('Usuarios invalidos', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))

        rol_en_obra = request.form.get('rol_en_obra') or request.form.get('rol') or 'operario'
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

        # Si se selecciono una etapa, asignar el usuario como responsable de TODAS las tareas de esa etapa
        tareas_asignadas = 0
        if etapa_id:
            etapa_obj = EtapaObra.query.get(int(etapa_id))
            if etapa_obj and etapa_obj.obra_id == obra_id:
                tareas_etapa = TareaEtapa.query.filter_by(etapa_id=int(etapa_id)).all()
                for tarea in tareas_etapa:
                    for uid in user_ids_int:
                        if not tarea.responsable_id:
                            tarea.responsable_id = uid
                        existe_miembro = TareaMiembro.query.filter_by(
                            tarea_id=tarea.id, user_id=uid
                        ).first()
                        if not existe_miembro:
                            db.session.add(TareaMiembro(tarea_id=tarea.id, user_id=uid))
                            tareas_asignadas += 1

        # Tambien crear AsignacionObra para que aparezca en "Equipo Asignado"
        for uid in user_ids_int:
            asig_existe = AsignacionObra.query.filter_by(
                obra_id=obra_id, usuario_id=uid, activo=True
            ).first()
            if not asig_existe:
                db.session.add(AsignacionObra(
                    obra_id=obra_id,
                    usuario_id=uid,
                    etapa_id=int(etapa_id) if etapa_id else None,
                    rol_en_obra=rol_en_obra,
                    activo=True
                ))

        db.session.commit()

        if is_ajax:
            return jsonify({"ok": True, "creados": creados, "ya_existian": ya_existian, "tareas_asignadas": tareas_asignadas})
        else:
            if creados > 0:
                msg = f'Se asignaron {creados} usuarios a la obra'
                if tareas_asignadas > 0:
                    msg += f' y {tareas_asignadas} tareas asignadas automaticamente'
                flash(msg, 'success')
            if ya_existian > 0:
                flash(f'{ya_existian} usuarios ya estaban asignados', 'info')
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


@obras_bp.route('/<int:obra_id>/asignar_tareas_batch', methods=['POST'])
@login_required
def asignar_tareas_batch(obra_id):
    """Asigna un usuario como responsable de múltiples tareas de una vez.

    Body JSON: {usuario_id, tarea_ids: [1, 2, 3]}
    Pone responsable_id en cada tarea y crea TareaMiembro si no existe.
    """
    if not is_admin():
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True) or {}
    usuario_id = data.get('usuario_id')
    tarea_ids = data.get('tarea_ids', [])

    if not usuario_id or not tarea_ids:
        return jsonify(ok=False, error='usuario_id y tarea_ids son requeridos'), 400

    try:
        usuario_id = int(usuario_id)
        tarea_ids = [int(t) for t in tarea_ids]

        usuario = Usuario.query.get(usuario_id)
        if not usuario:
            return jsonify(ok=False, error='Usuario no encontrado'), 404

        asignadas = 0
        for tarea_id in tarea_ids:
            tarea = TareaEtapa.query.get(tarea_id)
            if not tarea:
                continue
            # Verificar que la tarea pertenece a esta obra
            etapa = EtapaObra.query.get(tarea.etapa_id)
            if not etapa or etapa.obra_id != obra_id:
                continue

            tarea.responsable_id = usuario_id

            # Crear TareaMiembro si no existe
            existe = TareaMiembro.query.filter_by(tarea_id=tarea_id, user_id=usuario_id).first()
            if not existe:
                db.session.add(TareaMiembro(tarea_id=tarea_id, user_id=usuario_id))

            asignadas += 1

        db.session.commit()
        return jsonify(
            ok=True,
            message=f'{asignadas} tarea(s) asignadas a {usuario.nombre_completo}'
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error en asignar_tareas_batch obra {obra_id}")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:obra_id>/api/tareas_por_etapa', methods=['GET'])
@login_required
def api_tareas_por_etapa(obra_id):
    """Devuelve las tareas agrupadas por etapa para el modal de asignación batch."""
    etapas = EtapaObra.query.filter_by(obra_id=obra_id).order_by(EtapaObra.orden).all()
    resultado = []
    for etapa in etapas:
        tareas = TareaEtapa.query.filter_by(etapa_id=etapa.id).all()
        resultado.append({
            'etapa_id': etapa.id,
            'etapa_nombre': etapa.nombre,
            'tareas': [{
                'id': t.id,
                'nombre': t.nombre,
                'estado': t.estado,
                'responsable_id': t.responsable_id,
                'responsable_nombre': t.responsable.nombre_completo if t.responsable else None,
            } for t in tareas]
        })
    return jsonify(ok=True, etapas=resultado)


@obras_bp.route('/<int:obra_id>/quitar_usuario', methods=['POST'])
@login_required
def quitar_usuario(obra_id):
    """Quita un usuario de la obra y desvincular de todas sus tareas/etapas."""
    if not is_admin():
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True) or {}
    usuario_id = data.get('usuario_id')
    if not usuario_id:
        return jsonify(ok=False, error='usuario_id requerido'), 400

    try:
        usuario_id = int(usuario_id)

        # 1. Quitar de AsignacionObra
        asignaciones = AsignacionObra.query.filter_by(obra_id=obra_id, usuario_id=usuario_id).all()
        for a in asignaciones:
            a.activo = False
        asig_count = len(asignaciones)

        # 2. Quitar de obra_miembros (tabla directa)
        try:
            result = db.session.execute(
                text("DELETE FROM obra_miembros WHERE obra_id = :o AND usuario_id = :u"),
                {"o": obra_id, "u": usuario_id}
            )
            miembros_count = result.rowcount
        except Exception:
            miembros_count = 0

        # 3. Quitar como responsable de tareas de esta obra
        tareas_obra = TareaEtapa.query.join(EtapaObra).filter(
            EtapaObra.obra_id == obra_id,
            TareaEtapa.responsable_id == usuario_id
        ).all()
        for tarea in tareas_obra:
            tarea.responsable_id = None
        tareas_count = len(tareas_obra)

        # 4. Quitar de TareaMiembro para tareas de esta obra
        from models.projects import TareaMiembro
        tarea_ids = [t.id for t in TareaEtapa.query.join(EtapaObra).filter(EtapaObra.obra_id == obra_id).all()]
        if tarea_ids:
            miembros_tarea = TareaMiembro.query.filter(
                TareaMiembro.tarea_id.in_(tarea_ids),
                TareaMiembro.user_id == usuario_id
            ).all()
            for mt in miembros_tarea:
                db.session.delete(mt)
            tm_count = len(miembros_tarea)
        else:
            tm_count = 0

        db.session.commit()

        usuario = Usuario.query.get(usuario_id)
        nombre = usuario.nombre_completo if usuario else f'Usuario #{usuario_id}'

        return jsonify(
            ok=True,
            message=f'{nombre} fue quitado de la obra. Se desvincularon {tareas_count} tareas y {tm_count} asignaciones de miembro.'
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error quitando usuario {usuario_id} de obra {obra_id}")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:id>/etapa', methods=['POST'])
@login_required
def agregar_etapa(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para agregar etapas.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
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


@obras_bp.route('/geocodificar-todas', methods=['POST'])
@login_required
@limiter.limit("2 per hour")
def geocodificar_todas():
    if not is_admin():
        flash('Solo los administradores pueden ejecutar esta accion.', 'danger')
        return redirect(url_for('obras.lista'))

    try:
        from geocoding import geocodificar_obras_existentes
        exitosas, fallidas = geocodificar_obras_existentes()

        if exitosas > 0:
            flash(f'Geocodificacion completada: {exitosas} obras actualizadas, {fallidas} fallaron.', 'success')
        else:
            flash('No se pudieron geocodificar las obras. Verifica las direcciones.', 'warning')

    except Exception as e:
        flash(f'Error en la geocodificacion: {str(e)}', 'danger')

    return redirect(url_for('obras.lista'))


@obras_bp.route('/eliminar/<int:obra_id>', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def eliminar_obra(obra_id):
    roles = _get_roles_usuario(current_user)
    if not (current_user.is_super_admin or 'administrador' in roles or 'admin' in roles):
        flash('No tienes permisos para eliminar obras.', 'danger')
        return redirect(url_for('obras.lista'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first_or_404()
    nombre_obra = obra.nombre

    try:
        # Soft delete: marcar como inactiva y cancelada (no borrar datos)
        obra.activo = False
        obra.estado = 'cancelada'
        db.session.commit()

        try:
            from models.audit import registrar_audit
            registrar_audit('eliminar', 'obra', obra_id, f'Obra "{nombre_obra}" eliminada (soft delete)')
            db.session.commit()
        except Exception:
            pass

        log_data_deletion('Obra', obra_id, current_user.email)
        current_app.logger.warning(f'Obra soft-deleted: {obra_id} - {nombre_obra} por usuario {current_user.email}')
        flash(f'La obra "{nombre_obra}" ha sido eliminada exitosamente.', 'success')
        return redirect(url_for('obras.lista'))

    except Exception as e_soft:
        db.session.rollback()
        current_app.logger.error(f'Error en soft delete de obra {obra_id}: {e_soft}')
        flash(f'Error al eliminar la obra: {str(e_soft)}', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))
