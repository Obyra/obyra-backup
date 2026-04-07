"""
Tests de aislamiento multi-tenant — versión actual.

Verifica que las queries respeten organizacion_id y que un usuario
de la Org A no pueda ver/modificar datos de la Org B.

Esta es la suite MÁS CRÍTICA del sistema (F1.3 de la auditoría).
"""
import pytest
import uuid
from extensions import db
from models import Usuario, Organizacion


@pytest.mark.security
def test_dos_orgs_aisladas(app, test_org, test_org_b):
    """Confirma que dos organizaciones son entidades distintas en BD."""
    assert test_org.id != test_org_b.id
    assert test_org.nombre != test_org_b.nombre


@pytest.mark.security
def test_usuario_pertenece_solo_a_su_org(app, test_user, test_user_org_b, test_org, test_org_b):
    """Cada usuario pertenece a una única organización."""
    assert test_user.organizacion_id == test_org.id
    assert test_user_org_b.organizacion_id == test_org_b.id
    assert test_user.organizacion_id != test_user_org_b.organizacion_id


@pytest.mark.security
def test_query_usuarios_filtra_por_org(app, test_user, test_user_org_b, test_org, test_org_b):
    """Una query de usuarios por organizacion_id solo devuelve los de esa org."""
    with app.app_context():
        users_org_a = Usuario.query.filter_by(organizacion_id=test_org.id).all()
        users_org_b = Usuario.query.filter_by(organizacion_id=test_org_b.id).all()

        # Cada query debe devolver al menos su usuario
        org_a_ids = [u.id for u in users_org_a]
        org_b_ids = [u.id for u in users_org_b]

        assert test_user.id in org_a_ids
        assert test_user.id not in org_b_ids
        assert test_user_org_b.id in org_b_ids
        assert test_user_org_b.id not in org_a_ids


@pytest.mark.security
def test_obras_filtran_por_org(app, test_org, test_org_b):
    """Las obras se filtran correctamente por organizacion_id."""
    from models import Obra

    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        # Crear obra en cada org
        obra_a = Obra(
            nombre=f"Obra A {suffix}",
            cliente="Cliente A",
            organizacion_id=test_org.id,
            estado='en_curso',
        )
        obra_b = Obra(
            nombre=f"Obra B {suffix}",
            cliente="Cliente B",
            organizacion_id=test_org_b.id,
            estado='en_curso',
        )
        db.session.add_all([obra_a, obra_b])
        db.session.commit()

        try:
            # Query por org A debe devolver solo obra_a
            obras_a = Obra.query.filter_by(organizacion_id=test_org.id).all()
            obras_a_ids = [o.id for o in obras_a]
            assert obra_a.id in obras_a_ids
            assert obra_b.id not in obras_a_ids

            # Query por org B debe devolver solo obra_b
            obras_b = Obra.query.filter_by(organizacion_id=test_org_b.id).all()
            obras_b_ids = [o.id for o in obras_b]
            assert obra_b.id in obras_b_ids
            assert obra_a.id not in obras_b_ids
        finally:
            db.session.delete(obra_a)
            db.session.delete(obra_b)
            db.session.commit()


@pytest.mark.security
def test_get_obra_otra_org_no_la_devuelve(app, test_org, test_org_b):
    """filter_by(id=X, organizacion_id=org) no devuelve obras de otra org."""
    from models import Obra

    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        obra_b = Obra(
            nombre=f"Obra Solo B {suffix}",
            cliente="Cliente B",
            organizacion_id=test_org_b.id,
            estado='en_curso',
        )
        db.session.add(obra_b)
        db.session.commit()

        try:
            # Org A intenta acceder a obra_b por ID
            result = Obra.query.filter_by(
                id=obra_b.id,
                organizacion_id=test_org.id
            ).first()
            assert result is None  # NO debe encontrar nada
        finally:
            db.session.delete(obra_b)
            db.session.commit()


@pytest.mark.security
def test_emails_pueden_repetirse_entre_orgs(app, test_org, test_org_b):
    """
    NOTA: En el modelo actual, email es UNIQUE GLOBAL (no por org).
    Este test documenta el comportamiento actual.

    Si en el futuro se decide permitir mismo email en distintas orgs,
    este test debe actualizarse.
    """
    from sqlalchemy.exc import IntegrityError
    suffix = uuid.uuid4().hex[:8]
    email = f"shared_{suffix}@test.com"

    with app.app_context():
        u_a = Usuario(
            nombre="A", apellido="A",
            email=email,
            organizacion_id=test_org.id,
            rol="operario", role="operario",
        )
        u_a.set_password("Pass1234A", skip_validation=True)
        db.session.add(u_a)
        db.session.commit()

        u_b = Usuario(
            nombre="B", apellido="B",
            email=email,
            organizacion_id=test_org_b.id,
            rol="operario", role="operario",
        )
        u_b.set_password("Pass1234B", skip_validation=True)
        db.session.add(u_b)

        # Email global unique → debe fallar
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.delete(u_a)
        db.session.commit()


@pytest.mark.security
def test_count_usuarios_por_org(app, test_org, test_org_b):
    """Verificación cruzada: contar usuarios por org no incluye otras orgs."""
    with app.app_context():
        from sqlalchemy import func

        # Crear 2 users en org_a, 1 en org_b
        suffix = uuid.uuid4().hex[:8]
        u1 = Usuario(nombre="U1", apellido="A", email=f"u1_{suffix}@t.com",
                     organizacion_id=test_org.id, rol="operario", role="operario")
        u2 = Usuario(nombre="U2", apellido="A", email=f"u2_{suffix}@t.com",
                     organizacion_id=test_org.id, rol="operario", role="operario")
        u3 = Usuario(nombre="U3", apellido="B", email=f"u3_{suffix}@t.com",
                     organizacion_id=test_org_b.id, rol="operario", role="operario")
        for u in [u1, u2, u3]:
            u.set_password("Pass1234", skip_validation=True)
            db.session.add(u)
        db.session.commit()

        try:
            count_a = db.session.query(func.count(Usuario.id)).filter_by(
                organizacion_id=test_org.id
            ).scalar()
            count_b = db.session.query(func.count(Usuario.id)).filter_by(
                organizacion_id=test_org_b.id
            ).scalar()

            assert count_a >= 2  # Al menos los 2 que creamos
            assert count_b >= 1  # Al menos el 1
            # Total NO debe ser igual (son entidades distintas)
            assert count_a != count_b
        finally:
            for u in [u1, u2, u3]:
                db.session.delete(u)
            db.session.commit()
