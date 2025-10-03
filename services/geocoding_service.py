"""Geocoding helpers for resolving addresses with caching support."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from flask import current_app

from extensions import db
from models import GeocodeCache

DEFAULT_PROVIDER = "nominatim"
DEFAULT_USER_AGENT = os.environ.get("MAPS_USER_AGENT", "OBYRA-IA/1.0 (+https://obyra.com)")
DEFAULT_TIMEOUT = 10
CACHE_TTL_SECONDS = int(os.environ.get("GEOCODE_CACHE_TTL", "86400"))  # 24h


@dataclass
class GeocodeResult:
    display_name: str
    lat: float
    lng: float
    provider: str
    place_id: Optional[str] = None
    normalized: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None
    status: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "display_name": self.display_name,
            "lat": self.lat,
            "lng": self.lng,
            "provider": self.provider,
            "place_id": self.place_id,
            "normalized": self.normalized or _normalize_query(self.display_name),
            "raw": self.raw,
            "status": self.status,
        }


def _normalize_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def _should_refresh(entry: GeocodeCache) -> bool:
    if CACHE_TTL_SECONDS <= 0:
        return False
    if not entry.updated_at:
        return True
    delta = datetime.utcnow() - entry.updated_at
    return delta.total_seconds() > CACHE_TTL_SECONDS


def _fetch_nominatim(query: str, *, limit: int = 5) -> List[GeocodeResult]:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": max(1, min(limit, 10)),
        "addressdetails": 1,
    }
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }

    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json() or []

    results: List[GeocodeResult] = []
    for item in data:
        try:
            lat = float(item.get("lat"))
            lng = float(item.get("lon"))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            continue
        display_name = item.get("display_name") or query
        place_id = str(item.get("place_id") or "") or None
        normalized = _normalize_query(display_name)
        results.append(
            GeocodeResult(
                display_name=display_name,
                lat=lat,
                lng=lng,
                provider="nominatim",
                place_id=place_id,
                normalized=normalized,
                raw=item,
            )
        )
    return results


def search(query: str, *, provider: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Returns a list of candidate addresses for the given query."""

    if not query or not query.strip():
        return []

    provider_key = (provider or current_app.config.get("MAPS_PROVIDER") or DEFAULT_PROVIDER).lower()

    try:
        if provider_key in {"nominatim", "osm"}:
            results = _fetch_nominatim(query, limit=limit)
        else:
            current_app.logger.warning("Proveedor de mapas %s no soportado, usando Nominatim", provider_key)
            results = _fetch_nominatim(query, limit=limit)
    except requests.RequestException as exc:  # pragma: no cover - network errors
        current_app.logger.warning("Fallo al consultar geocodificador: %s", exc)
        return []

    return [result.to_dict() for result in results]


def resolve(query: str, *, provider: Optional[str] = None, use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """Resolves a single address, caching the result for future calls."""

    if not query or not query.strip():
        return None

    provider_key = (provider or current_app.config.get("MAPS_PROVIDER") or DEFAULT_PROVIDER).lower()
    normalized = _normalize_query(query)

    cache_entry: Optional[GeocodeCache] = None
    if use_cache:
        cache_entry = GeocodeCache.query.filter_by(provider=provider_key, normalized_text=normalized).first()
        if cache_entry and not _should_refresh(cache_entry):
            payload = cache_entry.to_payload()
            payload["cached"] = True
            return payload

    results = search(query, provider=provider_key, limit=1)
    if not results:
        if cache_entry and cache_entry.status != "fail":
            cache_entry.status = "fail"
            cache_entry.updated_at = datetime.utcnow()
            db.session.flush()
        return None

    result = results[0]
    _store_in_cache(query, normalized, provider_key, result)
    result["cached"] = False
    return result


def _store_in_cache(original_query: str, normalized: str, provider: str, result: Dict[str, Any]) -> None:
    now = datetime.utcnow()
    entry = GeocodeCache.query.filter_by(provider=provider, normalized_text=normalized).first()
    raw_payload = result.get("raw")
    raw_text = json.dumps(raw_payload) if raw_payload else None

    if entry is None:
        entry = GeocodeCache(
            provider=provider,
            query_text=original_query.strip(),
            normalized_text=normalized,
        )
        db.session.add(entry)

    entry.display_name = result.get("display_name") or original_query
    entry.place_id = result.get("place_id")
    entry.latitud = result.get("lat")
    entry.longitud = result.get("lng")
    entry.raw_response = raw_text
    entry.status = result.get("status") or "ok"
    entry.updated_at = now
    if not entry.created_at:
        entry.created_at = now

    # Nominatim impone límites estrictos, respetar un pequeño delay al insertar masivamente
    time.sleep(0.0)

    db.session.flush()


__all__ = ["search", "resolve"]
