import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logging(app):
    """Configura logging estructurado para la aplicacion"""

    # Crear directorio de logs si no existe
    log_dir = os.path.join(app.root_path, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # Configurar formato detallado
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )

    # Handler para archivo general de aplicacion
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Handler para errores criticos
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'errors.log'),
        maxBytes=10485760,
        backupCount=10
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)

    # Handler para seguridad y auditoria
    security_handler = RotatingFileHandler(
        os.path.join(log_dir, 'security.log'),
        maxBytes=10485760,
        backupCount=20  # Mas retention para auditorias
    )
    security_handler.setFormatter(formatter)
    security_handler.setLevel(logging.INFO)

    # Handler para performance
    performance_handler = RotatingFileHandler(
        os.path.join(log_dir, 'performance.log'),
        maxBytes=10485760,
        backupCount=5
    )
    performance_handler.setFormatter(formatter)
    performance_handler.setLevel(logging.WARNING)  # Solo slow requests

    # Agregar handlers al logger de la app
    app.logger.addHandler(file_handler)
    app.logger.addHandler(error_handler)
    app.logger.setLevel(logging.INFO)

    # Logger especifico para seguridad
    security_logger = logging.getLogger('security')
    security_logger.addHandler(security_handler)
    security_logger.setLevel(logging.INFO)
    security_logger.propagate = False  # No propagar a root logger

    # Logger especifico para performance
    performance_logger = logging.getLogger('performance')
    performance_logger.addHandler(performance_handler)
    performance_logger.setLevel(logging.WARNING)
    performance_logger.propagate = False

    app.logger.info('Sistema de logging configurado correctamente')
    app.logger.info(f'Logs guardados en: {log_dir}')
