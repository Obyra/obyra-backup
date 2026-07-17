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


# Deteccion de items NO-APU (honorarios, servicios, gastos generales): no son
# trabajo constructivo desglosable, van como monto global. Sirven para agrupar
# los rojos "legitimos" en un solo paso en la pantalla de revision (Fase 2.6).
_NO_APU_UNIDADES = {
    'gl', 'global', 'mes', 'meses', 'dia', 'dias', 'jornada',
    'hora', 'horas', 'hs', 'hh', 'semana', 'viaje', 'flete', '%', 'porcentaje',
}
_NO_APU_KEYWORDS = (
    'honorario', 'personal', 'servicio', 'administracion', 'direccion de obra',
    'direccion tecnica', 'representante tecnico', 'seguro', 'poliza', 'aseguradora',
    'art ', 'gestion', 'tramite', 'tasa', 'derecho de', 'impuesto de sellos', 'impuesto',
    'alquiler', 'movilidad', 'viatico', 'flete', 'acarreo', 'cartel de obra',
    'obrador', 'sereno', 'vigilancia', 'gastos generales', 'gasto general',
    'imprevisto', 'contingencia', 'ayuda de gremio', 'limpieza final',
    'ensayo', 'estudio de suelo', 'relevamiento', 'plano', 'documentacion',
)


def _es_no_apu(descripcion, unidad):
    """True si el item parece honorario/servicio/gasto general (monto global),
    no trabajo constructivo. Se usa solo para AGRUPAR rojos en revision."""
    import unicodedata
    u = (unidad or '').strip().lower()
    if u in _NO_APU_UNIDADES:
        return True
    d = (descripcion or '').lower()
    d = ''.join(ch for ch in unicodedata.normalize('NFD', d)
                if not unicodedata.combining(ch))
    return any(k in d for k in _NO_APU_KEYWORDS)


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


def procesar_items(items, *, organizacion_id, nivel='estandar', zona='CABA',
                   presupuesto=None, forzar_keyword=False):
    """Corre el pipeline completo sobre una lista de items {descripcion, unidad, cantidad}.

    Orden: aprendizaje por org -> clasificacion LLM -> descomposicion -> pricing -> score.
    """
    from services.coeficientes_loader import get_recursos
    from services.clasificador_llm import candidatos_para

    clasifs = _clasificar_con_aprendizaje(items, organizacion_id, forzar_keyword)

    precio_cache = {}  # (nombre, unidad, tipo) -> info (perf: dedup de recursos)
    salida = []
    resumen = {'verde': 0, 'amarillo': 0, 'rojo': 0, 'total': len(items),
               'fuente_clasificacion': 'aprendido', 'items_estimados': 0, 'aprendidos': 0,
               'rojos_no_apu': 0, 'rojos_constructivo': 0}
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
        detalle, costo_unit = (_precios_recursos(recursos, organizacion_id, zona, None, presupuesto, precio_cache)
                               if recursos else ([], Decimal('0')))

        # Scoring. Un item aprendido como 'manual' (lump-sum) queda RESUELTO (verde).
        if fuente == 'aprendido' and tratamiento == 'manual':
            color = 'verde'
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
            'precio_unitario': float(costo_unit),  # alias explicito para la UI (PASO 3)
            'costo_total': float(costo_unit * cantidad),
            'recursos_total': len(detalle),
            'recursos_sin_precio': sum(1 for r in detalle if r['precio'] <= 0 and not r['requiere_tc']),
            'precio_estimado': estimado,
            'requiere_tc': any(r['requiere_tc'] for r in detalle),
        }
        # Candidatos (para la pantalla de revision) solo en los que hay que revisar.
        if color in ('rojo', 'amarillo'):
            fila['candidatos'] = candidatos_para(it.get('descripcion'), it.get('unidad'), n=3)
        # Agrupacion de rojos: los no-APU (honorarios/servicios) se cargan como
        # monto global en un solo paso; los constructivos se revisan uno a uno.
        if color == 'rojo':
            es_no_apu = _es_no_apu(it.get('descripcion'), it.get('unidad'))
            fila['grupo_ayuda'] = 'no_apu' if es_no_apu else 'constructivo'
            resumen['rojos_no_apu' if es_no_apu else 'rojos_constructivo'] += 1
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
