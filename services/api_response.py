"""
API Response Helper
===================

Helper centralizado para respuestas JSON consistentes en toda la API.

Reemplaza los 4 formatos distintos identificados en la auditoría:
- {'ok': True/False}
- {'exito': True/False}
- {'success': True/False}
- {'error': '...'}

Por un único formato estándar:
    {
        "ok": bool,
        "data": <dict|list|None>,
        "error": <str|None>,
        "message": <str|None>
    }

Uso:
    from services.api_response import api_success, api_error

    # Éxito
    return api_success(data={'id': 123, 'nombre': 'Foo'})
    return api_success(message='Operación completada')

    # Error
    return api_error('No autorizado', status=403)
    return api_error('Recurso no encontrado', status=404, exception=e)
"""

from flask import jsonify, current_app
from typing import Any, Optional, Union


def api_success(
    data: Any = None,
    message: Optional[str] = None,
    status: int = 200,
):
    """
    Respuesta exitosa estandarizada.

    Args:
        data: Datos a devolver (dict, list, etc)
        message: Mensaje informativo opcional
        status: HTTP status code (default 200)

    Returns:
        Tupla (response, status) compatible con Flask
    """
    body = {'ok': True}
    if data is not None:
        body['data'] = data
    if message:
        body['message'] = message
    return jsonify(body), status


def api_error(
    message: str = 'Error interno del servidor',
    status: int = 500,
    exception: Optional[Exception] = None,
    error_code: Optional[str] = None,
):
    """
    Respuesta de error estandarizada.

    Args:
        message: Mensaje genérico para el cliente (NO exponer detalles internos)
        status: HTTP status code (default 500)
        exception: Excepción original (se loguea pero NO se expone)
        error_code: Código de error opcional para el frontend

    Returns:
        Tupla (response, status) compatible con Flask
    """
    if exception is not None:
        try:
            current_app.logger.error(
                f'API error [{status}]: {message} | Exception: {exception}',
                exc_info=True,
            )
        except RuntimeError:
            # Sin contexto de app, ignorar el log
            pass

    body = {'ok': False, 'error': message}
    if error_code:
        body['error_code'] = error_code
    return jsonify(body), status


def api_validation_error(
    message: str = 'Datos inválidos',
    fields: Optional[dict] = None,
    status: int = 400,
):
    """
    Respuesta para errores de validación de entrada.

    Args:
        message: Mensaje general
        fields: Diccionario {campo: mensaje_error}
        status: HTTP status code (default 400)
    """
    body = {'ok': False, 'error': message}
    if fields:
        body['fields'] = fields
    return jsonify(body), status


def api_not_found(resource: str = 'Recurso'):
    """Respuesta 404 estandarizada."""
    return api_error(f'{resource} no encontrado', status=404)


def api_forbidden(message: str = 'No tienes permisos para acceder a este recurso'):
    """Respuesta 403 estandarizada."""
    return api_error(message, status=403)


def api_unauthorized(message: str = 'Autenticación requerida'):
    """Respuesta 401 estandarizada."""
    return api_error(message, status=401)
