"""
Models for client management
"""
from extensions import db
from datetime import datetime


class Cliente(db.Model):
    """Modelo para gestión de clientes"""
    __tablename__ = 'clientes'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)

    # Información personal
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)

    # Identificación fiscal
    tipo_documento = db.Column(db.String(10), nullable=False, default='DNI')  # DNI, CUIT, CUIL, Pasaporte
    numero_documento = db.Column(db.String(20), nullable=False)

    # Contacto
    email = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(20))
    telefono_alternativo = db.Column(db.String(20))

    # Dirección
    direccion = db.Column(db.String(200))
    ciudad = db.Column(db.String(100))
    provincia = db.Column(db.String(100))
    codigo_postal = db.Column(db.String(10))

    # Información adicional
    empresa = db.Column(db.String(150))  # Razón social si es empresa
    contactos = db.Column(db.JSON)  # Array de contactos/empleados [{nombre, apellido, email, telefono, rol}]
    notas = db.Column(db.Text)

    # Metadata
    activo = db.Column(db.Boolean, default=True, nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_modificacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion', backref='clientes')
    presupuestos = db.relationship('Presupuesto', back_populates='cliente', lazy='dynamic')
    obras = db.relationship('Obra', back_populates='cliente_rel', lazy='dynamic')

    def __repr__(self):
        return f'<Cliente {self.nombre} {self.apellido}>'

    @property
    def nombre_completo(self):
        """Retorna el nombre completo del cliente"""
        return f"{self.nombre} {self.apellido}"

    @property
    def documento_formateado(self):
        """Retorna el documento formateado con su tipo"""
        return f"{self.tipo_documento}: {self.numero_documento}"

    def to_dict(self):
        """Convierte el cliente a diccionario para JSON"""
        return {
            'id': self.id,
            'nombre': self.nombre,
            'apellido': self.apellido,
            'nombre_completo': self.nombre_completo,
            'tipo_documento': self.tipo_documento,
            'numero_documento': self.numero_documento,
            'email': self.email,
            'telefono': self.telefono,
            'telefono_alternativo': self.telefono_alternativo,
            'direccion': self.direccion,
            'ciudad': self.ciudad,
            'provincia': self.provincia,
            'codigo_postal': self.codigo_postal,
            'empresa': self.empresa,
            'notas': self.notas,
            'activo': self.activo,
            'fecha_creacion': self.fecha_creacion.isoformat() if self.fecha_creacion else None,
        }
