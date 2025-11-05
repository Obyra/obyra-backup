"""
Security logging utilities for OBYRA IA
Logs security-relevant events for audit purposes
"""

from flask import current_app, request
from flask_login import current_user
from datetime import datetime
import json


def get_request_context():
    """Get current request context for logging"""
    try:
        return {
            'ip': request.remote_addr if request else None,
            'user_agent': request.user_agent.string if request and request.user_agent else None,
            'endpoint': request.endpoint if request else None,
            'method': request.method if request else None
        }
    except RuntimeError:
        # Outside request context
        return {}


def log_security_event(event_type, message, **extra_data):
    """
    Log a security event

    Args:
        event_type: Type of security event (e.g., 'login', 'logout', 'permission_denied')
        message: Human-readable message
        **extra_data: Additional data to log
    """
    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        user_email = current_user.email if current_user and current_user.is_authenticated else 'anonymous'

        context = get_request_context()

        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'message': message,
            'user_id': user_id,
            'user_email': user_email,
            'context': context,
            **extra_data
        }

        current_app.logger.warning(
            f"[SECURITY] {event_type}: {message}",
            extra={'security_event': log_data}
        )
    except Exception as e:
        # Don't let logging errors break the application
        current_app.logger.error(f"Error logging security event: {e}")


def log_login_attempt(email, success, reason=None):
    """Log a login attempt"""
    log_security_event(
        'login_attempt',
        f"Login attempt for {email}: {'SUCCESS' if success else 'FAILED'}",
        email=email,
        success=success,
        reason=reason
    )


def log_logout(email):
    """Log a logout event"""
    log_security_event(
        'logout',
        f"User {email} logged out",
        email=email
    )


def log_permission_denied(resource, action, reason=None):
    """Log a permission denied event"""
    log_security_event(
        'permission_denied',
        f"Permission denied for {action} on {resource}",
        resource=resource,
        action=action,
        reason=reason
    )


def log_data_modification(table, record_id, action, changes=None):
    """
    Log data modification (create, update, delete)

    Args:
        table: Table name
        record_id: ID of the record
        action: 'create', 'update', or 'delete'
        changes: Dictionary of changes (for updates)
    """
    log_security_event(
        'data_modification',
        f"{action.upper()} on {table} record {record_id}",
        table=table,
        record_id=record_id,
        action=action,
        changes=changes
    )


def log_data_deletion(table, record_id, soft_delete=False):
    """Log data deletion"""
    log_data_modification(
        table=table,
        record_id=record_id,
        action='soft_delete' if soft_delete else 'hard_delete'
    )


def log_role_change(user_id, old_role, new_role, changed_by):
    """Log a user role change"""
    log_security_event(
        'role_change',
        f"User {user_id} role changed from {old_role} to {new_role}",
        user_id=user_id,
        old_role=old_role,
        new_role=new_role,
        changed_by=changed_by
    )


def log_organization_change(user_id, old_org_id, new_org_id):
    """Log a user organization change"""
    log_security_event(
        'organization_change',
        f"User {user_id} organization changed from {old_org_id} to {new_org_id}",
        user_id=user_id,
        old_org_id=old_org_id,
        new_org_id=new_org_id
    )


def log_password_reset(email):
    """Log a password reset request"""
    log_security_event(
        'password_reset',
        f"Password reset requested for {email}",
        email=email
    )


def log_admin_action(action, target_user_id=None, details=None):
    """Log an administrative action"""
    log_security_event(
        'admin_action',
        f"Admin action: {action}",
        action=action,
        target_user_id=target_user_id,
        details=details
    )


def log_password_change(user_id, email):
    """Log a password change"""
    log_security_event(
        'password_change',
        f"Password changed for user {email}",
        user_id=user_id,
        email=email
    )


def log_transaction(transaction_type, amount, details=None):
    """Log a financial transaction"""
    log_security_event(
        'transaction',
        f"Transaction: {transaction_type} - Amount: {amount}",
        transaction_type=transaction_type,
        amount=amount,
        details=details
    )


def log_permission_change(user_id, permission, granted, changed_by=None):
    """Log a permission change"""
    log_security_event(
        'permission_change',
        f"Permission {permission} {'granted to' if granted else 'revoked from'} user {user_id}",
        user_id=user_id,
        permission=permission,
        granted=granted,
        changed_by=changed_by
    )
