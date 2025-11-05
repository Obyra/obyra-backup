import time
from flask import request, g
import logging


logger = logging.getLogger('performance')


def setup_request_timing(app):
    """
    Middleware para medir tiempo de requests y detectar requests lentos

    Agrega:
    - Medicion de tiempo de cada request
    - Log de requests lentos (>1 segundo)
    - Header X-Response-Time en todas las respuestas
    """

    @app.before_request
    def before_request():
        """Marca el tiempo de inicio del request"""
        g.start_time = time.time()
        g.request_path = request.path
        g.request_method = request.method

    @app.after_request
    def after_request(response):
        """
        Calcula el tiempo transcurrido y agrega header de timing
        Log de requests lentos
        """
        if hasattr(g, 'start_time'):
            elapsed = time.time() - g.start_time

            # Log requests lentos (>1 segundo)
            if elapsed > 1.0:
                logger.warning(
                    f'Slow request: {g.request_method} {g.request_path} - '
                    f'{elapsed:.2f}s - Status: {response.status_code}'
                )

            # Log requests muy lentos (>5 segundos)
            if elapsed > 5.0:
                logger.error(
                    f'Very slow request: {g.request_method} {g.request_path} - '
                    f'{elapsed:.2f}s - Status: {response.status_code}'
                )

            # Agregar header de timing a la respuesta
            response.headers['X-Response-Time'] = f'{elapsed:.3f}s'

        return response

    @app.teardown_request
    def teardown_request(exception=None):
        """
        Log de errores no manejados durante el request
        """
        if exception:
            elapsed = time.time() - g.start_time if hasattr(g, 'start_time') else 0
            logger.error(
                f'Request failed: {g.request_method if hasattr(g, "request_method") else "?"} '
                f'{g.request_path if hasattr(g, "request_path") else "?"} - '
                f'{elapsed:.2f}s - Exception: {str(exception)}'
            )
            app.logger.error(
                f'Exception during request: {exception}',
                exc_info=True
            )

    app.logger.info('Request timing middleware configurado correctamente')
