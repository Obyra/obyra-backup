"""Catalogo de precios de proveedores (Fase 5.A).

Una fila por (organizacion, proveedor, recurso normalizado, unidad).
Permite carga via importador Excel (Fase 5.B), carga manual puntual y
auto-feed desde OC completadas / cotizaciones aceptadas (Fase 5.C).

Multi-tenant strict: organizacion_id NOT NULL. Ningun query global cruza
organizaciones.
"""
import unicodedata
import re
from datetime import datetime, date

from extensions import db


def normalizar_descripcion_precio(texto):
    """Lowercase + sin acentos + colapsar whitespace.

    Misma logica que services/ia_learning_service.normalizar_descripcion para
    que el matching IA <-> precio use el mismo formato. Si esa funcion cambia,
    coordinar.
    """
    if not texto:
        return ''
    s = str(texto).strip().lower()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r'[^\w\s\-/]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:300]


class ProviderPriceList(db.Model):
    """Catalogo vigente de precios por proveedor.

    Etapa 2 base IA: el UNIQUE de unicidad ahora incluye zona y modalidad,
    via index expression-based con COALESCE (definido en la migracion
    202605050002). No se declara aqui como UniqueConstraint porque
    SQLAlchemy no soporta COALESCE en constraints declarativos — se
    crea solo via DDL en Alembic. Mantener en sincronia.
    """
    __tablename__ = 'provider_price_list'
    __table_args__ = (
        # NOTA: el UNIQUE viejo (org, proveedor, desc_norm, unidad) fue
        # reemplazado por uq_ppl_org_prov_desc_un_zona_modalidad en migration
        # 202605050002 — indice expression-based, no declarable aca.
        db.Index('ix_ppl_org_descnorm', 'organizacion_id', 'descripcion_normalizada'),
        db.Index('ix_ppl_org_proveedor', 'organizacion_id', 'proveedor_id'),
        db.Index('ix_ppl_org_invitem', 'organizacion_id', 'item_inventario_id'),
        db.Index('ix_ppl_vigencia', 'vigencia_hasta'),
        db.Index('ix_ppl_org_zona', 'organizacion_id', 'zona'),
        db.Index('ix_ppl_org_modalidad', 'organizacion_id', 'modalidad'),
        db.Index('ix_ppl_codigo_proveedor',
                 'organizacion_id', 'proveedor_id', 'codigo_proveedor'),
        db.Index('ix_ppl_import_batch', 'import_batch_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                nullable=False, index=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id', ondelete='SET NULL'),
                             nullable=True)
    descripcion = db.Column(db.String(300), nullable=False)
    descripcion_normalizada = db.Column(db.String(300), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id', ondelete='SET NULL'),
                                   nullable=True)
    precio_unitario = db.Column(db.Numeric(15, 2), nullable=False)
    moneda = db.Column(db.String(3), nullable=False, default='ARS', server_default='ARS')
    fecha_actualizacion = db.Column(db.Date, nullable=False, default=date.today)
    vigencia_hasta = db.Column(db.Date, nullable=True)
    fuente = db.Column(db.String(30), nullable=False, default='manual', server_default='manual')
    notas = db.Column(db.Text, nullable=True)
    batch_id = db.Column(db.String(40), nullable=True)

    # Etapa 2 base IA: zona, modalidad, codigo proveedor, import batch
    zona = db.Column(db.String(40), nullable=True)
    modalidad = db.Column(db.String(30), nullable=True)
    codigo_proveedor = db.Column(db.String(60), nullable=True)
    import_batch_id = db.Column(db.BigInteger,
                                db.ForeignKey('import_batch.id', ondelete='SET NULL'),
                                nullable=True)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                   nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    proveedor = db.relationship('ProveedorOC', foreign_keys=[proveedor_id])

    def __repr__(self):
        return f'<ProviderPriceList org={self.organizacion_id} {self.descripcion[:30]} ${self.precio_unitario}>'

    def esta_vigente(self, fecha_ref=None):
        """True si la vigencia_hasta es >= fecha_ref (default hoy)."""
        if not self.vigencia_hasta:
            return True  # sin vigencia explicita, asumimos vigente
        ref = fecha_ref or date.today()
        return self.vigencia_hasta >= ref

    def to_dict(self):
        return {
            'id': self.id,
            'organizacion_id': self.organizacion_id,
            'proveedor_id': self.proveedor_id,
            'proveedor_nombre': self.proveedor.razon_social if self.proveedor else None,
            'descripcion': self.descripcion,
            'descripcion_normalizada': self.descripcion_normalizada,
            'unidad': self.unidad,
            'precio_unitario': float(self.precio_unitario or 0),
            'moneda': self.moneda,
            'fecha_actualizacion': self.fecha_actualizacion.isoformat() if self.fecha_actualizacion else None,
            'vigencia_hasta': self.vigencia_hasta.isoformat() if self.vigencia_hasta else None,
            'vigente': self.esta_vigente(),
            'fuente': self.fuente,
            'item_inventario_id': self.item_inventario_id,
            # Etapa 2 base IA
            'zona': self.zona,
            'modalidad': self.modalidad,
            'codigo_proveedor': self.codigo_proveedor,
            'import_batch_id': self.import_batch_id,
        }
