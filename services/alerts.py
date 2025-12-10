"""Helpers para gestionar alertas deduplicadas del dashboard."""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional, Dict, Any

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app import db
from models import Event, Presupuesto


_SEVERITY_MAP = {
    "danger": "critica",
    "warning": "alta",
    "info": "media",
}


def _inicio_del_dia(dia: date) -> datetime:
    return datetime.combine(dia, datetime.min.time())


def _obtener_evento_por_clave(company_id: int, dedupe_key: str, inicio_dia: datetime) -> Optional[Event]:
    """Intenta obtener un evento existente filtrando por la clave de deduplicación."""
    query = Event.query.filter(
        Event.company_id == company_id,
        Event.type == "alert",
        Event.created_at >= inicio_dia,
    )

    try:
        query = query.filter(Event.meta['dedupe_key'].astext == dedupe_key)  # type: ignore[index]
        return query.first()
    except Exception:  # pragma: no cover - SQLite/json fallback
        eventos = query.all()
        for evento in eventos:
            if evento.meta and evento.meta.get("dedupe_key") == dedupe_key:
                return evento
    return None


def _crear_o_actualizar_evento(
    presupuesto: Presupuesto,
    dias_restantes: int,
    nivel: str,
    hoy: date,
    scope: str,
) -> Optional[Event]:
    if presupuesto is None or presupuesto.organizacion_id is None:
        return None

    dedupe_key = f"vigencia:{presupuesto.id}:{hoy.isoformat()}"
    inicio_dia = _inicio_del_dia(hoy)
    severity = _SEVERITY_MAP.get(nivel, "media")
    numero = presupuesto.numero or f"PRES-{presupuesto.id}" if presupuesto.id else "Presupuesto"
    cliente = None
    try:
        cliente = presupuesto.obra.cliente if presupuesto.obra else None
    except Exception:
        cliente = None

    evento = _obtener_evento_por_clave(presupuesto.organizacion_id, dedupe_key, inicio_dia)

    meta: Dict[str, Any] = {
        "dedupe_key": dedupe_key,
        "presupuesto_id": presupuesto.id,
        "presupuesto_numero": numero,
        "dias_restantes": dias_restantes,
        "nivel": nivel,
        "fecha_vigencia": presupuesto.fecha_vigencia.isoformat() if presupuesto.fecha_vigencia else None,
        "organizacion_id": presupuesto.organizacion_id,
    }
    if cliente:
        meta["cliente"] = cliente

    titulo = "Presupuesto por vencer"
    if dias_restantes <= 0:
        descripcion = f"{numero} ya se encuentra vencido."
    else:
        descripcion = f"{numero} vence en {dias_restantes} día{'s' if dias_restantes != 1 else ''}."
    if cliente:
        descripcion = f"{cliente} · {descripcion}"

    try:
        if evento:
            evento.severity = severity
            evento.title = titulo
            evento.description = descripcion
            scopes = set(evento.meta.get("scopes", [])) if evento.meta else set()
            scopes.add(scope)
            if evento.meta:
                evento.meta.update(meta)
            else:
                evento.meta = meta
            evento.meta["scopes"] = sorted(scopes)
        else:
            scopes = [scope]
            meta["scopes"] = scopes
            evento = Event(
                company_id=presupuesto.organizacion_id,
                project_id=presupuesto.obra_id,
                user_id=None,
                type='alert',
                severity=severity,
                title=titulo,
                description=descripcion,
                meta=meta,
            )
            db.session.add(evento)
        db.session.flush()
        return evento
    except SQLAlchemyError as exc:  # pragma: no cover - solo logging
        db.session.rollback()
        current_app.logger.exception("Error registrando alerta de vigencia: %s", exc)
        return None


def upsert_alert_vigencia(
    presupuesto: Presupuesto,
    dias_restantes: int,
    nivel: str,
    hoy: Optional[date] = None,
) -> Optional[Event]:
    """Crea o actualiza la alerta diaria de vigencia de un presupuesto."""
    if hoy is None:
        hoy = date.today()
    return _crear_o_actualizar_evento(presupuesto, dias_restantes, nivel, hoy, scope="alert")


def log_activity_vigencia(
    presupuesto: Presupuesto,
    dias_restantes: int,
    hoy: Optional[date] = None,
) -> Optional[Event]:
    """Marca la alerta como registrada en el feed de actividad sin duplicar eventos diarios."""
    if hoy is None:
        hoy = date.today()
    # Reutilizamos la misma clave de dedupe para que un solo evento alimente ambos paneles.
    return _crear_o_actualizar_evento(presupuesto, dias_restantes, _resolver_nivel(dias_restantes), hoy, scope="activity")


def _resolver_nivel(dias_restantes: int) -> str:
    if dias_restantes <= 3:
        return "danger"
    if dias_restantes <= 15:
        return "warning"
    return "info"


def limpiar_alertas_presupuestos_confirmados(org_id: int) -> int:
    """
    Elimina las alertas de presupuestos que ya fueron confirmados como obra o aprobados.
    Retorna el número de alertas eliminadas.
    """
    # Obtener IDs de presupuestos que ya no necesitan alertas
    presupuestos_finalizados = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id,
        Presupuesto.deleted_at.is_(None),
        db.or_(
            Presupuesto.confirmado_como_obra == True,
            Presupuesto.estado.in_(['aprobado', 'confirmado'])
        )
    ).with_entities(Presupuesto.id).all()

    ids_finalizados = [p.id for p in presupuestos_finalizados]

    if not ids_finalizados:
        return 0

    # Buscar y eliminar alertas de estos presupuestos
    alertas_a_eliminar = []
    alertas = Event.query.filter(
        Event.company_id == org_id,
        Event.type == 'alert',
        Event.title.like('%Presupuesto%vencer%')
    ).all()

    for alerta in alertas:
        if alerta.meta and alerta.meta.get('presupuesto_id') in ids_finalizados:
            alertas_a_eliminar.append(alerta)

    eliminadas = 0
    for alerta in alertas_a_eliminar:
        db.session.delete(alerta)
        eliminadas += 1

    if eliminadas > 0:
        try:
            db.session.commit()
            current_app.logger.info(f"Eliminadas {eliminadas} alertas de presupuestos confirmados")
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("Error eliminando alertas: %s", exc)
            return 0

    return eliminadas
