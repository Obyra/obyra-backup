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


NIVEL_DEFAULT = 'estandar'


def _regla_tiene_coef(regla) -> bool:
    if not regla:
        return False
    return bool(regla.get('recursos') or regla.get('niveles'))


def get_recursos(regla_id: str, nivel: Optional[str] = None) -> List[Dict[str, Any]]:
    """Devuelve la lista de recursos del YAML para una regla y nivel.

    Dos formatos de regla:
      1. Plano: `recursos: [...]` (el `nivel` se ignora).
      2. Por niveles: `recursos_base: [...]` + `niveles: {economico/estandar/premium:
         {recursos: [...]}}`. Se hace merge base + nivel POR `clave` (el recurso del
         nivel pisa/agrega al base). Si el nivel no existe, cae a estandar.

    Cada recurso es un dict {clave, tipo, nombre, unidad, coeficiente, notas}.
    """
    if not regla_id:
        return []
    data = _cargar_yaml()
    regla = (data.get('reglas') or {}).get(regla_id)
    if not regla:
        return []

    # Formato plano
    if regla.get('recursos'):
        return [r for r in regla['recursos'] if isinstance(r, dict)]

    # Formato por niveles
    niveles = regla.get('niveles') or {}
    if niveles:
        nivel = nivel or NIVEL_DEFAULT
        base = [r for r in (regla.get('recursos_base') or []) if isinstance(r, dict)]
        cfg = niveles.get(nivel) or niveles.get(NIVEL_DEFAULT) or {}
        nivel_recs = cfg.get('recursos') if isinstance(cfg, dict) else cfg
        nivel_recs = [r for r in (nivel_recs or []) if isinstance(r, dict)]
        # merge por clave: nivel pisa base
        por_clave = {}
        for r in base + nivel_recs:
            por_clave[r.get('clave')] = r
        return list(por_clave.values())

    return []


def niveles_disponibles(regla_id: str) -> List[str]:
    """Lista de niveles definidos para la regla (vacia si es plana)."""
    data = _cargar_yaml()
    regla = (data.get('reglas') or {}).get(regla_id) or {}
    return list((regla.get('niveles') or {}).keys())


def tiene_coeficientes(regla_id: str) -> bool:
    """True si la regla tiene recursos (planos o por niveles)."""
    data = _cargar_yaml()
    return _regla_tiene_coef((data.get('reglas') or {}).get(regla_id))


def reglas_con_coeficientes() -> Set[str]:
    """Set de regla_id que estan cubiertas por el YAML (planas o por niveles)."""
    data = _cargar_yaml()
    return {
        rid for rid, regla in (data.get('reglas') or {}).items()
        if _regla_tiene_coef(regla)
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
