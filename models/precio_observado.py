"""Precios observados — base inteligente de precios (Etapa 1).

Captura precios crudos provenientes de cualquier fuente (Excel importados
con precio, lista propia, OC completadas, cotizaciones de proveedor) sin
perder trazabilidad. Es append-only por diseño y sirve de "memoria"
historica de precios.

ETAPA 1: solo se popula desde el importer cuando un Excel trae precios > 0.
La estimacion automatica NO la consume todavia (eso es Etapa 2).

Multi-tenant strict: organizacion_id NOT NULL.

Dedup en re-import del mismo archivo:
   UNIQUE (organizacion_id, origen_archivo_id, origen_item_presupuesto_id, tipo_recurso)
   Como NULLs no comparan en UNIQUE de Postgres, esta tupla solo aplica
   cuando se completaron los campos — perfecto para el caso excel_pliego.
"""
from datetime import datetime

from extensions import db


class PrecioObservado(db.Model):
    __tablename__ = 'precio_observado'
    __table_args__ = (
        db.UniqueConstraint(
            'organizacion_id', 'origen_archivo_id',
            'origen_item_presupuesto_id', 'tipo_recurso',
            name='uq_precio_obs_archivo_item_tipo',
        ),
        db.Index('ix_precio_obs_org_desc_unidad',
                 'organizacion_id', 'descripcion_normalizada', 'unidad'),
        db.Index('ix_precio_obs_org_rubro', 'organizacion_id', 'rubro_nombre'),
        db.Index('ix_precio_obs_fecha', 'fecha_observado'),
        db.Index('ix_precio_obs_archivo', 'origen_archivo_id'),
        db.Index('ix_precio_obs_origen_tipo', 'origen_tipo'),
    )

    id = db.Column(db.BigInteger, primary_key=True)
    organizacion_id = db.Column(
        db.Integer,
        db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )

    # Origen / trazabilidad
    origen_tipo = db.Column(db.String(30), nullable=False)
    # En Etapa 1 solo 'excel_pliego'. Futuras: 'lista_propia', 'oc_completada',
    # 'cotizacion_proveedor', 'referencia_constructora'.

    origen_archivo_id = db.Column(
        db.Integer,
        db.ForeignKey('presupuesto_archivo.id', ondelete='SET NULL'),
        nullable=True,
    )
    origen_presupuesto_id = db.Column(
        db.Integer,
        db.ForeignKey('presupuestos.id', ondelete='SET NULL'),
        nullable=True,
    )
    origen_item_presupuesto_id = db.Column(
        db.Integer,
        db.ForeignKey('items_presupuesto.id', ondelete='SET NULL'),
        nullable=True,
    )

    # Datos del item observado
    descripcion = db.Column(db.Text, nullable=False)
    descripcion_normalizada = db.Column(db.String(300), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    rubro_nombre = db.Column(db.String(100), nullable=True)
    tipo_recurso = db.Column(db.String(20), nullable=False, default='item_completo')
    # 'material' | 'mano_obra' | 'equipo' | 'item_completo'

    # Precio
    precio_unitario = db.Column(db.Numeric(15, 2), nullable=False)
    moneda = db.Column(db.String(3), nullable=False, default='ARS', server_default='ARS')

    # Cuando se observo el precio (no el created_at del registro)
    fecha_observado = db.Column(db.Date, nullable=False)

    # Validacion humana — Etapa 6 permitira invalidar observaciones erroneas
    valido = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('TRUE'))

    notas = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relaciones (sin backrefs para no cascadear con tablas grandes)
    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    archivo = db.relationship('PresupuestoArchivo', foreign_keys=[origen_archivo_id])
    presupuesto = db.relationship('Presupuesto', foreign_keys=[origen_presupuesto_id])
    item_presupuesto = db.relationship(
        'ItemPresupuesto', foreign_keys=[origen_item_presupuesto_id]
    )

    def __repr__(self):
        return (f'<PrecioObservado #{self.id} {self.tipo_recurso} '
                f'"{self.descripcion[:40]}" {self.unidad} '
                f'{self.precio_unitario} {self.moneda}>')

    def to_dict(self):
        return {
            'id': self.id,
            'organizacion_id': self.organizacion_id,
            'origen_tipo': self.origen_tipo,
            'origen_archivo_id': self.origen_archivo_id,
            'origen_presupuesto_id': self.origen_presupuesto_id,
            'origen_item_presupuesto_id': self.origen_item_presupuesto_id,
            'descripcion': self.descripcion,
            'descripcion_normalizada': self.descripcion_normalizada,
            'unidad': self.unidad,
            'rubro_nombre': self.rubro_nombre,
            'tipo_recurso': self.tipo_recurso,
            'precio_unitario': float(self.precio_unitario) if self.precio_unitario else 0.0,
            'moneda': self.moneda,
            'fecha_observado': self.fecha_observado.isoformat() if self.fecha_observado else None,
            'valido': self.valido,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
