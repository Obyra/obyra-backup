# -*- coding: utf-8 -*-
"""Pipeline completo de presupuesto IA (Fase 2.4).

Toma items del Excel del cliente y produce, por item:
  1. clasificacion  -> regla_id (clasificador LLM, fallback keyword)
  2. descomposicion -> recursos (APU del YAML, segun nivel)
  3. pricing        -> precio de cada recurso (materiales + costo empresa MO)
  4. scoring        -> VERDE / AMARILLO / ROJO

Score por item (f(clasificacion, cobertura de composicion)):
  ROJO     : sin regla, o confianza < 0.5, o la regla no tiene coeficientes,
             o < 50% de los recursos con precio.
  VERDE    : confianza >= 0.85, regla con coeficientes, 100% recursos con precio.
  AMARILLO : el resto (confianza media, o algun recurso sin precio).

`precio_estimado` marca los items que dependen de materiales fuente='estimado'
(transparencia: hoy casi todos, hasta cargar listas reales).
"""
from decimal import Decimal


UMBRAL_VERDE = 0.85
UMBRAL_ROJO = 0.5


def _precios_recursos(recursos, organizacion_id, zona, fecha, presupuesto, cache=None):
    """Precio de cada recurso del APU. Devuelve (detalle, costo_unitario).

    `cache` (dict) memoiza por (nombre, unidad, tipo) para no repricear el mismo
    recurso en cada item del pliego (perf: 'Oficial albañil', 'Mortero', etc.)."""
    from services.precio_recurso_service import buscar_mejor_precio

    if cache is None:
        cache = {}
    detalle = []
    costo = Decimal('0')
    for r in recursos:
        tipo = 'mano_obra' if r.get('tipo') == 'mano_obra' else 'material'
        nombre = r.get('nombre', '')
        unidad = r.get('unidad', '')
        ckey = (nombre, unidad, tipo)
        info = cache.get(ckey)
        if info is None:
            info = buscar_mejor_precio(
                organizacion_id=organizacion_id, descripcion=nombre,
                unidad=unidad, tipo_recurso=tipo, zona=zona, presupuesto=presupuesto,
            )
            cache[ckey] = info
        precio = Decimal(str(info.get('precio') or 0))
        coef = Decimal(str(r.get('coeficiente') or 0))
        costo += coef * precio
        detalle.append({
            'clave': r.get('clave'), 'nombre': r.get('nombre'), 'tipo': tipo,
            'unidad': r.get('unidad'), 'coeficiente': float(coef),
            'precio': float(precio), 'fuente': info.get('fuente'),
            'requiere_tc': bool(info.get('requiere_tc')),
            'estimado': info.get('fuente_lista') == 'estimado',
        })
    return detalle, costo


def _color(confianza, tiene_coef, recursos_detalle):
    if not tiene_coef or confianza < UMBRAL_ROJO:
        return 'rojo'
    n = len(recursos_detalle)
    if n == 0:
        return 'rojo'
    sin_precio = sum(1 for r in recursos_detalle if r['precio'] <= 0 and not r['requiere_tc'])
    cobertura = 1 - (sin_precio / n)
    if confianza >= UMBRAL_VERDE and cobertura >= 0.999:
        return 'verde'
    if cobertura < 0.5 or confianza < 0.6:
        return 'rojo'
    return 'amarillo'


def _clasificar_con_aprendizaje(items, organizacion_id, forzar_keyword):
    """Resuelve primero los items ya aprendidos por la org (sin LLM); clasifica
    el resto. Devuelve lista de dicts alineada con `regla_id, confianza, fuente,
    tiene_coeficientes, tratamiento`."""
    from services.clasificador_llm import clasificar_items
    from services.coeficientes_loader import tiene_coeficientes
    from services.aprendizaje_ia import buscar_mapeos
    from models.mapeo_aprendido import normalizar_texto_item

    aprendidos = buscar_mapeos(organizacion_id, [it.get('descripcion') for it in items])

    idx_pend = [i for i, it in enumerate(items)
                if normalizar_texto_item(it.get('descripcion')) not in aprendidos]
    pend = [items[i] for i in idx_pend]
    clasif_pend = clasificar_items(pend, forzar_keyword=forzar_keyword) if pend else []
    por_idx = {i: clasif_pend[k] for k, i in enumerate(idx_pend)}

    out = []
    for i, it in enumerate(items):
        tn = normalizar_texto_item(it.get('descripcion'))
        m = aprendidos.get(tn)
        if m is not None:
            out.append({
                'regla_id': m.regla_id, 'confianza': 1.0, 'fuente': 'aprendido',
                'tiene_coeficientes': bool(m.regla_id and tiene_coeficientes(m.regla_id)),
                'tratamiento': m.tratamiento,
            })
        else:
            c = dict(por_idx[i])
            c['tratamiento'] = 'apu'
            out.append(c)
    return out


# Grupos de unidades equivalentes (para el guard item<->regla).
_UNID_GRUPOS = [
    {'m2', 'm²', 'mts2', 'mt2'}, {'m3', 'm³', 'mts3', 'mt3'},
    {'ml', 'm', 'mts', 'mtrs'}, {'kg', 'kilo', 'kilos'},
    {'un', 'u', 'ud', 'und', 'unidad', 'unidades', 'gl', 'global', 'gbl'},
    {'tn', 'tonelada', 'toneladas'}, {'l', 'lt', 'litro', 'litros'},
    {'mes', 'meses'}, {'jornal', 'dia', 'día'}, {'hora', 'hr', 'hs', 'h'},
]


def _norm_unidad(u):
    import re
    return re.sub(r'[^a-z0-9²³]', '', (u or '').lower())


def _unidad_item_compatible(u_item, u_regla):
    """True si la unidad del item del cliente es compatible con la de la regla.
    Si alguna falta, no bloquea (return True). Normaliza notacion ('Un.', 'm2 ')."""
    b = _norm_unidad(u_regla)
    if not b:
        return True
    a = _norm_unidad(u_item)
    if not a or a == b:
        return True
    for g in _UNID_GRUPOS:
        if a in g and b in g:
            return True
    return False


def procesar_items(items, *, organizacion_id, nivel='estandar', zona='CABA',
                   presupuesto=None, forzar_keyword=False):
    """Corre el pipeline completo sobre una lista de items {descripcion, unidad, cantidad}.

    Orden: aprendizaje por org -> clasificacion LLM -> descomposicion -> pricing -> score.
    """
    from services.coeficientes_loader import get_recursos, unidad_item_esperada
    from services.clasificador_llm import candidatos_para

    clasifs = _clasificar_con_aprendizaje(items, organizacion_id, forzar_keyword)

    precio_cache = {}  # (nombre, unidad, tipo) -> info (perf: dedup de recursos)
    salida = []
    resumen = {'verde': 0, 'amarillo': 0, 'rojo': 0, 'total': len(items),
               'fuente_clasificacion': 'aprendido', 'items_estimados': 0, 'aprendidos': 0}
    hubo_llm = False
    for it, cl in zip(items, clasifs):
        rid = cl['regla_id']
        conf = cl['confianza']
        tiene_coef = cl['tiene_coeficientes']
        fuente = cl['fuente']
        tratamiento = cl.get('tratamiento', 'apu')
        if fuente == 'llm':
            hubo_llm = True
        if fuente == 'aprendido':
            resumen['aprendidos'] += 1

        recursos = get_recursos(rid, nivel) if (rid and tiene_coef) else []
        regla_unidad = unidad_item_esperada(rid) if (rid and tiene_coef) else None
        unidad_ok = _unidad_item_compatible(it.get('unidad'), regla_unidad)
        detalle, costo_unit = (_precios_recursos(recursos, organizacion_id, zona, None, presupuesto, precio_cache)
                               if recursos else ([], Decimal('0')))

        # Guard de unidad: si el item viene en una unidad INCOMPATIBLE con la regla
        # (ej. item en m2 clasificado a una regla por tn/m3), el precio auto no es
        # confiable y produce totales absurdos -> a revision, y NO se cuenta su costo.
        unidad_incompatible = bool(recursos) and not unidad_ok
        if unidad_incompatible:
            costo_unit = Decimal('0')

        # Scoring. Un item aprendido como 'manual' (lump-sum) queda RESUELTO (verde).
        if fuente == 'aprendido' and tratamiento == 'manual':
            color = 'verde'
        elif unidad_incompatible:
            color = 'rojo'
        else:
            color = _color(conf, tiene_coef, detalle)
        resumen[color] += 1

        estimado = any(r['estimado'] for r in detalle)
        if estimado:
            resumen['items_estimados'] += 1
        try:
            cantidad = Decimal(str(it.get('cantidad') or 0))
        except Exception:
            cantidad = Decimal('0')

        fila = {
            'descripcion': it.get('descripcion'),
            'unidad': it.get('unidad'),
            'cantidad': float(cantidad),
            'regla_id': rid,
            'confianza': round(conf, 2),
            'fuente_clasificacion': fuente,
            'tratamiento': tratamiento,
            'color': color,
            'costo_unitario': float(costo_unit),
            'costo_total': float(costo_unit * cantidad),
            'recursos_total': len(detalle),
            'recursos_sin_precio': sum(1 for r in detalle if r['precio'] <= 0 and not r['requiere_tc']),
            'precio_estimado': estimado,
            'requiere_tc': any(r['requiere_tc'] for r in detalle),
            'unidad_incompatible': unidad_incompatible,
            'unidad_regla': regla_unidad,
        }
        # Candidatos (para la pantalla de revision) solo en los que hay que revisar.
        if color in ('rojo', 'amarillo'):
            fila['candidatos'] = candidatos_para(it.get('descripcion'), it.get('unidad'), n=3)
        salida.append(fila)

    if hubo_llm:
        resumen['fuente_clasificacion'] = 'llm'
    elif resumen['aprendidos'] < resumen['total']:
        resumen['fuente_clasificacion'] = 'keyword'

    tot = resumen['total'] or 1
    resumen['pct_verde'] = round(100 * resumen['verde'] / tot, 1)
    resumen['pct_amarillo'] = round(100 * resumen['amarillo'] / tot, 1)
    resumen['pct_rojo'] = round(100 * resumen['rojo'] / tot, 1)
    return {'items': salida, 'resumen': resumen}
