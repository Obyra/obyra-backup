"""Presupuesto Ejecutivo (APU).

Vista interna donde cada item del pliego se descompone en MO + materiales + equipos.
El cliente ve solo el presupuesto comercial; el ejecutivo es uso interno para
calcular costo estimado y margen por etapa antes de pasar a obra.

Rutas:
  GET  /presupuestos/<id>/ejecutivo           -> vista principal con items agrupados por etapa
"""
from collections import OrderedDict
from decimal import Decimal

from flask import render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from blueprint_presupuestos import presupuestos_bp
from extensions import db
from models import Presupuesto, ItemPresupuesto
from services.memberships import get_current_org_id


ESTADOS_EDITABLES_EJECUTIVO = ('borrador', 'enviado', 'aprobado')


def _puede_ver_ejecutivo(presupuesto):
    """El ejecutivo es interno: solo admin/PM."""
    if not current_user.is_authenticated:
        return False
    rol = getattr(current_user, 'role', '') or ''
    return rol in ('admin', 'administrador', 'pm', 'project_manager')


@presupuestos_bp.route('/<int:id>/ejecutivo')
@login_required
def ejecutivo_vista(id):
    """Vista del presupuesto ejecutivo: items del pliego agrupados por etapa."""
    org_id = get_current_org_id()
    if not org_id:
        flash('Seleccioná una organización.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion'))

    presupuesto = Presupuesto.query.filter_by(
        id=id, organizacion_id=org_id,
    ).first_or_404()

    if not _puede_ver_ejecutivo(presupuesto):
        abort(403)

    if presupuesto.estado not in ESTADOS_EDITABLES_EJECUTIVO:
        flash(
            f'El presupuesto ejecutivo solo está disponible para presupuestos '
            f'en estado borrador, enviado o aprobado (actual: {presupuesto.estado}).',
            'warning',
        )
        return redirect(url_for('presupuestos.detalle', id=id))

    # Traer items ordenados por etapa_nombre para agrupar en el template
    items = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
    ).order_by(
        ItemPresupuesto.etapa_nombre,
        ItemPresupuesto.id,
    ).all()

    # Agrupar por etapa preservando orden natural
    etapas = OrderedDict()
    for item in items:
        nombre_etapa = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Sin etapa')
        if nombre_etapa not in etapas:
            etapas[nombre_etapa] = {
                'items': [],
                'total_vendido': Decimal('0'),
                'total_costo': Decimal('0'),
            }
        etapas[nombre_etapa]['items'].append(item)
        etapas[nombre_etapa]['total_vendido'] += Decimal(str(item.total or 0))
        # Sumar composiciones (Fase 1: aún no hay, queda en 0)
        for comp in (item.composiciones or []):
            etapas[nombre_etapa]['total_costo'] += Decimal(str(comp.total or 0))

    total_vendido = sum((d['total_vendido'] for d in etapas.values()), Decimal('0'))
    total_costo = sum((d['total_costo'] for d in etapas.values()), Decimal('0'))
    margen = total_vendido - total_costo
    margen_pct = (margen / total_vendido * 100) if total_vendido > 0 else Decimal('0')

    return render_template(
        'presupuestos/ejecutivo.html',
        presupuesto=presupuesto,
        etapas=etapas,
        total_vendido=total_vendido,
        total_costo=total_costo,
        margen=margen,
        margen_pct=margen_pct,
    )
