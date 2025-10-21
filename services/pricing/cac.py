"""Backward-compatible wrappers for CAC helpers."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from services.cac.cac_service import (
    CACContext,
    get_cac_context,
    get_index_for_month,
    record_manual_index,
)


def get_current_cac_index(default: Decimal = Decimal('1.0')) -> Decimal:
    context = get_cac_context()
    return context.multiplier if context.multiplier > Decimal('0') else default


def set_cac_index(value: Decimal, valid_from: Optional[date] = None, notes: Optional[str] = None):
    target = valid_from or date.today()
    return record_manual_index(target.year, target.month, value, notes)


def ensure_cac_seed(default_value: Decimal = Decimal('1.0')) -> None:
    context = get_cac_context()
    if context.value > Decimal('0'):
        return
    record_manual_index(date.today().year, date.today().month, default_value)
