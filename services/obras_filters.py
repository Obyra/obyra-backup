"""Helpers para filtrar obras confirmadas y visibilidad multi-organización."""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import and_, exists, not_, or_

from models import Obra, Presupuesto

CONFIRMED_PRESUPUESTO_STATES = ("aprobado", "convertido")


def obras_visibles_clause(model: type[Obra]):
    """Devuelve la cláusula que define qué obras se consideran visibles."""
    presupuesto_activo = exists().where(
        and_(
            Presupuesto.obra_id == model.id,
            Presupuesto.deleted_at.is_(None),
        )
    )

    presupuesto_confirmado = exists().where(
        and_(
            Presupuesto.obra_id == model.id,
            Presupuesto.deleted_at.is_(None),
            or_(
                Presupuesto.confirmado_como_obra.is_(True),
                Presupuesto.estado.in_(CONFIRMED_PRESUPUESTO_STATES),
            ),
        )
    )

    return or_(not_(presupuesto_activo), presupuesto_confirmado)


def obra_tiene_presupuesto_confirmado(obra: Obra) -> bool:
    """Determina si la obra posee algún presupuesto confirmado o aprobado."""
    presupuestos_rel = getattr(obra, "presupuestos", None)
    if presupuestos_rel is None:
        return True

    if hasattr(presupuestos_rel, "filter"):
        activos: Iterable[Presupuesto] = presupuestos_rel.filter(
            Presupuesto.deleted_at.is_(None)
        ).all()
    else:
        activos = [p for p in presupuestos_rel if p.deleted_at is None]

    if not activos:
        return True

    for presupuesto in activos:
        estado = (presupuesto.estado or "").lower()
        if presupuesto.confirmado_como_obra or estado in CONFIRMED_PRESUPUESTO_STATES:
            return True

    return False


__all__ = [
    "CONFIRMED_PRESUPUESTO_STATES",
    "obra_tiene_presupuesto_confirmado",
    "obras_visibles_clause",
]
