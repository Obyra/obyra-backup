from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify
from flask_login import current_user, login_required
from app import db
from models import (
    Product, ProductVariant, Category, Supplier, ProductQNA,
    Order, OrderItem, Usuario
)
from sqlalchemy import or_, func
import json
from utils import safe_float, safe_int

market_bp = Blueprint('market', __name__, url_prefix='/market')

@market_bp.route('/')
def index():
    """Marketplace principal - lista de productos"""
    # Filtros
    categoria_id = request.args.get('categoria')
    ubicacion = request.args.get('ubicacion')
    verificado = request.args.get('verificado')
    precio_min = request.args.get('precio_min')
    precio_max = request.args.get('precio_max')
    buscar = request.args.get('buscar')
    
    # Query base - solo productos publicados
    query = Product.query.filter_by(estado='publicado').join(Supplier).filter(
        Supplier.estado == 'activo'
    )
    
    # Aplicar filtros
    if categoria_id:
        query = query.filter(Product.category_id == categoria_id)
    
    if ubicacion:
        query = query.filter(Supplier.ubicacion.contains(ubicacion))
    
    if verificado == '1':
        query = query.filter(Supplier.verificado == True)
    
    if buscar:
        query = query.filter(
            or_(
                Product.nombre.contains(buscar),
                Product.descripcion.contains(buscar),
                Supplier.razon_social.contains(buscar)
            )
        )
    
    productos = query.order_by(Product.updated_at.desc()).limit(50).all()
    
    # Filtrar por precio si se especifica
    if precio_min or precio_max:
        productos_filtrados = []
        for producto in productos:
            precio = producto.min_price
            if precio > 0:
                if precio_min and precio < float(precio_min):
                    continue
                if precio_max and precio > float(precio_max):
                    continue
                productos_filtrados.append(producto)
        productos = productos_filtrados
    
    # Obtener datos para filtros
    categorias = Category.query.all()
    ubicaciones = db.session.query(Supplier.ubicacion).filter(
        Supplier.ubicacion != None,
        Supplier.ubicacion != ''
    ).distinct().all()
    ubicaciones = [u[0] for u in ubicaciones if u[0]]
    
    return render_template('market/index.html',
                         productos=productos,
                         categorias=categorias,
                         ubicaciones=ubicaciones,
                         filtros={
                             'categoria': categoria_id,
                             'ubicacion': ubicacion,
                             'verificado': verificado,
                             'precio_min': precio_min,
                             'precio_max': precio_max,
                             'buscar': buscar
                         })

@market_bp.route('/producto/<int:id>')
def producto_detail(id):
    """Detalle de producto"""
    producto = Product.query.filter_by(id=id, estado='publicado').first_or_404()
    
    if producto.supplier.estado != 'activo':
        flash('Este producto no está disponible.', 'warning')
        return redirect(url_for('market.index'))
    
    # Obtener Q&A
    qnas = ProductQNA.query.filter_by(product_id=id).order_by(
        ProductQNA.created_at.desc()
    ).all()
    
    return render_template('market/producto_detail.html', 
                         producto=producto,
                         qnas=qnas)

@market_bp.route('/producto/<int:id>/pregunta', methods=['POST'])
def hacer_pregunta(id):
    """Hacer pregunta sobre un producto"""
    producto = Product.query.filter_by(id=id, estado='publicado').first_or_404()
    
    pregunta = request.form.get('pregunta', '').strip()
    if not pregunta:
        flash('La pregunta no puede estar vacía.', 'danger')
        return redirect(url_for('market.producto_detail', id=id))
    
    try:
        qna = ProductQNA(
            product_id=id,
            user_id=current_user.id if current_user.is_authenticated else None,
            pregunta=pregunta
        )
        db.session.add(qna)
        db.session.commit()
        
        flash('Pregunta enviada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al enviar la pregunta.', 'danger')
    
    return redirect(url_for('market.producto_detail', id=id))

@market_bp.route('/carrito')
def carrito():
    """Ver carrito de compras"""
    carrito_items = session.get('carrito', [])
    
    # Obtener detalles de los productos
    items_detalle = []
    total = 0
    
    for item in carrito_items:
        variante = ProductVariant.query.get(item['variant_id'])
        if variante and variante.is_available:
            subtotal = float(variante.precio) * item['qty']
            items_detalle.append({
                'variante': variante,
                'qty': item['qty'],
                'subtotal': subtotal
            })
            total += subtotal
    
    return render_template('market/carrito.html',
                         items=items_detalle,
                         total=total)

@market_bp.route('/carrito/agregar', methods=['POST'])
def agregar_carrito():
    """Agregar producto al carrito"""
    variant_id = request.form.get('variant_id')
    qty = safe_float(request.form.get('qty', 1), default=1.0)
    
    if not variant_id:
        return jsonify({'error': 'Variante no especificada'}), 400
    
    variante = ProductVariant.query.get(variant_id)
    if not variante or not variante.is_available:
        return jsonify({'error': 'Producto no disponible'}), 400
    
    if qty > variante.stock:
        return jsonify({'error': 'Stock insuficiente'}), 400
    
    # Obtener carrito actual
    carrito = session.get('carrito', [])
    
    # Verificar si ya existe el item
    item_existente = next((item for item in carrito if item['variant_id'] == int(variant_id)), None)
    
    if item_existente:
        nueva_qty = item_existente['qty'] + qty
        if nueva_qty > variante.stock:
            return jsonify({'error': 'Stock insuficiente'}), 400
        item_existente['qty'] = nueva_qty
    else:
        carrito.append({
            'variant_id': int(variant_id),
            'qty': qty
        })
    
    session['carrito'] = carrito
    
    return jsonify({'message': 'Producto agregado al carrito', 'carrito_count': len(carrito)})

@market_bp.route('/carrito/actualizar', methods=['POST'])
def actualizar_carrito():
    """Actualizar cantidad en carrito"""
    variant_id = safe_int(request.form.get('variant_id'))
    qty = safe_float(request.form.get('qty', 0))
    
    carrito = session.get('carrito', [])
    
    if qty <= 0:
        # Eliminar item
        carrito = [item for item in carrito if item['variant_id'] != variant_id]
    else:
        # Actualizar cantidad
        for item in carrito:
            if item['variant_id'] == variant_id:
                variante = ProductVariant.query.get(variant_id)
                if variante and qty <= variante.stock:
                    item['qty'] = qty
                else:
                    flash('Stock insuficiente.', 'warning')
                break
    
    session['carrito'] = carrito
    return redirect(url_for('market.carrito'))

@market_bp.route('/checkout', methods=['POST'])
@login_required
def checkout():
    """Crear orden desde el carrito"""
    carrito_items = session.get('carrito', [])
    
    if not carrito_items:
        flash('El carrito está vacío.', 'warning')
        return redirect(url_for('market.carrito'))
    
    try:
        # Agrupar items por proveedor
        items_por_supplier = {}
        for item in carrito_items:
            variante = ProductVariant.query.get(item['variant_id'])
            if not variante or not variante.is_available:
                flash(f'El producto {variante.display_name if variante else "desconocido"} ya no está disponible.', 'warning')
                return redirect(url_for('market.carrito'))
            
            supplier_id = variante.product.supplier_id
            if supplier_id not in items_por_supplier:
                items_por_supplier[supplier_id] = []
            
            items_por_supplier[supplier_id].append({
                'variante': variante,
                'qty': item['qty']
            })
        
        ordenes_creadas = []
        
        # Crear una orden por proveedor
        for supplier_id, items in items_por_supplier.items():
            total_orden = 0
            
            # Crear orden
            orden = Order(
                company_id=current_user.organizacion_id,
                supplier_id=supplier_id,
                total=0,  # Se calculará después
                payment_method='offline'  # Por defecto offline, se puede cambiar
            )
            db.session.add(orden)
            db.session.flush()  # Para obtener ID
            
            # Crear items de la orden
            for item_data in items:
                variante = item_data['variante']
                qty = item_data['qty']
                precio_unit = variante.precio
                subtotal = float(precio_unit) * qty
                
                order_item = OrderItem(
                    order_id=orden.id,
                    product_variant_id=variante.id,
                    qty=qty,
                    precio_unit=precio_unit,
                    subtotal=subtotal
                )
                db.session.add(order_item)
                
                # Actualizar stock
                variante.stock -= qty
                
                total_orden += subtotal
            
            # Actualizar total de la orden
            orden.total = total_orden
            ordenes_creadas.append(orden.id)
        
        db.session.commit()
        
        # Limpiar carrito
        session['carrito'] = []
        
        if len(ordenes_creadas) == 1:
            flash('Orden creada exitosamente.', 'success')
            return redirect(url_for('market.orden_detail', id=ordenes_creadas[0]))
        else:
            flash(f'{len(ordenes_creadas)} órdenes creadas exitosamente.', 'success')
            return redirect(url_for('market.mis_ordenes'))
            
    except Exception as e:
        db.session.rollback()
        flash('Error al crear la orden.', 'danger')
        return redirect(url_for('market.carrito'))

@market_bp.route('/mis-ordenes')
@login_required
def mis_ordenes():
    """Mis órdenes como comprador"""
    ordenes = Order.query.filter_by(company_id=current_user.organizacion_id).order_by(
        Order.created_at.desc()
    ).all()
    
    return render_template('market/mis_ordenes.html', ordenes=ordenes)

@market_bp.route('/orden/<int:id>')
@login_required
def orden_detail(id):
    """Detalle de orden"""
    orden = Order.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    return render_template('market/orden_detail.html', orden=orden)

@market_bp.route('/orden/<int:id>/checkout', methods=['POST'])
@login_required
def orden_checkout(id):
    """Proceder al pago de una orden (Mercado Pago)"""
    orden = Order.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    if orden.payment_status != 'init':
        flash('Esta orden ya fue procesada.', 'warning')
        return redirect(url_for('market.orden_detail', id=id))
    
    # TODO: Integrar con Mercado Pago
    # Por ahora marcamos como pendiente de pago online
    try:
        orden.payment_method = 'online'
        orden.payment_status = 'init'
        db.session.commit()
        
        flash('Redirigiendo a Mercado Pago...', 'info')
        # Aquí iría la redirección real a MP
        
    except Exception as e:
        db.session.rollback()
        flash('Error al procesar el pago.', 'danger')
    
    return redirect(url_for('market.orden_detail', id=id))

# Context processor para carrito
@market_bp.app_context_processor
def inject_carrito():
    """Inyecta información del carrito en todas las templates"""
    carrito_count = len(session.get('carrito', []))
    return dict(carrito_count=carrito_count)