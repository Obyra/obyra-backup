"""
OBYRA Market - Purchase Order Service
Generates PDF purchase orders using ReportLab and sends them to sellers
"""

import importlib.util
import logging
import os
import json
from datetime import datetime

REPORTLAB_AVAILABLE = importlib.util.find_spec("reportlab") is not None
if REPORTLAB_AVAILABLE:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
else:  # pragma: no cover - executed only when optional deps missing
    colors = None  # type: ignore[assignment]
    letter = A4 = None  # type: ignore[assignment]
    inch = 72  # type: ignore[assignment]

    def _missing_reportlab(*args, **kwargs):
        raise RuntimeError(
            "La generación de órdenes de compra en PDF requiere la librería reportlab. Instálala con 'pip install reportlab'."
        )

    SimpleDocTemplate = Table = TableStyle = Paragraph = Spacer = Image = _missing_reportlab  # type: ignore[assignment]
    getSampleStyleSheet = ParagraphStyle = _missing_reportlab  # type: ignore[assignment]
    TA_CENTER = TA_RIGHT = None  # type: ignore[assignment]

from app import db
from models_marketplace import *

def generate_purchase_orders(order_id):
    """
    Genera órdenes de compra por seller para una orden pagada
    """
    order = MarketOrder.query.get(order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")
    
    if order.status != 'paid':
        raise ValueError(f"Order {order_id} not paid")
    
    # Agrupar items por seller
    items_by_seller = {}
    for item in order.items:
        seller_id = item.seller_company_id
        if seller_id not in items_by_seller:
            items_by_seller[seller_id] = []
        items_by_seller[seller_id].append(item)
    
    generated_pos = []
    
    for seller_id, items in items_by_seller.items():
        try:
            po = create_purchase_order(order, seller_id, items)
            generated_pos.append(po)
            
            # Generar PDF
            pdf_path = generate_po_pdf(po)
            po.pdf_url = pdf_path
            
            # TODO: Enviar por email al seller
            send_po_email(po)
            
            po.status = 'sent'
            po.sent_at = datetime.utcnow()
            
        except Exception as e:
            logging.error(f"Error generating PO for seller {seller_id}: {str(e)}")
            continue
    
    db.session.commit()
    return generated_pos

def create_purchase_order(order, seller_id, items):
    """
    Crea el registro de orden de compra en la base de datos
    """
    seller = MarketCompany.query.get(seller_id)
    
    # Generar número de OC
    oc_number = f"OC-{order.id}-{seller_id}-{datetime.now().strftime('%Y%m%d')}"
    
    po = MarketPurchaseOrder(
        order_id=order.id,
        seller_company_id=seller_id,
        buyer_company_id=order.buyer_company_id,
        status='created',
        oc_number=oc_number
    )
    
    db.session.add(po)
    db.session.flush()
    
    return po

def generate_po_pdf(po):
    """
    Genera PDF de la orden de compra usando ReportLab
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "La generación de órdenes de compra en PDF requiere la librería reportlab. Instálala con 'pip install reportlab'."
        )

    from flask import current_app

    # Directorio de almacenamiento
    storage_dir = current_app.config.get('STORAGE_DIR', './storage')
    po_dir = os.path.join(storage_dir, 'po')
    os.makedirs(po_dir, exist_ok=True)
    
    # Nombre del archivo
    filename = f"{po.oc_number}.pdf"
    filepath = os.path.join(po_dir, filename)
    
    # Crear documento PDF
    doc = SimpleDocTemplate(filepath, pagesize=A4)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#2563eb')
    )
    
    # Título
    story.append(Paragraph("ORDEN DE COMPRA", title_style))
    story.append(Spacer(1, 20))
    
    # Información de la OC
    order = po.order
    seller = po.seller
    buyer = po.buyer
    
    # Datos básicos
    info_data = [
        ["Número de OC:", po.oc_number],
        ["Fecha:", datetime.now().strftime('%d/%m/%Y')],
        ["Orden OBYRA:", order.order_number],
        ["Estado:", "CONFIRMADA"]
    ]
    
    info_table = Table(info_data, colWidths=[2*inch, 3*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3f4f6')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    story.append(info_table)
    story.append(Spacer(1, 20))
    
    # Datos del comprador y vendedor
    parties_data = [
        ["COMPRADOR", "PROVEEDOR"],
        [
            f"{buyer.name}\nCUIT: {buyer.cuit}\n{buyer.billing_email}",
            f"{seller.name}\nCUIT: {seller.cuit}\n{seller.billing_email}"
        ]
    ]
    
    parties_table = Table(parties_data, colWidths=[3*inch, 3*inch])
    parties_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
    ]))
    
    story.append(parties_table)
    story.append(Spacer(1, 20))
    
    # Datos de envío
    shipping_data = json.loads(order.shipping_json) if order.shipping_json else {}
    
    story.append(Paragraph("DATOS DE ENTREGA", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    delivery_text = f"""
    <b>Dirección:</b> {shipping_data.get('address', 'A definir')}<br/>
    <b>Ciudad:</b> {shipping_data.get('city', 'A definir')}<br/>
    <b>Código Postal:</b> {shipping_data.get('postal_code', 'A definir')}<br/>
    <b>Contacto:</b> {shipping_data.get('contact_name', order.buyer_user.name)}<br/>
    <b>Teléfono:</b> {shipping_data.get('phone', 'A definir')}
    """
    
    story.append(Paragraph(delivery_text, styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Items de la orden
    story.append(Paragraph("DETALLE DE PRODUCTOS", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    # Filtrar items del seller actual
    seller_items = [item for item in order.items if item.seller_company_id == po.seller_company_id]
    
    items_data = [
        ["Código", "Producto", "Cantidad", "Precio Unit.", "Total"]
    ]
    
    total_amount = 0
    for item in seller_items:
        product = item.variant.product
        item_total = item.unit_price * item.qty
        total_amount += item_total
        
        items_data.append([
            item.variant.sku,
            f"{product.name}",
            str(item.qty),
            f"${item.unit_price:,.2f}",
            f"${item_total:,.2f}"
        ])
    
    # Fila de total
    items_data.append(["", "", "", "TOTAL:", f"${total_amount:,.2f}"])
    
    items_table = Table(items_data, colWidths=[1.5*inch, 3*inch, 1*inch, 1*inch, 1.2*inch])
    items_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        
        # Content
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 9),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        
        # Total row
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f3f4f6')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 10),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    story.append(items_table)
    story.append(Spacer(1, 30))
    
    # Términos y condiciones
    story.append(Paragraph("TÉRMINOS Y CONDICIONES", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    terms = """
    1. Esta orden de compra es vinculante una vez confirmada.<br/>
    2. El plazo de entrega se acordará directamente con el proveedor.<br/>
    3. Los productos deben cumplir con las especificaciones detalladas.<br/>
    4. El pago se realizará según los términos acordados con OBYRA.<br/>
    5. Cualquier modificación debe ser acordada por escrito.<br/>
    """
    
    story.append(Paragraph(terms, styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Footer
    footer_text = f"Generada automáticamente por OBYRA Market el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.grey
    )
    story.append(Paragraph(footer_text, footer_style))
    
    # Construir PDF
    doc.build(story)
    
    # Retornar path relativo para almacenar en DB
    return f"po/{filename}"

def send_po_email(po):
    """
    Envía la OC por email al proveedor
    """
    try:
        from services.email_service import send_email
        
        seller = po.seller
        order = po.order
        
        subject = f"Nueva Orden de Compra - {po.oc_number}"
        
        html_content = f"""
        <h2>Nueva Orden de Compra</h2>
        <p>Estimado proveedor <strong>{seller.name}</strong>,</p>
        
        <p>Se ha generado una nueva orden de compra para su empresa:</p>
        
        <ul>
            <li><strong>Número de OC:</strong> {po.oc_number}</li>
            <li><strong>Orden OBYRA:</strong> {order.order_number}</li>
            <li><strong>Fecha:</strong> {datetime.now().strftime('%d/%m/%Y')}</li>
            <li><strong>Comprador:</strong> {po.buyer.name}</li>
        </ul>
        
        <p>Por favor, revise el PDF adjunto con todos los detalles de la orden.</p>
        
        <p>Para confirmar la orden y gestionar el envío, ingrese a su portal de proveedor.</p>
        
        <p>Saludos,<br/>
        Equipo OBYRA Market</p>
        """
        
        # Adjuntar PDF
        from flask import current_app
        storage_dir = current_app.config.get('STORAGE_DIR', './storage')
        pdf_path = os.path.join(storage_dir, po.pdf_url)
        
        attachments = []
        if os.path.exists(pdf_path):
            attachments.append({
                'filename': f"{po.oc_number}.pdf",
                'path': pdf_path,
                'content_type': 'application/pdf'
            })
        
        send_email(
            to_email=seller.billing_email,
            subject=subject,
            html_content=html_content,
            attachments=attachments
        )
        
        logging.info(f"PO email sent to {seller.billing_email} for {po.oc_number}")
        
    except Exception as e:
        logging.error(f"Error sending PO email: {str(e)}")
        # No fallar el proceso por error de email
        pass