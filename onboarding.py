from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.routing import BuildError

from account import update_billing_from_form, update_profile_from_form

onboarding_bp = Blueprint('onboarding', __name__)


def _resolve_after_onboarding() -> str:
    for endpoint in (
        'reportes.dashboard',
        'obras.lista',
        'supplier_portal.dashboard',
        'index',
    ):
        try:
            return url_for(endpoint)
        except BuildError:
            continue
    return '/'


@onboarding_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    status = current_user.ensure_onboarding_status()

    # Solo admins necesitan completar billing
    requiere_billing = current_user.role == 'admin'

    if status.profile_completed and requiere_billing and not status.billing_completed and request.method != 'POST':
        return redirect(url_for('onboarding.billing'))

    if status.profile_completed and (not requiere_billing or status.billing_completed):
        return redirect(_resolve_after_onboarding())

    if request.method == 'POST':
        exito, mensaje = update_profile_from_form(current_user, request.form)
        if exito:
            if requiere_billing:
                flash('Perfil guardado. Ahora completá tus datos de facturación.', 'success')
                return redirect(url_for('onboarding.billing'))
            else:
                # Operarios y PMs no necesitan billing, marcar como completo
                status.mark_billing_completed()
                from extensions import db
                db.session.commit()
                flash('Perfil guardado correctamente. ¡Ya podés comenzar a usar OBYRA IA!', 'success')
                return redirect(_resolve_after_onboarding())
        flash(mensaje, 'danger')

    return render_template(
        'onboarding/profile.html',
        usuario=current_user,
        perfil=current_user.perfil,
        onboarding_status=status,
    )


@onboarding_bp.route('/billing', methods=['GET', 'POST'])
@login_required
def billing():
    status = current_user.ensure_onboarding_status()

    # Solo los administradores necesitan completar billing
    if current_user.role != 'admin':
        flash('Los datos de facturación son gestionados por el administrador principal.', 'info')
        return redirect(_resolve_after_onboarding())

    if not status.profile_completed:
        flash('Completá tu perfil antes de continuar con la facturación.', 'warning')
        return redirect(url_for('onboarding.profile'))

    if status.billing_completed and request.method != 'POST':
        return redirect(_resolve_after_onboarding())

    if request.method == 'POST':
        exito, mensaje = update_billing_from_form(current_user, request.form, require_card=True)
        if exito:
            flash('Datos de facturación guardados. ¡Ya podés comenzar a usar OBYRA IA!', 'success')
            return redirect(_resolve_after_onboarding())
        flash(mensaje, 'danger')

    return render_template(
        'onboarding/billing.html',
        usuario=current_user,
        billing_profile=current_user.billing_profile,
        onboarding_status=status,
        perfil=current_user.perfil,
    )
