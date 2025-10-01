"""Reusable middleware snippets for feature-flagged analytics and audit logging.

Designed to be copy-pasted into Flask/FastAPI services without affecting v1
behavior. Each middleware is inert unless its corresponding feature flag is ON.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from flask import g, request

from extensions import db


@dataclass
class FeatureFlags:
    analytics: bool
    audit_log: bool


def load_flags(tenant_id: Optional[str]) -> FeatureFlags:
    """Fetch flags from DB/cache with safe defaults."""
    if not tenant_id:
        return FeatureFlags(False, False)

    rows = db.session.execute(
        """
        SELECT flag, enabled
        FROM feature_flags
        WHERE tenant_id = :tenant_id AND flag IN ('FF_ANALYTICS', 'FF_AUDIT_LOG')
        """,
        {"tenant_id": tenant_id},
    ).all()
    mapping = {row.flag: row.enabled for row in rows}
    return FeatureFlags(
        analytics=mapping.get("FF_ANALYTICS", False),
        audit_log=mapping.get("FF_AUDIT_LOG", False),
    )


def emit_analytics(event_name: str, payload: Dict[str, Any]) -> None:
    tenant_id = getattr(g, "tenant_id", None)
    flags = load_flags(tenant_id)
    if not flags.analytics:
        return

    db.session.execute(
        """
        INSERT INTO analytics_events (id, tenant_id, user_id, event_name, payload, occurred_at)
        VALUES (gen_random_uuid(), :tenant_id, :user_id, :event_name, :payload::jsonb, :occurred_at)
        """,
        {
            "tenant_id": tenant_id,
            "user_id": getattr(g, "user_id", None),
            "event_name": event_name,
            "payload": payload,
            "occurred_at": datetime.now(timezone.utc),
        },
    )


def log_action(action: str, entity: str, entity_id: str, payload: Dict[str, Any]) -> None:
    tenant_id = getattr(g, "tenant_id", None)
    flags = load_flags(tenant_id)
    if not flags.audit_log:
        return

    db.session.execute(
        """
        INSERT INTO audit_log (id, tenant_id, user_id, action, entity, entity_id, payload, occurred_at)
        VALUES (gen_random_uuid(), :tenant_id, :user_id, :action, :entity, :entity_id, :payload::jsonb, :occurred_at)
        """,
        {
            "tenant_id": tenant_id,
            "user_id": getattr(g, "user_id", None),
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "payload": payload,
            "occurred_at": datetime.now(timezone.utc),
        },
    )


def analytics_middleware(app):
    """Flask middleware that emits analytics events in shadow mode."""

    @app.before_request
    def _set_context() -> None:  # type: ignore[override]
        g.tenant_id = request.headers.get("X-Tenant-ID")
        g.user_id = getattr(getattr(request, "user", None), "id", None)

    @app.after_request
    def _after(response):  # type: ignore[override]
        if response.status_code < 500:
            emit_analytics(
                event_name=f"http.{request.method.lower()}.{request.endpoint}",
                payload={
                    "path": request.path,
                    "status": response.status_code,
                },
            )
        return response

    return app


def wrap_handler(handler: Callable[..., Any], action: str, entity: str) -> Callable[..., Any]:
    """Decorator helper to log successful actions."""

    def _wrapper(*args, **kwargs):
        result = handler(*args, **kwargs)
        if getattr(result, "status_code", 200) < 400:
            entity_id = kwargs.get("entity_id") or getattr(result, "id", None)
            log_action(action, entity, str(entity_id), payload={"args": args, "kwargs": kwargs})
        return result

    return _wrapper

