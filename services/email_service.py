"""
OBYRA Market - Email Service
Handles email sending using Resend API for notifications and purchase orders
"""

import logging
import os
import requests


def send_email(to_email, subject, html_content, attachments=None, reply_to=None, text_content=None):
    """
    Envía email usando Resend API

    Args:
        to_email (str): Email destinatario
        subject (str): Asunto del email
        html_content (str): Contenido HTML del email
        attachments (list): Lista de archivos adjuntos [{'filename': 'x.pdf', 'content': bytes, 'content_type': 'application/pdf'}]
        reply_to (str): Email para respuestas
        text_content (str): Contenido de texto plano (alternativo al HTML)
    """
    try:
        from flask import current_app
        import base64

        resend_api_key = current_app.config.get('RESEND_API_KEY')
        from_email = current_app.config.get('FROM_EMAIL', 'OBYRA <onboarding@resend.dev>')

        current_app.logger.info(f"[EMAIL] Intentando enviar email a {to_email}")
        current_app.logger.info(f"[EMAIL] Resend API Key configurada: {'SI' if resend_api_key else 'NO'}")
        current_app.logger.info(f"[EMAIL] From: {from_email}")

        if not resend_api_key:
            current_app.logger.warning("[EMAIL] RESEND_API_KEY no configurada")
            return False

        # Construir payload del email
        email_payload = {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
        }

        # Agregar contenido HTML o texto
        if html_content:
            email_payload["html"] = html_content
        if text_content:
            email_payload["text"] = text_content

        # Agregar Reply-To si está configurado
        if reply_to:
            email_payload["reply_to"] = reply_to

        # Agregar adjuntos si existen
        if attachments:
            email_attachments = []
            for att in attachments:
                # Resend espera el contenido en base64
                if isinstance(att.get('content'), bytes):
                    content_b64 = base64.b64encode(att['content']).decode('utf-8')
                else:
                    content_b64 = att.get('content', '')

                email_attachments.append({
                    "filename": att.get('filename', 'adjunto.pdf'),
                    "content": content_b64
                })
            email_payload["attachments"] = email_attachments
            current_app.logger.info(f"[EMAIL] Adjuntos incluidos: {len(email_attachments)}")

        # Enviar via Resend API
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {resend_api_key}",
                "Content-Type": "application/json"
            },
            json=email_payload,
            timeout=30
        )

        if response.status_code == 200:
            current_app.logger.info(f"[EMAIL] ✅ Email enviado exitosamente a {to_email}")
            return True
        else:
            current_app.logger.error(f"[EMAIL] ❌ Error de Resend: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        from flask import current_app as app
        app.logger.error(f"[EMAIL] ❌ Error enviando email a {to_email}: {str(e)}")
        import traceback
        app.logger.error(f"[EMAIL] Traceback: {traceback.format_exc()}")
        return False

def send_po_notification(po):
    """
    Envía notificación de orden de compra al comprador
    """
    try:
        order = po.order
        buyer_email = order.buyer_user.email
        
        subject = f"Orden de Compra Generada - {po.oc_number}"
        
        html_content = f"""
        <h2>Orden de Compra Confirmada</h2>
        <p>Estimado {order.buyer_user.name},</p>
        
        <p>Su pago ha sido procesado exitosamente y se ha generado la siguiente orden de compra:</p>
        
        <ul>
            <li><strong>Número de Orden:</strong> {order.order_number}</li>
            <li><strong>OC Proveedor:</strong> {po.oc_number}</li>
            <li><strong>Proveedor:</strong> {po.seller.name}</li>
            <li><strong>Total:</strong> ${order.total:,.2f} {order.currency}</li>
        </ul>
        
        <p>El proveedor ha sido notificado y procesará su pedido a la brevedad.</p>
        
        <p>Puede hacer seguimiento del estado de su pedido en su panel de órdenes.</p>
        
        <p>Gracias por confiar en OBYRA Market.</p>
        
        <p>Saludos,<br/>
        Equipo OBYRA Market</p>
        """
        
        return send_email(buyer_email, subject, html_content)
        
    except Exception as e:
        logging.error(f"Error sending PO notification: {str(e)}")
        return False

def send_question_notification(question):
    """
    Notifica al seller sobre una nueva pregunta
    """
    try:
        product = question.product
        seller = product.seller
        
        subject = f"Nueva pregunta sobre {product.name}"
        
        html_content = f"""
        <h2>Nueva Pregunta de Cliente</h2>
        <p>Estimado proveedor {seller.name},</p>
        
        <p>Ha recibido una nueva pregunta sobre su producto:</p>
        
        <div style="background-color: #f3f4f6; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <p><strong>Producto:</strong> {product.name}</p>
            <p><strong>Pregunta:</strong></p>
            <p>{question.question}</p>
            <p><strong>Fecha:</strong> {question.created_at.strftime('%d/%m/%Y %H:%M')}</p>
        </div>
        
        <p>Por favor, responda a la brevedad para mantener un buen nivel de servicio.</p>
        
        <p>Puede responder desde su panel de preguntas en el portal de proveedores.</p>
        
        <p>Saludos,<br/>
        Equipo OBYRA Market</p>
        """
        
        return send_email(seller.billing_email, subject, html_content)
        
    except Exception as e:
        logging.error(f"Error sending question notification: {str(e)}")
        return False