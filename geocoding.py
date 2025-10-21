"""Compatibilidad de geocodificación para módulos históricos."""

from __future__ import annotations

from typing import Optional, Tuple

from flask import current_app

from services.geocoding_service import resolve, search


def geocodificar_direccion(direccion: str, *, provider: Optional[str] = None) -> Tuple[Optional[float], Optional[float]]:
    """Devuelve latitud y longitud para la dirección indicada."""

    resultado = resolve(direccion, provider=provider)
    if not resultado:
        return None, None

    return resultado.get("lat"), resultado.get("lng")


def sugerencias_direccion(direccion: str, *, provider: Optional[str] = None):
    """Devuelve hasta 5 sugerencias de direcciones similares."""

    return search(direccion, provider=provider, limit=5)


def geocodificar_obras_existentes():
    """Geocodifica obras sin coordenadas usando el servicio actual."""

    from app import db
    from models import Obra

    obras_pendientes = Obra.query.filter(
        Obra.direccion.isnot(None),
        Obra.direccion != "",
        db.or_(Obra.latitud.is_(None), Obra.longitud.is_(None)),
    ).all()

    exitosas = 0
    fallidas = 0

    for obra in obras_pendientes:
        resultado = resolve(obra.direccion)
        if not resultado:
            fallidas += 1
            continue

        obra.latitud = resultado.get("lat")
        obra.longitud = resultado.get("lng")
        obra.direccion_normalizada = resultado.get("normalized")
        obra.geocode_place_id = resultado.get("place_id")
        obra.geocode_provider = resultado.get("provider")
        obra.geocode_status = resultado.get("status") or "ok"
        exitosas += 1

    try:
        db.session.commit()
    except Exception:  # pragma: no cover - logging solamente
        db.session.rollback()
        fallidas = len(obras_pendientes)
        exitosas = 0
        if current_app:
            current_app.logger.exception("No se pudieron guardar los resultados de geocodificación masiva")

    return exitosas, fallidas


def normalizar_direccion_argentina(direccion: Optional[str]) -> Optional[str]:
    if not direccion:
        return direccion
    direccion = direccion.strip()
    if not direccion:
        return direccion
    direccion_lower = direccion.lower()
    if "argentina" not in direccion_lower:
        direccion = f"{direccion}, Argentina"
    return direccion
