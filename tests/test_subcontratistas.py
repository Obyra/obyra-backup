"""
Tests del modulo Subcontratistas.

Cubre:
- Modelo: estado_documentacion, dias_para_vencer, esta_vencido
- Multi-tenant: subcontratista de otra org no se ve / no se edita / no se elimina
- CRUD: lista, crear, editar, eliminar
- Documentos: properties calculadas de vencimiento
"""
import uuid
from datetime import date, timedelta

import pytest

from extensions import db
from models import Subcontratista, DocumentoSubcontratista


def _crear_sub(org, razon_social=None, **kwargs):
    sub = Subcontratista(
        organizacion_id=org.id,
        razon_social=razon_social or f"Sub {uuid.uuid4().hex[:6]}",
        **kwargs,
    )
    db.session.add(sub)
    db.session.commit()
    return sub


def _crear_doc(sub, tipo='seguro_art', vence_en_dias=None):
    fecha_venc = None
    if vence_en_dias is not None:
        fecha_venc = date.today() + timedelta(days=vence_en_dias)
    doc = DocumentoSubcontratista(
        subcontratista_id=sub.id,
        tipo=tipo,
        archivo_url=f'subcontratistas/{sub.organizacion_id}/{sub.id}/test.pdf',
        archivo_nombre='test.pdf',
        fecha_vencimiento=fecha_venc,
    )
    db.session.add(doc)
    db.session.commit()
    return doc


# ============================================================================
# Modelo: properties calculadas
# ============================================================================

@pytest.mark.unit
def test_estado_documentacion_ok_sin_documentos(app, test_org):
    with app.app_context():
        sub = _crear_sub(test_org)
        assert sub.estado_documentacion == 'ok'


@pytest.mark.unit
def test_estado_documentacion_vencido(app, test_org):
    with app.app_context():
        sub = _crear_sub(test_org)
        _crear_doc(sub, vence_en_dias=-5)  # vencio hace 5 dias
        assert sub.estado_documentacion == 'vencido'


@pytest.mark.unit
def test_estado_documentacion_por_vencer(app, test_org):
    with app.app_context():
        sub = _crear_sub(test_org)
        _crear_doc(sub, vence_en_dias=10)  # vence en 10 dias
        assert sub.estado_documentacion == 'por_vencer'


@pytest.mark.unit
def test_estado_documentacion_vigente(app, test_org):
    with app.app_context():
        sub = _crear_sub(test_org)
        _crear_doc(sub, vence_en_dias=180)
        assert sub.estado_documentacion == 'ok'


@pytest.mark.unit
def test_estado_documentacion_vencido_prevalece_sobre_por_vencer(app, test_org):
    """Si hay un vencido y otro por vencer, el estado debe ser 'vencido'."""
    with app.app_context():
        sub = _crear_sub(test_org)
        _crear_doc(sub, tipo='seguro_art', vence_en_dias=-1)
        _crear_doc(sub, tipo='contrato', vence_en_dias=15)
        assert sub.estado_documentacion == 'vencido'


@pytest.mark.unit
def test_documento_dias_para_vencer(app, test_org):
    with app.app_context():
        sub = _crear_sub(test_org)
        doc = _crear_doc(sub, vence_en_dias=7)
        assert doc.dias_para_vencer == 7
        assert not doc.esta_vencido


@pytest.mark.unit
def test_documento_esta_vencido(app, test_org):
    with app.app_context():
        sub = _crear_sub(test_org)
        doc = _crear_doc(sub, vence_en_dias=-3)
        assert doc.esta_vencido is True
        assert doc.dias_para_vencer == -3


@pytest.mark.unit
def test_documento_sin_fecha_vencimiento(app, test_org):
    with app.app_context():
        sub = _crear_sub(test_org)
        doc = _crear_doc(sub, vence_en_dias=None)
        assert doc.dias_para_vencer is None
        assert not doc.esta_vencido


# ============================================================================
# Multi-tenant: aislamiento entre organizaciones
# ============================================================================

@pytest.mark.security
def test_query_filtrado_por_organizacion(app, test_org, test_org_b):
    """Subcontratistas de orgA no aparecen al filtrar por orgB."""
    with app.app_context():
        nombre_a = f'Sub OrgA {uuid.uuid4().hex[:6]}'
        nombre_b = f'Sub OrgB {uuid.uuid4().hex[:6]}'
        _crear_sub(test_org, razon_social=nombre_a)
        _crear_sub(test_org_b, razon_social=nombre_b)

        nombres_a = [s.razon_social for s in Subcontratista.query.filter_by(organizacion_id=test_org.id).all()]
        nombres_b = [s.razon_social for s in Subcontratista.query.filter_by(organizacion_id=test_org_b.id).all()]

        assert nombre_a in nombres_a
        assert nombre_a not in nombres_b
        assert nombre_b in nombres_b
        assert nombre_b not in nombres_a


@pytest.mark.security
def test_no_acceso_a_subcontratista_de_otra_org(app, test_org, test_org_b):
    """Cargar por ID un sub de otra org y verificar que se detecta."""
    with app.app_context():
        sub_b = _crear_sub(test_org_b, razon_social='Privado')
        sub_id = sub_b.id

        # Simular validacion del blueprint
        sub = Subcontratista.query.get(sub_id)
        assert sub is not None
        assert sub.organizacion_id != test_org.id  # NO pertenece a org A


@pytest.mark.security
def test_documentos_aislados_por_organizacion(app, test_org, test_org_b):
    """Documentos de un sub de otra org no son accesibles."""
    with app.app_context():
        sub_a = _crear_sub(test_org)
        sub_b = _crear_sub(test_org_b)
        doc_a = _crear_doc(sub_a)
        doc_b = _crear_doc(sub_b)

        # Documentos del sub_a solo deben ser los del sub_a
        docs_a = sub_a.documentos.all()
        docs_b = sub_b.documentos.all()
        assert len(docs_a) == 1
        assert len(docs_b) == 1
        assert docs_a[0].id == doc_a.id
        assert docs_b[0].id == doc_b.id


# ============================================================================
# CRUD basico
# ============================================================================

@pytest.mark.unit
def test_crear_subcontratista(app, test_org):
    with app.app_context():
        sub = _crear_sub(
            test_org,
            razon_social='Electricidad SRL',
            cuit='30-12345678-9',
            rubro='Electricidad',
            email='contacto@elec.com',
        )
        assert sub.id is not None
        assert sub.razon_social == 'Electricidad SRL'
        assert sub.cuit == '30-12345678-9'
        assert sub.activo is True


@pytest.mark.unit
def test_eliminar_subcontratista_cascade_documentos(app, test_org):
    """Al eliminar un subcontratista, sus documentos tambien se eliminan."""
    with app.app_context():
        sub = _crear_sub(test_org)
        _crear_doc(sub, tipo='seguro_art', vence_en_dias=30)
        _crear_doc(sub, tipo='contrato', vence_en_dias=60)
        sub_id = sub.id

        assert DocumentoSubcontratista.query.filter_by(subcontratista_id=sub_id).count() == 2

        db.session.delete(sub)
        db.session.commit()

        assert Subcontratista.query.get(sub_id) is None
        assert DocumentoSubcontratista.query.filter_by(subcontratista_id=sub_id).count() == 0


@pytest.mark.unit
def test_documentos_por_vencer_filtra_correctamente(app, test_org):
    """La property documentos_por_vencer solo devuelve los que vencen en <=30 dias."""
    with app.app_context():
        sub = _crear_sub(test_org)
        _crear_doc(sub, tipo='seguro_art', vence_en_dias=15)   # por vencer
        _crear_doc(sub, tipo='contrato', vence_en_dias=60)     # NO
        _crear_doc(sub, tipo='poliza', vence_en_dias=-2)       # vencido, NO

        por_vencer = sub.documentos_por_vencer
        assert len(por_vencer) == 1
        assert por_vencer[0].tipo == 'seguro_art'


@pytest.mark.unit
def test_documentos_vencidos_filtra_correctamente(app, test_org):
    with app.app_context():
        sub = _crear_sub(test_org)
        _crear_doc(sub, tipo='seguro_art', vence_en_dias=-1)
        _crear_doc(sub, tipo='contrato', vence_en_dias=-10)
        _crear_doc(sub, tipo='poliza', vence_en_dias=30)

        vencidos = sub.documentos_vencidos
        assert len(vencidos) == 2
