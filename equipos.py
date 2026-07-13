import re
from typing import Optional

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

import roles_construccion as roles_defs
from extensions import db
from models import Usuario, AsignacionObra, Obra, RegistroTiempo, OrgMembership, CustomRole, RoleModule
from services.memberships import get_current_membership
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from auth import generate_temporary_password, send_new_member_invitation


ROLE_CATEGORY_OPTIONS = {
    categoria: list(roles) for categoria, roles in roles_defs.obtener_roles_por_categoria().items()
}
ROLES_DISPONIBLES = getattr(roles_defs, 'ROLES_DISPONIBLES', ROLE_CATEGORY_OPTIONS)

ROLES_MEMBRESIA = list(getattr(roles_defs, 'ROLES_MEMBRESIA', []))
if not ROLES_MEMBRESIA:
    ROLES_MEMBRESIA = ['operario', 'supervisor', 'admin']

ROLES_MEMBRESIA_LABELS = dict(getattr(roles_defs, 'ROLES_MEMBRESIA_LABELS', {}))
if not ROLES_MEMBRESIA_LABELS:
    def _default_membership_label(role: str) -> str:
        try:
            return roles_defs.obtener_nombre_rol(role)
        except Exception:
            return role.replace('_', ' ').title()

    ROLES_MEMBRESIA_LABELS = {
        role: _default_membership_label(role) for role in ROLES_MEMBRESIA
    }

_CANONICAL_MEMBERSHIP_ROLES = {role.lower(): role for role in ROLES_MEMBRESIA}
_MEMBERSHIP_ROLE_ALIASES = {
    'administrador': 'admin',
    'administradora': 'admin',
    'admin': 'admin',
    'operario': 'operario',
    'operaria': 'operario',
    'supervisor': 'project_manager',
    'project manager': 'project_manager',
    'project_manager': 'project_manager',
    'pm': 'project_manager',
}


def _normalize_membership_role(raw_role: Optional[str]) -> Optional[str]:
    if not raw_role:
        return None

    key = raw_role.strip().lower()
    if not key:
        return None

    if key in _CANONICAL_MEMBERSHIP_ROLES:
        return _CANONICAL_MEMBERSHIP_ROLES[key]

    alias = _MEMBERSHIP_ROLE_ALIASES.get(key)
    if alias:
        alias_key = alias.lower()
        return _CANONICAL_MEMBERSHIP_ROLES.get(alias_key, alias)

    return None


# Límite de usuarios por defecto (plan prueba)
MAX_USUARIOS_DEFAULT = 3


def contar_usuarios_organizacion(org_id):
    """
    Cuenta el número de usuarios activos en una organización.
    Retorna el conteo de miembros activos.
    """
    if not org_id:
        return 0

    return OrgMembership.query.filter(
        OrgMembership.org_id == org_id,
        OrgMembership.status == 'active'
    ).count()


def obtener_limite_usuarios(org_id):
    """Obtiene el límite de usuarios según el plan de la organización."""
    from models import Organizacion
    org = Organizacion.query.get(org_id)
    if org and org.max_usuarios:
        return org.max_usuarios
    return MAX_USUARIOS_DEFAULT


def verificar_limite_usuarios(org_id):
    """
    Verifica si la organización puede agregar más usuarios.
    Retorna (puede_agregar: bool, mensaje: str)
    """
    if not org_id:
        return False, "No se encontró la organización."

    cantidad_actual = contar_usuarios_organizacion(org_id)
    limite = obtener_limite_usuarios(org_id)

    if cantidad_actual >= limite:
        return False, f"Has alcanzado el límite de {limite} usuarios de tu plan. Para agregar más usuarios, mejorá tu plan."

    return True, f"Usuarios: {cantidad_actual}/{limite}"


equipos_bp = Blueprint('equipos', __name__)


# ============================================================================
# Fase 2: roles personalizados por organización
# ============================================================================

# Módulos del sistema sobre los que se definen permisos.
# OBYRA enforcea solo 2 niveles: Ver (can_view) y Editar (can_edit).
MODULOS_SISTEMA = [
    'obras', 'presupuestos', 'equipos', 'inventario',
    'marketplaces', 'reportes', 'seguridad',
]
MODULO_LABELS = {
    'obras': 'Obras', 'presupuestos': 'Presupuestos', 'equipos': 'Equipos',
    'inventario': 'Inventario', 'marketplaces': 'Marketplace',
    'reportes': 'Reportes', 'seguridad': 'Seguridad',
}
# Roles base que no se pueden borrar (rompería el acceso de la org).
ROLES_BASE = {'admin', 'pm', 'tecnico', 'operario'}


def _org_id_actual():
    """org activa del usuario (membresía actual o fallback legacy)."""
    m = get_current_membership()
    if m:
        return m.org_id
    return getattr(current_user, 'organizacion_id', None)


def _es_admin_org():
    return bool(getattr(current_user, 'is_super_admin', False)) or current_user.role == 'admin'


def _rol_valido_en_org(nombre, org_id):
    """True si `nombre` es un custom_role activo de esa organización."""
    if not nombre or not org_id:
        return False
    return CustomRole.query.filter_by(
        org_id=org_id, nombre=nombre, activo=True
    ).first() is not None


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
        .filter(
            OrgMembership.org_id == membership.org_id,
            db.or_(
                OrgMembership.archived.is_(False),
                OrgMembership.archived.is_(None),
            ),
        )
        .join(Usuario, OrgMembership.user_id == Usuario.id)
        # Excluir super administradores del sistema de la lista de equipos
        .filter(Usuario.is_super_admin.is_(False))
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
    if not current_user.es_admin():
        flash('No tienes permisos para crear usuarios.', 'danger')
        return redirect(url_for('auth.usuarios_admin'))
    
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
    temp_password_input = (request.form.get('password') or '').strip()

    if not email or not role:
        flash('Email y Rol son obligatorios.', 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

    # Validar formato de email
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        flash('Por favor, ingresa un email válido.', 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

    # Normalizar email a minúsculas
    email = email.lower().strip()

    # Verificar que el email no exista (case-insensitive)
    if Usuario.query.filter(func.lower(Usuario.email) == email).first():
        flash('Ya existe un usuario con ese email.', 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

    # Fase 2a: sin collapse. El rol debe existir en custom_roles de la org.
    if not _rol_valido_en_org(role, _org_id_actual()):
        flash(f"El rol '{role}' no existe en tu organización.", 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

    # Verificar límite de usuarios por organización
    membership_actual = get_current_membership()
    if membership_actual:
        puede_agregar, mensaje_limite = verificar_limite_usuarios(membership_actual.organizacion_id)
        if not puede_agregar:
            flash(mensaje_limite, 'danger')
            return redirect(url_for('equipos.usuarios_nuevo'))

    temp_password = temp_password_input or generate_temporary_password()

    try:
        # Crear usuario invitado
        user = Usuario(
            nombre=nombre,
            apellido=apellido,
            email=email.lower(),
            telefono=telefono,
            rol=Usuario._sync_rol_from_role(role),
            role=role,
            auth_provider='manual',
            activo=True,
            organizacion_id=current_user.organizacion_id,
            primary_org_id=current_user.primary_org_id or current_user.organizacion_id,
        )

        user.set_password(temp_password)

        db.session.add(user)
        db.session.flush()  # Para obtener el ID

        active_membership = get_current_membership()
        membership = None
        target_org_id = None
        if active_membership:
            target_org_id = active_membership.org_id
        else:
            target_org_id = current_user.primary_org_id or current_user.organizacion_id

        if target_org_id:
            membership = user.ensure_membership(
                target_org_id,
                role=role,
                status='active',
            )
        else:
            membership = None

        # Overrides de módulos (opcional)
        if customize:
            # Esperamos checkboxes tipo modules[obras][view]=on / modules[obras][edit]=on
            for module in ["obras","presupuestos","equipos","inventario","marketplaces","reportes"]:
                view = bool(request.form.get(f"modules[{module}][view]"))
                edit = bool(request.form.get(f"modules[{module}][edit]"))
                upsert_user_module(user.id, module, view, edit)

        db.session.commit()
        try:
            from models.audit import registrar_audit
            registrar_audit('crear', 'usuario', user.id, f'Usuario creado: {user.email} (rol: {user.role})')
            db.session.commit()
        except Exception:
            pass
        send_new_member_invitation(user, membership, temp_password)
        flash('Usuario creado exitosamente y se envió un email de bienvenida.', 'success')
        return redirect(url_for('auth.usuarios_admin'))

    except Exception as e:
        db.session.rollback()
        flash('Error al crear el usuario. Por favor, intenta de nuevo.', 'danger')
        return redirect(url_for('equipos.usuarios_nuevo'))

@equipos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    if not current_user.puede_acceder_modulo('equipos') or not current_user.es_admin():
        flash('No tienes permisos para crear usuarios.', 'danger')
        return redirect(url_for('equipos.lista'))
    
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
        
        # Normalizar email a minúsculas
        email = email.lower().strip()

        # Verificar que el email no exista (case-insensitive)
        if Usuario.query.filter(func.lower(Usuario.email) == email).first():
            flash('Ya existe un usuario con ese email.', 'danger')
            return render_template('equipos/crear.html', roles=ROLES_DISPONIBLES)

        # Verificar límite de usuarios por organización
        membership = get_current_membership()
        if membership:
            puede_agregar, mensaje_limite = verificar_limite_usuarios(membership.org_id)
            if not puede_agregar:
                flash(mensaje_limite, 'danger')
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
    
    membership = get_current_membership()
    if not membership:
        flash('Selecciona una organización para ver tus equipos.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion', next=request.url))

    miembro = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == membership.org_id,
            OrgMembership.user_id == id,
            db.or_(
                OrgMembership.archived.is_(False),
                OrgMembership.archived.is_(None),
            ),
        )
        .options(joinedload(OrgMembership.usuario))
        .first()
    )

    if not miembro:
        flash('El usuario no pertenece a tu organización.', 'danger')
        return redirect(url_for('equipos.lista'))

    usuario = miembro.usuario
    
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
    membership = get_current_membership()
    if not membership or membership.role != 'admin':
        flash('No tienes permisos para editar usuarios.', 'danger')
        return redirect(url_for('equipos.detalle', id=id))

    miembro_objetivo = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == membership.org_id,
            OrgMembership.user_id == id,
            db.or_(
                OrgMembership.archived.is_(False),
                OrgMembership.archived.is_(None),
            ),
        )
        .options(
            joinedload('usuario'),
            joinedload('organizacion'),
        )
        .first()
    )

    if not miembro_objetivo:
        flash('El usuario no pertenece a tu organización.', 'danger')
        return redirect(url_for('equipos.lista'))

    usuario = miembro_objetivo.usuario

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        email = request.form.get('email')
        telefono = request.form.get('telefono')
        rol_trabajo = request.form.get('rol')
        rol_membresia_raw = (
            request.form.get('rol_membresia')
            or request.form.get('rol_sistema')
            or request.form.get('membership_role')
        )

        membership_role = _normalize_membership_role(rol_membresia_raw)
        if membership_role is None:
            flash('Selecciona un rol válido para la organización.', 'danger')
            response = render_template(
                'equipos/editar.html',
                usuario=usuario,
                roles=ROLES_DISPONIBLES,
                membership_roles=ROLES_MEMBRESIA,
                membership_role_labels=ROLES_MEMBRESIA_LABELS,
                membership_objetivo=miembro_objetivo,
            )
            return response, 400

        if nombre:
            usuario.nombre = nombre.strip()
        if apellido:
            usuario.apellido = apellido.strip()
        if telefono is not None:
            telefono_limpio = telefono.strip()
            usuario.telefono = telefono_limpio or None
        # rol_trabajo ya no se usa - solo se actualiza 'role' más abajo

        if email:
            email_normalizado = email.strip().lower()
            if not email_normalizado:
                flash('El email no puede quedar vacío.', 'danger')
                response = render_template(
                    'equipos/editar.html',
                    usuario=usuario,
                    roles=ROLES_DISPONIBLES,
                    membership_roles=ROLES_MEMBRESIA,
                    membership_role_labels=ROLES_MEMBRESIA_LABELS,
                    membership_objetivo=miembro_objetivo,
                )
                return response, 400

            email_existente = (
                Usuario.query
                .filter(Usuario.email == email_normalizado, Usuario.id != usuario.id)
                .first()
            )
            if email_existente:
                flash('Ya existe otro usuario con ese email.', 'danger')
                response = render_template(
                    'equipos/editar.html',
                    usuario=usuario,
                    roles=ROLES_DISPONIBLES,
                    membership_roles=ROLES_MEMBRESIA,
                    membership_role_labels=ROLES_MEMBRESIA_LABELS,
                    membership_objetivo=miembro_objetivo,
                )
                return response, 400

            usuario.email = email_normalizado

        # Actualizar solo el campo unificado 'role'
        miembro_objetivo.role = membership_role
        usuario.role = membership_role

        try:
            db.session.commit()
            flash('Usuario actualizado exitosamente.', 'success')
            return redirect(url_for('equipos.detalle', id=id))
        except Exception:
            db.session.rollback()
            flash('Error al actualizar el usuario.', 'danger')

    return render_template(
        'equipos/editar.html',
        usuario=usuario,
        roles=ROLES_DISPONIBLES,
        membership_roles=ROLES_MEMBRESIA,
        membership_role_labels=ROLES_MEMBRESIA_LABELS,
        membership_objetivo=miembro_objetivo,
    )

@equipos_bp.route('/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_activo(id):
    membership = get_current_membership()
    if not membership or membership.role != 'admin':
        flash('No tienes permisos para activar/desactivar usuarios.', 'danger')
        return redirect(url_for('equipos.lista'))

    objetivo = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == membership.org_id,
            OrgMembership.user_id == id,
            db.or_(
                OrgMembership.archived.is_(False),
                OrgMembership.archived.is_(None),
            ),
        )
        .first()
    )

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

@equipos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_miembro(id):
    membership = get_current_membership()
    if not membership or membership.role != 'admin':
        flash('No tienes permisos para eliminar usuarios.', 'danger')
        return redirect(url_for('equipos.lista'))

    objetivo = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == membership.org_id,
            OrgMembership.user_id == id,
        )
        .first()
    )

    if not objetivo:
        flash('El usuario no pertenece a tu organización.', 'danger')
        return redirect(url_for('equipos.lista'))

    if objetivo.user_id == current_user.id:
        flash('No puedes eliminarte a ti mismo del equipo.', 'danger')
        return redirect(url_for('equipos.lista'))

    nombre = objetivo.usuario.nombre_completo if objetivo.usuario else 'Usuario'

    try:
        db.session.delete(objetivo)
        db.session.commit()
        flash(f'Usuario {nombre} eliminado del equipo exitosamente.', 'success')
    except Exception:
        db.session.rollback()
        flash('Error al eliminar el usuario del equipo.', 'danger')

    return redirect(url_for('equipos.lista'))

@equipos_bp.route('/rendimiento')
@login_required
def rendimiento():
    """Vista de rendimiento del equipo"""
    try:
        # Verificar permisos
        if not hasattr(current_user, 'role') or current_user.role not in ['admin', 'pm', 'tecnico']:
            flash('No tienes permisos para ver reportes de rendimiento.', 'danger')
            return redirect(url_for('equipos.lista'))

        # Obtener la membresía actual del usuario
        membership = get_current_membership()
        if not membership:
            flash('No tienes una organización asignada.', 'warning')
            return redirect(url_for('reportes.dashboard'))

        org_id = membership.org_id

        # Obtener usuarios con membresía activa en esta organización
        miembros = OrgMembership.query.options(
            joinedload(OrgMembership.usuario)
        ).filter(
            OrgMembership.org_id == org_id,
            OrgMembership.status == 'active',
            db.or_(OrgMembership.archived.is_(False), OrgMembership.archived.is_(None))
        ).all()

        estadisticas = []
        for miembro in miembros:
            usuario = miembro.usuario
            if not usuario or usuario.is_super_admin:
                continue

            # Valores por defecto - sin queries complejas para evitar errores
            total_horas = 0
            obras_activas = 0
            obras_completadas = 0
            tareas_mes = 0

            try:
                # Horas totales
                horas_result = db.session.query(
                    func.coalesce(func.sum(RegistroTiempo.horas_trabajadas), 0)
                ).filter(RegistroTiempo.usuario_id == usuario.id).scalar()
                total_horas = float(horas_result or 0)
            except:
                pass

            try:
                # Contar asignaciones activas
                obras_activas = AsignacionObra.query.join(Obra).filter(
                    AsignacionObra.usuario_id == usuario.id,
                    AsignacionObra.activo == True,
                    Obra.estado.in_(['planificacion', 'en_curso'])
                ).count()
            except:
                pass

            try:
                # Contar obras finalizadas
                obras_completadas = AsignacionObra.query.join(Obra).filter(
                    AsignacionObra.usuario_id == usuario.id,
                    Obra.estado == 'finalizada'
                ).count()
            except:
                pass

            estadisticas.append({
                'usuario': usuario,
                'total_horas': total_horas,
                'obras_activas': obras_activas,
                'obras_completadas': obras_completadas,
                'tareas_mes': tareas_mes
            })

        # Ordenar por horas trabajadas
        estadisticas.sort(key=lambda x: x['total_horas'], reverse=True)

        return render_template('equipos/rendimiento.html', estadisticas=estadisticas)

    except Exception as e:
        import traceback
        print(f"[ERROR] rendimiento(): {e}")
        print(traceback.format_exc())
        flash(f'Error al cargar rendimiento: {str(e)}', 'danger')
        return redirect(url_for('equipos.lista'))


# ===== NUEVAS RUTAS PARA GESTIÓN DE USUARIOS =====

@equipos_bp.route('/usuarios')
@login_required
def usuarios_listar():
    """Listado de usuarios para gestión administrativa"""
    # Verificar permisos admin/pm
    if current_user.role not in ['admin', 'pm']:
        flash('No tienes permisos para gestionar usuarios.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    # Obtener la membresía actual para filtrar por organización correcta
    membership = get_current_membership()
    if not membership:
        flash('No tienes una organización asignada.', 'warning')
        return redirect(url_for('reportes.dashboard'))

    org_id = membership.org_id

    # Obtener usuarios que tienen membresía activa en esta organización
    usuarios_ids = db.session.query(OrgMembership.user_id).filter(
        OrgMembership.org_id == org_id,
        OrgMembership.status == 'active',
        db.or_(OrgMembership.archived.is_(False), OrgMembership.archived.is_(None))
    ).subquery()

    users = Usuario.query.filter(
        Usuario.id.in_(usuarios_ids),
        Usuario.is_super_admin.is_(False)
    ).order_by(Usuario.nombre, Usuario.apellido).all()

    return render_template('equipo/usuarios.html', users=users)

@equipos_bp.route('/usuarios', methods=['POST'])
@login_required
def usuarios_crear():
    """Crear nuevo usuario con role específico"""
    # Verificar permisos admin/pm
    if current_user.role not in ['admin', 'pm']:
        return jsonify(ok=False, error="Sin permisos"), 403

    # Verificar límite de usuarios por organización
    membership = get_current_membership()
    if membership:
        puede_agregar, mensaje_limite = verificar_limite_usuarios(membership.org_id)
        if not puede_agregar:
            return jsonify(ok=False, error=mensaje_limite), 400

    f = request.form
    role = (f.get('role') or '').strip()
    org_id = _org_id_actual()

    raw_password = (f.get('password', '').strip() or 'temp123456')

    # Fase 2a: sin collapse. El rol debe existir en custom_roles de la org.
    if not _rol_valido_en_org(role, org_id):
        return jsonify(ok=False, error=f"El rol '{role}' no existe en tu organización."), 400
    normalized_role = role
    rol_legado = Usuario._sync_rol_from_role(role)  # campo legado derivado

    email_nuevo = f.get('email', '').lower().strip()

    # Verificar si el email ya existe
    from sqlalchemy import func
    usuario_existente = Usuario.query.filter(func.lower(Usuario.email) == email_nuevo).first()

    if usuario_existente:
        # Si el usuario existe, re-vincularlo a esta organizacion
        u = usuario_existente
        u.nombre = f.get('nombre', '').strip() or u.nombre
        u.apellido = f.get('apellido', '').strip() or u.apellido
        u.role = normalized_role
        u.rol = rol_legado
        u.activo = True
        if not u.organizacion_id:
            u.organizacion_id = org_id
        if not getattr(u, 'primary_org_id', None):
            u.primary_org_id = org_id
        if raw_password and raw_password != 'temp123456':
            try:
                u.set_password(raw_password)
            except ValueError:
                pass
    else:
        u = Usuario(
            nombre=f.get('nombre', '').strip(),
            apellido=f.get('apellido', '').strip(),
            email=email_nuevo,
            role=normalized_role,
            rol=rol_legado,
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
        return jsonify(ok=False, error="Error al crear el usuario. Intentá de nuevo."), 400

@equipos_bp.route('/usuarios/<int:uid>/rol', methods=['POST'])
@login_required
def usuarios_cambiar_rol(uid):
    """Cambiar rol de usuario específico"""
    # Verificar permisos admin/pm
    if current_user.role not in ['admin', 'pm']:
        return jsonify(ok=False, error="Sin permisos"), 403

    # Verificar que el usuario pertenece a la misma organización
    membership = get_current_membership()
    if not membership:
        return jsonify(ok=False, error="Sin organización activa"), 403

    target_membership = OrgMembership.query.filter_by(
        user_id=uid,
        org_id=membership.org_id,
        status='active'
    ).first()
    if not target_membership:
        return jsonify(ok=False, error="Usuario no encontrado en tu organización"), 404

    u = Usuario.query.get_or_404(uid)
    nuevo_role = (request.form.get('role') or '').strip()
    # Fase 2a: validar contra custom_roles de la org.
    if not _rol_valido_en_org(nuevo_role, membership.org_id):
        return jsonify(ok=False, error=f"El rol '{nuevo_role}' no existe en tu organización."), 400

    old_role = u.role
    u.role = nuevo_role
    u.rol = Usuario._sync_rol_from_role(nuevo_role)      # campo legado derivado
    target_membership.role = nuevo_role                  # FIX: sincronizar la membresía
    try:
        from models.audit import registrar_audit
        registrar_audit('cambiar_rol', 'usuario', uid,
                       f'Rol cambiado: {old_role} → {u.role} ({u.email})')
    except Exception:
        pass
    db.session.commit()
    return jsonify(ok=True)

@equipos_bp.route('/usuarios/<int:uid>', methods=['POST'])
@login_required
def usuarios_editar(uid):
    """Editar datos de usuario específico"""
    # Verificar permisos admin/pm
    if current_user.role not in ['admin', 'pm']:
        return jsonify(ok=False, error="Sin permisos"), 403

    # Verificar que el usuario pertenece a la misma organización
    membership = get_current_membership()
    if not membership:
        return jsonify(ok=False, error="Sin organización activa"), 403

    target_membership = OrgMembership.query.filter_by(
        user_id=uid,
        org_id=membership.org_id,
        status='active'
    ).first()
    if not target_membership:
        return jsonify(ok=False, error="Usuario no encontrado en tu organización"), 404

    u = Usuario.query.get_or_404(uid)
    f = request.form

    # Actualizar campos básicos
    u.nombre = f.get('nombre', '').strip()
    u.apellido = f.get('apellido', '').strip()

    # Actualizar email (verificar que no exista otro usuario con ese email)
    new_email = f.get('email', '').lower().strip()
    if new_email != u.email:
        existing = Usuario.query.filter_by(email=new_email).first()
        if existing:
            return jsonify(ok=False, error="El email ya existe"), 400
        u.email = new_email

    # Actualizar rol con normalización
    role = (f.get('role') or 'operario').strip()
    if role in ('admin', 'administrador'):
        normalized_role = 'admin'
        rol_legado = 'administrador'
    elif role == 'pm':
        normalized_role = 'pm'
        rol_legado = 'tecnico'
    else:
        normalized_role = 'operario'
        rol_legado = 'operario'

    u.role = normalized_role
    u.rol = rol_legado

    try:
        db.session.commit()
        return jsonify(ok=True)
    except IntegrityError:
        db.session.rollback()
        return jsonify(ok=False, error="Error al actualizar usuario"), 400


# ============================================================================
# Fase 2a — API de roles para poblar dropdowns dinámicos
# ============================================================================

@equipos_bp.route('/api/roles', methods=['GET'])
@login_required
def api_roles_listar():
    """Lista los custom_roles activos de la org actual (para dropdowns)."""
    org_id = _org_id_actual()
    roles = (CustomRole.query
             .filter_by(org_id=org_id, activo=True)
             .order_by(CustomRole.nombre)
             .all())
    return jsonify([
        {'id': r.id, 'nombre': r.nombre, 'descripcion': r.descripcion, 'activo': r.activo}
        for r in roles
    ])


# ============================================================================
# Fase 2b — Administración de roles (solo admin de la org)
# ============================================================================

@equipos_bp.route('/roles', methods=['GET'])
@login_required
def roles_admin():
    """Pantalla de administración de roles y permisos."""
    if not _es_admin_org():
        flash('Solo los administradores pueden gestionar roles.', 'danger')
        return redirect(url_for('equipos.lista'))
    org_id = _org_id_actual()
    roles = (CustomRole.query
             .filter_by(org_id=org_id)
             .order_by(CustomRole.activo.desc(), CustomRole.nombre)
             .all())
    return render_template(
        'equipos/roles_admin.html',
        roles=roles,
        modulos=MODULOS_SISTEMA,
        modulo_labels=MODULO_LABELS,
        roles_base=ROLES_BASE,
    )


@equipos_bp.route('/api/roles', methods=['POST'])
@login_required
def api_roles_crear():
    """Crea un custom_role + seedea RoleModule (todos Ver, sin Editar)."""
    if not _es_admin_org():
        return jsonify(ok=False, error="Sin permisos"), 403
    org_id = _org_id_actual()
    data = request.get_json(silent=True) or request.form
    nombre = (data.get('nombre') or '').strip()
    descripcion = (data.get('descripcion') or '').strip() or None

    if not nombre:
        return jsonify(ok=False, error="El nombre del rol es obligatorio."), 400
    if CustomRole.query.filter_by(org_id=org_id, nombre=nombre).first():
        return jsonify(ok=False, error=f"Ya existe un rol '{nombre}' en tu organización."), 400

    rol = CustomRole(org_id=org_id, nombre=nombre, descripcion=descripcion, activo=True)
    db.session.add(rol)
    # Permisos default: Ver en todos los módulos, sin Editar.
    for modulo in MODULOS_SISTEMA:
        db.session.add(RoleModule(
            org_id=org_id, role=nombre, module=modulo, can_view=True, can_edit=False,
        ))
    db.session.commit()
    return jsonify(ok=True, id=rol.id, nombre=rol.nombre)


@equipos_bp.route('/api/roles/<int:rid>', methods=['PUT'])
@login_required
def api_roles_editar(rid):
    """Edita nombre/descripción/activo de un custom_role.

    Si cambia el nombre, propaga el rename a RoleModule, Usuario.role y
    OrgMembership.role de esa org (el rol se referencia por string).
    """
    if not _es_admin_org():
        return jsonify(ok=False, error="Sin permisos"), 403
    org_id = _org_id_actual()
    rol = CustomRole.query.filter_by(id=rid, org_id=org_id).first_or_404()
    data = request.get_json(silent=True) or request.form

    nuevo_nombre = (data.get('nombre') or rol.nombre).strip()
    if nuevo_nombre != rol.nombre:
        if rol.nombre in ROLES_BASE:
            return jsonify(ok=False, error="No se puede renombrar un rol base."), 400
        if CustomRole.query.filter_by(org_id=org_id, nombre=nuevo_nombre).first():
            return jsonify(ok=False, error=f"Ya existe un rol '{nuevo_nombre}'."), 400
        # Propagar rename
        RoleModule.query.filter_by(org_id=org_id, role=rol.nombre).update({'role': nuevo_nombre})
        Usuario.query.filter_by(organizacion_id=org_id, role=rol.nombre).update({'role': nuevo_nombre})
        OrgMembership.query.filter_by(org_id=org_id, role=rol.nombre).update({'role': nuevo_nombre})
        rol.nombre = nuevo_nombre

    if 'descripcion' in data:
        rol.descripcion = (data.get('descripcion') or '').strip() or None
    if 'activo' in data:
        rol.activo = str(data.get('activo')).lower() in ('1', 'true', 'on', 'yes')

    db.session.commit()
    return jsonify(ok=True)


@equipos_bp.route('/api/roles/<int:rid>', methods=['DELETE'])
@login_required
def api_roles_borrar(rid):
    """Borra un custom_role + sus RoleModule. Bloquea si está en uso o es base."""
    if not _es_admin_org():
        return jsonify(ok=False, error="Sin permisos"), 403
    org_id = _org_id_actual()
    rol = CustomRole.query.filter_by(id=rid, org_id=org_id).first_or_404()

    if rol.nombre in ROLES_BASE:
        return jsonify(ok=False, error="No se puede borrar un rol base del sistema."), 400

    en_uso = (OrgMembership.query
              .filter_by(org_id=org_id, role=rol.nombre, status='active')
              .count())
    if en_uso:
        return jsonify(ok=False,
                       error=f"El rol está asignado a {en_uso} usuario(s). Reasignalos antes de borrar."), 400

    RoleModule.query.filter_by(org_id=org_id, role=rol.nombre).delete()
    db.session.delete(rol)
    db.session.commit()
    return jsonify(ok=True)


@equipos_bp.route('/api/roles/<int:rid>/permisos', methods=['GET'])
@login_required
def api_roles_permisos_listar(rid):
    """Devuelve los permisos (por módulo) de un rol."""
    if not _es_admin_org():
        return jsonify(ok=False, error="Sin permisos"), 403
    org_id = _org_id_actual()
    rol = CustomRole.query.filter_by(id=rid, org_id=org_id).first_or_404()
    perms = {rm.module: {'view': rm.can_view, 'edit': rm.can_edit}
             for rm in RoleModule.query.filter_by(org_id=org_id, role=rol.nombre)}
    return jsonify({
        'rol': rol.nombre,
        'permisos': [
            {'module': m, 'label': MODULO_LABELS.get(m, m),
             'view': perms.get(m, {}).get('view', False),
             'edit': perms.get(m, {}).get('edit', False)}
            for m in MODULOS_SISTEMA
        ],
    })


@equipos_bp.route('/api/roles/<int:rid>/permisos', methods=['POST'])
@login_required
def api_roles_permisos_upsert(rid):
    """Upsert de un permiso RoleModule (rol, módulo, can_view, can_edit)."""
    if not _es_admin_org():
        return jsonify(ok=False, error="Sin permisos"), 403
    org_id = _org_id_actual()
    rol = CustomRole.query.filter_by(id=rid, org_id=org_id).first_or_404()
    data = request.get_json(silent=True) or request.form

    module = (data.get('module') or '').strip()
    if module not in MODULOS_SISTEMA:
        return jsonify(ok=False, error=f"Módulo inválido: '{module}'."), 400

    def _b(v):
        return str(v).lower() in ('1', 'true', 'on', 'yes')
    can_view = _b(data.get('view'))
    can_edit = _b(data.get('edit'))
    if can_edit:
        can_view = True  # editar implica ver

    rm = RoleModule.query.filter_by(org_id=org_id, role=rol.nombre, module=module).first()
    if rm:
        rm.can_view = can_view
        rm.can_edit = can_edit
    else:
        db.session.add(RoleModule(
            org_id=org_id, role=rol.nombre, module=module,
            can_view=can_view, can_edit=can_edit,
        ))
    db.session.commit()
    return jsonify(ok=True, module=module, view=can_view, edit=can_edit)


@equipos_bp.route('/api/roles/<int:rid>/permisos/<modulo>', methods=['DELETE'])
@login_required
def api_roles_permisos_borrar(rid, modulo):
    """Borra el permiso de un módulo para un rol (queda sin acceso)."""
    if not _es_admin_org():
        return jsonify(ok=False, error="Sin permisos"), 403
    org_id = _org_id_actual()
    rol = CustomRole.query.filter_by(id=rid, org_id=org_id).first_or_404()
    RoleModule.query.filter_by(org_id=org_id, role=rol.nombre, module=modulo).delete()
    db.session.commit()
    return jsonify(ok=True)
