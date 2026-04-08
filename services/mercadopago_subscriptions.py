"""
Servicio de Suscripciones via Mercado Pago Preapproval API.

Doc oficial: https://www.mercadopago.com.ar/developers/es/reference/subscriptions/_preapproval/post

Flujo:
1. Usuario click en "Subscribirme" -> crear_preapproval() devuelve init_point URL
2. Usuario es redirigido a MP, completa datos de tarjeta y autoriza
3. MP cobra el primer pago y dispara webhook 'subscription_authorized_payment'
4. Nuestro webhook actualiza Subscription.status = 'authorized'
5. MP cobra automaticamente cada mes y dispara webhooks subsiguientes
6. Si el usuario cancela en MP, llega webhook 'subscription_preapproval' con status='cancelled'

Variables de entorno:
- MP_ACCESS_TOKEN_TEST: token de pruebas (sandbox)
- MP_ACCESS_TOKEN: token de produccion
- MP_USE_SANDBOX: '1' para usar el de prueba (default)
- MP_PRECIO_ARS: precio fijo en pesos (default 499000)
- MP_BASE_URL: URL publica de la app (para back_url y notification_url)
"""
import os
import json
from datetime import datetime
from decimal import Decimal

from flask import current_app

from extensions import db
from models.subscription import Subscription


def _get_access_token():
    """Devuelve el token TEST o PROD segun MP_USE_SANDBOX."""
    use_sandbox = os.environ.get('MP_USE_SANDBOX', '1') == '1'
    if use_sandbox:
        return os.environ.get('MP_ACCESS_TOKEN_TEST') or os.environ.get('MP_ACCESS_TOKEN')
    return os.environ.get('MP_ACCESS_TOKEN')


def _get_mp_client():
    import mercadopago
    token = _get_access_token()
    if not token:
        raise RuntimeError("No hay MP_ACCESS_TOKEN configurado")
    return mercadopago.SDK(token)


def _get_precio_ars() -> Decimal:
    return Decimal(os.environ.get('MP_PRECIO_ARS', '499000'))


def _get_base_url() -> str:
    return os.environ.get('MP_BASE_URL', 'https://app.obyra.com.ar').rstrip('/')


def crear_preapproval(organizacion, payer_email, created_by=None):
    """Crea una Preapproval en MP y guarda la Subscription local en estado 'pending'.

    Args:
        organizacion: instancia de Organizacion
        payer_email: email del usuario que va a pagar (puede diferir del admin)
        created_by: instancia de Usuario que dispara la creacion

    Returns:
        tuple (subscription, init_point_url)
    """
    sdk = _get_mp_client()
    monto = _get_precio_ars()
    base_url = _get_base_url()

    # Si la org ya tiene una sub pending, la reusamos para no llenar MP de basura
    sub_pendiente = Subscription.query.filter_by(
        organizacion_id=organizacion.id,
        status='pending'
    ).order_by(Subscription.created_at.desc()).first()
    if sub_pendiente and sub_pendiente.init_url:
        return sub_pendiente, sub_pendiente.init_url

    # External reference para encontrar la sub en webhooks
    external_ref = f'org_{organizacion.id}_{int(datetime.utcnow().timestamp())}'

    preapproval_data = {
        "reason": f"OBYRA Profesional - {organizacion.nombre}",
        "external_reference": external_ref,
        "payer_email": payer_email,
        "back_url": f"{base_url}/planes/mp/exito",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(monto),
            "currency_id": "ARS",
        },
        "status": "pending",
        # notification_url se setea a nivel app en panel de MP
    }

    try:
        result = sdk.preapproval().create(preapproval_data)
    except Exception as e:
        current_app.logger.exception("MP preapproval create error")
        raise RuntimeError(f"Error al conectar con Mercado Pago: {e}")

    if result.get("status") not in (200, 201):
        current_app.logger.error(f"MP preapproval failed: {result}")
        raise RuntimeError(f"Mercado Pago rechazo la solicitud: {result.get('response', {}).get('message', 'desconocido')}")

    response = result["response"]
    mp_id = response.get("id")
    init_point = response.get("init_point") or response.get("sandbox_init_point")

    sub = Subscription(
        organizacion_id=organizacion.id,
        created_by_id=created_by.id if created_by else None,
        mp_preapproval_id=mp_id,
        mp_payer_email=payer_email,
        plan_codigo='premium',
        plan_nombre='OBYRA Profesional',
        monto_ars=monto,
        frequency_type='months',
        frequency_value=1,
        status='pending',
        init_url=init_point,
        last_event_payload=json.dumps(response)[:5000],
    )
    db.session.add(sub)
    db.session.commit()

    return sub, init_point


def obtener_preapproval(mp_preapproval_id):
    """Consulta MP por el estado actual de un preapproval."""
    sdk = _get_mp_client()
    result = sdk.preapproval().get(mp_preapproval_id)
    if result.get("status") not in (200, 201):
        return None
    return result["response"]


def cancelar_preapproval(subscription):
    """Cancela una suscripcion en MP y la marca como cancelled localmente."""
    if not subscription.mp_preapproval_id:
        subscription.status = 'cancelled'
        subscription.cancelled_at = datetime.utcnow()
        db.session.commit()
        return True

    sdk = _get_mp_client()
    try:
        result = sdk.preapproval().update(subscription.mp_preapproval_id, {"status": "cancelled"})
        if result.get("status") in (200, 201):
            subscription.status = 'cancelled'
            subscription.cancelled_at = datetime.utcnow()
            db.session.commit()
            return True
    except Exception as e:
        current_app.logger.exception("Error cancelando preapproval en MP")
        raise RuntimeError(f"Error al cancelar en Mercado Pago: {e}")
    return False


def procesar_webhook(payload):
    """Procesa un evento de webhook de MP. Idempotente.

    Estructura tipica del payload:
        {
            "type": "subscription_preapproval",
            "data": {"id": "abc123"},
            ...
        }
    O con esquema viejo:
        {
            "topic": "preapproval",
            "resource": "https://api.mercadopago.com/preapproval/abc123",
            ...
        }

    Returns: dict con resultado para responder al webhook
    """
    # Extraer ID del preapproval del payload (soporta ambos esquemas)
    preapproval_id = None
    event_type = payload.get('type') or payload.get('topic') or ''

    if 'data' in payload and isinstance(payload['data'], dict):
        preapproval_id = payload['data'].get('id')
    elif 'resource' in payload:
        # extraer ID del final de la URL
        try:
            preapproval_id = payload['resource'].rstrip('/').split('/')[-1]
        except Exception:
            pass

    if not preapproval_id:
        return {'ok': False, 'error': 'No se pudo extraer preapproval_id del payload'}

    # Solo procesamos eventos de subscription/preapproval
    if 'preapproval' not in event_type and 'subscription' not in event_type:
        return {'ok': True, 'ignored': True, 'reason': f'event type {event_type} no relevante'}

    # Buscar la sub local
    sub = Subscription.query.filter_by(mp_preapproval_id=preapproval_id).first()
    if not sub:
        current_app.logger.warning(f"Webhook MP: preapproval {preapproval_id} no encontrado en DB")
        return {'ok': False, 'error': 'subscription no encontrada'}

    # Consultar MP por el estado actual
    mp_data = obtener_preapproval(preapproval_id)
    if not mp_data:
        return {'ok': False, 'error': 'no se pudo consultar MP'}

    # Mapear estados de MP a los nuestros
    mp_status = mp_data.get('status', '').lower()
    status_map = {
        'pending': 'pending',
        'authorized': 'authorized',
        'paused': 'paused',
        'cancelled': 'cancelled',
        'finished': 'finished',
    }
    nuevo_status = status_map.get(mp_status, sub.status)

    sub.status = nuevo_status
    sub.last_event_payload = json.dumps({'webhook': payload, 'mp_data': mp_data})[:5000]
    if nuevo_status == 'cancelled' and not sub.cancelled_at:
        sub.cancelled_at = datetime.utcnow()
    if nuevo_status == 'authorized':
        # Si MP ya tiene fechas de pago, las copiamos
        if mp_data.get('next_payment_date'):
            try:
                sub.next_payment_date = datetime.fromisoformat(mp_data['next_payment_date'].replace('Z', '+00:00'))
            except Exception:
                pass
        # Activar el plan en la organizacion
        try:
            org = sub.organizacion
            if org and org.plan_tipo != 'premium':
                org.plan_tipo = 'premium'
                org.max_obras = 999
                org.max_usuarios = 999
        except Exception:
            current_app.logger.exception("Error activando plan tras autorizacion")

    db.session.commit()
    return {'ok': True, 'subscription_id': sub.id, 'status': sub.status}


def get_subscription_activa(organizacion):
    """Devuelve la suscripcion authorized de la org, o None."""
    return Subscription.query.filter_by(
        organizacion_id=organizacion.id,
        status='authorized'
    ).order_by(Subscription.created_at.desc()).first()
