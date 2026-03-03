"""
Blueprint de Proveedores OC - Gestión de proveedores para Órdenes de Compra
CRUD completo + API JSON para autocompletado en formulario de OC
"""
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app)
from flask_login import login_required, current_user
from datetime import datetime
from extensions import db, csrf
from sqlalchemy import or_

proveedores_oc_bp = Blueprint('proveedores_oc', __name__, url_prefix='/proveedores-oc')


def _tiene_permiso():
    """Verifica si el usuario puede gestionar proveedores (admin o PM)."""
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm')


def _get_org_id():
    """Obtiene org_id del usuario actual."""
    return getattr(current_user, 'organizacion_id', None)


# ============================================================
# LISTA DE PROVEEDORES
# ============================================================

@proveedores_oc_bp.route('/')
@login_required
def lista():
    from models.proveedores_oc import ProveedorOC

    if not _tiene_permiso():
        flash('No tiene permisos para acceder a proveedores.', 'danger')
        return redirect(url_for('main.dashboard'))

    org_id = _get_org_id()

    # Filtros
    buscar = request.args.get('buscar', '').strip()
    tipo = request.args.get('tipo', '')
    activo = request.args.get('activo', '')

    query = ProveedorOC.query.filter_by(organizacion_id=org_id)

    if buscar:
        query = query.filter(
            or_(
                ProveedorOC.razon_social.ilike(f'%{buscar}%'),
                ProveedorOC.nombre_fantasia.ilike(f'%{buscar}%'),
                ProveedorOC.cuit.ilike(f'%{buscar}%'),
                ProveedorOC.contacto_nombre.ilike(f'%{buscar}%'),
            )
        )

    if tipo:
        query = query.filter_by(tipo=tipo)

    if activo == 'true':
        query = query.filter_by(activo=True)
    elif activo == 'false':
        query = query.filter_by(activo=False)

    query = query.order_by(ProveedorOC.razon_social)

    page = request.args.get('page', 1, type=int)
    proveedores = query.paginate(page=page, per_page=20, error_out=False)

    return render_template('proveedores_oc/lista.html',
                         proveedores=proveedores.items,
                         pagination=proveedores,
                         buscar=buscar, tipo=tipo, activo=activo)


# ============================================================
# CREAR PROVEEDOR
# ============================================================

@proveedores_oc_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def crear():
    from models.proveedores_oc import ProveedorOC

    if not _tiene_permiso():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('proveedores_oc.lista'))

    org_id = _get_org_id()

    if request.method == 'POST':
        try:
            razon_social = request.form.get('razon_social', '').strip()
            if not razon_social:
                flash('La razón social es obligatoria.', 'danger')
                return redirect(url_for('proveedores_oc.crear'))

            cuit = request.form.get('cuit', '').strip()

            # Verificar CUIT duplicado si se proporcionó
            if cuit:
                existente = ProveedorOC.query.filter_by(
                    organizacion_id=org_id, cuit=cuit
                ).first()
                if existente:
                    flash(f'Ya existe un proveedor con CUIT {cuit}.', 'warning')
                    return redirect(url_for('proveedores_oc.crear'))

            prov = ProveedorOC(
                organizacion_id=org_id,
                razon_social=razon_social,
                nombre_fantasia=request.form.get('nombre_fantasia', '').strip() or None,
                cuit=cuit or None,
                tipo=request.form.get('tipo', 'materiales'),
                email=request.form.get('email', '').strip() or None,
                telefono=request.form.get('telefono', '').strip() or None,
                direccion=request.form.get('direccion', '').strip() or None,
                ciudad=request.form.get('ciudad', '').strip() or None,
                provincia=request.form.get('provincia', '').strip() or None,
                contacto_nombre=request.form.get('contacto_nombre', '').strip() or None,
                contacto_telefono=request.form.get('contacto_telefono', '').strip() or None,
                condicion_pago=request.form.get('condicion_pago', '').strip() or None,
                notas=request.form.get('notas', '').strip() or None,
                created_by_id=current_user.id,
            )
            db.session.add(prov)
            db.session.commit()

            flash(f'Proveedor "{prov.razon_social}" creado exitosamente.', 'success')
            return redirect(url_for('proveedores_oc.detalle', id=prov.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creando proveedor OC: {e}")
            flash('Error al crear el proveedor.', 'danger')
            return redirect(url_for('proveedores_oc.crear'))

    return render_template('proveedores_oc/crear.html', proveedor=None)


# ============================================================
# DETALLE PROVEEDOR
# ============================================================

@proveedores_oc_bp.route('/<int:id>')
@login_required
def detalle(id):
    from models.proveedores_oc import ProveedorOC
    from models.inventory import OrdenCompra

    if not _tiene_permiso():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('main.dashboard'))

    prov = ProveedorOC.query.get_or_404(id)
    if prov.organizacion_id != _get_org_id():
        flash('No tiene acceso a este proveedor.', 'danger')
        return redirect(url_for('proveedores_oc.lista'))

    # OC vinculadas
    ordenes = OrdenCompra.query.filter_by(
        proveedor_oc_id=prov.id
    ).order_by(OrdenCompra.created_at.desc()).all()

    # Historial de precios
    precios = prov.historial_precios.limit(50).all()

    return render_template('proveedores_oc/detalle.html',
                         proveedor=prov, ordenes=ordenes, precios=precios)


# ============================================================
# EDITAR PROVEEDOR
# ============================================================

@proveedores_oc_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar(id):
    from models.proveedores_oc import ProveedorOC

    if not _tiene_permiso():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('proveedores_oc.lista'))

    prov = ProveedorOC.query.get_or_404(id)
    if prov.organizacion_id != _get_org_id():
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('proveedores_oc.lista'))

    if request.method == 'POST':
        try:
            razon_social = request.form.get('razon_social', '').strip()
            if not razon_social:
                flash('La razón social es obligatoria.', 'danger')
                return render_template('proveedores_oc/crear.html', proveedor=prov)

            cuit = request.form.get('cuit', '').strip()

            # Verificar CUIT duplicado (excluyendo el actual)
            if cuit:
                existente = ProveedorOC.query.filter(
                    ProveedorOC.organizacion_id == _get_org_id(),
                    ProveedorOC.cuit == cuit,
                    ProveedorOC.id != prov.id
                ).first()
                if existente:
                    flash(f'Ya existe otro proveedor con CUIT {cuit}.', 'warning')
                    return render_template('proveedores_oc/crear.html', proveedor=prov)

            prov.razon_social = razon_social
            prov.nombre_fantasia = request.form.get('nombre_fantasia', '').strip() or None
            prov.cuit = cuit or None
            prov.tipo = request.form.get('tipo', 'materiales')
            prov.email = request.form.get('email', '').strip() or None
            prov.telefono = request.form.get('telefono', '').strip() or None
            prov.direccion = request.form.get('direccion', '').strip() or None
            prov.ciudad = request.form.get('ciudad', '').strip() or None
            prov.provincia = request.form.get('provincia', '').strip() or None
            prov.contacto_nombre = request.form.get('contacto_nombre', '').strip() or None
            prov.contacto_telefono = request.form.get('contacto_telefono', '').strip() or None
            prov.condicion_pago = request.form.get('condicion_pago', '').strip() or None
            prov.notas = request.form.get('notas', '').strip() or None
            prov.updated_at = datetime.utcnow()

            db.session.commit()
            flash(f'Proveedor "{prov.razon_social}" actualizado.', 'success')
            return redirect(url_for('proveedores_oc.detalle', id=prov.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editando proveedor OC: {e}")
            flash('Error al actualizar el proveedor.', 'danger')

    return render_template('proveedores_oc/crear.html', proveedor=prov)


# ============================================================
# CAMBIAR ESTADO (ACTIVAR/DESACTIVAR)
# ============================================================

@proveedores_oc_bp.route('/<int:id>/cambiar-estado', methods=['POST'])
@csrf.exempt
@login_required
def cambiar_estado(id):
    from models.proveedores_oc import ProveedorOC

    if not _tiene_permiso():
        return jsonify({'error': 'Sin permisos'}), 403

    prov = ProveedorOC.query.get_or_404(id)
    if prov.organizacion_id != _get_org_id():
        return jsonify({'error': 'No autorizado'}), 403

    prov.activo = not prov.activo
    prov.updated_at = datetime.utcnow()
    db.session.commit()

    estado_txt = 'activado' if prov.activo else 'desactivado'
    return jsonify({
        'ok': True,
        'mensaje': f'Proveedor {prov.razon_social} {estado_txt}',
        'activo': prov.activo
    })


# ============================================================
# API JSON — Búsqueda / Autocompletado para OC
# ============================================================

@proveedores_oc_bp.route('/api/buscar')
@login_required
def api_buscar():
    """Buscar proveedores activos por texto (para autocompletado en OC)."""
    from models.proveedores_oc import ProveedorOC

    org_id = _get_org_id()
    termino = request.args.get('q', '').strip()

    if len(termino) < 2:
        return jsonify([])

    proveedores = ProveedorOC.query.filter_by(
        organizacion_id=org_id, activo=True
    ).filter(
        or_(
            ProveedorOC.razon_social.ilike(f'%{termino}%'),
            ProveedorOC.nombre_fantasia.ilike(f'%{termino}%'),
            ProveedorOC.cuit.ilike(f'%{termino}%'),
        )
    ).limit(10).all()

    return jsonify([p.to_dict() for p in proveedores])


@proveedores_oc_bp.route('/api/<int:id>')
@login_required
def api_detalle(id):
    """Datos completos de un proveedor (para rellenar form OC al seleccionar)."""
    from models.proveedores_oc import ProveedorOC

    prov = ProveedorOC.query.get_or_404(id)
    if prov.organizacion_id != _get_org_id():
        return jsonify({'error': 'No autorizado'}), 403

    return jsonify(prov.to_dict())


@proveedores_oc_bp.route('/api/crear', methods=['POST'])
@csrf.exempt
@login_required
def api_crear():
    """Crear proveedor inline desde modal en OC (retorna JSON)."""
    from models.proveedores_oc import ProveedorOC

    if not _tiene_permiso():
        return jsonify({'error': 'Sin permisos'}), 403

    org_id = _get_org_id()
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Datos JSON requeridos'}), 400

    razon_social = (data.get('razon_social') or '').strip()
    if not razon_social:
        return jsonify({'error': 'Razón social es obligatoria'}), 400

    cuit = (data.get('cuit') or '').strip()

    # Verificar CUIT duplicado
    if cuit:
        existente = ProveedorOC.query.filter_by(
            organizacion_id=org_id, cuit=cuit
        ).first()
        if existente:
            return jsonify({'error': f'Ya existe un proveedor con CUIT {cuit}'}), 400

    try:
        prov = ProveedorOC(
            organizacion_id=org_id,
            razon_social=razon_social,
            nombre_fantasia=(data.get('nombre_fantasia') or '').strip() or None,
            cuit=cuit or None,
            tipo=data.get('tipo', 'materiales'),
            email=(data.get('email') or '').strip() or None,
            telefono=(data.get('telefono') or '').strip() or None,
            contacto_nombre=(data.get('contacto_nombre') or '').strip() or None,
            condicion_pago=(data.get('condicion_pago') or '').strip() or None,
            created_by_id=current_user.id,
        )
        db.session.add(prov)
        db.session.commit()

        return jsonify({
            'success': True,
            'proveedor': prov.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en api_crear proveedor: {e}")
        return jsonify({'error': 'Error al crear proveedor'}), 500


@proveedores_oc_bp.route('/api/<int:id>/precios')
@login_required
def api_precios(id):
    """Historial de precios de un proveedor."""
    from models.proveedores_oc import ProveedorOC

    prov = ProveedorOC.query.get_or_404(id)
    if prov.organizacion_id != _get_org_id():
        return jsonify({'error': 'No autorizado'}), 403

    precios = prov.historial_precios.limit(50).all()
    return jsonify([p.to_dict() for p in precios])
