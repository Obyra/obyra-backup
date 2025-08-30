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

@equipos_bp.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
def usuarios_nuevo():
    """Crear nuevo usuario desde Gestión de Usuarios con permisos RBAC"""
    # Admins siempre pasan - NO redirigir al dashboard en GET
    if current_user.rol not in ['administrador', 'admin_empresa', 'superadmin']:
        flash('No tienes permisos para crear usuarios.', 'danger')
        return redirect(url_for('auth.usuarios_admin'))
    
    from roles_construccion import ROLES_DISPONIBLES
    from models import RoleModule, upsert_user_module
    
    if request.method == 'GET':
        # Cargar permisos por rol seleccionado (default 'operario')
        role = request.args.get('role', 'operario')
        role_perms = RoleModule.query.filter_by(role=role).all()
        return render_template('equipos/invitar.html', role=role, role_perms=role_perms, roles=ROLES_DISPONIBLES)
    
    # POST: crear usuario e invitar
    email = request.form.get('email')
    role = request.form.get('role')
    customize = request.form.get('customize') == 'on'
    
    # También permitir campos tradicionales si vienen del formulario
    nombre = request.form.get('nombre', email.split('@')[0])
    apellido = request.form.get('apellido', 'Usuario')
    telefono = request.form.get('telefono')
    password = request.form.get('password', 'temp123456')  # Temporal

    if not email or not role:
        flash('Email y Rol son obligatorios.', 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

    # Validar formato de email
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        flash('Por favor, ingresa un email válido.', 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

    # Verificar que el email no exista
    if Usuario.query.filter_by(email=email).first():
        flash('Ya existe un usuario con ese email.', 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

    try:
        from werkzeug.security import generate_password_hash
        
        # Crear usuario invitado
        user = Usuario(
            nombre=nombre,
            apellido=apellido,
            email=email.lower(),
            telefono=telefono,
            password_hash=generate_password_hash(password),
            rol=role,
            auth_provider='manual',
            activo=True,
            organizacion_id=current_user.organizacion_id
        )
        
        db.session.add(user)
        db.session.flush()  # Para obtener el ID

        # Overrides de módulos (opcional)
        if customize:
            # Esperamos checkboxes tipo modules[obras][view]=on / modules[obras][edit]=on
            for module in ["obras","presupuestos","equipos","inventario","marketplaces","reportes","documentos"]:
                view = bool(request.form.get(f"modules[{module}][view]"))
                edit = bool(request.form.get(f"modules[{module}][edit]"))
                upsert_user_module(user.id, module, view, edit)

        db.session.commit()
        flash('Usuario creado exitosamente.', 'success')
        return redirect(url_for('auth.usuarios_admin'))
        
    except Exception as e:
        db.session.rollback()
        flash('Error al crear el usuario. Por favor, intenta de nuevo.', 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

@equipos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    if not current_user.puede_acceder_modulo('equipos') or current_user.rol != 'administrador':
        flash('No tienes permisos para crear usuarios.', 'danger')
        return redirect(url_for('equipos.lista'))
    
    from roles_construccion import ROLES_DISPONIBLES
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        email = request.form.get('email')
        telefono = request.form.get('telefono')
        rol = request.form.get('rol')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validaciones
        if not all([nombre, apellido, email, rol, password]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            return render_template('equipos/crear.html', roles=ROLES_DISPONIBLES)
        
        # Validar formato de email
        import re
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            flash('Por favor, ingresa un email válido.', 'danger')
            return render_template('equipos/crear.html', roles=ROLES_DISPONIBLES)
        
        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('equipos/crear.html', roles=ROLES_DISPONIBLES)
        
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('equipos/crear.html', roles=ROLES_DISPONIBLES)
        
        # Verificar que el email no exista
        if Usuario.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese email.', 'danger')
            return render_template('equipos/crear.html', roles=ROLES_DISPONIBLES)
        
        try:
            from werkzeug.security import generate_password_hash
            
            # Crear nuevo usuario
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email.lower(),
                telefono=telefono,
                password_hash=generate_password_hash(password),
                rol=rol,
                auth_provider='manual',
                activo=True,
                organizacion_id=current_user.organizacion_id if current_user.organizacion_id else None
            )
            
            db.session.add(nuevo_usuario)
            db.session.commit()
            
            flash(f'Usuario {nombre} {apellido} creado exitosamente.', 'success')
            return redirect(url_for('equipos.detalle', id=nuevo_usuario.id))
            
        except Exception as e:
            db.session.rollback()
            flash('Error al crear el usuario. Por favor, intenta de nuevo.', 'danger')
    
    return render_template('equipos/crear.html', roles=ROLES_DISPONIBLES)

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

@equipos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar(id):
    if current_user.rol != 'administrador':
        flash('No tienes permisos para editar usuarios.', 'danger')
        return redirect(url_for('equipos.detalle', id=id))
    
    usuario = Usuario.query.get_or_404(id)
    from roles_construccion import ROLES_DISPONIBLES
    
    if request.method == 'POST':
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
            return render_template('equipos/editar.html', usuario=usuario, roles=ROLES_DISPONIBLES)
        
        try:
            db.session.commit()
            flash('Usuario actualizado exitosamente.', 'success')
            return redirect(url_for('equipos.detalle', id=id))
        except Exception as e:
            db.session.rollback()
            flash('Error al actualizar el usuario.', 'danger')
    
    return render_template('equipos/editar.html', usuario=usuario, roles=ROLES_DISPONIBLES)

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
