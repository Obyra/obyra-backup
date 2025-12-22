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

    requerimientos = query.all()

    # Obtener obras para filtro
    obras = Obra.query.filter_by(organizacion_id=org_id).order_by(Obra.nombre).all()

    # Contar por estado para badges
    conteos = db.session.query(
        RequerimientoCompra.estado,
        func.count(RequerimientoCompra.id)
    ).filter_by(organizacion_id=org_id).group_by(RequerimientoCompra.estado).all()

    conteos_dict = dict(conteos)

    return render_template('requerimientos/lista.html',
                          requerimientos=requerimientos,
                          obras=obras,
                          estado_filtro=estado,
                          prioridad_filtro=prioridad,
                          obra_id_filtro=obra_id,
                          conteos=conteos_dict)


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
            flash(f'Error al crear requerimiento: {str(e)}', 'danger')
            return redirect(url_for('requerimientos.crear', obra_id=obra_id))

    # GET - mostrar formulario
    obras = Obra.query.filter_by(
        organizacion_id=org_id
    ).filter(Obra.estado.in_(['planificacion', 'en_curso'])).order_by(Obra.nombre).all()

    obra_seleccionada = None
    materiales_obra = []

    if obra_id:
        obra_seleccionada = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first()
        if obra_seleccionada:
            # Obtener materiales planificados vs disponibles en la obra
            materiales_obra = _obtener_materiales_obra(obra_seleccionada)

    # Items de inventario para selector
    items_inventario = ItemInventario.query.filter_by(
        organizacion_id=org_id,
        activo=True
    ).order_by(ItemInventario.nombre).all()

    return render_template('requerimientos/crear.html',
                          obras=obras,
                          obra_seleccionada=obra_seleccionada,
                          materiales_obra=materiales_obra,
                          items_inventario=items_inventario)


@requerimientos_bp.route('/<int:id>')
@login_required
def detalle(id):
    """Ver detalle de un requerimiento"""
    from models.inventory import RequerimientoCompra

    requerimiento = RequerimientoCompra.query.filter_by(
        id=id,
        organizacion_id=current_user.organizacion_id
    ).first_or_404()

    return render_template('requerimientos/detalle.html',
                          requerimiento=requerimiento)


@requerimientos_bp.route('/<int:id>/aprobar', methods=['POST'])
@login_required
def aprobar(id):
    """Aprobar un requerimiento"""
    from models.inventory import RequerimientoCompra

    # Solo administradores pueden aprobar
    if current_user.rol not in ['administrador', 'admin']:
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
    if current_user.rol not in ['administrador', 'admin']:
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

    if current_user.rol not in ['administrador', 'admin']:
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

    flash(f'Requerimiento {requerimiento.numero} marcado como en proceso', 'info')
    return redirect(url_for('requerimientos.detalle', id=id))


@requerimientos_bp.route('/<int:id>/completar', methods=['POST'])
@login_required
def completar(id):
    """Marcar requerimiento como completado"""
    from models.inventory import RequerimientoCompra

    if current_user.rol not in ['administrador', 'admin']:
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
    if requerimiento.solicitante_id != current_user.id and current_user.rol not in ['administrador', 'admin']:
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
        return jsonify({'ok': False, 'error': str(e)}), 500


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

    obra = Obra.query.filter_by(
        id=obra_id,
        organizacion_id=current_user.organizacion_id
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
    """Notifica a los administradores sobre un nuevo requerimiento"""
    try:
        from models.core import Notificacion

        # Usar el método de clase para notificar a todos los admins
        Notificacion.notificar_administradores(
            organizacion_id=requerimiento.organizacion_id,
            tipo='requerimiento_compra',
            titulo=f'Nuevo requerimiento de compra: {requerimiento.numero}',
            mensaje=f'{requerimiento.solicitante.nombre} solicitó materiales para {requerimiento.obra.nombre}',
            url=url_for('requerimientos.detalle', id=requerimiento.id),
            referencia_tipo='requerimiento',
            referencia_id=requerimiento.id
        )
        db.session.commit()

        current_app.logger.info(f"Notificación enviada para requerimiento {requerimiento.numero}")

    except Exception as e:
        current_app.logger.error(f"Error notificando nuevo requerimiento: {e}")


def _notificar_cambio_estado(requerimiento, nuevo_estado):
    """Notifica al solicitante sobre cambio de estado"""
    try:
        from models.core import Notificacion

        mensajes = {
            'aprobado': f'Tu requerimiento {requerimiento.numero} fue aprobado',
            'rechazado': f'Tu requerimiento {requerimiento.numero} fue rechazado',
            'en_proceso': f'Tu requerimiento {requerimiento.numero} está en proceso de compra',
            'completado': f'Tu requerimiento {requerimiento.numero} fue completado'
        }

        Notificacion.crear_notificacion(
            organizacion_id=requerimiento.organizacion_id,
            usuario_id=requerimiento.solicitante_id,
            tipo='requerimiento_estado',
            titulo=mensajes.get(nuevo_estado, f'Requerimiento {requerimiento.numero} actualizado'),
            mensaje=requerimiento.notas_aprobacion or '',
            url=url_for('requerimientos.detalle', id=requerimiento.id),
            referencia_tipo='requerimiento',
            referencia_id=requerimiento.id
        )
        db.session.commit()

        current_app.logger.info(f"Cambio estado requerimiento {requerimiento.numero} a {nuevo_estado}")

    except Exception as e:
        current_app.logger.error(f"Error notificando cambio estado: {e}")
