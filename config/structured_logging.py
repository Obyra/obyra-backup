"""
Logging estructurado JSON
==========================

Provee un formatter y handlers que emiten logs en formato JSON,
listos para ser ingestados por sistemas centralizados:

- Loki + Grafana
- ELK Stack (Elasticsearch + Logstash + Kibana)
- AWS CloudWatch Logs
- Datadog
- Splunk

Cómo se activa:
    En .env:  LOG_FORMAT=json
    Default: LOG_FORMAT=text (mantiene el formato actual de OBYRA)

Cada log emitido incluye automáticamente:
    - timestamp ISO 8601
    - level
    - logger name
    - message
    - module / function / line
    - request_id (si hay request)
    - user_id, organizacion_id (si hay usuario logueado)
    - exception (con traceback) si aplica

Uso normal:
    import logging
    logger = logging.getLogger(__name__)
    logger.info('Usuario creó obra', extra={'obra_id': 123})

El campo `extra` se merge en el JSON output.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """Formatter que emite logs en JSON para ingesta centralizada."""

    # Campos estándar que NO van como `extra`
    STANDARD_FIELDS = {
        'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
        'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
        'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
        'thread', 'threadName', 'processName', 'process', 'message',
        'taskName',
    }

    def format(self, record: logging.LogRecord) -> str:
        log_dict: Dict[str, Any] = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Agregar excepción si existe
        if record.exc_info:
            log_dict['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': self.formatException(record.exc_info),
            }

        # Agregar contexto de request si existe
        try:
            from flask import has_request_context, request, g
            if has_request_context():
                log_dict['request'] = {
                    'method': request.method,
                    'path': request.path,
                    'remote_addr': request.headers.get('X-Forwarded-For', request.remote_addr),
                }
                # Request ID si está seteado
                if hasattr(g, 'request_id'):
                    log_dict['request']['id'] = g.request_id

                # Usuario actual
                try:
                    from flask_login import current_user
                    if current_user.is_authenticated:
                        log_dict['user'] = {
                            'id': current_user.id,
                            'email': getattr(current_user, 'email', None),
                            'organizacion_id': getattr(current_user, 'organizacion_id', None),
                        }
                except Exception:
                    pass
        except Exception:
            pass

        # Agregar campos extra del record
        for key, value in record.__dict__.items():
            if key not in self.STANDARD_FIELDS and not key.startswith('_'):
                try:
                    json.dumps(value)  # Verificar serializable
                    log_dict[key] = value
                except (TypeError, ValueError):
                    log_dict[key] = str(value)

        return json.dumps(log_dict, ensure_ascii=False, default=str)


def setup_structured_logging(app):
    """
    Configura logging estructurado JSON si LOG_FORMAT=json está seteado.
    Sino, mantiene el setup tradicional de OBYRA.
    """
    log_format = os.environ.get('LOG_FORMAT', 'text').lower()

    if log_format != 'json':
        # Mantener configuración tradicional
        return

    app.logger.info('[Logging] Activando formato JSON estructurado')

    # Reemplazar formatters de los handlers existentes
    json_formatter = JSONFormatter()

    for handler in app.logger.handlers:
        handler.setFormatter(json_formatter)

    # Reemplazar también en root logger para capturar logs de bibliotecas
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(json_formatter)

    # Agregar handler stdout para logs centralizados (Docker logs)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(json_formatter)
    stdout_handler.setLevel(logging.INFO)
    app.logger.addHandler(stdout_handler)

    # Loggers específicos
    for logger_name in ['security', 'performance', 'audit']:
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers:
            handler.setFormatter(json_formatter)
