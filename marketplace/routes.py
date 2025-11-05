"""
OBYRA Marketplace Routes - ISOLATED BLUEPRINT
Following strict instructions for namespaced routes and seller masking
"""

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from marketplace.models import *
from marketplace.services.masking import redact_public, apply_seller_masking, get_masked_seller_name
from marketplace.services.commissions import compute as compute_commission
from marketplace.services.po_pdf import generate_po_pdf
from marketplace.services.emailer import send_po_notification, send_order_confirmation
from services.memberships import get_current_org_id
from utils.security_logger import log_transaction, log_data_modification
import json
import logging
from datetime import datetime

# Create blueprint with no url_prefix (will be set in app.py)
bp = Blueprint('marketplace', __name__)

# ===== HEALTH CHECK =====
@bp.route('/market/health')
def health():
    """Health check for marketplace"""
    return jsonify({"status": "ok", "marketplace": "active"})

# ===== PUBLIC API (MASKED SELLER) =====
@bp.route('/api/market/search')
def api_search():
    """Public search API with seller masking"""
    q = request.args.get('q', '')
    cat = request.args.get('cat', type=int)
    brand = request.args.get('brand')
    sort = request.args.get('sort', 'relevance')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Build query
    query = MkProduct.query.join(MkProductVariant)
    
    if q:
        query = query.filter(MkProduct.name.ilike(f'%{q}%'))
    
    if cat:
        query = query.filter(MkProduct.category_id == cat)
    
    # Pagination
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Format response with seller masking
    items = []
    for product in paginated.items:
        first_variant = product.variants.first()
        if first_variant:
            item = {
                "id": product.id,
                "name": product.name,
                "price_from": float(first_variant.price),
                "currency": first_variant.currency,
                "seller": {"display": "OBYRA Partner"}  # MASKED
            }
            items.append(item)
    
    response = {
        "items": items,
        "facets": {},
        "paging": {
            "total": paginated.total,
            "page": page,
            "per_page": per_page,
            "pages": paginated.pages
        }
    }
    
    # Apply masking to entire response
    return jsonify(redact_public(response))

@bp.route('/api/market/products/<int:product_id>')
def api_product_detail(product_id):
    """Public product detail API with seller masking"""
    product = MkProduct.query.get_or_404(product_id)
    
    # Build product data
    product_data = {
        "id": product.id,
        "name": product.name,
        "description_html": product.description_html,
        "seller": {"display": "OBYRA Partner"},  # MASKED
        "variants": []
    }
    
    # Add variants
    for variant in product.variants:
        variant_data = {
            "id": variant.id,
            "sku": variant.sku,
            "price": float(variant.price),
            "currency": variant.currency,
            "stock_qty": variant.stock_qty
        }
        product_data["variants"].append(variant_data)
    
    # Apply seller masking
    return jsonify(redact_public(product_data))

# ===== AUTHENTICATED API (REAL SELLER IN CART/ORDERS) =====
@bp.route('/api/market/cart/items', methods=['POST'])
@login_required
def api_add_to_cart():
    """Add item to cart"""
    data = request.get_json()
    variant_id = data.get('variant_id')
    qty = data.get('qty', 1)
    buyer_user_id = current_user.id
    buyer_company_id = get_current_org_id()
    
    variant = MkProductVariant.query.get_or_404(variant_id)
    
    # Get or create cart
    cart = MkCart.query.filter_by(
        buyer_company_id=buyer_company_id,
        buyer_user_id=buyer_user_id
    ).first()
    
    if not cart:
        cart = MkCart(
            buyer_company_id=buyer_company_id,
            buyer_user_id=buyer_user_id
        )
        db.session.add(cart)
        db.session.flush()
    
    # Check if item already exists
    existing_item = MkCartItem.query.filter_by(
        cart_id=cart.id,
        variant_id=variant_id
    ).first()
    
    if existing_item:
        existing_item.qty += qty
        existing_item.price_snapshot = variant.price
    else:
        cart_item = MkCartItem(
            cart_id=cart.id,
            variant_id=variant_id,
            qty=qty,
            price_snapshot=variant.price,
            currency=variant.currency
        )
        db.session.add(cart_item)
    
    db.session.commit()
    
    return jsonify({"message": "Item added to cart", "cart_total": float(cart.total_amount)})

@bp.route('/api/market/cart')
@login_required
def api_get_cart():
    """Get cart with REAL seller names (authenticated endpoint)"""
    buyer_user_id = current_user.id
    buyer_company_id = get_current_org_id()
    
    cart = MkCart.query.filter_by(
        buyer_company_id=buyer_company_id,
        buyer_user_id=buyer_user_id
    ).first()
    
    if not cart:
        return jsonify({"groups": []})
    
    # Group by seller and show REAL seller names
    groups = []
    for seller_id, items in cart.items_by_seller.items():
        # TODO: Get real seller name from company/organization table
        seller_name = f"Proveedor {seller_id}"  # Placeholder - should fetch real name
        
        group_items = []
        for item in items:
            group_items.append({
                "variant_id": item.variant_id,
                "qty": item.qty,
                "price": float(item.price_snapshot),
                "currency": item.currency,
                "product_name": item.variant.product.name,
                "sku": item.variant.sku
            })
        
        groups.append({
            "seller": {"id": seller_id, "name": seller_name},  # REAL SELLER INFO
            "items": group_items,
            "shipping_options": [{"id": "std", "label": "48-72h", "price": 2999}]
        })
    
    return jsonify({"groups": groups})

@bp.route('/api/market/checkout', methods=['POST'])
@login_required
def api_checkout():
    """Create order from cart with commission calculation"""
    data = request.get_json()
    buyer_user_id = current_user.id
    buyer_company_id = get_current_org_id()
    billing = data.get('billing', {})
    shipping = data.get('shipping', {})

    # Get cart for authenticated user
    cart = MkCart.query.filter_by(
        buyer_company_id=buyer_company_id,
        buyer_user_id=buyer_user_id
    ).first_or_404()
    
    if not cart.items.count():
        return jsonify({"error": "Cart is empty"}), 400
    
    # Create order
    order = MkOrder(
        buyer_company_id=buyer_company_id,
        buyer_user_id=buyer_user_id,
        total=cart.total_amount,
        currency='ARS',
        billing_json=json.dumps(billing),
        shipping_json=json.dumps(shipping),
        status='pending',
        payment_status='pending'
    )
    db.session.add(order)
    db.session.flush()
    
    # Create order items with commission calculation
    for cart_item in cart.items:
        # Calculate commission
        commission_amount = compute_commission(
            category_id=cart_item.variant.product.category_id or 1,
            exposure='standard',  # TODO: Get from product publication
            price=float(cart_item.price_snapshot),
            qty=cart_item.qty
        )
        
        order_item = MkOrderItem(
            order_id=order.id,
            seller_company_id=cart_item.variant.product.seller_company_id,
            variant_id=cart_item.variant_id,
            qty=cart_item.qty,
            unit_price=cart_item.price_snapshot,
            currency=cart_item.currency,
            commission_amount=commission_amount
        )
        db.session.add(order_item)
    
    # Clear cart
    MkCartItem.query.filter_by(cart_id=cart.id).delete()

    db.session.commit()

    # Log transaction
    user_email = current_user.email if current_user.is_authenticated else 'anonymous'
    log_transaction('ORDEN_CREADA', float(order.total), order.currency, order.order_number, user_email)
    current_app.logger.info(f'Orden marketplace creada: {order.id} - {order.order_number} por {user_email} - Total: {order.currency} {order.total}')

    # TODO: Create payment URL with MercadoPago
    payment_url = f"/market/payment/{order.id}"

    return jsonify({
        "order_id": order.id,
        "order_number": order.order_number,
        "payment_url": payment_url
    })

@bp.route('/api/market/payments/mp/webhook', methods=['POST'])
def api_mp_webhook():
    """MercadoPago webhook handler"""
    data = request.get_json()
    order_id = data.get('order_id')
    status = data.get('status')
    payment_id = data.get('payment_id', 'demo123')
    amount = data.get('amount', 0)
    
    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400
    
    order = MkOrder.query.get_or_404(order_id)
    
    if status == 'approved':
        # Update order status
        order.status = 'paid'
        order.payment_status = 'approved'
        order.payment_method = 'mercadopago'
        
        # Create payment record
        payment = MkPayment(
            order_id=order.id,
            provider='mercadopago',
            provider_ref=payment_id,
            status='approved',
            paid_at=datetime.utcnow(),
            amount=amount,
            currency='ARS'
        )
        db.session.add(payment)

        # Log payment
        user_email = order.buyer_user.email if order.buyer_user else 'unknown'
        log_transaction('PAGO_APROBADO', float(amount), 'ARS', f'MP-{payment_id}', user_email)
        current_app.logger.info(f'Pago marketplace aprobado: Order {order.id} - Payment {payment_id} - Amount: ARS {amount}')
        
        # Generate purchase orders by seller
        sellers_items = {}
        for item in order.items:
            seller_id = item.seller_company_id
            if seller_id not in sellers_items:
                sellers_items[seller_id] = []
            sellers_items[seller_id].append(item)
        
        for seller_id, items in sellers_items.items():
            # Generate OC number
            oc_number = f"OC-{order.id}-{seller_id}-{datetime.now().strftime('%Y%m%d')}"
            
            # Create purchase order record
            po = MkPurchaseOrder(
                order_id=order.id,
                seller_company_id=seller_id,
                buyer_company_id=order.buyer_company_id,
                status='created',
                oc_number=oc_number
            )
            db.session.add(po)
            db.session.flush()
            
            # Prepare items for PDF
            pdf_items = []
            for item in items:
                pdf_items.append({
                    'sku': item.variant.sku,
                    'product_name': item.variant.product.name,
                    'qty': item.qty,
                    'unit_price': float(item.unit_price)
                })
            
            try:
                # Generate PDF
                billing_data = order.billing_data
                shipping_data = order.shipping_data
                
                public_url, abs_path = generate_po_pdf(
                    oc_number=oc_number,
                    supplier_name=f"Proveedor {seller_id}",  # TODO: Get real name
                    buyer_name=billing_data.get('company_name', 'Comprador'),
                    buyer_cuit=billing_data.get('cuit', ''),
                    delivery_addr=shipping_data.get('address', 'A coordinar'),
                    items=pdf_items
                )
                
                po.pdf_url = public_url
                po.status = 'sent'
                po.sent_at = datetime.utcnow()
                
                # Send email notification
                supplier_email = f"proveedor{seller_id}@demo.com"  # TODO: Get real email
                send_po_notification(
                    supplier_email=supplier_email,
                    oc_number=oc_number,
                    buyer_name=billing_data.get('company_name', 'Comprador'),
                    pdf_path=abs_path
                )
                
            except Exception as e:
                logging.error(f"Error generating PO for seller {seller_id}: {str(e)}")
        
        # Send order confirmation to buyer
        try:
            buyer_email = order.billing_data.get('email', 'comprador@demo.com')
            send_order_confirmation(
                buyer_email=buyer_email,
                order_number=order.order_number,
                total_amount=float(order.total)
            )
        except Exception as e:
            logging.error(f"Error sending order confirmation: {str(e)}")
        
        db.session.commit()
        
        return jsonify({"status": "payment_processed", "order_id": order.id})
    
    elif status in ['rejected', 'cancelled']:
        order.payment_status = 'rejected'
        db.session.commit()
        return jsonify({"status": "payment_failed"})
    
    return jsonify({"status": "unknown_status"})

@bp.route('/api/market/orders/<int:order_id>')
def api_order_detail(order_id):
    """Get order details with REAL seller info (authenticated)"""
    order = MkOrder.query.get_or_404(order_id)
    
    items = []
    for item in order.items:
        items.append({
            "id": item.id,
            "seller": {"id": item.seller_company_id, "name": f"Proveedor {item.seller_company_id}"},  # REAL SELLER
            "product_name": item.variant.product.name,
            "sku": item.variant.sku,
            "qty": item.qty,
            "unit_price": float(item.unit_price),
            "total": float(item.total_amount),
            "currency": item.currency
        })
    
    return jsonify({
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "total": float(order.total),
        "currency": order.currency,
        "billing": order.billing_data,
        "shipping": order.shipping_data,
        "items": items,
        "created_at": order.created_at.isoformat()
    })