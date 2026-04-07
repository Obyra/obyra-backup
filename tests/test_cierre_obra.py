"""
Tests del servicio CierreObraService.

Cubre:
- Iniciar cierre con validaciones
- Obra inexistente o de otra org → error
- Obra en estado finalizada/cancelada → error
- Cierre duplicado activo → error
- Confirmar cierre → obra pasa a finalizada
- Anular cierre → obra vuelve a en_curso
- Crear acta de entrega
"""
import uuid
import pytest
from extensions import db
from models import Usuario, Organizacion, Obra, CierreObra, ActaEntrega
from services.cierre_obra_service import CierreObraService, CierreObraError


def _crear_obra(test_org, nombre_suffix=None, estado='en_curso'):
    """Helper para crear una obra de prueba."""
    if nombre_suffix is None:
        nombre_suffix = uuid.uuid4().hex[:8]
    obra = Obra(
        nombre=f"Obra Test {nombre_suffix}",
        cliente="Cliente Test",
        organizacion_id=test_org.id,
        estado=estado,
    )
    db.session.add(obra)
    db.session.commit()
    return obra


@pytest.mark.unit
def test_iniciar_cierre_obra_valida(app, test_org, test_user):
    """Iniciar cierre de una obra válida en curso."""
    with app.app_context():
        obra = _crear_obra(test_org)

        try:
            cierre = CierreObraService.iniciar_cierre(
                obra_id=obra.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
                observaciones='Cierre de prueba',
            )
            assert cierre.id is not None
            assert cierre.estado == 'borrador'
            assert cierre.iniciado_por_id == test_user.id
            assert cierre.observaciones == 'Cierre de prueba'

            # Limpieza
            db.session.delete(cierre)
            db.session.commit()
        finally:
            db.session.delete(obra)
            db.session.commit()


@pytest.mark.unit
def test_iniciar_cierre_obra_inexistente(app, test_org, test_user):
    """Si la obra no existe, debe lanzar error."""
    with app.app_context():
        with pytest.raises(CierreObraError):
            CierreObraService.iniciar_cierre(
                obra_id=999999,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )


@pytest.mark.security
def test_iniciar_cierre_obra_otra_org(app, test_org, test_org_b, test_user):
    """Iniciar cierre de una obra de OTRA organización debe fallar (multi-tenant)."""
    with app.app_context():
        obra_otra_org = _crear_obra(test_org_b)

        try:
            with pytest.raises(CierreObraError):
                CierreObraService.iniciar_cierre(
                    obra_id=obra_otra_org.id,
                    organizacion_id=test_org.id,  # ⚠️ org distinta
                    usuario_id=test_user.id,
                )
        finally:
            db.session.delete(obra_otra_org)
            db.session.commit()


@pytest.mark.unit
def test_iniciar_cierre_obra_finalizada(app, test_org, test_user):
    """No se puede iniciar cierre si la obra ya está finalizada."""
    with app.app_context():
        obra = _crear_obra(test_org, estado='finalizada')

        try:
            with pytest.raises(CierreObraError):
                CierreObraService.iniciar_cierre(
                    obra_id=obra.id,
                    organizacion_id=test_org.id,
                    usuario_id=test_user.id,
                )
        finally:
            db.session.delete(obra)
            db.session.commit()


@pytest.mark.unit
def test_iniciar_cierre_obra_cancelada(app, test_org, test_user):
    """No se puede iniciar cierre si la obra ya está cancelada."""
    with app.app_context():
        obra = _crear_obra(test_org, estado='cancelada')

        try:
            with pytest.raises(CierreObraError):
                CierreObraService.iniciar_cierre(
                    obra_id=obra.id,
                    organizacion_id=test_org.id,
                    usuario_id=test_user.id,
                )
        finally:
            db.session.delete(obra)
            db.session.commit()


@pytest.mark.unit
def test_no_se_pueden_dos_cierres_activos(app, test_org, test_user):
    """No se puede iniciar dos cierres activos sobre la misma obra."""
    with app.app_context():
        obra = _crear_obra(test_org)

        try:
            cierre1 = CierreObraService.iniciar_cierre(
                obra_id=obra.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )

            # Segundo intento debe fallar
            with pytest.raises(CierreObraError):
                CierreObraService.iniciar_cierre(
                    obra_id=obra.id,
                    organizacion_id=test_org.id,
                    usuario_id=test_user.id,
                )

            db.session.delete(cierre1)
            db.session.commit()
        finally:
            db.session.delete(obra)
            db.session.commit()


@pytest.mark.unit
def test_confirmar_cierre_finaliza_obra(app, test_org, test_user):
    """Confirmar el cierre debe cambiar el estado de la obra a 'finalizada'."""
    with app.app_context():
        obra = _crear_obra(test_org)
        try:
            cierre = CierreObraService.iniciar_cierre(
                obra_id=obra.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )

            assert obra.estado == 'en_curso'

            cierre_confirmado = CierreObraService.confirmar_cierre(
                cierre_id=cierre.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )

            db.session.refresh(obra)
            assert cierre_confirmado.estado == 'cerrado'
            assert obra.estado == 'finalizada'
            assert cierre_confirmado.cerrado_por_id == test_user.id

            db.session.delete(cierre)
            db.session.commit()
        finally:
            db.session.delete(obra)
            db.session.commit()


@pytest.mark.unit
def test_anular_cierre_devuelve_obra_a_en_curso(app, test_org, test_user):
    """Anular un cierre debe devolver la obra a en_curso si estaba finalizada."""
    with app.app_context():
        obra = _crear_obra(test_org)
        try:
            cierre = CierreObraService.iniciar_cierre(
                obra_id=obra.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )
            CierreObraService.confirmar_cierre(
                cierre_id=cierre.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )
            db.session.refresh(obra)
            assert obra.estado == 'finalizada'

            CierreObraService.anular_cierre(
                cierre_id=cierre.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
                motivo='Necesitamos correcciones',
            )
            db.session.refresh(obra)
            db.session.refresh(cierre)
            assert cierre.estado == 'anulado'
            assert obra.estado == 'en_curso'

            db.session.delete(cierre)
            db.session.commit()
        finally:
            db.session.delete(obra)
            db.session.commit()


@pytest.mark.unit
def test_anular_sin_motivo_falla(app, test_org, test_user):
    """No se puede anular un cierre sin motivo."""
    with app.app_context():
        obra = _crear_obra(test_org)
        try:
            cierre = CierreObraService.iniciar_cierre(
                obra_id=obra.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )

            with pytest.raises(CierreObraError):
                CierreObraService.anular_cierre(
                    cierre_id=cierre.id,
                    organizacion_id=test_org.id,
                    usuario_id=test_user.id,
                    motivo='',
                )

            db.session.delete(cierre)
            db.session.commit()
        finally:
            db.session.delete(obra)
            db.session.commit()


@pytest.mark.unit
def test_crear_acta_entrega(app, test_org, test_user):
    """Crear acta de entrega vinculada a un cierre en borrador."""
    with app.app_context():
        obra = _crear_obra(test_org)
        try:
            cierre = CierreObraService.iniciar_cierre(
                obra_id=obra.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )

            acta = CierreObraService.crear_acta(
                cierre_id=cierre.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
                datos={
                    'tipo': 'definitiva',
                    'fecha_acta': '2026-04-08',
                    'recibido_por_nombre': 'Juan Pérez',
                    'recibido_por_dni': '12345678',
                    'recibido_por_cargo': 'Propietario',
                    'descripcion': 'Entrega final',
                    'plazo_garantia_meses': '12',
                },
            )

            assert acta.id is not None
            assert acta.cierre_id == cierre.id
            assert acta.recibido_por_nombre == 'Juan Pérez'
            assert acta.tipo == 'definitiva'
            assert acta.plazo_garantia_meses == 12

            db.session.delete(acta)
            db.session.delete(cierre)
            db.session.commit()
        finally:
            db.session.delete(obra)
            db.session.commit()


@pytest.mark.unit
def test_crear_acta_sin_nombre_falla(app, test_org, test_user):
    """No se puede crear acta sin nombre del receptor."""
    with app.app_context():
        obra = _crear_obra(test_org)
        try:
            cierre = CierreObraService.iniciar_cierre(
                obra_id=obra.id,
                organizacion_id=test_org.id,
                usuario_id=test_user.id,
            )

            with pytest.raises(CierreObraError):
                CierreObraService.crear_acta(
                    cierre_id=cierre.id,
                    organizacion_id=test_org.id,
                    usuario_id=test_user.id,
                    datos={
                        'tipo': 'definitiva',
                        'fecha_acta': '2026-04-08',
                        'recibido_por_nombre': '',  # vacío
                    },
                )

            db.session.delete(cierre)
            db.session.commit()
        finally:
            db.session.delete(obra)
            db.session.commit()
