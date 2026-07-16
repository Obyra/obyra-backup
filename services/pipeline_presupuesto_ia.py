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


def _precios_recursos(recursos, organizacion_id, zona, fecha, presupuesto):
    """Precio de cada recurso del APU. Devuelve (detalle, costo_unitario)."""
    from services.precio_recurso_service import buscar_mejor_precio

    detalle = []
    costo = Decimal('0')
    for r in recursos:
        tipo = 'mano_obra' if r.get('tipo') == 'mano_obra' else 'material'
        info = buscar_mejor_precio(
            organizacion_id=organizacion_id, descripcion=r.get('nombre', ''),
            unidad=r.get('unidad', ''), tipo_recurso=tipo, zona=zona, presupuesto=presupuesto,
        )
        precio = Decimal(str(info.get('precio') or 0))
        coef = Decimal(str(r.get('coeficiente') or 0))
        costo += coef * precio
        detalle.append({
            'clave': r.get('clave'), 'nombre': r.get('nombre'), 'tipo': tipo,
            'unidad': r.get('unidad'), 'coeficiente': float(coef),
            'precio': float(precio), 'fuente': info.get('fuente'),
            'requiere_tc': bool(info.get('requiere_tc')),
            'estimado': info.get('fuente') == 'estimado',
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


def procesar_items(items, *, organizacion_id, nivel='estandar', zona='CABA',
                   presupuesto=None, forzar_keyword=False):
    """Corre el pipeline completo sobre una lista de items {descripcion, unidad, cantidad}."""
    from services.clasificador_llm import clasificar_items
    from services.coeficientes_loader import get_recursos

    clasifs = clasificar_items(items, forzar_keyword=forzar_keyword)

    salida = []
    resumen = {'verde': 0, 'amarillo': 0, 'rojo': 0, 'total': len(items),
               'fuente_clasificacion': clasifs[0]['fuente'] if clasifs else 'keyword',
               'items_estimados': 0}
    for it, cl in zip(items, clasifs):
        rid = cl['regla_id']
        conf = cl['confianza']
        tiene_coef = cl['tiene_coeficientes']
        recursos = get_recursos(rid, nivel) if (rid and tiene_coef) else []
        detalle, costo_unit = _precios_recursos(recursos, organizacion_id, zona,
                                                None, presupuesto) if recursos else ([], Decimal('0'))
        color = _color(conf, tiene_coef, detalle)
        resumen[color] += 1

        estimado = any(r['estimado'] for r in detalle)
        if estimado:
            resumen['items_estimados'] += 1
        try:
            cantidad = Decimal(str(it.get('cantidad') or 0))
        except Exception:
            cantidad = Decimal('0')

        salida.append({
            'descripcion': it.get('descripcion'),
            'unidad': it.get('unidad'),
            'cantidad': float(cantidad),
            'regla_id': rid,
            'confianza': round(conf, 2),
            'fuente_clasificacion': cl['fuente'],
            'color': color,
            'costo_unitario': float(costo_unit),
            'costo_total': float(costo_unit * cantidad),
            'recursos_total': len(detalle),
            'recursos_sin_precio': sum(1 for r in detalle if r['precio'] <= 0 and not r['requiere_tc']),
            'precio_estimado': estimado,
            'requiere_tc': any(r['requiere_tc'] for r in detalle),
        })

    tot = resumen['total'] or 1
    resumen['pct_verde'] = round(100 * resumen['verde'] / tot, 1)
    resumen['pct_amarillo'] = round(100 * resumen['amarillo'] / tot, 1)
    resumen['pct_rojo'] = round(100 * resumen['rojo'] / tot, 1)
    return {'items': salida, 'resumen': resumen}
