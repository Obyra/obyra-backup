from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app import db, _login_redirect
from models import (
    Equipment, EquipmentAssignment, EquipmentUsage, MaintenanceTask, 
    MaintenanceAttachment, Obra, Usuario
)
from datetime import date, datetime
import os
from werkzeug.utils import secure_filename

equipos_new_bp = Blueprint('equipos_new', __name__, url_prefix='/equipos')

# Configuración para archivos
UPLOAD_FOLDER = 'uploads/maintenance'
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def requires_role(*roles):
    """Decorator para verificar roles"""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return _login_redirect()
            if current_user.rol not in roles and not current_user.es_admin():
                flash('No tienes permisos para esta acción.', 'danger')
                return redirect(url_for('equipos_new.lista'))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator

def get_json_response(data, status=200, error=None):
    """Genera respuesta JSON estándar"""
    if request.accept_mimetypes['application/json'] >= request.accept_mimetypes['text/html'] or request.args.get('format') == 'json':
        if error:
            return jsonify({'error': error}), status
        return jsonify(data), status
    return None

@equipos_new_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('equipos'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    # Filtros
    project_id = request.args.get('proyecto')
    estado = request.args.get('estado')
    tipo = request.args.get('tipo')
    
    query = Equipment.query.filter_by(company_id=current_user.organizacion_id)
    
    if project_id:
        # Equipos asignados a proyecto específico
        query = query.join(EquipmentAssignment).filter(
            EquipmentAssignment.project_id == project_id,
            EquipmentAssignment.estado == 'asignado'
        )
    
    if estado:
        query = query.filter(Equipment.estado == estado)
    
    if tipo:
        query = query.filter(Equipment.tipo == tipo)
    
    equipos = query.order_by(Equipment.nombre).all()
    
    # Para JSON
    json_resp = get_json_response({
        'data': [
            {
                'id': eq.id,
                'nombre': eq.nombre,
                'tipo': eq.tipo,
                'estado': eq.estado,
                'current_assignment': eq.current_assignment.project.nombre if eq.current_assignment else None
            } for eq in equipos
        ]
    })
    if json_resp:
        return json_resp
    
    # Obtener datos para filtros
    projects = Obra.query.filter_by(organizacion_id=current_user.organizacion_id).all()
    tipos = db.session.query(Equipment.tipo).filter_by(company_id=current_user.organizacion_id).distinct().all()
    
    return render_template('equipos_new/lista.html', 
                         equipos=equipos, 
                         projects=projects,
                         tipos=[t[0] for t in tipos],
                         filtros={'proyecto': project_id, 'estado': estado, 'tipo': tipo})

@equipos_new_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
@requires_role('administrador', 'tecnico')
def nuevo():
    if request.method == 'POST':
        # Validaciones
        required_fields = ['nombre', 'tipo']
        for field in required_fields:
            if not request.form.get(field):
                error = f'El campo {field} es obligatorio.'
                json_resp = get_json_response(None, 400, error)
                if json_resp:
                    return json_resp
                flash(error, 'danger')
                return render_template('equipos_new/form.html')
        
        try:
            equipo = Equipment(
                company_id=current_user.organizacion_id,
                nombre=request.form.get('nombre'),
                tipo=request.form.get('tipo'),
                marca=request.form.get('marca'),
                modelo=request.form.get('modelo'),
                nro_serie=request.form.get('nro_serie'),
                costo_hora=float(request.form.get('costo_hora', 0))
            )
            
            db.session.add(equipo)
            db.session.commit()
            
            json_resp = get_json_response({'id': equipo.id, 'mensaje': 'Equipo creado exitosamente'})
            if json_resp:
                return json_resp
                
            flash('Equipo creado exitosamente.', 'success')
            return redirect(url_for('equipos_new.detalle', id=equipo.id))
            
        except Exception as e:
            db.session.rollback()
            error = 'Error al crear el equipo.'
            json_resp = get_json_response(None, 500, error)
            if json_resp:
                return json_resp
            flash(error, 'danger')
    
    return render_template('equipos_new/form.html', equipo=None)

@equipos_new_bp.route('/<int:id>')
@login_required
def detalle(id):
    equipo = Equipment.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    # Obtener asignaciones
    asignaciones = EquipmentAssignment.query.filter_by(equipment_id=id).order_by(EquipmentAssignment.fecha_desde.desc()).all()
    
    # Obtener usos recientes
    usos = EquipmentUsage.query.filter_by(equipment_id=id).order_by(EquipmentUsage.fecha.desc()).limit(10).all()
    
    # Obtener tareas de mantenimiento
    mantenimientos = MaintenanceTask.query.filter_by(equipment_id=id).order_by(MaintenanceTask.fecha_prog.desc()).all()
    
    json_resp = get_json_response({
        'equipo': {
            'id': equipo.id,
            'nombre': equipo.nombre,
            'tipo': equipo.tipo,
            'estado': equipo.estado,
            'current_assignment': equipo.current_assignment.project.nombre if equipo.current_assignment else None
        },
        'asignaciones': len(asignaciones),
        'usos_pendientes': len([u for u in usos if u.estado == 'pendiente']),
        'mantenimientos_abiertos': len([m for m in mantenimientos if m.status == 'abierta'])
    })
    if json_resp:
        return json_resp
    
    return render_template('equipos_new/detalle.html', 
                         equipo=equipo, 
                         asignaciones=asignaciones,
                         usos=usos,
                         mantenimientos=mantenimientos)

@equipos_new_bp.route('/<int:id>/asignar', methods=['POST'])
@login_required
@requires_role('administrador', 'tecnico')
def asignar(id):
    equipo = Equipment.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    project_id = request.form.get('project_id')
    fecha_desde = request.form.get('fecha_desde')
    
    if not all([project_id, fecha_desde]):
        error = 'Proyecto y fecha desde son obligatorios.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
        return redirect(url_for('equipos_new.detalle', id=id))
    
    # Verificar que el equipo esté disponible
    if not equipo.is_available:
        error = 'El equipo no está disponible para asignación.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
        return redirect(url_for('equipos_new.detalle', id=id))
    
    try:
        asignacion = EquipmentAssignment(
            equipment_id=id,
            project_id=project_id,
            fecha_desde=datetime.strptime(fecha_desde, '%Y-%m-%d').date()
        )
        
        db.session.add(asignacion)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Equipo asignado exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Equipo asignado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al asignar el equipo.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('equipos_new.detalle', id=id))

@equipos_new_bp.route('/<int:id>/liberar', methods=['POST'])
@login_required
@requires_role('administrador', 'tecnico')
def liberar(id):
    equipo = Equipment.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    asignacion = equipo.current_assignment
    if not asignacion:
        error = 'El equipo no tiene una asignación activa.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'warning')
        return redirect(url_for('equipos_new.detalle', id=id))
    
    try:
        asignacion.estado = 'liberado'
        asignacion.fecha_hasta = date.today()
        
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Equipo liberado exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Equipo liberado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al liberar el equipo.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('equipos_new.detalle', id=id))

@equipos_new_bp.route('/<int:id>/uso', methods=['POST'])
@login_required
def crear_uso(id):
    equipo = Equipment.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    # Validar que el equipo esté asignado
    if not equipo.current_assignment:
        error = 'El equipo debe estar asignado a un proyecto para registrar uso.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'warning')
        return redirect(url_for('equipos_new.detalle', id=id))
    
    try:
        uso = EquipmentUsage(
            equipment_id=id,
            project_id=equipo.current_assignment.project_id,
            fecha=datetime.strptime(request.form.get('fecha'), '%Y-%m-%d').date(),
            horas=float(request.form.get('horas')),
            avance_m2=float(request.form.get('avance_m2', 0)) or None,
            avance_m3=float(request.form.get('avance_m3', 0)) or None,
            notas=request.form.get('notas'),
            user_id=current_user.id
        )
        
        db.session.add(uso)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Parte de uso registrado exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Parte de uso registrado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al registrar el parte de uso.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('equipos_new.detalle', id=id))

@equipos_new_bp.route('/uso/<int:uso_id>/aprobar', methods=['POST'])
@login_required
@requires_role('administrador', 'tecnico')
def aprobar_uso(uso_id):
    uso = EquipmentUsage.query.get_or_404(uso_id)
    
    try:
        uso.estado = 'aprobado'
        uso.approved_by = current_user.id
        uso.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Parte de uso aprobado'})
        if json_resp:
            return json_resp
            
        flash('Parte de uso aprobado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al aprobar el parte de uso.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('equipos_new.detalle', id=uso.equipment_id))

@equipos_new_bp.route('/uso/<int:uso_id>/rechazar', methods=['POST'])
@login_required
@requires_role('administrador', 'tecnico')
def rechazar_uso(uso_id):
    uso = EquipmentUsage.query.get_or_404(uso_id)
    
    try:
        uso.estado = 'rechazado'
        uso.approved_by = current_user.id
        uso.approved_at = datetime.utcnow()
        
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Parte de uso rechazado'})
        if json_resp:
            return json_resp
            
        flash('Parte de uso rechazado.', 'info')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al rechazar el parte de uso.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('equipos_new.detalle', id=uso.equipment_id))

@equipos_new_bp.route('/<int:id>/mantenimiento/nuevo', methods=['POST'])
@login_required
@requires_role('administrador', 'tecnico')
def nuevo_mantenimiento(id):
    equipo = Equipment.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    try:
        mantenimiento = MaintenanceTask(
            equipment_id=id,
            tipo=request.form.get('tipo'),
            fecha_prog=datetime.strptime(request.form.get('fecha_prog'), '%Y-%m-%d').date(),
            notas=request.form.get('notas'),
            created_by=current_user.id
        )
        
        db.session.add(mantenimiento)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Tarea de mantenimiento creada'})
        if json_resp:
            return json_resp
            
        flash('Tarea de mantenimiento creada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al crear la tarea de mantenimiento.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('equipos_new.detalle', id=id))