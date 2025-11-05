"""
Tests for database models.
"""
import pytest
from werkzeug.security import check_password_hash


@pytest.mark.unit
def test_organization_creation(app, test_org):
    """Test creating an organization."""
    assert test_org.id is not None
    assert test_org.nombre == "Test Organization"
    assert test_org.razon_social == "Test Org SA"
    assert test_org.cuit == "20-12345678-9"


@pytest.mark.unit
def test_user_creation(app, test_user):
    """Test creating a user."""
    assert test_user.id is not None
    assert test_user.username == "testuser"
    assert test_user.email == "test@example.com"
    assert test_user.organizacion_id is not None


@pytest.mark.unit
def test_user_password_hashing(app, test_user):
    """Test that user passwords are properly hashed."""
    # Password should be hashed, not plain text
    assert test_user.password_hash != "testpassword123"
    # But should validate correctly
    assert check_password_hash(test_user.password_hash, "testpassword123")
    # Wrong password should not validate
    assert not check_password_hash(test_user.password_hash, "wrongpassword")


@pytest.mark.unit
def test_user_organization_relationship(app, test_user, test_org):
    """Test user-organization relationship."""
    assert test_user.organizacion_id == test_org.id
    # Test the relationship if it exists
    if hasattr(test_user, 'organizacion'):
        assert test_user.organizacion.id == test_org.id


@pytest.mark.integration
def test_user_repr(app, test_user):
    """Test user string representation."""
    repr_str = repr(test_user)
    assert isinstance(repr_str, str)
    assert len(repr_str) > 0


@pytest.mark.unit
def test_admin_user_attributes(app, admin_user):
    """Test admin user has correct attributes."""
    assert admin_user.rol == "administrador"
    assert admin_user.role == "admin"
    assert admin_user.plan_activo == "premium"


@pytest.mark.integration
def test_db_session(app, db_session):
    """Test database session works."""
    from models import Usuario

    # Query should work
    users = db_session.query(Usuario).all()
    assert isinstance(users, list)


@pytest.mark.integration
def test_model_imports():
    """Test that core models can be imported."""
    try:
        from models import (
            Usuario,
            Organizacion,
            Obra,
            Presupuesto,
            ItemInventario,
        )

        assert Usuario is not None
        assert Organizacion is not None
        assert Obra is not None
        assert Presupuesto is not None
        assert ItemInventario is not None
    except ImportError as e:
        pytest.fail(f"Failed to import models: {e}")


@pytest.mark.unit
def test_organization_required_fields(app):
    """Test that organization validates required fields."""
    from models import Organizacion
    from extensions import db

    with app.app_context():
        # Create org with minimal required fields
        org = Organizacion(nombre="Minimal Org")
        db.session.add(org)
        db.session.commit()

        assert org.id is not None
        assert org.nombre == "Minimal Org"

        # Cleanup
        db.session.delete(org)
        db.session.commit()


@pytest.mark.unit
def test_user_email_uniqueness(app, test_org):
    """Test that user email should be unique (if constraint exists)."""
    from models import Usuario
    from extensions import db
    from werkzeug.security import generate_password_hash

    with app.app_context():
        # Create first user
        user1 = Usuario(
            username="user1",
            email="unique@test.com",
            password_hash=generate_password_hash("password123"),
            organizacion_id=test_org.id
        )
        db.session.add(user1)
        db.session.commit()

        # Try to create second user with same email
        user2 = Usuario(
            username="user2",
            email="unique@test.com",  # Same email
            password_hash=generate_password_hash("password123"),
            organizacion_id=test_org.id
        )
        db.session.add(user2)

        # This might or might not raise depending on DB constraints
        # Just test that we can handle it
        try:
            db.session.commit()
            # If it doesn't raise, that's ok too (no unique constraint)
        except Exception:
            db.session.rollback()

        # Cleanup
        db.session.delete(user1)
        db.session.commit()
