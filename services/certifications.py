"""Helpers for Certificaciones 2.0 (avance + pagos)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from flask import current_app
from sqlalchemy import func

from extensions import db
from models import Obra, Presupuesto, WorkCertification, WorkCertificationItem, WorkPayment


DecimalZero = Decimal('0')
DecimalOneHundred = Decimal('100')


@dataclass
class BudgetContext:
    amount_ars: Decimal
    amount_currency: Decimal
    currency: str
    tasa_usd: Optional[Decimal]
    indice_cac: Optional[Decimal]


def _as_decimal(value) -> Decimal:
    if value is None:
        return DecimalZero
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return DecimalZero


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def resolve_budget_context(obra: Obra) -> BudgetContext:
    """Resolve monetary context (currency, TC, CAC) for a project."""
    presupuesto: Optional[Presupuesto] = (
        obra.presupuestos.filter_by(estado='confirmado')
        .order_by(Presupuesto.fecha.desc())
        .first()
    )
    if not presupuesto:
        presupuesto = (
            obra.presupuestos.order_by(Presupuesto.fecha.desc()).first()
            if hasattr(obra.presupuestos, 'order_by')
            else None
        )

    currency = 'ARS'
    tasa_usd = None
    indice_cac = None
    total_currency = DecimalZero

    if presupuesto:
        currency = (presupuesto.currency or 'ARS').upper()
        tasa_usd = _as_decimal(presupuesto.tasa_usd_venta) or None
        indice_cac = _as_decimal(presupuesto.indice_cac_valor) or None
        total_currency = _as_decimal(
            presupuesto.total_con_iva or presupuesto.total_sin_iva
        )
    else:
        total_currency = _as_decimal(obra.presupuesto_total)

    if currency == 'USD':
        amount_ars = total_currency * (tasa_usd or Decimal('1'))
    else:
        amount_ars = total_currency

    return BudgetContext(
        amount_ars=_quantize_money(amount_ars),
        amount_currency=_quantize_money(total_currency),
        currency=currency,
        tasa_usd=tasa_usd,
        indice_cac=indice_cac,
    )


def compute_task_progress(obra: Obra) -> Decimal:
    """Compute progress suggested from tasks only."""
    etapas = obra.etapas.all() if hasattr(obra.etapas, 'all') else list(obra.etapas)
    total_etapas = len(etapas)
    if total_etapas == 0:
        return DecimalZero

    peso_etapa = DecimalOneHundred / Decimal(str(total_etapas))
    progreso = DecimalZero

    for etapa in etapas:
        tareas = etapa.tareas.all() if hasattr(etapa.tareas, 'all') else list(etapa.tareas)
        if tareas:
            total_tareas = Decimal(str(len(tareas)))
            completadas = Decimal(
                str(sum(1 for tarea in tareas if tarea.estado == 'completada'))
            )
            if total_tareas > 0:
                progreso += (completadas / total_tareas) * peso_etapa
        elif etapa.estado == 'finalizada':
            progreso += peso_etapa

    return progreso.quantize(Decimal('0.01'))


def certification_totals(obra: Obra) -> Dict[str, Decimal]:
    """Return summary totals (certified, paid, pending)."""
    approved = obra.work_certifications.filter_by(estado='aprobada')
    borradores = obra.work_certifications.filter(WorkCertification.estado == 'borrador')

    total_cert_ars = sum((_as_decimal(c.monto_certificado_ars) for c in approved), DecimalZero)
    total_cert_usd = sum((_as_decimal(c.monto_certificado_usd) for c in approved), DecimalZero)

    total_borrador_ars = sum((_as_decimal(c.monto_certificado_ars) for c in borradores), DecimalZero)

    pagos_confirmados = (
        obra.work_payments.filter_by(estado='confirmado')
        if hasattr(obra.work_payments, 'filter_by')
        else []
    )
    total_pagado_ars = sum((p.monto_equivalente_ars for p in pagos_confirmados), DecimalZero)
    total_pagado_usd = sum((p.monto_equivalente_usd for p in pagos_confirmados), DecimalZero)

    return {
        'certificado_ars': _quantize_money(total_cert_ars),
        'certificado_usd': _quantize_money(total_cert_usd),
        'borrador_ars': _quantize_money(total_borrador_ars),
        'pagado_ars': _quantize_money(total_pagado_ars),
        'pagado_usd': _quantize_money(total_pagado_usd),
    }


def pending_percentage(obra: Obra) -> Tuple[Decimal, Decimal, Decimal]:
    """Return (approved, borrador, suggested)."""
    approved = obra.work_certifications.filter_by(estado='aprobada')
    borradores = obra.work_certifications.filter(WorkCertification.estado == 'borrador')

    pct_aprobado = sum((_as_decimal(c.porcentaje_avance) for c in approved), DecimalZero)
    pct_borrador = sum((_as_decimal(c.porcentaje_avance) for c in borradores), DecimalZero)

    progreso_tareas = compute_task_progress(obra)
    sugerido = progreso_tareas - pct_aprobado - pct_borrador
    if sugerido < DecimalZero:
        sugerido = DecimalZero

    remaining = DecimalOneHundred - pct_aprobado - pct_borrador
    if sugerido > remaining:
        sugerido = remaining

    return (
        pct_aprobado.quantize(Decimal('0.01')),
        pct_borrador.quantize(Decimal('0.01')),
        sugerido.quantize(Decimal('0.01')),
    )


def build_pending_entries(obra: Obra) -> List[Dict]:
    """Build rows for the pending tab (borradores + suggestion)."""
    pending_rows: List[Dict] = []
    context = resolve_budget_context(obra)

    borradores = (
        obra.work_certifications.filter(WorkCertification.estado == 'borrador')
        .order_by(WorkCertification.created_at.desc())
        .all()
    )

    for cert in borradores:
        pending_rows.append(
            {
                'id': cert.id,
                'tipo': 'borrador',
                'periodo': (cert.periodo_desde, cert.periodo_hasta),
                'porcentaje': _as_decimal(cert.porcentaje_avance),
                'monto_ars': _as_decimal(cert.monto_certificado_ars),
                'monto_usd': _as_decimal(cert.monto_certificado_usd),
                'created_at': cert.created_at,
            }
        )

    _, _, sugerido = pending_percentage(obra)
    if sugerido > DecimalZero:
        monto_currency = _quantize_money((context.amount_currency * sugerido) / DecimalOneHundred)
        if context.currency == 'USD':
            monto_usd = monto_currency
            monto_ars = _quantize_money(monto_currency * (context.tasa_usd or Decimal('1')))
        else:
            monto_ars = monto_currency
            monto_usd = _quantize_money(
                monto_currency / (context.tasa_usd or Decimal('1')) if context.tasa_usd else DecimalZero
            )
        pending_rows.append(
            {
                'id': None,
                'tipo': 'sugerido',
                'periodo': None,
                'porcentaje': sugerido,
                'monto_ars': monto_ars,
                'monto_usd': monto_usd,
                'context_currency': context.currency,
            }
        )

    return pending_rows


def approved_entries(obra: Obra) -> List[Dict]:
    registros = (
        obra.work_certifications.filter_by(estado='aprobada')
        .order_by(WorkCertification.approved_at.desc().nullslast(), WorkCertification.created_at.desc())
        .all()
    )
    rows: List[Dict] = []
    for cert in registros:
        pagos = cert.payments.filter(WorkPayment.estado == 'confirmado').all()
        monto_pagado_ars = sum((p.monto_equivalente_ars for p in pagos), DecimalZero)
        monto_pagado_usd = sum((p.monto_equivalente_usd for p in pagos), DecimalZero)
        rows.append(
            {
                'id': cert.id,
                'periodo': (cert.periodo_desde, cert.periodo_hasta),
                'porcentaje': _as_decimal(cert.porcentaje_avance),
                'monto_ars': _as_decimal(cert.monto_certificado_ars),
                'monto_usd': _as_decimal(cert.monto_certificado_usd),
                'pagado_ars': _quantize_money(monto_pagado_ars),
                'pagado_usd': _quantize_money(monto_pagado_usd),
                'saldo_ars': _quantize_money(_as_decimal(cert.monto_certificado_ars) - monto_pagado_ars),
                'saldo_usd': _quantize_money(_as_decimal(cert.monto_certificado_usd) - monto_pagado_usd),
                'estado': cert.estado,
                'aprobada_en': cert.approved_at or cert.created_at,
            }
        )
    return rows


def create_certification(
    obra: Obra,
    usuario,
    porcentaje: Decimal,
    periodo: Optional[Tuple[Optional[date], Optional[date]]] = None,
    notas: Optional[str] = None,
    aprobar: bool = True,
    fuente: str = 'tareas',
) -> WorkCertification:
    """Create and persist a certification."""
    context = resolve_budget_context(obra)

    pct = _as_decimal(porcentaje)
    if pct <= DecimalZero:
        raise ValueError('El porcentaje debe ser mayor a cero.')

    pct_aprobado, pct_borrador, _ = pending_percentage(obra)
    if pct_aprobado + pct_borrador + pct > DecimalOneHundred:
        raise ValueError('El porcentaje supera el 100% disponible.')

    monto_currency = (context.amount_currency * pct) / DecimalOneHundred
    monto_currency = _quantize_money(monto_currency)

    if context.currency == 'USD':
        monto_usd = monto_currency
        monto_ars = _quantize_money(monto_currency * (context.tasa_usd or Decimal('1')))
    else:
        monto_ars = monto_currency
        monto_usd = (
            _quantize_money(monto_currency / (context.tasa_usd or Decimal('1'))) if context.tasa_usd else DecimalZero
        )

    certificacion = WorkCertification(
        obra_id=obra.id,
        organizacion_id=obra.organizacion_id,
        periodo_desde=periodo[0] if periodo else None,
        periodo_hasta=periodo[1] if periodo else None,
        porcentaje_avance=pct,
        monto_certificado_ars=monto_ars,
        monto_certificado_usd=monto_usd,
        moneda_base=context.currency,
        tc_usd=context.tasa_usd,
        indice_cac=context.indice_cac,
        estado='aprobada' if aprobar else 'borrador',
        notas=notas,
        created_by_id=usuario.id,
    )
    if aprobar:
        certificacion.marcar_aprobada(usuario)

    db.session.add(certificacion)
    db.session.flush()

    resumen = {
        'fuente': fuente,
        'progreso_tareas': str(compute_task_progress(obra)),
        'presupuesto_base': str(context.amount_currency),
    }

    item = WorkCertificationItem(
        certificacion_id=certificacion.id,
        porcentaje_aplicado=pct,
        monto_ars=monto_ars,
        monto_usd=monto_usd,
        fuente_avance=fuente,
        resumen_avance=json_dumps(resumen),
    )
    db.session.add(item)

    return certificacion


def json_dumps(payload: Dict) -> str:
    import json

    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return '{}'


def register_payment(
    certificacion: Optional[WorkCertification],
    obra: Obra,
    usuario,
    monto: Decimal,
    metodo: str,
    moneda: str = 'ARS',
    fecha: Optional[date] = None,
    tc_usd: Optional[Decimal] = None,
    notas: Optional[str] = None,
    operario_id: Optional[int] = None,
    comprobante_url: Optional[str] = None,
) -> WorkPayment:
    monto = _quantize_money(_as_decimal(monto))
    if monto <= DecimalZero:
        raise ValueError('El monto debe ser mayor a cero.')

    payment = WorkPayment(
        certificacion_id=certificacion.id if certificacion else None,
        obra_id=obra.id,
        organizacion_id=obra.organizacion_id,
        operario_id=operario_id,
        metodo_pago=metodo,
        moneda=(moneda or 'ARS').upper(),
        monto=monto,
        tc_usd_pago=_as_decimal(tc_usd) if tc_usd else None,
        fecha_pago=fecha or date.today(),
        comprobante_url=comprobante_url,
        notas=notas,
        estado='confirmado',
        created_by_id=usuario.id,
    )
    db.session.add(payment)
    return payment


def pending_alerts(org_id: int) -> int:
    """Return count of certifications pending for more than 7 days."""
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    query = WorkCertification.query.filter(
        WorkCertification.organizacion_id == org_id,
        WorkCertification.estado == 'borrador',
        WorkCertification.created_at < seven_days_ago,
    )
    return query.count()
