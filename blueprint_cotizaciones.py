"""
Blueprint de Cotizaciones de Proveedores.

Flujo: RC aprobado → Solicitar cotizaciones a 2-3 proveedores →
       Cargar precios → Comparar → Elegir mejor → Generar OC pre-llenada.
"""
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app)
from flask_login import login_required, current_user
from datetime import datetime
from extensions import db, csrf

cotizaciones_bp = Blueprint('cotizaciones', __name__, url_prefix='/cotizaciones')


def _tiene_permiso():
    """Verifica si el usuario puede gestionar cotizaciones (admin o PM)."""
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm')


def _get_org_id():
    return getattr(current_user, 'organizacion_id', None)


# ============================================================
# GESTIONAR COTIZACIONES DE UN RC
# ============================================================

@cotizaciones_bp.route('/requerimiento/<int:rc_id>')
@login_required
def gestionar(rc_id):
    from models.inventory import RequerimientoCompra
    from models.proveedores_oc import CotizacionProveedor

    if not _tiene_permiso():
        flash('No tiene permisos para gestionar cotizaciones.', 'danger')
        return redirect(url_for('main.dashboard'))

    org_id = _get_org_id()

    rc = RequerimientoCompra.query.get_or_404(rc_id)
    if rc.organizacion_id != org_id:
        flash('No tiene acceso a este requerimiento.', 'danger')
        return redirect(url_for('requerimientos.lista'))

    cotizaciones = CotizacionProveedor.query.filter_by(
        requerimiento_id=rc.id
    ).order_by(CotizacionProveedor.created_at).all()

    # Contar estados
    recibidas = sum(1 for c in cotizaciones if c.estado in ('recibida', 'elegida'))
    elegida = next((c for c in cotizaciones if c.estado == 'elegida'), None)

    # Proveedores disponibles para el dropdown
    from models.proveedores_oc import ProveedorOC
    proveedores_disponibles = ProveedorOC.query.filter_by(
        organizacion_id=org_id, activo=True
    ).order_by(ProveedorOC.razon_social).all()

    return render_template('cotizaciones/gestionar.html',
                         rc=rc, cotizaciones=cotizaciones,
                         recibidas=recibidas, elegida=elegida,
                         proveedores_disponibles=proveedores_disponibles)


# ============================================================
# AGREGAR PROVEEDOR A COTIZACIÓN
# ============================================================

@cotizaciones_bp.route('/requerimiento/<int:rc_id>/agregar-proveedor', methods=['POST'])
@login_required
def agregar_proveedor(rc_id):
    from models.inventory import RequerimientoCompra
    from models.proveedores_oc import CotizacionProveedor, CotizacionProveedorItem, ProveedorOC

    if not _tiene_permiso():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('cotizaciones.gestionar', rc_id=rc_id))

    org_id = _get_org_id()

    rc = RequerimientoCompra.query.get_or_404(rc_id)
    if rc.organizacion_id != org_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('requerimientos.lista'))

    proveedor_oc_id = request.form.get('proveedor_oc_id', type=int)
    if not proveedor_oc_id:
        flash('Debe seleccionar un proveedor.', 'danger')
        return redirect(url_for('cotizaciones.gestionar', rc_id=rc_id))

    # Verificar proveedor existe y es de la org
    prov = ProveedorOC.query.get(proveedor_oc_id)
    if not prov or prov.organizacion_id != org_id:
        flash('Proveedor no válido.', 'danger')
        return redirect(url_for('cotizaciones.gestionar', rc_id=rc_id))

    # Verificar no duplicado
    existente = CotizacionProveedor.query.filter_by(
        requerimiento_id=rc.id, proveedor_oc_id=proveedor_oc_id
    ).first()
    if existente:
        flash(f'El proveedor "{prov.razon_social}" ya tiene una cotización para este RC.', 'warning')
        return redirect(url_for('cotizaciones.gestionar', rc_id=rc_id))

    try:
        cot = CotizacionProveedor(
            requerimiento_id=rc.id,
            proveedor_oc_id=proveedor_oc_id,
            organizacion_id=org_id,
            estado='borrador',
            moneda='ARS',
            condicion_pago=prov.condicion_pago,
            created_by_id=current_user.id,
        )
        db.session.add(cot)
        db.session.flush()

        # Crear items desde el RC (snapshot)
        for rc_item in rc.items:
            cot_item = CotizacionProveedorItem(
                cotizacion_id=cot.id,
                requerimiento_item_id=rc_item.id,
                descripcion=rc_item.descripcion,
                cantidad=rc_item.cantidad,
                unidad=rc_item.unidad or 'unidad',
                item_inventario_id=rc_item.item_inventario_id,
                precio_unitario=0,
                subtotal=0,
            )
            db.session.add(cot_item)

        db.session.commit()
        flash(f'Proveedor "{prov.razon_social}" agregado. Cargue los precios cotizados.', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error agregando proveedor a cotización: {e}")
        flash('Error al agregar proveedor.', 'danger')

    return redirect(url_for('cotizaciones.gestionar', rc_id=rc_id))


# ============================================================
# CARGAR PRECIOS DE UNA COTIZACIÓN
# ============================================================

@cotizaciones_bp.route('/<int:id>/cargar-precios', methods=['POST'])
@login_required
def cargar_precios(id):
    from models.proveedores_oc import CotizacionProveedor, CotizacionProveedorItem

    if not _tiene_permiso():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('main.dashboard'))

    cot = CotizacionProveedor.query.get_or_404(id)
    if cot.organizacion_id != _get_org_id():
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('requerimientos.lista'))

    try:
        # Actualizar condiciones comerciales
        cot.condicion_pago = request.form.get('condicion_pago', '').strip() or None
        cot.plazo_entrega = request.form.get('plazo_entrega', '').strip() or None
        cot.validez = request.form.get('validez', '').strip() or None
        cot.notas = request.form.get('notas', '').strip() or None
        cot.moneda = request.form.get('moneda', 'ARS')

        # Actualizar precios de cada item
        tiene_precios = False
        for item in cot.items:
            precio_str = request.form.get(f'precio_{item.id}', '0')
            nota_item = request.form.get(f'nota_{item.id}', '').strip()
            try:
                precio = float(precio_str.replace(',', '.'))
            except (ValueError, TypeError):
                precio = 0

            item.precio_unitario = precio
            item.notas = nota_item or None

            # Modalidad compra/alquiler
            modalidad = request.form.get(f'modalidad_{item.id}', 'compra')
            item.modalidad = modalidad
            dias_alq = request.form.get(f'dias_alquiler_{item.id}', '').strip()
            item.dias_alquiler = int(dias_alq) if dias_alq and modalidad == 'alquiler' else None

            item.recalcular_subtotal()

            if precio > 0:
                tiene_precios = True

        # Recalcular totales
        cot.recalcular_totales()

        # Cambiar estado a recibida si tiene precios
        if tiene_precios and cot.estado == 'borrador':
            cot.estado = 'recibida'
            cot.fecha_recepcion = datetime.utcnow()

        cot.updated_at = datetime.utcnow()
        db.session.commit()

        flash(f'Precios actualizados para {cot.proveedor.razon_social}.', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error cargando precios cotización: {e}")
        flash('Error al guardar precios.', 'danger')

    return redirect(url_for('cotizaciones.gestionar', rc_id=cot.requerimiento_id))


# ============================================================
# CUADRO COMPARATIVO
# ============================================================

@cotizaciones_bp.route('/requerimiento/<int:rc_id>/comparar')
@login_required
def comparar(rc_id):
    from models.inventory import RequerimientoCompra
    from models.proveedores_oc import CotizacionProveedor

    if not _tiene_permiso():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('main.dashboard'))

    org_id = _get_org_id()

    rc = RequerimientoCompra.query.get_or_404(rc_id)
    if rc.organizacion_id != org_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('requerimientos.lista'))

    cotizaciones = CotizacionProveedor.query.filter_by(
        requerimiento_id=rc.id
    ).filter(
        CotizacionProveedor.estado.in_(['recibida', 'elegida'])
    ).all()

    if len(cotizaciones) < 2:
        flash('Se necesitan al menos 2 cotizaciones recibidas para comparar.', 'warning')
        return redirect(url_for('cotizaciones.gestionar', rc_id=rc_id))

    # Armar estructura de comparación: filas = items RC, columnas = proveedores
    rc_items = list(rc.items)
    comparacion = []
    for rc_item in rc_items:
        fila = {
            'item': rc_item,
            'precios': {},
            'mejor_precio': None,
        }
        precios_validos = []
        for cot in cotizaciones:
            cot_item = next(
                (ci for ci in cot.items if ci.requerimiento_item_id == rc_item.id),
                None
            )
            precio = float(cot_item.precio_unitario or 0) if cot_item else 0
            subtotal = float(cot_item.subtotal or 0) if cot_item else 0
            fila['precios'][cot.id] = {
                'precio_unitario': precio,
                'subtotal': subtotal,
                'notas': cot_item.notas if cot_item else None,
            }
            if precio > 0:
                precios_validos.append((cot.id, precio))

        # Determinar mejor precio por fila
        if precios_validos:
            fila['mejor_precio'] = min(precios_validos, key=lambda x: x[1])[0]

        comparacion.append(fila)

    # Totales por proveedor
    totales = {}
    for cot in cotizaciones:
        totales[cot.id] = float(cot.total or 0)

    mejor_total = min(totales, key=totales.get) if totales else None

    return render_template('cotizaciones/comparar.html',
                         rc=rc, cotizaciones=cotizaciones,
                         comparacion=comparacion, totales=totales,
                         mejor_total=mejor_total)


# ============================================================
# ELEGIR COTIZACIÓN
# ============================================================

@cotizaciones_bp.route('/<int:id>/elegir', methods=['POST'])
@csrf.exempt
@login_required
def elegir(id):
    from models.proveedores_oc import CotizacionProveedor

    if not _tiene_permiso():
        return jsonify({'error': 'Sin permisos'}), 403

    cot = CotizacionProveedor.query.get_or_404(id)
    if cot.organizacion_id != _get_org_id():
        return jsonify({'error': 'No autorizado'}), 403

    if cot.estado not in ('recibida', 'elegida'):
        return jsonify({'error': 'Solo se puede elegir una cotización recibida'}), 400

    try:
        # Marcar esta como elegida
        cot.estado = 'elegida'
        cot.updated_at = datetime.utcnow()

        # Marcar todas las demás del mismo RC como descartada
        otras = CotizacionProveedor.query.filter(
            CotizacionProveedor.requerimiento_id == cot.requerimiento_id,
            CotizacionProveedor.id != cot.id,
            CotizacionProveedor.estado.in_(['recibida', 'elegida'])
        ).all()
        for otra in otras:
            otra.estado = 'descartada'
            otra.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            'ok': True,
            'mensaje': f'Cotización de {cot.proveedor.razon_social} elegida'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error eligiendo cotización: {e}")
        return jsonify({'error': 'Error al elegir cotización'}), 500


# ============================================================
# ELIMINAR COTIZACIÓN (solo borrador)
# ============================================================

@cotizaciones_bp.route('/<int:id>/eliminar', methods=['POST'])
@csrf.exempt
@login_required
def eliminar(id):
    from models.proveedores_oc import CotizacionProveedor

    if not _tiene_permiso():
        return jsonify({'error': 'Sin permisos'}), 403

    cot = CotizacionProveedor.query.get_or_404(id)
    if cot.organizacion_id != _get_org_id():
        return jsonify({'error': 'No autorizado'}), 403

    if cot.estado != 'borrador':
        return jsonify({'error': 'Solo se pueden eliminar cotizaciones en borrador'}), 400

    try:
        rc_id = cot.requerimiento_id
        nombre = cot.proveedor.razon_social
        db.session.delete(cot)
        db.session.commit()
        return jsonify({'ok': True, 'mensaje': f'Cotización de {nombre} eliminada'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Error al eliminar'}), 500


# ============================================================
# GENERAR OC DESDE COTIZACIÓN ELEGIDA
# ============================================================

@cotizaciones_bp.route('/requerimiento/<int:rc_id>/generar-oc')
@login_required
def generar_oc(rc_id):
    from models.inventory import RequerimientoCompra
    from models.proveedores_oc import CotizacionProveedor

    if not _tiene_permiso():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('main.dashboard'))

    org_id = _get_org_id()

    rc = RequerimientoCompra.query.get_or_404(rc_id)
    if rc.organizacion_id != org_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('requerimientos.lista'))

    elegida = CotizacionProveedor.query.filter_by(
        requerimiento_id=rc.id, estado='elegida'
    ).first()

    if not elegida:
        flash('Debe elegir una cotización antes de generar la OC.', 'warning')
        return redirect(url_for('cotizaciones.gestionar', rc_id=rc_id))

    # Redirigir a crear OC con parámetros de la cotización elegida
    return redirect(url_for('ordenes_compra.crear',
                          requerimiento_id=rc.id,
                          cotizacion_id=elegida.id))


# ============================================================
# PDF: COTIZACIÓN INDIVIDUAL
# ============================================================

@cotizaciones_bp.route('/<int:id>/pdf')
@login_required
def pdf_cotizacion(id):
    """Genera PDF del presupuesto de un proveedor."""
    from models.proveedores_oc import CotizacionProveedor
    from weasyprint import HTML
    import io, os, base64

    cot = CotizacionProveedor.query.get_or_404(id)
    if cot.organizacion_id != _get_org_id():
        flash('Sin acceso.', 'danger')
        return redirect(url_for('requerimientos.lista'))

    organizacion = cot.organizacion
    rc = cot.requerimiento

    # Solo items con precio > 0
    items_con_precio = [i for i in cot.items if i.precio_unitario and float(i.precio_unitario) > 0]

    # Logo
    logo_base64 = None
    if organizacion and organizacion.logo_url:
        try:
            logo_path = os.path.join(current_app.static_folder, organizacion.logo_url)
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass

    html_string = render_template('pdf_cotizacion.html',
        cot=cot, rc=rc, items=items_con_precio,
        organizacion=organizacion, logo_base64=logo_base64)

    from flask import send_file
    pdf_buffer = io.BytesIO()
    HTML(string=html_string).write_pdf(pdf_buffer, presentational_hints=True)
    pdf_buffer.seek(0)

    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True,
                     download_name=f'Cotizacion_{cot.proveedor.razon_social}_{rc.numero}.pdf')


# ============================================================
# PDF: COMPARATIVA DE COTIZACIONES
# ============================================================

@cotizaciones_bp.route('/requerimiento/<int:rc_id>/comparativa-pdf')
@login_required
def pdf_comparativa(rc_id):
    """Genera PDF comparativo de todas las cotizaciones."""
    from models.inventory import RequerimientoCompra
    from models.proveedores_oc import CotizacionProveedor
    from weasyprint import HTML
    import io, os, base64

    if not _tiene_permiso():
        flash('Sin permisos.', 'danger')
        return redirect(url_for('main.dashboard'))

    rc = RequerimientoCompra.query.get_or_404(rc_id)
    if rc.organizacion_id != _get_org_id():
        flash('Sin acceso.', 'danger')
        return redirect(url_for('requerimientos.lista'))

    cotizaciones = CotizacionProveedor.query.filter_by(
        requerimiento_id=rc.id
    ).filter(CotizacionProveedor.estado.in_(['recibida', 'elegida'])).all()

    organizacion = rc.organizacion

    # Construir comparación
    items_rc = rc.items
    comparacion = []
    for rc_item in items_rc:
        fila = {'descripcion': rc_item.descripcion, 'cantidad': float(rc_item.cantidad),
                'unidad': rc_item.unidad, 'precios': {}}
        for cot in cotizaciones:
            cot_item = next((ci for ci in cot.items if ci.requerimiento_item_id == rc_item.id), None)
            if cot_item and cot_item.precio_unitario and float(cot_item.precio_unitario) > 0:
                fila['precios'][cot.id] = {
                    'precio': float(cot_item.precio_unitario),
                    'subtotal': float(cot_item.subtotal or 0),
                    'modalidad': cot_item.modalidad or 'compra'
                }
        if fila['precios']:
            mejor = min(fila['precios'].items(), key=lambda x: x[1]['subtotal'])
            fila['mejor_cot_id'] = mejor[0]
            comparacion.append(fila)

    totales = {cot.id: float(cot.total or 0) for cot in cotizaciones}
    mejor_total = min(totales, key=totales.get) if totales else None

    # Logo
    logo_base64 = None
    if organizacion and organizacion.logo_url:
        try:
            logo_path = os.path.join(current_app.static_folder, organizacion.logo_url)
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass

    html_string = render_template('pdf_comparativa.html',
        rc=rc, cotizaciones=cotizaciones, comparacion=comparacion,
        totales=totales, mejor_total=mejor_total,
        organizacion=organizacion, logo_base64=logo_base64)

    from flask import send_file
    pdf_buffer = io.BytesIO()
    HTML(string=html_string).write_pdf(pdf_buffer, presentational_hints=True)
    pdf_buffer.seek(0)

    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True,
                     download_name=f'Comparativa_{rc.numero}.pdf')
