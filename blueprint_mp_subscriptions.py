"""
Blueprint para suscripciones via Mercado Pago Preapproval.

Rutas:
- POST /planes/mp/subscribirme           : crea preapproval y redirige a MP
- GET  /planes/mp/exito                  : callback de MP tras autorizacion
- GET  /planes/mp/error                  : callback de MP en caso de error
- POST /api/mercadopago/webhook          : recibe eventos de MP (publico)
- POST /account/subscription/cancelar    : cancela la suscripcion activa
- GET  /account/subscription             : ver estado de la suscripcion
"""
import json
from flask import (Blueprint, request, redirect, url_for, flash,
                   render_template, jsonify, current_app)
from flask_login import login_required, current_user

from extensions import db
from models.subscription import Subscription
from services.mercadopago_subscriptions import (
    crear_preapproval,
    cancelar_preapproval,
    procesar_webhook,
    get_subscription_activa,
)

mp_subs_bp = Blueprint('mp_subs', __name__)


@mp_subs_bp.route('/planes/mp/subscribirme', methods=['POST'])
@login_required
def subscribirme():
    """Crea preapproval en MP y redirige al usuario a autorizar el cobro."""
    org = current_user.organizacion
    if not org:
        flash('No tenes una organizacion activa', 'warning')
        return redirect(url_for('planes.mostrar_planes'))

    # Solo admin puede subscribir
    if (getattr(current_user, 'role', '') or '').lower() not in ('admin', 'administrador'):
        flash('Solo el administrador puede activar la suscripcion', 'warning')
        return redirect(url_for('planes.mostrar_planes'))

    # Permitir que el usuario indique un email distinto para MP
    # (su cuenta de Mercado Pago puede usar otro email que el de OBYRA)
    payer_email = (request.form.get('payer_email') or '').strip() or current_user.email
    if not payer_email:
        flash('Tu cuenta no tiene email registrado', 'danger')
        return redirect(url_for('planes.mostrar_planes'))

    try:
        sub, init_url = crear_preapproval(org, payer_email, created_by=current_user)
        if not init_url:
            flash('No se pudo generar el link de pago', 'danger')
            return redirect(url_for('planes.mostrar_planes'))
        return redirect(init_url)
    except Exception as e:
        current_app.logger.exception("Error en subscribirme")
        flash(f'Error al iniciar suscripcion: {e}', 'danger')
        return redirect(url_for('planes.mostrar_planes'))


@mp_subs_bp.route('/planes/mp/exito')
@login_required
def exito():
    """Callback de MP tras autorizacion exitosa."""
    return render_template('planes/mp_exito.html')


@mp_subs_bp.route('/planes/mp/error')
@login_required
def error():
    return render_template('planes/mp_error.html')


@mp_subs_bp.route('/api/mercadopago/webhook', methods=['POST', 'GET'])
def webhook():
    """Recibe notificaciones de MP. Publico (sin auth).

    MP envia POST con JSON, pero a veces tambien GET con query params.
    Idempotencia: el servicio re-consulta MP por el estado actual, asi
    que aunque llegue 5 veces el mismo evento, el resultado es el mismo.
    """
    try:
        if request.method == 'POST':
            payload = request.get_json(silent=True) or {}
            # MP a veces manda los datos en query string ademas
            if not payload and request.args:
                payload = dict(request.args)
        else:
            payload = dict(request.args)

        current_app.logger.info(f"MP Webhook recibido: {json.dumps(payload)[:500]}")

        result = procesar_webhook(payload)
        # MP espera 200/201 para no reintentar. Si devolvemos error, MP reintenta.
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.exception("Error procesando webhook MP")
        # 200 igual para que MP no haga retry storm si el bug es nuestro
        return jsonify({'ok': False, 'error': str(e)}), 200


@mp_subs_bp.route('/account/subscription')
@login_required
def ver_subscription():
    """Pantalla con el estado de la suscripcion del usuario."""
    org = current_user.organizacion
    if not org:
        flash('No tenes una organizacion activa', 'warning')
        return redirect(url_for('index'))

    sub_activa = get_subscription_activa(org)
    historial = Subscription.query.filter_by(
        organizacion_id=org.id
    ).order_by(Subscription.created_at.desc()).limit(10).all()

    return render_template(
        'account/subscription.html',
        sub_activa=sub_activa,
        historial=historial,
        organizacion=org,
    )


@mp_subs_bp.route('/account/subscription/cancelar', methods=['POST'])
@login_required
def cancelar():
    """Cancela la suscripcion activa de la organizacion."""
    org = current_user.organizacion
    if not org:
        return jsonify(ok=False, error='Sin organizacion'), 400

    if (getattr(current_user, 'role', '') or '').lower() not in ('admin', 'administrador'):
        return jsonify(ok=False, error='Solo admin puede cancelar'), 403

    sub = get_subscription_activa(org)
    if not sub:
        flash('No tenes una suscripcion activa para cancelar', 'info')
        return redirect(url_for('mp_subs.ver_subscription'))

    try:
        cancelar_preapproval(sub)
        flash('Tu suscripcion fue cancelada. Vas a poder seguir usando OBYRA hasta el final del periodo facturado.', 'success')
    except Exception as e:
        current_app.logger.exception("Error cancelando suscripcion")
        flash(f'Error al cancelar: {e}', 'danger')

    return redirect(url_for('mp_subs.ver_subscription'))
