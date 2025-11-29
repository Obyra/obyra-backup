"""
Permissions Service
==================

Sistema centralizado de permisos y autorización.
Provee decoradores y funciones para validar roles y permisos de usuarios.

Uso:
    from services.permissions import require_role, require_any_role, is_admin

    @app.route('/admin')
    @login_required
    @require_role('admin')
    def admin_panel():
        ...

    @app.route('/gestionar')
    @login_required
    @require_any_role('admin', 'pm', 'tecnico')
    def gestionar():
        ...
"""

from functools import wraps
from flask import abort, flash, redirect, url_for, request, jsonify
from flask_login import current_user


# Mapeo de roles equivalentes (sistema antiguo vs nuevo)
ROLE_EQUIVALENTS = {
    'admin': ['admin', 'administrador'],
    'administrador': ['admin', 'administrador'],
    'pm': ['pm', 'project_manager'],
    'project_manager': ['pm', 'project_manager'],
    'tecnico': ['tecnico', 'technical'],
    'technical': ['tecnico', 'technical'],
    'operario': ['operario', 'worker'],
    'worker': ['operario', 'worker'],
    'proveedor': ['proveedor', 'supplier'],
    'supplier': ['proveedor', 'supplier'],
}

# Jerarquía de roles (mayor número = más permisos)
ROLE_HIERARCHY = {
    'operario': 1,
    'worker': 1,
    'proveedor': 2,
    'supplier': 2,
    'tecnico': 3,
    'technical': 3,
    'pm': 4,
    'project_manager': 4,
    'admin': 5,
    'administrador': 5,
}


def get_user_roles(user=None):
    """
    Obtiene todos los roles del usuario (normalizados).

    Returns:
        set: Conjunto de roles del usuario
    """
    if user is None:
        user = current_user

    if not user or not user.is_authenticated:
        return set()

    roles = set()

    # Obtener rol del campo 'role' (nuevo)
    if hasattr(user, 'role') and user.role:
        roles.add(user.role.lower())
        # Agregar equivalentes
        for equiv in ROLE_EQUIVALENTS.get(user.role.lower(), []):
            roles.add(equiv)

    # Obtener rol del campo 'rol' (antiguo)
    if hasattr(user, 'rol') and user.rol:
        roles.add(user.rol.lower())
        # Agregar equivalentes
        for equiv in ROLE_EQUIVALENTS.get(user.rol.lower(), []):
            roles.add(equiv)

    # Super admin tiene todos los roles
    if getattr(user, 'is_super_admin', False):
        roles.update(['admin', 'administrador', 'pm', 'tecnico', 'operario'])

    return roles


def has_role(role, user=None):
    """
    Verifica si el usuario tiene un rol específico.

    Args:
        role: Rol a verificar
        user: Usuario (por defecto current_user)

    Returns:
        bool: True si tiene el rol
    """
    user_roles = get_user_roles(user)
    role_lower = role.lower()

    # Verificar rol directo
    if role_lower in user_roles:
        return True

    # Verificar equivalentes
    for equiv in ROLE_EQUIVALENTS.get(role_lower, []):
        if equiv in user_roles:
            return True

    return False


def has_any_role(*roles, user=None):
    """
    Verifica si el usuario tiene al menos uno de los roles especificados.

    Args:
        *roles: Roles a verificar
        user: Usuario (por defecto current_user)

    Returns:
        bool: True si tiene al menos un rol
    """
    for role in roles:
        if has_role(role, user):
            return True
    return False


def has_all_roles(*roles, user=None):
    """
    Verifica si el usuario tiene TODOS los roles especificados.

    Args:
        *roles: Roles a verificar
        user: Usuario (por defecto current_user)

    Returns:
        bool: True si tiene todos los roles
    """
    for role in roles:
        if not has_role(role, user):
            return False
    return True


def has_min_role(min_role, user=None):
    """
    Verifica si el usuario tiene al menos el nivel de rol especificado.

    Args:
        min_role: Rol mínimo requerido
        user: Usuario (por defecto current_user)

    Returns:
        bool: True si tiene el nivel mínimo
    """
    user_roles = get_user_roles(user)
    min_level = ROLE_HIERARCHY.get(min_role.lower(), 0)

    for role in user_roles:
        if ROLE_HIERARCHY.get(role, 0) >= min_level:
            return True

    return False


def is_admin(user=None):
    """Verifica si el usuario es administrador."""
    return has_role('admin', user) or getattr(user or current_user, 'is_super_admin', False)


def is_pm(user=None):
    """Verifica si el usuario es PM o superior."""
    return has_min_role('pm', user)


def is_tecnico(user=None):
    """Verifica si el usuario es técnico o superior."""
    return has_min_role('tecnico', user)


def is_operario(user=None):
    """Verifica si el usuario es operario."""
    return has_role('operario', user)


def _handle_unauthorized(message='No tienes permisos para acceder a esta página.'):
    """
    Maneja respuesta de no autorizado según tipo de request.

    Args:
        message: Mensaje de error

    Returns:
        Response apropiada (JSON o redirect)
    """
    # Si es una petición AJAX o API
    if (request.is_json or
        request.path.startswith('/api/') or
        request.path.startswith('/obras/api/') or
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
        return jsonify({'ok': False, 'error': message}), 403

    # Si es una petición normal
    flash(message, 'danger')

    # Intentar redirigir a una página apropiada
    if current_user.is_authenticated:
        # Operarios van a mis_tareas
        if is_operario():
            return redirect(url_for('obras.mis_tareas'))
        # Otros van al dashboard
        return redirect(url_for('reportes.dashboard'))

    return redirect(url_for('index'))


def require_role(role):
    """
    Decorador que requiere un rol específico.

    Usage:
        @require_role('admin')
        def admin_only():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if not has_role(role):
                return _handle_unauthorized(
                    f'Se requiere rol de {role} para acceder a esta función.'
                )

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_any_role(*roles):
    """
    Decorador que requiere al menos uno de los roles especificados.

    Usage:
        @require_any_role('admin', 'pm', 'tecnico')
        def gestionar():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if not has_any_role(*roles):
                roles_str = ', '.join(roles)
                return _handle_unauthorized(
                    f'Se requiere uno de los siguientes roles: {roles_str}'
                )

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_min_role(min_role):
    """
    Decorador que requiere al menos el nivel de rol especificado.

    Usage:
        @require_min_role('tecnico')  # tecnico, pm, o admin
        def ver_reportes():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if not has_min_role(min_role):
                return _handle_unauthorized(
                    f'Se requiere nivel de {min_role} o superior.'
                )

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_admin(f):
    """
    Decorador que requiere rol de administrador.

    Usage:
        @require_admin
        def admin_panel():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)

        if not is_admin():
            return _handle_unauthorized(
                'Se requieren permisos de administrador.'
            )

        return f(*args, **kwargs)
    return decorated_function


def require_not_operario(f):
    """
    Decorador que bloquea acceso a operarios.
    Útil para funciones de gestión que no deben ver operarios.

    Usage:
        @require_not_operario
        def ver_presupuestos():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)

        user_roles = get_user_roles()

        # Si SOLO es operario (no tiene otros roles)
        if user_roles == {'operario', 'worker'} or user_roles == {'operario'} or user_roles == {'worker'}:
            return _handle_unauthorized(
                'Los operarios no tienen acceso a esta función.'
            )

        return f(*args, **kwargs)
    return decorated_function
