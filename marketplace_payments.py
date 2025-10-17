"""
OBYRA Market - Payment Processing with Mercado Pago
Handles payment creation, webhooks, and purchase order generation
"""

from flask import Blueprint, request, jsonify, current_app, render_template
from extensions import db
from models_marketplace import *
from datetime import datetime
import json

payments_bp = Blueprint('payments', __name__)

@payments_bp.route('/api/payments/mp/create-preference', methods=['POST'])
def create_mp_preference():
    """Crear preferencia de pago en Mercado Pago"""
    try:
        import mercadopago

        data = request.get_json()
        order_id = data.get('order_id')

        order = MarketOrder.query.get_or_404(order_id)

        access_token = current_app.config.get('MP_ACCESS_TOKEN')
        if not access_token:
            current_app.logger.error(
                'Mercado Pago access token missing; cannot create payment preference.'
            )
            return jsonify({"error": "Mercado Pago no está configurado"}), 503

        # Configurar SDK de MercadoPago
        sdk = mercadopago.SDK(access_token)

        # Items para MP (agrupados, sin revelar sellers)
        items = []
        for item in order.items:
            product = item.variant.product
            items.append({
                "id": str(item.variant.id),
                "title": f"{product.name} - {item.variant.sku}",
                "description": product.description_html or product.name,
                "quantity": item.qty,
                "unit_price": float(item.unit_price),
                "currency_id": item.currency
            })
        
        preference_data = {
            "items": items,
            "payer": {
                "name": order.buyer_user.name,
                "email": order.buyer_user.email
            },
            "payment_methods": {
                "excluded_payment_types": [],
                "installments": 12
            },
            "back_urls": {
                "success": f"{current_app.config['BASE_URL']}/marketplace_new/payment-success",
                "failure": f"{current_app.config['BASE_URL']}/marketplace_new/payment-failure",
                "pending": f"{current_app.config['BASE_URL']}/marketplace_new/payment-pending"
            },
            "auto_return": "approved",
            "external_reference": str(order.id),
            "notification_url": current_app.config.get('MP_WEBHOOK_PUBLIC_URL'),
            "statement_descriptor": "OBYRA MARKET"
        }
        
        preference_response = sdk.preference().create(preference_data)

        if preference_response["status"] == 201:
            return jsonify({
                "preference_id": preference_response["response"]["id"],
                "init_point": preference_response["response"]["init_point"],
                "sandbox_init_point": preference_response["response"]["sandbox_init_point"]
            })
        else:
            current_app.logger.error(f"Error creating MP preference: {preference_response}")
            return jsonify({"error": "Error al crear preferencia de pago"}), 500

    except Exception:
        current_app.logger.exception("Exception in create_mp_preference")
        return jsonify({"error": "Error interno del servidor"}), 500

@payments_bp.route('/api/payments/mp/webhook', methods=['POST'])
def mp_webhook():
    """Webhook de Mercado Pago para confirmar pagos"""
    try:
        current_app.logger.info(
            f"MP webhook URL: {current_app.config.get('MP_WEBHOOK_PUBLIC_URL')}"
        )

        # Log del webhook recibido
        webhook_data = request.get_json() or {}
        current_app.logger.info(f"MP Webhook received: {webhook_data}")

        # Verificar que es una notificación de pago
        if webhook_data.get("type") != "payment":
            return jsonify({"status": "ignored"}), 200

        payment_id = webhook_data.get("data", {}).get("id")
        if not payment_id:
            return jsonify({"error": "No payment ID"}), 400

        access_token = current_app.config.get('MP_ACCESS_TOKEN')
        if not access_token:
            current_app.logger.error(
                'Mercado Pago access token missing; cannot process webhook.'
            )
            return jsonify({"error": "Mercado Pago no está configurado"}), 503

        import mercadopago

        sdk = mercadopago.SDK(access_token)

        # Obtener información del pago
        payment_response = sdk.payment().get(payment_id)

        if payment_response["status"] != 200:
            current_app.logger.error(f"Error getting payment info: {payment_response}")
            return jsonify({"error": "Error getting payment info"}), 500
        
        payment_data = payment_response["response"]
        
        # Obtener la orden usando external_reference
        external_reference = payment_data.get("external_reference")
        if not external_reference:
            current_app.logger.error("No external_reference in payment data")
            return jsonify({"error": "No external_reference"}), 400

        order = MarketOrder.query.get(int(external_reference))
        if not order:
            current_app.logger.error(f"Order not found: {external_reference}")
            return jsonify({"error": "Order not found"}), 404
        
        # Procesar según el estado del pago
        payment_status = payment_data.get("status")
        
        if payment_status == "approved":
            # Pago aprobado - actualizar orden y generar OCs
            order.status = 'paid'
            order.payment_status = 'paid'
            order.payment_method = payment_data.get("payment_method_id", "mercadopago")
            
            # Crear registro de pago
            payment_record = MarketPayment(
                order_id=order.id,
                provider='mercadopago',
                provider_ref=str(payment_id),
                status='approved',
                amount=order.total,
                currency=order.currency,
                paid_at=datetime.utcnow()
            )
            db.session.add(payment_record)
            
            # Revelar sellers en order_items (seller masking removal)
            for item in order.items:
                item.seller_revealed = True
            
            db.session.commit()
            
            # Generar órdenes de compra por seller
            try:
                from services.po_service import generate_purchase_orders
                generate_purchase_orders(order.id)
                current_app.logger.info(f"Purchase orders generated for order {order.id}")
            except Exception:
                current_app.logger.exception(
                    f"Error generating purchase orders for order {order.id}"
                )

            return jsonify({"status": "payment_processed"}), 200

        elif payment_status in ["rejected", "cancelled"]:
            # Pago rechazado/cancelado
            order.payment_status = 'failed'
            
            payment_record = MarketPayment(
                order_id=order.id,
                provider='mercadopago',
                provider_ref=str(payment_id),
                status='rejected',
                amount=order.total,
                currency=order.currency
            )
            db.session.add(payment_record)
            db.session.commit()

            return jsonify({"status": "payment_failed"}), 200

        elif payment_status == "pending":
            # Pago pendiente
            order.payment_status = 'pending'
            
            payment_record = MarketPayment(
                order_id=order.id,
                provider='mercadopago',
                provider_ref=str(payment_id),
                status='pending',
                amount=order.total,
                currency=order.currency
            )
            db.session.add(payment_record)
            db.session.commit()

            return jsonify({"status": "payment_pending"}), 200

        else:
            current_app.logger.warning(f"Unknown payment status: {payment_status}")
            return jsonify({"status": "unknown_status"}), 200

    except Exception:
        current_app.logger.exception("Exception in mp_webhook")
        return jsonify({"error": "Internal server error"}), 500


@payments_bp.route('/api/payments/mp/health', methods=['GET'])
def mp_webhook_health():
    """Endpoint de salud para validar despliegues sin tocar Mercado Pago."""

    return jsonify(
        {
            "ok": True,
            "webhook": bool(current_app.config.get('MP_WEBHOOK_PUBLIC_URL')),
        }
    )

@payments_bp.route('/payment-success')
def payment_success():
    """Página de éxito de pago"""
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    external_reference = request.args.get('external_reference')
    
    order = None
    if external_reference:
        order = MarketOrder.query.get(int(external_reference))
    
    return render_template('marketplace_new/payment_success.html', 
                         order=order, 
                         payment_id=payment_id,
                         status=status)

@payments_bp.route('/payment-failure')
def payment_failure():
    """Página de fallo de pago"""
    return render_template('marketplace_new/payment_failure.html')

@payments_bp.route('/payment-pending')
def payment_pending():
    """Página de pago pendiente"""
    return render_template('marketplace_new/payment_pending.html')
