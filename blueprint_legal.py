"""Blueprint Legal - Terminos, Privacidad, Cookies + flujo de consentimiento.

Rutas publicas (paginas):
  GET  /terminos
  GET  /privacidad
  GET  /cookies
  GET  /eliminacion-de-datos

Endpoints autenticados (consentimiento):
  GET  /legal/pendientes           -> JSON con docs pendientes de aceptar
  POST /legal/aceptar              -> registra UserConsent
  POST /legal/aceptar/<int:doc_id> -> alias para aceptar uno especifico
"""
from datetime import date, datetime
from flask import Blueprint, render_template, request, jsonify, abort, current_app
from flask_login import login_required, current_user

from extensions import db


legal_bp = Blueprint('legal', __name__)

# Fallback de vigencia para los templates estaticos cuando todavia no hay
# LegalDocument cargado en BD (ej: primera vez que arranca el sistema).
VIGENCIA_FALLBACK = date(2026, 4, 8)


def _doc_vigente_o_none(tipo: str):
    """Devuelve el LegalDocument vigente del tipo o None si la tabla no existe."""
    try:
        from models.legal import LegalDocument
        return LegalDocument.vigente(tipo)
    except Exception:
        return None


def _vigencia_visible(tipo: str):
    doc = _doc_vigente_o_none(tipo)
    if doc and doc.fecha_vigencia:
        return doc.fecha_vigencia
    return VIGENCIA_FALLBACK


@legal_bp.route('/terminos')
def terminos():
    return render_template('legal/terminos.html', vigencia=_vigencia_visible('terminos'))


@legal_bp.route('/privacidad')
def privacidad():
    return render_template('legal/privacidad.html', vigencia=_vigencia_visible('privacidad'))


@legal_bp.route('/cookies')
def cookies():
    return render_template('legal/cookies.html', vigencia=_vigencia_visible('cookies'))


@legal_bp.route('/eliminacion-de-datos')
def eliminacion_datos():
    """Pagina publica: como solicitar eliminacion/exportacion de datos.

    Intenta usar template; si no existe, devuelve un HTML minimo inline para
    que la URL este disponible (requerida por Play Store y AAIP).
    """
    try:
        return render_template('legal/eliminacion_datos.html', vigencia=_vigencia_visible('eliminacion_datos'))
    except Exception:
        return ('<!doctype html><html><head><meta charset="utf-8"><title>Eliminación de datos - OBYRA</title></head>'
                '<body style="font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;">'
                '<h1>Eliminación de datos personales</h1>'
                '<p>Como usuario de OBYRA podés solicitar la eliminación, anonimización o exportación '
                'de tus datos personales en cualquier momento, en cumplimiento de la Ley 25.326 de '
                'Protección de Datos Personales (Argentina) y del GDPR.</p>'
                '<h2>Cómo solicitarlo</h2>'
                '<ol>'
                '<li>Si ya tenés cuenta, ingresá y andá a <code>Mi cuenta &gt; Datos y Privacidad</code>.</li>'
                '<li>Desde ahí podés <strong>exportar</strong> tus datos en JSON (Art. 20 GDPR) o '
                '<strong>solicitar la eliminación</strong> de tu cuenta (anonimización + soft-delete).</li>'
                '<li>Tambien podés escribirnos a <a href="mailto:obyra.servicios@gmail.com">'
                'obyra.servicios@gmail.com</a> indicando el correo registrado.</li>'
                '</ol>'
                '<p><small>OBYRA almacena tus datos para prestar el servicio y mejorarlo. No se '
                'comparten con terceros sin tu consentimiento.</small></p>'
                '</body></html>')


# ============================================================
# Endpoints de consentimiento (requieren login)
# ============================================================

@legal_bp.route('/legal/pendientes', methods=['GET'])
@login_required
def legal_pendientes():
    """JSON con los documentos vigentes que el usuario aun NO acepto.

    Usado por el modal bloqueante en base.html para detectar si hace falta
    interrumpir al usuario.
    """
    try:
        from models.legal import documentos_pendientes_para_usuario
        pendientes = documentos_pendientes_para_usuario(current_user.id)
        return jsonify(
            ok=True,
            pendientes=[d.to_dict() for d in pendientes],
            count=len(pendientes),
        )
    except Exception as e:
        # Si la tabla todavia no existe (deploy en curso), no bloquear nada.
        current_app.logger.debug(f'legal_pendientes: {e}')
        return jsonify(ok=True, pendientes=[], count=0)


@legal_bp.route('/legal/aceptar', methods=['POST'])
@legal_bp.route('/legal/aceptar/<int:doc_id>', methods=['POST'])
@login_required
def legal_aceptar(doc_id=None):
    """Registra UserConsent para uno o varios documentos.

    Body JSON:
      {"document_ids": [1, 2, 3]}      # acepta los 3
      {"document_id": 5}               # acepta solo el 5
    Tambien acepta path param /legal/aceptar/<id>.
    """
    from models.legal import LegalDocument, UserConsent
    from services.memberships import get_current_org_id

    data = request.get_json(silent=True) or {}
    ids = []
    if doc_id is not None:
        ids = [doc_id]
    elif 'document_ids' in data and isinstance(data['document_ids'], list):
        ids = [int(x) for x in data['document_ids'] if x]
    elif 'document_id' in data and data['document_id']:
        ids = [int(data['document_id'])]

    if not ids:
        return jsonify(ok=False, error='Se requiere document_id o document_ids'), 400

    metodo = (data.get('metodo') or 'modal_reacept').strip()
    ip = request.remote_addr
    ua = (request.headers.get('User-Agent') or '')[:400]
    org_id = get_current_org_id()

    aceptados = 0
    detalles = []
    for did in ids:
        doc = LegalDocument.query.get(did)
        if not doc or not doc.activo:
            continue
        if UserConsent.acepto(current_user.id, doc.id):
            continue  # ya estaba
        consent = UserConsent(
            user_id=current_user.id,
            organizacion_id=org_id,
            legal_document_id=doc.id,
            tipo_documento=doc.tipo_documento,
            version=doc.version,
            accepted=True,
            accepted_at=datetime.utcnow(),
            ip_address=ip,
            user_agent=ua,
            metodo=metodo[:40],
        )
        db.session.add(consent)
        aceptados += 1
        detalles.append(f'{doc.tipo_documento}:v{doc.version}')

    if aceptados:
        try:
            from models.audit import registrar_audit
            registrar_audit(
                accion='aceptar_legal',
                entidad='usuario',
                entidad_id=current_user.id,
                detalle=f'Aceptacion legal via {metodo[:40]} ({", ".join(detalles)})',
            )
        except Exception:
            pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error guardando UserConsent')
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, aceptados=aceptados)
