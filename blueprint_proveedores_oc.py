"""
Blueprint de Proveedores OC - Gestión de proveedores para Órdenes de Compra
CRUD completo + API JSON para autocompletado en formulario de OC
"""
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app)
from flask_login import login_required, current_user
from datetime import datetime
from extensions import db
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


def _es_super_admin():
    """True si el usuario actual es superadmin de OBYRA (cruza tenants)."""
    return bool(getattr(current_user, 'is_super_admin', False))


def _query_visible(org_id):
    """Query base de ProveedorOC visible para el tenant `org_id`.

    El superadmin ve TODO (globales + todos los tenants).
    Cada tenant ve los suyos + los globales (scope='global', org_id NULL).
    """
    from models.proveedores_oc import ProveedorOC
    base = ProveedorOC.query
    if _es_super_admin():
        return base
    return base.filter(
        or_(
            ProveedorOC.scope == 'global',
            ProveedorOC.organizacion_id == org_id,
        )
    )


def _puede_ver(prov, org_id):
    """True si el proveedor es visible para `org_id` (o superadmin)."""
    if _es_super_admin():
        return True
    if prov.scope == 'global':
        return True
    return prov.organizacion_id == org_id


def _puede_editar(prov, org_id):
    """True si el proveedor es editable por el usuario actual.

    - Globales: solo superadmin.
    - Tenant: usuario con permiso de la organizacion duenia.
    """
    if not _tiene_permiso():
        return False
    if prov.scope == 'global':
        return _es_super_admin()
    return prov.organizacion_id == org_id


# ============================================================
# LISTA DE PROVEEDORES
# ============================================================

@proveedores_oc_bp.route('/')
@login_required
def lista():
    from models.proveedores_oc import ProveedorOC, Zona

    if not _tiene_permiso():
        flash('No tiene permisos para acceder a proveedores.', 'danger')
        return redirect(url_for('main.dashboard'))

    org_id = _get_org_id()

    # Filtros
    buscar = request.args.get('buscar', '').strip()
    tipo = request.args.get('tipo', '')
    activo = request.args.get('activo', '')
    scope = request.args.get('scope', '')           # '', 'global', 'tenant'
    zona_id = request.args.get('zona_id', type=int)
    tier = request.args.get('tier', '')
    categoria = request.args.get('categoria', '')

    query = _query_visible(org_id)

    if buscar:
        query = query.filter(
            or_(
                ProveedorOC.razon_social.ilike(f'%{buscar}%'),
                ProveedorOC.nombre_fantasia.ilike(f'%{buscar}%'),
                ProveedorOC.cuit.ilike(f'%{buscar}%'),
                ProveedorOC.contacto_nombre.ilike(f'%{buscar}%'),
                ProveedorOC.categoria.ilike(f'%{buscar}%'),
                ProveedorOC.subcategoria.ilike(f'%{buscar}%'),
            )
        )

    if tipo:
        query = query.filter(ProveedorOC.tipo == tipo)
    if scope in ('global', 'tenant'):
        query = query.filter(ProveedorOC.scope == scope)
    if zona_id:
        query = query.filter(ProveedorOC.zona_id == zona_id)
    if tier:
        query = query.filter(ProveedorOC.tier == tier)
    if categoria:
        query = query.filter(ProveedorOC.categoria == categoria)

    if activo == 'true':
        query = query.filter(ProveedorOC.activo.is_(True))
    elif activo == 'false':
        query = query.filter(ProveedorOC.activo.is_(False))

    query = query.order_by(ProveedorOC.scope.desc(), ProveedorOC.razon_social)

    page = request.args.get('page', 1, type=int)
    proveedores = query.paginate(page=page, per_page=20, error_out=False)

    # Catalogos para los filtros
    zonas = Zona.query.filter_by(activa=True).order_by(Zona.nombre).all()
    categorias = [c[0] for c in db.session.query(ProveedorOC.categoria)
                  .filter(ProveedorOC.categoria.isnot(None))
                  .distinct().order_by(ProveedorOC.categoria).all()]

    return render_template('proveedores_oc/lista.html',
                         proveedores=proveedores.items,
                         pagination=proveedores,
                         buscar=buscar, tipo=tipo, activo=activo,
                         scope=scope, zona_id=zona_id, tier=tier, categoria=categoria,
                         zonas=zonas, categorias=categorias,
                         es_super_admin=_es_super_admin())


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

    org_id = _get_org_id()
    prov = ProveedorOC.query.get_or_404(id)
    if not _puede_ver(prov, org_id):
        flash('No tiene acceso a este proveedor.', 'danger')
        return redirect(url_for('proveedores_oc.lista'))

    # OC vinculadas (solo del propio tenant; si es global no filtramos)
    try:
        oc_query = OrdenCompra.query.filter_by(proveedor_oc_id=prov.id)
        if prov.scope == 'tenant':
            oc_query = oc_query.filter_by(organizacion_id=org_id)
        ordenes = oc_query.order_by(OrdenCompra.created_at.desc()).all()
    except Exception:
        ordenes = []

    # Historial de precios
    try:
        precios = prov.historial_precios.limit(50).all()
    except Exception:
        precios = []

    # Historial de cotizaciones (ganadas, perdidas, todas)
    cotizaciones = []
    try:
        from models.proveedores_oc import CotizacionProveedor
        cotizaciones = CotizacionProveedor.query.filter_by(
            proveedor_oc_id=prov.id
        ).order_by(CotizacionProveedor.created_at.desc()).all()
    except Exception:
        pass

    # Evaluaciones / Scorecard
    evaluaciones = []
    scorecard = None
    try:
        evaluaciones = prov.evaluaciones.order_by(
            db.text('created_at desc')
        ).limit(10).all()
        scorecard = prov.scorecard
    except Exception:
        pass

    # Contactos: del tenant + globales (creados por superadmin) sobre este proveedor.
    # Si soy superadmin veo todos.
    from models.proveedores_oc import ContactoProveedor
    contactos_q = ContactoProveedor.query.filter_by(proveedor_id=prov.id, activo=True)
    if not _es_super_admin():
        contactos_q = contactos_q.filter(
            or_(
                ContactoProveedor.organizacion_id == org_id,
                ContactoProveedor.organizacion_id.is_(None),
            )
        )
    contactos = contactos_q.order_by(
        ContactoProveedor.principal.desc(), ContactoProveedor.nombre
    ).all()

    return render_template('proveedores_oc/detalle.html',
                         proveedor=prov, ordenes=ordenes, precios=precios,
                         cotizaciones=cotizaciones, evaluaciones=evaluaciones,
                         scorecard=scorecard, contactos=contactos,
                         puede_editar=_puede_editar(prov, org_id),
                         es_super_admin=_es_super_admin())


@proveedores_oc_bp.route('/<int:id>/evaluar', methods=['POST'])
@login_required
def evaluar_proveedor(id):
    """Crear evaluación/scorecard de un proveedor."""
    from models.proveedores_oc import ProveedorOC, ProveedorEvaluacion

    if not _tiene_permiso():
        return jsonify(ok=False, error='Sin permisos'), 403

    prov = ProveedorOC.query.get_or_404(id)
    org_id = _get_org_id()
    if not _puede_ver(prov, org_id):
        return jsonify(ok=False, error='Sin acceso'), 403

    data = request.get_json(silent=True) or {}

    def _clamp(val, lo=1, hi=5):
        try:
            return max(lo, min(hi, int(val)))
        except (TypeError, ValueError):
            return 3

    ev = ProveedorEvaluacion(
        proveedor_id=prov.id,
        orden_compra_id=data.get('orden_compra_id') or None,
        evaluador_id=current_user.id,
        organizacion_id=org_id,
        puntaje_entrega=_clamp(data.get('puntaje_entrega', 3)),
        puntaje_precio=_clamp(data.get('puntaje_precio', 3)),
        puntaje_calidad=_clamp(data.get('puntaje_calidad', 3)),
        puntaje_servicio=_clamp(data.get('puntaje_servicio', 3)),
        comentario=(data.get('comentario') or '').strip()[:500],
    )
    db.session.add(ev)
    db.session.commit()

    return jsonify(ok=True, puntaje_promedio=ev.puntaje_promedio)


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

    org_id = _get_org_id()
    prov = ProveedorOC.query.get_or_404(id)
    if not _puede_editar(prov, org_id):
        if prov.scope == 'global':
            flash('Los proveedores del directorio global solo puede editarlos OBYRA.', 'warning')
        else:
            flash('No tiene acceso.', 'danger')
        return redirect(url_for('proveedores_oc.detalle', id=prov.id))

    if request.method == 'POST':
        try:
            razon_social = request.form.get('razon_social', '').strip()
            if not razon_social:
                flash('La razón social es obligatoria.', 'danger')
                return render_template('proveedores_oc/crear.html', proveedor=prov)

            cuit = request.form.get('cuit', '').strip()

            # Verificar CUIT duplicado (excluyendo el actual). Solo aplica entre
            # proveedores del mismo tenant; los globales no compiten.
            if cuit:
                dup_q = ProveedorOC.query.filter(
                    ProveedorOC.cuit == cuit,
                    ProveedorOC.id != prov.id,
                )
                if prov.scope == 'global':
                    dup_q = dup_q.filter(ProveedorOC.scope == 'global')
                else:
                    dup_q = dup_q.filter(ProveedorOC.organizacion_id == org_id)
                existente = dup_q.first()
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
@login_required
def cambiar_estado(id):
    from models.proveedores_oc import ProveedorOC

    if not _tiene_permiso():
        return jsonify({'error': 'Sin permisos'}), 403

    org_id = _get_org_id()
    prov = ProveedorOC.query.get_or_404(id)
    if not _puede_editar(prov, org_id):
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

    proveedores = _query_visible(org_id).filter(
        ProveedorOC.activo.is_(True)
    ).filter(
        or_(
            ProveedorOC.razon_social.ilike(f'%{termino}%'),
            ProveedorOC.nombre_fantasia.ilike(f'%{termino}%'),
            ProveedorOC.cuit.ilike(f'%{termino}%'),
        )
    ).limit(10).all()

    return jsonify([p.to_dict() for p in proveedores])


@proveedores_oc_bp.route('/api/crear-rapido', methods=['POST'])
@login_required
def api_crear_rapido():
    """Crear un proveedor rápido desde cotizaciones u OC."""
    from models.proveedores_oc import ProveedorOC

    org_id = _get_org_id()
    if not org_id:
        return jsonify({'ok': False, 'error': 'Sin organización'}), 400

    data = request.get_json()
    razon_social = (data.get('razon_social') or '').strip()
    if not razon_social:
        return jsonify({'ok': False, 'error': 'Razón social es obligatoria'}), 400

    try:
        prov = ProveedorOC(
            organizacion_id=org_id,
            razon_social=razon_social,
            cuit=(data.get('cuit') or '').strip() or None,
            email=(data.get('email') or '').strip() or None,
            telefono=(data.get('telefono') or '').strip() or None,
            activo=True
        )
        db.session.add(prov)
        db.session.commit()

        return jsonify({
            'ok': True,
            'id': prov.id,
            'razon_social': prov.razon_social,
            'cuit': prov.cuit or ''
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@proveedores_oc_bp.route('/api/<int:id>')
@login_required
def api_detalle(id):
    """Datos completos de un proveedor (para rellenar form OC al seleccionar)."""
    from models.proveedores_oc import ProveedorOC

    prov = ProveedorOC.query.get_or_404(id)
    if not _puede_ver(prov, _get_org_id()):
        return jsonify({'error': 'No autorizado'}), 403

    return jsonify(prov.to_dict())


@proveedores_oc_bp.route('/api/<int:id>/editar-contacto', methods=['POST'])
@login_required
def api_editar_contacto(id):
    """Editar inline el telefono y/o email del proveedor.

    Usado desde pantallas como "Recursos a cotizar" cuando falta el dato
    y se necesita arreglarlo sin ir al formulario completo del proveedor.
    Acepta cualquiera de los dos (no necesariamente ambos).
    """
    from models.proveedores_oc import ProveedorOC

    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    org_id = _get_org_id()
    prov = ProveedorOC.query.get_or_404(id)
    if not _puede_editar(prov, org_id):
        return jsonify({'ok': False, 'error': 'Los proveedores globales solo los edita OBYRA'}), 403

    data = request.get_json(silent=True) or {}
    telefono = data.get('telefono')
    email = data.get('email')

    if telefono is None and email is None:
        return jsonify({'ok': False, 'error': 'Al menos uno de telefono o email'}), 400

    if telefono is not None:
        telefono = (telefono or '').strip()[:50]
        prov.telefono = telefono or None
    if email is not None:
        email = (email or '').strip()[:200]
        prov.email = email or None

    try:
        db.session.commit()
        return jsonify({
            'ok': True,
            'telefono': prov.telefono,
            'email': prov.email,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@proveedores_oc_bp.route('/api/crear', methods=['POST'])
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
    if not _puede_ver(prov, _get_org_id()):
        return jsonify({'error': 'No autorizado'}), 403

    precios = prov.historial_precios.limit(50).all()
    return jsonify([p.to_dict() for p in precios])


# ============================================================
# CONTACTOS DE PROVEEDOR (multi-contacto, scoped por tenant)
# ============================================================

@proveedores_oc_bp.route('/<int:id>/contactos', methods=['POST'])
@login_required
def crear_contacto(id):
    """Agrega un contacto a un proveedor.

    Reglas:
      - Cualquier usuario con permiso puede agregar contactos sobre proveedores
        que ve (propios o globales). El contacto queda scopeado a su tenant.
      - Si el usuario es superadmin, puede crear el contacto como global
        (sin organizacion_id, visible a todos los tenants).
    """
    from models.proveedores_oc import ProveedorOC, ContactoProveedor

    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    org_id = _get_org_id()
    prov = ProveedorOC.query.get_or_404(id)
    if not _puede_ver(prov, org_id):
        return jsonify({'ok': False, 'error': 'Sin acceso'}), 403

    data = request.get_json(silent=True) or request.form
    nombre = (data.get('nombre') or '').strip()
    if not nombre:
        return jsonify({'ok': False, 'error': 'Nombre obligatorio'}), 400

    es_global = bool(data.get('global')) and _es_super_admin()
    contacto = ContactoProveedor(
        proveedor_id=prov.id,
        organizacion_id=None if es_global else org_id,
        nombre=nombre[:200],
        cargo=(data.get('cargo') or '').strip()[:120] or None,
        email=(data.get('email') or '').strip()[:200] or None,
        telefono=(data.get('telefono') or '').strip()[:50] or None,
        whatsapp=(data.get('whatsapp') or '').strip()[:50] or None,
        notas=(data.get('notas') or '').strip() or None,
        principal=bool(data.get('principal')),
        activo=True,
        created_by_id=current_user.id,
    )

    # Si se marca como principal, desmarcar el resto del mismo scope
    if contacto.principal:
        siblings = ContactoProveedor.query.filter_by(
            proveedor_id=prov.id, organizacion_id=contacto.organizacion_id
        ).all()
        for s in siblings:
            s.principal = False

    try:
        db.session.add(contacto)
        db.session.commit()
        return jsonify({'ok': True, 'contacto': contacto.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error creando contacto: {e}')
        return jsonify({'ok': False, 'error': 'Error al crear el contacto'}), 500


def _puede_modificar_contacto(contacto, org_id):
    """True si el usuario actual puede editar/borrar este contacto."""
    if _es_super_admin():
        return True
    # Tenant solo puede tocar sus propios contactos (no los globales del catalogo)
    return contacto.organizacion_id == org_id


@proveedores_oc_bp.route('/<int:proveedor_id>/contactos/<int:contacto_id>', methods=['POST'])
@login_required
def editar_contacto(proveedor_id, contacto_id):
    """Editar un contacto. Devuelve JSON."""
    from models.proveedores_oc import ContactoProveedor

    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    org_id = _get_org_id()
    contacto = ContactoProveedor.query.get_or_404(contacto_id)
    if contacto.proveedor_id != proveedor_id:
        return jsonify({'ok': False, 'error': 'Contacto no pertenece a ese proveedor'}), 400
    if not _puede_modificar_contacto(contacto, org_id):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    data = request.get_json(silent=True) or request.form
    if 'nombre' in data:
        contacto.nombre = (data.get('nombre') or '').strip()[:200] or contacto.nombre
    if 'cargo' in data:
        contacto.cargo = (data.get('cargo') or '').strip()[:120] or None
    if 'email' in data:
        contacto.email = (data.get('email') or '').strip()[:200] or None
    if 'telefono' in data:
        contacto.telefono = (data.get('telefono') or '').strip()[:50] or None
    if 'whatsapp' in data:
        contacto.whatsapp = (data.get('whatsapp') or '').strip()[:50] or None
    if 'notas' in data:
        contacto.notas = (data.get('notas') or '').strip() or None
    if 'principal' in data:
        nuevo_principal = bool(data.get('principal'))
        if nuevo_principal and not contacto.principal:
            siblings = ContactoProveedor.query.filter(
                ContactoProveedor.proveedor_id == contacto.proveedor_id,
                ContactoProveedor.organizacion_id == contacto.organizacion_id,
                ContactoProveedor.id != contacto.id,
            ).all()
            for s in siblings:
                s.principal = False
        contacto.principal = nuevo_principal

    try:
        db.session.commit()
        return jsonify({'ok': True, 'contacto': contacto.to_dict()})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error editando contacto: {e}')
        return jsonify({'ok': False, 'error': 'Error al editar el contacto'}), 500


@proveedores_oc_bp.route('/<int:proveedor_id>/contactos/<int:contacto_id>/eliminar', methods=['POST'])
@login_required
def eliminar_contacto(proveedor_id, contacto_id):
    """Soft delete (activo=False) del contacto."""
    from models.proveedores_oc import ContactoProveedor

    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    org_id = _get_org_id()
    contacto = ContactoProveedor.query.get_or_404(contacto_id)
    if contacto.proveedor_id != proveedor_id:
        return jsonify({'ok': False, 'error': 'Contacto no pertenece a ese proveedor'}), 400
    if not _puede_modificar_contacto(contacto, org_id):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    contacto.activo = False
    try:
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error eliminando contacto: {e}')
        return jsonify({'ok': False, 'error': 'Error al eliminar'}), 500
