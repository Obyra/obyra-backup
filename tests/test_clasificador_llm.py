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
def test_prompt_no_baja_del_minimo_cacheable(app):
    """Guarda del prompt caching: Haiku 4.5 tiene el minimo cacheable mas alto de
    todos los modelos (4096 tokens). Si el system prompt baja de ahi la API deja de
    cachear SIN dar error (cache_creation_input_tokens vuelve 0) y se paga todo full.

    Medido contra claude-haiku-4-5 con count_tokens: 12.255 chars = 5.215 tokens
    (~2,35 chars/token). El piso de 9.625 chars es el equivalente a 4096 tokens.
    Se usan chars y no tokens para no pegarle a la API desde CI.
    """
    import json

    with app.app_context():
        prefijo = len(CLL._system_prompt(CLL.catalogo_reglas())) + len(json.dumps(CLL._TOOL))
        assert prefijo >= 9625, (
            f'El prefijo cacheable bajo a {prefijo} chars (~{round(prefijo / 2.35)} '
            f'tokens), por debajo del minimo de 4096 de Haiku 4.5. El cache se apaga '
            f'en silencio. Volve a medir con count_tokens antes de recortar el catalogo.'
        )


@pytest.mark.unit
def test_prompt_incluye_unidades_y_excluyentes(app):
    """Los dos campos que se sumaron al catalogo tienen que llegar al modelo:
    unidades alternativas (senal positiva) y excluyentes (senal negativa)."""
    with app.app_context():
        sp = CLL._system_prompt(CLL.catalogo_reglas())
        assert 'acepta:' in sp
        assert 'NO aplica si dice:' in sp
        # revoque_grueso excluye 'yeso'; tiene que verse en su linea
        linea = next(x for x in sp.split('\n') if x.startswith('- revoque_grueso '))
        assert 'NO aplica si dice:' in linea


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
