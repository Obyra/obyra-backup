"""Archivo de pliego cargado en un presupuesto (Fase 6.A).

Permite que un mismo presupuesto tenga MULTIPLES archivos Excel/PDF.
Hasta Fase 6.A solo soportamos pliegos Excel.

Multi-tenant strict: organizacion_id NOT NULL + redundante con
presupuesto.organizacion_id (cache para queries rapidas).

Storage: archivos guardados FUERA de /static/ (en storage/uploads/...).
Las descargas pasan SIEMPRE por endpoint protegido — el path no se sirve
directamente.
"""
from datetime import datetime

from extensions import db


class PresupuestoArchivo(db.Model):
    __tablename__ = 'presupuesto_archivo'
    __table_args__ = (
        db.UniqueConstraint('presupuesto_id', 'checksum_sha256',
                            name='uq_pa_pres_checksum'),
        db.Index('ix_pa_presupuesto', 'presupuesto_id'),
        db.Index('ix_pa_org', 'organizacion_id'),
        db.Index('ix_pa_estado', 'estado_importacion'),
        db.Index('ix_pa_uploaded', 'uploaded_at'),
        db.Index('ix_pa_checksum', 'checksum_sha256'),
    )

    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(db.Integer,
                               db.ForeignKey('presupuestos.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    organizacion_id = db.Column(db.Integer,
                                db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                nullable=False, index=True)
    uploaded_by_user_id = db.Column(db.Integer,
                                    db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                    nullable=True)

    # Datos del archivo
    filename_original = db.Column(db.String(255), nullable=False)
    filename_storage = db.Column(db.String(255), nullable=False)  # nombre en disco
    file_path = db.Column(db.String(500), nullable=False)         # path completo (no servido directo)
    mime_type = db.Column(db.String(80), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    checksum_sha256 = db.Column(db.String(64), nullable=True)
    tipo_archivo = db.Column(db.String(30), nullable=False,
                             default='pliego_excel', server_default='pliego_excel')

    # Estado de importacion
    estado_importacion = db.Column(db.String(20), nullable=False,
                                   default='pendiente', server_default='pendiente')
    cantidad_hojas_detectadas = db.Column(db.Integer, default=0)
    cantidad_items_detectados = db.Column(db.Integer, default=0)
    cantidad_items_importados = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)

    # Timestamps
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    imported_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    presupuesto = db.relationship('Presupuesto', foreign_keys=[presupuesto_id],
                                  backref=db.backref('archivos', cascade='all, delete-orphan',
                                                     lazy='dynamic'))
    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    uploaded_by = db.relationship('Usuario', foreign_keys=[uploaded_by_user_id])

    def __repr__(self):
        return f'<PresupuestoArchivo pres={self.presupuesto_id} {self.filename_original}>'

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def to_dict(self):
        return {
            'id': self.id,
            'presupuesto_id': self.presupuesto_id,
            'organizacion_id': self.organizacion_id,
            'uploaded_by_user_id': self.uploaded_by_user_id,
            'uploaded_by_nombre': (
                f'{self.uploaded_by.nombre} {self.uploaded_by.apellido or ""}'.strip()
                if self.uploaded_by else None
            ),
            'filename_original': self.filename_original,
            'mime_type': self.mime_type,
            'size_bytes': self.size_bytes,
            'tipo_archivo': self.tipo_archivo,
            'estado_importacion': self.estado_importacion,
            'cantidad_hojas_detectadas': self.cantidad_hojas_detectadas or 0,
            'cantidad_items_detectados': self.cantidad_items_detectados or 0,
            'cantidad_items_importados': self.cantidad_items_importados or 0,
            'error_message': self.error_message,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'imported_at': self.imported_at.isoformat() if self.imported_at else None,
            'is_deleted': self.is_deleted,
            # Diagnostico del parser cuando estado_importacion == 'error'
            'diagnostico': (self.metadata_json or {}).get('diagnostico') if self.metadata_json else None,
        }
