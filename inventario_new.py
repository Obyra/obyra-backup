from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app import db
from models import (
    InventoryCategory, InventoryItem, Warehouse, Stock, 
    StockMovement, StockReservation, Obra
)
from datetime import datetime
from sqlalchemy import func, and_

inventario_new_bp = Blueprint('inventario_new', __name__, url_prefix='/inventario')

def requires_role(*roles):
    """Decorator para verificar roles"""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.rol not in roles and not current_user.es_admin():
                flash('No tienes permisos para esta acción.', 'danger')
                return redirect(url_for('inventario_new.items'))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator

def get_json_response(data, status=200, error=None):
    """Genera respuesta JSON estándar"""
    if request.accept_mimetypes['application/json'] >= request.accept_mimetypes['text/html'] or request.args.get('format') == 'json':
        if error:
            return jsonify({'error': error}), status
        return jsonify(data), status
    return None

@inventario_new_bp.route('/')
@inventario_new_bp.route('/items')
@login_required
def items():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    # Filtros
    categoria_id = request.args.get('categoria')
    buscar = request.args.get('buscar')
    stock_bajo = request.args.get('stock_bajo')
    
    query = InventoryItem.query.filter_by(company_id=current_user.organizacion_id, activo=True)
    
    if categoria_id:
        query = query.filter(InventoryItem.categoria_id == categoria_id)
    
    if buscar:
        query = query.filter(
            db.or_(
                InventoryItem.sku.contains(buscar),
                InventoryItem.nombre.contains(buscar),
                InventoryItem.descripcion.contains(buscar)
            )
        )
    
    items = query.order_by(InventoryItem.nombre).all()
    
    # Filtrar por stock bajo si se solicita
    if stock_bajo:
        items = [item for item in items if item.is_low_stock]
    
    # Para JSON
    json_resp = get_json_response({
        'data': [
            {
                'id': item.id,
                'sku': item.sku,
                'nombre': item.nombre,
                'categoria': item.categoria.nombre,
                'total_stock': float(item.total_stock),
                'min_stock': float(item.min_stock),
                'is_low_stock': item.is_low_stock
            } for item in items
        ]
    })
    if json_resp:
        return json_resp
    
    # Obtener categorías para filtros
    categorias = InventoryCategory.query.filter_by(company_id=current_user.organizacion_id).all()
    
    return render_template('inventario_new/items.html', 
                         items=items, 
                         categorias=categorias,
                         filtros={'categoria': categoria_id, 'buscar': buscar, 'stock_bajo': stock_bajo})

@inventario_new_bp.route('/items/nuevo', methods=['GET', 'POST'])
@login_required
@requires_role('administrador', 'compras')
def nuevo_item():
    categorias = InventoryCategory.query.filter_by(company_id=current_user.organizacion_id).all()
    
    if request.method == 'POST':
        # Validaciones
        required_fields = ['sku', 'nombre', 'categoria_id', 'unidad']
        for field in required_fields:
            if not request.form.get(field):
                error = f'El campo {field} es obligatorio.'
                json_resp = get_json_response(None, 400, error)
                if json_resp:
                    return json_resp
                flash(error, 'danger')
                return render_template('inventario_new/item_form.html', categorias=categorias)
        
        # Verificar SKU único
        sku = request.form.get('sku')
        if InventoryItem.query.filter_by(sku=sku).first():
            error = 'Ya existe un item con ese SKU.'
            json_resp = get_json_response(None, 400, error)
            if json_resp:
                return json_resp
            flash(error, 'danger')
            return render_template('inventario_new/item_form.html', categorias=categorias)
        
        try:
            item = InventoryItem(
                company_id=current_user.organizacion_id,
                sku=sku,
                nombre=request.form.get('nombre'),
                categoria_id=request.form.get('categoria_id'),
                unidad=request.form.get('unidad'),
                min_stock=float(request.form.get('min_stock', 0)),
                descripcion=request.form.get('descripcion')
            )
            
            db.session.add(item)
            db.session.commit()
            
            json_resp = get_json_response({'id': item.id, 'mensaje': 'Item creado exitosamente'})
            if json_resp:
                return json_resp
                
            flash('Item creado exitosamente.', 'success')
            return redirect(url_for('inventario_new.detalle_item', id=item.id))
            
        except Exception as e:
            db.session.rollback()
            error = 'Error al crear el item.'
            json_resp = get_json_response(None, 500, error)
            if json_resp:
                return json_resp
            flash(error, 'danger')
    
    return render_template('inventario_new/item_form.html', categorias=categorias, item=None)

@inventario_new_bp.route('/items/<int:id>')
@login_required
def detalle_item(id):
    item = InventoryItem.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    # Obtener stocks por depósito
    stocks = Stock.query.filter_by(item_id=id).join(Warehouse).all()
    
    # Obtener movimientos recientes
    movimientos = StockMovement.query.filter_by(item_id=id).order_by(StockMovement.fecha.desc()).limit(20).all()
    
    # Obtener reservas activas
    reservas = StockReservation.query.filter_by(item_id=id, estado='activa').all()
    
    json_resp = get_json_response({
        'item': {
            'id': item.id,
            'sku': item.sku,
            'nombre': item.nombre,
            'total_stock': float(item.total_stock),
            'reserved_stock': float(item.reserved_stock),
            'available_stock': float(item.available_stock),
            'is_low_stock': item.is_low_stock
        },
        'stocks': [
            {
                'warehouse': stock.warehouse.nombre,
                'cantidad': float(stock.cantidad)
            } for stock in stocks
        ]
    })
    if json_resp:
        return json_resp
    
    return render_template('inventario_new/item_detalle.html', 
                         item=item, 
                         stocks=stocks,
                         movimientos=movimientos,
                         reservas=reservas)

@inventario_new_bp.route('/warehouses')
@login_required
def warehouses():
    warehouses = Warehouse.query.filter_by(company_id=current_user.organizacion_id, activo=True).all()
    
    json_resp = get_json_response({
        'data': [
            {
                'id': wh.id,
                'nombre': wh.nombre,
                'direccion': wh.direccion,
                'items_count': len(wh.stocks)
            } for wh in warehouses
        ]
    })
    if json_resp:
        return json_resp
    
    return render_template('inventario_new/warehouses.html', warehouses=warehouses)

@inventario_new_bp.route('/warehouses/nuevo', methods=['POST'])
@login_required
@requires_role('administrador', 'compras')
def nuevo_warehouse():
    nombre = request.form.get('nombre')
    
    if not nombre:
        error = 'El nombre del depósito es obligatorio.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
        return redirect(url_for('inventario_new.warehouses'))
    
    try:
        warehouse = Warehouse(
            company_id=current_user.organizacion_id,
            nombre=nombre,
            direccion=request.form.get('direccion')
        )
        
        db.session.add(warehouse)
        db.session.commit()
        
        json_resp = get_json_response({'id': warehouse.id, 'mensaje': 'Depósito creado exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Depósito creado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al crear el depósito.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.warehouses'))

@inventario_new_bp.route('/movimientos', methods=['GET', 'POST'])
@login_required
def movimientos():
    if request.method == 'POST' and current_user.rol in ['administrador', 'compras']:
        return crear_movimiento()
    
    # Listar movimientos
    movimientos = StockMovement.query.join(InventoryItem).filter(
        InventoryItem.company_id == current_user.organizacion_id
    ).order_by(StockMovement.fecha.desc()).limit(50).all()
    
    json_resp = get_json_response({
        'data': [
            {
                'id': mov.id,
                'item': mov.item.nombre,
                'tipo': mov.tipo,
                'cantidad': float(mov.qty),
                'warehouse': mov.warehouse_display,
                'fecha': mov.fecha.isoformat(),
                'usuario': mov.user.nombre_completo
            } for mov in movimientos
        ]
    })
    if json_resp:
        return json_resp
    
    # Obtener datos para el formulario
    items = InventoryItem.query.filter_by(company_id=current_user.organizacion_id, activo=True).all()
    warehouses = Warehouse.query.filter_by(company_id=current_user.organizacion_id, activo=True).all()
    projects = Obra.query.filter_by(organizacion_id=current_user.organizacion_id).all()
    
    return render_template('inventario_new/movimientos.html', 
                         movimientos=movimientos,
                         items=items,
                         warehouses=warehouses,
                         projects=projects)

def crear_movimiento():
    """Crea un nuevo movimiento de stock"""
    item_id = request.form.get('item_id')
    tipo = request.form.get('tipo')
    qty = request.form.get('qty')
    motivo = request.form.get('motivo')
    
    if not all([item_id, tipo, qty, motivo]):
        error = 'Todos los campos son obligatorios.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
        return redirect(url_for('inventario_new.movimientos'))
    
    try:
        qty = float(qty)
        if qty <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")
            
        item = InventoryItem.query.get(item_id)
        
        # Validaciones específicas por tipo
        if tipo == 'ingreso':
            warehouse_id = request.form.get('destino_warehouse_id')
            if not warehouse_id:
                raise ValueError("Depósito destino es obligatorio para ingresos")
            movimiento = crear_movimiento_ingreso(item, qty, warehouse_id, motivo)
            
        elif tipo == 'egreso':
            warehouse_id = request.form.get('origen_warehouse_id')
            if not warehouse_id:
                raise ValueError("Depósito origen es obligatorio para egresos")
            movimiento = crear_movimiento_egreso(item, qty, warehouse_id, motivo)
            
        elif tipo == 'transferencia':
            origen_id = request.form.get('origen_warehouse_id')
            destino_id = request.form.get('destino_warehouse_id')
            if not all([origen_id, destino_id]):
                raise ValueError("Depósitos origen y destino son obligatorios para transferencias")
            if origen_id == destino_id:
                raise ValueError("El depósito origen debe ser diferente al destino")
            movimiento = crear_movimiento_transferencia(item, qty, origen_id, destino_id, motivo)
            
        elif tipo == 'ajuste':
            warehouse_id = request.form.get('destino_warehouse_id')
            nuevo_stock = request.form.get('nuevo_stock')
            if not all([warehouse_id, nuevo_stock]):
                raise ValueError("Depósito y nuevo stock son obligatorios para ajustes")
            movimiento = crear_movimiento_ajuste(item, float(nuevo_stock), warehouse_id, motivo)
        
        else:
            raise ValueError("Tipo de movimiento no válido")
        
        db.session.add(movimiento)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Movimiento registrado exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Movimiento registrado exitosamente.', 'success')
        
    except ValueError as e:
        error = str(e)
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    except Exception as e:
        db.session.rollback()
        error = 'Error al registrar el movimiento.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.movimientos'))

def crear_movimiento_ingreso(item, qty, warehouse_id, motivo):
    """Crea un movimiento de ingreso"""
    # Actualizar o crear stock
    stock = Stock.query.filter_by(item_id=item.id, warehouse_id=warehouse_id).first()
    if not stock:
        stock = Stock(item_id=item.id, warehouse_id=warehouse_id, cantidad=0)
        db.session.add(stock)
    
    stock.cantidad += qty
    
    return StockMovement(
        item_id=item.id,
        tipo='ingreso',
        qty=qty,
        destino_warehouse_id=warehouse_id,
        motivo=motivo,
        user_id=current_user.id
    )

def crear_movimiento_egreso(item, qty, warehouse_id, motivo):
    """Crea un movimiento de egreso"""
    stock = Stock.query.filter_by(item_id=item.id, warehouse_id=warehouse_id).first()
    if not stock or stock.cantidad < qty:
        raise ValueError("Stock insuficiente en el depósito")
    
    stock.cantidad -= qty
    
    return StockMovement(
        item_id=item.id,
        tipo='egreso',
        qty=qty,
        origen_warehouse_id=warehouse_id,
        motivo=motivo,
        user_id=current_user.id
    )

def crear_movimiento_transferencia(item, qty, origen_id, destino_id, motivo):
    """Crea un movimiento de transferencia"""
    # Verificar stock origen
    stock_origen = Stock.query.filter_by(item_id=item.id, warehouse_id=origen_id).first()
    if not stock_origen or stock_origen.cantidad < qty:
        raise ValueError("Stock insuficiente en el depósito origen")
    
    # Actualizar stock origen
    stock_origen.cantidad -= qty
    
    # Actualizar o crear stock destino
    stock_destino = Stock.query.filter_by(item_id=item.id, warehouse_id=destino_id).first()
    if not stock_destino:
        stock_destino = Stock(item_id=item.id, warehouse_id=destino_id, cantidad=0)
        db.session.add(stock_destino)
    
    stock_destino.cantidad += qty
    
    return StockMovement(
        item_id=item.id,
        tipo='transferencia',
        qty=qty,
        origen_warehouse_id=origen_id,
        destino_warehouse_id=destino_id,
        motivo=motivo,
        user_id=current_user.id
    )

def crear_movimiento_ajuste(item, nuevo_stock, warehouse_id, motivo):
    """Crea un movimiento de ajuste"""
    stock = Stock.query.filter_by(item_id=item.id, warehouse_id=warehouse_id).first()
    if not stock:
        stock = Stock(item_id=item.id, warehouse_id=warehouse_id, cantidad=0)
        db.session.add(stock)
    
    stock_anterior = stock.cantidad
    stock.cantidad = nuevo_stock
    qty_ajuste = nuevo_stock - stock_anterior
    
    return StockMovement(
        item_id=item.id,
        tipo='ajuste',
        qty=abs(qty_ajuste),
        destino_warehouse_id=warehouse_id,
        motivo=f"Ajuste: {stock_anterior} → {nuevo_stock}. {motivo}",
        user_id=current_user.id
    )

@inventario_new_bp.route('/alertas')
@login_required
def alertas():
    """Muestra items con stock bajo"""
    items_stock_bajo = InventoryItem.query.filter_by(
        company_id=current_user.organizacion_id, 
        activo=True
    ).all()
    
    items_stock_bajo = [item for item in items_stock_bajo if item.is_low_stock]
    
    json_resp = get_json_response({
        'data': [
            {
                'id': item.id,
                'sku': item.sku,
                'nombre': item.nombre,
                'total_stock': float(item.total_stock),
                'min_stock': float(item.min_stock),
                'diferencia': float(item.min_stock - item.total_stock)
            } for item in items_stock_bajo
        ]
    })
    if json_resp:
        return json_resp
    
    return render_template('inventario_new/alertas.html', items=items_stock_bajo)

@inventario_new_bp.route('/reservas', methods=['GET', 'POST'])
@login_required
def reservas():
    if request.method == 'POST':
        return crear_reserva()
    
    # Listar reservas activas
    reservas = StockReservation.query.join(InventoryItem).filter(
        InventoryItem.company_id == current_user.organizacion_id,
        StockReservation.estado == 'activa'
    ).all()
    
    json_resp = get_json_response({
        'data': [
            {
                'id': res.id,
                'item': res.item.nombre,
                'proyecto': res.project.nombre,
                'cantidad': float(res.qty),
                'fecha': res.created_at.isoformat()
            } for res in reservas
        ]
    })
    if json_resp:
        return json_resp
    
    # Obtener datos para el formulario
    items = InventoryItem.query.filter_by(company_id=current_user.organizacion_id, activo=True).all()
    projects = Obra.query.filter_by(organizacion_id=current_user.organizacion_id).all()
    
    return render_template('inventario_new/reservas.html', 
                         reservas=reservas,
                         items=items,
                         projects=projects)

def crear_reserva():
    """Crea una nueva reserva de stock"""
    item_id = request.form.get('item_id')
    project_id = request.form.get('project_id')
    qty = request.form.get('qty')
    
    if not all([item_id, project_id, qty]):
        error = 'Todos los campos son obligatorios.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
        return redirect(url_for('inventario_new.reservas'))
    
    try:
        qty = float(qty)
        item = InventoryItem.query.get(item_id)
        
        if qty > item.available_stock:
            raise ValueError("No hay suficiente stock disponible para reservar")
        
        reserva = StockReservation(
            item_id=item_id,
            project_id=project_id,
            qty=qty,
            created_by=current_user.id
        )
        
        db.session.add(reserva)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Reserva creada exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Reserva creada exitosamente.', 'success')
        
    except ValueError as e:
        error = str(e)
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    except Exception as e:
        db.session.rollback()
        error = 'Error al crear la reserva.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.reservas'))

@inventario_new_bp.route('/reservas/<int:id>/liberar', methods=['POST'])
@login_required
@requires_role('administrador', 'compras')
def liberar_reserva(id):
    reserva = StockReservation.query.get_or_404(id)
    
    try:
        reserva.estado = 'liberada'
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Reserva liberada exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Reserva liberada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al liberar la reserva.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.reservas'))

@inventario_new_bp.route('/reservas/<int:id>/consumir', methods=['POST'])
@login_required
@requires_role('administrador', 'compras')
def consumir_reserva(id):
    reserva = StockReservation.query.get_or_404(id)
    
    try:
        # Crear movimiento de egreso
        # Buscar el depósito con más stock del item
        stock_disponible = Stock.query.filter_by(item_id=reserva.item_id).order_by(Stock.cantidad.desc()).first()
        
        if not stock_disponible or stock_disponible.cantidad < reserva.qty:
            raise ValueError("No hay suficiente stock disponible para consumir la reserva")
        
        # Crear movimiento de egreso
        movimiento = StockMovement(
            item_id=reserva.item_id,
            tipo='egreso',
            qty=reserva.qty,
            origen_warehouse_id=stock_disponible.warehouse_id,
            project_id=reserva.project_id,
            motivo=f"Consumo de reserva para {reserva.project.nombre}",
            user_id=current_user.id
        )
        
        # Actualizar stock
        stock_disponible.cantidad -= reserva.qty
        
        # Marcar reserva como consumida
        reserva.estado = 'consumida'
        
        db.session.add(movimiento)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Reserva consumida exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Reserva consumida exitosamente.', 'success')
        
    except ValueError as e:
        error = str(e)
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    except Exception as e:
        db.session.rollback()
        error = 'Error al consumir la reserva.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.reservas'))