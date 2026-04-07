"""Obras -- Remitos routes."""
from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort)
from flask_login import login_required, current_user
from datetime import date
from extensions import db
from services.permissions import validate_obra_ownership
from services.memberships import get_current_org_id

from obras import obras_bp, _get_roles_usuario


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

        for item_data in data.get('items', []):
            item = RemitoItem(
                remito_id=remito.id,
                descripcion=item_data['descripcion'],
                cantidad=item_data['cantidad'],
                unidad=item_data.get('unidad', 'u'),
                observacion=item_data.get('observacion'),
                oc_item_id=int(item_data['oc_item_id']) if item_data.get('oc_item_id') else None,
                item_inventario_id=int(item_data['item_inventario_id']) if item_data.get('item_inventario_id') else None,
                precio_unitario=float(item_data['precio_unitario']) if item_data.get('precio_unitario') else None,
            )
            db.session.add(item)

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
