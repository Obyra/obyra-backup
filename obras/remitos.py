"""Obras -- Remitos routes."""
from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort)
from flask_login import login_required, current_user
from datetime import date, datetime
from decimal import Decimal
from extensions import db
from services.permissions import validate_obra_ownership
from services.memberships import get_current_org_id
from services.inventory_helpers import find_or_create_item_inventario

from obras import obras_bp, _get_roles_usuario


def _resolve_item_inventario_id(item_data, org_id):
    """Resuelve el item_inventario_id de un item de remito con 3 fallbacks.

    Prioridad:
      1. item_inventario_id explícito del request
      2. Heredar del OrdenCompraItem (si remito viene de una OC)
         - Si el OC item no tiene vínculo tampoco (OCs previas al fix),
           auto-crear y backfillear el OC.
      3. Auto-crear desde la descripción del remito (remito manual sin OC)

    Garantiza que todo RemitoItem tenga item_inventario_id antes de guardarse,
    para que _sync_remito_to_stock pueda impactar en StockObra.
    """
    from models.inventory import OrdenCompraItem

    item_inv_id = item_data.get('item_inventario_id')
    if item_inv_id:
        return int(item_inv_id)

    # Fallback 1: heredar del OC item vinculado
    oc_item_id = item_data.get('oc_item_id')
    if oc_item_id:
        oc_item = OrdenCompraItem.query.get(int(oc_item_id))
        if oc_item:
            if oc_item.item_inventario_id:
                return oc_item.item_inventario_id
            # OC viejo sin vínculo: auto-crear y backfillear
            nuevo_id = find_or_create_item_inventario(
                oc_item.descripcion,
                oc_item.unidad,
                float(oc_item.precio_unitario or 0),
                org_id,
            )
            if nuevo_id:
                oc_item.item_inventario_id = nuevo_id
            return nuevo_id

    # Fallback 2: auto-crear desde descripción del remito
    descripcion = item_data.get('descripcion')
    if descripcion:
        return find_or_create_item_inventario(
            descripcion,
            item_data.get('unidad', 'u'),
            float(item_data.get('precio_unitario') or 0),
            org_id,
        )

    return None


def _sync_remito_to_stock(remito):
    """Sincroniza los items de un remito recibido al StockObra.

    Para cada RemitoItem vinculado a un ItemInventario:
    - Crea o incrementa StockObra.cantidad_disponible
    - Registra MovimientoStockObra tipo 'entrada'
    """
    from models.inventory import StockObra, MovimientoStockObra

    for ri in remito.items:
        if not ri.item_inventario_id or not ri.cantidad:
            continue
        cantidad = float(ri.cantidad)
        if cantidad <= 0:
            continue

        stock = StockObra.query.filter_by(
            obra_id=remito.obra_id,
            item_inventario_id=ri.item_inventario_id,
        ).first()

        if not stock:
            stock = StockObra(
                obra_id=remito.obra_id,
                item_inventario_id=ri.item_inventario_id,
                cantidad_disponible=0,
                cantidad_consumida=0,
            )
            db.session.add(stock)
            db.session.flush()

        stock.cantidad_disponible = float(
            Decimal(str(stock.cantidad_disponible or 0)) + Decimal(str(cantidad))
        )
        stock.fecha_ultimo_traslado = datetime.utcnow()

        mov = MovimientoStockObra(
            stock_obra_id=stock.id,
            tipo='entrada',
            cantidad=cantidad,
            fecha=datetime.utcnow(),
            usuario_id=remito.created_by_id or remito.recibido_por_id,
            observaciones=f'Remito #{remito.numero_remito} - {ri.descripcion}',
            precio_unitario=float(ri.precio_unitario) if ri.precio_unitario else None,
            moneda='ARS',
        )
        db.session.add(mov)


def _reverse_remito_stock(remito):
    """Revierte el stock que ingresó por un remito (antes de eliminarlo)."""
    from models.inventory import StockObra

    for ri in remito.items:
        if not ri.item_inventario_id or not ri.cantidad:
            continue
        cantidad = float(ri.cantidad)
        stock = StockObra.query.filter_by(
            obra_id=remito.obra_id,
            item_inventario_id=ri.item_inventario_id,
        ).first()
        if stock:
            stock.cantidad_disponible = max(
                0, float(Decimal(str(stock.cantidad_disponible or 0)) - Decimal(str(cantidad)))
            )


@obras_bp.route('/<int:obra_id>/remitos', methods=['POST'])
@login_required
def crear_remito(obra_id):
    """Crear un remito manualmente."""
    validate_obra_ownership(obra_id)
    from models.inventory import Remito, RemitoItem
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador', 'pm', 'project_manager', 'jefe_obra'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos invalidos'), 400

    try:
        remito = Remito(
            organizacion_id=current_user.organizacion_id,
            obra_id=obra_id,
            numero_remito=data['numero_remito'],
            proveedor=data['proveedor'],
            fecha=date.fromisoformat(data['fecha']),
            estado=data.get('estado', 'recibido'),
            requerimiento_id=int(data['requerimiento_id']) if data.get('requerimiento_id') else None,
            orden_compra_id=int(data['orden_compra_id']) if data.get('orden_compra_id') else None,
            recibido_por_id=int(data['recibido_por_id']) if data.get('recibido_por_id') else current_user.id,
            notas=data.get('notas'),
            created_by_id=current_user.id,
        )
        db.session.add(remito)
        db.session.flush()

        org_id = current_user.organizacion_id
        for item_data in data.get('items', []):
            # Resolver item_inventario_id con 3 fallbacks (ver helper).
            # Garantiza que _sync_remito_to_stock pueda crear StockObra.
            item_inv_id = _resolve_item_inventario_id(item_data, org_id)

            item = RemitoItem(
                remito_id=remito.id,
                descripcion=item_data['descripcion'],
                cantidad=item_data['cantidad'],
                unidad=item_data.get('unidad', 'u'),
                observacion=item_data.get('observacion'),
                oc_item_id=int(item_data['oc_item_id']) if item_data.get('oc_item_id') else None,
                item_inventario_id=item_inv_id,
                precio_unitario=float(item_data['precio_unitario']) if item_data.get('precio_unitario') else None,
            )
            db.session.add(item)

        db.session.flush()

        # Sincronizar items del remito al stock de la obra
        if remito.estado == 'recibido':
            _sync_remito_to_stock(remito)

        db.session.commit()
        return jsonify(ok=True, id=remito.id)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error creando remito")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:obra_id>/remitos/<int:remito_id>')
@login_required
def ver_remito(obra_id, remito_id):
    """API: obtener detalle de un remito."""
    validate_obra_ownership(obra_id)
    from models.inventory import Remito
    remito = Remito.query.get_or_404(remito_id)
    if remito.obra.organizacion_id != get_current_org_id():
        abort(403)
    return jsonify(ok=True, remito={
        'id': remito.id,
        'numero_remito': remito.numero_remito,
        'proveedor': remito.proveedor,
        'fecha': remito.fecha.strftime('%d/%m/%Y') if remito.fecha else None,
        'estado': remito.estado,
        'estado_display': remito.estado_display,
        'estado_color': remito.estado_color,
        'notas': remito.notas,
        'recibido_por': remito.recibido_por.nombre_completo if remito.recibido_por else None,
        'requerimiento_numero': remito.requerimiento.numero if remito.requerimiento else None,
        'items': [{
            'descripcion': i.descripcion,
            'cantidad': float(i.cantidad),
            'unidad': i.unidad,
            'observacion': i.observacion,
        } for i in remito.items],
    })


@obras_bp.route('/<int:obra_id>/remitos/<int:remito_id>', methods=['DELETE'])
@login_required
def eliminar_remito(obra_id, remito_id):
    """Eliminar un remito."""
    validate_obra_ownership(obra_id)
    from models.inventory import Remito
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador', 'pm', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    remito = Remito.query.get_or_404(remito_id)
    if remito.obra.organizacion_id != get_current_org_id():
        abort(403)
    try:
        # Revertir stock si el remito estaba recibido
        if remito.estado == 'recibido':
            _reverse_remito_stock(remito)
        db.session.delete(remito)
        db.session.commit()
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


# ============================================================
# PDF -- REMITO
# ============================================================

@obras_bp.route('/<int:obra_id>/remitos/<int:remito_id>/pdf')
@login_required
def remito_pdf(obra_id, remito_id):
    """Genera PDF del remito con la misma estetica que presupuestos."""
    validate_obra_ownership(obra_id)
    from models.inventory import Remito
    from weasyprint import HTML
    import io, os, base64

    remito = Remito.query.get_or_404(remito_id)
    organizacion = remito.organizacion

    logo_base64 = None
    if organizacion.logo_url:
        try:
            logo_path = os.path.join(current_app.static_folder, organizacion.logo_url)
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass

    tiene_precios = any(i.precio_unitario and float(i.precio_unitario) > 0 for i in remito.items)
    total_remito = sum(
        float(i.cantidad or 0) * float(i.precio_unitario or 0)
        for i in remito.items
    ) if tiene_precios else 0

    oc_numero = remito.orden_compra.numero if remito.orden_compra else None

    html_string = render_template('pdf_remito.html',
        remito=remito,
        organizacion=organizacion,
        logo_base64=logo_base64,
        tiene_precios=tiene_precios,
        total_remito=total_remito,
        oc_numero=oc_numero,
    )

    from flask import send_file
    pdf_buffer = io.BytesIO()
    HTML(string=html_string).write_pdf(pdf_buffer, presentational_hints=True)
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Remito_{remito.numero_remito}.pdf'
    )
