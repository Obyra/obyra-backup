from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required
from werkzeug.routing import BuildError

from account import update_billing_from_form, update_profile_from_form

onboarding_bp = Blueprint('onboarding', __name__)


@onboarding_bp.route('/cargar-demo', methods=['POST'])
@login_required
def cargar_demo():
    """Crea una obra demo en la organizacion del usuario actual."""
    from services.demo_data_service import crear_obra_demo
    from services.memberships import get_current_org_id

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        flash('No tenes una organizacion activa', 'warning')
        return redirect(url_for('reportes.dashboard'))

    try:
        obra, created = crear_obra_demo(org_id, user_id=current_user.id)
        if created:
            flash(f'Obra demo "{obra.nombre}" creada con exito. Explorala desde el listado de obras.', 'success')
        else:
            flash('Ya existe una obra demo en tu organizacion.', 'info')
        return redirect(url_for('obras.detalle', id=obra.id))
    except Exception as e:
        current_app.logger.exception('Error creando obra demo')
        flash(f'Error al cargar datos demo: {e}', 'danger')
        return redirect(url_for('reportes.dashboard'))


@onboarding_bp.route('/eliminar-demo', methods=['POST'])
@login_required
def eliminar_demo():
    """Elimina la obra demo de la organizacion."""
    from services.demo_data_service import eliminar_obra_demo
    from services.memberships import get_current_org_id

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        return redirect(url_for('reportes.dashboard'))

    try:
        if eliminar_obra_demo(org_id):
            flash('Obra demo eliminada correctamente.', 'success')
        else:
            flash('No habia obra demo para eliminar.', 'info')
    except Exception as e:
        current_app.logger.exception('Error eliminando obra demo')
        flash(f'Error: {e}', 'danger')
    return redirect(url_for('reportes.dashboard'))


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
        # Mitigacion: durante el trial NO pedimos tarjeta. Solo guardamos
        # los datos de facturacion (razon social, CUIT, email, direccion)
        # para emitir factura cuando active la suscripcion.
        exito, mensaje = update_billing_from_form(current_user, request.form, require_card=False)
        if exito:
            status.mark_billing_completed()
            from extensions import db
            db.session.commit()
            flash('Datos guardados. Comenza a usar OBYRA gratis durante 30 dias. Antes de que termine te contactamos para activar tu suscripcion.', 'success')
            return redirect(_resolve_after_onboarding())
        flash(mensaje, 'danger')

    return render_template(
        'onboarding/billing.html',
        usuario=current_user,
        billing_profile=current_user.billing_profile,
        onboarding_status=status,
        perfil=current_user.perfil,
    )
