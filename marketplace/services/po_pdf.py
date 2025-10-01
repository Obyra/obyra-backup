"""
OBYRA Marketplace - Purchase Order PDF Generation Service
"""

import importlib.util
import os
from datetime import datetime

REPORTLAB_AVAILABLE = importlib.util.find_spec("reportlab") is not None
if REPORTLAB_AVAILABLE:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
else:  # pragma: no cover - executed only when optional deps missing
    colors = None  # type: ignore[assignment]
    A4 = None  # type: ignore[assignment]
    inch = 72  # type: ignore[assignment]

    def _missing_reportlab(*args, **kwargs):
        raise RuntimeError(
            "La generación de órdenes de compra en PDF requiere la librería reportlab. Instálala con 'pip install reportlab'."
        )

    SimpleDocTemplate = Table = TableStyle = Paragraph = Spacer = _missing_reportlab  # type: ignore[assignment]
    getSampleStyleSheet = ParagraphStyle = _missing_reportlab  # type: ignore[assignment]
    TA_CENTER = TA_RIGHT = None  # type: ignore[assignment]

def generate_po_pdf(oc_number: str, supplier_name: str, buyer_name: str, buyer_cuit: str,
                   delivery_addr: str, items: list[dict]) -> tuple[str, str]:
    """
    Generate purchase order PDF
    
    Args:
        oc_number: Purchase order number
        supplier_name: Supplier company name
        buyer_name: Buyer company name  
        buyer_cuit: Buyer CUIT
        delivery_addr: Delivery address
        items: List of order items with product info
        
    Returns:
        Tuple of (public_url, abs_path)
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "La generación de órdenes de compra en PDF requiere la librería reportlab. Instálala con 'pip install reportlab'."
        )

    # Create storage directory
    storage_dir = os.environ.get('STORAGE_DIR', './storage')
    po_dir = os.path.join(storage_dir, 'po')
    os.makedirs(po_dir, exist_ok=True)
    
    # Generate filename
    filename = f"{oc_number}.pdf"
    abs_path = os.path.join(po_dir, filename)
    
    # Create PDF document
    doc = SimpleDocTemplate(abs_path, pagesize=A4)
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
    
    # Title
    story.append(Paragraph("ORDEN DE COMPRA", title_style))
    story.append(Spacer(1, 20))
    
    # Order information
    info_data = [
        ["Número de OC:", oc_number],
        ["Fecha:", datetime.now().strftime('%d/%m/%Y')],
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
    
    # Buyer and supplier information
    parties_data = [
        ["COMPRADOR", "PROVEEDOR"],
        [
            f"{buyer_name}\nCUIT: {buyer_cuit}",
            f"{supplier_name}"
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
    
    # Delivery information
    story.append(Paragraph("DATOS DE ENTREGA", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    delivery_text = f"<b>Dirección:</b> {delivery_addr}"
    story.append(Paragraph(delivery_text, styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Items table
    story.append(Paragraph("DETALLE DE PRODUCTOS", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    items_data = [
        ["Código", "Producto", "Cantidad", "Precio Unit.", "Total"]
    ]
    
    total_amount = 0
    for item in items:
        item_total = item['unit_price'] * item['qty']
        total_amount += item_total
        
        items_data.append([
            item.get('sku', 'N/A'),
            item['product_name'],
            str(item['qty']),
            f"${item['unit_price']:,.2f}",
            f"${item_total:,.2f}"
        ])
    
    # Total row
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
    
    # Terms and conditions
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
    
    # Build PDF
    doc.build(story)
    
    # Generate public URL
    base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
    public_url = f"{base_url}/storage/po/{filename}"
    
    return public_url, abs_path
