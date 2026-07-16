# -*- coding: utf-8 -*-
"""Tests del clasificador LLM de items (Fase 2.3).

La llamada real a la API se mockea (no gasta creditos). Se validan:
  - catalogo de reglas validas,
  - parseo + constrain del output del LLM (ids inventados -> null),
  - fallback por keywords,
  - degradacion elegante.
"""
import pytest

from services import clasificador_llm as CLL


@pytest.mark.unit
def test_catalogo_incluye_reglas_nuevas(app):
    with app.app_context():
        cat = CLL.catalogo_reglas()
        ids = {c['id'] for c in cat}
        assert 'dintel_hormigon' in ids
        assert 'contrapiso_alivianado' in ids
        # las nuevas tienen coeficientes cargados
        dintel = next(c for c in cat if c['id'] == 'dintel_hormigon')
        assert dintel['tiene_coef'] is True


@pytest.mark.unit
def test_solo_con_coeficientes_filtra(app):
    with app.app_context():
        con = CLL.catalogo_reglas(solo_con_coeficientes=True)
        ids = {c['id'] for c in con}
        assert 'dintel_hormigon' in ids
        # una regla sin coeficientes NO aparece
        assert 'cartel_obra' not in ids


@pytest.mark.unit
def test_llm_parse_y_constrain(app, monkeypatch):
    """El LLM parsea bien y descarta ids inventados (constrained)."""
    with app.app_context():
        def _fake_api(system, user):
            return [
                {'indice': 0, 'regla_id': 'dintel_hormigon', 'confianza': 0.92},
                {'indice': 1, 'regla_id': 'regla_inventada_xyz', 'confianza': 0.8},  # invalida
                {'indice': 2, 'regla_id': None, 'confianza': 0.1},
            ]
        monkeypatch.setattr(CLL, '_llamar_api', _fake_api)

        items = [
            {'descripcion': 'Dinteles sobre carpinterias', 'unidad': 'ml'},
            {'descripcion': 'Item raro', 'unidad': 'u'},
            {'descripcion': 'Otro', 'unidad': 'gl'},
        ]
        res = CLL._clasificar_llm(items, CLL.catalogo_reglas())
        assert res[0]['regla_id'] == 'dintel_hormigon'
        assert res[0]['confianza'] == pytest.approx(0.92)
        assert res[1]['regla_id'] is None   # id inventado -> descartado
        assert res[2]['regla_id'] is None


@pytest.mark.unit
def test_confianza_clamp(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(CLL, '_llamar_api',
                            lambda s, u: [{'indice': 0, 'regla_id': 'dintel_hormigon', 'confianza': 1.9}])
        res = CLL._clasificar_llm([{'descripcion': 'x', 'unidad': 'ml'}], CLL.catalogo_reglas())
        assert res[0]['confianza'] == 1.0  # clamp a [0,1]


@pytest.mark.integration
def test_fallback_keyword(app):
    """forzar_keyword clasifica sin LLM y marca fuente='keyword'."""
    with app.app_context():
        items = [
            {'descripcion': 'DINTELES SOBRE CARPINTERÍAS', 'unidad': 'ml'},
            {'descripcion': 'CONTRAPISO ALIVIANADO CON PENDIENTE', 'unidad': 'm3'},
        ]
        res = CLL.clasificar_items(items, forzar_keyword=True)
        assert res[0]['fuente'] == 'keyword'
        assert res[0]['regla_id'] == 'dintel_hormigon'
        assert res[0]['tiene_coeficientes'] is True
        assert res[1]['regla_id'] == 'contrapiso_alivianado'


@pytest.mark.unit
def test_llm_no_disponible_sin_key(app, monkeypatch):
    with app.app_context():
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        assert CLL.llm_disponible() is False
