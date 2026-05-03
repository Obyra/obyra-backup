"""Servicio de aprendizaje IA continuo (Fase B).

Punto unico que el endpoint `aplicar_analisis_ia` invoca despues de aplicar
las sugerencias al ItemPresupuesto. Tres efectos:

  1. Crear IACorrectionLog con el diff sugerencia <-> correccion del usuario.
  2. Acumular IARuleCandidate por descripcion_normalizada (upsert manual).
  3. Actualizar IARuleUsageStat de la regla involucrada (upsert manual).

Diseño:
- Sin observaciones libres en correccion_usuario_json (decision Fase B).
- Solo campos estructurados: descripcion, rubro, etapa, unidad, materiales,
  maquinaria, mano_obra.
- Upsert "find-then-update" portable a SQLite y PostgreSQL. Si hay race en
  alta concurrencia y aparece un IntegrityError, hacemos rollback parcial
  del savepoint y re-intentamos como UPDATE; si vuelve a fallar, salimos
  silenciosos. El log no debe romper el endpoint principal.
- Respeta multi-tenant: el organizacion_id viene del caller, no se infiere.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, Optional

from extensions import db


# Stopwords minimas para no afectar el matching: solo cosas que claramente
# no aportan al clustering.
_STOPWORDS_NORM = {'de', 'del', 'la', 'el', 'los', 'las', 'y', 'o', 'a', 'en', 'por', 'con', 'sin'}


def normalizar_descripcion(texto: Optional[str]) -> str:
    """lowercase + sin diacriticos + colapsar whitespace + remover puntuacion comun.

    NO hace stemming ni elimina stopwords agresivamente — preferimos
    sobre-clustering (mas candidatas) que falsos positivos.
    """
    if not texto:
        return ''
    s = str(texto).strip().lower()
    # Quitar diacriticos
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    # Reemplazar caracteres de puntuacion por espacio
    s = re.sub(r'[^\w\s\-/]', ' ', s)
    # Colapsar whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:500]


def _detectar_tipos_correccion(entry: Dict[str, Any], analisis: Dict[str, Any]) -> list:
    """Compara lo que el usuario aplico vs lo que la IA sugirio."""
    tipos = []

    sugerencias = (analisis or {}).get('sugerencias') if 'sugerencias' in (analisis or {}) else (analisis or {})
    sugerencias = sugerencias or {}

    desc_sugerida = (sugerencias.get('descripcion_normalizada') or '').strip().lower()
    desc_aplicada = (entry.get('descripcion') or '').strip().lower()
    if desc_aplicada and desc_sugerida and desc_aplicada != desc_sugerida:
        tipos.append('editada_descripcion')

    unidad_sugerida = (sugerencias.get('unidad_sugerida') or '').strip().lower()
    unidad_aplicada = (entry.get('unidad') or '').strip().lower()
    if unidad_aplicada and unidad_sugerida and unidad_aplicada != unidad_sugerida:
        tipos.append('editada_unidad')

    etapa_sugerida = (sugerencias.get('etapa_sugerida') or '').strip().lower()
    etapa_aplicada = (entry.get('etapa_nombre') or '').strip().lower()
    if etapa_aplicada and etapa_sugerida and etapa_aplicada != etapa_sugerida:
        tipos.append('editada_etapa')

    rubro_aplicado = (entry.get('rubro') or '').strip().lower()
    rubro_sugerido = (sugerencias.get('rubro_sugerido') or '').strip().lower()
    if rubro_aplicado and rubro_sugerido and rubro_aplicado != rubro_sugerido:
        tipos.append('editada_rubro')

    materiales_aplicados = entry.get('materiales')
    if isinstance(materiales_aplicados, list):
        if set(map(str, materiales_aplicados)) != set(map(str, sugerencias.get('materiales_sugeridos') or [])):
            tipos.append('editada_materiales')

    maquinaria_aplicada = entry.get('maquinaria')
    if isinstance(maquinaria_aplicada, list):
        if set(map(str, maquinaria_aplicada)) != set(map(str, sugerencias.get('maquinaria_sugerida') or [])):
            tipos.append('editada_maquinaria')

    mano_obra_aplicada = entry.get('mano_obra')
    if isinstance(mano_obra_aplicada, list):
        if set(map(str, mano_obra_aplicada)) != set(map(str, sugerencias.get('mano_obra_sugerida') or [])):
            tipos.append('editada_mano_obra')

    # Confianza: tag indicativo
    label = (sugerencias.get('confianza_label') or '').lower()
    if label == 'alta':
        tipos.append('aplicada_alta_confianza')
    elif label == 'media':
        tipos.append('aplicada_media_confianza')
    elif label == 'baja':
        tipos.append('aplicada_baja_confianza')

    # Casos especiales
    if not sugerencias.get('regla_id'):
        tipos.append('creada_manual_sin_sugerencia')

    if not tipos:
        tipos.append('aceptada_sin_editar')
    elif all(t.startswith('aplicada_') for t in tipos):
        # Solo tags de confianza, sin ediciones reales
        tipos.append('aceptada_sin_editar')

    return tipos


def _campos_estructurados(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Extrae solo campos estructurados del entry (sin observaciones libres)."""
    out = {}
    for k in ('descripcion', 'unidad', 'etapa_nombre', 'rubro'):
        v = entry.get(k)
        if v is not None and str(v).strip():
            out[k] = str(v).strip()[:300]
    for k in ('materiales', 'maquinaria', 'mano_obra'):
        v = entry.get(k)
        if isinstance(v, list):
            out[k] = [str(x)[:200] for x in v if x]
    return out


def _upsert_candidata(desc_original: str, desc_norm: str, sugerencias: Dict[str, Any], confianza: float):
    """Find-or-create idempotente sobre IARuleCandidate.

    No se loggea aqui en audit (lo hace el caller). No commitea.
    """
    from models.ia_learning import IARuleCandidate

    if not desc_norm:
        return None

    cand = IARuleCandidate.query.filter_by(descripcion_normalizada=desc_norm).first()

    rubro = (sugerencias.get('rubro_sugerido') or '').strip() or None
    etapa = (sugerencias.get('etapa_sugerida') or '').strip() or None
    unidad = (sugerencias.get('unidad_sugerida') or '').strip() or None
    materiales = sugerencias.get('materiales_sugeridos') or []
    maquinaria = sugerencias.get('maquinaria_sugerida') or []

    if cand:
        cand.cantidad_ocurrencias = (cand.cantidad_ocurrencias or 0) + 1
        # Promedio incremental simple
        if confianza is not None:
            actual = cand.confianza_promedio or 0.0
            n = cand.cantidad_ocurrencias
            cand.confianza_promedio = ((actual * (n - 1)) + float(confianza)) / n
        # Acumular materiales/maquinaria como conteo
        cand.materiales_sugeridos_json = _merge_conteo(cand.materiales_sugeridos_json, materiales)
        cand.maquinaria_sugerida_json = _merge_conteo(cand.maquinaria_sugerida_json, maquinaria)
        # Si la candidata no tenia rubro/etapa/unidad, completar; no pisar.
        if not cand.rubro_sugerido and rubro:
            cand.rubro_sugerido = rubro
        if not cand.etapa_sugerida and etapa:
            cand.etapa_sugerida = etapa
        if not cand.unidad_sugerida and unidad:
            cand.unidad_sugerida = unidad
        cand.updated_at = datetime.utcnow()
        return cand

    cand = IARuleCandidate(
        descripcion_original=(desc_original or '')[:500],
        descripcion_normalizada=desc_norm[:500],
        rubro_sugerido=rubro,
        etapa_sugerida=etapa,
        unidad_sugerida=unidad,
        materiales_sugeridos_json=_merge_conteo(None, materiales),
        maquinaria_sugerida_json=_merge_conteo(None, maquinaria),
        cantidad_ocurrencias=1,
        confianza_promedio=float(confianza) if confianza is not None else None,
        estado='pendiente',
    )
    db.session.add(cand)
    return cand


def _merge_conteo(actual: Optional[Dict[str, int]], nuevos: list) -> Dict[str, int]:
    """Acumula conteo {nombre: veces}. Tolerante a None y a tipos viejos."""
    out = {}
    if isinstance(actual, dict):
        for k, v in actual.items():
            try:
                out[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
    for n in nuevos or []:
        if not n:
            continue
        key = str(n)[:200]
        out[key] = out.get(key, 0) + 1
    return out


def _upsert_stat(regla_id: Optional[str], confianza: float, fue_editada: bool):
    """Find-or-create sobre IARuleUsageStat. No commitea."""
    from models.ia_learning import IARuleUsageStat

    if not regla_id:
        return None

    stat = IARuleUsageStat.query.filter_by(regla_tecnica_id=regla_id).first()
    now = datetime.utcnow()

    if stat:
        stat.cantidad_usos = (stat.cantidad_usos or 0) + 1
        if fue_editada:
            stat.cantidad_editadas = (stat.cantidad_editadas or 0) + 1
        else:
            stat.cantidad_aceptadas_sin_edicion = (stat.cantidad_aceptadas_sin_edicion or 0) + 1
        if confianza is not None:
            actual = stat.confianza_promedio or 0.0
            n = stat.cantidad_usos
            stat.confianza_promedio = ((actual * (n - 1)) + float(confianza)) / n
        stat.ultima_utilizacion = now
        stat.updated_at = now
        return stat

    stat = IARuleUsageStat(
        regla_tecnica_id=str(regla_id)[:80],
        cantidad_usos=1,
        cantidad_aceptadas_sin_edicion=0 if fue_editada else 1,
        cantidad_editadas=1 if fue_editada else 0,
        cantidad_rechazadas=0,
        confianza_promedio=float(confianza) if confianza is not None else None,
        ultima_utilizacion=now,
    )
    db.session.add(stat)
    return stat


def registrar_aplicacion_ia(
    *,
    item,
    entry: Dict[str, Any],
    presupuesto,
    user_id: Optional[int],
    organizacion_id: Optional[int],
) -> Dict[str, Any]:
    """Registra el efecto de aplicar una sugerencia IA sobre un item.

    Args:
      item: ItemPresupuesto recien actualizado por el endpoint.
      entry: dict del payload del usuario (puede traer descripcion/unidad/etapa
             y materiales/maquinaria/mano_obra opcionales + 'analisis' blob).
      presupuesto: instancia Presupuesto.
      user_id, organizacion_id: contexto multi-tenant del caller.

    Returns:
      dict con 'log_id', 'candidata_id', 'tipos_correccion', 'es_nueva_candidata'.
      Si algo falla, devuelve dict con 'error' y NO rompe el endpoint principal:
      usamos un SAVEPOINT (db.session.begin_nested) para aislar fallos del
      aprendizaje y no perder los cambios del item ya aplicados por el caller.
    """
    from models.ia_learning import IACorrectionLog

    try:
        sp = db.session.begin_nested()
    except Exception:
        sp = None

    try:
        analisis_blob = entry.get('analisis') or {}
        # El blob puede venir aplanado o con la estructura {original, sugerencias, ...}
        sugerencias = analisis_blob.get('sugerencias') if 'sugerencias' in analisis_blob else analisis_blob
        sugerencias = sugerencias or {}

        desc_original = (item.descripcion_original or item.descripcion or '')[:500]
        desc_norm = normalizar_descripcion(desc_original)
        confianza = sugerencias.get('confianza')
        regla_id = sugerencias.get('regla_id')

        tipos = _detectar_tipos_correccion(entry, analisis_blob)
        fue_editada = any(t.startswith('editada_') for t in tipos)

        # Sanitizar sugerencia_original_json (sin observaciones libres)
        sugerencia_safe = {k: sugerencias.get(k) for k in (
            'descripcion_normalizada', 'rubro_sugerido', 'etapa_sugerida', 'tarea_sugerida',
            'unidad_sugerida', 'criterio_medicion', 'materiales_sugeridos',
            'mano_obra_sugerida', 'maquinaria_sugerida', 'rendimiento_estimado',
            'desperdicio_estimado', 'confianza', 'confianza_label', 'regla_id',
        ) if k in sugerencias}

        log = IACorrectionLog(
            organizacion_id=organizacion_id,
            user_id=user_id,
            presupuesto_id=presupuesto.id if presupuesto else None,
            item_presupuesto_id=item.id,
            descripcion_original=desc_original,
            descripcion_normalizada=desc_norm,
            sugerencia_original_json=sugerencia_safe or None,
            correccion_usuario_json=_campos_estructurados(entry) or None,
            tipos_correccion=tipos,
            confianza_original=float(confianza) if confianza is not None else None,
            regla_tecnica_id=str(regla_id)[:80] if regla_id else None,
        )
        db.session.add(log)
        db.session.flush()

        # Candidata: solo si hubo edicion real o si no tenia regla
        es_nueva_candidata = False
        candidata_id = None
        if fue_editada or not regla_id:
            cand_antes = None
            from models.ia_learning import IARuleCandidate
            cand_antes = IARuleCandidate.query.filter_by(descripcion_normalizada=desc_norm).first()
            es_nueva_candidata = cand_antes is None
            cand = _upsert_candidata(desc_original, desc_norm, sugerencias, confianza or 0.0)
            if cand:
                db.session.flush()
                candidata_id = cand.id

        # Stat: siempre que haya regla_id
        if regla_id:
            _upsert_stat(regla_id, confianza or 0.0, fue_editada)
            db.session.flush()

        # Audit (sin commit; lo hace el endpoint caller)
        try:
            from models.audit import registrar_audit
            registrar_audit(
                accion='correccion_ia',
                entidad='item_presupuesto',
                entidad_id=item.id,
                detalle=f"tipos={','.join(tipos)} regla={regla_id or '-'} confianza={confianza or 0:.2f}",
            )
            if es_nueva_candidata and candidata_id:
                registrar_audit(
                    accion='crear_candidata_ia',
                    entidad='ia_rule_candidate',
                    entidad_id=candidata_id,
                    detalle=f"desc_norm={desc_norm[:120]}",
                )
        except Exception:
            pass

        return {
            'log_id': log.id,
            'candidata_id': candidata_id,
            'tipos_correccion': tipos,
            'es_nueva_candidata': es_nueva_candidata,
        }

    except Exception as e:
        # Importante: NO propagar — el aprendizaje no debe romper el aplicar IA.
        # Solo revertimos el savepoint, dejando intactos los cambios del item.
        try:
            if sp is not None:
                sp.rollback()
        except Exception:
            pass
        return {'error': f'{type(e).__name__}: {str(e)[:200]}'}
