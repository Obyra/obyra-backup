"""
Panel de Superadministrador
============================
Permite a los superadministradores ver datos de todas las organizaciones.
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from functools import wraps

from app import db
from models import (
    Organizacion, Usuario, OrgMembership,
    Obra, Presupuesto, ItemInventario, Cliente, Proveedor
)
from services.memberships import get_current_org_id

superadmin_bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')


def require_super_admin(f):
    """Decorador que requiere que el usuario sea superadmin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Debes iniciar sesión para acceder a esta sección.', 'warning')
            return redirect(url_for('auth.login'))
        if not current_user.is_super_admin:
            flash('No tienes permisos para acceder a esta sección.', 'danger')
            return redirect(url_for('reportes.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@superadmin_bp.route('/')
@login_required
@require_super_admin
def panel():
    """Panel principal del superadmin con resumen de todas las organizaciones"""

    # Obtener todas las organizaciones con estadísticas
    organizaciones = Organizacion.query.order_by(Organizacion.nombre).all()

    org_stats = []
    for org in organizaciones:
        stats = {
            'organizacion': org,
            'usuarios': Usuario.query.filter_by(organizacion_id=org.id).count(),
            'obras': Obra.query.filter_by(organizacion_id=org.id).count(),
            'presupuestos': Presupuesto.query.filter_by(organizacion_id=org.id).count(),
            'items_inventario': ItemInventario.query.filter_by(organizacion_id=org.id, activo=True).count(),
            'clientes': Cliente.query.filter_by(organizacion_id=org.id).count(),
            'proveedores': Proveedor.query.filter_by(organizacion_id=org.id).count() if hasattr(Proveedor, 'organizacion_id') else 0
        }
        org_stats.append(stats)

    # Totales globales
    totales = {
        'organizaciones': len(organizaciones),
        'usuarios': Usuario.query.count(),
        'obras': Obra.query.count(),
        'presupuestos': Presupuesto.query.count(),
        'items_inventario': ItemInventario.query.filter_by(activo=True).count()
    }

    return render_template('superadmin/panel.html',
                          org_stats=org_stats,
                          totales=totales)


@superadmin_bp.route('/organizacion/<int:org_id>')
@login_required
@require_super_admin
def ver_organizacion(org_id):
    """Ver detalles de una organización específica"""

    org = Organizacion.query.get_or_404(org_id)

    # Obtener datos de la organización
    usuarios = Usuario.query.filter_by(organizacion_id=org_id).order_by(Usuario.nombre).all()
    obras = Obra.query.filter_by(organizacion_id=org_id).order_by(Obra.fecha_creacion.desc()).limit(20).all()
    presupuestos = Presupuesto.query.filter_by(organizacion_id=org_id).order_by(Presupuesto.fecha_creacion.desc()).limit(20).all()
    items = ItemInventario.query.filter_by(organizacion_id=org_id, activo=True).order_by(ItemInventario.nombre).all()
    clientes = Cliente.query.filter_by(organizacion_id=org_id).order_by(Cliente.nombre).all()

    return render_template('superadmin/organizacion.html',
                          org=org,
                          usuarios=usuarios,
                          obras=obras,
                          presupuestos=presupuestos,
                          items=items,
                          clientes=clientes)


@superadmin_bp.route('/inventario')
@login_required
@require_super_admin
def inventario_global():
    """Ver inventario de todas las organizaciones"""

    org_filter = request.args.get('org_id', type=int)
    buscar = request.args.get('buscar', '')

    query = ItemInventario.query.filter_by(activo=True)

    if org_filter:
        query = query.filter(ItemInventario.organizacion_id == org_filter)

    if buscar:
        query = query.filter(
            db.or_(
                ItemInventario.codigo.ilike(f'%{buscar}%'),
                ItemInventario.nombre.ilike(f'%{buscar}%')
            )
        )

    items = query.order_by(ItemInventario.organizacion_id, ItemInventario.nombre).all()
    organizaciones = Organizacion.query.order_by(Organizacion.nombre).all()

    return render_template('superadmin/inventario.html',
                          items=items,
                          organizaciones=organizaciones,
                          org_filter=org_filter,
                          buscar=buscar)


@superadmin_bp.route('/obras')
@login_required
@require_super_admin
def obras_global():
    """Ver obras de todas las organizaciones"""

    org_filter = request.args.get('org_id', type=int)

    query = Obra.query

    if org_filter:
        query = query.filter(Obra.organizacion_id == org_filter)

    obras = query.order_by(Obra.fecha_creacion.desc()).all()
    organizaciones = Organizacion.query.order_by(Organizacion.nombre).all()

    return render_template('superadmin/obras.html',
                          obras=obras,
                          organizaciones=organizaciones,
                          org_filter=org_filter)


@superadmin_bp.route('/usuarios')
@login_required
@require_super_admin
def usuarios_global():
    """Ver usuarios de todas las organizaciones"""

    org_filter = request.args.get('org_id', type=int)

    query = Usuario.query

    if org_filter:
        query = query.filter(Usuario.organizacion_id == org_filter)

    usuarios = query.order_by(Usuario.organizacion_id, Usuario.nombre).all()
    organizaciones = Organizacion.query.order_by(Organizacion.nombre).all()

    return render_template('superadmin/usuarios.html',
                          usuarios=usuarios,
                          organizaciones=organizaciones,
                          org_filter=org_filter)


@superadmin_bp.route('/api/stats')
@login_required
@require_super_admin
def api_stats():
    """API para obtener estadísticas globales"""

    stats = {
        'organizaciones': Organizacion.query.count(),
        'usuarios': Usuario.query.count(),
        'obras': Obra.query.count(),
        'presupuestos': Presupuesto.query.count(),
        'items_inventario': ItemInventario.query.filter_by(activo=True).count(),
        'clientes': Cliente.query.count()
    }

    return jsonify(stats)
