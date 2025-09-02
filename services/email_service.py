"""
OBYRA Market - Email Service
Handles SMTP email sending for notifications and purchase orders
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os

def send_email(to_email, subject, html_content, attachments=None):
    """
    Envía email usando configuración SMTP
    
    Args:
        to_email (str): Email destinatario
        subject (str): Asunto del email
        html_content (str): Contenido HTML del email
        attachments (list): Lista de archivos adjuntos
    """
    try:
        from flask import current_app
        
        smtp_host = current_app.config.get('SMTP_HOST')
        smtp_port = current_app.config.get('SMTP_PORT', 587)
        smtp_user = current_app.config.get('SMTP_USER')
        smtp_password = current_app.config.get('SMTP_PASSWORD')
        from_email = current_app.config.get('FROM_EMAIL', smtp_user)
        
        if not all([smtp_host, smtp_user, smtp_password]):
            logging.warning("SMTP configuration incomplete, email not sent")
            return False
        
        # Crear mensaje
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
        
        # Contenido HTML
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # Adjuntos
        if attachments:
            for attachment in attachments:
                if os.path.exists(attachment['path']):
                    with open(attachment['path'], 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename= {attachment["filename"]}'
                        )
                        msg.attach(part)
        
        # Enviar email
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        server.quit()
        
        logging.info(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        logging.error(f"Error sending email to {to_email}: {str(e)}")
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