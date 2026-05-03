"""Modelos para aprendizaje continuo de la Calculadora IA (Fase B).

IACorrectionLog
    Una fila por cada vez que el usuario aplica una sugerencia de la IA al
    presupuesto, registrando el diff entre lo que sugirio la IA y lo que
    finalmente quedo en el item. Sirve para detectar patrones de correccion
    y ofrecer dataset de entrenamiento futuro.

IARuleCandidate
    Candidatas a nuevas reglas tecnicas. Una fila por descripcion_normalizada
    unica. Cada nueva correccion sobre la misma desc_normalizada incrementa
    cantidad_ocurrencias y actualiza los promedios. Solo cambia de estado por
    accion explicita del Super Admin.

IARuleUsageStat
    Estadisticas de uso por regla tecnica (id string del REGLAS_TECNICAS en
    services/base_tecnica_computos.py). Se actualiza upsert dentro del mismo
    endpoint que aplica la IA.

Notas:
- Todos los JSON usan db.JSON (JSONB en PostgreSQL, TEXT-as-json en SQLite).
  No hacemos queries con operadores JSON; los filtros agregados se hacen
  en Python o con SELECT/COUNT clasicos para mantener portabilidad.
- ondelete='SET NULL' en organizacion_id / user_id para preservar evidencia
  historica si la organizacion o el usuario son eliminados (anonimizacion).
"""
from datetime import datetime
from extensions import db


# Catalogo de tipos de correccion (string canonico, almacenado en
# IACorrectionLog.tipos_correccion como array JSON):
TIPOS_CORRECCION = (
    'aceptada_sin_editar',
    'editada_descripcion',
    'editada_rubro',
    'editada_etapa',
    'editada_unidad',
    'editada_materiales',
    'editada_maquinaria',
    'editada_mano_obra',
    'aplicada_baja_confianza',
    'aplicada_media_confianza',
    'aplicada_alta_confianza',
    'creada_manual_sin_sugerencia',
)

# Estados de candidata
ESTADOS_CANDIDATA = ('pendiente', 'aprobada', 'rechazada', 'convertida_en_regla')


class IACorrectionLog(db.Model):
    """Log de correcciones a sugerencias IA aplicadas a items de presupuesto."""
    __tablename__ = 'ia_correction_log'
    __table_args__ = (
        db.Index('ix_iacorr_org_created', 'organizacion_id', 'created_at'),
        db.Index('ix_iacorr_descnorm', 'descripcion_normalizada'),
        db.Index('ix_iacorr_regla', 'regla_tecnica_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='SET NULL'),
                                nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                        nullable=True, index=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id', ondelete='CASCADE'),
                               nullable=True, index=True)
    item_presupuesto_id = db.Column(db.Integer, db.ForeignKey('items_presupuesto.id', ondelete='CASCADE'),
                                    nullable=True, index=True)

    descripcion_original = db.Column(db.String(500), nullable=False)
    descripcion_normalizada = db.Column(db.String(500), nullable=False)

    # Estructura: lo que sugirio la IA (rubro, etapa, unidad, materiales, maquinaria,
    # confianza, regla_id, observaciones) tal cual vino del servicio determinista.
    sugerencia_original_json = db.Column(db.JSON, nullable=True)

    # Estructura: solo campos estructurados que el usuario dejo aplicar
    # (rubro, etapa, unidad, descripcion, materiales, maquinaria, mano_obra).
    # NO se guardan observaciones libres por confidencialidad.
    correccion_usuario_json = db.Column(db.JSON, nullable=True)

    # Array de strings con los tipos de correccion detectados en este item.
    # Ejemplo: ["editada_rubro", "editada_unidad", "aplicada_baja_confianza"]
    tipos_correccion = db.Column(db.JSON, nullable=True)

    confianza_original = db.Column(db.Float, nullable=True)
    regla_tecnica_id = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    usuario = db.relationship('Usuario', foreign_keys=[user_id])

    def __repr__(self):
        return f'<IACorrectionLog id={self.id} item={self.item_presupuesto_id} regla={self.regla_tecnica_id}>'


class IARuleCandidate(db.Model):
    """Candidatas a nuevas reglas tecnicas, agregadas por descripcion_normalizada."""
    __tablename__ = 'ia_rule_candidate'
    __table_args__ = (
        db.UniqueConstraint('descripcion_normalizada', name='uq_iarc_descnorm'),
        db.Index('ix_iarc_estado_count', 'estado', 'cantidad_ocurrencias'),
    )

    id = db.Column(db.Integer, primary_key=True)
    descripcion_original = db.Column(db.String(500), nullable=False)  # primera ocurrencia, representativa
    descripcion_normalizada = db.Column(db.String(500), nullable=False)

    # Sugerencias predominantes (string mas votado entre las correcciones que la formaron).
    rubro_sugerido = db.Column(db.String(100), nullable=True)
    etapa_sugerida = db.Column(db.String(100), nullable=True)
    unidad_sugerida = db.Column(db.String(20), nullable=True)

    # JSON: {nombre_material: cantidad_veces_sugerido} y {nombre_maquinaria: cantidad}
    materiales_sugeridos_json = db.Column(db.JSON, nullable=True)
    maquinaria_sugerida_json = db.Column(db.JSON, nullable=True)

    cantidad_ocurrencias = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    confianza_promedio = db.Column(db.Float, nullable=True)

    # pendiente | aprobada | rechazada | convertida_en_regla
    estado = db.Column(db.String(40), nullable=False, default='pendiente', server_default='pendiente', index=True)

    # Trazabilidad de aprobacion/rechazo
    aprobada_por_user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True)
    aprobada_at = db.Column(db.DateTime, nullable=True)
    notas_admin = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    aprobada_por = db.relationship('Usuario', foreign_keys=[aprobada_por_user_id])

    def __repr__(self):
        return f'<IARuleCandidate id={self.id} estado={self.estado} ocurr={self.cantidad_ocurrencias}>'

    def to_dict(self):
        return {
            'id': self.id,
            'descripcion_original': self.descripcion_original,
            'descripcion_normalizada': self.descripcion_normalizada,
            'rubro_sugerido': self.rubro_sugerido,
            'etapa_sugerida': self.etapa_sugerida,
            'unidad_sugerida': self.unidad_sugerida,
            'cantidad_ocurrencias': self.cantidad_ocurrencias,
            'confianza_promedio': float(self.confianza_promedio) if self.confianza_promedio else None,
            'estado': self.estado,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class IARuleUsageStat(db.Model):
    """Estadistica acumulativa por regla tecnica (id string del REGLAS_TECNICAS)."""
    __tablename__ = 'ia_rule_usage_stat'
    __table_args__ = (
        db.UniqueConstraint('regla_tecnica_id', name='uq_iarus_regla'),
    )

    id = db.Column(db.Integer, primary_key=True)
    regla_tecnica_id = db.Column(db.String(80), nullable=False)

    cantidad_usos = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    cantidad_aceptadas_sin_edicion = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    cantidad_editadas = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    cantidad_rechazadas = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    confianza_promedio = db.Column(db.Float, nullable=True)
    ultima_utilizacion = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<IARuleUsageStat regla={self.regla_tecnica_id} usos={self.cantidad_usos}>'

    def to_dict(self):
        return {
            'id': self.id,
            'regla_tecnica_id': self.regla_tecnica_id,
            'cantidad_usos': self.cantidad_usos,
            'cantidad_aceptadas_sin_edicion': self.cantidad_aceptadas_sin_edicion,
            'cantidad_editadas': self.cantidad_editadas,
            'cantidad_rechazadas': self.cantidad_rechazadas,
            'confianza_promedio': float(self.confianza_promedio) if self.confianza_promedio else None,
            'ultima_utilizacion': self.ultima_utilizacion.isoformat() if self.ultima_utilizacion else None,
        }
