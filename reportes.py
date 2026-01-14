from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, send_file
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import func, desc
from app import db
from models import (Obra, Usuario, Presupuesto, ItemInventario, RegistroTiempo,
                   AsignacionObra, UsoInventario, MovimientoInventario, CategoriaInventario,
                   Organizacion)
from services.alerts import upsert_alert_vigencia, log_activity_vigencia, limpiar_alertas_presupuestos_confirmados
from services.alertas_dashboard import obtener_alertas_para_dashboard, contar_alertas_por_severidad
from services.memberships import get_current_org_id
from services.obras_filters import obras_visibles_clause
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
        visible_clause
    ).group_by(Obra.estado).all()

    # Obras con ubicación para el mapa (filtradas por organización)
    obras_con_ubicacion = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.direccion.isnot(None),
        Obra.direccion != ''
    ).all()

    # Presupuestos recientes
    presupuestos_recientes = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id
    ).order_by(desc(Presupuesto.fecha_creacion)).limit(5).all()

    # Buscar presupuestos que necesitan actualización de estado a "vencido"
    presupuestos_expirados = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id,
        Presupuesto.deleted_at.is_(None),
        Presupuesto.fecha_vigencia.isnot(None),
        Presupuesto.fecha_vigencia < date.today(),
        # Solo buscar presupuestos en estados que necesitan actualización
        Presupuesto.estado.in_(['borrador', 'enviado', 'rechazado'])
    ).all()

    cambios_estado = 0
    for presupuesto in presupuestos_expirados:
        presupuesto.estado = 'vencido'
        cambios_estado += 1

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
        Obra.fecha_fin_estimada <= fecha_limite,
        Obra.fecha_fin_estimada >= date.today(),
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).order_by(Obra.fecha_fin_estimada).limit(5).all()

    # Rendimiento del equipo (últimos 30 días)
    rendimiento_equipo = calcular_rendimiento_equipo(fecha_desde_obj, fecha_hasta_obj)
    
    # Obras activas para el dashboard
    obras_activas = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).order_by(desc(Obra.fecha_creacion)).limit(10).all()

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
                         show_reports_banner=show_reports_banner)


@reportes_bp.route('/alertas')
@login_required
def ver_alertas():
    """Muestra todas las alertas del sistema"""
    from services.alertas_dashboard import (
        obtener_alertas_stock_bajo,
        obtener_alertas_presupuestos_vencer,
        obtener_alertas_obras_demoradas,
        obtener_alertas_tareas_vencidas,
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
    alertas_tareas = obtener_alertas_tareas_vencidas(org_id, limite=20)
    alertas_sobrecosto = obtener_alertas_sobrecosto(org_id, limite=20)
    conteo = contar_alertas_por_severidad(org_id)

    return render_template('reportes/alertas.html',
                         alertas_stock=alertas_stock,
                         alertas_presupuestos=alertas_presupuestos,
                         alertas_obras=alertas_obras,
                         alertas_tareas=alertas_tareas,
                         alertas_sobrecosto=alertas_sobrecosto,
                         conteo=conteo)


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
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).count()

    # Obras nuevas este mes
    primer_dia_mes = date.today().replace(day=1)
    obras_nuevas_mes = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.fecha_creacion >= primer_dia_mes
    ).count()

    # Costo total de obras activas (en millones)
    costo_total = db.session.query(
        func.sum(Obra.presupuesto_total)
    ).filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    costo_total_millones = float(costo_total) / 1000000 if costo_total else 0
    
    # Variación vs presupuesto
    costo_real_total = db.session.query(
        func.sum(Obra.costo_real)
    ).filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.estado.in_(['planificacion', 'en_curso']),
        Obra.costo_real.isnot(None)
    ).scalar() or 0
    
    variacion_presupuesto = 0
    if costo_total > 0 and costo_real_total > 0:
        variacion_presupuesto = ((float(costo_real_total) - float(costo_total)) / float(costo_total)) * 100
    
    # Avance promedio de obras activas
    avance_promedio = db.session.query(
        func.avg(Obra.progreso)
    ).filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    
    # Obras retrasadas (progreso menor al esperado)
    obras_retrasadas = Obra.query.filter(
        Obra.organizacion_id == org_id,
        visible_clause,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).filter(
        Obra.progreso < 50  # Simplificado: menos del 50% se considera retrasado
    ).count()
    
    # Personal activo (excluir super administradores del sistema)
    personal_activo = Usuario.query.filter(
        Usuario.organizacion_id == org_id,
        Usuario.activo == True,
        Usuario.is_super_admin.is_(False)
    ).count()

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

def calcular_rendimiento_equipo(fecha_desde, fecha_hasta):
    """Calcula el rendimiento del equipo en el período"""
    
    rendimiento = db.session.query(
        Usuario.id,
        Usuario.nombre,
        Usuario.apellido,
        Usuario.rol,
        func.sum(RegistroTiempo.horas_trabajadas).label('total_horas'),
        func.count(RegistroTiempo.id).label('dias_trabajados')
    ).join(RegistroTiempo).filter(
        Usuario.activo == True,
        RegistroTiempo.fecha >= fecha_desde,
        RegistroTiempo.fecha <= fecha_hasta
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

    # Base query con filtro de organización
    query = Obra.query.filter(Obra.organizacion_id == org_id)

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

        obras_data.append({
            'obra': obra,
            'presupuesto': presupuesto,
            'costo_real': costo_real,
            'costo_inventario': float(costo_inventario),
            'desvio': desvio,
            'rentabilidad': rentabilidad,
            'dias_transcurridos': dias_transcurridos,
            'dias_estimados': dias_estimados,
            'estado_cronograma': estado_cronograma
        })

    # Estadísticas globales
    obras_con_sobrecosto = len([o for o in obras_data if o['desvio'] > 0])
    obras_retrasadas = len([o for o in obras_data if o['estado_cronograma'] == 'retrasada'])
    rentabilidad_total = sum(o['rentabilidad'] for o in obras_data)

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
    }

    return render_template('reportes/obras.html',
                         obras=obras,
                         obras_data=obras_data,
                         estadisticas=estadisticas,
                         estado=estado,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

@reportes_bp.route('/costos')
@login_required
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
    obras = Obra.query.filter(Obra.organizacion_id == org_id).order_by(Obra.nombre).all()

    # Base query para uso de inventario
    query = UsoInventario.query.join(ItemInventario).join(Obra).filter(
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
                'presupuesto': float(uso.obra.presupuesto_total or 0) if uso.obra else 0,
                'obra_id': uso.obra.id if uso.obra else None
            }
        costos_por_obra[obra_nombre]['ars'] += costo_item
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
            'desvio': desvio,
            'items_usados': datos['items'],
            'estado': 'sobrecosto' if desvio > 10 else 'alerta' if desvio > 0 else 'ok'
        })

    # Ordenar por desvío (peores primero)
    analisis_obras.sort(key=lambda x: x['desvio'], reverse=True)

    estadisticas = {
        'costo_total_ars': costo_total_ars,
        'costo_total_usd': costo_total_usd,
        'total_usos': len(usos),
        'obras_con_costos': len(costos_por_obra),
        'categorias': len(costos_por_categoria),
        'promedio_diario': costo_total_ars / 30 if costo_total_ars > 0 else 0,
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
                         obra_id=obra_id,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         agrupar_por=agrupar_por)

@reportes_bp.route('/inventario')
@login_required
def reporte_inventario():
    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para ver reportes de inventario.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    tipo = request.args.get('tipo', '')
    stock_bajo = request.args.get('stock_bajo', '')
    ordenar_por = request.args.get('ordenar', 'nombre')  # nombre, valor, rotacion, stock

    # Base query con filtro de organización
    query = ItemInventario.query.filter(ItemInventario.organizacion_id == org_id)

    if tipo:
        query = query.join(CategoriaInventario).filter(CategoriaInventario.tipo == tipo)

    if stock_bajo:
        query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)

    items = query.filter(ItemInventario.activo == True).all()

    # Calcular métricas por item
    items_data = []
    valor_total_ars = 0
    valor_total_usd = 0
    items_criticos = 0
    items_sin_movimiento = 0

    # Período para análisis de rotación (últimos 90 días)
    fecha_90_dias = date.today() - timedelta(days=90)

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

        # Calcular rotación de inventario (usos en últimos 90 días)
        usos_90_dias = db.session.query(
            func.coalesce(func.sum(UsoInventario.cantidad_usada), 0)
        ).filter(
            UsoInventario.item_id == item.id,
            UsoInventario.fecha_uso >= fecha_90_dias
        ).scalar() or 0

        # Calcular índice de rotación
        if stock > 0 and float(usos_90_dias) > 0:
            rotacion = (float(usos_90_dias) / stock) * 4  # Anualizado
        else:
            rotacion = 0

        # Items sin movimiento
        ultimo_movimiento = db.session.query(
            func.max(MovimientoInventario.fecha)
        ).filter(
            MovimientoInventario.item_id == item.id
        ).scalar()

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
            'usos_90_dias': float(usos_90_dias),
            'rotacion': rotacion,
            'dias_sin_movimiento': dias_sin_movimiento,
            'necesita_reposicion': necesita_reposicion,
            'categoria': item.categoria.nombre if item.categoria else 'Sin categoría'
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

    return render_template('reportes/inventario.html',
                         items=items,
                         items_data=items_data,
                         estadisticas=estadisticas,
                         por_categoria=por_categoria,
                         top_valor=top_valor,
                         top_rotacion=top_rotacion,
                         items_criticos_lista=items_criticos_lista,
                         items_obsoletos=items_obsoletos,
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
    query = Obra.query.filter(Obra.organizacion_id == org_id)

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

    # Renderizar HTML
    html_content = render_template('reportes/pdf_obras.html',
                                   obras_data=obras_data,
                                   estadisticas=estadisticas,
                                   filtros=filtros,
                                   organizacion=organizacion,
                                   usuario=current_user,
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

    obras = Obra.query.filter(Obra.organizacion_id == org_id).order_by(Obra.nombre).all()

    query = UsoInventario.query.join(ItemInventario).join(Obra).filter(
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
        'total_usos': len(usos),
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

    query = ItemInventario.query.filter(ItemInventario.organizacion_id == org_id)

    if tipo:
        query = query.join(CategoriaInventario).filter(CategoriaInventario.tipo == tipo)

    if stock_bajo:
        query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)

    items = query.filter(ItemInventario.activo == True).all()

    items_data = []
    valor_total_ars = 0
    valor_total_usd = 0
    items_criticos = 0
    items_sin_movimiento = 0
    fecha_90_dias = date.today() - timedelta(days=90)

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

        usos_90_dias = db.session.query(
            func.coalesce(func.sum(UsoInventario.cantidad_usada), 0)
        ).filter(
            UsoInventario.item_id == item.id,
            UsoInventario.fecha_uso >= fecha_90_dias
        ).scalar() or 0

        if stock > 0 and float(usos_90_dias) > 0:
            rotacion = (float(usos_90_dias) / stock) * 4
        else:
            rotacion = 0

        ultimo_movimiento = db.session.query(
            func.max(MovimientoInventario.fecha)
        ).filter(
            MovimientoInventario.item_id == item.id
        ).scalar()

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
            'usos_90_dias': float(usos_90_dias),
            'rotacion': rotacion,
            'dias_sin_movimiento': dias_sin_movimiento,
            'necesita_reposicion': necesita_reposicion,
            'categoria': item.categoria.nombre if item.categoria else 'Sin categoria'
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

    html_content = render_template('reportes/pdf_inventario.html',
                                   items_data=items_data,
                                   estadisticas=estadisticas,
                                   por_categoria=por_categoria,
                                   items_criticos_lista=items_criticos_lista,
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
