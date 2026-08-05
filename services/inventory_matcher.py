# -*- coding: utf-8 -*-
"""Vinculacion de items de presupuesto con el inventario de la organizacion.

POR QUE EXISTE ESTE MODULO (2026-08-04)
---------------------------------------
`buscar_item_inventario_por_nombre()` (blueprint_presupuestos/__init__.py:79) se
llamaba desde UN solo lugar: la Calculadora IA (core.py:384), donde las
descripciones son limpias ("Cemento Portland 50kg"). Los presupuestos importados
desde pliego Excel nunca la ejecutaban, asi que TODOS sus materiales quedaban con
item_inventario_id = NULL -> caen en el balde `sin_vincular` de
/api/obras/<id>/analizar-materiales, el unico que no se puede reservar contra el
deposito. El usuario tiene el material en stock y el sistema le propone comprarlo.

Reusar aquel matcher para pliegos NO era opcion. Su paso 3 toma las primeras 3
palabras de mas de 2 caracteres y devuelve el PRIMER item de inventario que
contenga alguna, con un `.first()` sin `order_by`. En un pliego esas primeras
palabras son siempre las mismas muletillas ("Provision", "Colocacion",
"Ejecucion"), asi que el resultado es basura determinada por el orden de la tabla:

    "Provision y colocacion de hormigon H21 elaborado"  ->  "Provision de agua obra"
    "Suministro y colocacion de caneria PVC 110mm"      ->  "Colocacion de ceramicos"

Un vinculo EQUIVOCADO es peor que ninguno: `gestionar-materiales` reserva stock
real contra ese item_inventario_id. Por eso este matcher es deliberadamente
conservador y prefiere devolver None antes que arriesgar. Devuelve tambien el
score y el motivo para que la UI pueda pedir confirmacion en vez de decidir sola.

USO EN IMPORTS GRANDES
----------------------
El indice se construye UNA vez por import (1 query) y se reusa para todos los
items; no hay N+1 aunque el pliego traiga 200 renglones.

    indice = construir_indice_inventario(org_id)
    for it in items:
        inv_id, score, motivo = vincular_item_inventario(
            it['descripcion'], it['unidad'], indice)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Se reusan el tokenizador y el comparador de unidades que ya existen para el
# matching de precios. Mismo criterio de normalizacion en todo el sistema.
from services.precio_recurso_service import (
    _tokens_significativos,
    _unidades_compatibles,
)


# Verbos y muletillas de pliego. NO discriminan material: aparecen en casi todos
# los renglones de una licitacion. Son exactamente los tokens que hacian fallar
# al matcher viejo, porque son los que quedan primero al splitear la descripcion.
_STOPWORDS_PLIEGO = {
    'provision', 'provisiones', 'provisto', 'provista',
    'colocacion', 'colocado', 'colocada', 'coloc',
    'ejecucion', 'ejecutado', 'ejecutada',
    'montaje', 'montado', 'suministro', 'suministrado',
    'instalacion', 'instalado', 'instalada',
    'incluye', 'incluido', 'incluida', 'incluidos', 'incluidas',
    'completo', 'completa', 'terminado', 'terminada', 'nuevo', 'nueva',
    'obra', 'obras', 'trabajo', 'trabajos', 'item', 'items', 'rubro',
    'plano', 'planos', 'especificacion', 'especificaciones',
    'detalle', 'detalles', 'proyecto', 'norma', 'normas', 'calidad',
    'mano', 'materiales', 'material', 'equipo', 'equipos',
    'reglamento', 'pliego', 'unidad', 'unidades', 'cant', 'cantidad',
}

# Umbrales de aceptacion. Conservadores a proposito: ver el docstring de arriba.
_MIN_TOKENS_COMUNES = 2    # al menos 2 palabras significativas compartidas
_MIN_COBERTURA = 0.60      # 60% del nombre de inventario presente en la descripcion
_GAP_MIN = 0.15            # ventaja minima sobre el 2do candidato (mismo criterio
                           # que clasificar_con_margen en pipeline_presupuesto_ia)


def _tokens_utiles(texto: str) -> set:
    """Tokens significativos SIN las muletillas de pliego."""
    return _tokens_significativos(texto) - _STOPWORDS_PLIEGO


def construir_indice_inventario(org_id: int) -> List[Dict[str, Any]]:
    """Carga los items de inventario activos de la org con sus tokens ya
    calculados. UNA query; el resultado se reusa para todos los items del import.

    Se traen solo id/nombre/unidad (no el modelo completo): el indice se usa para
    matchear, no para leer stock.
    """
    from models.inventory import ItemInventario

    filas = (ItemInventario.query
             .with_entities(ItemInventario.id,
                            ItemInventario.nombre,
                            ItemInventario.unidad)
             .filter(ItemInventario.organizacion_id == org_id,
                     ItemInventario.activo.is_(True))
             .order_by(ItemInventario.id)     # determinista: sin esto el desempate
             .all())                          # dependeria del plan de Postgres

    return [{'id': f.id, 'nombre': f.nombre, 'unidad': f.unidad,
             'tokens': _tokens_utiles(f.nombre)}
            for f in filas]


def evaluar_candidatos(
    descripcion: str,
    unidad: Optional[str],
    indice: List[Dict[str, Any]],
    incluir_rechazados: bool = False,
) -> List[Dict[str, Any]]:
    """Puntua los items del indice contra una descripcion.

    FUENTE UNICA del scoring: tanto `vincular_item_inventario` (produccion) como
    el dry-run de calibracion (scripts/dry_run_vinculacion_inventario.py) pasan
    por aca. Asi el reporte no puede desincronizarse de lo que realmente vincula.

    Con `incluir_rechazados=True` devuelve tambien los que NO pasaron los
    umbrales, con el campo `rechazo` explicando por que ('unidad',
    'pocos_tokens', 'cobertura_baja'). Eso es lo que permite ver si 0.60 / 0.15
    estan bien calibrados. En produccion queda en False: no se arma la lista de
    descartados.

    Devuelve la lista ordenada de mejor a peor: cobertura desc, tokens comunes
    desc, id asc (determinista, no depende del plan de Postgres).
    """
    tk_desc = _tokens_utiles(descripcion)
    if not tk_desc:
        return []

    out = []
    for inv in indice:
        tk_inv = inv['tokens']
        if not tk_inv:
            continue

        # Guard de unidad. Un renglon de pliego en m2 (superficie de pared) NO se
        # reserva contra un inventario en 'un' (ladrillos sueltos) ni en 'balde':
        # hace falta un factor de conversion que hoy no se aplica. Si el pliego no
        # trae unidad no se filtra, pero el resto de los umbrales sigue aplicando.
        unidad_mala = bool(
            unidad and inv['unidad']
            and not _unidades_compatibles(unidad, inv['unidad'])
        )

        comunes = tk_desc & tk_inv
        # Cobertura del NOMBRE DE INVENTARIO, no de la descripcion: los nombres de
        # inventario son cortos y especificos ("Hormigon H21 elaborado") y las
        # descripciones de pliego son largas. Lo que queremos saber es si el nombre
        # del inventario esta contenido en la descripcion, no al reves.
        cobertura = len(comunes) / len(tk_inv)

        if unidad_mala:
            rechazo = 'unidad'
        elif len(comunes) < _MIN_TOKENS_COMUNES:
            rechazo = 'pocos_tokens'
        elif cobertura < _MIN_COBERTURA:
            rechazo = 'cobertura_baja'
        else:
            rechazo = None

        if rechazo is not None:
            # Sin tokens en comun no aporta ni al diagnostico: seria ruido.
            if not incluir_rechazados or not comunes:
                continue

        out.append({
            'id': inv['id'], 'nombre': inv['nombre'], 'unidad': inv['unidad'],
            'comunes': sorted(comunes), 'n_comunes': len(comunes),
            'cobertura': round(cobertura, 3), 'rechazo': rechazo,
        })

    out.sort(key=lambda c: (-c['cobertura'], -c['n_comunes'], c['id']))
    return out


def vincular_item_inventario(
    descripcion: str,
    unidad: Optional[str],
    indice: List[Dict[str, Any]],
) -> Tuple[Optional[int], float, str]:
    """Busca el item de inventario que corresponde a una descripcion.

    Args:
        descripcion: texto del item del presupuesto (crudo, como vino del Excel).
        unidad: unidad del item. Si esta, se usa como filtro duro.
        indice: salida de construir_indice_inventario().

    Returns:
        (item_inventario_id | None, score 0..1, motivo)

        motivo es 'ok' | 'sin_candidatos' | 'ambiguo' | 'descripcion_sin_tokens'.
        El score es la cobertura del nombre de inventario: 1.0 = todas las
        palabras del item de inventario aparecen en la descripcion del pliego.
    """
    # Los importadores de pliego marcan TODAS las filas como tipo='material', asi
    # que llegan aca honorarios, seguros, gastos generales y tramites. Nada de eso
    # se reserva contra el deposito. _es_no_apu() ya sabe reconocerlos (lo usa el
    # pipeline IA para agrupar los rojos "legitimos"), asi que se reusa en vez de
    # duplicar la lista de keywords.
    #
    # Se filtra ACA y no cambiando el `tipo` del item a proposito: solo existen
    # tres tipos ('material', 'equipo', 'mano_obra') y 128 lugares del codigo
    # dependen de 'material' --incluido el armado del PDF al cliente--. Un servicio
    # es un renglon facturable que el cliente TIENE que ver; sacarlo de 'material'
    # arriesga que desaparezca del presupuesto impreso. Lo que hay que evitar no es
    # que sea 'material', es que se vincule a stock.
    from services.pipeline_presupuesto_ia import _es_no_apu
    if _es_no_apu(descripcion, unidad):
        return None, 0.0, 'no_es_material'

    if not _tokens_utiles(descripcion):
        return None, 0.0, 'descripcion_sin_tokens'

    aceptados = evaluar_candidatos(descripcion, unidad, indice)
    if not aceptados:
        return None, 0.0, 'sin_candidatos'

    mejor = aceptados[0]

    # Empate real entre dos items distintos -> no adivinamos. Tipico con variantes
    # que el pliego no desambigua ("hierro aletado" sin diametro): que lo resuelva
    # una persona, no el orden de la tabla.
    if len(aceptados) > 1:
        segundo = aceptados[1]
        if ((mejor['cobertura'] - segundo['cobertura']) <= _GAP_MIN
                and mejor['n_comunes'] == segundo['n_comunes']):
            return None, round(mejor['cobertura'], 2), 'ambiguo'

    return mejor['id'], round(mejor['cobertura'], 2), 'ok'
