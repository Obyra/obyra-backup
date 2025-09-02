"""
OBYRA Marketplace - Email Service
Isolated SMTP service for marketplace notifications
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

def send(to_email: str, subject: str, html: str, attachments=None):
    """
    Send email using marketplace SMTP configuration
    
    Args:
        to_email: Recipient email
        subject: Email subject
        html: HTML content
        attachments: List of file paths to attach
        
    Returns:
        bool: Success status
    """
    try:
        # Get SMTP configuration from environment
        smtp_host = os.environ.get('SMTP_HOST')
        smtp_port = int(os.environ.get('SMTP_PORT', 587))
        smtp_user = os.environ.get('SMTP_USER')
        smtp_password = os.environ.get('SMTP_PASSWORD')
        from_email = os.environ.get('FROM_EMAIL', 'OBYRA <notificaciones@obyra.com>')
        
        if not all([smtp_host, smtp_user, smtp_password]):
            print("SMTP configuration incomplete, email not sent")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
        
        # Add HTML content
        html_part = MIMEText(html, 'html', 'utf-8')
        msg.attach(html_part)
        
        # Add attachments if provided
        if attachments:
            for attachment_path in attachments:
                if os.path.exists(attachment_path):
                    with open(attachment_path, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        
                        filename = os.path.basename(attachment_path)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename= {filename}'
                        )
                        msg.attach(part)
        
        # Send email
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        server.quit()
        
        print(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        print(f"Error sending email to {to_email}: {str(e)}")
        return False

def send_po_notification(supplier_email: str, oc_number: str, buyer_name: str, pdf_path: str):
    """
    Send purchase order notification to supplier
    """
    subject = f"Nueva Orden de Compra - {oc_number}"
    
    html = f"""
    <h2>Nueva Orden de Compra</h2>
    <p>Estimado proveedor,</p>
    
    <p>Se ha generado una nueva orden de compra:</p>
    
    <ul>
        <li><strong>Número de OC:</strong> {oc_number}</li>
        <li><strong>Comprador:</strong> {buyer_name}</li>
        <li><strong>Fecha:</strong> {datetime.now().strftime('%d/%m/%Y')}</li>
    </ul>
    
    <p>Por favor, revise el PDF adjunto con todos los detalles.</p>
    
    <p>Saludos,<br/>
    Equipo OBYRA Market</p>
    """
    
    return send(supplier_email, subject, html, [pdf_path] if pdf_path else None)

def send_order_confirmation(buyer_email: str, order_number: str, total_amount: float):
    """
    Send order confirmation to buyer
    """
    subject = f"Confirmación de Orden - {order_number}"
    
    html = f"""
    <h2>Orden Confirmada</h2>
    <p>Estimado cliente,</p>
    
    <p>Su orden ha sido procesada exitosamente:</p>
    
    <ul>
        <li><strong>Número de Orden:</strong> {order_number}</li>
        <li><strong>Total:</strong> ${total_amount:,.2f} ARS</li>
    </ul>
    
    <p>Las órdenes de compra han sido enviadas a los proveedores.</p>
    
    <p>Gracias por confiar en OBYRA Market.</p>
    
    <p>Saludos,<br/>
    Equipo OBYRA Market</p>
    """
    
    return send(buyer_email, subject, html)

from datetime import datetime