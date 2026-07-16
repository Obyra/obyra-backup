# -*- coding: utf-8 -*-
"""Tests del pipeline IA de presupuesto (Fase 2.4) — scoring verde/amarillo/rojo."""
import pytest

from services.pipeline_presupuesto_ia import _color


def _recs(n_con_precio, n_sin_precio=0, n_tc=0):
    r = [{'precio': 100, 'requiere_tc': False} for _ in range(n_con_precio)]
    r += [{'precio': 0, 'requiere_tc': False} for _ in range(n_sin_precio)]
    r += [{'precio': 0, 'requiere_tc': True} for _ in range(n_tc)]
    return r


@pytest.mark.unit
def test_verde_alta_confianza_todo_priceado():
    assert _color(0.95, True, _recs(4)) == 'verde'


@pytest.mark.unit
def test_amarillo_confianza_media():
    # confianza < 0.85 pero regla con coef y todo priceado -> amarillo
    assert _color(0.75, True, _recs(4)) == 'amarillo'


@pytest.mark.unit
def test_amarillo_algun_recurso_sin_precio():
    # alta confianza pero 1 de 4 sin precio -> amarillo (cobertura 0.75)
    assert _color(0.95, True, _recs(3, n_sin_precio=1)) == 'amarillo'


@pytest.mark.unit
def test_rojo_sin_coeficientes():
    assert _color(0.9, False, []) == 'rojo'


@pytest.mark.unit
def test_rojo_baja_confianza():
    assert _color(0.3, True, _recs(4)) == 'rojo'


@pytest.mark.unit
def test_rojo_mayoria_sin_precio():
    assert _color(0.9, True, _recs(1, n_sin_precio=3)) == 'rojo'


@pytest.mark.unit
def test_requiere_tc_no_cuenta_como_sin_precio():
    # un recurso USD (requiere_tc) no rompe la cobertura
    assert _color(0.95, True, _recs(3, n_tc=1)) == 'verde'
