"""Funciones de verificación de permisos para OBYRA IA."""


def is_admin_or_pm(user) -> bool:
    """Verifica si el usuario tiene rol de administrador o PM."""
    role = getattr(user, 'role', None)
    if role and role.lower() in ('admin', 'pm'):
        return True
    rol = getattr(user, 'rol', None)
    if rol and rol.lower() in ('administrador', 'admin', 'tecnico', 'project_manager', 'pm'):
        return True
    return False
