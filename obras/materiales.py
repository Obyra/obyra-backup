"""Obras -- Materials/inventory integration routes."""
from flask import request, jsonify, current_app, render_template
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
from extensions import db
from models import Obra, ItemPresupuesto, UsoInventario

from services.permissions import validate_obra_ownership
from services.memberships import get_current_org_id

from obras import (
    obras_bp, _get_roles_usuario, can_manage_obra, calcular_costo_materiales,
)


@obras_bp.route('/api/obras/<int:obra_id>/reservar-materiales', methods=['POST'])
@login_required
def api_reservar_materiales(obra_id):
    """Genera reservas de stock en inventario para los materiales del presupuesto de la obra."""
    try:
        from models.inventory import ItemInventario, ReservaStock

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        presupuesto = obra.presupuestos.filter_by(confirmado_como_obra=True).first()
        if not presupuesto:
            return jsonify({'ok': False, 'error': 'Esta obra no tiene presupuesto confirmado'}), 400

        materiales = [item for item in presupuesto.items if item.tipo == 'material']

        if not materiales:
            return jsonify({'ok': False, 'error': 'No hay materiales en el presupuesto'}), 400

        reservas_creadas = []
        alertas_compra = []
        materiales_sin_vincular = []

        for material in materiales:
            if not material.item_inventario_id:
                materiales_sin_vincular.append({
                    'descripcion': material.descripcion,
                    'cantidad': float(material.cantidad),
                    'unidad': material.unidad
                })
                continue

            item_inv = ItemInventario.query.get(material.item_inventario_id)
            if not item_inv:
                materiales_sin_vincular.append({
                    'descripcion': material.descripcion,
                    'cantidad': float(material.cantidad),
                    'unidad': material.unidad
                })
                continue

            current_app.logger.info(f"Procesando material '{material.descripcion}' vinculado a '{item_inv.nombre}'")

            stock_actual = float(item_inv.stock_actual or 0)

            reservas_activas = ReservaStock.query.filter_by(
                item_inventario_id=item_inv.id,
                estado='activa'
            ).all()
            stock_reservado = sum(float(r.cantidad) for r in reservas_activas)
            stock_disponible = stock_actual - stock_reservado

            cantidad_necesaria = float(material.cantidad)

            reserva_existente = ReservaStock.query.filter_by(
                item_inventario_id=item_inv.id,
                obra_id=obra.id,
                estado='activa'
            ).first()

            if reserva_existente:
                reservas_creadas.append({
                    'material': item_inv.nombre,
                    'cantidad': float(reserva_existente.cantidad),
                    'unidad': item_inv.unidad,
                    'nota': 'Ya reservado'
                })
                continue

            if stock_disponible >= cantidad_necesaria:
                reserva = ReservaStock(
                    item_inventario_id=item_inv.id,
                    obra_id=obra.id,
                    cantidad=cantidad_necesaria,
                    estado='activa',
                    usuario_id=current_user.id
                )
                db.session.add(reserva)
                reservas_creadas.append({
                    'material': item_inv.nombre,
                    'cantidad': cantidad_necesaria,
                    'unidad': item_inv.unidad
                })
            else:
                alertas_compra.append({
                    'material': item_inv.nombre,
                    'cantidad_necesaria': cantidad_necesaria,
                    'stock_disponible': max(0, stock_disponible),
                    'faltante': cantidad_necesaria - max(0, stock_disponible),
                    'unidad': item_inv.unidad
                })

        db.session.commit()

        return jsonify({
            'ok': True,
            'reservas_creadas': len(reservas_creadas),
            'alertas_compra': len(alertas_compra),
            'materiales_sin_match': len(materiales_sin_vincular),
            'detalle': {
                'reservas': reservas_creadas,
                'alertas': alertas_compra,
                'sin_match': materiales_sin_vincular
            }
        })

    except Exception as e:
        current_app.logger.exception(f"Error al reservar materiales: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/reservas', methods=['GET'])
@login_required
def api_obtener_reservas(obra_id):
    """Obtiene las reservas de stock activas para una obra."""
    try:
        from models.inventory import ReservaStock, ItemInventario

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        reservas = ReservaStock.query.filter_by(
            obra_id=obra_id
        ).join(ItemInventario).all()

        reservas_data = []
        for r in reservas:
            reservas_data.append({
                'id': r.id,
                'item_id': r.item_inventario_id,
                'item_nombre': r.item.nombre,
                'item_codigo': r.item.codigo,
                'cantidad': float(r.cantidad),
                'unidad': r.item.unidad,
                'estado': r.estado,
                'fecha': r.fecha_reserva.strftime('%d/%m/%Y %H:%M') if r.fecha_reserva else None
            })

        return jsonify({
            'ok': True,
            'reservas': reservas_data,
            'total_activas': len([r for r in reservas_data if r['estado'] == 'activa']),
            'total_consumidas': len([r for r in reservas_data if r['estado'] == 'consumida'])
        })

    except Exception as e:
        current_app.logger.exception(f"Error al obtener reservas: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/analizar-materiales', methods=['GET'])
@login_required
def api_analizar_materiales(obra_id):
    """Analiza TODOS los materiales del presupuesto contra el inventario."""
    try:
        from models.inventory import ItemInventario, ReservaStock

        obra = Obra.query.get_or_404(obra_id)
        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        presupuesto = obra.presupuestos.filter_by(confirmado_como_obra=True).first()
        if not presupuesto:
            return jsonify({'ok': False, 'error': 'Esta obra no tiene presupuesto confirmado'}), 400

        materiales_raw = [item for item in presupuesto.items if item.tipo == 'material']
        if not materiales_raw:
            return jsonify({'ok': False, 'error': 'No hay materiales en el presupuesto'}), 400

        # Consolidar materiales duplicados
        _mat_consolidados = {}
        for item in materiales_raw:
            if item.item_inventario_id:
                key = ('inv', item.item_inventario_id)
            else:
                key = ('desc', (item.descripcion or '').strip().lower())
            if key in _mat_consolidados:
                existing = _mat_consolidados[key]
                existing['_cantidad_total'] += float(item.cantidad or 0)
            else:
                _mat_consolidados[key] = {
                    'item': item,
                    '_cantidad_total': float(item.cantidad or 0),
                }
        materiales = []
        for data in _mat_consolidados.values():
            item = data['item']
            item._cantidad_consolidada_api = data['_cantidad_total']
            materiales.append(item)

        # Obtener cantidades ya pedidas en requerimientos de compra activos
        ya_pedido_por_item = {}
        ya_pedido_por_desc = {}
        try:
            from models.inventory import RequerimientoCompra, RequerimientoCompraItem
            reqs = RequerimientoCompra.query.filter(
                RequerimientoCompra.obra_id == obra.id,
                RequerimientoCompra.estado.notin_(['cancelado', 'rechazado'])
            ).all()
            for req in reqs:
                for item in req.items:
                    cant = float(item.cantidad or 0)
                    if item.item_inventario_id:
                        ya_pedido_por_item[item.item_inventario_id] = ya_pedido_por_item.get(item.item_inventario_id, 0) + cant
                    if item.descripcion:
                        key = item.descripcion.lower().strip()
                        ya_pedido_por_desc[key] = ya_pedido_por_desc.get(key, 0) + cant
        except Exception:
            db.session.rollback()

        con_stock = []
        stock_parcial = []
        sin_stock = []
        sin_vincular = []

        for material in materiales:
            cantidad_necesaria = float(getattr(material, '_cantidad_consolidada_api', material.cantidad) or 0)
            if cantidad_necesaria <= 0:
                continue

            if not material.item_inventario_id:
                sin_vincular.append({
                    'descripcion': material.descripcion,
                    'cantidad': cantidad_necesaria,
                    'unidad': material.unidad or 'unidad',
                    'codigo': getattr(material, 'codigo_excel', '') or ''
                })
                continue

            item_inv = ItemInventario.query.get(material.item_inventario_id)
            if not item_inv:
                sin_vincular.append({
                    'descripcion': material.descripcion,
                    'cantidad': cantidad_necesaria,
                    'unidad': material.unidad or 'unidad',
                    'codigo': getattr(material, 'codigo_excel', '') or ''
                })
                continue

            stock_actual = float(item_inv.stock_actual or 0)
            reservas_activas = ReservaStock.query.filter_by(
                item_inventario_id=item_inv.id,
                estado='activa'
            ).all()
            stock_reservado = sum(float(r.cantidad) for r in reservas_activas)

            reserva_esta_obra = next(
                (r for r in reservas_activas if r.obra_id == obra.id), None
            )
            ya_reservado = float(reserva_esta_obra.cantidad) if reserva_esta_obra else 0

            stock_disponible = stock_actual - stock_reservado + ya_reservado

            cant_pedida = ya_pedido_por_item.get(item_inv.id, 0) or ya_pedido_por_desc.get(item_inv.nombre.lower().strip(), 0)

            item_data = {
                'item_inventario_id': item_inv.id,
                'descripcion': item_inv.nombre,
                'codigo': item_inv.codigo or '',
                'unidad': item_inv.unidad or 'unidad',
                'cantidad_necesaria': cantidad_necesaria,
                'stock_disponible': max(0, stock_disponible),
                'ya_reservado': ya_reservado,
                'ya_pedido': cant_pedida > 0,
                'cantidad_pedida': cant_pedida,
            }

            if ya_reservado >= cantidad_necesaria:
                item_data['estado'] = 'ya_reservado'
                con_stock.append(item_data)
            elif stock_disponible >= cantidad_necesaria:
                item_data['estado'] = 'disponible'
                item_data['a_reservar'] = cantidad_necesaria
                con_stock.append(item_data)
            elif stock_disponible > 0:
                item_data['estado'] = 'parcial'
                item_data['a_reservar'] = stock_disponible
                item_data['faltante'] = cantidad_necesaria - stock_disponible
                stock_parcial.append(item_data)
            else:
                item_data['estado'] = 'sin_stock'
                item_data['faltante'] = cantidad_necesaria
                sin_stock.append(item_data)

        return jsonify({
            'ok': True,
            'obra_nombre': obra.nombre,
            'con_stock': con_stock,
            'stock_parcial': stock_parcial,
            'sin_stock': sin_stock,
            'sin_vincular': sin_vincular,
            'resumen': {
                'total_materiales': len(con_stock) + len(stock_parcial) + len(sin_stock) + len(sin_vincular),
                'con_stock': len(con_stock),
                'parcial': len(stock_parcial),
                'sin_stock': len(sin_stock),
                'sin_vincular': len(sin_vincular)
            }
        })

    except Exception as e:
        current_app.logger.exception(f"Error al analizar materiales: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/gestionar-materiales', methods=['POST'])
@login_required
def api_gestionar_materiales(obra_id):
    """Endpoint unificado: reserva stock + crea solicitud de compra en un solo paso."""
    try:
        from models.inventory import (
            ItemInventario, ReservaStock,
            RequerimientoCompra, RequerimientoCompraItem
        )

        obra = Obra.query.get_or_404(obra_id)
        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        items_reservar = data.get('reservar', [])
        items_comprar = data.get('comprar', [])
        motivo = data.get('motivo', 'Falta de material en obra')
        prioridad = data.get('prioridad', 'normal')
        fecha_necesidad_str = data.get('fecha_necesidad')

        reservas_resultado = []
        compra_resultado = None

        # 1. Crear reservas
        for item_data in items_reservar:
            item_inv_id = item_data.get('item_inventario_id')
            cantidad = float(item_data.get('cantidad', 0))
            if not item_inv_id or cantidad <= 0:
                continue

            item_inv = ItemInventario.query.get(item_inv_id)
            if not item_inv:
                continue

            reserva_existente = ReservaStock.query.filter_by(
                item_inventario_id=item_inv.id,
                obra_id=obra.id,
                estado='activa'
            ).first()

            if reserva_existente:
                if cantidad > float(reserva_existente.cantidad):
                    reserva_existente.cantidad = cantidad
                reservas_resultado.append({
                    'material': item_inv.nombre,
                    'cantidad': float(reserva_existente.cantidad),
                    'unidad': item_inv.unidad,
                    'accion': 'actualizada'
                })
            else:
                stock_actual = float(item_inv.stock_actual or 0)
                reservas_otros = ReservaStock.query.filter(
                    ReservaStock.item_inventario_id == item_inv.id,
                    ReservaStock.estado == 'activa',
                    ReservaStock.obra_id != obra.id
                ).all()
                stock_reservado_otros = sum(float(r.cantidad) for r in reservas_otros)
                stock_libre = stock_actual - stock_reservado_otros

                cantidad_real = min(cantidad, max(0, stock_libre))
                if cantidad_real > 0:
                    reserva = ReservaStock(
                        item_inventario_id=item_inv.id,
                        obra_id=obra.id,
                        cantidad=cantidad_real,
                        estado='activa',
                        usuario_id=current_user.id
                    )
                    db.session.add(reserva)
                    reservas_resultado.append({
                        'material': item_inv.nombre,
                        'cantidad': cantidad_real,
                        'unidad': item_inv.unidad,
                        'accion': 'creada'
                    })

        # 2. Crear solicitud de compra (si hay items)
        if items_comprar:
            from datetime import datetime as dt
            org_id = current_user.organizacion_id

            # Generar numero con retry para evitar colision de unique constraint
            from sqlalchemy.exc import IntegrityError as _IntegrityError
            requerimiento = None
            for _intento in range(5):
                try:
                    requerimiento = RequerimientoCompra(
                        numero=RequerimientoCompra.generar_numero(org_id),
                        organizacion_id=org_id,
                        obra_id=obra.id,
                        solicitante_id=current_user.id,
                        motivo=motivo,
                        prioridad=prioridad,
                        fecha_necesidad=dt.strptime(fecha_necesidad_str, '%Y-%m-%d').date() if fecha_necesidad_str else None
                    )
                    db.session.add(requerimiento)
                    db.session.flush()
                    break
                except _IntegrityError:
                    db.session.rollback()
                    continue
            if not requerimiento or not requerimiento.id:
                return jsonify({'ok': False, 'error': 'No se pudo generar número de requerimiento. Intentá de nuevo.'}), 500

            for item_data in items_comprar:
                item = RequerimientoCompraItem(
                    requerimiento_id=requerimiento.id,
                    item_inventario_id=item_data.get('item_inventario_id') or None,
                    descripcion=item_data.get('descripcion', ''),
                    codigo=item_data.get('codigo', ''),
                    cantidad=float(item_data.get('cantidad', 1)),
                    unidad=item_data.get('unidad', 'unidad'),
                    cantidad_planificada=float(item_data.get('cantidad_planificada', 0)),
                    cantidad_actual_obra=float(item_data.get('cantidad_actual_obra', 0)),
                    tipo=item_data.get('tipo', 'material')
                )
                db.session.add(item)

            compra_resultado = {
                'requerimiento_id': requerimiento.id,
                'numero': requerimiento.numero,
                'items_count': len(items_comprar)
            }

        db.session.commit()

        if compra_resultado:
            try:
                from blueprint_requerimientos import _notificar_nuevo_requerimiento
                req = RequerimientoCompra.query.get(compra_resultado['requerimiento_id'])
                if req:
                    _notificar_nuevo_requerimiento(req)
            except Exception as notify_err:
                current_app.logger.warning(f"Error al notificar: {notify_err}")

        return jsonify({
            'ok': True,
            'reservas': {
                'count': len(reservas_resultado),
                'detalle': reservas_resultado
            },
            'compra': compra_resultado,
            'message': _build_result_message(reservas_resultado, compra_resultado)
        })

    except Exception as e:
        current_app.logger.exception(f"Error en gestionar-materiales: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


def _build_result_message(reservas, compra):
    """Construye mensaje de resumen para el usuario."""
    parts = []
    if reservas:
        parts.append(f'{len(reservas)} material(es) reservado(s)')
    if compra:
        parts.append(f'Solicitud de compra {compra["numero"]} creada con {compra["items_count"]} item(s)')
    return ' | '.join(parts) if parts else 'No se realizaron acciones'


@obras_bp.route('/api/obras/<int:obra_id>/consumir-material', methods=['POST'])
@login_required
def api_consumir_material(obra_id):
    """Consume material de una reserva activa."""
    try:
        from models.inventory import ReservaStock, ItemInventario, UsoInventario, MovimientoInventario
        from decimal import Decimal
        from datetime import datetime

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        reserva_id = data.get('reserva_id')
        cantidad_consumir = float(data.get('cantidad', 0))
        observaciones = data.get('observaciones', '')

        if not reserva_id or cantidad_consumir <= 0:
            return jsonify({'ok': False, 'error': 'Reserva y cantidad son requeridos'}), 400

        reserva = ReservaStock.query.get(reserva_id)
        if not reserva or reserva.obra_id != obra_id:
            return jsonify({'ok': False, 'error': 'Reserva no encontrada'}), 404

        if reserva.estado != 'activa':
            return jsonify({'ok': False, 'error': f'La reserva no esta activa (estado: {reserva.estado})'}), 400

        cantidad_reservada = float(reserva.cantidad)
        if cantidad_consumir > cantidad_reservada:
            return jsonify({
                'ok': False,
                'error': f'No puedes consumir mas de lo reservado ({cantidad_reservada} {reserva.item.unidad})'
            }), 400

        item = reserva.item

        stock_actual = float(item.stock_actual or 0)
        if stock_actual < cantidad_consumir:
            return jsonify({
                'ok': False,
                'error': f'No hay stock fisico suficiente de {item.nombre} (disponible: {stock_actual})'
            }), 400

        item.stock_actual = float(Decimal(str(stock_actual)) - Decimal(str(cantidad_consumir)))

        movimiento = MovimientoInventario(
            item_id=item.id,
            tipo='salida',
            cantidad=cantidad_consumir,
            motivo=f'Consumo en obra: {obra.nombre}',
            observaciones=observaciones or f'Consumido de reserva #{reserva_id}',
            usuario_id=current_user.id
        )
        db.session.add(movimiento)

        if cantidad_consumir >= cantidad_reservada:
            reserva.estado = 'consumida'
            reserva.fecha_consumo = datetime.utcnow()
        else:
            reserva.cantidad = float(Decimal(str(cantidad_reservada)) - Decimal(str(cantidad_consumir)))

        uso = UsoInventario(
            obra_id=obra_id,
            item_id=item.id,
            cantidad_usada=cantidad_consumir,
            observaciones=observaciones or f'Consumido de reserva #{reserva_id}',
            usuario_id=current_user.id,
            precio_unitario_al_uso=item.precio_promedio,
            moneda='ARS'
        )
        db.session.add(uso)

        db.session.commit()

        stock_restante = float(item.stock_actual or 0)
        stock_minimo = float(item.stock_minimo or 0)
        alerta_stock_bajo = stock_restante <= stock_minimo

        return jsonify({
            'ok': True,
            'mensaje': f'Consumidos {cantidad_consumir} {item.unidad} de {item.nombre}',
            'reserva_estado': reserva.estado,
            'stock_restante': stock_restante,
            'alerta_stock_bajo': alerta_stock_bajo
        })

    except Exception as e:
        current_app.logger.exception(f"Error al consumir material: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/liberar-reserva', methods=['POST'])
@login_required
def api_liberar_reserva(obra_id):
    """Libera una reserva activa (devuelve el stock al disponible)."""
    try:
        from models.inventory import ReservaStock

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        reserva_id = data.get('reserva_id')

        if not reserva_id:
            return jsonify({'ok': False, 'error': 'ID de reserva requerido'}), 400

        reserva = ReservaStock.query.get(reserva_id)
        if not reserva or reserva.obra_id != obra_id:
            return jsonify({'ok': False, 'error': 'Reserva no encontrada'}), 404

        if reserva.estado != 'activa':
            return jsonify({'ok': False, 'error': 'Solo se pueden liberar reservas activas'}), 400

        reserva.estado = 'cancelada'
        db.session.commit()

        return jsonify({
            'ok': True,
            'mensaje': f'Reserva de {reserva.item.nombre} liberada exitosamente'
        })

    except Exception as e:
        current_app.logger.exception(f"Error al liberar reserva: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ========== STOCK EN OBRA (Inventario Local) ==========

@obras_bp.route('/api/obras/<int:obra_id>/stock-obra', methods=['GET'])
@login_required
def api_obtener_stock_obra(obra_id):
    """Obtiene el stock fisico presente en una obra."""
    try:
        from models.inventory import StockObra, ItemInventario

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        stock_items = StockObra.query.filter_by(obra_id=obra_id).all()

        stock_data = []
        for s in stock_items:
            stock_data.append({
                'id': s.id,
                'item_inventario_id': s.item_inventario_id,
                'item_nombre': s.item.nombre,
                'item_codigo': s.item.codigo,
                'unidad': s.item.unidad,
                'cantidad_disponible': float(s.cantidad_disponible or 0),
                'cantidad_consumida': float(s.cantidad_consumida or 0),
                'fecha_ultimo_traslado': s.fecha_ultimo_traslado.isoformat() if s.fecha_ultimo_traslado else None,
                'fecha_ultimo_uso': s.fecha_ultimo_uso.isoformat() if s.fecha_ultimo_uso else None
            })

        return jsonify({
            'ok': True,
            'stock': stock_data,
            'total_items': len(stock_data)
        })

    except Exception as e:
        current_app.logger.exception(f"Error al obtener stock de obra: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/usar-stock', methods=['POST'])
@login_required
def api_usar_stock_obra(obra_id):
    """Registra el uso/consumo de material del stock de la obra."""
    try:
        from models.inventory import StockObra, MovimientoStockObra
        from decimal import Decimal
        from datetime import datetime

        obra = Obra.query.get_or_404(obra_id)

        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        stock_obra_id = data.get('stock_obra_id')
        cantidad = float(data.get('cantidad', 0))
        observaciones = data.get('observaciones', '')

        if not stock_obra_id or cantidad <= 0:
            return jsonify({'ok': False, 'error': 'Stock y cantidad son requeridos'}), 400

        stock_obra = StockObra.query.get(stock_obra_id)
        if not stock_obra or stock_obra.obra_id != obra_id:
            return jsonify({'ok': False, 'error': 'Stock no encontrado'}), 404

        disponible = float(stock_obra.cantidad_disponible or 0)
        if cantidad > disponible:
            return jsonify({
                'ok': False,
                'error': f'Stock insuficiente. Disponible: {disponible} {stock_obra.item.unidad}'
            }), 400

        stock_obra.cantidad_disponible = float(
            Decimal(str(disponible)) - Decimal(str(cantidad))
        )
        stock_obra.cantidad_consumida = float(
            Decimal(str(stock_obra.cantidad_consumida or 0)) + Decimal(str(cantidad))
        )
        stock_obra.fecha_ultimo_uso = datetime.utcnow()

        ultimo_precio_entry = db.session.query(MovimientoStockObra.precio_unitario, MovimientoStockObra.moneda)\
            .filter_by(stock_obra_id=stock_obra.id, tipo='entrada')\
            .filter(MovimientoStockObra.precio_unitario > 0)\
            .order_by(MovimientoStockObra.fecha.desc())\
            .first()
        if ultimo_precio_entry:
            precio_unitario = float(ultimo_precio_entry[0])
            moneda = ultimo_precio_entry[1] or 'ARS'
        else:
            precio_unitario = float(stock_obra.item.precio_promedio or 0)
            moneda = 'ARS'

        movimiento = MovimientoStockObra(
            stock_obra_id=stock_obra.id,
            tipo='consumo',
            cantidad=cantidad,
            fecha=datetime.utcnow(),
            usuario_id=current_user.id,
            observaciones=observaciones,
            precio_unitario=precio_unitario,
            moneda=moneda
        )
        db.session.add(movimiento)

        from models.inventory import UsoInventario
        uso = UsoInventario(
            obra_id=obra_id,
            item_id=stock_obra.item_inventario_id,
            cantidad_usada=cantidad,
            fecha_uso=datetime.utcnow().date(),
            usuario_id=current_user.id,
            observaciones=observaciones,
            precio_unitario_al_uso=precio_unitario,
            moneda=moneda
        )
        db.session.add(uso)

        db.session.commit()

        return jsonify({
            'ok': True,
            'mensaje': f'Se registro el uso de {cantidad} {stock_obra.item.unidad} de {stock_obra.item.nombre}',
            'stock_restante': float(stock_obra.cantidad_disponible),
            'costo_registrado': float(movimiento.precio_unitario or 0) * cantidad if movimiento.precio_unitario else 0
        })

    except Exception as e:
        current_app.logger.exception(f"Error al registrar uso de stock: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@obras_bp.route('/api/obras/<int:obra_id>/consumo-batch', methods=['POST'])
@login_required
def api_consumo_batch(obra_id):
    """Registra consumo de multiples materiales del stock de obra de una sola vez."""
    try:
        from models.inventory import StockObra, MovimientoStockObra, UsoInventario
        from decimal import Decimal
        from datetime import datetime

        obra = Obra.query.get_or_404(obra_id)
        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        data = request.get_json() or {}
        items = data.get('items', [])
        if not items:
            return jsonify({'ok': False, 'error': 'No se enviaron materiales'}), 400

        resultados = []
        for item_data in items:
            stock_obra_id = item_data.get('stock_obra_id')
            cantidad = float(item_data.get('cantidad', 0))
            obs = item_data.get('observaciones', '')

            if not stock_obra_id or cantidad <= 0:
                continue

            stock_obra = StockObra.query.get(stock_obra_id)
            if not stock_obra or stock_obra.obra_id != obra_id:
                continue

            disponible = float(stock_obra.cantidad_disponible or 0)
            if cantidad > disponible:
                cantidad = disponible

            if cantidad <= 0:
                continue

            stock_obra.cantidad_disponible = float(
                Decimal(str(disponible)) - Decimal(str(cantidad))
            )
            stock_obra.cantidad_consumida = float(
                Decimal(str(stock_obra.cantidad_consumida or 0)) + Decimal(str(cantidad))
            )
            stock_obra.fecha_ultimo_uso = datetime.utcnow()

            ultimo_precio_entry = db.session.query(
                MovimientoStockObra.precio_unitario, MovimientoStockObra.moneda
            ).filter_by(stock_obra_id=stock_obra.id, tipo='entrada')\
             .filter(MovimientoStockObra.precio_unitario > 0)\
             .order_by(MovimientoStockObra.fecha.desc()).first()

            if ultimo_precio_entry:
                precio_unitario = float(ultimo_precio_entry[0])
                moneda = ultimo_precio_entry[1] or 'ARS'
            else:
                precio_unitario = float(stock_obra.item.precio_promedio or 0)
                moneda = 'ARS'

            mov = MovimientoStockObra(
                stock_obra_id=stock_obra.id,
                tipo='consumo',
                cantidad=cantidad,
                fecha=datetime.utcnow(),
                usuario_id=current_user.id,
                observaciones=obs,
                precio_unitario=precio_unitario,
                moneda=moneda
            )
            db.session.add(mov)

            uso = UsoInventario(
                obra_id=obra_id,
                item_id=stock_obra.item_inventario_id,
                cantidad_usada=cantidad,
                fecha_uso=datetime.utcnow().date(),
                usuario_id=current_user.id,
                observaciones=obs,
                precio_unitario_al_uso=precio_unitario,
                moneda=moneda
            )
            db.session.add(uso)

            resultados.append({
                'nombre': stock_obra.item.nombre,
                'cantidad': cantidad,
                'costo': precio_unitario * cantidad
            })

        if not resultados:
            return jsonify({'ok': False, 'error': 'No se pudo consumir ningun material'}), 400

        # Recalcular costo real
        costo_materiales = calcular_costo_materiales(obra_id)
        from models.templates import LiquidacionMO as LiqMO, LiquidacionMOItem
        costo_mo = db.session.query(
            db.func.coalesce(db.func.sum(LiquidacionMOItem.monto), 0)
        ).join(LiqMO).filter(
            LiqMO.obra_id == obra_id,
            LiquidacionMOItem.estado == 'pagado'
        ).scalar() or Decimal('0')
        obra.costo_real = float(Decimal(str(costo_materiales)) + Decimal(str(costo_mo)))

        db.session.commit()

        return jsonify({
            'ok': True,
            'mensaje': f'Se consumieron {len(resultados)} materiales',
            'items': resultados,
            'costo_real_actualizado': float(obra.costo_real)
        })

    except Exception as e:
        current_app.logger.exception(f"Error en consumo batch: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================
# TRANSFERENCIAS: obra↔depósito, obra↔obra
# ============================================================

@obras_bp.route('/api/obras/<int:obra_id>/transferir', methods=['POST'])
@login_required
def api_transferir_material(obra_id):
    """Transfiere materiales o maquinaria entre obra↔depósito u obra↔obra.

    JSON body:
        items: [{item_inventario_id, cantidad}]
        destino_tipo: 'deposito' | 'obra'
        destino_obra_id: int (solo si destino_tipo == 'obra')
        observaciones: str (opcional)
    """
    try:
        from models.inventory import (
            StockObra, MovimientoStockObra, ItemInventario,
            MovimientoInventario,
        )

        obra_origen = Obra.query.get_or_404(obra_id)
        if obra_origen.organizacion_id != current_user.organizacion_id:
            return jsonify(ok=False, error='Sin permisos'), 403

        data = request.get_json() or {}
        items = data.get('items', [])
        destino_tipo = data.get('destino_tipo', '')  # 'deposito' | 'obra'
        destino_obra_id = data.get('destino_obra_id')
        observaciones = data.get('observaciones', '')

        if not items:
            return jsonify(ok=False, error='No se enviaron items'), 400
        if destino_tipo not in ('deposito', 'obra'):
            return jsonify(ok=False, error='destino_tipo debe ser "deposito" o "obra"'), 400

        obra_destino = None
        if destino_tipo == 'obra':
            if not destino_obra_id:
                return jsonify(ok=False, error='Falta destino_obra_id'), 400
            obra_destino = Obra.query.get_or_404(int(destino_obra_id))
            if obra_destino.organizacion_id != current_user.organizacion_id:
                return jsonify(ok=False, error='La obra destino no pertenece a tu organización'), 403
            if obra_destino.id == obra_id:
                return jsonify(ok=False, error='Origen y destino no pueden ser la misma obra'), 400

        resultados = []

        for item_data in items:
            inv_id = item_data.get('item_inventario_id')
            cantidad = float(item_data.get('cantidad', 0))
            if not inv_id or cantidad <= 0:
                continue

            # Bajar del stock de la obra origen
            stock_origen = StockObra.query.filter_by(
                obra_id=obra_id, item_inventario_id=inv_id
            ).first()
            if not stock_origen:
                continue
            disponible = float(stock_origen.cantidad_disponible or 0)
            if cantidad > disponible:
                cantidad = disponible
            if cantidad <= 0:
                continue

            stock_origen.cantidad_disponible = float(
                Decimal(str(disponible)) - Decimal(str(cantidad))
            )

            # Movimiento de salida en origen
            mov_salida = MovimientoStockObra(
                stock_obra_id=stock_origen.id,
                tipo='devolucion',
                cantidad=cantidad,
                fecha=datetime.utcnow(),
                usuario_id=current_user.id,
                observaciones=f'Transferencia a {"depósito" if destino_tipo == "deposito" else obra_destino.nombre}. {observaciones}'.strip(),
            )
            db.session.add(mov_salida)

            item_inv = ItemInventario.query.get(inv_id)
            nombre_item = item_inv.nombre if item_inv else f'Item #{inv_id}'

            if destino_tipo == 'deposito':
                # Devolver al stock central del inventario
                if item_inv:
                    item_inv.stock_actual = float(
                        Decimal(str(item_inv.stock_actual or 0)) + Decimal(str(cantidad))
                    )
                    mov_inv = MovimientoInventario(
                        item_id=inv_id,
                        tipo='entrada',
                        cantidad=cantidad,
                        fecha=datetime.utcnow(),
                        usuario_id=current_user.id,
                        observaciones=f'Devuelto desde obra {obra_origen.nombre}. {observaciones}'.strip(),
                    )
                    db.session.add(mov_inv)
            else:
                # Crear/incrementar stock en obra destino
                stock_destino = StockObra.query.filter_by(
                    obra_id=obra_destino.id, item_inventario_id=inv_id
                ).first()
                if not stock_destino:
                    stock_destino = StockObra(
                        obra_id=obra_destino.id,
                        item_inventario_id=inv_id,
                        cantidad_disponible=0,
                        cantidad_consumida=0,
                    )
                    db.session.add(stock_destino)
                    db.session.flush()

                stock_destino.cantidad_disponible = float(
                    Decimal(str(stock_destino.cantidad_disponible or 0)) + Decimal(str(cantidad))
                )
                stock_destino.fecha_ultimo_traslado = datetime.utcnow()

                mov_entrada = MovimientoStockObra(
                    stock_obra_id=stock_destino.id,
                    tipo='entrada',
                    cantidad=cantidad,
                    fecha=datetime.utcnow(),
                    usuario_id=current_user.id,
                    observaciones=f'Transferencia desde obra {obra_origen.nombre}. {observaciones}'.strip(),
                )
                db.session.add(mov_entrada)

            resultados.append({
                'nombre': nombre_item,
                'cantidad': cantidad,
                'destino': 'Depósito central' if destino_tipo == 'deposito' else obra_destino.nombre,
            })

        if not resultados:
            return jsonify(ok=False, error='No se pudo transferir ningún material'), 400

        db.session.commit()
        return jsonify(ok=True, mensaje=f'{len(resultados)} items transferidos', items=resultados)

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error en transferencia: {e}")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/api/obras/<int:obra_id>/recibir-de-deposito', methods=['POST'])
@login_required
def api_recibir_de_deposito(obra_id):
    """Transfiere materiales desde depósito central a la obra.

    JSON body:
        items: [{item_inventario_id, cantidad}]
        observaciones: str (opcional)
    """
    try:
        from models.inventory import (
            StockObra, MovimientoStockObra, ItemInventario,
            MovimientoInventario,
        )

        obra = Obra.query.get_or_404(obra_id)
        if obra.organizacion_id != current_user.organizacion_id:
            return jsonify(ok=False, error='Sin permisos'), 403

        data = request.get_json() or {}
        items = data.get('items', [])
        observaciones = data.get('observaciones', '')

        if not items:
            return jsonify(ok=False, error='No se enviaron items'), 400

        resultados = []

        for item_data in items:
            inv_id = item_data.get('item_inventario_id')
            cantidad = float(item_data.get('cantidad', 0))
            if not inv_id or cantidad <= 0:
                continue

            item_inv = ItemInventario.query.get(inv_id)
            if not item_inv or item_inv.organizacion_id != current_user.organizacion_id:
                continue

            stock_central = float(item_inv.stock_actual or 0)
            if cantidad > stock_central:
                cantidad = stock_central
            if cantidad <= 0:
                continue

            # Bajar del depósito central
            item_inv.stock_actual = float(
                Decimal(str(stock_central)) - Decimal(str(cantidad))
            )
            mov_inv = MovimientoInventario(
                item_id=inv_id,
                tipo='salida',
                cantidad=cantidad,
                fecha=datetime.utcnow(),
                usuario_id=current_user.id,
                observaciones=f'Enviado a obra {obra.nombre}. {observaciones}'.strip(),
            )
            db.session.add(mov_inv)

            # Subir al stock de la obra
            stock_obra = StockObra.query.filter_by(
                obra_id=obra_id, item_inventario_id=inv_id
            ).first()
            if not stock_obra:
                stock_obra = StockObra(
                    obra_id=obra_id,
                    item_inventario_id=inv_id,
                    cantidad_disponible=0,
                    cantidad_consumida=0,
                )
                db.session.add(stock_obra)
                db.session.flush()

            stock_obra.cantidad_disponible = float(
                Decimal(str(stock_obra.cantidad_disponible or 0)) + Decimal(str(cantidad))
            )
            stock_obra.fecha_ultimo_traslado = datetime.utcnow()

            mov_entrada = MovimientoStockObra(
                stock_obra_id=stock_obra.id,
                tipo='entrada',
                cantidad=cantidad,
                fecha=datetime.utcnow(),
                usuario_id=current_user.id,
                observaciones=f'Desde depósito central. {observaciones}'.strip(),
                precio_unitario=float(item_inv.precio_promedio or 0),
                moneda='ARS',
            )
            db.session.add(mov_entrada)

            resultados.append({
                'nombre': item_inv.nombre,
                'cantidad': cantidad,
            })

        if not resultados:
            return jsonify(ok=False, error='No se pudo transferir ningún material'), 400

        db.session.commit()
        return jsonify(ok=True, mensaje=f'{len(resultados)} items recibidos en obra', items=resultados)

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error recibiendo de depósito: {e}")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/api/inventario-con-stock', methods=['GET'])
@login_required
def api_inventario_con_stock():
    """Devuelve items de inventario con stock > 0 para transferir a obras."""
    try:
        from models.inventory import ItemInventario
        org_id = get_current_org_id() or current_user.organizacion_id
        items = ItemInventario.query.filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.activo.is_(True),
            ItemInventario.stock_actual > 0,
        ).order_by(ItemInventario.nombre).all()

        return jsonify(ok=True, items=[{
            'id': i.id,
            'nombre': i.nombre,
            'codigo': i.codigo,
            'unidad': i.unidad,
            'stock_actual': float(i.stock_actual or 0),
        } for i in items])
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
