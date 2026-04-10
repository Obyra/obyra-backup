from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, send_file
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import func, desc
from extensions import db
from services.plan_service import require_feature
from models import (Obra, Usuario, Presupuesto, ItemInventario, RegistroTiempo,
                   AsignacionObra, UsoInventario, MovimientoInventario,
                   Organizacion, OrgMembership, ItemPresupuesto, EtapaObra,
                   TareaPlanSemanal, TareaAvanceSemanal)
from services.alerts import upsert_alert_vigencia, log_activity_vigencia, limpiar_alertas_presupuestos_confirmados
from services.alertas_dashboard import obtener_alertas_para_dashboard, contar_alertas_por_severidad
from services.memberships import get_current_org_id
from services.obras_filters import obras_visibles_clause
from config.cache_config import cache_query
import io

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

try:  # pragma: no cover - optional dependency check
    import matplotlib  # noqa: F401
    CHARTS_ENABLED = True
except Exception:  # pragma: no cover - fallback for dev environments
    CHARTS_ENABLED = False

reportes_bp = Blueprint('reportes', __name__)


@reportes_bp.route('/audit-log')
@login_required
def audit_log():
    """Vista del registro de auditoría — solo super admin."""
    if not getattr(current_user, 'is_super_admin', False):
        flash('Acceso restringido a super administradores.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    from models.audit import AuditLog
    from datetime import datetime as dt

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = AuditLog.query
    if not current_user.is_super_admin:
        query = query.filter_by(organizacion_id=org_id)

    # Filtros
    accion = request.args.get('accion', '')
    entidad = request.args.get('entidad', '')
    desde = request.args.get('desde', '')
    hasta = request.args.get('hasta', '')

    if accion:
        query = query.filter_by(accion=accion)
    if entidad:
        query = query.filter_by(entidad=entidad)
    if desde:
        try:
            query = query.filter(AuditLog.timestamp >= dt.strptime(desde, '%Y-%m-%d'))
        except ValueError:
            pass
    if hasta:
        try:
            query = query.filter(AuditLog.timestamp <= dt.strptime(hasta + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            pass

    total = query.count()
    total_pages = (total + per_page - 1) // per_page
    logs = query.order_by(AuditLog.timestamp.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return render_template('reportes/audit_log.html',
                           logs=logs, page=page, total_pages=total_pages)


# ============================================================================
# Mapeo de categorías de inventario legacy → nombres alineados a etapas de obra
# ============================================================================
_MAPEO_CATEGORIAS = {
    # Materiales generales
    'material de construcción': 'Materiales de Construcción',
    'material de construccion': 'Materiales de Construcción',
    'materiales': 'Materiales de Construcción',
    # Estructura / encofrados
    'encofrados': 'Estructura y Encofrados',
    'encofrado': 'Estructura y Encofrados',
    'hierro': 'Estructura y Encofrados',
    'acero': 'Estructura y Encofrados',
    'hormigón': 'Estructura y Encofrados',
    'hormigon': 'Estructura y Encofrados',
    # Mampostería
    'mampostería': 'Mampostería',
    'mamposteria': 'Mampostería',
    'ladrillos': 'Mampostería',
    # Techos
    'techos': 'Techos e Impermeabilización',
    'cubiertas': 'Techos e Impermeabilización',
    'impermeabilización': 'Techos e Impermeabilización',
    'impermeabilizacion': 'Techos e Impermeabilización',
    'membranas': 'Techos e Impermeabilización',
    # Instalaciones eléctricas
    'instalaciones electricas': 'Instalaciones Eléctricas',
    'instalaciones eléctricas': 'Instalaciones Eléctricas',
    'electricidad': 'Instalaciones Eléctricas',
    # Instalaciones sanitarias
    'instalaciones sanitarias': 'Instalaciones Sanitarias',
    'sanitarios': 'Instalaciones Sanitarias',
    'plomería': 'Instalaciones Sanitarias',
    'plomeria': 'Instalaciones Sanitarias',
    # Instalaciones de gas
    'instalaciones de gas': 'Instalaciones de Gas',
    'gas': 'Instalaciones de Gas',
    # Climatización / complementarias
    'instalaciones climatizacion': 'Instalaciones Complementarias',
    'instalaciones climatización': 'Instalaciones Complementarias',
    'climatización': 'Instalaciones Complementarias',
    'climatizacion': 'Instalaciones Complementarias',
    'aire acondicionado': 'Instalaciones Complementarias',
    'calefacción': 'Instalaciones Complementarias',
    'calefaccion': 'Instalaciones Complementarias',
    'equipo contra incendios + maquinaria edificio': 'Instalaciones Complementarias',
    'equipo contra incendios': 'Instalaciones Complementarias',
    'incendios': 'Instalaciones Complementarias',
    # Pisos / revestimientos
    'pisos': 'Pisos y Revestimientos',
    'pisos y revestimientos': 'Pisos y Revestimientos',
    'revestimientos': 'Pisos y Revestimientos',
    'cerámicos': 'Pisos y Revestimientos',
    'ceramicos': 'Pisos y Revestimientos',
    # Revoques / yesería
    'revoques': 'Revoques y Terminaciones',
    'yesería': 'Revoques y Terminaciones',
    'yeseria': 'Revoques y Terminaciones',
    # Carpintería
    'carpintería': 'Carpintería',
    'carpinteria': 'Carpintería',
    # Pintura
    'pintura': 'Pintura',
    'pinturas': 'Pintura',
    # Herramientas / maquinaria
    'maquinarias': 'Equipos y Maquinaria',
    'maquinaria': 'Equipos y Maquinaria',
    'maquinaria edificio': 'Equipos y Maquinaria',
    'herramientas': 'Equipos y Maquinaria',
    'equipos': 'Equipos y Maquinaria',
    # Seguridad
    'seguridad': 'Seguridad e Higiene',
    'epp': 'Seguridad e Higiene',
}

def _normalizar_categoria(nombre_original):
    """Mapea nombre de categoría legacy a nombre alineado con etapas de obra."""
    if not nombre_original:
        return 'Sin Categoría'
    clave = nombre_original.strip().lower()
    return _MAPEO_CATEGORIAS.get(clave, nombre_original.strip().title())

@reportes_bp.route('/dashboard')
@login_required
def dashboard():
    # Si es operario, NO ve dashboard → lo mandamos a Mis Tareas
    if getattr(current_user, "role", None) == "operario":
        return redirect(url_for("obras.mis_tareas"))
    # Admin y PM siguen viendo el dashboard
    # Obtener fecha de filtro
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    
    if not fecha_desde:
        fecha_desde = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not fecha_hasta:
        fecha_hasta = date.today().strftime('%Y-%m-%d')
    
    # Convertir a objetos date
    try:
        fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
        fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
    except ValueError:
        fecha_desde_obj = date.today() - timedelta(days=30)
        fecha_hasta_obj = date.today()
        fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
        fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
    
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        flash('Selecciona una organización para ver el tablero.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion'))

    visible_clause = obras_visibles_clause(Obra)

    # KPIs principales
    kpis = calcular_kpis(fecha_desde_obj, fecha_hasta_obj, org_id=org_id, visible_clause=visible_clause)

    # Obras por estado
    obras_por_estado = db.session.query(
        Obra.estado,
        func.count(Obra.id)
    ).filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None)
    ).group_by(Obra.estado).all()

    # Obras con ubicación para el mapa (filtradas por organización)
    obras_con_ubicacion = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.direccion.isnot(None),
        Obra.direccion != ''
    ).all()

    # Presupuestos recientes
    presupuestos_recientes = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id,
        Presupuesto.deleted_at.is_(None)
    ).order_by(desc(Presupuesto.fecha_creacion)).limit(5).all()

    # Bulk update: marcar presupuestos expirados como vencidos en una sola query
    cambios_estado = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id,
        Presupuesto.deleted_at.is_(None),
        Presupuesto.fecha_vigencia.isnot(None),
        Presupuesto.fecha_vigencia < date.today(),
        Presupuesto.estado.in_(['borrador', 'enviado', 'rechazado'])
    ).update(
        {Presupuesto.estado: 'vencido'},
        synchronize_session=False
    )

    if cambios_estado:
        db.session.commit()

    # Limpiar alertas de presupuestos que ya fueron confirmados como obra o aprobados
    limpiar_alertas_presupuestos_confirmados(org_id)

    # SOLO mostrar alerta si hay presupuestos que realmente están vencidos Y necesitan atención
    # No contar presupuestos ya confirmados como obra, aprobados, o en estados finales
    presupuestos_vencidos_activos = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id,
        Presupuesto.deleted_at.is_(None),
        Presupuesto.estado == 'vencido',
        # Excluir presupuestos que ya fueron confirmados como obra
        Presupuesto.confirmado_como_obra == False
    ).count()

    presupuestos_vencidos = presupuestos_vencidos_activos

    presupuestos_monitoreo = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id,
        Presupuesto.deleted_at.is_(None),
        Presupuesto.fecha_vigencia.isnot(None),
        Presupuesto.estado.in_(['borrador', 'enviado', 'rechazado'])
    ).all()

    hoy = date.today()
    for presupuesto in presupuestos_monitoreo:
        dias = presupuesto.dias_restantes_vigencia
        if dias is None:
            continue
        if dias < 0:
            continue  # Ya se contabilizan como vencidos
        if dias <= 3:
            nivel = 'danger'
        elif dias <= 15:
            nivel = 'warning'
        else:
            nivel = 'info'

        upsert_alert_vigencia(presupuesto, dias, nivel, hoy)
        log_activity_vigencia(presupuesto, dias, hoy)

    if db.session.new or db.session.dirty:
        try:
            db.session.commit()
        except Exception as exc:  # pragma: no cover - logging defensivo
            current_app.logger.exception("Error guardando alertas de vigencia: %s", exc)
            db.session.rollback()

    # Items con stock bajo
    items_stock_bajo = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.stock_actual <= ItemInventario.stock_minimo,
        ItemInventario.activo == True
    ).order_by(ItemInventario.stock_actual).limit(10).all()

    # Obras próximas a vencer
    fecha_limite = date.today() + timedelta(days=7)
    obras_vencimiento = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.fecha_fin_estimada <= fecha_limite,
        Obra.fecha_fin_estimada >= date.today(),
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).order_by(Obra.fecha_fin_estimada).limit(5).all()

    # Rendimiento del equipo (últimos 30 días)
    rendimiento_equipo = calcular_rendimiento_equipo(fecha_desde_obj, fecha_hasta_obj, org_id=org_id)
    
    # Obras activas para el dashboard
    obras_activas = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).order_by(desc(Obra.fecha_creacion)).limit(10).all()

    # Encargados de obra (jefe_obra o supervisor) para cada obra activa
    encargados_obra = {}
    try:
        if obras_activas:
            obra_ids = [o.id for o in obras_activas]
            asignaciones_jefe = db.session.query(
                AsignacionObra.obra_id,
                Usuario.nombre,
                Usuario.apellido,
                AsignacionObra.rol_en_obra
            ).join(Usuario, AsignacionObra.usuario_id == Usuario.id).filter(
                AsignacionObra.obra_id.in_(obra_ids),
                AsignacionObra.activo == True,
                AsignacionObra.rol_en_obra.in_(['jefe_obra', 'supervisor'])
            ).all()
            # Priorizar jefe_obra sobre supervisor
            for obra_id, nombre, apellido, rol in asignaciones_jefe:
                if obra_id not in encargados_obra or rol == 'jefe_obra':
                    encargados_obra[obra_id] = {
                        'nombre': f"{nombre} {apellido or ''}".strip(),
                        'rol': 'Jefe de Obra' if rol == 'jefe_obra' else 'Supervisor'
                    }
    except Exception:
        db.session.rollback()

    # Alertas del sistema - obtener eventos recientes
    from models import Event

    # Feed de eventos para "Actividad Reciente" - últimos 25
    eventos_recientes = Event.query.filter(
        Event.company_id == org_id
    ).order_by(desc(Event.created_at)).limit(25).all()

    # Alertas de alta prioridad para el panel lateral (eventos del sistema)
    alertas_eventos = Event.query.filter(
        Event.company_id == org_id,
        Event.severity.in_(['media', 'alta', 'critica'])
    ).order_by(desc(Event.created_at)).limit(10).all()

    # Alertas reales del dashboard (stock, presupuestos, obras, tareas, sobrecosto)
    alertas_dashboard = obtener_alertas_para_dashboard(org_id, limite=10)
    conteo_alertas = contar_alertas_por_severidad(org_id)
    
    # Mostrar banner solo para administradores en entornos de desarrollo cuando los reportes están deshabilitados
    admin_checker = getattr(current_user, 'es_admin', None)
    if callable(admin_checker):
        is_admin_user = bool(admin_checker())
    else:
        role_attr = getattr(current_user, 'role', '') or getattr(current_user, 'rol', '')
        is_admin_user = str(role_attr).lower() in {'admin', 'administrador'}
        if not is_admin_user:
            role_helper = getattr(current_user, 'tiene_rol', None)
            if callable(role_helper):
                is_admin_user = bool(role_helper('admin'))

    env_name = (current_app.config.get('ENV') or '').lower()
    is_dev_env = current_app.debug or env_name in {'development', 'dev'}
    reports_service_enabled = bool(current_app.config.get('ENABLE_REPORTS_SERVICE'))
    # Solo advertir cuando se intentó habilitar el servicio pero faltan dependencias opcionales.
    should_warn_reports = reports_service_enabled and (not CHARTS_ENABLED)
    show_reports_banner = is_admin_user and is_dev_env and should_warn_reports

    # Datos financieros para gráficos
    datos_financieros = calcular_datos_financieros(obras_activas, org_id)

    # Checklist de onboarding (primeros pasos para usuario nuevo)
    onboarding_checklist = None
    try:
        from models import Organizacion as _Org, Cliente as _Cliente
        organizacion = db.session.get(_Org, org_id) if org_id else None
        total_obras = Obra.query.filter(
            Obra.organizacion_id == org_id,
            Obra.deleted_at.is_(None)
        ).count()
        total_usuarios = Usuario.query.filter_by(organizacion_id=org_id, activo=True).count()
        try:
            total_clientes = _Cliente.query.filter_by(organizacion_id=org_id).count()
        except Exception:
            total_clientes = 0
        try:
            from models.subcontratista import Subcontratista as _Sub
            total_subs = _Sub.query.filter_by(organizacion_id=org_id).count()
        except Exception:
            total_subs = 0

        def _safe_url(endpoint, **kwargs):
            try:
                return url_for(endpoint, **kwargs)
            except Exception:
                return '#'

        tiene_logo = bool(organizacion and getattr(organizacion, 'logo_url', None))
        tiene_obra = total_obras > 0
        tiene_equipo = total_usuarios > 1
        tiene_cliente = total_clientes > 0
        tiene_sub = total_subs > 0

        pasos = [
            {'id': 'logo', 'label': 'Subir logo de tu empresa', 'done': tiene_logo,
             'url': _safe_url('account.organizacion'), 'icon': 'fa-image'},
            {'id': 'cliente', 'label': 'Crear tu primer cliente', 'done': tiene_cliente,
             'url': _safe_url('clientes.crear') if 'clientes.crear' in current_app.view_functions else _safe_url('clientes.lista'),
             'icon': 'fa-user-tie'},
            {'id': 'obra', 'label': 'Crear tu primera obra (o cargar demo)', 'done': tiene_obra,
             'url': _safe_url('obras.lista'), 'icon': 'fa-building'},
            {'id': 'equipo', 'label': 'Invitar a tu equipo', 'done': tiene_equipo,
             'url': _safe_url('auth.usuarios_admin'), 'icon': 'fa-users'},
            {'id': 'sub', 'label': 'Agregar un subcontratista', 'done': tiene_sub,
             'url': _safe_url('subcontratistas.lista'), 'icon': 'fa-hard-hat'},
        ]

        completados = sum(1 for p in pasos if p['done'])
        total_pasos = len(pasos)
        porcentaje = int((completados / total_pasos) * 100) if total_pasos else 0

        # Mostrar solo si NO esta todo completado
        if completados < total_pasos:
            onboarding_checklist = {
                'pasos': pasos,
                'completados': completados,
                'total': total_pasos,
                'porcentaje': porcentaje,
            }
    except Exception as e:
        current_app.logger.warning(f"No se pudo calcular onboarding checklist: {e}")
        db.session.rollback()

    # KPIs de obras finalizadas (módulo cierre de obra)
    cierre_kpis = {
        'total': 0, 'mes_actual': 0, 'anio_actual': 0,
        'tiempo_promedio_dias': 0, 'desvio_promedio': 0,
        'ultimas': []
    }
    try:
        from models.cierre_obra import CierreObra
        from sqlalchemy import extract
        hoy_dt = date.today()

        base_q = CierreObra.query.filter(
            CierreObra.organizacion_id == org_id,
            CierreObra.estado == 'cerrado'
        )
        cierre_kpis['total'] = base_q.count()
        cierre_kpis['mes_actual'] = base_q.filter(
            extract('month', CierreObra.fecha_cierre_definitivo) == hoy_dt.month,
            extract('year', CierreObra.fecha_cierre_definitivo) == hoy_dt.year
        ).count()
        cierre_kpis['anio_actual'] = base_q.filter(
            extract('year', CierreObra.fecha_cierre_definitivo) == hoy_dt.year
        ).count()

        cierres_cerrados = base_q.filter(
            CierreObra.fecha_cierre_definitivo.isnot(None),
            CierreObra.fecha_inicio_cierre.isnot(None)
        ).all()
        if cierres_cerrados:
            dias_total = sum(
                max(0, (c.fecha_cierre_definitivo - c.fecha_inicio_cierre).days)
                for c in cierres_cerrados
            )
            cierre_kpis['tiempo_promedio_dias'] = round(dias_total / len(cierres_cerrados), 1)

            desvios = []
            for c in cierres_cerrados:
                if c.presupuesto_inicial and float(c.presupuesto_inicial) > 0 and c.monto_certificado is not None:
                    pi = float(c.presupuesto_inicial)
                    desvios.append(((float(c.monto_certificado) - pi) / pi) * 100)
            if desvios:
                cierre_kpis['desvio_promedio'] = round(sum(desvios) / len(desvios), 1)

        cierre_kpis['ultimas'] = base_q.order_by(
            desc(CierreObra.fecha_cierre_definitivo)
        ).limit(5).all()
    except Exception as e:
        current_app.logger.warning(f"No se pudieron calcular KPIs de cierre: {e}")
        db.session.rollback()

    # Entregas próximas de OC (próximos 7 días)
    entregas_proximas = []
    try:
        from models.inventory import OrdenCompra
        fecha_limite_oc = date.today() + timedelta(days=7)
        entregas_proximas = OrdenCompra.query.filter(
            OrdenCompra.organizacion_id == org_id,
            OrdenCompra.estado.in_(['emitida', 'recibida_parcial']),
            OrdenCompra.fecha_entrega_estimada.isnot(None),
            OrdenCompra.fecha_entrega_estimada <= fecha_limite_oc,
        ).order_by(OrdenCompra.fecha_entrega_estimada).all()
    except Exception:
        pass

    return render_template('reportes/dashboard.html',
                         kpis=kpis,
                         obras_activas=obras_activas,
                         eventos_recientes=eventos_recientes,
                         alertas=alertas_eventos,
                         alertas_dashboard=alertas_dashboard,
                         conteo_alertas=conteo_alertas,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         presupuestos_vencidos=presupuestos_vencidos,
                         items_stock_bajo=items_stock_bajo,
                         obras_vencimiento=obras_vencimiento,
                         charts_enabled=CHARTS_ENABLED,
                         show_reports_banner=show_reports_banner,
                         encargados_obra=encargados_obra,
                         datos_financieros=datos_financieros,
                         entregas_proximas=entregas_proximas,
                         cierre_kpis=cierre_kpis,
                         onboarding_checklist=onboarding_checklist,
                         fecha_hoy=date.today())


@reportes_bp.route('/alertas')
@login_required
def ver_alertas():
    """Muestra todas las alertas del sistema"""
    from services.alertas_dashboard import (
        obtener_alertas_stock_bajo,
        obtener_alertas_presupuestos_vencer,
        obtener_alertas_obras_demoradas,
        obtener_alertas_etapas_demoradas,
        obtener_alertas_tareas_vencidas,
        obtener_alertas_tareas_en_riesgo,
        obtener_alertas_sobrecosto,
        contar_alertas_por_severidad
    )

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        flash('Selecciona una organizacion para ver las alertas.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion'))

    # Obtener todas las alertas por categoria
    alertas_stock = obtener_alertas_stock_bajo(org_id, limite=20)
    alertas_presupuestos = obtener_alertas_presupuestos_vencer(org_id, limite=20)
    alertas_obras = obtener_alertas_obras_demoradas(org_id, limite=20)
    alertas_etapas = obtener_alertas_etapas_demoradas(org_id, limite=20)
    alertas_tareas = obtener_alertas_tareas_vencidas(org_id, limite=20)
    alertas_en_riesgo = obtener_alertas_tareas_en_riesgo(org_id, limite=20)
    alertas_sobrecosto = obtener_alertas_sobrecosto(org_id, limite=20)
    conteo = contar_alertas_por_severidad(org_id)

    return render_template('reportes/alertas.html',
                         alertas_stock=alertas_stock,
                         alertas_presupuestos=alertas_presupuestos,
                         alertas_obras=alertas_obras,
                         alertas_etapas=alertas_etapas,
                         alertas_tareas=alertas_tareas,
                         alertas_en_riesgo=alertas_en_riesgo,
                         alertas_sobrecosto=alertas_sobrecosto,
                         conteo=conteo)


@reportes_bp.route('/api/curva-s/<int:obra_id>')
@login_required
def api_curva_s(obra_id):
    """API: datos de Curva S (Planned Value vs Earned Value vs Actual Cost) por semana"""
    from flask import jsonify
    from models.projects import TareaEtapa

    obra = Obra.query.get_or_404(obra_id)
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if obra.organizacion_id != org_id:
        return jsonify({'error': 'No autorizado'}), 403

    tarea_ids = [t.id for t in TareaEtapa.query.filter_by(obra_id=obra_id).all()]

    semanas = []
    pv_acum = []
    ev_acum = []
    ac_acum = []

    if tarea_ids:
        # Planned Value semanal
        pv_data = db.session.query(
            TareaPlanSemanal.semana,
            func.sum(TareaPlanSemanal.pv_mo).label('pv')
        ).filter(
            TareaPlanSemanal.tarea_id.in_(tarea_ids)
        ).group_by(TareaPlanSemanal.semana).order_by(TareaPlanSemanal.semana).all()

        # Actual Cost y Earned Value semanal
        av_data = db.session.query(
            TareaAvanceSemanal.semana,
            func.sum(TareaAvanceSemanal.ac_mo).label('ac'),
            func.sum(TareaAvanceSemanal.ev_mo).label('ev')
        ).filter(
            TareaAvanceSemanal.tarea_id.in_(tarea_ids)
        ).group_by(TareaAvanceSemanal.semana).order_by(TareaAvanceSemanal.semana).all()

        # Unificar semanas
        all_weeks = sorted(set(
            [r.semana for r in pv_data] + [r.semana for r in av_data]
        ))

        pv_dict = {r.semana: float(r.pv or 0) for r in pv_data}
        ac_dict = {r.semana: float(r.ac or 0) for r in av_data}
        ev_dict = {r.semana: float(r.ev or 0) for r in av_data}

        acum_pv = 0
        acum_ev = 0
        acum_ac = 0

        for w in all_weeks:
            acum_pv += pv_dict.get(w, 0)
            acum_ev += ev_dict.get(w, 0)
            acum_ac += ac_dict.get(w, 0)
            semanas.append(w.strftime('%d/%m'))
            pv_acum.append(round(acum_pv, 0))
            ev_acum.append(round(acum_ev, 0))
            ac_acum.append(round(acum_ac, 0))

    # Si no hay datos EVM, usar etapas como fallback visual
    if not semanas:
        etapas = EtapaObra.query.filter_by(obra_id=obra_id).order_by(EtapaObra.orden).all()
        if etapas and obra.fecha_inicio:
            presupuesto = float(obra.presupuesto_total or 0)
            total_etapas = len(etapas)
            for i, etapa in enumerate(etapas, 1):
                label = etapa.fecha_fin_estimada.strftime('%d/%m') if etapa.fecha_fin_estimada else f'Et.{i}'
                semanas.append(label)
                pv_acum.append(round(presupuesto * i / total_etapas, 0))
                # EV based on actual progress
                progreso = float(etapa.porcentaje_avance_medicion or 0) / 100
                ev_acum.append(round(presupuesto * (sum(
                    float(e.porcentaje_avance_medicion or 0) for e in etapas[:i]
                ) / (100 * total_etapas)), 0))
            ac_acum = [round(float(obra.costo_real or 0) * (i / total_etapas), 0)
                       for i in range(1, total_etapas + 1)]

    return jsonify({
        'obra': obra.nombre,
        'semanas': semanas,
        'pv': pv_acum,
        'ev': ev_acum,
        'ac': ac_acum,
    })


def calcular_datos_financieros(obras_activas, org_id):
    """Calcula datos para gráficos financieros del dashboard"""
    datos = {
        'presupuesto_vs_real': [],
        'desglose_presupuesto': {'materiales': 0, 'mano_obra': 0, 'equipos': 0},
        'desglose_real': {'materiales': 0, 'mano_obra': 0, 'equipos': 0},
        'gastos_mensuales': [],
        'dias_stock': [],
    }

    if not obras_activas:
        return datos

    obra_ids = [o.id for o in obras_activas]

    # 1) Presupuesto vs Real por obra
    for obra in obras_activas:
        pres = float(obra.presupuesto_total or 0)
        real = float(obra.costo_real or 0)
        if pres > 0 or real > 0:
            datos['presupuesto_vs_real'].append({
                'nombre': obra.nombre[:25],
                'presupuesto': round(pres, 0),
                'real': round(real, 0),
                'porcentaje': round((real / pres) * 100, 1) if pres > 0 else 0,
            })

    # 2) Desglose por tipo (del presupuesto confirmado como obra)
    try:
        presupuesto_ids = [p.id for o in obras_activas
                          for p in (Presupuesto.query.filter_by(
                              obra_id=o.id, organizacion_id=org_id
                          ).filter(Presupuesto.deleted_at.is_(None)).all())]
        if presupuesto_ids:
            desglose = db.session.query(
                ItemPresupuesto.tipo,
                func.sum(ItemPresupuesto.total)
            ).filter(
                ItemPresupuesto.presupuesto_id.in_(presupuesto_ids)
            ).group_by(ItemPresupuesto.tipo).all()

            for tipo, total in desglose:
                total_f = float(total or 0)
                if tipo == 'material':
                    datos['desglose_presupuesto']['materiales'] = round(total_f, 0)
                elif tipo == 'mano_obra':
                    datos['desglose_presupuesto']['mano_obra'] = round(total_f, 0)
                elif tipo == 'equipo':
                    datos['desglose_presupuesto']['equipos'] = round(total_f, 0)
    except Exception:
        db.session.rollback()

    # 3) Desglose real: materiales (UsoInventario), MO (LiquidacionMO), Equipos (EquipmentUsage)
    try:
        # Materiales reales
        costo_materiales = db.session.query(
            func.coalesce(func.sum(
                UsoInventario.cantidad_usada * func.coalesce(
                    UsoInventario.precio_unitario_al_uso,
                    ItemInventario.precio_promedio
                )
            ), 0)
        ).join(ItemInventario).filter(
            UsoInventario.obra_id.in_(obra_ids)
        ).scalar() or 0
        datos['desglose_real']['materiales'] = round(float(costo_materiales), 0)

        # MO real
        from models import LiquidacionMO
        costo_mo = db.session.query(
            func.coalesce(func.sum(LiquidacionMO.monto_total), 0)
        ).filter(
            LiquidacionMO.obra_id.in_(obra_ids),
            LiquidacionMO.organizacion_id == org_id
        ).scalar() or 0
        datos['desglose_real']['mano_obra'] = round(float(costo_mo), 0)

        # Equipos real
        from models.equipment import Equipment, EquipmentUsage
        costo_equipos = db.session.query(
            func.coalesce(func.sum(EquipmentUsage.horas * Equipment.costo_hora), 0)
        ).join(Equipment).filter(
            EquipmentUsage.project_id.in_(obra_ids)
        ).scalar() or 0
        datos['desglose_real']['equipos'] = round(float(costo_equipos), 0)
    except Exception:
        db.session.rollback()

    # 4) Gastos mensuales (burn rate) - últimos 6 meses de UsoInventario
    try:
        hace_6_meses = date.today() - timedelta(days=180)
        gastos_mes = db.session.query(
            func.date_trunc('month', UsoInventario.fecha_uso).label('mes'),
            func.sum(
                UsoInventario.cantidad_usada * func.coalesce(
                    UsoInventario.precio_unitario_al_uso,
                    ItemInventario.precio_promedio
                )
            ).label('total')
        ).join(ItemInventario).filter(
            UsoInventario.obra_id.in_(obra_ids),
            UsoInventario.fecha_uso >= hace_6_meses
        ).group_by('mes').order_by('mes').all()

        for mes, total in gastos_mes:
            datos['gastos_mensuales'].append({
                'mes': mes.strftime('%b %Y') if mes else '',
                'total': round(float(total or 0), 0),
            })
    except Exception:
        db.session.rollback()

    # 5) Días de stock restante para items críticos
    try:
        fecha_30_dias = date.today() - timedelta(days=30)
        items_activos = ItemInventario.query.filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.activo == True,
            ItemInventario.stock_actual > 0
        ).all()

        item_ids = [i.id for i in items_activos]
        if item_ids:
            consumos = db.session.query(
                UsoInventario.item_id,
                func.sum(UsoInventario.cantidad_usada).label('consumo_30d')
            ).filter(
                UsoInventario.item_id.in_(item_ids),
                UsoInventario.fecha_uso >= fecha_30_dias
            ).group_by(UsoInventario.item_id).all()

            consumo_dict = {c.item_id: float(c.consumo_30d) for c in consumos}

            for item in items_activos:
                consumo_30 = consumo_dict.get(item.id, 0)
                if consumo_30 > 0:
                    consumo_diario = consumo_30 / 30.0
                    dias_restantes = float(item.stock_actual) / consumo_diario
                    if dias_restantes <= 30:  # Solo mostrar items con menos de 30 días
                        datos['dias_stock'].append({
                            'nombre': item.nombre[:30],
                            'stock': float(item.stock_actual),
                            'unidad': item.unidad or 'u',
                            'consumo_diario': round(consumo_diario, 1),
                            'dias': round(dias_restantes, 0),
                            'critico': dias_restantes <= 7,
                        })

            datos['dias_stock'].sort(key=lambda x: x['dias'])
            datos['dias_stock'] = datos['dias_stock'][:10]
    except Exception:
        db.session.rollback()

    return datos


def calcular_kpis(fecha_desde, fecha_hasta, *, org_id=None, visible_clause=None):
    """Calcula los KPIs principales del dashboard"""

    org_id = org_id or get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        return {
            'obras_activas': 0,
            'obras_nuevas_mes': 0,
            'costo_total': 0,
            'variacion_presupuesto': 0,
            'avance_promedio': 0,
            'obras_retrasadas': 0,
            'personal_activo': 0,
            'obras_con_personal': 0,
        }

    if visible_clause is None:
        visible_clause = obras_visibles_clause(Obra)

    # Obras activas
    obras_activas = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).count()

    # Obras nuevas este mes
    primer_dia_mes = date.today().replace(day=1)
    obras_nuevas_mes = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.fecha_creacion >= primer_dia_mes
    ).count()

    # Presupuesto total de obras activas (en millones)
    presupuesto_total = db.session.query(
        func.sum(Obra.presupuesto_total)
    ).filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    costo_total_millones = float(presupuesto_total) / 1000000 if presupuesto_total else 0

    # Costo real total
    costo_real_total = db.session.query(
        func.sum(Obra.costo_real)
    ).filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.estado.in_(['planificacion', 'en_curso']),
        Obra.costo_real.isnot(None)
    ).scalar() or 0

    # Porcentaje del presupuesto ejecutado (costo_real / presupuesto * 100)
    variacion_presupuesto = 0
    if float(presupuesto_total) > 0 and float(costo_real_total) > 0:
        variacion_presupuesto = (float(costo_real_total) / float(presupuesto_total)) * 100
    
    # Avance promedio de obras activas
    avance_promedio = db.session.query(
        func.avg(Obra.progreso)
    ).filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    
    # Obras retrasadas (progreso menor al esperado)
    obras_retrasadas = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.deleted_at.is_(None),
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).filter(
        Obra.progreso < 50  # Simplificado: menos del 50% se considera retrasado
    ).count()
    
    # Personal activo: contar miembros reales de la organización vía OrgMembership
    personal_activo = db.session.query(func.count(OrgMembership.id)).join(
        Usuario, OrgMembership.user_id == Usuario.id
    ).filter(
        OrgMembership.org_id == org_id,
        Usuario.activo == True,
        Usuario.is_super_admin.is_(False)
    ).scalar() or 0

    # Obras con personal asignado
    obras_con_personal = db.session.query(
        func.count(func.distinct(AsignacionObra.obra_id))
    ).join(Obra).filter(
        Obra.organizacion_id == org_id,
        visible_clause
    ).scalar() or 0
    
    return {
        'obras_activas': obras_activas,
        'obras_nuevas_mes': obras_nuevas_mes,
        'costo_total': costo_total_millones,
        'variacion_presupuesto': variacion_presupuesto,
        'avance_promedio': float(avance_promedio) if avance_promedio else 0,
        'obras_retrasadas': obras_retrasadas,
        'personal_activo': personal_activo,
        'obras_con_personal': obras_con_personal
    }

def calcular_rendimiento_equipo(fecha_desde, fecha_hasta, org_id=None):
    """Calcula el rendimiento del equipo en el período"""

    filtros = [
        Usuario.activo == True,
        RegistroTiempo.fecha >= fecha_desde,
        RegistroTiempo.fecha <= fecha_hasta
    ]
    if org_id is not None:
        filtros.append(Usuario.organizacion_id == org_id)

    rendimiento = db.session.query(
        Usuario.id,
        Usuario.nombre,
        Usuario.apellido,
        Usuario.rol,
        func.sum(RegistroTiempo.horas_trabajadas).label('total_horas'),
        func.count(RegistroTiempo.id).label('dias_trabajados')
    ).join(RegistroTiempo).filter(
        *filtros
    ).group_by(
        Usuario.id, Usuario.nombre, Usuario.apellido, Usuario.rol
    ).order_by(desc('total_horas')).limit(10).all()
    
    return rendimiento

@reportes_bp.route('/obras')
@login_required
def reporte_obras():
    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para ver reportes.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    estado = request.args.get('estado', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')

    # Base query con filtro de organización (excluir canceladas/eliminadas)
    query = Obra.query.filter(Obra.organizacion_id == org_id, Obra.deleted_at.is_(None))
    if not estado:
        query = query.filter(Obra.estado != 'cancelada')

    if estado:
        query = query.filter(Obra.estado == estado)

    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(Obra.fecha_inicio >= fecha_desde_obj)
        except ValueError:
            pass

    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(Obra.fecha_inicio <= fecha_hasta_obj)
        except ValueError:
            pass

    obras = query.order_by(desc(Obra.fecha_creacion)).all()

    # Calcular estadísticas básicas
    total_obras = len(obras)
    total_presupuesto = sum(float(obra.presupuesto_total or 0) for obra in obras)
    total_costo_real = sum(float(obra.costo_real or 0) for obra in obras)
    progreso_promedio = sum(obra.progreso or 0 for obra in obras) / total_obras if total_obras > 0 else 0

    # Calcular estadísticas avanzadas por obra
    obras_data = []
    for obra in obras:
        presupuesto = float(obra.presupuesto_total or 0)
        costo_real = float(obra.costo_real or 0)

        # Calcular costo de inventario usado en esta obra
        costo_inventario = db.session.query(
            func.coalesce(func.sum(
                UsoInventario.cantidad_usada * ItemInventario.precio_promedio
            ), 0)
        ).join(ItemInventario).filter(
            UsoInventario.obra_id == obra.id
        ).scalar() or 0

        # Calcular desvío presupuestario
        desvio = ((costo_real / presupuesto) - 1) * 100 if presupuesto > 0 else 0

        # Calcular rentabilidad estimada
        rentabilidad = presupuesto - costo_real if presupuesto > 0 else 0

        # Calcular días de obra
        dias_transcurridos = 0
        dias_estimados = 0
        if obra.fecha_inicio:
            fecha_fin = obra.fecha_fin_real or date.today()
            dias_transcurridos = (fecha_fin - obra.fecha_inicio).days

            if obra.fecha_fin_estimada:
                dias_estimados = (obra.fecha_fin_estimada - obra.fecha_inicio).days

        # Estado del cronograma
        if obra.estado == 'finalizada':
            estado_cronograma = 'completada'
        elif dias_estimados > 0 and dias_transcurridos > dias_estimados:
            estado_cronograma = 'retrasada'
        elif (obra.progreso or 0) > 0 and dias_estimados > 0:
            avance_esperado = (dias_transcurridos / dias_estimados) * 100
            if (obra.progreso or 0) >= avance_esperado - 5:
                estado_cronograma = 'en_tiempo'
            else:
                estado_cronograma = 'retrasada'
        else:
            estado_cronograma = 'sin_datos'

        # Consumo por rubro (para índices de construcción)
        from indices_construccion import (
            MAPEO_CATEGORIA_A_RUBRO, UNIDAD_POR_RUBRO, obtener_nombre_rubro,
        )
        from sqlalchemy.orm import joinedload as _jl

        usos_obra = UsoInventario.query.options(
            _jl(UsoInventario.item).joinedload(ItemInventario.categoria)
        ).filter(UsoInventario.obra_id == obra.id).all()

        consumo_rubros = {}
        for uso in usos_obra:
            cant = float(uso.cantidad_usada or 0)
            precio = float(uso.item.precio_promedio or 0)
            cat_nombre = ''
            if uso.item.categoria:
                cat_nombre = uso.item.categoria.nombre.lower().strip()
            else:
                cat_nombre = (uso.item.nombre or '').lower().strip()

            rubro = None
            for kw, rb in MAPEO_CATEGORIA_A_RUBRO.items():
                if kw in cat_nombre:
                    rubro = rb
                    break
            if rubro:
                if rubro not in consumo_rubros:
                    consumo_rubros[rubro] = {
                        'cantidad': 0, 'costo': 0,
                        'unidad': UNIDAD_POR_RUBRO.get(rubro, ''),
                        'nombre': obtener_nombre_rubro(rubro),
                    }
                consumo_rubros[rubro]['cantidad'] += cant
                consumo_rubros[rubro]['costo'] += cant * precio

        # Calcular costo por unidad por rubro
        indices_obra = []
        for rubro, datos in consumo_rubros.items():
            cpu = datos['costo'] / datos['cantidad'] if datos['cantidad'] > 0 else 0
            indices_obra.append({
                'nombre': datos['nombre'],
                'unidad': datos['unidad'],
                'cantidad': round(datos['cantidad'], 2),
                'costo_total': round(datos['costo'], 2),
                'costo_por_unidad': round(cpu, 2),
            })
        indices_obra.sort(key=lambda x: x['costo_total'], reverse=True)

        # ========== HORAS-HOMBRE (Fichadas) ==========
        horas_hombre = 0
        fichadas_count = 0
        try:
            from models.projects import Fichada
            fichadas_obra = Fichada.query.filter(Fichada.obra_id == obra.id).order_by(Fichada.fecha_hora).all()
            fichadas_count = len(fichadas_obra)
            # Emparejar ingresos con egresos por usuario y fecha
            ingresos_pendientes = {}
            for f in fichadas_obra:
                uid = f.usuario_id
                if f.tipo == 'ingreso':
                    ingresos_pendientes[uid] = f.fecha_hora
                elif f.tipo == 'egreso' and uid in ingresos_pendientes:
                    delta = (f.fecha_hora - ingresos_pendientes[uid]).total_seconds() / 3600.0
                    if 0 < delta < 24:  # Validar que sea razonable
                        horas_hombre += delta
                    del ingresos_pendientes[uid]
        except Exception:
            pass

        # ========== AVANCE POR ETAPAS ==========
        etapas_data = []
        try:
            etapas = EtapaObra.query.filter(EtapaObra.obra_id == obra.id).order_by(EtapaObra.orden).all()
            for etapa in etapas:
                etapas_data.append({
                    'nombre': etapa.nombre,
                    'estado': etapa.estado,
                    'progreso': etapa.progreso or 0,
                    'fecha_inicio': etapa.fecha_inicio_real or etapa.fecha_inicio_estimada,
                    'fecha_fin': etapa.fecha_fin_real or etapa.fecha_fin_estimada,
                })
        except Exception:
            pass

        total_etapas = len(etapas_data)
        etapas_finalizadas = len([e for e in etapas_data if e['estado'] == 'finalizada'])
        etapas_en_curso = len([e for e in etapas_data if e['estado'] == 'en_curso'])

        # ========== CERTIFICACIONES ==========
        total_certificado = 0
        certificaciones_count = 0
        try:
            from models.templates import WorkCertification
            certs = WorkCertification.query.filter(
                WorkCertification.obra_id == obra.id,
                WorkCertification.organizacion_id == org_id
            ).all()
            certificaciones_count = len(certs)
            total_certificado = sum(float(c.monto_certificado_ars or 0) for c in certs)
        except Exception:
            pass

        # Diferencia entre certificado y gastado
        diferencia_cert_costo = total_certificado - costo_real if total_certificado > 0 else 0

        # ========== COSTO MO y EQUIPOS por obra ==========
        costo_mo_obra = 0
        costo_eq_obra = 0
        try:
            from models import LiquidacionMO
            costo_mo_obra = float(db.session.query(
                func.coalesce(func.sum(LiquidacionMO.monto_total), 0)
            ).filter(LiquidacionMO.obra_id == obra.id,
                     LiquidacionMO.organizacion_id == org_id).scalar() or 0)
        except Exception:
            pass
        try:
            from models.equipment import Equipment, EquipmentUsage
            costo_eq_obra = float(db.session.query(
                func.coalesce(func.sum(EquipmentUsage.horas * Equipment.costo_hora), 0)
            ).join(Equipment).filter(EquipmentUsage.project_id == obra.id).scalar() or 0)
        except Exception:
            pass

        obras_data.append({
            'obra': obra,
            'presupuesto': presupuesto,
            'costo_real': costo_real,
            'costo_inventario': float(costo_inventario),
            'costo_materiales': float(costo_inventario),
            'costo_mo': costo_mo_obra,
            'costo_equipos': costo_eq_obra,
            'desvio': desvio,
            'rentabilidad': rentabilidad,
            'dias_transcurridos': dias_transcurridos,
            'dias_estimados': dias_estimados,
            'estado_cronograma': estado_cronograma,
            'indices_rubro': indices_obra,
            'horas_hombre': round(horas_hombre, 1),
            'fichadas_count': fichadas_count,
            'etapas': etapas_data,
            'total_etapas': total_etapas,
            'etapas_finalizadas': etapas_finalizadas,
            'etapas_en_curso': etapas_en_curso,
            'total_certificado': total_certificado,
            'certificaciones_count': certificaciones_count,
            'diferencia_cert_costo': diferencia_cert_costo,
        })

    # Estadísticas globales
    obras_con_sobrecosto = len([o for o in obras_data if o['desvio'] > 0])
    obras_retrasadas = len([o for o in obras_data if o['estado_cronograma'] == 'retrasada'])
    rentabilidad_total = sum(o['rentabilidad'] for o in obras_data)

    total_horas_hombre = sum(o['horas_hombre'] for o in obras_data)
    total_certificado_global = sum(o['total_certificado'] for o in obras_data)

    estadisticas = {
        'total_obras': total_obras,
        'total_presupuesto': total_presupuesto,
        'total_costo_real': total_costo_real,
        'progreso_promedio': progreso_promedio,
        'desvio_promedio': ((total_costo_real / total_presupuesto) - 1) * 100 if total_presupuesto > 0 else 0,
        'obras_con_sobrecosto': obras_con_sobrecosto,
        'obras_retrasadas': obras_retrasadas,
        'rentabilidad_total': rentabilidad_total,
        'obras_en_curso': len([o for o in obras if o.estado == 'en_curso']),
        'obras_finalizadas': len([o for o in obras if o.estado == 'finalizada']),
        'total_horas_hombre': round(total_horas_hombre, 1),
        'total_certificado': total_certificado_global,
    }

    # Desglose presupuesto por tipo (MO/Material/Equipo)
    desglose_presupuesto = {'materiales': 0, 'mano_obra': 0, 'equipos': 0}
    desglose_real = {'materiales': 0, 'mano_obra': 0, 'equipos': 0}
    try:
        obra_ids_list = [o.id for o in obras]
        if obra_ids_list:
            pres_ids = [p.id for p in Presupuesto.query.filter(
                Presupuesto.obra_id.in_(obra_ids_list),
                Presupuesto.organizacion_id == org_id,
                Presupuesto.deleted_at.is_(None)
            ).all()]
            if pres_ids:
                for tipo, total in db.session.query(
                    ItemPresupuesto.tipo, func.sum(ItemPresupuesto.total)
                ).filter(ItemPresupuesto.presupuesto_id.in_(pres_ids)
                ).group_by(ItemPresupuesto.tipo).all():
                    t = float(total or 0)
                    if tipo == 'material':
                        desglose_presupuesto['materiales'] = round(t, 0)
                    elif tipo == 'mano_obra':
                        desglose_presupuesto['mano_obra'] = round(t, 0)
                    elif tipo == 'equipo':
                        desglose_presupuesto['equipos'] = round(t, 0)

            # Real: materiales
            costo_mat = db.session.query(
                func.coalesce(func.sum(
                    UsoInventario.cantidad_usada * func.coalesce(
                        UsoInventario.precio_unitario_al_uso, ItemInventario.precio_promedio
                    )), 0)
            ).join(ItemInventario).filter(UsoInventario.obra_id.in_(obra_ids_list)).scalar() or 0
            desglose_real['materiales'] = round(float(costo_mat), 0)

            # Real: MO
            from models import LiquidacionMO
            costo_mo = db.session.query(
                func.coalesce(func.sum(LiquidacionMO.monto_total), 0)
            ).filter(LiquidacionMO.obra_id.in_(obra_ids_list),
                     LiquidacionMO.organizacion_id == org_id).scalar() or 0
            desglose_real['mano_obra'] = round(float(costo_mo), 0)

            # Real: Equipos
            from models.equipment import Equipment, EquipmentUsage
            costo_eq = db.session.query(
                func.coalesce(func.sum(EquipmentUsage.horas * Equipment.costo_hora), 0)
            ).join(Equipment).filter(EquipmentUsage.project_id.in_(obra_ids_list)).scalar() or 0
            desglose_real['equipos'] = round(float(costo_eq), 0)
    except Exception:
        db.session.rollback()

    return render_template('reportes/obras.html',
                         obras=obras,
                         obras_data=obras_data,
                         estadisticas=estadisticas,
                         desglose_presupuesto=desglose_presupuesto,
                         desglose_real=desglose_real,
                         estado=estado,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

@reportes_bp.route('/costos')
@login_required
@require_feature('reports.costos')
def reporte_costos():
    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para ver reportes de costos.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra_id = request.args.get('obra_id', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    agrupar_por = request.args.get('agrupar', 'obra')  # obra, categoria, mes

    # Obtener obras de la organización
    obras = Obra.query.filter(Obra.organizacion_id == org_id, Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

    # OPTIMIZACION: Base query con EAGER LOADING para evitar N+1
    from sqlalchemy.orm import joinedload
    query = UsoInventario.query.options(
        joinedload(UsoInventario.item).joinedload(ItemInventario.categoria),
        joinedload(UsoInventario.obra)
    ).join(ItemInventario).join(Obra).filter(
        Obra.organizacion_id == org_id
    )

    if obra_id:
        query = query.filter(UsoInventario.obra_id == obra_id)

    fecha_desde_obj = None
    fecha_hasta_obj = None

    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(UsoInventario.fecha_uso >= fecha_desde_obj)
        except ValueError:
            pass

    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(UsoInventario.fecha_uso <= fecha_hasta_obj)
        except ValueError:
            pass

    usos = query.order_by(desc(UsoInventario.fecha_uso)).all()

    # ========== COSTOS DE MANO DE OBRA (LiquidacionMO) ==========
    liquidaciones = []
    try:
        from models import LiquidacionMO
        liq_query = LiquidacionMO.query.join(Obra).filter(
            LiquidacionMO.organizacion_id == org_id
        )
        if obra_id:
            liq_query = liq_query.filter(LiquidacionMO.obra_id == obra_id)
        if fecha_desde_obj:
            liq_query = liq_query.filter(LiquidacionMO.fecha_liquidacion >= fecha_desde_obj)
        if fecha_hasta_obj:
            liq_query = liq_query.filter(LiquidacionMO.fecha_liquidacion <= fecha_hasta_obj)
        liquidaciones = liq_query.all()
    except Exception:
        pass

    # ========== COSTOS DE CAJA (MovimientoCaja) ==========
    gastos_caja = []
    costo_total_caja = 0
    try:
        from models.templates import MovimientoCaja
        caja_query = MovimientoCaja.query.join(Obra).filter(
            MovimientoCaja.organizacion_id == org_id,
            MovimientoCaja.estado == 'confirmado',
            MovimientoCaja.tipo.in_(['gasto_obra', 'pago_proveedor'])
        )
        if obra_id:
            caja_query = caja_query.filter(MovimientoCaja.obra_id == obra_id)
        if fecha_desde_obj:
            caja_query = caja_query.filter(MovimientoCaja.fecha_movimiento >= fecha_desde_obj)
        if fecha_hasta_obj:
            caja_query = caja_query.filter(MovimientoCaja.fecha_movimiento <= fecha_hasta_obj)
        gastos_caja = caja_query.order_by(desc(MovimientoCaja.fecha_movimiento)).all()
        costo_total_caja = sum(float(g.monto or 0) for g in gastos_caja)
    except Exception:
        pass

    # ========== COSTOS DE EQUIPOS (EquipmentUsage) ==========
    usos_equipos = []
    try:
        from models.equipment import Equipment, EquipmentUsage
        eq_query = db.session.query(EquipmentUsage, Equipment).join(Equipment).join(
            Obra, Obra.id == EquipmentUsage.project_id
        ).filter(Obra.organizacion_id == org_id)
        if obra_id:
            eq_query = eq_query.filter(EquipmentUsage.project_id == obra_id)
        if fecha_desde_obj:
            eq_query = eq_query.filter(EquipmentUsage.date >= fecha_desde_obj)
        if fecha_hasta_obj:
            eq_query = eq_query.filter(EquipmentUsage.date <= fecha_hasta_obj)
        usos_equipos = eq_query.all()
    except Exception:
        pass

    # Calcular costos detallados
    costo_total_ars = 0
    costo_total_usd = 0
    costos_por_obra = {}
    costos_por_categoria = {}
    costos_por_mes = {}
    materiales_mas_usados = {}

    for uso in usos:
        # Usar precio actual del item
        precio = float(uso.item.precio_promedio or 0)
        cantidad = float(uso.cantidad_usada or 0)
        costo_item = cantidad * precio

        # Por ahora todo en ARS (moneda por defecto)
        costo_total_ars += costo_item

        # Agrupar por obra
        obra_nombre = uso.obra.nombre if uso.obra else 'Sin obra'
        if obra_nombre not in costos_por_obra:
            costos_por_obra[obra_nombre] = {
                'ars': 0, 'usd': 0, 'items': 0,
                'materiales': 0, 'mano_obra': 0, 'equipos': 0,
                'presupuesto': float(uso.obra.presupuesto_total or 0) if uso.obra else 0,
                'obra_id': uso.obra.id if uso.obra else None
            }
        costos_por_obra[obra_nombre]['ars'] += costo_item
        costos_por_obra[obra_nombre]['materiales'] += costo_item
        costos_por_obra[obra_nombre]['items'] += 1

        # Agrupar por categoría
        categoria_nombre = uso.item.categoria.nombre if uso.item.categoria else 'Sin categoría'
        if categoria_nombre not in costos_por_categoria:
            costos_por_categoria[categoria_nombre] = {'ars': 0, 'usd': 0, 'items': 0}
        costos_por_categoria[categoria_nombre]['ars'] += costo_item
        costos_por_categoria[categoria_nombre]['items'] += 1

        # Agrupar por mes
        if uso.fecha_uso:
            mes_key = uso.fecha_uso.strftime('%Y-%m')
            mes_display = uso.fecha_uso.strftime('%B %Y')
            if mes_key not in costos_por_mes:
                costos_por_mes[mes_key] = {'display': mes_display, 'ars': 0, 'usd': 0, 'items': 0}
            costos_por_mes[mes_key]['ars'] += costo_item
            costos_por_mes[mes_key]['items'] += 1

        # Top materiales más usados
        material_nombre = uso.item.nombre
        if material_nombre not in materiales_mas_usados:
            materiales_mas_usados[material_nombre] = {
                'cantidad': 0, 'costo_ars': 0, 'costo_usd': 0,
                'unidad': uso.item.unidad, 'codigo': uso.item.codigo
            }
        materiales_mas_usados[material_nombre]['cantidad'] += cantidad
        materiales_mas_usados[material_nombre]['costo_ars'] += costo_item

    # ========== PROCESAR LIQUIDACIONES DE MO ==========
    for liq in liquidaciones:
        costo_mo = float(liq.monto_total or 0)
        costo_total_ars += costo_mo

        obra_obj = liq.obra if hasattr(liq, 'obra') and liq.obra else Obra.query.get(liq.obra_id)
        obra_nombre = obra_obj.nombre if obra_obj else 'Sin obra'
        if obra_nombre not in costos_por_obra:
            costos_por_obra[obra_nombre] = {
                'ars': 0, 'usd': 0, 'items': 0,
                'materiales': 0, 'mano_obra': 0, 'equipos': 0,
                'presupuesto': float(obra_obj.presupuesto_total or 0) if obra_obj else 0,
                'obra_id': obra_obj.id if obra_obj else None
            }
        costos_por_obra[obra_nombre]['ars'] += costo_mo
        costos_por_obra[obra_nombre]['mano_obra'] += costo_mo
        costos_por_obra[obra_nombre]['items'] += 1

        cat_mo = 'Mano de Obra'
        if cat_mo not in costos_por_categoria:
            costos_por_categoria[cat_mo] = {'ars': 0, 'usd': 0, 'items': 0}
        costos_por_categoria[cat_mo]['ars'] += costo_mo
        costos_por_categoria[cat_mo]['items'] += 1

        fecha_liq = liq.fecha_liquidacion if hasattr(liq, 'fecha_liquidacion') else None
        if fecha_liq:
            mes_key = fecha_liq.strftime('%Y-%m')
            mes_display = fecha_liq.strftime('%B %Y')
            if mes_key not in costos_por_mes:
                costos_por_mes[mes_key] = {'display': mes_display, 'ars': 0, 'usd': 0, 'items': 0}
            costos_por_mes[mes_key]['ars'] += costo_mo
            costos_por_mes[mes_key]['items'] += 1

    # ========== PROCESAR USO DE EQUIPOS ==========
    for usage, equip in usos_equipos:
        costo_eq = float(usage.horas or 0) * float(equip.costo_hora or 0)
        costo_total_ars += costo_eq

        obra_obj = Obra.query.get(usage.project_id) if usage.project_id else None
        obra_nombre = obra_obj.nombre if obra_obj else 'Sin obra'
        if obra_nombre not in costos_por_obra:
            costos_por_obra[obra_nombre] = {
                'ars': 0, 'usd': 0, 'items': 0,
                'materiales': 0, 'mano_obra': 0, 'equipos': 0,
                'presupuesto': float(obra_obj.presupuesto_total or 0) if obra_obj else 0,
                'obra_id': obra_obj.id if obra_obj else None
            }
        costos_por_obra[obra_nombre]['ars'] += costo_eq
        costos_por_obra[obra_nombre]['equipos'] += costo_eq
        costos_por_obra[obra_nombre]['items'] += 1

        cat_eq = 'Equipos / Maquinaria'
        if cat_eq not in costos_por_categoria:
            costos_por_categoria[cat_eq] = {'ars': 0, 'usd': 0, 'items': 0}
        costos_por_categoria[cat_eq]['ars'] += costo_eq
        costos_por_categoria[cat_eq]['items'] += 1

        if usage.date:
            mes_key = usage.date.strftime('%Y-%m')
            mes_display = usage.date.strftime('%B %Y')
            if mes_key not in costos_por_mes:
                costos_por_mes[mes_key] = {'display': mes_display, 'ars': 0, 'usd': 0, 'items': 0}
            costos_por_mes[mes_key]['ars'] += costo_eq
            costos_por_mes[mes_key]['items'] += 1

    # ========== PROCESAR GASTOS DE CAJA ==========
    for gasto in gastos_caja:
        costo_g = float(gasto.monto or 0)
        costo_total_ars += costo_g

        obra_obj = gasto.obra if hasattr(gasto, 'obra') and gasto.obra else None
        obra_nombre = obra_obj.nombre if obra_obj else 'Sin obra'
        if obra_nombre not in costos_por_obra:
            costos_por_obra[obra_nombre] = {
                'ars': 0, 'usd': 0, 'items': 0,
                'materiales': 0, 'mano_obra': 0, 'equipos': 0, 'caja': 0,
                'presupuesto': float(obra_obj.presupuesto_total or 0) if obra_obj else 0,
                'obra_id': obra_obj.id if obra_obj else None
            }
        if 'caja' not in costos_por_obra[obra_nombre]:
            costos_por_obra[obra_nombre]['caja'] = 0
        costos_por_obra[obra_nombre]['ars'] += costo_g
        costos_por_obra[obra_nombre]['caja'] += costo_g
        costos_por_obra[obra_nombre]['items'] += 1

        cat_caja = 'Gastos de Caja'
        if cat_caja not in costos_por_categoria:
            costos_por_categoria[cat_caja] = {'ars': 0, 'usd': 0, 'items': 0}
        costos_por_categoria[cat_caja]['ars'] += costo_g
        costos_por_categoria[cat_caja]['items'] += 1

        if gasto.fecha_movimiento:
            mes_key = gasto.fecha_movimiento.strftime('%Y-%m')
            mes_display = gasto.fecha_movimiento.strftime('%B %Y')
            if mes_key not in costos_por_mes:
                costos_por_mes[mes_key] = {'display': mes_display, 'ars': 0, 'usd': 0, 'items': 0}
            costos_por_mes[mes_key]['ars'] += costo_g
            costos_por_mes[mes_key]['items'] += 1

    # Ordenar top materiales por costo
    top_materiales = sorted(
        materiales_mas_usados.items(),
        key=lambda x: x[1]['costo_ars'] + x[1]['costo_usd'],
        reverse=True
    )[:10]

    # Ordenar meses cronológicamente
    costos_por_mes_ordenado = dict(sorted(costos_por_mes.items()))

    # Calcular comparativa con presupuestos
    analisis_obras = []
    for obra_nombre, datos in costos_por_obra.items():
        presupuesto = datos['presupuesto']
        costo_total_obra = datos['ars']  # Por ahora solo ARS para comparación
        desvio = ((costo_total_obra / presupuesto) - 1) * 100 if presupuesto > 0 else 0

        analisis_obras.append({
            'nombre': obra_nombre,
            'obra_id': datos['obra_id'],
            'presupuesto': presupuesto,
            'costo_real': costo_total_obra,
            'costo_usd': datos['usd'],
            'materiales': datos.get('materiales', 0),
            'mano_obra': datos.get('mano_obra', 0),
            'equipos': datos.get('equipos', 0),
            'desvio': desvio,
            'items_usados': datos['items'],
            'estado': 'sobrecosto' if desvio > 10 else 'alerta' if desvio > 0 else 'ok'
        })

    # Ordenar por desvío (peores primero)
    analisis_obras.sort(key=lambda x: x['desvio'], reverse=True)

    # --- Índices de construcción por rubro (costo/m², costo/m³, etc.) ---
    from indices_construccion import (
        MAPEO_CATEGORIA_A_RUBRO, UNIDAD_POR_RUBRO,
        obtener_nombre_rubro, SECCIONES_EDIFICIO,
    )

    consumo_por_rubro = {}  # {rubro: {cantidad, costo, unidad}}
    for uso in usos:
        cantidad = float(uso.cantidad_usada or 0)
        precio = float(uso.item.precio_promedio or 0)
        costo_item = cantidad * precio

        # Determinar rubro a partir de la categoría del item
        cat_nombre = ''
        if uso.item.categoria:
            cat_nombre = uso.item.categoria.nombre.lower().strip()
        else:
            cat_nombre = (uso.item.nombre or '').lower().strip()

        rubro = None
        for keyword, rubro_mapped in MAPEO_CATEGORIA_A_RUBRO.items():
            if keyword in cat_nombre:
                rubro = rubro_mapped
                break

        if rubro:
            if rubro not in consumo_por_rubro:
                consumo_por_rubro[rubro] = {
                    'cantidad': 0,
                    'costo': 0,
                    'unidad': UNIDAD_POR_RUBRO.get(rubro, ''),
                    'nombre': obtener_nombre_rubro(rubro),
                }
            consumo_por_rubro[rubro]['cantidad'] += cantidad
            consumo_por_rubro[rubro]['costo'] += costo_item

    # Calcular costo por unidad para cada rubro
    indices_rubro = []
    for rubro, datos in consumo_por_rubro.items():
        costo_unidad = datos['costo'] / datos['cantidad'] if datos['cantidad'] > 0 else 0
        indices_rubro.append({
            'rubro': rubro,
            'nombre': datos['nombre'],
            'unidad': datos['unidad'],
            'cantidad': round(datos['cantidad'], 2),
            'costo_total': round(datos['costo'], 2),
            'costo_por_unidad': round(costo_unidad, 2),
        })
    indices_rubro.sort(key=lambda x: x['costo_total'], reverse=True)

    # Incidencia por rubro (% del total)
    for idx in indices_rubro:
        idx['incidencia'] = round((idx['costo_total'] / costo_total_ars) * 100, 1) if costo_total_ars > 0 else 0

    estadisticas = {
        'costo_total_ars': costo_total_ars,
        'costo_total_usd': costo_total_usd,
        'total_usos': len(usos) + len(liquidaciones) + len(usos_equipos),
        'obras_con_costos': len(costos_por_obra),
        'categorias': len(costos_por_categoria),
        'promedio_diario': costo_total_ars / 30 if costo_total_ars > 0 else 0,
        'total_materiales': len(usos),
        'total_mo': len(liquidaciones),
        'total_equipos': len(usos_equipos),
    }

    return render_template('reportes/costos.html',
                         usos=usos,
                         obras=obras,
                         estadisticas=estadisticas,
                         costos_por_obra=costos_por_obra,
                         costos_por_categoria=costos_por_categoria,
                         costos_por_mes=costos_por_mes_ordenado,
                         top_materiales=top_materiales,
                         analisis_obras=analisis_obras,
                         indices_rubro=indices_rubro,
                         obra_id=obra_id,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         agrupar_por=agrupar_por)

@reportes_bp.route('/inventario')
@login_required
@require_feature('reports.inventario')
def reporte_inventario():
    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para ver reportes de inventario.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    tipo = request.args.get('tipo', '')
    stock_bajo = request.args.get('stock_bajo', '')
    ordenar_por = request.args.get('ordenar', 'nombre')  # nombre, valor, rotacion, stock

    # Base query con filtro de organización y EAGER LOADING de categoria
    from sqlalchemy.orm import joinedload
    query = ItemInventario.query.options(
        joinedload(ItemInventario.categoria)
    ).filter(ItemInventario.organizacion_id == org_id)

    if tipo:
        from models.inventory import InventoryCategory as IC
        query = query.join(IC, ItemInventario.categoria_id == IC.id).filter(IC.nombre.ilike(f'%{tipo}%'))

    if stock_bajo:
        query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)

    items = query.filter(ItemInventario.activo == True).all()

    # Período para análisis de rotación (últimos 90 días)
    fecha_90_dias = date.today() - timedelta(days=90)

    # OPTIMIZACION: Subquery de IDs activos de la org (evita IN con miles de IDs)
    item_ids_subq = db.session.query(ItemInventario.id).filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo == True
    ).subquery()

    # Obtener usos agrupados
    usos_query = db.session.query(
        UsoInventario.item_id,
        func.coalesce(func.sum(UsoInventario.cantidad_usada), 0).label('total_usos')
    ).filter(
        UsoInventario.item_id.in_(item_ids_subq),
        UsoInventario.fecha_uso >= fecha_90_dias
    ).group_by(UsoInventario.item_id).all()

    usos_dict = {u.item_id: float(u.total_usos) for u in usos_query}

    # Obtener últimos movimientos
    movimientos_query = db.session.query(
        MovimientoInventario.item_id,
        func.max(MovimientoInventario.fecha).label('ultima_fecha')
    ).filter(
        MovimientoInventario.item_id.in_(item_ids_subq)
    ).group_by(MovimientoInventario.item_id).all()

    movimientos_dict = {m.item_id: m.ultima_fecha for m in movimientos_query}

    # Calcular métricas por item (sin queries adicionales en el loop)
    items_data = []
    valor_total_ars = 0
    valor_total_usd = 0
    items_criticos = 0
    items_sin_movimiento = 0

    for item in items:
        stock = float(item.stock_actual or 0)
        precio_ars = float(item.precio_promedio or 0)
        precio_usd = float(item.precio_promedio_usd or 0)

        valor_ars = stock * precio_ars
        valor_usd = stock * precio_usd

        valor_total_ars += valor_ars
        valor_total_usd += valor_usd

        # Verificar si necesita reposición
        necesita_reposicion = item.necesita_reposicion
        if necesita_reposicion:
            items_criticos += 1

        # Obtener usos del diccionario (sin query)
        usos_90_dias = usos_dict.get(item.id, 0)

        # Calcular índice de rotación
        if stock > 0 and usos_90_dias > 0:
            rotacion = (usos_90_dias / stock) * 4  # Anualizado
        else:
            rotacion = 0

        # Obtener último movimiento del diccionario (sin query)
        ultimo_movimiento = movimientos_dict.get(item.id)

        dias_sin_movimiento = None
        if ultimo_movimiento:
            dias_sin_movimiento = (datetime.now() - ultimo_movimiento).days
            if dias_sin_movimiento > 90:
                items_sin_movimiento += 1
        else:
            items_sin_movimiento += 1
            dias_sin_movimiento = 999

        # Clasificación ABC basada en valor
        items_data.append({
            'item': item,
            'stock': stock,
            'precio_ars': precio_ars,
            'precio_usd': precio_usd,
            'valor_ars': valor_ars,
            'valor_usd': valor_usd,
            'usos_90_dias': usos_90_dias,
            'rotacion': rotacion,
            'dias_sin_movimiento': dias_sin_movimiento,
            'necesita_reposicion': necesita_reposicion,
            'categoria': _normalizar_categoria(item.categoria.nombre if item.categoria else None)
        })

    # Ordenar según criterio
    if ordenar_por == 'valor':
        items_data.sort(key=lambda x: x['valor_ars'], reverse=True)
    elif ordenar_por == 'rotacion':
        items_data.sort(key=lambda x: x['rotacion'], reverse=True)
    elif ordenar_por == 'stock':
        items_data.sort(key=lambda x: x['stock'], reverse=True)
    else:
        items_data.sort(key=lambda x: x['item'].nombre.lower())

    # Clasificación ABC (80-15-5)
    items_sorted_by_value = sorted(items_data, key=lambda x: x['valor_ars'], reverse=True)
    valor_acumulado = 0
    for i, item_data in enumerate(items_sorted_by_value):
        valor_acumulado += item_data['valor_ars']
        porcentaje_acumulado = (valor_acumulado / valor_total_ars * 100) if valor_total_ars > 0 else 0

        if porcentaje_acumulado <= 80:
            item_data['clasificacion_abc'] = 'A'
        elif porcentaje_acumulado <= 95:
            item_data['clasificacion_abc'] = 'B'
        else:
            item_data['clasificacion_abc'] = 'C'

    # Agrupar por categoría
    por_categoria = {}
    for item_data in items_data:
        cat = item_data['categoria']
        if cat not in por_categoria:
            por_categoria[cat] = {'items': 0, 'valor_ars': 0, 'valor_usd': 0}
        por_categoria[cat]['items'] += 1
        por_categoria[cat]['valor_ars'] += item_data['valor_ars']
        por_categoria[cat]['valor_usd'] += item_data['valor_usd']

    # Ordenar categorías por valor
    por_categoria = dict(sorted(por_categoria.items(), key=lambda x: x[1]['valor_ars'], reverse=True))

    # Top items más valiosos
    top_valor = sorted(items_data, key=lambda x: x['valor_ars'], reverse=True)[:10]

    # Top items más rotados
    top_rotacion = sorted(items_data, key=lambda x: x['rotacion'], reverse=True)[:10]

    # Items críticos (stock bajo)
    items_criticos_lista = [i for i in items_data if i['necesita_reposicion']]

    # Items sin movimiento (posible obsolescencia)
    items_obsoletos = [i for i in items_data if i['dias_sin_movimiento'] and i['dias_sin_movimiento'] > 90]

    estadisticas = {
        'total_items': len(items),
        'valor_total_ars': valor_total_ars,
        'valor_total_usd': valor_total_usd,
        'items_criticos': items_criticos,
        'items_sin_movimiento': items_sin_movimiento,
        'items_clase_a': len([i for i in items_data if i.get('clasificacion_abc') == 'A']),
        'items_clase_b': len([i for i in items_data if i.get('clasificacion_abc') == 'B']),
        'items_clase_c': len([i for i in items_data if i.get('clasificacion_abc') == 'C']),
        'categorias': len(por_categoria),
    }

    # Días de stock restante (proyección)
    dias_stock = []
    for item_d in items_data:
        if item_d.get('usos_90_dias', 0) > 0 and item_d.get('stock', 0) > 0:
            consumo_diario = item_d['usos_90_dias'] / 90.0
            dias_rest = item_d['stock'] / consumo_diario
            if dias_rest <= 60:
                dias_stock.append({
                    'nombre': item_d['item'].nombre[:30],
                    'stock': round(item_d['stock'], 1),
                    'unidad': item_d['item'].unidad or 'u',
                    'consumo_diario': round(consumo_diario, 1),
                    'dias': round(dias_rest, 0),
                    'critico': dias_rest <= 7,
                })
    dias_stock.sort(key=lambda x: x['dias'])

    # ========== MOVIMIENTOS RECIENTES (últimos 30 días) ==========
    fecha_30_dias = date.today() - timedelta(days=30)
    movimientos_recientes = []
    try:
        from sqlalchemy.orm import joinedload as _jl_inv
        movs = MovimientoInventario.query.options(
            _jl_inv(MovimientoInventario.item)
        ).join(ItemInventario).filter(
            ItemInventario.organizacion_id == org_id,
            MovimientoInventario.fecha >= fecha_30_dias
        ).order_by(desc(MovimientoInventario.fecha)).limit(20).all()

        for mov in movs:
            movimientos_recientes.append({
                'fecha': mov.fecha.strftime('%d/%m/%Y') if mov.fecha else '-',
                'item_nombre': mov.item.nombre if mov.item else '-',
                'tipo': mov.tipo,
                'cantidad': float(mov.cantidad or 0),
                'unidad': mov.item.unidad if mov.item else '',
                'motivo': mov.motivo or '',
                'observaciones': mov.observaciones or '',
            })
    except Exception:
        pass

    # ========== COSTO DE STOCK INMOVILIZADO ==========
    valor_inmovilizado = sum(d['valor_ars'] for d in items_data if d.get('dias_sin_movimiento', 0) > 90)

    estadisticas['valor_inmovilizado'] = valor_inmovilizado

    # Limitar tabla detallada a 100 items para performance del template
    items_data_table = items_data[:100]
    mostrar_mas = len(items_data) > 100

    return render_template('reportes/inventario.html',
                         items=items,
                         items_data=items_data_table,
                         total_items_real=len(items_data),
                         mostrar_mas=mostrar_mas,
                         estadisticas=estadisticas,
                         por_categoria=por_categoria,
                         top_valor=top_valor,
                         top_rotacion=top_rotacion,
                         items_criticos_lista=items_criticos_lista[:20],
                         items_obsoletos=items_obsoletos[:20],
                         dias_stock=dias_stock,
                         movimientos_recientes=movimientos_recientes,
                         tipo=tipo,
                         stock_bajo=stock_bajo,
                         ordenar_por=ordenar_por)


# ============================================
# EXPORTACION PDF DE REPORTES
# ============================================

@reportes_bp.route('/obras/pdf')
@login_required
def exportar_obras_pdf():
    """Exporta el reporte de obras a PDF"""
    if not WEASYPRINT_AVAILABLE:
        flash('La exportacion a PDF no esta disponible. Contacte al administrador.', 'warning')
        return redirect(url_for('reportes.reporte_obras'))

    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para exportar reportes.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    estado = request.args.get('estado', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')

    # Base query con filtro de organizacion
    query = Obra.query.filter(Obra.organizacion_id == org_id, Obra.deleted_at.is_(None))

    if estado:
        query = query.filter(Obra.estado == estado)

    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(Obra.fecha_inicio >= fecha_desde_obj)
        except ValueError:
            pass

    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(Obra.fecha_inicio <= fecha_hasta_obj)
        except ValueError:
            pass

    obras = query.order_by(desc(Obra.fecha_creacion)).all()

    # Calcular estadisticas
    total_obras = len(obras)
    total_presupuesto = sum(float(obra.presupuesto_total or 0) for obra in obras)
    total_costo_real = sum(float(obra.costo_real or 0) for obra in obras)
    progreso_promedio = sum(obra.progreso or 0 for obra in obras) / total_obras if total_obras > 0 else 0

    # Calcular estadisticas avanzadas por obra
    obras_data = []
    for obra in obras:
        presupuesto = float(obra.presupuesto_total or 0)
        costo_real = float(obra.costo_real or 0)
        desvio = ((costo_real / presupuesto) - 1) * 100 if presupuesto > 0 else 0
        rentabilidad = presupuesto - costo_real if presupuesto > 0 else 0

        dias_transcurridos = 0
        dias_estimados = 0
        if obra.fecha_inicio:
            fecha_fin = obra.fecha_fin_real or date.today()
            dias_transcurridos = (fecha_fin - obra.fecha_inicio).days
            if obra.fecha_fin_estimada:
                dias_estimados = (obra.fecha_fin_estimada - obra.fecha_inicio).days

        if obra.estado == 'finalizada':
            estado_cronograma = 'completada'
        elif dias_estimados > 0 and dias_transcurridos > dias_estimados:
            estado_cronograma = 'retrasada'
        elif (obra.progreso or 0) > 0 and dias_estimados > 0:
            avance_esperado = (dias_transcurridos / dias_estimados) * 100
            if (obra.progreso or 0) >= avance_esperado - 5:
                estado_cronograma = 'en_tiempo'
            else:
                estado_cronograma = 'retrasada'
        else:
            estado_cronograma = 'sin_datos'

        obras_data.append({
            'obra': obra,
            'presupuesto': presupuesto,
            'costo_real': costo_real,
            'desvio': desvio,
            'rentabilidad': rentabilidad,
            'dias_transcurridos': dias_transcurridos,
            'dias_estimados': dias_estimados,
            'estado_cronograma': estado_cronograma
        })

    obras_retrasadas = len([o for o in obras_data if o['estado_cronograma'] == 'retrasada'])

    estadisticas = {
        'total_obras': total_obras,
        'total_presupuesto': total_presupuesto,
        'total_costo_real': total_costo_real,
        'progreso_promedio': progreso_promedio,
        'desvio_promedio': ((total_costo_real / total_presupuesto) - 1) * 100 if total_presupuesto > 0 else 0,
        'obras_retrasadas': obras_retrasadas,
        'obras_en_curso': len([o for o in obras if o.estado == 'en_curso']),
        'obras_finalizadas': len([o for o in obras if o.estado == 'finalizada']),
    }

    filtros = {
        'estado': estado,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta
    }

    organizacion = Organizacion.query.get(org_id) if org_id else None

    # Desglose presupuesto y real por categoría
    desglose_presupuesto = {'materiales': 0, 'mano_obra': 0, 'equipos': 0}
    desglose_real = {'materiales': 0, 'mano_obra': 0, 'equipos': 0}
    try:
        obra_ids_list = [o.id for o in obras]
        if obra_ids_list:
            pres_ids = [p.id for p in Presupuesto.query.filter(
                Presupuesto.obra_id.in_(obra_ids_list),
                Presupuesto.organizacion_id == org_id,
                Presupuesto.deleted_at.is_(None)
            ).all()]
            if pres_ids:
                for tipo, total in db.session.query(
                    ItemPresupuesto.tipo, func.sum(ItemPresupuesto.total)
                ).filter(ItemPresupuesto.presupuesto_id.in_(pres_ids)
                ).group_by(ItemPresupuesto.tipo).all():
                    t = float(total or 0)
                    if tipo == 'material':
                        desglose_presupuesto['materiales'] = round(t, 0)
                    elif tipo == 'mano_obra':
                        desglose_presupuesto['mano_obra'] = round(t, 0)
                    elif tipo == 'equipo':
                        desglose_presupuesto['equipos'] = round(t, 0)

            costo_mat = db.session.query(
                func.coalesce(func.sum(
                    UsoInventario.cantidad_usada * func.coalesce(
                        UsoInventario.precio_unitario_al_uso, ItemInventario.precio_promedio
                    )), 0)
            ).join(ItemInventario).filter(UsoInventario.obra_id.in_(obra_ids_list)).scalar() or 0
            desglose_real['materiales'] = round(float(costo_mat), 0)

            from models import LiquidacionMO
            costo_mo = db.session.query(
                func.coalesce(func.sum(LiquidacionMO.monto_total), 0)
            ).filter(LiquidacionMO.obra_id.in_(obra_ids_list),
                     LiquidacionMO.organizacion_id == org_id).scalar() or 0
            desglose_real['mano_obra'] = round(float(costo_mo), 0)

            from models.equipment import Equipment, EquipmentUsage
            costo_eq = db.session.query(
                func.coalesce(func.sum(EquipmentUsage.horas * Equipment.costo_hora), 0)
            ).join(Equipment).filter(EquipmentUsage.project_id.in_(obra_ids_list)).scalar() or 0
            desglose_real['equipos'] = round(float(costo_eq), 0)
    except Exception:
        db.session.rollback()

    # Cargar logo como base64 (soporta local + S3/R2)
    logo_base64 = None
    logo_mime = 'image/png'
    if organizacion and getattr(organizacion, 'logo_url', None):
        try:
            import base64
            from services.storage_service import storage
            content = storage.read(organizacion.logo_url)
            if content:
                logo_base64 = base64.b64encode(content).decode('utf-8')
                ext = (organizacion.logo_url.rsplit('.', 1)[-1] or '').lower()
                logo_mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                             'png': 'image/png', 'webp': 'image/webp',
                             'svg': 'image/svg+xml'}.get(ext, 'image/png')
        except Exception as e:
            current_app.logger.warning(f"No se pudo cargar logo para reporte PDF: {e}")

    color_primario = (getattr(organizacion, 'color_primario', None) or '#1A374D') if organizacion else '#1A374D'

    # Renderizar HTML
    html_content = render_template('reportes/pdf_obras.html',
                                   obras_data=obras_data,
                                   estadisticas=estadisticas,
                                   filtros=filtros,
                                   organizacion=organizacion,
                                   usuario=current_user,
                                   desglose_presupuesto=desglose_presupuesto,
                                   desglose_real=desglose_real,
                                   logo_base64=logo_base64,
                                   logo_mime=logo_mime,
                                   color_primario=color_primario,
                                   fecha_generacion=datetime.now().strftime('%d/%m/%Y %H:%M'))

    # Convertir a PDF
    pdf_buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)

    filename = f"reporte_obras_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


@reportes_bp.route('/costos/pdf')
@login_required
def exportar_costos_pdf():
    """Exporta el reporte de costos a PDF"""
    if not WEASYPRINT_AVAILABLE:
        flash('La exportacion a PDF no esta disponible. Contacte al administrador.', 'warning')
        return redirect(url_for('reportes.reporte_costos'))

    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para exportar reportes.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra_id = request.args.get('obra_id', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')

    obras = Obra.query.filter(Obra.organizacion_id == org_id, Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

    # OPTIMIZACION: Eager loading para evitar N+1
    from sqlalchemy.orm import joinedload
    query = UsoInventario.query.options(
        joinedload(UsoInventario.item).joinedload(ItemInventario.categoria),
        joinedload(UsoInventario.obra)
    ).join(ItemInventario).join(Obra).filter(
        Obra.organizacion_id == org_id
    )

    obra_nombre = ''
    if obra_id:
        query = query.filter(UsoInventario.obra_id == obra_id)
        obra_sel = Obra.query.get(obra_id)
        obra_nombre = obra_sel.nombre if obra_sel else ''

    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(UsoInventario.fecha_uso >= fecha_desde_obj)
        except ValueError:
            pass

    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(UsoInventario.fecha_uso <= fecha_hasta_obj)
        except ValueError:
            pass

    usos = query.order_by(desc(UsoInventario.fecha_uso)).all()

    # ========== COSTOS DE MANO DE OBRA (LiquidacionMO) ==========
    liquidaciones = []
    try:
        from models import LiquidacionMO
        liq_query = LiquidacionMO.query.join(Obra).filter(
            LiquidacionMO.organizacion_id == org_id
        )
        if obra_id:
            liq_query = liq_query.filter(LiquidacionMO.obra_id == obra_id)
        if fecha_desde:
            try:
                fd = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
                liq_query = liq_query.filter(LiquidacionMO.fecha_liquidacion >= fd)
            except ValueError:
                pass
        if fecha_hasta:
            try:
                fh = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
                liq_query = liq_query.filter(LiquidacionMO.fecha_liquidacion <= fh)
            except ValueError:
                pass
        liquidaciones = liq_query.all()
    except Exception:
        pass

    # ========== COSTOS DE EQUIPOS (EquipmentUsage) ==========
    usos_equipos = []
    try:
        from models.equipment import Equipment, EquipmentUsage
        eq_query = db.session.query(EquipmentUsage, Equipment).join(Equipment).join(
            Obra, Obra.id == EquipmentUsage.project_id
        ).filter(Obra.organizacion_id == org_id)
        if obra_id:
            eq_query = eq_query.filter(EquipmentUsage.project_id == obra_id)
        if fecha_desde:
            try:
                fd = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
                eq_query = eq_query.filter(EquipmentUsage.date >= fd)
            except ValueError:
                pass
        if fecha_hasta:
            try:
                fh = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
                eq_query = eq_query.filter(EquipmentUsage.date <= fh)
            except ValueError:
                pass
        usos_equipos = eq_query.all()
    except Exception:
        pass

    # Calcular costos
    costo_total_ars = 0
    costos_por_obra = {}
    costos_por_categoria = {}
    materiales_mas_usados = {}

    for uso in usos:
        precio = float(uso.item.precio_promedio or 0)
        cantidad = float(uso.cantidad_usada or 0)
        costo_item = cantidad * precio
        costo_total_ars += costo_item

        obra_nombre_item = uso.obra.nombre if uso.obra else 'Sin obra'
        if obra_nombre_item not in costos_por_obra:
            costos_por_obra[obra_nombre_item] = {
                'ars': 0, 'items': 0,
                'presupuesto': float(uso.obra.presupuesto_total or 0) if uso.obra else 0,
                'obra_id': uso.obra.id if uso.obra else None
            }
        costos_por_obra[obra_nombre_item]['ars'] += costo_item
        costos_por_obra[obra_nombre_item]['items'] += 1

        categoria_nombre = uso.item.categoria.nombre if uso.item.categoria else 'Sin categoria'
        if categoria_nombre not in costos_por_categoria:
            costos_por_categoria[categoria_nombre] = {'ars': 0, 'items': 0}
        costos_por_categoria[categoria_nombre]['ars'] += costo_item
        costos_por_categoria[categoria_nombre]['items'] += 1

        material_nombre = uso.item.nombre
        if material_nombre not in materiales_mas_usados:
            materiales_mas_usados[material_nombre] = {
                'cantidad': 0, 'costo_ars': 0,
                'unidad': uso.item.unidad, 'codigo': uso.item.codigo
            }
        materiales_mas_usados[material_nombre]['cantidad'] += cantidad
        materiales_mas_usados[material_nombre]['costo_ars'] += costo_item

    # ========== PROCESAR LIQUIDACIONES DE MO (PDF) ==========
    for liq in liquidaciones:
        costo_mo = float(liq.monto_total or 0)
        costo_total_ars += costo_mo

        obra_obj = liq.obra if hasattr(liq, 'obra') and liq.obra else Obra.query.get(liq.obra_id)
        ob_nombre = obra_obj.nombre if obra_obj else 'Sin obra'
        if ob_nombre not in costos_por_obra:
            costos_por_obra[ob_nombre] = {
                'ars': 0, 'items': 0,
                'presupuesto': float(obra_obj.presupuesto_total or 0) if obra_obj else 0,
                'obra_id': obra_obj.id if obra_obj else None
            }
        costos_por_obra[ob_nombre]['ars'] += costo_mo
        costos_por_obra[ob_nombre]['items'] += 1

        cat_mo = 'Mano de Obra'
        if cat_mo not in costos_por_categoria:
            costos_por_categoria[cat_mo] = {'ars': 0, 'items': 0}
        costos_por_categoria[cat_mo]['ars'] += costo_mo
        costos_por_categoria[cat_mo]['items'] += 1

    # ========== PROCESAR USO DE EQUIPOS (PDF) ==========
    for usage, equip in usos_equipos:
        costo_eq = float(usage.horas or 0) * float(equip.costo_hora or 0)
        costo_total_ars += costo_eq

        obra_obj = Obra.query.get(usage.project_id) if usage.project_id else None
        ob_nombre = obra_obj.nombre if obra_obj else 'Sin obra'
        if ob_nombre not in costos_por_obra:
            costos_por_obra[ob_nombre] = {
                'ars': 0, 'items': 0,
                'presupuesto': float(obra_obj.presupuesto_total or 0) if obra_obj else 0,
                'obra_id': obra_obj.id if obra_obj else None
            }
        costos_por_obra[ob_nombre]['ars'] += costo_eq
        costos_por_obra[ob_nombre]['items'] += 1

        cat_eq = 'Equipos / Maquinaria'
        if cat_eq not in costos_por_categoria:
            costos_por_categoria[cat_eq] = {'ars': 0, 'items': 0}
        costos_por_categoria[cat_eq]['ars'] += costo_eq
        costos_por_categoria[cat_eq]['items'] += 1

    top_materiales = sorted(
        materiales_mas_usados.items(),
        key=lambda x: x[1]['costo_ars'],
        reverse=True
    )[:10]

    analisis_obras = []
    for ob_nombre, datos in costos_por_obra.items():
        presupuesto = datos['presupuesto']
        costo_total_obra = datos['ars']
        desvio = ((costo_total_obra / presupuesto) - 1) * 100 if presupuesto > 0 else 0
        analisis_obras.append({
            'nombre': ob_nombre,
            'obra_id': datos['obra_id'],
            'presupuesto': presupuesto,
            'costo_real': costo_total_obra,
            'desvio': desvio,
            'items_usados': datos['items'],
            'estado': 'sobrecosto' if desvio > 10 else 'alerta' if desvio > 0 else 'ok'
        })
    analisis_obras.sort(key=lambda x: x['desvio'], reverse=True)

    estadisticas = {
        'costo_total_ars': costo_total_ars,
        'total_usos': len(usos) + len(liquidaciones) + len(usos_equipos),
        'obras_con_costos': len(costos_por_obra),
        'categorias': len(costos_por_categoria),
        'promedio_diario': costo_total_ars / 30 if costo_total_ars > 0 else 0,
    }

    filtros = {
        'obra_id': obra_id,
        'obra_nombre': obra_nombre,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta
    }

    organizacion = Organizacion.query.get(org_id) if org_id else None

    html_content = render_template('reportes/pdf_costos.html',
                                   analisis_obras=analisis_obras,
                                   costos_por_categoria=costos_por_categoria,
                                   top_materiales=top_materiales,
                                   estadisticas=estadisticas,
                                   filtros=filtros,
                                   organizacion=organizacion,
                                   usuario=current_user,
                                   fecha_generacion=datetime.now().strftime('%d/%m/%Y %H:%M'))

    pdf_buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)

    filename = f"reporte_costos_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


@reportes_bp.route('/inventario/pdf')
@login_required
def exportar_inventario_pdf():
    """Exporta el reporte de inventario a PDF"""
    if not WEASYPRINT_AVAILABLE:
        flash('La exportacion a PDF no esta disponible. Contacte al administrador.', 'warning')
        return redirect(url_for('reportes.reporte_inventario'))

    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para exportar reportes.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    tipo = request.args.get('tipo', '')
    stock_bajo = request.args.get('stock_bajo', '')

    # OPTIMIZACION: Eager loading de categoria
    from sqlalchemy.orm import joinedload
    query = ItemInventario.query.options(
        joinedload(ItemInventario.categoria)
    ).filter(ItemInventario.organizacion_id == org_id)

    if tipo:
        from models.inventory import InventoryCategory as IC
        query = query.join(IC, ItemInventario.categoria_id == IC.id).filter(IC.nombre.ilike(f'%{tipo}%'))

    if stock_bajo:
        query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)

    items = query.filter(ItemInventario.activo == True).all()

    # OPTIMIZACION: Subquery + batch queries
    fecha_90_dias = date.today() - timedelta(days=90)
    item_ids_subq = db.session.query(ItemInventario.id).filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo == True
    ).subquery()

    usos_query = db.session.query(
        UsoInventario.item_id,
        func.coalesce(func.sum(UsoInventario.cantidad_usada), 0).label('total_usos')
    ).filter(
        UsoInventario.item_id.in_(item_ids_subq),
        UsoInventario.fecha_uso >= fecha_90_dias
    ).group_by(UsoInventario.item_id).all()
    usos_dict = {u.item_id: float(u.total_usos) for u in usos_query}

    movimientos_query = db.session.query(
        MovimientoInventario.item_id,
        func.max(MovimientoInventario.fecha).label('ultima_fecha')
    ).filter(
        MovimientoInventario.item_id.in_(item_ids_subq)
    ).group_by(MovimientoInventario.item_id).all()
    movimientos_dict = {m.item_id: m.ultima_fecha for m in movimientos_query}

    items_data = []
    valor_total_ars = 0
    valor_total_usd = 0
    items_criticos = 0
    items_sin_movimiento = 0

    for item in items:
        stock = float(item.stock_actual or 0)
        precio_ars = float(item.precio_promedio or 0)
        precio_usd = float(item.precio_promedio_usd or 0)
        valor_ars = stock * precio_ars
        valor_usd = stock * precio_usd
        valor_total_ars += valor_ars
        valor_total_usd += valor_usd

        necesita_reposicion = item.necesita_reposicion
        if necesita_reposicion:
            items_criticos += 1

        # Usar diccionarios en lugar de queries
        usos_90_dias = usos_dict.get(item.id, 0)

        if stock > 0 and usos_90_dias > 0:
            rotacion = (usos_90_dias / stock) * 4
        else:
            rotacion = 0

        ultimo_movimiento = movimientos_dict.get(item.id)

        dias_sin_movimiento = None
        if ultimo_movimiento:
            dias_sin_movimiento = (datetime.now() - ultimo_movimiento).days
            if dias_sin_movimiento > 90:
                items_sin_movimiento += 1
        else:
            items_sin_movimiento += 1
            dias_sin_movimiento = 999

        items_data.append({
            'item': item,
            'stock': stock,
            'precio_ars': precio_ars,
            'precio_usd': precio_usd,
            'valor_ars': valor_ars,
            'valor_usd': valor_usd,
            'usos_90_dias': usos_90_dias,
            'rotacion': rotacion,
            'dias_sin_movimiento': dias_sin_movimiento,
            'necesita_reposicion': necesita_reposicion,
            'categoria': _normalizar_categoria(item.categoria.nombre if item.categoria else None)
        })

    # Clasificacion ABC
    items_sorted_by_value = sorted(items_data, key=lambda x: x['valor_ars'], reverse=True)
    valor_acumulado = 0
    for item_data in items_sorted_by_value:
        valor_acumulado += item_data['valor_ars']
        porcentaje_acumulado = (valor_acumulado / valor_total_ars * 100) if valor_total_ars > 0 else 0
        if porcentaje_acumulado <= 80:
            item_data['clasificacion_abc'] = 'A'
        elif porcentaje_acumulado <= 95:
            item_data['clasificacion_abc'] = 'B'
        else:
            item_data['clasificacion_abc'] = 'C'

    # Agrupar por categoria
    por_categoria = {}
    for item_data in items_data:
        cat = item_data['categoria']
        if cat not in por_categoria:
            por_categoria[cat] = {'items': 0, 'valor_ars': 0, 'valor_usd': 0}
        por_categoria[cat]['items'] += 1
        por_categoria[cat]['valor_ars'] += item_data['valor_ars']
        por_categoria[cat]['valor_usd'] += item_data['valor_usd']
    por_categoria = dict(sorted(por_categoria.items(), key=lambda x: x[1]['valor_ars'], reverse=True))

    items_criticos_lista = [i for i in items_data if i['necesita_reposicion']]

    estadisticas = {
        'total_items': len(items),
        'valor_total_ars': valor_total_ars,
        'valor_total_usd': valor_total_usd,
        'items_criticos': items_criticos,
        'items_sin_movimiento': items_sin_movimiento,
        'items_clase_a': len([i for i in items_data if i.get('clasificacion_abc') == 'A']),
        'items_clase_b': len([i for i in items_data if i.get('clasificacion_abc') == 'B']),
        'items_clase_c': len([i for i in items_data if i.get('clasificacion_abc') == 'C']),
        'categorias': len(por_categoria),
    }

    filtros = {
        'tipo': tipo,
        'stock_bajo': stock_bajo
    }

    organizacion = Organizacion.query.get(org_id) if org_id else None

    # Limitar items para el PDF (WeasyPrint es lento con tablas grandes)
    items_data_pdf = items_data[:50]
    items_criticos_pdf = items_criticos_lista[:15]

    try:
        html_content = render_template('reportes/pdf_inventario.html',
                                       items_data=items_data_pdf,
                                       total_items_real=len(items_data),
                                       estadisticas=estadisticas,
                                       por_categoria=por_categoria,
                                       items_criticos_lista=items_criticos_pdf,
                                       filtros=filtros,
                                       organizacion=organizacion,
                                       usuario=current_user,
                                       fecha_generacion=datetime.now().strftime('%d/%m/%Y %H:%M'))

        pdf_buffer = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)

        filename = f"reporte_inventario_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f'Error al generar el PDF: {str(e)[:200]}', 'danger')
        return redirect(url_for('reportes.reporte_inventario'))


# ============================================================================
# REPORTE FINANCIERO — Rentabilidad, márgenes y flujo de caja por obra
# ============================================================================

@reportes_bp.route('/financiero')
@login_required
@require_feature('reports.financiero')
def reporte_financiero():
    """Dashboard financiero: rentabilidad por obra, márgenes y desglose de costos."""
    try:
        return _reporte_financiero_impl()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en reporte financiero: {e}", exc_info=True)
        flash(f'Error al generar reporte financiero: {str(e)[:200]}', 'danger')
        return redirect(url_for('reportes.dashboard'))


def _reporte_financiero_impl():
    if current_user.role not in ('admin', 'pm'):
        flash('No tienes permisos para ver el reporte financiero.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    from decimal import Decimal, ROUND_HALF_UP

    # Import defensivo de modelos de liquidación
    try:
        from models.templates import LiquidacionMO as LiqMO, LiquidacionMOItem
        HAS_LIQUIDACION = True
    except ImportError:
        HAS_LIQUIDACION = False

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        flash('Selecciona una organización para ver el reporte financiero.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion'))

    # Obras activas (no canceladas, no eliminadas)
    try:
        obras = Obra.query.filter(
            Obra.organizacion_id == org_id,
            Obra.deleted_at.is_(None),
            Obra.estado.notin_(['cancelada'])
        ).order_by(Obra.nombre).all()
    except Exception:
        db.session.rollback()
        # Fallback si deleted_at no existe aún en la BD
        obras = Obra.query.filter(
            Obra.organizacion_id == org_id,
            Obra.estado.notin_(['cancelada'])
        ).order_by(Obra.nombre).all()

    # ---------- Calcular costos desglosados por obra ----------
    obras_data = []
    total_presupuestado = Decimal('0')
    total_costo_real = Decimal('0')
    total_materiales = Decimal('0')
    total_mano_obra = Decimal('0')
    total_maquinaria = Decimal('0')

    # Chart data
    chart_nombres = []
    chart_presupuestos = []
    chart_costos_reales = []

    for obra in obras:
        presupuesto = Decimal(str(obra.presupuesto_total or 0))

        # 1. Costo materiales (from UsoInventario)
        costo_mat = db.session.query(
            func.coalesce(
                func.sum(
                    UsoInventario.cantidad_usada *
                    func.coalesce(UsoInventario.precio_unitario_al_uso, 0)
                ), 0
            )
        ).filter(UsoInventario.obra_id == obra.id).scalar()
        costo_mat = Decimal(str(costo_mat or 0))

        # 2. Costo mano de obra (from liquidaciones pagadas)
        costo_mo = Decimal('0')
        if HAS_LIQUIDACION:
            try:
                costo_mo_raw = db.session.query(
                    func.coalesce(func.sum(LiquidacionMOItem.monto), 0)
                ).join(LiqMO).filter(
                    LiqMO.obra_id == obra.id,
                    LiquidacionMOItem.estado == 'pagado'
                ).scalar() or 0
                costo_mo = Decimal(str(costo_mo_raw))
            except Exception:
                db.session.rollback()

        # 3. Costo maquinaria (from EquipmentUsage)
        costo_maq = Decimal('0')
        try:
            from models.equipment import EquipmentUsage, Equipment
            maq_raw = db.session.query(
                func.coalesce(func.sum(EquipmentUsage.horas * Equipment.costo_hora), 0)
            ).join(Equipment).filter(
                EquipmentUsage.project_id == obra.id,
                EquipmentUsage.estado == 'aprobado'
            ).scalar() or 0
            costo_maq = Decimal(str(maq_raw))
        except Exception:
            db.session.rollback()

        costo_total = costo_mat + costo_mo + costo_maq
        margen = presupuesto - costo_total
        pct_margen = (margen / presupuesto * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP) if presupuesto > 0 else Decimal('0')

        # Semáforo
        if pct_margen > 15:
            semaforo = 'verde'
        elif pct_margen >= 5:
            semaforo = 'amarillo'
        else:
            semaforo = 'rojo'

        obras_data.append({
            'obra': obra,
            'presupuesto': presupuesto,
            'costo_materiales': costo_mat,
            'costo_mano_obra': costo_mo,
            'costo_maquinaria': costo_maq,
            'costo_total': costo_total,
            'margen': margen,
            'pct_margen': float(pct_margen),
            'progreso': obra.progreso or 0,
            'semaforo': semaforo,
        })

        total_presupuestado += presupuesto
        total_costo_real += costo_total
        total_materiales += costo_mat
        total_mano_obra += costo_mo
        total_maquinaria += costo_maq

        # Chart data
        chart_nombres.append(obra.nombre[:25])
        chart_presupuestos.append(float(presupuesto))
        chart_costos_reales.append(float(costo_total))

    # ---------- Summary ----------
    margen_bruto = total_presupuestado - total_costo_real
    pct_margen_global = float(
        (margen_bruto / total_presupuestado * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    ) if total_presupuestado > 0 else 0.0

    # Otros costos (total - materiales - MO - maquinaria), mínimo 0
    otros = max(Decimal('0'), total_costo_real - total_materiales - total_mano_obra - total_maquinaria)

    resumen = {
        'total_presupuestado': total_presupuestado,
        'total_costo_real': total_costo_real,
        'margen_bruto': margen_bruto,
        'pct_margen': pct_margen_global,
    }

    # Pie chart data
    pie_labels = ['Materiales', 'Mano de Obra', 'Maquinaria', 'Otros']
    pie_values = [
        float(total_materiales),
        float(total_mano_obra),
        float(total_maquinaria),
        float(otros),
    ]

    return render_template('reportes/financiero.html',
                           resumen=resumen,
                           obras_data=obras_data,
                           chart_nombres=chart_nombres,
                           chart_presupuestos=chart_presupuestos,
                           chart_costos_reales=chart_costos_reales,
                           pie_labels=pie_labels,
                           pie_values=pie_values)
