"""Blueprint de Categorias de Jornal (mano de obra).

Catalogo hibrido:
  - Categorias globales (organizacion_id IS NULL): curadas por OBYRA superadmin,
    visibles a todos los tenants.
  - Categorias por tenant: cargadas por la propia constructora.

Cada constructora ve: globales + propias. Solo el superadmin edita las globales.
Cada tenant edita las propias.

Endpoints:
  GET  /jornales                        -> pagina HTML con la tabla
  GET  /jornales/api                    -> JSON con jornales visibles
  POST /jornales                        -> crear (form o JSON)
  POST /jornales/<id>                   -> editar (form o JSON)
  POST /jornales/<id>/eliminar          -> soft delete
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from datetime import date

from extensions import db
from services.memberships import get_current_org_id


jornales_bp = Blueprint('jornales', __name__, url_prefix='/jornales')


def _es_super_admin():
    return bool(getattr(current_user, 'is_super_admin', False))


def _tiene_permiso():
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm')


def _puede_editar(cat, org_id):
    if cat.is_global:
        return _es_super_admin()
    return cat.organizacion_id == org_id


def _query_visible(org_id):
    from models.budgets import CategoriaJornal
    from sqlalchemy import or_
    base = CategoriaJornal.query.filter_by(activo=True)
    if _es_super_admin():
        return base
    return base.filter(or_(
        CategoriaJornal.organizacion_id.is_(None),
        CategoriaJornal.organizacion_id == org_id,
    ))


@jornales_bp.route('/')
@login_required
def lista():
    if not _tiene_permiso():
        flash('No tiene permisos para ver categorias de jornal.', 'danger')
        return redirect(url_for('main.dashboard'))

    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    cats = _query_visible(org_id).order_by(
        CategoriaJornal.organizacion_id.asc().nullsfirst(),  # globales primero
        CategoriaJornal.nombre,
    ).all()
    return render_template('jornales/lista.html',
                           jornales=cats,
                           es_super_admin=_es_super_admin(),
                           org_id=org_id)


@jornales_bp.route('/api')
@login_required
def api_lista():
    """JSON con jornales visibles - usado por el modal de MO en presupuestos."""
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    cats = _query_visible(org_id).order_by(
        CategoriaJornal.organizacion_id.asc().nullsfirst(),
        CategoriaJornal.nombre,
    ).all()
    return jsonify({'ok': True, 'jornales': [c.to_dict() for c in cats]})


@jornales_bp.route('/', methods=['POST'])
@login_required
def crear():
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    data = request.get_json(silent=True) or request.form

    nombre = (data.get('nombre') or '').strip()
    if not nombre:
        return jsonify({'ok': False, 'error': 'Nombre obligatorio'}), 400

    try:
        precio = float(data.get('precio_jornal') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Precio jornal invalido'}), 400

    es_global = bool(data.get('global')) and _es_super_admin()
    cat = CategoriaJornal(
        organizacion_id=None if es_global else org_id,
        nombre=nombre[:120],
        codigo=(data.get('codigo') or '').strip()[:40] or None,
        precio_jornal=precio,
        moneda=(data.get('moneda') or 'ARS').strip()[:3].upper(),
        fuente=(data.get('fuente') or 'manual').strip()[:40],
        notas=(data.get('notas') or '').strip() or None,
        vigencia_desde=date.today(),
        activo=True,
        created_by_id=current_user.id,
    )

    try:
        db.session.add(cat)
        db.session.commit()
        return jsonify({'ok': True, 'categoria': cat.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error creando categoria jornal')
        return jsonify({'ok': False, 'error': str(e)}), 500


@jornales_bp.route('/<int:id>', methods=['POST'])
@login_required
def editar(id):
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    cat = CategoriaJornal.query.get_or_404(id)
    if not _puede_editar(cat, org_id):
        return jsonify({'ok': False, 'error': 'Esta categoria es global y solo la edita OBYRA'}), 403

    data = request.get_json(silent=True) or request.form
    if 'nombre' in data:
        cat.nombre = (data.get('nombre') or '').strip()[:120] or cat.nombre
    if 'codigo' in data:
        cat.codigo = (data.get('codigo') or '').strip()[:40] or None
    if 'precio_jornal' in data:
        try:
            cat.precio_jornal = float(data.get('precio_jornal') or 0)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Precio jornal invalido'}), 400
    if 'moneda' in data:
        cat.moneda = (data.get('moneda') or 'ARS').strip()[:3].upper()
    if 'notas' in data:
        cat.notas = (data.get('notas') or '').strip() or None
    if 'fuente' in data:
        cat.fuente = (data.get('fuente') or 'manual').strip()[:40]

    cat.vigencia_desde = date.today()

    try:
        db.session.commit()
        return jsonify({'ok': True, 'categoria': cat.to_dict()})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error editando categoria jornal')
        return jsonify({'ok': False, 'error': str(e)}), 500


@jornales_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar(id):
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    cat = CategoriaJornal.query.get_or_404(id)
    if not _puede_editar(cat, org_id):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    cat.activo = False
    try:
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
