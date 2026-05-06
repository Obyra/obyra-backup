"""Generador de composicion ejecutiva automatica (Fase 4).

Toma cada item del presupuesto que tiene `analisis_ia.regla_id` y crea
una serie de `ItemPresupuestoComposicion` (materiales + MO + equipos)
usando los coeficientes del YAML.

Reglas operativas:
  - Idempotente: si el item ya tiene composiciones con origen='calculadora_ia',
    salta el item (no duplica).
  - Respeta composiciones manuales: si el item tiene composiciones con
    origen != 'calculadora_ia', tambien salta. La sugerencia es que el
    usuario las borre antes de regenerar.
  - Filtra cantidades < 0.001 (ruido por coeficientes muy chicos).
  - Marca todas las composiciones generadas como `es_estimado=True` y
    `precio_unitario=0` (el precio se llena en la etapa de catalogo).
  - Sincroniza MaterialCotizable al final.
  - NO modifica presupuestos aprobados ni con ejecutivo aprobado (esa
    validacion esta en el endpoint).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from extensions import db


CANTIDAD_MINIMA = Decimal('0.001')

# Tipos validos para ItemPresupuestoComposicion.tipo. El YAML puede tener
# otros (ej: 'servicio') pero los mapeamos aca para mantener compat con la
# logica existente de sincronizar_materiales_cotizables.
TIPOS_VALIDOS = ('material', 'mano_obra', 'equipo')


def _normalizar_descripcion(s: str) -> str:
    """Normaliza descripcion para matching: lowercase, sin acentos, collapse spaces."""
    if not s:
        return ''
    import unicodedata, re
    s = str(s).strip().lower()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r'\s+', ' ', s)
    return s


def _match_catchall_para_item(descripcion: str, unidad: str = ''):
    """MVP autoclasificación 2026-05-06.

    Si el item no tiene regla_id (porque el matcher IA no se ejecutó o no
    matcheó nada), intenta matchear contra las reglas catch-all de
    REGLAS_TECNICAS que tienen `tipo_tratamiento` definido.

    Retorna {'regla_id': str, 'tipo_tratamiento': str, 'confianza': str}
    o None si no matchea.

    Match por keyword fuerte = alta. Por keyword media = media. Excluyentes
    bloquean el match.
    """
    if not descripcion:
        return None
    from services.base_tecnica_computos import REGLAS_TECNICAS

    desc_norm = _normalizar_descripcion(descripcion)
    unidad_norm = (unidad or '').strip().lower()

    mejor = None
    mejor_score = 0

    for regla in REGLAS_TECNICAS:
        tt = regla.get('tipo_tratamiento')
        if not tt:
            continue  # Solo evaluamos catch-all explícitas
        # Excluyentes: si alguna keyword excluyente está en la descripción, salta.
        excl = [_normalizar_descripcion(k) for k in regla.get('palabras_excluyentes', [])]
        if any(k and k in desc_norm for k in excl):
            continue

        score = 0
        for kw in regla.get('palabras_clave_fuertes', []) or []:
            kn = _normalizar_descripcion(kw)
            if kn and kn in desc_norm:
                score += 50
        for kw in regla.get('palabras_clave_medias', []) or []:
            kn = _normalizar_descripcion(kw)
            if kn and kn in desc_norm:
                score += 25
        for kw in regla.get('palabras_clave_debiles', []) or []:
            kn = _normalizar_descripcion(kw)
            if kn and kn in desc_norm:
                score += 10

        # Bonus por unidad coincidente
        unidades_validas = [u.lower() for u in regla.get('unidades_validas', []) or []]
        if unidad_norm and unidad_norm in unidades_validas:
            score += 5

        if score > mejor_score and score >= 50:  # mínimo: 1 keyword fuerte
            mejor_score = score
            mejor = regla

    if not mejor:
        return None
    confianza = 'alta' if mejor_score >= 50 else 'media'
    return {
        'regla_id': mejor.get('id'),
        'tipo_tratamiento': mejor.get('tipo_tratamiento'),
        'confianza': confianza,
        'score': mejor_score,
    }


def _tipo_tratamiento_de_regla(regla_id: str):
    """Devuelve el tipo_tratamiento (global/servicio/desglosar/excluir) declarado
    en la regla técnica si existe, sino None.
    """
    if not regla_id:
        return None
    from services.base_tecnica_computos import regla_por_id
    r = regla_por_id(regla_id)
    if not r:
        return None
    return (r.get('tipo_tratamiento') or '').lower() or None


def _normalizar_tipo(tipo_yaml: str) -> str:
    """Mapea tipos del YAML a los tipos validos en BD.

    En Fase 4, 'servicio' se mapea a 'equipo' por simplicidad (decision
    confirmada por producto). Si en el futuro queremos distinguir, agregar
    'servicio' como tipo valido y ajustar sincronizar_materiales_cotizables.
    """
    t = (tipo_yaml or '').strip().lower()
    if t in TIPOS_VALIDOS:
        return t
    if t == 'servicio':
        return 'equipo'
    if t in ('mo', 'manoobra'):
        return 'mano_obra'
    # Default a material si viene algo raro
    return 'material'


def _decimal(v) -> Decimal:
    """Convierte a Decimal de forma segura (devuelve 0 si no se puede)."""
    if v is None:
        return Decimal('0')
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal('0')


def _composiciones_existentes(item) -> Dict[str, int]:
    """Cuenta composiciones del item agrupadas por origen.

    Returns: {'manual': N, 'calculadora_ia': M, ...}
    """
    out: Dict[str, int] = {}
    try:
        for c in (item.composiciones.all() if hasattr(item.composiciones, 'all') else item.composiciones):
            o = (c.origen or 'manual').lower()
            out[o] = out.get(o, 0) + 1
    except Exception:
        pass
    return out


def _crear_composicion_item_completo(item, *, tipo: str, motivo: str) -> bool:
    """Crea una composición que representa el ítem entero, sin desglose.

    Útil cuando el ítem se trata como global/servicio/sin coeficiente: queda
    UNA fila en ItemPresupuestoComposicion con la cantidad y unidad del
    ítem, lista para que la Calculadora IA estime su precio o se mande a
    proveedores como recurso completo. Sin esto, el ítem queda con 0
    composiciones y el estimador no lo puede tocar.

    Idempotente: si ya existe una composición auto_ia para este item, no
    crea nada y devuelve False.
    """
    from models.budgets import ItemPresupuestoComposicion
    existentes = _composiciones_existentes(item)
    if existentes.get('calculadora_ia', 0) > 0:
        return False
    otras = sum(v for k, v in existentes.items() if k != 'calculadora_ia')
    if otras > 0:
        # Composiciones manuales presentes — no las pisamos
        return False
    cantidad = _decimal(item.cantidad)
    if cantidad <= 0:
        return False
    tipo_norm = _normalizar_tipo(tipo or 'material')
    descripcion = (getattr(item, 'descripcion', '') or '')[:300]
    unidad = (getattr(item, 'unidad', '') or 'gl')[:20]
    notas = (
        f'Ítem completo (sin desglose técnico). Motivo: {motivo}. '
        f'Estimable como recurso global o cotizable a proveedor.'
    )[:1000]
    comp = ItemPresupuestoComposicion(
        item_presupuesto_id=item.id,
        tipo=tipo_norm,
        descripcion=descripcion,
        unidad=unidad,
        cantidad=cantidad,
        precio_unitario=Decimal('0'),
        total=Decimal('0'),
        notas=notas,
        origen='calculadora_ia',
        es_estimado=True,
        coeficiente_usado=f'item_completo:{motivo}'[:80],
    )
    db.session.add(comp)
    return True


def generar_para_item(item, *, regla_id: Optional[str]) -> Dict[str, Any]:
    """Genera composiciones para UN item. Idempotente.

    Returns dict con:
      'estado': 'creado' | 'sin_regla' | 'sin_coeficiente' |
                'ya_generado' | 'respetado_manual' | 'cantidad_invalida' |
                'global_no_desglosa' | 'servicio_no_desglosa' | 'excluido'
      'composiciones_creadas': int
      'recursos_filtrados_chicos': int  (cantidad < 0.001)
    """
    from models.budgets import ItemPresupuestoComposicion
    from services.coeficientes_loader import get_recursos, tiene_coeficientes

    # Respeto al tipo_tratamiento elegido por el usuario:
    # 'global'    -> el item entra al ejecutivo como linea global, no se desglosa.
    # 'servicio'  -> se cotizara como servicio, no se desglosa con coeficientes.
    # 'excluir'   -> queda fuera del preliminar.
    # 'desglosar' -> flujo normal con coeficientes YAML.
    blob = getattr(item, 'analisis_ia', None) or {}
    tt = ''
    if isinstance(blob, dict):
        tt = (blob.get('tipo_tratamiento') or '').lower()
        if not tt:
            sug_tt = blob.get('sugerencias') if 'sugerencias' in blob else None
            if isinstance(sug_tt, dict):
                tt = (sug_tt.get('tipo_tratamiento') or '').lower()
    if tt == 'excluir':
        return {'estado': 'excluido', 'composiciones_creadas': 0}
    if tt == 'global':
        creada = _crear_composicion_item_completo(item, tipo='material', motivo='global')
        return {
            'estado': 'global_no_desglosa',
            'composiciones_creadas': 1 if creada else 0,
        }
    if tt == 'servicio':
        creada = _crear_composicion_item_completo(item, tipo='equipo', motivo='servicio')
        return {
            'estado': 'servicio_no_desglosa',
            'composiciones_creadas': 1 if creada else 0,
        }

    # MVP autoclasificación: si la regla técnica matcheada por IA tiene
    # tipo_tratamiento definido (ej: personal_admin, servicio_tecnico, etc.),
    # respetarlo aunque el usuario NO lo haya elegido manualmente. Esto
    # baja drásticamente la cantidad de items que quedan en "sin_regla" o
    # "sin_coeficiente" pidiendo clasificación manual.
    if regla_id:
        tt_regla = _tipo_tratamiento_de_regla(regla_id)
        if tt_regla in ('global', 'servicio', 'excluir'):
            # Persistir el tipo_tratamiento auto en el blob para que el resto
            # del sistema (vista ejecutiva, totales, banner) lo reconozca.
            try:
                if not isinstance(blob, dict):
                    blob = {}
                blob.setdefault('sugerencias', {})
                blob['tipo_tratamiento'] = tt_regla
                blob['tipo_tratamiento_origen'] = 'auto_regla_catchall'
                item.analisis_ia = blob
            except Exception:
                pass
            estado_map = {
                'global': 'global_auto', 'servicio': 'servicio_auto',
                'excluir': 'excluido',
            }
            comps_creadas = 0
            if tt_regla == 'global':
                if _crear_composicion_item_completo(item, tipo='material',
                                                    motivo='global_auto'):
                    comps_creadas = 1
            elif tt_regla == 'servicio':
                if _crear_composicion_item_completo(item, tipo='equipo',
                                                    motivo='servicio_auto'):
                    comps_creadas = 1
            return {'estado': estado_map[tt_regla],
                    'composiciones_creadas': comps_creadas}

    # Si NO hay regla_id (o el matcher IA no detectó nada), intentar el
    # matcher catch-all directamente acá. Cubre items que el usuario nunca
    # pasó por "Analizar con IA" (caso típico: imports nuevos sin click).
    if not regla_id:
        match = _match_catchall_para_item(
            getattr(item, 'descripcion', '') or '',
            getattr(item, 'unidad', '') or '',
        )
        if match:
            tt_match = match['tipo_tratamiento']
            try:
                if not isinstance(blob, dict):
                    blob = {}
                blob.setdefault('sugerencias', {})
                blob['sugerencias']['regla_id'] = match['regla_id']
                blob['sugerencias']['confianza'] = match['confianza']
                blob['tipo_tratamiento'] = tt_match
                blob['tipo_tratamiento_origen'] = 'auto_catchall_directo'
                item.analisis_ia = blob
            except Exception:
                pass
            estado_map = {
                'global': 'global_auto', 'servicio': 'servicio_auto',
                'excluir': 'excluido',
            }
            comps = 0
            if tt_match == 'global':
                if _crear_composicion_item_completo(item, tipo='material',
                                                    motivo='global_catchall'):
                    comps = 1
            elif tt_match == 'servicio':
                if _crear_composicion_item_completo(item, tipo='equipo',
                                                    motivo='servicio_catchall'):
                    comps = 1
            return {
                'estado': estado_map.get(tt_match, 'sin_regla'),
                'composiciones_creadas': comps,
            }
        return {'estado': 'sin_regla', 'composiciones_creadas': 0}

    if not tiene_coeficientes(regla_id):
        # MVP demo: aunque no tengamos coeficientes YAML para esta regla,
        # si el item ya quedó clasificado (regla_id presente), creamos UNA
        # composición item_completo para que la IA y proveedores puedan
        # avanzar. Sino el item queda invisible para el resto del sistema.
        creada = _crear_composicion_item_completo(item, tipo='material',
                                                  motivo=f'sin_coef_{regla_id}'[:50])
        return {
            'estado': 'sin_coeficiente_clasificado',
            'composiciones_creadas': 1 if creada else 0,
        }

    # Idempotencia + respeto a composiciones manuales
    existentes = _composiciones_existentes(item)
    if existentes.get('calculadora_ia', 0) > 0:
        return {'estado': 'ya_generado', 'composiciones_creadas': 0}
    # Si tiene composiciones de cualquier otro origen (manual / importado),
    # no las pisamos. El usuario debe borrarlas manualmente para regenerar.
    otras = sum(v for k, v in existentes.items() if k != 'calculadora_ia')
    if otras > 0:
        return {'estado': 'respetado_manual', 'composiciones_creadas': 0}

    cantidad_item = _decimal(item.cantidad)
    if cantidad_item <= 0:
        return {'estado': 'cantidad_invalida', 'composiciones_creadas': 0}

    recursos = get_recursos(regla_id)
    creadas = 0
    filtradas = 0

    for r in recursos:
        coef = _decimal(r.get('coeficiente'))
        if coef <= 0:
            continue
        cantidad_calc = (cantidad_item * coef).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
        if cantidad_calc < CANTIDAD_MINIMA:
            filtradas += 1
            continue

        notas_partes = ['Estimacion orientativa.', f'Coeficiente: {coef}.']
        if r.get('notas'):
            notas_partes.append(str(r['notas']))
        notas = ' '.join(notas_partes)[:1000]

        clave_yaml = f"{regla_id}.{r.get('clave', '')}"[:80]

        comp = ItemPresupuestoComposicion(
            item_presupuesto_id=item.id,
            tipo=_normalizar_tipo(r.get('tipo', 'material')),
            descripcion=str(r.get('nombre') or '')[:300],
            unidad=str(r.get('unidad') or '')[:20],
            cantidad=cantidad_calc,
            precio_unitario=Decimal('0'),
            total=Decimal('0'),
            notas=notas,
            origen='calculadora_ia',
            es_estimado=True,
            coeficiente_usado=clave_yaml,
        )
        db.session.add(comp)
        creadas += 1

    return {
        'estado': 'creado' if creadas else 'sin_recursos_validos',
        'composiciones_creadas': creadas,
        'recursos_filtrados_chicos': filtradas,
    }


def generar_preliminar(presupuesto, *, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Genera composiciones ejecutivas para todos los items del presupuesto.

    Retorna un dict con resumen + lista de items saltados (max 50).
    NO commitea. El caller (endpoint) hace el commit + audit log + sync.
    """
    from models.budgets import ItemPresupuesto
    from services.coeficientes_loader import metadatos as yaml_metadatos

    items = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
        solo_interno=False,
    ).order_by(ItemPresupuesto.id).all()

    contadores = {
        'items_procesados': 0,
        'items_creados': 0,
        'composiciones_creadas': 0,
        'items_ya_generado': 0,
        'items_respetado_manual': 0,
        'items_sin_regla': 0,
        'items_sin_coeficiente': 0,
        'items_clasificados_sin_coef': 0,  # MVP demo: tienen regla pero el YAML no tiene coef.
                                            # Quedan como item_completo, listos para cotizar.
        'items_cantidad_invalida': 0,
        'items_globales': 0,
        'items_servicio': 0,
        'items_excluidos': 0,
        'recursos_filtrados_chicos': 0,
        # MVP autoclasificación: items que la regla catch-all clasificó sola
        'items_globales_auto': 0,
        'items_servicio_auto': 0,
    }
    saltados: List[Dict[str, Any]] = []
    advertencias: List[str] = []

    for it in items:
        contadores['items_procesados'] += 1
        # Extraer regla_id del blob analisis_ia (lo guardado al aplicar IA)
        regla_id = None
        analisis = getattr(it, 'analisis_ia', None) or {}
        if isinstance(analisis, dict):
            sug = analisis.get('sugerencias') if 'sugerencias' in analisis else analisis
            if isinstance(sug, dict):
                regla_id = sug.get('regla_id')

        res = generar_para_item(it, regla_id=regla_id)
        estado = res['estado']
        contadores['composiciones_creadas'] += res.get('composiciones_creadas', 0)
        contadores['recursos_filtrados_chicos'] += res.get('recursos_filtrados_chicos', 0)

        if estado == 'creado':
            contadores['items_creados'] += 1
        elif estado == 'sin_regla':
            contadores['items_sin_regla'] += 1
            if len(saltados) < 50:
                saltados.append({
                    'item_id': it.id,
                    'descripcion': (it.descripcion or '')[:120],
                    'razon': 'Sin regla técnica detectada por la Calculadora IA. Aplicar análisis IA primero.',
                })
        elif estado == 'sin_coeficiente':
            contadores['items_sin_coeficiente'] += 1
            if len(saltados) < 50:
                saltados.append({
                    'item_id': it.id,
                    'descripcion': (it.descripcion or '')[:120],
                    'razon': f'Sin coeficiente cargado para esta regla técnica ({regla_id}).',
                })
        elif estado == 'sin_coeficiente_clasificado':
            # MVP demo: sin coeficiente YAML pero clasificado y con composición
            # item_completo. Cuenta como resuelto para cobertura.
            contadores['items_clasificados_sin_coef'] += 1
        elif estado == 'ya_generado':
            contadores['items_ya_generado'] += 1
        elif estado == 'respetado_manual':
            contadores['items_respetado_manual'] += 1
            if len(saltados) < 50:
                saltados.append({
                    'item_id': it.id,
                    'descripcion': (it.descripcion or '')[:120],
                    'razon': 'Respetado: el ítem ya tiene composiciones manuales.',
                })
        elif estado == 'cantidad_invalida':
            contadores['items_cantidad_invalida'] += 1
            if len(saltados) < 50:
                saltados.append({
                    'item_id': it.id,
                    'descripcion': (it.descripcion or '')[:120],
                    'razon': 'Cantidad del ítem es 0 o negativa.',
                })
        elif estado == 'global_no_desglosa':
            contadores['items_globales'] += 1
        elif estado == 'servicio_no_desglosa':
            contadores['items_servicio'] += 1
        elif estado == 'global_auto':
            contadores['items_globales_auto'] += 1
        elif estado == 'servicio_auto':
            contadores['items_servicio_auto'] += 1
        elif estado == 'excluido':
            contadores['items_excluidos'] += 1

    # Advertencias contextuales
    if contadores['items_sin_regla'] > 0:
        advertencias.append(
            f'{contadores["items_sin_regla"]} ítems no tienen regla técnica detectada. '
            'Abrí "Analizar con IA" y aplicá el análisis antes de regenerar.'
        )
    if contadores['items_sin_coeficiente'] > 0:
        advertencias.append(
            f'{contadores["items_sin_coeficiente"]} ítems tienen regla técnica pero todavía no '
            'hay coeficiente cargado para esa regla en el YAML del producto.'
        )
    if contadores['items_respetado_manual'] > 0:
        advertencias.append(
            f'{contadores["items_respetado_manual"]} ítems se respetaron porque ya tenían '
            'composiciones manuales. Borralas antes si querés regenerar.'
        )

    # Cobertura: tres métricas separadas para mejor lectura del demo.
    # 1) Cobertura de clasificación: items con clasificación clara
    #    (cualquier estado resuelto, incluyendo globales/servicios y items
    #    clasificados sin coef YAML que quedaron como item_completo).
    # 2) Cobertura de composición técnica: solo items que se descompusieron
    #    en materiales/MO/equipos (`items_creados`).
    # 3) Items listos para cotizar: cualquier item con composición
    #    (descompuesto, global, servicio, item_completo) — la IA puede
    #    estimar precio sobre todos ellos.
    total = contadores['items_procesados']
    globales_total = contadores['items_globales'] + contadores['items_globales_auto']
    servicios_total = contadores['items_servicio'] + contadores['items_servicio_auto']
    descompuestos = contadores['items_creados']
    clasificados_sin_coef = contadores['items_clasificados_sin_coef']
    # Items con AL MENOS UNA composición (estimable por IA / proveedor).
    items_listos_cotizar = (
        descompuestos
        + globales_total
        + servicios_total
        + clasificados_sin_coef
    )
    # Items resueltos a nivel clasificación (incluye respetados y excluidos).
    items_resueltos = (
        items_listos_cotizar
        + contadores['items_ya_generado']
        + contadores['items_excluidos']
        + contadores['items_respetado_manual']
    )
    pendientes_reales = (
        contadores['items_sin_regla']
        + contadores['items_sin_coeficiente']  # legacy: items con sin coef sin item_completo creado
        + contadores['items_cantidad_invalida']
    )
    cobertura_clasificacion_pct = round(100.0 * items_resueltos / total, 1) if total > 0 else 0.0
    cobertura_composicion_pct = round(100.0 * descompuestos / total, 1) if total > 0 else 0.0
    cobertura_listos_cotizar_pct = round(100.0 * items_listos_cotizar / total, 1) if total > 0 else 0.0

    return {
        'contadores': contadores,
        'saltados': saltados,
        'saltados_truncado': max(0,
            (contadores['items_sin_regla']
             + contadores['items_sin_coeficiente']
             + contadores['items_respetado_manual']
             + contadores['items_cantidad_invalida'])
            - len(saltados)
        ),
        'advertencias': advertencias,
        'yaml_version': yaml_metadatos().get('version'),
        # Cobertura: 3 métricas separadas
        'cobertura_pct': cobertura_clasificacion_pct,                  # principal del banner (compat)
        'cobertura_clasificacion_pct': cobertura_clasificacion_pct,    # nuevo
        'cobertura_composicion_pct': cobertura_composicion_pct,         # nuevo
        'cobertura_listos_cotizar_pct': cobertura_listos_cotizar_pct,   # nuevo (KPI demo)
        'items_total': total,
        'items_resueltos': items_resueltos,
        'items_listos_cotizar': items_listos_cotizar,
        'items_descompuestos': descompuestos,
        'items_globales_total': globales_total,
        'items_servicios_total': servicios_total,
        'items_clasificados_sin_coef': clasificados_sin_coef,
        'pendientes_reales': pendientes_reales,
    }
