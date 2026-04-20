"""Presupuesto Ejecutivo (APU).

Vista interna donde cada item del pliego se descompone en MO + materiales + equipos.
El cliente ve solo el presupuesto comercial; el ejecutivo es uso interno para
calcular costo estimado y margen por etapa antes de pasar a obra.

Rutas:
  GET  /presupuestos/<id>/ejecutivo           -> vista principal con items agrupados por etapa
"""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from flask import render_template, redirect, url_for, flash, abort, request, jsonify
from flask_login import login_required, current_user

from blueprint_presupuestos import presupuestos_bp
from extensions import db
from models import Presupuesto, ItemPresupuesto, ItemPresupuestoComposicion
from services.memberships import get_current_org_id


TIPOS_COMPOSICION = ('material', 'mano_obra', 'equipo')


ESTADOS_EDITABLES_EJECUTIVO = ('borrador', 'enviado', 'aprobado')


def _puede_ver_ejecutivo(presupuesto):
    """El ejecutivo es interno: solo admin/PM."""
    if not current_user.is_authenticated:
        return False
    rol = getattr(current_user, 'role', '') or ''
    return rol in ('admin', 'administrador', 'pm', 'project_manager')


@presupuestos_bp.route('/<int:id>/ejecutivo')
@login_required
def ejecutivo_vista(id):
    """Vista del presupuesto ejecutivo: items del pliego agrupados por etapa."""
    org_id = get_current_org_id()
    if not org_id:
        flash('Seleccioná una organización.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion'))

    presupuesto = Presupuesto.query.filter_by(
        id=id, organizacion_id=org_id,
    ).first_or_404()

    if not _puede_ver_ejecutivo(presupuesto):
        abort(403)

    if presupuesto.estado not in ESTADOS_EDITABLES_EJECUTIVO:
        flash(
            f'El presupuesto ejecutivo solo está disponible para presupuestos '
            f'en estado borrador, enviado o aprobado (actual: {presupuesto.estado}).',
            'warning',
        )
        return redirect(url_for('presupuestos.detalle', id=id))

    # Traer items ordenados por etapa_nombre para agrupar en el template
    items = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
    ).order_by(
        ItemPresupuesto.etapa_nombre,
        ItemPresupuesto.id,
    ).all()

    # Agrupar por etapa preservando orden natural.
    # Pre-cargamos las composiciones ordenadas como atributo comp_list
    # para evitar queries repetidas y order_by dentro del template.
    etapas = OrderedDict()
    for item in items:
        nombre_etapa = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Sin etapa')

        comp_list = item.composiciones.order_by(
            ItemPresupuestoComposicion.tipo,
            ItemPresupuestoComposicion.id,
        ).all()
        item.comp_list = comp_list
        costo_item = sum((Decimal(str(c.total or 0)) for c in comp_list), Decimal('0'))
        item.costo_estimado = costo_item

        if nombre_etapa not in etapas:
            etapas[nombre_etapa] = {
                'items': [],
                'total_vendido': Decimal('0'),
                'total_costo': Decimal('0'),
            }
        etapas[nombre_etapa]['items'].append(item)
        etapas[nombre_etapa]['total_vendido'] += Decimal(str(item.total or 0))
        etapas[nombre_etapa]['total_costo'] += costo_item

    total_vendido = sum((d['total_vendido'] for d in etapas.values()), Decimal('0'))
    total_costo = sum((d['total_costo'] for d in etapas.values()), Decimal('0'))
    margen = total_vendido - total_costo
    margen_pct = (margen / total_vendido * 100) if total_vendido > 0 else Decimal('0')

    return render_template(
        'presupuestos/ejecutivo.html',
        presupuesto=presupuesto,
        etapas=etapas,
        total_vendido=total_vendido,
        total_costo=total_costo,
        margen=margen,
        margen_pct=margen_pct,
    )


def _parse_decimal(val, default='0'):
    try:
        return Decimal(str(val).replace(',', '.'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _item_pertenece_a_org(item, org_id):
    """Valida que el item pertenezca a un presupuesto de la org activa."""
    return bool(item and item.presupuesto and item.presupuesto.organizacion_id == org_id)


def _serializar_composicion(comp):
    return {
        'id': comp.id,
        'tipo': comp.tipo,
        'descripcion': comp.descripcion,
        'unidad': comp.unidad,
        'cantidad': float(comp.cantidad or 0),
        'precio_unitario': float(comp.precio_unitario or 0),
        'total': float(comp.total or 0),
        'item_inventario_id': comp.item_inventario_id,
        'modalidad_costo': comp.modalidad_costo,
        'notas': comp.notas,
    }


@presupuestos_bp.route('/items/<int:item_id>/composicion', methods=['POST'])
@login_required
def composicion_crear(item_id):
    """Crea una composición (material/mano_obra/equipo) dentro de un item del pliego."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    item = ItemPresupuesto.query.get_or_404(item_id)
    if not _item_pertenece_a_org(item, org_id):
        return jsonify(ok=False, error='Item no pertenece a tu organización'), 403

    if item.presupuesto.estado not in ESTADOS_EDITABLES_EJECUTIVO:
        return jsonify(
            ok=False,
            error=f'No se puede editar el ejecutivo en estado {item.presupuesto.estado}',
        ), 400

    data = request.get_json(silent=True) or request.form.to_dict()

    tipo = (data.get('tipo') or '').strip().lower()
    if tipo not in TIPOS_COMPOSICION:
        return jsonify(ok=False, error=f'Tipo inválido. Usá uno de: {", ".join(TIPOS_COMPOSICION)}'), 400

    descripcion = (data.get('descripcion') or '').strip()
    if not descripcion:
        return jsonify(ok=False, error='La descripción es obligatoria'), 400

    unidad = (data.get('unidad') or '').strip() or 'un'
    cantidad = _parse_decimal(data.get('cantidad'), '0')
    precio = _parse_decimal(data.get('precio_unitario'), '0')

    if cantidad < 0 or precio < 0:
        return jsonify(ok=False, error='Cantidad y precio no pueden ser negativos'), 400

    item_inventario_id = data.get('item_inventario_id')
    try:
        item_inventario_id = int(item_inventario_id) if item_inventario_id else None
    except (ValueError, TypeError):
        item_inventario_id = None

    # Modalidad de costo: solo aplica a equipos (compra | alquiler).
    modalidad = (data.get('modalidad_costo') or '').strip().lower() or None
    if tipo == 'equipo' and modalidad not in ('compra', 'alquiler', None):
        return jsonify(ok=False, error='Modalidad de equipo inválida (usá compra o alquiler)'), 400
    if tipo != 'equipo':
        modalidad = None

    comp = ItemPresupuestoComposicion(
        item_presupuesto_id=item.id,
        tipo=tipo,
        descripcion=descripcion[:300],
        unidad=unidad[:20],
        cantidad=cantidad,
        precio_unitario=precio,
        total=cantidad * precio,
        item_inventario_id=item_inventario_id,
        modalidad_costo=modalidad,
        notas=(data.get('notas') or None),
    )
    db.session.add(comp)
    db.session.commit()

    return jsonify(ok=True, composicion=_serializar_composicion(comp))


@presupuestos_bp.route('/composicion/<int:comp_id>', methods=['PUT', 'PATCH'])
@login_required
def composicion_actualizar(comp_id):
    """Edita una composición existente."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    comp = ItemPresupuestoComposicion.query.get_or_404(comp_id)
    if not _item_pertenece_a_org(comp.item_presupuesto, org_id):
        return jsonify(ok=False, error='Composición no pertenece a tu organización'), 403

    if comp.item_presupuesto.presupuesto.estado not in ESTADOS_EDITABLES_EJECUTIVO:
        return jsonify(
            ok=False,
            error=f'No se puede editar el ejecutivo en estado {comp.item_presupuesto.presupuesto.estado}',
        ), 400

    data = request.get_json(silent=True) or request.form.to_dict()

    # Validar tipo solo si se envía (en edición puede no cambiar)
    if 'tipo' in data:
        nuevo_tipo = (data.get('tipo') or '').strip().lower()
        if nuevo_tipo not in TIPOS_COMPOSICION:
            return jsonify(ok=False, error='Tipo inválido'), 400
        comp.tipo = nuevo_tipo

    if 'descripcion' in data:
        desc = (data.get('descripcion') or '').strip()
        if not desc:
            return jsonify(ok=False, error='La descripción es obligatoria'), 400
        comp.descripcion = desc[:300]

    if 'unidad' in data:
        comp.unidad = ((data.get('unidad') or 'un').strip() or 'un')[:20]

    if 'cantidad' in data:
        cantidad = _parse_decimal(data.get('cantidad'), '0')
        if cantidad < 0:
            return jsonify(ok=False, error='Cantidad no puede ser negativa'), 400
        comp.cantidad = cantidad

    if 'precio_unitario' in data:
        precio = _parse_decimal(data.get('precio_unitario'), '0')
        if precio < 0:
            return jsonify(ok=False, error='Precio no puede ser negativo'), 400
        comp.precio_unitario = precio

    # Modalidad aplica solo a equipos; si el tipo final no es equipo, la blanqueamos.
    if comp.tipo == 'equipo':
        if 'modalidad_costo' in data:
            modalidad = (data.get('modalidad_costo') or '').strip().lower() or None
            if modalidad not in ('compra', 'alquiler', None):
                return jsonify(ok=False, error='Modalidad inválida'), 400
            comp.modalidad_costo = modalidad
    else:
        comp.modalidad_costo = None

    if 'notas' in data:
        comp.notas = (data.get('notas') or None)

    comp.recalcular_total()
    db.session.commit()

    return jsonify(ok=True, composicion=_serializar_composicion(comp))


@presupuestos_bp.route('/composicion/<int:comp_id>', methods=['DELETE'])
@login_required
def composicion_eliminar(comp_id):
    """Elimina una composición del ejecutivo."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    comp = ItemPresupuestoComposicion.query.get_or_404(comp_id)
    if not _item_pertenece_a_org(comp.item_presupuesto, org_id):
        return jsonify(ok=False, error='Composición no pertenece a tu organización'), 403

    if comp.item_presupuesto.presupuesto.estado not in ESTADOS_EDITABLES_EJECUTIVO:
        return jsonify(
            ok=False,
            error=f'No se puede editar el ejecutivo en estado {comp.item_presupuesto.presupuesto.estado}',
        ), 400

    db.session.delete(comp)
    db.session.commit()

    return jsonify(ok=True)


@presupuestos_bp.route('/items/<int:item_id>/composiciones', methods=['GET'])
@login_required
def composiciones_listar(item_id):
    """Devuelve las composiciones de un item (para refrescar UI sin reload)."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    item = ItemPresupuesto.query.get_or_404(item_id)
    if not _item_pertenece_a_org(item, org_id):
        return jsonify(ok=False, error='Item no pertenece a tu organización'), 403

    comps = item.composiciones.order_by(ItemPresupuestoComposicion.tipo, ItemPresupuestoComposicion.id).all()
    costo_total = sum((float(c.total or 0) for c in comps), 0.0)
    return jsonify(
        ok=True,
        item_id=item.id,
        costo_estimado=costo_total,
        composiciones=[_serializar_composicion(c) for c in comps],
    )
