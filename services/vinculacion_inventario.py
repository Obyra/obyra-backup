# -*- coding: utf-8 -*-
"""Pantalla de confirmacion de vinculos pliego <-> inventario.

QUE HACE Y QUE NO
-----------------
El import de pliego NO escribe vinculos (se probo y se revirtio: vincular sin
preguntar mete vinculos equivocados, y un vinculo equivocado reserva stock real
contra el deposito). Este modulo calcula las propuestas AL VUELO cada vez que se
abre la pantalla, y solo persiste lo que una persona confirma.

Consecuencia util: en un presupuesto importado, una fila en
`item_presupuesto_inventario` significa literalmente "un humano confirmo esto".
No hace falta una columna de estado para saber que falta revisar.

LOS BALDES
----------
    confirmados   ya tienen vinculo humano. Se muestran para poder deshacerlos.
    altos         cobertura >= UMBRAL_ALTA. Van pre-marcados.
    revisar       UMBRAL_MIN <= cobertura < UMBRAL_ALTA. Van DESMARCADOS.
    multiples     empate entre candidatos: o es uno de esos, o son todos (1-a-N).
    sin_vincular  el matcher no encontro nada. Buscador manual.

El corte de UMBRAL_ALTA no es arbitrario: es el mismo `_MIN_COBERTURA + 0.15`
que el dry-run de calibracion reporta como "entraron raspando, reviselos a mano"
(scripts/dry_run_vinculacion_inventario.py). Esos son justo los que no queremos
pre-marcar.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from services.inventory_matcher import (
    _MIN_COBERTURA,
    construir_indice_inventario,
    evaluar_candidatos,
    hay_empate,
)

# Los de cobertura menor a esto se proponen pero DESMARCADOS.
UMBRAL_ALTA = round(_MIN_COBERTURA + 0.15, 2)

# Tope de candidatos que se ofrecen por renglon en el balde "multiples". Mas que
# esto no es una eleccion, es una lista: si el matcher duda entre 6 variantes, el
# usuario esta mejor servido por el buscador manual.
MAX_CANDIDATOS = 4


def _f(val) -> float:
    return float(val or 0)


def _stock_por_item(org_id: int) -> Dict[int, Dict[str, Any]]:
    """id -> {stock, codigo}. Una query. El indice del matcher no trae stock a
    proposito (se usa para matchear, no para leer deposito), pero la pantalla si
    necesita mostrarlo: "vinculalo con esto, tenes 45 m3" es la info que hace
    que la decision valga la pena."""
    from models.inventory import ItemInventario

    filas = (ItemInventario.query
             .with_entities(ItemInventario.id,
                            ItemInventario.stock_actual,
                            ItemInventario.codigo)
             .filter(ItemInventario.organizacion_id == org_id,
                     ItemInventario.activo.is_(True))
             .all())
    return {f.id: {'stock': _f(f.stock_actual), 'codigo': f.codigo or ''}
            for f in filas}


def _candidato_dict(cand: Dict[str, Any], stocks: Dict[int, Dict[str, Any]],
                    cantidad_pliego: float) -> Dict[str, Any]:
    extra = stocks.get(cand['id'], {})
    return {
        'id': cand['id'],
        'nombre': cand['nombre'],
        'unidad': cand['unidad'] or '',
        'codigo': extra.get('codigo', ''),
        'stock': extra.get('stock', 0.0),
        'cobertura': cand['cobertura'],
        'comunes': cand['comunes'],
        # Sugerencia de cantidad: la del pliego. El matcher ya garantizo que las
        # unidades son compatibles, pero no hay factor de conversion en el
        # sistema, asi que esto es una sugerencia editable, no una verdad.
        'cantidad_sugerida': cantidad_pliego,
    }


def preparar_pantalla(presupuesto, org_id: int) -> Dict[str, Any]:
    """Arma los baldes de la pantalla de confirmacion.

    No escribe nada. Costo: 2 queries (indice de inventario + stocks) mas la
    carga de los items del presupuesto, sin importar cuantos renglones tenga.
    """
    from models.budgets import ItemPresupuesto

    items = (ItemPresupuesto.query
             .filter(ItemPresupuesto.presupuesto_id == presupuesto.id,
                     ItemPresupuesto.tipo == 'material')
             .order_by(ItemPresupuesto.id)
             .all())

    indice = construir_indice_inventario(org_id)
    stocks = _stock_por_item(org_id)
    nombres = {inv['id']: inv['nombre'] for inv in indice}

    baldes: Dict[str, List[Dict[str, Any]]] = {
        'confirmados': [], 'altos': [], 'revisar': [],
        'multiples': [], 'sin_vincular': [],
    }

    for item in items:
        cantidad = _f(item.cantidad)
        fila = {
            'item_id': item.id,
            'descripcion': item.descripcion or '',
            'unidad': item.unidad or '',
            'cantidad': cantidad,
        }

        # Ya confirmado por una persona -> no se recalcula, se muestra tal cual
        # quedo. Recalcular acá haría que la pantalla "corrija" decisiones humanas.
        vinculos = list(item.vinculos_inventario)
        if vinculos:
            fila['vinculos'] = [{
                'inv_id': v.item_inventario_id,
                'nombre': nombres.get(v.item_inventario_id, '(item dado de baja)'),
                'cantidad': _f(v.cantidad),
            } for v in vinculos]
            baldes['confirmados'].append(fila)
            continue

        aceptados = evaluar_candidatos(item.descripcion or '', item.unidad, indice)
        if not aceptados:
            baldes['sin_vincular'].append(fila)
            continue

        mejor = aceptados[0]

        # Empate: el matcher en produccion devuelve None acá. La pantalla, en
        # cambio, puede preguntar — que es el unico lugar donde el caso 1-a-N
        # ("son los dos") se puede resolver bien.
        if len(aceptados) > 1 and hay_empate(mejor, aceptados[1]):
            fila['candidatos'] = [_candidato_dict(c, stocks, cantidad)
                                  for c in aceptados[:MAX_CANDIDATOS]]
            baldes['multiples'].append(fila)
            continue

        fila['candidatos'] = [_candidato_dict(mejor, stocks, cantidad)]
        # Alternativas para el desplegable "cambiar", sin llegar a ser un empate.
        fila['alternativas'] = [_candidato_dict(c, stocks, cantidad)
                                for c in aceptados[1:MAX_CANDIDATOS]]
        if mejor['cobertura'] >= UMBRAL_ALTA:
            baldes['altos'].append(fila)
        else:
            baldes['revisar'].append(fila)

    total = len(items)
    encontrados = (len(baldes['confirmados']) + len(baldes['altos'])
                   + len(baldes['revisar']) + len(baldes['multiples']))
    return {
        'baldes': baldes,
        'total': total,
        'encontrados': encontrados,
        'confirmados': len(baldes['confirmados']),
        'pct': round(100 * encontrados / total) if total else 0,
        'umbral_alta': UMBRAL_ALTA,
    }


def guardar_vinculos(presupuesto, org_id: int, usuario_id: Optional[int],
                     seleccion: List[Dict[str, Any]]) -> Dict[str, int]:
    """Persiste lo que el usuario confirmo. Reemplaza los vinculos de cada
    renglon que venga en `seleccion` (lista vacia de invs = desvincular).

    `seleccion`: [{'item_id': int,
                   'invs': [{'inv_id': int, 'cantidad': float, 'score': float|None}]}]

    Valida que TODO id venga de esta organizacion. El body no es confiable: sin
    esta validacion, un item_id o un inv_id de otra org entraria por el POST.
    """
    from extensions import db
    from models.budgets import ItemPresupuesto, ItemPresupuestoInventario
    from models.inventory import ItemInventario

    if not seleccion:
        return {'vinculados': 0, 'desvinculados': 0, 'renglones': 0}

    item_ids = {int(s['item_id']) for s in seleccion}
    inv_ids = {int(v['inv_id']) for s in seleccion for v in s.get('invs', [])}

    # Los renglones tienen que ser de ESTE presupuesto (que ya fue verificado
    # contra la org por la vista). Filtrar por presupuesto_id es mas estricto
    # que filtrar por org y ademas evita mezclar presupuestos de la misma org.
    validos = {i.id: i for i in ItemPresupuesto.query.filter(
        ItemPresupuesto.presupuesto_id == presupuesto.id,
        ItemPresupuesto.id.in_(item_ids)).all()}

    invs_validos = set()
    if inv_ids:
        invs_validos = {r.id for r in ItemInventario.query.with_entities(
            ItemInventario.id).filter(
                ItemInventario.organizacion_id == org_id,
                ItemInventario.activo.is_(True),
                ItemInventario.id.in_(inv_ids)).all()}

    vinculados = desvinculados = renglones = 0

    for sel in seleccion:
        item = validos.get(int(sel['item_id']))
        if item is None:
            continue        # id ajeno o inexistente: se ignora en silencio

        previos = ItemPresupuestoInventario.query.filter_by(
            item_presupuesto_id=item.id).all()
        for p in previos:
            db.session.delete(p)
            desvinculados += 1

        for v in sel.get('invs', []):
            inv_id = int(v['inv_id'])
            if inv_id not in invs_validos:
                continue
            score = v.get('score')
            db.session.add(ItemPresupuestoInventario(
                item_presupuesto_id=item.id,
                item_inventario_id=inv_id,
                cantidad=Decimal(str(v.get('cantidad') or 0)),
                score_propuesto=Decimal(str(score)) if score is not None else None,
                confirmado_por_id=usuario_id,
            ))
            vinculados += 1
        renglones += 1

    db.session.commit()
    return {'vinculados': vinculados,
            'desvinculados': desvinculados,
            'renglones': renglones}


def contar_para_banner(presupuesto) -> Dict[str, int]:
    """(renglones de material, renglones con vinculo confirmado) para el banner.

    Dos COUNT, sin correr el matcher: tokenizar el catalogo entero contra 200
    renglones en cada carga de pagina seria carisimo. La propuesta se calcula
    recien cuando el usuario abre la pantalla.

    Solo para pliegos importados. Los presupuestos de la Calculadora IA escriben
    ItemPresupuesto.item_inventario_id al crear los items, asi que decirles
    "todavia no vinculaste" seria falso.
    """
    from extensions import db
    from models.budgets import ItemPresupuesto, ItemPresupuestoInventario

    if presupuesto.origen_creacion != 'excel':
        return {'vinc_total': 0, 'vinc_confirmados': 0}

    total = (ItemPresupuesto.query
             .filter(ItemPresupuesto.presupuesto_id == presupuesto.id,
                     ItemPresupuesto.tipo == 'material')
             .count())
    confirmados = (
        db.session.query(ItemPresupuestoInventario.item_presupuesto_id)
        .join(ItemPresupuesto,
              ItemPresupuesto.id == ItemPresupuestoInventario.item_presupuesto_id)
        .filter(ItemPresupuesto.presupuesto_id == presupuesto.id)
        .distinct().count()
    )
    return {'vinc_total': total, 'vinc_confirmados': confirmados}
