"""
Endpoints para solicitar cotizacion a proveedores via WhatsApp
desde un presupuesto.
"""
from datetime import datetime
from flask import (render_template, request, jsonify, redirect, url_for,
                   flash, abort, current_app)
from flask_login import login_required, current_user

from blueprint_presupuestos import presupuestos_bp
from extensions import db
from models import (Presupuesto, ItemPresupuesto, ProveedorOC,
                    ItemPresupuestoProveedor, SolicitudCotizacionWA)
from services.memberships import get_current_org_id
from services.whatsapp_service import (
    normalizar_telefono, generar_mensaje_cotizacion, generar_url_wa_me,
    construir_items_snapshot, generar_numero_solicitud,
)


def _get_presupuesto_o_404(presupuesto_id):
    """Valida que el presupuesto existe y pertenece a la org actual."""
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        abort(403)
    p = Presupuesto.query.get_or_404(presupuesto_id)
    if p.organizacion_id != org_id:
        abort(403)
    return p, org_id


@presupuestos_bp.route('/<int:presupuesto_id>/cotizar-wa')
@login_required
def cotizar_wa_vista(presupuesto_id):
    """Vista: items del presupuesto + selector multi-proveedor + historial."""
    presupuesto, org_id = _get_presupuesto_o_404(presupuesto_id)

    # Items del presupuesto (solo tipo material/equipo, no mano de obra)
    items = presupuesto.items.filter(
        ItemPresupuesto.tipo.in_(['material', 'equipo'])
    ).order_by(ItemPresupuesto.id).all()

    # Proveedores activos de la org
    proveedores = ProveedorOC.query.filter_by(
        organizacion_id=org_id, activo=True
    ).order_by(ProveedorOC.razon_social).all()

    # Map item_id -> [proveedor_ids] sugeridos (vacio para items nuevos)
    vinculos = {}
    for it in items:
        vinculos[it.id] = [v.proveedor_oc_id for v in it.proveedores_sugeridos]

    # Agrupar items por etapa para mejor UX
    from collections import OrderedDict
    items_por_etapa = OrderedDict()
    for it in items:
        etapa = it.etapa_nombre or 'Sin etapa'
        items_por_etapa.setdefault(etapa, []).append(it)

    # Historial de solicitudes del presupuesto
    solicitudes = (SolicitudCotizacionWA.query
                   .filter_by(presupuesto_id=presupuesto_id)
                   .order_by(SolicitudCotizacionWA.created_at.desc())
                   .all())

    return render_template('presupuestos/cotizar_wa.html',
                           presupuesto=presupuesto,
                           items=items,
                           items_por_etapa=items_por_etapa,
                           proveedores=proveedores,
                           vinculos=vinculos,
                           solicitudes=solicitudes)


@presupuestos_bp.route('/<int:presupuesto_id>/cotizar-wa/item/<int:item_id>/editar', methods=['POST'])
@login_required
def cotizar_wa_editar_item(presupuesto_id, item_id):
    """Edita inline cantidad y/o precio_unitario de un item del presupuesto."""
    from decimal import Decimal, InvalidOperation
    presupuesto, org_id = _get_presupuesto_o_404(presupuesto_id)

    item = ItemPresupuesto.query.filter_by(
        id=item_id, presupuesto_id=presupuesto_id
    ).first()
    if not item:
        return jsonify(ok=False, error='item no encontrado'), 404

    data = request.get_json(silent=True) or {}

    def _to_dec(val, default=None):
        if val is None or val == '':
            return default
        try:
            return Decimal(str(val).replace(',', '.'))
        except (InvalidOperation, ValueError):
            return default

    nueva_cant = _to_dec(data.get('cantidad'))
    nuevo_precio = _to_dec(data.get('precio_unitario'))
    nueva_desc = data.get('descripcion')

    if nueva_cant is not None and nueva_cant >= 0:
        item.cantidad = nueva_cant
    if nuevo_precio is not None and nuevo_precio >= 0:
        item.precio_unitario = nuevo_precio
    if nueva_desc is not None and str(nueva_desc).strip():
        item.descripcion = str(nueva_desc).strip()[:300]

    # Recalcular total
    item.total = (item.cantidad or Decimal('0')) * (item.precio_unitario or Decimal('0'))

    # Recalcular subtotales del presupuesto
    try:
        from sqlalchemy import func
        subt = db.session.query(
            func.coalesce(func.sum(ItemPresupuesto.total), 0)
        ).filter_by(presupuesto_id=presupuesto_id).scalar() or 0
        presupuesto.subtotal_materiales = Decimal(str(subt))
        presupuesto.total_sin_iva = Decimal(str(subt))
        iva_pct = Decimal(str(presupuesto.iva_porcentaje or 21))
        presupuesto.total_con_iva = Decimal(str(subt)) + (Decimal(str(subt)) * iva_pct / Decimal('100'))
    except Exception:
        pass

    db.session.commit()
    return jsonify(
        ok=True,
        cantidad=float(item.cantidad or 0),
        precio_unitario=float(item.precio_unitario or 0),
        total=float(item.total or 0),
    )


@presupuestos_bp.route('/<int:presupuesto_id>/cotizar-wa/vincular', methods=['POST'])
@login_required
def cotizar_wa_vincular(presupuesto_id):
    """Guarda vinculacion item <-> proveedores sugeridos."""
    presupuesto, org_id = _get_presupuesto_o_404(presupuesto_id)

    data = request.get_json(silent=True) or {}
    item_id = data.get('item_id')
    proveedor_ids = data.get('proveedor_ids') or []

    if not item_id:
        return jsonify(ok=False, error='item_id requerido'), 400

    # Validar item pertenece al presupuesto
    item = ItemPresupuesto.query.filter_by(
        id=item_id, presupuesto_id=presupuesto_id
    ).first()
    if not item:
        return jsonify(ok=False, error='item no encontrado'), 404

    # Validar proveedores pertenecen a la org
    proveedor_ids = [int(pid) for pid in proveedor_ids if pid]
    if proveedor_ids:
        count_validos = ProveedorOC.query.filter(
            ProveedorOC.id.in_(proveedor_ids),
            ProveedorOC.organizacion_id == org_id,
        ).count()
        if count_validos != len(proveedor_ids):
            return jsonify(ok=False, error='proveedor invalido'), 400

    try:
        # Borrar vinculos actuales del item
        ItemPresupuestoProveedor.query.filter_by(
            item_presupuesto_id=item_id
        ).delete()

        # Crear nuevos
        for pid in proveedor_ids:
            db.session.add(ItemPresupuestoProveedor(
                item_presupuesto_id=item_id,
                proveedor_oc_id=pid,
            ))
        db.session.commit()
        return jsonify(ok=True, proveedor_ids=proveedor_ids)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error vinculando item-proveedor")
        return jsonify(ok=False, error=str(e)), 500


@presupuestos_bp.route('/<int:presupuesto_id>/cotizar-wa/generar', methods=['POST'])
@login_required
def cotizar_wa_generar(presupuesto_id):
    """Agrupa items por proveedor y genera SolicitudCotizacionWA (una por proveedor)."""
    presupuesto, org_id = _get_presupuesto_o_404(presupuesto_id)
    org_nombre = presupuesto.organizacion.nombre if presupuesto.organizacion else 'OBYRA'

    # Traer items con proveedores vinculados
    items_con_prov = (db.session.query(ItemPresupuestoProveedor, ItemPresupuesto)
                      .join(ItemPresupuesto,
                            ItemPresupuesto.id == ItemPresupuestoProveedor.item_presupuesto_id)
                      .filter(ItemPresupuesto.presupuesto_id == presupuesto_id)
                      .all())

    if not items_con_prov:
        return jsonify(ok=False, error='No hay items vinculados a proveedores'), 400

    # Agrupar por proveedor
    por_proveedor = {}  # prov_id -> [items]
    for vinc, item in items_con_prov:
        por_proveedor.setdefault(vinc.proveedor_oc_id, []).append(item)

    # Generar solicitudes (omitir si ya hay borrador/enviado no cerrado para el mismo proveedor)
    creadas = []
    for prov_id, items in por_proveedor.items():
        proveedor = ProveedorOC.query.get(prov_id)
        if not proveedor:
            continue

        # Chequear si ya existe solicitud abierta para este proveedor+presupuesto
        existente = SolicitudCotizacionWA.query.filter(
            SolicitudCotizacionWA.presupuesto_id == presupuesto_id,
            SolicitudCotizacionWA.proveedor_oc_id == prov_id,
            SolicitudCotizacionWA.estado.in_(['borrador', 'enviado']),
        ).first()
        if existente:
            continue

        telefono = normalizar_telefono(proveedor.contacto_telefono or proveedor.telefono)
        snapshot = construir_items_snapshot(items)
        mensaje = generar_mensaje_cotizacion(
            proveedor_nombre=proveedor.contacto_nombre or proveedor.razon_social,
            org_nombre=org_nombre,
            items=snapshot,
            presupuesto_numero=presupuesto.numero,
        )

        sol = SolicitudCotizacionWA(
            numero=generar_numero_solicitud(org_id),
            organizacion_id=org_id,
            presupuesto_id=presupuesto_id,
            proveedor_oc_id=prov_id,
            telefono_destino=telefono,
            mensaje_enviado=mensaje,
            canal='wa_link',
            estado='borrador',
            items_snapshot=snapshot,
            created_by_id=current_user.id,
        )
        db.session.add(sol)
        db.session.flush()
        wa_url = generar_url_wa_me(telefono, mensaje) if telefono else None
        creadas.append({
            'id': sol.id,
            'proveedor': proveedor.razon_social,
            'numero': sol.numero,
            'telefono': telefono,
            'wa_url': wa_url,
        })

    db.session.commit()
    return jsonify(ok=True, solicitudes_creadas=creadas, total=len(creadas))


@presupuestos_bp.route('/solicitudes-wa/<int:sol_id>/preview')
@login_required
def solicitud_wa_preview(sol_id):
    """JSON con datos para mostrar modal de preview."""
    sol = SolicitudCotizacionWA.query.get_or_404(sol_id)
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if sol.organizacion_id != org_id:
        abort(403)

    wa_url = generar_url_wa_me(sol.telefono_destino, sol.mensaje_enviado or '')
    return jsonify(
        ok=True,
        id=sol.id,
        numero=sol.numero,
        proveedor=sol.proveedor.razon_social if sol.proveedor else 'N/A',
        telefono_destino=sol.telefono_destino,
        mensaje=sol.mensaje_enviado or '',
        estado=sol.estado,
        wa_url=wa_url,
    )


@presupuestos_bp.route('/solicitudes-wa/<int:sol_id>/marcar-enviado', methods=['POST'])
@login_required
def solicitud_wa_marcar_enviado(sol_id):
    """Marca solicitud como enviada + guarda mensaje final editado."""
    sol = SolicitudCotizacionWA.query.get_or_404(sol_id)
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if sol.organizacion_id != org_id:
        abort(403)

    data = request.get_json(silent=True) or {}
    mensaje_final = data.get('mensaje')
    telefono_final = data.get('telefono')

    if mensaje_final is not None:
        sol.mensaje_enviado = mensaje_final
    if telefono_final is not None:
        sol.telefono_destino = normalizar_telefono(telefono_final) or telefono_final

    sol.estado = 'enviado'
    sol.fecha_envio = datetime.utcnow()
    db.session.commit()

    return jsonify(ok=True, estado=sol.estado)


@presupuestos_bp.route('/solicitudes-wa/<int:sol_id>/marcar-respondido', methods=['POST'])
@login_required
def solicitud_wa_marcar_respondido(sol_id):
    """Carga manual de respuesta del proveedor."""
    sol = SolicitudCotizacionWA.query.get_or_404(sol_id)
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if sol.organizacion_id != org_id:
        abort(403)

    data = request.get_json(silent=True) or {}
    respuesta = (data.get('respuesta') or '').strip()
    if not respuesta:
        return jsonify(ok=False, error='Respuesta vacia'), 400

    sol.respuesta_texto = respuesta
    sol.fecha_respuesta = datetime.utcnow()
    sol.estado = 'respondido'
    db.session.commit()
    return jsonify(ok=True, estado=sol.estado)


@presupuestos_bp.route('/solicitudes-wa/<int:sol_id>/cerrar', methods=['POST'])
@login_required
def solicitud_wa_cerrar(sol_id):
    """Cierra una solicitud (no se usa mas)."""
    sol = SolicitudCotizacionWA.query.get_or_404(sol_id)
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if sol.organizacion_id != org_id:
        abort(403)

    sol.estado = 'cerrado'
    db.session.commit()
    return jsonify(ok=True)
