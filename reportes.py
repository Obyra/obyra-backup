from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import func, desc
from app import db
from models import (Obra, Usuario, Presupuesto, ItemInventario, RegistroTiempo,
                   AsignacionObra, UsoInventario, MovimientoInventario)

reportes_bp = Blueprint('reportes', __name__)

@reportes_bp.route('/dashboard')
@login_required
def dashboard():
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
    
    return render_template('reportes/dashboard.html',
                         kpis=kpis,
                         obras_por_estado=obras_por_estado,
                         obras_con_ubicacion=obras_con_ubicacion,
                         presupuestos_recientes=presupuestos_recientes,
                         items_stock_bajo=items_stock_bajo,
                         obras_vencimiento=obras_vencimiento,
                         rendimiento_equipo=rendimiento_equipo,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

def calcular_kpis(fecha_desde, fecha_hasta):
    """Calcula los KPIs principales del dashboard"""
    
    # Total de obras activas
    obras_activas = Obra.query.filter(
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).count()
    
    # Obras finalizadas en el período
    obras_finalizadas = Obra.query.filter(
        Obra.estado == 'finalizada',
        Obra.fecha_fin_real >= fecha_desde,
        Obra.fecha_fin_real <= fecha_hasta
    ).count()
    
    # Presupuestos generados en el período
    presupuestos_periodo = Presupuesto.query.filter(
        Presupuesto.fecha >= fecha_desde,
        Presupuesto.fecha <= fecha_hasta
    ).count()
    
    # Valor total de presupuestos aprobados
    valor_presupuestos = db.session.query(
        func.sum(Presupuesto.total_con_iva)
    ).filter(
        Presupuesto.estado == 'aprobado',
        Presupuesto.fecha >= fecha_desde,
        Presupuesto.fecha <= fecha_hasta
    ).scalar() or 0
    
    # Horas trabajadas en el período
    horas_trabajadas = db.session.query(
        func.sum(RegistroTiempo.horas_trabajadas)
    ).filter(
        RegistroTiempo.fecha >= fecha_desde,
        RegistroTiempo.fecha <= fecha_hasta
    ).scalar() or 0
    
    # Usuarios activos
    usuarios_activos = Usuario.query.filter_by(activo=True).count()
    
    # Items con stock crítico
    items_criticos = ItemInventario.query.filter(
        ItemInventario.stock_actual <= ItemInventario.stock_minimo,
        ItemInventario.activo == True
    ).count()
    
    # Progreso promedio de obras activas
    progreso_promedio = db.session.query(
        func.avg(Obra.progreso)
    ).filter(
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    
    return {
        'total_obras': obras_activas,
        'obras_finalizadas': obras_finalizadas,
        'presupuestos_periodo': presupuestos_periodo,
        'ingresos_totales': float(valor_presupuestos),
        'horas_trabajadas': float(horas_trabajadas),
        'total_usuarios': usuarios_activos,
        'alertas_inventario': items_criticos,
        'progreso_promedio': float(progreso_promedio)
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
