"""Banco Nación exchange rate provider."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

try:  # pragma: no cover - optional dependency
    import requests
except Exception:  # pragma: no cover - fallback when requests missing
    requests = None  # type: ignore[assignment]

from flask import current_app

from services.exchange.base import ExchangeRateSnapshot, _to_decimal

BNA_ENDPOINT = "https://www.dolarsi.com/api/api.php?type=valoresprincipales"


def fetch_official_rate() -> Optional[ExchangeRateSnapshot]:
    """Fetch the Banco Nación seller rate (ARS -> USD)."""

    if requests is None:
        if current_app:
            current_app.logger.warning('No se pudo consultar Banco Nación: requests no está disponible.')
        return None

    try:
        response = requests.get(BNA_ENDPOINT, timeout=6)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # pragma: no cover - network dependent
        if current_app:
            current_app.logger.warning('No se pudo obtener el tipo de cambio del BNA: %s', exc)
        return None

    if not isinstance(payload, list):
        return None

    for entry in payload:
        casa = entry.get('casa') if isinstance(entry, dict) else None
        if not isinstance(casa, dict):
            continue
        nombre = str(casa.get('nombre', '')).lower()
        if 'nación' in nombre or 'nacion' in nombre:
            venta = casa.get('venta')
            rate = _to_decimal(str(venta).replace(',', '.'))
            if rate <= Decimal('0'):
                continue
            return ExchangeRateSnapshot(
                id=None,
                provider='bna',
                base_currency='ARS',
                quote_currency='USD',
                rate=rate,
                fetched_at=datetime.utcnow(),
                source_url=BNA_ENDPOINT,
                notes='Cotización vendedor Banco Nación',
            )

    return None
