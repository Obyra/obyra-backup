"""
Audit Log - Registro de cambios en el sistema
Permite rastrear quién cambió qué y cuándo.
"""
from datetime import datetime
from app import db


class AuditLog(db.Model):
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True, index=True)
    user_email = db.Column(db.String(200))  # Guardar email por si el usuario se borra
    accion = db.Column(db.String(50), nullable=False, index=True)  # crear, editar, eliminar, login, etc.
    entidad = db.Column(db.String(100), nullable=False, index=True)  # obra, presupuesto, item_inventario, etc.
    entidad_id = db.Column(db.Integer, nullable=True)  # ID del recurso afectado
    detalle = db.Column(db.Text)  # Descripción legible del cambio
    datos_anteriores = db.Column(db.Text)  # JSON con valores previos (opcional)
    datos_nuevos = db.Column(db.Text)  # JSON con valores nuevos (opcional)
    ip_address = db.Column(db.String(45))  # IPv4 o IPv6
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Relaciones
    usuario = db.relationship('Usuario', backref='audit_logs')

    def __repr__(self):
        return f'<AuditLog {self.accion} {self.entidad}:{self.entidad_id} by {self.user_email}>'


def registrar_audit(accion, entidad, entidad_id=None, detalle=None,
                    datos_anteriores=None, datos_nuevos=None):
    """Helper para registrar un evento de auditoría desde cualquier blueprint."""
    from flask_login import current_user
    from flask import request
    from services.memberships import get_current_org_id
    import json

    try:
        log = AuditLog(
            organizacion_id=get_current_org_id() if get_current_org_id else None,
            user_id=current_user.id if current_user and current_user.is_authenticated else None,
            user_email=current_user.email if current_user and current_user.is_authenticated else 'sistema',
            accion=accion,
            entidad=entidad,
            entidad_id=entidad_id,
            detalle=detalle,
            datos_anteriores=json.dumps(datos_anteriores, default=str) if datos_anteriores else None,
            datos_nuevos=json.dumps(datos_nuevos, default=str) if datos_nuevos else None,
            ip_address=request.remote_addr if request else None,
        )
        db.session.add(log)
        # No hacemos commit — se commitea con la transacción del caller
    except Exception:
        pass  # Nunca bloquear la operación principal por un error de audit
