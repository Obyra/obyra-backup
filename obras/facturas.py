"""Caja A — Facturas administrativas por obra (Fase 1 MVP).

Rutas:
  GET  /obras/<id>/facturas              -> listado JSON / vista
  POST /obras/<id>/facturas              -> crear factura (multipart con archivo)
  GET  /obras/<id>/facturas/<fid>        -> detalle (JSON)
  POST /obras/<id>/facturas/<fid>/pagar  -> marcar pagada
  POST /obras/<id>/facturas/<fid>/rechazar -> rechazar (con motivo)
  POST /obras/<id>/facturas/<fid>/observar -> observar (con texto)
  GET  /obras/<id>/facturas/<fid>/archivo  -> descargar adjunto

Permisos MVP:
  Solo admin/PM puede listar/crear/marcar/rechazar.
  Operario queda para fase posterior con flujo de aprobacion.

NO toca obra.costo_real. La promocion a Caja B es Fase 3.
"""
import os
import uuid
from datetime import datetime, date as date_cls
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, request, jsonify, current_app, send_file, abort,
                   render_template, redirect, url_for, flash)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from extensions import db
from models import Obra, Usuario
from models.obra_factura import (
    ObraFactura, ObraFacturaAudit,
    TIPOS_COMPROBANTE, ESTADOS_FACTURA, FORMAS_PAGO, FORMAS_PAGO_YA_PAGADAS,
    adjunto_es_obligatorio,
)
from models.proveedores_oc import ProveedorOC
from obras import obras_bp


# STORAGE_BASE compartido con el resto de uploads (mismo patron que pliegos).
STORAGE_BASE = os.environ.get('STORAGE_BASE', 'storage')
FACTURAS_DIRNAME = os.path.join('uploads', 'obras_facturas')

ALLOWED_EXT = {'pdf', 'jpg', 'jpeg', 'png', 'webp'}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _es_admin_o_pm() -> bool:
    rol = (getattr(current_user, 'rol', '') or '').lower()
    role = (getattr(current_user, 'role', '') or '').lower()
    return rol in ('administrador', 'admin') or role in ('admin', 'pm', 'project_manager')


def _obra_de_org(obra_id: int):
    """Obtiene la obra validando org. Lanza 404 si no corresponde."""
    org_id = getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first()
    if not obra:
        abort(404)
    if getattr(obra, 'deleted_at', None) is not None:
        abort(404)
    return obra


def _carpeta_obra(obra_id: int) -> str:
    """Directorio absoluto donde se guardan adjuntos de esta obra."""
    return os.path.join(STORAGE_BASE, FACTURAS_DIRNAME, str(obra_id))


def _validar_extension(filename: str) -> str:
    """Devuelve la extension en minusculas si es valida, o tira ValueError."""
    if not filename or '.' not in filename:
        raise ValueError('Archivo sin extensión válida.')
    ext = filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f'Extensión no permitida: {ext}. Aceptadas: pdf, jpg, png, webp.')
    return ext


def _guardar_adjunto(file_storage, obra_id: int) -> dict:
    """Guarda el archivo bajo STORAGE_BASE/uploads/obras_facturas/<obra_id>/<uuid>.<ext>.
    Devuelve dict con path_relativo (para BD), nombre_original, mime, tamano."""
    ext = _validar_extension(file_storage.filename)
    # Tamaño: leer y descartar para medir es caro; mejor confiar en Content-Length
    # y validar al final con seek/tell.
    nombre_original = secure_filename(file_storage.filename) or f'factura.{ext}'
    uid = uuid.uuid4().hex
    rel = os.path.join(FACTURAS_DIRNAME, str(obra_id), f'{uid}.{ext}')
    abs_path = os.path.join(STORAGE_BASE, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    file_storage.save(abs_path)

    tamano = os.path.getsize(abs_path)
    if tamano > MAX_UPLOAD_BYTES:
        try:
            os.unlink(abs_path)
        except Exception:
            pass
        raise ValueError(f'El archivo supera el límite de 10 MB (tiene {tamano // 1024} KB).')

    return {
        'archivo_path': rel.replace('\\', '/'),
        'archivo_nombre_original': nombre_original[:255],
        'archivo_mime': (file_storage.mimetype or '')[:80] or None,
        'archivo_tamano_bytes': tamano,
    }


def _registrar_audit(factura: ObraFactura, accion: str, detalle: str = None):
    db.session.add(ObraFacturaAudit(
        factura_id=factura.id,
        accion=accion,
        user_id=current_user.id if current_user.is_authenticated else None,
        detalle=detalle,
    ))


def _parsear_fecha(s: str):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _tc_dia_si_usd(moneda: str):
    """Si la moneda es USD intenta capturar el tipo de cambio del dia.
    Returns: (tc Decimal | None, importe_ars Decimal | None calculado afuera).
    Usa el servicio BNA existente; si falla, deja None para que el usuario
    pueda completar manual despues."""
    if (moneda or 'ARS').upper() != 'USD':
        return None
    try:
        from services.exchange.base import ensure_rate
        from services.exchange.providers.bna import fetch_official_rate
        snap = ensure_rate(
            provider='bna_html',
            base_currency='ARS',
            quote_currency='USD',
            fetcher=fetch_official_rate,
            as_of=date_cls.today(),
            fallback_rate=Decimal('1000.00'),
        )
        return Decimal(str(snap.value)) if snap and snap.value else None
    except Exception:
        return None


# =============================================================================
# CATALOGOS PARA EL MODAL: usuarios elegibles + busqueda de proveedores
# =============================================================================

@obras_bp.route('/<int:obra_id>/facturas/_usuarios', methods=['GET'])
@login_required
def facturas_usuarios_elegibles(obra_id):
    """Usuarios elegibles para 'pagar_a_user_id' en una factura.

    Por ahora devuelve TODOS los usuarios activos de la org. En el futuro
    se podria limitar a operarios/responsables asignados a la obra.
    """
    if not _es_admin_o_pm():
        return jsonify(ok=False, error='Sin permiso'), 403
    obra = _obra_de_org(obra_id)
    usuarios = (Usuario.query
                .filter_by(organizacion_id=obra.organizacion_id, activo=True)
                .order_by(Usuario.nombre, Usuario.apellido)
                .all())
    return jsonify(ok=True, usuarios=[
        {
            'id': u.id,
            'nombre': f"{u.nombre or ''} {u.apellido or ''}".strip() or u.email,
            'email': u.email,
            'role': getattr(u, 'role', None) or getattr(u, 'rol', None),
        } for u in usuarios
    ])


# =============================================================================
# LISTAR (vista HTML) — embebida en detalle obra via tab; ademas endpoint JSON
# =============================================================================

@obras_bp.route('/<int:obra_id>/facturas', methods=['GET'])
@login_required
def facturas_listar(obra_id):
    if not _es_admin_o_pm():
        return jsonify(ok=False, error='Sin permiso'), 403
    obra = _obra_de_org(obra_id)

    estado_filtro = (request.args.get('estado') or '').strip()
    q = ObraFactura.query.filter(
        ObraFactura.obra_id == obra.id,
        ObraFactura.organizacion_id == obra.organizacion_id,
    )
    if estado_filtro in ESTADOS_FACTURA:
        q = q.filter(ObraFactura.estado == estado_filtro)

    facturas = q.order_by(ObraFactura.fecha_factura.desc(),
                          ObraFactura.id.desc()).all()

    # Resumenes para badges
    totales = {
        'pendiente_ars': Decimal('0'),
        'pagado_ars': Decimal('0'),
        'rechazado_ars': Decimal('0'),
        'count_total': len(facturas),
    }
    for f in facturas:
        monto = f.importe_ars if f.moneda == 'USD' and f.importe_ars else f.importe
        monto = Decimal(str(monto or 0))
        if f.estado == 'pendiente':
            totales['pendiente_ars'] += monto
        elif f.estado == 'pagada':
            totales['pagado_ars'] += monto
        elif f.estado == 'rechazada':
            totales['rechazado_ars'] += monto

    # Respuesta JSON si el caller lo pide explicitamente
    if request.headers.get('Accept', '').startswith('application/json') or request.args.get('format') == 'json':
        return jsonify(
            ok=True,
            facturas=[f.to_dict() for f in facturas],
            totales={k: float(v) if isinstance(v, Decimal) else v for k, v in totales.items()},
        )

    return render_template(
        'obras/facturas_lista.html',
        obra=obra,
        facturas=facturas,
        totales=totales,
        estado_filtro=estado_filtro,
        estados_disponibles=ESTADOS_FACTURA,
        tipos_comprobante=TIPOS_COMPROBANTE,
    )


# =============================================================================
# CREAR (multipart)
# =============================================================================

@obras_bp.route('/<int:obra_id>/facturas', methods=['POST'])
@login_required
def facturas_crear(obra_id):
    if not _es_admin_o_pm():
        return jsonify(ok=False, error='Sin permiso'), 403
    obra = _obra_de_org(obra_id)

    f = request.form

    tipo_comprobante = (f.get('tipo_comprobante') or 'factura').strip().lower()
    if tipo_comprobante not in TIPOS_COMPROBANTE:
        return jsonify(ok=False, error=f'tipo_comprobante invalido: {tipo_comprobante}'), 400

    concepto = (f.get('concepto') or '').strip()
    if not concepto:
        return jsonify(ok=False, error='El concepto es obligatorio.'), 400

    fecha_factura = _parsear_fecha(f.get('fecha_factura'))
    if not fecha_factura:
        return jsonify(ok=False, error='Fecha de factura invalida (usar YYYY-MM-DD o DD/MM/YYYY).'), 400

    try:
        importe = Decimal(str(f.get('importe') or '0').replace(',', '.'))
    except (InvalidOperation, ValueError):
        return jsonify(ok=False, error='Importe invalido.'), 400
    if importe <= 0:
        return jsonify(ok=False, error='El importe debe ser mayor a 0.'), 400

    moneda = (f.get('moneda') or 'ARS').upper()
    if moneda not in ('ARS', 'USD'):
        return jsonify(ok=False, error='Moneda debe ser ARS o USD.'), 400

    # === 3 actores: proveedor (opcional) + comprador interno + forma de pago ===
    # 1) Proveedor: id de provider_oc O nombre externo.
    prov_raw = (f.get('proveedor_id') or '').strip()
    prov_externo = (f.get('proveedor_externo_nombre') or '').strip()
    proveedor_id = int(prov_raw) if prov_raw.isdigit() else None
    proveedor_externo_nombre = prov_externo[:200] if prov_externo else None
    # No exigimos proveedor obligatorio: hay gastos sin proveedor formal.
    if proveedor_id:
        # Validar que el proveedor exista (puede ser global o de la org)
        prov = ProveedorOC.query.filter_by(id=proveedor_id).first()
        if not prov:
            return jsonify(ok=False, error='Proveedor invalido.'), 400

    # 2) Comprador interno: usuario que hizo la compra (obligatorio).
    comprador_raw = (f.get('comprado_por_user_id') or '').strip()
    comprado_por_user_id = int(comprador_raw) if comprador_raw.isdigit() else None
    if not comprado_por_user_id:
        # Default = quien carga la factura
        comprado_por_user_id = current_user.id
    u = Usuario.query.filter_by(id=comprado_por_user_id,
                                 organizacion_id=obra.organizacion_id).first()
    if not u:
        return jsonify(ok=False, error='Comprador interno invalido.'), 400

    # 3) Forma de pago: define con quien queda la deuda.
    forma_pago = (f.get('forma_pago') or '').strip().lower()
    if not forma_pago:
        return jsonify(ok=False, error='Indicá la forma de pago.'), 400
    if forma_pago not in FORMAS_PAGO:
        return jsonify(ok=False, error=f'Forma de pago invalida: {forma_pago}'), 400
    # Si la forma de pago es "cuenta_corriente_proveedor", debe haber proveedor.
    if forma_pago == 'cuenta_corriente_proveedor' and not proveedor_id:
        return jsonify(ok=False,
                       error='Para "cuenta corriente con proveedor" tenés que seleccionar un proveedor de la lista.'), 400

    # Adjunto
    archivo = request.files.get('archivo')
    info_adjunto = None
    if archivo and archivo.filename:
        try:
            info_adjunto = _guardar_adjunto(archivo, obra.id)
        except ValueError as ve:
            return jsonify(ok=False, error=str(ve)), 400
        except Exception as e:
            current_app.logger.exception('Error guardando adjunto factura')
            return jsonify(ok=False, error=f'No se pudo guardar el archivo: {type(e).__name__}'), 500
    elif adjunto_es_obligatorio(tipo_comprobante):
        return jsonify(ok=False,
                       error='Para este tipo de comprobante el adjunto es obligatorio.'), 400

    # Tipo de cambio (si USD)
    tc = _tc_dia_si_usd(moneda)
    importe_ars = None
    if moneda == 'USD' and tc:
        importe_ars = (importe * tc).quantize(Decimal('0.01'))

    # Si forma_pago es "ya pagada" (caja_obra / caja_oficina), nace pagada.
    estado_inicial = 'pagada' if forma_pago in FORMAS_PAGO_YA_PAGADAS else 'pendiente'
    fecha_pago_inicial = date_cls.today() if estado_inicial == 'pagada' else None
    pagada_por_user_id_inicial = current_user.id if estado_inicial == 'pagada' else None
    marcada_paga_at_inicial = datetime.utcnow() if estado_inicial == 'pagada' else None

    factura = ObraFactura(
        organizacion_id=obra.organizacion_id,
        obra_id=obra.id,
        tipo_comprobante=tipo_comprobante,
        numero_factura=(f.get('numero_factura') or '').strip()[:50] or None,
        concepto=concepto[:300],
        fecha_factura=fecha_factura,
        importe=importe,
        moneda=moneda,
        tipo_cambio_usado=tc,
        importe_ars=importe_ars,
        # 3 actores
        proveedor_id=proveedor_id,
        proveedor_externo_nombre=proveedor_externo_nombre,
        comprado_por_user_id=comprado_por_user_id,
        forma_pago=forma_pago,
        cargada_por_user_id=current_user.id,
        estado=estado_inicial,
        fecha_pago=fecha_pago_inicial,
        pagada_por_user_id=pagada_por_user_id_inicial,
        marcada_paga_at=marcada_paga_at_inicial,
        observaciones=(f.get('observaciones') or '').strip() or None,
        archivo_path=info_adjunto['archivo_path'] if info_adjunto else None,
        archivo_nombre_original=info_adjunto['archivo_nombre_original'] if info_adjunto else None,
        archivo_mime=info_adjunto['archivo_mime'] if info_adjunto else None,
        archivo_tamano_bytes=info_adjunto['archivo_tamano_bytes'] if info_adjunto else None,
    )
    db.session.add(factura)
    db.session.flush()
    _registrar_audit(factura, 'creada',
                      f'importe={importe} {moneda} forma_pago={forma_pago} estado={estado_inicial}')
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error commiteando factura')
        return jsonify(ok=False, error=f'Error al guardar: {type(e).__name__}'), 500

    return jsonify(ok=True, factura=factura.to_dict())


# =============================================================================
# DETALLE
# =============================================================================

@obras_bp.route('/<int:obra_id>/facturas/<int:factura_id>', methods=['GET'])
@login_required
def facturas_detalle(obra_id, factura_id):
    if not _es_admin_o_pm():
        return jsonify(ok=False, error='Sin permiso'), 403
    obra = _obra_de_org(obra_id)
    factura = ObraFactura.query.filter_by(id=factura_id, obra_id=obra.id).first()
    if not factura:
        abort(404)

    detalle = factura.to_dict()
    detalle['auditoria'] = [
        {
            'accion': a.accion,
            'detalle': a.detalle,
            'usuario': (a.usuario.nombre + ' ' + (a.usuario.apellido or '')).strip()
                       if a.usuario else None,
            'created_at': a.created_at.isoformat() if a.created_at else None,
        }
        for a in factura.auditoria
    ]
    detalle['cargada_por'] = (
        (factura.cargada_por.nombre + ' ' +
         (factura.cargada_por.apellido or '')).strip()
        if factura.cargada_por else None
    )
    return jsonify(ok=True, factura=detalle)


# =============================================================================
# ACCIONES (pagar / rechazar / observar)
# =============================================================================

@obras_bp.route('/<int:obra_id>/facturas/<int:factura_id>/pagar', methods=['POST'])
@login_required
def facturas_pagar(obra_id, factura_id):
    if not _es_admin_o_pm():
        return jsonify(ok=False, error='Sin permiso'), 403
    obra = _obra_de_org(obra_id)
    factura = ObraFactura.query.filter_by(id=factura_id, obra_id=obra.id).first()
    if not factura:
        abort(404)
    if factura.estado not in ('pendiente', 'observada'):
        return jsonify(ok=False,
                       error=f'No se puede marcar pagada una factura en estado {factura.estado}.'), 400

    data = request.get_json(silent=True) or request.form.to_dict()
    fecha_pago = _parsear_fecha(data.get('fecha_pago')) or date_cls.today()
    obs = (data.get('observaciones') or '').strip() or None

    factura.estado = 'pagada'
    factura.fecha_pago = fecha_pago
    factura.pagada_por_user_id = current_user.id
    factura.marcada_paga_at = datetime.utcnow()
    if obs:
        factura.observaciones = ((factura.observaciones or '') + '\n[Pago] ' + obs).strip()

    _registrar_audit(factura, 'pagada', f'fecha_pago={fecha_pago.isoformat()}')
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error marcando pagada')
        return jsonify(ok=False, error=f'Error: {type(e).__name__}'), 500
    return jsonify(ok=True, factura=factura.to_dict())


@obras_bp.route('/<int:obra_id>/facturas/<int:factura_id>/rechazar', methods=['POST'])
@login_required
def facturas_rechazar(obra_id, factura_id):
    if not _es_admin_o_pm():
        return jsonify(ok=False, error='Sin permiso'), 403
    obra = _obra_de_org(obra_id)
    factura = ObraFactura.query.filter_by(id=factura_id, obra_id=obra.id).first()
    if not factura:
        abort(404)
    if factura.estado not in ('pendiente', 'observada'):
        return jsonify(ok=False,
                       error=f'No se puede rechazar una factura {factura.estado}.'), 400

    data = request.get_json(silent=True) or request.form.to_dict()
    motivo = (data.get('motivo') or '').strip()
    if not motivo:
        return jsonify(ok=False, error='Indicá el motivo del rechazo.'), 400

    factura.estado = 'rechazada'
    factura.motivo_rechazo = motivo[:500]
    factura.rechazada_por_user_id = current_user.id
    factura.rechazada_at = datetime.utcnow()
    _registrar_audit(factura, 'rechazada', motivo[:300])
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error rechazando factura')
        return jsonify(ok=False, error=f'Error: {type(e).__name__}'), 500
    return jsonify(ok=True, factura=factura.to_dict())


@obras_bp.route('/<int:obra_id>/facturas/<int:factura_id>/observar', methods=['POST'])
@login_required
def facturas_observar(obra_id, factura_id):
    if not _es_admin_o_pm():
        return jsonify(ok=False, error='Sin permiso'), 403
    obra = _obra_de_org(obra_id)
    factura = ObraFactura.query.filter_by(id=factura_id, obra_id=obra.id).first()
    if not factura:
        abort(404)
    if factura.estado not in ('pendiente',):
        return jsonify(ok=False,
                       error=f'Solo se observan facturas pendientes (actual: {factura.estado}).'), 400

    data = request.get_json(silent=True) or request.form.to_dict()
    obs = (data.get('observaciones') or '').strip()
    if not obs:
        return jsonify(ok=False, error='Indicá la observación.'), 400

    factura.estado = 'observada'
    factura.observaciones = ((factura.observaciones or '') + '\n[Obs] ' + obs).strip()
    _registrar_audit(factura, 'observada', obs[:300])
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=f'Error: {type(e).__name__}'), 500
    return jsonify(ok=True, factura=factura.to_dict())


# =============================================================================
# DESCARGAR ADJUNTO
# =============================================================================

@obras_bp.route('/<int:obra_id>/facturas/<int:factura_id>/archivo', methods=['GET'])
@login_required
def facturas_descargar_archivo(obra_id, factura_id):
    if not _es_admin_o_pm():
        abort(403)
    obra = _obra_de_org(obra_id)
    factura = ObraFactura.query.filter_by(id=factura_id, obra_id=obra.id).first()
    if not factura or not factura.archivo_path:
        abort(404)
    abs_path = os.path.join(STORAGE_BASE, factura.archivo_path)
    if not os.path.exists(abs_path):
        current_app.logger.warning(
            f'Adjunto factura {factura.id} no encontrado en disco: {abs_path}'
        )
        abort(404)
    return send_file(
        abs_path,
        as_attachment=False,
        download_name=factura.archivo_nombre_original or 'factura.pdf',
        mimetype=factura.archivo_mime or 'application/octet-stream',
    )
