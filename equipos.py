from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app import db
from models import Usuario, AsignacionObra, Obra, RegistroTiempo, OrgMembership
from services.memberships import get_current_membership
from sqlalchemy.exc import IntegrityError

equipos_bp = Blueprint('equipos', __name__)

@equipos_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('equipos'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    membership = get_current_membership()
    if not membership:
        flash('Selecciona una organización para ver tus equipos.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion', next=request.url))

    rol_filtro = request.args.get('rol', '')
    buscar = request.args.get('buscar', '')
    activo = request.args.get('activo', '')

    query = (
        OrgMembership.query
        .filter_by(org_id=membership.org_id, archived=False)
        .join(Usuario)
    )

    if rol_filtro:
        query = query.filter(OrgMembership.role == rol_filtro)

    if buscar:
        query = query.filter(
            db.or_(
                Usuario.nombre.contains(buscar),
                Usuario.apellido.contains(buscar),
                Usuario.email.contains(buscar)
            )
        )

    if activo:
        query = query.filter(OrgMembership.status == ('active' if activo == 'true' else 'inactive'))

    miembros = query.order_by(Usuario.apellido, Usuario.nombre).all()

    for membership_usuario in miembros:
        usuario = membership_usuario.usuario
        usuario.obras_activas = usuario.obras_asignadas.join(Obra).filter(
            AsignacionObra.activo == True,
            Obra.estado.in_(['planificacion', 'en_curso'])
        ).count()

    return render_template('equipos/lista.html',
                         miembros=miembros,
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
        # Crear usuario invitado
        user = Usuario(
            nombre=nombre,
            apellido=apellido,
            email=email.lower(),
            telefono=telefono,
            rol=role,
            role='admin' if role in ('administrador', 'admin') else 'operario',
            auth_provider='manual',
            activo=True,
            organizacion_id=current_user.organizacion_id,
            primary_org_id=current_user.primary_org_id or current_user.organizacion_id,
        )

        user.set_password(password)

        db.session.add(user)
        db.session.flush()  # Para obtener el ID

        active_membership = get_current_membership()
        if active_membership:
            user.ensure_membership(
                active_membership.org_id,
                role='admin' if role in ('administrador', 'admin') else 'operario',
                status='active',
            )

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
            # Crear nuevo usuario
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email.lower(),
                telefono=telefono,
                rol=rol,
                role='admin' if rol in ('administrador', 'admin') else 'operario',
                auth_provider='manual',
                activo=True,
                organizacion_id=current_user.organizacion_id if current_user.organizacion_id else None,
                primary_org_id=current_user.primary_org_id or current_user.organizacion_id,
            )

            nuevo_usuario.set_password(password)

            db.session.add(nuevo_usuario)
            db.session.flush()

            active_membership = get_current_membership()
            if active_membership:
                nuevo_usuario.ensure_membership(
                    active_membership.org_id,
                    role='admin' if rol in ('administrador', 'admin') else 'operario',
                    status='active',
                )

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
    membership = get_current_membership()
    if not membership or membership.role != 'admin':
        flash('No tienes permisos para activar/desactivar usuarios.', 'danger')
        return redirect(url_for('equipos.lista'))

    objetivo = OrgMembership.query.filter_by(org_id=membership.org_id, user_id=id, archived=False).first()

    if not objetivo:
        flash('El usuario no pertenece a tu organización.', 'danger')
        return redirect(url_for('equipos.lista'))

    if objetivo.user_id == current_user.id:
        flash('No puedes desactivar tu propia cuenta.', 'danger')
        return redirect(url_for('equipos.lista'))

    activar = not (objetivo.status == 'active' and objetivo.usuario.activo)
    objetivo.status = 'active' if activar else 'inactive'
    objetivo.usuario.activo = activar

    try:
        db.session.commit()
        estado = "activado" if activar else "desactivado"
        flash(f'Usuario {objetivo.usuario.nombre_completo} {estado} exitosamente.', 'success')
    except Exception:
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


# ===== NUEVAS RUTAS PARA GESTIÓN DE USUARIOS =====

@equipos_bp.route('/usuarios')
@login_required
def usuarios_listar():
    """Listado de usuarios para gestión administrativa"""
    # Verificar permisos admin/pm
    if current_user.role not in ['admin', 'pm']:
        flash('No tienes permisos para gestionar usuarios.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    users = Usuario.query.filter_by(organizacion_id=current_user.organizacion_id).order_by(Usuario.id.desc()).all()
    return render_template('equipo/usuarios.html', users=users)

@equipos_bp.route('/usuarios', methods=['POST'])
@login_required
def usuarios_crear():
    """Crear nuevo usuario con role específico"""
    # Verificar permisos admin/pm
    if current_user.role not in ['admin', 'pm']:
        return jsonify(ok=False, error="Sin permisos"), 403
    
    f = request.form
    role = (f.get('role') or 'operario').strip()
    org_id = getattr(current_user, 'organizacion_id', None)

    raw_password = (f.get('password', '').strip() or 'temp123456')

    normalized_role = 'admin' if role in ('admin', 'administrador') else 'operario'

    u = Usuario(
        nombre=f.get('nombre', '').strip(),
        apellido=f.get('apellido', '').strip(),
        email=f.get('email', '').lower().strip(),
        role=normalized_role,
        rol='administrador' if normalized_role == 'admin' else 'operario',  # Mantener rol legado por compatibilidad
        organizacion_id=org_id,
        primary_org_id=org_id,
        auth_provider='manual',
    )

    try:
        u.set_password(raw_password)
    except ValueError:
        return jsonify(ok=False, error="La contraseña no puede estar vacía."), 400

    db.session.add(u)
    try:
        db.session.flush()

        active_membership = get_current_membership()
        if active_membership:
            u.ensure_membership(
                active_membership.org_id,
                role=normalized_role,
                status='active',
            )

        db.session.commit()
        return jsonify(ok=True)
    except IntegrityError:
        db.session.rollback()
        return jsonify(ok=False, error="El email ya existe"), 400

@equipos_bp.route('/usuarios/<int:uid>/rol', methods=['POST'])
@login_required
def usuarios_cambiar_rol(uid):
    """Cambiar rol de usuario específico"""
    # Verificar permisos admin/pm
    if current_user.role not in ['admin', 'pm']:
        return jsonify(ok=False, error="Sin permisos"), 403
    
    u = Usuario.query.get_or_404(uid)
    u.role = request.form.get('role', 'operario')
    db.session.commit()
    return jsonify(ok=True)
