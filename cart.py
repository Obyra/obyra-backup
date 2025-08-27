"""
Blueprint del Carrito de Compras
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import current_user
from sqlalchemy import func
from app import db
from models import Cart, CartItem, ProductVariant, Product, Supplier, Order, OrderItem, OrderCommission
from commission_utils import get_commission_summary
from decimal import Decimal
from collections import defaultdict
import uuid

cart_bp = Blueprint('cart', __name__, url_prefix='/cart')


def get_or_create_cart():
    """Obtiene o crea un carrito para el usuario/sesión actual"""
    if current_user.is_authenticated:
        # Usuario logueado: buscar por user_id
        cart = Cart.query.filter_by(user_id=current_user.id).first()
        if not cart:
            cart = Cart(user_id=current_user.id)
            db.session.add(cart)
            db.session.commit()
    else:
        # Usuario anónimo: usar session_id
        session_id = session.get('cart_session_id')
        if not session_id:
            session_id = str(uuid.uuid4())
            session['cart_session_id'] = session_id
        
        cart = Cart.query.filter_by(session_id=session_id).first()
        if not cart:
            cart = Cart(session_id=session_id)
            db.session.add(cart)
            db.session.commit()
    
    return cart


@cart_bp.route('/')
def view_cart():
    """Ver contenido del carrito"""
    cart = get_or_create_cart()
    
    # Agrupar items por proveedor para mostrar el checkout
    items_by_supplier = defaultdict(list)
    total_general = Decimal('0')
    
    for item in cart.items:
        items_by_supplier[item.supplier].append(item)
        total_general += item.subtotal
    
    return render_template('cart/view.html',
                         cart=cart,
                         items_by_supplier=dict(items_by_supplier),
                         total_general=total_general)


@cart_bp.route('/add', methods=['POST'])
def add_to_cart():
    """Agregar producto al carrito"""
    variant_id = request.form.get('variant_id', type=int)
    qty = Decimal(request.form.get('qty', '1'))
    
    if not variant_id or qty <= 0:
        flash('Datos de producto inválidos', 'error')
        return redirect(request.referrer or url_for('marketplace.productos'))
    
    variant = ProductVariant.query.get_or_404(variant_id)
    
    # Verificar disponibilidad
    if not variant.is_available:
        flash('Producto no disponible', 'error')
        return redirect(request.referrer or url_for('marketplace.productos'))
    
    # Verificar stock
    if variant.stock < qty:
        flash(f'Stock insuficiente. Disponible: {variant.stock} {variant.unidad}', 'error')
        return redirect(request.referrer or url_for('marketplace.productos'))
    
    cart = get_or_create_cart()
    
    # Verificar si ya existe en el carrito
    existing_item = CartItem.query.filter_by(
        cart_id=cart.id,
        product_variant_id=variant_id
    ).first()
    
    if existing_item:
        # Actualizar cantidad
        new_qty = existing_item.qty + qty
        if new_qty > variant.stock:
            flash(f'No se puede agregar más cantidad. Stock máximo: {variant.stock}', 'error')
            return redirect(request.referrer or url_for('marketplace.productos'))
        
        existing_item.qty = new_qty
        existing_item.precio_snapshot = variant.precio  # Actualizar precio
    else:
        # Crear nuevo item
        cart_item = CartItem(
            cart_id=cart.id,
            product_variant_id=variant_id,
            supplier_id=variant.product.supplier_id,
            qty=qty,
            precio_snapshot=variant.precio
        )
        db.session.add(cart_item)
    
    db.session.commit()
    flash(f'Producto agregado al carrito: {variant.display_name}', 'success')
    
    return redirect(request.referrer or url_for('cart.view_cart'))


@cart_bp.route('/update', methods=['POST'])
def update_cart():
    """Actualizar cantidades en el carrito"""
    item_id = request.form.get('item_id', type=int)
    qty = Decimal(request.form.get('qty', '0'))
    
    if not item_id:
        flash('Item no encontrado', 'error')
        return redirect(url_for('cart.view_cart'))
    
    cart = get_or_create_cart()
    item = CartItem.query.filter_by(id=item_id, cart_id=cart.id).first_or_404()
    
    if qty <= 0:
        # Eliminar item
        db.session.delete(item)
        flash('Producto eliminado del carrito', 'info')
    else:
        # Verificar stock
        if qty > item.variant.stock:
            flash(f'Stock insuficiente. Disponible: {item.variant.stock}', 'error')
            return redirect(url_for('cart.view_cart'))
        
        item.qty = qty
        item.precio_snapshot = item.variant.precio  # Actualizar precio
        flash('Carrito actualizado', 'success')
    
    db.session.commit()
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/remove/<int:item_id>', methods=['POST'])
def remove_item(item_id):
    """Eliminar item del carrito"""
    cart = get_or_create_cart()
    item = CartItem.query.filter_by(id=item_id, cart_id=cart.id).first_or_404()
    
    db.session.delete(item)
    db.session.commit()
    
    flash('Producto eliminado del carrito', 'info')
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/clear', methods=['POST'])
def clear_cart():
    """Vaciar el carrito completamente"""
    cart = get_or_create_cart()
    cart.clear()
    
    flash('Carrito vaciado', 'info')
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/checkout')
def checkout():
    """Página de checkout con resumen por proveedor"""
    cart = get_or_create_cart()
    
    if not cart.items:
        flash('El carrito está vacío', 'error')
        return redirect(url_for('marketplace.productos'))
    
    # Agrupar items por proveedor
    orders_preview = defaultdict(lambda: {
        'supplier': None,
        'items': [],
        'subtotal': Decimal('0'),
        'commission_info': None
    })
    
    for item in cart.items:
        supplier_id = item.supplier_id
        orders_preview[supplier_id]['supplier'] = item.supplier
        orders_preview[supplier_id]['items'].append(item)
        orders_preview[supplier_id]['subtotal'] += item.subtotal
    
    # Calcular comisiones para cada orden
    for supplier_id, order_data in orders_preview.items():
        commission_info = get_commission_summary(order_data['subtotal'])
        orders_preview[supplier_id]['commission_info'] = commission_info
    
    return render_template('cart/checkout.html',
                         cart=cart,
                         orders_preview=dict(orders_preview))


@cart_bp.route('/checkout/confirm', methods=['POST'])
def checkout_confirm():
    """Confirmar compra y crear órdenes"""
    cart = get_or_create_cart()
    
    if not cart.items:
        flash('El carrito está vacío', 'error')
        return redirect(url_for('marketplace.productos'))
    
    if not current_user.is_authenticated:
        flash('Debes iniciar sesión para completar la compra', 'error')
        return redirect(url_for('auth.login'))
    
    # Agrupar items por proveedor
    items_by_supplier = defaultdict(list)
    for item in cart.items:
        items_by_supplier[item.supplier_id].append(item)
    
    created_orders = []
    
    try:
        for supplier_id, items in items_by_supplier.items():
            # Calcular total de la orden
            total = sum(item.subtotal for item in items)
            
            # Crear orden
            order = Order(
                company_id=current_user.organizacion_id,
                supplier_id=supplier_id,
                total=total,
                moneda='ARS',
                estado='pendiente',
                payment_method='offline',  # Por defecto offline, puede cambiarse a online
                payment_status='init'
            )
            db.session.add(order)
            db.session.flush()  # Para obtener el ID
            
            # Crear items de la orden y verificar stock
            for item in items:
                variant = item.variant
                
                # Verificar stock al momento de la compra
                if variant.stock < item.qty:
                    db.session.rollback()
                    flash(f'Stock insuficiente para {variant.display_name}. Disponible: {variant.stock}', 'error')
                    return redirect(url_for('cart.view_cart'))
                
                # Descontar stock
                variant.stock -= item.qty
                
                # Crear order item
                order_item = OrderItem(
                    order_id=order.id,
                    product_variant_id=variant.id,
                    qty=item.qty,
                    precio_unit=item.precio_snapshot,
                    subtotal=item.subtotal
                )
                db.session.add(order_item)
            
            # Crear comisión
            commission_info = get_commission_summary(total)
            commission = OrderCommission(
                order_id=order.id,
                base=total,
                rate=commission_info['commission_rate'],
                monto=commission_info['commission_base'],
                iva=commission_info['commission_iva'],
                total=commission_info['commission_total']
            )
            db.session.add(commission)
            
            created_orders.append(order.id)
        
        # Limpiar carrito
        cart.clear()
        
        db.session.commit()
        
        flash(f'¡Compra realizada exitosamente! Se crearon {len(created_orders)} órdenes.', 'success')
        
        # Redirigir a la primera orden o a un resumen
        if created_orders:
            return redirect(url_for('orders.view_order', order_id=created_orders[0]))
        else:
            return redirect(url_for('marketplace.productos'))
    
    except Exception as e:
        db.session.rollback()
        flash('Error al procesar la compra. Intenta nuevamente.', 'error')
        return redirect(url_for('cart.checkout'))


@cart_bp.route('/count')
def cart_count():
    """API endpoint para obtener el número de items en el carrito (AJAX)"""
    cart = get_or_create_cart()
    return jsonify({'count': int(cart.total_items)})