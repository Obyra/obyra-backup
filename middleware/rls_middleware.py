"""
Row Level Security middleware
==============================

Setea las variables PostgreSQL `app.current_org_id` y `app.is_super_admin` en cada
request, para que las policies RLS funcionen correctamente.

Sin este middleware, RLS bloquearía todas las queries (porque current_setting()
devolvería NULL).

Cómo se integra (en app.py):
    from middleware.rls_middleware import setup_rls_middleware
    setup_rls_middleware(app, db)
"""

import logging
from flask import g, has_request_context
from flask_login import current_user
from sqlalchemy import event, text


logger = logging.getLogger(__name__)


def setup_rls_middleware(app, db):
    """
    Configura el listener de SQLAlchemy para setear variables PostgreSQL en cada checkout
    de conexión del pool.

    Esto es más confiable que un before_request porque cubre TODAS las queries,
    incluyendo las que no vienen de un endpoint HTTP (Celery tasks, CLI, etc).
    """

    @event.listens_for(db.engine, "checkout")
    def receive_checkout(dbapi_connection, connection_record, connection_proxy):
        """Cada vez que la app saca una conexión del pool, setea el contexto."""
        try:
            org_id = None
            is_super = False

            if has_request_context():
                # Obtener org_id de la sesión Flask
                try:
                    from services.memberships import get_current_org_id
                    org_id = get_current_org_id()
                except Exception:
                    pass

                # Verificar super admin
                try:
                    if current_user.is_authenticated:
                        is_super = bool(getattr(current_user, 'is_super_admin', False))
                except Exception:
                    pass

            cursor = dbapi_connection.cursor()
            try:
                # Setear variables PostgreSQL
                if org_id is not None:
                    cursor.execute(f"SET app.current_org_id = '{int(org_id)}';")
                else:
                    cursor.execute("SET app.current_org_id = '';")

                cursor.execute(
                    f"SET app.is_super_admin = '{'true' if is_super else 'false'}';"
                )
            finally:
                cursor.close()

        except Exception as exc:
            # NO bloquear la app si esto falla
            logger.warning(f'[RLS] Error seteando contexto: {exc}')

    app.logger.info('[RLS] Middleware configurado correctamente')


def reset_rls_context(db):
    """Resetea las variables RLS (útil para tests y CLI)."""
    try:
        db.session.execute(text("RESET app.current_org_id;"))
        db.session.execute(text("RESET app.is_super_admin;"))
        db.session.commit()
    except Exception:
        db.session.rollback()
