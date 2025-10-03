"""Utilities to manage CAC price index."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from flask import current_app

from extensions import db
from models import PricingIndex


def _to_decimal(value: object, default: str = "1") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def get_current_cac_index(default: Decimal = Decimal('1.0')) -> Decimal:
    """Return the latest CAC index value (defaults to 1.0)."""

    query = PricingIndex.query.filter_by(name='CAC').order_by(
        PricingIndex.valid_from.desc(),
        PricingIndex.created_at.desc(),
    )
    record = query.first()
    if record:
        return _to_decimal(record.value, '1')
    return default


def set_cac_index(value: Decimal, valid_from: Optional[date] = None, notes: Optional[str] = None) -> PricingIndex:
    """Persist a new CAC index entry."""

    valid_date = valid_from or date.today()
    cac_value = _to_decimal(value, '1')

    record = PricingIndex(
        name='CAC',
        value=cac_value,
        valid_from=valid_date,
        notes=notes,
    )
    db.session.add(record)
    db.session.commit()

    if current_app:
        current_app.logger.info(
            '📈 Índice CAC actualizado',
            extra={
                'valor': float(cac_value),
                'valid_from': valid_date.isoformat(),
            },
        )

    return record


def ensure_cac_seed(default_value: Decimal = Decimal('1.0')) -> None:
    """Guarantee at least one CAC value exists."""

    if PricingIndex.query.filter_by(name='CAC').count():
        return
    set_cac_index(default_value, date.today(), notes='Semilla automática CAC')
