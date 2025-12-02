"""
Validador de Webhooks de Mercado Pago
=====================================
Implementa validación de firma HMAC-SHA256 según documentación oficial de MP.
https://www.mercadopago.com.ar/developers/es/docs/your-integrations/notifications/webhooks

Seguridad implementada:
1. Validación de firma HMAC-SHA256
2. Prevención de replay attacks (request_id único)
3. Validación de timestamp (máx 5 minutos de antigüedad)
4. Logging de seguridad para auditoría
"""

import hmac
import hashlib
import time
from functools import wraps
from flask import request, jsonify, current_app
from extensions import db
from datetime import datetime


class WebhookValidationError(Exception):
    """Error de validación de webhook"""
    pass


# Modelo para trackear webhooks procesados (prevención de replay)
class ProcessedWebhook(db.Model):
    """Registro de webhooks procesados para evitar replay attacks"""
    __tablename__ = 'processed_webhooks'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False)  # mercadopago, stripe, etc
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    payload_hash = db.Column(db.String(64))  # SHA256 del payload

    def __repr__(self):
        return f'<ProcessedWebhook {self.provider}:{self.request_id}>'


def validate_mp_signature(payload: bytes, x_signature: str, x_request_id: str, secret: str) -> bool:
    """
    Valida la firma de Mercado Pago según su documentación oficial.

    Mercado Pago envía el header x-signature con formato:
    ts=timestamp,v1=hash

    El hash se calcula como HMAC-SHA256 de:
    id=[data.id];request-id=[x-request-id];ts=[timestamp];

    Args:
        payload: Body del request en bytes
        x_signature: Header x-signature de MP
        x_request_id: Header x-request-id de MP
        secret: Webhook secret de MP

    Returns:
        True si la firma es válida, False si no
    """
    if not x_signature or not secret:
        return False

    try:
        # Parsear x-signature: "ts=1234567890,v1=abc123..."
        parts = {}
        for part in x_signature.split(','):
            if '=' in part:
                key, value = part.split('=', 1)
                parts[key] = value

        ts = parts.get('ts')
        v1 = parts.get('v1')

        if not ts or not v1:
            current_app.logger.warning("MP webhook: x-signature malformado")
            return False

        # Validar timestamp (máximo 5 minutos de antigüedad)
        try:
            timestamp = int(ts)
            current_time = int(time.time())
            if abs(current_time - timestamp) > 300:  # 5 minutos
                current_app.logger.warning(
                    f"MP webhook: timestamp fuera de rango ({current_time - timestamp}s)"
                )
                return False
        except ValueError:
            return False

        # Obtener data.id del payload
        import json
        try:
            payload_data = json.loads(payload)
            data_id = payload_data.get('data', {}).get('id', '')
        except (json.JSONDecodeError, TypeError):
            data_id = ''

        # Construir el manifest según documentación de MP
        # Formato: id=[data.id];request-id=[x-request-id];ts=[timestamp];
        manifest = f"id={data_id};request-id={x_request_id};ts={ts};"

        # Calcular HMAC-SHA256
        expected_hash = hmac.new(
            secret.encode('utf-8'),
            manifest.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Comparación segura para evitar timing attacks
        return hmac.compare_digest(expected_hash, v1)

    except Exception as e:
        current_app.logger.error(f"Error validando firma MP: {e}")
        return False


def check_replay_attack(request_id: str, provider: str = 'mercadopago') -> bool:
    """
    Verifica si un webhook ya fue procesado (prevención de replay attack).

    Args:
        request_id: ID único del request
        provider: Proveedor del webhook

    Returns:
        True si es un replay (ya procesado), False si es nuevo
    """
    if not request_id:
        return True  # Sin request_id = sospechoso

    existing = ProcessedWebhook.query.filter_by(
        request_id=request_id,
        provider=provider
    ).first()

    return existing is not None


def mark_webhook_processed(request_id: str, payload: bytes, provider: str = 'mercadopago'):
    """
    Marca un webhook como procesado para evitar replay attacks.

    Args:
        request_id: ID único del request
        payload: Payload del webhook
        provider: Proveedor del webhook
    """
    if not request_id:
        return

    payload_hash = hashlib.sha256(payload).hexdigest()

    webhook_record = ProcessedWebhook(
        request_id=request_id,
        provider=provider,
        payload_hash=payload_hash
    )

    try:
        db.session.add(webhook_record)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error registrando webhook: {e}")


def require_valid_mp_webhook(f):
    """
    Decorator para validar webhooks de Mercado Pago.

    Uso:
        @payments_bp.route('/webhook', methods=['POST'])
        @require_valid_mp_webhook
        def mp_webhook():
            # El código aquí solo se ejecuta si el webhook es válido
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Obtener headers de MP
        x_signature = request.headers.get('x-signature', '')
        x_request_id = request.headers.get('x-request-id', '')

        # Obtener payload
        payload = request.get_data()

        # Obtener secret de configuración
        webhook_secret = current_app.config.get('MP_WEBHOOK_SECRET')
        is_production = current_app.config.get('FLASK_ENV') == 'production'

        # Log de seguridad
        from utils.security_logger import log_security_event

        # En producción, SIEMPRE validar firma
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
                        'request_id': x_request_id
                    },
                    severity='high'
                )
                current_app.logger.warning(
                    f"MP webhook rechazado: firma inválida (request_id: {x_request_id})"
                )
                return jsonify({"error": "Invalid signature"}), 401

        # En desarrollo, validar SI hay secret configurado
        elif webhook_secret:
            if not validate_mp_signature(payload, x_signature, x_request_id, webhook_secret):
                current_app.logger.warning(
                    f"MP webhook: firma inválida en desarrollo (request_id: {x_request_id})"
                )
                # En desarrollo, loguear pero permitir (para testing)
                # Descomentar la siguiente línea para ser estricto también en desarrollo:
                # return jsonify({"error": "Invalid signature"}), 401

        # Verificar replay attack
        if x_request_id and check_replay_attack(x_request_id):
            log_security_event(
                event_type='webhook_replay_detected',
                details={
                    'provider': 'mercadopago',
                    'request_id': x_request_id
                },
                severity='medium'
            )
            current_app.logger.warning(
                f"MP webhook: replay detectado (request_id: {x_request_id})"
            )
            # Retornar 200 para que MP no reintente (ya fue procesado)
            return jsonify({"status": "already_processed"}), 200

        # Ejecutar el handler
        result = f(*args, **kwargs)

        # Marcar como procesado (solo si fue exitoso)
        if x_request_id:
            mark_webhook_processed(x_request_id, payload)

        return result

    return decorated_function


def cleanup_old_webhooks(days: int = 30):
    """
    Limpia registros de webhooks antiguos para evitar que la tabla crezca indefinidamente.

    Args:
        days: Eliminar registros más antiguos que estos días
    """
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(days=days)

    try:
        deleted = ProcessedWebhook.query.filter(
            ProcessedWebhook.processed_at < cutoff
        ).delete()
        db.session.commit()

        if deleted > 0:
            current_app.logger.info(f"Limpiados {deleted} webhooks antiguos")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error limpiando webhooks: {e}")
