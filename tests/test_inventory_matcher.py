# -*- coding: utf-8 -*-
"""Tests del matcher de inventario (services/inventory_matcher.py).

Contexto: `buscar_item_inventario_por_nombre()` solo se usaba desde la
Calculadora IA, donde las descripciones son limpias ("Cemento Portland 50kg").
Al intentar reusarlo para pliegos Excel producia falsos positivos masivos: su
paso 3 tomaba las primeras 3 palabras de mas de 2 caracteres -que en un pliego
son SIEMPRE "provision", "colocacion", "ejecucion"- y devolvia el primer item de
inventario que contuviera alguna, con un `.first()` sin `order_by`.

    "Provision y colocacion de hormigon H21"  ->  "Provision de agua obra"

Un vinculo equivocado es peor que ninguno: gestionar-materiales reserva stock
real contra ese item_inventario_id. Estos tests fijan el comportamiento nuevo:
conservador, determinista, y que prefiere no vincular antes que arriesgar.

No necesitan DB: la parte pura del matcher trabaja sobre un indice en memoria.
"""
import pytest

from services.inventory_matcher import (
    _tokens_utiles,
    evaluar_candidatos,
    vincular_item_inventario,
    _MIN_COBERTURA,
    _GAP_MIN,
)


# Inventario tipico de una constructora chica, con las trampas que importan:
#  - "Provision de agua obra" empieza con la muletilla que rompia el matcher viejo
#  - H21/H17 y 8mm/12mm son variantes que un pliego suele no desambiguar
#  - la pintura esta en 'balde' y el ladrillo en 'un': unidades que no convierten
_INVENTARIO = [
    (1,  "Provisión de agua obra",     "gl"),
    (2,  "Cemento Portland 50kg",      "bolsa"),
    (3,  "Hormigón H21 elaborado",     "m3"),
    (4,  "Hormigón H17 elaborado",     "m3"),
    (5,  "Hierro aletado 8mm",         "kg"),
    (6,  "Hierro aletado 12mm",        "kg"),
    (7,  "Ladrillo hueco 12x18x33",    "un"),
    (8,  "Ladrillo común",             "un"),
    (9,  "Arena fina",                 "m3"),
    (10, "Cal hidratada 25kg",         "bolsa"),
    (11, "Membrana asfáltica 4mm",     "m2"),
    (12, "Pintura látex interior 20L", "balde"),
    (13, "Colocación de cerámicos",    "m2"),
    (14, "Caño PVC 110mm",             "ml"),
]


def _indice(items=None):
    """Arma el indice en memoria, igual que construir_indice_inventario() pero
    sin tocar la DB."""
    return [{'id': i, 'nombre': n, 'unidad': u, 'tokens': _tokens_utiles(n)}
            for (i, n, u) in (items or _INVENTARIO)]


@pytest.fixture
def indice():
    return _indice()


# ---------------------------------------------------------------- regresiones

def test_verbo_de_pliego_no_vincula_a_provision_de_agua(indice):
    """REGRESION del bug original: la muletilla 'Provisión' no puede arrastrar
    el match. Con el matcher viejo esto devolvia "Provisión de agua obra"."""
    inv_id, _score, _motivo = vincular_item_inventario(
        "Provisión y colocación de hormigón H21 elaborado para losas", "m3", indice)
    assert inv_id == 3, "debe vincular al H21, no al item que comparte la muletilla"


@pytest.mark.parametrize("descripcion,unidad", [
    ("Provisión y colocación de mampostería de ladrillo hueco 12cm", "m2"),
    ("Provisión de cartelería de obra según pliego", "un"),
    ("Ejecución de tareas varias de albañilería", "gl"),
])
def test_muletillas_solas_no_alcanzan_para_vincular(descripcion, unidad, indice):
    """Compartir solo verbos de pliego nunca debe producir un vinculo."""
    inv_id, _score, _motivo = vincular_item_inventario(descripcion, unidad, indice)
    assert inv_id != 1, f"'{descripcion}' no debe vincular a 'Provisión de agua obra'"


# ------------------------------------------------------------------- aciertos

@pytest.mark.parametrize("descripcion,unidad,esperado", [
    ("Provisión y colocación de hormigón H21 elaborado para losas", "m3", 3),
    ("Membrana asfáltica con aluminio 4mm en cubierta",             "m2", 11),
    ("Suministro y colocación de cañería PVC 110mm para desagüe",   "ml", 14),
    # nombres limpios estilo Calculadora IA: el camino que ya andaba
    ("Cemento Portland 50kg",                                    "bolsa", 2),
    ("Hierro aletado 8mm",                                          "kg", 5),
    ("Arena fina",                                                  "m3", 9),
])
def test_vincula_el_material_correcto(descripcion, unidad, esperado, indice):
    inv_id, score, motivo = vincular_item_inventario(descripcion, unidad, indice)
    assert inv_id == esperado
    assert motivo == 'ok'
    assert score >= _MIN_COBERTURA


# ----------------------------------------------------------------- abstenerse

@pytest.mark.parametrize("descripcion,unidad", [
    # texto compatible pero unidad que no convierte sin factor_conversion
    ("Pintura látex acrílico sobre paramentos interiores", "m2"),
    ("Provisión y colocación de mampostería de ladrillo hueco 12cm", "m2"),
])
def test_guard_de_unidad_impide_vincular(descripcion, unidad, indice):
    """m2 de pared no se reserva contra 'un' de ladrillo ni 'balde' de pintura."""
    inv_id, _score, _motivo = vincular_item_inventario(descripcion, unidad, indice)
    assert inv_id is None


def test_variante_ambigua_no_se_adivina(indice):
    """El pliego no dice el diametro: 8mm y 12mm empatan. Que lo resuelva una
    persona, no el orden de la tabla."""
    inv_id, _score, motivo = vincular_item_inventario(
        "Provisión y montaje de armadura de hierro aletado ADN 420", "kg", indice)
    assert inv_id is None
    assert motivo in ('ambiguo', 'sin_candidatos')


def test_sin_relacion_no_vincula(indice):
    inv_id, _score, motivo = vincular_item_inventario(
        "Excavación manual para fundaciones", "m3", indice)
    assert inv_id is None
    assert motivo == 'sin_candidatos'


def test_descripcion_vacia_no_rompe(indice):
    for vacia in (None, '', '   ', 'de la y'):
        inv_id, score, motivo = vincular_item_inventario(vacia, 'm2', indice)
        assert inv_id is None
        assert score == 0.0
        assert motivo == 'descripcion_sin_tokens'


def test_inventario_vacio_no_rompe():
    inv_id, _score, motivo = vincular_item_inventario("Cemento Portland 50kg", "bolsa", [])
    assert inv_id is None
    assert motivo == 'sin_candidatos'


# --------------------------------------------------------------- determinismo

def test_resultado_no_depende_del_orden_del_indice():
    """El bug viejo dependia del orden fisico de la tabla (.first() sin order_by).
    El resultado tiene que ser identico con el indice permutado."""
    directo = _indice()
    invertido = _indice(list(reversed(_INVENTARIO)))
    casos = [(d, u) for (d, u, _e) in [
        ("Provisión y colocación de hormigón H21 elaborado para losas", "m3", 3),
        ("Membrana asfáltica con aluminio 4mm en cubierta", "m2", 11),
        ("Suministro y colocación de cañería PVC 110mm para desagüe", "ml", 14),
        ("Provisión y montaje de armadura de hierro aletado ADN 420", "kg", None),
    ]]
    for desc, unidad in casos:
        assert (vincular_item_inventario(desc, unidad, directo)
                == vincular_item_inventario(desc, unidad, invertido)), desc


# ------------------------------------------- consistencia con el dry-run

def test_evaluar_candidatos_es_consistente_con_vincular(indice):
    """scripts/dry_run_vinculacion_inventario.py calibra los umbrales barriendo
    evaluar_candidatos(). Si ese barrido no coincidiera con vincular_item_inventario()
    en el umbral vigente, el reporte aconsejaria sobre una funcion distinta de la
    que corre en produccion."""
    descripciones = [
        ("Provisión y colocación de hormigón H21 elaborado para losas", "m3"),
        ("Membrana asfáltica con aluminio 4mm en cubierta", "m2"),
        ("Suministro y colocación de cañería PVC 110mm para desagüe", "ml"),
        ("Provisión y montaje de armadura de hierro aletado ADN 420", "kg"),
        ("Excavación manual para fundaciones", "m3"),
        ("Cemento Portland 50kg", "bolsa"),
    ]

    reales = sum(1 for d, u in descripciones
                 if vincular_item_inventario(d, u, indice)[0] is not None)

    # replica del barrido del script en el umbral vigente
    barrido = 0
    for d, u in descripciones:
        cands = evaluar_candidatos(d, u, indice, incluir_rechazados=True)
        elegibles = [c for c in cands
                     if c['rechazo'] in (None, 'cobertura_baja')
                     and c['cobertura'] >= _MIN_COBERTURA]
        if not elegibles:
            continue
        if len(elegibles) > 1:
            a, b = elegibles[0], elegibles[1]
            if (a['cobertura'] - b['cobertura']) <= _GAP_MIN and a['n_comunes'] == b['n_comunes']:
                continue
        barrido += 1

    assert barrido == reales


@pytest.mark.parametrize("descripcion,unidad", [
    ("Honorarios de dirección técnica", "gl"),
    ("Seguro de obra y póliza de caución", "mes"),
    ("Gestión de permisos municipales", "un"),
    ("Cartel de obra según pliego", "un"),
    ("Gastos generales e imprevistos", "gl"),
])
def test_servicios_no_se_vinculan_a_stock(descripcion, unidad, indice):
    """Los importadores marcan TODO como tipo='material', asi que honorarios y
    tramites llegan al matcher. Nada de eso se reserva contra el deposito."""
    inv_id, _score, motivo = vincular_item_inventario(descripcion, unidad, indice)
    assert inv_id is None
    assert motivo == 'no_es_material'


def test_unidad_uni_es_compatible_con_un():
    """REGRESION: 'UNI' es el 64% del inventario de produccion (7.210 de 11.265)
    y no estaba en la tabla de sinonimos, asi que el guard de unidad descartaba
    todos esos items."""
    from services.precio_recurso_service import _unidades_compatibles
    assert _unidades_compatibles('UNI', 'un')
    assert _unidades_compatibles('uni', 'unidad')
    assert _unidades_compatibles('LTS', 'litro')
    assert _unidades_compatibles('JOR', 'jornal')
    # y que no se haya aflojado de mas
    assert not _unidades_compatibles('uni', 'm2')
    assert not _unidades_compatibles('lts', 'kg')


def test_material_en_uni_vincula(indice):
    """Un item de inventario cargado en 'UNI' ahora si matchea un pliego en 'un'."""
    idx = _indice([(90, "Ladrillo hueco 12x18x33", "UNI")])
    inv_id, _score, motivo = vincular_item_inventario(
        "Ladrillo hueco 12x18x33", "un", idx)
    assert inv_id == 90
    assert motivo == 'ok'


def test_incluir_rechazados_expone_el_motivo(indice):
    """El dry-run necesita saber POR QUE se descarto cada candidato."""
    cands = evaluar_candidatos(
        "Provisión y montaje de armadura de hierro aletado ADN 420", "kg",
        indice, incluir_rechazados=True)
    assert cands, "debe haber candidatos con tokens en comun aunque se rechacen"
    assert all('rechazo' in c and 'cobertura' in c for c in cands)
    assert any(c['rechazo'] == 'cobertura_baja' for c in cands)

    # sin la bandera, solo vuelven los aceptados
    aceptados = evaluar_candidatos(
        "Provisión y montaje de armadura de hierro aletado ADN 420", "kg", indice)
    assert all(c['rechazo'] is None for c in aceptados)
