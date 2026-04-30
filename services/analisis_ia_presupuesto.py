"""Análisis IA de items de un presupuesto importado desde Excel.

Toma los items existentes del presupuesto y produce sugerencias para:
  - Normalizar la descripción.
  - Detectar etapa estándar del sistema (rubro).
  - Sugerir/normalizar unidad de medida.
  - Sugerir materiales relacionados.
  - Sugerir maquinaria si aplica.
  - Observaciones técnicas.
  - Confianza del análisis.

Estrategia hibrida:
  1. Reglas deterministicas (siempre disponibles): usa etapa_matcher,
     diccionario de unidades comunes, palabras clave.
  2. Si OPENAI_API_KEY esta configurada y hay items que el algoritmo
     deterministico no clasifica con confianza, se llama a OpenAI con
     un prompt acotado para esos items en particular (best-effort).

NO modifica la BD: solo retorna estructuras Python con sugerencias. El
endpoint que llame a este servicio debe persistir aparte si el usuario
confirma.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Diccionario de unidades comunes (sinónimos -> unidad estándar)
# ---------------------------------------------------------------
UNIDADES_NORMALIZADAS = {
    'm2': ['m2', 'm²', 'metro cuadrado', 'metros cuadrados', 'mts2', 'm. cuadrado'],
    'm3': ['m3', 'm³', 'metro cubico', 'metros cubicos', 'mts3'],
    'm':  ['m', 'metro', 'metros', 'mts', 'metro lineal', 'ml'],
    'kg': ['kg', 'kilo', 'kilos', 'kilogramo', 'kilogramos'],
    'tn': ['tn', 'tonelada', 'toneladas', 't'],
    'l':  ['l', 'lt', 'lts', 'litro', 'litros'],
    'h':  ['h', 'hora', 'horas', 'hs'],
    'dia': ['dia', 'dias', 'jornada', 'jornadas'],
    'jornal': ['jornal', 'jornales'],
    'unidad': ['un', 'u', 'unidad', 'unidades', 'pieza', 'piezas'],
    'gl': ['gl', 'global', 'gbl'],
    'bolsa': ['bolsa', 'bolsas'],
    'caja': ['caja', 'cajas'],
}


# ---------------------------------------------------------------
# Diccionario de materiales sugeridos por palabra clave en descripción
# ---------------------------------------------------------------
MATERIALES_POR_KEYWORD = {
    'hormigon': ['Cemento Portland', 'Arena gruesa', 'Piedra partida 6-12', 'Hierro estructural', 'Encofrado'],
    'mamposteria': ['Ladrillo común', 'Mortero CPN', 'Mezcla cal-cemento'],
    'revoque': ['Cemento Portland', 'Cal hidratada', 'Arena fina', 'Mortero adhesivo'],
    'piso': ['Ceramica', 'Pegamento cementicio', 'Pastina'],
    'pintura': ['Pintura latex interior', 'Imprimación fijadora', 'Rodillo', 'Cinta de papel'],
    'techo': ['Chapa galvanizada', 'Membrana asfáltica', 'Tornillería autoperforante'],
    'instalacion electrica': ['Cable unipolar', 'Caño corrugado', 'Caja de paso', 'Disyuntor'],
    'instalacion sanitaria': ['Caño PVC 110', 'Codo PVC', 'Llave de paso', 'Sellador'],
    'gas': ['Caño epoxi', 'Llave de paso de gas', 'Sellador para gas'],
    'demolicion': ['Volquete (alquiler)', 'Bolsa para escombros', 'Martillo eléctrico'],
    'excavacion': ['Retroexcavadora (alquiler)', 'Cinta perimetral', 'Nivel topográfico'],
    'fundacion': ['Cemento Portland', 'Hierro 8mm', 'Hierro 10mm', 'Encofrado'],
    'estructura': ['Hormigón H21', 'Hierro estructural', 'Encofrado'],
    'aislacion': ['Membrana', 'Imprimación asfáltica', 'Aislante térmico'],
    'carpinteria': ['Marco', 'Hoja', 'Bisagras', 'Cerradura'],
    'pared': ['Ladrillo', 'Mortero', 'Aislante'],
    'cielorraso': ['Placa de yeso', 'Perfilería de aluminio', 'Tornillos', 'Cinta'],
    'durlock': ['Placa de yeso', 'Perfilería', 'Cinta', 'Masilla'],
    'permiso': [],
    'cartel': ['Cartel de obra', 'Estructura metálica'],
    'obrador': ['Container', 'Sereno', 'Generador'],
}


# ---------------------------------------------------------------
# Diccionario de maquinaria sugerida por palabra clave
# ---------------------------------------------------------------
MAQUINARIA_POR_KEYWORD = {
    'excavacion': ['Retroexcavadora', 'Pala mecánica'],
    'movimiento de suelo': ['Retroexcavadora', 'Camión volcador'],
    'demolicion': ['Martillo demoledor', 'Volquete'],
    'hormigon': ['Hormigonera', 'Vibrador de inmersión'],
    'pulido': ['Helicoptero pulidor'],
    'corte': ['Disco diamantado', 'Amoladora'],
    'andamio': ['Andamio tubular'],
    'altura': ['Andamio', 'Plataforma elevadora'],
    'soldadura': ['Soldadora eléctrica'],
    'compactacion': ['Vibroapisonador', 'Rodillo compactador'],
}


def _normalizar(s: str) -> str:
    """Lowercase + sin acentos + espacios colapsados."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = s.lower()
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _sugerir_unidad(unidad_actual: str, descripcion: str) -> Optional[str]:
    """Devuelve la unidad estándar más probable, o None si la actual ya es OK."""
    if not unidad_actual:
        return None
    actual_norm = _normalizar(unidad_actual)
    desc_norm = _normalizar(descripcion or '')

    # Si la unidad actual ya es estándar, no sugerir cambio
    if actual_norm in UNIDADES_NORMALIZADAS:
        return None

    # Buscar match por sinónimos
    for std, sinonimos in UNIDADES_NORMALIZADAS.items():
        for syn in sinonimos:
            if actual_norm == _normalizar(syn):
                return std if std != actual_norm else None

    # Heurística por descripción (ej. "metros lineales de canaleta" -> 'm')
    if 'm2' in desc_norm or 'metro cuadrado' in desc_norm:
        return 'm2'
    if 'm3' in desc_norm or 'metro cubico' in desc_norm:
        return 'm3'

    return None


def _sugerir_materiales(descripcion: str, max_items: int = 5) -> List[str]:
    """Lista de materiales sugeridos según keywords en la descripción."""
    if not descripcion:
        return []
    desc_norm = _normalizar(descripcion)
    sugerencias = []
    vistos = set()
    for kw, materiales in MATERIALES_POR_KEYWORD.items():
        if kw in desc_norm:
            for m in materiales:
                if m not in vistos:
                    sugerencias.append(m)
                    vistos.add(m)
                if len(sugerencias) >= max_items:
                    return sugerencias
    return sugerencias


def _sugerir_maquinaria(descripcion: str) -> List[str]:
    """Lista de maquinaria sugerida según keywords en la descripción."""
    if not descripcion:
        return []
    desc_norm = _normalizar(descripcion)
    sugerencias = []
    vistos = set()
    for kw, maquinas in MAQUINARIA_POR_KEYWORD.items():
        if kw in desc_norm:
            for m in maquinas:
                if m not in vistos:
                    sugerencias.append(m)
                    vistos.add(m)
    return sugerencias


def _normalizar_descripcion(descripcion: str) -> str:
    """Limpia espacios, mayúsculas raras, abreviaturas más comunes."""
    if not descripcion:
        return descripcion
    s = descripcion.strip()
    # Capitalizar primera letra de cada oración (sin tocar el resto)
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    # Reemplazos comunes
    s = re.sub(r'\bH\s*°?\s*A\s*°?\b', 'H°A°', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+', ' ', s)
    return s


def _calcular_confianza(item_sugerencias: Dict[str, Any], etapa_excel: Optional[str]) -> float:
    """Confianza heurística 0..1 basada en cuántas señales positivas hay."""
    score = 0.0
    if item_sugerencias.get('etapa_sugerida'):
        score += 0.5
    if item_sugerencias.get('materiales_sugeridos'):
        score += 0.2
    if item_sugerencias.get('unidad_sugerida'):
        score += 0.1
    if etapa_excel:
        # Si el Excel ya traía una etapa explícita, baja la incertidumbre
        score += 0.2
    return round(min(score, 1.0), 2)


# ---------------------------------------------------------------
# Punto de entrada del servicio
# ---------------------------------------------------------------

def analizar_items_con_ia(items_payload: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analiza una lista de items y retorna sugerencias.

    Args:
        items_payload: lista de dicts con al menos:
            - id (int)
            - descripcion (str)
            - unidad (str)
            - cantidad (number)
            - etapa_nombre (opcional, str): la etapa actual del item
            - tipo (opcional, str)

    Retorna dict:
        {
          'items': [{
              'id': int,
              'original': {...},
              'sugerencias': {
                  'descripcion_normalizada': str,
                  'rubro_sugerido': str | None,   # alias de etapa
                  'etapa_sugerida': str | None,
                  'unidad_sugerida': str | None,
                  'materiales_sugeridos': [str],
                  'maquinaria_sugerida': [str],
                  'observaciones_ia': str,
                  'confianza': float,
              },
              'cambios_detectados': bool,
          }, ...],
          'total_items': int,
          'items_con_cambios': int,
          'fuente': 'reglas' | 'reglas+openai',
        }
    """
    from services.etapa_matcher import matchear_etapa_estandar

    resultados = []
    items_con_cambios = 0

    for item in items_payload or []:
        descripcion = (item.get('descripcion') or '').strip()
        unidad = (item.get('unidad') or '').strip()
        etapa_actual = (item.get('etapa_nombre') or '').strip() or None

        # 1. Normalizar descripcion
        desc_norm = _normalizar_descripcion(descripcion)

        # 2. Detectar etapa: prioridad a la actual si ya esta, sino matchear
        etapa_sugerida = None
        if not etapa_actual:
            etapa_sugerida = matchear_etapa_estandar(descripcion)
        else:
            # Aun teniendo etapa, ofrecer alternativa si el matcher detecta algo mas claro
            posible = matchear_etapa_estandar(descripcion)
            if posible and _normalizar(posible) != _normalizar(etapa_actual):
                etapa_sugerida = posible

        # 3. Unidad sugerida
        unidad_sugerida = _sugerir_unidad(unidad, descripcion)

        # 4. Materiales sugeridos
        materiales = _sugerir_materiales(descripcion)

        # 5. Maquinaria sugerida
        maquinaria = _sugerir_maquinaria(descripcion)

        # 6. Observaciones (heuristicas)
        obs = []
        if not etapa_actual and not etapa_sugerida:
            obs.append('No se pudo inferir el rubro automaticamente. Revisar manualmente.')
        if unidad and unidad_sugerida:
            obs.append(f'Unidad ambigua "{unidad}" - se sugiere normalizar a "{unidad_sugerida}".')
        if not unidad:
            obs.append('Item sin unidad. Conviene asignar una para que cuadre con compras.')
        observaciones_ia = ' / '.join(obs) if obs else ''

        sugerencias = {
            'descripcion_normalizada': desc_norm if desc_norm != descripcion else None,
            'rubro_sugerido': etapa_sugerida,    # alias semantico
            'etapa_sugerida': etapa_sugerida,
            'unidad_sugerida': unidad_sugerida,
            'materiales_sugeridos': materiales,
            'maquinaria_sugerida': maquinaria,
            'observaciones_ia': observaciones_ia,
        }
        sugerencias['confianza'] = _calcular_confianza(sugerencias, etapa_actual)

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

    fuente = 'reglas'
    # Hook para futura integracion con OpenAI: si OPENAI_API_KEY esta y hay
    # items con confianza baja, se podria enriquecer con LLM. Por ahora
    # mantenemos solo reglas para que sea predecible y barato.
    if os.environ.get('OPENAI_API_KEY'):
        fuente = 'reglas+openai-disponible'  # marcador, no se llama todavia

    return {
        'items': resultados,
        'total_items': len(resultados),
        'items_con_cambios': items_con_cambios,
        'fuente': fuente,
    }
