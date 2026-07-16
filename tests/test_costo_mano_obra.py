# -*- coding: utf-8 -*-
"""Tests del servicio de costo empresa de mano de obra (Fase 2.0 IA presupuestos).

Verificacion clave: el motor reproduce la planilla real de Brenda (oficial
especializado, abril 2026, CABA) -> $12.205,79/hh con bono / $12.177,38 sin bono.
"""
from datetime import date
from decimal import Decimal

import pytest

from services.costo_mano_obra import (
    desglose_costo_hora, _linea_por_hora,
    resolver_estructura, resolver_basico_hora, costo_empresa_hora,
)


# --- Stubs livianos para tests puros del motor (sin DB) ---------------------

class _Linea:
    def __init__(self, concepto, grupo, tipo_calculo, valor, activo=True):
        self.concepto = concepto
        self.grupo = grupo
        self.tipo_calculo = tipo_calculo
        self.valor = Decimal(str(valor))
        self.activo = activo


class _Estructura:
    def __init__(self, lineas, horas_mensuales=176, horas_por_dia=8):
        self.lineas = lineas
        self.horas_mensuales = horas_mensuales
        self.horas_por_dia = horas_por_dia


def _lineas_planilla_brenda(con_bono=True):
    lineas = [
        _Linea('Presentismo', 'adicional_remunerativo', 'pct_hora_convenio', 20),
        _Linea('F.931', 'carga_social', 'pct_bruto', '58.74'),
        _Linea('Fondo de desempleo', 'carga_social', 'pct_bruto', 12),
        _Linea('SAC', 'carga_social', 'pct_bruto', '8.33'),
        _Linea('Vacaciones', 'carga_social', 'pct_bruto', '4.17'),
        _Linea('UOCRA', 'carga_social', 'monto_dia', '278.30'),
        _Linea('IERIC', 'carga_social', 'monto_mes', '15.90'),
        _Linea('Comida', 'adicional_no_remunerativo', 'monto_dia', '911.11'),
        _Linea('EPP', 'adicional_no_remunerativo', 'monto_mes', '130.91'),
    ]
    if con_bono:
        lineas.append(_Linea('Bono anual', 'adicional_no_remunerativo', 'monto_mes', 5000))
    return lineas


# --- Tests puros del motor ---------------------------------------------------

@pytest.mark.unit
def test_reproduce_planilla_brenda_con_bono():
    """Target real: oficial especializado $5.470/hh -> $12.206,20 (con bono)."""
    est = _Estructura(_lineas_planilla_brenda(con_bono=True))
    d = desglose_costo_hora(Decimal('5470'), est)
    assert d['bruto_hora'] == Decimal('6564.00')
    assert abs(d['costo_hora'] - Decimal('12206.20')) <= Decimal('0.50')


@pytest.mark.unit
def test_reproduce_planilla_brenda_sin_bono():
    """Target real sin bono: $12.177,79."""
    est = _Estructura(_lineas_planilla_brenda(con_bono=False))
    d = desglose_costo_hora(Decimal('5470'), est)
    assert abs(d['costo_hora'] - Decimal('12177.79')) <= Decimal('0.50')


@pytest.mark.unit
def test_pct_bruto_usa_bruto_no_basico():
    """Una carga pct_bruto se calcula sobre el bruto (basico + adicionales), no el basico."""
    est = _Estructura([
        _Linea('Presentismo', 'adicional_remunerativo', 'pct_hora_convenio', 100),  # bruto = 2x basico
        _Linea('Carga', 'carga_social', 'pct_bruto', 10),
    ])
    d = desglose_costo_hora(Decimal('1000'), est)
    assert d['bruto_hora'] == Decimal('2000.00')
    # carga = 10% de 2000 = 200 (no 10% de 1000 = 100)
    assert d['cargas_sociales'] == Decimal('200.00')
    assert d['costo_hora'] == Decimal('2200.00')


@pytest.mark.unit
def test_monto_periodicidades():
    """monto_dia /8, monto_mes /176, monto_anio /(176*12)."""
    est = _Estructura([], horas_mensuales=176, horas_por_dia=8)
    assert _linea_por_hora(_Linea('x', 'carga_social', 'monto_dia', 800), 0, 0, 176, 8) == Decimal('100')
    assert _linea_por_hora(_Linea('x', 'carga_social', 'monto_mes', 176), 0, 0, 176, 8) == Decimal('1')
    anio = _linea_por_hora(_Linea('x', 'carga_social', 'monto_anio', 2112), 0, 0, 176, 8)
    assert anio == Decimal('1')  # 2112 / (176*12)


@pytest.mark.unit
def test_escala_con_basico():
    """Al duplicar el basico, las partes proporcionales (bruto, cargas %) escalan."""
    lineas = [
        _Linea('Presentismo', 'adicional_remunerativo', 'pct_hora_convenio', 20),
        _Linea('F931', 'carga_social', 'pct_bruto', 50),
    ]
    d1 = desglose_costo_hora(Decimal('1000'), _Estructura(list(lineas)))
    d2 = desglose_costo_hora(Decimal('2000'), _Estructura(list(lineas)))
    # sin montos fijos, todo es proporcional -> el costo se duplica exacto
    assert d2['costo_hora'] == d1['costo_hora'] * 2


@pytest.mark.unit
def test_sin_estructura_devuelve_basico():
    """Degradacion elegante: sin estructura, el costo empresa == basico."""
    d = desglose_costo_hora(Decimal('5470'), None)
    assert d['costo_hora'] == Decimal('5470.00')
    assert d.get('sin_estructura') is True


@pytest.mark.unit
def test_lineas_inactivas_no_computan():
    """Una linea activo=False no suma."""
    est = _Estructura([
        _Linea('Presentismo', 'adicional_remunerativo', 'pct_hora_convenio', 20),
        _Linea('Extra', 'carga_social', 'pct_bruto', 100, activo=False),
    ])
    d = desglose_costo_hora(Decimal('1000'), est)
    assert d['cargas_sociales'] == Decimal('0.00')
    assert d['costo_hora'] == Decimal('1200.00')


# --- Tests con DB (resolvers + fallback global) ------------------------------

@pytest.mark.integration
def test_resolver_fallback_global_y_override(app):
    """Global consultable por cualquier org; una estructura de org pisa la global."""
    from extensions import db
    from models.budgets import CategoriaJornal
    from models.mano_obra import EstructuraRecargosMO, RecargoMOLinea

    with app.app_context():
        # Limpiar posibles restos de otros tests
        RecargoMOLinea.query.delete()
        EstructuraRecargosMO.query.delete()
        CategoriaJornal.query.filter(CategoriaJornal.codigo == 'oficial_esp').delete()
        db.session.commit()

        # Basico global
        db.session.add(CategoriaJornal(
            organizacion_id=None, nombre='Oficial Esp', codigo='oficial_esp',
            valor_hora_convenio=Decimal('1000'), precio_jornal=Decimal('8000'),
            fuente='uocra', vigencia_desde=date(2026, 4, 1), activo=True,
        ))
        # Estructura global: presentismo 20%
        eg = EstructuraRecargosMO(organizacion_id=None, nombre='Global', zona='CABA',
                                  vigencia_desde=date(2026, 4, 1), activo=True)
        eg.lineas.append(RecargoMOLinea(orden=1, concepto='Presentismo',
                                        grupo='adicional_remunerativo',
                                        tipo_calculo='pct_hora_convenio', valor=Decimal('20')))
        db.session.add(eg)
        db.session.commit()

        # Org 999 sin datos propios -> usa global (costo = 1000 * 1.2 = 1200)
        assert costo_empresa_hora('oficial_esp', organizacion_id=999, zona='CABA',
                                  fecha=date(2026, 4, 1)) == Decimal('1200.00')

        # Org 999 con estructura propia (presentismo 50%) -> pisa la global
        eo = EstructuraRecargosMO(organizacion_id=999, nombre='Org999', zona='CABA',
                                  vigencia_desde=date(2026, 4, 1), activo=True)
        eo.lineas.append(RecargoMOLinea(orden=1, concepto='Presentismo',
                                        grupo='adicional_remunerativo',
                                        tipo_calculo='pct_hora_convenio', valor=Decimal('50')))
        db.session.add(eo)
        db.session.commit()

        est = resolver_estructura(organizacion_id=999, zona='CABA', fecha=date(2026, 4, 1))
        assert est.organizacion_id == 999
        assert costo_empresa_hora('oficial_esp', organizacion_id=999, zona='CABA',
                                  fecha=date(2026, 4, 1)) == Decimal('1500.00')

        # Cleanup
        RecargoMOLinea.query.delete()
        EstructuraRecargosMO.query.delete()
        CategoriaJornal.query.filter(CategoriaJornal.codigo == 'oficial_esp').delete()
        db.session.commit()
