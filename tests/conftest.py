"""
Pytest configuration and fixtures for OBYRA testing.
"""
import os
import tempfile
import pytest
from pathlib import Path

# Set test environment variables before importing app
os.environ['FLASK_ENV'] = 'testing'
os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only'
os.environ['TESTING'] = '1'
os.environ['WTF_CSRF_ENABLED'] = 'False'  # Disable CSRF for testing

# Use in-memory SQLite for tests
test_db_fd, test_db_path = tempfile.mkstemp(suffix='.db')
os.environ['DATABASE_URL'] = f'sqlite:///{test_db_path}'

from app import app as flask_app
from extensions import db
from models import Usuario, Organizacion


@pytest.fixture(scope='session')
def app():
    """Create and configure a Flask app instance for testing."""
    # Configure app for testing
    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{test_db_path}',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'LOGIN_DISABLED': False,
        'SECRET_KEY': 'test-secret-key',
    })

    # Create application context
    with flask_app.app_context():
        # Create all tables
        db.create_all()

        yield flask_app

        # Cleanup
        db.session.remove()
        db.drop_all()

    # Close and remove test database
    os.close(test_db_fd)
    os.unlink(test_db_path)


@pytest.fixture(scope='function')
def client(app):
    """Create a test client for making requests."""
    return app.test_client()


@pytest.fixture(scope='function')
def runner(app):
    """Create a CLI runner for testing CLI commands."""
    return app.test_cli_runner()


@pytest.fixture(scope='function')
def db_session(app):
    """Create a new database session for a test.

    This fixture provides transaction rollback after each test.
    """
    with app.app_context():
        # Start a transaction
        connection = db.engine.connect()
        transaction = connection.begin()

        # Bind the session to the connection
        session = db.session

        yield session

        # Rollback the transaction
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope='function')
def test_org(app):
    """Create a test organization."""
    with app.app_context():
        org = Organizacion(
            nombre="Test Organization",
            razon_social="Test Org SA",
            cuit="20-12345678-9"
        )
        db.session.add(org)
        db.session.commit()

        yield org

        # Cleanup
        db.session.delete(org)
        db.session.commit()


@pytest.fixture(scope='function')
def test_user(app, test_org):
    """Create a test user."""
    with app.app_context():
        from werkzeug.security import generate_password_hash

        user = Usuario(
            username="testuser",
            email="test@example.com",
            password_hash=generate_password_hash("testpassword123"),
            organizacion_id=test_org.id,
            rol="administrador",
            role="admin"
        )
        db.session.add(user)
        db.session.commit()

        yield user

        # Cleanup
        db.session.delete(user)
        db.session.commit()


@pytest.fixture(scope='function')
def authenticated_client(client, test_user):
    """Create an authenticated test client."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
        sess['_fresh'] = True

    return client


@pytest.fixture(scope='function')
def admin_user(app, test_org):
    """Create an admin user for testing."""
    with app.app_context():
        from werkzeug.security import generate_password_hash

        admin = Usuario(
            username="admin",
            email="admin@obyra.com",
            password_hash=generate_password_hash("admin123"),
            organizacion_id=test_org.id,
            rol="administrador",
            role="admin",
            plan_activo="premium"
        )
        db.session.add(admin)
        db.session.commit()

        yield admin

        # Cleanup
        db.session.delete(admin)
        db.session.commit()


# Markers for categorizing tests
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests (fast)"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (slower)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
