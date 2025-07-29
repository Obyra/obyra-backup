from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from models import Usuario, AsignacionObra, Obra, RegistroTiempo

equipos_bp = Blueprint('equipos', __name__)

@equipos_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('equipos'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    rol_filtro = request.args.get('rol', '')
    buscar = request.args.get('buscar', '')
    activo = request.args.get('activo', '')
    
    query = Usuario.query
    
    if rol_filtro:
        query = query.filter(Usuario.rol == rol_filtro)
    
    if buscar:
        query = query.filter(
            db.or_(
                Usuario.nombre.contains(buscar),
                Usuario.apellido.contains(buscar),
                Usuario.email.contains(buscar)
            )
        )
    
    if activo:
        query = query.filter(Usuario.activo == (activo == 'true'))
    
    usuarios = query.order_by(Usuario.apellido, Usuario.nombre).all()
    
    # Obtener estadísticas de asignaciones para cada usuario
    for usuario in usuarios:
        usuario.obras_activas = usuario.obras_asignadas.join(Obra).filter(
            AsignacionObra.activo == True,
            Obra.estado.in_(['planificacion', 'en_curso'])
        ).count()
    
    return render_template('equipos/lista.html', 
                         usuarios=usuarios, 
                         rol_filtro=rol_filtro,
                         buscar=buscar,
                         activo=activo)

@equipos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    # Redirigir a registro de auth
    return redirect(url_for('auth.register'))

@equipos_bp.route('/<int:id>')
@login_required
def detalle(id):
    if not current_user.puede_acceder_modulo('equipos'):
        flash('No tienes permisos para ver detalles de equipos.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    usuario = Usuario.query.get_or_404(id)
    
    # Obtener asignaciones activas
    asignaciones_activas = usuario.obras_asignadas.filter_by(activo=True).all()
    
    # Obtener estadísticas de rendimiento
    total_horas = sum(reg.horas_trabajadas for reg in usuario.registros_tiempo)
    obras_completadas = usuario.obras_asignadas.join(Obra).filter(
        Obra.estado == 'finalizada'
    ).count()
    
    return render_template('equipos/detalle.html',
                         usuario=usuario,
                         asignaciones_activas=asignaciones_activas,
                         total_horas=total_horas,
                         obras_completadas=obras_completadas)

@equipos_bp.route('/<int:id>/editar', methods=['POST'])
@login_required
def editar(id):
    if current_user.rol != 'administrador':
        flash('No tienes permisos para editar usuarios.', 'danger')
        return redirect(url_for('equipos.detalle', id=id))
    
    usuario = Usuario.query.get_or_404(id)
    
    usuario.nombre = request.form.get('nombre', usuario.nombre)
    usuario.apellido = request.form.get('apellido', usuario.apellido)
    usuario.email = request.form.get('email', usuario.email)
    usuario.telefono = request.form.get('telefono', usuario.telefono)
    usuario.rol = request.form.get('rol', usuario.rol)
    
    # Validar email único
    email_existente = Usuario.query.filter(
        Usuario.email == usuario.email,
        Usuario.id != usuario.id
    ).first()
    
    if email_existente:
        flash('Ya existe otro usuario con ese email.', 'danger')
        return redirect(url_for('equipos.detalle', id=id))
    
    try:
        db.session.commit()
        flash('Usuario actualizado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al actualizar el usuario.', 'danger')
    
    return redirect(url_for('equipos.detalle', id=id))

@equipos_bp.route('/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_activo(id):
    if current_user.rol != 'administrador':
        flash('No tienes permisos para activar/desactivar usuarios.', 'danger')
        return redirect(url_for('equipos.lista'))
    
    usuario = Usuario.query.get_or_404(id)
    
    if usuario.id == current_user.id:
        flash('No puedes desactivar tu propia cuenta.', 'danger')
        return redirect(url_for('equipos.lista'))
    
    usuario.activo = not usuario.activo
    
    try:
        db.session.commit()
        estado = "activado" if usuario.activo else "desactivado"
        flash(f'Usuario {usuario.nombre_completo} {estado} exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al cambiar el estado del usuario.', 'danger')
    
    return redirect(url_for('equipos.lista'))

@equipos_bp.route('/rendimiento')
@login_required
def rendimiento():
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para ver reportes de rendimiento.', 'danger')
        return redirect(url_for('equipos.lista'))
    
    # Obtener todos los usuarios activos con estadísticas
    usuarios = Usuario.query.filter_by(activo=True).all()
    
    estadisticas = []
    for usuario in usuarios:
        # Horas totales trabajadas
        total_horas = db.session.query(db.func.sum(RegistroTiempo.horas_trabajadas)).filter_by(usuario_id=usuario.id).scalar() or 0
        
        # Obras activas
        obras_activas = usuario.obras_asignadas.join(Obra).filter(
            AsignacionObra.activo == True,
            Obra.estado.in_(['planificacion', 'en_curso'])
        ).count()
        
        # Obras completadas
        obras_completadas = usuario.obras_asignadas.join(Obra).filter(
            Obra.estado == 'finalizada'
        ).count()
        
        # Tareas completadas (este mes)
        from datetime import datetime, timedelta
        inicio_mes = datetime.now().replace(day=1)
        tareas_mes = db.session.query(db.func.count(RegistroTiempo.id)).filter(
            RegistroTiempo.usuario_id == usuario.id,
            RegistroTiempo.fecha >= inicio_mes.date()
        ).scalar() or 0
        
        estadisticas.append({
            'usuario': usuario,
            'total_horas': float(total_horas),
            'obras_activas': obras_activas,
            'obras_completadas': obras_completadas,
            'tareas_mes': tareas_mes
        })
    
    # Ordenar por horas trabajadas
    estadisticas.sort(key=lambda x: x['total_horas'], reverse=True)
    
    return render_template('equipos/rendimiento.html', estadisticas=estadisticas)
