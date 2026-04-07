"""
Blueprint de Cierre Formal de Obra.

Rutas:
- GET  /cierre-obra/                          → Lista de cierres
- GET  /cierre-obra/iniciar/<obra_id>         → Wizard paso 1: checklist
- POST /cierre-obra/iniciar/<obra_id>         → Crear cierre en borrador
- GET  /cierre-obra/<id>                       → Ver detalle del cierre
- POST /cierre-obra/<id>/confirmar            → Confirmar cierre (obra → finalizada)
- POST /cierre-obra/<id>/anular               → Anular cierre
- GET  /cierre-obra/<id>/acta/nueva           → Wizard acta paso 2: datos
- POST /cierre-obra/<id>/acta/nueva           → Crear acta
- GET  /cierre-obra/<id>/acta/<acta_id>/pdf   → PDF del acta de entrega
"""
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, current_app, send_file
)
from flask_login import login_required, current_user

from extensions import db
from services.memberships import get_current_org_id
from services.cierre_obra_service import CierreObraService, CierreObraError
from models import CierreObra, ActaEntrega, Obra


cierre_obra_bp = Blueprint(
    'cierre_obra',
    __name__,
    url_prefix='/cierre-obra'
)


def _require_admin_or_pm():
    """Helper: solo admin/pm pueden gestionar cierres."""
    role = getattr(current_user, 'role', None)
    rol = getattr(current_user, 'rol', None)
    allowed = {'admin', 'administrador', 'pm', 'project_manager'}
    if role not in allowed and rol not in allowed:
        if not getattr(current_user, 'is_super_admin', False):
            abort(403)


@cierre_obra_bp.route('/')
@login_required
def lista():
    """Lista todos los cierres de la organización."""
    org_id = get_current_org_id()
    if not org_id:
        flash('No tenés una organización activa.', 'warning')
        return redirect(url_for('reportes.dashboard'))

    estado = request.args.get('estado', '').strip() or None
    cierres = CierreObraService.listar_cierres(org_id, estado=estado)

    return render_template(
        'cierre_obra/lista.html',
        cierres=cierres,
        filtro_estado=estado,
    )


@cierre_obra_bp.route('/iniciar/<int:obra_id>', methods=['GET', 'POST'])
@login_required
def iniciar(obra_id):
    """Wizard paso 1: muestra checklist y permite crear el cierre."""
    _require_admin_or_pm()
    org_id = get_current_org_id()
    if not org_id:
        flash('No tenés una organización activa.', 'warning')
        return redirect(url_for('reportes.dashboard'))

    obra = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first_or_404()

    # Verificar si ya existe un cierre activo
    cierre_activo = CierreObraService.get_cierre_activo(obra_id)
    if cierre_activo:
        flash(
            f'Esta obra ya tiene un cierre {cierre_activo.estado_display.lower()}.',
            'info'
        )
        return redirect(url_for('cierre_obra.detalle', cierre_id=cierre_activo.id))

    if obra.estado in ('finalizada', 'cancelada'):
        flash(
            f'No se puede cerrar una obra en estado "{obra.estado}".',
            'warning'
        )
        return redirect(url_for('obras.detalle', id=obra_id))

    # Generar checklist actual
    checklist = CierreObraService.generar_checklist(obra)

    if request.method == 'POST':
        observaciones = request.form.get('observaciones', '').strip()
        try:
            cierre = CierreObraService.iniciar_cierre(
                obra_id=obra_id,
                organizacion_id=org_id,
                usuario_id=current_user.id,
                observaciones=observaciones,
            )
            flash('Cierre iniciado correctamente. Ahora podés cargar el acta de entrega.', 'success')
            return redirect(url_for('cierre_obra.detalle', cierre_id=cierre.id))
        except CierreObraError as e:
            flash(str(e), 'danger')
        except Exception as e:
            current_app.logger.error(f'Error iniciando cierre: {e}')
            flash('Error al iniciar el cierre. Intentá nuevamente.', 'danger')

    return render_template(
        'cierre_obra/iniciar.html',
        obra=obra,
        checklist=checklist,
    )


@cierre_obra_bp.route('/<int:cierre_id>')
@login_required
def detalle(cierre_id):
    """Vista detalle del cierre con sus actas."""
    org_id = get_current_org_id()
    cierre = CierreObra.query.filter_by(
        id=cierre_id, organizacion_id=org_id
    ).first_or_404()

    actas = cierre.actas.order_by(ActaEntrega.fecha_creacion.desc()).all()
    checklist = cierre.get_checklist()

    return render_template(
        'cierre_obra/detalle.html',
        cierre=cierre,
        actas=actas,
        checklist=checklist,
    )


@cierre_obra_bp.route('/<int:cierre_id>/confirmar', methods=['POST'])
@login_required
def confirmar(cierre_id):
    """Confirma el cierre: obra pasa a 'finalizada'."""
    _require_admin_or_pm()
    org_id = get_current_org_id()

    try:
        cierre = CierreObraService.confirmar_cierre(
            cierre_id=cierre_id,
            organizacion_id=org_id,
            usuario_id=current_user.id,
        )
        flash(
            f'Obra "{cierre.obra.nombre}" finalizada correctamente.',
            'success'
        )
    except CierreObraError as e:
        flash(str(e), 'danger')
    except Exception as e:
        current_app.logger.error(f'Error confirmando cierre {cierre_id}: {e}')
        flash('Error al confirmar el cierre.', 'danger')

    return redirect(url_for('cierre_obra.detalle', cierre_id=cierre_id))


@cierre_obra_bp.route('/<int:cierre_id>/anular', methods=['POST'])
@login_required
def anular(cierre_id):
    """Anula un cierre. Si la obra estaba finalizada, vuelve a en_curso."""
    _require_admin_or_pm()
    org_id = get_current_org_id()
    motivo = request.form.get('motivo', '').strip()

    try:
        CierreObraService.anular_cierre(
            cierre_id=cierre_id,
            organizacion_id=org_id,
            usuario_id=current_user.id,
            motivo=motivo,
        )
        flash('Cierre anulado correctamente.', 'success')
    except CierreObraError as e:
        flash(str(e), 'danger')
    except Exception as e:
        current_app.logger.error(f'Error anulando cierre {cierre_id}: {e}')
        flash('Error al anular el cierre.', 'danger')

    return redirect(url_for('cierre_obra.detalle', cierre_id=cierre_id))


@cierre_obra_bp.route('/<int:cierre_id>/acta/nueva', methods=['GET', 'POST'])
@login_required
def crear_acta(cierre_id):
    """Wizard paso 2: crear acta de entrega."""
    _require_admin_or_pm()
    org_id = get_current_org_id()

    cierre = CierreObra.query.filter_by(
        id=cierre_id, organizacion_id=org_id
    ).first_or_404()

    if cierre.estado == 'anulado':
        flash('No se pueden crear actas de un cierre anulado.', 'warning')
        return redirect(url_for('cierre_obra.detalle', cierre_id=cierre_id))

    if request.method == 'POST':
        datos = {
            'tipo': request.form.get('tipo', 'definitiva'),
            'fecha_acta': request.form.get('fecha_acta', ''),
            'recibido_por_nombre': request.form.get('recibido_por_nombre', ''),
            'recibido_por_dni': request.form.get('recibido_por_dni', ''),
            'recibido_por_cargo': request.form.get('recibido_por_cargo', ''),
            'descripcion': request.form.get('descripcion', ''),
            'observaciones_cliente': request.form.get('observaciones_cliente', ''),
            'observaciones_internas': request.form.get('observaciones_internas', ''),
            'items_entregados': request.form.get('items_entregados', ''),
            'plazo_garantia_meses': request.form.get('plazo_garantia_meses', ''),
        }
        try:
            acta = CierreObraService.crear_acta(
                cierre_id=cierre_id,
                organizacion_id=org_id,
                usuario_id=current_user.id,
                datos=datos,
            )
            flash('Acta de entrega creada correctamente.', 'success')

            # Envío automático por email si el usuario lo seleccionó
            if request.form.get('enviar_email_cliente') == '1':
                try:
                    from services.acta_email_service import enviar_acta_por_email
                    email_override = (request.form.get('email_destinatario') or '').strip() or None
                    result = enviar_acta_por_email(acta, destinatario_override=email_override)
                    if result['ok']:
                        flash(f'📧 Email enviado a {result["destinatario"]}', 'info')
                    else:
                        flash(f'⚠️ Acta creada pero el email no se envió: {result["message"]}', 'warning')
                except Exception as _email_e:
                    current_app.logger.error(f'Error enviando email del acta: {_email_e}')
                    flash('⚠️ Acta creada pero hubo un error al enviar el email.', 'warning')

            return redirect(url_for('cierre_obra.detalle', cierre_id=cierre_id))
        except CierreObraError as e:
            flash(str(e), 'danger')
        except Exception as e:
            current_app.logger.error(f'Error creando acta: {e}')
            flash('Error al crear el acta.', 'danger')

    return render_template(
        'cierre_obra/crear_acta.html',
        cierre=cierre,
    )


@cierre_obra_bp.route('/<int:cierre_id>/acta/<int:acta_id>')
@login_required
def ver_acta(cierre_id, acta_id):
    """Ver detalle de un acta."""
    org_id = get_current_org_id()
    acta = ActaEntrega.query.filter_by(
        id=acta_id,
        cierre_id=cierre_id,
        organizacion_id=org_id,
    ).first_or_404()

    return render_template(
        'cierre_obra/ver_acta.html',
        acta=acta,
        cierre=acta.cierre,
    )


@cierre_obra_bp.route('/<int:cierre_id>/acta/<int:acta_id>/enviar-email', methods=['POST'])
@login_required
def acta_enviar_email(cierre_id, acta_id):
    """Reenvía el acta de entrega por email al cliente."""
    _require_admin_or_pm()
    org_id = get_current_org_id()
    acta = ActaEntrega.query.filter_by(
        id=acta_id,
        cierre_id=cierre_id,
        organizacion_id=org_id,
    ).first_or_404()

    email_override = (request.form.get('email_destinatario') or '').strip() or None

    try:
        from services.acta_email_service import enviar_acta_por_email
        result = enviar_acta_por_email(acta, destinatario_override=email_override)
        if result['ok']:
            flash(f'📧 Email enviado a {result["destinatario"]}', 'success')
        else:
            flash(f'⚠️ No se pudo enviar el email: {result["message"]}', 'warning')
    except Exception as e:
        current_app.logger.error(f'Error enviando acta por email: {e}')
        flash('Error al enviar el email del acta.', 'danger')

    return redirect(url_for('cierre_obra.ver_acta', cierre_id=cierre_id, acta_id=acta_id))


@cierre_obra_bp.route('/<int:cierre_id>/acta/<int:acta_id>/pdf')
@login_required
def acta_pdf(cierre_id, acta_id):
    """Genera y descarga el PDF del acta de entrega."""
    from io import BytesIO
    org_id = get_current_org_id()
    acta = ActaEntrega.query.filter_by(
        id=acta_id,
        cierre_id=cierre_id,
        organizacion_id=org_id,
    ).first_or_404()

    try:
        from services.acta_pdf_service import generar_pdf_acta
        pdf_bytes = generar_pdf_acta(acta)
    except Exception as e:
        current_app.logger.error(f'Error generando PDF acta {acta_id}: {e}')
        flash('Error al generar el PDF. Intentá nuevamente.', 'danger')
        return redirect(url_for('cierre_obra.ver_acta', cierre_id=cierre_id, acta_id=acta_id))

    obra_nombre = (acta.obra.nombre or 'obra').replace(' ', '_').lower()
    filename = f'acta_entrega_{obra_nombre}_{acta.id:05d}.pdf'

    return send_file(
        BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )
