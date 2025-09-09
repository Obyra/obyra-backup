# utils/permissions.py - Helper de permisos para sistema RBAC

def is_admin_or_pm(user):
    """Verificar si el usuario es admin o project manager"""
    return getattr(user, "role", None) in ("admin", "pm")

def is_operario(user):
    """Verificar si el usuario es operario"""
    return getattr(user, "role", None) == "operario"

def get_home_route_for_user(user):
    """Obtener la ruta home apropiada según el rol del usuario"""
    if is_operario(user):
        return "obras.mis_tareas"
    return "reportes.dashboard"  # Admin y PM van al dashboard

def can_approve_avance(user, avance):
    """Verificar si el usuario puede aprobar un avance"""
    return is_admin_or_pm(user) and user.id != avance.user_id