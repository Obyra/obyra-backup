"""
Caja A - Facturas administrativas por obra (Fase 1 MVP)
========================================================

Modelo de facturas/comprobantes cargados contra una obra. NO impactan en
costo_real automaticamente — son administrativas. La promocion a Caja B
(costo real) se hace por accion explicita del admin/PM en Fase 3.

Decisiones de producto MVP:
  - Adjunto OBLIGATORIO para tipo_comprobante in (factura_a, factura_b,
    factura_c, factura). Opcional para recibo, remito, otro.
  - Una factura corresponde a UNA persona (usuario interno OR proveedor
    OR nombre externo). Sin split entre varios.
  - Carga: solo admin/PM (operario queda para fase posterior con aprobacion).
  - Moneda: ARS o USD. Si USD, guardar tipo de cambio del dia.
"""
from datetime import datetime, date
from extensions import db


TIPOS_COMPROBANTE = (
    'factura_a', 'factura_b', 'factura_c', 'factura',
    'remito', 'recibo', 'nota_credito', 'nota_debito', 'otro',
)

ESTADOS_FACTURA = ('pendiente', 'pagada', 'rechazada', 'observada')

# Forma de pago: define con quien queda la deuda (o si nace ya pagada).
# - cuenta_corriente_proveedor: la obra le debe al proveedor.
# - usuario_bolsillo: el comprador interno puso plata de su bolsillo, hay que reintegrarle.
# - caja_obra: pagada con caja en obra (no hay deuda).
# - caja_oficina: pagada con caja oficina (no hay deuda).
# - otro: caso atipico (cheque diferido, mercado pago empresa, etc).
FORMAS_PAGO = (
    'cuenta_corriente_proveedor',
    'usuario_bolsillo',
    'caja_obra',
    'caja_oficina',
    'otro',
)

# Formas de pago que YA pagan al cargar (no generan deuda pendiente).
FORMAS_PAGO_YA_PAGADAS = ('caja_obra', 'caja_oficina')


def deuda_con_para(forma_pago: str) -> str:
    """Devuelve 'proveedor', 'usuario', o 'ninguno' segun la forma de pago."""
    if forma_pago == 'cuenta_corriente_proveedor':
        return 'proveedor'
    if forma_pago == 'usuario_bolsillo':
        return 'usuario'
    return 'ninguno'


def adjunto_es_obligatorio(tipo_comprobante: str) -> bool:
    """Reglas para validacion server-side."""
    return (tipo_comprobante or '').strip().lower() in (
        'factura_a', 'factura_b', 'factura_c', 'factura',
    )


class ObraFactura(db.Model):
    """Factura/comprobante cargado en Caja A de una obra.

    Caja A es ADMINISTRATIVA: registra que se cargo el comprobante y a
    quien hay que pagarle. NO suma a obra.costo_real salvo que en Fase 3
    se promueva explicitamente a Caja B.
    """

    __tablename__ = 'obra_facturas'

    id = db.Column(db.Integer, primary_key=True)

    # Multi-tenant
    organizacion_id = db.Column(db.Integer,
                                 db.ForeignKey('organizaciones.id'),
                                 nullable=False, index=True)
    obra_id = db.Column(db.Integer,
                         db.ForeignKey('obras.id'),
                         nullable=False, index=True)

    # Identificacion del comprobante
    tipo_comprobante = db.Column(db.String(20), nullable=False, default='factura')
    numero_factura = db.Column(db.String(50))         # Opcional: "A-0001-00012345"
    concepto = db.Column(db.String(300), nullable=False)

    # Fechas
    fecha_factura = db.Column(db.Date, nullable=False)
    fecha_carga = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Importes
    importe = db.Column(db.Numeric(15, 2), nullable=False)
    moneda = db.Column(db.String(3), nullable=False, default='ARS')
    # Si moneda=USD, capturamos tipo de cambio del dia al cargar.
    tipo_cambio_usado = db.Column(db.Numeric(15, 4), nullable=True)
    importe_ars = db.Column(db.Numeric(15, 2), nullable=True)  # importe * TC si USD

    # === Modelo 3 actores (refactor 2026-05-13) ===
    # 1) Proveedor: quien emite la factura. Opcional (puede ser un gasto sin
    #    proveedor formal cargado, ej. fletero eventual).
    proveedor_id = db.Column(db.Integer,
                              db.ForeignKey('proveedores_oc.id', ondelete='SET NULL'),
                              nullable=True, index=True)
    proveedor_externo_nombre = db.Column(db.String(200), nullable=True)
    # 2) Comprador interno: el usuario que fue fisicamente a comprar.
    #    Default = quien carga la factura, editable si fue otra persona.
    comprado_por_user_id = db.Column(db.Integer,
                                      db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                      nullable=True, index=True)
    # 3) Forma de pago: define con quien queda la deuda.
    forma_pago = db.Column(db.String(40), nullable=True, index=True)

    # Auditoria
    cargada_por_user_id = db.Column(db.Integer,
                                     db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                     nullable=True)

    # Estado y pago
    estado = db.Column(db.String(20), nullable=False, default='pendiente', index=True)
    fecha_pago = db.Column(db.Date, nullable=True)
    pagada_por_user_id = db.Column(db.Integer,
                                    db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                    nullable=True)
    marcada_paga_at = db.Column(db.DateTime, nullable=True)
    motivo_rechazo = db.Column(db.Text, nullable=True)
    rechazada_por_user_id = db.Column(db.Integer,
                                       db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                       nullable=True)
    rechazada_at = db.Column(db.DateTime, nullable=True)
    observaciones = db.Column(db.Text)

    # Adjunto (path relativo a STORAGE_BASE/uploads/obras/<obra_id>/facturas/)
    archivo_path = db.Column(db.String(500), nullable=True)
    archivo_nombre_original = db.Column(db.String(255), nullable=True)
    archivo_mime = db.Column(db.String(80), nullable=True)
    archivo_tamano_bytes = db.Column(db.BigInteger, nullable=True)

    # Promocion a Caja B (Fase 3, en MVP queda en FALSE siempre)
    promovida_a_caja_b = db.Column(db.Boolean, nullable=False, default=False,
                                    server_default=db.text('false'))
    movimiento_caja_b_id = db.Column(db.Integer,
                                      db.ForeignKey('movimientos_caja.id', ondelete='SET NULL'),
                                      nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                            onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    obra = db.relationship('Obra', foreign_keys=[obra_id], backref='facturas_caja_a')
    proveedor = db.relationship('ProveedorOC', foreign_keys=[proveedor_id],
                                 backref='facturas_caja_a')
    comprador = db.relationship('Usuario', foreign_keys=[comprado_por_user_id])
    cargada_por = db.relationship('Usuario', foreign_keys=[cargada_por_user_id])
    pagada_por = db.relationship('Usuario', foreign_keys=[pagada_por_user_id])
    rechazada_por = db.relationship('Usuario', foreign_keys=[rechazada_por_user_id])
    auditoria = db.relationship('ObraFacturaAudit',
                                 back_populates='factura',
                                 cascade='all, delete-orphan',
                                 order_by='ObraFacturaAudit.created_at.desc()')

    __table_args__ = (
        db.Index('ix_obra_factura_obra_estado', 'obra_id', 'estado'),
        db.Index('ix_obra_factura_org_fecha', 'organizacion_id', 'fecha_factura'),
        db.Index('ix_obra_factura_proveedor', 'proveedor_id'),
        db.Index('ix_obra_factura_comprador', 'comprado_por_user_id'),
        db.CheckConstraint("moneda IN ('ARS', 'USD')", name='ck_obra_factura_moneda'),
        db.CheckConstraint(
            "estado IN ('pendiente', 'pagada', 'rechazada', 'observada')",
            name='ck_obra_factura_estado',
        ),
        db.CheckConstraint(
            "forma_pago IS NULL OR forma_pago IN ('cuenta_corriente_proveedor', "
            "'usuario_bolsillo', 'caja_obra', 'caja_oficina', 'otro')",
            name='ck_obra_factura_forma_pago',
        ),
    )

    def __repr__(self):
        return f'<ObraFactura #{self.id} obra={self.obra_id} {self.estado} ${self.importe}>'

    @property
    def proveedor_display(self) -> str:
        if self.proveedor_id and self.proveedor:
            return self.proveedor.razon_social
        if self.proveedor_externo_nombre:
            return self.proveedor_externo_nombre + ' (externo)'
        return '—'

    @property
    def comprador_display(self) -> str:
        if self.comprado_por_user_id and self.comprador:
            u = self.comprador
            nombre = f"{u.nombre or ''} {getattr(u, 'apellido', '') or ''}".strip()
            return nombre or u.email or f'Usuario #{u.id}'
        return '—'

    @property
    def deuda_con(self) -> str:
        """Quien queda como deudor segun forma_pago + estado.

        Returns: 'proveedor' | 'usuario' | 'ninguno'
        """
        if self.estado != 'pendiente':
            return 'ninguno'
        return deuda_con_para(self.forma_pago or '')

    @property
    def deuda_display(self) -> str:
        """Texto amigable de a quien se le debe (o '—' si no hay deuda)."""
        d = self.deuda_con
        if d == 'proveedor':
            return self.proveedor_display
        if d == 'usuario':
            return self.comprador_display
        return '—'

    @property
    def tiene_adjunto(self) -> bool:
        return bool(self.archivo_path)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'obra_id': self.obra_id,
            'tipo_comprobante': self.tipo_comprobante,
            'numero_factura': self.numero_factura,
            'concepto': self.concepto,
            'fecha_factura': self.fecha_factura.isoformat() if self.fecha_factura else None,
            'fecha_carga': self.fecha_carga.isoformat() if self.fecha_carga else None,
            'importe': float(self.importe) if self.importe is not None else 0,
            'moneda': self.moneda,
            'tipo_cambio_usado': float(self.tipo_cambio_usado) if self.tipo_cambio_usado else None,
            'importe_ars': float(self.importe_ars) if self.importe_ars is not None else None,
            # 3 actores
            'proveedor_id': self.proveedor_id,
            'proveedor_display': self.proveedor_display,
            'proveedor_externo_nombre': self.proveedor_externo_nombre,
            'comprado_por_user_id': self.comprado_por_user_id,
            'comprador_display': self.comprador_display,
            'forma_pago': self.forma_pago,
            # Deuda calculada
            'deuda_con': self.deuda_con,
            'deuda_display': self.deuda_display,
            'estado': self.estado,
            'fecha_pago': self.fecha_pago.isoformat() if self.fecha_pago else None,
            'tiene_adjunto': self.tiene_adjunto,
            'archivo_nombre_original': self.archivo_nombre_original,
            'observaciones': self.observaciones,
            'promovida_a_caja_b': self.promovida_a_caja_b,
        }


class ObraFacturaAudit(db.Model):
    """Bitacora de cambios sobre una factura para trazabilidad.

    Cada accion (crear, marcar pagada, rechazar, editar, observar) deja
    una fila aca con timestamp + usuario + detalle.
    """

    __tablename__ = 'obra_factura_audit'

    id = db.Column(db.Integer, primary_key=True)
    factura_id = db.Column(db.Integer,
                            db.ForeignKey('obra_facturas.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    accion = db.Column(db.String(40), nullable=False)
    # 'creada' | 'pagada' | 'rechazada' | 'observada' | 'editada' |
    # 'promovida_caja_b'
    user_id = db.Column(db.Integer,
                         db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                         nullable=True)
    detalle = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    factura = db.relationship('ObraFactura', back_populates='auditoria')
    usuario = db.relationship('Usuario', foreign_keys=[user_id])

    def __repr__(self):
        return f'<ObraFacturaAudit factura={self.factura_id} accion={self.accion}>'
