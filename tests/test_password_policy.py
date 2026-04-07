"""
Tests de política de contraseñas (F2.4 de la auditoría).

Verifica que validar_password() rechace contraseñas débiles:
- Menos de 8 caracteres
- Sin mayúscula
- Sin minúscula
- Sin número
- Vacía o None
"""
import pytest
from models import Usuario


@pytest.mark.unit
def test_password_valida():
    """Una contraseña que cumple todos los requisitos pasa."""
    valida, msg = Usuario.validar_password("ValidPass123")
    assert valida is True
    assert msg == ''


@pytest.mark.unit
def test_password_vacia_falla():
    """Contraseña vacía o None debe fallar."""
    for invalid in ['', None]:
        valida, msg = Usuario.validar_password(invalid)
        assert valida is False
        assert 'vacía' in msg.lower() or 'vacia' in msg.lower()


@pytest.mark.unit
def test_password_corta_falla():
    """Contraseñas con menos de 8 caracteres deben fallar."""
    for short in ['Abc12', 'A1b2c3', '1234567']:
        valida, msg = Usuario.validar_password(short)
        assert valida is False
        assert '8' in msg


@pytest.mark.unit
def test_password_sin_mayuscula_falla():
    """Contraseña sin mayúsculas debe fallar."""
    valida, msg = Usuario.validar_password("validpass123")
    assert valida is False
    assert 'mayúscula' in msg.lower() or 'mayuscula' in msg.lower()


@pytest.mark.unit
def test_password_sin_minuscula_falla():
    """Contraseña sin minúsculas debe fallar."""
    valida, msg = Usuario.validar_password("VALIDPASS123")
    assert valida is False
    assert 'minúscula' in msg.lower() or 'minuscula' in msg.lower()


@pytest.mark.unit
def test_password_sin_numero_falla():
    """Contraseña sin números debe fallar."""
    valida, msg = Usuario.validar_password("ValidPassword")
    assert valida is False
    assert 'número' in msg.lower() or 'numero' in msg.lower()


@pytest.mark.unit
def test_password_minimo_8_chars():
    """Una contraseña de exactamente 8 caracteres válida pasa."""
    valida, msg = Usuario.validar_password("Pass1234")
    assert valida is True


@pytest.mark.unit
def test_set_password_valida_por_default(app, test_org):
    """set_password() valida por default — rechaza contraseñas débiles."""
    from extensions import db
    import uuid

    with app.app_context():
        user = Usuario(
            nombre="T", apellido="U",
            email=f"test_{uuid.uuid4().hex[:8]}@test.com",
            organizacion_id=test_org.id,
            rol="operario", role="operario",
        )
        # Sin skip_validation, debe fallar con password débil
        with pytest.raises(ValueError):
            user.set_password("weak")  # muy corta y sin requisitos


@pytest.mark.unit
def test_set_password_skip_validation(app, test_org):
    """set_password(skip_validation=True) permite cualquier contraseña.
    Necesario para migrar usuarios viejos con passwords débiles.
    """
    from extensions import db
    import uuid

    with app.app_context():
        user = Usuario(
            nombre="T", apellido="U",
            email=f"test_{uuid.uuid4().hex[:8]}@test.com",
            organizacion_id=test_org.id,
            rol="operario", role="operario",
        )
        # Con skip_validation, no debe fallar
        user.set_password("oldweakpass", skip_validation=True)
        assert user.password_hash is not None
        assert user.check_password("oldweakpass") is True
