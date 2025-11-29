"""
Security Headers Middleware
===========================

Agrega headers HTTP de seguridad a todas las respuestas para proteger contra:
- XSS (Cross-Site Scripting)
- Clickjacking
- MIME-type sniffing
- Information disclosure

Referencias:
- OWASP Secure Headers: https://owasp.org/www-project-secure-headers/
- MDN HTTP Headers: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers
"""

import os
from flask import request


def setup_security_headers(app):
    """
    Configura headers de seguridad HTTP en todas las respuestas.

    Headers agregados:
    - Content-Security-Policy (CSP)
    - X-Content-Type-Options
    - X-Frame-Options
    - X-XSS-Protection
    - Referrer-Policy
    - Permissions-Policy
    - Strict-Transport-Security (HSTS) - solo en producción con HTTPS
    """

    # Detectar si estamos en producción
    is_production = os.environ.get('FLASK_ENV') == 'production'

    @app.after_request
    def add_security_headers(response):
        """Agrega headers de seguridad a cada respuesta."""

        # ===== Content-Security-Policy (CSP) =====
        # Política que controla qué recursos pueden cargarse
        # Nota: 'unsafe-inline' y 'unsafe-eval' son necesarios para Bootstrap/jQuery
        # En el futuro se pueden eliminar usando nonces
        csp_directives = [
            "default-src 'self'",
            # Scripts: self + CDNs de Bootstrap, jQuery, FontAwesome, Chart.js
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com "
            "https://code.jquery.com "
            "https://unpkg.com "
            "https://accounts.google.com "
            "https://apis.google.com",
            # Estilos: self + CDNs + inline (Bootstrap requiere inline styles)
            "style-src 'self' 'unsafe-inline' "
            "https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com "
            "https://fonts.googleapis.com "
            "https://unpkg.com",
            # Fuentes: self + Google Fonts + FontAwesome
            "font-src 'self' "
            "https://fonts.gstatic.com "
            "https://cdnjs.cloudflare.com "
            "data:",
            # Imágenes: self + data URIs + blob (para previews)
            "img-src 'self' data: blob: https:",
            # Conexiones: self + APIs externas necesarias
            "connect-src 'self' "
            "https://accounts.google.com "
            "https://apis.google.com "
            "https://nominatim.openstreetmap.org "
            "https://api.mercadopago.com "
            "wss: ws:",
            # Frames: permitir Google OAuth
            "frame-src 'self' "
            "https://accounts.google.com "
            "https://www.google.com",
            # Formularios: solo a self
            "form-action 'self'",
            # Base URI: solo self
            "base-uri 'self'",
            # Object/embed: ninguno (previene Flash, etc.)
            "object-src 'none'",
            # Upgrade insecure requests en producción
            "upgrade-insecure-requests" if is_production else "",
        ]

        # Filtrar directivas vacías y unir
        csp_policy = "; ".join(d for d in csp_directives if d)
        response.headers['Content-Security-Policy'] = csp_policy

        # ===== X-Content-Type-Options =====
        # Previene MIME-type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'

        # ===== X-Frame-Options =====
        # Previene clickjacking (embeber en iframes)
        # SAMEORIGIN permite iframes del mismo dominio (necesario para algunos modales)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'

        # ===== X-XSS-Protection =====
        # Activa filtro XSS del navegador (legacy, pero no hace daño)
        response.headers['X-XSS-Protection'] = '1; mode=block'

        # ===== Referrer-Policy =====
        # Controla qué información se envía en el header Referer
        # strict-origin-when-cross-origin: envía origen completo a mismo sitio,
        # solo origen a otros sitios (no path ni query)
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # ===== Permissions-Policy (antes Feature-Policy) =====
        # Controla acceso a APIs del navegador
        permissions = [
            "accelerometer=()",
            "camera=()",
            "geolocation=(self)",  # Permitir geolocalización para mapas
            "gyroscope=()",
            "magnetometer=()",
            "microphone=()",
            "payment=(self)",  # Permitir Payment API para Mercado Pago
            "usb=()",
        ]
        response.headers['Permissions-Policy'] = ", ".join(permissions)

        # ===== Strict-Transport-Security (HSTS) =====
        # Solo en producción con HTTPS - fuerza conexiones seguras
        if is_production and request.is_secure:
            # max-age=31536000 = 1 año
            # includeSubDomains = aplica a subdominios
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains; preload'
            )

        # ===== Cache-Control para páginas dinámicas =====
        # Evitar cache de páginas con datos sensibles
        if response.content_type and 'text/html' in response.content_type:
            # No cachear HTML que puede contener datos del usuario
            if not response.headers.get('Cache-Control'):
                response.headers['Cache-Control'] = (
                    'no-store, no-cache, must-revalidate, private, max-age=0'
                )

        # ===== X-Permitted-Cross-Domain-Policies =====
        # Previene carga desde Flash/PDF
        response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'

        return response

    app.logger.info('Security headers middleware configurado correctamente')
