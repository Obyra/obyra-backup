"""
Panel de Superadministrador
============================
Permite a los superadministradores ver datos de todas las organizaciones.
"""

from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from functools import wraps

from extensions import db
from models import (
    Organizacion, Usuario, OrgMembership,
    Obra, Presupuesto, ItemInventario, Cliente, Proveedor
)
from services.memberships import get_current_org_id

superadmin_bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')


def require_super_admin(f):
    """Decorador que requiere que el usuario sea superadmin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Debes iniciar sesión para acceder a esta sección.', 'warning')
            return redirect(url_for('auth.login'))
        if not current_user.is_super_admin:
            flash('No tienes permisos para acceder a esta sección.', 'danger')
            return redirect(url_for('reportes.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@superadmin_bp.route('/')
@login_required
@require_super_admin
def panel():
    """Panel principal del superadmin con resumen de todas las organizaciones"""

    # Obtener todas las organizaciones con estadísticas
    organizaciones = Organizacion.query.order_by(Organizacion.nombre).all()

    org_stats = []
    for org in organizaciones:
        stats = {
            'organizacion': org,
            'usuarios': Usuario.query.filter_by(organizacion_id=org.id).count(),
            'obras': Obra.query.filter_by(organizacion_id=org.id).count(),
            'presupuestos': Presupuesto.query.filter_by(organizacion_id=org.id).count(),
            'items_inventario': ItemInventario.query.filter_by(organizacion_id=org.id, activo=True).count(),
            'clientes': Cliente.query.filter_by(organizacion_id=org.id).count(),
            'proveedores': Proveedor.query.filter_by(organizacion_id=org.id).count() if hasattr(Proveedor, 'organizacion_id') else 0
        }
        org_stats.append(stats)

    # Totales globales
    totales = {
        'organizaciones': len(organizaciones),
        'usuarios': Usuario.query.count(),
        'obras': Obra.query.count(),
        'presupuestos': Presupuesto.query.count(),
        'items_inventario': ItemInventario.query.filter_by(activo=True).count()
    }

    return render_template('superadmin/panel.html',
                          org_stats=org_stats,
                          totales=totales)


@superadmin_bp.route('/organizacion/<int:org_id>')
@login_required
@require_super_admin
def ver_organizacion(org_id):
    """Ver detalles de una organización específica"""
    from services.plan_service import get_plan_summary, get_subscription_status, PLAN_FEATURES

    org = Organizacion.query.get_or_404(org_id)

    # Obtener datos de la organización
    usuarios = Usuario.query.filter_by(organizacion_id=org_id).order_by(Usuario.nombre).all()
    obras = Obra.query.filter_by(organizacion_id=org_id).order_by(Obra.fecha_creacion.desc()).limit(20).all()
    presupuestos = Presupuesto.query.filter_by(organizacion_id=org_id).order_by(Presupuesto.fecha_creacion.desc()).limit(20).all()
    items = ItemInventario.query.filter_by(organizacion_id=org_id, activo=True).order_by(ItemInventario.nombre).all()
    clientes = Cliente.query.filter_by(organizacion_id=org_id).order_by(Cliente.nombre).all()

    # Plan summary para la vista
    plan_summary = get_plan_summary(org)
    status, days_remaining, is_writable = get_subscription_status(org)

    # Warnings de excedentes
    plan_warnings = []
    plan_config = PLAN_FEATURES.get(org.plan_tipo or 'prueba', PLAN_FEATURES['prueba'])
    obras_activas = len([o for o in obras if getattr(o, 'estado', '') != 'cancelada'])
    usuarios_activos = len([u for u in usuarios if getattr(u, 'activo', True)])

    if obras_activas > (org.max_obras or plan_config['max_obras']):
        plan_warnings.append(f'Tiene {obras_activas} obras activas pero el plan permite {org.max_obras or plan_config["max_obras"]}.')
    if usuarios_activos > (org.max_usuarios or plan_config['max_usuarios']):
        plan_warnings.append(f'Tiene {usuarios_activos} usuarios activos pero el plan permite {org.max_usuarios or plan_config["max_usuarios"]}.')

    return render_template('superadmin/organizacion.html',
                          org=org,
                          usuarios=usuarios,
                          obras=obras,
                          presupuestos=presupuestos,
                          items=items,
                          clientes=clientes,
                          plan_summary=plan_summary,
                          plan_warnings=plan_warnings,
                          subscription_status=status,
                          days_remaining=days_remaining)


@superadmin_bp.route('/inventario')
@login_required
@require_super_admin
def inventario_global():
    """Ver inventario de todas las organizaciones"""

    org_filter = request.args.get('org_id', type=int)
    buscar = request.args.get('buscar', '')

    query = ItemInventario.query.filter_by(activo=True)

    if org_filter:
        query = query.filter(ItemInventario.organizacion_id == org_filter)

    if buscar:
        query = query.filter(
            db.or_(
                ItemInventario.codigo.ilike(f'%{buscar}%'),
                ItemInventario.nombre.ilike(f'%{buscar}%')
            )
        )

    items = query.order_by(ItemInventario.organizacion_id, ItemInventario.nombre).all()
    organizaciones = Organizacion.query.order_by(Organizacion.nombre).all()

    return render_template('superadmin/inventario.html',
                          items=items,
                          organizaciones=organizaciones,
                          org_filter=org_filter,
                          buscar=buscar)


@superadmin_bp.route('/obras')
@login_required
@require_super_admin
def obras_global():
    """Ver obras de todas las organizaciones"""

    org_filter = request.args.get('org_id', type=int)

    query = Obra.query

    if org_filter:
        query = query.filter(Obra.organizacion_id == org_filter)

    obras = query.order_by(Obra.fecha_creacion.desc()).all()
    organizaciones = Organizacion.query.order_by(Organizacion.nombre).all()

    return render_template('superadmin/obras.html',
                          obras=obras,
                          organizaciones=organizaciones,
                          org_filter=org_filter)


@superadmin_bp.route('/usuarios')
@login_required
@require_super_admin
def usuarios_global():
    """Ver usuarios de todas las organizaciones"""

    org_filter = request.args.get('org_id', type=int)

    query = Usuario.query

    if org_filter:
        query = query.filter(Usuario.organizacion_id == org_filter)

    usuarios = query.order_by(Usuario.organizacion_id, Usuario.nombre).all()
    organizaciones = Organizacion.query.order_by(Organizacion.nombre).all()

    return render_template('superadmin/usuarios.html',
                          usuarios=usuarios,
                          organizaciones=organizaciones,
                          org_filter=org_filter)


@superadmin_bp.route('/activar-plan/<int:org_id>', methods=['POST'])
@login_required
@require_super_admin
def activar_plan(org_id):
    """Activar o cambiar el plan de una organización manualmente"""
    from services.plan_service import PLAN_FEATURES, change_plan

    org = Organizacion.query.get_or_404(org_id)
    plan_tipo = request.form.get('plan_tipo', 'estandar')
    dias = int(request.form.get('dias', 30))
    contract_type = request.form.get('contract_type', 'subscription')

    # Usar change_plan del plan_service para manejo seguro
    success, message, warnings = change_plan(
        org, plan_tipo, days=dias, contract_type=contract_type,
        changed_by=current_user.id
    )

    if not success:
        flash(message, 'error')
        return redirect(url_for('superadmin.ver_organizacion', org_id=org_id))

    # Actualizar subscription_status
    org.subscription_status = 'active'
    org.grace_period_until = None
    db.session.commit()

    for w in warnings:
        flash(w, 'warning')

    flash(message, 'success')
    return redirect(url_for('superadmin.ver_organizacion', org_id=org_id))


@superadmin_bp.route('/suspender/<int:org_id>', methods=['POST'])
@login_required
@require_super_admin
def suspender_org(org_id):
    """Suspender una organización"""
    org = Organizacion.query.get_or_404(org_id)
    org.subscription_status = 'suspended'
    db.session.commit()
    flash(f'Organización {org.nombre} suspendida.', 'warning')
    return redirect(url_for('superadmin.ver_organizacion', org_id=org_id))


@superadmin_bp.route('/reactivar/<int:org_id>', methods=['POST'])
@login_required
@require_super_admin
def reactivar_org(org_id):
    """Reactivar una organización suspendida"""
    org = Organizacion.query.get_or_404(org_id)
    org.subscription_status = 'active'
    org.grace_period_until = None
    db.session.commit()
    flash(f'Organización {org.nombre} reactivada.', 'success')
    return redirect(url_for('superadmin.ver_organizacion', org_id=org_id))


@superadmin_bp.route('/gracia/<int:org_id>', methods=['POST'])
@login_required
@require_super_admin
def dar_gracia(org_id):
    """Otorgar período de gracia a una organización"""
    org = Organizacion.query.get_or_404(org_id)
    dias_gracia = int(request.form.get('dias_gracia', 7))
    org.subscription_status = 'grace_period'
    org.grace_period_until = datetime.utcnow() + timedelta(days=dias_gracia)
    db.session.commit()
    flash(f'Período de gracia de {dias_gracia} días otorgado a {org.nombre}.', 'info')
    return redirect(url_for('superadmin.ver_organizacion', org_id=org_id))


@superadmin_bp.route('/descuento/<int:org_id>', methods=['POST'])
@login_required
@require_super_admin
def asignar_descuento(org_id):
    """Asignar o modificar descuento a una organización."""
    org = Organizacion.query.get_or_404(org_id)

    porcentaje = int(request.form.get('descuento_porcentaje', 0))
    meses = int(request.form.get('descuento_meses', 0))

    if porcentaje not in [0, 10, 20, 30, 40, 50]:
        flash('Porcentaje de descuento no válido. Use 0, 10, 20, 30, 40 o 50.', 'danger')
        return redirect(url_for('superadmin.ver_organizacion', org_id=org_id))

    if porcentaje == 0 or meses == 0:
        # Quitar descuento
        org.descuento_porcentaje = 0
        org.descuento_meses = 0
        org.descuento_inicio = None
        db.session.commit()
        flash(f'Descuento removido para {org.nombre}.', 'info')
    else:
        org.descuento_porcentaje = porcentaje
        org.descuento_meses = meses
        org.descuento_inicio = datetime.utcnow()
        db.session.commit()

        try:
            from models.audit import registrar_audit
            registrar_audit('descuento', 'organizacion', org_id,
                           f'Descuento {porcentaje}% por {meses} meses a {org.nombre}')
            db.session.commit()
        except Exception:
            pass

        flash(f'Descuento de {porcentaje}% por {meses} meses asignado a {org.nombre}.', 'success')

    return redirect(url_for('superadmin.ver_organizacion', org_id=org_id))


@superadmin_bp.route('/api/stats')
@login_required
@require_super_admin
def api_stats():
    """API para obtener estadísticas globales"""

    stats = {
        'organizaciones': Organizacion.query.count(),
        'usuarios': Usuario.query.count(),
        'obras': Obra.query.count(),
        'presupuestos': Presupuesto.query.count(),
        'items_inventario': ItemInventario.query.filter_by(activo=True).count(),
        'clientes': Cliente.query.count()
    }

    return jsonify(stats)


@superadmin_bp.route('/debug-obra-coords/<int:obra_id>')
@login_required
@require_super_admin
def debug_obra_coords(obra_id):
    """Ver coordenadas de una obra para debug de GPS."""
    from models.projects import Obra
    obra = Obra.query.get_or_404(obra_id)
    return jsonify({
        'id': obra.id,
        'nombre': obra.nombre,
        'direccion': obra.direccion,
        'latitud': float(obra.latitud) if obra.latitud else None,
        'longitud': float(obra.longitud) if obra.longitud else None,
        'radio_fichada_metros': obra.radio_fichada_metros,
        'geocode_status': obra.geocode_status,
        'geocode_provider': obra.geocode_provider,
        'direccion_normalizada': obra.direccion_normalizada,
        'google_maps_link': f'https://www.google.com/maps?q={obra.latitud},{obra.longitud}' if obra.latitud else None,
    })


@superadmin_bp.route('/fix-obra-coords/<int:obra_id>', methods=['POST'])
@login_required
@require_super_admin
def fix_obra_coords(obra_id):
    """Forzar coordenadas de una obra (superadmin)."""
    from models.projects import Obra
    obra = Obra.query.get_or_404(obra_id)
    data = request.get_json(silent=True) or {}
    lat = data.get('latitud')
    lng = data.get('longitud')
    if lat is None or lng is None:
        return jsonify({'ok': False, 'error': 'Faltan latitud/longitud'}), 400
    old_lat, old_lng = float(obra.latitud) if obra.latitud else None, float(obra.longitud) if obra.longitud else None
    obra.latitud = float(lat)
    obra.longitud = float(lng)
    obra.geocode_status = 'ok'
    obra.geocode_provider = 'manual_superadmin'
    db.session.commit()
    return jsonify({
        'ok': True,
        'obra': obra.nombre,
        'old': {'lat': old_lat, 'lng': old_lng},
        'new': {'lat': float(obra.latitud), 'lng': float(obra.longitud)},
    })


@superadmin_bp.route('/cron/alertas-entregas-oc')
@login_required
@require_super_admin
def cron_alertas_entregas_oc():
    """Ejecutar alertas de entregas próximas de OC (llamar diariamente)."""
    from blueprint_ordenes_compra import notificar_entregas_proximas
    cantidad = notificar_entregas_proximas()
    return jsonify({'ok': True, 'ocs_con_entrega_proxima': cantidad})


@superadmin_bp.route('/limpiar-marcas-cuadrillas', methods=['GET', 'POST'])
@login_required
@require_super_admin
def limpiar_marcas_cuadrillas():
    """Eliminar marcas comerciales de nombres de cuadrillas y roles."""
    from models.budgets import CuadrillaTipo, MiembroCuadrilla
    import re

    marcas = [
        'PERI', 'Peri', 'peri',
        'DOKA', 'Doka', 'doka',
        'ULMA', 'Ulma', 'ulma',
        'EFCO', 'Efco', 'efco',
        'Sinis', 'SINIS',
        'Kaufmann', 'KAUFMANN',
        'Encomax', 'ENCOMAX',
    ]

    cambios = 0

    # Limpiar nombres de cuadrillas
    cuadrillas = CuadrillaTipo.query.all()
    for c in cuadrillas:
        nombre_original = c.nombre
        for marca in marcas:
            c.nombre = c.nombre.replace(f' - sistema {marca}', '')
            c.nombre = c.nombre.replace(f' - Sistema {marca}', '')
            c.nombre = c.nombre.replace(f' {marca}', '')
            c.nombre = c.nombre.replace(f' sistema {marca}', '')
        # Limpiar espacios dobles
        c.nombre = re.sub(r'\s+', ' ', c.nombre).strip()
        if c.nombre != nombre_original:
            cambios += 1

    # Limpiar roles de miembros
    miembros = MiembroCuadrilla.query.all()
    for m in miembros:
        rol_original = m.rol
        for marca in marcas:
            m.rol = m.rol.replace(f' {marca}', '')
            m.rol = m.rol.replace(f' {marca.upper()}', '')
        m.rol = re.sub(r'\s+', ' ', m.rol).strip()
        if m.rol != rol_original:
            cambios += 1

    db.session.commit()
    flash(f'Limpieza completada: {cambios} registros actualizados.', 'success')
    return redirect(url_for('superadmin.panel'))


# ============================================================
# Aprendizaje Calculadora IA (Fase B)
# ============================================================

@superadmin_bp.route('/calculadora-ia/aprendizaje')
@login_required
@require_super_admin
def calculadora_ia_aprendizaje():
    """Panel global de aprendizaje IA: candidatas, top reglas, items sin sugerencia."""
    from models.ia_learning import IACorrectionLog, IARuleCandidate, IARuleUsageStat
    from sqlalchemy import func

    # Resumen general
    total_correcciones = db.session.query(func.count(IACorrectionLog.id)).scalar() or 0
    total_candidatas = db.session.query(func.count(IARuleCandidate.id)).scalar() or 0
    candidatas_pendientes = db.session.query(func.count(IARuleCandidate.id)).filter(
        IARuleCandidate.estado == 'pendiente'
    ).scalar() or 0
    candidatas_aprobadas = db.session.query(func.count(IARuleCandidate.id)).filter(
        IARuleCandidate.estado == 'aprobada'
    ).scalar() or 0
    candidatas_rechazadas = db.session.query(func.count(IARuleCandidate.id)).filter(
        IARuleCandidate.estado == 'rechazada'
    ).scalar() or 0
    total_reglas_usadas = db.session.query(func.count(IARuleUsageStat.id)).scalar() or 0

    resumen = {
        'total_correcciones': total_correcciones,
        'total_candidatas': total_candidatas,
        'candidatas_pendientes': candidatas_pendientes,
        'candidatas_aprobadas': candidatas_aprobadas,
        'candidatas_rechazadas': candidatas_rechazadas,
        'total_reglas_usadas': total_reglas_usadas,
    }

    return render_template('superadmin/calculadora_ia_aprendizaje.html', resumen=resumen)


@superadmin_bp.route('/calculadora-ia/api/candidatas-pendientes')
@login_required
@require_super_admin
def api_ia_candidatas_pendientes():
    """Lista de candidatas pendientes ordenadas por cantidad_ocurrencias."""
    from models.ia_learning import IARuleCandidate

    estado = (request.args.get('estado') or 'pendiente').strip()
    limit = min(int(request.args.get('limit') or 50), 200)

    q = IARuleCandidate.query
    if estado != 'todos':
        q = q.filter(IARuleCandidate.estado == estado)
    items = q.order_by(
        IARuleCandidate.cantidad_ocurrencias.desc(),
        IARuleCandidate.updated_at.desc(),
    ).limit(limit).all()
    return jsonify(ok=True, items=[c.to_dict() for c in items])


@superadmin_bp.route('/calculadora-ia/api/top-reglas')
@login_required
@require_super_admin
def api_ia_top_reglas():
    """Reglas mas usadas, mas aceptadas, mas editadas."""
    from models.ia_learning import IARuleUsageStat

    bucket = (request.args.get('bucket') or 'usos').strip()
    limit = min(int(request.args.get('limit') or 20), 100)

    q = IARuleUsageStat.query
    if bucket == 'aceptadas':
        q = q.order_by(IARuleUsageStat.cantidad_aceptadas_sin_edicion.desc())
    elif bucket == 'editadas':
        q = q.order_by(IARuleUsageStat.cantidad_editadas.desc())
    elif bucket == 'rechazadas':
        q = q.order_by(IARuleUsageStat.cantidad_rechazadas.desc())
    else:
        q = q.order_by(IARuleUsageStat.cantidad_usos.desc())
    items = q.limit(limit).all()
    return jsonify(ok=True, items=[s.to_dict() for s in items])


@superadmin_bp.route('/calculadora-ia/api/items-sin-sugerencia')
@login_required
@require_super_admin
def api_ia_items_sin_sugerencia():
    """Top descripciones recurrentes que la IA no logra clasificar (regla_id NULL)."""
    from models.ia_learning import IACorrectionLog
    from sqlalchemy import func

    limit = min(int(request.args.get('limit') or 30), 100)
    rows = (
        db.session.query(
            IACorrectionLog.descripcion_normalizada,
            func.count(IACorrectionLog.id).label('ocurrencias'),
            func.max(IACorrectionLog.descripcion_original).label('ejemplo'),
        )
        .filter(IACorrectionLog.regla_tecnica_id.is_(None))
        .group_by(IACorrectionLog.descripcion_normalizada)
        .order_by(func.count(IACorrectionLog.id).desc())
        .limit(limit)
        .all()
    )
    return jsonify(
        ok=True,
        items=[
            {'descripcion_normalizada': r[0], 'ocurrencias': r[1], 'ejemplo': r[2]}
            for r in rows
        ],
    )


@superadmin_bp.route('/calculadora-ia/api/baja-confianza')
@login_required
@require_super_admin
def api_ia_baja_confianza():
    """Top descripciones con baja confianza recurrente (< 0.45)."""
    from models.ia_learning import IACorrectionLog
    from sqlalchemy import func

    limit = min(int(request.args.get('limit') or 30), 100)
    rows = (
        db.session.query(
            IACorrectionLog.descripcion_normalizada,
            func.count(IACorrectionLog.id).label('ocurrencias'),
            func.avg(IACorrectionLog.confianza_original).label('confianza_avg'),
            func.max(IACorrectionLog.descripcion_original).label('ejemplo'),
        )
        .filter(IACorrectionLog.confianza_original.isnot(None))
        .filter(IACorrectionLog.confianza_original < 0.45)
        .group_by(IACorrectionLog.descripcion_normalizada)
        .order_by(func.count(IACorrectionLog.id).desc())
        .limit(limit)
        .all()
    )
    return jsonify(
        ok=True,
        items=[
            {
                'descripcion_normalizada': r[0],
                'ocurrencias': r[1],
                'confianza_avg': float(r[2]) if r[2] is not None else None,
                'ejemplo': r[3],
            }
            for r in rows
        ],
    )


@superadmin_bp.route('/calculadora-ia/api/correcciones-resumen')
@login_required
@require_super_admin
def api_ia_correcciones_resumen():
    """Resumen agregado por tipo: rubros mas corregidos, unidades, etc.

    Iteramos en Python sobre los ultimos N logs para portabilidad SQLite/PG
    (no usamos operadores JSONB-specific). Limite alto para representatividad.
    """
    from models.ia_learning import IACorrectionLog

    limit = min(int(request.args.get('limit') or 1000), 5000)
    logs = (
        IACorrectionLog.query
        .order_by(IACorrectionLog.created_at.desc())
        .limit(limit)
        .all()
    )

    rubros_corregidos = {}
    unidades_corregidas = {}
    materiales_agregados = {}
    maquinaria_agregada = {}
    total_aceptadas = 0
    total_editadas = 0

    for log in logs:
        tipos = log.tipos_correccion or []
        if 'aceptada_sin_editar' in tipos and not any(t.startswith('editada_') for t in tipos):
            total_aceptadas += 1
        if any(t.startswith('editada_') for t in tipos):
            total_editadas += 1
        correcc = log.correccion_usuario_json or {}
        if 'editada_rubro' in tipos:
            r = (correcc.get('rubro') or '').strip()
            if r:
                rubros_corregidos[r] = rubros_corregidos.get(r, 0) + 1
        if 'editada_unidad' in tipos:
            u = (correcc.get('unidad') or '').strip()
            if u:
                unidades_corregidas[u] = unidades_corregidas.get(u, 0) + 1
        if 'editada_materiales' in tipos:
            for m in (correcc.get('materiales') or []):
                materiales_agregados[str(m)] = materiales_agregados.get(str(m), 0) + 1
        if 'editada_maquinaria' in tipos:
            for mq in (correcc.get('maquinaria') or []):
                maquinaria_agregada[str(mq)] = maquinaria_agregada.get(str(mq), 0) + 1

    def top(d, n=20):
        return sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]

    return jsonify(
        ok=True,
        ventana_logs=len(logs),
        total_aceptadas_sin_editar=total_aceptadas,
        total_editadas=total_editadas,
        rubros_corregidos=top(rubros_corregidos),
        unidades_corregidas=top(unidades_corregidas),
        materiales_agregados=top(materiales_agregados),
        maquinaria_agregada=top(maquinaria_agregada),
    )


@superadmin_bp.route('/calculadora-ia/candidata/<int:cand_id>/<accion>', methods=['POST'])
@login_required
@require_super_admin
def accion_candidata_ia(cand_id, accion):
    """Aprobar o rechazar una candidata. NO inserta como regla activa todavia."""
    from models.ia_learning import IARuleCandidate

    if accion not in ('aprobar', 'rechazar'):
        return jsonify(ok=False, error='accion invalida'), 400

    cand = IARuleCandidate.query.get_or_404(cand_id)
    if cand.estado not in ('pendiente',):
        return jsonify(ok=False, error=f'candidata ya esta en estado {cand.estado}'), 400

    notas = (request.get_json(silent=True) or {}).get('notas')
    if accion == 'aprobar':
        cand.estado = 'aprobada'
        audit_accion = 'aprobar_candidata_ia'
    else:
        cand.estado = 'rechazada'
        audit_accion = 'rechazar_candidata_ia'
    cand.aprobada_por_user_id = current_user.id
    cand.aprobada_at = datetime.utcnow()
    cand.notas_admin = (notas or '').strip()[:500] or None
    cand.updated_at = datetime.utcnow()

    try:
        from models.audit import registrar_audit
        registrar_audit(
            accion=audit_accion,
            entidad='ia_rule_candidate',
            entidad_id=cand.id,
            detalle=f'desc_norm={cand.descripcion_normalizada[:120]} ocurr={cand.cantidad_ocurrencias}',
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, candidata=cand.to_dict())
