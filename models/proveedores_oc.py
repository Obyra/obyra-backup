"""
Models para gestión de Proveedores de Órdenes de Compra.
Separado del modelo legacy Proveedor (marketplace) en models/suppliers.py.
"""
from extensions import db
from datetime import datetime


class ProveedorOC(db.Model):
    """Proveedor vinculado a Órdenes de Compra."""
    __tablename__ = 'proveedores_oc'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)

    # Datos principales
    razon_social = db.Column(db.String(200), nullable=False)
    nombre_fantasia = db.Column(db.String(200))
    cuit = db.Column(db.String(20))
    tipo = db.Column(db.String(50), default='materiales')  # materiales, servicios, equipos, otros

    # Contacto
    email = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    direccion = db.Column(db.String(300))
    ciudad = db.Column(db.String(100))
    provincia = db.Column(db.String(100))

    # Persona de contacto
    contacto_nombre = db.Column(db.String(200))
    contacto_telefono = db.Column(db.String(50))

    # Comercial
    condicion_pago = db.Column(db.String(100))  # "Contado", "30 días", etc
    notas = db.Column(db.Text)

    # Estado
    activo = db.Column(db.Boolean, default=True, nullable=False)

    # Auditoría
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion', backref='proveedores_oc')
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])
    historial_precios = db.relationship('HistorialPrecioProveedor', back_populates='proveedor',
                                        lazy='dynamic', order_by='HistorialPrecioProveedor.fecha.desc()')

    def __repr__(self):
        return f'<ProveedorOC {self.razon_social}>'

    @property
    def nombre_display(self):
        if self.nombre_fantasia:
            return f"{self.nombre_fantasia} ({self.razon_social})"
        return self.razon_social

    @property
    def tipo_display(self):
        tipos = {
            'materiales': 'Materiales',
            'servicios': 'Servicios',
            'equipos': 'Equipos',
            'otros': 'Otros'
        }
        return tipos.get(self.tipo, self.tipo or 'Otros')

    @property
    def tipo_color(self):
        colores = {
            'materiales': 'primary',
            'servicios': 'success',
            'equipos': 'warning',
            'otros': 'secondary'
        }
        return colores.get(self.tipo, 'secondary')

    def to_dict(self):
        return {
            'id': self.id,
            'razon_social': self.razon_social,
            'nombre_fantasia': self.nombre_fantasia,
            'nombre_display': self.nombre_display,
            'cuit': self.cuit,
            'tipo': self.tipo,
            'email': self.email,
            'telefono': self.telefono,
            'direccion': self.direccion,
            'ciudad': self.ciudad,
            'provincia': self.provincia,
            'contacto_nombre': self.contacto_nombre,
            'contacto_telefono': self.contacto_telefono,
            'condicion_pago': self.condicion_pago,
            'activo': self.activo,
        }


class HistorialPrecioProveedor(db.Model):
    """Registro histórico de precios por proveedor (append-only, se crea al completar OC)."""
    __tablename__ = 'historial_precios_proveedor'

    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id'), nullable=False)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=True)
    descripcion_item = db.Column(db.String(300), nullable=False)
    precio_unitario = db.Column(db.Numeric(15, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    orden_compra_id = db.Column(db.Integer, db.ForeignKey('ordenes_compra.id'), nullable=True)
    fecha = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    proveedor = db.relationship('ProveedorOC', back_populates='historial_precios')
    item_inventario = db.relationship('ItemInventario')
    orden_compra = db.relationship('OrdenCompra')

    def to_dict(self):
        return {
            'id': self.id,
            'descripcion_item': self.descripcion_item,
            'precio_unitario': float(self.precio_unitario or 0),
            'moneda': self.moneda,
            'fecha': self.fecha.isoformat() if self.fecha else None,
            'orden_compra_numero': self.orden_compra.numero if self.orden_compra else None,
        }
