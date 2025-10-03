"""Provider that scrapes the CAC index from Cifras Online PDF."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

try:  # pragma: no cover - optional dependency
    import requests
except Exception:  # pragma: no cover - allow graceful degradation
    requests = None  # type: ignore[assignment]

try:  # pragma: no cover - PDF parsing optional
    from pdfminer.high_level import extract_text
except Exception:  # pragma: no cover
    extract_text = None  # type: ignore[assignment]

from flask import current_app

from services.exchange.base import _to_decimal

DEFAULT_INDEX_PAGE = "https://www.cifrasonline.com.ar/indice-cac/"


@dataclass
class CACProviderResult:
    year: int
    month: int
    value: Decimal
    provider: str
    source_url: Optional[str]
    fetched_at: datetime


def _resolve_pdf_url(index_html: str, base_url: str) -> Optional[str]:
    matches = re.findall(r"href=\"([^\"]+\.pdf)\"", index_html, flags=re.IGNORECASE)
    if not matches:
        return None
    href = matches[0]
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        # combine base domain
        if base_url.endswith('/'):
            base_url = base_url[:-1]
        return f"{base_url}{href}"
    return href


def _parse_index_value(text: str) -> Optional[Decimal]:
    patterns = [
        r"ÍNDICE[^0-9]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})",
        r"Indice[^0-9]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value_text = match.group(1).replace('.', '').replace(',', '.')
            value = _to_decimal(value_text, '0')
            if value > Decimal('0'):
                return value
    return None


def fetch_index(year: Optional[int] = None, month: Optional[int] = None) -> Optional[CACProviderResult]:
    """Download and parse the CAC index PDF. Returns None on failure."""

    if requests is None or extract_text is None:
        # Missing dependencies, rely on manual input
        if current_app:
            current_app.logger.warning('No se puede descargar el índice CAC automáticamente (falta requests/pdfminer).')
        return None

    target_year = year or date.today().year
    target_month = month or date.today().month
    page_url = (current_app.config.get('CAC_PDF_URL') if current_app else None) or DEFAULT_INDEX_PAGE

    try:
        index_resp = requests.get(page_url, timeout=15)
        index_resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - network dependent
        if current_app:
            current_app.logger.warning('No se pudo acceder a la página del índice CAC: %s', exc)
        return None

    content_type = index_resp.headers.get('Content-Type', '')
    if 'pdf' in content_type.lower():
        pdf_bytes = index_resp.content
        pdf_url = page_url
    else:
        pdf_url = _resolve_pdf_url(index_resp.text, page_url)
        if not pdf_url:
            return None
        try:
            pdf_resp = requests.get(pdf_url, timeout=20)
            pdf_resp.raise_for_status()
            pdf_bytes = pdf_resp.content
        except Exception as exc:  # pragma: no cover
            if current_app:
                current_app.logger.warning('No se pudo descargar el PDF del índice CAC: %s', exc)
            return None

    try:
        text = extract_text(io.BytesIO(pdf_bytes))
    except Exception as exc:  # pragma: no cover
        if current_app:
            current_app.logger.warning('No se pudo extraer texto del PDF CAC: %s', exc)
        return None

    value = _parse_index_value(text)
    if value is None:
        return None

    fetched_at = datetime.utcnow()
    return CACProviderResult(
        year=target_year,
        month=target_month,
        value=value,
        provider='cifras_pdf',
        source_url=pdf_url,
        fetched_at=fetched_at,
    )
