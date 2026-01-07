from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta, date
from decimal import Decimal
import os
from werkzeug.utils import secure_filename
from app import db
from models import Usuario
from models.core import Organizacion
from config.billing_config import BILLING

planes_bp = Blueprint('planes', __name__, url_prefix='/planes')

# Features comunes a todos los planes (sistema completo)
FEATURES_SISTEMA_COMPLETO = [
    'Calculadora IA completa',
    'Presupuestos ilimitados',
    'Gestion de obras',
    'Gestion de clientes',
    'Inventario completo',
    'Gestion de equipos Leiten',
    'Modo offline para operarios',
    'Reportes completos',
    'Soporte por email y WhatsApp',
    'Actualizaciones incluidas'
]

# Configuración de planes de suscripción
# La única diferencia entre planes es la cantidad de usuarios
PLANES_CONFIG = {
    'prueba': {
        'nombre': 'Prueba Gratuita',
        'precio_usd': Decimal('0.00'),
        'precio_mensual_usd': Decimal('0.00'),
        'max_usuarios': 5,
        'duracion_dias': 30,
        'descripcion': '30 dias de prueba gratuita',
        'features': ['Sistema completo por 30 dias', 'Hasta 5 usuarios', 'Soporte por email']
    },
    'estandar': {
        'nombre': 'Plan Estandar',
        'precio_usd': Decimal('150.00'),
        'precio_mensual_usd': Decimal('150.00'),
        'max_usuarios': 5,
        'duracion_dias': 365,
        'descripcion': 'Ideal para equipos pequenos',
        'features': FEATURES_SISTEMA_COMPLETO + ['Hasta 5 usuarios']
    },
    'premium': {
        'nombre': 'Plan Premium',
        'precio_usd': Decimal('250.00'),
        'precio_mensual_usd': Decimal('250.00'),
        'max_usuarios': 10,
        'duracion_dias': 365,
        'descripcion': 'Para empresas en crecimiento',
        'features': FEATURES_SISTEMA_COMPLETO + ['Hasta 10 usuarios'],
        'popular': True
    },
    'full_premium': {
        'nombre': 'Plan Full Premium',
        'precio_usd': Decimal('300.00'),
        'precio_mensual_usd': Decimal('300.00'),
        'max_usuarios': 20,
        'duracion_dias': 365,
        'descripcion': 'Para grandes constructoras',
        'features': FEATURES_SISTEMA_COMPLETO + ['Hasta 20 usuarios']
    }
}

# Precio legacy (mantener compatibilidad)
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

    # Calcular precios en ARS para cada plan
    planes_con_precios = {}
    for key, plan in PLANES_CONFIG.items():
        if key == 'prueba':
            continue  # No mostrar plan de prueba en la selección
        precio_ars = plan['precio_usd'] * Decimal(str(cotizacion['value']))
        planes_con_precios[key] = {
            **plan,
            'precio_ars': float(precio_ars.quantize(Decimal('0.01'))),
            'precio_usd': float(plan['precio_usd'])
        }

    # Obtener plan actual de la organización del usuario
    plan_actual = None
    org_info = None
    if current_user.is_authenticated and current_user.organizacion:
        org = current_user.organizacion
        plan_actual = org.plan_tipo or 'prueba'
        org_info = {
            'nombre': org.nombre,
            'plan_tipo': plan_actual,
            'max_usuarios': org.max_usuarios or 5,
            'usuarios_actuales': org.usuarios_activos_count
        }

    return render_template('planes/planes.html',
        planes=planes_con_precios,
        plan_actual=plan_actual,
        org_info=org_info,
        cotizacion=cotizacion,
        # Legacy - mantener compatibilidad
        precio_usd=float(PLAN_PRECIO_USD),
        precio_ars=float(PLAN_PRECIO_USD * Decimal(str(cotizacion['value'])))
    )


@planes_bp.route('/seleccionar/<plan_tipo>')
@login_required
def seleccionar_plan(plan_tipo):
    """Seleccionar un plan y redirigir a instrucciones de pago"""
    if plan_tipo not in PLANES_CONFIG or plan_tipo == 'prueba':
        flash('Plan no válido.', 'error')
        return redirect(url_for('planes.mostrar_planes'))

    plan = PLANES_CONFIG[plan_tipo]
    cotizacion = obtener_cotizacion_bna()
    precio_ars = plan['precio_usd'] * Decimal(str(cotizacion['value']))

    return render_template('planes/instrucciones_pago.html',
        plan_seleccionado=plan_tipo,
        plan_nombre=plan['nombre'],
        precio_usd=float(plan['precio_usd']),
        precio_ars=float(precio_ars.quantize(Decimal('0.01'))),
        max_usuarios=plan['max_usuarios'],
        cotizacion=cotizacion,
        bank_info=BILLING.get_bank_info(),
        user=current_user
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


@planes_bp.route('/pago-mercadopago/<plan>')
@login_required
def pago_mercadopago(plan):
    """Crear preferencia de pago en MercadoPago y redirigir al checkout."""
    import mercadopago

    # Verificar que MP está configurado
    mp_access_token = os.getenv('MP_ACCESS_TOKEN', '').strip()
    if not mp_access_token:
        flash('El pago con tarjeta no está disponible en este momento. Por favor, usa transferencia bancaria.', 'warning')
        return redirect(url_for('planes.instrucciones_pago'))

    # Obtener info del plan
    if plan not in PLANES_CONFIG:
        plan = 'premium'  # Default

    plan_info = PLANES_CONFIG[plan]
    cotizacion = obtener_cotizacion_bna()
    precio_ars = float(plan_info['precio_usd'] * Decimal(str(cotizacion['value'])))

    # Inicializar SDK
    sdk = mercadopago.SDK(mp_access_token)

    # Obtener URL base para callbacks
    base_url = os.getenv('BASE_URL', '').strip()
    if not base_url or 'localhost' in base_url:
        # En desarrollo local, usar una URL genérica (MP redirige igual)
        base_url = request.url_root.rstrip('/')

    # Crear preferencia
    preference_data = {
        "items": [
            {
                "id": f"plan_{plan}",
                "title": f"OBYRA Pro - {plan_info['nombre']}",
                "description": f"Suscripcion mensual - Hasta {plan_info['max_usuarios']} usuarios",
                "category_id": "services",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": round(precio_ars, 2)
            }
        ],
        "payer": {
            "name": current_user.nombre,
            "surname": current_user.apellido,
            "email": current_user.email
        },
        "external_reference": f"user_{current_user.id}_plan_{plan}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "statement_descriptor": "OBYRA PRO"
    }

    # Solo agregar back_urls y auto_return si tenemos URL pública configurada
    public_url = os.getenv('MP_WEBHOOK_PUBLIC_URL', '').strip()
    if public_url:
        preference_data["back_urls"] = {
            "success": f"{public_url}/planes/pago-exitoso",
            "failure": f"{public_url}/planes/pago-fallido",
            "pending": f"{public_url}/planes/pago-pendiente"
        }
        preference_data["auto_return"] = "approved"
        preference_data["notification_url"] = f"{public_url}/planes/webhook-mercadopago"

    try:
        preference_response = sdk.preference().create(preference_data)
        preference = preference_response.get("response", {})

        if not preference.get("init_point"):
            print(f"MP Error Response: {preference_response}")
            flash('Error al crear el pago. Por favor, intenta nuevamente.', 'error')
            return redirect(url_for('planes.instrucciones_pago'))

        # Redirigir al checkout de MercadoPago
        return redirect(preference["init_point"])

    except Exception as e:
        print(f"Error creando preferencia MP: {e}")
        flash('Error al procesar el pago. Por favor, intenta con transferencia bancaria.', 'error')
        return redirect(url_for('planes.instrucciones_pago'))


@planes_bp.route('/pago-exitoso')
@login_required
def pago_exitoso():
    """Callback cuando el pago fue exitoso."""
    # Obtener datos del pago
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    external_reference = request.args.get('external_reference', '')

    # Parsear el plan del external_reference
    plan_tipo = 'premium'  # Default
    if 'plan_' in external_reference:
        try:
            plan_tipo = external_reference.split('plan_')[1].split('_')[0]
        except:
            pass

    if status == 'approved':
        # Activar el plan del usuario
        try:
            org = current_user.organizacion
            if org:
                plan_info = PLANES_CONFIG.get(plan_tipo, PLANES_CONFIG['premium'])
                org.plan_tipo = plan_tipo
                org.max_usuarios = plan_info['max_usuarios']
                org.fecha_inicio_plan = datetime.utcnow()
                org.fecha_fin_plan = datetime.utcnow() + timedelta(days=30)  # 1 mes
                db.session.commit()

                flash(f'¡Pago exitoso! Tu plan {plan_info["nombre"]} ha sido activado.', 'success')
            else:
                flash('Pago recibido. Contactanos para activar tu plan.', 'info')
        except Exception as e:
            print(f"Error activando plan: {e}")
            flash('Pago recibido. Estamos procesando tu suscripcion.', 'info')
    else:
        flash('El pago fue procesado. Te notificaremos cuando se confirme.', 'info')

    return redirect(url_for('planes.ver_planes'))


@planes_bp.route('/pago-fallido')
@login_required
def pago_fallido():
    """Callback cuando el pago falló."""
    flash('El pago no pudo ser procesado. Por favor, intenta nuevamente o usa otra forma de pago.', 'error')
    return redirect(url_for('planes.instrucciones_pago'))


@planes_bp.route('/pago-pendiente')
@login_required
def pago_pendiente():
    """Callback cuando el pago está pendiente."""
    flash('Tu pago está siendo procesado. Te notificaremos cuando se confirme.', 'info')
    return redirect(url_for('planes.ver_planes'))


@planes_bp.route('/webhook-mercadopago', methods=['POST'])
def webhook_mercadopago():
    """Webhook para recibir notificaciones de MercadoPago."""
    import mercadopago

    mp_access_token = os.getenv('MP_ACCESS_TOKEN', '').strip()
    if not mp_access_token:
        return jsonify({"status": "error"}), 400

    data = request.get_json(silent=True) or {}
    topic = data.get('type') or request.args.get('topic')
    resource_id = data.get('data', {}).get('id') or request.args.get('id')

    if topic == 'payment' and resource_id:
        try:
            sdk = mercadopago.SDK(mp_access_token)
            payment_info = sdk.payment().get(resource_id)
            payment = payment_info.get("response", {})

            if payment.get("status") == "approved":
                external_reference = payment.get("external_reference", "")
                # Parsear user_id y plan
                if "user_" in external_reference and "_plan_" in external_reference:
                    parts = external_reference.split("_")
                    user_id = int(parts[1])
                    plan_tipo = parts[3]

                    # Activar plan
                    user = Usuario.query.get(user_id)
                    if user and user.organizacion:
                        plan_info = PLANES_CONFIG.get(plan_tipo, PLANES_CONFIG['premium'])
                        user.organizacion.plan_tipo = plan_tipo
                        user.organizacion.max_usuarios = plan_info['max_usuarios']
                        user.organizacion.fecha_inicio_plan = datetime.utcnow()
                        user.organizacion.fecha_fin_plan = datetime.utcnow() + timedelta(days=30)
                        db.session.commit()
                        print(f"Plan {plan_tipo} activado para usuario {user_id}")

        except Exception as e:
            print(f"Error procesando webhook MP: {e}")

    return jsonify({"status": "ok"}), 200


@planes_bp.route('/procesar-pago-tarjeta', methods=['POST'])
@login_required
def procesar_pago_tarjeta():
    """Procesar pago con tarjeta (redirige a MercadoPago)."""
    return redirect(url_for('planes.pago_mercadopago', plan='premium'))


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

    # Super Admin nunca requiere plan
    if hasattr(current_user, 'is_super_admin') and current_user.is_super_admin:
        return False

    # Si ya tiene un plan activo, no necesita seleccionar
    if hasattr(current_user, 'plan_activo') and current_user.plan_activo:
        return False

    # Verificar si han pasado 30 días desde el registro
    return verificar_periodo_prueba(current_user)