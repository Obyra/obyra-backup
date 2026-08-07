# -*- coding: utf-8 -*-
"""Tests del breakdown por rubro del analizador deterministico (keywords).

Regresion de un bug medido en el pres 70 (2026-08-07): `breakdown_rubro` se armaba
con `rubro_sugerido`, que se anula A PROPOSITO cuando el item ya esta en la etapa
correcta (no hay cambio que proponer). Resultado: los items MEJOR clasificados se
contaban como "(Sin clasificar)". Reportaba 110 de 192 sin clasificar cuando los
reales eran <=56. El breakdown ahora va por `rubro_detectado`.
"""
import pytest

from services.analisis_ia_presupuesto import _mejor_regla
from services.analisis_ia_presupuesto import analizar_items_con_ia

DESC_CLASIFICABLE = 'Mamposteria de ladrillo hueco 12x18x33'


def _item(descripcion, unidad='m2', etapa=None):
    return {'id': 1, 'descripcion': descripcion, 'unidad': unidad,
            'cantidad': 10, 'etapa_nombre': etapa}


@pytest.mark.unit
def test_item_en_etapa_correcta_no_cuenta_como_sin_clasificar(app):
    """El corazon del bug: mismo item, misma confianza, distinta etapa cargada.

    Con la etapa ya alineada `rubro_sugerido` queda en None (correcto: no hay
    cambio que aplicar), pero el item ESTA clasificado y el breakdown tiene que
    reflejarlo.
    """
    with app.app_context():
        regla, _ = _mejor_regla(DESC_CLASIFICABLE, 'm2', None)
        rubro = regla['rubro']

        sin_etapa = analizar_items_con_ia([_item(DESC_CLASIFICABLE)])
        con_etapa = analizar_items_con_ia([_item(DESC_CLASIFICABLE, etapa=regla['etapa'])])

        # El breakdown es el mismo en los dos casos: el item esta clasificado.
        assert sin_etapa['breakdown_rubro'] == {rubro: 1}
        assert con_etapa['breakdown_rubro'] == {rubro: 1}
        assert '(Sin clasificar)' not in con_etapa['breakdown_rubro']

        # Y la semantica de rubro_sugerido NO cambio: sigue siendo None cuando no
        # hay cambio que proponer (de eso dependen aplicar-analisis-ia y el
        # aprendizaje; si esto se rompe se empiezan a aplicar cambios vacios).
        assert con_etapa['items'][0]['sugerencias']['rubro_sugerido'] is None
        assert con_etapa['items'][0]['sugerencias']['rubro_detectado'] == rubro


@pytest.mark.unit
def test_sin_clasificar_sigue_apareciendo_cuando_es_real(app):
    """La contracara: un item que no matchea ninguna regla SI tiene que caer ahi."""
    with app.app_context():
        r = analizar_items_con_ia([_item('Provision de zarandajas de qwerty', unidad='u')])
        sug = r['items'][0]['sugerencias']
        assert sug['regla_id'] is None
        assert sug['rubro_detectado'] is None
        assert r['breakdown_rubro'] == {'(Sin clasificar)': 1}


@pytest.mark.unit
def test_breakdown_rubro_suma_el_total(app):
    """Invariante: todo item cae en exactamente un balde."""
    with app.app_context():
        items = [
            _item(DESC_CLASIFICABLE),
            _item(DESC_CLASIFICABLE, etapa='Mamposteria'),
            _item('Provision de zarandajas de qwerty', unidad='u'),
        ]
        for i, it in enumerate(items):
            it['id'] = i
        r = analizar_items_con_ia(items)
        assert sum(r['breakdown_rubro'].values()) == r['total_items'] == len(items)
        assert sum(r['breakdown_confianza'].values()) == len(items)
