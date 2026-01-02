from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta, date
from decimal import Decimal
import os
from werkzeug.utils import secure_filename
from app import db
from models import Usuario
from config.billing_config import BILLING

planes_bp = Blueprint('planes', __name__, url_prefix='/planes')

# Precio del plan en USD
PLAN_PRECIO_USD = Decimal('250.00')


def obtener_cotizacion_bna():
    """
    Obtiene la cotización del dólar vendedor del Banco Nación.
    Retorna la tasa y la fecha.
    """
    try:
        from services.exchange.providers.bna import fetch_official_rate
        from services.exchange.base import ensure_rate

        snapshot = ensure_rate(
            provider='bna_html',
            base_currency='ARS',
            quote_currency='USD',
            fetcher=fetch_official_rate,
            fallback_rate=Decimal('1100.0')  # Fallback en caso de error
        )
        return {
            'value': float(snapshot.value),
            'as_of_date': snapshot.as_of_date.isoformat() if snapshot.as_of_date else date.today().isoformat(),
            'provider': snapshot.provider,
            'success': True
        }
    except Exception as e:
        # Retornar un fallback si hay error
        return {
            'value': 1100.0,
            'as_of_date': date.today().isoformat(),
            'provider': 'fallback',
            'success': False,
            'error': str(e)
        }


@planes_bp.route('/api/cotizacion')
def api_cotizacion():
    """API endpoint para obtener cotización USD/ARS del BNA."""
    cotizacion = obtener_cotizacion_bna()

    # Calcular precio en ARS
    precio_ars = PLAN_PRECIO_USD * Decimal(str(cotizacion['value']))

    return jsonify({
        'cotizacion': cotizacion,
        'plan': {
            'nombre': 'OBYRA Pro',
            'precio_usd': float(PLAN_PRECIO_USD),
            'precio_ars': float(precio_ars.quantize(Decimal('0.01'))),
        }
    })


@planes_bp.route('/')
def mostrar_planes():
    """Página de planes de suscripción"""
    # Obtener cotización actual
    cotizacion = obtener_cotizacion_bna()
    precio_ars = PLAN_PRECIO_USD * Decimal(str(cotizacion['value']))

    return render_template('planes/planes.html',
        precio_usd=float(PLAN_PRECIO_USD),
        precio_ars=float(precio_ars.quantize(Decimal('0.01'))),
        cotizacion=cotizacion
    )


@planes_bp.route('/pagar')
@login_required
def instrucciones_pago():
    """Página con instrucciones de pago por transferencia bancaria."""
    # Obtener cotización actual
    cotizacion = obtener_cotizacion_bna()
    precio_ars = PLAN_PRECIO_USD * Decimal(str(cotizacion['value']))

    # Obtener datos bancarios
    bank_info = BILLING.get_bank_info()

    return render_template('planes/instrucciones_pago.html',
        precio_usd=float(PLAN_PRECIO_USD),
        precio_ars=float(precio_ars.quantize(Decimal('0.01'))),
        cotizacion=cotizacion,
        bank_info=bank_info,
        user=current_user
    )


@planes_bp.route('/standard')
def plan_standard():
    """Redirigir a instrucciones de pago"""
    return redirect(url_for('planes.instrucciones_pago'))


@planes_bp.route('/premium')
def plan_premium():
    """Redirigir a instrucciones de pago"""
    return redirect(url_for('planes.instrucciones_pago'))


@planes_bp.route('/pagar-tarjeta')
@login_required
def pago_tarjeta():
    """Página para pago con tarjeta de crédito/débito."""
    cotizacion = obtener_cotizacion_bna()
    precio_ars = PLAN_PRECIO_USD * Decimal(str(cotizacion['value']))

    return render_template('planes/pago_tarjeta.html',
        precio_usd=float(PLAN_PRECIO_USD),
        precio_ars=float(precio_ars.quantize(Decimal('0.01'))),
        cotizacion=cotizacion
    )


@planes_bp.route('/procesar-pago-tarjeta', methods=['POST'])
@login_required
def procesar_pago_tarjeta():
    """Procesar pago con tarjeta (placeholder - a implementar con pasarela de pagos)."""
    # Por ahora solo redirigir con mensaje
    flash('El pago con tarjeta estará disponible próximamente. Por favor, usa la opción de transferencia bancaria.', 'info')
    return redirect(url_for('planes.instrucciones_pago'))


@planes_bp.route('/enviar-comprobante', methods=['POST'])
@login_required
def enviar_comprobante():
    """Recibe el comprobante de transferencia y envía email a obyra.servicios@gmail.com."""
    try:
        # Obtener datos del formulario
        razon_social = request.form.get('razon_social', '').strip()
        cuit_dni = request.form.get('cuit_dni', '').strip()
        email = request.form.get('email', '').strip()
        telefono = request.form.get('telefono', '').strip()
        moneda = request.form.get('moneda', '').strip()
        monto = request.form.get('monto', '').strip()
        comentarios = request.form.get('comentarios', '').strip()

        # Validar campos requeridos
        if not all([razon_social, cuit_dni, email, telefono, moneda, monto]):
            flash('Por favor completa todos los campos requeridos.', 'error')
            return redirect(url_for('planes.instrucciones_pago'))

        # Obtener archivo
        if 'comprobante' not in request.files:
            flash('Por favor adjunta el comprobante de transferencia.', 'error')
            return redirect(url_for('planes.instrucciones_pago'))

        archivo = request.files['comprobante']
        if archivo.filename == '':
            flash('Por favor selecciona un archivo.', 'error')
            return redirect(url_for('planes.instrucciones_pago'))

        # Validar extensión
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
        extension = archivo.filename.rsplit('.', 1)[1].lower() if '.' in archivo.filename else ''
        if extension not in allowed_extensions:
            flash('Formato de archivo no válido. Usa JPG, PNG o PDF.', 'error')
            return redirect(url_for('planes.instrucciones_pago'))

        # Guardar archivo temporalmente
        filename = secure_filename(f"comprobante_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}")
        upload_folder = os.path.join(os.path.dirname(__file__), 'instance', 'uploads', 'comprobantes')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        archivo.save(filepath)

        # Preparar y enviar email
        enviar_email_comprobante(
            razon_social=razon_social,
            cuit_dni=cuit_dni,
            email=email,
            telefono=telefono,
            moneda=moneda,
            monto=monto,
            comentarios=comentarios,
            archivo_path=filepath,
            usuario=current_user
        )

        flash('¡Comprobante enviado correctamente! Verificaremos tu pago y te notificaremos por email cuando tu plan esté activo.', 'success')
        return redirect(url_for('planes.instrucciones_pago'))

    except Exception as e:
        print(f"Error al procesar comprobante: {e}")
        flash('Ocurrió un error al enviar el comprobante. Por favor intenta nuevamente o contáctanos por WhatsApp.', 'error')
        return redirect(url_for('planes.instrucciones_pago'))


def enviar_email_comprobante(razon_social, cuit_dni, email, telefono, moneda, monto, comentarios, archivo_path, usuario):
    """Envía el email con el comprobante a obyra.servicios@gmail.com."""
    try:
        from flask_mail import Message
        from extensions import mail

        # Crear mensaje
        msg = Message(
            subject=f'[PAGO] Nuevo comprobante de transferencia - {razon_social}',
            sender=('OBYRA Pagos', 'noreply@obyra.com'),
            recipients=['obyra.servicios@gmail.com']
        )

        # Cuerpo del email
        msg.html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #1A374D, #2D5A7B); padding: 20px; text-align: center;">
                <h1 style="color: white; margin: 0;">Nuevo Comprobante de Pago</h1>
            </div>

            <div style="padding: 20px; background: #f8f9fa;">
                <h2 style="color: #1A374D; border-bottom: 2px solid #4CAF50; padding-bottom: 10px;">
                    Datos del Cliente
                </h2>

                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold; width: 40%;">Razón Social:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{razon_social}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold;">CUIT/DNI:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{cuit_dni}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold;">Email:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{email}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold;">Teléfono:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{telefono}</td>
                    </tr>
                </table>

                <h2 style="color: #1A374D; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; margin-top: 30px;">
                    Datos de la Transferencia
                </h2>

                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold; width: 40%;">Moneda:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{moneda}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold;">Monto:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-size: 18px; color: #4CAF50; font-weight: bold;">${monto} {moneda}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold;">Comentarios:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{comentarios or 'Sin comentarios'}</td>
                    </tr>
                </table>

                <h2 style="color: #1A374D; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; margin-top: 30px;">
                    Datos del Usuario en OBYRA
                </h2>

                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold; width: 40%;">Usuario ID:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{usuario.id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold;">Nombre:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{usuario.nombre}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold;">Email Usuario:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{usuario.email}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; font-weight: bold;">Organización:</td>
                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{usuario.organization.name if usuario.organization else 'Sin organización'}</td>
                    </tr>
                </table>

                <div style="margin-top: 30px; padding: 15px; background: #fff3cd; border-radius: 8px; border-left: 4px solid #ffc107;">
                    <strong>Acción requerida:</strong> Verificar la acreditación del pago y activar el plan del usuario.
                </div>
            </div>

            <div style="background: #1A374D; padding: 15px; text-align: center; color: white;">
                <p style="margin: 0;">OBYRA - Sistema de Gestión de Obras</p>
                <p style="margin: 5px 0 0 0; font-size: 12px; opacity: 0.7;">Este email fue generado automáticamente</p>
            </div>
        </body>
        </html>
        """

        # Adjuntar comprobante
        with open(archivo_path, 'rb') as f:
            filename = os.path.basename(archivo_path)
            msg.attach(filename, 'application/octet-stream', f.read())

        # Enviar
        mail.send(msg)
        print(f"Email de comprobante enviado para {razon_social}")

    except Exception as e:
        print(f"Error al enviar email de comprobante: {e}")
        # No lanzar excepción para no bloquear el flujo
        # El archivo ya se guardó, se puede procesar manualmente

def verificar_periodo_prueba(usuario):
    """Verifica si el usuario ha cumplido los 30 días de prueba"""
    if not usuario.fecha_registro:
        return False
    
    fecha_limite = usuario.fecha_registro + timedelta(days=30)
    return datetime.utcnow() > fecha_limite

def usuario_requiere_plan():
    """Middleware para verificar si el usuario necesita seleccionar un plan"""
    if not current_user.is_authenticated:
        return False
    
    # Si ya tiene un plan activo, no necesita seleccionar
    if hasattr(current_user, 'plan_activo') and current_user.plan_activo:
        return False
    
    # Verificar si han pasado 30 días desde el registro
    return verificar_periodo_prueba(current_user)