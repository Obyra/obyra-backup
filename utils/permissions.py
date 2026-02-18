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


def can_approve_avance(user, avance) -> bool:
    """Verifica si el usuario puede aprobar/rechazar un avance."""
    if not is_admin_or_pm(user):
        return False
    # Verificar que el avance pertenece a la misma organización
    try:
        obra_org_id = avance.tarea.etapa.obra.organizacion_id
        user_org_id = getattr(user, 'organizacion_id', None)
        if obra_org_id and user_org_id and obra_org_id == user_org_id:
            return True
        # Fallback: verificar membresía activa
        from services.memberships import get_current_org_id
        current_org = get_current_org_id()
        if current_org and obra_org_id == current_org:
            return True
    except Exception:
        pass
    return False
