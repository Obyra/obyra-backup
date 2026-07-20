# -*- coding: utf-8 -*-
"""Aprendizaje por organizacion (Fase 2.5).

- buscar_mapeos(org, descripciones): resuelve en batch los items ya aprendidos.
- guardar_correccion(...): upsert de una correccion del usuario.

El pipeline consulta buscar_mapeos ANTES del LLM: los items ya aprendidos se
resuelven directo (verde), sin gastar API.
"""
from extensions import db


def _tokset(texto_norm):
    """Set de tokens significativos para comparar por similitud: len>=3, o numericos
    cortos (espesores/medidas como '12','18' distinguen materiales -> no se ignoran)."""
    return {t for t in (texto_norm or '').split() if len(t) >= 3 or t.isdigit()}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


# Umbral de similitud para aplicar un mapeo aprendido a un item PARECIDO (no exacto).
# 0.70 matchea variantes de acabado ("tabique ... doble placa verde" vs "... estandar",
# ~0.71) sin confundir materiales/espesores distintos ("ladrillo hueco 12" vs "comun
# 12", ~0.6). Tuneable si sobre/sub-matchea.
_SIM_UMBRAL = 0.70


def buscar_mapeos(organizacion_id, descripciones):
    """Devuelve {texto_normalizado_del_item: MapeoItemAprendido} para los items ya
    aprendidos por esta org. Primero match EXACTO; para los que no matchean, match
    por SIMILITUD de tokens (Jaccard >= umbral) -> resolver un item resuelve a los
    casi-identicos (ej. 'doble placa verde' y 'doble placa estandar')."""
    from models.mapeo_aprendido import MapeoItemAprendido, normalizar_texto_item

    if not organizacion_id or not descripciones:
        return {}
    q_norms = {normalizar_texto_item(d) for d in descripciones if d}
    q_norms.discard('')
    if not q_norms:
        return {}

    # 1. Match exacto (batch).
    filas = MapeoItemAprendido.query.filter(
        MapeoItemAprendido.organizacion_id == organizacion_id,
        MapeoItemAprendido.texto_normalizado.in_(list(q_norms)),
    ).all()
    res = {f.texto_normalizado: f for f in filas}

    # 2. Similitud para los que no matchearon exacto.
    faltan = [n for n in q_norms if n not in res]
    if faltan:
        todos = (MapeoItemAprendido.query
                 .filter_by(organizacion_id=organizacion_id).limit(3000).all())
        stored = [(f, _tokset(f.texto_normalizado)) for f in todos]
        stored = [(f, ts) for f, ts in stored if len(ts) >= 2]
        for n in faltan:
            ts = _tokset(n)
            if len(ts) < 3:  # descripciones muy cortas: no arriesgar fuzzy
                continue
            best, best_sim = None, 0.0
            for f, fts in stored:
                sim = _jaccard(ts, fts)
                if sim > best_sim:
                    best_sim, best = sim, f
            if best is not None and best_sim >= _SIM_UMBRAL:
                res[n] = best
    return res


def guardar_correccion(organizacion_id, descripcion, *, regla_id=None, nivel='estandar',
                       tratamiento='apu', user_id=None):
    """Upsert de una correccion (por org + texto_normalizado). Devuelve el mapeo."""
    from models.mapeo_aprendido import MapeoItemAprendido, normalizar_texto_item, TRATAMIENTOS_MAPEO

    if not organizacion_id:
        raise ValueError('organizacion_id requerido')
    tn = normalizar_texto_item(descripcion)
    if not tn:
        raise ValueError('descripcion vacia')
    if tratamiento not in TRATAMIENTOS_MAPEO:
        tratamiento = 'apu'
    if tratamiento == 'manual':
        regla_id = None  # lump-sum: sin regla

    fila = MapeoItemAprendido.query.filter_by(
        organizacion_id=organizacion_id, texto_normalizado=tn,
    ).first()
    if fila is None:
        fila = MapeoItemAprendido(
            organizacion_id=organizacion_id, texto_normalizado=tn,
            texto_original=(descripcion or '')[:400], created_by_id=user_id,
        )
        db.session.add(fila)
    fila.regla_id = regla_id
    fila.nivel = nivel or 'estandar'
    fila.tratamiento = tratamiento
    db.session.commit()
    return fila
