"""
Service para generación de reportes PDF del dashboard.
Genera informes con KPIs, alertas recientes y obras activas.
"""

from flask import Blueprint, request, jsonify, current_app, make_response
from flask_login import login_required, current_user
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from io import BytesIO
from datetime import datetime, timedelta
import logging

from models import Event, Obra, Presupuesto, ItemInventario, db
from sqlalchemy import func, desc

# Blueprint para endpoints de reportes
reports_bp = Blueprint('reports', __name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@reports_bp.route('/api/reports/dashboard', methods=['POST'])
@login_required
def generate_dashboard_report():
    """
    Endpoint POST /api/reports/dashboard para generar reporte PDF del dashboard
    Body JSON (opcional):
    {
      "range": "last_30d",
      "include_alerts": true,
      "project_ids": [1,2],
      "locale": "es-AR",
      "currency": "ARS"
    }
    """
    try:
        # Verificar permisos
        if current_user.rol not in ['administrador', 'gestor']:
            return jsonify({'error': 'Sin permisos para generar reportes'}), 403
        
        data = request.get_json() or {}
        
        # Parámetros con valores por defecto
        date_range = data.get('range', 'last_30d')
        include_alerts = data.get('include_alerts', True)
        project_ids = data.get('project_ids', [])
        locale = data.get('locale', 'es-AR')
        currency = data.get('currency', 'ARS')
        
        # Calcular fechas según el rango
        end_date = datetime.now()
        if date_range == 'last_7d':
            start_date = end_date - timedelta(days=7)
            range_text = 'Últimos 7 días'
        elif date_range == 'last_30d':
            start_date = end_date - timedelta(days=30)
            range_text = 'Últimos 30 días'
        elif date_range == 'last_90d':
            start_date = end_date - timedelta(days=90)
            range_text = 'Últimos 90 días'
        else:
            start_date = end_date - timedelta(days=30)
            range_text = 'Últimos 30 días'
        
        # Validar project_ids si se proporcionan
        if project_ids:
            valid_projects = Obra.query.filter(
                Obra.id.in_(project_ids),
                Obra.organizacion_id == current_user.organizacion_id
            ).all()
            if len(valid_projects) != len(project_ids):
                return jsonify({'error': 'Algunos proyectos no pertenecen a la organización'}), 400
        
        # Generar el PDF
        pdf_buffer = BytesIO()
        pdf = generate_pdf_report(
            pdf_buffer, current_user.organizacion, 
            start_date, end_date, range_text,
            include_alerts, project_ids, currency
        )
        
        pdf_buffer.seek(0)
        
        # Crear respuesta con el PDF
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=obyra-dashboard-{datetime.now().strftime("%Y%m%d")}.pdf'
        response.headers['Cache-Control'] = 'no-cache'
        
        logger.info(f"Reporte PDF generado por usuario {current_user.id} para organización {current_user.organizacion_id}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error generando reporte PDF: {str(e)}")
        return jsonify({'error': 'Error generando el reporte PDF'}), 500


def generate_pdf_report(buffer, organizacion, start_date, end_date, range_text, include_alerts, project_ids, currency):
    """Genera el PDF del reporte usando ReportLab"""
    
    # Crear documento PDF
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                          rightMargin=72, leftMargin=72,
                          topMargin=72, bottomMargin=18)
    
    # Estilos
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1,  # Center
        textColor=colors.HexColor('#2C3E50')
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=20,
        textColor=colors.HexColor('#34495E')
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=12
    )
    
    # Contenido del PDF
    story = []
    
    # Portada
    story.append(Paragraph("OBYRA IA", title_style))
    story.append(Paragraph("Reporte del Dashboard", subtitle_style))
    story.append(Spacer(1, 12))
    
    story.append(Paragraph(f"<b>Organización:</b> {organizacion.nombre}", normal_style))
    story.append(Paragraph(f"<b>Período:</b> {range_text}", normal_style))
    story.append(Paragraph(f"<b>Fecha de generación:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", normal_style))
    story.append(Paragraph(f"<b>Generado por:</b> {current_user.nombre} {current_user.apellido}", normal_style))
    story.append(Spacer(1, 30))
    
    # KPIs principales
    story.append(Paragraph("Métricas Clave (KPIs)", subtitle_style))
    
    kpis = calculate_report_kpis(organizacion.id, start_date.date(), end_date.date(), project_ids)
    
    kpis_data = [
        ['Métrica', 'Valor'],
        ['Obras Activas', str(kpis.get('obras_activas', 0))],
        ['Costo Total', f"${kpis.get('costo_total', 0):,.2f} {currency}"],
        ['Avance Promedio', f"{kpis.get('avance_promedio', 0):.1f}%"],
        ['Personal Activo', str(kpis.get('personal_activo', 0))],
        ['Obras Nuevas (período)', str(kpis.get('obras_nuevas_periodo', 0))],
        ['Presupuestos Creados', str(kpis.get('presupuestos_creados', 0))]
    ]
    
    kpis_table = Table(kpis_data, colWidths=[3*inch, 2*inch])
    kpis_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498DB')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(kpis_table)
    story.append(Spacer(1, 30))
    
    # Alertas recientes (si se incluyen)
    if include_alerts:
        story.append(Paragraph("Alertas Recientes", subtitle_style))
        
        alertas = Event.query.filter(
            Event.company_id == organizacion.id,
            Event.severity.in_(['alta', 'critica']),
            Event.created_at >= start_date
        ).order_by(desc(Event.created_at)).limit(10).all()
        
        if alertas:
            alertas_data = [['Severidad', 'Título', 'Descripción', 'Fecha']]
            
            for alerta in alertas:
                alertas_data.append([
                    alerta.severity.title(),
                    alerta.title[:40] + '...' if len(alerta.title) > 40 else alerta.title,
                    (alerta.description[:50] + '...') if alerta.description and len(alerta.description) > 50 else (alerta.description or ''),
                    alerta.created_at.strftime('%d/%m/%Y %H:%M')
                ])
            
            alertas_table = Table(alertas_data, colWidths=[1*inch, 2*inch, 2.5*inch, 1.5*inch])
            alertas_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E74C3C')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#FADBD8')),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(alertas_table)
        else:
            story.append(Paragraph("No hay alertas de alta prioridad en el período seleccionado.", normal_style))
        
        story.append(Spacer(1, 30))
    
    # Obras activas
    story.append(Paragraph("Obras Activas", subtitle_style))
    
    obras_query = Obra.query.filter(
        Obra.organizacion_id == organizacion.id,
        Obra.estado.in_(['planificacion', 'en_curso'])
    )
    
    if project_ids:
        obras_query = obras_query.filter(Obra.id.in_(project_ids))
    
    obras_activas = obras_query.order_by(desc(Obra.fecha_creacion)).limit(15).all()
    
    if obras_activas:
        obras_data = [['Obra', 'Ubicación', 'Estado', '% Avance', 'Presupuesto']]
        
        for obra in obras_activas:
            obras_data.append([
                obra.nombre[:30] + '...' if len(obra.nombre) > 30 else obra.nombre,
                (obra.direccion[:25] + '...') if obra.direccion and len(obra.direccion) > 25 else (obra.direccion or 'N/A'),
                obra.estado.title(),
                f"{obra.progreso or 0}%",
                f"${obra.presupuesto_total or 0:,.0f}" if obra.presupuesto_total else 'N/A'
            ])
        
        obras_table = Table(obras_data, colWidths=[2*inch, 2*inch, 1*inch, 1*inch, 1*inch])
        obras_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27AE60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (3, 1), (4, -1), 'RIGHT'),  # Align percentage and budget to right
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#D5F5E3')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(obras_table)
    else:
        story.append(Paragraph("No hay obras activas en el período seleccionado.", normal_style))
    
    story.append(Spacer(1, 30))
    
    # Footer con información adicional
    story.append(PageBreak())
    story.append(Paragraph("Información Adicional", subtitle_style))
    story.append(Paragraph(f"Este reporte fue generado automáticamente por el sistema OBYRA IA el {datetime.now().strftime('%d de %B de %Y a las %H:%M')}.", normal_style))
    story.append(Paragraph(f"Los datos mostrados corresponden al período: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}", normal_style))
    story.append(Paragraph("Para más información, contacta con el administrador del sistema.", normal_style))
    
    # Generar PDF
    doc.build(story)
    
    return buffer


def calculate_report_kpis(org_id, fecha_desde, fecha_hasta, project_ids):
    """Calcula KPIs específicos para el reporte"""
    
    # Query base filtrada por organización
    obras_query = Obra.query.filter(Obra.organizacion_id == org_id)
    
    if project_ids:
        obras_query = obras_query.filter(Obra.id.in_(project_ids))
    
    # Obras activas
    obras_activas = obras_query.filter(
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).count()
    
    # Obras nuevas en el período
    obras_nuevas_periodo = obras_query.filter(
        Obra.fecha_creacion >= fecha_desde,
        Obra.fecha_creacion <= fecha_hasta
    ).count()
    
    # Costo total de obras activas
    costo_total = db.session.query(
        func.sum(Obra.presupuesto_total)
    ).filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    
    # Avance promedio
    avance_promedio = db.session.query(
        func.avg(Obra.progreso)
    ).filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso']),
        Obra.progreso.isnot(None)
    ).scalar() or 0
    
    # Personal activo (usuarios activos de la organización)
    from models import Usuario
    personal_activo = Usuario.query.filter(
        Usuario.organizacion_id == org_id,
        Usuario.activo == True
    ).count()
    
    # Presupuestos creados en el período
    presupuestos_creados = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id,
        Presupuesto.fecha_creacion >= fecha_desde,
        Presupuesto.fecha_creacion <= fecha_hasta
    ).count()
    
    return {
        'obras_activas': obras_activas,
        'obras_nuevas_periodo': obras_nuevas_periodo,
        'costo_total': float(costo_total) if costo_total else 0,
        'avance_promedio': float(avance_promedio) if avance_promedio else 0,
        'personal_activo': personal_activo,
        'presupuestos_creados': presupuestos_creados
    }