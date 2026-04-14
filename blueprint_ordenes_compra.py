"""
Blueprint para Órdenes de Compra

Gestiona el ciclo de compras formales:
1. Admin/PM genera OC desde requerimiento aprobado (o libre)
2. Se emite la OC al proveedor
3. Se registra recepción parcial o total
4. Al recibir material, se actualiza automáticamente el stock de la obra
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import or_, func

ordenes_compra_bp = Blueprint('ordenes_compra', __name__, url_prefix='/ordenes-compra')


def _find_or_create_item_inventario(descripcion, unidad, precio_unitario, org_id):
    """Busca un ItemInventario existente por nombre normalizado.
    Si no existe, lo crea automáticamente con datos mínimos.

    Criterio de búsqueda: nombre normalizado (lowercase, stripped) + misma org.
    Esto evita duplicados como "Cemento Portland" vs "cemento portland".

    Returns: ItemInventario.id
    """
    from models.inventory import ItemInventario
    import re

    nombre_norm = descripcion.strip()
    if not nombre_norm:
        return None

    # 1. Buscar existente por nombre exacto (case-insensitive)
    existente = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        func.lower(ItemInventario.nombre) == nombre_norm.lower(),
        ItemInventario.activo.is_(True),
    ).first()

    if existente:
        # Actualizar precio si viene uno mejor
        if precio_unitario and precio_unitario > 0:
            if not existente.precio_promedio or float(existente.precio_promedio) == 0:
                existente.precio_promedio = float(precio_unitario)
        return existente.id

    # 2. Crear nuevo ItemInventario
    # Generar código automático: OC + correlativo
    prefijo = 'OC-'
    ultimo = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.codigo.like(f'{prefijo}%'),
    ).order_by(ItemInventario.codigo.desc()).first()

    siguiente = 1
    if ultimo and ultimo.codigo:
        match = re.search(r'(\d+)$', ultimo.codigo)
        if match:
            siguiente = int(match.group(1)) + 1
    codigo = f"{prefijo}{siguiente:04d}"

    while ItemInventario.query.filter_by(codigo=codigo, organizacion_id=org_id).first():
        siguiente += 1
        codigo = f"{prefijo}{siguiente:04d}"

    nuevo = ItemInventario(
        codigo=codigo,
        nombre=nombre_norm,
        descripcion=f'Creado automáticamente desde Orden de Compra',
        unidad=unidad or 'u',
        stock_actual=0,
        stock_minimo=0,
        precio_promedio=float(precio_unitario) if precio_unitario else 0,
        activo=True,
        organizacion_id=org_id,
    )
    db.session.add(nuevo)
    db.session.flush()  # Para obtener el ID
    return nuevo.id


def _tiene_permiso_oc():
    """Verifica si el usuario puede gestionar OC (admin o PM)."""
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm')


# ============================================================
# LISTA DE ÓRDENES DE COMPRA
# ============================================================

@ordenes_compra_bp.route('/')
@login_required
def lista():
    from models.inventory import OrdenCompra
    from models.projects import Obra

    if not _tiene_permiso_oc():
        flash('No tiene permisos para acceder a órdenes de compra.', 'danger')
        return redirect(url_for('main.dashboard'))

    org_id = current_user.organizacion_id

    # Filtros
    estado = request.args.get('estado', '')
    obra_id = request.args.get('obra_id', type=int)
    proveedor_q = request.args.get('proveedor', '')

    query = OrdenCompra.query.filter_by(organizacion_id=org_id)

    if estado:
        query = query.filter_by(estado=estado)
    if obra_id:
        query = query.filter_by(obra_id=obra_id)
    if proveedor_q:
        query = query.filter(OrdenCompra.proveedor.ilike(f'%{proveedor_q}%'))

    ordenes = query.order_by(OrdenCompra.created_at.desc()).all()

    # Conteos por estado
    base_q = OrdenCompra.query.filter_by(organizacion_id=org_id)
    conteos = {}
    for est in ['borrador', 'emitida', 'recibida_parcial', 'completada', 'cancelada']:
        conteos[est] = base_q.filter_by(estado=est).count()

    obras = Obra.query.filter_by(organizacion_id=org_id).filter(Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

    return render_template('ordenes_compra/lista.html',
                         ordenes=ordenes, conteos=conteos,
                         estado_filtro=estado, obra_id_filtro=obra_id,
                         proveedor_filtro=proveedor_q, obras=obras,
                         today=date.today())


# ============================================================
# CREAR ORDEN DE COMPRA
# ============================================================

@ordenes_compra_bp.route('/nueva', methods=['GET', 'POST'])
@login_required
def crear():
    from models.inventory import OrdenCompra, OrdenCompraItem, RequerimientoCompra
    from models.projects import Obra

    if not _tiene_permiso_oc():
        flash('No tiene permisos para crear órdenes de compra.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    org_id = current_user.organizacion_id

    if request.method == 'POST':
        try:
            obra_id = request.form.get('obra_id', type=int)
            requerimiento_id = request.form.get('requerimiento_id', type=int) or None
            proveedor_oc_id = request.form.get('proveedor_oc_id', type=int) or None
            proveedor = request.form.get('proveedor', '').strip()
            proveedor_cuit = request.form.get('proveedor_cuit', '').strip()
            proveedor_contacto = request.form.get('proveedor_contacto', '').strip()

            # Si se selecciono un proveedor del catalogo, copiar datos como snapshot
            if proveedor_oc_id:
                from models.proveedores_oc import ProveedorOC
                prov_obj = ProveedorOC.query.get(proveedor_oc_id)
                if prov_obj and prov_obj.organizacion_id == org_id:
                    proveedor = proveedor or prov_obj.razon_social
                    proveedor_cuit = proveedor_cuit or (prov_obj.cuit or '')
                    proveedor_contacto = proveedor_contacto or (prov_obj.telefono or '')
            moneda = request.form.get('moneda', 'ARS')
            condicion_pago = request.form.get('condicion_pago', '').strip()
            fecha_entrega_str = request.form.get('fecha_entrega_estimada', '')
            notas = request.form.get('notas', '').strip()

            if not obra_id or not proveedor:
                flash('Obra y proveedor son obligatorios.', 'danger')
                return redirect(request.url)

            oc = OrdenCompra(
                numero=OrdenCompra.generar_numero(org_id),
                organizacion_id=org_id,
                obra_id=obra_id,
                requerimiento_id=requerimiento_id,
                proveedor_oc_id=proveedor_oc_id,
                proveedor=proveedor,
                proveedor_cuit=proveedor_cuit,
                proveedor_contacto=proveedor_contacto,
                estado='borrador',
                moneda=moneda,
                condicion_pago=condicion_pago,
                notas=notas,
                created_by_id=current_user.id,
                fecha_emision=date.today(),
            )

            if fecha_entrega_str:
                try:
                    oc.fecha_entrega_estimada = datetime.strptime(fecha_entrega_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            db.session.add(oc)
            db.session.flush()

            # Procesar items del formulario
            idx = 0
            while True:
                desc = request.form.get(f'item_descripcion_{idx}')
                if desc is None:
                    break
                desc = desc.strip()
                if not desc:
                    idx += 1
                    continue

                cantidad = request.form.get(f'item_cantidad_{idx}', '0')
                unidad = request.form.get(f'item_unidad_{idx}', 'unidad')
                precio = request.form.get(f'item_precio_{idx}', '0')
                item_inv_id = request.form.get(f'item_inventario_id_{idx}', type=int) or None

                try:
                    cant_val = Decimal(str(cantidad).replace(',', '.'))
                    precio_val = Decimal(str(precio).replace(',', '.'))
                except Exception:
                    cant_val = Decimal('0')
                    precio_val = Decimal('0')

                # Auto-crear o vincular ItemInventario si no viene seleccionado
                if not item_inv_id and desc:
                    item_inv_id = _find_or_create_item_inventario(
                        desc, unidad, float(precio_val), org_id
                    )

                item = OrdenCompraItem(
                    orden_compra_id=oc.id,
                    item_inventario_id=item_inv_id,
                    descripcion=desc,
                    cantidad=cant_val,
                    unidad=unidad,
                    precio_unitario=precio_val,
                    subtotal=cant_val * precio_val,
                )
                db.session.add(item)
                idx += 1

            oc.recalcular_totales()

            # Si viene de un requerimiento, marcar como en_proceso
            if requerimiento_id:
                req = RequerimientoCompra.query.filter_by(id=requerimiento_id, organizacion_id=org_id).first()
                if req and req.estado == 'aprobado':
                    req.marcar_en_proceso()

            db.session.commit()
            flash(f'Orden de compra {oc.numero} creada exitosamente.', 'success')
            return redirect(url_for('ordenes_compra.detalle', id=oc.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creando OC: {e}")
            flash(f'Error al crear la orden de compra: {str(e)}', 'danger')
            return redirect(request.url)

    # GET
    obras = Obra.query.filter_by(organizacion_id=org_id).filter(Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

    # Si viene de un requerimiento, precargar datos
    requerimiento = None
    requerimiento_id = request.args.get('requerimiento_id', type=int)
    items_precarga = []
    cotizacion_precarga = None

    if requerimiento_id:
        requerimiento = RequerimientoCompra.query.get(requerimiento_id)
        if requerimiento and requerimiento.organizacion_id == org_id:
            # Verificar si hay cotización elegida para usar sus precios
            cotizacion_id = request.args.get('cotizacion_id', type=int)
            if cotizacion_id:
                from models.proveedores_oc import CotizacionProveedor
                cot = CotizacionProveedor.query.get(cotizacion_id)
                if cot and cot.organizacion_id == org_id and cot.estado == 'elegida':
                    cotizacion_precarga = cot
                    # Precargar items con precios de la cotización
                    for cot_item in cot.items:
                        items_precarga.append({
                            'descripcion': cot_item.descripcion,
                            'cantidad': float(cot_item.cantidad or 0),
                            'unidad': cot_item.unidad or 'unidad',
                            'precio_unitario': float(cot_item.precio_unitario or 0),
                            'item_inventario_id': cot_item.item_inventario_id,
                        })

            # Si no hay cotización, usar items del RC con costo estimado
            if not items_precarga:
                for item in requerimiento.items:
                    items_precarga.append({
                        'descripcion': item.descripcion,
                        'cantidad': float(item.cantidad or 0),
                        'unidad': item.unidad or 'unidad',
                        'precio_unitario': float(item.costo_estimado or 0),
                        'item_inventario_id': item.item_inventario_id,
                    })

    return render_template('ordenes_compra/crear.html',
                         obras=obras, requerimiento=requerimiento,
                         items_precarga=items_precarga,
                         cotizacion_precarga=cotizacion_precarga)


# ============================================================
# DETALLE DE ORDEN DE COMPRA
# ============================================================

@ordenes_compra_bp.route('/<int:id>')
@login_required
def detalle(id):
    from models.inventory import OrdenCompra

    if not _tiene_permiso_oc():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('main.dashboard'))

    oc = OrdenCompra.query.get_or_404(id)
    if oc.organizacion_id != current_user.organizacion_id:
        flash('No tiene acceso a esta orden de compra.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    return render_template('ordenes_compra/detalle.html', oc=oc)


# ============================================================
# EMITIR OC
# ============================================================

@ordenes_compra_bp.route('/<int:id>/emitir', methods=['POST'])
@login_required
def emitir(id):
    from models.inventory import OrdenCompra

    if not _tiene_permiso_oc():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    oc = OrdenCompra.query.get_or_404(id)
    if oc.organizacion_id != current_user.organizacion_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    if oc.estado != 'borrador':
        flash('Solo se puede emitir una OC en borrador.', 'warning')
        return redirect(url_for('ordenes_compra.detalle', id=oc.id))

    if oc.total_items == 0:
        flash('No se puede emitir una OC sin items.', 'warning')
        return redirect(url_for('ordenes_compra.detalle', id=oc.id))

    oc.estado = 'emitida'
    oc.fecha_emision = date.today()
    db.session.commit()

    # Notificar al PM y admins de la obra sobre la OC emitida
    try:
        _notificar_oc_emitida(oc)
    except Exception:
        current_app.logger.exception('Error al notificar OC emitida')

    flash(f'OC {oc.numero} emitida exitosamente.', 'success')
    return redirect(url_for('ordenes_compra.detalle', id=oc.id))


# ============================================================
# ACTUALIZAR FECHA DE ENTREGA
# ============================================================

@ordenes_compra_bp.route('/<int:id>/fecha-entrega', methods=['POST'])
@login_required
def actualizar_fecha_entrega(id):
    from models.inventory import OrdenCompra

    if not _tiene_permiso_oc():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    oc = OrdenCompra.query.get_or_404(id)
    if oc.organizacion_id != current_user.organizacion_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    fecha_str = request.form.get('fecha_entrega_estimada', '')
    if fecha_str:
        try:
            oc.fecha_entrega_estimada = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            db.session.commit()
            flash(f'Fecha de entrega actualizada a {oc.fecha_entrega_estimada.strftime("%d/%m/%Y")}.', 'success')
        except ValueError:
            flash('Formato de fecha inválido.', 'danger')
    else:
        oc.fecha_entrega_estimada = None
        db.session.commit()
        flash('Fecha de entrega eliminada.', 'info')

    return redirect(url_for('ordenes_compra.detalle', id=oc.id))


# ============================================================
# CANCELAR OC
# ============================================================

@ordenes_compra_bp.route('/<int:id>/cancelar', methods=['POST'])
@login_required
def cancelar(id):
    from models.inventory import OrdenCompra

    if not _tiene_permiso_oc():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    oc = OrdenCompra.query.get_or_404(id)
    if oc.organizacion_id != current_user.organizacion_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    if oc.estado in ('completada', 'cancelada'):
        flash('No se puede cancelar esta OC.', 'warning')
        return redirect(url_for('ordenes_compra.detalle', id=oc.id))

    oc.estado = 'cancelada'
    db.session.commit()
    flash(f'OC {oc.numero} cancelada.', 'info')
    return redirect(url_for('ordenes_compra.detalle', id=oc.id))


# ============================================================
# REGISTRAR RECEPCIÓN
# ============================================================

@ordenes_compra_bp.route('/<int:id>/recepcion', methods=['GET', 'POST'])
@login_required
def recepcion(id):
    from models.inventory import OrdenCompra, RecepcionOC, RecepcionOCItem, StockObra, MovimientoStockObra

    if not _tiene_permiso_oc():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    oc = OrdenCompra.query.get_or_404(id)
    if oc.organizacion_id != current_user.organizacion_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    if oc.estado not in ('emitida', 'recibida_parcial'):
        flash('Solo se puede registrar recepción en OC emitidas.', 'warning')
        return redirect(url_for('ordenes_compra.detalle', id=oc.id))

    if request.method == 'POST':
        try:
            fecha_str = request.form.get('fecha_recepcion', '')
            remito = request.form.get('remito_numero', '').strip()
            notas = request.form.get('notas', '').strip()

            try:
                fecha_recepcion = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else date.today()
            except ValueError:
                fecha_recepcion = date.today()

            recepcion = RecepcionOC(
                orden_compra_id=oc.id,
                fecha_recepcion=fecha_recepcion,
                recibido_por_id=current_user.id,
                remito_numero=remito,
                notas=notas,
            )
            db.session.add(recepcion)
            db.session.flush()

            alguno_recibido = False
            for oc_item in oc.items:
                cant_str = request.form.get(f'cantidad_{oc_item.id}', '0')
                try:
                    cant = Decimal(str(cant_str).replace(',', '.'))
                except Exception:
                    cant = Decimal('0')

                if cant <= 0:
                    continue

                # No recibir más de lo pendiente
                pendiente = Decimal(str(oc_item.pendiente_recibir))
                if cant > pendiente:
                    cant = pendiente

                alguno_recibido = True

                # Crear item de recepción
                rec_item = RecepcionOCItem(
                    recepcion_id=recepcion.id,
                    oc_item_id=oc_item.id,
                    cantidad_recibida=cant,
                )
                db.session.add(rec_item)

                # Actualizar cantidad recibida en el item de OC
                oc_item.cantidad_recibida = Decimal(str(oc_item.cantidad_recibida or 0)) + cant

                # Actualizar stock de la obra
                if oc_item.item_inventario_id:
                    stock = StockObra.query.filter_by(
                        obra_id=oc.obra_id,
                        item_inventario_id=oc_item.item_inventario_id
                    ).first()
                    if stock:
                        stock.cantidad_disponible = Decimal(str(stock.cantidad_disponible or 0)) + cant
                        stock.fecha_ultimo_traslado = datetime.utcnow()
                    else:
                        stock = StockObra(
                            obra_id=oc.obra_id,
                            item_inventario_id=oc_item.item_inventario_id,
                            cantidad_disponible=cant,
                            fecha_ultimo_traslado=datetime.utcnow(),
                        )
                        db.session.add(stock)
                    db.session.flush()

                    # Registrar movimiento de entrada con precio de OC
                    mov_entrada = MovimientoStockObra(
                        stock_obra_id=stock.id,
                        tipo='entrada',
                        cantidad=float(cant),
                        fecha=datetime.utcnow(),
                        usuario_id=current_user.id,
                        observaciones=f'Recepción OC {oc.numero}' + (f' - Remito: {remito}' if remito else ''),
                        precio_unitario=float(oc_item.precio_unitario or 0),
                        moneda=oc.moneda or 'ARS'
                    )
                    db.session.add(mov_entrada)

            if not alguno_recibido:
                db.session.rollback()
                flash('Debe ingresar al menos una cantidad recibida.', 'warning')
                return redirect(url_for('ordenes_compra.recepcion', id=oc.id))

            # Actualizar estado de OC
            todos_completos = all(i.recepcion_completa for i in oc.items)
            if todos_completos:
                oc.estado = 'completada'
                oc.fecha_entrega_real = fecha_recepcion
                # Completar requerimiento si existe
                if oc.requerimiento and oc.requerimiento.estado != 'completado':
                    oc.requerimiento.completar()
                # Guardar historial de precios del proveedor
                if oc.proveedor_oc_id:
                    try:
                        from models.proveedores_oc import HistorialPrecioProveedor
                        for oc_item in oc.items:
                            if float(oc_item.precio_unitario or 0) > 0:
                                hist = HistorialPrecioProveedor(
                                    proveedor_id=oc.proveedor_oc_id,
                                    item_inventario_id=oc_item.item_inventario_id,
                                    descripcion_item=oc_item.descripcion,
                                    precio_unitario=oc_item.precio_unitario,
                                    moneda=oc.moneda,
                                    orden_compra_id=oc.id,
                                    fecha=fecha_recepcion,
                                )
                                db.session.add(hist)
                    except Exception as hist_err:
                        current_app.logger.warning(f"Error guardando historial precios: {hist_err}")
            else:
                oc.estado = 'recibida_parcial'

            db.session.commit()

            if todos_completos:
                flash(f'Recepción completa registrada. OC {oc.numero} completada.', 'success')
            else:
                flash(f'Recepción parcial registrada para OC {oc.numero}.', 'success')

            return redirect(url_for('ordenes_compra.detalle', id=oc.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error en recepción OC: {e}")
            flash(f'Error al registrar recepción: {str(e)}', 'danger')
            return redirect(url_for('ordenes_compra.recepcion', id=oc.id))

    # GET
    return render_template('ordenes_compra/recepcion.html', oc=oc)


@ordenes_compra_bp.route('/<int:id>/items-para-remito')
@login_required
def items_para_remito(id):
    """Retorna items de una OC para pre-llenar un remito."""
    from models.inventory import OrdenCompra

    oc = OrdenCompra.query.get_or_404(id)
    if oc.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin acceso'}), 403

    items = []
    for item in oc.items:
        items.append({
            'oc_item_id': item.id,
            'item_inventario_id': item.item_inventario_id,
            'descripcion': item.descripcion,
            'cantidad': float(item.cantidad or 0),
            'cantidad_recibida': float(item.cantidad_recibida or 0),
            'pendiente': float(item.pendiente_recibir) if hasattr(item, 'pendiente_recibir') else float((item.cantidad or 0) - (item.cantidad_recibida or 0)),
            'unidad': item.unidad or 'u',
            'precio_unitario': float(item.precio_unitario or 0),
        })

    return jsonify({
        'ok': True,
        'oc_numero': oc.numero,
        'proveedor': oc.proveedor_oc.razon_social if oc.proveedor_oc else '',
        'moneda': oc.moneda or 'ARS',
        'items': items
    })


@ordenes_compra_bp.route('/<int:id>/pdf')
@login_required
def oc_pdf(id):
    """Genera PDF de la Orden de Compra."""
    from models.inventory import OrdenCompra
    from weasyprint import HTML
    import io, os, base64

    oc = OrdenCompra.query.get_or_404(id)
    if oc.organizacion_id != current_user.organizacion_id:
        flash('Sin acceso.', 'danger')
        return redirect(url_for('ordenes_compra.lista'))

    organizacion = oc.organizacion

    # Logo en base64
    logo_base64 = None
    if organizacion.logo_url:
        try:
            logo_path = os.path.join(current_app.static_folder, organizacion.logo_url)
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass

    html_string = render_template('pdf_oc.html',
        oc=oc,
        organizacion=organizacion,
        logo_base64=logo_base64,
    )

    from flask import send_file
    pdf_buffer = io.BytesIO()
    HTML(string=html_string).write_pdf(pdf_buffer, presentational_hints=True)
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'OC_{oc.numero}.pdf'
    )


# ============================================================
# NOTIFICACIONES DE OC
# ============================================================

def _notificar_oc_emitida(oc):
    """Notifica al PM y admins de la obra que se emitió una OC."""
    from models.core import Notificacion
    from models.projects import ObraMiembro, AsignacionObra
    from models import Usuario

    obra = oc.obra
    org_id = oc.organizacion_id
    fecha_entrega = oc.fecha_entrega_estimada

    fecha_str = fecha_entrega.strftime('%d/%m/%Y') if fecha_entrega else 'sin fecha definida'
    titulo = f'OC {oc.numero} emitida — {oc.proveedor}'
    mensaje = (
        f'Se emitió la orden de compra {oc.numero} para la obra {obra.nombre}. '
        f'Proveedor: {oc.proveedor}. '
        f'Fecha estimada de entrega: {fecha_str}.'
    )
    url = url_for('ordenes_compra.detalle', id=oc.id)

    # Buscar PMs y admins de la obra
    usuarios_notificar = set()

    # PMs asignados a la obra (ObraMiembro)
    miembros = ObraMiembro.query.filter_by(obra_id=obra.id).all()
    for m in miembros:
        if m.usuario and m.usuario.role in ('pm', 'admin'):
            usuarios_notificar.add(m.usuario_id)

    # PMs asignados via AsignacionObra
    asignaciones = AsignacionObra.query.filter_by(obra_id=obra.id).all()
    for a in asignaciones:
        if a.usuario and a.usuario.role in ('pm', 'admin'):
            usuarios_notificar.add(a.usuario_id)

    # Admins de la org
    admins = Usuario.query.filter_by(organizacion_id=org_id, role='admin').all()
    for admin in admins:
        usuarios_notificar.add(admin.id)

    for uid in usuarios_notificar:
        Notificacion.crear_notificacion(
            organizacion_id=org_id,
            usuario_id=uid,
            tipo='oc_emitida',
            titulo=titulo,
            mensaje=mensaje,
            url=url,
            referencia_tipo='orden_compra',
            referencia_id=oc.id
        )
    db.session.commit()


def notificar_entregas_proximas(app=None):
    """
    Genera alertas para OC con entrega próxima.
    Llamar diariamente (ej. desde cron o ruta admin).

    - 2 días antes de fecha_entrega_estimada: alerta inicial
    - Cada día hasta la fecha: recordatorio diario
    """
    from models.inventory import OrdenCompra
    from models.core import Notificacion
    from models.projects import ObraMiembro, AsignacionObra
    from models import Usuario

    hoy = date.today()
    en_7_dias = hoy + __import__('datetime').timedelta(days=7)

    # OCs emitidas con entrega entre hoy y 2 días
    ocs = OrdenCompra.query.filter(
        OrdenCompra.estado == 'emitida',
        OrdenCompra.fecha_entrega_estimada.isnot(None),
        OrdenCompra.fecha_entrega_estimada <= en_7_dias,
        OrdenCompra.fecha_entrega_estimada >= hoy
    ).all()

    for oc in ocs:
        dias_restantes = (oc.fecha_entrega_estimada - hoy).days
        obra = oc.obra
        org_id = oc.organizacion_id

        if dias_restantes == 0:
            titulo = f'HOY llega material — OC {oc.numero}'
            mensaje = f'Hoy es la fecha de entrega de {oc.proveedor} para {obra.nombre}.'
        elif dias_restantes == 1:
            titulo = f'MANANA llega material — OC {oc.numero}'
            mensaje = f'Manana {oc.proveedor} entrega material para {obra.nombre}.'
        else:
            titulo = f'En {dias_restantes} dias llega material — OC {oc.numero}'
            mensaje = f'{oc.proveedor} entrega material para {obra.nombre} el {oc.fecha_entrega_estimada.strftime("%d/%m/%Y")}.'

        url_oc = f'/ordenes-compra/{oc.id}'

        # Buscar PMs y admins
        usuarios_notificar = set()
        miembros = ObraMiembro.query.filter_by(obra_id=obra.id).all()
        for m in miembros:
            if m.usuario and m.usuario.role in ('pm', 'admin'):
                usuarios_notificar.add(m.usuario_id)
        asignaciones = AsignacionObra.query.filter_by(obra_id=obra.id).all()
        for a in asignaciones:
            if a.usuario and a.usuario.role in ('pm', 'admin'):
                usuarios_notificar.add(a.usuario_id)
        admins = Usuario.query.filter_by(organizacion_id=org_id, role='admin').all()
        for admin in admins:
            usuarios_notificar.add(admin.id)

        for uid in usuarios_notificar:
            # Evitar duplicados: no notificar si ya se notificó hoy para esta OC
            ya_existe = Notificacion.query.filter_by(
                usuario_id=uid,
                referencia_tipo='oc_entrega',
                referencia_id=oc.id,
            ).filter(
                db.func.date(Notificacion.fecha_creacion) == hoy
            ).first()
            if not ya_existe:
                Notificacion.crear_notificacion(
                    organizacion_id=org_id,
                    usuario_id=uid,
                    tipo='oc_entrega',
                    titulo=titulo,
                    mensaje=mensaje,
                    url=url_oc,
                    referencia_tipo='oc_entrega',
                    referencia_id=oc.id
                )
    db.session.commit()
    return len(ocs)
