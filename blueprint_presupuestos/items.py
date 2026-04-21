"""
Item management routes: detalle, agregar_item, editar_item, eliminar_item
"""
import json
from collections import defaultdict, OrderedDict
from types import SimpleNamespace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort)
from flask_login import login_required, current_user

from extensions import db, limiter
from models import Presupuesto, ItemPresupuesto, Obra, Cliente
from models import ItemInventario
from services.calculation import BudgetCalculator, BudgetConstants
from services.memberships import get_current_org_id

from blueprint_presupuestos import presupuestos_bp, _d, _f


@presupuestos_bp.route('/<int:id>')
@login_required
def detalle(id):
    """Ver detalle de un presupuesto"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Recalcular totales del presupuesto para asegurar que estén actualizados
        presupuesto.calcular_totales()
        db.session.commit()

        # Obtener items agrupados por tipo y origen.
        # Ordenamos por etapa_nombre para permitir render con headers de etapa en el template
        # (presupuestos importados del Excel traen etapa; los viejos quedan en "Sin Etapa").
        # Excluimos items solo_interno (son del ejecutivo APU, no del pliego al cliente).
        items = ItemPresupuesto.query.filter_by(
            presupuesto_id=id, solo_interno=False,
        ).order_by(
            ItemPresupuesto.tipo,
            ItemPresupuesto.etapa_nombre,
            ItemPresupuesto.id
        ).all()

        # Agrupar por tipo
        items_materiales = [i for i in items if i.tipo == 'material']
        items_mano_obra = [i for i in items if i.tipo == 'mano_obra']
        items_equipos = [i for i in items if i.tipo == 'equipo']

        # Separar items de IA
        ia_materiales = [i for i in items if i.tipo == 'material' and i.origen == 'ia']
        ia_mano_obra = [i for i in items if i.tipo == 'mano_obra' and i.origen == 'ia']
        ia_equipos = [i for i in items if i.tipo == 'equipo' and i.origen == 'ia']
        ia_herramientas = [i for i in items if i.tipo == 'herramienta' and i.origen == 'ia']

        # Agrupar items IA por etapa para vista organizada
        ia_por_etapa = defaultdict(lambda: {'materiales': [], 'mano_obra': [], 'equipos': [], 'herramientas': []})

        # Definir orden de etapas de construccion
        etapas_orden = [
            'Trabajos Preliminares', 'Movimiento de Suelos', 'Estructura',
            'Mamposteria', 'Cubierta', 'Instalacion Sanitaria', 'Instalacion Electrica',
            'Instalacion de Gas', 'Carpinteria', 'Revestimientos', 'Pintura',
            'Vidrios', 'Pisos', 'Instalaciones Especiales', 'Limpieza Final', 'Otros'
        ]

        for item in ia_materiales:
            # Usar etapa_nombre guardado, o nombre de etapa vinculada, o 'Sin Etapa'
            nombre = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Sin Etapa')
            ia_por_etapa[nombre]['materiales'].append(item)

        for item in ia_mano_obra:
            nombre = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Sin Etapa')
            ia_por_etapa[nombre]['mano_obra'].append(item)

        for item in ia_equipos:
            nombre = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Sin Etapa')
            ia_por_etapa[nombre]['equipos'].append(item)

        for item in ia_herramientas:
            nombre = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Sin Etapa')
            ia_por_etapa[nombre]['herramientas'].append(item)

        # Unificar items duplicados (misma descripcion) dentro de cada etapa
        def _consolidar_items(items_lista):
            """Unifica items con misma descripcion sumando cantidades y totales."""
            if not items_lista:
                return items_lista
            grupos = OrderedDict()
            for item in items_lista:
                key = (item.descripcion or '').strip()
                if not key:
                    key = f'_item_{item.id}'
                if key in grupos:
                    g = grupos[key]
                    g['cantidad'] += _d(item.cantidad)
                    g['total'] += _d(item.total)
                    g['total_ars'] += _d(item.total_ars or item.total)
                    g['total_currency'] += _d(item.total_currency)
                else:
                    grupos[key] = {
                        'id': item.id,
                        'descripcion': item.descripcion,
                        'unidad': item.unidad,
                        'cantidad': _d(item.cantidad),
                        'precio_unitario': _d(item.precio_unitario),
                        'total': _d(item.total),
                        'price_unit_ars': _d(item.price_unit_ars or item.precio_unitario),
                        'total_ars': _d(item.total_ars or item.total),
                        'price_unit_currency': _d(item.price_unit_currency),
                        'total_currency': _d(item.total_currency),
                        'currency': getattr(item, 'currency', 'ARS'),
                        'origen': item.origen,
                        'tipo': item.tipo,
                    }
            result = []
            for data in grupos.values():
                cant = data['cantidad']
                if cant > 0:
                    data['precio_unitario'] = data['total'] / cant
                    data['price_unit_ars'] = data['total_ars'] / cant
                    if data['total_currency'] > 0:
                        data['price_unit_currency'] = data['total_currency'] / cant
                result.append(SimpleNamespace(**data))
            return result

        for etapa_nombre in ia_por_etapa:
            for tipo in ['materiales', 'mano_obra', 'equipos', 'herramientas']:
                ia_por_etapa[etapa_nombre][tipo] = _consolidar_items(
                    ia_por_etapa[etapa_nombre][tipo]
                )

        # Ordenar etapas segun el orden definido
        ia_por_etapa_ordenado = {}
        for etapa in etapas_orden:
            if etapa in ia_por_etapa:
                ia_por_etapa_ordenado[etapa] = ia_por_etapa[etapa]
        # Agregar etapas que no estan en el orden predefinido
        for etapa, items_etapa in ia_por_etapa.items():
            if etapa not in ia_por_etapa_ordenado:
                ia_por_etapa_ordenado[etapa] = items_etapa

        # Calcular subtotales por etapa usando Decimal
        subtotales_por_etapa = {}
        for etapa_nombre, items_etapa in ia_por_etapa_ordenado.items():
            subtotal_etapa = Decimal('0')
            subtotal_etapa_usd = Decimal('0')
            for tipo in ['materiales', 'mano_obra', 'equipos', 'herramientas']:
                for item in items_etapa[tipo]:
                    subtotal_etapa += _d(item.total)
                    subtotal_etapa_usd += _d(item.total_currency)
            subtotales_por_etapa[etapa_nombre] = {
                'total': _f(subtotal_etapa),
                'total_usd': _f(subtotal_etapa_usd)
            }

        # Calcular totales de IA
        totales_ia = {
            'materiales': sum(i.total for i in ia_materiales),
            'mano_obra': sum(i.total for i in ia_mano_obra),
            'equipos': sum(i.total for i in ia_equipos),
            'herramientas': sum(i.total for i in ia_herramientas),
        }
        totales_ia['general'] = sum(totales_ia.values())

        # Calcular totales en USD
        totales_ia_usd = {
            'materiales': sum((i.total_currency or Decimal('0')) for i in ia_materiales),
            'mano_obra': sum((i.total_currency or Decimal('0')) for i in ia_mano_obra),
            'equipos': sum((i.total_currency or Decimal('0')) for i in ia_equipos),
            'herramientas': sum((i.total_currency or Decimal('0')) for i in ia_herramientas),
        }
        totales_ia_usd['general'] = sum(totales_ia_usd.values())

        # Calcular subtotales por categoría (en moneda principal y USD)
        subtotal_materiales = sum(i.total for i in items_materiales)
        subtotal_mano_obra = sum(i.total for i in items_mano_obra)
        subtotal_equipos = sum(i.total for i in items_equipos)

        # Calcular subtotales en USD (usando total_currency si existe, o total_ars/tasa como fallback)
        tasa_usd = presupuesto.tasa_usd_venta or Decimal('0')

        def _item_usd(item):
            """Obtener total USD de un item, calculando si no existe."""
            if item.total_currency and item.total_currency > 0:
                return item.total_currency
            if tasa_usd > 0:
                ars = item.total_ars or item.total or Decimal('0')
                return (ars / tasa_usd).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return Decimal('0')

        subtotal_materiales_usd = sum(_item_usd(i) for i in items_materiales)
        subtotal_mano_obra_usd = sum(_item_usd(i) for i in items_mano_obra)
        subtotal_equipos_usd = sum(_item_usd(i) for i in items_equipos)

        # Calcular subtotales en ARS
        subtotal_materiales_ars = sum((i.total_ars or i.total or Decimal('0')) for i in items_materiales)
        subtotal_mano_obra_ars = sum((i.total_ars or i.total or Decimal('0')) for i in items_mano_obra)
        subtotal_equipos_ars = sum((i.total_ars or i.total or Decimal('0')) for i in items_equipos)

        # Calcular total general del presupuesto
        subtotal = sum(i.total for i in items)
        subtotal_usd = sum(_item_usd(i) for i in items)
        subtotal_ars = sum((i.total_ars or i.total or Decimal('0')) for i in items)
        iva_monto = subtotal * (presupuesto.iva_porcentaje / Decimal('100'))
        iva_monto_usd = subtotal_usd * (presupuesto.iva_porcentaje / Decimal('100'))
        iva_monto_ars = subtotal_ars * (presupuesto.iva_porcentaje / Decimal('100'))
        total_con_iva = subtotal + iva_monto
        total_con_iva_usd = subtotal_usd + iva_monto_usd
        total_con_iva_ars = subtotal_ars + iva_monto_ars

        # Parsear datos_proyecto para obtener información del cliente y obra
        datos_proyecto = {}
        if presupuesto.datos_proyecto:
            try:
                datos_proyecto = json.loads(presupuesto.datos_proyecto)
            except (json.JSONDecodeError, TypeError) as e:
                current_app.logger.error(f"Error al parsear datos_proyecto para presupuesto {presupuesto.id}: {e}")
                datos_proyecto = {}

        # Obtener items de inventario para el selector de vinculación
        items_inventario = ItemInventario.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).order_by(ItemInventario.nombre).all()

        # Pasar subtotales como variables separadas al template
        return render_template('presupuestos/detalle.html',
                             presupuesto=presupuesto,
                             materiales=items_materiales,
                             mano_obra=items_mano_obra,
                             equipos=items_equipos,
                             items_materiales=items_materiales,
                             items_mano_obra=items_mano_obra,
                             items_equipos=items_equipos,
                             ia_materiales=ia_materiales,
                             ia_mano_obra=ia_mano_obra,
                             ia_equipos=ia_equipos,
                             ia_herramientas=ia_herramientas,
                             ia_por_etapa=ia_por_etapa_ordenado,
                             subtotales_por_etapa=subtotales_por_etapa,
                             totales_ia=totales_ia,
                             totales_ia_usd=totales_ia_usd,
                             subtotal_materiales=subtotal_materiales,
                             subtotal_mano_obra=subtotal_mano_obra,
                             subtotal_equipos=subtotal_equipos,
                             subtotal_materiales_usd=subtotal_materiales_usd,
                             subtotal_mano_obra_usd=subtotal_mano_obra_usd,
                             subtotal_equipos_usd=subtotal_equipos_usd,
                             subtotal_materiales_ars=subtotal_materiales_ars,
                             subtotal_mano_obra_ars=subtotal_mano_obra_ars,
                             subtotal_equipos_ars=subtotal_equipos_ars,
                             subtotal=subtotal,
                             subtotal_usd=subtotal_usd,
                             subtotal_ars=subtotal_ars,
                             iva_monto=iva_monto,
                             iva_monto_usd=iva_monto_usd,
                             iva_monto_ars=iva_monto_ars,
                             total_con_iva=total_con_iva,
                             total_con_iva_usd=total_con_iva_usd,
                             total_con_iva_ars=total_con_iva_ars,
                             datos_proyecto=datos_proyecto,
                             items_inventario=items_inventario,
                             tasa_usd=tasa_usd)

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.detalle: {e}")
        flash('Error al cargar el presupuesto', 'danger')
        return redirect(url_for('presupuestos.lista'))


@presupuestos_bp.route('/<int:id>/items/agregar', methods=['POST'])
@login_required
def agregar_item(id):
    """Agregar item a presupuesto"""
    if not current_user.puede_gestionar():
        return jsonify({'ok': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'ok': False, 'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        if presupuesto.estado != 'borrador':
            flash('Solo se pueden agregar items a presupuestos en borrador', 'warning')
            return redirect(url_for('presupuestos.detalle', id=id))

        # Obtener datos del formulario
        descripcion = request.form.get('descripcion', '').strip()
        tipo = request.form.get('tipo', 'material')
        cantidad = Decimal(request.form.get('cantidad', '0'))
        unidad = request.form.get('unidad', 'un')
        precio_unitario = Decimal(request.form.get('precio_unitario', '0'))
        currency = request.form.get('currency', presupuesto.currency or 'ARS')
        item_inventario_id = request.form.get('item_inventario_id', type=int)

        # Modalidad de costo (solo aplica para tipo='equipo')
        modalidad_costo = request.form.get('modalidad_costo', 'compra')
        if modalidad_costo not in ('compra', 'alquiler'):
            modalidad_costo = 'compra'
        if tipo != 'equipo':
            modalidad_costo = None  # Solo persiste para equipos

        if not descripcion or cantidad <= 0 or precio_unitario <= 0:
            flash('Datos inválidos para el item', 'danger')
            return redirect(url_for('presupuestos.detalle', id=id))

        # Calcular total
        total = cantidad * precio_unitario

        # Calcular equivalentes en ARS y USD
        price_unit_ars = precio_unitario
        total_ars = total
        price_unit_usd = Decimal('0')
        total_usd = Decimal('0')

        tasa = Decimal(str(presupuesto.tasa_usd_venta)) if presupuesto.tasa_usd_venta else Decimal('0')

        if currency == 'USD':
            # Precio ingresado en USD
            price_unit_usd = precio_unitario
            total_usd = total
            if tasa > 0:
                price_unit_ars = BudgetCalculator.convertir_moneda(precio_unitario, tasa)
                total_ars = BudgetCalculator.convertir_moneda(total, tasa)
        else:
            # Precio ingresado en ARS → calcular equivalente USD
            price_unit_ars = precio_unitario
            total_ars = total
            if tasa > 0:
                price_unit_usd = (precio_unitario / tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                total_usd = (total / tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Crear item
        item = ItemPresupuesto(
            presupuesto_id=id,
            descripcion=descripcion,
            tipo=tipo,
            cantidad=cantidad,
            unidad=unidad,
            precio_unitario=precio_unitario,
            total=total,
            currency=currency,
            price_unit_currency=price_unit_usd,
            total_currency=total_usd,
            price_unit_ars=price_unit_ars,
            total_ars=total_ars,
            origen='manual',
            item_inventario_id=item_inventario_id if item_inventario_id else None,
            modalidad_costo=modalidad_costo
        )

        db.session.add(item)

        # Actualizar totales del presupuesto
        presupuesto.calcular_totales()
        db.session.commit()

        flash('Item agregado exitosamente', 'success')
        return redirect(url_for('presupuestos.detalle', id=id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.agregar_item: {e}")
        db.session.rollback()
        flash('Error al agregar el item', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/item/<int:id>/editar', methods=['POST'])
@login_required
def editar_item(id):
    """Editar item de presupuesto"""
    # Usar método centralizado de permisos
    if not current_user.puede_editar():
        return jsonify({'exito': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'exito': False, 'error': 'Sin organización activa'}), 400

        item = ItemPresupuesto.query.get(id)
        if not item:
            abort(404)
        presupuesto = item.presupuesto

        if presupuesto.organizacion_id != org_id:
            abort(404)

        if presupuesto.estado != 'borrador':
            return jsonify({'exito': False, 'error': 'Solo se pueden editar items de presupuestos en borrador'}), 400

        # Obtener datos del JSON
        data = request.get_json()

        # Actualizar campos básicos
        if 'descripcion' in data:
            item.descripcion = data['descripcion']
        if 'unidad' in data:
            item.unidad = data['unidad']
        if 'cantidad' in data:
            item.cantidad = Decimal(str(data['cantidad']))
        if 'precio_unitario' in data:
            item.precio_unitario = Decimal(str(data['precio_unitario']))
        if 'currency' in data:
            item.currency = data['currency']

        # Modalidad de costo (solo aplica para tipo='equipo')
        if 'modalidad_costo' in data:
            nueva_mod = data['modalidad_costo']
            if item.tipo == 'equipo' and nueva_mod in ('compra', 'alquiler'):
                item.modalidad_costo = nueva_mod

        # Recalcular total
        item.total = item.cantidad * item.precio_unitario

        # Calcular equivalentes en ARS y USD
        tasa = Decimal(str(presupuesto.tasa_usd_venta)) if presupuesto.tasa_usd_venta else Decimal('0')

        if item.currency == 'USD':
            item.price_unit_currency = item.precio_unitario
            item.total_currency = item.total
            if tasa > 0:
                item.price_unit_ars = BudgetCalculator.convertir_moneda(item.precio_unitario, tasa)
                item.total_ars = BudgetCalculator.convertir_moneda(item.total, tasa)
            else:
                item.price_unit_ars = item.precio_unitario
                item.total_ars = item.total
        else:
            item.price_unit_ars = item.precio_unitario
            item.total_ars = item.total
            if tasa > 0:
                item.price_unit_currency = (item.precio_unitario / tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                item.total_currency = (item.total / tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                item.price_unit_currency = Decimal('0')
                item.total_currency = Decimal('0')

        # Actualizar totales del presupuesto
        presupuesto.calcular_totales()
        db.session.commit()

        # Devolver totales actualizados
        return jsonify({
            'exito': True,
            'nuevo_total': _f(item.total),
            'price_unit_ars': _f(item.price_unit_ars) if item.price_unit_ars else None,
            'total_ars': _f(item.total_ars) if item.total_ars else None,
            'price_unit_usd': _f(item.price_unit_currency) if item.price_unit_currency else None,
            'total_usd': _f(item.total_currency) if item.total_currency else None,
            'currency': item.currency,
            'modalidad_costo': item.modalidad_costo,
            'subtotal_materiales': _f(presupuesto.subtotal_materiales),
            'subtotal_mano_obra': _f(presupuesto.subtotal_mano_obra),
            'subtotal_equipos': _f(presupuesto.subtotal_equipos),
            'total_sin_iva': _f(presupuesto.total_sin_iva),
            'iva_monto': _f(_d(presupuesto.total_con_iva) - _d(presupuesto.total_sin_iva)),
            'total_con_iva': _f(presupuesto.total_con_iva)
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.editar_item: {e}")
        db.session.rollback()
        return jsonify({'exito': False, 'error': 'Error al editar el item'}), 500


@presupuestos_bp.route('/items/<int:id>/eliminar', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def eliminar_item(id):
    """Eliminar item de presupuesto"""
    if not current_user.puede_gestionar():
        return jsonify({'ok': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'ok': False, 'error': 'Sin organización activa'}), 400

        item = ItemPresupuesto.query.get(id)
        if not item:
            abort(404)
        presupuesto = item.presupuesto

        if presupuesto.organizacion_id != org_id:
            abort(404)

        if presupuesto.estado != 'borrador':
            flash('Solo se pueden eliminar items de presupuestos en borrador', 'warning')
            return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

        db.session.delete(item)

        # Actualizar totales del presupuesto después de eliminar
        presupuesto.calcular_totales()
        db.session.commit()

        flash('Item eliminado exitosamente', 'success')
        return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.eliminar_item: {e}")
        db.session.rollback()
        flash('Error al eliminar el item', 'danger')
        return redirect(url_for('index'))
