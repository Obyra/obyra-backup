"""
OBYRA Market - Main Flask Blueprint
ML-like B2B marketplace with seller masking and purchase order generation
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app import db
from models_marketplace import *
from sqlalchemy import func
import json
import os

marketplace_new_bp = Blueprint('marketplace_new', __name__)

# ===== CATALOG ROUTES =====

@marketplace_new_bp.route('/')
def home():
    """Homepage del marketplace"""
    # Obtener categorías principales
    main_categories = MarketCategory.query.filter_by(parent_id=None, is_active=True).limit(8).all()
    
    # Productos destacados (premium activos)
    featured_products = db.session.query(MarketProduct).join(MarketPublication).filter(
        MarketPublication.status == 'active',
        MarketPublication.exposure == 'premium'
    ).limit(12).all()
    
    return render_template('marketplace_new/home.html', 
                         categories=main_categories,
                         featured_products=featured_products)

@marketplace_new_bp.route('/search')
def search():
    """Búsqueda de productos con facetas"""
    q = request.args.get('q', '')
    category_id = request.args.get('category')
    brand_id = request.args.get('brand')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    sort = request.args.get('sort', 'relevance')
    page = request.args.get('page', 1, type=int)
    per_page = 24
    
    # Query base - solo productos con publicaciones activas
    query = db.session.query(MarketProduct).join(MarketPublication).filter(
        MarketPublication.status == 'active'
    )
    
    # Filtros
    if q:
        query = query.filter(MarketProduct.name.ilike(f'%{q}%'))
    
    if category_id:
        query = query.filter(MarketProduct.category_id == category_id)
    
    if brand_id:
        query = query.filter(MarketProduct.brand_id == brand_id)
    
    # Filtro por precio (usando la primera variante como referencia)
    if min_price or max_price:
        variant_subquery = db.session.query(MarketProductVariant.product_id).distinct()
        if min_price:
            variant_subquery = variant_subquery.filter(MarketProductVariant.price >= min_price)
        if max_price:
            variant_subquery = variant_subquery.filter(MarketProductVariant.price <= max_price)
        query = query.filter(MarketProduct.id.in_(variant_subquery))
    
    # Ordenamiento
    if sort == 'price_asc':
        query = query.join(MarketProductVariant).order_by(MarketProductVariant.price.asc())
    elif sort == 'price_desc':
        query = query.join(MarketProductVariant).order_by(MarketProductVariant.price.desc())
    elif sort == 'name':
        query = query.order_by(MarketProduct.name.asc())
    else:  # relevance default
        # Dar prioridad a exposición premium
        query = query.join(MarketPublication).order_by(
            MarketPublication.exposure.desc(),
            MarketProduct.name.asc()
        )
    
    # Paginación
    products = query.distinct().paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Facetas para filtros
    categories = MarketCategory.query.filter_by(is_active=True).all()
    brands = MarketBrand.query.filter_by(is_active=True).all()
    
    return render_template('marketplace_new/search.html',
                         products=products,
                         categories=categories,
                         brands=brands,
                         filters={
                             'q': q,
                             'category_id': category_id,
                             'brand_id': brand_id,
                             'min_price': min_price,
                             'max_price': max_price,
                             'sort': sort
                         })

@marketplace_new_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    """Detalle de producto con seller masking"""
    product = MarketProduct.query.get_or_404(product_id)
    
    # Verificar que esté publicado
    publication = MarketPublication.query.filter_by(
        product_id=product_id,
        status='active'
    ).first_or_404()
    
    # Variantes del producto
    variants = MarketProductVariant.query.filter_by(
        product_id=product_id,
        is_active=True
    ).all()
    
    # Preguntas públicas
    questions = MarketQuestion.query.filter_by(
        product_id=product_id,
        is_public=True
    ).filter(MarketQuestion.answer.isnot(None)).order_by(
        MarketQuestion.created_at.desc()
    ).limit(10).all()
    
    # Calificaciones promedio (solo si el seller no está enmascarado)
    avg_rating = None
    if not product.is_masked_seller:
        ratings = db.session.query(func.avg(MarketRating.product_rating)).filter_by(
            product_id=product_id
        ).scalar()
        avg_rating = round(ratings, 1) if ratings else None
    
    return render_template('marketplace_new/product_detail.html',
                         product=product,
                         publication=publication,
                         variants=variants,
                         questions=questions,
                         avg_rating=avg_rating)

# ===== CART ROUTES =====

@marketplace_new_bp.route('/cart')
@login_required
def cart():
    """Ver carrito actual"""
    if not hasattr(current_user, 'company_id'):
        flash('Debes ser parte de una empresa para comprar.', 'error')
        return redirect(url_for('marketplace_new.home'))
    
    # Obtener o crear carrito
    user_cart = MarketCart.query.filter_by(
        buyer_company_id=current_user.company_id,
        buyer_user_id=current_user.id
    ).first()
    
    if not user_cart:
        user_cart = MarketCart(
            buyer_company_id=current_user.company_id,
            buyer_user_id=current_user.id
        )
        db.session.add(user_cart)
        db.session.commit()
    
    # Items agrupados por seller (enmascarado)
    items_by_seller = user_cart.items_by_seller
    
    return render_template('marketplace_new/cart.html',
                         cart=user_cart,
                         items_by_seller=items_by_seller)

@marketplace_new_bp.route('/api/cart/add', methods=['POST'])
@login_required
def add_to_cart():
    """Agregar item al carrito"""
    if not hasattr(current_user, 'company_id'):
        return jsonify({'error': 'Usuario sin empresa'}), 400
    
    data = request.get_json()
    variant_id = data.get('variant_id')
    qty = data.get('qty', 1)
    
    variant = MarketProductVariant.query.get_or_404(variant_id)
    
    # Verificar stock disponible
    if variant.available_stock < qty:
        return jsonify({'error': 'Stock insuficiente'}), 400
    
    # Obtener o crear carrito
    user_cart = MarketCart.query.filter_by(
        buyer_company_id=current_user.company_id,
        buyer_user_id=current_user.id
    ).first()
    
    if not user_cart:
        user_cart = MarketCart(
            buyer_company_id=current_user.company_id,
            buyer_user_id=current_user.id
        )
        db.session.add(user_cart)
        db.session.flush()
    
    # Verificar si ya existe el item
    existing_item = MarketCartItem.query.filter_by(
        cart_id=user_cart.id,
        variant_id=variant_id
    ).first()
    
    if existing_item:
        existing_item.qty += qty
        existing_item.price_snapshot = variant.price  # Actualizar precio
    else:
        cart_item = MarketCartItem(
            cart_id=user_cart.id,
            variant_id=variant_id,
            qty=qty,
            price_snapshot=variant.price,
            currency=variant.currency
        )
        db.session.add(cart_item)
    
    db.session.commit()
    
    return jsonify({'message': 'Producto agregado al carrito', 'cart_total': user_cart.total_amount})

@marketplace_new_bp.route('/api/cart/remove/<int:item_id>', methods=['DELETE'])
@login_required
def remove_from_cart(item_id):
    """Remover item del carrito"""
    cart_item = MarketCartItem.query.get_or_404(item_id)
    
    # Verificar que pertenece al usuario
    if cart_item.cart.buyer_user_id != current_user.id:
        return jsonify({'error': 'No autorizado'}), 403
    
    db.session.delete(cart_item)
    db.session.commit()
    
    return jsonify({'message': 'Item removido del carrito'})

# ===== CHECKOUT & ORDERS =====

@marketplace_new_bp.route('/checkout')
@login_required
def checkout():
    """Proceso de checkout"""
    if not hasattr(current_user, 'company_id'):
        flash('Debes ser parte de una empresa para comprar.', 'error')
        return redirect(url_for('marketplace_new.home'))
    
    # Obtener carrito
    user_cart = MarketCart.query.filter_by(
        buyer_company_id=current_user.company_id,
        buyer_user_id=current_user.id
    ).first()
    
    if not user_cart or not user_cart.items:
        flash('El carrito está vacío.', 'warning')
        return redirect(url_for('marketplace_new.cart'))
    
    # Verificar stock de todos los items
    for item in user_cart.items:
        if item.variant.available_stock < item.qty:
            flash(f'Stock insuficiente para {item.variant.product.name}', 'error')
            return redirect(url_for('marketplace_new.cart'))
    
    return render_template('marketplace_new/checkout.html', cart=user_cart)

@marketplace_new_bp.route('/api/orders/create', methods=['POST'])
@login_required
def create_order():
    """Crear orden desde el carrito"""
    if not hasattr(current_user, 'company_id'):
        return jsonify({'error': 'Usuario sin empresa'}), 400
    
    data = request.get_json()
    
    # Obtener carrito
    user_cart = MarketCart.query.filter_by(
        buyer_company_id=current_user.company_id,
        buyer_user_id=current_user.id
    ).first()
    
    if not user_cart or not user_cart.items:
        return jsonify({'error': 'Carrito vacío'}), 400
    
    # Crear orden
    order = MarketOrder(
        buyer_company_id=current_user.company_id,
        buyer_user_id=current_user.id,
        total=user_cart.total_amount,
        currency='ARS',
        billing_json=json.dumps(data.get('billing', {})),
        shipping_json=json.dumps(data.get('shipping', {})),
        status='pending',
        payment_status='pending'
    )
    
    db.session.add(order)
    db.session.flush()
    
    # Crear order items y calcular comisiones
    for cart_item in user_cart.items:
        # Buscar comisión para esta categoría/exposición
        product = cart_item.variant.product
        publication = MarketPublication.query.filter_by(
            product_id=product.id,
            status='active'
        ).first()
        
        commission_rate = 0
        if publication:
            commission = MarketCommission.query.filter_by(
                category_id=product.category_id,
                exposure=publication.exposure
            ).first()
            if commission:
                commission_rate = float(commission.take_rate_pct)
        
        commission_amount = (cart_item.total_price * commission_rate) / 100
        
        order_item = MarketOrderItem(
            order_id=order.id,
            seller_company_id=product.seller_company_id,
            variant_id=cart_item.variant_id,
            qty=cart_item.qty,
            unit_price=cart_item.price_snapshot,
            currency=cart_item.currency,
            commission_amount=commission_amount,
            seller_revealed=False  # Seller masking
        )
        
        db.session.add(order_item)
    
    # Limpiar carrito
    MarketCartItem.query.filter_by(cart_id=user_cart.id).delete()
    
    db.session.commit()
    
    return jsonify({
        'order_id': order.id,
        'order_number': order.order_number,
        'total': float(order.total),
        'redirect_url': url_for('marketplace_new.order_detail', order_id=order.id)
    })

@marketplace_new_bp.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    """Detalle de orden"""
    order = MarketOrder.query.get_or_404(order_id)
    
    # Verificar permisos
    if order.buyer_user_id != current_user.id:
        flash('No tienes permisos para ver esta orden.', 'error')
        return redirect(url_for('marketplace_new.home'))
    
    return render_template('marketplace_new/order_detail.html', order=order)

@marketplace_new_bp.route('/orders')
@login_required
def orders():
    """Lista de órdenes del usuario"""
    if not hasattr(current_user, 'company_id'):
        flash('Debes ser parte de una empresa.', 'error')
        return redirect(url_for('marketplace_new.home'))
    
    user_orders = MarketOrder.query.filter_by(
        buyer_company_id=current_user.company_id
    ).order_by(MarketOrder.created_at.desc()).all()
    
    return render_template('marketplace_new/orders.html', orders=user_orders)

# ===== Q&A =====

@marketplace_new_bp.route('/api/products/<int:product_id>/questions', methods=['POST'])
@login_required
def ask_question(product_id):
    """Hacer pregunta sobre producto"""
    if not hasattr(current_user, 'company_id'):
        return jsonify({'error': 'Usuario sin empresa'}), 400
    
    data = request.get_json()
    question_text = data.get('question', '').strip()
    
    if not question_text:
        return jsonify({'error': 'La pregunta no puede estar vacía'}), 400
    
    product = MarketProduct.query.get_or_404(product_id)
    
    question = MarketQuestion(
        product_id=product_id,
        buyer_company_id=current_user.company_id,
        buyer_user_id=current_user.id,
        question=question_text,
        is_public=True
    )
    
    db.session.add(question)
    db.session.commit()
    
    # TODO: Enviar notificación al seller
    
    return jsonify({'message': 'Pregunta enviada correctamente'})

# ===== SELLER DASHBOARD =====

@marketplace_new_bp.route('/seller')
@login_required
def seller_dashboard():
    """Dashboard del vendedor"""
    if not hasattr(current_user, 'company_id'):
        flash('Debes ser parte de una empresa.', 'error')
        return redirect(url_for('marketplace_new.home'))
    
    # Verificar que la empresa es vendedora
    company = MarketCompany.query.get(current_user.company_id)
    if not company or company.type not in ['seller', 'both']:
        flash('Tu empresa no está habilitada como vendedor.', 'error')
        return redirect(url_for('marketplace_new.home'))
    
    # Métricas básicas
    total_products = MarketProduct.query.filter_by(seller_company_id=current_user.company_id).count()
    active_publications = db.session.query(MarketPublication).join(MarketProduct).filter(
        MarketProduct.seller_company_id == current_user.company_id,
        MarketPublication.status == 'active'
    ).count()
    
    pending_orders = db.session.query(MarketOrderItem).filter(
        MarketOrderItem.seller_company_id == current_user.company_id
    ).join(MarketOrder).filter(
        MarketOrder.status == 'paid'
    ).count()
    
    # Órdenes recientes
    recent_orders = db.session.query(MarketOrderItem).filter(
        MarketOrderItem.seller_company_id == current_user.company_id
    ).join(MarketOrder).order_by(MarketOrder.created_at.desc()).limit(10).all()
    
    return render_template('marketplace_new/seller/dashboard.html',
                         metrics={
                             'total_products': total_products,
                             'active_publications': active_publications,
                             'pending_orders': pending_orders
                         },
                         recent_orders=recent_orders)

@marketplace_new_bp.route('/seller/products')
@login_required
def seller_products():
    """Gestión de productos del seller"""
    if not hasattr(current_user, 'company_id'):
        return redirect(url_for('marketplace_new.home'))
    
    products = MarketProduct.query.filter_by(
        seller_company_id=current_user.company_id
    ).order_by(MarketProduct.created_at.desc()).all()
    
    return render_template('marketplace_new/seller/products.html', products=products)

@marketplace_new_bp.route('/seller/orders')
@login_required
def seller_orders():
    """Órdenes del seller"""
    if not hasattr(current_user, 'company_id'):
        return redirect(url_for('marketplace_new.home'))
    
    order_items = db.session.query(MarketOrderItem).filter(
        MarketOrderItem.seller_company_id == current_user.company_id
    ).join(MarketOrder).order_by(MarketOrder.created_at.desc()).all()
    
    return render_template('marketplace_new/seller/orders.html', order_items=order_items)

# ===== ADMIN ROUTES =====

@marketplace_new_bp.route('/admin')
@login_required
def admin_dashboard():
    """Dashboard administrativo"""
    # TODO: Verificar permisos de admin
    
    # Métricas generales
    total_companies = MarketCompany.query.count()
    total_products = MarketProduct.query.count()
    total_orders = MarketOrder.query.count()
    pending_approvals = MarketCompany.query.filter_by(kyc_status='pending').count()
    
    return render_template('marketplace_new/admin/dashboard.html',
                         metrics={
                             'total_companies': total_companies,
                             'total_products': total_products,
                             'total_orders': total_orders,
                             'pending_approvals': pending_approvals
                         })

@marketplace_new_bp.route('/admin/categories')
@login_required
def admin_categories():
    """Gestión de categorías"""
    categories = MarketCategory.query.order_by(MarketCategory.name.asc()).all()
    return render_template('marketplace_new/admin/categories.html', categories=categories)

@marketplace_new_bp.route('/admin/commissions')
@login_required
def admin_commissions():
    """Gestión de comisiones"""
    commissions = MarketCommission.query.join(MarketCategory).order_by(
        MarketCategory.name.asc(),
        MarketCommission.exposure.asc()
    ).all()
    
    categories = MarketCategory.query.filter_by(is_active=True).all()
    
    return render_template('marketplace_new/admin/commissions.html',
                         commissions=commissions,
                         categories=categories)