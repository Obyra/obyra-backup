# -*- coding: utf-8 -*-
"""Costo empresa de mano de obra (Fase 2.0 IA presupuestos).

Calcula el costo/hora y costo/jornal de una categoria de MO combinando:
  - el basico (hora convenio) de `CategoriaJornal`, y
  - una `EstructuraRecargosMO` (lineas de recargo parametrizadas).

Diseno normalizado: el costo NO se persiste; se computa on-demand. Al actualizar
el basico (paritaria) o una linea de recargo, todo recalcula solo.

Resolucion multi-tenant (fallback global): primero busca datos de la org; si no
hay, cae a la base global (organizacion_id IS NULL).

Formula (todo llevado a $/hora):
  bruto_hora = basico_hora + SUM(adicional_remunerativo)
  costo_hora = bruto_hora + SUM(carga_social) + SUM(adicional_no_remunerativo)

donde cada linea se normaliza a $/hora segun su tipo_calculo:
  pct_hora_convenio -> valor% * basico_hora
  pct_bruto         -> valor% * bruto_hora
  monto_hora        -> valor
  monto_dia         -> valor / horas_por_dia
  monto_mes         -> valor / horas_mensuales
  monto_anio        -> valor / (horas_mensuales * 12)
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from extensions import db


CENT = Decimal('0.01')


def _d(v):
    if v is None:
        return Decimal('0')
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal('0')


def _q(v):
    return _d(v).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Resolvers de vigencia + fallback global
# ---------------------------------------------------------------------------

def resolver_estructura(organizacion_id=None, zona='CABA', fecha=None):
    """Devuelve la EstructuraRecargosMO activa/vigente. Org propia pisa la global."""
    from models.mano_obra import EstructuraRecargosMO
    fecha = fecha or date.today()

    def _query(oid):
        q = EstructuraRecargosMO.query.filter(
            EstructuraRecargosMO.activo.is_(True),
            EstructuraRecargosMO.vigencia_desde <= fecha,
            db.or_(EstructuraRecargosMO.vigencia_hasta.is_(None),
                   EstructuraRecargosMO.vigencia_hasta >= fecha),
        )
        if oid is None:
            q = q.filter(EstructuraRecargosMO.organizacion_id.is_(None))
        else:
            q = q.filter(EstructuraRecargosMO.organizacion_id == oid)
        if zona:
            q = q.filter(EstructuraRecargosMO.zona == zona)
        return q.order_by(EstructuraRecargosMO.vigencia_desde.desc()).first()

    if organizacion_id is not None:
        propia = _query(organizacion_id)
        if propia:
            return propia
    return _query(None)


def resolver_basico_hora(categoria_codigo, organizacion_id=None, fecha=None):
    """Devuelve (basico_hora Decimal, CategoriaJornal) para el codigo dado.

    Prefiere valor_hora_convenio; si es NULL, cae a precio_jornal/8. Org propia
    pisa la global. `categoria_codigo` matchea contra CategoriaJornal.codigo.
    """
    from models.budgets import CategoriaJornal
    fecha = fecha or date.today()

    def _query(oid):
        q = CategoriaJornal.query.filter(
            CategoriaJornal.activo.is_(True),
            CategoriaJornal.codigo == categoria_codigo,
        )
        if oid is None:
            q = q.filter(CategoriaJornal.organizacion_id.is_(None))
        else:
            q = q.filter(CategoriaJornal.organizacion_id == oid)
        return q.order_by(CategoriaJornal.vigencia_desde.desc().nullslast()).first()

    cat = None
    if organizacion_id is not None:
        cat = _query(organizacion_id)
    if cat is None:
        cat = _query(None)
    if cat is None:
        return Decimal('0'), None

    if cat.valor_hora_convenio is not None:
        basico = _d(cat.valor_hora_convenio)
    else:
        basico = _d(cat.precio_jornal) / Decimal('8')
    return basico, cat


# ---------------------------------------------------------------------------
# Normalizacion de una linea a $/hora
# ---------------------------------------------------------------------------

def _linea_por_hora(linea, basico_hora, bruto_hora, horas_mensuales, horas_por_dia):
    valor = _d(linea.valor)
    tc = linea.tipo_calculo
    if tc == 'pct_hora_convenio':
        return basico_hora * valor / Decimal('100')
    if tc == 'pct_bruto':
        return bruto_hora * valor / Decimal('100')
    if tc == 'monto_hora':
        return valor
    if tc == 'monto_dia':
        hpd = Decimal(str(horas_por_dia or 8)) or Decimal('8')
        return valor / hpd
    if tc == 'monto_mes':
        hm = Decimal(str(horas_mensuales or 176)) or Decimal('176')
        return valor / hm
    if tc == 'monto_anio':
        hm = Decimal(str(horas_mensuales or 176)) or Decimal('176')
        return valor / (hm * Decimal('12'))
    return Decimal('0')


# ---------------------------------------------------------------------------
# Calculo principal
# ---------------------------------------------------------------------------

def desglose_costo_hora(basico_hora, estructura):
    """Motor puro: dado un basico_hora (Decimal) y una EstructuraRecargosMO,
    devuelve un dict con el desglose y el costo_hora final (sin redondear las
    parciales, redondeo solo al final)."""
    basico_hora = _d(basico_hora)
    if estructura is None:
        # Sin estructura: el costo empresa es el basico liso (degradacion elegante).
        return {
            'basico_hora': _q(basico_hora),
            'bruto_hora': _q(basico_hora),
            'costo_hora': _q(basico_hora),
            'adicionales_remun': Decimal('0'),
            'cargas_sociales': Decimal('0'),
            'adicionales_no_remun': Decimal('0'),
            'lineas': [],
            'sin_estructura': True,
        }

    hm = estructura.horas_mensuales or 176
    hpd = estructura.horas_por_dia or 8
    lineas = [l for l in estructura.lineas if l.activo]

    # Paso 1: bruto = basico + adicionales remunerativos
    add_remun = Decimal('0')
    detalle = []
    for l in lineas:
        if l.grupo == 'adicional_remunerativo':
            aporte = _linea_por_hora(l, basico_hora, basico_hora, hm, hpd)
            add_remun += aporte
            detalle.append((l, aporte))
    bruto_hora = basico_hora + add_remun

    # Paso 2: cargas (sobre bruto) + adicionales no remunerativos
    cargas = Decimal('0')
    no_remun = Decimal('0')
    for l in lineas:
        if l.grupo == 'carga_social':
            aporte = _linea_por_hora(l, basico_hora, bruto_hora, hm, hpd)
            cargas += aporte
            detalle.append((l, aporte))
        elif l.grupo == 'adicional_no_remunerativo':
            aporte = _linea_por_hora(l, basico_hora, bruto_hora, hm, hpd)
            no_remun += aporte
            detalle.append((l, aporte))

    costo_hora = bruto_hora + cargas + no_remun

    return {
        'basico_hora': _q(basico_hora),
        'bruto_hora': _q(bruto_hora),
        'costo_hora': _q(costo_hora),
        'adicionales_remun': _q(add_remun),
        'cargas_sociales': _q(cargas),
        'adicionales_no_remun': _q(no_remun),
        'lineas': [
            {'concepto': l.concepto, 'grupo': l.grupo, 'tipo_calculo': l.tipo_calculo,
             'valor': float(l.valor), 'aporte_hora': float(_q(aporte))}
            for l, aporte in detalle
        ],
    }


def costo_empresa_hora(categoria_codigo, organizacion_id=None, zona='CABA', fecha=None,
                       estructura=None):
    """Costo empresa por HORA de una categoria. Decimal redondeado a centavos."""
    basico, _cat = resolver_basico_hora(categoria_codigo, organizacion_id, fecha)
    est = estructura if estructura is not None else resolver_estructura(organizacion_id, zona, fecha)
    return desglose_costo_hora(basico, est)['costo_hora']


def costo_empresa_jornal(categoria_codigo, organizacion_id=None, zona='CABA', fecha=None,
                         estructura=None):
    """Costo empresa por JORNAL (hora * horas_por_dia de la estructura)."""
    est = estructura if estructura is not None else resolver_estructura(organizacion_id, zona, fecha)
    hpd = Decimal(str((est.horas_por_dia if est else 8) or 8))
    basico, _cat = resolver_basico_hora(categoria_codigo, organizacion_id, fecha)
    costo_h = desglose_costo_hora(basico, est)['costo_hora']
    return _q(costo_h * hpd)


def desglose_categoria(categoria_codigo, organizacion_id=None, zona='CABA', fecha=None):
    """Desglose completo (para UI/auditoria): basico, bruto, cargas, costo/hora y /jornal."""
    basico, cat = resolver_basico_hora(categoria_codigo, organizacion_id, fecha)
    est = resolver_estructura(organizacion_id, zona, fecha)
    d = desglose_costo_hora(basico, est)
    hpd = Decimal(str((est.horas_por_dia if est else 8) or 8))
    d['categoria_codigo'] = categoria_codigo
    d['categoria_nombre'] = cat.nombre if cat else categoria_codigo
    d['costo_jornal'] = _q(d['costo_hora'] * hpd)
    d['estructura_id'] = est.id if est else None
    d['estructura_nombre'] = est.nombre if est else None
    return d
