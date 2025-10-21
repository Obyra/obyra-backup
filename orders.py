"""
Blueprint para manejo de órdenes - vista tanto para compradores como proveedores
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from models import Order, OrderItem, OrderCommission, Supplier
from datetime import datetime

orders_bp = Blueprint('orders', __name__, url_prefix='/orders')


@orders_bp.route('/')
@login_required
def my_orders():
    """Mis órdenes como comprador"""
    page = request.args.get('page', 1, type=int)
    
    orders = Order.query.filter_by(company_id=current_user.organizacion_id)\
                       .order_by(Order.created_at.desc())\
                       .paginate(page=page, per_page=10, error_out=False)
    
    return render_template('orders/my_orders.html', orders=orders)


@orders_bp.route('/<int:order_id>')
@login_required
def view_order(order_id):
    """Ver detalle de una orden"""
    order = Order.query.get_or_404(order_id)
    
    # Verificar acceso: solo el comprador o el proveedor pueden ver la orden
    is_buyer = current_user.organizacion_id == order.company_id
    is_supplier = hasattr(current_user, 'supplier_user') and \
                  current_user.supplier_user and \
                  current_user.supplier_user.supplier_id == order.supplier_id
    
    if not (is_buyer or is_supplier):
        abort(403)
    
    return render_template('orders/order_detail.html', 
                         order=order, 
                         is_buyer=is_buyer,
                         is_supplier=is_supplier)


@orders_bp.route('/<int:order_id>/pay', methods=['POST'])
@login_required
def initiate_payment(order_id):
    """Iniciar pago online (Mercado Pago)"""
    order = Order.query.get_or_404(order_id)
    
    # Verificar que sea el comprador
    if current_user.organizacion_id != order.company_id:
        abort(403)
    
    # Verificar que esté pendiente de pago
    if order.payment_status != 'init':
        flash('Esta orden ya fue procesada', 'error')
        return redirect(url_for('orders.view_order', order_id=order_id))
    
    # TODO: Implementar integración con Mercado Pago
    flash('Funcionalidad de pago en línea pendiente de implementación', 'info')
    return redirect(url_for('orders.view_order', order_id=order_id))


@orders_bp.route('/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel_order(order_id):
    """Cancelar orden (solo si está pendiente)"""
    order = Order.query.get_or_404(order_id)
    
    # Verificar que sea el comprador
    if current_user.organizacion_id != order.company_id:
        abort(403)
    
    # Solo se puede cancelar si está pendiente
    if order.estado != 'pendiente':
        flash('Solo se pueden cancelar órdenes pendientes', 'error')
        return redirect(url_for('orders.view_order', order_id=order_id))
    
    # Devolver stock a las variantes
    for item in order.items:
        item.variant.stock += item.qty
    
    order.estado = 'cancelado'
    db.session.commit()
    
    flash('Orden cancelada exitosamente', 'success')
    return redirect(url_for('orders.view_order', order_id=order_id))