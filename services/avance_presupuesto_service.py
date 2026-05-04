"""Calculo de avance del Presupuesto Preliminar IA hacia el 90%.

Este servicio NO es la confianza IA. Mide que tan COMPLETO esta el presupuesto
para presentarse al cliente, no que tan segura esta la IA de su clasificacion.

Componentes (cada uno aporta un % al avance total):
  1. Items reconocidos tecnicamente             -> 20 puntos
  2. Composicion ejecutiva generada (Fase 4)    -> 20 puntos
  3. Cantidades / distribucion validas          -> 15 puntos
  4. Precios encontrados (Fase 5)               -> 20 puntos
  5. Mano de obra / equipos estimados (Fase 4)  -> 10 puntos
  6. Margen / indirectos configurados           -> 10 puntos
  7. Perfil tecnico cargado / completo          -> 5  puntos
                                                  ===
                                                  100 puntos

En Fase 3.5 solo se pueden evaluar:
  - (1) reconocimiento tecnico (de la respuesta IA actual)
  - (7) perfil tecnico cargado
Los demas componentes quedan documentados como "pendientes" y aportan 0
hasta que las fases siguientes los activen.

El servicio devuelve:
  - porcentaje_avance: 0..100
  - breakdown: dict con cada componente y su aporte actual
  - pendientes: lista de strings que el usuario ve como "Para llegar al 90%..."
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


PESOS = {
    'items_reconocidos': 20,
    'composicion_generada': 20,
    'cantidades_distribuidas': 15,
    'precios_encontrados': 20,
    'mano_obra_equipos': 10,
    'margen_indirectos': 10,
    'perfil_tecnico_completo': 5,
}


def calcular_avance(
    *,
    total_items: int,
    items_reconocidos: int,
    perfil_tecnico: Optional[Dict[str, Any]],
    estados_kpis: Optional[Dict[str, int]] = None,
    presupuesto: Any = None,
) -> Dict[str, Any]:
    """Calcula el % de avance del presupuesto preliminar.

    Args:
      total_items: ItemPresupuesto.count() del presupuesto.
      items_reconocidos: items con regla_id != null (de la IA).
      perfil_tecnico: dict del ProjectTechnicalProfile (to_dict) o None.
      estados_kpis: dict {estado: count} del estado_operativo_service.
      presupuesto: instancia Presupuesto para chequear ejecutivo_aprobado,
        composiciones, materiales cotizables.

    Returns:
      {
        'porcentaje_avance': float 0..100,
        'breakdown': {componente: {puntos_obtenidos, puntos_max, descripcion}},
        'pendientes': [str],
      }
    """
    breakdown = {}
    pendientes = []

    # Helper: agregar pendiente estructurado con texto principal, ayuda y accion.
    def _add_pendiente(pid, texto, ayuda, boton_label, boton_accion, boton_disabled=False):
        pendientes.append({
            'id': pid,
            'texto': texto,
            'ayuda': ayuda,
            'boton_label': boton_label,
            'boton_accion': boton_accion,        # ID logico para el frontend
            'boton_disabled': boton_disabled,
        })

    # ---- 1. Items reconocidos tecnicamente ----
    if total_items > 0:
        ratio = items_reconocidos / total_items
        puntos = round(PESOS['items_reconocidos'] * ratio, 1)
    else:
        ratio = 0
        puntos = 0
    breakdown['items_reconocidos'] = {
        'puntos_obtenidos': puntos,
        'puntos_max': PESOS['items_reconocidos'],
        'descripcion': f'{items_reconocidos} de {total_items} items reconocidos por la base tecnica',
    }
    if total_items and items_reconocidos < total_items:
        no_reconocidos = total_items - items_reconocidos
        _add_pendiente(
            'revision_tecnica',
            f'{no_reconocidos} ítems necesitan revisión técnica',
            'OBYRA necesita confirmar rubro, etapa, unidad o tipo de recurso antes de usarlos en el presupuesto.',
            'Resolver ítems pendientes',
            'revisar_pendientes',
        )

    # ---- 2. Composicion ejecutiva generada ----
    composiciones_count = 0
    items_con_composicion_count = 0
    if presupuesto is not None:
        try:
            for it in (presupuesto.items.all() if hasattr(presupuesto.items, 'all') else presupuesto.items):
                comp_count = int(it.composiciones.count())
                composiciones_count += comp_count
                if comp_count > 0:
                    items_con_composicion_count += 1
        except Exception:
            composiciones_count = 0
    items_con_composicion = composiciones_count > 0
    # Calculo proporcional: ratio items con composicion sobre total
    if total_items > 0:
        ratio_comp = items_con_composicion_count / total_items
        comp_pts = round(PESOS['composicion_generada'] * ratio_comp, 1)
    else:
        comp_pts = 0
    breakdown['composicion_generada'] = {
        'puntos_obtenidos': comp_pts,
        'puntos_max': PESOS['composicion_generada'],
        'descripcion': (
            f'{items_con_composicion_count} de {total_items} items con composicion ejecutiva'
            if items_con_composicion_count else 'Sin composicion ejecutiva generada'
        ),
    }
    if items_con_composicion_count < total_items:
        sin_comp = total_items - items_con_composicion_count
        _add_pendiente(
            'composicion_ejecutiva',
            f'{sin_comp} ítems todavía no fueron desglosados en materiales, mano de obra y equipos',
            'La composición ejecutiva convierte cada ítem del Excel en recursos reales para cotizar.',
            'Generar composición ejecutiva',
            'generar_composicion',
        )

    # ---- 3. Cantidades / distribucion validas ----
    cantidades_pts = 0
    if perfil_tecnico:
        crit = (perfil_tecnico.get('criterio_distribucion') or '').lower()
        cant_niveles = perfil_tecnico.get('cantidad_niveles_total') or 0
        if crit in ('por_piso_automatico', 'por_piso_manual') and cant_niveles > 0:
            cantidades_pts = round(PESOS['cantidades_distribuidas'] * 0.5, 1)
    breakdown['cantidades_distribuidas'] = {
        'puntos_obtenidos': cantidades_pts,
        'puntos_max': PESOS['cantidades_distribuidas'],
        'descripcion': (
            'Niveles cargados; falta distribuir cantidades por piso'
            if cantidades_pts else 'Sin distribucion por piso configurada'
        ),
    }
    if cantidades_pts < PESOS['cantidades_distribuidas']:
        _add_pendiente(
            'distribucion_pisos',
            'Falta distribuir cantidades por pisos o sectores',
            'OBYRA usará el perfil técnico de la obra para repartir internamente cantidades como losas, columnas, vigas, mampostería e instalaciones.',
            'Distribuir cantidades',
            'distribuir_cantidades',
            boton_disabled=True,  # se habilita en una etapa posterior
        )

    # ---- 4. Precios encontrados ----
    breakdown['precios_encontrados'] = {
        'puntos_obtenidos': 0,
        'puntos_max': PESOS['precios_encontrados'],
        'descripcion': 'Sin lista de precios de proveedores cargada',
    }
    _add_pendiente(
        'precios_proveedores',
        'Falta cargar precios de proveedores',
        'Para calcular costos reales, OBYRA necesita una lista de precios actualizada o precios cargados manualmente.',
        'Cargar lista de precios',
        'cargar_precios',
        boton_disabled=True,  # se habilita en la etapa de precios
    )

    # ---- 5. Mano de obra / equipos estimados ----
    breakdown['mano_obra_equipos'] = {
        'puntos_obtenidos': 0,
        'puntos_max': PESOS['mano_obra_equipos'],
        'descripcion': 'Sin estimacion automatica de MO/equipos',
    }

    # ---- 6. Margen / indirectos configurados ----
    breakdown['margen_indirectos'] = {
        'puntos_obtenidos': 0,
        'puntos_max': PESOS['margen_indirectos'],
        'descripcion': 'Sin margen comercial e indirectos configurados',
    }

    # ---- 7. Perfil tecnico cargado / completo ----
    perfil_pts = 0
    if perfil_tecnico:
        tiene_minimos = bool(
            perfil_tecnico.get('tipo_obra')
            and (perfil_tecnico.get('cantidad_pisos', 0) or perfil_tecnico.get('tiene_planta_baja'))
        )
        completo = bool(
            tiene_minimos
            and perfil_tecnico.get('tipo_estructura') and perfil_tecnico.get('tipo_estructura') != 'no_definida'
            and perfil_tecnico.get('tipo_fundacion') and perfil_tecnico.get('tipo_fundacion') != 'no_definida'
            and perfil_tecnico.get('superficie_por_planta_m2')
        )
        if completo:
            perfil_pts = PESOS['perfil_tecnico_completo']
        elif tiene_minimos:
            perfil_pts = round(PESOS['perfil_tecnico_completo'] * 0.5, 1)
    breakdown['perfil_tecnico_completo'] = {
        'puntos_obtenidos': perfil_pts,
        'puntos_max': PESOS['perfil_tecnico_completo'],
        'descripcion': (
            'Perfil tecnico completo' if perfil_pts == PESOS['perfil_tecnico_completo']
            else 'Perfil tecnico parcial' if perfil_pts > 0
            else 'Sin perfil tecnico cargado'
        ),
    }
    if perfil_pts < PESOS['perfil_tecnico_completo']:
        if perfil_pts == 0:
            _add_pendiente(
                'perfil_tecnico_vacio',
                'Cargar el perfil técnico de la obra',
                'Tipo de obra, pisos, superficie, estructura y fundación. Sin estos datos, OBYRA no puede distribuir cantidades ni armar la futura obra por pisos.',
                'Completar perfil técnico',
                'cargar_perfil',
            )
        else:
            _add_pendiente(
                'perfil_tecnico_parcial',
                'Completar tipo de estructura / fundación en el perfil técnico',
                'Datos faltantes en el perfil técnico evitan que OBYRA clasifique ítems sensibles (estructura, fundaciones, instalaciones).',
                'Completar perfil técnico',
                'cargar_perfil',
            )

    # ---- Total ----
    total_pts = sum(c['puntos_obtenidos'] for c in breakdown.values())
    return {
        'porcentaje_avance': round(total_pts, 1),
        'breakdown': breakdown,
        'pendientes': pendientes,
    }
