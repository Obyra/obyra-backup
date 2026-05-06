"""Endpoints de gestion editable de etapas y items — Etapa 1 modulo flexible.

Provee operaciones CRUD sobre PresupuestoEtapa y operaciones extra sobre
ItemPresupuesto (mover entre etapas, duplicar, excluir/reactivar) que el
flujo legacy no contemplaba.

Filosofia:
- `etapa_nombre` (string en items_presupuesto) sigue siendo el cache
  denormalizado. Toda operacion que cambie la etapa de un item actualiza
  AMBOS: la FK `etapa_presupuesto_id` y el cache `etapa_nombre`.
- Los endpoints solo permiten operar sobre presupuestos en estado
  'borrador' o 'enviado'. En 'aprobado' / 'perdido' / 'eliminado' devuelven 400.
- Multi-tenant: scope por organizacion_id en cada query.
"""
from datetime import datetime
from decimal import Decimal

from flask import jsonify, request, current_app, abort
from flask_login import login_required, current_user

from blueprint_presupuestos import presupuestos_bp
from extensions import db
from models import Presupuesto, ItemPresupuesto
from models.presupuesto_etapa import PresupuestoEtapa
from services.memberships import get_current_org_id


_ESTADOS_EDITABLES = ('borrador', 'enviado')


def _get_presupuesto_editable_o_400(presupuesto_id):
    """Helper: obtiene presupuesto del org actual en estado editable o aborta.

    Retorna (presupuesto, None) si OK; (None, jsonify_response) si error.
    """
    org_id = get_current_org_id()
    if not org_id:
        return None, (jsonify(ok=False, error='Sin organizacion activa'), 400)
    p = Presupuesto.query.filter_by(id=presupuesto_id, organizacion_id=org_id).first()
    if not p:
        return None, (jsonify(ok=False, error='Presupuesto no encontrado'), 404)
    if p.estado not in _ESTADOS_EDITABLES:
        return None, (jsonify(
            ok=False,
            error=f'No se puede editar la estructura: presupuesto en estado {p.estado}',
        ), 400)
    return p, None


def _get_item_editable_o_400(item_id):
    """Helper: obtiene item editable del org actual o aborta."""
    org_id = get_current_org_id()
    if not org_id:
        return None, None, (jsonify(ok=False, error='Sin organizacion activa'), 400)
    item = ItemPresupuesto.query.get(item_id)
    if not item:
        return None, None, (jsonify(ok=False, error='Item no encontrado'), 404)
    p = item.presupuesto
    if p.organizacion_id != org_id:
        return None, None, (jsonify(ok=False, error='Item no encontrado'), 404)
    if p.estado not in _ESTADOS_EDITABLES:
        return None, None, (jsonify(
            ok=False,
            error=f'No se puede editar: presupuesto en estado {p.estado}',
        ), 400)
    return item, p, None


# ============================================================================
# CRUD de etapas
# ============================================================================

@presupuestos_bp.route('/<int:id>/etapas', methods=['GET'])
@login_required
def listar_etapas(id):
    """Lista las etapas del presupuesto con conteo de items."""
    org_id = get_current_org_id()
    p = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

    etapas = (PresupuestoEtapa.query
              .filter_by(presupuesto_id=p.id)
              .order_by(PresupuestoEtapa.orden, PresupuestoEtapa.id)
              .all())

    # Contar items y total por etapa
    cuenta = {}
    total = {}
    for it in p.items:
        if getattr(it, 'excluido', False):
            continue
        eid = getattr(it, 'etapa_presupuesto_id', None)
        cuenta[eid] = cuenta.get(eid, 0) + 1
        total[eid] = (total.get(eid, Decimal('0')) +
                      Decimal(str(it.total or 0)))

    return jsonify(
        ok=True,
        etapas=[e.to_dict(items_count=cuenta.get(e.id, 0),
                          items_total=float(total.get(e.id, Decimal('0'))))
                for e in etapas],
    )


@presupuestos_bp.route('/<int:id>/etapas', methods=['POST'])
@login_required
def crear_etapa(id):
    """Crea una nueva etapa en el presupuesto."""
    if not current_user.puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    p, err = _get_presupuesto_editable_o_400(id)
    if err:
        return err

    data = request.get_json() or {}
    nombre = PresupuestoEtapa.normalizar_nombre(data.get('nombre'))
    if not nombre:
        return jsonify(ok=False, error='Nombre requerido'), 400

    # Verificar duplicado
    existing = (PresupuestoEtapa.query
                .filter_by(presupuesto_id=p.id, nombre=nombre)
                .first())
    if existing:
        return jsonify(
            ok=False,
            error='Ya existe una etapa con ese nombre',
            etapa_existente_id=existing.id,
        ), 409

    # Calcular orden = max + 1
    max_orden = (db.session.query(db.func.coalesce(db.func.max(PresupuestoEtapa.orden), -1))
                 .filter_by(presupuesto_id=p.id)
                 .scalar()) or -1
    e = PresupuestoEtapa(
        presupuesto_id=p.id,
        nombre=nombre,
        orden=int(max_orden) + 1,
        oculto=False,
    )
    db.session.add(e)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error creando etapa')
        return jsonify(ok=False, error='Error creando etapa'), 500
    return jsonify(ok=True, etapa=e.to_dict(items_count=0, items_total=0.0)), 201


@presupuestos_bp.route('/<int:id>/etapas/<int:eid>', methods=['PATCH'])
@login_required
def editar_etapa(id, eid):
    """Renombra y/u oculta una etapa. Si se renombra, actualiza tambien el
    cache `etapa_nombre` en todos los items vinculados.
    """
    if not current_user.puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    p, err = _get_presupuesto_editable_o_400(id)
    if err:
        return err

    e = PresupuestoEtapa.query.filter_by(id=eid, presupuesto_id=p.id).first()
    if not e:
        return jsonify(ok=False, error='Etapa no encontrada'), 404

    data = request.get_json() or {}
    cambios = []

    if 'nombre' in data:
        nuevo = PresupuestoEtapa.normalizar_nombre(data.get('nombre'))
        if not nuevo:
            return jsonify(ok=False, error='Nombre invalido'), 400
        if nuevo != e.nombre:
            # Verificar duplicado
            otra = (PresupuestoEtapa.query
                    .filter(PresupuestoEtapa.presupuesto_id == p.id,
                            PresupuestoEtapa.nombre == nuevo,
                            PresupuestoEtapa.id != eid)
                    .first())
            if otra:
                return jsonify(
                    ok=False,
                    error='Ya existe otra etapa con ese nombre',
                ), 409
            e.nombre = nuevo
            # Sincronizar cache denormalizado en items
            (ItemPresupuesto.query
             .filter_by(presupuesto_id=p.id, etapa_presupuesto_id=e.id)
             .update({'etapa_nombre': nuevo},
                     synchronize_session=False))
            cambios.append('nombre')

    if 'oculto' in data:
        e.oculto = bool(data['oculto'])
        cambios.append('oculto')

    if not cambios:
        return jsonify(ok=False, error='Sin cambios'), 400

    e.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error editando etapa')
        return jsonify(ok=False, error='Error editando etapa'), 500
    return jsonify(ok=True, etapa=e.to_dict())


@presupuestos_bp.route('/<int:id>/etapas/<int:eid>', methods=['DELETE'])
@login_required
def eliminar_etapa(id, eid):
    """Elimina una etapa solo si esta vacia (sin items asociados, ni siquiera
    excluidos)."""
    if not current_user.puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    p, err = _get_presupuesto_editable_o_400(id)
    if err:
        return err

    e = PresupuestoEtapa.query.filter_by(id=eid, presupuesto_id=p.id).first()
    if not e:
        return jsonify(ok=False, error='Etapa no encontrada'), 404

    items_count = (ItemPresupuesto.query
                   .filter_by(presupuesto_id=p.id, etapa_presupuesto_id=e.id)
                   .count())
    if items_count > 0:
        return jsonify(
            ok=False,
            error=(f'La etapa tiene {items_count} item(s). Move o elimina los '
                   f'items antes de borrar la etapa.'),
            items_count=items_count,
        ), 400

    try:
        db.session.delete(e)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error eliminando etapa')
        return jsonify(ok=False, error='Error eliminando etapa'), 500
    return jsonify(ok=True, eliminada_id=eid)


# ============================================================================
# Operaciones extra sobre ItemPresupuesto
# ============================================================================

@presupuestos_bp.route('/items/<int:id>/mover', methods=['POST'])
@login_required
def mover_item(id):
    """Mueve un item a otra etapa del MISMO presupuesto.
    Body JSON: {etapa_id: int}. La etapa destino debe pertenecer al
    presupuesto del item; sino 400.
    """
    if not current_user.puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    item, p, err = _get_item_editable_o_400(id)
    if err:
        return err

    data = request.get_json() or {}
    nueva_etapa_id = data.get('etapa_id')
    if nueva_etapa_id is None:
        return jsonify(ok=False, error='etapa_id requerido'), 400

    nueva_etapa = PresupuestoEtapa.query.filter_by(
        id=nueva_etapa_id, presupuesto_id=p.id,
    ).first()
    if not nueva_etapa:
        return jsonify(
            ok=False,
            error='Etapa destino invalida (no pertenece al presupuesto)',
        ), 400

    item.etapa_presupuesto_id = nueva_etapa.id
    item.etapa_nombre = nueva_etapa.nombre
    item.editado_at = datetime.utcnow()
    if current_user.is_authenticated:
        item.editado_por_user_id = current_user.id
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error moviendo item')
        return jsonify(ok=False, error='Error moviendo item'), 500
    return jsonify(
        ok=True,
        item_id=item.id,
        etapa_presupuesto_id=item.etapa_presupuesto_id,
        etapa_nombre=item.etapa_nombre,
    )


@presupuestos_bp.route('/items/<int:id>/duplicar', methods=['POST'])
@login_required
def duplicar_item(id):
    """Duplica un item dentro de la misma etapa. La copia tiene origen='manual'
    y editado_at seteado. NO se duplica analisis_ia ni revisado_ia (la copia
    es un item nuevo). NO se hereda solo_interno (la copia es 'normal').
    """
    if not current_user.puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    item, p, err = _get_item_editable_o_400(id)
    if err:
        return err

    nuevo = ItemPresupuesto(
        presupuesto_id=item.presupuesto_id,
        tipo=item.tipo,
        descripcion=(item.descripcion or '') + ' (copia)',
        unidad=item.unidad,
        cantidad=item.cantidad,
        precio_unitario=item.precio_unitario,
        total=item.total,
        etapa_id=item.etapa_id,
        etapa_nombre=item.etapa_nombre,
        etapa_presupuesto_id=item.etapa_presupuesto_id,
        origen='manual',
        currency=item.currency,
        price_unit_currency=item.price_unit_currency,
        total_currency=item.total_currency,
        price_unit_ars=item.price_unit_ars,
        total_ars=item.total_ars,
        nivel_nombre=item.nivel_nombre,
        modalidad_costo=item.modalidad_costo,
        personas=item.personas,
        dias=item.dias,
        categoria_jornal_id=item.categoria_jornal_id,
        editado_at=datetime.utcnow(),
        editado_por_user_id=(current_user.id if current_user.is_authenticated else None),
    )
    db.session.add(nuevo)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error duplicando item')
        return jsonify(ok=False, error='Error duplicando item'), 500
    return jsonify(
        ok=True,
        item_id=nuevo.id,
        descripcion=nuevo.descripcion,
        etapa_presupuesto_id=nuevo.etapa_presupuesto_id,
    ), 201


@presupuestos_bp.route('/items/<int:id>/excluir', methods=['POST'])
@login_required
def toggle_excluir_item(id):
    """Toggle del flag `excluido`. Body JSON opcional: {valor: true|false}.
    Si no se pasa valor, invierte el estado actual.

    Items excluidos siguen visibles en la UI (con badge tachado) pero no
    suman al total del presupuesto (filtro en calcular_totales).
    """
    if not current_user.puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    item, p, err = _get_item_editable_o_400(id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    if 'valor' in data:
        item.excluido = bool(data['valor'])
    else:
        item.excluido = not bool(item.excluido)

    item.editado_at = datetime.utcnow()
    if current_user.is_authenticated:
        item.editado_por_user_id = current_user.id
    try:
        # Recalcular totales (excluidos no cuentan ahora)
        p.calcular_totales()
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error excluyendo item')
        return jsonify(ok=False, error='Error excluyendo item'), 500

    return jsonify(
        ok=True,
        item_id=item.id,
        excluido=item.excluido,
        total_sin_iva=float(p.total_sin_iva or 0),
        total_con_iva=float(p.total_con_iva or 0),
    )
