"""
Blueprint de Presupuestos - Gestión de presupuestos y cotizaciones
"""
import os


def _d(val, default=0):
    """Convierte valor a Decimal de forma segura (para cálculos financieros)."""
    if val is None:
        return Decimal(str(default))
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError):
        return Decimal(str(default))


def _f(val):
    """Convierte Decimal a float para serialización JSON."""
    if val is None:
        return 0
    return float(val)
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort, send_file)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from extensions import db, csrf, limiter
from sqlalchemy import desc, or_
from models import Presupuesto, ItemPresupuesto, Obra, Organizacion, Cliente
from services.calculation import BudgetCalculator, BudgetConstants
from services.memberships import get_current_org_id, get_current_membership
from utils.pagination import Pagination
from utils import safe_int
import io
import re
from weasyprint import HTML
from flask_mail import Message

presupuestos_bp = Blueprint('presupuestos', __name__)


def _limpiar_metadata_pdf(pdf_buffer, presupuesto, organizacion):
    """Reescribe metadatos del PDF para evitar falsos positivos de antivirus.

    Avast y otros antivirus detectan PDFs generados por WeasyPrint como
    'PDF:MalwareX-gen [Phish]' por los metadatos Producer/Creator.
    Esta función los reemplaza con datos legítimos de la empresa.
    """
    try:
        from PyPDF2 import PdfReader, PdfWriter
        reader = PdfReader(pdf_buffer)
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        # Reemplazar metadatos sospechosos con datos de la empresa
        nombre_org = organizacion.nombre if organizacion else 'OBYRA'
        writer.add_metadata({
            '/Title': f'Presupuesto {presupuesto.numero}',
            '/Author': nombre_org,
            '/Creator': nombre_org,
            '/Producer': f'{nombre_org} - Sistema de Gestion',
            '/Subject': f'Presupuesto comercial N° {presupuesto.numero}',
        })

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        return output
    except Exception:
        # Si falla el post-procesado, devolver el PDF original
        pdf_buffer.seek(0)
        return pdf_buffer


def buscar_item_inventario_por_nombre(descripcion, org_id):
    """
    Busca un item de inventario que coincida con la descripción del material.
    Optimizado: primero busca en BD, solo hace fuzzy en memoria si es necesario.

    Args:
        descripcion: Descripción del material del presupuesto
        org_id: ID de la organización

    Returns:
        ItemInventario o None si no encuentra coincidencia
    """
    from models.inventory import ItemInventario
    from sqlalchemy import func

    if not descripcion:
        return None

    descripcion = descripcion.strip()
    if not descripcion:
        return None

    # 1. Búsqueda exacta (case insensitive) - muy rápida con índice
    item = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo == True,
        func.lower(ItemInventario.nombre) == descripcion.lower()
    ).first()
    if item:
        return item

    # 2. Búsqueda parcial: descripción contenida en nombre o viceversa
    item = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo == True,
        func.lower(ItemInventario.nombre).contains(descripcion.lower())
    ).first()
    if item:
        return item

    # 3. Búsqueda por palabras clave (primeras 2-3 palabras significativas)
    palabras = [p for p in descripcion.lower().split() if len(p) > 2][:3]
    if palabras:
        for palabra in palabras:
            item = ItemInventario.query.filter(
                ItemInventario.organizacion_id == org_id,
                ItemInventario.activo == True,
                func.lower(ItemInventario.nombre).contains(palabra)
            ).first()
            if item:
                return item

    # 4. Fuzzy search limitado (solo si las búsquedas anteriores fallaron)
    # Limitar a 100 items para evitar cargar toda la BD en memoria
    items = ItemInventario.query.filter_by(
        organizacion_id=org_id,
        activo=True
    ).limit(100).all()

    def normalizar(texto):
        if not texto:
            return ''
        texto = texto.lower().strip()
        reemplazos = {'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ñ': 'n', 'ü': 'u'}
        for acento, sin_acento in reemplazos.items():
            texto = texto.replace(acento, sin_acento)
        texto = re.sub(r'[^a-z0-9\s]', '', texto)
        return re.sub(r'\s+', ' ', texto)

    desc_normalizada = normalizar(descripcion)
    mejor_match = None
    mejor_score = 0

    for item in items:
        nombre_normalizado = normalizar(item.nombre)
        if not nombre_normalizado:
            continue

        # Coincidencia exacta normalizada
        if desc_normalizada == nombre_normalizado:
            return item

        # Calcular score por palabras en común
        palabras_desc = set(desc_normalizada.split())
        palabras_item = set(nombre_normalizado.split())
        coincidencias = palabras_desc & palabras_item

        if len(coincidencias) >= 2:
            score = len(coincidencias) * 10
            if score > mejor_score:
                mejor_score = score
                mejor_match = item

    return mejor_match if mejor_score >= 5 else None


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
        query = Presupuesto.query.filter_by(organizacion_id=org_id).filter(
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
        obras = Obra.query.filter_by(organizacion_id=org_id).order_by(Obra.nombre).all()

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
            import json
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
                            item_inventario_id=item_inventario_id
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
        obras = Obra.query.filter_by(organizacion_id=org_id).order_by(Obra.nombre).all()

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
        flash(f'Error al crear el presupuesto: {str(e)}', 'danger')
        return redirect(url_for('presupuestos.lista'))


@presupuestos_bp.route('/crear-manual', methods=['GET', 'POST'])
@login_required
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

                    item_presupuesto = ItemPresupuesto(
                        presupuesto_id=presupuesto.id,
                        tipo=item_data.get('tipo', 'material'),
                        descripcion=item_data.get('descripcion', ''),
                        unidad=item_data.get('unidad', 'unidad'),
                        cantidad=cantidad,
                        precio_unitario=precio_unit,
                        total=subtotal,
                        origen='manual',
                        currency=moneda,
                        price_unit_ars=precio_unit_ars,
                        total_ars=total_ars,
                        item_inventario_id=item_inventario_id
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

        # Obtener items agrupados por tipo y origen
        items = ItemPresupuesto.query.filter_by(presupuesto_id=id).order_by(
            ItemPresupuesto.tipo,
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
        from collections import defaultdict, OrderedDict
        from types import SimpleNamespace
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
        import json
        datos_proyecto = {}
        if presupuesto.datos_proyecto:
            try:
                datos_proyecto = json.loads(presupuesto.datos_proyecto)
            except (json.JSONDecodeError, TypeError) as e:
                current_app.logger.error(f"Error al parsear datos_proyecto para presupuesto {presupuesto.id}: {e}")
                datos_proyecto = {}

        # Obtener items de inventario para el selector de vinculación
        from models import ItemInventario
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


@presupuestos_bp.route('/<int:id>/pdf')
@login_required
def generar_pdf(id):
    """Generar PDF del presupuesto con WeasyPrint - 2 páginas (USD y ARS)"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        # Obtener presupuesto con eager loading para evitar queries dentro del template
        from sqlalchemy.orm import joinedload
        presupuesto = Presupuesto.query.options(
            joinedload(Presupuesto.cliente)
        ).filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Obtener organización
        organizacion = Organizacion.query.get(org_id)

        # Obtener items ordenados usando sintaxis SQLAlchemy 2.0
        from models.budgets import ItemPresupuesto
        from extensions import db
        items_ordenados = db.session.query(ItemPresupuesto).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id
        ).order_by(ItemPresupuesto.tipo, ItemPresupuesto.id).all()

        # Obtener cotización del dólar (Banco Nación vendedor)
        cotizacion_dolar = 1050.0  # Valor por defecto
        fecha_cotizacion = presupuesto.fecha.strftime('%d/%m/%Y')

        # Intentar obtener cotización guardada en el presupuesto
        if presupuesto.tasa_usd_venta:
            cotizacion_dolar = float(presupuesto.tasa_usd_venta)
            if presupuesto.exchange_rate_as_of:
                fecha_cotizacion = presupuesto.exchange_rate_as_of.strftime('%d/%m/%Y')
        else:
            # Intentar obtener cotización actual del BNA
            try:
                from services.exchange.providers.bna import fetch_official_rate
                rate_snapshot = fetch_official_rate()
                if rate_snapshot and rate_snapshot.value:
                    cotizacion_dolar = float(rate_snapshot.value)
                    fecha_cotizacion = rate_snapshot.as_of_date.strftime('%d/%m/%Y') if rate_snapshot.as_of_date else datetime.now().strftime('%d/%m/%Y')
            except Exception as e:
                current_app.logger.warning(f"No se pudo obtener cotización BNA: {e}")

        # Determinar moneda principal y alternativa
        moneda_principal = presupuesto.currency or 'ARS'
        moneda_alternativa = 'USD' if moneda_principal == 'ARS' else 'ARS'

        # Calcular factor de conversión
        # Si moneda principal es ARS, convertir a USD (dividir por cotización)
        # Si moneda principal es USD, convertir a ARS (multiplicar por cotización)
        if moneda_principal == 'ARS':
            factor_conversion = 1 / cotizacion_dolar if cotizacion_dolar > 0 else 0
        else:
            factor_conversion = cotizacion_dolar

        # Parsear datos_proyecto para obtener información adicional
        import json
        datos_proyecto = {}
        nombre_proyecto = None
        tipo_construccion = None
        superficie_m2 = None

        if presupuesto.datos_proyecto:
            try:
                datos_proyecto = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                nombre_proyecto = datos_proyecto.get('nombre_obra') or datos_proyecto.get('nombre')
                tipo_construccion = datos_proyecto.get('tipo_construccion')
                superficie_m2 = datos_proyecto.get('superficie_m2')
            except (json.JSONDecodeError, TypeError) as e:
                current_app.logger.warning(f"Error parseando datos_proyecto en PDF: {e}")

        # Agrupar items por etapa para vista simplificada del cliente
        from collections import OrderedDict
        from decimal import Decimal

        etapas_orden_pdf = [
            'Trabajos preliminares', 'Excavación', 'Fundaciones', 'Estructura',
            'Mampostería', 'Techos y cubiertas', 'Instalación eléctrica',
            'Instalación sanitaria', 'Instalación de gas', 'Pisos y revestimientos',
            'Carpintería', 'Pintura', 'Equipamiento', 'Terminaciones', 'Otros'
        ]

        etapas_totales = OrderedDict()
        for item in items_ordenados:
            nombre_etapa = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Otros')
            if nombre_etapa not in etapas_totales:
                etapas_totales[nombre_etapa] = Decimal('0')
            etapas_totales[nombre_etapa] += item.total or Decimal('0')

        # Ordenar: primero las etapas conocidas, luego el resto
        etapas_ordenadas = OrderedDict()
        for etapa in etapas_orden_pdf:
            if etapa in etapas_totales:
                etapas_ordenadas[etapa] = etapas_totales[etapa]
        for etapa, total in etapas_totales.items():
            if etapa not in etapas_ordenadas:
                etapas_ordenadas[etapa] = total

        # Cargar logo como base64 para embeber en el PDF
        logo_base64 = None
        if organizacion.logo_url:
            try:
                import base64
                logo_path = os.path.join(current_app.static_folder, organizacion.logo_url)
                if os.path.exists(logo_path):
                    with open(logo_path, 'rb') as f:
                        logo_base64 = base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                current_app.logger.warning(f"No se pudo cargar logo para PDF: {e}")

        try:
            # Renderizar HTML
            html_string = render_template(
                'presupuestos/pdf_template.html',
                presupuesto=presupuesto,
                organizacion=organizacion,
                usuario=current_user,
                now=datetime.now(),
                items=items_ordenados,
                etapas_totales=etapas_ordenadas,
                moneda_principal=moneda_principal,
                moneda_alternativa=moneda_alternativa,
                cotizacion_dolar=cotizacion_dolar,
                fecha_cotizacion=fecha_cotizacion,
                factor_conversion=factor_conversion,
                nombre_proyecto=nombre_proyecto,
                tipo_construccion=tipo_construccion,
                superficie_m2=superficie_m2,
                logo_base64=logo_base64
            )
        except Exception as render_error:
            current_app.logger.error(f"Error al renderizar template PDF: {render_error}", exc_info=True)
            raise Exception(f"Error al renderizar template: {str(render_error)}")

        try:
            # Generar PDF con WeasyPrint
            pdf_raw = io.BytesIO()
            HTML(string=html_string).write_pdf(
                pdf_raw,
                presentational_hints=True
            )
            pdf_raw.seek(0)

            # Post-procesar: limpiar metadatos para evitar falsos positivos de antivirus
            pdf_buffer = _limpiar_metadata_pdf(pdf_raw, presupuesto, organizacion)
        except Exception as pdf_error:
            current_app.logger.error(f"Error al generar PDF con WeasyPrint: {pdf_error}", exc_info=True)
            raise Exception(f"Error al generar PDF: {str(pdf_error)}")

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'presupuesto_{presupuesto.numero}.pdf'
        )

    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback_str = traceback.format_exc()
        current_app.logger.error(f"Error en presupuestos.generar_pdf: {error_msg}\n{traceback_str}")
        flash(f'Error al generar el PDF: {error_msg}', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/<int:id>/enviar-email', methods=['GET', 'POST'])
@login_required
def enviar_email(id):
    """Enviar presupuesto por email"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            # Si es JSON, retornar error JSON
            if request.is_json:
                return jsonify({'error': 'No tienes una organización activa'}), 403
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        organizacion = Organizacion.query.get(org_id)

        if request.method == 'GET':
            # Mostrar formulario de envío
            email_destino = presupuesto.cliente.email if presupuesto.cliente else ''
            user_name = f"{current_user.nombre} {current_user.apellido}" if current_user.is_authenticated else "nuestro equipo"
            mensaje_default = f"""Estimado/a,

Adjunto encontrará el presupuesto Nº {presupuesto.numero} solicitado.

Este presupuesto tiene una vigencia hasta el {presupuesto.fecha_vigencia.strftime('%d/%m/%Y') if presupuesto.fecha_vigencia else 'consultar'}.

Para cualquier consulta, puede responder directamente este email y su mensaje llegará a {user_name}.

Saludos cordiales,
{organizacion.nombre}"""

            return render_template(
                'presupuestos/enviar_email.html',
                presupuesto=presupuesto,
                email_destino=email_destino,
                mensaje_default=mensaje_default
            )

        # POST: Enviar email (puede ser form o JSON)
        if request.is_json:
            data = request.get_json()
            email_destino = data.get('email', '').strip()
            asunto = data.get('asunto', f'Presupuesto {presupuesto.numero}').strip()
            mensaje = data.get('mensaje', '').strip()
        else:
            email_destino = request.form.get('email', '').strip()
            asunto = request.form.get('asunto', f'Presupuesto {presupuesto.numero}').strip()
            mensaje = request.form.get('mensaje', '').strip()

        if not email_destino:
            if request.is_json:
                return jsonify({'error': 'Debe ingresar un email de destino'}), 400
            flash('Debe ingresar un email de destino', 'danger')
            return redirect(url_for('presupuestos.enviar_email', id=id))

        # Verificar que el presupuesto tenga ítems
        if presupuesto.items.count() == 0:
            if request.is_json:
                return jsonify({'error': 'No se puede enviar un presupuesto sin ítems'}), 400
            flash('No se puede enviar un presupuesto sin ítems. Por favor agregue ítems al presupuesto primero.', 'warning')
            return redirect(url_for('presupuestos.detalle', id=id))

        # Obtener items ordenados (igual que en generar_pdf)
        from models.budgets import ItemPresupuesto
        items_ordenados = db.session.query(ItemPresupuesto).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id
        ).order_by(ItemPresupuesto.tipo, ItemPresupuesto.id).all()

        # Obtener cotización del dólar para el PDF dual moneda
        cotizacion_dolar = 1050.0  # Valor por defecto
        fecha_cotizacion = presupuesto.fecha.strftime('%d/%m/%Y')

        if presupuesto.tasa_usd_venta:
            cotizacion_dolar = float(presupuesto.tasa_usd_venta)
            if presupuesto.exchange_rate_as_of:
                fecha_cotizacion = presupuesto.exchange_rate_as_of.strftime('%d/%m/%Y')
        else:
            try:
                from services.exchange.providers.bna import fetch_official_rate
                rate_snapshot = fetch_official_rate()
                if rate_snapshot and rate_snapshot.value:
                    cotizacion_dolar = float(rate_snapshot.value)
                    fecha_cotizacion = rate_snapshot.as_of_date.strftime('%d/%m/%Y') if rate_snapshot.as_of_date else datetime.now().strftime('%d/%m/%Y')
            except Exception as e:
                current_app.logger.warning(f"No se pudo obtener cotización BNA: {e}")

        moneda_principal = presupuesto.currency or 'ARS'
        moneda_alternativa = 'USD' if moneda_principal == 'ARS' else 'ARS'

        if moneda_principal == 'ARS':
            factor_conversion = 1 / cotizacion_dolar if cotizacion_dolar > 0 else 0
        else:
            factor_conversion = cotizacion_dolar

        # Agrupar items por etapa para vista simplificada del cliente
        from collections import OrderedDict
        from decimal import Decimal as Dec

        etapas_orden_email = [
            'Trabajos preliminares', 'Excavación', 'Fundaciones', 'Estructura',
            'Mampostería', 'Techos y cubiertas', 'Instalación eléctrica',
            'Instalación sanitaria', 'Instalación de gas', 'Pisos y revestimientos',
            'Carpintería', 'Pintura', 'Equipamiento', 'Terminaciones', 'Otros'
        ]
        etapas_totales_email = OrderedDict()
        for item in items_ordenados:
            nombre_etapa = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Otros')
            if nombre_etapa not in etapas_totales_email:
                etapas_totales_email[nombre_etapa] = Dec('0')
            etapas_totales_email[nombre_etapa] += item.total or Dec('0')

        etapas_ordenadas_email = OrderedDict()
        for etapa in etapas_orden_email:
            if etapa in etapas_totales_email:
                etapas_ordenadas_email[etapa] = etapas_totales_email[etapa]
        for etapa, total in etapas_totales_email.items():
            if etapa not in etapas_ordenadas_email:
                etapas_ordenadas_email[etapa] = total

        # Parsear datos_proyecto para la template
        import json as json_mod
        nombre_proyecto = None
        tipo_construccion = None
        superficie_m2 = None
        if presupuesto.datos_proyecto:
            try:
                datos_proy = json_mod.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                nombre_proyecto = datos_proy.get('nombre_obra') or datos_proy.get('nombre')
                tipo_construccion = datos_proy.get('tipo_construccion')
                superficie_m2 = datos_proy.get('superficie_m2')
            except (json_mod.JSONDecodeError, TypeError):
                pass

        # Cargar logo como base64 para embeber en el PDF
        logo_base64 = None
        if organizacion.logo_url:
            try:
                import base64
                logo_path = os.path.join(current_app.static_folder, organizacion.logo_url)
                if os.path.exists(logo_path):
                    with open(logo_path, 'rb') as f:
                        logo_base64 = base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                current_app.logger.warning(f"No se pudo cargar logo para PDF email: {e}")

        # Generar PDF
        html_string = render_template(
            'presupuestos/pdf_template.html',
            presupuesto=presupuesto,
            organizacion=organizacion,
            usuario=current_user,
            now=datetime.now(),
            items=items_ordenados,
            etapas_totales=etapas_ordenadas_email,
            moneda_principal=moneda_principal,
            moneda_alternativa=moneda_alternativa,
            cotizacion_dolar=cotizacion_dolar,
            fecha_cotizacion=fecha_cotizacion,
            factor_conversion=factor_conversion,
            nombre_proyecto=nombre_proyecto,
            tipo_construccion=tipo_construccion,
            superficie_m2=superficie_m2,
            logo_base64=logo_base64
        )

        # Generar PDF y limpiar metadatos para evitar falsos positivos de antivirus
        pdf_raw = io.BytesIO()
        HTML(string=html_string).write_pdf(
            pdf_raw,
            presentational_hints=True
        )
        pdf_raw.seek(0)
        pdf_clean = _limpiar_metadata_pdf(pdf_raw, presupuesto, organizacion)
        pdf_bytes = pdf_clean.read()

        # Preparar datos del remitente
        user_email = current_user.email if current_user.is_authenticated else None
        user_name = f"{current_user.nombre} {current_user.apellido}" if current_user.is_authenticated else "OBYRA"

        # Intentar primero con Resend (más confiable)
        email_enviado = False
        resend_api_key = current_app.config.get('RESEND_API_KEY')

        if resend_api_key:
            try:
                from services.email_service import send_email as resend_send_email

                current_app.logger.info(f"Intentando enviar email via Resend a {email_destino}")

                # Convertir mensaje de texto a HTML simple
                mensaje_html = f"<pre style='font-family: Arial, sans-serif; white-space: pre-wrap;'>{mensaje}</pre>"

                # Preparar adjunto
                adjuntos = [{
                    'filename': f'presupuesto_{presupuesto.numero}.pdf',
                    'content': pdf_bytes,
                    'content_type': 'application/pdf'
                }]

                # Enviar con Resend
                email_enviado = resend_send_email(
                    to_email=email_destino,
                    subject=asunto,
                    html_content=mensaje_html,
                    attachments=adjuntos,
                    reply_to=user_email,
                    text_content=mensaje
                )

                if email_enviado:
                    current_app.logger.info("Email enviado exitosamente via Resend!")
                else:
                    current_app.logger.warning("Resend falló, intentando con Flask-Mail...")

            except Exception as resend_error:
                current_app.logger.warning(f"Error con Resend: {resend_error}, intentando Flask-Mail...")

        # Si Resend no funcionó, intentar con Flask-Mail
        if not email_enviado:
            try:
                from extensions import mail

                sender_email = f"{user_name} - OBYRA <{current_app.config.get('MAIL_DEFAULT_SENDER')}>"

                current_app.logger.info(f"Intentando enviar email via Flask-Mail desde {sender_email} hacia {email_destino}")

                msg = Message(
                    asunto,
                    recipients=[email_destino],
                    body=mensaje,
                    sender=sender_email
                )

                if user_email:
                    msg.reply_to = f"{user_name} <{user_email}>"
                msg.attach(
                    f'presupuesto_{presupuesto.numero}.pdf',
                    'application/pdf',
                    pdf_bytes
                )

                mail.send(msg)
                email_enviado = True
                current_app.logger.info("Email enviado exitosamente via Flask-Mail!")

            except ImportError:
                current_app.logger.warning("Flask-Mail no está configurado")
            except Exception as mail_error:
                error_msg = str(mail_error)
                current_app.logger.error(f"Error al enviar email via Flask-Mail: {mail_error}", exc_info=True)

                # Mostrar error específico
                if 'SMTPAuthenticationError' in type(mail_error).__name__ or 'Authentication' in error_msg or '535' in error_msg:
                    flash('Error de autenticación del servidor de correo. Por favor contacte al administrador.', 'danger')
                elif 'SMTP' in type(mail_error).__name__ or 'smtp' in error_msg.lower():
                    flash(f'Error del servidor de correo: {error_msg[:100]}', 'danger')
                else:
                    flash(f'Error al enviar el email: {error_msg[:100]}', 'danger')
                return redirect(url_for('presupuestos.enviar_email', id=id))

        # Si ninguno funcionó
        if not email_enviado:
            if request.is_json:
                return jsonify({'error': 'No se pudo enviar el email. Verifique la configuración del servidor de correo.'}), 500
            flash('No se pudo enviar el email. Verifique la configuración del servidor de correo.', 'danger')
            return redirect(url_for('presupuestos.enviar_email', id=id))

        # Actualizar estado si está en borrador
        if presupuesto.estado == 'borrador':
            presupuesto.estado = 'enviado'
            db.session.commit()

        if request.is_json:
            return jsonify({
                'success': True,
                'message': f'Presupuesto enviado exitosamente a {email_destino}'
            }), 200

        flash(f'Presupuesto enviado exitosamente a {email_destino}', 'success')
        return redirect(url_for('presupuestos.detalle', id=id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.enviar_email: {e}", exc_info=True)
        if request.is_json:
            return jsonify({'error': 'Error al procesar el envío del email'}), 500
        flash('Error al procesar el envío del email', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


def identificar_etapa_por_tipo(item):
    """
    Identifica la etapa correspondiente basándose en el tipo y descripción del ítem.
    Utilizado para items sin etapa_id asignada.
    """
    # Mapeo de palabras clave a etapas
    ETAPA_KEYWORDS = {
        'Excavación': ['excavacion', 'movimiento', 'suelo', 'terreno', 'nivelacion'],
        'Fundaciones': ['fundacion', 'cimiento', 'zapata', 'viga de fundacion', 'hormigon armado'],
        'Estructura': ['estructura', 'columna', 'viga', 'losa', 'hormigon', 'acero', 'hierro'],
        'Mampostería': ['muro', 'pared', 'tabique', 'ladrillo', 'bloque'],
        'Techos': ['techo', 'cubierta', 'teja', 'chapa', 'impermeabilizacion'],
        'Instalaciones Eléctricas': ['electric', 'cable', 'tablero', 'luminaria', 'tomacorriente'],
        'Instalaciones Sanitarias': ['sanitari', 'agua', 'desague', 'cañeria', 'inodoro', 'lavabo'],
        'Instalaciones de Gas': ['gas', 'gasoducto', 'artefacto a gas'],
        'Revoque Grueso': ['revoque grueso', 'azotado', 'jaharro'],
        'Revoque Fino': ['revoque fino', 'enlucido', 'terminacion'],
        'Pisos': ['piso', 'ceramica', 'porcelanato', 'carpeta', 'contrapiso'],
        'Carpintería': ['puerta', 'ventana', 'marco', 'madera', 'carpinteria'],
        'Pintura': ['pintura', 'latex', 'esmalte', 'barniz'],
        'Instalaciones Complementarias': ['aire acondicionado', 'calefaccion', 'ventilacion'],
        'Limpieza Final': ['limpieza', 'acondicionamiento final'],
    }

    descripcion_lower = item.descripcion.lower() if item.descripcion else ''

    # Buscar coincidencias por palabras clave
    for etapa_nombre, keywords in ETAPA_KEYWORDS.items():
        for keyword in keywords:
            if keyword in descripcion_lower:
                return etapa_nombre

    # Identificación por tipo de ítem
    if item.tipo == 'material':
        if 'cemento' in descripcion_lower or 'hormigon' in descripcion_lower:
            return 'Fundaciones'
        return 'Materiales Generales'
    elif item.tipo == 'mano_obra':
        return 'Mano de Obra General'
    elif item.tipo == 'maquinaria':
        return 'Maquinaria y Equipos'
    else:
        return 'Otros'


@presupuestos_bp.route('/<int:id>/confirmar-obra', methods=['POST'])
@login_required
def confirmar_como_obra(id):
    """Confirmar presupuesto y convertirlo en obra"""
    try:
        org_id = get_current_org_id()
        presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

        # Solo administradores pueden confirmar presupuestos
        if not current_user.es_admin():
            return jsonify({'error': '⛔ Solo administradores pueden confirmar presupuestos como obras. Contactá a tu administrador.'}), 403

        # Verificar que el presupuesto no esté ya confirmado
        if presupuesto.confirmado_como_obra:
            return jsonify({'error': '❌ Este presupuesto ya fue confirmado como obra. No se puede confirmar dos veces.'}), 400

        # Verificar que tenga ítems
        if presupuesto.items.count() == 0:
            return jsonify({'error': '❌ No se puede confirmar un presupuesto sin ítems. Agregá al menos un ítem o usá la calculadora IA primero.'}), 400

        # Verificar límite de obras del plan
        from obras import verificar_limite_obras
        puede_crear, mensaje_obras = verificar_limite_obras(org_id)
        if not puede_crear:
            return jsonify({'error': f'❌ {mensaje_obras}'}), 400

        # Obtener datos del formulario
        data = request.get_json() or {}
        crear_tareas = data.get('crear_tareas', True)
        normalizar_slugs = data.get('normalizar_slugs', True)

        # Crear la obra desde el presupuesto
        obra = Obra()

        # Datos básicos de la obra
        # Extraer el nombre del JSON datos_proyecto si existe
        nombre_obra = f"Obra {presupuesto.numero}"
        if presupuesto.datos_proyecto:
            try:
                import json
                proyecto_data = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                nombre_obra = proyecto_data.get('nombre_obra') or proyecto_data.get('nombre') or nombre_obra
            except (json.JSONDecodeError, TypeError):
                pass

        obra.nombre = nombre_obra[:200]  # Limitar a 200 caracteres
        obra.organizacion_id = presupuesto.organizacion_id

        # Cliente
        if presupuesto.cliente:
            obra.cliente_id = presupuesto.cliente_id
            obra.cliente = presupuesto.cliente.nombre_completo
            obra.telefono_cliente = presupuesto.cliente.telefono
            obra.email_cliente = presupuesto.cliente.email
        else:
            obra.cliente = "Sin cliente asignado"

        # Ubicación
        obra.direccion = presupuesto.ubicacion_texto
        obra.direccion_normalizada = presupuesto.ubicacion_normalizada
        obra.latitud = presupuesto.geo_latitud
        obra.longitud = presupuesto.geo_longitud
        obra.geocode_place_id = presupuesto.geocode_place_id
        obra.geocode_provider = presupuesto.geocode_provider
        obra.geocode_status = presupuesto.geocode_status
        obra.geocode_raw = presupuesto.geocode_raw
        obra.geocode_actualizado = presupuesto.geocode_actualizado

        # Presupuesto y fechas
        obra.presupuesto_total = presupuesto.total_con_iva
        obra.fecha_inicio = date.today()
        obra.fecha_fin_estimada = presupuesto.fecha_vigencia
        obra.estado = 'planificacion'
        obra.progreso = 0

        db.session.add(obra)
        db.session.flush()  # Para obtener el ID de la obra

        # Marcar el presupuesto como confirmado
        presupuesto.confirmado_como_obra = True
        presupuesto.obra_id = obra.id
        presupuesto.estado = 'aprobado'

        # SIEMPRE crear/asociar etapas del presupuesto a la obra automáticamente
        from models.budgets import ItemPresupuesto
        from models.projects import EtapaObra, TareaEtapa

        # Obtener todos los ítems del presupuesto
        items = db.session.query(ItemPresupuesto).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id
        ).order_by(ItemPresupuesto.etapa_id, ItemPresupuesto.tipo).all()

        # Verificar si hay payload de IA guardado en datos_proyecto
        ia_payload = None
        if presupuesto.datos_proyecto:
            try:
                proyecto_data = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                ia_payload = proyecto_data.get('ia_payload')
                if ia_payload:
                    current_app.logger.info(f"📌 Payload de IA encontrado para presupuesto {presupuesto.numero}, creando etapas desde IA")
            except (json.JSONDecodeError, TypeError) as e:
                current_app.logger.error(f"Error parseando datos_proyecto: {str(e)}")

        # Agrupar ítems por etapa
        etapas_dict = {}
        etapas_obj_map = {}  # Para mapear nombre -> objeto EtapaObra

        if ia_payload and ia_payload.get('etapas'):
            # Usar el payload de IA para crear etapas
            etapas_ia = ia_payload.get('etapas', [])
            items_list = list(items)  # Convertir a lista para iterar
            item_index = 0

            for orden, etapa_ia in enumerate(etapas_ia, start=1):
                etapa_nombre = etapa_ia.get('nombre', f'Etapa {orden}')
                num_items_etapa = len(etapa_ia.get('items', []))

                # Crear EtapaObra
                etapa_obj = EtapaObra(
                    obra_id=obra.id,
                    nombre=etapa_nombre,
                    orden=orden,
                    estado='pendiente',
                    progreso=0
                )
                db.session.add(etapa_obj)
                db.session.flush()  # Para obtener el ID

                etapas_obj_map[etapa_nombre] = etapa_obj
                etapas_dict[etapa_nombre] = []

                current_app.logger.info(f"📌 Creada etapa '{etapa_nombre}' (ID: {etapa_obj.id}) para obra {obra.id}")

                # Asignar items a esta etapa
                for _ in range(num_items_etapa):
                    if item_index < len(items_list):
                        item = items_list[item_index]
                        item.etapa_id = etapa_obj.id
                        etapas_dict[etapa_nombre].append(item)
                        item_index += 1
                        current_app.logger.info(f"📌 Item '{item.descripcion}' asignado a etapa '{etapa_nombre}' (ID: {etapa_obj.id})")

        else:
            # Fallback: agrupar por identificación automática
            for item in items:
                if item.etapa_id and item.etapa:
                    etapa_nombre = item.etapa.nombre
                    etapa_obj = item.etapa
                else:
                    etapa_nombre = identificar_etapa_por_tipo(item)
                    etapa_obj = None

                if etapa_nombre not in etapas_dict:
                    etapas_dict[etapa_nombre] = []
                    if etapa_obj:
                        etapas_obj_map[etapa_nombre] = etapa_obj

                etapas_dict[etapa_nombre].append(item)

        # Crear/asociar todas las etapas a la obra
        orden_etapa = 1
        etapas_creadas = {}  # Mapeo nombre -> id de etapa en la obra

        for etapa_nombre, items_etapa in etapas_dict.items():
            # Buscar si ya existe una etapa con ese nombre en la obra
            etapa = EtapaObra.query.filter_by(obra_id=obra.id, nombre=etapa_nombre).first()

            if not etapa:
                # Verificar si hay una etapa existente (del presupuesto) que podemos asociar
                if etapa_nombre in etapas_obj_map:
                    etapa_existente = etapas_obj_map[etapa_nombre]
                    etapa_existente.obra_id = obra.id
                    etapa = etapa_existente
                    current_app.logger.info(f"Asociando etapa existente '{etapa_nombre}' (ID: {etapa.id}) a obra {obra.id}")
                else:
                    # Crear nueva etapa
                    etapa = EtapaObra(
                        obra_id=obra.id,
                        nombre=etapa_nombre,
                        orden=orden_etapa,
                        estado='pendiente',
                        progreso=0
                    )
                    db.session.add(etapa)
                    db.session.flush()  # Para obtener etapa.id
                    current_app.logger.info(f"Creada nueva etapa '{etapa_nombre}' (ID: {etapa.id}) para obra {obra.id}")

            etapas_creadas[etapa_nombre] = etapa.id

            # Actualizar etapa_id en los items si no lo tenían
            for item in items_etapa:
                if not item.etapa_id:
                    item.etapa_id = etapa.id

            # Calcular mediciones totales para esta etapa
            cantidad_total_etapa = 0
            unidad_etapa = 'm2'  # Default

            for item in items_etapa:
                if item and item.cantidad:
                    cantidad_total_etapa += float(item.cantidad)
                    if item.unidad:
                        unidad_etapa = item.unidad  # Tomar la unidad del último item

            # Asignar mediciones a la etapa
            etapa.unidad_medida = unidad_etapa
            etapa.cantidad_total_planificada = cantidad_total_etapa
            etapa.cantidad_total_ejecutada = 0
            etapa.porcentaje_avance_medicion = 0

            current_app.logger.info(f"📏 Etapa '{etapa_nombre}': {cantidad_total_etapa} {unidad_etapa} planificados")

            orden_etapa += 1

        db.session.flush()

        # Opcionalmente crear tareas desde los ítems del presupuesto
        if crear_tareas:
            for etapa_nombre, items_etapa in etapas_dict.items():
                etapa_id = etapas_creadas[etapa_nombre]

                # Crear tareas para cada ítem de la etapa
                for item in items_etapa:
                    tarea = TareaEtapa(
                        etapa_id=etapa_id,
                        nombre=item.descripcion,
                        estado='pendiente',
                        cantidad_planificada=float(item.cantidad) if item.cantidad else 0,
                        unidad=item.unidad or 'un',
                        item_presupuesto_id=item.id  # Vincular tarea con item del presupuesto
                    )
                    db.session.add(tarea)

            current_app.logger.info(f"Creadas tareas para {len(etapas_dict)} etapas en obra {obra.id}")

        db.session.commit()

        # Asignar niveles de encadenamiento por defecto a las etapas
        try:
            from services.dependency_service import asignar_niveles_por_defecto
            asignadas = asignar_niveles_por_defecto(obra.id)
            if asignadas:
                db.session.commit()
                current_app.logger.info(f"Asignados niveles de encadenamiento a {asignadas} etapas de obra {obra.id}")
        except Exception as e_dep:
            current_app.logger.warning(f"No se pudieron asignar niveles de dependencias: {e_dep}")

        current_app.logger.info(f"Presupuesto {presupuesto.numero} confirmado como obra {obra.id}")

        return jsonify({
            'success': True,
            'message': f'Presupuesto confirmado exitosamente. Obra creada: {obra.nombre}',
            'obra_id': obra.id,
            'obra_url': url_for('obras.detalle', id=obra.id),
            'redirect_url': url_for('obras.detalle', id=obra.id)
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en presupuestos.confirmar_como_obra: {e}", exc_info=True)
        return jsonify({'error': 'Error al confirmar el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/editar-obra', methods=['POST'])
@csrf.exempt
@login_required
def editar_obra(id):
    """Editar información de la obra/proyecto del presupuesto"""
    try:
        org_id = get_current_org_id()
        presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

        # Admin, PM y técnicos pueden editar
        # Usar método centralizado de permisos
        if not current_user.puede_editar():
            return jsonify({'error': '⛔ Solo administradores, PM y técnicos pueden editar presupuestos. Contactá a tu administrador.'}), 403

        # No se puede editar si ya está confirmado como obra
        if presupuesto.confirmado_como_obra:
            return jsonify({'error': '❌ No se puede editar un presupuesto ya confirmado como obra. Si necesitás hacer cambios, contactá al administrador para revertir la confirmación.'}), 400

        data = request.get_json() or {}

        # Obtener datos del proyecto actual
        import json
        if presupuesto.datos_proyecto:
            try:
                proyecto_data = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
            except (json.JSONDecodeError, TypeError):
                proyecto_data = {}
        else:
            proyecto_data = {}

        # Actualizar campos del proyecto
        if 'nombre' in data:
            proyecto_data['nombre_obra'] = data['nombre'].strip()

        if 'cliente' in data:
            proyecto_data['cliente_nombre'] = data['cliente'].strip()

        if 'descripcion' in data:
            proyecto_data['descripcion'] = data['descripcion'].strip()

        if 'direccion' in data:
            proyecto_data['ubicacion'] = data['direccion'].strip()

        if 'tipo_obra' in data:
            proyecto_data['tipo_obra'] = data['tipo_obra'].strip()

        if 'superficie_m2' in data:
            superficie = data['superficie_m2']
            if superficie:
                try:
                    proyecto_data['superficie_m2'] = float(superficie)
                except (ValueError, TypeError):
                    proyecto_data['superficie_m2'] = superficie
            else:
                proyecto_data['superficie_m2'] = None

        # Actualizar cliente_id en el presupuesto si se proporciona
        if 'cliente_id' in data:
            cliente_id = data['cliente_id']
            if cliente_id:
                presupuesto.cliente_id = int(cliente_id)
            else:
                presupuesto.cliente_id = None

        # Guardar el JSON actualizado
        presupuesto.datos_proyecto = json.dumps(proyecto_data, ensure_ascii=False)

        db.session.commit()

        current_app.logger.info(f"Información del presupuesto {presupuesto.numero} actualizada")

        return jsonify({
            'exito': True,
            'mensaje': 'Información actualizada correctamente'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en presupuestos.editar_obra: {e}", exc_info=True)
        return jsonify({'error': 'Error al actualizar la información'}), 500


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
            item_inventario_id=item_inventario_id if item_inventario_id else None
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
@csrf.exempt
def editar_item(id):
    """Editar item de presupuesto"""
    # Usar método centralizado de permisos
    if not current_user.puede_editar():
        return jsonify({'exito': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'exito': False, 'error': 'Sin organización activa'}), 400

        item = ItemPresupuesto.query.get_or_404(id)
        presupuesto = item.presupuesto

        if presupuesto.organizacion_id != org_id:
            return jsonify({'exito': False, 'error': 'No autorizado'}), 403

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

        item = ItemPresupuesto.query.get_or_404(id)
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


@presupuestos_bp.route('/<int:id>/eliminar', methods=['POST'])
@csrf.exempt  # Exentar CSRF para este endpoint que usa AJAX
@login_required
@limiter.limit("10 per minute")
def eliminar(id):
    """Eliminar (archivar) presupuesto"""
    try:
        # Log para debugging
        current_app.logger.info(f'Usuario {current_user.id} intentando eliminar presupuesto {id}')
        current_app.logger.info(f'Usuario rol: {getattr(current_user, "rol", None)}, role: {getattr(current_user, "role", None)}')

        # Verificar permisos usando ambos sistemas de roles
        es_admin = (getattr(current_user, 'rol', None) == 'administrador' or
                    getattr(current_user, 'role', None) == 'admin' or
                    getattr(current_user, 'is_super_admin', False))

        if not es_admin:
            current_app.logger.warning(f'Usuario {current_user.id} sin permisos de admin')
            return jsonify({'error': '⛔ Solo administradores pueden eliminar presupuestos. Contactá a tu administrador.'}), 403

        org_id = get_current_org_id()
        current_app.logger.info(f'Org ID obtenido: {org_id}')

        if not org_id:
            # Intentar obtener de usuario directamente
            org_id = getattr(current_user, 'organizacion_id', None)
            current_app.logger.info(f'Org ID de usuario: {org_id}')

        if not org_id:
            current_app.logger.warning('No se pudo obtener organización activa')
            return jsonify({'error': 'Sin organización activa'}), 400

        # Query atómica: filtrar por ID + org_id en una sola consulta (previene IDOR)
        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first()
        if not presupuesto:
            current_app.logger.warning(f'Presupuesto {id} no encontrado o sin autorización')
            return jsonify({'error': 'Presupuesto no encontrado'}), 404

        # Verificar si el presupuesto está confirmado como obra
        if presupuesto.confirmado_como_obra:
            current_app.logger.warning(f'Intento de eliminar presupuesto {id} confirmado como obra')
            return jsonify({'error': '❌ No se puede eliminar un presupuesto que ya fue confirmado como obra. Primero debés revertir la confirmación.'}), 400

        # Administradores pueden eliminar presupuestos en cualquier estado
        # (excepto confirmados como obra)
        current_app.logger.info(f'Admin eliminando presupuesto {id} en estado {presupuesto.estado}')

        # Marcar como eliminado en lugar de borrar
        presupuesto.estado = 'eliminado'
        db.session.commit()

        current_app.logger.info(f'Presupuesto {presupuesto.numero} eliminado correctamente')
        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} eliminado correctamente'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.eliminar: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': f'Error al eliminar el presupuesto: {str(e)}'}), 500


@presupuestos_bp.route('/<int:id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado(id):
    """Cambiar estado del presupuesto"""
    if not current_user.puede_gestionar():
        flash('No tienes permisos para cambiar el estado', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))

    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        nuevo_estado = request.form.get('estado', '').strip()
        estados_validos = ['borrador', 'enviado', 'aprobado', 'confirmado', 'rechazado', 'perdido', 'vencido']

        if nuevo_estado not in estados_validos:
            flash('Estado inválido', 'danger')
            return redirect(url_for('presupuestos.detalle', id=id))

        presupuesto.estado = nuevo_estado
        db.session.commit()

        flash(f'Estado cambiado a {nuevo_estado}', 'success')
        return redirect(url_for('presupuestos.detalle', id=id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.cambiar_estado: {e}")
        db.session.rollback()
        flash('Error al cambiar el estado', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/<int:id>/revertir-borrador', methods=['POST'])
@csrf.exempt
@login_required
def revertir_borrador(id):
    """Revertir presupuesto a estado borrador (solo administradores)"""
    try:
        # Solo administradores
        if not current_user.es_admin():
            return jsonify({'error': 'Solo administradores pueden revertir presupuestos'}), 403

        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Verificar que el presupuesto esté en un estado que permita revertir
        if presupuesto.estado not in ['enviado', 'aprobado', 'rechazado', 'perdido']:
            return jsonify({'error': f'No se puede revertir un presupuesto en estado {presupuesto.estado}'}), 400

        # Revertir a borrador
        estado_anterior = presupuesto.estado
        presupuesto.estado = 'borrador'

        # Si estaba marcado como perdido, limpiar esos datos
        if estado_anterior == 'perdido':
            presupuesto.perdido_motivo = None
            presupuesto.perdido_fecha = None

        db.session.commit()

        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} revertido a borrador exitosamente',
            'estado_anterior': estado_anterior,
            'estado_nuevo': 'borrador'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.revertir_borrador: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': 'Error al revertir el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/restaurar', methods=['POST'])
@login_required
def restaurar(id):
    """Restaurar presupuesto perdido a borrador"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Solo se pueden restaurar presupuestos perdidos
        if presupuesto.estado != 'perdido':
            return jsonify({'error': 'Solo se pueden restaurar presupuestos marcados como perdidos'}), 400

        presupuesto.estado = 'borrador'
        presupuesto.perdido_motivo = None
        presupuesto.perdido_fecha = None
        db.session.commit()

        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} restaurado a borrador'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.restaurar: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': 'Error al restaurar el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/asignar-cliente', methods=['POST'])
@csrf.exempt
@login_required
def asignar_cliente(id):
    """Asignar un cliente existente al presupuesto"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'exito': False, 'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        data = request.get_json()
        cliente_id = data.get('cliente_id')

        if not cliente_id:
            return jsonify({'exito': False, 'error': 'Debe seleccionar un cliente'}), 400

        # Convertir a entero
        try:
            cliente_id = int(cliente_id)
        except (ValueError, TypeError):
            return jsonify({'exito': False, 'error': 'ID de cliente inválido'}), 400

        # Verificar que el cliente existe y pertenece a la organización
        cliente = Cliente.query.filter_by(
            id=cliente_id,
            organizacion_id=org_id
        ).first()

        if not cliente:
            return jsonify({'exito': False, 'error': 'Cliente no encontrado'}), 404

        # Asignar cliente
        presupuesto.cliente_id = cliente.id
        db.session.commit()

        return jsonify({
            'exito': True,
            'mensaje': f'Cliente {cliente.nombre_completo} asignado correctamente',
            'cliente_id': cliente.id,
            'cliente_nombre': cliente.nombre_completo
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.asignar_cliente: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'exito': False, 'error': 'Error al asignar cliente'}), 500


@presupuestos_bp.route('/<int:id>/crear-asignar-cliente', methods=['POST'])
@csrf.exempt
@login_required
def crear_asignar_cliente(id):
    """Crear un cliente nuevo y asignarlo al presupuesto"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'exito': False, 'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        data = request.get_json()
        nombre = data.get('nombre', '').strip()
        apellido = data.get('apellido', '').strip() or ''
        email = data.get('email', '').strip()
        telefono = data.get('telefono', '').strip()
        tipo_documento = data.get('tipo_documento', 'CUIT').strip()
        numero_documento = data.get('numero_documento', '').strip()

        # Validaciones
        if not nombre:
            return jsonify({'exito': False, 'error': 'El nombre es requerido'}), 400
        if not email:
            return jsonify({'exito': False, 'error': 'El email es requerido'}), 400
        if not numero_documento:
            return jsonify({'exito': False, 'error': 'El número de documento es requerido'}), 400

        # Verificar si ya existe un cliente con ese documento
        existing = Cliente.query.filter_by(
            organizacion_id=org_id,
            numero_documento=numero_documento
        ).first()

        if existing:
            return jsonify({
                'exito': False,
                'error': f'Ya existe un cliente con el documento {numero_documento}'
            }), 400

        # Crear cliente
        cliente = Cliente(
            organizacion_id=org_id,
            nombre=nombre,
            apellido=apellido,
            tipo_documento=tipo_documento,
            numero_documento=numero_documento,
            email=email,
            telefono=telefono or None,
            empresa=nombre if not apellido else None  # Si no hay apellido, usar nombre como empresa
        )

        db.session.add(cliente)
        db.session.flush()  # Para obtener el ID

        # Asignar al presupuesto
        presupuesto.cliente_id = cliente.id
        db.session.commit()

        return jsonify({
            'exito': True,
            'mensaje': f'Cliente {cliente.nombre_completo} creado y asignado correctamente',
            'cliente_id': cliente.id,
            'cliente_nombre': cliente.nombre_completo
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.crear_asignar_cliente: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'exito': False, 'error': f'Error al crear cliente: {str(e)}'}), 500


@presupuestos_bp.route('/<int:id>/revertir-confirmacion', methods=['POST'])
@login_required
def revertir_confirmacion_obra(id):
    """Revertir confirmación de obra - SOLO ADMINISTRADORES

    Esta función permite a los administradores deshacer la confirmación de un
    presupuesto como obra. ATENCIÓN: Esto puede causar inconsistencias si la
    obra ya tiene avances registrados.
    """
    try:
        # Solo administradores pueden revertir confirmaciones
        if not current_user.es_admin():
            return jsonify({
                'error': '⛔ Solo administradores pueden revertir confirmaciones de obra. Esta operación requiere privilegios especiales.'
            }), 403

        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': '❌ Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Verificar que el presupuesto esté confirmado como obra
        if not presupuesto.confirmado_como_obra:
            return jsonify({
                'error': '❌ Este presupuesto no está confirmado como obra. No hay nada que revertir.'
            }), 400

        # Obtener la obra asociada
        from models import Obra, TareaEtapa, TareaAvance, Etapa
        obra = None
        if presupuesto.obra_id:
            obra = Obra.query.get(presupuesto.obra_id)

        # Verificar si hay avances registrados en la obra (esto es una operación delicada)
        tiene_avances = False
        mensaje_advertencia = ""

        if obra:
            # Contar avances en todas las tareas de la obra
            avances_count = db.session.query(TareaAvance).join(TareaEtapa).filter(
                TareaEtapa.etapa_id.in_(
                    db.session.query(Etapa.id).filter(Etapa.obra_id == obra.id)
                )
            ).count()

            tiene_avances = avances_count > 0

            if tiene_avances:
                mensaje_advertencia = f"⚠️ ADVERTENCIA: La obra tiene {avances_count} avance(s) registrado(s). "

        # Revertir la confirmación
        presupuesto.confirmado_como_obra = False
        presupuesto.obra_id = None
        presupuesto.estado = 'borrador'  # Volver a borrador para permitir edición

        # NO eliminamos la obra porque puede tener datos importantes
        # El administrador debe manejar eso manualmente si es necesario

        db.session.commit()

        current_app.logger.info(
            f"Admin {current_user.id} revirtió confirmación de obra para presupuesto {presupuesto.numero}"
        )

        return jsonify({
            'exito': True,
            'mensaje': f'{mensaje_advertencia}Confirmación revertida exitosamente. El presupuesto {presupuesto.numero} volvió a estado borrador.',
            'presupuesto_numero': presupuesto.numero,
            'tenia_avances': tiene_avances,
            'obra_id': obra.id if obra else None
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.revertir_confirmacion_obra: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'error': f'❌ Error al revertir la confirmación: {str(e)}'
        }), 500


@presupuestos_bp.route('/guardar', methods=['POST'])
@login_required
def guardar_presupuesto():
    """Guardar presupuesto desde calculadora IA"""
    if not current_user.puede_gestionar():
        return jsonify({'ok': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'ok': False, 'error': 'Sin organización activa'}), 400

        data = request.get_json() or request.form.to_dict()

        # Crear presupuesto
        numero = data.get('numero', f"PRES-{date.today().strftime('%Y%m%d')}")

        presupuesto = Presupuesto(
            organizacion_id=org_id,
            numero=numero,
            obra_id=data.get('obra_id'),
            cliente_nombre=data.get('cliente_nombre', ''),
            fecha=date.today(),
            vigencia_dias=30,
            estado='borrador',
            currency='ARS',
            iva_porcentaje=BudgetConstants.DEFAULT_IVA_RATE
        )

        db.session.add(presupuesto)
        db.session.flush()

        # Agregar items si vienen en el payload
        items_data = data.get('items', [])
        for item_data in items_data:
            item = ItemPresupuesto(
                presupuesto_id=presupuesto.id,
                descripcion=item_data.get('descripcion', ''),
                tipo=item_data.get('tipo', 'material'),
                cantidad=Decimal(str(item_data.get('cantidad', 0))),
                unidad=item_data.get('unidad', 'un'),
                precio_unitario=Decimal(str(item_data.get('precio_unitario', 0))),
                subtotal=Decimal(str(item_data.get('subtotal', 0))),
                orden=item_data.get('orden', 0)
            )
            db.session.add(item)

        db.session.commit()

        return jsonify({
            'ok': True,
            'presupuesto_id': presupuesto.id,
            'message': 'Presupuesto guardado exitosamente'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.guardar_presupuesto: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/ia/calcular/etapas', methods=['POST'])
@csrf.exempt
@login_required
def calcular_etapas_ia():
    """
    Endpoint para cálculo de etapas seleccionadas con reglas determinísticas.
    Soporta redondeo de compras y precios duales USD/ARS.
    """
    try:
        from calculadora_ia import calcular_etapas_seleccionadas
        from services.exchange.base import ensure_rate
        from services.exchange.providers.bna import fetch_official_rate
        from services.budget_rounding_service import process_budget_with_rounding_and_dual_currency
        from decimal import Decimal
        from datetime import date

        data = request.get_json() or {}

        # Validar datos requeridos
        superficie_m2 = data.get('superficie_m2')
        if not superficie_m2 or float(superficie_m2) <= 0:
            return jsonify({
                'ok': False,
                'error': 'Superficie en m² es requerida y debe ser mayor a 0'
            }), 400

        etapa_ids = data.get('etapa_ids', [])
        if not etapa_ids:
            return jsonify({
                'ok': False,
                'error': 'Debes seleccionar al menos una etapa para calcular'
            }), 400

        # Parámetros opcionales
        tipo_calculo = data.get('tipo_calculo', 'Estándar')
        parametros_contexto = data.get('parametros_contexto', {})
        presupuesto_id = data.get('presupuesto_id')
        currency = (data.get('currency') or data.get('moneda', 'ARS')).upper()
        aplicar_desperdicio = data.get('aplicar_desperdicio', True)  # Por defecto True
        aplicar_redondeo = data.get('aplicar_redondeo', True)  # Redondeo de compras
        mostrar_sobrante = data.get('mostrar_sobrante', True)  # Mostrar sobrantes

        # Siempre obtener tipo de cambio para precios duales
        fx_snapshot = None
        fx_rate = None
        try:
            fx_snapshot = ensure_rate(
                provider='bna_html',
                base_currency='ARS',
                quote_currency='USD',
                fetcher=fetch_official_rate,
                as_of=date.today(),
                fallback_rate=Decimal('1000.00')  # Fallback conservador
            )
            fx_rate = float(fx_snapshot.value)
            current_app.logger.info(f"Tipo de cambio BNA obtenido: {fx_rate} ARS/USD")
        except Exception as e:
            current_app.logger.warning(f"No se pudo obtener tipo de cambio: {str(e)}")
            # Continuar sin tipo de cambio

        # Obtener org_id del usuario actual para consultar inventario
        org_id = get_current_org_id()

        # Verificar si hay niveles de edificio configurados
        niveles = data.get('niveles')

        if niveles and len(niveles) > 0 and any(float(n.get('area_m2', 0)) > 0 for n in niveles):
            # Modo edificio por niveles
            from calculadora_ia import calcular_etapas_por_niveles
            resultado = calcular_etapas_por_niveles(
                etapas_payload=etapa_ids,
                niveles=niveles,
                tipo_calculo=tipo_calculo,
                contexto=parametros_contexto,
                presupuesto_id=presupuesto_id,
                currency='ARS',
                fx_snapshot=None,
                aplicar_desperdicio=aplicar_desperdicio,
                org_id=org_id,
            )
        else:
            # Modo global m² (sin cambios)
            resultado = calcular_etapas_seleccionadas(
                etapas_payload=etapa_ids,
                superficie_m2=float(superficie_m2),
                tipo_calculo=tipo_calculo,
                contexto=parametros_contexto,
                presupuesto_id=presupuesto_id,
                currency='ARS',
                fx_snapshot=None,
                aplicar_desperdicio=aplicar_desperdicio,
                org_id=org_id,
            )

        if resultado.get('ok') and resultado.get('etapas'):
            # Aplicar redondeo de compras y precios duales
            resultado_procesado = process_budget_with_rounding_and_dual_currency(
                etapas=resultado['etapas'],
                fx_rate=fx_rate,
                base_currency='ARS',
                apply_rounding=aplicar_redondeo,
                include_surplus=mostrar_sobrante
            )

            # Actualizar resultado con datos procesados
            resultado['etapas'] = resultado_procesado['etapas']
            resultado['total_parcial_ars'] = resultado_procesado.get('total_parcial_ars', resultado.get('total_parcial', 0))
            resultado['total_parcial'] = resultado['total_parcial_ars']  # Mantener compatibilidad
            resultado['redondeo_aplicado'] = aplicar_redondeo

            if fx_rate:
                resultado['total_parcial_usd'] = resultado_procesado.get('total_parcial_usd')
                resultado['tipo_cambio'] = {
                    'valor': fx_rate,
                    'proveedor': fx_snapshot.provider if fx_snapshot else 'fallback',
                    'base_currency': 'ARS',
                    'quote_currency': 'USD',
                    'fetched_at': fx_snapshot.fetched_at.isoformat() if fx_snapshot else None,
                    'as_of': fx_snapshot.as_of_date.isoformat() if fx_snapshot else None
                }

            if mostrar_sobrante and aplicar_redondeo:
                resultado['total_sobrante_estimado'] = resultado_procesado.get('total_sobrante_estimado', 0)

        return jsonify(resultado), 200

    except ValueError as e:
        current_app.logger.error(f"Error de validación en calcular_etapas_ia: {str(e)}")
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 400
    except Exception as e:
        current_app.logger.error(f"Error en calcular_etapas_ia: {str(e)}", exc_info=True)
        return jsonify({
            'ok': False,
            'error': f'Error al calcular etapas: {str(e)}'
        }), 500


# =============================================================================
# API DE PRECIOS - Datos importados desde Excel
# =============================================================================

@presupuestos_bp.route('/api/precios/buscar')
@login_required
def api_buscar_precios():
    """
    Busca articulos y precios en la base de datos de Excel importada.

    Query params:
        q: Termino de busqueda
        tipo: Tipo de construccion (Economica, Estandar, Premium)
        limite: Maximo de resultados (default 20)
    """
    try:
        from services.calculadora_precios import buscar_articulos

        termino = request.args.get('q', '').strip()
        tipo_construccion = request.args.get('tipo', 'Estandar')
        limite = min(int(request.args.get('limite', 20)), 100)

        if not termino or len(termino) < 2:
            return jsonify({'ok': True, 'articulos': [], 'mensaje': 'Ingrese al menos 2 caracteres'})

        articulos = buscar_articulos(
            termino=termino,
            tipo_construccion=tipo_construccion,
            solo_con_precio=True,
            limite=limite
        )

        return jsonify({
            'ok': True,
            'articulos': articulos,
            'total': len(articulos),
            'tipo_construccion': tipo_construccion
        })

    except Exception as e:
        current_app.logger.error(f"Error buscando precios: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/precios/categoria/<path:categoria>')
@login_required
def api_precios_categoria(categoria):
    """
    Obtiene todos los precios de una categoria especifica.
    """
    try:
        from services.calculadora_precios import obtener_precios_categoria

        tipo_construccion = request.args.get('tipo', 'Estandar')

        articulos = obtener_precios_categoria(
            categoria=categoria,
            tipo_construccion=tipo_construccion,
            solo_con_precio=True
        )

        return jsonify({
            'ok': True,
            'categoria': categoria,
            'articulos': articulos,
            'total': len(articulos),
            'tipo_construccion': tipo_construccion
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo precios de categoria: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/precios/categorias')
@login_required
def api_listar_categorias():
    """
    Lista todas las categorias disponibles.
    """
    try:
        from services.calculadora_precios import obtener_categorias_disponibles

        tipo_construccion = request.args.get('tipo', 'Estandar')
        categorias = obtener_categorias_disponibles(tipo_construccion)

        return jsonify({
            'ok': True,
            'categorias': categorias,
            'total': len(categorias),
            'tipo_construccion': tipo_construccion
        })

    except Exception as e:
        current_app.logger.error(f"Error listando categorias: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/precios/estadisticas')
@login_required
def api_estadisticas_precios():
    """
    Obtiene estadisticas de los datos de precios importados.
    """
    try:
        from services.calculadora_precios import obtener_estadisticas

        stats = obtener_estadisticas()

        return jsonify({
            'ok': True,
            'estadisticas': stats
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo estadisticas: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================================
# CALCULADORA IA MEJORADA - Endpoints
# ============================================================================

@presupuestos_bp.route('/api/calculadora/etapas')
@login_required
def api_calculadora_etapas():
    """
    Obtiene la lista de etapas disponibles con cantidad de items.
    """
    try:
        from services.calculadora_ia_mejorada import obtener_resumen_etapas

        etapas = obtener_resumen_etapas()

        return jsonify({
            'ok': True,
            'etapas': etapas,
            'total_etapas': len(etapas)
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo etapas: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/calculadora/calcular-etapa', methods=['POST'])
@login_required
def api_calculadora_calcular_etapa():
    """
    Calcula el presupuesto para una etapa específica.

    Body JSON:
        - etapa_slug: slug de la etapa
        - metros_cuadrados: superficie en m²
        - tipo_construccion: 'Económica', 'Estándar' o 'Premium'
        - tipo_cambio_usd: (opcional) tipo de cambio USD/ARS
    """
    try:
        from services.calculadora_ia_mejorada import calcular_etapa_mejorada

        data = request.get_json() or {}

        etapa_slug = data.get('etapa_slug')
        metros_cuadrados = float(data.get('metros_cuadrados', 0))
        tipo_construccion = data.get('tipo_construccion', 'Estándar')
        tipo_cambio_usd = float(data.get('tipo_cambio_usd', 1200))

        if not etapa_slug:
            return jsonify({'ok': False, 'error': 'etapa_slug es requerido'}), 400

        if metros_cuadrados <= 0:
            return jsonify({'ok': False, 'error': 'metros_cuadrados debe ser mayor a 0'}), 400

        org_id = get_current_org_id() or 2

        resultado = calcular_etapa_mejorada(
            etapa_slug=etapa_slug,
            metros_cuadrados=metros_cuadrados,
            tipo_construccion=tipo_construccion,
            org_id=org_id,
            tipo_cambio_usd=tipo_cambio_usd,
            incluir_items_detalle=True
        )

        return jsonify({
            'ok': True,
            'calculo': resultado
        })

    except Exception as e:
        current_app.logger.error(f"Error calculando etapa: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/calculadora/calcular-completo', methods=['POST'])
@login_required
def api_calculadora_calcular_completo():
    """
    Calcula el presupuesto completo para múltiples etapas.

    Body JSON:
        - metros_cuadrados: superficie en m²
        - tipo_construccion: 'Económica', 'Estándar' o 'Premium'
        - etapas: (opcional) lista de slugs de etapas, null = todas
        - tipo_cambio_usd: (opcional) tipo de cambio USD/ARS
    """
    try:
        from services.calculadora_ia_mejorada import calcular_presupuesto_completo

        data = request.get_json() or {}

        metros_cuadrados = float(data.get('metros_cuadrados', 0))
        tipo_construccion = data.get('tipo_construccion', 'Estándar')
        etapas = data.get('etapas')  # None = todas
        tipo_cambio_usd = float(data.get('tipo_cambio_usd', 1200))

        if metros_cuadrados <= 0:
            return jsonify({'ok': False, 'error': 'metros_cuadrados debe ser mayor a 0'}), 400

        org_id = get_current_org_id() or 2

        resultado = calcular_presupuesto_completo(
            metros_cuadrados=metros_cuadrados,
            tipo_construccion=tipo_construccion,
            etapas_seleccionadas=etapas,
            org_id=org_id,
            tipo_cambio_usd=tipo_cambio_usd
        )

        return jsonify({
            'ok': True,
            'presupuesto': resultado
        })

    except Exception as e:
        current_app.logger.error(f"Error calculando presupuesto completo: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/calculadora/items-etapa/<etapa_slug>')
@login_required
def api_calculadora_items_etapa(etapa_slug):
    """
    Obtiene los items de inventario para una etapa específica.

    Query params:
        - tipo: 'Económica', 'Estándar' o 'Premium' (default: Estándar)
        - limite: máximo de items a retornar (default: 50)
    """
    try:
        from services.calculadora_ia_mejorada import obtener_items_etapa_desde_bd, contar_items_etapa

        tipo_construccion = request.args.get('tipo', 'Estándar')
        limite = int(request.args.get('limite', 50))

        org_id = get_current_org_id() or 2

        items = obtener_items_etapa_desde_bd(
            etapa_slug=etapa_slug,
            tipo_construccion=tipo_construccion,
            org_id=org_id,
            limite=limite
        )

        conteo = contar_items_etapa(etapa_slug, tipo_construccion, org_id)

        return jsonify({
            'ok': True,
            'etapa_slug': etapa_slug,
            'tipo_construccion': tipo_construccion,
            'items': items,
            'total_disponibles': conteo['total'],
            'con_precio': conteo['con_precio']
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo items de etapa: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================================
# MERCADOLIBRE - Precios de referencia
# ============================================================================

@presupuestos_bp.route('/api/calculadora/precios-mercadolibre')
@login_required
def api_precios_mercadolibre():
    """
    Obtiene precios de materiales desde MercadoLibre (cache 24hs).
    Query params:
        - material: codigo de material (ej: MAT-CEMENTO). Si no se pasa, retorna todos.
        - forzar: si '1', ignora cache
    """
    try:
        from services.mercadolibre_precios import (
            obtener_precio_material_ml,
            obtener_precios_ml_como_referencia,
            MATERIALES_ML
        )

        material = request.args.get('material')
        forzar = request.args.get('forzar') == '1'

        if material:
            resultado = obtener_precio_material_ml(material, forzar=forzar)
            if resultado:
                return jsonify({'ok': True, 'precio': resultado})
            return jsonify({'ok': False, 'error': f'Sin resultados para {material}'}), 404

        # Retornar todos los precios en cache
        precios = obtener_precios_ml_como_referencia()
        materiales_disponibles = list(MATERIALES_ML.keys())
        return jsonify({
            'ok': True,
            'precios': precios,
            'materiales_disponibles': materiales_disponibles,
            'total_en_cache': len(precios),
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo precios ML: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/calculadora/actualizar-precios-ml', methods=['POST'])
@csrf.exempt
@login_required
def api_actualizar_precios_ml():
    """
    Actualiza todos los precios de materiales desde MercadoLibre.
    Solo admin puede forzar actualizacion.
    """
    try:
        rol = getattr(current_user, 'rol', '') or ''
        role = getattr(current_user, 'role', '') or ''
        if rol not in ('administrador', 'admin') and role not in ('admin',):
            return jsonify({'error': 'Solo admin puede actualizar precios'}), 403

        from services.mercadolibre_precios import actualizar_todos_los_precios
        resultado = actualizar_todos_los_precios(forzar=True)
        return jsonify({'ok': True, 'resultado': resultado})

    except Exception as e:
        current_app.logger.error(f"Error actualizando precios ML: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/calculadora/buscar-precio-ml')
@login_required
def api_buscar_precio_ml():
    """
    Busca un producto en MercadoLibre y retorna precios.
    Query params:
        - q: termino de busqueda (ej: 'cemento portland 50kg')
        - limit: cantidad de resultados (default 10)
    """
    try:
        from services.mercadolibre_precios import buscar_precio_mercadolibre

        query = request.args.get('q', '').strip()
        limit = int(request.args.get('limit', 10))

        if not query:
            return jsonify({'ok': False, 'error': 'Parametro q requerido'}), 400

        resultado = buscar_precio_mercadolibre(query, limit=limit)
        if resultado:
            return jsonify({'ok': True, 'resultado': resultado})
        return jsonify({'ok': False, 'error': 'Sin resultados'}), 404

    except Exception as e:
        current_app.logger.error(f"Error buscando precio ML: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/api/calculadora/precios-referencia')
@login_required
def api_precios_referencia():
    """
    Retorna los precios de referencia de constructoras reales
    cargados desde el Excel de presupuestos.
    """
    try:
        from services.calculadora_ia_mejorada import _cargar_precios_constructora
        ref = _cargar_precios_constructora()
        return jsonify({
            'ok': True,
            'etapas_con_referencia': list(ref.keys()),
            'datos': ref,
        })
    except Exception as e:
        current_app.logger.error(f"Error obteniendo precios referencia: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
