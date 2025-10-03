"""Utilities to persist and retrieve foreign exchange rates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from flask import current_app

from extensions import db
from models import ExchangeRate


@dataclass
class ExchangeRateSnapshot:
    """Lightweight representation of an exchange rate snapshot."""

    id: Optional[int]
    provider: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    fetched_at: datetime
    source_url: Optional[str] = None
    notes: Optional[str] = None


def _to_decimal(value: object, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _as_snapshot(exchange: ExchangeRate) -> ExchangeRateSnapshot:
    return ExchangeRateSnapshot(
        id=exchange.id,
        provider=exchange.provider,
        base_currency=exchange.base_currency,
        quote_currency=exchange.quote_currency,
        rate=_to_decimal(exchange.rate, '0'),
        fetched_at=exchange.fetched_at or exchange.created_at or datetime.utcnow(),
        source_url=exchange.source_url,
        notes=exchange.notes,
    )


def get_latest_rate(provider: str, base_currency: str, quote_currency: str) -> Optional[ExchangeRateSnapshot]:
    """Return the most recent stored rate for the given provider pair."""

    query = ExchangeRate.query.filter_by(
        provider=provider,
        base_currency=base_currency,
        quote_currency=quote_currency,
    ).order_by(ExchangeRate.fetched_at.desc(), ExchangeRate.id.desc())

    existing = query.first()
    if existing:
        return _as_snapshot(existing)
    return None


def store_rate(snapshot: ExchangeRateSnapshot) -> ExchangeRateSnapshot:
    """Persist the snapshot and return it with a database identifier."""

    exchange = ExchangeRate(
        provider=snapshot.provider,
        base_currency=snapshot.base_currency,
        quote_currency=snapshot.quote_currency,
        rate=_to_decimal(snapshot.rate, '0'),
        fetched_at=snapshot.fetched_at,
        source_url=snapshot.source_url,
        notes=snapshot.notes,
    )
    db.session.add(exchange)
    db.session.commit()
    return _as_snapshot(exchange)


def ensure_rate(
    provider: str,
    base_currency: str,
    quote_currency: str,
    fetcher: Callable[[], Optional[ExchangeRateSnapshot]],
    freshness_minutes: int = 60,
    fallback_rate: Optional[Decimal] = None,
) -> ExchangeRateSnapshot:
    """Get a fresh rate ensuring at most ``freshness_minutes`` of staleness."""

    provider_key = provider.lower()
    base_currency = base_currency.upper()
    quote_currency = quote_currency.upper()

    snapshot = get_latest_rate(provider_key, base_currency, quote_currency)

    freshness_delta = timedelta(minutes=max(freshness_minutes, 0))
    needs_refresh = True
    now = datetime.utcnow()

    if snapshot and freshness_minutes >= 0:
        age = now - snapshot.fetched_at
        needs_refresh = age > freshness_delta

    if needs_refresh:
        fetched = fetcher()
        if fetched:
            fetched.provider = provider_key
            fetched.base_currency = base_currency
            fetched.quote_currency = quote_currency
            snapshot = store_rate(fetched)
        elif snapshot is None and fallback_rate is not None:
            fallback_snapshot = ExchangeRateSnapshot(
                id=None,
                provider=provider_key,
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=fallback_rate,
                fetched_at=now,
                notes='Fallback rate (static configuration)',
            )
            snapshot = store_rate(fallback_snapshot)
        elif snapshot is None:
            fallback_env = current_app.config.get('EXCHANGE_FALLBACK_RATE') if current_app else None
            if fallback_env is None:
                fallback_env = None
            if fallback_env:
                snapshot = store_rate(
                    ExchangeRateSnapshot(
                        id=None,
                        provider=provider_key,
                        base_currency=base_currency,
                        quote_currency=quote_currency,
                        rate=_to_decimal(fallback_env, '0'),
                        fetched_at=now,
                        notes='Fallback rate (env EXCHANGE_FALLBACK_RATE)',
                    )
                )
            else:
                raise RuntimeError('No se pudo obtener el tipo de cambio y no hay fallback configurado.')

    return snapshot
