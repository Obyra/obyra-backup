# -*- coding: utf-8 -*-
"""Cap de gasto de LLM por usuario/dia (defensa en profundidad de costos).

El pipeline IA (services/clasificador_llm) llama a la API de Anthropic. Sin tope,
un usuario autenticado podria disparar /pipeline-ia/analizar hasta el rate-limit
global (200/min) y generar una factura enorme. Aca:
  - check_llm_budget(): gate ANTES de la llamada (el endpoint devuelve 429 si se paso).
  - register_llm_spend(): registra tokens/costo REALES DESPUES de la llamada.

Limites configurables por env (defaults pensados para NO romper el uso normal
-varios pliegos por dia- pero cortar el abuso en ~1 min de martilleo a 200/min):
  LLM_MAX_TOKENS_DAY  (default 2_000_000)
  LLM_MAX_USD_DAY     (default 15.0)
  LLM_BUDGET_ENFORCE  (default '1'; poner '0' desactiva el gate, ej. dev)

Precio Haiku 4.5 (aprox, conservador para que el cap corte antes que gastar de mas):
  input  ~ US$1.00 / 1M tokens   ·   output ~ US$5.00 / 1M tokens

Todo best-effort / fail-open: un error en el contador NUNCA debe romper el pipeline.
"""
import os
from datetime import date
from decimal import Decimal

from extensions import db

_PRECIO_INPUT_USD_POR_M = 1.00
_PRECIO_OUTPUT_USD_POR_M = 5.00


def _limite_tokens():
    try:
        return int(os.getenv('LLM_MAX_TOKENS_DAY', '2000000'))
    except (TypeError, ValueError):
        return 2_000_000


def _limite_usd():
    try:
        return float(os.getenv('LLM_MAX_USD_DAY', '15'))
    except (TypeError, ValueError):
        return 15.0


def _enforce():
    return os.getenv('LLM_BUDGET_ENFORCE', '1') != '0'


def estimar_costo_usd(input_tokens, output_tokens):
    return ((input_tokens or 0) / 1_000_000) * _PRECIO_INPUT_USD_POR_M + \
           ((output_tokens or 0) / 1_000_000) * _PRECIO_OUTPUT_USD_POR_M


def get_or_create_daily_spend(usuario_id):
    """Fila de gasto de HOY para el usuario (la crea si no existe). Maneja la carrera
    de dos requests concurrentes creando la misma fila."""
    from models.core import UserDailyLLMSpend
    hoy = date.today()
    spend = UserDailyLLMSpend.query.filter_by(usuario_id=usuario_id, fecha=hoy).first()
    if spend is None:
        spend = UserDailyLLMSpend(usuario_id=usuario_id, fecha=hoy,
                                  tokens_usados=0, costo_usd=Decimal('0'), llamadas=0)
        db.session.add(spend)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()  # otro request la creo primero -> recuperarla
            spend = UserDailyLLMSpend.query.filter_by(usuario_id=usuario_id, fecha=hoy).first()
    return spend


def check_llm_budget(usuario_id, estimated_tokens=8000):
    """(puede_proceder: bool, motivo: str|None).

    Fail-open: si el enforcement esta apagado, no hay usuario, o algo falla, deja
    pasar (nunca romper el pipeline por el contador de gasto)."""
    if not usuario_id or not _enforce():
        return True, None
    try:
        spend = get_or_create_daily_spend(usuario_id)
        tok = int(spend.tokens_usados or 0)
        usd = float(spend.costo_usd or 0)
    except Exception:
        return True, None  # fail-open
    if tok + int(estimated_tokens or 0) > _limite_tokens():
        return False, (f'Alcanzaste el limite diario de uso de IA '
                       f'({tok:,}/{_limite_tokens():,} tokens). Se resetea manana.')
    if usd + estimar_costo_usd(estimated_tokens, 0) > _limite_usd():
        return False, (f'Alcanzaste el limite diario de gasto de IA '
                       f'(US${usd:.2f}/US${_limite_usd():.2f}). Se resetea manana.')
    return True, None


def register_llm_spend(usuario_id, input_tokens, output_tokens):
    """Registra el uso REAL despues de una llamada exitosa. Best-effort."""
    if not usuario_id:
        return
    tokens = int(input_tokens or 0) + int(output_tokens or 0)
    if tokens <= 0:
        return
    costo = Decimal(str(round(estimar_costo_usd(input_tokens, output_tokens), 6)))
    try:
        spend = get_or_create_daily_spend(usuario_id)
        spend.tokens_usados = int(spend.tokens_usados or 0) + tokens
        spend.costo_usd = (spend.costo_usd or Decimal('0')) + costo
        spend.llamadas = int(spend.llamadas or 0) + 1
        db.session.commit()
    except Exception:
        db.session.rollback()
