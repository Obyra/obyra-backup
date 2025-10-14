from __future__ import annotations

from functools import wraps
from typing import Iterable, Optional

from flask import current_app, g, redirect, request, session, url_for, flash
from flask_login import current_user

from sqlalchemy.orm.attributes import set_committed_value

from models import OrgMembership, Usuario, db


def _membership_query(user_id: int) -> Iterable[OrgMembership]:
    return (
        OrgMembership.query
        .filter(
            OrgMembership.user_id == user_id,
            db.or_(
                OrgMembership.archived.is_(False),
                OrgMembership.archived.is_(None),
            ),
        )
        .order_by(OrgMembership.id.asc())
    )


def initialize_membership_session(usuario: Usuario) -> Optional[str]:
    """Sincroniza la sesión con las membresías disponibles y devuelve una URL si se requiere selección."""
    if not usuario:
        return None

    memberships = list(_membership_query(usuario.id))

    if not memberships and usuario.organizacion_id:
        membership = usuario.ensure_membership(usuario.organizacion_id, role=usuario.role, status='active')
        db.session.commit()
        memberships = [membership]

    active_memberships = [m for m in memberships if m.status == 'active']

    if not active_memberships:
        # Si no hay membresías activas, no forzamos logout pero bloqueamos acceso.
        session.pop('current_membership_id', None)
        session.pop('current_org_id', None)
        return None

    active_ids = {m.id for m in active_memberships}
    session['available_membership_ids'] = list(active_ids)

    current_membership_id = session.get('current_membership_id')
    previous_confirmed = session.get('membership_selection_confirmed')

    if current_membership_id not in active_ids:
        selected = active_memberships[0]
    else:
        selected = next((m for m in active_memberships if m.id == current_membership_id), active_memberships[0])

    session['current_membership_id'] = selected.id
    session['current_org_id'] = selected.org_id
    session['membership_selection_confirmed'] = selected.id

    requires_selection = len(active_memberships) > 1 and (previous_confirmed not in active_ids or previous_confirmed is None)

    return url_for('auth.seleccionar_organizacion') if requires_selection else None


def load_membership_into_context() -> None:
    """Carga la membresía activa en el contexto de la petición."""
    g.current_membership = None
    g.current_org_id = None

    if not current_user.is_authenticated:
        return

    membership_id = session.get('current_membership_id')
    membership: Optional[OrgMembership] = None

    if membership_id:
        membership = (
            OrgMembership.query
            .filter(
                OrgMembership.id == membership_id,
                OrgMembership.user_id == current_user.id,
                db.or_(
                    OrgMembership.archived.is_(False),
                    OrgMembership.archived.is_(None),
                ),
            )
            .first()
        )

        if not membership or membership.status != 'active':
            session.pop('current_membership_id', None)
            session.pop('current_org_id', None)
            membership = None

    if membership is None:
        memberships = list(_membership_query(current_user.id))
        active = [m for m in memberships if m.status == 'active']
        if active:
            membership = active[0]
            session['current_membership_id'] = membership.id
            session['current_org_id'] = membership.org_id

    if membership is None:
        return

    g.current_membership = membership
    g.current_org_id = membership.org_id

    # Actualizar cache de selección para evitar re-prompt innecesarios
    session['membership_selection_confirmed'] = membership.id

    # Sincronizar atributos comunes del usuario con la membresía actual
    try:
        set_committed_value(current_user, 'organizacion_id', membership.org_id)
        if getattr(current_user, 'primary_org_id', None) is None:
            set_committed_value(current_user, 'primary_org_id', membership.org_id)

        if membership.role == 'admin':
            set_committed_value(current_user, 'rol', 'administrador')
            set_committed_value(current_user, 'role', 'admin')
        else:
            set_committed_value(current_user, 'rol', 'operario')
            set_committed_value(current_user, 'role', 'operario')
    except Exception:
        # En entornos donde current_user es proxy sin estos atributos, ignoramos el error.
        pass


def get_current_membership() -> Optional[OrgMembership]:
    return getattr(g, 'current_membership', None)


def get_current_org_id() -> Optional[int]:
    membership = get_current_membership()
    if membership:
        return membership.org_id
    return session.get('current_org_id')


def require_membership(role: Optional[str] = None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))

            membership = get_current_membership()
            if not membership or membership.status != 'active':
                flash('Tu cuenta no tiene acceso activo a esta organización.', 'danger')
                return redirect(url_for('auth.seleccionar_organizacion', next=request.url))

            if role and membership.role != role:
                flash('No tienes permisos para realizar esta acción en la organización actual.', 'danger')
                return redirect(url_for('reportes.dashboard'))

            g.current_membership = membership
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def set_current_membership(membership_id: int) -> bool:
    if not current_user.is_authenticated:
        return False

    membership = (
        OrgMembership.query
        .filter(
            OrgMembership.id == membership_id,
            OrgMembership.user_id == current_user.id,
            db.or_(
                OrgMembership.archived.is_(False),
                OrgMembership.archived.is_(None),
            ),
        )
        .first()
    )

    if not membership or membership.status != 'active':
        return False

    session['current_membership_id'] = membership.id
    session['current_org_id'] = membership.org_id
    session['membership_selection_confirmed'] = membership.id
    return True


def activate_pending_memberships(usuario: Usuario) -> bool:
    memberships = (
        OrgMembership.query
        .filter(
            OrgMembership.user_id == usuario.id,
            OrgMembership.status == 'pending',
            db.or_(
                OrgMembership.archived.is_(False),
                OrgMembership.archived.is_(None),
            ),
        )
        .all()
    )
    changed = False
    for membership in memberships:
        membership.marcar_activa()
        changed = True
    if changed and current_app:
        current_app.logger.info('✅ Membresías activadas para %s', usuario.email)
    return changed
