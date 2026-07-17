"""
bp_dashboards — 4 dashboards diferenciados por rol
=================================================================
Rutas:
  /dashboard/admin     -> admin (y super_admin)
  /dashboard/pm        -> pm (y admin/super_admin)
  /dashboard/tecnico   -> tecnico (y pm/admin/super_admin)
  /dashboard/operario  -> operario (y admin/super_admin para preview)

Cada ruta valida el rol; si el usuario no corresponde, se lo redirige a
SU propio dashboard (dashboard_endpoint_for) en vez de mostrar un 403 seco.

La logica de datos vive en services.dashboard_service.
"""
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

import services.dashboard_service as ds

dashboards_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


# ---------------------------------------------------------------------------
# Ruteo por rol (usado tambien por app.py para el redirect post-login)
# ---------------------------------------------------------------------------

def dashboard_endpoint_for(user) -> str:
    """Devuelve el endpoint del dashboard que corresponde al rol del usuario."""
    if getattr(user, 'is_super_admin', False):
        return 'dashboard.admin'
    role = (getattr(user, 'role', None) or 'operario').lower()
    return {
        'admin': 'dashboard.admin',
        'pm': 'dashboard.pm',
        'tecnico': 'dashboard.tecnico',
        'operario': 'dashboard.operario',
    }.get(role, 'dashboard.operario')


def _es_admin(user) -> bool:
    return getattr(user, 'is_super_admin', False) or (getattr(user, 'role', None) == 'admin')


def _redirect_a_mi_dashboard():
    return redirect(url_for(dashboard_endpoint_for(current_user)))


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@dashboards_bp.route('/')
@login_required
def index():
    """Dispatcher por rol: redirige al dashboard que corresponde al usuario."""
    return _redirect_a_mi_dashboard()


@dashboards_bp.route('/admin')
@login_required
def admin():
    if not _es_admin(current_user):
        return _redirect_a_mi_dashboard()
    data = ds.data_admin(current_user.organizacion_id)
    return render_template('dashboards/admin.html', **data)


@dashboards_bp.route('/pm')
@login_required
def pm():
    # Admin puede ver el dashboard de PM; el resto solo si es pm.
    if not (_es_admin(current_user) or current_user.role == 'pm'):
        return _redirect_a_mi_dashboard()
    data = ds.data_pm(current_user)
    return render_template('dashboards/pm.html', **data)


@dashboards_bp.route('/tecnico')
@login_required
def tecnico():
    if not (_es_admin(current_user) or current_user.role in ('pm', 'tecnico')):
        return _redirect_a_mi_dashboard()
    data = ds.data_tecnico(current_user)
    return render_template('dashboards/tecnico.html', **data)


@dashboards_bp.route('/operario')
@login_required
def operario():
    # Todos tienen un "mis tareas"; admin puede entrar para preview.
    data = ds.data_operario(current_user)
    return render_template('dashboards/operario.html', **data)
