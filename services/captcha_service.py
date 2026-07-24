# -*- coding: utf-8 -*-
"""Validacion de Cloudflare Turnstile para formularios publicos (anti-bot).

Protege register / forgot-password de creacion masiva de cuentas y mail-bombing.

Feature-flag por env: si TURNSTILE_SECRET_KEY NO esta seteada, la validacion queda
DESHABILITADA y deja pasar todo (los formularios funcionan igual que antes). Asi el
deploy del codigo no rompe nada hasta que Obyra cree las claves en Cloudflare y las
configure. El widget en el template tambien se muestra solo si hay TURNSTILE_SITE_KEY.
"""
import os


def _secret():
    return (os.getenv('TURNSTILE_SECRET_KEY') or '').strip()


def turnstile_enabled():
    """True si Turnstile esta configurado (hay secret)."""
    return bool(_secret())


def verify_turnstile(token, remoteip=None):
    """Valida el token del widget contra Cloudflare.

    Devuelve (ok: bool, motivo: str|None).
      - Sin secret configurado -> (True, None): feature off, no bloquea.
      - Cloudflare caido / timeout -> (True, None): fail-open a proposito, para no
        dejar afuera a usuarios legitimos por un problema de red. El rate-limit
        (3-5/min en estos endpoints) sigue conteniendo el abuso.
      - Token ausente o rechazado -> (False, motivo).
    """
    secret = _secret()
    if not secret:
        return True, None
    if not token:
        return False, 'Completá la verificación anti-robot y reintentá.'
    try:
        import requests
        resp = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret, 'response': token, 'remoteip': remoteip or ''},
            timeout=5,
        )
        data = resp.json()
    except Exception:
        return True, None  # fail-open ante error de red con Cloudflare
    if data.get('success'):
        return True, None
    return False, 'No pudimos verificar que no seas un robot. Reintentá.'
