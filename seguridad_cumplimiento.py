"""
Módulo de Seguridad y Cumplimiento - OBYRA IA
Gestión de protocolos de seguridad, cumplimiento normativo,
registro de incidentes y certificaciones.
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
import json
from utils.pagination import Pagination
from app import db
from models import *
from utils import *

seguridad_bp = Blueprint('seguridad', __name__)

class ProtocoloSeguridad(db.Model):
    __tablename__ = 'protocolos_seguridad'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    categoria = db.Column(db.String(50), nullable=False)  # epp, procedimiento, emergencia, inspeccion
    obligatorio = db.Column(db.Boolean, default=True)
    frecuencia_revision = db.Column(db.Integer, default=30)  # días
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)
    normativa_referencia = db.Column(db.String(200))

class ChecklistSeguridad(db.Model):
    __tablename__ = 'checklists_seguridad'
    
    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    protocolo_id = db.Column(db.Integer, db.ForeignKey('protocolos_seguridad.id'), nullable=False)
    fecha_inspeccion = db.Column(db.Date, nullable=False)
    inspector_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, completado, no_conforme
    puntuacion = db.Column(db.Integer)  # 0-100
    observaciones = db.Column(db.Text)
    acciones_correctivas = db.Column(db.Text)
    fecha_completado = db.Column(db.DateTime)
    
    # Relaciones
    obra = db.relationship('Obra')
    protocolo = db.relationship('ProtocoloSeguridad')
    inspector = db.relationship('Usuario')

class ItemChecklist(db.Model):
    __tablename__ = 'items_checklist'
    
    id = db.Column(db.Integer, primary_key=True)
    checklist_id = db.Column(db.Integer, db.ForeignKey('checklists_seguridad.id'), nullable=False)
    descripcion = db.Column(db.String(300), nullable=False)
    conforme = db.Column(db.Boolean)
    observacion = db.Column(db.Text)
    criticidad = db.Column(db.String(20), default='media')  # baja, media, alta, critica
    
    # Relaciones
    checklist = db.relationship('ChecklistSeguridad')

class IncidenteSeguridad(db.Model):
    __tablename__ = 'incidentes_seguridad'
    
    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    fecha_incidente = db.Column(db.DateTime, nullable=False)
    tipo_incidente = db.Column(db.String(50), nullable=False)  # accidente, casi_accidente, condicion_insegura
    gravedad = db.Column(db.String(20), nullable=False)  # leve, moderado, grave, muy_grave
    descripcion = db.Column(db.Text, nullable=False)
    ubicacion_exacta = db.Column(db.String(200))
    persona_afectada = db.Column(db.String(100))
    testigos = db.Column(db.Text)
    primeros_auxilios = db.Column(db.Boolean, default=False)
    atencion_medica = db.Column(db.Boolean, default=False)
    dias_perdidos = db.Column(db.Integer, default=0)
    causa_raiz = db.Column(db.Text)
    acciones_inmediatas = db.Column(db.Text)
    acciones_preventivas = db.Column(db.Text)
    responsable_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    estado = db.Column(db.String(20), default='abierto')  # abierto, investigando, cerrado
    fecha_cierre = db.Column(db.DateTime)
    
    # Relaciones
    obra = db.relationship('Obra')
    responsable = db.relationship('Usuario')

class CertificacionPersonal(db.Model):
    __tablename__ = 'certificaciones_personal'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    tipo_certificacion = db.Column(db.String(100), nullable=False)
    entidad_emisora = db.Column(db.String(200), nullable=False)
    numero_certificado = db.Column(db.String(50))
    fecha_emision = db.Column(db.Date, nullable=False)
    fecha_vencimiento = db.Column(db.Date)
    archivo_certificado = db.Column(db.String(500))
    activo = db.Column(db.Boolean, default=True)
    
    # Relaciones
    usuario = db.relationship('Usuario')

class AuditoriaSeguridad(db.Model):
    __tablename__ = 'auditorias_seguridad'
    
    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    fecha_auditoria = db.Column(db.Date, nullable=False)
    auditor_externo = db.Column(db.String(200))
    tipo_auditoria = db.Column(db.String(50), nullable=False)  # interna, externa, oficial
    puntuacion_general = db.Column(db.Integer)  # 0-100
    hallazgos_criticos = db.Column(db.Integer, default=0)
    hallazgos_mayores = db.Column(db.Integer, default=0)
    hallazgos_menores = db.Column(db.Integer, default=0)
    informe_path = db.Column(db.String(500))
    plan_accion_path = db.Column(db.String(500))
    fecha_seguimiento = db.Column(db.Date)
    estado = db.Column(db.String(20), default='programada')  # programada, ejecutada, cerrada
    
    # Relaciones
    obra = db.relationship('Obra')

@seguridad_bp.route('/')
@login_required
def dashboard():
    """Dashboard principal de seguridad y cumplimiento"""
    # KPIs de seguridad
    incidentes_mes = IncidenteSeguridad.query.filter(
        IncidenteSeguridad.fecha_incidente >= datetime.now().replace(day=1)
    ).count()
    
    checklists_pendientes = ChecklistSeguridad.query.filter_by(estado='pendiente').count()
    
    certificaciones_vencen = CertificacionPersonal.query.filter(
        CertificacionPersonal.fecha_vencimiento <= date.today() + timedelta(days=30),
        CertificacionPersonal.activo == True
    ).count()
    
    obras_sin_inspeccion = obtener_obras_sin_inspeccion_reciente()
    
    # Estadísticas
    stats = calcular_estadisticas_seguridad()
    
    return render_template('seguridad/dashboard.html',
                         incidentes_mes=incidentes_mes,
                         checklists_pendientes=checklists_pendientes,
                         certificaciones_vencen=certificaciones_vencen,
                         obras_sin_inspeccion=len(obras_sin_inspeccion),
                         stats=stats)

@seguridad_bp.route('/protocolos')
@login_required
def protocolos():
    """Gestión de protocolos de seguridad"""
    protocolos = ProtocoloSeguridad.query.filter_by(activo=True).all()
    return render_template('seguridad/protocolos.html', protocolos=protocolos)

@seguridad_bp.route('/crear_protocolo')
@login_required
def crear_protocolo():
    """Formulario para crear nuevo protocolo"""
    if current_user.role not in ['admin', 'pm', 'tecnico']:
        flash('No tienes permisos para crear protocolos', 'danger')
        return redirect(url_for('seguridad.protocolos'))
    
    return render_template('seguridad/crear_protocolo.html')

@seguridad_bp.route('/crear_protocolo', methods=['POST'])
@login_required
def procesar_protocolo():
    """Procesa la creación de un nuevo protocolo"""
    try:
        protocolo = ProtocoloSeguridad(
            nombre=request.form.get('nombre'),
            descripcion=request.form.get('descripcion'),
            categoria=request.form.get('categoria'),
            obligatorio=request.form.get('obligatorio') == 'on',
            frecuencia_revision=safe_int(request.form.get('frecuencia_revision', 30), default=30),
            normativa_referencia=request.form.get('normativa_referencia')
        )
        
        db.session.add(protocolo)
        db.session.commit()
        
        flash('Protocolo creado correctamente', 'success')
        return redirect(url_for('seguridad.protocolos'))
    
    except Exception as e:
        db.session.rollback()
        flash(f'Error al crear protocolo: {str(e)}', 'danger')
        return redirect(url_for('seguridad.crear_protocolo'))

@seguridad_bp.route('/checklists')
@login_required
def checklists():
    """Lista de checklists de seguridad"""
    obra_id = request.args.get('obra_id', type=int)
    estado = request.args.get('estado')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = ChecklistSeguridad.query

    if obra_id:
        query = query.filter_by(obra_id=obra_id)
    if estado:
        query = query.filter_by(estado=estado)

    checklists = query.order_by(ChecklistSeguridad.fecha_inspeccion.desc()).paginate(page=page, per_page=per_page, error_out=False)
    obras = Obra.query.all()

    return render_template('seguridad/checklists.html', checklists=checklists, obras=obras)

@seguridad_bp.route('/nuevo_checklist')
@login_required
def nuevo_checklist():
    """Formulario para nuevo checklist"""
    obras = Obra.query.filter(Obra.estado.in_(['en_curso', 'planificacion'])).all()
    protocolos = ProtocoloSeguridad.query.filter_by(activo=True).all()
    return render_template('seguridad/nuevo_checklist.html', obras=obras, protocolos=protocolos)

@seguridad_bp.route('/ejecutar_checklist/<int:checklist_id>')
@login_required
def ejecutar_checklist(checklist_id):
    """Formulario para ejecutar checklist"""
    checklist = ChecklistSeguridad.query.get_or_404(checklist_id)
    items = generar_items_checklist(checklist.protocolo_id)
    return render_template('seguridad/ejecutar_checklist.html', checklist=checklist, items=items)

@seguridad_bp.route('/procesar_checklist/<int:checklist_id>', methods=['POST'])
@login_required
def procesar_checklist(checklist_id):
    """Procesa la ejecución de un checklist"""
    try:
        checklist = ChecklistSeguridad.query.get_or_404(checklist_id)
        
        # Procesar items
        items_conformes = 0
        total_items = 0
        
        for key, value in request.form.items():
            if key.startswith('item_'):
                item_id = key.replace('item_', '')
                conforme = value == 'conforme'
                observacion = request.form.get(f'obs_{item_id}', '')
                
                # Crear o actualizar item
                item = ItemChecklist(
                    checklist_id=checklist_id,
                    descripcion=request.form.get(f'desc_{item_id}'),
                    conforme=conforme,
                    observacion=observacion,
                    criticidad=request.form.get(f'crit_{item_id}', 'media')
                )
                db.session.add(item)
                
                if conforme:
                    items_conformes += 1
                total_items += 1
        
        # Calcular puntuación
        puntuacion = (items_conformes / total_items * 100) if total_items > 0 else 0
        
        # Actualizar checklist
        checklist.estado = 'completado' if puntuacion >= 80 else 'no_conforme'
        checklist.puntuacion = int(puntuacion)
        checklist.observaciones = request.form.get('observaciones_generales')
        checklist.acciones_correctivas = request.form.get('acciones_correctivas')
        checklist.fecha_completado = datetime.utcnow()
        
        db.session.commit()
        
        flash(f'Checklist completado. Puntuación: {puntuacion:.1f}%', 'success')
        return redirect(url_for('seguridad.checklists'))
    
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar checklist: {str(e)}', 'danger')
        return redirect(url_for('seguridad.ejecutar_checklist', checklist_id=checklist_id))

@seguridad_bp.route('/incidentes')
@login_required
def incidentes():
    """Lista de incidentes de seguridad"""
    obra_id = request.args.get('obra_id', type=int)
    gravedad = request.args.get('gravedad')
    estado = request.args.get('estado')
    
    query = IncidenteSeguridad.query
    
    if obra_id:
        query = query.filter_by(obra_id=obra_id)
    if gravedad:
        query = query.filter_by(gravedad=gravedad)
    if estado:
        query = query.filter_by(estado=estado)
    
    incidentes = query.order_by(IncidenteSeguridad.fecha_incidente.desc()).all()
    obras = Obra.query.all()
    
    return render_template('seguridad/incidentes.html', incidentes=incidentes, obras=obras)

@seguridad_bp.route('/reportar_incidente')
@login_required
def reportar_incidente():
    """Formulario para reportar incidente"""
    obras = Obra.query.filter(Obra.estado.in_(['en_curso'])).all()
    return render_template('seguridad/reportar_incidente.html', obras=obras)

@seguridad_bp.route('/reportar_incidente', methods=['POST'])
@login_required
def procesar_incidente():
    """Procesa el reporte de un incidente"""
    try:
        incidente = IncidenteSeguridad(
            obra_id=request.form.get('obra_id'),
            fecha_incidente=datetime.strptime(request.form.get('fecha_incidente'), '%Y-%m-%d %H:%M'),
            tipo_incidente=request.form.get('tipo_incidente'),
            gravedad=request.form.get('gravedad'),
            descripcion=request.form.get('descripcion'),
            ubicacion_exacta=request.form.get('ubicacion_exacta'),
            persona_afectada=request.form.get('persona_afectada'),
            testigos=request.form.get('testigos'),
            primeros_auxilios=request.form.get('primeros_auxilios') == 'on',
            atencion_medica=request.form.get('atencion_medica') == 'on',
            dias_perdidos=safe_int(request.form.get('dias_perdidos', 0)),
            acciones_inmediatas=request.form.get('acciones_inmediatas'),
            responsable_id=current_user.id
        )
        
        db.session.add(incidente)
        db.session.commit()
        
        flash('Incidente reportado correctamente', 'success')
        
        # Enviar notificaciones si es grave
        if incidente.gravedad in ['grave', 'muy_grave']:
            enviar_notificacion_incidente_grave(incidente)
        
        return redirect(url_for('seguridad.incidentes'))
    
    except Exception as e:
        db.session.rollback()
        flash(f'Error al reportar incidente: {str(e)}', 'danger')
        return redirect(url_for('seguridad.reportar_incidente'))

@seguridad_bp.route('/certificaciones')
@login_required
def certificaciones():
    """Gestión de certificaciones del personal"""
    usuario_id = request.args.get('usuario_id', type=int)
    
    query = CertificacionPersonal.query.filter_by(activo=True)
    
    if usuario_id:
        query = query.filter_by(usuario_id=usuario_id)
    
    certificaciones = query.order_by(CertificacionPersonal.fecha_vencimiento.asc()).all()
    usuarios = Usuario.query.filter(
        Usuario.activo == True,
        Usuario.is_super_admin.is_(False)
    ).all()
    
    return render_template('seguridad/certificaciones.html', certificaciones=certificaciones, usuarios=usuarios)

@seguridad_bp.route('/auditorias')
@login_required
def auditorias():
    """Gestión de auditorías de seguridad"""
    auditorias = AuditoriaSeguridad.query.order_by(AuditoriaSeguridad.fecha_auditoria.desc()).all()
    return render_template('seguridad/auditorias.html', auditorias=auditorias)

@seguridad_bp.route('/reportes_seguridad')
@login_required
def reportes():
    """Reportes y análisis de seguridad"""
    reporte = generar_reporte_seguridad()
    return render_template('seguridad/reportes.html', reporte=reporte)

@seguridad_bp.route('/indicadores_seguridad')
@login_required
def indicadores():
    """Indicadores clave de seguridad"""
    kpis = calcular_kpis_seguridad()
    return render_template('seguridad/indicadores.html', kpis=kpis)

# Funciones auxiliares

def obtener_obras_sin_inspeccion_reciente():
    """Obtiene obras que no han tenido inspección en los últimos 15 días"""
    fecha_limite = date.today() - timedelta(days=15)
    
    obras_con_inspeccion = db.session.query(ChecklistSeguridad.obra_id).filter(
        ChecklistSeguridad.fecha_inspeccion >= fecha_limite
    ).subquery()
    
    obras_sin_inspeccion = Obra.query.filter(
        Obra.estado == 'en_curso',
        ~Obra.id.in_(obras_con_inspeccion)
    ).all()
    
    return obras_sin_inspeccion

def calcular_estadisticas_seguridad():
    """Calcula estadísticas generales de seguridad"""
    return {
        'total_incidentes': IncidenteSeguridad.query.count(),
        'incidentes_mes': IncidenteSeguridad.query.filter(
            IncidenteSeguridad.fecha_incidente >= datetime.now().replace(day=1)
        ).count(),
        'dias_sin_accidentes': calcular_dias_sin_accidentes(),
        'indice_frecuencia': calcular_indice_frecuencia(),
        'indice_gravedad': calcular_indice_gravedad()
    }

def generar_items_checklist(protocolo_id):
    """Genera items estándar para un protocolo"""
    items_estandar = {
        'epp': [
            {'descripcion': 'Personal usa casco de seguridad', 'criticidad': 'critica'},
            {'descripcion': 'Personal usa calzado de seguridad', 'criticidad': 'critica'},
            {'descripcion': 'Personal usa chaleco reflectivo', 'criticidad': 'alta'},
            {'descripcion': 'Personal usa protección ocular cuando corresponde', 'criticidad': 'alta'},
            {'descripcion': 'Personal usa guantes apropiados', 'criticidad': 'media'}
        ],
        'procedimiento': [
            {'descripcion': 'Se siguió el procedimiento establecido', 'criticidad': 'alta'},
            {'descripcion': 'Personal capacitado ejecuta la tarea', 'criticidad': 'critica'},
            {'descripcion': 'Herramientas en buen estado', 'criticidad': 'alta'},
            {'descripcion': 'Área de trabajo ordenada y limpia', 'criticidad': 'media'}
        ],
        'emergencia': [
            {'descripcion': 'Extintores en su lugar y vigentes', 'criticidad': 'critica'},
            {'descripcion': 'Salidas de emergencia señalizadas y despejadas', 'criticidad': 'critica'},
            {'descripcion': 'Botiquín completo y actualizado', 'criticidad': 'alta'},
            {'descripcion': 'Personal conoce procedimientos de emergencia', 'criticidad': 'alta'}
        ]
    }
    
    protocolo = ProtocoloSeguridad.query.get(protocolo_id)
    return items_estandar.get(protocolo.categoria, [])

def enviar_notificacion_incidente_grave(incidente):
    """Envía notificaciones para incidentes graves"""
    # Aquí implementarías el sistema de notificaciones
    # Por ejemplo, email, SMS, etc.
    pass

def calcular_dias_sin_accidentes():
    """Calcula días sin accidentes graves"""
    ultimo_accidente = IncidenteSeguridad.query.filter(
        IncidenteSeguridad.tipo_incidente == 'accidente',
        IncidenteSeguridad.gravedad.in_(['grave', 'muy_grave'])
    ).order_by(IncidenteSeguridad.fecha_incidente.desc()).first()
    
    if ultimo_accidente:
        return (date.today() - ultimo_accidente.fecha_incidente.date()).days
    else:
        return 365  # Default si no hay registros

def calcular_indice_frecuencia():
    """Calcula índice de frecuencia de accidentes"""
    # IF = (Número de accidentes * 1,000,000) / Horas trabajadas
    # Simplificado para el ejemplo
    accidentes_año = IncidenteSeguridad.query.filter(
        IncidenteSeguridad.fecha_incidente >= datetime.now().replace(month=1, day=1),
        IncidenteSeguridad.tipo_incidente == 'accidente'
    ).count()
    
    # Estimar horas trabajadas (simplificado)
    horas_estimadas = 2000 * Usuario.query.filter(Usuario.activo == True, Usuario.is_super_admin.is_(False)).count()
    
    return (accidentes_año * 1000000) / horas_estimadas if horas_estimadas > 0 else 0

def calcular_indice_gravedad():
    """Calcula índice de gravedad de accidentes"""
    # IG = (Días perdidos * 1,000,000) / Horas trabajadas
    dias_perdidos = db.session.query(db.func.sum(IncidenteSeguridad.dias_perdidos)).filter(
        IncidenteSeguridad.fecha_incidente >= datetime.now().replace(month=1, day=1)
    ).scalar() or 0
    
    horas_estimadas = 2000 * Usuario.query.filter(Usuario.activo == True, Usuario.is_super_admin.is_(False)).count()
    
    return (dias_perdidos * 1000000) / horas_estimadas if horas_estimadas > 0 else 0

def calcular_kpis_seguridad():
    """Calcula KPIs principales de seguridad"""
    return {
        'tasa_accidentalidad': calcular_tasa_accidentalidad(),
        'cumplimiento_protocolos': calcular_cumplimiento_protocolos(),
        'capacitaciones_vencidas': calcular_capacitaciones_vencidas(),
        'obras_conformes': calcular_obras_conformes()
    }

def calcular_tasa_accidentalidad():
    """Calcula tasa de accidentalidad"""
    accidentes_mes = IncidenteSeguridad.query.filter(
        IncidenteSeguridad.fecha_incidente >= datetime.now().replace(day=1),
        IncidenteSeguridad.tipo_incidente == 'accidente'
    ).count()
    
    trabajadores_activos = Usuario.query.filter(Usuario.activo == True, Usuario.is_super_admin.is_(False)).count()
    
    return (accidentes_mes / trabajadores_activos * 100) if trabajadores_activos > 0 else 0

def calcular_cumplimiento_protocolos():
    """Calcula porcentaje de cumplimiento de protocolos"""
    checklists_completados = ChecklistSeguridad.query.filter_by(estado='completado').count()
    total_checklists = ChecklistSeguridad.query.count()
    
    return (checklists_completados / total_checklists * 100) if total_checklists > 0 else 0

def calcular_capacitaciones_vencidas():
    """Calcula porcentaje de capacitaciones vencidas"""
    certificaciones_vencidas = CertificacionPersonal.query.filter(
        CertificacionPersonal.fecha_vencimiento < date.today(),
        CertificacionPersonal.activo == True
    ).count()
    
    total_certificaciones = CertificacionPersonal.query.filter_by(activo=True).count()
    
    return (certificaciones_vencidas / total_certificaciones * 100) if total_certificaciones > 0 else 0

def calcular_obras_conformes():
    """Calcula porcentaje de obras conformes en seguridad"""
    obras_conformes = db.session.query(ChecklistSeguridad.obra_id).filter(
        ChecklistSeguridad.puntuacion >= 80
    ).distinct().count()
    
    total_obras = Obra.query.filter_by(estado='en_curso').count()
    
    return (obras_conformes / total_obras * 100) if total_obras > 0 else 0

def generar_reporte_seguridad():
    """Genera reporte completo de seguridad"""
    return {
        'periodo': f"{datetime.now().strftime('%B %Y')}",
        'incidentes_por_tipo': obtener_incidentes_por_tipo(),
        'incidentes_por_obra': obtener_incidentes_por_obra(),
        'evolución_indices': obtener_evolucion_indices(),
        'recomendaciones': generar_recomendaciones_seguridad()
    }

def obtener_incidentes_por_tipo():
    """Obtiene estadísticas de incidentes por tipo"""
    return db.session.query(
        IncidenteSeguridad.tipo_incidente,
        db.func.count(IncidenteSeguridad.id)
    ).group_by(IncidenteSeguridad.tipo_incidente).all()

def obtener_incidentes_por_obra():
    """Obtiene estadísticas de incidentes por obra"""
    return db.session.query(
        Obra.nombre,
        db.func.count(IncidenteSeguridad.id)
    ).join(IncidenteSeguridad).group_by(Obra.id).all()

def obtener_evolucion_indices():
    """Obtiene evolución de índices de seguridad"""
    # Implementar lógica para obtener evolución temporal
    return []

def generar_recomendaciones_seguridad():
    """Genera recomendaciones automáticas de seguridad"""
    recomendaciones = []
    
    # Verificar obras sin inspección
    obras_sin_inspeccion = obtener_obras_sin_inspeccion_reciente()
    if obras_sin_inspeccion:
        recomendaciones.append(
            f"Programar inspecciones para {len(obras_sin_inspeccion)} obras sin revisión reciente"
        )
    
    # Verificar certificaciones próximas a vencer
    cert_por_vencer = CertificacionPersonal.query.filter(
        CertificacionPersonal.fecha_vencimiento <= date.today() + timedelta(days=30),
        CertificacionPersonal.activo == True
    ).count()
    
    if cert_por_vencer > 0:
        recomendaciones.append(
            f"Renovar {cert_por_vencer} certificaciones que vencen próximamente"
        )
    
    # Verificar incidentes recurrentes
    if calcular_tasa_accidentalidad() > 5:
        recomendaciones.append("Revisar protocolos de seguridad - tasa de accidentalidad elevada")
    
    return recomendaciones