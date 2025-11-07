from datetime import datetime
import re
from typing import Tuple

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from extensions import db
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

    if not all([nombre, apellido, email, direccion, cuit_input]):
        return False, 'Por favor, completa todos los campos obligatorios.'

    if not _EMAIL_REGEX.match(email):
        return False, 'El email ingresado no es válido.'

    cuit_normalizado = normalizar_cuit(cuit_input)
    if not validar_cuit(cuit_normalizado):
        return False, 'El CUIL/CUIT ingresado no es válido.'

    email_existente = (
        Usuario.query
        .filter(func.lower(Usuario.email) == email.lower(), Usuario.id != usuario.id)
        .first()
    )
    if email_existente:
        return False, 'Ya existe un usuario registrado con ese email.'

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

    perfil.cuit = cuit_normalizado
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
    if request.method == 'POST':
        exito, mensaje = update_billing_from_form(current_user, request.form)
        if exito:
            flash(mensaje, 'success')
            return redirect(url_for('account.facturacion'))
        flash(mensaje, 'danger')

    billing_profile = current_user.billing_profile
    onboarding_status = current_user.onboarding_status
    return render_template(
        'account/facturacion.html',
        usuario=current_user,
        billing_profile=billing_profile,
        onboarding_status=onboarding_status,
        perfil=current_user.perfil,
    )


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
