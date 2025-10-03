from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import func, desc
from app import db
from models import (Obra, Usuario, Presupuesto, ItemInventario, RegistroTiempo,
                   AsignacionObra, UsoInventario, MovimientoInventario)
from services.alerts import upsert_alert_vigencia, log_activity_vigencia

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
    
    # KPIs principales
    kpis = calcular_kpis(fecha_desde_obj, fecha_hasta_obj)
    
    # Obras por estado
    obras_por_estado = db.session.query(
        Obra.estado,
        func.count(Obra.id)
    ).filter(Obra.organizacion_id == current_user.organizacion_id).group_by(Obra.estado).all()
    
    # Obras con ubicación para el mapa (filtradas por organización)
    obras_con_ubicacion = Obra.query.filter(
        Obra.organizacion_id == current_user.organizacion_id,
        Obra.direccion.isnot(None),
        Obra.direccion != ''
    ).all()
    
    # Presupuestos recientes
    presupuestos_recientes = Presupuesto.query.filter(
        Presupuesto.organizacion_id == current_user.organizacion_id
    ).order_by(desc(Presupuesto.fecha_creacion)).limit(5).all()

    presupuestos_expirados = Presupuesto.query.filter(
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None),
        Presupuesto.fecha_vigencia.isnot(None),
        Presupuesto.fecha_vigencia < date.today(),
    ).all()

    cambios_estado = 0
    for presupuesto in presupuestos_expirados:
        if presupuesto.estado not in ['vencido', 'convertido', 'eliminado']:
            presupuesto.estado = 'vencido'
            cambios_estado += 1

    if cambios_estado:
        db.session.commit()

    presupuestos_vencidos = len(presupuestos_expirados)

    presupuestos_monitoreo = Presupuesto.query.filter(
        Presupuesto.organizacion_id == current_user.organizacion_id,
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
        ItemInventario.organizacion_id == current_user.organizacion_id,
        ItemInventario.stock_actual <= ItemInventario.stock_minimo,
        ItemInventario.activo == True
    ).order_by(ItemInventario.stock_actual).limit(10).all()
    
    # Obras próximas a vencer
    fecha_limite = date.today() + timedelta(days=7)
    obras_vencimiento = Obra.query.filter(
        Obra.organizacion_id == current_user.organizacion_id,
        Obra.fecha_fin_estimada <= fecha_limite,
        Obra.fecha_fin_estimada >= date.today(),
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).order_by(Obra.fecha_fin_estimada).limit(5).all()
    
    # Rendimiento del equipo (últimos 30 días)
    rendimiento_equipo = calcular_rendimiento_equipo(fecha_desde_obj, fecha_hasta_obj)
    
    # Obras activas para el dashboard
    obras_activas = Obra.query.filter(
        Obra.organizacion_id == current_user.organizacion_id,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).order_by(desc(Obra.fecha_creacion)).limit(10).all()
    
    # Alertas del sistema - obtener eventos recientes
    from models import Event
    
    # Feed de eventos para "Actividad Reciente" - últimos 25
    eventos_recientes = Event.query.filter(
        Event.company_id == current_user.organizacion_id
    ).order_by(desc(Event.created_at)).limit(25).all()
    
    # Alertas de alta prioridad para el panel lateral
    alertas = Event.query.filter(
        Event.company_id == current_user.organizacion_id,
        Event.severity.in_(['media', 'alta', 'critica'])
    ).order_by(desc(Event.created_at)).limit(10).all()
    
    return render_template('reportes/dashboard.html',
                         kpis=kpis,
                         obras_activas=obras_activas,
                         eventos_recientes=eventos_recientes,
                         alertas=alertas,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         presupuestos_vencidos=presupuestos_vencidos,
                         charts_enabled=CHARTS_ENABLED)

def calcular_kpis(fecha_desde, fecha_hasta):
    """Calcula los KPIs principales del dashboard"""
    
    # Filtrar por organización del usuario actual
    org_id = current_user.organizacion_id
    
    # Obras activas
    obras_activas = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).count()
    
    # Obras nuevas este mes
    primer_dia_mes = date.today().replace(day=1)
    obras_nuevas_mes = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.fecha_creacion >= primer_dia_mes
    ).count()
    
    # Costo total de obras activas (en millones)
    costo_total = db.session.query(
        func.sum(Obra.presupuesto_total)
    ).filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    costo_total_millones = float(costo_total) / 1000000 if costo_total else 0
    
    # Variación vs presupuesto
    costo_real_total = db.session.query(
        func.sum(Obra.costo_real)
    ).filter(
        Obra.organizacion_id == org_id,
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
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    
    # Obras retrasadas (progreso menor al esperado)
    obras_retrasadas = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).filter(
        Obra.progreso < 50  # Simplificado: menos del 50% se considera retrasado
    ).count()
    
    # Personal activo
    personal_activo = Usuario.query.filter(
        Usuario.organizacion_id == org_id,
        Usuario.activo == True
    ).count()
    
    # Obras con personal asignado
    obras_con_personal = db.session.query(
        func.count(func.distinct(AsignacionObra.obra_id))
    ).join(Obra).filter(
        Obra.organizacion_id == org_id
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
    
    estado = request.args.get('estado', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    
    query = Obra.query
    
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
    
    # Calcular estadísticas
    total_obras = len(obras)
    total_presupuesto = sum(obra.presupuesto_total for obra in obras if obra.presupuesto_total)
    progreso_promedio = sum(obra.progreso for obra in obras) / total_obras if total_obras > 0 else 0
    
    estadisticas = {
        'total_obras': total_obras,
        'total_presupuesto': float(total_presupuesto),
        'progreso_promedio': progreso_promedio
    }
    
    return render_template('reportes/obras.html',
                         obras=obras,
                         estadisticas=estadisticas,
                         estado=estado,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

@reportes_bp.route('/costos')
@login_required
def reporte_costos():
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para ver reportes de costos.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    obra_id = request.args.get('obra_id', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    
    obras = Obra.query.order_by(Obra.nombre).all()
    
    # Base query para uso de inventario
    query = UsoInventario.query.join(ItemInventario)
    
    if obra_id:
        query = query.filter(UsoInventario.obra_id == obra_id)
    
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
    costo_total = 0
    costos_por_obra = {}
    
    for uso in usos:
        costo_item = float(uso.cantidad_usada) * float(uso.item.precio_promedio)
        costo_total += costo_item
        
        if uso.obra.nombre not in costos_por_obra:
            costos_por_obra[uso.obra.nombre] = 0
        costos_por_obra[uso.obra.nombre] += costo_item
    
    return render_template('reportes/costos.html',
                         usos=usos,
                         obras=obras,
                         costo_total=costo_total,
                         costos_por_obra=costos_por_obra,
                         obra_id=obra_id,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

@reportes_bp.route('/inventario')
@login_required
def reporte_inventario():
    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para ver reportes de inventario.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    tipo = request.args.get('tipo', '')
    stock_bajo = request.args.get('stock_bajo', '')
    
    query = ItemInventario.query.join(CategoriaInventario)
    
    if tipo:
        query = query.filter(CategoriaInventario.tipo == tipo)
    
    if stock_bajo:
        query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)
    
    items = query.filter_by(activo=True).order_by(ItemInventario.nombre).all()
    
    # Calcular valor total del inventario
    valor_total = sum(float(item.stock_actual) * float(item.precio_promedio) for item in items)
    
    # Items críticos
    items_criticos = len([item for item in items if item.necesita_reposicion])
    
    estadisticas = {
        'total_items': len(items),
        'valor_total': valor_total,
        'items_criticos': items_criticos
    }
    
    return render_template('reportes/inventario.html',
                         items=items,
                         estadisticas=estadisticas,
                         tipo=tipo,
                         stock_bajo=stock_bajo)
