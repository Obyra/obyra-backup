"""High level helpers to manage CAC indices."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from flask import current_app
from sqlalchemy import desc

from extensions import db
from models import CACIndex

try:  # pragma: no cover - optional provider import
    from . import cifras_pdf_provider
except Exception:  # pragma: no cover - provider optional
    cifras_pdf_provider = None  # type: ignore[assignment]


@dataclass
class CACContext:
    """Snapshot with the CAC index details used for a budget."""

    value: Decimal
    period: date
    base_value: Decimal
    base_period: date
    multiplier: Decimal
    provider: str
    source_url: Optional[str]


def _to_decimal(value: object, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _get_base_config() -> tuple[Decimal, date]:
    base_value_raw = (current_app.config.get('CAC_BASE_INDEX') if current_app else None) or '100.00'
    base_date_raw = (current_app.config.get('CAC_BASE_DATE') if current_app else None) or '2024-01-01'
    base_value = _to_decimal(base_value_raw, '100.00')
    try:
        year, month, day = [int(part) for part in str(base_date_raw).split('-')]
        base_date = date(year, month, day)
    except Exception:
        base_date = date(2024, 1, 1)
    return base_value if base_value > Decimal('0') else Decimal('100.00'), base_date


def get_index_for_month(year: int, month: int) -> Optional[CACIndex]:
    """Return the most recent index for the given month (manual overrides automatic)."""

    query = CACIndex.query.filter_by(year=year, month=month)
    # Prefer manual entries over automated providers
    query = query.order_by(
        desc(CACIndex.provider == 'manual'),
        desc(CACIndex.fetched_at),
        desc(CACIndex.created_at),
    )
    return query.first()


def _store_index(year: int, month: int, value: Decimal, provider: str, source_url: Optional[str]) -> CACIndex:
    record = CACIndex.query.filter_by(year=year, month=month, provider=provider).first()
    timestamp = datetime.utcnow()
    if record:
        record.value = value
        record.source_url = source_url
        record.fetched_at = timestamp
    else:
        record = CACIndex(
            year=year,
            month=month,
            value=value,
            provider=provider,
            source_url=source_url,
            fetched_at=timestamp,
        )
        db.session.add(record)
    db.session.commit()
    return record


def record_manual_index(year: int, month: int, value: Decimal, notes_url: Optional[str] = None) -> CACIndex:
    """Persist a manual CAC entry (used from admin/CLI)."""

    value = _to_decimal(value, '0')
    if value <= Decimal('0'):
        raise ValueError('El valor del índice CAC debe ser mayor que cero.')
    return _store_index(year, month, value, 'manual', notes_url)


def refresh_from_provider(year: Optional[int] = None, month: Optional[int] = None) -> Optional[CACIndex]:
    """Fetch the CAC index using the configured provider and persist it."""

    provider_key = (current_app.config.get('CAC_PROVIDER') if current_app else None) or 'cifras_pdf'
    year = year or date.today().year
    month = month or date.today().month

    if provider_key == 'cifras_pdf' and cifras_pdf_provider is not None:
        try:
            result = cifras_pdf_provider.fetch_index(year=year, month=month)
        except Exception as exc:  # pragma: no cover - depends on remote PDF
            if current_app:
                current_app.logger.warning('No se pudo obtener el índice CAC desde Cifras Online: %s', exc)
            result = None
        if result and result.value > Decimal('0'):
            return _store_index(result.year, result.month, result.value, result.provider, result.source_url)
    return None


def get_cac_context(target_date: Optional[date] = None) -> CACContext:
    """Resolve the CAC multiplier and metadata for the requested date."""

    base_value, base_date = _get_base_config()
    today = target_date or date.today()
    year, month = today.year, today.month

    record = get_index_for_month(year, month)
    if record is None:
        record = refresh_from_provider(year, month)

    if record is None:
        # fallback to base configuration
        value = base_value
        provider = 'config'
        source_url = None
        period = date(year, month, 1)
    else:
        value = _to_decimal(record.value, '0')
        provider = record.provider
        source_url = record.source_url
        period = date(record.year, record.month, 1)

    if value <= Decimal('0'):
        value = base_value

    multiplier = (value / base_value).quantize(Decimal('0.0001')) if base_value > Decimal('0') else Decimal('1')

    return CACContext(
        value=value,
        period=period,
        base_value=base_value,
        base_period=base_date,
        multiplier=multiplier,
        provider=provider,
        source_url=source_url,
    )
