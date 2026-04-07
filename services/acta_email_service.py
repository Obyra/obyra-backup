"""
Servicio para enviar el Acta de Entrega por email al cliente.

Aprovecha:
- services.acta_pdf_service para generar el PDF
- services.email_service para enviar via Resend
- services.branding_service para los datos de la empresa
- templates/emails/acta_entrega.html para el HTML del email
"""

import logging
from typing import Optional

from flask import current_app, render_template


logger = logging.getLogger(__name__)


def _calcular_texto_contraste(hex_color: Optional[str]) -> str:
    """
    Calcula color de texto (#ffffff o #1a1a1a) según luminancia del color de fondo.
    Mismo algoritmo que el template del PDF.
    """
    if not hex_color:
        return '#ffffff'
    try:
        clean = hex_color.lstrip('#')
        if len(clean) != 6:
            return '#ffffff'
        r = int(clean[0:2], 16)
        g = int(clean[2:4], 16)
        b = int(clean[4:6], 16)
        luminancia = (r * 299 + g * 587 + b * 114) / 1000
        return '#1a1a1a' if luminancia > 140 else '#ffffff'
    except Exception:
        return '#ffffff'


def _obtener_email_cliente(obra) -> Optional[str]:
    """
    Obtiene el email del cliente de la obra, intentando varias fuentes:
    1. obra.cliente_email (campo directo)
    2. obra.email_cliente (otra variante del nombre)
    3. obra.cliente_rel.email (vía relación con tabla Cliente)
    """
    for attr in ('cliente_email', 'email_cliente'):
        try:
            email = getattr(obra, attr, None)
            if email and '@' in str(email):
                return email.strip()
        except Exception:
            pass

    try:
        cliente_rel = getattr(obra, 'cliente_rel', None)
        if cliente_rel:
            email = getattr(cliente_rel, 'email', None)
            if email and '@' in str(email):
                return email.strip()
    except Exception:
        pass

    return None


def enviar_acta_por_email(acta, destinatario_override: Optional[str] = None) -> dict:
    """
    Genera el PDF del acta y lo envía por email al cliente.

    Args:
        acta: instancia de ActaEntrega
        destinatario_override: email opcional para forzar destinatario (testing)

    Returns:
        dict con 'ok', 'message', 'destinatario'
    """
    obra = acta.obra

    # 1) Determinar destinatario
    destinatario = destinatario_override or _obtener_email_cliente(obra)
    if not destinatario:
        msg = 'No se encontró email del cliente para enviar el acta.'
        logger.warning(f'[ACTA EMAIL] {msg} (acta_id={acta.id}, obra_id={obra.id if obra else None})')
        return {'ok': False, 'message': msg, 'destinatario': None}

    # 2) Generar PDF
    try:
        from services.acta_pdf_service import generar_pdf_acta
        pdf_bytes = generar_pdf_acta(acta)
    except Exception as e:
        logger.error(f'[ACTA EMAIL] Error generando PDF: {e}')
        return {'ok': False, 'message': 'Error al generar el PDF del acta', 'destinatario': destinatario}

    # 3) Branding de la organización
    try:
        from services.branding_service import get_branding_dict
        org = obra.organizacion if obra else None
        branding = get_branding_dict(org)
    except Exception:
        branding = {
            'nombre_display': 'OBYRA',
            'logo_url': None,
            'color_primario': '#1a3556',
            'cuit': None,
            'direccion': None,
            'telefono': None,
            'email': None,
        }

    # Resolver URL absoluta del logo si existe
    branding['logo_absolute_url'] = None
    if branding.get('logo_url'):
        try:
            from flask import url_for
            base_url = current_app.config.get('BASE_URL', 'https://app.obyra.com.ar').rstrip('/')
            branding['logo_absolute_url'] = f"{base_url}/static/{branding['logo_url']}"
        except Exception:
            pass

    texto_sobre_primario = _calcular_texto_contraste(branding.get('color_primario'))

    # 4) Renderizar HTML del email
    try:
        html = render_template(
            'emails/acta_entrega.html',
            acta=acta,
            obra=obra,
            branding=branding,
            texto_sobre_primario=texto_sobre_primario,
        )
    except Exception as e:
        logger.error(f'[ACTA EMAIL] Error renderizando template: {e}')
        return {'ok': False, 'message': 'Error al renderizar email', 'destinatario': destinatario}

    # 5) Asunto del email
    nombre_empresa = branding.get('nombre_display') or 'OBYRA'
    subject = f'Acta de Entrega - {obra.nombre} - {nombre_empresa}'

    # 6) Adjunto PDF
    obra_slug = (obra.nombre or 'obra').replace(' ', '_').lower()
    filename = f'acta_entrega_{obra_slug}_{acta.id:05d}.pdf'

    attachments = [{
        'filename': filename,
        'content': pdf_bytes,
        'content_type': 'application/pdf',
    }]

    # 7) Enviar
    try:
        from services.email_service import send_email
        reply_to = branding.get('email') or None

        result = send_email(
            to_email=destinatario,
            subject=subject,
            html_content=html,
            attachments=attachments,
            reply_to=reply_to,
        )
        if result:
            logger.info(f'[ACTA EMAIL] Enviado a {destinatario} (acta {acta.id})')
            return {'ok': True, 'message': f'Email enviado a {destinatario}', 'destinatario': destinatario}
        else:
            return {'ok': False, 'message': 'No se pudo enviar el email (Resend devolvió error)', 'destinatario': destinatario}
    except Exception as e:
        logger.error(f'[ACTA EMAIL] Error enviando: {e}')
        return {'ok': False, 'message': f'Error al enviar email', 'destinatario': destinatario}
