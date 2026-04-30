"""Análisis IA de items de un presupuesto importado desde Excel.

V2 — usa la Base Tecnica de Computos OBYRA para reconocer rubros, etapas,
unidades, materiales, mano de obra y maquinaria con scoring granular y
confianza realista.

Estrategia:
  1. Para cada item del presupuesto, evaluar TODAS las reglas tecnicas.
  2. Cada regla aporta un score:
       +0.50 por palabra clave FUERTE matcheada
       +0.25 por palabra clave MEDIA
       +0.10 por palabra clave DEBIL
       +0.20 si la unidad esta dentro de unidades_validas
       +0.05 si la etapa actual del item coincide con la etapa de la regla
       -0.50 si aparece una palabra excluyente (descarta la regla)
  3. La regla con mayor score determina la sugerencia.
  4. Si score >= 0.70 -> alta confianza; >= 0.50 media; >= 0.30 baja;
     < 0.30 sin sugerencia (o solo etapa por matcher fallback).
  5. Fallback: si ninguna regla matchea, intentar `etapa_matcher` con
     confianza limitada a 0.40.

NO modifica BD: solo retorna estructuras Python con sugerencias.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from services.base_tecnica_computos import REGLAS_TECNICAS

logger = logging.getLogger(__name__)


# Diccionario de unidades aceptadas (sinónimos -> estándar)
SINONIMOS_UNIDAD = {
    'm2': {'m2', 'm²', 'mts2', 'mt2', 'metro cuadrado', 'metros cuadrados'},
    'm3': {'m3', 'm³', 'mts3', 'metro cubico', 'metro cúbico', 'metros cubicos'},
    'm':  {'m', 'ml', 'metro', 'metros', 'mt', 'mts', 'metro lineal'},
    'kg': {'kg', 'kilo', 'kilos', 'kilogramo', 'kilogramos'},
    'tn': {'tn', 't', 'tonelada', 'toneladas'},
    'l':  {'l', 'lt', 'lts', 'litro', 'litros'},
    'h':  {'h', 'hora', 'horas', 'hs'},
    'dia': {'dia', 'dias', 'día', 'días', 'jornada', 'jornadas'},
    'mes': {'mes', 'meses'},
    'jornal': {'jornal', 'jornales'},
    'unidad': {'un', 'u', 'unidad', 'unidades', 'pieza', 'piezas', 'boca'},
    'gl': {'gl', 'gbl', 'global', 'g'},
    'bolsa': {'bolsa', 'bolsas'},
    'caja': {'caja', 'cajas'},
}


def _normalizar(s: str) -> str:
    """Lowercase + sin acentos + espacios colapsados."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('ascii')
    s = s.lower()
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _unidad_estandar(unidad: str) -> Optional[str]:
    """Devuelve la unidad estándar a partir de un sinónimo, o None."""
    u = _normalizar(unidad)
    if not u:
        return None
    for std, sinonimos in SINONIMOS_UNIDAD.items():
        if u == std or u in {_normalizar(s) for s in sinonimos}:
            return std
    return None


def _evaluar_regla(regla: Dict[str, Any], desc_norm: str, unidad_actual: str, etapa_actual: Optional[str]) -> float:
    """Calcula score 0..1+ de cuán bien una regla matchea un item."""
    # Si aparece palabra excluyente -> descartar
    for kw_ex in regla.get('palabras_excluyentes', []) or []:
        if _normalizar(kw_ex) and _normalizar(kw_ex) in desc_norm:
            return 0.0

    score = 0.0
    matched_strong = 0
    matched_medium = 0
    matched_weak = 0

    for kw in regla.get('palabras_clave_fuertes', []) or []:
        kw_norm = _normalizar(kw)
        if kw_norm and kw_norm in desc_norm:
            matched_strong += 1
            score += 0.50

    if matched_strong == 0:  # solo evaluar medias/débiles si no hay fuerte
        for kw in regla.get('palabras_clave_medias', []) or []:
            kw_norm = _normalizar(kw)
            if kw_norm and kw_norm in desc_norm:
                matched_medium += 1
                score += 0.25

        if matched_medium == 0:
            for kw in regla.get('palabras_clave_debiles', []) or []:
                kw_norm = _normalizar(kw)
                if kw_norm and kw_norm in desc_norm:
                    matched_weak += 1
                    score += 0.10

    # Bonus por unidad coincidente
    unidad_std = _unidad_estandar(unidad_actual)
    unidades_validas = {_unidad_estandar(u) or _normalizar(u) for u in (regla.get('unidades_validas') or [])}
    unidades_validas.discard(None)
    if unidad_std and unidad_std in unidades_validas:
        score += 0.20

    # Bonus si la etapa actual ya está alineada
    etapa_regla_norm = _normalizar(regla.get('etapa') or '')
    if etapa_actual and etapa_regla_norm:
        if _normalizar(etapa_actual) == etapa_regla_norm:
            score += 0.05

    return round(score, 3)


def _mejor_regla(desc: str, unidad: str, etapa_actual: Optional[str]) -> Tuple[Optional[Dict[str, Any]], float]:
    """Recorre todas las reglas y devuelve la de mayor score (con su valor)."""
    desc_norm = _normalizar(desc)
    if not desc_norm:
        return (None, 0.0)
    mejor = None
    mejor_score = 0.0
    for regla in REGLAS_TECNICAS:
        s = _evaluar_regla(regla, desc_norm, unidad, etapa_actual)
        if s > mejor_score:
            mejor_score = s
            mejor = regla
    return (mejor, mejor_score)


def _normalizar_descripcion(descripcion: str) -> Optional[str]:
    """Normalización ligera: trim + capital + espacios + abreviaturas."""
    if not descripcion:
        return None
    s = descripcion.strip()
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    s = re.sub(r'\bH\s*°?\s*A\s*°?\b', 'H°A°', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+', ' ', s)
    return s if s != descripcion else None


def _confianza_label(score: float) -> str:
    """Etiqueta de confianza según score 0..1."""
    if score >= 0.80:
        return 'alta'
    if score >= 0.60:
        return 'media'
    if score >= 0.30:
        return 'baja'
    return 'sin'


def analizar_items_con_ia(items_payload: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analiza items y retorna sugerencias estructuradas.

    Retorna dict con:
      'items': [
        {
          'id': int,
          'original': {descripcion, unidad, cantidad, etapa_nombre, tipo},
          'sugerencias': {
              'descripcion_normalizada': str | None,
              'rubro_sugerido': str | None,
              'etapa_sugerida': str | None,
              'tarea_sugerida': str | None,
              'unidad_sugerida': str | None,
              'criterio_medicion': str | None,
              'materiales_sugeridos': [str],
              'mano_obra_sugerida': [str],
              'maquinaria_sugerida': [str],
              'rendimiento_estimado': str | None,
              'desperdicio_estimado': str | None,
              'observaciones_ia': str,
              'confianza': float,        # 0..1
              'confianza_label': str,    # alta | media | baja | sin
              'regla_id': str | None,
          },
          'cambios_detectados': bool,
        }
      ],
      'total_items', 'items_con_cambios',
      'breakdown_confianza': {alta, media, baja, sin},
      'fuente': 'base_tecnica_computos_v2',
    """
    from services.etapa_matcher import matchear_etapa_estandar

    resultados = []
    breakdown = {'alta': 0, 'media': 0, 'baja': 0, 'sin': 0}
    items_con_cambios = 0

    for item in items_payload or []:
        descripcion = (item.get('descripcion') or '').strip()
        unidad = (item.get('unidad') or '').strip()
        etapa_actual = (item.get('etapa_nombre') or '').strip() or None

        # 1) Buscar la mejor regla técnica
        regla, score = _mejor_regla(descripcion, unidad, etapa_actual)

        # 2) Normalización de descripción (siempre)
        desc_norm = _normalizar_descripcion(descripcion)

        if regla and score >= 0.30:
            sugerencias = {
                'descripcion_normalizada': desc_norm,
                'rubro_sugerido': regla.get('rubro'),
                'etapa_sugerida': regla.get('etapa'),
                'tarea_sugerida': regla.get('tarea'),
                'unidad_sugerida': regla.get('unidad_esperada'),
                'criterio_medicion': regla.get('criterio_medicion'),
                'materiales_sugeridos': list(regla.get('materiales_sugeridos') or []),
                'mano_obra_sugerida': list(regla.get('mano_obra_sugerida') or []),
                'maquinaria_sugerida': list(regla.get('maquinaria_sugerida') or []),
                'rendimiento_estimado': regla.get('rendimiento_estimado'),
                'desperdicio_estimado': regla.get('desperdicio_estimado'),
                'observaciones_ia': regla.get('observaciones_tecnicas') or '',
                'confianza': min(round(score, 2), 1.0),
                'regla_id': regla.get('id'),
            }
            # Si la unidad actual ya es la esperada, no sugerir cambio
            if _unidad_estandar(unidad) == regla.get('unidad_esperada'):
                sugerencias['unidad_sugerida'] = None
            # Si la etapa ya está alineada, no sugerir cambio
            if etapa_actual and _normalizar(etapa_actual) == _normalizar(regla.get('etapa') or ''):
                sugerencias['etapa_sugerida'] = None
                sugerencias['rubro_sugerido'] = None
        else:
            # Fallback: solo etapa por matcher viejo, confianza limitada
            etapa_fallback = matchear_etapa_estandar(descripcion)
            sugerencias = {
                'descripcion_normalizada': desc_norm,
                'rubro_sugerido': None,
                'etapa_sugerida': etapa_fallback if etapa_fallback and _normalizar(etapa_fallback) != _normalizar(etapa_actual or '') else None,
                'tarea_sugerida': None,
                'unidad_sugerida': None,
                'criterio_medicion': None,
                'materiales_sugeridos': [],
                'mano_obra_sugerida': [],
                'maquinaria_sugerida': [],
                'rendimiento_estimado': None,
                'desperdicio_estimado': None,
                'observaciones_ia': 'Item sin coincidencia clara con la base tecnica. Revisar manualmente.',
                'confianza': 0.20 if etapa_fallback else 0.0,
                'regla_id': None,
            }

        # Etiqueta y observaciones extra
        sugerencias['confianza_label'] = _confianza_label(sugerencias['confianza'])
        breakdown[sugerencias['confianza_label']] += 1

        if not unidad and not sugerencias.get('unidad_sugerida'):
            sep = ' / ' if sugerencias['observaciones_ia'] else ''
            sugerencias['observaciones_ia'] = (
                (sugerencias['observaciones_ia'] or '') + sep +
                'Item sin unidad cargada.'
            )

        # ¿Hay cambios reales para aplicar?
        cambios = bool(
            sugerencias['descripcion_normalizada']
            or sugerencias['etapa_sugerida']
            or sugerencias['unidad_sugerida']
            or sugerencias['materiales_sugeridos']
            or sugerencias['maquinaria_sugerida']
        )
        if cambios:
            items_con_cambios += 1

        resultados.append({
            'id': item.get('id'),
            'original': {
                'descripcion': descripcion,
                'unidad': unidad,
                'cantidad': item.get('cantidad'),
                'etapa_nombre': etapa_actual,
                'tipo': item.get('tipo'),
            },
            'sugerencias': sugerencias,
            'cambios_detectados': cambios,
        })

    # Auditoria adicional: distribucion por rubro, top baja confianza,
    # y candidatos a falsos positivos en "Preliminares y Organización".
    breakdown_rubro = {}
    items_preliminares = []
    items_para_ranking = []

    for r in resultados:
        sug = r['sugerencias']
        rubro = sug.get('rubro_sugerido') or '(Sin clasificar)'
        breakdown_rubro[rubro] = breakdown_rubro.get(rubro, 0) + 1

        # Candidatos a falso positivo: caen en Preliminares con confianza < alta
        # (los que coinciden bien con preliminares quedan en alta y son legítimos)
        if rubro and 'Preliminares' in rubro:
            items_preliminares.append({
                'id': r['id'],
                'descripcion': r['original']['descripcion'],
                'tarea_sugerida': sug.get('tarea_sugerida'),
                'confianza': sug['confianza'],
                'confianza_label': sug['confianza_label'],
                'sospechoso': sug['confianza_label'] in ('baja', 'media'),
            })

        # Para ranking de menor confianza (excluir los que ya son 0 sin sugerencia)
        items_para_ranking.append({
            'id': r['id'],
            'descripcion': r['original']['descripcion'],
            'unidad': r['original']['unidad'],
            'rubro_sugerido': sug.get('rubro_sugerido'),
            'tarea_sugerida': sug.get('tarea_sugerida'),
            'confianza': sug['confianza'],
            'confianza_label': sug['confianza_label'],
        })

    # Orden ascendente por confianza para mostrar los 10 más débiles
    items_para_ranking.sort(key=lambda x: (x['confianza'], x['descripcion'] or ''))
    top_baja_confianza = items_para_ranking[:10]

    # Orden alfabetico breakdown_rubro descendente por count
    breakdown_rubro_ordenado = dict(sorted(breakdown_rubro.items(), key=lambda kv: -kv[1]))

    return {
        'items': resultados,
        'total_items': len(resultados),
        'items_con_cambios': items_con_cambios,
        'breakdown_confianza': breakdown,
        'breakdown_rubro': breakdown_rubro_ordenado,
        'top_baja_confianza': top_baja_confianza,
        'items_preliminares': items_preliminares,
        'fuente': 'base_tecnica_computos_v2',
    }
