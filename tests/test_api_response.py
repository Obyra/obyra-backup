"""
Tests del helper api_response (F3.11).

Verifica que api_success/api_error/etc devuelvan el formato JSON esperado.
"""
import pytest
import json
from services.api_response import (
    api_success,
    api_error,
    api_validation_error,
    api_not_found,
    api_forbidden,
    api_unauthorized,
)


@pytest.mark.unit
def test_api_success_basic(app):
    """api_success() sin args devuelve {ok: True} con status 200."""
    with app.app_context():
        response, status = api_success()
        assert status == 200
        body = json.loads(response.get_data(as_text=True))
        assert body == {'ok': True}


@pytest.mark.unit
def test_api_success_with_data(app):
    """api_success(data=...) incluye los datos en 'data'."""
    with app.app_context():
        data = {'id': 123, 'nombre': 'Foo'}
        response, status = api_success(data=data)
        assert status == 200
        body = json.loads(response.get_data(as_text=True))
        assert body['ok'] is True
        assert body['data'] == data


@pytest.mark.unit
def test_api_success_with_message(app):
    """api_success(message='...') incluye el mensaje."""
    with app.app_context():
        response, status = api_success(message='Operación OK')
        body = json.loads(response.get_data(as_text=True))
        assert body['message'] == 'Operación OK'


@pytest.mark.unit
def test_api_error_basic(app):
    """api_error() devuelve {ok: False, error: ...} con 500."""
    with app.app_context():
        response, status = api_error()
        assert status == 500
        body = json.loads(response.get_data(as_text=True))
        assert body['ok'] is False
        assert 'error' in body


@pytest.mark.unit
def test_api_error_custom_message(app):
    """api_error con mensaje personalizado."""
    with app.app_context():
        response, status = api_error('Algo salió mal', status=400)
        assert status == 400
        body = json.loads(response.get_data(as_text=True))
        assert body['error'] == 'Algo salió mal'


@pytest.mark.unit
def test_api_error_logs_exception_but_doesnt_expose(app):
    """
    CRÍTICO: api_error con exception NO expone el str(e) al cliente.
    Solo loguea internamente.
    """
    with app.app_context():
        try:
            raise ValueError("Detalle interno secreto: contraseña=abc")
        except ValueError as e:
            response, status = api_error('Error de validación', exception=e)
            body = json.loads(response.get_data(as_text=True))
            # NO debe contener el detalle interno
            assert 'contraseña' not in body['error']
            assert 'secreto' not in body['error']
            assert body['error'] == 'Error de validación'


@pytest.mark.unit
def test_api_validation_error(app):
    """api_validation_error con campos."""
    with app.app_context():
        response, status = api_validation_error(
            'Campos inválidos',
            fields={'email': 'Email inválido', 'edad': 'Debe ser positivo'}
        )
        assert status == 400
        body = json.loads(response.get_data(as_text=True))
        assert body['ok'] is False
        assert 'fields' in body
        assert body['fields']['email'] == 'Email inválido'


@pytest.mark.unit
def test_api_not_found(app):
    """api_not_found devuelve 404."""
    with app.app_context():
        response, status = api_not_found('Obra')
        assert status == 404
        body = json.loads(response.get_data(as_text=True))
        assert 'Obra' in body['error']
        assert 'no encontrad' in body['error'].lower()


@pytest.mark.unit
def test_api_forbidden(app):
    """api_forbidden devuelve 403."""
    with app.app_context():
        response, status = api_forbidden()
        assert status == 403
        body = json.loads(response.get_data(as_text=True))
        assert body['ok'] is False


@pytest.mark.unit
def test_api_unauthorized(app):
    """api_unauthorized devuelve 401."""
    with app.app_context():
        response, status = api_unauthorized()
        assert status == 401
        body = json.loads(response.get_data(as_text=True))
        assert body['ok'] is False
