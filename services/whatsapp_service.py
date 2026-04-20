"""
Servicio de WhatsApp para solicitar cotizaciones a proveedores.

MVP (Nivel 1): genera URL wa.me con mensaje pre-cargado.
Fase 2 (Nivel 2): integracion con WhatsApp Cloud API (Meta).
Fase 3 (Nivel 3): auto-deteccion de precios + alertas de respuesta.
"""
import re
from decimal import Decimal
from urllib.parse import quote


def normalizar_telefono(tel_raw, cod_pais_default='54'):
    """Convierte telefono local a formato internacional sin + (para wa.me).

    Ejemplos:
      '11 2345-6789'       -> '5491123456789'  (movil AR requiere el 9)
      '+54 9 11 2345 6789' -> '5491123456789'
      '+1 415 555 1234'    -> '14155551234'
      '011 4567-8901'      -> '5491145678901'

    Retorna None si no se puede parsear.
    """
    if not tel_raw:
        return None

    # Quitar todo lo que no sea digito o +
    tel = re.sub(r'[^\d+]', '', str(tel_raw))

    if not tel:
        return None

    # Si ya tiene +, sacar el +
    if tel.startswith('+'):
        tel = tel[1:]
        # Si ya viene con codigo pais, devolverlo
        if len(tel) >= 10:
            return tel
        return None

    # Quitar 0 inicial (prefijo nacional argentino)
    if tel.startswith('0'):
        tel = tel[1:]

    # Quitar 15 intermedio argentino (movil viejo): 11 15 2345 6789 -> 11 2345 6789
    # Buscar patron de area (2-4 digitos) + 15 + numero
    m = re.match(r'^(\d{2,4})15(\d{6,8})$', tel)
    if m:
        tel = m.group(1) + m.group(2)

    # Si ya empieza con codigo de pais (ej: 54), devolverlo tal cual
    if cod_pais_default == '54' and tel.startswith('54') and len(tel) >= 12:
        # Verificar que tenga el 9 para movil AR
        # Formato: 54 9 [area] [numero]
        if not tel.startswith('549') and len(tel) == 12:
            # 54 11 2345 6789 -> 54 9 11 2345 6789
            return '549' + tel[2:]
        return tel

    # Agregar codigo pais + 9 (movil AR)
    if cod_pais_default == '54':
        return '549' + tel

    return cod_pais_default + tel


def generar_mensaje_cotizacion(proveedor_nombre, org_nombre, items, presupuesto_numero=None):
    """Genera el texto default del mensaje de cotizacion.

    Args:
        proveedor_nombre: nombre a saludar
        org_nombre: nombre de la empresa que solicita
        items: lista de dicts con {descripcion, cantidad, unidad}
        presupuesto_numero: opcional, para referencia

    Retorna: str con el mensaje formateado (editable por el usuario antes de enviar).
    """
    saludo = f"Hola {proveedor_nombre}," if proveedor_nombre else "Hola,"
    header = f"{saludo} desde *{org_nombre}* necesitamos cotización para los siguientes ítems:"

    lineas = []
    for i, item in enumerate(items[:30], start=1):  # max 30 items por mensaje
        desc = (item.get('descripcion') or '').strip()
        cant = item.get('cantidad') or 0
        unid = item.get('unidad') or ''
        # Formatear cantidad sin decimales si es entero
        try:
            cant_d = Decimal(str(cant))
            cant_str = str(int(cant_d)) if cant_d == cant_d.to_integral_value() else str(cant_d.normalize())
        except Exception:
            cant_str = str(cant)
        lineas.append(f"{i}) {desc} — {cant_str} {unid}")

    items_block = "\n".join(lineas)

    if len(items) > 30:
        items_block += f"\n\n_...y {len(items) - 30} ítems más (ver detalle adjunto)_"

    footer = (
        "\n\nPor favor envíanos:\n"
        "  • Precio unitario\n"
        "  • Plazo de entrega\n"
        "  • Condición de pago\n"
        "  • Validez de la oferta\n"
    )

    if presupuesto_numero:
        footer += f"\n_Ref: Presupuesto {presupuesto_numero}_"

    footer += "\n\n¡Muchas gracias!"

    return f"{header}\n\n{items_block}{footer}"


def generar_url_wa_me(telefono_normalizado, mensaje):
    """Genera URL https://wa.me/<numero>?text=<mensaje-url-encoded>."""
    if not telefono_normalizado:
        return None
    mensaje_encoded = quote(mensaje or '')
    return f"https://wa.me/{telefono_normalizado}?text={mensaje_encoded}"


def construir_items_snapshot(items_presupuesto):
    """Arma snapshot JSON-serializable de items para guardar en la solicitud."""
    snapshot = []
    for it in items_presupuesto:
        snapshot.append({
            'id': it.id,
            'descripcion': it.descripcion,
            'cantidad': float(it.cantidad or 0),
            'unidad': it.unidad or '',
            'precio_unitario': float(it.precio_unitario or 0),
            'total': float(it.total or 0),
            'tipo': it.tipo,
        })
    return snapshot


def enviar_por_api_cloud(solicitud):
    """STUB Fase 2: envio real via WhatsApp Cloud API (Meta Graph API).

    Implementacion futura:
    - POST https://graph.facebook.com/v18.0/{phone_number_id}/messages
    - Headers: Authorization Bearer <META_ACCESS_TOKEN>
    - Body: {messaging_product: whatsapp, to: telefono, type: template, template: {...}}
    - Requiere plantilla pre-aprobada por Meta si es la primera interaccion.

    Retorna: (success: bool, error_msg: str | None)
    """
    raise NotImplementedError(
        "Integracion con WhatsApp Cloud API pendiente (Fase 2). "
        "Por ahora usar canal='wa_link' (apertura manual de WhatsApp Web)."
    )


def generar_numero_solicitud(org_id):
    """Genera numero incremental SCW-YYYY-NNNN por organizacion."""
    from models.presupuestos_wa import SolicitudCotizacionWA
    from datetime import datetime
    from sqlalchemy import func
    from extensions import db

    anio = datetime.now().year
    prefix = f"SCW-{anio}-"
    count = db.session.query(func.count(SolicitudCotizacionWA.id)).filter(
        SolicitudCotizacionWA.organizacion_id == org_id,
        SolicitudCotizacionWA.numero.like(f"{prefix}%"),
    ).scalar() or 0
    return f"{prefix}{(count + 1):04d}"
