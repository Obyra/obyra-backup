"""
Core CRUD routes: lista, crear, crear_manual, importar_excel
"""
import os
import json
from datetime import date
from decimal import Decimal

from flask import (render_template, request, flash, redirect,
                   url_for, current_app)
from flask_login import login_required, current_user
from sqlalchemy import desc, or_

from extensions import db
from models import Presupuesto, ItemPresupuesto, Obra, Cliente
from services.calculation import BudgetCalculator, BudgetConstants
from services.memberships import get_current_org_id
from services.plan_service import require_active_subscription

from blueprint_presupuestos import presupuestos_bp, buscar_item_inventario_por_nombre


@presupuestos_bp.route('/')
@login_required
def lista():
    """Lista de presupuestos"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        # Filtros
        estado = request.args.get('estado', '')
        vigencia = request.args.get('vigencia', '')
        obra_id = request.args.get('obra_id', type=int)

        # Query base - excluir presupuestos eliminados y presupuestos confirmados como obras
        from datetime import datetime
        query = Presupuesto.query.filter_by(organizacion_id=org_id).filter(
            Presupuesto.deleted_at.is_(None),
            Presupuesto.estado != 'eliminado',
            or_(
                Presupuesto.confirmado_como_obra.is_(False),
                Presupuesto.confirmado_como_obra.is_(None)
            )
        )

        # Aplicar filtros
        if estado:
            query = query.filter_by(estado=estado)

        # Filtro de vigencia basado en fecha_vigencia
        if vigencia == 'vigentes':
            query = query.filter(
                Presupuesto.estado.in_(['borrador', 'enviado', 'aprobado']),
                or_(
                    Presupuesto.fecha_vigencia.is_(None),
                    Presupuesto.fecha_vigencia >= datetime.utcnow()
                )
            )
        elif vigencia == 'vencidos':
            query = query.filter(
                Presupuesto.fecha_vigencia < datetime.utcnow()
            )

        if obra_id:
            query = query.filter_by(obra_id=obra_id)

        # Ordenar por fecha de creación descendente
        query = query.order_by(desc(Presupuesto.fecha))

        # Paginación
        page = request.args.get('page', 1, type=int)
        per_page = 20

        presupuestos = query.paginate(page=page, per_page=per_page, error_out=False)

        # Recalcular totales de todos los presupuestos en la página actual
        for presupuesto in presupuestos.items:
            presupuesto.calcular_totales()
        db.session.commit()

        # Obras disponibles para filtro
        obras = Obra.query.filter_by(organizacion_id=org_id).filter(Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

        return render_template('presupuestos/lista.html',
                             presupuestos=presupuestos.items,
                             pagination=presupuestos,
                             estado=estado,
                             vigencia=vigencia,
                             obra_id=obra_id,
                             obras=obras)
    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.lista: {e}")
        flash('Error al cargar la lista de presupuestos', 'danger')
        return redirect(url_for('index'))


@presupuestos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@require_active_subscription
def crear():
    """Crear nuevo presupuesto"""
    # Log database info for debugging
    db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')
    current_app.logger.info(f"🔍 [CREAR PRESUPUESTO] DB URL: {db_url[:50]}... | Method: {request.method} | User: {current_user.id}")

    # Verificar permisos de gestión usando método centralizado
    if not current_user.puede_gestionar():
        flash('No tienes permisos para crear presupuestos', 'danger')
        return redirect(url_for('presupuestos.lista'))

    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        if request.method == 'POST':
            # Obtener datos del formulario
            numero = request.form.get('numero', '').strip()
            obra_id = request.form.get('obra_id', type=int)
            cliente_id = request.form.get('cliente_id', type=int)  # ID del cliente seleccionado
            cliente_nombre = request.form.get('cliente_nombre', '').strip()  # Nombre (para retrocompatibilidad)
            vigencia_dias = request.form.get('vigencia_dias', 30, type=int)

            # Validaciones
            if not numero:
                flash('El número de presupuesto es requerido', 'danger')
                return redirect(url_for('presupuestos.crear'))

            # Verificar que el número no esté duplicado
            existing = Presupuesto.query.filter_by(
                organizacion_id=org_id,
                numero=numero
            ).first()

            if existing:
                flash(f'Ya existe un presupuesto con el número {numero}', 'danger')
                return redirect(url_for('presupuestos.crear'))

            # Si se seleccionó un cliente, obtener su nombre de la base de datos
            if cliente_id:
                cliente = Cliente.query.filter_by(id=cliente_id, organizacion_id=org_id).first()
                if cliente:
                    cliente_nombre = cliente.nombre_completo

            # Preparar datos del proyecto como JSON
            datos_proyecto = {
                'nombre_obra': request.form.get('nombre_obra', '').strip(),
                'tipo_obra': request.form.get('tipo_obra', '').strip(),
                'ubicacion': request.form.get('ubicacion', '').strip(),
                'tipo_construccion': request.form.get('tipo_construccion', '').strip(),
                'superficie_m2': request.form.get('superficie_m2', '').strip(),
                'cliente_nombre': cliente_nombre,
            }

            # Procesar datos de IA antes de crear el presupuesto
            ia_payload_str = request.form.get('ia_etapas_payload', '').strip()
            current_app.logger.info(f"🔍 DEBUG: ia_etapas_payload recibido: {ia_payload_str[:200] if ia_payload_str else 'VACIO'}")
            moneda_presupuesto = 'ARS'  # Default

            if ia_payload_str:
                try:
                    ia_payload = json.loads(ia_payload_str)
                    # Obtener la moneda del payload de IA
                    moneda_presupuesto = ia_payload.get('moneda', 'ARS')
                except Exception as e:
                    current_app.logger.error(f"Error parseando payload IA para obtener moneda: {str(e)}")

            # Obtener tasa de cambio actual del BNA
            tasa_usd = None
            tasa_fecha = None
            tasa_provider = 'BNA'
            try:
                from services.exchange.providers.bna import fetch_official_rate
                rate_snapshot = fetch_official_rate()
                if rate_snapshot and rate_snapshot.value:
                    tasa_usd = Decimal(str(rate_snapshot.value))  # Mantener como Decimal para consistencia
                    tasa_fecha = rate_snapshot.as_of_date
            except Exception as e:
                current_app.logger.warning(f"No se pudo obtener cotización BNA al crear presupuesto: {e}")

            # Obtener índice CAC actual
            indice_cac = None
            cac_fecha = None
            try:
                from services.cac.cac_service import get_index_for_month
                from datetime import date as dt_date
                today = dt_date.today()
                cac_index = get_index_for_month(today.year, today.month)
                if not cac_index:
                    # Intentar mes anterior
                    prev_month = today.month - 1 if today.month > 1 else 12
                    prev_year = today.year if today.month > 1 else today.year - 1
                    cac_index = get_index_for_month(prev_year, prev_month)
                if cac_index:
                    indice_cac = float(cac_index.value)
                    cac_fecha = dt_date(cac_index.period_year, cac_index.period_month, 1)
            except Exception as e:
                current_app.logger.warning(f"No se pudo obtener índice CAC al crear presupuesto: {e}")

            # Crear presupuesto con la moneda correcta y datos de cotización
            presupuesto = Presupuesto(
                organizacion_id=org_id,
                numero=numero,
                obra_id=obra_id if obra_id else None,
                cliente_id=cliente_id if cliente_id else None,  # Asignar el cliente seleccionado
                fecha=date.today(),
                vigencia_dias=vigencia_dias,
                datos_proyecto=json.dumps(datos_proyecto),
                ubicacion_texto=request.form.get('ubicacion', '').strip(),
                estado='borrador',
                currency=moneda_presupuesto,
                iva_porcentaje=BudgetConstants.DEFAULT_IVA_RATE,
                vigencia_bloqueada=True,
                tasa_usd_venta=tasa_usd,
                exchange_rate_as_of=tasa_fecha,
                exchange_rate_provider=tasa_provider,
                indice_cac_valor=indice_cac,
                indice_cac_fecha=cac_fecha
            )

            db.session.add(presupuesto)
            db.session.flush()  # Get presupuesto.id before commit

            # Guardar niveles del edificio si existen
            niveles_json_str = request.form.get('niveles_json', '').strip()
            if niveles_json_str:
                try:
                    from models import NivelPresupuesto
                    niveles_data = json.loads(niveles_json_str)
                    for ndata in niveles_data:
                        nivel = NivelPresupuesto(
                            presupuesto_id=presupuesto.id,
                            tipo_nivel=ndata.get('tipo_nivel', 'piso_tipo'),
                            nombre=ndata.get('nombre', ''),
                            orden=int(ndata.get('orden', 0)),
                            repeticiones=int(ndata.get('repeticiones', 1)),
                            area_m2=Decimal(str(ndata.get('area_m2', 0))),
                            hormigon_m3=Decimal(str(ndata.get('hormigon_m3', 0))),
                            albanileria_m2=Decimal(str(ndata.get('albanileria_m2', 0))),
                            atributos=ndata.get('atributos', {}),
                        )
                        db.session.add(nivel)
                    current_app.logger.info(f"Guardados {len(niveles_data)} niveles para presupuesto {numero}")
                except Exception as e:
                    current_app.logger.error(f"Error guardando niveles: {e}")

            # Procesar items calculados por IA si existen
            if ia_payload_str:
                try:
                    ia_payload = json.loads(ia_payload_str)
                    etapas_ia = ia_payload.get('etapas', [])
                    moneda_ia = ia_payload.get('moneda', 'ARS')

                    # Guardar el payload de IA en datos_proyecto para usarlo al confirmar como obra
                    datos_proyecto_dict = json.loads(datos_proyecto) if isinstance(datos_proyecto, str) else datos_proyecto
                    datos_proyecto_dict['ia_payload'] = ia_payload
                    presupuesto.datos_proyecto = json.dumps(datos_proyecto_dict)

                    # Crear items SIN etapa_id pero CON etapa_nombre
                    # Unificar items duplicados (misma descripcion+etapa+tipo) antes de guardar
                    items_vinculados = 0
                    items_agrupados = {}  # key: (etapa, tipo, descripcion) -> item_data

                    for etapa in etapas_ia:
                        nombre_etapa = etapa.get('nombre', 'Sin Etapa')
                        items_etapa = etapa.get('items', [])
                        for item in items_etapa:
                            tipo_item = item.get('tipo', 'material')
                            desc = (item.get('descripcion', '') or '').strip()
                            key = (nombre_etapa, tipo_item, desc)

                            precio_unit = Decimal(str(item.get('precio_unit', 0)))
                            subtotal = Decimal(str(item.get('subtotal', 0)))
                            precio_unit_ars = Decimal(str(item.get('precio_unit_ars', item.get('precio_unit', 0))))
                            total_ars = Decimal(str(item.get('subtotal_ars', item.get('subtotal', 0))))
                            cantidad = Decimal(str(item.get('cantidad', 0)))

                            if key in items_agrupados:
                                # Sumar al item existente
                                existing = items_agrupados[key]
                                existing['cantidad'] += cantidad
                                existing['subtotal'] += subtotal
                                existing['total_ars'] += total_ars
                            else:
                                items_agrupados[key] = {
                                    'nombre_etapa': nombre_etapa,
                                    'tipo': tipo_item,
                                    'descripcion': desc,
                                    'unidad': item.get('unidad', 'unidades'),
                                    'cantidad': cantidad,
                                    'precio_unit': precio_unit,
                                    'subtotal': subtotal,
                                    'precio_unit_ars': precio_unit_ars,
                                    'total_ars': total_ars,
                                    'nivel_nombre': item.get('nivel_nombre'),
                                }

                    # Guardar items unificados
                    for key, item in items_agrupados.items():
                        cant = item['cantidad']
                        subtotal = item['subtotal']
                        total_ars = item['total_ars']

                        # Recalcular precio unitario si se unificaron items
                        if cant > 0:
                            precio_unit = subtotal / cant
                            precio_unit_ars = total_ars / cant
                        else:
                            precio_unit = item['precio_unit']
                            precio_unit_ars = item['precio_unit_ars']

                        if moneda_ia == 'USD':
                            price_unit_usd = precio_unit
                            total_usd = subtotal
                        elif tasa_usd and tasa_usd > Decimal('0'):
                            price_unit_usd = precio_unit / tasa_usd
                            total_usd = subtotal / tasa_usd
                        else:
                            price_unit_usd = None
                            total_usd = None

                        # Buscar vinculacion con inventario
                        item_inventario_id = None
                        if item['tipo'] == 'material':
                            item_inv = buscar_item_inventario_por_nombre(
                                item['descripcion'], org_id
                            )
                            if item_inv:
                                item_inventario_id = item_inv.id
                                items_vinculados += 1

                        # Modalidad de costo: la IA siempre cotiza alquiler para
                        # equipos (precios diarios derivados de precio_alquiler_usd/28).
                        # Para otros tipos el campo se deja en NULL.
                        modalidad = 'alquiler' if item['tipo'] == 'equipo' else None

                        item_presupuesto = ItemPresupuesto(
                            presupuesto_id=presupuesto.id,
                            tipo=item['tipo'],
                            descripcion=item['descripcion'],
                            unidad=item['unidad'],
                            cantidad=cant,
                            precio_unitario=precio_unit,
                            total=subtotal,
                            origen='ia',
                            currency=moneda_ia,
                            price_unit_currency=price_unit_usd,
                            total_currency=total_usd,
                            price_unit_ars=precio_unit_ars,
                            total_ars=total_ars,
                            etapa_id=None,
                            etapa_nombre=item['nombre_etapa'],
                            nivel_nombre=item['nivel_nombre'],
                            item_inventario_id=item_inventario_id,
                            modalidad_costo=modalidad
                        )
                        db.session.add(item_presupuesto)

                    total_items_original = sum(len(e.get('items', [])) for e in etapas_ia)
                    total_items_guardados = len(items_agrupados)
                    current_app.logger.info(
                        f"Guardados {total_items_guardados} items de IA (de {total_items_original} originales, "
                        f"unificados) en {moneda_ia} para presupuesto {numero} "
                        f"({items_vinculados} vinculados a inventario)"
                    )

                    # CRÍTICO: Calcular totales después de agregar items
                    db.session.flush()  # Asegurar que los items estén en la sesión
                    presupuesto.calcular_totales()
                    current_app.logger.info(f"💰 Totales calculados: Sin IVA={presupuesto.total_sin_iva}, Con IVA={presupuesto.total_con_iva}")
                except Exception as e:
                    current_app.logger.error(f"Error procesando items de IA: {str(e)}")
                    import traceback
                    current_app.logger.error(traceback.format_exc())
                    # No fallar la creación del presupuesto por este error

            db.session.commit()

            flash(f'Presupuesto {numero} creado exitosamente', 'success')
            return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

        # GET - Mostrar formulario
        obras = Obra.query.filter_by(organizacion_id=org_id).filter(Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

        # Generar número de presupuesto sugerido ÚNICO
        fecha_hoy = date.today().strftime('%Y%m%d')

        # Buscar TODOS los presupuestos del día (incluyendo eliminados) para evitar colisiones
        presupuestos_hoy = Presupuesto.query.filter_by(organizacion_id=org_id).filter(
            Presupuesto.numero.like(f'PRES-{fecha_hoy}-%')
        ).all()

        # Extraer todos los números correlativos usados
        numeros_usados = set()
        for p in presupuestos_hoy:
            try:
                partes = p.numero.split('-')
                if len(partes) == 3:
                    numeros_usados.add(int(partes[2]))
            except (IndexError, ValueError, AttributeError):
                pass

        # Encontrar el primer número disponible
        num = 1
        while num in numeros_usados:
            num += 1

        numero_sugerido = f"PRES-{fecha_hoy}-{num:03d}"

        # Obtener lista de clientes activos de la organización
        clientes = Cliente.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).order_by(Cliente.nombre, Cliente.apellido).all()

        return render_template('presupuestos/crear.html',
                             obras=obras,
                             numero_sugerido=numero_sugerido,
                             clientes=clientes,
                             google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        current_app.logger.error(f"Error en presupuestos.crear: {e}\n{error_details}")
        # Mostrar error más descriptivo al usuario
        current_app.logger.error(f'Error al crear presupuesto: {e}')
        flash('Error al crear el presupuesto. Intente nuevamente.', 'danger')
        return redirect(url_for('presupuestos.lista'))


@presupuestos_bp.route('/crear-manual', methods=['GET', 'POST'])
@login_required
@require_active_subscription
def crear_manual():
    """Crear nuevo presupuesto de forma manual (sin IA)"""
    # Verificar permisos de gestión
    if not current_user.puede_gestionar():
        flash('No tienes permisos para crear presupuestos', 'danger')
        return redirect(url_for('presupuestos.lista'))

    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        if request.method == 'POST':
            import json

            # Obtener datos del formulario
            numero = request.form.get('numero', '').strip()
            cliente_id = request.form.get('cliente_id', type=int)
            vigencia_dias = request.form.get('vigencia_dias', 30, type=int)
            moneda = request.form.get('moneda', 'ARS')

            # Datos del proyecto
            nombre_obra = request.form.get('nombre_obra', '').strip()
            ubicacion = request.form.get('ubicacion', '').strip()
            descripcion = request.form.get('descripcion', '').strip()

            # Validaciones
            if not numero:
                flash('El número de presupuesto es requerido', 'danger')
                return redirect(url_for('presupuestos.crear_manual'))

            # Verificar que el número no esté duplicado
            existing = Presupuesto.query.filter_by(
                organizacion_id=org_id,
                numero=numero
            ).first()

            if existing:
                flash(f'Ya existe un presupuesto con el número {numero}', 'danger')
                return redirect(url_for('presupuestos.crear_manual'))

            # Obtener nombre del cliente si se seleccionó
            cliente_nombre = ''
            if cliente_id:
                cliente = Cliente.query.filter_by(id=cliente_id, organizacion_id=org_id).first()
                if cliente:
                    cliente_nombre = cliente.nombre_completo

            # Preparar datos del proyecto como JSON
            datos_proyecto = {
                'nombre_obra': nombre_obra,
                'ubicacion': ubicacion,
                'descripcion': descripcion,
                'cliente_nombre': cliente_nombre,
                'modo_creacion': 'manual'
            }

            # Obtener tasa de cambio actual del BNA
            tasa_usd = None
            tasa_fecha = None
            tasa_provider = 'BNA'
            try:
                from services.exchange.providers.bna import fetch_official_rate
                rate_snapshot = fetch_official_rate()
                if rate_snapshot and rate_snapshot.value:
                    tasa_usd = float(rate_snapshot.value)
                    tasa_fecha = rate_snapshot.as_of_date
            except Exception as e:
                current_app.logger.warning(f"No se pudo obtener cotización BNA: {e}")

            # Obtener índice CAC actual
            indice_cac = None
            cac_fecha = None
            try:
                from services.cac.cac_service import get_index_for_month
                from datetime import date as dt_date
                today = dt_date.today()
                cac_index = get_index_for_month(today.year, today.month)
                if not cac_index:
                    prev_month = today.month - 1 if today.month > 1 else 12
                    prev_year = today.year if today.month > 1 else today.year - 1
                    cac_index = get_index_for_month(prev_year, prev_month)
                if cac_index:
                    indice_cac = float(cac_index.value)
                    cac_fecha = dt_date(cac_index.period_year, cac_index.period_month, 1)
            except Exception as e:
                current_app.logger.warning(f"No se pudo obtener índice CAC: {e}")

            # Crear presupuesto
            presupuesto = Presupuesto(
                organizacion_id=org_id,
                numero=numero,
                cliente_id=cliente_id if cliente_id else None,
                fecha=date.today(),
                vigencia_dias=vigencia_dias,
                datos_proyecto=json.dumps(datos_proyecto),
                ubicacion_texto=ubicacion,
                estado='borrador',
                currency=moneda,
                iva_porcentaje=BudgetConstants.DEFAULT_IVA_RATE,
                vigencia_bloqueada=True,
                tasa_usd_venta=tasa_usd,
                exchange_rate_as_of=tasa_fecha,
                exchange_rate_provider=tasa_provider,
                indice_cac_valor=indice_cac,
                indice_cac_fecha=cac_fecha
            )

            db.session.add(presupuesto)
            db.session.flush()

            # Procesar items manuales
            items_json = request.form.get('items_json', '[]')
            try:
                items_data = json.loads(items_json)
                for item_data in items_data:
                    precio_unit = Decimal(str(item_data.get('precio_unitario', 0)))
                    cantidad = Decimal(str(item_data.get('cantidad', 0)))
                    subtotal = precio_unit * cantidad

                    # Calcular precio en ARS si la moneda es USD
                    precio_unit_ars = precio_unit
                    total_ars = subtotal
                    if moneda == 'USD' and tasa_usd:
                        precio_unit_ars = precio_unit * Decimal(str(tasa_usd))
                        total_ars = subtotal * Decimal(str(tasa_usd))

                    # Obtener item_inventario_id si viene del inventario
                    item_inventario_id = item_data.get('item_inventario_id')
                    if item_inventario_id:
                        item_inventario_id = int(item_inventario_id)

                    # Modalidad de costo: si es equipo, acepta la que venga del
                    # payload, default 'compra'. Para otros tipos queda NULL.
                    tipo_item = item_data.get('tipo', 'material')
                    if tipo_item == 'equipo':
                        modalidad_item = item_data.get('modalidad_costo', 'compra')
                        if modalidad_item not in ('compra', 'alquiler'):
                            modalidad_item = 'compra'
                    else:
                        modalidad_item = None

                    item_presupuesto = ItemPresupuesto(
                        presupuesto_id=presupuesto.id,
                        tipo=tipo_item,
                        descripcion=item_data.get('descripcion', ''),
                        unidad=item_data.get('unidad', 'unidad'),
                        cantidad=cantidad,
                        precio_unitario=precio_unit,
                        total=subtotal,
                        origen='manual',
                        currency=moneda,
                        price_unit_ars=precio_unit_ars,
                        total_ars=total_ars,
                        item_inventario_id=item_inventario_id,
                        modalidad_costo=modalidad_item
                    )
                    db.session.add(item_presupuesto)

                current_app.logger.info(f"✅ Creado presupuesto manual {numero} con {len(items_data)} items")
            except Exception as e:
                current_app.logger.error(f"Error procesando items manuales: {str(e)}")

            db.session.commit()

            flash(f'Presupuesto {numero} creado exitosamente', 'success')
            return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

        # GET - Mostrar formulario
        # Generar número de presupuesto sugerido
        fecha_hoy = date.today().strftime('%Y%m%d')
        ultimo_hoy = Presupuesto.query.filter_by(organizacion_id=org_id).filter(
            Presupuesto.numero.like(f'PRES-{fecha_hoy}-%')
        ).order_by(desc(Presupuesto.id)).first()

        if ultimo_hoy and ultimo_hoy.numero:
            try:
                partes = ultimo_hoy.numero.split('-')
                if len(partes) == 3:
                    num = int(partes[2]) + 1
                    numero_sugerido = f"PRES-{fecha_hoy}-{num:03d}"
                else:
                    numero_sugerido = f"PRES-{fecha_hoy}-001"
            except (IndexError, ValueError, AttributeError):
                numero_sugerido = f"PRES-{fecha_hoy}-001"
        else:
            numero_sugerido = f"PRES-{fecha_hoy}-001"

        # Obtener lista de clientes
        clientes = Cliente.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).order_by(Cliente.nombre, Cliente.apellido).all()

        # Obtener items del inventario para el selector
        from models.inventory import ItemInventario
        items_inventario = ItemInventario.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).order_by(ItemInventario.nombre).all()

        return render_template('presupuestos/crear_manual.html',
                             numero_sugerido=numero_sugerido,
                             clientes=clientes,
                             items_inventario=items_inventario,
                             google_maps_key=os.environ.get('GOOGLE_MAPS_API_KEY', ''))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.crear_manual: {e}")
        flash('Error al crear el presupuesto', 'danger')
        return redirect(url_for('presupuestos.lista'))


# ==========================================
# IMPORTAR DESDE EXCEL (deshabilitado - ahora se carga desde inventario)
# ==========================================


@presupuestos_bp.route('/importar-excel', methods=['GET'])
@login_required
def importar_excel():
    """Funcionalidad eliminada — redirige a presupuestos."""
    flash('Esta función ya no está disponible.', 'info')
    return redirect(url_for('presupuestos.lista'))
