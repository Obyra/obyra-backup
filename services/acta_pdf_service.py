"""
Servicio de generación de PDF para Acta de Entrega.

Genera un PDF profesional con los datos del acta:
- Encabezado con logo (si existe) y número de acta
- Datos de la obra y organización
- Datos del receptor (cliente)
- Descripción, items entregados, observaciones
- Garantía si aplica
- Espacios para firmas
- Pie de página con metadata
"""

from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.colors import HexColor, black, gray, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether
)


# Colores de marca
COLOR_PRIMARY = HexColor('#1a3556')   # Azul marino OBYRA
COLOR_ACCENT = HexColor('#4caf50')    # Verde accent
COLOR_LIGHT = HexColor('#f5f7fa')
COLOR_BORDER = HexColor('#dce0e8')
COLOR_MUTED = HexColor('#6b6b6b')


def _format_fecha(dt) -> str:
    """Formatea una fecha en español."""
    if not dt:
        return '-'
    meses = [
        'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
        'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'
    ]
    try:
        return f"{dt.day} de {meses[dt.month - 1]} de {dt.year}"
    except (AttributeError, IndexError):
        return str(dt)


def generar_pdf_acta(acta) -> bytes:
    """
    Genera el PDF del acta de entrega.

    Args:
        acta: instancia de ActaEntrega

    Returns:
        bytes del PDF generado
    """
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Acta de Entrega - Obra {acta.obra.nombre}",
        author="OBYRA",
    )

    # ─── Estilos ───
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        'TitleObyra',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=COLOR_PRIMARY,
        alignment=TA_CENTER,
        spaceAfter=8,
        fontName='Helvetica-Bold',
    )
    style_subtitle = ParagraphStyle(
        'SubtitleObyra',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=COLOR_MUTED,
        alignment=TA_CENTER,
        spaceAfter=20,
    )
    style_section = ParagraphStyle(
        'SectionObyra',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=COLOR_PRIMARY,
        spaceBefore=14,
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )
    style_normal = ParagraphStyle(
        'NormalObyra',
        parent=styles['Normal'],
        fontSize=10,
        textColor=black,
        leading=14,
        alignment=TA_JUSTIFY,
    )
    style_label = ParagraphStyle(
        'LabelObyra',
        parent=styles['Normal'],
        fontSize=9,
        textColor=COLOR_MUTED,
        fontName='Helvetica-Bold',
    )
    style_value = ParagraphStyle(
        'ValueObyra',
        parent=styles['Normal'],
        fontSize=10,
        textColor=black,
    )
    style_footer = ParagraphStyle(
        'FooterObyra',
        parent=styles['Normal'],
        fontSize=8,
        textColor=COLOR_MUTED,
        alignment=TA_CENTER,
    )

    story = []

    # ─── ENCABEZADO ───
    # Tabla con logo (texto por ahora) y número de acta
    org_nombre = ''
    try:
        if acta.obra and acta.obra.organizacion:
            org_nombre = acta.obra.organizacion.nombre
    except Exception:
        pass

    encabezado_data = [
        [
            Paragraph(f'<b><font color="{COLOR_PRIMARY.hexval()}" size="16">OBYRA</font></b><br/>'
                      f'<font color="{COLOR_MUTED.hexval()}" size="8">{org_nombre}</font>',
                      style_normal),
            Paragraph(f'<para alignment="right"><b>ACTA Nº {acta.id:05d}</b><br/>'
                      f'<font size="8" color="{COLOR_MUTED.hexval()}">{_format_fecha(acta.fecha_acta)}</font></para>',
                      style_normal),
        ]
    ]
    encabezado_tabla = Table(encabezado_data, colWidths=[10 * cm, 7 * cm])
    encabezado_tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 2, COLOR_ACCENT),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(encabezado_tabla)
    story.append(Spacer(1, 16))

    # ─── TÍTULO ───
    tipo_titulo = (acta.tipo or 'definitiva').upper()
    story.append(Paragraph(f'ACTA DE ENTREGA {tipo_titulo}', style_title))
    story.append(Paragraph('Obra: ' + (acta.obra.nombre or '-'), style_subtitle))

    # ─── DATOS DE LA OBRA ───
    story.append(Paragraph('DATOS DE LA OBRA', style_section))

    obra_data = [
        [
            Paragraph('OBRA', style_label),
            Paragraph(acta.obra.nombre or '-', style_value),
        ],
        [
            Paragraph('CLIENTE', style_label),
            Paragraph(getattr(acta.obra, 'cliente', None) or '-', style_value),
        ],
        [
            Paragraph('DIRECCIÓN', style_label),
            Paragraph(getattr(acta.obra, 'direccion', None) or '-', style_value),
        ],
        [
            Paragraph('FECHA DE ENTREGA', style_label),
            Paragraph(_format_fecha(acta.fecha_acta), style_value),
        ],
    ]
    obra_tabla = Table(obra_data, colWidths=[5 * cm, 12 * cm])
    obra_tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, COLOR_BORDER),
        ('BACKGROUND', (0, 0), (0, -1), COLOR_LIGHT),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(obra_tabla)

    # ─── RECIBE ───
    story.append(Paragraph('RECEPTOR DE LA ENTREGA', style_section))

    receptor_data = [
        [
            Paragraph('NOMBRE', style_label),
            Paragraph(acta.recibido_por_nombre or '-', style_value),
        ],
    ]
    if acta.recibido_por_dni:
        receptor_data.append([
            Paragraph('DNI', style_label),
            Paragraph(acta.recibido_por_dni, style_value),
        ])
    if acta.recibido_por_cargo:
        receptor_data.append([
            Paragraph('CARGO', style_label),
            Paragraph(acta.recibido_por_cargo, style_value),
        ])

    receptor_tabla = Table(receptor_data, colWidths=[5 * cm, 12 * cm])
    receptor_tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, COLOR_BORDER),
        ('BACKGROUND', (0, 0), (0, -1), COLOR_LIGHT),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(receptor_tabla)

    # ─── DESCRIPCIÓN ───
    if acta.descripcion:
        story.append(Paragraph('DESCRIPCIÓN', style_section))
        story.append(Paragraph(acta.descripcion.replace('\n', '<br/>'), style_normal))

    # ─── ITEMS ENTREGADOS ───
    if acta.items_entregados:
        story.append(Paragraph('ITEMS ENTREGADOS', style_section))
        story.append(Paragraph(acta.items_entregados.replace('\n', '<br/>'), style_normal))

    # ─── OBSERVACIONES DEL CLIENTE ───
    if acta.observaciones_cliente:
        story.append(Paragraph('OBSERVACIONES DEL CLIENTE', style_section))
        story.append(Paragraph(acta.observaciones_cliente.replace('\n', '<br/>'), style_normal))

    # ─── GARANTÍA ───
    if acta.plazo_garantia_meses:
        story.append(Paragraph('GARANTÍA', style_section))
        garantia_text = (
            f'Se establece una garantía de <b>{acta.plazo_garantia_meses} meses</b> '
            f'a partir del {_format_fecha(acta.fecha_inicio_garantia or acta.fecha_acta)}.'
        )
        story.append(Paragraph(garantia_text, style_normal))

    # ─── FIRMAS ───
    story.append(Spacer(1, 30))

    firmas_data = [
        [
            Paragraph('<para alignment="center">________________________________<br/><br/>'
                      f'<b>{acta.recibido_por_nombre or "Firma del Cliente"}</b><br/>'
                      f'<font size="8" color="{COLOR_MUTED.hexval()}">Recibe conforme</font></para>',
                      style_normal),
            Paragraph('<para alignment="center">________________________________<br/><br/>'
                      f'<b>{org_nombre or "OBYRA"}</b><br/>'
                      f'<font size="8" color="{COLOR_MUTED.hexval()}">Entrega</font></para>',
                      style_normal),
        ]
    ]
    firmas_tabla = Table(firmas_data, colWidths=[8.5 * cm, 8.5 * cm])
    firmas_tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(firmas_tabla)

    # ─── PIE ───
    story.append(Spacer(1, 24))
    pie = (
        f'Documento generado el {datetime.utcnow().strftime("%d/%m/%Y %H:%M")} UTC '
        f'por OBYRA · Acta Nº {acta.id:05d} · Cierre Nº {acta.cierre_id}'
    )
    story.append(Paragraph(pie, style_footer))

    doc.build(story)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
