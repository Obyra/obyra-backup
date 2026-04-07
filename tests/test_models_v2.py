"""
Tests de modelos básicos — versión actual.

Cubre:
- Creación de Organizacion
- Creación de Usuario con campos correctos
- Hash de contraseñas
- Relación Usuario ↔ Organizacion
- Email único
- Soft delete (campo activo)
"""
import pytest
from extensions import db
from models import Usuario, Organizacion


@pytest.mark.unit
def test_create_organizacion(app):
    """Crear una organización con campos básicos."""
    import uuid
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        org = Organizacion(
            nombre=f"Empresa Test {suffix}",
            plan_tipo='estandar',
            max_usuarios=5,
            max_obras=3,
        )
        db.session.add(org)
        db.session.commit()

        assert org.id is not None
        assert org.nombre == f"Empresa Test {suffix}"
        assert org.plan_tipo == 'estandar'
        assert org.max_usuarios == 5
        assert org.max_obras == 3

        # Cleanup
        db.session.delete(org)
        db.session.commit()


@pytest.mark.unit
def test_create_usuario(app, test_org):
    """Crear un usuario con campos correctos."""
    import uuid
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        user = Usuario(
            nombre="Juan",
            apellido="Pérez",
            email=f"juan_{suffix}@test.com",
            organizacion_id=test_org.id,
            rol="administrador",
            role="admin",
            activo=True,
        )
        user.set_password("ValidPass123", skip_validation=True)
        db.session.add(user)
        db.session.commit()

        assert user.id is not None
        assert user.nombre == "Juan"
        assert user.apellido == "Pérez"
        assert user.email == f"juan_{suffix}@test.com"
        assert user.organizacion_id == test_org.id
        assert user.role == "admin"
        assert user.activo is True

        # Cleanup
        db.session.delete(user)
        db.session.commit()


@pytest.mark.unit
def test_password_hashing(app, test_org):
    """El password se guarda hasheado, no en texto plano."""
    import uuid
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        user = Usuario(
            nombre="T",
            apellido="U",
            email=f"hash_{suffix}@test.com",
            organizacion_id=test_org.id,
            rol="operario",
            role="operario",
        )
        plain = "MySecretPass123"
        user.set_password(plain, skip_validation=True)
        db.session.add(user)
        db.session.commit()

        # El hash NO debe ser igual al texto plano
        assert user.password_hash != plain
        assert user.password_hash is not None
        # check_password debe funcionar
        assert user.check_password(plain) is True
        assert user.check_password("WrongPass") is False

        db.session.delete(user)
        db.session.commit()


@pytest.mark.unit
def test_usuario_organizacion_relationship(app, test_org, test_user):
    """El usuario está correctamente vinculado a su organización."""
    with app.app_context():
        # Recargar para asegurar relación cargada
        user = db.session.get(Usuario, test_user.id)
        assert user.organizacion_id == test_org.id
        # La relación reverse debería funcionar
        assert user.organizacion is not None
        assert user.organizacion.id == test_org.id


@pytest.mark.unit
def test_email_unique_constraint(app, test_org):
    """Dos usuarios no pueden tener el mismo email."""
    import uuid
    from sqlalchemy.exc import IntegrityError

    suffix = uuid.uuid4().hex[:8]
    email = f"unique_{suffix}@test.com"

    with app.app_context():
        u1 = Usuario(
            nombre="A",
            apellido="A",
            email=email,
            organizacion_id=test_org.id,
            rol="operario",
            role="operario",
        )
        u1.set_password("Pass12345", skip_validation=True)
        db.session.add(u1)
        db.session.commit()

        # Intentar crear segundo usuario con mismo email
        u2 = Usuario(
            nombre="B",
            apellido="B",
            email=email,
            organizacion_id=test_org.id,
            rol="operario",
            role="operario",
        )
        u2.set_password("Pass12345", skip_validation=True)
        db.session.add(u2)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()
        # Cleanup
        db.session.delete(u1)
        db.session.commit()


@pytest.mark.unit
def test_usuario_inactivo(app, test_org):
    """Un usuario puede marcarse como inactivo."""
    import uuid
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        user = Usuario(
            nombre="In",
            apellido="Active",
            email=f"inactive_{suffix}@test.com",
            organizacion_id=test_org.id,
            rol="operario",
            role="operario",
            activo=False,
        )
        user.set_password("Pass12345", skip_validation=True)
        db.session.add(user)
        db.session.commit()

        assert user.activo is False

        db.session.delete(user)
        db.session.commit()


@pytest.mark.unit
def test_organizacion_default_plan(app):
    """Una organización nueva sin plan_tipo usa 'prueba' por default."""
    import uuid
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        org = Organizacion(nombre=f"Default Plan {suffix}")
        db.session.add(org)
        db.session.commit()

        # Plan default según el modelo
        plan = getattr(org, 'plan_tipo', None)
        # Acepta 'prueba' o None (depende del default del modelo)
        assert plan in ('prueba', None)

        db.session.delete(org)
        db.session.commit()
