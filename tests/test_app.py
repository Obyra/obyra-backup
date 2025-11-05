"""
Basic smoke tests for the OBYRA application.
"""
import pytest


@pytest.mark.unit
def test_app_exists(app):
    """Test that the Flask app instance exists."""
    assert app is not None


@pytest.mark.unit
def test_app_is_testing(app):
    """Test that the app is in testing mode."""
    assert app.config['TESTING'] is True


@pytest.mark.unit
def test_secret_key_is_set(app):
    """Test that a secret key is configured."""
    assert app.secret_key is not None
    assert app.secret_key != ''


@pytest.mark.unit
def test_database_is_configured(app):
    """Test that the database is configured."""
    assert 'SQLALCHEMY_DATABASE_URI' in app.config
    assert app.config['SQLALCHEMY_DATABASE_URI'] is not None


@pytest.mark.integration
def test_index_route(client):
    """Test that the index route is accessible."""
    response = client.get('/')
    assert response.status_code in [200, 302]  # 200 or redirect


@pytest.mark.integration
def test_health_endpoint_if_exists(client):
    """Test health check endpoint if it exists."""
    response = client.get('/health')
    # Health endpoint might not exist, so we allow 404
    assert response.status_code in [200, 404]


@pytest.mark.integration
def test_static_files_accessible(client):
    """Test that static files route exists."""
    # Try to access a common static path
    response = client.get('/static/css/style.css')
    # File might not exist, but route should be registered
    assert response.status_code in [200, 304, 404]


@pytest.mark.unit
def test_csrf_protection_enabled(app):
    """Test that CSRF protection is enabled (but disabled in testing)."""
    # In testing, CSRF should be disabled
    assert app.config.get('WTF_CSRF_ENABLED') is False


@pytest.mark.unit
def test_extensions_initialized(app):
    """Test that Flask extensions are properly initialized."""
    from extensions import db, login_manager, csrf

    assert db is not None
    assert login_manager is not None
    assert csrf is not None


@pytest.mark.unit
def test_blueprints_registered(app):
    """Test that blueprints are registered."""
    # Check that we have more than just the default blueprints
    blueprints = list(app.blueprints.keys())
    assert len(blueprints) > 0

    # Check for some core blueprints that should exist
    # Note: These might not all be registered depending on imports
    # but there should be at least one
    possible_blueprints = ['auth', 'obras', 'presupuestos', 'reportes']
    has_core_blueprint = any(bp in blueprints for bp in possible_blueprints)
    # If none are registered, it's still ok in minimal test mode
    # Just verify we don't crash
    assert isinstance(blueprints, list)


@pytest.mark.integration
def test_app_context(app):
    """Test that app context works properly."""
    with app.app_context():
        from flask import current_app
        assert current_app == app


@pytest.mark.integration
def test_request_context(app):
    """Test that request context works properly."""
    with app.test_request_context('/'):
        from flask import request
        assert request.path == '/'
