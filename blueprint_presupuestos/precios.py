"""Endpoint de estimacion automatica de precios (Fase 5.A).

  POST /presupuestos/<id>/estimar-precios

Itera composiciones del presupuesto y aplica precio_unitario segun la
jerarquia dual del servicio (MO vs material/equipo).

Idempotente: respeta composiciones con precio_estado='manual' y bloquea
si presupuesto.precios_snapshot_at esta seteado (snapshot al confirmar
como obra - Fase 5.C).
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


@presupuestos_bp.route('/<int:id>/estimar-precios', methods=['POST'])
@login_required
def estimar_precios(id):
    """Estima precios para todas las composiciones del presupuesto."""
    from models.budgets import Presupuesto
    from services.precio_recurso_service import estimar_precios_presupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    try:
        resumen = estimar_precios_presupuesto(
            presupuesto,
            user_id=current_user.id if current_user.is_authenticated else None,
        )
    except ValueError as ve:
        db.session.rollback()
        return jsonify(ok=False, error=str(ve)), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error en estimar-precios')
        if _es_super_admin() or _puede_gestionar():
            detalle = f'{type(e).__name__}: {str(e)[:300]}'
        else:
            detalle = 'No se pudo estimar precios. Avisale al equipo de OBYRA.'
        return jsonify(ok=False, error=detalle), 500

    # Audit
    try:
        from models.audit import registrar_audit
        c = resumen
        registrar_audit(
            accion='estimar_precios',
            entidad='presupuesto',
            entidad_id=presupuesto.id,
            detalle=(
                f'evaluadas={c["composiciones_evaluadas"]} '
                f'actualizados={c["actualizados"]} estimados={c["estimados"]} '
                f'vencidos={c["vencidos"]} sin_precio={c["sin_precio"]} '
                f'requiere_tc={c["requiere_tc"]} manual={c["manual"]} '
                f'mo={c["mo_aplicadas"]} '
                f'costo={c["total_costo"]:.2f} margen={c["margen_aplicado"]}%'
            ),
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error commiteando estimar_precios')
        return jsonify(ok=False, error=f'Error al guardar: {type(e).__name__}'), 500

    return jsonify(ok=True, **resumen)
