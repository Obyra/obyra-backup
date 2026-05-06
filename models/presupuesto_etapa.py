"""Etapa editable de presupuesto — Etapa 1 esqueleto editable.

Cada presupuesto tiene N etapas; cada etapa agrupa M items_presupuesto.
A diferencia de EtapaObra (que pertenece a Obra), PresupuestoEtapa
pertenece al PRESUPUESTO y existe desde su creación, sin requerir
que el presupuesto sea confirmado como obra.

Mantiene `items_presupuesto.etapa_nombre` como cache denormalizado
para compatibilidad con código legacy (queries por string), pero la
fuente de verdad de la jerarquía pasa a ser `etapa_presupuesto_id`.
"""
from datetime import datetime

from extensions import db


class PresupuestoEtapa(db.Model):
    __tablename__ = 'presupuesto_etapa'
    __table_args__ = (
        db.UniqueConstraint('presupuesto_id', 'nombre',
                            name='uq_presupuesto_etapa_pres_nombre'),
        db.Index('ix_presupuesto_etapa_pres', 'presupuesto_id'),
        db.Index('ix_presupuesto_etapa_orden', 'presupuesto_id', 'orden'),
        db.Index('ix_presupuesto_etapa_oculto', 'oculto'),
    )

    id = db.Column(db.BigInteger, primary_key=True)
    presupuesto_id = db.Column(
        db.Integer,
        db.ForeignKey('presupuestos.id', ondelete='CASCADE'),
        nullable=False,
    )
    nombre = db.Column(db.String(150), nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    oculto = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('FALSE'))

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)

    presupuesto = db.relationship('Presupuesto', foreign_keys=[presupuesto_id])

    def __repr__(self):
        return f'<PresupuestoEtapa #{self.id} pres={self.presupuesto_id} "{self.nombre}">'

    def to_dict(self, items_count=None, items_total=None):
        return {
            'id': self.id,
            'presupuesto_id': self.presupuesto_id,
            'nombre': self.nombre,
            'orden': self.orden,
            'oculto': self.oculto,
            'items_count': items_count,
            'items_total': items_total,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @staticmethod
    def normalizar_nombre(nombre):
        """Trim + collapse de whitespace interno. Devuelve string vacio si None."""
        if not nombre:
            return ''
        import re
        return re.sub(r'\s+', ' ', str(nombre).strip())[:150]
