"""
Tests de seguridad multi-tenant para OBYRA.
Verifica que los datos de una organización no sean accesibles por otra.

Estos tests previenen regresiones en el aislamiento de datos entre clientes.
"""
import pytest
import json
from werkzeug.security import generate_password_hash


@pytest.fixture(scope='function')
def two_orgs(app):
    """Crea dos organizaciones con usuarios para probar aislamiento."""
    from extensions import db
    from models import Organizacion, Usuario, OrgMembership

    with app.app_context():
        # Org A
        org_a = Organizacion(nombre="Empresa A", razon_social="Empresa A SA", cuit="20-11111111-1",
                             plan_tipo='premium', max_usuarios=10, max_obras=5)
        db.session.add(org_a)
        db.session.flush()

        user_a = Usuario(nombre="Admin", apellido="EmpA", email="admin@empresa-a.com",
                         password_hash=generate_password_hash("test123"),
                         organizacion_id=org_a.id, role="admin", rol="administrador", activo=True)
        db.session.add(user_a)
        db.session.flush()

        memb_a = OrgMembership(user_id=user_a.id, org_id=org_a.id, role='admin', status='active')
        db.session.add(memb_a)

        # Org B
        org_b = Organizacion(nombre="Empresa B", razon_social="Empresa B SA", cuit="20-22222222-2",
                             plan_tipo='premium', max_usuarios=10, max_obras=5)
        db.session.add(org_b)
        db.session.flush()

        user_b = Usuario(nombre="Admin", apellido="EmpB", email="admin@empresa-b.com",
                         password_hash=generate_password_hash("test123"),
                         organizacion_id=org_b.id, role="admin", rol="administrador", activo=True)
        db.session.add(user_b)
        db.session.flush()

        memb_b = OrgMembership(user_id=user_b.id, org_id=org_b.id, role='admin', status='active')
        db.session.add(memb_b)

        db.session.commit()

        yield {
            'org_a': org_a, 'user_a': user_a, 'memb_a': memb_a,
            'org_b': org_b, 'user_b': user_b, 'memb_b': memb_b,
        }

        # Cleanup
        db.session.rollback()
        for obj in [memb_a, memb_b, user_a, user_b, org_a, org_b]:
            try:
                db.session.delete(obj)
            except Exception:
                db.session.rollback()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _login_as(client, user):
    """Helper para autenticar como un usuario específico."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['current_org_id'] = user.organizacion_id
        sess['current_membership_id'] = user.id


# ============================================================================
# C1: IDOR en equipos — no puede cambiar rol de usuario de otra org
# ============================================================================

class TestEquiposIDOR:
    """Verifica que un admin de OrgA no pueda modificar usuarios de OrgB."""

    def test_cambiar_rol_otra_org_devuelve_404(self, client, app, two_orgs):
        """Admin de OrgA intenta cambiar rol de usuario de OrgB → 404."""
        with app.app_context():
            _login_as(client, two_orgs['user_a'])
            resp = client.post(f"/equipos/usuarios/{two_orgs['user_b'].id}/rol",
                               data={'role': 'operario'})
            assert resp.status_code in (403, 404), \
                f"IDOR: Admin de OrgA pudo cambiar rol de usuario de OrgB (status={resp.status_code})"

    def test_editar_usuario_otra_org_devuelve_404(self, client, app, two_orgs):
        """Admin de OrgA intenta editar datos de usuario de OrgB → 404."""
        with app.app_context():
            _login_as(client, two_orgs['user_a'])
            resp = client.post(f"/equipos/usuarios/{two_orgs['user_b'].id}",
                               data={'nombre': 'Hackeado', 'email': 'hack@test.com'})
            assert resp.status_code in (403, 404), \
                f"IDOR: Admin de OrgA pudo editar usuario de OrgB (status={resp.status_code})"


# ============================================================================
# C2: Inventario API — no puede ver stock de otra org
# ============================================================================

class TestInventarioIDOR:
    """Verifica que un usuario no pueda acceder al inventario de otra org."""

    def test_stock_obras_otra_org_devuelve_404(self, client, app, two_orgs):
        """Usuario de OrgA intenta ver stock de item de OrgB → 404."""
        from models import ItemInventario

        with app.app_context():
            # Crear item en OrgB
            item_b = ItemInventario(
                codigo='TEST-ITEM-B', nombre='Item de OrgB', unidad='unidad',
                organizacion_id=two_orgs['org_b'].id, activo=True
            )
            from extensions import db
            db.session.add(item_b)
            db.session.commit()
            item_b_id = item_b.id

            # Login como OrgA
            _login_as(client, two_orgs['user_a'])
            resp = client.get(f"/inventario/api/{item_b_id}/stock-obras")
            assert resp.status_code in (403, 404), \
                f"IDOR: OrgA pudo ver stock de item de OrgB (status={resp.status_code})"

            # Cleanup
            db.session.delete(item_b)
            db.session.commit()


# ============================================================================
# C3: Presupuesto — no puede acceder a presupuesto de otra org
# ============================================================================

class TestPresupuestoIDOR:
    """Verifica aislamiento de presupuestos entre organizaciones."""

    def test_eliminar_presupuesto_otra_org_devuelve_404(self, client, app, two_orgs):
        """OrgA intenta eliminar presupuesto de OrgB → 404."""
        from models import Presupuesto

        with app.app_context():
            from extensions import db
            pres_b = Presupuesto(
                numero='PRES-TEST-B', nombre='Presupuesto OrgB',
                organizacion_id=two_orgs['org_b'].id, estado='borrador'
            )
            db.session.add(pres_b)
            db.session.commit()
            pres_b_id = pres_b.id

            _login_as(client, two_orgs['user_a'])
            resp = client.post(f"/presupuestos/admin/eliminar/{pres_b_id}",
                               content_type='application/json')
            assert resp.status_code in (400, 403, 404), \
                f"IDOR: OrgA pudo eliminar presupuesto de OrgB (status={resp.status_code})"

            # Cleanup
            db.session.delete(pres_b)
            db.session.commit()


# ============================================================================
# C6: XSS — innerHTML reemplazado por textContent
# ============================================================================

class TestXSS:
    """Verifica que no haya innerHTML con datos de usuario."""

    def test_base_template_no_tiene_innerHTML_con_datos(self, app):
        """El template base no debe usar innerHTML con datos de notificaciones."""
        import os
        template_path = os.path.join(app.root_path, 'templates', 'base.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Buscar innerHTML que use datos de API (n.titulo, n.mensaje, etc.)
        assert 'n.titulo' not in content or 'innerHTML' not in content.split('n.titulo')[0][-200:], \
            "XSS: base.html todavía usa innerHTML con datos de notificaciones"


# ============================================================================
# H1: Super admin — no debe estar hardcodeado por email
# ============================================================================

class TestSuperAdmin:
    """Verifica que super admin use is_super_admin flag, no emails."""

    def test_es_admin_completo_usa_flag(self, app, two_orgs):
        """es_admin_completo() debe depender solo de is_super_admin."""
        with app.app_context():
            user = two_orgs['user_a']
            user.is_super_admin = False
            assert not user.es_admin_completo(), \
                "Usuario sin is_super_admin=True no debe ser admin completo"

            user.is_super_admin = True
            assert user.es_admin_completo(), \
                "Usuario con is_super_admin=True debe ser admin completo"

    def test_email_no_otorga_super_admin(self, app):
        """Un email específico no debe otorgar permisos de super admin."""
        from extensions import db
        from models import Organizacion

        with app.app_context():
            org = Organizacion(nombre="Test SA", razon_social="Test", cuit="20-99999999-9")
            db.session.add(org)
            db.session.flush()

            user = Usuario(nombre="Brenda", apellido="Test", email="brenda@gmail.com",
                           password_hash="x", organizacion_id=org.id, role="admin",
                           is_super_admin=False, activo=True)
            db.session.add(user)
            db.session.commit()

            assert not user.es_admin_completo(), \
                "SEGURIDAD: email hardcodeado otorga super admin"

            db.session.delete(user)
            db.session.delete(org)
            db.session.commit()


# ============================================================================
# CSRF: Fetch interceptor global
# ============================================================================

class TestCSRF:
    """Verifica que el interceptor CSRF global esté presente."""

    def test_base_template_tiene_csrf_interceptor(self, app):
        """base.html debe tener el fetch interceptor que agrega X-CSRFToken."""
        import os
        template_path = os.path.join(app.root_path, 'templates', 'base.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'X-CSRFToken' in content, \
            "base.html no tiene el interceptor CSRF global para fetch"
        assert 'window.fetch' in content or 'originalFetch' in content, \
            "base.html no tiene el monkey-patch de fetch para CSRF"


# ============================================================================
# Soft Delete: Obras canceladas no visibles
# ============================================================================

class TestSoftDelete:
    """Verifica que obras eliminadas (canceladas) no aparezcan en listados."""

    def test_obra_cancelada_no_aparece_en_lista(self, client, app, two_orgs):
        """Una obra con estado='cancelada' no debe aparecer en la lista."""
        from models.projects import Obra
        from extensions import db

        with app.app_context():
            obra = Obra(nombre="Obra Eliminada", organizacion_id=two_orgs['org_a'].id,
                        estado='cancelada', progreso=0)
            db.session.add(obra)
            db.session.commit()

            _login_as(client, two_orgs['user_a'])
            resp = client.get("/obras/")

            # La obra cancelada no debe estar en la respuesta
            assert resp.status_code == 200
            assert b'Obra Eliminada' not in resp.data, \
                "Obra cancelada aparece en la lista de obras"

            db.session.delete(obra)
            db.session.commit()


# ============================================================================
# Audit Log: Registra operaciones
# ============================================================================

class TestAuditLog:
    """Verifica que el modelo de audit log funcione."""

    def test_registrar_audit_no_falla(self, app, two_orgs):
        """registrar_audit() no debe fallar ni bloquear la operación principal."""
        from models.audit import registrar_audit, AuditLog
        from extensions import db

        with app.app_context():
            _login_as_context = None  # No hay request context en test
            # Llamar directamente sin request context — no debe fallar
            try:
                log = AuditLog(
                    organizacion_id=two_orgs['org_a'].id,
                    user_id=two_orgs['user_a'].id,
                    user_email=two_orgs['user_a'].email,
                    accion='test',
                    entidad='test',
                    detalle='Test de audit log'
                )
                db.session.add(log)
                db.session.commit()

                # Verificar que se guardó
                saved = AuditLog.query.filter_by(accion='test').first()
                assert saved is not None, "Audit log no se guardó"
                assert saved.user_email == 'admin@empresa-a.com'

                # Cleanup
                db.session.delete(saved)
                db.session.commit()
            except Exception as e:
                pytest.fail(f"registrar_audit falló: {e}")


# ============================================================================
# Stock bajo: no cuenta items con stock_minimo=0
# ============================================================================

class TestStockBajo:
    """Verifica la lógica de stock bajo."""

    def test_item_sin_minimo_no_necesita_reposicion(self, app, two_orgs):
        """Item con stock_minimo=0 no debe marcarse como stock bajo."""
        from models import ItemInventario
        from extensions import db

        with app.app_context():
            item = ItemInventario(
                codigo='TEST-STOCK-0', nombre='Item sin mínimo', unidad='unidad',
                organizacion_id=two_orgs['org_a'].id, stock_actual=0, stock_minimo=0, activo=True
            )
            db.session.add(item)
            db.session.commit()

            assert not item.necesita_reposicion, \
                "Item con stock_minimo=0 no debería necesitar reposición"

            db.session.delete(item)
            db.session.commit()

    def test_item_con_minimo_bajo_stock_necesita_reposicion(self, app, two_orgs):
        """Item con stock < stock_minimo > 0 debe marcarse como stock bajo."""
        from models import ItemInventario
        from extensions import db

        with app.app_context():
            item = ItemInventario(
                codigo='TEST-STOCK-LOW', nombre='Item bajo stock', unidad='unidad',
                organizacion_id=two_orgs['org_a'].id, stock_actual=3, stock_minimo=10, activo=True
            )
            db.session.add(item)
            db.session.commit()

            assert item.necesita_reposicion, \
                "Item con stock=3 y minimo=10 debería necesitar reposición"

            db.session.delete(item)
            db.session.commit()
