"""Banco Nación exchange rate provider (cotización venta oficial)."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

try:  # pragma: no cover - optional dependency
    import requests
except Exception:  # pragma: no cover - fallback when requests missing
    requests = None  # type: ignore[assignment]

try:  # pragma: no cover - Python 3.9+ provides zoneinfo
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

from flask import current_app

from services.exchange.base import ExchangeRateSnapshot, _to_decimal

BNA_ENDPOINT = "https://www.bna.com.ar/Personas"
DEFAULT_TZ = "America/Argentina/Buenos_Aires"


def _parse_decimal(text: str) -> Decimal:
    normalized = text.strip().replace(".", "").replace(",", ".")
    return _to_decimal(normalized, '0')


def _get_timezone():
    tz_name = (current_app.config.get('FX_TZ') if current_app else None) or DEFAULT_TZ
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:  # pragma: no cover - invalid tz
        return None


def fetch_official_rate(as_of: Optional[date] = None) -> Optional[ExchangeRateSnapshot]:
    """Fetch the Banco Nación seller rate (ARS -> USD) for the requested day."""

    if requests is None:
        if current_app:
            current_app.logger.warning('No se pudo consultar Banco Nación: requests no está disponible.')
        return None

    target_date = as_of or date.today()
    url = (current_app.config.get('FX_BNA_URL') if current_app else None) or BNA_ENDPOINT

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; ObyraBot/1.0; +https://obyra.com)'
    }

    try:
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        html = response.text
    except Exception as exc:  # pragma: no cover - network dependent
        if current_app:
            current_app.logger.warning('No se pudo obtener el tipo de cambio del BNA: %s', exc)
        return None

    row_match = re.search(
        r"D[oó]lar\s+U\.?S\.?A\.?\s*</td>(?P<cells>.*?)</tr>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not row_match:
        return None

    cells_html = row_match.group('cells')
    cells = re.findall(r"<td[^>]*>(.*?)</td>", cells_html, flags=re.IGNORECASE | re.DOTALL)
    if len(cells) < 2:
        return None

    venta_raw = re.sub(r"<.*?>", "", cells[1])
    rate = _parse_decimal(venta_raw)
    if rate <= Decimal('0'):
        return None

    tz = _get_timezone()
    fetched_at = datetime.now(tz) if tz else datetime.utcnow()
    fetched_utc = fetched_at.astimezone(ZoneInfo('UTC')) if tz and ZoneInfo else datetime.utcnow()

    return ExchangeRateSnapshot(
        id=None,
        provider='bna_html',
        base_currency='ARS',
        quote_currency='USD',
        value=rate,
        as_of_date=target_date,
        fetched_at=fetched_utc,
        source_url=url,
        notes='Cotización vendedor Banco Nación',
    )
