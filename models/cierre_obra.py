"""
Modelos para Cierre Formal de Obra y Acta de Entrega.

CierreObra: registra el proceso de cierre administrativo de una obra
            (verificación de tareas, certificaciones, materiales, etc.)

ActaEntrega: documento formal de entrega al cliente, vinculado al cierre.
             Incluye firma del cliente y observaciones finales.
"""
from datetime import datetime
from extensions import db


class CierreObra(db.Model):
    """
    Registro del cierre formal de una obra.
    Una obra puede tener un solo cierre activo (obra en estado 'finalizada').
    Si el cierre se anula, queda historial pero se permite crear uno nuevo.
    """
    __tablename__ = 'cierres_obra'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False, index=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)

    # Estado del cierre
    # estados: borrador, cerrado, anulado
    estado = db.Column(db.String(20), default='borrador', nullable=False)

    # Fechas
    fecha_inicio_cierre = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_cierre_definitivo = db.Column(db.DateTime, nullable=True)
    fecha_anulacion = db.Column(db.DateTime, nullable=True)

    # Responsables
    iniciado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    cerrado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True, index=True)
    anulado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True, index=True)

    # Datos del checklist (snapshot al momento del cierre)
    # JSON con: tareas_completadas, tareas_pendientes, certificaciones_cobradas,
    #            materiales_consumidos, presupuesto_real, observaciones
    checklist_data = db.Column(db.Text, nullable=True)

    # Observaciones del cierre
    observaciones = db.Column(db.Text, nullable=True)
    motivo_anulacion = db.Column(db.Text, nullable=True)

    # Datos financieros (snapshot)
    presupuesto_inicial = db.Column(db.Numeric(15, 2), nullable=True)
    monto_certificado = db.Column(db.Numeric(15, 2), nullable=True)
    monto_cobrado = db.Column(db.Numeric(15, 2), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    obra = db.relationship('Obra', backref=db.backref('cierres', lazy='dynamic'))
    iniciado_por = db.relationship('Usuario', foreign_keys=[iniciado_por_id])
    cerrado_por = db.relationship('Usuario', foreign_keys=[cerrado_por_id])
    anulado_por = db.relationship('Usuario', foreign_keys=[anulado_por_id])
    actas = db.relationship('ActaEntrega', back_populates='cierre',
                            cascade='all, delete-orphan', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_cierre_obra_org', 'organizacion_id', 'estado'),
    )

    def get_checklist(self) -> dict:
        """Devuelve el checklist parseado como dict."""
        import json
        if not self.checklist_data:
            return {}
        try:
            return json.loads(self.checklist_data)
        except (ValueError, TypeError):
            return {}

    def set_checklist(self, data: dict) -> None:
        """Guarda el checklist serializado como JSON."""
        import json
        self.checklist_data = json.dumps(data, default=str)

    @property
    def estado_display(self) -> str:
        return {
            'borrador': 'En proceso',
            'cerrado': 'Cerrado',
            'anulado': 'Anulado',
        }.get(self.estado, self.estado)

    @property
    def estado_badge_class(self) -> str:
        return {
            'borrador': 'bg-warning text-dark',
            'cerrado': 'bg-success',
            'anulado': 'bg-secondary',
        }.get(self.estado, 'bg-light text-dark')

    def __repr__(self):
        return f'<CierreObra obra={self.obra_id} estado={self.estado}>'


class ActaEntrega(db.Model):
    """
    Acta formal de entrega de la obra al cliente.
    Vinculada a un CierreObra. Puede haber múltiples actas
    (parcial, definitiva, recepción, etc.).
    """
    __tablename__ = 'actas_entrega'

    id = db.Column(db.Integer, primary_key=True)
    cierre_id = db.Column(db.Integer, db.ForeignKey('cierres_obra.id'), nullable=False, index=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False, index=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)

    # Tipo: provisoria, definitiva, parcial
    tipo = db.Column(db.String(20), default='definitiva', nullable=False)

    # Fechas
    fecha_acta = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    # Datos del cliente que recibe
    recibido_por_nombre = db.Column(db.String(200), nullable=False)
    recibido_por_dni = db.Column(db.String(20), nullable=True)
    recibido_por_cargo = db.Column(db.String(100), nullable=True)

    # Estado de la firma
    firmado = db.Column(db.Boolean, default=False)
    fecha_firma = db.Column(db.DateTime, nullable=True)
    firma_imagen_path = db.Column(db.String(500), nullable=True)  # Si se sube imagen de firma

    # Contenido del acta
    descripcion = db.Column(db.Text, nullable=True)
    observaciones_cliente = db.Column(db.Text, nullable=True)
    observaciones_internas = db.Column(db.Text, nullable=True)

    # Items entregados (lista descriptiva opcional)
    items_entregados = db.Column(db.Text, nullable=True)  # Texto libre

    # Garantías
    plazo_garantia_meses = db.Column(db.Integer, nullable=True)
    fecha_inicio_garantia = db.Column(db.Date, nullable=True)

    # Usuario que generó el acta
    creado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)

    # Relaciones
    cierre = db.relationship('CierreObra', back_populates='actas')
    obra = db.relationship('Obra')
    creado_por = db.relationship('Usuario', foreign_keys=[creado_por_id])

    __table_args__ = (
        db.Index('ix_acta_entrega_org', 'organizacion_id'),
    )

    @property
    def tipo_display(self) -> str:
        return {
            'provisoria': 'Provisoria',
            'definitiva': 'Definitiva',
            'parcial': 'Parcial',
        }.get(self.tipo, self.tipo)

    def __repr__(self):
        return f'<ActaEntrega obra={self.obra_id} tipo={self.tipo}>'
