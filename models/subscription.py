"""
Modelo Subscription - Suscripcion mensual via Mercado Pago Preapproval.

Cada Organizacion puede tener una sola Subscription activa por vez.
El historial queda preservado: cuando una sub se cancela, queda con
estado='cancelled' y se puede crear una nueva.

Estados (espejo de los de MP):
- pending: creada pero el usuario aun no autorizo el pago en MP
- authorized: el usuario autorizo y MP confirmo el primer cobro
- paused: pausada manualmente o por fallo de pago
- cancelled: cancelada (por usuario o por nosotros)
- finished: termino el periodo y no se renovo
"""
from datetime import datetime
from extensions import db


class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    # Identificadores Mercado Pago
    mp_preapproval_id = db.Column(db.String(64), unique=True, index=True, nullable=True)
    mp_payer_id = db.Column(db.String(64), nullable=True)
    mp_payer_email = db.Column(db.String(255), nullable=True)

    # Datos del plan al momento de la suscripcion (snapshot)
    plan_codigo = db.Column(db.String(50), default='premium', nullable=False)
    plan_nombre = db.Column(db.String(100), default='OBYRA Profesional')
    monto_ars = db.Column(db.Numeric(12, 2), nullable=False)
    frequency_type = db.Column(db.String(20), default='months', nullable=False)
    frequency_value = db.Column(db.Integer, default=1, nullable=False)

    # Estado y fechas
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    # pending | authorized | paused | cancelled | finished
    init_url = db.Column(db.Text, nullable=True)  # URL para que el usuario autorice en MP
    last_payment_date = db.Column(db.DateTime, nullable=True)
    next_payment_date = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    # Auditoria
    last_event_payload = db.Column(db.Text, nullable=True)  # ultimo webhook recibido (debug)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    organizacion = db.relationship('Organizacion', backref=db.backref('subscriptions', lazy='dynamic'))
    created_by = db.relationship('Usuario')

    @property
    def is_active(self):
        return self.status == 'authorized'

    @property
    def is_pending(self):
        return self.status == 'pending'

    @property
    def is_cancelled(self):
        return self.status in ('cancelled', 'finished')

    def __repr__(self):
        return f'<Subscription org={self.organizacion_id} status={self.status}>'
