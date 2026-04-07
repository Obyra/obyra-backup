"""
PDF generation + email routes: generar_pdf, enviar_email
"""
import os
import io
from datetime import datetime
from decimal import Decimal
from collections import OrderedDict

from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app, send_file)
from flask_login import login_required, current_user
from flask_mail import Message
from weasyprint import HTML

from extensions import db
from models import Presupuesto, Organizacion
from services.memberships import get_current_org_id

from blueprint_presupuestos import presupuestos_bp, _limpiar_metadata_pdf


@presupuestos_bp.route('/<int:id>/pdf')
@login_required
def generar_pdf(id):
    """Generar PDF del presupuesto con WeasyPrint - 2 páginas (USD y ARS)"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        # Obtener presupuesto con eager loading para evitar queries dentro del template
        from sqlalchemy.orm import joinedload
        presupuesto = Presupuesto.query.options(
            joinedload(Presupuesto.cliente)
        ).filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Obtener organización
        organizacion = Organizacion.query.get(org_id)

        # Obtener items ordenados usando sintaxis SQLAlchemy 2.0
        from models.budgets import ItemPresupuesto
        from extensions import db
        items_ordenados = db.session.query(ItemPresupuesto).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id
        ).order_by(ItemPresupuesto.tipo, ItemPresupuesto.id).all()

        # Obtener cotización del dólar (Banco Nación vendedor)
        cotizacion_dolar = 1050.0  # Valor por defecto
        fecha_cotizacion = presupuesto.fecha.strftime('%d/%m/%Y')

        # Intentar obtener cotización guardada en el presupuesto
        if presupuesto.tasa_usd_venta:
            cotizacion_dolar = float(presupuesto.tasa_usd_venta)
            if presupuesto.exchange_rate_as_of:
                fecha_cotizacion = presupuesto.exchange_rate_as_of.strftime('%d/%m/%Y')
        else:
            # Intentar obtener cotización actual del BNA
            try:
                from services.exchange.providers.bna import fetch_official_rate
                rate_snapshot = fetch_official_rate()
                if rate_snapshot and rate_snapshot.value:
                    cotizacion_dolar = float(rate_snapshot.value)
                    fecha_cotizacion = rate_snapshot.as_of_date.strftime('%d/%m/%Y') if rate_snapshot.as_of_date else datetime.now().strftime('%d/%m/%Y')
            except Exception as e:
                current_app.logger.warning(f"No se pudo obtener cotización BNA: {e}")

        # Determinar moneda principal y alternativa
        moneda_principal = presupuesto.currency or 'ARS'
        moneda_alternativa = 'USD' if moneda_principal == 'ARS' else 'ARS'

        # Calcular factor de conversión
        # Si moneda principal es ARS, convertir a USD (dividir por cotización)
        # Si moneda principal es USD, convertir a ARS (multiplicar por cotización)
        if moneda_principal == 'ARS':
            factor_conversion = 1 / cotizacion_dolar if cotizacion_dolar > 0 else 0
        else:
            factor_conversion = cotizacion_dolar

        # Parsear datos_proyecto para obtener información adicional
        import json
        datos_proyecto = {}
        nombre_proyecto = None
        tipo_construccion = None
        superficie_m2 = None

        if presupuesto.datos_proyecto:
            try:
                datos_proyecto = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                nombre_proyecto = datos_proyecto.get('nombre_obra') or datos_proyecto.get('nombre')
                tipo_construccion = datos_proyecto.get('tipo_construccion')
                superficie_m2 = datos_proyecto.get('superficie_m2')
            except (json.JSONDecodeError, TypeError) as e:
                current_app.logger.warning(f"Error parseando datos_proyecto en PDF: {e}")

        # Agrupar items por etapa para vista simplificada del cliente
        from decimal import Decimal

        etapas_orden_pdf = [
            'Trabajos preliminares', 'Excavación', 'Fundaciones', 'Estructura',
            'Mampostería', 'Techos y cubiertas', 'Instalación eléctrica',
            'Instalación sanitaria', 'Instalación de gas', 'Pisos y revestimientos',
            'Carpintería', 'Pintura', 'Equipamiento', 'Terminaciones', 'Otros'
        ]

        etapas_totales = OrderedDict()
        for item in items_ordenados:
            nombre_etapa = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Otros')
            if nombre_etapa not in etapas_totales:
                etapas_totales[nombre_etapa] = Decimal('0')
            etapas_totales[nombre_etapa] += item.total or Decimal('0')

        # Ordenar: primero las etapas conocidas, luego el resto
        etapas_ordenadas = OrderedDict()
        for etapa in etapas_orden_pdf:
            if etapa in etapas_totales:
                etapas_ordenadas[etapa] = etapas_totales[etapa]
        for etapa, total in etapas_totales.items():
            if etapa not in etapas_ordenadas:
                etapas_ordenadas[etapa] = total

        # Cargar logo como base64 para embeber en el PDF
        logo_base64 = None
        if organizacion.logo_url:
            try:
                import base64
                logo_path = os.path.join(current_app.static_folder, organizacion.logo_url)
                if os.path.exists(logo_path):
                    with open(logo_path, 'rb') as f:
                        logo_base64 = base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                current_app.logger.warning(f"No se pudo cargar logo para PDF: {e}")

        try:
            # Renderizar HTML
            html_string = render_template(
                'presupuestos/pdf_template.html',
                presupuesto=presupuesto,
                organizacion=organizacion,
                usuario=current_user,
                now=datetime.now(),
                items=items_ordenados,
                etapas_totales=etapas_ordenadas,
                moneda_principal=moneda_principal,
                moneda_alternativa=moneda_alternativa,
                cotizacion_dolar=cotizacion_dolar,
                fecha_cotizacion=fecha_cotizacion,
                factor_conversion=factor_conversion,
                nombre_proyecto=nombre_proyecto,
                tipo_construccion=tipo_construccion,
                superficie_m2=superficie_m2,
                logo_base64=logo_base64
            )
        except Exception as render_error:
            current_app.logger.error(f"Error al renderizar template PDF: {render_error}", exc_info=True)
            raise Exception(f"Error al renderizar template: {str(render_error)}")

        try:
            # Generar PDF con WeasyPrint
            pdf_raw = io.BytesIO()
            HTML(string=html_string).write_pdf(
                pdf_raw,
                presentational_hints=True
            )
            pdf_raw.seek(0)

            # Post-procesar: limpiar metadatos para evitar falsos positivos de antivirus
            pdf_buffer = _limpiar_metadata_pdf(pdf_raw, presupuesto, organizacion)
        except Exception as pdf_error:
            current_app.logger.error(f"Error al generar PDF con WeasyPrint: {pdf_error}", exc_info=True)
            raise Exception(f"Error al generar PDF: {str(pdf_error)}")

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'presupuesto_{presupuesto.numero}.pdf'
        )

    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback_str = traceback.format_exc()
        current_app.logger.error(f"Error en presupuestos.generar_pdf: {error_msg}\n{traceback_str}")
        flash(f'Error al generar el PDF: {error_msg}', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/<int:id>/enviar-email', methods=['GET', 'POST'])
@login_required
def enviar_email(id):
    """Enviar presupuesto por email"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            # Si es JSON, retornar error JSON
            if request.is_json:
                return jsonify({'error': 'No tienes una organización activa'}), 403
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        organizacion = Organizacion.query.get(org_id)

        if request.method == 'GET':
            # Mostrar formulario de envío
            email_destino = presupuesto.cliente.email if presupuesto.cliente else ''
            user_name = f"{current_user.nombre} {current_user.apellido}" if current_user.is_authenticated else "nuestro equipo"
            mensaje_default = f"""Estimado/a,

Adjunto encontrará el presupuesto Nº {presupuesto.numero} solicitado.

Este presupuesto tiene una vigencia hasta el {presupuesto.fecha_vigencia.strftime('%d/%m/%Y') if presupuesto.fecha_vigencia else 'consultar'}.

Para cualquier consulta, puede responder directamente este email y su mensaje llegará a {user_name}.

Saludos cordiales,
{organizacion.nombre}"""

            return render_template(
                'presupuestos/enviar_email.html',
                presupuesto=presupuesto,
                email_destino=email_destino,
                mensaje_default=mensaje_default
            )

        # POST: Enviar email (puede ser form o JSON)
        if request.is_json:
            data = request.get_json()
            email_destino = data.get('email', '').strip()
            asunto = data.get('asunto', f'Presupuesto {presupuesto.numero}').strip()
            mensaje = data.get('mensaje', '').strip()
        else:
            email_destino = request.form.get('email', '').strip()
            asunto = request.form.get('asunto', f'Presupuesto {presupuesto.numero}').strip()
            mensaje = request.form.get('mensaje', '').strip()

        if not email_destino:
            if request.is_json:
                return jsonify({'error': 'Debe ingresar un email de destino'}), 400
            flash('Debe ingresar un email de destino', 'danger')
            return redirect(url_for('presupuestos.enviar_email', id=id))

        # Verificar que el presupuesto tenga ítems
        if presupuesto.items.count() == 0:
            if request.is_json:
                return jsonify({'error': 'No se puede enviar un presupuesto sin ítems'}), 400
            flash('No se puede enviar un presupuesto sin ítems. Por favor agregue ítems al presupuesto primero.', 'warning')
            return redirect(url_for('presupuestos.detalle', id=id))

        # Obtener items ordenados (igual que en generar_pdf)
        from models.budgets import ItemPresupuesto
        items_ordenados = db.session.query(ItemPresupuesto).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id
        ).order_by(ItemPresupuesto.tipo, ItemPresupuesto.id).all()

        # Obtener cotización del dólar para el PDF dual moneda
        cotizacion_dolar = 1050.0  # Valor por defecto
        fecha_cotizacion = presupuesto.fecha.strftime('%d/%m/%Y')

        if presupuesto.tasa_usd_venta:
            cotizacion_dolar = float(presupuesto.tasa_usd_venta)
            if presupuesto.exchange_rate_as_of:
                fecha_cotizacion = presupuesto.exchange_rate_as_of.strftime('%d/%m/%Y')
        else:
            try:
                from services.exchange.providers.bna import fetch_official_rate
                rate_snapshot = fetch_official_rate()
                if rate_snapshot and rate_snapshot.value:
                    cotizacion_dolar = float(rate_snapshot.value)
                    fecha_cotizacion = rate_snapshot.as_of_date.strftime('%d/%m/%Y') if rate_snapshot.as_of_date else datetime.now().strftime('%d/%m/%Y')
            except Exception as e:
                current_app.logger.warning(f"No se pudo obtener cotización BNA: {e}")

        moneda_principal = presupuesto.currency or 'ARS'
        moneda_alternativa = 'USD' if moneda_principal == 'ARS' else 'ARS'

        if moneda_principal == 'ARS':
            factor_conversion = 1 / cotizacion_dolar if cotizacion_dolar > 0 else 0
        else:
            factor_conversion = cotizacion_dolar

        # Agrupar items por etapa para vista simplificada del cliente
        from decimal import Decimal as Dec

        etapas_orden_email = [
            'Trabajos preliminares', 'Excavación', 'Fundaciones', 'Estructura',
            'Mampostería', 'Techos y cubiertas', 'Instalación eléctrica',
            'Instalación sanitaria', 'Instalación de gas', 'Pisos y revestimientos',
            'Carpintería', 'Pintura', 'Equipamiento', 'Terminaciones', 'Otros'
        ]
        etapas_totales_email = OrderedDict()
        for item in items_ordenados:
            nombre_etapa = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Otros')
            if nombre_etapa not in etapas_totales_email:
                etapas_totales_email[nombre_etapa] = Dec('0')
            etapas_totales_email[nombre_etapa] += item.total or Dec('0')

        etapas_ordenadas_email = OrderedDict()
        for etapa in etapas_orden_email:
            if etapa in etapas_totales_email:
                etapas_ordenadas_email[etapa] = etapas_totales_email[etapa]
        for etapa, total in etapas_totales_email.items():
            if etapa not in etapas_ordenadas_email:
                etapas_ordenadas_email[etapa] = total

        # Parsear datos_proyecto para la template
        import json as json_mod
        nombre_proyecto = None
        tipo_construccion = None
        superficie_m2 = None
        if presupuesto.datos_proyecto:
            try:
                datos_proy = json_mod.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                nombre_proyecto = datos_proy.get('nombre_obra') or datos_proy.get('nombre')
                tipo_construccion = datos_proy.get('tipo_construccion')
                superficie_m2 = datos_proy.get('superficie_m2')
            except (json_mod.JSONDecodeError, TypeError):
                pass

        # Cargar logo como base64 para embeber en el PDF
        logo_base64 = None
        if organizacion.logo_url:
            try:
                import base64
                logo_path = os.path.join(current_app.static_folder, organizacion.logo_url)
                if os.path.exists(logo_path):
                    with open(logo_path, 'rb') as f:
                        logo_base64 = base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                current_app.logger.warning(f"No se pudo cargar logo para PDF email: {e}")

        # Generar PDF
        html_string = render_template(
            'presupuestos/pdf_template.html',
            presupuesto=presupuesto,
            organizacion=organizacion,
            usuario=current_user,
            now=datetime.now(),
            items=items_ordenados,
            etapas_totales=etapas_ordenadas_email,
            moneda_principal=moneda_principal,
            moneda_alternativa=moneda_alternativa,
            cotizacion_dolar=cotizacion_dolar,
            fecha_cotizacion=fecha_cotizacion,
            factor_conversion=factor_conversion,
            nombre_proyecto=nombre_proyecto,
            tipo_construccion=tipo_construccion,
            superficie_m2=superficie_m2,
            logo_base64=logo_base64
        )

        # Generar PDF y limpiar metadatos para evitar falsos positivos de antivirus
        pdf_raw = io.BytesIO()
        HTML(string=html_string).write_pdf(
            pdf_raw,
            presentational_hints=True
        )
        pdf_raw.seek(0)
        pdf_clean = _limpiar_metadata_pdf(pdf_raw, presupuesto, organizacion)
        pdf_bytes = pdf_clean.read()

        # Preparar datos del remitente
        user_email = current_user.email if current_user.is_authenticated else None
        user_name = f"{current_user.nombre} {current_user.apellido}" if current_user.is_authenticated else "OBYRA"

        # Intentar primero con Resend (más confiable)
        email_enviado = False
        resend_api_key = current_app.config.get('RESEND_API_KEY')

        if resend_api_key:
            try:
                from services.email_service import send_email as resend_send_email

                current_app.logger.info(f"Intentando enviar email via Resend a {email_destino}")

                # Convertir mensaje de texto a HTML simple
                mensaje_html = f"<pre style='font-family: Arial, sans-serif; white-space: pre-wrap;'>{mensaje}</pre>"

                # Preparar adjunto
                adjuntos = [{
                    'filename': f'presupuesto_{presupuesto.numero}.pdf',
                    'content': pdf_bytes,
                    'content_type': 'application/pdf'
                }]

                # Enviar con Resend
                email_enviado = resend_send_email(
                    to_email=email_destino,
                    subject=asunto,
                    html_content=mensaje_html,
                    attachments=adjuntos,
                    reply_to=user_email,
                    text_content=mensaje
                )

                if email_enviado:
                    current_app.logger.info("Email enviado exitosamente via Resend!")
                else:
                    current_app.logger.warning("Resend falló, intentando con Flask-Mail...")

            except Exception as resend_error:
                current_app.logger.warning(f"Error con Resend: {resend_error}, intentando Flask-Mail...")

        # Si Resend no funcionó, intentar con Flask-Mail
        if not email_enviado:
            try:
                from extensions import mail

                sender_email = f"{user_name} - OBYRA <{current_app.config.get('MAIL_DEFAULT_SENDER')}>"

                current_app.logger.info(f"Intentando enviar email via Flask-Mail desde {sender_email} hacia {email_destino}")

                msg = Message(
                    asunto,
                    recipients=[email_destino],
                    body=mensaje,
                    sender=sender_email
                )

                if user_email:
                    msg.reply_to = f"{user_name} <{user_email}>"
                msg.attach(
                    f'presupuesto_{presupuesto.numero}.pdf',
                    'application/pdf',
                    pdf_bytes
                )

                mail.send(msg)
                email_enviado = True
                current_app.logger.info("Email enviado exitosamente via Flask-Mail!")

            except ImportError:
                current_app.logger.warning("Flask-Mail no está configurado")
            except Exception as mail_error:
                error_msg = str(mail_error)
                current_app.logger.error(f"Error al enviar email via Flask-Mail: {mail_error}", exc_info=True)

                # Mostrar error específico
                if 'SMTPAuthenticationError' in type(mail_error).__name__ or 'Authentication' in error_msg or '535' in error_msg:
                    flash('Error de autenticación del servidor de correo. Por favor contacte al administrador.', 'danger')
                elif 'SMTP' in type(mail_error).__name__ or 'smtp' in error_msg.lower():
                    flash(f'Error del servidor de correo: {error_msg[:100]}', 'danger')
                else:
                    flash(f'Error al enviar el email: {error_msg[:100]}', 'danger')
                return redirect(url_for('presupuestos.enviar_email', id=id))

        # Si ninguno funcionó
        if not email_enviado:
            if request.is_json:
                return jsonify({'error': 'No se pudo enviar el email. Verifique la configuración del servidor de correo.'}), 500
            flash('No se pudo enviar el email. Verifique la configuración del servidor de correo.', 'danger')
            return redirect(url_for('presupuestos.enviar_email', id=id))

        # Actualizar estado si está en borrador
        if presupuesto.estado == 'borrador':
            presupuesto.estado = 'enviado'
            db.session.commit()

        if request.is_json:
            return jsonify({
                'success': True,
                'message': f'Presupuesto enviado exitosamente a {email_destino}'
            }), 200

        flash(f'Presupuesto enviado exitosamente a {email_destino}', 'success')
        return redirect(url_for('presupuestos.detalle', id=id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.enviar_email: {e}", exc_info=True)
        if request.is_json:
            return jsonify({'error': 'Error al procesar el envío del email'}), 500
        flash('Error al procesar el envío del email', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
