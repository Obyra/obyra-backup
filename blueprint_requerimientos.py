"""
Blueprint para Requerimientos de Compra

Gestiona las solicitudes de compra originadas desde obras cuando falta
material o maquinaria. El flujo es:
1. Usuario en obra detecta falta de material
2. Crea requerimiento de compra desde la obra
3. Administrador recibe notificación y revisa
4. Aprueba/rechaza el requerimiento
5. Si aprobado, se procede con la compra
6. Material llega y se marca como completado
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from datetime import datetime, date
from sqlalchemy import or_, func

requerimientos_bp = Blueprint('requerimientos', __name__, url_prefix='/requerimientos')


# ============================================================
# VISTAS PRINCIPALES
# ============================================================

@requerimientos_bp.route('/')
@login_required
def lista():
    """Lista de requerimientos de compra"""
    from models.inventory import RequerimientoCompra
    from models.projects import Obra

    org_id = current_user.organizacion_id

    # Filtros
    estado = request.args.get('estado', '')
    prioridad = request.args.get('prioridad', '')
    obra_id = request.args.get('obra_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = 25

    query = RequerimientoCompra.query.filter_by(organizacion_id=org_id)

    if estado:
        query = query.filter_by(estado=estado)
    if prioridad:
        query = query.filter_by(prioridad=prioridad)
    if obra_id:
        query = query.filter_by(obra_id=obra_id)

    # Ordenar por fecha descendente, urgentes primero
    query = query.order_by(
        RequerimientoCompra.prioridad.desc(),
        RequerimientoCompra.fecha_solicitud.desc()
    )

    total = query.count()
    total_pages = (total + per_page - 1) // per_page
    requerimientos = query.offset((page - 1) * per_page).limit(per_page).all()

    # Obtener obras para filtro
    obras = Obra.query.filter_by(organizacion_id=org_id).filter(Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

    # Contar por estado para badges
    conteos = db.session.query(
        RequerimientoCompra.estado,
        func.count(RequerimientoCompra.id)
    ).filter_by(organizacion_id=org_id).group_by(RequerimientoCompra.estado).all()

    conteos_dict = dict(conteos)

    from datetime import date
    return render_template('requerimientos/lista.html',
                          requerimientos=requerimientos,
                          obras=obras,
                          estado_filtro=estado,
                          prioridad_filtro=prioridad,
                          obra_id_filtro=obra_id,
                          conteos=conteos_dict,
                          today=date.today(),
                          page=page,
                          total_pages=total_pages)


@requerimientos_bp.route('/nuevo', methods=['GET', 'POST'])
@requerimientos_bp.route('/nuevo/<int:obra_id>', methods=['GET', 'POST'])
@login_required
def crear(obra_id=None):
    """Crear nuevo requerimiento de compra"""
    from models.inventory import RequerimientoCompra, RequerimientoCompraItem, ItemInventario
    from models.projects import Obra

    org_id = current_user.organizacion_id

    if request.method == 'POST':
        try:
            obra_id = request.form.get('obra_id', type=int)
            motivo = request.form.get('motivo', '').strip()
            prioridad = request.form.get('prioridad', 'normal')
            fecha_necesidad_str = request.form.get('fecha_necesidad')

            if not obra_id:
                flash('Debe seleccionar una obra', 'danger')
                return redirect(url_for('requerimientos.crear'))

            if not motivo:
                flash('Debe indicar el motivo del requerimiento', 'danger')
                return redirect(url_for('requerimientos.crear', obra_id=obra_id))

            # Crear requerimiento
            requerimiento = RequerimientoCompra(
                numero=RequerimientoCompra.generar_numero(org_id),
                organizacion_id=org_id,
                obra_id=obra_id,
                solicitante_id=current_user.id,
                motivo=motivo,
                prioridad=prioridad,
                fecha_necesidad=datetime.strptime(fecha_necesidad_str, '%Y-%m-%d').date() if fecha_necesidad_str else None
            )
            db.session.add(requerimiento)
            db.session.flush()  # Para obtener el ID

            # Procesar items
            items_json = request.form.get('items_json', '[]')
            import json
            items_data = json.loads(items_json)

            for item_data in items_data:
                item = RequerimientoCompraItem(
                    requerimiento_id=requerimiento.id,
                    item_inventario_id=item_data.get('item_inventario_id') or None,
                    descripcion=item_data.get('descripcion', ''),
                    codigo=item_data.get('codigo', ''),
                    cantidad=float(item_data.get('cantidad', 1)),
                    unidad=item_data.get('unidad', 'unidad'),
                    cantidad_planificada=float(item_data.get('cantidad_planificada', 0)),
                    cantidad_actual_obra=float(item_data.get('cantidad_actual_obra', 0)),
                    costo_estimado=float(item_data.get('costo_estimado')) if item_data.get('costo_estimado') else None,
                    notas=item_data.get('notas', ''),
                    tipo=item_data.get('tipo', 'material')
                )
                db.session.add(item)

            db.session.commit()

            # Notificar a administradores
            _notificar_nuevo_requerimiento(requerimiento)

            flash(f'Requerimiento {requerimiento.numero} creado exitosamente', 'success')
            return redirect(url_for('requerimientos.detalle', id=requerimiento.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creando requerimiento: {e}")
            flash('Error al crear requerimiento. Intente nuevamente.', 'danger')
            return redirect(url_for('requerimientos.crear', obra_id=obra_id))

    # GET - mostrar formulario
    obras = Obra.query.filter_by(
        organizacion_id=org_id
    ).filter(Obra.estado.in_(['planificacion', 'en_curso']), Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

    obra_seleccionada = None
    materiales_obra = []

    if obra_id:
        obra_seleccionada = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first()
        if obra_seleccionada:
            # Obtener materiales planificados vs disponibles en la obra
            materiales_obra = _obtener_materiales_obra(obra_seleccionada)

    # Ya no cargamos items_inventario aquí - ahora se buscan vía AJAX
    # para mejor rendimiento en móviles

    return render_template('requerimientos/crear.html',
                          obras=obras,
                          obra_seleccionada=obra_seleccionada,
                          materiales_obra=materiales_obra)


@requerimientos_bp.route('/<int:id>')
@login_required
def detalle(id):
    """Ver detalle de un requerimiento"""
    from models.inventory import RequerimientoCompra
    from models.proveedores_oc import ProveedorOC

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    # Cargar proveedores para el dropdown de "Cargar Precios"
    proveedores = ProveedorOC.query.filter_by(
        organizacion_id=current_user.organizacion_id,
        activo=True
    ).order_by(ProveedorOC.razon_social).all()

    # Admin/PM puede editar cantidades si no está completado ni cancelado
    puede_editar_items = (
        current_user.role in ('admin', 'pm')
        or current_user.is_super_admin
    ) and requerimiento.estado not in ('completado', 'cancelado')

    return render_template('requerimientos/detalle.html',
                          requerimiento=requerimiento,
                          proveedores=proveedores,
                          puede_editar_items=puede_editar_items)


@requerimientos_bp.route('/<int:id>/aprobar', methods=['POST'])
@login_required
def aprobar(id):
    """Aprobar un requerimiento"""
    from models.inventory import RequerimientoCompra

    # Solo administradores pueden aprobar
    if current_user.role not in ['admin']:
        flash('No tiene permisos para aprobar requerimientos', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    if requerimiento.estado != 'pendiente':
        flash('Este requerimiento ya fue procesado', 'warning')
        return redirect(url_for('requerimientos.detalle', id=id))

    notas = request.form.get('notas', '')
    requerimiento.aprobar(current_user.id, notas)
    db.session.commit()

    # Notificar al solicitante
    _notificar_cambio_estado(requerimiento, 'aprobado')

    flash(f'Requerimiento {requerimiento.numero} aprobado', 'success')
    return redirect(url_for('requerimientos.detalle', id=id))


@requerimientos_bp.route('/<int:id>/rechazar', methods=['POST'])
@login_required
def rechazar(id):
    """Rechazar un requerimiento"""
    from models.inventory import RequerimientoCompra

    # Solo administradores pueden rechazar
    if current_user.role not in ['admin']:
        flash('No tiene permisos para rechazar requerimientos', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    if requerimiento.estado != 'pendiente':
        flash('Este requerimiento ya fue procesado', 'warning')
        return redirect(url_for('requerimientos.detalle', id=id))

    notas = request.form.get('notas', '')
    if not notas:
        flash('Debe indicar el motivo del rechazo', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento.rechazar(current_user.id, notas)
    db.session.commit()

    # Notificar al solicitante
    _notificar_cambio_estado(requerimiento, 'rechazado')

    flash(f'Requerimiento {requerimiento.numero} rechazado', 'info')
    return redirect(url_for('requerimientos.detalle', id=id))


@requerimientos_bp.route('/<int:id>/en-proceso', methods=['POST'])
@login_required
def marcar_en_proceso(id):
    """Marcar requerimiento como en proceso de compra"""
    from models.inventory import RequerimientoCompra

    if current_user.role not in ['admin']:
        flash('No tiene permisos para esta acción', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    if requerimiento.estado != 'aprobado':
        flash('El requerimiento debe estar aprobado primero', 'warning')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento.marcar_en_proceso()
    db.session.commit()

    _notificar_cambio_estado(requerimiento, 'en_proceso')

    flash(f'Requerimiento {requerimiento.numero} marcado como en proceso', 'info')
    return redirect(url_for('requerimientos.detalle', id=id))


@requerimientos_bp.route('/<int:id>/completar', methods=['POST'])
@login_required
def completar(id):
    """Marcar requerimiento como completado"""
    from models.inventory import RequerimientoCompra

    if current_user.role not in ['admin']:
        flash('No tiene permisos para esta acción', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    if requerimiento.estado not in ['aprobado', 'en_proceso']:
        flash('El requerimiento debe estar aprobado o en proceso', 'warning')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento.completar()
    db.session.commit()

    # Notificar al solicitante
    _notificar_cambio_estado(requerimiento, 'completado')

    flash(f'Requerimiento {requerimiento.numero} completado', 'success')
    return redirect(url_for('requerimientos.detalle', id=id))


@requerimientos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar(id):
    """Eliminar un requerimiento.

    Modo normal: solicitante o admin puede eliminar si no está completado.
      Desvincula OCs y Remitos (deja los registros), elimina cotizaciones e items.

    Modo forzado (admin + ?forzar=1): cascada total.
      Elimina OCs vinculadas, sus Remitos (revierte StockObra), cotizaciones,
      items, y el requerimiento. Usar para limpiar data de prueba.
    """
    from models.inventory import RequerimientoCompra, RequerimientoCompraItem

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    # Solo el solicitante o admin puede eliminar
    es_admin = current_user.role in ['admin']
    es_solicitante = requerimiento.solicitante_id == current_user.id
    if not (es_admin or es_solicitante):
        flash('No tiene permisos para eliminar este requerimiento', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    forzar = request.args.get('forzar') == '1' or request.form.get('forzar') == '1'

    # Solo admin puede forzar
    if forzar and not es_admin:
        flash('Solo un admin puede forzar eliminación', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    # Sin forzar: no eliminar requerimientos completados
    if requerimiento.estado == 'completado' and not forzar:
        flash('No se puede eliminar un requerimiento completado. Si es admin, use el botón "Eliminar forzado".', 'warning')
        return redirect(url_for('requerimientos.detalle', id=id))

    numero = requerimiento.numero

    try:
        if forzar:
            _cascada_eliminar_ocs_y_remitos(id)
        else:
            # Modo normal: solo desvincular
            try:
                from models.inventory import OrdenCompra
                OrdenCompra.query.filter_by(requerimiento_id=id).update({'requerimiento_id': None})
                db.session.flush()
            except Exception:
                db.session.rollback()
            try:
                from models.inventory import Remito
                Remito.query.filter_by(requerimiento_id=id).update({'requerimiento_id': None})
                db.session.flush()
            except Exception:
                db.session.rollback()

        # Eliminar cotizaciones y sus items (FK es NOT NULL)
        try:
            from models.proveedores_oc import CotizacionProveedor, CotizacionProveedorItem
            cotizaciones = CotizacionProveedor.query.filter_by(requerimiento_id=id).all()
            for cot in cotizaciones:
                CotizacionProveedorItem.query.filter_by(cotizacion_id=cot.id).delete()
                db.session.delete(cot)
            db.session.flush()
        except Exception:
            db.session.rollback()

        # Eliminar items del requerimiento
        RequerimientoCompraItem.query.filter_by(requerimiento_id=id).delete()

        # Eliminar el requerimiento
        db.session.delete(requerimiento)
        try:
            from models.audit import registrar_audit
            accion = 'eliminar_forzado' if forzar else 'eliminar'
            registrar_audit(accion, 'requerimiento', id, f'Requerimiento {numero} eliminado')
        except Exception:
            pass
        db.session.commit()

        msg = f'Requerimiento {numero} eliminado con cascada (OCs, Remitos, Stock revertido)' if forzar \
              else f'Requerimiento {numero} eliminado'
        flash(msg, 'info')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error eliminando requerimiento {id}")
        flash(f'Error al eliminar: {str(e)}', 'danger')

    return redirect(url_for('requerimientos.lista'))


def _cascada_eliminar_ocs_y_remitos(requerimiento_id):
    """Elimina en cascada todas las OCs vinculadas al requerimiento, sus
    remitos, y revierte el StockObra generado.

    Orden de eliminación (respeta FKs):
      1. Para cada Remito de la OC:
         - Revertir StockObra por cada RemitoItem (decrementa cantidad_disponible)
         - Eliminar StockObra si quedó en 0 y sin consumos previos (con sus movimientos)
         - Eliminar Remito (cascade elimina RemitoItems)
      2. Eliminar OrdenCompra (cascade elimina OrdenCompraItems y Recepciones)
    """
    from models.inventory import (
        OrdenCompra, Remito, RemitoItem,
        StockObra, MovimientoStockObra,
    )
    from decimal import Decimal

    ocs = OrdenCompra.query.filter_by(requerimiento_id=requerimiento_id).all()

    for oc in ocs:
        remitos = list(oc.remitos_vinculados)  # materializar antes de eliminar

        for remito in remitos:
            for ri in remito.items:
                if not ri.item_inventario_id or not ri.cantidad:
                    continue

                stock = StockObra.query.filter_by(
                    obra_id=remito.obra_id,
                    item_inventario_id=ri.item_inventario_id,
                ).first()
                if not stock:
                    continue

                # Revertir cantidad_disponible
                cant = Decimal(str(ri.cantidad))
                disp = Decimal(str(stock.cantidad_disponible or 0))
                stock.cantidad_disponible = float(max(Decimal('0'), disp - cant))

                # Si quedó sin stock y sin consumos previos, eliminar StockObra
                cons = Decimal(str(stock.cantidad_consumida or 0))
                if stock.cantidad_disponible == 0 and cons == 0:
                    MovimientoStockObra.query.filter_by(stock_obra_id=stock.id).delete()
                    db.session.delete(stock)
                else:
                    # Solo eliminar movimientos del tipo 'entrada' de este remito
                    MovimientoStockObra.query.filter(
                        MovimientoStockObra.stock_obra_id == stock.id,
                        MovimientoStockObra.tipo == 'entrada',
                        MovimientoStockObra.observaciones.like(f'%Remito #{remito.numero_remito}%'),
                    ).delete(synchronize_session=False)

            db.session.delete(remito)
        db.session.flush()

        db.session.delete(oc)
        db.session.flush()


@requerimientos_bp.route('/<int:id>/cancelar', methods=['POST'])
@login_required
def cancelar(id):
    """Cancelar un requerimiento"""
    from models.inventory import RequerimientoCompra

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    # Solo el solicitante o admin puede cancelar
    if requerimiento.solicitante_id != current_user.id and current_user.role not in ['admin']:
        flash('No tiene permisos para cancelar este requerimiento', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    if requerimiento.estado in ['completado', 'cancelado']:
        flash('Este requerimiento no puede ser cancelado', 'warning')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento.estado = 'cancelado'
    db.session.commit()

    flash(f'Requerimiento {requerimiento.numero} cancelado', 'info')
    return redirect(url_for('requerimientos.lista'))


# ============================================================
# API ENDPOINTS
# ============================================================

@requerimientos_bp.route('/<int:id>/cargar-precios', methods=['POST'])
@login_required
def cargar_precios(id):
    """Cargar precios reales de compra para los items del requerimiento"""
    from models.inventory import RequerimientoCompra, RequerimientoCompraItem

    if current_user.role not in ['admin']:
        flash('No tiene permisos para esta acción', 'danger')
        return redirect(url_for('requerimientos.detalle', id=id))

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    if requerimiento.estado not in ['en_proceso', 'aprobado']:
        flash('Solo se pueden cargar precios en requerimientos aprobados o en proceso', 'warning')
        return redirect(url_for('requerimientos.detalle', id=id))

    proveedor_global = request.form.get('proveedor_global', '').strip()
    factura_global = request.form.get('factura_global', '').strip()
    from datetime import datetime as dt
    fecha_compra_str = request.form.get('fecha_compra_global', '')
    fecha_compra = dt.strptime(fecha_compra_str, '%Y-%m-%d').date() if fecha_compra_str else None

    items_actualizados = 0
    for item in requerimiento.items:
        precio_key = f'precio_{item.id}'
        cantidad_key = f'cantidad_{item.id}'
        cant_solicitada_key = f'cant_solicitada_{item.id}'

        # Actualizar cantidad solicitada si cambió
        cant_sol_str = request.form.get(cant_solicitada_key, '').strip()
        if cant_sol_str:
            try:
                item.cantidad = float(cant_sol_str)
            except (ValueError, TypeError):
                pass

        precio_str = request.form.get(precio_key, '').strip()
        if precio_str:
            try:
                item.precio_unitario_compra = float(precio_str)
                cant_str = request.form.get(cantidad_key, '').strip()
                item.cantidad_comprada = float(cant_str) if cant_str else float(item.cantidad)
                item.proveedor_compra = proveedor_global or item.proveedor_compra
                item.factura_compra = factura_global or item.factura_compra
                item.fecha_compra = fecha_compra or item.fecha_compra
                items_actualizados += 1
            except (ValueError, TypeError):
                continue

    db.session.commit()
    flash(f'Precios cargados para {items_actualizados} items. Total compra: ${requerimiento.costo_compra_total:,.2f}', 'success')
    return redirect(url_for('requerimientos.detalle', id=id))


@requerimientos_bp.route('/api/crear-desde-obra', methods=['POST'])
@login_required
def api_crear_desde_obra():
    """API para crear requerimiento desde la vista de obra"""
    from models.inventory import RequerimientoCompra, RequerimientoCompraItem
    from models.projects import Obra

    try:
        data = request.get_json() or {}
        org_id = current_user.organizacion_id

        obra_id = data.get('obra_id')
        items = data.get('items', [])
        motivo = data.get('motivo', 'Falta de material en obra')
        prioridad = data.get('prioridad', 'normal')
        fecha_necesidad_str = data.get('fecha_necesidad')

        if not obra_id:
            return jsonify({'ok': False, 'error': 'obra_id es requerido'}), 400

        if not items:
            return jsonify({'ok': False, 'error': 'Debe incluir al menos un item'}), 400

        # Verificar obra
        obra = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first()
        if not obra:
            return jsonify({'ok': False, 'error': 'Obra no encontrada'}), 404

        # Crear requerimiento
        requerimiento = RequerimientoCompra(
            numero=RequerimientoCompra.generar_numero(org_id),
            organizacion_id=org_id,
            obra_id=obra_id,
            solicitante_id=current_user.id,
            motivo=motivo,
            prioridad=prioridad,
            fecha_necesidad=datetime.strptime(fecha_necesidad_str, '%Y-%m-%d').date() if fecha_necesidad_str else None
        )
        db.session.add(requerimiento)
        db.session.flush()

        # Agregar items
        for item_data in items:
            item = RequerimientoCompraItem(
                requerimiento_id=requerimiento.id,
                item_inventario_id=item_data.get('item_inventario_id') or None,
                descripcion=item_data.get('descripcion', ''),
                codigo=item_data.get('codigo', ''),
                cantidad=float(item_data.get('cantidad', 1)),
                unidad=item_data.get('unidad', 'unidad'),
                cantidad_planificada=float(item_data.get('cantidad_planificada', 0)),
                cantidad_actual_obra=float(item_data.get('cantidad_actual_obra', 0)),
                costo_estimado=float(item_data.get('costo_estimado')) if item_data.get('costo_estimado') else None,
                notas=item_data.get('notas', ''),
                tipo=item_data.get('tipo', 'material')
            )
            db.session.add(item)

        db.session.commit()

        # Notificar
        _notificar_nuevo_requerimiento(requerimiento)

        return jsonify({
            'ok': True,
            'requerimiento_id': requerimiento.id,
            'numero': requerimiento.numero,
            'message': f'Requerimiento {requerimiento.numero} creado exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en api_crear_desde_obra: {e}")
        current_app.logger.error(f'Error requerimientos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@requerimientos_bp.route('/api/pendientes/count')
@login_required
def api_count_pendientes():
    """Retorna el conteo de requerimientos pendientes para badges"""
    from models.inventory import RequerimientoCompra

    count = RequerimientoCompra.query.filter_by(
        organizacion_id=current_user.organizacion_id,
        estado='pendiente'
    ).count()

    return jsonify({'count': count})


@requerimientos_bp.route('/api/materiales-obra/<int:obra_id>')
@login_required
def api_materiales_obra(obra_id):
    """Retorna los materiales de una obra con su estado de stock"""
    from models.projects import Obra

    from services.memberships import get_current_org_id
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(
        id=obra_id,
        organizacion_id=org_id
    ).first_or_404()

    materiales = _obtener_materiales_obra(obra)

    return jsonify({
        'ok': True,
        'materiales': materiales
    })


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def _obtener_materiales_obra(obra):
    """
    Obtiene los materiales planificados vs disponibles en una obra.
    Retorna lista de dicts con: descripcion, codigo, planificado, disponible, deficit
    """
    from models.inventory import StockUbicacion, Location, ItemInventario
    from models.projects import EtapaObra, TareaEtapa

    materiales = []

    # Obtener ubicación de la obra
    location = Location.query.filter_by(obra_id=obra.id).first()

    # Obtener materiales planificados desde presupuesto/etapas
    for presupuesto in obra.presupuestos:
        if hasattr(presupuesto, 'items') and presupuesto.items:
            for item in presupuesto.items:
                if item.tipo == 'material':
                    # Buscar stock en obra
                    stock_obra = 0
                    if location and item.item_inventario_id:
                        stock_loc = StockUbicacion.query.filter_by(
                            location_id=location.id,
                            item_id=item.item_inventario_id
                        ).first()
                        if stock_loc:
                            stock_obra = float(stock_loc.cantidad or 0)

                    cantidad_plan = float(item.cantidad or 0)
                    deficit = max(0, cantidad_plan - stock_obra)

                    materiales.append({
                        'item_inventario_id': item.item_inventario_id,
                        'descripcion': item.descripcion,
                        'codigo': item.codigo or '',
                        'unidad': item.unidad or 'unidad',
                        'cantidad_planificada': cantidad_plan,
                        'cantidad_actual_obra': stock_obra,
                        'deficit': deficit,
                        'tipo': 'material'
                    })

    # También revisar UsoInventario para obtener stock real en obra
    if location:
        stocks = StockUbicacion.query.filter_by(location_id=location.id).all()
        items_incluidos = {m['item_inventario_id'] for m in materiales if m.get('item_inventario_id')}

        for stock in stocks:
            if stock.item_id not in items_incluidos:
                item_inv = stock.item
                if item_inv:
                    materiales.append({
                        'item_inventario_id': item_inv.id,
                        'descripcion': item_inv.nombre,
                        'codigo': item_inv.codigo,
                        'unidad': item_inv.unidad or 'unidad',
                        'cantidad_planificada': 0,
                        'cantidad_actual_obra': float(stock.cantidad or 0),
                        'deficit': 0,
                        'tipo': 'material'
                    })

    return materiales


def _notificar_nuevo_requerimiento(requerimiento):
    """Notifica a los administradores y registra evento en el dashboard"""
    try:
        from models.core import Notificacion
        from models.marketplace import Event

        # 1. Notificación a admins (campana)
        Notificacion.notificar_administradores(
            organizacion_id=requerimiento.organizacion_id,
            tipo='requerimiento_compra',
            titulo=f'Nuevo requerimiento de compra: {requerimiento.numero}',
            mensaje=f'{requerimiento.solicitante.nombre} solicitó materiales para {requerimiento.obra.nombre}',
            url=url_for('requerimientos.detalle', id=requerimiento.id),
            referencia_tipo='requerimiento',
            referencia_id=requerimiento.id
        )

        # 2. Evento para el dashboard (Actividad Reciente)
        total_items = len(requerimiento.items.all()) if hasattr(requerimiento.items, 'all') else 0
        evento = Event(
            company_id=requerimiento.organizacion_id,
            project_id=requerimiento.obra_id,
            user_id=requerimiento.solicitante_id,
            type='alert',
            severity='alta' if requerimiento.prioridad in ('alta', 'urgente') else 'media',
            title=f'Solicitud de compra {requerimiento.numero}',
            description=f'{requerimiento.solicitante.nombre} solicitó {total_items} materiales para {requerimiento.obra.nombre}. Prioridad: {requerimiento.prioridad}.',
            meta={
                'requerimiento_id': requerimiento.id,
                'numero': requerimiento.numero,
                'prioridad': requerimiento.prioridad,
                'url': url_for('requerimientos.detalle', id=requerimiento.id)
            },
            created_by=requerimiento.solicitante_id
        )
        db.session.add(evento)
        db.session.commit()

        current_app.logger.info(f"Notificación + evento creados para requerimiento {requerimiento.numero}")

    except Exception as e:
        current_app.logger.error(f"Error notificando nuevo requerimiento: {e}")


def _notificar_cambio_estado(requerimiento, nuevo_estado):
    """Notifica al solicitante sobre cambio de estado y registra evento en dashboard"""
    try:
        from models.core import Notificacion
        from models.marketplace import Event

        mensajes = {
            'aprobado': f'Requerimiento {requerimiento.numero} aprobado',
            'rechazado': f'Requerimiento {requerimiento.numero} rechazado',
            'en_proceso': f'Requerimiento {requerimiento.numero} en proceso de compra',
            'completado': f'Requerimiento {requerimiento.numero} completado'
        }

        severidades = {
            'aprobado': 'media',
            'rechazado': 'alta',
            'en_proceso': 'media',
            'completado': 'baja'
        }

        titulo = mensajes.get(nuevo_estado, f'Requerimiento {requerimiento.numero} actualizado')

        # 1. Notificación al solicitante (campana)
        Notificacion.crear_notificacion(
            organizacion_id=requerimiento.organizacion_id,
            usuario_id=requerimiento.solicitante_id,
            tipo='requerimiento_estado',
            titulo=titulo,
            mensaje=requerimiento.notas_aprobacion or '',
            url=url_for('requerimientos.detalle', id=requerimiento.id),
            referencia_tipo='requerimiento',
            referencia_id=requerimiento.id
        )

        # 2. Evento para el dashboard (Actividad Reciente)
        descripcion_evento = f'{requerimiento.obra.nombre} — {titulo}'
        if requerimiento.notas_aprobacion:
            descripcion_evento += f'. Notas: {requerimiento.notas_aprobacion}'

        evento = Event(
            company_id=requerimiento.organizacion_id,
            project_id=requerimiento.obra_id,
            user_id=current_user.id,
            type='status_change',
            severity=severidades.get(nuevo_estado, 'baja'),
            title=titulo,
            description=descripcion_evento,
            meta={
                'requerimiento_id': requerimiento.id,
                'numero': requerimiento.numero,
                'estado': nuevo_estado,
                'url': url_for('requerimientos.detalle', id=requerimiento.id)
            },
            created_by=current_user.id
        )
        db.session.add(evento)
        db.session.commit()

        current_app.logger.info(f"Cambio estado requerimiento {requerimiento.numero} a {nuevo_estado}")

    except Exception as e:
        current_app.logger.error(f"Error notificando cambio estado: {e}")


# ============================================================
# API: EDITAR CANTIDAD DE ITEM
# ============================================================

@requerimientos_bp.route('/api/item/<int:item_id>/cantidad', methods=['POST'])
@login_required
def api_editar_cantidad_item(item_id):
    """Permite a admin/PM editar la cantidad de un item del requerimiento."""
    from models.inventory import RequerimientoCompraItem, RequerimientoCompra

    item = RequerimientoCompraItem.query.get_or_404(item_id)
    requerimiento = RequerimientoCompra.query.get(item.requerimiento_id)

    if not requerimiento or requerimiento.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    # Solo admin/PM pueden editar
    es_admin = current_user.role in ('admin', 'pm') or current_user.is_super_admin
    if not es_admin:
        return jsonify({'ok': False, 'error': 'Solo administradores pueden editar cantidades'}), 403

    # No editar si completado o cancelado
    if requerimiento.estado in ('completado', 'cancelado'):
        return jsonify({'ok': False, 'error': f'No se puede editar en estado {requerimiento.estado}'}), 400

    data = request.get_json()
    nueva_cantidad = data.get('cantidad')

    if nueva_cantidad is None or nueva_cantidad < 0:
        return jsonify({'ok': False, 'error': 'Cantidad inválida'}), 400

    try:
        item.cantidad = float(nueva_cantidad)
        db.session.commit()
        return jsonify({
            'ok': True,
            'item_id': item.id,
            'cantidad': float(item.cantidad)
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error requerimientos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500
