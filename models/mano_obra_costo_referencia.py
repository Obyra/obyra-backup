"""Costo empresa de mano de obra (Fase 5.A - referencia Gedif).

Modelo separado de CategoriaJornal y EscalaSalarialUOCRA para no romper el
flujo actual. Aca se guarda el COSTO EMPRESA REAL incluyendo cargas, aportes,
contribuciones, SAC, vacaciones, comida, EPP, IERIC, UOCRA, fondo desempleo,
bono anual, etc.

La Calculadora IA usa costo_empresa_hora como precio principal de mano de
obra (no el jornal liso).

Multi-tenant hibrido:
  organizacion_id = NULL -> curado por OBYRA, visible a todos los tenants.
  organizacion_id = X    -> privado del tenant X (override de la version global).
"""
from datetime import datetime, date
from decimal import Decimal

from extensions import db


# Catalogo abierto de categorias canonicas. Se permiten valores fuera de la
# lista (ej: oficial_soldador, capataz) — solo es referencia para UI/heuristica.
CATEGORIAS_BASE = (
    'oficial_especializado',
    'oficial',
    'medio_oficial',
    'ayudante',
    'sereno',
)


class ManoObraCostoReferencia(db.Model):
    """Referencia de costo empresa por hora/jornal/mes para mano de obra."""
    __tablename__ = 'mano_obra_costo_referencia'
    __table_args__ = (
        db.UniqueConstraint('organizacion_id', 'categoria', 'zona', 'periodo',
                            name='uq_mocr_org_cat_zona_periodo'),
        db.Index('ix_mocr_org_cat_zona', 'organizacion_id', 'categoria', 'zona'),
        db.Index('ix_mocr_vigencia', 'fecha_vigencia_desde', 'fecha_vigencia_hasta'),
        db.Index('ix_mocr_activo', 'activo'),
    )

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                nullable=True, index=True)  # NULL = global

    # Identidad
    categoria = db.Column(db.String(60), nullable=False)        # 'oficial', 'oficial_especializado', etc.
    descripcion = db.Column(db.String(120), nullable=True)      # "Oficial especializado" (display)
    zona = db.Column(db.String(40), nullable=False, default='CABA')
    periodo = db.Column(db.String(7), nullable=False)            # 'YYYY-MM'

    # Vigencia
    fecha_vigencia_desde = db.Column(db.Date, nullable=False, default=date.today)
    fecha_vigencia_hasta = db.Column(db.Date, nullable=True)

    # Base hora convenio (input)
    valor_hora_convenio = db.Column(db.Numeric(12, 2), nullable=False)
    valor_jornal_convenio = db.Column(db.Numeric(12, 2), nullable=True)  # calculado: hora * 8
    horas_mensuales = db.Column(db.Integer, nullable=False, default=176)

    # Adicionales sobre hora convenio (% o monto)
    presentismo_pct = db.Column(db.Numeric(5, 2), nullable=False, default=20)
    hh_50_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    hh_100_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    adicional_fijo_hora = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    # Calculados intermedios (auditoria)
    bruto_estimado_hora = db.Column(db.Numeric(12, 2), nullable=True)
    neto_estimado_hora = db.Column(db.Numeric(12, 2), nullable=True)

    # Cargas y aportes (% sobre bruto)
    f931_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    fondo_desempleo_pct = db.Column(db.Numeric(5, 2), nullable=False, default=12)
    uocra_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    ieric_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)

    # SAC y vacaciones (% sobre bruto)
    sac_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    vacaciones_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)

    # Adicionales fijos (monto mensual, se prorratea por hora)
    comida_monto_mes = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    epp_monto_mes = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    bono_anual_monto = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    # Resultados (lo que usa la Calculadora IA)
    costo_empresa_hora = db.Column(db.Numeric(12, 2), nullable=True)
    costo_empresa_jornal_8h = db.Column(db.Numeric(12, 2), nullable=True)
    costo_empresa_mes_176h = db.Column(db.Numeric(12, 2), nullable=True)

    # Auditoria de la fuente
    fuente = db.Column(db.String(40), nullable=False, default='planilla_constructora_gedif',
                       server_default='planilla_constructora_gedif')
    confianza = db.Column(db.String(20), nullable=False, default='media', server_default='media')
    observaciones = db.Column(db.Text, nullable=True)
    parametros_supuestos_json = db.Column(db.JSON, nullable=True)
    valores_excel_originales_json = db.Column(db.JSON, nullable=True)  # snapshot del Excel

    # Aprobacion y estado
    aprobado_por_user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                     nullable=True)
    aprobado_at = db.Column(db.DateTime, nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, server_default='true')

    created_by_user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                   nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    aprobado_por = db.relationship('Usuario', foreign_keys=[aprobado_por_user_id])
    created_by = db.relationship('Usuario', foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f'<ManoObraCostoReferencia {self.categoria}@{self.zona} {self.periodo} ${self.costo_empresa_hora}>'

    @property
    def is_global(self):
        return self.organizacion_id is None

    def recalcular(self):
        """Recalcula bruto, neto, costo_empresa_hora/jornal/mes desde los
        parametros base. Se llama al guardar (decision: recalcular siempre,
        no confiar en valores del Excel).

        Formula:
          bruto_hora = valor_hora * (1 + (presentismo + hh_50 + hh_100) / 100)
                      + adicional_fijo_hora
          cargas_pct = f931 + fondo_desempleo + uocra + ieric + sac + vacaciones
          costo_h = bruto_hora * (1 + cargas_pct/100)
                   + (comida_mes + epp_mes + bono_anual/12) / horas_mensuales
        """
        v = self._d
        valor_hora = v(self.valor_hora_convenio)
        if valor_hora <= 0:
            return

        self.valor_jornal_convenio = (valor_hora * Decimal('8')).quantize(Decimal('0.01'))

        # Bruto hora (valor convenio + presentismo + extras + adicional)
        factor_bruto = Decimal('1') + (
            v(self.presentismo_pct) + v(self.hh_50_pct) + v(self.hh_100_pct)
        ) / Decimal('100')
        bruto = valor_hora * factor_bruto + v(self.adicional_fijo_hora)
        self.bruto_estimado_hora = bruto.quantize(Decimal('0.01'))

        # Neto estimado: bruto - aportes del trabajador (no se usa para costo
        # empresa, pero sirve como auditoria visible). Aproximamos 17%.
        self.neto_estimado_hora = (bruto * Decimal('0.83')).quantize(Decimal('0.01'))

        # Cargas porcentuales sobre bruto
        cargas_pct = (
            v(self.f931_pct) + v(self.fondo_desempleo_pct) + v(self.uocra_pct)
            + v(self.ieric_pct) + v(self.sac_pct) + v(self.vacaciones_pct)
        )
        bruto_con_cargas = bruto * (Decimal('1') + cargas_pct / Decimal('100'))

        # Adicionales fijos prorrateados por hora
        horas_mes = Decimal(str(self.horas_mensuales or 176))
        if horas_mes <= 0:
            horas_mes = Decimal('176')
        adicionales_fijos_mes = (
            v(self.comida_monto_mes) + v(self.epp_monto_mes)
            + v(self.bono_anual_monto) / Decimal('12')
        )
        adicionales_por_hora = adicionales_fijos_mes / horas_mes

        costo_h = (bruto_con_cargas + adicionales_por_hora).quantize(Decimal('0.01'))
        self.costo_empresa_hora = costo_h
        self.costo_empresa_jornal_8h = (costo_h * Decimal('8')).quantize(Decimal('0.01'))
        self.costo_empresa_mes_176h = (costo_h * horas_mes).quantize(Decimal('0.01'))

    @staticmethod
    def _d(v):
        if v is None:
            return Decimal('0')
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal('0')

    def to_dict(self):
        return {
            'id': self.id,
            'organizacion_id': self.organizacion_id,
            'is_global': self.is_global,
            'categoria': self.categoria,
            'descripcion': self.descripcion,
            'zona': self.zona,
            'periodo': self.periodo,
            'fecha_vigencia_desde': self.fecha_vigencia_desde.isoformat() if self.fecha_vigencia_desde else None,
            'fecha_vigencia_hasta': self.fecha_vigencia_hasta.isoformat() if self.fecha_vigencia_hasta else None,
            'valor_hora_convenio': float(self.valor_hora_convenio or 0),
            'valor_jornal_convenio': float(self.valor_jornal_convenio or 0),
            'horas_mensuales': self.horas_mensuales,
            'presentismo_pct': float(self.presentismo_pct or 0),
            'hh_50_pct': float(self.hh_50_pct or 0),
            'hh_100_pct': float(self.hh_100_pct or 0),
            'adicional_fijo_hora': float(self.adicional_fijo_hora or 0),
            'bruto_estimado_hora': float(self.bruto_estimado_hora or 0),
            'neto_estimado_hora': float(self.neto_estimado_hora or 0),
            'f931_pct': float(self.f931_pct or 0),
            'fondo_desempleo_pct': float(self.fondo_desempleo_pct or 0),
            'uocra_pct': float(self.uocra_pct or 0),
            'ieric_pct': float(self.ieric_pct or 0),
            'sac_pct': float(self.sac_pct or 0),
            'vacaciones_pct': float(self.vacaciones_pct or 0),
            'comida_monto_mes': float(self.comida_monto_mes or 0),
            'epp_monto_mes': float(self.epp_monto_mes or 0),
            'bono_anual_monto': float(self.bono_anual_monto or 0),
            'costo_empresa_hora': float(self.costo_empresa_hora or 0),
            'costo_empresa_jornal_8h': float(self.costo_empresa_jornal_8h or 0),
            'costo_empresa_mes_176h': float(self.costo_empresa_mes_176h or 0),
            'fuente': self.fuente,
            'confianza': self.confianza,
            'observaciones': self.observaciones,
            'aprobado_por_user_id': self.aprobado_por_user_id,
            'aprobado_at': self.aprobado_at.isoformat() if self.aprobado_at else None,
            'activo': self.activo,
        }


def categoria_canonica_para(descripcion: str) -> str:
    """Heuristica: mapea descripcion de composicion -> categoria canonica.

    Reglas (en orden de prioridad):
      'oficial especializado' -> 'oficial_especializado'
      'medio oficial'         -> 'medio_oficial'
      'ayudante'              -> 'ayudante'
      'sereno'                -> 'sereno'
      'oficial' (sin las anteriores) -> 'oficial'
      otro                    -> '' (sin match)

    Matching es case-insensitive y sin acentos.
    """
    if not descripcion:
        return ''
    import unicodedata
    s = unicodedata.normalize('NFD', str(descripcion).lower()).encode('ascii', 'ignore').decode('ascii')

    if 'oficial especializado' in s:
        return 'oficial_especializado'
    if 'medio oficial' in s or 'medio_oficial' in s:
        return 'medio_oficial'
    if 'ayudante' in s:
        return 'ayudante'
    if 'sereno' in s:
        return 'sereno'
    if 'oficial' in s:
        return 'oficial'
    return ''
