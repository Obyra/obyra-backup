"""Servicio del Perfil Tecnico del Proyecto (Fase 2).

Encapsula:
  - upsert del ProjectTechnicalProfile asociado a un presupuesto;
  - auto-generacion de NivelPresupuesto cuando criterio_distribucion lo pide;
  - extraccion del contexto que se pasa a la Calculadora IA.

Reglas multi-tenant:
  - Siempre se valida que el presupuesto.organizacion_id coincida con el
    org_id del caller (o que el caller sea super admin).
  - La tabla `project_technical_profile.organizacion_id` se setea desde el
    presupuesto, nunca confiando en input externo.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from extensions import db


def _criterio_genera_niveles(criterio: str) -> bool:
    return criterio in ('por_piso_automatico', 'por_piso_manual')


def upsert_perfil_tecnico(
    *,
    presupuesto,
    payload: Dict[str, Any],
    user_id: Optional[int],
    autogenerar_niveles: bool = True,
):
    """Crea o actualiza el ProjectTechnicalProfile del presupuesto.

    Args:
      presupuesto: instancia Presupuesto.
      payload: dict con los campos a persistir (NO normalizado todavia).
      user_id: usuario actual (para auditoria).
      autogenerar_niveles: si True y el criterio lo amerita, crea niveles.

    Returns:
      dict {profile, niveles_generados, fue_creacion}.

    Raises:
      ValueError: payload invalido en algun campo enum/numerico.
    """
    from models.project_technical_profile import (
        ProjectTechnicalProfile, validar_y_normalizar,
    )

    norm = validar_y_normalizar(payload)

    profile = ProjectTechnicalProfile.query.filter_by(
        presupuesto_id=presupuesto.id
    ).first()

    fue_creacion = profile is None
    if fue_creacion:
        profile = ProjectTechnicalProfile(
            organizacion_id=presupuesto.organizacion_id,
            presupuesto_id=presupuesto.id,
            obra_id=getattr(presupuesto, 'obra_id', None),
        )
        db.session.add(profile)

    # Aplicar campos normalizados
    for k, v in norm.items():
        setattr(profile, k, v)
    profile.completado_at = datetime.utcnow()
    profile.completado_por_user_id = user_id
    profile.updated_at = datetime.utcnow()

    db.session.flush()

    niveles_generados = 0
    if autogenerar_niveles and _criterio_genera_niveles(profile.criterio_distribucion):
        niveles_generados = _autogenerar_niveles(presupuesto, profile)

    return {
        'profile': profile,
        'niveles_generados': niveles_generados,
        'fue_creacion': fue_creacion,
    }


def _autogenerar_niveles(presupuesto, profile) -> int:
    """Genera NivelPresupuesto a partir del perfil tecnico.

    Solo crea niveles que NO existen ya (por nombre+presupuesto). No borra
    niveles existentes — el usuario puede tener niveles cargados a mano.

    Defaults:
      - area_m2 = profile.superficie_por_planta_m2 (o 0 si NULL)
      - atributos.espesor_losa = profile.espesor_losa_cm
      - atributos.altura_libre = profile.altura_promedio_piso_m
      - sistema_constructivo = mapeado desde profile.tipo_estructura
      - hormigon_m3 / albanileria_m2 = 0 (calcular en fase posterior)
    """
    from models.budgets import NivelPresupuesto

    sistema_map = {
        'hormigon_armado': 'hormigon',
        'metalica': 'metalica',
        'mixta': 'mixta',
        'mamposteria_portante': 'mamposteria',
        'no_definida': 'hormigon',
    }
    sistema = sistema_map.get(profile.tipo_estructura, 'hormigon')

    area_default = float(profile.superficie_por_planta_m2 or 0)
    atributos_default = {}
    if profile.espesor_losa_cm:
        atributos_default['espesor_losa'] = float(profile.espesor_losa_cm)
    if profile.altura_promedio_piso_m:
        atributos_default['altura_libre'] = float(profile.altura_promedio_piso_m)
    if profile.cantidad_cocheras:
        atributos_default['cocheras'] = profile.cantidad_cocheras

    existentes = {
        n.nombre.strip().lower(): n
        for n in NivelPresupuesto.query.filter_by(presupuesto_id=presupuesto.id).all()
    }

    plan = _construir_plan_niveles(profile)

    creados = 0
    for orden, item in enumerate(plan, start=1):
        nombre_lower = item['nombre'].strip().lower()
        if nombre_lower in existentes:
            continue  # respetamos lo que el usuario ya tenia
        nivel = NivelPresupuesto(
            presupuesto_id=presupuesto.id,
            tipo_nivel=item['tipo_nivel'],
            nombre=item['nombre'],
            orden=orden,
            repeticiones=1,
            area_m2=area_default,
            sistema_constructivo=sistema,
            hormigon_m3=0,
            albanileria_m2=0,
            atributos=dict(atributos_default),
        )
        db.session.add(nivel)
        creados += 1

    return creados


def _construir_plan_niveles(profile) -> list:
    """Devuelve la lista ordenada de niveles teoricos del proyecto.

    Orden de subsuelos: el mas profundo primero (S-{N}, ..., S-1) para que
    al ordenar por `orden` ascendente se respete la lectura logica de un
    edificio (subsuelo abajo, terraza arriba).
    """
    plan = []

    # Subsuelos: S-N (mas profundo) primero, hasta S-1.
    if profile.cantidad_subsuelos and profile.cantidad_subsuelos > 0:
        for i in range(profile.cantidad_subsuelos, 0, -1):
            plan.append({'tipo_nivel': 'subsuelo', 'nombre': f'Subsuelo {i}'})

    if profile.tiene_planta_baja:
        plan.append({'tipo_nivel': 'pb', 'nombre': 'Planta Baja'})

    if profile.cantidad_pisos and profile.cantidad_pisos > 0:
        for i in range(1, profile.cantidad_pisos + 1):
            plan.append({'tipo_nivel': 'piso_tipo', 'nombre': f'Piso {i}'})

    if profile.tiene_terraza:
        plan.append({'tipo_nivel': 'terraza', 'nombre': 'Terraza'})

    return plan


def construir_contexto_ia(presupuesto) -> Optional[Dict[str, Any]]:
    """Devuelve el dict de contexto que se pasa a analizar_items_con_ia.

    Si el presupuesto no tiene perfil cargado, devuelve None para que la IA
    se comporte como antes (sin contexto).
    """
    from models.project_technical_profile import ProjectTechnicalProfile
    from models.budgets import NivelPresupuesto

    profile = ProjectTechnicalProfile.query.filter_by(
        presupuesto_id=presupuesto.id
    ).first()
    if not profile:
        return None

    niveles = NivelPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id
    ).order_by(NivelPresupuesto.orden).all()

    return {
        'perfil_tecnico': profile.to_dict(),
        'niveles': [n.to_dict() for n in niveles],
    }
