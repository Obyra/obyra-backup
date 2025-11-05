"""
Configuración de Rate Limiting para OBYRA
Protege APIs contra abuso y ataques DoS
"""

import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def get_limiter_key():
    """
    Obtiene la clave para rate limiting.
    Prioriza: user_id > IP address
    """
    from flask import g
    from flask_login import current_user

    # Si el usuario está autenticado, usar su ID
    if hasattr(current_user, 'id') and current_user.is_authenticated:
        return f"user:{current_user.id}"

    # Si no, usar la IP
    return f"ip:{get_remote_address()}"


def setup_rate_limiter(app):
    """
    Configura Flask-Limiter con límites apropiados

    Límites por defecto:
    - 200 requests por minuto por usuario/IP
    - 1000 requests por hora por usuario/IP
    """

    # Configuración de storage
    # En producción, debería usar Redis: "redis://localhost:6379"
    # En desarrollo, usar memoria
    storage_uri = os.environ.get('RATE_LIMITER_STORAGE', 'memory://')

    limiter = Limiter(
        app=app,
        key_func=get_limiter_key,
        storage_uri=storage_uri,
        default_limits=["200 per minute", "1000 per hour"],
        strategy="fixed-window",  # fixed-window or moving-window
        headers_enabled=True,  # Agregar headers X-RateLimit-* a las respuestas
        swallow_errors=True,  # No fallar si el storage no está disponible
        in_memory_fallback_enabled=True,  # Fallback a memoria si Redis falla
    )

    # Registrar handler de error personalizado
    @app.errorhandler(429)
    def ratelimit_handler(e):
        from flask import jsonify, request

        # Si es una petición API, devolver JSON
        if request.path.startswith('/api/'):
            return jsonify({
                'error': 'Rate limit exceeded',
                'message': 'Has excedido el límite de peticiones. Por favor intenta más tarde.',
                'retry_after': e.description
            }), 429

        # Si no, devolver HTML
        from flask import render_template
        return render_template(
            'errors/429.html',
            retry_after=e.description
        ), 429

    app.logger.info(f'[OK] Rate limiter configurado con storage: {storage_uri}')

    return limiter


# Decoradores pre-configurados para casos comunes

def rate_limit_strict(func):
    """
    Rate limit estricto para endpoints sensibles (login, registro, cambio de contraseña)
    Límite: 5 requests por minuto
    """
    from flask_limiter import Limiter
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper._rate_limit = "5 per minute"
    return wrapper


def rate_limit_api(func):
    """
    Rate limit para APIs generales
    Límite: 100 requests por minuto
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper._rate_limit = "100 per minute"
    return wrapper


def rate_limit_expensive(func):
    """
    Rate limit para operaciones costosas (reportes, exports, PDF generation)
    Límite: 10 requests por minuto
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper._rate_limit = "10 per minute"
    return wrapper
