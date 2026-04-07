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
from extensions import db
from models import *
from utils import *
from services.memberships import get_current_org_id

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
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True, index=True)

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
    
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True, index=True)

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
    
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True, index=True)

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
    
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True, index=True)

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
    
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True, index=True)

    # Relaciones
    obra = db.relationship('Obra')

@seguridad_bp.route('/')
@login_required
def dashboard():
    """Dashboard principal de seguridad y cumplimiento"""
    org_id = get_current_org_id()

    # KPIs de seguridad
    incidentes_mes = IncidenteSeguridad.query.filter(
        IncidenteSeguridad.organizacion_id == org_id,
        IncidenteSeguridad.fecha_incidente >= datetime.now().replace(day=1)
    ).count()

    checklists_pendientes = ChecklistSeguridad.query.filter_by(
        organizacion_id=org_id, estado='pendiente'
    ).count()

    certificaciones_vencen = CertificacionPersonal.query.filter(
        CertificacionPersonal.organizacion_id == org_id,
        CertificacionPersonal.fecha_vencimiento <= date.today() + timedelta(days=30),
        CertificacionPersonal.activo == True
    ).count()

    obras_sin_inspeccion = obtener_obras_sin_inspeccion_reciente(org_id)

    # Estadísticas
    stats = calcular_estadisticas_seguridad(org_id)

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
    org_id = get_current_org_id()
    protocolos = ProtocoloSeguridad.query.filter_by(activo=True, organizacion_id=org_id).all()
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
        org_id = get_current_org_id()
        protocolo = ProtocoloSeguridad(
            nombre=request.form.get('nombre'),
            descripcion=request.form.get('descripcion'),
            categoria=request.form.get('categoria'),
            obligatorio=request.form.get('obligatorio') == 'on',
            frecuencia_revision=safe_int(request.form.get('frecuencia_revision', 30), default=30),
            normativa_referencia=request.form.get('normativa_referencia'),
            organizacion_id=org_id
        )
        
        db.session.add(protocolo)
        db.session.commit()
        
        flash('Protocolo creado correctamente', 'success')
        return redirect(url_for('seguridad.protocolos'))
    
    except Exception as e:
        db.session.rollback()
        flash('Error al crear protocolo. Intente nuevamente.', 'danger')
        return redirect(url_for('seguridad.crear_protocolo'))

@seguridad_bp.route('/checklists')
@login_required
def checklists():
    """Lista de checklists de seguridad"""
    org_id = get_current_org_id()
    obra_id = request.args.get('obra_id', type=int)
    estado = request.args.get('estado')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = ChecklistSeguridad.query.filter_by(organizacion_id=org_id)

    if obra_id:
        query = query.filter_by(obra_id=obra_id)
    if estado:
        query = query.filter_by(estado=estado)

    checklists = query.order_by(ChecklistSeguridad.fecha_inspeccion.desc()).paginate(page=page, per_page=per_page, error_out=False)
    obras = Obra.query.filter_by(organizacion_id=org_id).all()

    return render_template('seguridad/checklists.html', checklists=checklists, obras=obras)

@seguridad_bp.route('/nuevo_checklist')
@login_required
def nuevo_checklist():
    """Formulario para nuevo checklist"""
    org_id = get_current_org_id()
    obras = Obra.query.filter(Obra.organizacion_id == org_id, Obra.estado.in_(['en_curso', 'planificacion'])).all()
    protocolos = ProtocoloSeguridad.query.filter_by(activo=True, organizacion_id=org_id).all()
    from datetime import date
    return render_template('seguridad/nuevo_checklist.html', obras=obras, protocolos=protocolos, today=date.today().isoformat())

@seguridad_bp.route('/nuevo_checklist', methods=['POST'])
@login_required
def procesar_nuevo_checklist():
    """Procesa la creación de un nuevo checklist"""
    try:
        from datetime import datetime

        fecha_inspeccion_str = request.form.get('fecha_inspeccion')
        fecha_inspeccion = datetime.strptime(fecha_inspeccion_str, '%Y-%m-%d').date() if fecha_inspeccion_str else date.today()

        org_id = get_current_org_id()
        checklist = ChecklistSeguridad(
            obra_id=safe_int(request.form.get('obra_id')),
            protocolo_id=safe_int(request.form.get('protocolo_id')),
            fecha_inspeccion=fecha_inspeccion,
            inspector_id=safe_int(request.form.get('inspector_id', current_user.id)),
            estado='pendiente',
            organizacion_id=org_id
        )

        db.session.add(checklist)
        db.session.commit()

        flash(f'Checklist creado correctamente. Ahora puede ejecutarlo en obra.', 'success')
        return redirect(url_for('seguridad.ejecutar_checklist', checklist_id=checklist.id))

    except Exception as e:
        db.session.rollback()
        flash('Error al crear checklist. Intente nuevamente.', 'danger')
        return redirect(url_for('seguridad.nuevo_checklist'))

@seguridad_bp.route('/ejecutar_checklist/<int:checklist_id>')
@login_required
def ejecutar_checklist(checklist_id):
    """Formulario para ejecutar checklist"""
    org_id = get_current_org_id()
    checklist = ChecklistSeguridad.query.filter_by(id=checklist_id, organizacion_id=org_id).first_or_404()
    items = generar_items_checklist(checklist.protocolo_id)
    return render_template('seguridad/ejecutar_checklist.html', checklist=checklist, items=items)

@seguridad_bp.route('/procesar_checklist/<int:checklist_id>', methods=['POST'])
@login_required
def procesar_checklist(checklist_id):
    """Procesa la ejecución de un checklist"""
    try:
        org_id = get_current_org_id()
        checklist = ChecklistSeguridad.query.filter_by(id=checklist_id, organizacion_id=org_id).first_or_404()

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
        flash('Error al procesar checklist. Intente nuevamente.', 'danger')
        return redirect(url_for('seguridad.ejecutar_checklist', checklist_id=checklist_id))

@seguridad_bp.route('/incidentes')
@login_required
def incidentes():
    """Lista de incidentes de seguridad"""
    org_id = get_current_org_id()
    obra_id = request.args.get('obra_id', type=int)
    gravedad = request.args.get('gravedad')
    estado = request.args.get('estado')

    query = IncidenteSeguridad.query.filter_by(organizacion_id=org_id)

    if obra_id:
        query = query.filter_by(obra_id=obra_id)
    if gravedad:
        query = query.filter_by(gravedad=gravedad)
    if estado:
        query = query.filter_by(estado=estado)

    incidentes = query.order_by(IncidenteSeguridad.fecha_incidente.desc()).all()
    obras = Obra.query.filter_by(organizacion_id=org_id).all()

    return render_template('seguridad/incidentes.html', incidentes=incidentes, obras=obras)

@seguridad_bp.route('/reportar_incidente')
@login_required
def reportar_incidente():
    """Formulario para reportar incidente"""
    org_id = get_current_org_id()
    obras = Obra.query.filter(Obra.organizacion_id == org_id, Obra.estado.in_(['en_curso'])).all()
    return render_template('seguridad/reportar_incidente.html', obras=obras)

@seguridad_bp.route('/reportar_incidente', methods=['POST'])
@login_required
def procesar_incidente():
    """Procesa el reporte de un incidente"""
    try:
        org_id = get_current_org_id()
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
            responsable_id=current_user.id,
            organizacion_id=org_id
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
        flash('Error al reportar incidente. Intente nuevamente.', 'danger')
        return redirect(url_for('seguridad.reportar_incidente'))

@seguridad_bp.route('/certificaciones')
@login_required
def certificaciones():
    """Gestión de certificaciones del personal"""
    org_id = get_current_org_id()
    usuario_id = request.args.get('usuario_id', type=int)
    obra_id = request.args.get('obra_id', type=int)

    query = CertificacionPersonal.query.filter_by(activo=True, organizacion_id=org_id)

    if usuario_id:
        query = query.filter_by(usuario_id=usuario_id)

    certificaciones = query.order_by(CertificacionPersonal.fecha_vencimiento.asc()).all()
    usuarios = Usuario.query.filter(
        Usuario.activo == True,
        Usuario.is_super_admin.is_(False)
    ).all()
    obras = Obra.query.filter(Obra.organizacion_id == org_id, Obra.estado.in_(['en_curso', 'planificacion'])).all()

    return render_template('seguridad/certificaciones.html',
                         certificaciones=certificaciones,
                         usuarios=usuarios,
                         obras=obras,
                         today=date.today())

@seguridad_bp.route('/agregar_certificacion')
@login_required
def agregar_certificacion():
    """Formulario para agregar nueva certificación de personal"""
    if current_user.role not in ['admin', 'pm', 'tecnico']:
        flash('No tienes permisos para agregar certificaciones', 'danger')
        return redirect(url_for('seguridad.certificaciones'))

    org_id = get_current_org_id()
    obra_id = request.args.get('obra_id', type=int)

    # Obtener obras activas
    obras = Obra.query.filter(Obra.organizacion_id == org_id, Obra.estado.in_(['en_curso', 'planificacion'])).all()

    # Si se especifica una obra, obtener operarios asignados a esa obra
    usuarios = []
    if obra_id:
        # Buscar operarios asignados a la obra
        from models.projects import AsignacionObra
        asignaciones = AsignacionObra.query.filter_by(obra_id=obra_id, activo=True).all()
        usuario_ids = [a.usuario_id for a in asignaciones]
        usuarios = Usuario.query.filter(
            Usuario.id.in_(usuario_ids),
            Usuario.activo == True
        ).all()
    else:
        # Todos los usuarios activos que no son super_admin
        usuarios = Usuario.query.filter(
            Usuario.activo == True,
            Usuario.is_super_admin.is_(False)
        ).all()

    return render_template('seguridad/agregar_certificacion.html',
                         obras=obras,
                         usuarios=usuarios,
                         obra_id=obra_id,
                         today=date.today().isoformat())

@seguridad_bp.route('/agregar_certificacion', methods=['POST'])
@login_required
def procesar_agregar_certificacion():
    """Procesa la creación de una nueva certificación de personal"""
    if current_user.role not in ['admin', 'pm', 'tecnico']:
        flash('No tienes permisos para agregar certificaciones', 'danger')
        return redirect(url_for('seguridad.certificaciones'))

    try:
        # Parsear fechas
        fecha_emision_str = request.form.get('fecha_emision')
        fecha_vencimiento_str = request.form.get('fecha_vencimiento')

        fecha_emision = datetime.strptime(fecha_emision_str, '%Y-%m-%d').date() if fecha_emision_str else date.today()
        fecha_vencimiento = datetime.strptime(fecha_vencimiento_str, '%Y-%m-%d').date() if fecha_vencimiento_str else None

        org_id = get_current_org_id()
        certificacion = CertificacionPersonal(
            usuario_id=safe_int(request.form.get('usuario_id')),
            tipo_certificacion=request.form.get('tipo_certificacion'),
            entidad_emisora=request.form.get('entidad_emisora'),
            numero_certificado=request.form.get('numero_certificado'),
            fecha_emision=fecha_emision,
            fecha_vencimiento=fecha_vencimiento,
            archivo_certificado=request.form.get('archivo_certificado'),
            activo=True,
            organizacion_id=org_id
        )

        db.session.add(certificacion)
        db.session.commit()

        flash('Certificación agregada correctamente', 'success')
        return redirect(url_for('seguridad.certificaciones'))

    except Exception as e:
        db.session.rollback()
        flash('Error al agregar certificación. Intente nuevamente.', 'danger')
        return redirect(url_for('seguridad.agregar_certificacion'))

@seguridad_bp.route('/api/operarios_obra/<int:obra_id>')
@login_required
def api_operarios_obra(obra_id):
    """API para obtener operarios asignados a una obra"""
    try:
        org_id = get_current_org_id()
        # Verificar que la obra pertenece a la organización
        obra = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first_or_404()
        from models.projects import AsignacionObra
        asignaciones = AsignacionObra.query.filter_by(obra_id=obra_id, activo=True).all()
        usuario_ids = [a.usuario_id for a in asignaciones]
        usuarios = Usuario.query.filter(
            Usuario.id.in_(usuario_ids),
            Usuario.activo == True
        ).all()

        return jsonify([{
            'id': u.id,
            'nombre': u.nombre,
            'email': u.email,
            'role': u.role
        } for u in usuarios])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@seguridad_bp.route('/auditorias')
@login_required
def auditorias():
    """Gestión de auditorías de seguridad"""
    org_id = get_current_org_id()
    auditorias = AuditoriaSeguridad.query.filter_by(organizacion_id=org_id).order_by(AuditoriaSeguridad.fecha_auditoria.desc()).all()
    return render_template('seguridad/auditorias.html', auditorias=auditorias)

@seguridad_bp.route('/reportes_seguridad')
@login_required
def reportes():
    """Reportes y análisis de seguridad"""
    org_id = get_current_org_id()
    reporte = generar_reporte_seguridad(org_id)
    return render_template('seguridad/reportes.html', reporte=reporte)

@seguridad_bp.route('/indicadores_seguridad')
@login_required
def indicadores():
    """Indicadores clave de seguridad"""
    org_id = get_current_org_id()
    kpis = calcular_kpis_seguridad(org_id)
    return render_template('seguridad/indicadores.html', kpis=kpis)

# Funciones auxiliares

def obtener_obras_sin_inspeccion_reciente(org_id=None):
    """Obtiene obras que no han tenido inspección en los últimos 15 días"""
    if org_id is None:
        org_id = get_current_org_id()
    fecha_limite = date.today() - timedelta(days=15)

    obras_con_inspeccion = db.session.query(ChecklistSeguridad.obra_id).filter(
        ChecklistSeguridad.organizacion_id == org_id,
        ChecklistSeguridad.fecha_inspeccion >= fecha_limite
    ).subquery()

    obras_sin_inspeccion = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.estado == 'en_curso',
        Obra.deleted_at.is_(None),
        ~Obra.id.in_(obras_con_inspeccion)
    ).all()

    return obras_sin_inspeccion

def calcular_estadisticas_seguridad(org_id=None):
    """Calcula estadísticas generales de seguridad"""
    if org_id is None:
        org_id = get_current_org_id()
    return {
        'total_incidentes': IncidenteSeguridad.query.filter_by(organizacion_id=org_id).count(),
        'incidentes_mes': IncidenteSeguridad.query.filter(
            IncidenteSeguridad.organizacion_id == org_id,
            IncidenteSeguridad.fecha_incidente >= datetime.now().replace(day=1)
        ).count(),
        'dias_sin_accidentes': calcular_dias_sin_accidentes(org_id),
        'indice_frecuencia': calcular_indice_frecuencia(org_id),
        'indice_gravedad': calcular_indice_gravedad(org_id)
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
    
    org_id = get_current_org_id()
    protocolo = ProtocoloSeguridad.query.filter_by(id=protocolo_id, organizacion_id=org_id).first()
    if not protocolo:
        return []
    return items_estandar.get(protocolo.categoria, [])

def enviar_notificacion_incidente_grave(incidente):
    """Envía notificaciones para incidentes graves"""
    # Aquí implementarías el sistema de notificaciones
    # Por ejemplo, email, SMS, etc.
    pass

def calcular_dias_sin_accidentes(org_id=None):
    """Calcula días sin accidentes graves"""
    if org_id is None:
        org_id = get_current_org_id()
    ultimo_accidente = IncidenteSeguridad.query.filter(
        IncidenteSeguridad.organizacion_id == org_id,
        IncidenteSeguridad.tipo_incidente == 'accidente',
        IncidenteSeguridad.gravedad.in_(['grave', 'muy_grave'])
    ).order_by(IncidenteSeguridad.fecha_incidente.desc()).first()

    if ultimo_accidente:
        return (date.today() - ultimo_accidente.fecha_incidente.date()).days
    else:
        return 365  # Default si no hay registros

def calcular_indice_frecuencia(org_id=None):
    """Calcula índice de frecuencia de accidentes"""
    if org_id is None:
        org_id = get_current_org_id()
    # IF = (Número de accidentes * 1,000,000) / Horas trabajadas
    # Simplificado para el ejemplo
    accidentes_año = IncidenteSeguridad.query.filter(
        IncidenteSeguridad.organizacion_id == org_id,
        IncidenteSeguridad.fecha_incidente >= datetime.now().replace(month=1, day=1),
        IncidenteSeguridad.tipo_incidente == 'accidente'
    ).count()

    # Estimar horas trabajadas (simplificado)
    horas_estimadas = 2000 * Usuario.query.filter(Usuario.activo == True, Usuario.is_super_admin.is_(False)).count()

    return (accidentes_año * 1000000) / horas_estimadas if horas_estimadas > 0 else 0

def calcular_indice_gravedad(org_id=None):
    """Calcula índice de gravedad de accidentes"""
    if org_id is None:
        org_id = get_current_org_id()
    # IG = (Días perdidos * 1,000,000) / Horas trabajadas
    dias_perdidos = db.session.query(db.func.sum(IncidenteSeguridad.dias_perdidos)).filter(
        IncidenteSeguridad.organizacion_id == org_id,
        IncidenteSeguridad.fecha_incidente >= datetime.now().replace(month=1, day=1)
    ).scalar() or 0

    horas_estimadas = 2000 * Usuario.query.filter(Usuario.activo == True, Usuario.is_super_admin.is_(False)).count()

    return (dias_perdidos * 1000000) / horas_estimadas if horas_estimadas > 0 else 0

def calcular_kpis_seguridad(org_id=None):
    """Calcula KPIs principales de seguridad"""
    if org_id is None:
        org_id = get_current_org_id()
    return {
        'tasa_accidentalidad': calcular_tasa_accidentalidad(org_id),
        'cumplimiento_protocolos': calcular_cumplimiento_protocolos(org_id),
        'capacitaciones_vencidas': calcular_capacitaciones_vencidas(org_id),
        'obras_conformes': calcular_obras_conformes(org_id)
    }

def calcular_tasa_accidentalidad(org_id=None):
    """Calcula tasa de accidentalidad"""
    if org_id is None:
        org_id = get_current_org_id()
    accidentes_mes = IncidenteSeguridad.query.filter(
        IncidenteSeguridad.organizacion_id == org_id,
        IncidenteSeguridad.fecha_incidente >= datetime.now().replace(day=1),
        IncidenteSeguridad.tipo_incidente == 'accidente'
    ).count()

    trabajadores_activos = Usuario.query.filter(Usuario.activo == True, Usuario.is_super_admin.is_(False)).count()

    return (accidentes_mes / trabajadores_activos * 100) if trabajadores_activos > 0 else 0

def calcular_cumplimiento_protocolos(org_id=None):
    """Calcula porcentaje de cumplimiento de protocolos"""
    if org_id is None:
        org_id = get_current_org_id()
    checklists_completados = ChecklistSeguridad.query.filter_by(organizacion_id=org_id, estado='completado').count()
    total_checklists = ChecklistSeguridad.query.filter_by(organizacion_id=org_id).count()

    return (checklists_completados / total_checklists * 100) if total_checklists > 0 else 0

def calcular_capacitaciones_vencidas(org_id=None):
    """Calcula porcentaje de capacitaciones vencidas"""
    if org_id is None:
        org_id = get_current_org_id()
    certificaciones_vencidas = CertificacionPersonal.query.filter(
        CertificacionPersonal.organizacion_id == org_id,
        CertificacionPersonal.fecha_vencimiento < date.today(),
        CertificacionPersonal.activo == True
    ).count()

    total_certificaciones = CertificacionPersonal.query.filter_by(activo=True, organizacion_id=org_id).count()

    return (certificaciones_vencidas / total_certificaciones * 100) if total_certificaciones > 0 else 0

def calcular_obras_conformes(org_id=None):
    """Calcula porcentaje de obras conformes en seguridad"""
    if org_id is None:
        org_id = get_current_org_id()
    obras_conformes = db.session.query(ChecklistSeguridad.obra_id).filter(
        ChecklistSeguridad.organizacion_id == org_id,
        ChecklistSeguridad.puntuacion >= 80
    ).distinct().count()

    total_obras = Obra.query.filter_by(organizacion_id=org_id, estado='en_curso').count()

    return (obras_conformes / total_obras * 100) if total_obras > 0 else 0

def generar_reporte_seguridad(org_id=None):
    """Genera reporte completo de seguridad"""
    if org_id is None:
        org_id = get_current_org_id()
    return {
        'periodo': f"{datetime.now().strftime('%B %Y')}",
        'incidentes_por_tipo': obtener_incidentes_por_tipo(org_id),
        'incidentes_por_obra': obtener_incidentes_por_obra(org_id),
        'evolución_indices': obtener_evolucion_indices(),
        'recomendaciones': generar_recomendaciones_seguridad(org_id)
    }

def obtener_incidentes_por_tipo(org_id=None):
    """Obtiene estadísticas de incidentes por tipo"""
    if org_id is None:
        org_id = get_current_org_id()
    return db.session.query(
        IncidenteSeguridad.tipo_incidente,
        db.func.count(IncidenteSeguridad.id)
    ).filter(
        IncidenteSeguridad.organizacion_id == org_id
    ).group_by(IncidenteSeguridad.tipo_incidente).all()

def obtener_incidentes_por_obra(org_id=None):
    """Obtiene estadísticas de incidentes por obra"""
    if org_id is None:
        org_id = get_current_org_id()
    return db.session.query(
        Obra.nombre,
        db.func.count(IncidenteSeguridad.id)
    ).join(IncidenteSeguridad).filter(
        Obra.organizacion_id == org_id
    ).group_by(Obra.id).all()

def obtener_evolucion_indices():
    """Obtiene evolución de índices de seguridad"""
    # Implementar lógica para obtener evolución temporal
    return []

def generar_recomendaciones_seguridad(org_id=None):
    """Genera recomendaciones automáticas de seguridad"""
    if org_id is None:
        org_id = get_current_org_id()
    recomendaciones = []

    # Verificar obras sin inspección
    obras_sin_inspeccion = obtener_obras_sin_inspeccion_reciente(org_id)
    if obras_sin_inspeccion:
        recomendaciones.append(
            f"Programar inspecciones para {len(obras_sin_inspeccion)} obras sin revisión reciente"
        )

    # Verificar certificaciones próximas a vencer
    cert_por_vencer = CertificacionPersonal.query.filter(
        CertificacionPersonal.organizacion_id == org_id,
        CertificacionPersonal.fecha_vencimiento <= date.today() + timedelta(days=30),
        CertificacionPersonal.activo == True
    ).count()

    if cert_por_vencer > 0:
        recomendaciones.append(
            f"Renovar {cert_por_vencer} certificaciones que vencen próximamente"
        )

    # Verificar incidentes recurrentes
    if calcular_tasa_accidentalidad(org_id) > 5:
        recomendaciones.append("Revisar protocolos de seguridad - tasa de accidentalidad elevada")

    return recomendaciones