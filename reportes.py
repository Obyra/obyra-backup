from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import func, desc
from app import db
from models import (
    Obra,
    Usuario,
    Presupuesto,
    ItemInventario,
    RegistroTiempo,
    AsignacionObra,
    UsoInventario,
    MovimientoInventario,
    CategoriaInventario,
)

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
        Event.severity.in_(['alta', 'critica'])
    ).order_by(desc(Event.created_at)).limit(10).all()
    
    return render_template('reportes/dashboard.html',
                         kpis=kpis,
                         obras_activas=obras_activas,
                         eventos_recientes=eventos_recientes,
                         alertas=alertas,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

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
    responsable_id = request.args.get('responsable_id', '')
    cliente = request.args.get('cliente', '').strip()
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')

    query = Obra.query.filter(Obra.organizacion_id == current_user.organizacion_id)

    if estado:
        query = query.filter(Obra.estado == estado)

    if responsable_id:
        try:
            responsable_id_int = int(responsable_id)
            query = query.join(AsignacionObra).filter(AsignacionObra.usuario_id == responsable_id_int)
        except ValueError:
            responsable_id_int = None
        else:
            query = query.distinct()
    else:
        responsable_id_int = None

    if cliente:
        like_value = f"%{cliente.lower()}%"
        query = query.filter(func.lower(Obra.cliente).like(like_value))

    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(Obra.fecha_inicio >= fecha_desde_obj)
        except ValueError:
            fecha_desde_obj = None
    else:
        fecha_desde_obj = None

    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(Obra.fecha_inicio <= fecha_hasta_obj)
        except ValueError:
            fecha_hasta_obj = None
    else:
        fecha_hasta_obj = None

    obras = query.order_by(desc(Obra.fecha_creacion)).all()

    total_obras = len(obras)
    total_presupuesto = sum(float(obra.presupuesto_total or 0) for obra in obras)
    total_costo_real = sum(float(obra.costo_real or 0) for obra in obras)
    progreso_promedio = sum(obra.progreso for obra in obras) / total_obras if total_obras > 0 else 0

    variacion_presupuestaria = 0
    if total_presupuesto:
        variacion_presupuestaria = ((total_costo_real - total_presupuesto) / total_presupuesto) * 100

    estadisticas = {
        'total_obras': total_obras,
        'total_presupuesto': total_presupuesto,
        'total_costo_real': total_costo_real,
        'progreso_promedio': progreso_promedio,
        'variacion_presupuestaria': variacion_presupuestaria,
    }

    resumen_por_estado = (
        query.with_entities(
            Obra.estado,
            func.count(Obra.id),
            func.avg(Obra.progreso),
            func.sum(Obra.presupuesto_total),
            func.sum(Obra.costo_real),
        )
        .group_by(Obra.estado)
        .all()
    )

    responsables = (
        Usuario.query.join(AsignacionObra)
        .join(Obra)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
        .distinct()
        .order_by(Usuario.nombre, Usuario.apellido)
        .all()
    )

    clientes_disponibles = (
        db.session.query(func.distinct(Obra.cliente))
        .filter(
            Obra.organizacion_id == current_user.organizacion_id,
            Obra.cliente.isnot(None),
            Obra.cliente != '',
        )
        .all()
    )

    clientes_disponibles = sorted(
        (row[0] for row in clientes_disponibles if row[0]),
        key=lambda nombre: nombre.lower(),
    )

    ranking_avance = sorted(obras, key=lambda o: o.progreso or 0, reverse=True)[:5]
    ranking_presupuesto = sorted(
        obras, key=lambda o: float(o.presupuesto_total or 0), reverse=True
    )[:5]

    estados_disponibles = [
        ('planificacion', 'Planificación'),
        ('en_curso', 'En curso'),
        ('pausada', 'Pausada'),
        ('finalizada', 'Finalizada'),
        ('cancelada', 'Cancelada'),
    ]

    return render_template(
        'reportes/obras.html',
        obras=obras,
        estadisticas=estadisticas,
        estado=estado,
        responsable_id=responsable_id,
        responsable_id_int=responsable_id_int,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cliente=cliente,
        resumen_por_estado=resumen_por_estado,
        responsables=responsables,
        estados_disponibles=estados_disponibles,
        ranking_avance=ranking_avance,
        ranking_presupuesto=ranking_presupuesto,
        clientes_disponibles=clientes_disponibles,
    )

@reportes_bp.route('/costos')
@login_required
def reporte_costos():
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para ver reportes de costos.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    obra_id = request.args.get('obra_id', '')
    categoria_id = request.args.get('categoria_id', '')
    responsable_id = request.args.get('responsable_id', '')
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')

    obras = (
        Obra.query.filter(Obra.organizacion_id == current_user.organizacion_id)
        .order_by(Obra.nombre)
        .all()
    )
    categorias = CategoriaInventario.query.order_by(CategoriaInventario.nombre).all()
    responsables = (
        Usuario.query.join(UsoInventario)
        .join(Obra)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
        .distinct()
        .order_by(Usuario.nombre, Usuario.apellido)
        .all()
    )

    query = (
        UsoInventario.query.join(ItemInventario)
        .join(Obra)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
    )

    if obra_id:
        try:
            obra_id_int = int(obra_id)
            query = query.filter(UsoInventario.obra_id == obra_id_int)
        except ValueError:
            obra_id_int = None
    else:
        obra_id_int = None

    if categoria_id:
        try:
            categoria_id_int = int(categoria_id)
            query = query.filter(ItemInventario.categoria_id == categoria_id_int)
        except ValueError:
            categoria_id_int = None
    else:
        categoria_id_int = None

    if responsable_id:
        try:
            responsable_id_int = int(responsable_id)
            query = query.filter(UsoInventario.usuario_id == responsable_id_int)
        except ValueError:
            responsable_id_int = None
    else:
        responsable_id_int = None

    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(UsoInventario.fecha_uso >= fecha_desde_obj)
        except ValueError:
            fecha_desde_obj = None
    else:
        fecha_desde_obj = None

    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(UsoInventario.fecha_uso <= fecha_hasta_obj)
        except ValueError:
            fecha_hasta_obj = None
    else:
        fecha_hasta_obj = None

    usos = query.order_by(desc(UsoInventario.fecha_uso)).all()

    costo_total = 0
    costos_por_obra = {}
    costos_por_categoria = {}
    costos_por_item = {}

    for uso in usos:
        precio_promedio = float(uso.item.precio_promedio or 0)
        costo_item = float(uso.cantidad_usada or 0) * precio_promedio
        costo_total += costo_item

        costos_por_obra.setdefault(uso.obra.nombre, 0)
        costos_por_obra[uso.obra.nombre] += costo_item

        categoria_nombre = uso.item.categoria.nombre if uso.item.categoria else 'Sin categoría'
        costos_por_categoria.setdefault(categoria_nombre, 0)
        costos_por_categoria[categoria_nombre] += costo_item

        costos_por_item.setdefault(uso.item.nombre, 0)
        costos_por_item[uso.item.nombre] += costo_item

    promedio_diario = 0
    if fecha_desde_obj and fecha_hasta_obj and fecha_hasta_obj >= fecha_desde_obj:
        dias = (fecha_hasta_obj - fecha_desde_obj).days + 1
        if dias > 0:
            promedio_diario = costo_total / dias

    movimientos_recientes = (
        MovimientoInventario.query.join(ItemInventario)
        .filter(ItemInventario.organizacion_id == current_user.organizacion_id)
        .order_by(desc(MovimientoInventario.fecha))
        .limit(20)
        .all()
    )

    costos_por_obra_items = sorted(costos_por_obra.items(), key=lambda item: item[1], reverse=True)
    costos_por_categoria_items = sorted(
        costos_por_categoria.items(), key=lambda item: item[1], reverse=True
    )
    costos_por_item_items = sorted(costos_por_item.items(), key=lambda item: item[1], reverse=True)

    return render_template(
        'reportes/costos.html',
        usos=usos,
        obras=obras,
        categorias=categorias,
        responsables=responsables,
        costo_total=costo_total,
        costos_por_obra_items=costos_por_obra_items,
        costos_por_categoria_items=costos_por_categoria_items,
        costos_por_item_items=costos_por_item_items,
        promedio_diario=promedio_diario,
        obra_id=obra_id,
        categoria_id=categoria_id,
        responsable_id=responsable_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        movimientos_recientes=movimientos_recientes,
    )

@reportes_bp.route('/inventario')
@login_required
def reporte_inventario():
    if not current_user.puede_acceder_modulo('reportes'):
        flash('No tienes permisos para ver reportes de inventario.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    tipo = request.args.get('tipo', '')
    categoria_id = request.args.get('categoria_id', '')
    stock_bajo = request.args.get('stock_bajo', '')

    categorias = CategoriaInventario.query.order_by(CategoriaInventario.nombre).all()
    tipos_disponibles = sorted({categoria.tipo for categoria in categorias})

    query = (
        ItemInventario.query.join(CategoriaInventario)
        .filter(ItemInventario.organizacion_id == current_user.organizacion_id)
    )

    if tipo:
        query = query.filter(CategoriaInventario.tipo == tipo)

    if categoria_id:
        try:
            categoria_id_int = int(categoria_id)
            query = query.filter(ItemInventario.categoria_id == categoria_id_int)
        except ValueError:
            categoria_id_int = None
    else:
        categoria_id_int = None

    if stock_bajo:
        query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)

    items = (
        query.filter(ItemInventario.activo.is_(True))
        .order_by(ItemInventario.nombre)
        .all()
    )

    valor_total = sum(float(item.stock_actual or 0) * float(item.precio_promedio or 0) for item in items)
    stock_total = sum(float(item.stock_actual or 0) for item in items)
    items_criticos = len([item for item in items if item.necesita_reposicion])
    porcentaje_critico = (items_criticos / len(items) * 100) if items else 0

    estadisticas = {
        'total_items': len(items),
        'valor_total': valor_total,
        'stock_total': stock_total,
        'items_criticos': items_criticos,
        'porcentaje_critico': porcentaje_critico,
    }

    consumos_recientes = (
        UsoInventario.query.join(ItemInventario)
        .filter(ItemInventario.organizacion_id == current_user.organizacion_id)
        .order_by(desc(UsoInventario.fecha_uso))
        .limit(20)
        .all()
    )

    movimientos_recientes = (
        MovimientoInventario.query.join(ItemInventario)
        .filter(ItemInventario.organizacion_id == current_user.organizacion_id)
        .order_by(desc(MovimientoInventario.fecha))
        .limit(20)
        .all()
    )

    return render_template(
        'reportes/inventario.html',
        items=items,
        estadisticas=estadisticas,
        tipo=tipo,
        categoria_id=categoria_id,
        categorias=categorias,
        tipos_disponibles=tipos_disponibles,
        stock_bajo=stock_bajo,
        consumos_recientes=consumos_recientes,
        movimientos_recientes=movimientos_recientes,
    )
