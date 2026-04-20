"""
Modelos para solicitud de cotizacion a proveedores via WhatsApp
desde un presupuesto.
"""
from datetime import datetime

from extensions import db


class ItemPresupuestoProveedor(db.Model):
    """Pivot: que proveedores se sugieren para cada item del presupuesto."""
    __tablename__ = 'item_presupuesto_proveedores'

    id = db.Column(db.Integer, primary_key=True)
    item_presupuesto_id = db.Column(
        db.Integer, db.ForeignKey('items_presupuesto.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    proveedor_oc_id = db.Column(
        db.Integer, db.ForeignKey('proveedores_oc.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    item_presupuesto = db.relationship('ItemPresupuesto', backref=db.backref(
        'proveedores_sugeridos', lazy='dynamic', cascade='all, delete-orphan'
    ))
    proveedor = db.relationship('ProveedorOC')

    __table_args__ = (
        db.UniqueConstraint('item_presupuesto_id', 'proveedor_oc_id', name='uq_item_prov'),
    )

    def __repr__(self):
        return f'<ItemPresupuestoProveedor item={self.item_presupuesto_id} prov={self.proveedor_oc_id}>'


class SolicitudCotizacionWA(db.Model):
    """Solicitud de cotizacion a un proveedor via WhatsApp (una por proveedor)."""
    __tablename__ = 'solicitudes_cotizacion_wa'

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), index=True)  # SCW-2026-0001
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=False, index=True)
    proveedor_oc_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id'), nullable=False, index=True)

    telefono_destino = db.Column(db.String(20))      # formato internacional sin + (ej: 5491123456789)
    mensaje_enviado = db.Column(db.Text)

    # wa_link = MVP con wa.me | wa_api = Fase 2 con Cloud API
    canal = db.Column(db.String(20), default='wa_link')

    # borrador | enviado | respondido | cerrado | cancelado
    estado = db.Column(db.String(20), default='borrador')

    # Snapshot de items al momento de generar la solicitud (por si el presupuesto cambia despues)
    items_snapshot = db.Column(db.JSON)

    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_envio = db.Column(db.DateTime)
    fecha_respuesta = db.Column(db.DateTime)
    respuesta_texto = db.Column(db.Text)
    notas = db.Column(db.Text)

    # Relaciones
    organizacion = db.relationship('Organizacion')
    presupuesto = db.relationship('Presupuesto', backref=db.backref('solicitudes_wa', lazy='dynamic'))
    proveedor = db.relationship('ProveedorOC', backref=db.backref('solicitudes_wa', lazy='dynamic'))
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<SolicitudCotizacionWA {self.numero} prov={self.proveedor_oc_id} estado={self.estado}>'

    @property
    def estado_color(self):
        return {
            'borrador': 'secondary',
            'enviado': 'primary',
            'respondido': 'success',
            'cerrado': 'dark',
            'cancelado': 'danger',
        }.get(self.estado, 'secondary')

    @property
    def items_count(self):
        try:
            return len(self.items_snapshot or [])
        except Exception:
            return 0
