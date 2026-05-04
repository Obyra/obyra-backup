"""Endpoint del Generador Preliminar IA (Fase 4).

  POST /presupuestos/<id>/generar-preliminar

Toma los items del presupuesto que tienen regla tecnica detectada y genera
composiciones ejecutivas automaticas (materiales + MO + equipos) usando
los coeficientes del YAML.

Validaciones:
  - El usuario debe pertenecer a la organizacion del presupuesto (o ser
    super admin).
  - El rol debe ser administrativo (admin / pm / project_manager).
  - El presupuesto debe estar en estado borrador o enviado.
  - El ejecutivo no debe estar aprobado.

Idempotente: llamar 2 veces no duplica composiciones.
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


@presupuestos_bp.route('/<int:id>/generar-preliminar', methods=['POST'])
@login_required
def generar_preliminar(id):
    """Genera composicion ejecutiva automatica para los items del presupuesto."""
    from models.budgets import Presupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(
            ok=False,
            error=f'No se puede generar el preliminar en estado {presupuesto.estado}',
        ), 400
    if presupuesto.ejecutivo_aprobado:
        return jsonify(
            ok=False,
            error='El Presupuesto Ejecutivo ya esta aprobado. Reverti la aprobacion antes de regenerar.',
        ), 400

    # Generacion (servicio puro, no commitea)
    try:
        from services.composicion_auto_service import generar_preliminar as svc_generar
        resumen = svc_generar(
            presupuesto,
            user_id=current_user.id if current_user.is_authenticated else None,
        )
    except ModuleNotFoundError as e:
        db.session.rollback()
        current_app.logger.exception('ModuleNotFoundError en generar_preliminar')
        # Mensaje claro: que modulo falta. Se muestra a super admin / admin
        # para diagnostico rapido sin exponer paths internos.
        msg_admin = f'Falta dependencia Python: {e.name}. Verificar requirements.txt + redeploy.'
        return jsonify(
            ok=False,
            error=msg_admin if (_es_super_admin() or _puede_gestionar()) else
                  'No se pudo generar el preliminar. Avisale al equipo de OBYRA.',
            modulo_faltante=getattr(e, 'name', None),
        ), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error generando preliminar')
        # A super admin / admin le mostramos el tipo + mensaje. Al usuario
        # comun, solo un texto generico (sin stack trace).
        if _es_super_admin() or _puede_gestionar():
            detalle = f'{type(e).__name__}: {str(e)[:300]}'
        else:
            detalle = 'No se pudo generar el preliminar. Avisale al equipo de OBYRA.'
        return jsonify(ok=False, error=detalle), 500

    # Sincronizar MaterialCotizable para consolidar recursos para cotizacion
    try:
        from blueprint_presupuestos.ejecutivo import sincronizar_materiales_cotizables
        sincronizar_materiales_cotizables(presupuesto)
    except Exception:
        current_app.logger.exception(
            'Error sincronizando materiales_cotizables despues de generar preliminar'
        )
        # No abortar: las composiciones ya estan; sincronizar es opcional

    # Audit log
    try:
        from models.audit import registrar_audit
        c = resumen['contadores']
        registrar_audit(
            accion='generar_preliminar',
            entidad='presupuesto',
            entidad_id=presupuesto.id,
            detalle=(
                f'items_procesados={c["items_procesados"]} '
                f'items_con_composicion_nueva={c["items_creados"]} '
                f'composiciones_creadas={c["composiciones_creadas"]} '
                f'sin_regla={c["items_sin_regla"]} '
                f'sin_coef={c["items_sin_coeficiente"]} '
                f'respetado_manual={c["items_respetado_manual"]} '
                f'ya_generado={c["items_ya_generado"]}'
            ),
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error commiteando generar_preliminar')
        return jsonify(ok=False, error=f'Error al guardar: {type(e).__name__}'), 500

    return jsonify(ok=True, **resumen)
