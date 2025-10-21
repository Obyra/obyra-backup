"""
Dashboard PDF Report V2 Service - Professional reports with branding, KPIs, and charts.
Reemplaza completamente la versión anterior del sistema de reportes.
"""

from flask import Blueprint, request, jsonify, make_response, current_app
from flask_login import login_required, current_user
try:
    import weasyprint
    WEASYPRINT_AVAILABLE = True
    WEASYPRINT_IMPORT_ERROR = None
except Exception as weasy_exc:  # pragma: no cover - platform dependent
    weasyprint = None  # type: ignore
    WEASYPRINT_AVAILABLE = False
    WEASYPRINT_IMPORT_ERROR = weasy_exc
from jinja2 import Template
from io import BytesIO
import base64
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
from datetime import datetime, timedelta
import logging

from models import Event, Obra, Presupuesto, Usuario, Organizacion, db
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
    Endpoint POST /api/reports/dashboard V2 - Reporte profesional con branding y gráficos
    Body JSON (opcional):
    {
      "range": "last_30d",
      "include_alerts": true,
      "project_ids": [1,2],
      "compare_with_previous": true,
      "locale": "es-AR",
      "currency": "ARS"
    }
    """
    if not WEASYPRINT_AVAILABLE:
        details = str(WEASYPRINT_IMPORT_ERROR) if WEASYPRINT_IMPORT_ERROR else 'weasyprint dependency missing'
        current_app.logger.warning(
            "WeasyPrint not available; dashboard PDF cannot be generated (%s)",
            details
        )
        return jsonify({
            'error': 'pdf_engine_unavailable',
            'details': details,
            'help': 'Instala las dependencias de WeasyPrint (GTK / libgobject) para habilitar los reportes PDF.'
        }), 503

    try:
        # Verificar permisos
        if current_user.rol not in ['administrador', 'gestor']:
            return jsonify({'error': 'Sin permisos para generar reportes'}), 403
        
        data = request.get_json() or {}
        
        # Parámetros con valores por defecto - V2
        date_range = data.get('range', 'last_30d')
        include_alerts = data.get('include_alerts', True)
        project_ids = data.get('project_ids', [])
        compare_with_previous = data.get('compare_with_previous', True)
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
        
        # Generar el PDF V2 con WeasyPrint
        try:
            pdf_buffer = generate_pdf_v2_report(
                current_user.organizacion, 
                start_date, end_date, range_text,
                include_alerts, project_ids, currency, compare_with_previous
            )
        except Exception as pdf_error:
            logger.error(f"Error en generación PDF V2: {pdf_error}")
            return jsonify({'error': 'pdf_render_failed', 'details': str(pdf_error)}), 500
        
        # Crear respuesta con el PDF
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=obyra-dashboard-{datetime.now().strftime("%Y%m%d")}.pdf'
        response.headers['Cache-Control'] = 'no-cache'
        
        logger.info(f"Reporte PDF V2 generado por usuario {current_user.id} para organización {current_user.organizacion_id}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error generando reporte PDF: {str(e)}")
        return jsonify({'error': 'Error generando el reporte PDF'}), 500


def generate_pdf_v2_report(organizacion, start_date, end_date, range_text, include_alerts, project_ids, currency, compare_with_previous):
    """Genera PDF Dashboard V2 con WeasyPrint - Profesional con branding, KPIs comparativos y gráficos"""
    
    # Obtener datos para el reporte
    report_data = gather_report_data_v2(
        organizacion.id, start_date.date(), end_date.date(), 
        project_ids, include_alerts, compare_with_previous
    )
    
    # Generar gráficos como imágenes base64
    charts = generate_charts_v2(report_data, start_date.date(), end_date.date())
    
    # Calcular días del rango para el subtítulo
    rango_dias = (end_date.date() - start_date.date()).days
    
    # Preparar contexto para el template
    context = {
        'organizacion': organizacion,
        'range_text': range_text,
        'rango_dias': rango_dias,
        'start_date': start_date,
        'end_date': end_date,
        'current_date': datetime.now(),
        'current_user': current_user,
        'currency': currency,
        'data': report_data,
        'charts': charts,
        'include_alerts': include_alerts
    }
    
    # Renderizar template HTML
    with open('templates/reports/dashboard.html', 'r', encoding='utf-8') as f:
        template_content = f.read()
    
    template = Template(template_content)
    html_content = template.render(**context)
    
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError('WeasyPrint no está disponible en este entorno')

    # Convertir HTML a PDF con WeasyPrint
    try:
        pdf_document = weasyprint.HTML(string=html_content).write_pdf()
        pdf_buffer = BytesIO(pdf_document)
        pdf_buffer.seek(0)
        return pdf_buffer
    except Exception as render_error:
        logger.error(f"WeasyPrint render error: {render_error}")
        raise


def gather_report_data_v2(org_id, fecha_desde, fecha_hasta, project_ids, include_alerts, compare_with_previous):
    """Recopila datos para el reporte Dashboard V2 incluyendo comparativas"""
    
    data = {
        'kpis': [],
        'obras_activas': [],
        'alertas': [],
        'alertas_stats': {}
    }
    
    # Calcular período anterior para comparativas
    periodo_dias = (fecha_hasta - fecha_desde).days
    fecha_anterior_desde = fecha_desde - timedelta(days=periodo_dias)
    fecha_anterior_hasta = fecha_desde - timedelta(days=1)
    
    # === KPIs con comparativa ===
    kpis_actuales = calculate_kpis_v2(org_id, fecha_desde, fecha_hasta, project_ids)
    kpis_anteriores = calculate_kpis_v2(org_id, fecha_anterior_desde, fecha_anterior_hasta, project_ids) if compare_with_previous else {}
    
    # Formatear KPIs con deltas
    kpi_definitions = [
        {
            'key': 'obras_activas',
            'icon': '🏗️',
            'label': 'Obras Activas',
            'format': 'number'
        },
        {
            'key': 'costo_total',
            'icon': '💰',
            'label': 'Costo Total (M)',
            'format': 'currency_millions'
        },
        {
            'key': 'avance_promedio',
            'icon': '📈',
            'label': 'Avance Promedio',
            'format': 'percentage'
        },
        {
            'key': 'personal_activo',
            'icon': '👥',
            'label': 'Personal Activo',
            'format': 'number'
        },
        {
            'key': 'obras_nuevas',
            'icon': '🆕',
            'label': 'Obras Nuevas',
            'format': 'number'
        },
        {
            'key': 'presupuestos_creados',
            'icon': '📊',
            'label': 'Presupuestos Creados',
            'format': 'number'
        }
    ]
    
    for kpi_def in kpi_definitions:
        key = kpi_def['key']
        current_value = kpis_actuales.get(key, 0)
        previous_value = kpis_anteriores.get(key, 0) if compare_with_previous else None
        
        # Formatear valor
        if kpi_def['format'] == 'currency_millions':
            formatted_value = f"{current_value:.1f}M"
        elif kpi_def['format'] == 'percentage':
            formatted_value = f"{current_value:.1f}%"
        else:
            formatted_value = str(int(current_value))
        
        kpi_data = {
            'icon': kpi_def['icon'],
            'label': kpi_def['label'],
            'value': formatted_value
        }
        
        # Calcular delta si hay comparativa usando función auxiliar
        if compare_with_previous:
            delta_result = compute_delta(current_value, previous_value)
            
            if delta_result is None:
                # Sin datos previos
                kpi_data.update({
                    'delta': 'sin datos previos',
                    'delta_symbol': '—',
                    'delta_class': 'delta-no-data'
                })
            elif delta_result['direction'] == 'flat':
                # Variación 0
                kpi_data.update({
                    'delta': f"{delta_result['pct']:.1f}",
                    'delta_symbol': '→',
                    'delta_class': 'delta-neutral'
                })
            elif delta_result['direction'] == 'up':
                # Variación positiva
                kpi_data.update({
                    'delta': f"{delta_result['pct']:.1f}",
                    'delta_symbol': '↗',
                    'delta_class': 'delta-positive'
                })
            else:
                # Variación negativa
                kpi_data.update({
                    'delta': f"{abs(delta_result['pct']):.1f}",
                    'delta_symbol': '↘',
                    'delta_class': 'delta-negative'
                })
        
        data['kpis'].append(kpi_data)
    
    # === Obras Activas ===
    obras_query = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso'])
    )
    
    if project_ids:
        obras_query = obras_query.filter(Obra.id.in_(project_ids))
    
    # Ordenar por % avance descendente
    data['obras_activas'] = obras_query.order_by(desc(Obra.progreso)).limit(15).all()
    
    # === Alertas ===
    if include_alerts:
        alertas_query = Event.query.filter(
            Event.company_id == org_id,
            Event.created_at >= fecha_desde,
            Event.created_at <= fecha_hasta
        ).order_by(desc(Event.created_at)).limit(20)
        
        data['alertas'] = alertas_query.all()
        
        # Estadísticas de alertas por severidad
        alertas_stats = db.session.query(
            Event.severity, func.count(Event.id)
        ).filter(
            Event.company_id == org_id,
            Event.created_at >= fecha_desde,
            Event.created_at <= fecha_hasta
        ).group_by(Event.severity).all()
        
        data['alertas_stats'] = {severity: count for severity, count in alertas_stats}
    
    return data


def calculate_kpis_v2(org_id, fecha_desde, fecha_hasta, project_ids):
    """Calcula KPIs para un período específico"""
    
    # Query base filtrada por organización
    obras_query = Obra.query.filter(Obra.organizacion_id == org_id)
    
    if project_ids:
        obras_query = obras_query.filter(Obra.id.in_(project_ids))
    
    # Obras activas al final del período
    obras_activas = obras_query.filter(
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).count()
    
    # Obras nuevas en el período
    obras_nuevas = obras_query.filter(
        Obra.fecha_creacion >= fecha_desde,
        Obra.fecha_creacion <= fecha_hasta
    ).count()
    
    # Costo total (en millones)
    costo_total = db.session.query(
        func.sum(Obra.presupuesto_total)
    ).filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso'])
    ).scalar() or 0
    costo_total_millones = float(costo_total) / 1000000 if costo_total else 0
    
    # Avance promedio
    avance_promedio = db.session.query(
        func.avg(Obra.progreso)
    ).filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso']),
        Obra.progreso.isnot(None)
    ).scalar() or 0
    
    # Personal activo
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
        'obras_nuevas': obras_nuevas,
        'costo_total': costo_total_millones,
        'avance_promedio': float(avance_promedio) if avance_promedio else 0,
        'personal_activo': personal_activo,
        'presupuestos_creados': presupuestos_creados
    }


def generate_charts_v2(report_data, fecha_desde, fecha_hasta):
    """Genera gráficos como imágenes base64 para incluir en PDF"""
    
    charts = {}
    
    try:
        # Configurar matplotlib para generar imágenes limpias
        try:
            plt.style.use('seaborn-v0_8')
        except:
            plt.style.use('default')  # Fallback to default style
        
        plt.rcParams.update({
            'figure.facecolor': 'white',
            'axes.facecolor': 'white',
            'font.size': 10,
            'figure.dpi': 100
        })
        
        # === Gráfico 1: Alertas por Severidad (Barras) ===
        if report_data['alertas_stats'] and any(report_data['alertas_stats'].values()):
            fig, ax = plt.subplots(figsize=(8, 5))
            
            severities = ['critica', 'alta', 'media', 'baja']
            colors = ['#dc3545', '#fd7e14', '#ffc107', '#6c757d']  # Colores más claros y consistentes
            values = [report_data['alertas_stats'].get(sev, 0) for sev in severities]
            labels = ['Crítica', 'Alta', 'Media', 'Baja']
            
            bars = ax.bar(labels, values, color=colors, alpha=0.85, edgecolor='white', linewidth=1)
            ax.set_title('Distribución de Alertas por Severidad', fontsize=14, fontweight='bold', pad=20)
            ax.set_ylabel('Cantidad de Alertas')
            ax.grid(axis='y', alpha=0.3, linestyle='--')
            
            # Agregar valores en las barras
            for bar, value in zip(bars, values):
                if value > 0:
                    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                           str(int(value)), ha='center', va='bottom', fontweight='bold', fontsize=11)
            
            plt.tight_layout()
            
            # Convertir a base64
            buffer = BytesIO()
            plt.savefig(buffer, format='png', bbox_inches='tight', facecolor='white', dpi=150)
            buffer.seek(0)
            charts['alerts_by_severity'] = base64.b64encode(buffer.getvalue()).decode()
            buffer.close()
            plt.close()
        else:
            # Placeholder para sin datos
            charts['alerts_by_severity_placeholder'] = True
        
        # === Gráfico 2: Progreso de Obras (Torta) ===
        if report_data['obras_activas']:
            fig, ax = plt.subplots(figsize=(8, 6))
            
            # Categorizar obras por rango de progreso - paleta de azules/verdes
            progress_ranges = [
                (0, 25, '0-25%', '#ff6b6b'),      # Rojo suave para bajo progreso
                (26, 50, '26-50%', '#feca57'),    # Amarillo para progreso medio-bajo
                (51, 75, '51-75%', '#48dbfb'),    # Azul para progreso medio-alto
                (76, 100, '76-100%', '#0abde3')   # Azul fuerte para alto progreso
            ]
            
            range_counts = []
            range_labels = []
            range_colors = []
            
            for min_prog, max_prog, label, color in progress_ranges:
                count = sum(1 for obra in report_data['obras_activas'] 
                          if (obra.progreso or 0) >= min_prog and (obra.progreso or 0) <= max_prog)
                if count > 0:
                    range_counts.append(count)
                    range_labels.append(f"{label}\n({count} obras)")
                    range_colors.append(color)
            
            if range_counts:
                wedges, texts, autotexts = ax.pie(range_counts, labels=range_labels, colors=range_colors,
                                                 autopct='%1.1f%%', startangle=90, 
                                                 textprops={'fontsize': 10, 'fontweight': 'bold'})
                ax.set_title('Distribución de Obras por Progreso', fontsize=14, fontweight='bold', pad=20)
                
                # Mejorar apariencia de los textos
                for autotext in autotexts:
                    autotext.set_color('white')
                    autotext.set_fontweight('bold')
                
                plt.tight_layout()
                
                buffer = BytesIO()
                plt.savefig(buffer, format='png', bbox_inches='tight', facecolor='white', dpi=150)
                buffer.seek(0)
                charts['project_progress'] = base64.b64encode(buffer.getvalue()).decode()
                buffer.close()
            else:
                charts['project_progress_placeholder'] = True
            plt.close()
        else:
            charts['project_progress_placeholder'] = True
        
        # === Gráfico 3: Timeline de Presupuestos (Línea) ===
        presupuestos_timeline = db.session.query(
            func.date(Presupuesto.fecha_creacion).label('fecha'),
            func.count(Presupuesto.id).label('cantidad')
        ).filter(
            Presupuesto.fecha_creacion >= fecha_desde,
            Presupuesto.fecha_creacion <= fecha_hasta
        ).group_by(func.date(Presupuesto.fecha_creacion)).order_by('fecha').all()
        
        if presupuestos_timeline and len(presupuestos_timeline) > 0:
            fig, ax = plt.subplots(figsize=(10, 5))
            
            fechas = [item.fecha for item in presupuestos_timeline]
            cantidades = [item.cantidad for item in presupuestos_timeline]
            
            # Línea azul más marcada con gradiente
            ax.plot(fechas, cantidades, marker='o', linewidth=3, markersize=8, 
                   color='#2980b9', markerfacecolor='#3498db', markeredgecolor='white', 
                   markeredgewidth=2, alpha=0.9)
            
            # Rellenar área bajo la curva
            ax.fill_between(fechas, cantidades, alpha=0.2, color='#3498db')
            
            ax.set_title('Presupuestos Creados en el Tiempo', fontsize=14, fontweight='bold', pad=20)
            ax.set_xlabel('Fecha', fontweight='bold')
            ax.set_ylabel('Cantidad de Presupuestos', fontweight='bold')
            ax.grid(True, alpha=0.3, linestyle='--')
            
            # Mejorar formato de fechas
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            
            buffer = BytesIO()
            plt.savefig(buffer, format='png', bbox_inches='tight', facecolor='white', dpi=150)
            buffer.seek(0)
            charts['budgets_timeline'] = base64.b64encode(buffer.getvalue()).decode()
            buffer.close()
            plt.close()
        else:
            charts['budgets_timeline_placeholder'] = True
            
    except Exception as chart_error:
        logger.warning(f"Error generando gráficos: {chart_error}")
        # Continuar sin gráficos si hay error
        
    return charts


def compute_delta(curr, prev):
    """Calcula la variación porcentual entre valores actuales y previos"""
    try:
        prev = float(prev) if prev not in (None, 0) else None
    except:
        prev = None
    
    try:
        curr = float(curr) if curr is not None else 0.0
    except:
        curr = 0.0
    
    if prev is None:
        return None
    
    pct = round(((curr - prev) / prev) * 100, 1)
    direction = "flat" if pct == 0 else ("up" if pct > 0 else "down")
    
    return {"pct": pct, "direction": direction}