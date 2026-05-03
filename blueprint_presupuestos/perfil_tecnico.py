"""Endpoints del Perfil Tecnico del Proyecto (Fase 2).

  GET  /presupuestos/<id>/perfil-tecnico    -> JSON con perfil + niveles
  POST /presupuestos/<id>/perfil-tecnico    -> crear/actualizar perfil

Multi-tenant: solo puede operar el usuario de la organizacion duena del
presupuesto, o un super admin.
"""
from __future__ import annotations

from flask import request, jsonify, current_app
from flask_login import login_required, current_user

from extensions import db
from services.memberships import get_current_org_id
from blueprint_presupuestos import presupuestos_bp


def _es_super_admin():
    return bool(getattr(current_user, 'is_super_admin', False))


def _verificar_acceso_presupuesto(presupuesto):
    if not current_user.is_authenticated:
        return False
    if _es_super_admin():
        return True
    org_id = get_current_org_id()
    return presupuesto.organizacion_id == org_id


def _puede_gestionar():
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm', 'project_manager')


@presupuestos_bp.route('/<int:id>/perfil-tecnico', methods=['GET'])
@login_required
def perfil_tecnico_get(id):
    """Devuelve el perfil tecnico + niveles del presupuesto.

    Si no hay perfil cargado, devuelve ok=True con profile=None para que el
    frontend muestre "Sin perfil tecnico cargado" + boton de completar.
    """
    from models.budgets import Presupuesto
    from models.project_technical_profile import ProjectTechnicalProfile

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403

    profile = ProjectTechnicalProfile.query.filter_by(presupuesto_id=presupuesto.id).first()
    if not profile:
        return jsonify(ok=True, profile=None, niveles=[])

    return jsonify(ok=True, profile=profile.to_dict(include_niveles=True))


@presupuestos_bp.route('/<int:id>/perfil-tecnico', methods=['POST'])
@login_required
def perfil_tecnico_post(id):
    """Crea o actualiza el perfil tecnico del presupuesto.

    Body JSON con cualquier subset de campos (ver validar_y_normalizar).
    Retorna {ok, profile, niveles_generados, fue_creacion}.
    """
    from models.budgets import Presupuesto
    from services.perfil_tecnico_service import upsert_perfil_tecnico

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    # Bloquear edicion de perfil tecnico si el presupuesto esta aprobado.
    # En estado borrador / enviado se puede editar libremente.
    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(
            ok=False,
            error=f'No se puede modificar el perfil tecnico de un presupuesto en estado {presupuesto.estado}',
        ), 400

    payload = request.get_json(silent=True) or request.form.to_dict()
    autogenerar = bool(payload.get('autogenerar_niveles', True))

    try:
        result = upsert_perfil_tecnico(
            presupuesto=presupuesto,
            payload=payload,
            user_id=current_user.id if current_user.is_authenticated else None,
            autogenerar_niveles=autogenerar,
        )
    except ValueError as ve:
        db.session.rollback()
        return jsonify(ok=False, error=str(ve)), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error guardando perfil tecnico')
        return jsonify(ok=False, error='Error interno guardando el perfil'), 500

    # Audit
    try:
        from models.audit import registrar_audit
        registrar_audit(
            accion='crear_perfil_tecnico' if result['fue_creacion'] else 'editar_perfil_tecnico',
            entidad='presupuesto',
            entidad_id=presupuesto.id,
            detalle=(
                f'tipo_obra={result["profile"].tipo_obra} '
                f'pisos={result["profile"].cantidad_pisos} '
                f'subsuelos={result["profile"].cantidad_subsuelos} '
                f'criterio={result["profile"].criterio_distribucion} '
                f'niveles_generados={result["niveles_generados"]}'
            ),
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error commiteando perfil tecnico')
        return jsonify(ok=False, error=f'Error al guardar: {type(e).__name__}'), 500

    return jsonify(
        ok=True,
        profile=result['profile'].to_dict(include_niveles=True),
        niveles_generados=result['niveles_generados'],
        fue_creacion=result['fue_creacion'],
    )
