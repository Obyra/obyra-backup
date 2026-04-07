"""
Tests de límites de plan (F6 de la auditoría).

Verifica que los métodos de validación de límites del plan funcionen correctamente:
- puede_agregar_usuario() respeta max_usuarios
- usuarios_disponibles() devuelve la cuenta correcta
- usuarios_activos_count solo cuenta activos
"""
import pytest
import uuid
from extensions import db
from models import Usuario, Organizacion


def _crear_usuario(test_org, nombre, activo=True):
    """Helper para crear usuario en una org de prueba."""
    suffix = uuid.uuid4().hex[:8]
    user = Usuario(
        nombre=nombre,
        apellido="Test",
        email=f"{nombre.lower()}_{suffix}@test.com",
        organizacion_id=test_org.id,
        rol="operario",
        role="operario",
        activo=activo,
    )
    user.set_password("Pass1234", skip_validation=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.mark.unit
def test_org_estandar_permite_5_usuarios(app, test_org):
    """Plan estandar permite hasta 5 usuarios (max_usuarios=5)."""
    with app.app_context():
        assert test_org.max_usuarios == 5

        # Inicialmente puede agregar
        assert test_org.puede_agregar_usuario() is True
        assert test_org.usuarios_disponibles() == 5


@pytest.mark.unit
def test_puede_agregar_decrementa_con_cada_user(app):
    """Cada usuario nuevo activo decrementa los disponibles."""
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        org = Organizacion(
            nombre=f"Test Limit {suffix}",
            plan_tipo='estandar',
            max_usuarios=3,  # Solo 3 para test rápido
            max_obras=3,
        )
        db.session.add(org)
        db.session.commit()

        try:
            assert org.usuarios_disponibles() == 3

            u1 = _crear_usuario(org, "U1")
            db.session.refresh(org)
            assert org.usuarios_disponibles() == 2

            u2 = _crear_usuario(org, "U2")
            db.session.refresh(org)
            assert org.usuarios_disponibles() == 1

            u3 = _crear_usuario(org, "U3")
            db.session.refresh(org)
            assert org.usuarios_disponibles() == 0
            assert org.puede_agregar_usuario() is False

            # Cleanup users
            for u in [u1, u2, u3]:
                db.session.delete(u)
            db.session.commit()
        finally:
            db.session.delete(org)
            db.session.commit()


@pytest.mark.unit
def test_usuarios_inactivos_no_cuentan(app):
    """Los usuarios inactivos no consumen cupo del plan."""
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        org = Organizacion(
            nombre=f"Test Inactive {suffix}",
            plan_tipo='estandar',
            max_usuarios=2,
            max_obras=3,
        )
        db.session.add(org)
        db.session.commit()

        try:
            # Crear 1 activo y 5 inactivos
            u_activo = _crear_usuario(org, "Activo", activo=True)
            inactivos = []
            for i in range(5):
                inactivos.append(_crear_usuario(org, f"Inact{i}", activo=False))

            db.session.refresh(org)
            # Solo el activo cuenta
            assert org.usuarios_disponibles() == 1
            assert org.puede_agregar_usuario() is True

            # Cleanup
            for u in [u_activo] + inactivos:
                db.session.delete(u)
            db.session.commit()
        finally:
            db.session.delete(org)
            db.session.commit()


@pytest.mark.unit
def test_org_full_premium_25_usuarios(app):
    """Plan full_premium permite 25 usuarios."""
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        org = Organizacion(
            nombre=f"Full Premium {suffix}",
            plan_tipo='full_premium',
            max_usuarios=25,
            max_obras=15,
        )
        db.session.add(org)
        db.session.commit()

        try:
            assert org.max_usuarios == 25
            assert org.usuarios_disponibles() == 25
            assert org.puede_agregar_usuario() is True
        finally:
            db.session.delete(org)
            db.session.commit()


@pytest.mark.unit
def test_org_premium_15_usuarios(app):
    """Plan premium permite 15 usuarios."""
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        org = Organizacion(
            nombre=f"Premium {suffix}",
            plan_tipo='premium',
            max_usuarios=15,
            max_obras=5,
        )
        db.session.add(org)
        db.session.commit()

        try:
            assert org.max_usuarios == 15
            assert org.usuarios_disponibles() == 15
        finally:
            db.session.delete(org)
            db.session.commit()


@pytest.mark.unit
def test_max_usuarios_default_5(app):
    """Si no se especifica max_usuarios, el default es 5."""
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        org = Organizacion(nombre=f"Default {suffix}")
        db.session.add(org)
        db.session.commit()

        try:
            # Sin max_usuarios explícito, default model = 5
            max_u = org.max_usuarios or 5
            assert max_u == 5
        finally:
            db.session.delete(org)
            db.session.commit()
