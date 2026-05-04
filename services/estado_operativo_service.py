"""Servicio de estados operativos del Generador Preliminar IA (Fase 3.5).

Mappea (sugerencia IA + perfil tecnico) -> estado operativo de negocio.

NO modifica la logica de la Calculadora IA. Solo traduce confianza interna
(alta/media/baja/sin) en estados que el usuario final entiende:
  - listo                Listo para presupuestar
  - requiere_revision    Requiere revision
  - falta_precio         Falta precio
  - falta_dato_tecnico   Falta dato tecnico
  - no_reconocido        No reconocido
  - excluido             Excluido del calculo

Prioridad confirmada (mayor a menor):
  1. excluido            (gana siempre - flag manual)
  2. no_reconocido       (sin regla)
  3. falta_dato_tecnico  (regla pide perfil tecnico que esta no_definida)
  4. falta_precio        (Fase 5: sin precio en composicion. Hoy NO se evalua.)
  5. requiere_revision   (confianza media o baja)
  6. listo               (confianza alta sin faltantes)

En Fase 3.5 NO se evalua falta_precio (eso es Fase 5). El servicio deja la
puerta lista — basta extender clasificar_item() con la consulta de precios.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


ESTADOS_OPERATIVOS = (
    'listo',
    'requiere_revision',
    'falta_precio',
    'falta_dato_tecnico',
    'no_reconocido',
    'excluido',
)

# Etiquetas visibles para el usuario final
ESTADO_LABELS = {
    'listo': 'Listo para presupuestar',
    'requiere_revision': 'Requiere revision',
    'falta_precio': 'Falta precio',
    'falta_dato_tecnico': 'Falta dato tecnico',
    'no_reconocido': 'No reconocido',
    'excluido': 'Excluido del calculo',
}

# Clases Bootstrap para badge visual
ESTADO_BADGE_CLASS = {
    'listo': 'bg-success',
    'requiere_revision': 'bg-warning text-dark',
    'falta_precio': 'bg-info text-dark',
    'falta_dato_tecnico': 'bg-primary',
    'no_reconocido': 'bg-secondary',
    'excluido': 'bg-dark',
}

# Iconos FontAwesome
ESTADO_ICON = {
    'listo': 'fa-check-circle',
    'requiere_revision': 'fa-exclamation-triangle',
    'falta_precio': 'fa-dollar-sign',
    'falta_dato_tecnico': 'fa-drafting-compass',
    'no_reconocido': 'fa-question-circle',
    'excluido': 'fa-ban',
}

# =====================================================================
# Rubros que requieren perfil tecnico cargado para clasificar bien.
#
# Lista AMPLIABLE — agregar acentos/sin acentos y variaciones razonables.
# El matching es CASE-INSENSITIVE Y SIN ACENTOS via _normalizar_rubro().
#
# Razonamiento:
# - REQUIEREN_TIPO_ESTRUCTURA: rubros donde saber HºAº vs metalica vs mixta
#   cambia el desglose de materiales (hierro, perfiles, encofrado, etc.).
# - REQUIEREN_TIPO_FUNDACION: cambia el calculo de excavacion/hormigon.
# - REQUIEREN_GEOMETRIA: rubros donde saber cantidad_pisos / superficie_por_planta
#   permite distribuir cantidades; en Fase 4 se usaran para esto.
#
# Para el clasificador en Fase 3.5 todos los grupos se tratan igual:
# si el rubro pertenece a alguno y el dato relevante esta `no_definida` o
# el perfil no esta cargado, el item se marca `falta_dato_tecnico`.
# =====================================================================
RUBROS_REQUIEREN_TIPO_ESTRUCTURA = (
    'estructura',
    'estructuras',
    'estructura de hormigon',
    'estructura de hormigon armado',
    'estructura metalica',
    'hormigon armado',
    'losas',
    'losa',
    'columnas',
    'columna',
    'vigas',
    'viga',
    'tabiques de hormigon',
)

RUBROS_REQUIEREN_TIPO_FUNDACION = (
    'fundaciones',
    'fundacion',
    'submuracion',
    'submuraciones',
    'movimiento de suelos',
    'movimientos de suelo',
    'depresion de napa',
    'depresion de napas',
    'excavaciones',
    'excavacion',
)

# Rubros que necesitan saber cantidad_pisos o superficie_por_planta para
# distribuir cantidades. Se usaran en Fase 4 para distribucion automatica;
# hoy solo se valida que el perfil este cargado.
RUBROS_REQUIEREN_GEOMETRIA = (
    'mamposteria',
    'mamposteria portante',
    'instalaciones',
    'instalacion electrica',
    'instalacion sanitaria',
    'instalacion de gas',
    'instalaciones electricas',
    'instalaciones sanitarias',
    'instalaciones de gas',
    'revoques',
    'revoque grueso',
    'revoque fino',
    'pisos y revestimientos',
    'pisos',
    'contrapisos',
    'cielorrasos',
)


# Compatibilidad hacia atras: aliases que apuntan a las listas nuevas
RUBROS_REQUIEREN_ESTRUCTURA = RUBROS_REQUIEREN_TIPO_ESTRUCTURA
RUBROS_REQUIEREN_FUNDACION = RUBROS_REQUIEREN_TIPO_FUNDACION


def _normalizar_rubro(rubro: str) -> str:
    """Lowercase + sin acentos, para matching robusto."""
    if not rubro:
        return ''
    import unicodedata
    s = unicodedata.normalize('NFD', str(rubro)).encode('ascii', 'ignore').decode('ascii')
    return s.lower().strip()


def clasificar_item(
    sugerencia: Optional[Dict[str, Any]],
    perfil_tecnico: Optional[Dict[str, Any]] = None,
    item: Any = None,
) -> str:
    """Devuelve el estado operativo prioritizado para un item.

    Args:
      sugerencia: dict de sugerencias IA (rubro_sugerido, confianza_label,
        regla_id, etc.).
      perfil_tecnico: dict del ProjectTechnicalProfile (a partir de to_dict()).
        Si es None, se asume que no hay perfil cargado.
      item: opcional, instancia ItemPresupuesto. Hoy solo se mira el flag
        de exclusion manual si existe.

    Returns:
      string con el estado canonico (uno de ESTADOS_OPERATIVOS).
    """
    sug = sugerencia or {}

    # 1. EXCLUIDO: flag manual del item (futuro, hoy nunca se emite)
    if item is not None and getattr(item, 'excluido_de_preliminar', False):
        return 'excluido'

    # 2. NO RECONOCIDO: la IA no pudo asignar regla
    label = (sug.get('confianza_label') or '').lower()
    regla_id = sug.get('regla_id')
    if not regla_id or label == 'sin' or label == '':
        return 'no_reconocido'

    # 3. FALTA DATO TECNICO: la regla pertenece a un rubro que necesita
    #    perfil tecnico para clasificar bien, y el perfil dice no_definida
    #    o no esta cargado. Matching case-insensitive + sin acentos.
    rubro_norm = _normalizar_rubro(sug.get('rubro_sugerido') or '')
    perfil = perfil_tecnico or {}
    perfil_no_cargado = not perfil  # dict vacio o None

    if rubro_norm in RUBROS_REQUIEREN_TIPO_ESTRUCTURA:
        tipo_estr = (perfil.get('tipo_estructura') or '').lower() if not perfil_no_cargado else ''
        if perfil_no_cargado or tipo_estr in ('', 'no_definida'):
            return 'falta_dato_tecnico'

    if rubro_norm in RUBROS_REQUIEREN_TIPO_FUNDACION:
        tipo_fund = (perfil.get('tipo_fundacion') or '').lower() if not perfil_no_cargado else ''
        if perfil_no_cargado or tipo_fund in ('', 'no_definida'):
            return 'falta_dato_tecnico'

    if rubro_norm in RUBROS_REQUIEREN_GEOMETRIA:
        # Para distribucion (Fase 4) necesitamos saber pisos/superficie.
        # Si el perfil no esta cargado o cantidad_pisos = 0 y no hay PB,
        # no podemos distribuir bien.
        if perfil_no_cargado:
            return 'falta_dato_tecnico'
        cant_pisos = perfil.get('cantidad_pisos') or 0
        cant_subs = perfil.get('cantidad_subsuelos') or 0
        tiene_pb = perfil.get('tiene_planta_baja')
        if not (cant_pisos or cant_subs or tiene_pb):
            return 'falta_dato_tecnico'

    # 4. FALTA PRECIO: se evalua en Fase 5 con catalogo de precios.
    #    En Fase 3.5 dejamos pasar — la composicion ejecutiva todavia no
    #    se genera automaticamente, asi que no podemos saber si "falta precio"
    #    sin tener que asumir. Mejor no marcar falsos positivos.

    # 5. REQUIERE REVISION: confianza media o baja
    if label in ('media', 'baja'):
        return 'requiere_revision'

    # 6. LISTO: confianza alta + nada faltante
    if label == 'alta':
        return 'listo'

    # Fallback defensivo
    return 'requiere_revision'


def calcular_resumen(
    items_resultado: Iterable[Dict[str, Any]],
    perfil_tecnico: Optional[Dict[str, Any]] = None,
    items_db: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Recorre los items del resultado IA y devuelve KPIs + estado por item.

    Args:
      items_resultado: lista de items del resultado IA (cada uno trae 'sugerencias').
      perfil_tecnico: dict del perfil del presupuesto, opcional.
      items_db: opcional, lista de ItemPresupuesto matchable por id (para
        leer flags como excluido_de_preliminar).

    Returns:
      {
        'kpis': {estado: count} para los 6 estados,
        'total': total de items,
        'estados_por_item': {item_id: estado},
        'porcentaje_listos': float (0..100),
      }
    """
    kpis = {e: 0 for e in ESTADOS_OPERATIVOS}
    estados_por_item = {}

    items_db_map = {}
    if items_db:
        for it in items_db:
            try:
                items_db_map[int(it.id)] = it
            except Exception:
                continue

    total = 0
    for r in items_resultado or []:
        total += 1
        sug = r.get('sugerencias') if isinstance(r, dict) else None
        item_id = r.get('id') if isinstance(r, dict) else None
        item_db = items_db_map.get(int(item_id)) if item_id is not None else None
        estado = clasificar_item(sug, perfil_tecnico=perfil_tecnico, item=item_db)
        kpis[estado] += 1
        if item_id is not None:
            estados_por_item[item_id] = estado

    pct_listos = round(100.0 * kpis['listo'] / total, 1) if total else 0.0

    return {
        'kpis': kpis,
        'total': total,
        'estados_por_item': estados_por_item,
        'porcentaje_listos': pct_listos,
    }


def metadatos_estado(estado: str) -> Dict[str, str]:
    """Devuelve {label, badge_class, icon} para el estado dado."""
    return {
        'estado': estado,
        'label': ESTADO_LABELS.get(estado, estado),
        'badge_class': ESTADO_BADGE_CLASS.get(estado, 'bg-secondary'),
        'icon': ESTADO_ICON.get(estado, 'fa-circle'),
    }


def metadatos_todos_estados() -> List[Dict[str, str]]:
    """Devuelve la lista canonica de estados con sus metadatos.

    Util para que el frontend renderice las pildoras + opciones de filtro
    sin hardcodearlas en JS.
    """
    return [metadatos_estado(e) for e in ESTADOS_OPERATIVOS]
