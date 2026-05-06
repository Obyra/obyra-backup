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


@presupuestos_bp.route('/items/<int:id>/restaurar-ia', methods=['POST'])
@login_required
def restaurar_ia_item(id):
    """Restaura el precio estimado por IA en un item lockeado manualmente.

    MVP Lock Manual: solo afecta precio (no cantidad). Pasos:
      1. Limpia precio_locked y editado_at del item.
      2. Resetea las composiciones a precio_estado='sin_precio' para que
         la proxima estimacion las rellene.
      3. Re-estima precios solo para este item.

    Si el item no tiene composiciones, no hay nada que re-estimar — devuelve
    info_message indicando que primero hay que generar APU.
    """
    from models.budgets import Presupuesto, ItemPresupuesto

    item = ItemPresupuesto.query.get(id)
    if not item:
        return jsonify(ok=False, error='Item no encontrado'), 404
    presupuesto = item.presupuesto
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403
    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(ok=False, error=(
            f'No se puede restaurar IA: presupuesto en estado {presupuesto.estado}'
        )), 400

    composiciones = (item.composiciones.all()
                     if hasattr(item.composiciones, 'all')
                     else list(item.composiciones))
    if not composiciones:
        # Sin APU no hay nada que IA pueda recalcular. Solo limpiamos el lock.
        item.precio_locked = False
        item.editado_at = None
        item.editado_por_user_id = None
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Error limpiando lock sin APU')
            return jsonify(ok=False, error='Error al guardar'), 500
        return jsonify(
            ok=True,
            requiere_apu=True,
            mensaje=('El item no tiene composicion ejecutiva. Genera APU primero '
                     '(boton "Generar composicion ejecutiva") para que la IA pueda '
                     'estimar precios. Por ahora solo se quito el lock.'),
        )

    # Limpiar lock + resetear composiciones
    item.precio_locked = False
    item.editado_at = None
    item.editado_por_user_id = None
    for comp in composiciones:
        # Solo resetear las que estaban marcadas manual (sino sobrescribiriamos
        # el origen real de cada composicion).
        if (comp.precio_estado or '').lower() == 'manual':
            comp.precio_estado = 'sin_precio'

    # Re-estimar todo el presupuesto. Es lo mas seguro: usa la misma logica
    # que el endpoint principal y respeta otras composiciones manuales que
    # NO pertenecen a este item (porque siguen con precio_estado='manual').
    try:
        from services.precio_recurso_service import estimar_precios_presupuesto
        resumen = estimar_precios_presupuesto(
            presupuesto,
            user_id=current_user.id if current_user.is_authenticated else None,
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error restaurando IA')
        return jsonify(ok=False, error=f'{type(e).__name__}: {str(e)[:200]}'), 500

    return jsonify(
        ok=True,
        item_id=item.id,
        precio_locked=item.precio_locked,
        precio_unitario=float(item.precio_unitario or 0),
        cobertura_pct=resumen.get('cobertura_pct', 0),
    )
