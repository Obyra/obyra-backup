"""Utilities to persist and retrieve foreign exchange rates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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
    value: Decimal
    as_of_date: date
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
        value=_to_decimal(exchange.value, '0'),
        as_of_date=exchange.as_of_date or exchange.fetched_at.date(),
        fetched_at=exchange.fetched_at or exchange.created_at or datetime.utcnow(),
        source_url=exchange.source_url,
        notes=exchange.notes,
    )


def get_rate_for_date(
    provider: str,
    base_currency: str,
    quote_currency: str,
    as_of: date,
) -> Optional[ExchangeRateSnapshot]:
    """Return the stored rate for the given date (closest match if exact missing)."""

    query = (
        ExchangeRate.query.filter_by(
            provider=provider,
            base_currency=base_currency,
            quote_currency=quote_currency,
        )
        .filter(ExchangeRate.as_of_date == as_of)
        .order_by(ExchangeRate.fetched_at.desc(), ExchangeRate.id.desc())
    )

    existing = query.first()
    if existing:
        return _as_snapshot(existing)

    # fallback to most recent older snapshot
    fallback = (
        ExchangeRate.query.filter_by(
            provider=provider,
            base_currency=base_currency,
            quote_currency=quote_currency,
        )
        .filter(ExchangeRate.as_of_date <= as_of)
        .order_by(ExchangeRate.as_of_date.desc(), ExchangeRate.fetched_at.desc(), ExchangeRate.id.desc())
        .first()
    )
    if fallback:
        return _as_snapshot(fallback)
    return None


def store_rate(snapshot: ExchangeRateSnapshot) -> ExchangeRateSnapshot:
    """Persist the snapshot and return it with a database identifier."""

    exchange = ExchangeRate(
        provider=snapshot.provider,
        base_currency=snapshot.base_currency,
        quote_currency=snapshot.quote_currency,
        value=_to_decimal(snapshot.value, '0'),
        as_of_date=snapshot.as_of_date,
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
    fetcher: Callable[[date], Optional[ExchangeRateSnapshot]],
    as_of: Optional[date] = None,
    fallback_rate: Optional[Decimal] = None,
) -> ExchangeRateSnapshot:
    """Return an exchange rate snapshot for the requested day."""

    provider_key = provider.lower()
    base_currency = base_currency.upper()
    quote_currency = quote_currency.upper()
    as_of_date = as_of or date.today()

    snapshot = get_rate_for_date(provider_key, base_currency, quote_currency, as_of_date)

    if snapshot and snapshot.as_of_date == as_of_date:
        return snapshot

    fetched = fetcher(as_of_date)
    if fetched:
        fetched.provider = provider_key
        fetched.base_currency = base_currency
        fetched.quote_currency = quote_currency
        if not fetched.as_of_date:
            fetched.as_of_date = as_of_date
        snapshot = store_rate(fetched)
    elif snapshot is None and fallback_rate is not None:
        now = datetime.utcnow()
        snapshot = store_rate(
            ExchangeRateSnapshot(
                id=None,
                provider=provider_key,
                base_currency=base_currency,
                quote_currency=quote_currency,
                value=fallback_rate,
                as_of_date=as_of_date,
                fetched_at=now,
                notes='Fallback rate (static configuration)',
            )
        )
    elif snapshot is None:
        fallback_env = current_app.config.get('EXCHANGE_FALLBACK_RATE') if current_app else None
        if fallback_env:
            now = datetime.utcnow()
            snapshot = store_rate(
                ExchangeRateSnapshot(
                    id=None,
                    provider=provider_key,
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    value=_to_decimal(fallback_env, '0'),
                    as_of_date=as_of_date,
                    fetched_at=now,
                    notes='Fallback rate (env EXCHANGE_FALLBACK_RATE)',
                )
            )
        else:
            raise RuntimeError('No se pudo obtener el tipo de cambio y no hay fallback configurado.')

    return snapshot
