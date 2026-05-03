"""Modelos legales: documentos versionados y registro de aceptaciones.

LegalDocument:
  Cada version de Terminos / Privacidad / Cookies / Politica de eliminacion
  queda como un registro versionado. Permite "publicar v1.1.0" sin perder v1.0.0.

UserConsent:
  Cada vez que un usuario acepta un documento, se guarda evidencia legal
  (version, fecha, IP, user agent). Sirve para auditoria, GDPR Art. 7
  y registro AAIP.
"""
from datetime import datetime, date
from extensions import db


TIPOS_DOCUMENTO = ('terminos', 'privacidad', 'cookies', 'eliminacion_datos')


class LegalDocument(db.Model):
    """Documento legal versionado (TOS, Privacidad, Cookies, etc.)."""
    __tablename__ = 'legal_documents'
    __table_args__ = (
        db.UniqueConstraint('tipo_documento', 'version', name='uq_legal_doc_tipo_version'),
        db.Index('ix_legal_doc_tipo_activo', 'tipo_documento', 'activo'),
    )

    id = db.Column(db.Integer, primary_key=True)
    tipo_documento = db.Column(db.String(40), nullable=False)  # terminos | privacidad | cookies | eliminacion_datos
    version = db.Column(db.String(40), nullable=False)         # ej: '1.0.0' o '2026-05-01'
    titulo = db.Column(db.String(200), nullable=False)
    contenido_html = db.Column(db.Text)                        # opcional: si es null, se renderiza el template estatico
    fecha_vigencia = db.Column(db.Date, nullable=False, default=date.today)
    # Si requiere_reaceptacion=True, todos los usuarios deben aceptar antes
    # de seguir operando (modal bloqueante). Para cambios cosmeticos dejar False.
    requiere_reaceptacion = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    activo = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    notas = db.Column(db.Text)                                 # cambios respecto de la version anterior
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    consents = db.relationship('UserConsent', back_populates='documento', cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<LegalDocument {self.tipo_documento} v{self.version}>'

    @property
    def descripcion(self):
        return f'{self.titulo} (v{self.version})'

    @classmethod
    def vigente(cls, tipo: str):
        """Devuelve el documento ACTIVO mas reciente del tipo dado."""
        return (
            cls.query
            .filter_by(tipo_documento=tipo, activo=True)
            .order_by(cls.fecha_vigencia.desc(), cls.id.desc())
            .first()
        )

    @classmethod
    def vigentes_por_tipo(cls):
        """Dict {tipo: LegalDocument vigente} para los 4 tipos canonicos."""
        return {tipo: cls.vigente(tipo) for tipo in TIPOS_DOCUMENTO}

    def to_dict(self):
        return {
            'id': self.id,
            'tipo_documento': self.tipo_documento,
            'version': self.version,
            'titulo': self.titulo,
            'fecha_vigencia': self.fecha_vigencia.isoformat() if self.fecha_vigencia else None,
            'requiere_reaceptacion': self.requiere_reaceptacion,
            'activo': self.activo,
        }


class UserConsent(db.Model):
    """Evidencia de aceptacion de un documento legal por parte de un usuario."""
    __tablename__ = 'user_consents'
    __table_args__ = (
        db.Index('ix_consent_user_doc', 'user_id', 'legal_document_id'),
        db.Index('ix_consent_user_tipo', 'user_id', 'tipo_documento'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='SET NULL'), nullable=True, index=True)
    legal_document_id = db.Column(db.Integer, db.ForeignKey('legal_documents.id', ondelete='RESTRICT'), nullable=False, index=True)

    # Datos denormalizados para queries rapidas y para preservar evidencia
    # incluso si el documento original cambia.
    tipo_documento = db.Column(db.String(40), nullable=False, index=True)
    version = db.Column(db.String(40), nullable=False)

    accepted = db.Column(db.Boolean, nullable=False, default=True)
    accepted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))                       # IPv4 o IPv6
    user_agent = db.Column(db.String(400))
    metodo = db.Column(db.String(40), default='checkbox_registro')  # checkbox_registro | modal_reacept | api | superadmin

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship('Usuario', backref=db.backref('consents', lazy='dynamic', cascade='all, delete-orphan'))
    documento = db.relationship('LegalDocument', back_populates='consents')

    def __repr__(self):
        return f'<UserConsent user={self.user_id} {self.tipo_documento} v{self.version}>'

    @classmethod
    def acepto(cls, user_id: int, legal_document_id: int) -> bool:
        """True si el usuario ya acepto ese documento especifico."""
        return cls.query.filter_by(
            user_id=user_id,
            legal_document_id=legal_document_id,
            accepted=True,
        ).first() is not None

    def to_dict(self):
        return {
            'id': self.id,
            'tipo_documento': self.tipo_documento,
            'version': self.version,
            'accepted': self.accepted,
            'accepted_at': self.accepted_at.isoformat() if self.accepted_at else None,
            'ip_address': self.ip_address,
            'metodo': self.metodo,
        }


def documentos_pendientes_para_usuario(user_id: int) -> list:
    """Devuelve la lista de LegalDocument vigentes que el usuario aun NO acepto.

    Se usa para el middleware bloqueante: si esta lista no esta vacia, mostrar
    modal hasta que el usuario acepte.

    Solo considera documentos con `requiere_reaceptacion=True` ademas de los
    nunca aceptados — los cambios cosmeticos no fuerzan al usuario.
    """
    pendientes = []
    vigentes = LegalDocument.vigentes_por_tipo()
    for tipo, doc in vigentes.items():
        if not doc:
            continue
        ya_acepto_esta = UserConsent.acepto(user_id, doc.id)
        if ya_acepto_esta:
            continue
        # Si no acepto ESTA version pero acepto una anterior, depende del flag.
        if doc.requiere_reaceptacion:
            pendientes.append(doc)
            continue
        # Si nunca acepto NINGUNA version del tipo (ej: usuario antiguo sin consent)
        ya_tiene_alguna = UserConsent.query.filter_by(
            user_id=user_id,
            tipo_documento=tipo,
            accepted=True,
        ).first() is not None
        if not ya_tiene_alguna:
            pendientes.append(doc)
    return pendientes
