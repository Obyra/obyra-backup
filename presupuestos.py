from flask import Blueprint, render_template, request, flash, redirect, url_for, make_response, jsonify, current_app, g
from flask_login import login_required, current_user
import datetime as dt
from datetime import date, timedelta
from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import importlib.util
import json
import os
from typing import Any, Optional

REPORTLAB_AVAILABLE = importlib.util.find_spec("reportlab") is not None
if REPORTLAB_AVAILABLE:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
else:  # pragma: no cover - executed only when optional deps missing
    letter = A4 = None  # type: ignore[assignment]
    colors = None  # type: ignore[assignment]
    inch = 72  # type: ignore[assignment]

    def _missing_reportlab(*args: Any, **kwargs: Any):
        raise RuntimeError(
            "La librería reportlab no está instalada. Ejecuta 'pip install reportlab' para habilitar la generación de PDFs."
        )

    SimpleDocTemplate = Table = TableStyle = Paragraph = Spacer = _missing_reportlab  # type: ignore[assignment]
    getSampleStyleSheet = ParagraphStyle = _missing_reportlab  # type: ignore[assignment]
    TA_CENTER = TA_RIGHT = None  # type: ignore[assignment]


XLSXWRITER_AVAILABLE = importlib.util.find_spec("xlsxwriter") is not None
if XLSXWRITER_AVAILABLE:
    import xlsxwriter
else:  # pragma: no cover - executed only when optional deps missing
    xlsxwriter = None  # type: ignore[assignment]

from app import db
from models import Presupuesto, ItemPresupuesto, Obra, EtapaObra, TareaEtapa, Event
from calculadora_ia import (
    procesar_presupuesto_ia,
    COEFICIENTES_CONSTRUCCION,
    calcular_etapas_seleccionadas,
    slugify_etapa,
)
from obras import seed_tareas_para_etapa
from services.exchange import base as exchange_service
from services.exchange.providers import bna as bna_provider
from services.cac.cac_service import get_cac_context
from services.geocoding_service import resolve as resolve_geocode, search as search_geocode
from services.memberships import get_current_org_id


def _clean_text(value: Any) -> Optional[str]:
    """Normaliza cadenas eliminando espacios y devolviendo None para vacíos."""

    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return str(value)


def _parse_date(value: Any) -> Optional[date]:
    """Intenta parsear una fecha en formatos comunes (ISO o DD/MM/YYYY)."""

    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(str(value), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


DECIMAL_ZERO = Decimal("0")
CURRENCY_QUANT = Decimal("0.01")
QUANTITY_QUANT = Decimal("0.001")
ALLOWED_CURRENCIES = {"ARS", "USD"}
COORD_QUANT = Decimal("0.00000001")


def _to_bool(value: Any, default: bool = False) -> bool:
    """Convierte entradas típicas de formularios/JSON a booleanos reales."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "on", "yes", "si", "sí"}:
            return True
        if normalized in {"0", "false", "f", "off", "no"}:
            return False
    return default


def _registrar_evento_confirmacion(org_id: Optional[int], obra_id: Optional[int],
                                   presupuesto_id: Optional[int], usuario_id: Optional[int],
                                   trigger: str) -> None:
    """Registra un evento de auditoría para la confirmación de presupuestos."""

    if not org_id or not obra_id or not presupuesto_id:
        return

    try:
        evento = Event(
            company_id=org_id,
            project_id=obra_id,
            user_id=usuario_id,
            type='status_change',
            severity='media',
            title='Presupuesto confirmado',
            description=(
                f'El presupuesto #{presupuesto_id} fue confirmado y se creó la obra #{obra_id}.'
            ),
            meta={
                'source': trigger,
                'presupuesto_id': presupuesto_id,
                'obra_id': obra_id,
            },
            created_by=usuario_id,
        )
        db.session.add(evento)
        db.session.commit()
    except Exception:  # pragma: no cover - logging auxiliar
        db.session.rollback()
        current_app.logger.exception(
            'No se pudo registrar el evento de confirmación del presupuesto %s',
            presupuesto_id,
        )


def _resolve_currency_context(raw_currency: Any):
    """Determina la moneda solicitada y obtiene el tipo de cambio si aplica."""

    currency = str(raw_currency).upper() if raw_currency else 'ARS'
    if currency not in ALLOWED_CURRENCIES:
        currency = 'ARS'

    snapshot = None
    if currency != 'ARS':
        provider = (os.environ.get('FX_PROVIDER') or 'bna').lower()
        if provider != 'bna':
            provider = 'bna'
        fallback_env = os.environ.get('EXCHANGE_FALLBACK_RATE')
        fallback = Decimal(str(fallback_env)) if fallback_env else None
        try:
            snapshot = exchange_service.ensure_rate(
                provider,
                base_currency='ARS',
                quote_currency=currency,
                fetcher=bna_provider.fetch_official_rate,
                as_of=date.today(),
                fallback_rate=fallback,
            )
        except Exception as exc:
            current_app.logger.warning('No se pudo obtener el tipo de cambio: %s', exc)
            if fallback is not None:
                snapshot = exchange_service.ensure_rate(
                    provider,
                    base_currency='ARS',
                    quote_currency=currency,
                    fetcher=lambda *_args, **_kwargs: None,
                    as_of=date.today(),
                    fallback_rate=fallback,
                )
            else:
                raise

    return currency, snapshot


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    """Convierte un valor arbitrario a Decimal utilizando '.' como separador."""

    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    if isinstance(value, (int, float)):
        normalized = str(value)
    else:
        text = str(value).strip()
        if not text:
            return Decimal(default)
        normalized = text.replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _quantize_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)


def _quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_QUANT, rounding=ROUND_HALF_UP)


def _quantize_coord(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        coord = _to_decimal(value, '0')
    except (InvalidOperation, ValueError, TypeError):
        return None
    return coord.quantize(COORD_QUANT, rounding=ROUND_HALF_UP)


def _parse_vigencia_dias(raw_value: Any) -> Optional[int]:
    if raw_value is None:
        return None
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return None
    if value < 1 or value > 180:
        return None
    return value


def _sumar_totales(items) -> Decimal:
    total = DECIMAL_ZERO
    for item in items:
        valor = getattr(item, 'total_currency', None)
        if valor is None:
            valor = getattr(item, 'total', 0)
        total += _quantize_currency(_to_decimal(valor, '0'))
    return _quantize_currency(total)


def _persistir_resultados_etapas(
    presupuesto: Presupuesto,
    etapas_resultado: list,
    superficie: Optional[Decimal],
    tipo_calculo: str,
    currency: str,
    fx_snapshot,
    cac_context,
):
    """Aplica los resultados IA al presupuesto, reemplazando items previos de cada etapa."""

    if not etapas_resultado:
        return False, 'Sin etapas para aplicar'

    presupuesto.currency = currency
    try:
        presupuesto.registrar_tipo_cambio(fx_snapshot)
    except AttributeError:
        pass

    if cac_context:
        presupuesto.indice_cac_valor = _quantize_currency(_to_decimal(cac_context.value, '0'))
        presupuesto.indice_cac_fecha = cac_context.period

    obra = presupuesto.obra
    slug_a_etapa = {}
    orden_base = 0
    if obra:
        etapas_existentes = obra.etapas.order_by(EtapaObra.orden.asc()).all()
        slug_a_etapa = {slugify_etapa(e.nombre): e for e in etapas_existentes}
        orden_base = len(etapas_existentes)

    hubo_cambios = False

    for index, etapa_data in enumerate(etapas_resultado, start=1):
        slug = slugify_etapa(etapa_data.get('slug') or etapa_data.get('nombre') or f'etapa-{index}')
        etapa_modelo = slug_a_etapa.get(slug)

        if obra and not etapa_modelo:
            etapa_modelo = EtapaObra(
                obra_id=obra.id,
                nombre=etapa_data.get('nombre') or f'Etapa {index}',
                descripcion=etapa_data.get('notas') or f'Etapa generada automáticamente ({tipo_calculo})',
                orden=orden_base + index,
                estado='pendiente',
            )
            db.session.add(etapa_modelo)
            db.session.flush()
            slug_a_etapa[slug] = etapa_modelo
            hubo_cambios = True

        query = ItemPresupuesto.query.filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id,
            ItemPresupuesto.origen == 'ia',
        )
        if etapa_modelo:
            query = query.filter(ItemPresupuesto.etapa_id == etapa_modelo.id)
        else:
            query = query.filter(ItemPresupuesto.etapa_id.is_(None))

        eliminados = query.delete(synchronize_session=False)
        if eliminados:
            hubo_cambios = True

        for item_data in etapa_data.get('items', []):
            tipo_item = (item_data.get('tipo') or 'material').strip().lower()
            if tipo_item not in {'material', 'mano_obra', 'equipo', 'herramienta'}:
                tipo_item = 'material'

            cantidad = _quantize_quantity(_to_decimal(item_data.get('cantidad'), '0'))
            precio_moneda = _quantize_currency(_to_decimal(item_data.get('precio_unit'), '0'))
            precio_ars = _quantize_currency(_to_decimal(item_data.get('precio_unit_ars'), '0'))

            if precio_ars <= DECIMAL_ZERO and fx_snapshot and getattr(fx_snapshot, 'value', None):
                precio_ars = _quantize_currency(precio_moneda * _to_decimal(fx_snapshot.value, '1'))

            total_currency = _quantize_currency(cantidad * precio_moneda)
            total_ars = _quantize_currency(cantidad * (precio_ars if precio_ars > DECIMAL_ZERO else precio_moneda))

            nuevo_item = ItemPresupuesto(
                presupuesto_id=presupuesto.id,
                tipo=tipo_item,
                descripcion=item_data.get('descripcion') or f'Ítem {tipo_item} etapa {etapa_data.get("nombre") or index}',
                unidad=item_data.get('unidad') or 'unidades',
                cantidad=cantidad,
                precio_unitario=precio_ars,
                total=total_ars,
                origen='ia',
                currency=currency,
                price_unit_currency=precio_moneda,
                total_currency=total_currency,
                price_unit_ars=precio_ars,
                total_ars=total_ars,
            )

            if etapa_modelo:
                nuevo_item.etapa_id = etapa_modelo.id

            db.session.add(nuevo_item)
            hubo_cambios = True

    if hubo_cambios:
        presupuesto.calcular_totales()
        db.session.add(presupuesto)

    return hubo_cambios, None


presupuestos_bp = Blueprint('presupuestos', __name__)

@presupuestos_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    estado = request.args.get('estado', '')
    vigencia = request.args.get('vigencia', '')
    if estado == 'eliminado' and current_user.rol != 'administrador':
        estado = ''
    incluir_eliminados = estado == 'eliminado'
    buscar = request.args.get('buscar', '')

    # Modificar query para incluir presupuestos sin obra (LEFT JOIN) y excluir convertidos
    query = Presupuesto.query.outerjoin(Obra).filter(
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.estado != 'convertido'  # Excluir presupuestos ya convertidos en obras
    )

    if incluir_eliminados:
        query = query.filter(Presupuesto.deleted_at.isnot(None))
    else:
        query = query.filter(Presupuesto.deleted_at.is_(None))

    if estado and estado != 'eliminado':
        query = query.filter(Presupuesto.estado == estado)
    elif not incluir_eliminados:
        query = query.filter(Presupuesto.estado != 'eliminado')
    
    if vigencia == 'vencidos':
        query = query.filter(
            Presupuesto.fecha_vigencia.isnot(None),
            Presupuesto.fecha_vigencia < date.today(),
            Presupuesto.estado.in_(['borrador', 'perdido', 'enviado', 'rechazado', 'vencido'])
        )
    elif vigencia == 'por_vencer':
        limite = date.today() + timedelta(days=7)
        query = query.filter(
            Presupuesto.fecha_vigencia.isnot(None),
            Presupuesto.fecha_vigencia >= date.today(),
            Presupuesto.fecha_vigencia <= limite,
            Presupuesto.estado.in_(['borrador', 'enviado'])
        )

    if buscar:
        query = query.filter(
            db.or_(
                Presupuesto.numero.contains(buscar),
                Presupuesto.observaciones.contains(buscar),
                Obra.nombre.contains(buscar) if Obra.nombre else False,
                Obra.cliente.contains(buscar) if Obra.cliente else False
            )
        )

    presupuestos = query.order_by(Presupuesto.fecha_creacion.desc()).all()

    return render_template('presupuestos/lista.html',
                         presupuestos=presupuestos,
                         estado=estado,
                         buscar=buscar,
                         vigencia=vigencia)


@presupuestos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para crear presupuestos.', 'danger')
        return redirect(url_for('presupuestos.lista'))
    
    if request.method == 'POST':
        # Obtener datos del nuevo formulario
        nombre_obra = request.form.get('nombre_obra')
        tipo_obra = request.form.get('tipo_obra')
        ubicacion = request.form.get('ubicacion')
        tipo_construccion = request.form.get('tipo_construccion')
        superficie_m2 = request.form.get('superficie_m2')
        fecha_inicio = request.form.get('fecha_inicio')
        fecha_fin = request.form.get('fecha_fin')
        presupuesto_disponible = request.form.get('presupuesto_disponible')
        moneda = request.form.get('moneda', 'ARS')
        cliente_nombre = request.form.get('cliente_nombre')
        plano_pdf = request.files.get('plano_pdf')
        ia_payload_raw = request.form.get('ia_etapas_payload')
        ia_payload = None
        if ia_payload_raw:
            try:
                ia_payload = json.loads(
                    ia_payload_raw,
                    parse_float=Decimal,
                    parse_int=Decimal,
                )
            except (TypeError, ValueError, InvalidOperation):
                current_app.logger.warning(
                    'Payload IA de etapas inválido, se omitirá durante la creación del presupuesto.'
                )
                ia_payload = None

        ubicacion_lat = request.form.get('ubicacion_lat')
        ubicacion_lng = request.form.get('ubicacion_lng')
        ubicacion_normalizada = request.form.get('ubicacion_normalizada') or None
        ubicacion_place_id = request.form.get('ubicacion_place_id') or None
        ubicacion_provider = request.form.get('ubicacion_provider') or None
        ubicacion_geocode_status = request.form.get('ubicacion_geocode_status') or None

        # Validaciones
        if not all([nombre_obra, tipo_obra, ubicacion, tipo_construccion, superficie_m2]):
            flash('Completa todos los campos obligatorios.', 'danger')
            return render_template('presupuestos/crear.html')
        
        superficie_decimal = _quantize_quantity(_to_decimal(superficie_m2, '0'))
        if superficie_decimal <= DECIMAL_ZERO:
            flash('La superficie debe ser mayor a 0.', 'danger')
            return render_template('presupuestos/crear.html')

        try:
            currency, fx_snapshot = _resolve_currency_context(moneda)
        except Exception as exc:
            current_app.logger.exception('Error obteniendo tipo de cambio para crear presupuesto')
            flash('No pudimos obtener el tipo de cambio solicitado. Intenta nuevamente más tarde.', 'danger')
            return render_template('presupuestos/crear.html')

        geocode_payload = None
        geocode_status = ubicacion_geocode_status or 'pending'
        geocode_provider = ubicacion_provider or current_app.config.get('MAPS_PROVIDER') or 'nominatim'
        geocode_place_id = ubicacion_place_id
        direccion_normalizada = ubicacion_normalizada

        lat_decimal = _quantize_coord(ubicacion_lat)
        lng_decimal = _quantize_coord(ubicacion_lng)

        if lat_decimal is not None and lng_decimal is not None:
            geocode_payload = {
                'lat': float(lat_decimal),
                'lng': float(lng_decimal),
                'provider': geocode_provider,
                'place_id': geocode_place_id,
                'normalized': direccion_normalizada or _clean_text(ubicacion),
                'status': geocode_status or 'ok',
                'raw': None,
            }

        if geocode_payload is None:
            try:
                resolved = resolve_geocode(ubicacion)
            except Exception as exc:  # pragma: no cover - logging fallback
                current_app.logger.warning('No se pudo geocodificar la dirección %s: %s', ubicacion, exc)
                resolved = None

            if resolved:
                geocode_payload = resolved
                direccion_normalizada = resolved.get('normalized') or direccion_normalizada
                geocode_provider = resolved.get('provider') or geocode_provider
                geocode_place_id = resolved.get('place_id') or geocode_place_id
                geocode_status = resolved.get('status') or 'ok'
                lat_decimal = _quantize_coord(resolved.get('lat'))
                lng_decimal = _quantize_coord(resolved.get('lng'))
            else:
                geocode_status = 'fail'

        # Crear nueva obra basada en los datos del formulario
        nueva_obra = Obra()
        nueva_obra.nombre = nombre_obra
        nueva_obra.descripcion = f"Obra {tipo_obra.replace('_', ' ').title()} - {tipo_construccion.title()}"
        nueva_obra.direccion = ubicacion
        nueva_obra.direccion_normalizada = direccion_normalizada
        nueva_obra.cliente = cliente_nombre or "Cliente Sin Especificar"
        nueva_obra.estado = 'planificacion'
        nueva_obra.organizacion_id = current_user.organizacion_id

        if lat_decimal is not None and lng_decimal is not None:
            nueva_obra.latitud = lat_decimal
            nueva_obra.longitud = lng_decimal
        if geocode_payload:
            nueva_obra.geocode_place_id = geocode_place_id
            nueva_obra.geocode_provider = geocode_provider
            nueva_obra.geocode_status = geocode_status
            raw_payload = geocode_payload.get('raw')
            nueva_obra.geocode_raw = json.dumps(raw_payload) if raw_payload else nueva_obra.geocode_raw
            nueva_obra.geocode_actualizado = dt.datetime.utcnow()
        elif geocode_status:
            nueva_obra.geocode_status = geocode_status
        
        # Procesar fechas
        if fecha_inicio:
            nueva_obra.fecha_inicio = dt.datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
        if fecha_fin:
            nueva_obra.fecha_fin_estimada = dt.datetime.strptime(fecha_fin, '%Y-%m-%d').date()
        
        # Procesar presupuesto disponible
        if presupuesto_disponible:
            try:
                presupuesto_decimal = _quantize_currency(_to_decimal(presupuesto_disponible, '0'))
                nueva_obra.presupuesto_total = presupuesto_decimal
            except (InvalidOperation, ValueError, TypeError):
                pass
        
        try:
            db.session.add(nueva_obra)
            db.session.flush()  # Para obtener el ID de la obra
            
            # Generar número de presupuesto único
            ultimo_numero = db.session.query(db.func.max(Presupuesto.numero)).scalar()
            if ultimo_numero and ultimo_numero.startswith('PRES-'):
                try:
                    siguiente_num = int(ultimo_numero.split('-')[1]) + 1
                except:
                    siguiente_num = 1
            else:
                siguiente_num = 1
            
            # Asegurar que el número sea único
            while True:
                numero = f"PRES-{siguiente_num:04d}"
                existe = Presupuesto.query.filter_by(numero=numero).first()
                if not existe:
                    break
                siguiente_num += 1
            
            # Crear presupuesto asociado
            nuevo_presupuesto = Presupuesto()
            nuevo_presupuesto.obra_id = nueva_obra.id
            nuevo_presupuesto.numero = numero
            nuevo_presupuesto.iva_porcentaje = Decimal('21.00')  # Fijo según lo solicitado
            nuevo_presupuesto.organizacion_id = current_user.organizacion_id
            nuevo_presupuesto.currency = currency
            vigencia_form = request.form.get('vigencia_dias', '').strip()
            if vigencia_form:
                vigencia_dias = _parse_vigencia_dias(vigencia_form)
                if vigencia_dias is None:
                    flash('La vigencia debe ser un número entre 1 y 180 días.', 'danger')
                    return render_template('presupuestos/crear.html')
            else:
                vigencia_dias = 30

            nuevo_presupuesto.vigencia_dias = vigencia_dias
            nuevo_presupuesto.vigencia_bloqueada = True
            nuevo_presupuesto.asegurar_vigencia()

            # Agregar observaciones con detalles del proyecto
            observaciones_proyecto = []
            observaciones_proyecto.append(f"Tipo de obra: {tipo_obra.replace('_', ' ').title()}")
            observaciones_proyecto.append(f"Tipo de construcción: {tipo_construccion.title()}")
            observaciones_proyecto.append(f"Superficie: {superficie_decimal} m²")
            if presupuesto_disponible:
                observaciones_proyecto.append(f"Presupuesto disponible: {currency} {presupuesto_disponible}")
            if plano_pdf and plano_pdf.filename:
                observaciones_proyecto.append(f"Plano PDF: {plano_pdf.filename}")

            nuevo_presupuesto.observaciones = " | ".join(observaciones_proyecto)
            nuevo_presupuesto.ubicacion_texto = ubicacion
            nuevo_presupuesto.ubicacion_normalizada = direccion_normalizada
            nuevo_presupuesto.geo_latitud = lat_decimal
            nuevo_presupuesto.geo_longitud = lng_decimal
            nuevo_presupuesto.geocode_place_id = geocode_place_id
            nuevo_presupuesto.geocode_provider = geocode_provider
            nuevo_presupuesto.geocode_status = geocode_status

            db.session.add(nuevo_presupuesto)
            db.session.flush()  # Para obtener el ID del presupuesto

            try:
                nuevo_presupuesto.registrar_tipo_cambio(fx_snapshot)
            except AttributeError:
                pass

            if geocode_payload:
                raw_payload = geocode_payload.get('raw')
                nuevo_presupuesto.geocode_raw = json.dumps(raw_payload) if raw_payload else nuevo_presupuesto.geocode_raw
                nuevo_presupuesto.geocode_actualizado = dt.datetime.utcnow()

            datos_proyecto = {
                'nombre': nombre_obra,
                'tipo_obra': tipo_obra,
                'tipo_construccion': tipo_construccion,
                'superficie': float(superficie_decimal),
                'ubicacion': ubicacion,
                'ubicacion_normalizada': direccion_normalizada,
                'latitud': float(lat_decimal) if lat_decimal is not None else None,
                'longitud': float(lng_decimal) if lng_decimal is not None else None,
                'geocode_provider': geocode_provider,
                'geocode_status': geocode_status,
                'geocode_place_id': geocode_place_id,
            }
            nuevo_presupuesto.datos_proyecto = json.dumps(datos_proyecto, default=str)

            cac_context = get_cac_context()
            if cac_context:
                nuevo_presupuesto.indice_cac_valor = _quantize_currency(_to_decimal(cac_context.value, '0'))
                nuevo_presupuesto.indice_cac_fecha = cac_context.period

            # Procesar etapas si se enviaron
            etapas_count = 0
            etapa_index = 0
            etapas_creadas_por_slug = {}
            etapas_serializadas = []
            while True:
                etapa_nombre = request.form.get(f'etapas[{etapa_index}][nombre]')
                if not etapa_nombre:
                    break

                etapa_descripcion = request.form.get(f'etapas[{etapa_index}][descripcion]', '')
                etapa_orden = request.form.get(f'etapas[{etapa_index}][orden]', etapa_index + 1)
                etapa_slug = request.form.get(f'etapas[{etapa_index}][slug]')

                try:
                    orden_int = int(etapa_orden)
                except ValueError:
                    orden_int = etapa_index + 1

                slug_normalizado = slugify_etapa(etapa_slug or etapa_nombre)

                # Crear etapa para la obra
                nueva_etapa = EtapaObra(
                    obra_id=nueva_obra.id,
                    nombre=etapa_nombre,
                    descripcion=etapa_descripcion,
                    orden=orden_int,
                    estado='pendiente'
                )

                db.session.add(nueva_etapa)
                db.session.flush()
                seed_tareas_para_etapa(
                    nueva_etapa,
                    auto_commit=False,
                    slug=slug_normalizado,
                )
                if nueva_etapa.tareas.count() == 0:
                    db.session.add(TareaEtapa(
                        etapa_id=nueva_etapa.id,
                        nombre=f'Tarea inicial de {etapa_nombre}',
                        descripcion='Tarea generada automáticamente a partir del presupuesto.',
                        estado='pendiente'
                    ))

                etapas_creadas_por_slug[slug_normalizado] = nueva_etapa
                etapas_serializadas.append({
                    'nombre': etapa_nombre,
                    'descripcion': etapa_descripcion or '',
                    'orden': orden_int,
                    'slug': slug_normalizado
                })
                etapas_count += 1
                etapa_index += 1

            # Crear items a partir del cálculo IA por etapas si llegó payload
            if ia_payload and ia_payload.get('etapas'):
                tipos_validos = {'material', 'mano_obra', 'equipo', 'herramienta'}
                for etapa_resultado in ia_payload.get('etapas', []):
                    slug_etapa = slugify_etapa(etapa_resultado.get('slug') or etapa_resultado.get('nombre'))
                    etapa_modelo = etapas_creadas_por_slug.get(slug_etapa)

                    for item_data in etapa_resultado.get('items', []):
                        try:
                            tipo_item = (item_data.get('tipo') or 'material').strip()
                        except AttributeError:
                            tipo_item = 'material'
                        tipo_item = tipo_item if tipo_item in tipos_validos else 'material'

                        cantidad_dec = _quantize_quantity(_to_decimal(item_data.get('cantidad'), '0'))
                        precio_moneda = _quantize_currency(_to_decimal(item_data.get('precio_unit'), '0'))
                        precio_ars = _quantize_currency(_to_decimal(item_data.get('precio_unit_ars'), '0'))
                        if precio_ars <= DECIMAL_ZERO and fx_snapshot and getattr(fx_snapshot, 'value', None):
                            precio_ars = _quantize_currency(precio_moneda * _to_decimal(fx_snapshot.value, '1'))

                        total_currency = _quantize_currency(cantidad_dec * precio_moneda)
                        total_ars = _quantize_currency(cantidad_dec * (precio_ars if precio_ars > DECIMAL_ZERO else precio_moneda))

                        nuevo_item = ItemPresupuesto(
                            presupuesto_id=nuevo_presupuesto.id,
                            tipo=tipo_item,
                            descripcion=item_data.get('descripcion', 'Item IA de etapa'),
                            unidad=item_data.get('unidad', 'unidades'),
                            cantidad=cantidad_dec,
                            precio_unitario=precio_ars,
                            total=total_ars,
                            origen='ia',
                            currency=currency,
                            price_unit_currency=precio_moneda,
                            total_currency=total_currency,
                            price_unit_ars=precio_ars,
                            total_ars=total_ars,
                        )
                        if etapa_modelo:
                            nuevo_item.etapa_id = etapa_modelo.id

                        db.session.add(nuevo_item)

                nuevo_presupuesto.calcular_totales()
            else:
                nuevo_presupuesto.asegurar_vigencia()

            if etapas_serializadas:
                datos_proyecto['etapas'] = etapas_serializadas

            nuevo_presupuesto.datos_proyecto = json.dumps(datos_proyecto, default=str)

            db.session.commit()

            mensaje_exito = f'Obra "{nombre_obra}" y presupuesto {numero} creados exitosamente.'
            if etapas_count > 0:
                mensaje_exito += f' Se agregaron {etapas_count} etapas al proyecto.'
            
            flash(mensaje_exito, 'success')
            return redirect(url_for('presupuestos.detalle', id=nuevo_presupuesto.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear la obra y presupuesto: {str(e)}', 'danger')
    
    return render_template('presupuestos/crear.html')

@presupuestos_bp.route('/calculadora-ia')
@login_required
def calculadora_ia():
    """Nueva calculadora IA de presupuestos basada en planos"""
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para acceder a la calculadora IA.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    obras = Obra.query.filter(Obra.estado.in_(['planificacion', 'en_curso'])).order_by(Obra.nombre).all()
    tipos_construccion = list(COEFICIENTES_CONSTRUCCION.keys())
    
    return render_template('presupuestos/calculadora_ia.html',
                         obras=obras,
                         tipos_construccion=tipos_construccion)


@presupuestos_bp.route('/geo/sugerencias')
@login_required
def sugerencias_geograficas():
    if not current_user.puede_acceder_modulo('presupuestos'):
        return jsonify({'ok': False, 'error': 'Sin permisos para geocodificar'}), 403

    consulta = (request.args.get('q') or '').strip()
    if not consulta:
        return jsonify({'ok': True, 'resultados': []})

    provider = request.args.get('provider')
    resultados = search_geocode(consulta, provider=provider, limit=5)

    serializados = []
    for resultado in resultados:
        serializados.append({
            'display_name': resultado.get('display_name'),
            'lat': resultado.get('lat'),
            'lng': resultado.get('lng'),
            'provider': resultado.get('provider'),
            'place_id': resultado.get('place_id'),
            'normalized': resultado.get('normalized'),
            'status': resultado.get('status'),
        })

    return jsonify({'ok': True, 'resultados': serializados})

@presupuestos_bp.route('/procesar-calculadora-ia', methods=['POST'])
@login_required
def procesar_calculadora_ia():
    """Procesa el análisis IA del plano y calcula materiales - Estilo Togal.AI"""
    if not current_user.puede_acceder_modulo('presupuestos'):
        return jsonify({'error': 'Sin permisos'}), 403
    
    try:
        # Obtener datos del formulario
        metros_cuadrados = request.form.get('metros_cuadrados')
        tipo_construccion = request.form.get('tipo_construccion', '').strip()
        archivo_pdf = request.files.get('archivo_pdf')
        
        # Validación: debe tener superficie
        if not metros_cuadrados:
            return jsonify({'error': 'Ingresa los metros cuadrados del proyecto'}), 400
        
        try:
            superficie_m2 = float(metros_cuadrados)
            if superficie_m2 <= 0:
                return jsonify({'error': 'Los metros cuadrados deben ser mayor a 0'}), 400
        except ValueError:
            return jsonify({'error': 'Metros cuadrados inválidos'}), 400
        
        # Si no hay tipo, usar IA para sugerir o usar Estándar
        if not tipo_construccion:
            # IA sugiere tipo basado en superficie
            if superficie_m2 < 80:
                tipo_final = "Económica"
            elif superficie_m2 > 300:
                tipo_final = "Premium"
            else:
                tipo_final = "Estándar"
        else:
            tipo_final = tipo_construccion
        
        # Validar tipo
        if tipo_final not in COEFICIENTES_CONSTRUCCION:
            tipo_final = "Estándar"
        
        # USAR FUNCIÓN COMPLETA CON ETAPAS
        resultado = procesar_presupuesto_ia(
            archivo_pdf=archivo_pdf,
            metros_cuadrados_manual=metros_cuadrados,
            tipo_construccion_forzado=tipo_final
        )
        
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({'error': f'Error procesando calculadora: {str(e)}'}), 500


@presupuestos_bp.route('/ia/calcular/etapas', methods=['POST'])
@login_required
def calcular_etapas_ia():
    """Calcula con IA determinística las etapas seleccionadas de un presupuesto."""
    if not current_user.puede_acceder_modulo('presupuestos'):
        return jsonify({'ok': False, 'error': 'Sin permisos para usar la IA de presupuestos'}), 403

    data = request.get_json(silent=True) or {}
    etapa_payload = data.get('etapa_ids') or []
    superficie = data.get('superficie_m2')
    tipo_calculo = data.get('tipo_calculo') or data.get('tipo_construccion') or 'Estándar'
    contexto = data.get('parametros_contexto') or {}
    presupuesto_id = data.get('presupuesto_id')
    persistir = bool(data.get('persistir'))
    moneda_raw = data.get('currency') or data.get('moneda')

    try:
        currency, fx_snapshot = _resolve_currency_context(moneda_raw)
    except Exception as exc:
        current_app.logger.exception('No se pudo resolver la moneda para la IA de presupuestos')
        return jsonify({'ok': False, 'error': f'No se pudo obtener el tipo de cambio: {exc}'}), 500

    if superficie is None:
        return jsonify({'ok': False, 'error': 'Debes indicar la superficie en m² para calcular.'}), 400

    superficie_decimal = _quantize_quantity(_to_decimal(superficie, '0'))
    if superficie_decimal <= DECIMAL_ZERO:
        return jsonify({'ok': False, 'error': 'La superficie debe ser mayor a 0.'}), 400

    try:
        resultado = calcular_etapas_seleccionadas(
            etapas_payload=etapa_payload,
            superficie_m2=str(superficie_decimal),
            tipo_calculo=tipo_calculo,
            contexto=contexto,
            presupuesto_id=presupuesto_id,
            currency=currency,
            fx_snapshot=fx_snapshot,
        )
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:  # pragma: no cover - logging de errores inesperados
        current_app.logger.exception('Error calculando etapas IA')
        return jsonify({'ok': False, 'error': 'No se pudo calcular las etapas seleccionadas.'}), 500

    resultado['superficie_usada'] = float(superficie_decimal)
    resultado['tipo_calculo'] = tipo_calculo
    resultado['ok'] = True
    resultado['presupuesto_id'] = presupuesto_id
    resultado['parametros_contexto'] = contexto
    resultado['moneda'] = currency

    if presupuesto_id and persistir:
        presupuesto = Presupuesto.query.filter_by(
            id=presupuesto_id,
            organizacion_id=current_user.organizacion_id,
        ).first()

        if not presupuesto:
            return jsonify({'ok': False, 'error': 'No encontramos el presupuesto indicado para aplicar los resultados.'}), 404

        total_antes = float(presupuesto.total_con_iva or 0)

        try:
            cac_context = get_cac_context()
            cambios, _ = _persistir_resultados_etapas(
                presupuesto,
                resultado.get('etapas', []),
                superficie_decimal,
                tipo_calculo,
                currency,
                fx_snapshot,
                cac_context,
            )
            if cambios:
                db.session.commit()
                total_despues = float(presupuesto.total_con_iva or 0)
                resultado['guardado'] = True
                resultado['total_actualizado'] = {
                    'antes': total_antes,
                    'despues': total_despues,
                }
                current_app.logger.info(
                    '💾 Etapas IA aplicadas al presupuesto',
                    extra={
                        'usuario_id': current_user.id,
                        'organizacion_id': current_user.organizacion_id,
                        'presupuesto_id': presupuesto.id,
                        'etapas': [e.get('slug') or e.get('nombre') for e in (resultado.get('etapas') or [])],
                        'total_antes': total_antes,
                        'total_despues': total_despues,
                        'superficie': float(superficie_decimal),
                        'tipo_calculo': tipo_calculo,
                    },
                )
            else:
                db.session.rollback()
                resultado['guardado'] = False
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Error persistiendo resultados de etapas IA en presupuesto')
            return jsonify({'ok': False, 'error': 'El cálculo se generó pero no pudimos guardarlo en el presupuesto.'}), 500

    current_app.logger.info(
        '🧠 IA etapas calculada',
        extra={
            'usuario_id': current_user.id,
            'organizacion_id': current_user.organizacion_id,
            'etapas_solicitadas': [e.get('slug') if isinstance(e, dict) else e for e in (etapa_payload or [])],
            'presupuesto_id': presupuesto_id,
        },
    )
    return jsonify(resultado)

@presupuestos_bp.route('/crear-desde-ia', methods=['POST'])
@login_required  
def crear_desde_ia():
    """Crea un presupuesto a partir de los resultados de la calculadora IA"""
    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'error': 'No tienes permisos para crear presupuestos'}), 403
    
    try:
        # Obtener datos del JSON enviado
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se recibieron datos'}), 400
        
        presupuesto_ia = data.get('presupuesto')
        observaciones = data.get('observaciones', '')
        datos_proyecto = data.get('datos_proyecto', {})
        
        if not presupuesto_ia:
            return jsonify({'error': 'Datos del presupuesto incompletos'}), 400

        currency_raw = datos_proyecto.get('currency') if isinstance(datos_proyecto, dict) else data.get('currency')
        try:
            currency, fx_snapshot = _resolve_currency_context(currency_raw)
        except Exception as exc:
            current_app.logger.exception('Error obteniendo tipo de cambio para crear presupuesto desde IA')
            return jsonify({'error': 'No se pudo obtener el tipo de cambio solicitado.'}), 500

        # NO CREAR OBRA AUTOMÁTICAMENTE - Solo guardar datos del proyecto
        # Los presupuestos quedan como "borrador" hasta que se confirmen explícitamente
        
        # Generar número de presupuesto único
        ultimo_numero = db.session.query(db.func.max(Presupuesto.numero)).scalar()
        if ultimo_numero and ultimo_numero.startswith('PRES-'):
            try:
                siguiente_num = int(ultimo_numero.split('-')[1]) + 1
            except:
                siguiente_num = 1
        else:
            siguiente_num = 1
        
        # Asegurar que el número sea único
        while True:
            numero = f"PRES-{siguiente_num:04d}"
            existe = Presupuesto.query.filter_by(numero=numero).first()
            if not existe:
                break
            siguiente_num += 1
        
        # Crear presupuesto base (SIN obra_id)
        nuevo_presupuesto = Presupuesto()
        nuevo_presupuesto.obra_id = None  # Sin obra asociada hasta confirmar
        nuevo_presupuesto.numero = numero
        nuevo_presupuesto.observaciones = f"Calculado con IA - {observaciones}"
        nuevo_presupuesto.iva_porcentaje = 21.0
        nuevo_presupuesto.estado = 'borrador'  # Borrador hasta que se confirme
        nuevo_presupuesto.confirmado_como_obra = False
        nuevo_presupuesto.datos_proyecto = json.dumps(datos_proyecto)  # Guardar datos para posterior conversión
        nuevo_presupuesto.organizacion_id = current_user.organizacion_id
        nuevo_presupuesto.currency = currency
        vigencia_config = datos_proyecto.get('vigencia_dias') if isinstance(datos_proyecto, dict) else None
        vigencia_dias = _parse_vigencia_dias(vigencia_config) if vigencia_config is not None else 30
        if vigencia_dias is None:
            vigencia_dias = 30
        nuevo_presupuesto.vigencia_dias = vigencia_dias
        nuevo_presupuesto.vigencia_bloqueada = True
        nuevo_presupuesto.asegurar_vigencia()

        db.session.add(nuevo_presupuesto)
        db.session.flush()  # Para obtener el ID

        try:
            nuevo_presupuesto.registrar_tipo_cambio(fx_snapshot)
        except AttributeError:
            pass
        
        # Agregar items de materiales
        materiales = presupuesto_ia.get('materiales', {})
        for material, cantidad in materiales.items():
            if cantidad > 0:
                # Mapear nombres técnicos a descripciones legibles expandidas
                descripciones = {
                    # Materiales estructurales
                    'ladrillos': 'Ladrillos comunes',
                    'cemento': 'Bolsas de cemento',
                    'cal': 'Cal hidratada',
                    'arena': 'Arena gruesa',
                    'piedra': 'Piedra partida',
                    'hierro_8': 'Hierro 8mm',
                    'hierro_10': 'Hierro 10mm', 
                    'hierro_12': 'Hierro 12mm',
                    
                    # Revestimientos y pisos
                    'ceramicos': 'Cerámicos esmaltados',
                    'porcelanato': 'Porcelanato rectificado',
                    'azulejos': 'Azulejos para baños',
                    
                    # Instalaciones
                    'cables_electricos': 'Cables eléctricos',
                    'caños_agua': 'Caños para agua',
                    'caños_cloacas': 'Caños cloacales',
                    
                    # Techado
                    'chapas': 'Chapas acanaladas',
                    'tejas': 'Tejas cerámicas',
                    'aislacion_termica': 'Aislación térmica',
                    
                    # Terminaciones
                    'yeso': 'Yeso para terminaciones',
                    'madera_estructural': 'Madera estructural',
                    'vidrios': 'Vidrios templados',
                    'aberturas_metal': 'Aberturas metálicas',
                    
                    # Impermeabilización
                    'membrana': 'Membrana asfáltica',
                    'pintura': 'Pintura látex interior',
                    'pintura_exterior': 'Pintura exterior',
                    'sellador': 'Sellador acrílico'
                }
                
                unidades = {
                    # Estructurales
                    'ladrillos': 'unidades',
                    'cemento': 'bolsas',
                    'cal': 'kg',
                    'arena': 'm³',
                    'piedra': 'm³',
                    'hierro_8': 'kg',
                    'hierro_10': 'kg',
                    'hierro_12': 'kg',
                    
                    # Revestimientos
                    'ceramicos': 'm²',
                    'porcelanato': 'm²',
                    'azulejos': 'm²',
                    
                    # Instalaciones
                    'cables_electricos': 'metros',
                    'caños_agua': 'metros',
                    'caños_cloacas': 'metros',
                    
                    # Techado
                    'chapas': 'm²',
                    'tejas': 'm²',
                    'aislacion_termica': 'm²',
                    
                    # Terminaciones
                    'yeso': 'kg',
                    'madera_estructural': 'm³',
                    'vidrios': 'm²',
                    'aberturas_metal': 'm²',
                    
                    # Impermeabilización
                    'membrana': 'm²',
                    'pintura': 'litros',
                    'pintura_exterior': 'litros',
                    'sellador': 'litros'
                }
                
                cantidad_dec = _quantize_quantity(_to_decimal(cantidad, '0'))
                item = ItemPresupuesto()
                item.presupuesto_id = nuevo_presupuesto.id
                item.tipo = 'material'
                item.descripcion = descripciones.get(material, material.title())
                item.unidad = unidades.get(material, 'unidades')
                item.cantidad = cantidad_dec
                item.precio_unitario = DECIMAL_ZERO
                item.total = DECIMAL_ZERO
                item.origen = 'ia'
                item.currency = currency
                item.price_unit_currency = DECIMAL_ZERO
                item.total_currency = DECIMAL_ZERO
                db.session.add(item)
        
        # Agregar equipos
        equipos = presupuesto_ia.get('equipos', {})
        for equipo, specs in equipos.items():
            # Manejar tanto diccionarios como valores simples
            if isinstance(specs, dict):
                cantidad = specs.get('cantidad', 0)
                dias_uso = specs.get('dias_uso', 0)
            else:
                # Fallback si no es un diccionario
                cantidad = 1
                dias_uso = 0
                
            if cantidad > 0:
                descripciones_equipos = {
                    'hormigonera': 'Alquiler Hormigonera',
                    'andamios': 'Alquiler Andamios',  
                    'carretilla': 'Carretilla',
                    'nivel_laser': 'Alquiler Nivel Láser',
                    'martillo_demoledor': 'Alquiler Martillo Demoledor',
                    'soldadora': 'Alquiler Soldadora',
                    'compresora': 'Alquiler Compresora',
                    'generador': 'Alquiler Generador',
                    'elevador': 'Alquiler Elevador',
                    'mezcladora': 'Alquiler Mezcladora'
                }
                
                item = ItemPresupuesto()
                item.presupuesto_id = nuevo_presupuesto.id
                item.tipo = 'equipo'
                
                # Descripción con días de uso si aplica
                base_desc = descripciones_equipos.get(equipo, equipo.replace('_', ' ').title())
                if dias_uso > 0:
                    item.descripcion = f"{base_desc} - {dias_uso} días"
                else:
                    item.descripcion = base_desc
                    
                item.unidad = 'días' if equipo in ['hormigonera', 'andamios', 'nivel_laser'] else 'unidades'
                item.cantidad = _quantize_quantity(_to_decimal(cantidad, '0'))
                item.precio_unitario = DECIMAL_ZERO
                item.total = DECIMAL_ZERO
                item.origen = 'ia'
                item.currency = currency
                item.price_unit_currency = DECIMAL_ZERO
                item.total_currency = DECIMAL_ZERO
                db.session.add(item)
        
        # Agregar herramientas
        herramientas = presupuesto_ia.get('herramientas', {})
        for herramienta, cantidad in herramientas.items():
            try:
                cantidad_dec = _quantize_quantity(_to_decimal(cantidad, '0')) if cantidad else DECIMAL_ZERO
                if cantidad_dec > DECIMAL_ZERO:
                    descripciones_herramientas = {
                        'palas': 'Palas',
                        'baldes': 'Baldes',
                        'fratacho': 'Fratacho',
                        'regla': 'Regla de albañil',
                        'llanas': 'Llanas',
                        'martillos': 'Martillos',
                        'serruchos': 'Serruchos',
                        'taladros': 'Taladros',
                        'nivel_burbuja': 'Nivel de burbuja',
                        'flexometros': 'Flexómetros',
                        'amoladoras': 'Amoladoras',
                        'pistola_calor': 'Pistola de calor',
                        'alicates': 'Alicates',
                        'destornilladores': 'Destornilladores',
                        'sierra_circular': 'Sierra circular',
                        'router': 'Router'
                    }
                    
                    item = ItemPresupuesto()
                    item.presupuesto_id = nuevo_presupuesto.id
                    item.tipo = 'herramienta'
                    item.descripcion = descripciones_herramientas.get(herramienta, herramienta.replace('_', ' ').title())
                    item.unidad = 'unidades'
                    item.cantidad = cantidad_dec
                    item.precio_unitario = DECIMAL_ZERO
                    item.total = DECIMAL_ZERO
                    item.origen = 'ia'
                    item.currency = currency
                    item.price_unit_currency = DECIMAL_ZERO
                    item.total_currency = DECIMAL_ZERO
                    db.session.add(item)
            except (ValueError, TypeError):
                # Omitir herramientas con valores inválidos
                continue
        
        db.session.commit()
        
        return jsonify({
            'exito': True,
            'presupuesto_id': nuevo_presupuesto.id,
            'numero': numero,
            'mensaje': 'Presupuesto creado como borrador. Podrás convertirlo en obra desde la lista de presupuestos.',
            'redirect_url': url_for('presupuestos.detalle', id=nuevo_presupuesto.id)
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error creando presupuesto: {str(e)}'}), 500

@presupuestos_bp.route('/exportar-excel-ia', methods=['POST'])
@login_required
def exportar_excel_ia():
    """Exporta los resultados de la calculadora IA a Excel"""
    if not current_user.puede_acceder_modulo('presupuestos'):
        return jsonify({'error': 'Sin permisos'}), 403

    if not XLSXWRITER_AVAILABLE:
        return (
            jsonify({
                'error': "La exportación a Excel requiere la librería xlsxwriter. Instálala con 'pip install xlsxwriter'."
            }),
            500,
        )

    try:
        data = request.get_json()
        if not data or not data.get('presupuesto'):
            return jsonify({'error': 'No se recibieron datos'}), 400
        
        presupuesto = data['presupuesto']
        
        # Crear archivo Excel en memoria
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        
        # Formatos
        header_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'bg_color': '#2E5BBA',
            'color': 'white',
            'align': 'center'
        })
        
        subheader_format = workbook.add_format({
            'bold': True,
            'font_size': 12,
            'bg_color': '#F0F0F0'
        })
        
        number_format = workbook.add_format({'num_format': '#,##0.00'})
        
        # Hoja principal
        worksheet = workbook.add_worksheet('Presupuesto IA')
        
        # Encabezado
        worksheet.merge_range('A1:E1', 'PRESUPUESTO CALCULADO CON IA', header_format)
        
        row = 3
        
        # Información del proyecto
        metadata = presupuesto.get('metadata', {})
        worksheet.write(row, 0, 'Superficie:', subheader_format)
        worksheet.write(row, 1, f"{metadata.get('superficie_m2', 0)} m²")
        row += 1
        
        worksheet.write(row, 0, 'Tipo de Construcción:', subheader_format)
        worksheet.write(row, 1, metadata.get('tipo_construccion', 'N/A'))
        row += 2
        
        # Materiales
        worksheet.write(row, 0, 'MATERIALES', subheader_format)
        row += 1
        
        worksheet.write(row, 0, 'Material', subheader_format)
        worksheet.write(row, 1, 'Cantidad', subheader_format)
        worksheet.write(row, 2, 'Unidad', subheader_format)
        row += 1
        
        materiales = presupuesto.get('materiales', {})
        unidades_map = {
            'ladrillos': 'unidades', 'cemento': 'bolsas', 'cal': 'kg',
            'arena': 'm³', 'piedra': 'm³', 'hierro_8': 'kg',
            'hierro_10': 'kg', 'hierro_12': 'kg', 'membrana': 'm²',
            'pintura': 'litros'
        }
        
        for material, cantidad in materiales.items():
            worksheet.write(row, 0, material.replace('_', ' ').title())
            worksheet.write(row, 1, cantidad, number_format)
            worksheet.write(row, 2, unidades_map.get(material, 'unidades'))
            row += 1
        
        row += 1
        
        # Equipos
        worksheet.write(row, 0, 'EQUIPOS Y MAQUINARIAS', subheader_format)
        row += 1
        
        worksheet.write(row, 0, 'Equipo', subheader_format)
        worksheet.write(row, 1, 'Cantidad', subheader_format)
        worksheet.write(row, 2, 'Días de Uso', subheader_format)
        row += 1
        
        equipos = presupuesto.get('equipos', {})
        for equipo, specs in equipos.items():
            if specs.get('cantidad', 0) > 0:
                worksheet.write(row, 0, equipo.replace('_', ' ').title())
                worksheet.write(row, 1, specs.get('cantidad', 0))
                worksheet.write(row, 2, specs.get('dias_uso', 0))
                row += 1
        
        workbook.close()
        output.seek(0)
        
        # Crear respuesta
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename=presupuesto_ia_{dt.datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
        
        return response
        
    except Exception as e:
        return jsonify({'error': f'Error exportando Excel: {str(e)}'}), 500

@presupuestos_bp.route('/<int:id>')
@login_required
def detalle(id):
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para ver presupuestos.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None)
    ).first_or_404()
    items = presupuesto.items.all()
    
    # Agrupar items por tipo
    materiales = [item for item in items if item.tipo == 'material']
    mano_obra = [item for item in items if item.tipo == 'mano_obra']
    equipos = [item for item in items if item.tipo == 'equipo']
    herramientas = [item for item in items if item.tipo == 'herramienta']

    ia_materiales = [item for item in materiales if item.origen == 'ia']
    ia_mano_obra = [item for item in mano_obra if item.origen == 'ia']
    ia_equipos = [item for item in equipos if item.origen == 'ia']
    ia_herramientas = [item for item in herramientas if item.origen == 'ia']

    totales_ia = {
        'materiales': _sumar_totales(ia_materiales),
        'mano_obra': _sumar_totales(ia_mano_obra),
        'equipos': _sumar_totales(ia_equipos),
        'herramientas': _sumar_totales(ia_herramientas),
    }
    totales_ia['general'] = _quantize_currency(
        totales_ia['materiales'] + totales_ia['mano_obra'] + totales_ia['equipos'] + totales_ia['herramientas']
    )

    g.currency_context = presupuesto.currency

    return render_template('presupuestos/detalle.html',
                         presupuesto=presupuesto,
                         materiales=materiales,
                         mano_obra=mano_obra,
                         equipos=equipos,
                         herramientas=herramientas,
                         ia_materiales=ia_materiales,
                         ia_mano_obra=ia_mano_obra,
                         ia_equipos=ia_equipos,
                         ia_herramientas=ia_herramientas,
                         totales_ia=totales_ia)

@presupuestos_bp.route('/<int:id>/item', methods=['POST'])
@login_required
def agregar_item(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para agregar items.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None)
    ).first_or_404()
    
    if presupuesto.estado != 'borrador':
        flash('Solo se pueden agregar items a presupuestos en borrador.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    tipo = request.form.get('tipo')
    descripcion = request.form.get('descripcion')
    unidad = request.form.get('unidad')
    cantidad = request.form.get('cantidad')
    precio_unitario = request.form.get('precio_unitario')
    
    if not all([tipo, descripcion, unidad, cantidad, precio_unitario]):
        flash('Completa todos los campos.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    try:
        cantidad_dec = _quantize_quantity(_to_decimal(cantidad, '0'))
        precio_unitario_dec = _quantize_currency(_to_decimal(precio_unitario, '0'))
        total_dec = _quantize_currency(cantidad_dec * precio_unitario_dec)
    except (InvalidOperation, ValueError, TypeError):
        flash('Cantidad y precio deben ser números válidos.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))

    nuevo_item = ItemPresupuesto()
    nuevo_item.presupuesto_id = id
    nuevo_item.tipo = tipo
    nuevo_item.descripcion = descripcion
    nuevo_item.unidad = unidad
    nuevo_item.cantidad = cantidad_dec
    nuevo_item.precio_unitario = precio_unitario_dec
    nuevo_item.total = total_dec
    nuevo_item.origen = 'manual'
    nuevo_item.currency = presupuesto.currency or 'ARS'
    nuevo_item.price_unit_currency = precio_unitario_dec
    nuevo_item.total_currency = total_dec

    try:
        db.session.add(nuevo_item)
        presupuesto.calcular_totales()
        db.session.commit()
        flash('Item agregado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al agregar el item.', 'danger')
    
    return redirect(url_for('presupuestos.detalle', id=id))

@presupuestos_bp.route('/item/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_item(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para eliminar items.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    item = ItemPresupuesto.query.get_or_404(id)
    presupuesto = item.presupuesto

    if presupuesto.organizacion_id != current_user.organizacion_id or presupuesto.deleted_at is not None:
        flash('No tienes permisos para eliminar este item.', 'danger')
        return redirect(url_for('presupuestos.lista'))
    
    if presupuesto.estado != 'borrador':
        flash('Solo se pueden eliminar items de presupuestos en borrador.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=presupuesto.id))
    
    try:
        db.session.delete(item)
        presupuesto.calcular_totales()
        db.session.commit()
        flash('Item eliminado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al eliminar el item.', 'danger')
    
    return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

@presupuestos_bp.route('/<int:id>/estado', methods=['POST'])
@login_required
def cambiar_estado(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para cambiar el estado.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None)
    ).first_or_404()

    if presupuesto.estado in ['perdido', 'eliminado']:
        flash('No puedes modificar el estado de un presupuesto archivado.', 'warning')
        return redirect(url_for('presupuestos.detalle', id=id))
    nuevo_estado = request.form.get('estado')
    
    if nuevo_estado not in ['borrador', 'enviado', 'aprobado', 'rechazado']:
        flash('Estado no válido.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    presupuesto.estado = nuevo_estado
    
    try:
        db.session.commit()
        flash(f'Estado cambiado a {nuevo_estado} exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al cambiar el estado.', 'danger')
    
    return redirect(url_for('presupuestos.detalle', id=id))

@presupuestos_bp.route('/<int:id>/pdf')
@login_required
def generar_pdf(id):
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para generar PDFs.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    if not REPORTLAB_AVAILABLE:
        flash(
            "La generación de PDF requiere la librería reportlab. Instálala ejecutando 'pip install reportlab'.",
            'danger'
        )
        return redirect(url_for('presupuestos.detalle', id=id))

    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None)
    ).first_or_404()
    items = presupuesto.items.all()

    # Crear buffer para el PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    
    # Estilos
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    # Título
    story.append(Paragraph('PRESUPUESTO DE OBRA', title_style))
    story.append(Spacer(1, 20))
    
    # Información del presupuesto
    info_data = [
        ['Número:', presupuesto.numero],
        ['Fecha:', presupuesto.fecha.strftime('%d/%m/%Y')],
        ['Obra:', presupuesto.obra.nombre],
        ['Cliente:', presupuesto.obra.cliente],
        ['Estado:', presupuesto.estado.upper()]
    ]
    
    info_table = Table(info_data, colWidths=[2*inch, 4*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    story.append(info_table)
    story.append(Spacer(1, 30))
    
    # Tabla de items
    if items:
        # Encabezados
        data = [['Descripción', 'Unidad', 'Cantidad', 'P. Unit.', 'Total']]
        
        # Materiales
        materiales = [item for item in items if item.tipo == 'material']
        if materiales:
            data.append(['MATERIALES', '', '', '', ''])
            for item in materiales:
                data.append([
                    item.descripcion,
                    item.unidad,
                    f"{item.cantidad:.2f}",
                    f"${item.precio_unitario:.2f}",
                    f"${item.total:.2f}"
                ])
            data.append(['', '', '', 'Subtotal Materiales:', f"${presupuesto.subtotal_materiales:.2f}"])
        
        # Mano de obra
        mano_obra = [item for item in items if item.tipo == 'mano_obra']
        if mano_obra:
            data.append(['', '', '', '', ''])
            data.append(['MANO DE OBRA', '', '', '', ''])
            for item in mano_obra:
                data.append([
                    item.descripcion,
                    item.unidad,
                    f"{item.cantidad:.2f}",
                    f"${item.precio_unitario:.2f}",
                    f"${item.total:.2f}"
                ])
            data.append(['', '', '', 'Subtotal Mano de Obra:', f"${presupuesto.subtotal_mano_obra:.2f}"])
        
        # Equipos
        equipos = [item for item in items if item.tipo == 'equipo']
        if equipos:
            data.append(['', '', '', '', ''])
            data.append(['EQUIPOS', '', '', '', ''])
            for item in equipos:
                data.append([
                    item.descripcion,
                    item.unidad,
                    f"{item.cantidad:.2f}",
                    f"${item.precio_unitario:.2f}",
                    f"${item.total:.2f}"
                ])
            data.append(['', '', '', 'Subtotal Equipos:', f"${presupuesto.subtotal_equipos:.2f}"])
        
        # Totales
        data.append(['', '', '', '', ''])
        data.append(['', '', '', 'TOTAL SIN IVA:', f"${presupuesto.total_sin_iva:.2f}"])
        data.append(['', '', '', f'IVA ({presupuesto.iva_porcentaje}%):', f"${(presupuesto.total_con_iva - presupuesto.total_sin_iva):.2f}"])
        data.append(['', '', '', 'TOTAL CON IVA:', f"${presupuesto.total_con_iva:.2f}"])
        
        table = Table(data, colWidths=[3*inch, 0.8*inch, 0.8*inch, 1.2*inch, 1.2*inch])
        table.setStyle(TableStyle([
            # Encabezado
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            
            # Cuerpo
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            
            # Subtotales y totales en negrita
            ('FONTNAME', (3, -4), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        story.append(table)
    
    # Observaciones
    if presupuesto.observaciones:
        story.append(Spacer(1, 30))
        story.append(Paragraph('Observaciones:', styles['Heading2']))
        story.append(Paragraph(presupuesto.observaciones, styles['Normal']))
    
    # Generar PDF
    doc.build(story)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=presupuesto_{presupuesto.numero}.pdf'
    
    return response

@presupuestos_bp.route('/<int:id>/editar-obra', methods=['POST'])
@login_required
def editar_obra(id):
    """Editar información de la obra asociada al presupuesto"""
    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'error': 'Sin permisos'}), 403

    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None)
    ).first_or_404()

    if presupuesto.estado != 'borrador':
        return jsonify({'error': 'Solo puedes editar presupuestos en borrador.'}), 400

    payload = request.get_json(silent=True) or request.form.to_dict()
    if not payload:
        return jsonify({'error': 'No se recibieron datos para actualizar la obra.'}), 400

    obra: Optional[Obra] = None
    new_obra_created = False

    raw_obra_id = payload.get('obra_id') or presupuesto.obra_id
    if raw_obra_id:
        try:
            obra_id = int(raw_obra_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Identificador de obra inválido.'}), 400

        obra = Obra.query.filter_by(id=obra_id, organizacion_id=current_user.organizacion_id).first()
        if obra is None:
            return jsonify({'error': 'Obra asociada no encontrada.'}), 404
    else:
        obra = presupuesto.obra

    if obra and obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'error': 'No tienes permisos para modificar esta obra.'}), 403

    if obra is None:
        obra = Obra(
            organizacion_id=current_user.organizacion_id,
            estado='planificacion',
            cliente='Cliente sin especificar'
        )
        presupuesto.obra = obra
        db.session.add(obra)
        new_obra_created = True

    try:
        if 'nombre' in payload:
            nombre = _clean_text(payload.get('nombre'))
            if not nombre:
                return jsonify({'error': 'El nombre de la obra no puede estar vacío.'}), 400
            obra.nombre = nombre
        elif new_obra_created:
            return jsonify({'error': 'El nombre de la obra es obligatorio.'}), 400

        if 'cliente' in payload:
            cliente = _clean_text(payload.get('cliente')) or 'Cliente sin especificar'
            obra.cliente = cliente
        elif new_obra_created and not obra.cliente:
            obra.cliente = 'Cliente sin especificar'

        for campo in ('descripcion', 'direccion'):
            if campo in payload:
                setattr(obra, campo, _clean_text(payload.get(campo)))

        if 'fecha_inicio' in payload:
            parsed = _parse_date(payload.get('fecha_inicio'))
            if payload.get('fecha_inicio') and parsed is None:
                return jsonify({'error': 'Formato de fecha de inicio inválido.'}), 400
            obra.fecha_inicio = parsed

        if 'fecha_fin_estimada' in payload:
            parsed = _parse_date(payload.get('fecha_fin_estimada'))
            if payload.get('fecha_fin_estimada') and parsed is None:
                return jsonify({'error': 'Formato de fecha de finalización inválido.'}), 400
            obra.fecha_fin_estimada = parsed

        if 'presupuesto_total' in payload:
            bruto_presupuesto = payload.get('presupuesto_total')
            if bruto_presupuesto in (None, ''):
                obra.presupuesto_total = None
            else:
                try:
                    obra.presupuesto_total = _quantize_currency(_to_decimal(bruto_presupuesto, '0'))
                except (InvalidOperation, ValueError, TypeError):
                    return jsonify({'error': 'El presupuesto total debe ser numérico.'}), 400

        db.session.commit()
        return jsonify({
            'exito': True,
            'mensaje': 'Obra actualizada correctamente',
            'obra_id': obra.id
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error actualizando la obra asociada al presupuesto %s', id)
        return jsonify({'error': f'Error actualizando obra: {str(e)}'}), 500

@presupuestos_bp.route('/item/<int:item_id>/editar', methods=['POST'])
@login_required
def editar_item(item_id):
    """Editar un item específico del presupuesto"""
    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'error': 'Sin permisos'}), 403
    
    item = ItemPresupuesto.query.get_or_404(item_id)
    presupuesto = item.presupuesto

    if presupuesto.organizacion_id != current_user.organizacion_id or presupuesto.deleted_at is not None:
        return jsonify({'error': 'No tienes permisos para editar este item.'}), 403

    if presupuesto.estado != 'borrador':
        return jsonify({'error': 'Solo puedes editar items en presupuestos en borrador.'}), 400
    
    data = request.get_json()
    
    try:
        # Actualizar campos del item
        if 'descripcion' in data:
            item.descripcion = data['descripcion']
        if 'unidad' in data:
            item.unidad = data['unidad']
        if 'cantidad' in data:
            item.cantidad = _quantize_quantity(_to_decimal(data['cantidad'], '0'))
        if 'precio_unitario' in data:
            item.precio_unitario = _quantize_currency(_to_decimal(data['precio_unitario'], '0'))

        cantidad_dec = _to_decimal(item.cantidad, '0')
        precio_unitario_dec = _to_decimal(item.precio_unitario, '0')

        # Recalcular total
        item.total = _quantize_currency(cantidad_dec * precio_unitario_dec)
        
        # Recalcular totales del presupuesto
        presupuesto.calcular_totales()
        
        db.session.commit()
        return jsonify({
            'exito': True, 
            'mensaje': 'Item actualizado correctamente',
            'nuevo_total': float(item.total),
            'subtotal_materiales': float(presupuesto.subtotal_materiales),
            'subtotal_mano_obra': float(presupuesto.subtotal_mano_obra),
            'subtotal_equipos': float(presupuesto.subtotal_equipos),
            'total_sin_iva': float(presupuesto.total_sin_iva),
            'total_con_iva': float(presupuesto.total_con_iva)
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error actualizando item: {str(e)}'}), 500


@presupuestos_bp.route('/<int:id>/confirmar-obra', methods=['POST'])
@login_required
def confirmar_como_obra(id):
    """Convierte un presupuesto borrador en una obra confirmada."""

    wants_json = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    payload = request.get_json(silent=True) if request.is_json else None
    payload = payload or request.form

    crear_tareas = _to_bool(payload.get('crear_tareas'), True)
    normalizar_slugs = _to_bool(payload.get('normalizar_slugs'), True)
    notificar = _to_bool(payload.get('notificar'), True)
    trigger_source = 'list_modal' if wants_json else 'detail_view'

    puede_acceder = getattr(current_user, 'puede_acceder_modulo', lambda modulo: True)
    if not puede_acceder('presupuestos') or getattr(current_user, 'rol', None) not in ['administrador', 'tecnico']:
        mensaje = 'No tienes permisos para confirmar obras.'
        if wants_json:
            return jsonify({'error': mensaje}), 403
        flash(mensaje, 'danger')
        return redirect(url_for('presupuestos.lista'))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        mensaje = 'No se pudo determinar la organización activa.'
        if wants_json:
            return jsonify({'error': mensaje}), 400
        flash(mensaje, 'danger')
        return redirect(url_for('presupuestos.lista'))

    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == org_id
    ).first_or_404()

    if presupuesto.deleted_at is not None:
        mensaje = 'No puedes confirmar un presupuesto eliminado.'
        if wants_json:
            return jsonify({'error': mensaje}), 400
        flash(mensaje, 'danger')
        return redirect(url_for('presupuestos.lista'))

    if presupuesto.confirmado_como_obra:
        obra_url = url_for('obras.detalle', id=presupuesto.obra_id) if presupuesto.obra_id else None
        mensaje = 'Este presupuesto ya fue confirmado como obra.'
        if wants_json:
            return jsonify({
                'status': 'already_confirmed',
                'message': mensaje,
                'obra_id': presupuesto.obra_id,
                'obra_url': obra_url,
                'presupuesto_estado': presupuesto.estado
            })
        flash(mensaje, 'warning')
        return redirect(obra_url or url_for('presupuestos.detalle', id=id))

    if presupuesto.estado != 'borrador':
        mensaje = 'Solo los presupuestos en borrador pueden confirmarse como obra.'
        if wants_json:
            return jsonify({'error': mensaje}), 400
        flash(mensaje, 'warning')
        return redirect(url_for('presupuestos.detalle', id=id))

    datos_proyecto: dict[str, Any] = {}
    if presupuesto.datos_proyecto:
        try:
            datos_proyecto = json.loads(presupuesto.datos_proyecto)
        except json.JSONDecodeError:
            datos_proyecto = {}

    cliente = None
    if presupuesto.obra:
        cliente = presupuesto.obra.cliente
    elif isinstance(datos_proyecto, dict):
        cliente = datos_proyecto.get('cliente')
    if not cliente:
        mensaje = 'Completa los datos del cliente antes de confirmar el presupuesto.'
        if wants_json:
            return jsonify({'error': mensaje}), 400
        flash(mensaje, 'warning')
        return redirect(url_for('presupuestos.detalle', id=id))

    ubicacion_texto = presupuesto.ubicacion_texto
    if not ubicacion_texto and isinstance(datos_proyecto, dict):
        ubicacion_texto = datos_proyecto.get('ubicacion')
    if not ubicacion_texto:
        mensaje = 'Debes indicar una ubicación válida antes de confirmar el presupuesto.'
        if wants_json:
            return jsonify({'error': mensaje}), 400
        flash(mensaje, 'warning')
        return redirect(url_for('presupuestos.detalle', id=id))

    if presupuesto.currency not in ALLOWED_CURRENCIES:
        mensaje = 'La moneda seleccionada no es compatible con la conversión a obra.'
        if wants_json:
            return jsonify({'error': mensaje}), 400
        flash(mensaje, 'warning')
        return redirect(url_for('presupuestos.detalle', id=id))

    if presupuesto.currency != 'ARS' and not presupuesto.tasa_usd_venta:
        mensaje = 'No se encontró el tipo de cambio aplicado para este presupuesto. Vuelve a calcular antes de confirmar.'
        if wants_json:
            return jsonify({'error': mensaje}), 400
        flash(mensaje, 'warning')
        return redirect(url_for('presupuestos.detalle', id=id))

    if presupuesto.indice_cac_valor is None:
        mensaje = 'Debes aplicar el índice CAC vigente antes de confirmar el presupuesto.'
        if wants_json:
            return jsonify({'error': mensaje}), 400
        flash(mensaje, 'warning')
        return redirect(url_for('presupuestos.detalle', id=id))

    nueva_obra = None
    try:
        nombre_obra = None
        if isinstance(datos_proyecto, dict):
            nombre_obra = datos_proyecto.get('nombre')
        if not nombre_obra:
            nombre_obra = f'Obra desde Presupuesto {presupuesto.numero}'

        nueva_obra = Obra()
        nueva_obra.nombre = nombre_obra
        nueva_obra.cliente = cliente
        if isinstance(datos_proyecto, dict):
            descripcion = (
                f"Superficie: {datos_proyecto.get('superficie', 0)}m² - "
                f"{datos_proyecto.get('ubicacion', 'Ubicación no especificada')} - "
                f"Tipo: {datos_proyecto.get('tipo_construccion', 'Estándar')}"
            )
        else:
            descripcion = f'Obra creada a partir del presupuesto {presupuesto.numero}'
        nueva_obra.descripcion = descripcion
        nueva_obra.direccion = presupuesto.ubicacion_texto or ubicacion_texto or 'Por especificar'
        nueva_obra.direccion_normalizada = presupuesto.ubicacion_normalizada or (
            datos_proyecto.get('ubicacion_normalizada') if isinstance(datos_proyecto, dict) else None
        )
        nueva_obra.estado = 'planificacion'
        nueva_obra.presupuesto_total = _quantize_currency(_to_decimal(presupuesto.total_con_iva, '0'))
        nueva_obra.organizacion_id = org_id

        lat_decimal = presupuesto.geo_latitud
        if lat_decimal is None and isinstance(datos_proyecto, dict):
            lat_decimal = datos_proyecto.get('latitud')
        lng_decimal = presupuesto.geo_longitud
        if lng_decimal is None and isinstance(datos_proyecto, dict):
            lng_decimal = datos_proyecto.get('longitud')

        if lat_decimal is not None and lng_decimal is not None:
            try:
                nueva_obra.latitud = _quantize_coord(lat_decimal)
                nueva_obra.longitud = _quantize_coord(lng_decimal)
            except Exception:
                nueva_obra.latitud = _quantize_coord(lat_decimal)
                nueva_obra.longitud = _quantize_coord(lng_decimal)
        else:
            resolved = resolve_geocode(ubicacion_texto)
            if resolved:
                nueva_obra.latitud = _quantize_coord(resolved.get('lat'))
                nueva_obra.longitud = _quantize_coord(resolved.get('lng'))
                nueva_obra.geocode_place_id = resolved.get('place_id')
                nueva_obra.geocode_provider = resolved.get('provider')
                nueva_obra.geocode_status = resolved.get('status') or 'ok'
                raw_payload = resolved.get('raw')
                nueva_obra.geocode_raw = json.dumps(raw_payload) if raw_payload else None
                nueva_obra.geocode_actualizado = dt.datetime.utcnow()

        nueva_obra.geocode_place_id = presupuesto.geocode_place_id or nueva_obra.geocode_place_id
        nueva_obra.geocode_provider = presupuesto.geocode_provider or nueva_obra.geocode_provider
        nueva_obra.geocode_status = presupuesto.geocode_status or nueva_obra.geocode_status
        nueva_obra.geocode_raw = presupuesto.geocode_raw or nueva_obra.geocode_raw
        if presupuesto.geocode_actualizado:
            nueva_obra.geocode_actualizado = presupuesto.geocode_actualizado

        db.session.add(nueva_obra)
        db.session.flush()

        presupuesto.obra_id = nueva_obra.id
        presupuesto.confirmado_como_obra = True
        presupuesto.estado = 'convertido'

        etapas_existentes = EtapaObra.query.filter_by(obra_id=nueva_obra.id).count()

        if etapas_existentes == 0:
            raw_etapas = []
            if isinstance(datos_proyecto, dict):
                raw_etapas = datos_proyecto.get('etapas') or []

            etapas_config = []
            for etapa in raw_etapas:
                if not isinstance(etapa, dict):
                    continue
                nombre_etapa = (etapa.get('nombre') or '').strip()
                if not nombre_etapa:
                    continue
                descripcion_etapa = (etapa.get('descripcion') or '').strip()
                slug_original = etapa.get('slug') or nombre_etapa
                slug_etapa = slugify_etapa(slug_original) if normalizar_slugs else slug_original.strip()
                etapas_config.append({
                    'nombre': nombre_etapa,
                    'descripcion': descripcion_etapa,
                    'orden': etapa.get('orden'),
                    'slug': slug_etapa
                })

            if not etapas_config:
                etapas_config = [
                    {'nombre': 'Excavación', 'descripcion': 'Preparación del terreno y excavaciones', 'orden': 1},
                    {'nombre': 'Fundaciones', 'descripcion': 'Construcción de fundaciones y bases', 'orden': 2},
                    {'nombre': 'Estructura', 'descripcion': 'Construcción de estructura principal', 'orden': 3},
                    {'nombre': 'Mampostería', 'descripcion': 'Construcción de muros y paredes', 'orden': 4},
                    {'nombre': 'Techos', 'descripcion': 'Construcción de techos y cubiertas', 'orden': 5},
                    {'nombre': 'Instalaciones', 'descripcion': 'Instalaciones eléctricas, sanitarias y gas', 'orden': 6},
                    {'nombre': 'Terminaciones', 'descripcion': 'Acabados y terminaciones finales', 'orden': 7}
                ]

            slugs_creados = set()
            for idx, etapa_data in enumerate(etapas_config, start=1):
                nombre = (etapa_data.get('nombre') or '').strip() or f'Etapa {idx}'
                descripcion = etapa_data.get('descripcion') or ''
                try:
                    orden = int(etapa_data.get('orden') or idx)
                except (TypeError, ValueError):
                    orden = idx
                slug_fuente = etapa_data.get('slug') or nombre
                slug = slugify_etapa(slug_fuente) if normalizar_slugs else slug_fuente.strip()
                if slug in slugs_creados:
                    continue
                slugs_creados.add(slug)

                nueva_etapa = EtapaObra(
                    obra_id=nueva_obra.id,
                    nombre=nombre,
                    descripcion=descripcion,
                    orden=orden,
                    estado='pendiente'
                )

                db.session.add(nueva_etapa)
                db.session.flush()

                creadas = 0
                if crear_tareas:
                    creadas = seed_tareas_para_etapa(
                        nueva_etapa,
                        auto_commit=False,
                        slug=slug,
                    ) or 0
                if not crear_tareas or creadas == 0:
                    db.session.add(TareaEtapa(
                        etapa_id=nueva_etapa.id,
                        nombre=f'Tarea inicial de {nombre}',
                        descripcion='Tarea generada automáticamente al confirmar el presupuesto.',
                        estado='pendiente'
                    ))

                etapa_data['slug'] = slug

            if isinstance(datos_proyecto, dict):
                datos_proyecto['etapas'] = etapas_config
                presupuesto.datos_proyecto = json.dumps(datos_proyecto, default=str)

        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Error confirmando presupuesto %s: %s', id, exc)
        mensaje = f'Error al confirmar obra: {str(exc)}'
        if wants_json:
            return jsonify({'error': mensaje}), 500
        flash(mensaje, 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))

    obra_creada_id = nueva_obra.id if nueva_obra else None
    obra_nombre = nueva_obra.nombre if nueva_obra else ''
    estado_respuesta = presupuesto.estado

    _registrar_evento_confirmacion(
        org_id=org_id,
        obra_id=obra_creada_id,
        presupuesto_id=presupuesto.id,
        usuario_id=getattr(current_user, 'id', None),
        trigger=trigger_source,
    )

    if notificar:
        current_app.logger.info(
            'Confirmación de presupuesto %s solicitó notificación por email (pendiente de implementación).',
            presupuesto.numero
        )

    if wants_json:
        return jsonify({
            'status': 'ok',
            'message': 'Obra creada correctamente.',
            'obra_id': obra_creada_id,
            'obra_url': url_for('obras.detalle', id=obra_creada_id) if obra_creada_id else None,
            'presupuesto_estado': estado_respuesta,
            'trigger': trigger_source
        })

    flash(f'¡Presupuesto convertido exitosamente en obra "{obra_nombre}"!', 'success')
    return redirect(url_for('obras.detalle', id=obra_creada_id))
@presupuestos_bp.route('/<int:id>/perder', methods=['POST'])
@login_required
def marcar_presupuesto_perdido(id: int):
    """Marca un presupuesto como perdido y registra el motivo."""

    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'error': 'No tienes permisos para modificar presupuestos.'}), 403

    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None)
    ).first_or_404()

    if presupuesto.estado != 'borrador':
        return jsonify({'error': 'Solo los presupuestos en borrador pueden marcarse como perdidos.'}), 400

    data = request.get_json(silent=True) or request.form
    motivo_principal = _clean_text(data.get('motivo')) if data else None
    detalle = _clean_text(data.get('detalle')) if data else None

    if not motivo_principal and not detalle:
        return jsonify({'error': 'Indica al menos un motivo para registrar el cambio.'}), 400

    if motivo_principal and detalle:
        motivo = f"{motivo_principal} - {detalle}"
    else:
        motivo = motivo_principal or detalle

    presupuesto.estado = 'perdido'
    presupuesto.perdido_motivo = motivo
    presupuesto.perdido_fecha = dt.datetime.utcnow()
    presupuesto.confirmado_como_obra = False

    try:
        db.session.commit()
        actor = getattr(current_user, 'email', None) or str(getattr(current_user, 'id', 'desconocido'))
        current_app.logger.info(
            'Presupuesto %s marcado como perdido por %s',
            presupuesto.numero,
            actor
        )
        return jsonify({'mensaje': 'Presupuesto archivado como perdido.'})
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error marcando presupuesto %s como perdido', id)
        return jsonify({'error': 'No se pudo actualizar el presupuesto.'}), 500


@presupuestos_bp.route('/<int:id>/restaurar', methods=['POST'])
@login_required
def restaurar_presupuesto(id: int):
    """Restaura un presupuesto perdido a estado borrador."""

    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'error': 'No tienes permisos para modificar presupuestos.'}), 403

    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None)
    ).first_or_404()

    if presupuesto.estado != 'perdido':
        return jsonify({'error': 'Solo los presupuestos perdidos pueden restaurarse.'}), 400

    presupuesto.estado = 'borrador'
    presupuesto.perdido_fecha = None
    presupuesto.perdido_motivo = None

    try:
        db.session.commit()
        actor = getattr(current_user, 'email', None) or str(getattr(current_user, 'id', 'desconocido'))
        current_app.logger.info(
            'Presupuesto %s restaurado a borrador por %s',
            presupuesto.numero,
            actor
        )
        return jsonify({'mensaje': 'Presupuesto restaurado a borrador.'})
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error restaurando presupuesto %s', id)
        return jsonify({'error': 'No se pudo restaurar el presupuesto.'}), 500


@presupuestos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_presupuesto(id: int):
    """Realiza un soft-delete del presupuesto seleccionado."""

    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol != 'administrador':
        return jsonify({'error': 'Solo los administradores pueden eliminar presupuestos.'}), 403

    presupuesto = Presupuesto.query.filter(
        Presupuesto.id == id,
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.deleted_at.is_(None)
    ).first_or_404()

    if presupuesto.estado not in ['borrador', 'perdido']:
        return jsonify({'error': 'Solo los presupuestos en borrador o perdidos pueden eliminarse.'}), 400

    presupuesto.estado = 'eliminado'
    presupuesto.deleted_at = dt.datetime.utcnow()

    try:
        db.session.commit()
        actor = getattr(current_user, 'email', None) or str(getattr(current_user, 'id', 'desconocido'))
        current_app.logger.info(
            'Presupuesto %s eliminado por %s',
            presupuesto.numero,
            actor
        )
        return jsonify({'mensaje': 'Presupuesto eliminado correctamente.'})
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error eliminando presupuesto %s', id)
        return jsonify({'error': 'No se pudo eliminar el presupuesto.'}), 500


@presupuestos_bp.route("/guardar", methods=["POST"])
@login_required
def guardar_presupuesto():
    """Guarda presupuesto con opción de crear obra nueva o usar existente"""
    if not current_user.puede_acceder_modulo('presupuestos'):
        return jsonify({'error': 'Sin permisos'}), 403
    
    data = request.form or request.json

    obra_id = data.get("obra_id")  # id si seleccionó obra existente
    crear_nueva = data.get("crear_nueva_obra") == "1"
    
    try:
        if crear_nueva:
            # Crear nueva obra con los datos del formulario
            obra = Obra(
                nombre = data.get("obra_nombre") or "Obra sin nombre",
                organizacion_id = current_user.organizacion_id,  # Usar organizacion_id del sistema actual
                cliente_nombre = data.get("cliente_nombre"),
                cliente_email  = data.get("cliente_email"),
                cliente_telefono = data.get("cliente_telefono"),
                direccion = data.get("direccion"),
                ciudad    = data.get("ciudad"),
                provincia = data.get("provincia"),
                pais      = data.get("pais") or "Argentina",
                codigo_postal = data.get("codigo_postal"),
                referencia = data.get("referencia"),
                notas = data.get("obra_notas"),
                estado = 'planificacion'
            )
            db.session.add(obra)
            db.session.flush()   # obtiene obra.id
            obra_id = obra.id
        else:
            obra = Obra.query.get(obra_id) if obra_id else None

        # Generar número de presupuesto único
        ultimo_numero = db.session.query(db.func.max(Presupuesto.numero)).scalar()
        if ultimo_numero and ultimo_numero.startswith('PRES-'):
            try:
                siguiente_num = int(ultimo_numero.split('-')[1]) + 1
            except:
                siguiente_num = 1
        else:
            siguiente_num = 1

        # Asegurar que el número sea único
        while True:
            numero = f"PRES-{siguiente_num:04d}"
            existe = Presupuesto.query.filter_by(numero=numero).first()
            if not existe:
                break
            siguiente_num += 1

        iva_valor = _to_decimal(data.get("iva_porcentaje") or '21')
        try:
            iva_valor = iva_valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            iva_valor = Decimal('21.00')

        # Crear presupuesto asociado
        p = Presupuesto(
            obra_id = obra_id,
            numero = numero,
            organizacion_id = current_user.organizacion_id,
            observaciones = data.get("observaciones"),
            iva_porcentaje = iva_valor,
            estado = 'borrador'
        )

        # Agregar campos adicionales si están disponibles
        superficie_val = data.get("superficie")
        superficie_decimal = _to_decimal(superficie_val) if superficie_val else None
        if superficie_decimal is not None and superficie_decimal != DECIMAL_ZERO:
            p.observaciones = f"{p.observaciones or ''} | Superficie: {superficie_decimal} m²"

        if data.get("tipo_construccion"):
            p.observaciones = f"{p.observaciones or ''} | Tipo: {data.get('tipo_construccion')}"

        if data.get("calculo_json"):
            p.datos_proyecto = data.get("calculo_json")

        if data.get("total_estimado"):
            total_estimado = _quantize_currency(_to_decimal(data.get("total_estimado")))
            p.total_con_iva = total_estimado

        db.session.add(p)
        db.session.commit()
        
        return jsonify({"ok": True, "presupuesto_id": p.id, "obra_id": obra_id})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
