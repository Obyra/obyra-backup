"""
OBYRA Market - Payment Processing with Mercado Pago
Handles payment creation, webhooks, and purchase order generation

Seguridad implementada:
- Validación de firma HMAC-SHA256 en webhooks
- Prevención de replay attacks
- Logging de seguridad para auditoría
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
    """
    Webhook de Mercado Pago para confirmar pagos.

    Seguridad:
    - Valida firma HMAC-SHA256 en producción
    - Previene replay attacks
    - Registra eventos de seguridad
    """
    try:
        # Importar validador
        from utils.webhook_validator import (
            validate_mp_signature,
            check_replay_attack,
            mark_webhook_processed
        )
        from utils.security_logger import log_security_event

        # Obtener headers de seguridad
        x_signature = request.headers.get('x-signature', '')
        x_request_id = request.headers.get('x-request-id', '')
        payload = request.get_data()

        # Obtener configuración
        webhook_secret = current_app.config.get('MP_WEBHOOK_SECRET')
        is_production = current_app.config.get('FLASK_ENV') == 'production'

        # === VALIDACIÓN DE FIRMA ===
        if is_production:
            if not webhook_secret:
                log_security_event(
                    event_type='webhook_rejected',
                    details={'reason': 'no_secret_configured', 'provider': 'mercadopago'},
                    severity='critical'
                )
                current_app.logger.error(
                    "CRÍTICO: MP_WEBHOOK_SECRET no configurado en producción"
                )
                return jsonify({"error": "Webhook validation failed"}), 401

            if not validate_mp_signature(payload, x_signature, x_request_id, webhook_secret):
                log_security_event(
                    event_type='webhook_rejected',
                    details={
                        'reason': 'invalid_signature',
                        'provider': 'mercadopago',
                        'request_id': x_request_id,
                        'ip': request.remote_addr
                    },
                    severity='high'
                )
                current_app.logger.warning(
                    f"MP webhook rechazado: firma inválida (request_id: {x_request_id})"
                )
                return jsonify({"error": "Invalid signature"}), 401
        elif webhook_secret:
            # En desarrollo con secret configurado, validar pero loguear
            if not validate_mp_signature(payload, x_signature, x_request_id, webhook_secret):
                current_app.logger.warning(
                    f"MP webhook: firma inválida en desarrollo (request_id: {x_request_id})"
                )

        # === PREVENCIÓN DE REPLAY ATTACKS ===
        if x_request_id and check_replay_attack(x_request_id):
            log_security_event(
                event_type='webhook_replay_detected',
                details={'provider': 'mercadopago', 'request_id': x_request_id},
                severity='medium'
            )
            current_app.logger.warning(
                f"MP webhook: replay detectado (request_id: {x_request_id})"
            )
            return jsonify({"status": "already_processed"}), 200

        # === PROCESAR WEBHOOK ===
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

            # Marcar webhook como procesado (prevención de replay)
            if x_request_id:
                mark_webhook_processed(x_request_id, payload)

            # Log de seguridad - pago exitoso
            log_security_event(
                event_type='payment_approved',
                details={
                    'order_id': order.id,
                    'payment_id': payment_id,
                    'amount': float(order.total),
                    'currency': order.currency
                },
                severity='info'
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

            # Marcar webhook como procesado
            if x_request_id:
                mark_webhook_processed(x_request_id, payload)

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

            # Marcar webhook como procesado
            if x_request_id:
                mark_webhook_processed(x_request_id, payload)

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
