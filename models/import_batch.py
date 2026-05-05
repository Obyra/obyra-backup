"""ImportBatch — traza cada import de fuente de precios (Etapa 2 base IA).

Tabla creada en migration 202605050002. Modelo declarativo mínimo, sin
lógica de orquestación (eso vive en services/import_batch_service.py
que se crea en Etapa 3).

Cada import_batch agrupa N filas escritas a `provider_price_list` y/o
`precio_observado`. Permite "deshacer" un import erróneo borrando
todas las filas con import_batch_id=X y marcando deshecho_at.

Multi-tenant strict: organizacion_id NOT NULL.

UNIQUE parcial (org, checksum) WHERE deshecho_at IS NULL → bloquea
re-import del mismo archivo, salvo que el batch anterior se deshaga.
"""
from datetime import datetime

from extensions import db


class ImportBatch(db.Model):
    __tablename__ = 'import_batch'
    __table_args__ = (
        db.Index('ix_import_batch_org', 'organizacion_id'),
        db.Index('ix_import_batch_perfil', 'perfil'),
        db.Index('ix_import_batch_estado', 'estado'),
        db.Index('ix_import_batch_started', 'started_at'),
    )

    id = db.Column(db.BigInteger, primary_key=True)
    organizacion_id = db.Column(
        db.Integer,
        db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
        nullable=False,
    )
    perfil = db.Column(db.String(40), nullable=False)
    # ej: 'obyra_base_v1', 'lista_propia', 'lista_proveedor', 'costo_mano_obra'
    filename = db.Column(db.String(255), nullable=False)
    checksum_sha256 = db.Column(db.String(64), nullable=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True,
    )

    total_input = db.Column(db.Integer, nullable=False, default=0)
    total_inserted = db.Column(db.Integer, nullable=False, default=0)
    total_updated = db.Column(db.Integer, nullable=False, default=0)
    total_invalid = db.Column(db.Integer, nullable=False, default=0)

    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(20), nullable=False, default='en_curso',
                       server_default='en_curso')
    # 'en_curso' | 'completado' | 'fallido' | 'deshecho'

    deshecho_at = db.Column(db.DateTime, nullable=True)
    undo_motivo = db.Column(db.Text, nullable=True)

    metadata_json = db.Column(db.JSON, nullable=True)

    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    user = db.relationship('Usuario', foreign_keys=[user_id])

    def __repr__(self):
        return (f'<ImportBatch #{self.id} {self.perfil} "{self.filename}" '
                f'{self.estado}>')

    def to_dict(self):
        return {
            'id': self.id,
            'organizacion_id': self.organizacion_id,
            'perfil': self.perfil,
            'filename': self.filename,
            'checksum_sha256': self.checksum_sha256,
            'user_id': self.user_id,
            'total_input': self.total_input,
            'total_inserted': self.total_inserted,
            'total_updated': self.total_updated,
            'total_invalid': self.total_invalid,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'estado': self.estado,
            'deshecho_at': self.deshecho_at.isoformat() if self.deshecho_at else None,
            'undo_motivo': self.undo_motivo,
        }
