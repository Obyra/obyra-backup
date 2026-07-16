# -*- coding: utf-8 -*-
"""Aprendizaje por organizacion (Fase 2.5).

- buscar_mapeos(org, descripciones): resuelve en batch los items ya aprendidos.
- guardar_correccion(...): upsert de una correccion del usuario.

El pipeline consulta buscar_mapeos ANTES del LLM: los items ya aprendidos se
resuelven directo (verde), sin gastar API.
"""
from extensions import db


def buscar_mapeos(organizacion_id, descripciones):
    """Devuelve {texto_normalizado: MapeoItemAprendido} para los textos ya
    aprendidos por esta org. Batch (una sola query)."""
    from models.mapeo_aprendido import MapeoItemAprendido, normalizar_texto_item

    if not organizacion_id or not descripciones:
        return {}
    norms = {normalizar_texto_item(d) for d in descripciones if d}
    norms.discard('')
    if not norms:
        return {}
    filas = MapeoItemAprendido.query.filter(
        MapeoItemAprendido.organizacion_id == organizacion_id,
        MapeoItemAprendido.texto_normalizado.in_(list(norms)),
    ).all()
    return {f.texto_normalizado: f for f in filas}


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
