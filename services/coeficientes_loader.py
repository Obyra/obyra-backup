"""Loader del YAML de coeficientes constructivos (Fase 4).

Carga el archivo `services/coeficientes_constructivos.yml` una sola vez
por proceso (cache via lru_cache) y expone helpers para:
  - get_recursos(regla_id): lista de recursos para una regla.
  - tiene_coeficientes(regla_id): True si la regla tiene entrada cargada.
  - reglas_con_coeficientes(): set de IDs cargados.
  - metadatos(): version, moneda, notas.

NO modifica el YAML. Si el archivo cambia en disco, hay que reiniciar
el proceso para que se vea el cambio (cache de proceso).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set

import yaml


_YAML_PATH = os.path.join(os.path.dirname(__file__), 'coeficientes_constructivos.yml')


@lru_cache(maxsize=1)
def _cargar_yaml() -> Dict[str, Any]:
    """Carga el YAML una sola vez por proceso. Tolerante si no existe."""
    if not os.path.exists(_YAML_PATH):
        return {'version': '0.0.0', 'reglas': {}, 'notas': ''}
    with open(_YAML_PATH, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    if 'reglas' not in data:
        data['reglas'] = {}
    return data


def get_recursos(regla_id: str) -> List[Dict[str, Any]]:
    """Devuelve la lista de recursos del YAML para una regla.

    Cada recurso es un dict {clave, tipo, nombre, unidad, coeficiente, notas}.
    Si la regla no tiene entrada o no tiene 'recursos', devuelve [].
    """
    if not regla_id:
        return []
    data = _cargar_yaml()
    regla = (data.get('reglas') or {}).get(regla_id)
    if not regla:
        return []
    recursos = regla.get('recursos') or []
    return [r for r in recursos if isinstance(r, dict)]


def tiene_coeficientes(regla_id: str) -> bool:
    """True si la regla tiene al menos 1 recurso definido en el YAML."""
    return len(get_recursos(regla_id)) > 0


def reglas_con_coeficientes() -> Set[str]:
    """Set de regla_id que estan cubiertas por el YAML."""
    data = _cargar_yaml()
    return {
        rid for rid, regla in (data.get('reglas') or {}).items()
        if regla and (regla.get('recursos') or [])
    }


def metadatos() -> Dict[str, Any]:
    """Devuelve version, moneda y notas del YAML."""
    data = _cargar_yaml()
    return {
        'version': data.get('version'),
        'moneda_referencia': data.get('moneda_referencia'),
        'notas': data.get('notas'),
        'cantidad_reglas': len(reglas_con_coeficientes()),
    }


def descripcion_regla(regla_id: str) -> Optional[str]:
    """Devuelve la descripcion humana de la regla, si existe en YAML."""
    data = _cargar_yaml()
    regla = (data.get('reglas') or {}).get(regla_id) or {}
    return regla.get('descripcion')


def unidad_item_esperada(regla_id: str) -> Optional[str]:
    """Devuelve la unidad esperada del item del pliego para esta regla."""
    data = _cargar_yaml()
    regla = (data.get('reglas') or {}).get(regla_id) or {}
    return regla.get('unidad_item')
