"""
Pytest configuration and fixtures for OBYRA testing.

Usa SQLite in-memory por defecto. La app real usa PostgreSQL,
pero los tests no necesitan toda la complejidad.
"""
import os
import sys
import tempfile
import pytest

# === Configurar entorno ANTES de importar nada de la app ===
os.environ['FLASK_ENV'] = 'testing'
os.environ['TESTING'] = '1'
os.environ['WTF_CSRF_ENABLED'] = 'False'
os.environ['SECRET_KEY'] = 'test-secret-key-for-testing-only'
os.environ['SESSION_SECRET'] = 'test-secret-key-for-testing-only'
os.environ['ADMIN_DEFAULT_PASSWORD'] = 'TestAdmin123'

# Usar SQLite con archivo temporal
test_db_fd, test_db_path = tempfile.mkstemp(suffix='.db')
os.environ['DATABASE_URL'] = f'sqlite:///{test_db_path}'

# IMPORTANTE: parchear app.py para que NO use connect_args de PostgreSQL
# cuando la URL es sqlite. Hacemos un monkeypatch al módulo de modelos
# antes de cargar la app.

# Importar Flask app — esto inicializa todo
from app import app as flask_app
from extensions import db
from models import Usuario, Organizacion

# Forzar reconfiguración del engine para SQLite
# (la app cargó con connect_args de PostgreSQL que no funcionan en SQLite)
flask_app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{test_db_path}'
flask_app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {}

# Disponer del engine viejo y crear uno nuevo
with flask_app.app_context():
    try:
        db.engine.dispose()
    except Exception:
        pass


@pytest.fixture(scope='session')
def app():
    """Flask app configurada para testing."""
    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'LOGIN_DISABLED': False,
        'SECRET_KEY': 'test-secret-key',
    })

    with flask_app.app_context():
        # Importar TODOS los modelos para asegurar registro en metadata
        try:
            import models  # noqa
            from models import core, projects, inventory, equipment, budgets  # noqa
            from models import audit, clients, suppliers, templates, utils  # noqa
            from models import marketplace as mk_models  # noqa
            from models import proveedores_oc  # noqa
        except ImportError:
            pass

        # Crear tablas una por una (tolerante a errores de SQLite con JSONB, etc)
        from sqlalchemy.exc import CompileError, OperationalError
        for table_name, table_obj in db.metadata.tables.items():
            try:
                table_obj.create(bind=db.engine, checkfirst=True)
            except (CompileError, OperationalError, Exception) as e:
                # Algunas tablas usan tipos PostgreSQL (JSONB) que SQLite no soporta
                # Las saltamos para tests
                pass

        yield flask_app

        # Cleanup
        try:
            db.session.remove()
            db.drop_all()
        except Exception:
            pass

    try:
        os.close(test_db_fd)
        os.unlink(test_db_path)
    except OSError:
        pass


@pytest.fixture(scope='function')
def client(app):
    """Test client de Flask."""
    return app.test_client()


@pytest.fixture(scope='function')
def runner(app):
    """CLI runner para tests de comandos."""
    return app.test_cli_runner()


import uuid


def _unique_suffix():
    """Genera un sufijo único para evitar colisiones entre tests."""
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope='function')
def test_org(app):
    """Crea una organización de prueba con nombre único."""
    suffix = _unique_suffix()
    with app.app_context():
        org = Organizacion(
            nombre=f"Test Org {suffix}",
            plan_tipo='estandar',
            max_usuarios=5,
            max_obras=3,
        )
        db.session.add(org)
        db.session.commit()
        org_id = org.id

        yield org

        # Cleanup: usar refresh + delete
        try:
            db.session.expire_all()
            obj = db.session.get(Organizacion, org_id)
            if obj:
                db.session.delete(obj)
                db.session.commit()
        except Exception:
            db.session.rollback()


@pytest.fixture(scope='function')
def test_org_b(app):
    """Crea una segunda organización (para tests multi-tenant)."""
    suffix = _unique_suffix()
    with app.app_context():
        org = Organizacion(
            nombre=f"Test Org B {suffix}",
            plan_tipo='estandar',
            max_usuarios=5,
            max_obras=3,
        )
        db.session.add(org)
        db.session.commit()
        org_id = org.id

        yield org

        try:
            db.session.expire_all()
            obj = db.session.get(Organizacion, org_id)
            if obj:
                db.session.delete(obj)
                db.session.commit()
        except Exception:
            db.session.rollback()


@pytest.fixture(scope='function')
def test_user(app, test_org):
    """Crea un usuario admin de prueba con email único."""
    suffix = _unique_suffix()
    with app.app_context():
        user = Usuario(
            nombre="Test",
            apellido="User",
            email=f"test_{suffix}@example.com",
            organizacion_id=test_org.id,
            rol="administrador",
            role="admin",
            activo=True,
        )
        user.set_password("TestPass123", skip_validation=True)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        yield user

        try:
            db.session.expire_all()
            obj = db.session.get(Usuario, user_id)
            if obj:
                db.session.delete(obj)
                db.session.commit()
        except Exception:
            db.session.rollback()


@pytest.fixture(scope='function')
def test_user_org_b(app, test_org_b):
    """Crea un usuario en la segunda organización con email único."""
    suffix = _unique_suffix()
    with app.app_context():
        user = Usuario(
            nombre="Other",
            apellido="User",
            email=f"other_{suffix}@example.com",
            organizacion_id=test_org_b.id,
            rol="administrador",
            role="admin",
            activo=True,
        )
        user.set_password("OtherPass123", skip_validation=True)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        yield user

        try:
            db.session.expire_all()
            obj = db.session.get(Usuario, user_id)
            if obj:
                db.session.delete(obj)
                db.session.commit()
        except Exception:
            db.session.rollback()


@pytest.fixture(scope='function')
def authenticated_client(client, test_user):
    """Test client autenticado como test_user."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
        sess['_fresh'] = True
    return client


# Markers
def pytest_configure(config):
    config.addinivalue_line("markers", "unit: tests rápidos unitarios")
    config.addinivalue_line("markers", "integration: tests de integración")
    config.addinivalue_line("markers", "slow: tests lentos")
    config.addinivalue_line("markers", "security: tests de seguridad/multi-tenant")
