from datetime import datetime
import os
import re
import uuid
from typing import Tuple

from flask import Blueprint, flash, redirect, render_template, request, url_for, jsonify, current_app
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.utils import secure_filename

from extensions import db, csrf
from models import PerfilUsuario, Usuario
from auth import normalizar_cuit, validar_cuit

account_bp = Blueprint('account', __name__)

_EMAIL_REGEX = re.compile(r'^[^@]+@[^@]+\.[^@]+$')


def update_profile_from_form(usuario: Usuario, form) -> Tuple[bool, str]:
    nombre = (form.get('nombre') or '').strip()
    apellido = (form.get('apellido') or '').strip()
    email = (form.get('email') or '').strip().lower()
    telefono = (form.get('telefono') or '').strip()
    direccion = (form.get('direccion') or '').strip()
    cuit_input = (form.get('cuit') or '').strip()

    # Solo nombre, apellido y email son obligatorios
    if not all([nombre, apellido, email]):
        return False, 'Por favor, completa nombre, apellido y email.'

    if not _EMAIL_REGEX.match(email):
        return False, 'El email ingresado no es valido.'

    email_existente = (
        Usuario.query
        .filter(func.lower(Usuario.email) == email.lower(), Usuario.id != usuario.id)
        .first()
    )
    if email_existente:
        return False, 'Ya existe un usuario registrado con ese email.'

    # Validar CUIT solo si se proporciona
    cuit_normalizado = None
    if cuit_input:
        cuit_normalizado = normalizar_cuit(cuit_input)
        if not validar_cuit(cuit_normalizado):
            return False, 'El CUIL/CUIT ingresado no es valido.'

        cuit_existente = (
            PerfilUsuario.query
            .filter(PerfilUsuario.cuit == cuit_normalizado, PerfilUsuario.usuario_id != usuario.id)
            .first()
        )
        if cuit_existente:
            return False, 'El CUIL/CUIT ingresado pertenece a otro usuario.'

    usuario.nombre = nombre
    usuario.apellido = apellido
    usuario.email = email
    usuario.telefono = telefono

    perfil = usuario.perfil
    if not perfil:
        perfil = PerfilUsuario(usuario=usuario)
        db.session.add(perfil)

    if cuit_normalizado:
        perfil.cuit = cuit_normalizado
    if direccion:
        perfil.direccion = direccion

    status = usuario.ensure_onboarding_status()
    status.mark_profile_completed()

    db.session.commit()
    return True, 'Perfil actualizado correctamente.'


def _detectar_marca_tarjeta(numero: str) -> str:
    if numero.startswith('4'):
        return 'Visa'
    if numero[:2] in {'51', '52', '53', '54', '55'}:
        return 'Mastercard'
    if numero.startswith('34') or numero.startswith('37'):
        return 'American Express'
    if numero.startswith('36'):
        return 'Diners Club'
    if numero.startswith('6'):
        return 'Discover'
    return 'Tarjeta'


def _validar_expiracion(mes: str, año: str) -> Tuple[bool, str, str]:
    mes = (mes or '').strip()
    año = (año or '').strip()

    if not mes or not año:
        return False, mes, año

    if not mes.isdigit() or not año.isdigit():
        return False, mes, año

    mes_int = int(mes)
    if mes_int < 1 or mes_int > 12:
        return False, mes, año

    if len(año) == 2:
        año = f'20{año}'
    elif len(año) != 4:
        return False, mes, año

    año_int = int(año)
    ahora = datetime.utcnow()
    if año_int < ahora.year or (año_int == ahora.year and mes_int < ahora.month):
        return False, mes, año

    return True, f'{mes_int:02d}', año


def update_billing_from_form(usuario: Usuario, form, *, require_card: bool = False) -> Tuple[bool, str]:
    profile = usuario.ensure_billing_profile()

    razon_social = (form.get('razon_social') or '').strip()
    tax_id_input = (form.get('tax_id') or '').strip()
    billing_email = (form.get('billing_email') or usuario.email).strip().lower()
    billing_phone = (form.get('billing_phone') or '').strip()
    address_line1 = (form.get('address_line1') or '').strip()
    address_line2 = (form.get('address_line2') or '').strip()
    city = (form.get('city') or '').strip()
    province = (form.get('province') or '').strip()
    postal_code = (form.get('postal_code') or '').strip()
    country = (form.get('country') or profile.country or 'Argentina').strip()

    cardholder_name = (form.get('cardholder_name') or '').strip()
    card_number = ''.join(ch for ch in (form.get('card_number') or '') if ch.isdigit())
    exp_month = (form.get('exp_month') or '').strip()
    exp_year = (form.get('exp_year') or '').strip()

    if require_card and not all([razon_social, tax_id_input, address_line1, city, province, postal_code, cardholder_name, card_number, exp_month, exp_year]):
        return False, 'Por favor, completa todos los campos de facturación y tarjeta.'

    if billing_email and not _EMAIL_REGEX.match(billing_email):
        return False, 'El email de facturación no es válido.'

    tax_id_normalizado = normalizar_cuit(tax_id_input) if tax_id_input else ''
    if tax_id_normalizado and not validar_cuit(tax_id_normalizado):
        return False, 'El CUIT de facturación ingresado no es válido.'

    if card_number:
        if len(card_number) < 12:
            return False, 'El número de tarjeta debe tener al menos 12 dígitos.'
        exp_valida, mes_normalizado, año_normalizado = _validar_expiracion(exp_month, exp_year)
        if not exp_valida:
            return False, 'La fecha de vencimiento de la tarjeta no es válida.'

        # SEGURIDAD CRÍTICA: Solo guardar los últimos 4 dígitos
        # Sobrescribir inmediatamente la variable para evitar que quede en memoria
        last_four = card_number[-4:]
        card_brand = _detectar_marca_tarjeta(card_number)

        # Eliminar el número completo de la memoria
        card_number = None

        # Guardar solo los datos seguros
        profile.card_last4 = last_four
        profile.card_brand = card_brand
        profile.card_exp_month = mes_normalizado
        profile.card_exp_year = año_normalizado
        profile.cardholder_name = cardholder_name or profile.cardholder_name
    elif require_card and not profile.card_last4:
        return False, 'Debes ingresar los datos de una tarjeta válida.'

    profile.razon_social = razon_social or profile.razon_social
    profile.tax_id = tax_id_normalizado or profile.tax_id
    profile.billing_email = billing_email or profile.billing_email
    profile.billing_phone = billing_phone or profile.billing_phone
    profile.address_line1 = address_line1 or profile.address_line1
    profile.address_line2 = address_line2 or profile.address_line2
    profile.city = city or profile.city
    profile.province = province or profile.province
    profile.postal_code = postal_code or profile.postal_code
    profile.country = country or profile.country or 'Argentina'

    status = usuario.ensure_onboarding_status()
    if profile.card_last4 and profile.razon_social and profile.tax_id:
        status.mark_billing_completed()

    db.session.commit()
    return True, 'Datos de facturación guardados correctamente.'


@account_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        exito, mensaje = update_profile_from_form(current_user, request.form)
        if exito:
            flash(mensaje, 'success')
            return redirect(url_for('account.perfil'))
        flash(mensaje, 'danger')

    perfil_usuario = current_user.perfil
    onboarding_status = current_user.onboarding_status
    return render_template(
        'account/perfil.html',
        usuario=current_user,
        perfil=perfil_usuario,
        onboarding_status=onboarding_status,
    )


@account_bp.route('/facturacion', methods=['GET', 'POST'])
@login_required
def facturacion():
    # Solo los administradores pueden acceder a facturación
    if current_user.role not in ('admin',):
        flash('Los datos de facturación son gestionados por el administrador de tu organización.', 'info')
        return redirect(url_for('account.perfil'))

    import os
    from flask import current_app
    from werkzeug.utils import secure_filename

    if request.method == 'POST':
        form_type = request.form.get('form_type', 'facturacion')

        if form_type == 'facturacion':
            # Guardar datos de facturacion
            exito, mensaje = update_billing_from_form(current_user, request.form)
            if exito:
                flash(mensaje, 'success')
            else:
                flash(mensaje, 'danger')

        elif form_type == 'comprobante':
            # Procesar comprobante de pago
            try:
                monto = request.form.get('monto_transferido')
                fecha = request.form.get('fecha_transferencia')
                concepto = request.form.get('concepto')
                notas = request.form.get('notas_pago', '')
                archivo = request.files.get('comprobante')

                if not all([monto, fecha, archivo]):
                    flash('Por favor completa todos los campos obligatorios.', 'danger')
                else:
                    # Validar archivo
                    if archivo.filename:
                        filename = secure_filename(archivo.filename)
                        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

                        if ext not in ['pdf', 'jpg', 'jpeg', 'png']:
                            flash('Formato de archivo no permitido.', 'danger')
                        else:
                            # Guardar archivo
                            upload_folder = os.path.join(current_app.root_path, 'instance', 'comprobantes')
                            os.makedirs(upload_folder, exist_ok=True)

                            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                            nuevo_nombre = f"{current_user.id}_{timestamp}_{filename}"
                            filepath = os.path.join(upload_folder, nuevo_nombre)
                            archivo.save(filepath)

                            # Enviar email con el comprobante
                            _enviar_email_comprobante(
                                usuario=current_user,
                                monto=monto,
                                fecha=fecha,
                                concepto=concepto,
                                notas=notas,
                                archivo_path=filepath
                            )

                            flash('Comprobante enviado correctamente. Lo revisaremos a la brevedad.', 'success')

            except Exception as e:
                current_app.logger.error(f"Error procesando comprobante: {e}")
                flash(f'Error al procesar el comprobante: {str(e)}', 'danger')

        return redirect(url_for('account.facturacion'))

    billing_profile = current_user.billing_profile
    onboarding_status = current_user.onboarding_status
    return render_template(
        'account/facturacion.html',
        usuario=current_user,
        billing_profile=billing_profile,
        onboarding_status=onboarding_status,
        perfil=current_user.perfil,
        pagos_recientes=[]  # TODO: Implementar historial de pagos
    )


def _enviar_email_comprobante(usuario, monto, fecha, concepto, notas, archivo_path):
    """Envia email con comprobante de pago a obyra.servicios@gmail.com"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    from flask import current_app
    import os

    try:
        # Configuracion del email
        smtp_server = current_app.config.get('MAIL_SERVER', 'smtp.gmail.com')
        smtp_port = current_app.config.get('MAIL_PORT', 587)
        smtp_user = current_app.config.get('MAIL_USERNAME')
        smtp_pass = current_app.config.get('MAIL_PASSWORD')

        if not smtp_user or not smtp_pass:
            current_app.logger.warning("Email no configurado, comprobante guardado pero no enviado")
            return

        # Crear mensaje
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = 'obyra.servicios@gmail.com'
        msg['Subject'] = f'Nuevo Comprobante de Pago - {usuario.nombre_completo}'

        # Conceptos legibles
        conceptos = {
            'obyra_pro': 'OBYRA Pro - $250 USD/mes',
            'otro': 'Otro'
        }

        body = f"""
Nuevo comprobante de pago recibido:

Usuario: {usuario.nombre_completo}
Email: {usuario.email}
Organizacion ID: {usuario.organizacion_id}

Datos del pago:
- Monto: ${monto}
- Fecha: {fecha}
- Concepto: {conceptos.get(concepto, concepto)}
- Notas: {notas or 'Sin notas'}

Por favor, verificar el comprobante adjunto y procesar el pago.
        """

        msg.attach(MIMEText(body, 'plain'))

        # Adjuntar archivo
        if archivo_path and os.path.exists(archivo_path):
            with open(archivo_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename={os.path.basename(archivo_path)}'
                )
                msg.attach(part)

        # Enviar
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        current_app.logger.info(f"Email de comprobante enviado para usuario {usuario.id}")

    except Exception as e:
        current_app.logger.error(f"Error enviando email de comprobante: {e}")
        raise


@account_bp.route('/organizacion', methods=['GET', 'POST'])
@login_required
def organizacion():
    """Configuración de la organización"""
    from helpers import get_current_org_id
    from models import Organizacion

    org_id = get_current_org_id()
    organizacion = Organizacion.query.get_or_404(org_id)

    if request.method == 'POST':
        organizacion.nombre = request.form.get('nombre', '').strip()
        organizacion.descripcion = request.form.get('descripcion', '').strip()
        organizacion.cuit = request.form.get('cuit', '').strip()
        organizacion.direccion = request.form.get('direccion', '').strip()
        organizacion.telefono = request.form.get('telefono', '').strip()
        organizacion.email = request.form.get('email', '').strip()

        # Manejar upload de logo
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            allowed_ext = {'png', 'jpg', 'jpeg', 'webp'}
            ext = logo_file.filename.rsplit('.', 1)[-1].lower() if '.' in logo_file.filename else ''
            if ext in allowed_ext:
                logo_dir = os.path.join(current_app.static_folder, 'uploads', 'logos', str(org_id))
                os.makedirs(logo_dir, exist_ok=True)
                # Eliminar logo anterior si existe
                if organizacion.logo_url:
                    old_path = os.path.join(current_app.static_folder, organizacion.logo_url)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                safe_name = f"logo_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(logo_dir, safe_name)
                logo_file.save(filepath)
                organizacion.logo_url = f"uploads/logos/{org_id}/{safe_name}"
            else:
                flash('El logo debe ser PNG, JPG o WEBP', 'warning')

        # Eliminar logo si se pidió
        if request.form.get('eliminar_logo') == '1' and organizacion.logo_url:
            old_path = os.path.join(current_app.static_folder, organizacion.logo_url)
            if os.path.exists(old_path):
                os.remove(old_path)
            organizacion.logo_url = None

        try:
            db.session.commit()
            flash('Información de la organización actualizada correctamente', 'success')
            return redirect(url_for('account.organizacion'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar la organización: {str(e)}', 'danger')

    return render_template(
        'account/organizacion.html',
        organizacion=organizacion,
        usuario=current_user
    )


@account_bp.route('/cambiar-password', methods=['POST'])
@csrf.exempt
@login_required
def cambiar_password():
    """Permite al usuario cambiar su contraseña"""

    password_actual = request.form.get('password_actual', '')
    password_nueva = request.form.get('password_nueva', '')
    password_confirmar = request.form.get('password_confirmar', '')

    if not all([password_actual, password_nueva, password_confirmar]):
        return jsonify({'success': False, 'message': 'Todos los campos son obligatorios'}), 400

    if password_nueva != password_confirmar:
        return jsonify({'success': False, 'message': 'Las contraseñas no coinciden'}), 400

    if len(password_nueva) < 6:
        return jsonify({'success': False, 'message': 'La contraseña debe tener al menos 6 caracteres'}), 400

    if not current_user.check_password(password_actual):
        return jsonify({'success': False, 'message': 'La contraseña actual es incorrecta'}), 400

    try:
        current_user.set_password(password_nueva)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Contraseña actualizada correctamente'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Error al actualizar la contraseña'}), 500
