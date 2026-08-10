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


@pytest.mark.unit
def test_unidad_incompatible_es_distinto_de_no_saber():
    """El guard de unidad apaga el precio A PROPOSITO cuando el item viene en una
    unidad que no es la de la receta (item en m3 vs receta en m2): multiplicar ahi
    da totales absurdos. Eso NO es lo mismo que "la IA no supo que era", y la
    pantalla lo distingue con `unidad_incompatible` + `unidad_regla`.

    Sin ese par de campos los dos casos son un $0 indistinguible. En el
    presupuesto 70 eran 20 items: reconocidos, con regla valida, en $0 y sin una
    palabra de explicacion (ej. 'Tabiques' en m3 contra
    mamposteria_ladrillo_hueco_12, que se mide en m2).
    """
    from services.pipeline_presupuesto_ia import _unidad_item_compatible

    # m3 contra una receta en m2: incompatible -> el pipeline apaga el precio.
    assert _unidad_item_compatible('m3', 'm2') is False
    # ml contra una receta en m2 (AISLACION HIDROFUGA vs azotado_hidrofugo).
    assert _unidad_item_compatible('ml', 'm2') is False
    # Sinonimos de la MISMA unidad no son incompatibles.
    assert _unidad_item_compatible('m2', 'm²') is True
    assert _unidad_item_compatible('un', 'u') is True
