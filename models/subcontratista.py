"""
Modelos para Subcontratistas y su documentacion legal.

Subcontratista: empresa o persona contratada para ejecutar tareas especificas
                de una obra (electricista, plomero, yesero, etc.)
DocumentoSubcontratista: archivos adjuntos (seguro ART, contrato, poliza, etc.)
                         con fecha de vencimiento para alertas.
"""
from datetime import datetime, date
from extensions import db


class Subcontratista(db.Model):
    __tablename__ = 'subcontratistas'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)

    razon_social = db.Column(db.String(200), nullable=False)
    nombre_contacto = db.Column(db.String(150), nullable=True)
    cuit = db.Column(db.String(20), nullable=True, index=True)
    rubro = db.Column(db.String(100), nullable=True)  # electricidad, plomeria, yeseria, etc.

    email = db.Column(db.String(150), nullable=True)
    telefono = db.Column(db.String(50), nullable=True)
    direccion = db.Column(db.String(255), nullable=True)
    ciudad = db.Column(db.String(100), nullable=True)
    provincia = db.Column(db.String(100), nullable=True)

    notas = db.Column(db.Text, nullable=True)
    activo = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    documentos = db.relationship(
        'DocumentoSubcontratista',
        backref='subcontratista',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    @property
    def documentos_vencidos(self):
        hoy = date.today()
        return [d for d in self.documentos if d.fecha_vencimiento and d.fecha_vencimiento < hoy]

    @property
    def documentos_por_vencer(self):
        """Vencen en los proximos 30 dias."""
        from datetime import timedelta
        hoy = date.today()
        limite = hoy + timedelta(days=30)
        return [d for d in self.documentos
                if d.fecha_vencimiento and hoy <= d.fecha_vencimiento <= limite]

    @property
    def estado_documentacion(self):
        """Devuelve 'ok', 'por_vencer', 'vencido' segun el estado de los documentos."""
        if any(self.documentos_vencidos):
            return 'vencido'
        if any(self.documentos_por_vencer):
            return 'por_vencer'
        return 'ok'

    def __repr__(self):
        return f'<Subcontratista {self.razon_social}>'


class DocumentoSubcontratista(db.Model):
    __tablename__ = 'documentos_subcontratistas'

    id = db.Column(db.Integer, primary_key=True)
    subcontratista_id = db.Column(
        db.Integer,
        db.ForeignKey('subcontratistas.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    tipo = db.Column(db.String(50), nullable=False)  # seguro_art, contrato, poliza, habilitacion, otro
    descripcion = db.Column(db.String(255), nullable=True)
    archivo_url = db.Column(db.String(500), nullable=True)  # path en storage (local o R2)
    archivo_nombre = db.Column(db.String(255), nullable=True)

    fecha_emision = db.Column(db.Date, nullable=True)
    fecha_vencimiento = db.Column(db.Date, nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    @property
    def esta_vencido(self):
        return self.fecha_vencimiento and self.fecha_vencimiento < date.today()

    @property
    def dias_para_vencer(self):
        if not self.fecha_vencimiento:
            return None
        return (self.fecha_vencimiento - date.today()).days

    def __repr__(self):
        return f'<DocumentoSubcontratista {self.tipo} sub={self.subcontratista_id}>'
