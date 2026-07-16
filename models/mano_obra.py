# -*- coding: utf-8 -*-
"""Costo empresa de mano de obra — modelo NORMALIZADO (Fase 2.0 IA presupuestos).

Reemplaza el enfoque denormalizado de `ManoObraCostoReferencia` (que horneaba
los recargos por fila de categoria). Aca el costo/hh se calcula a partir de
tres piezas separadas, de modo que actualizar la paritaria recalcula todo:

  1. BASICO por categoria  -> `CategoriaJornal` (models/budgets.py), reusada.
     Es el input de la paritaria: hora convenio por categoria + vigencia.

  2. RECARGOS parametrizados -> `EstructuraRecargosMO` + `RecargoMOLinea` (aqui).
     Una estructura = un set de lineas (presentismo, F931, UOCRA, comida, ...),
     COMPARTIDA por todas las categorias. Editable en un solo lugar. Cada linea
     declara su propia base y periodicidad (tipo_calculo), asi reproduce una
     planilla de costo laboral real linea por linea (mezcla de % y montos).

  3. INDICES (ICAC/ICP) -> `IndiceActualizacion` (aqui).
     Serie temporal para reindexar presupuestos viejos. General (MO y materiales).

El costo/hh se computa on-demand en services/costo_mano_obra.py; no se persiste
(salvo que un presupuesto congele su valor).

Multi-tenant hibrido: organizacion_id NULL = curado por OBYRA (global, visible a
todos los tenants); con valor = privado del tenant (override de la version global).
"""
from datetime import datetime, date

from extensions import db


# --- Vocabulario de las lineas de recargo -----------------------------------

# Grupo: define el orden de aplicacion en la formula.
#   adicional_remunerativo  -> se suma al basico para formar el BRUTO
#   carga_social            -> se aplica sobre el bruto (aportes/contribuciones)
#   adicional_no_remunerativo -> montos fijos que no son remuneracion (comida, EPP)
GRUPOS_RECARGO = ('adicional_remunerativo', 'carga_social', 'adicional_no_remunerativo')

# tipo_calculo: como se interpreta `valor` y contra que base.
#   pct_hora_convenio -> valor% sobre la hora convenio (basico)
#   pct_bruto         -> valor% sobre el bruto/hora
#   monto_hora        -> $ por hora
#   monto_dia         -> $ por dia (se prorratea /horas_por_dia)
#   monto_mes         -> $ por mes (se prorratea /horas_mensuales)
#   monto_anio        -> $ por anio (se prorratea /(horas_mensuales*12))
TIPOS_CALCULO = (
    'pct_hora_convenio', 'pct_bruto',
    'monto_hora', 'monto_dia', 'monto_mes', 'monto_anio',
)


class EstructuraRecargosMO(db.Model):
    """Cabecera de una estructura de recargos de mano de obra (compartida)."""
    __tablename__ = 'estructura_recargos_mo'
    __table_args__ = (
        db.Index('ix_erm_org_zona', 'organizacion_id', 'zona'),
        db.Index('ix_erm_vigencia', 'vigencia_desde', 'vigencia_hasta'),
        db.Index('ix_erm_activo', 'activo'),
    )

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                nullable=True, index=True)  # NULL = global OBYRA

    nombre = db.Column(db.String(120), nullable=False, default='Estructura de recargos')
    zona = db.Column(db.String(40), nullable=False, default='CABA')

    # Vigencia (para historial: al cargar la nueva se cierra la anterior con hasta)
    vigencia_desde = db.Column(db.Date, nullable=False, default=date.today)
    vigencia_hasta = db.Column(db.Date, nullable=True)

    # Parametros de prorrateo de los montos fijos
    horas_mensuales = db.Column(db.Integer, nullable=False, default=176)
    horas_por_dia = db.Column(db.Integer, nullable=False, default=8)

    fuente = db.Column(db.String(60), nullable=False, default='manual')
    notas = db.Column(db.Text, nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, server_default='true')

    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                              nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                           nullable=False)

    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    lineas = db.relationship('RecargoMOLinea', back_populates='estructura',
                             cascade='all, delete-orphan',
                             order_by='RecargoMOLinea.orden')

    @property
    def is_global(self):
        return self.organizacion_id is None

    def to_dict(self, incluir_lineas=True):
        d = {
            'id': self.id,
            'organizacion_id': self.organizacion_id,
            'is_global': self.is_global,
            'nombre': self.nombre,
            'zona': self.zona,
            'vigencia_desde': self.vigencia_desde.isoformat() if self.vigencia_desde else None,
            'vigencia_hasta': self.vigencia_hasta.isoformat() if self.vigencia_hasta else None,
            'horas_mensuales': self.horas_mensuales,
            'horas_por_dia': self.horas_por_dia,
            'fuente': self.fuente,
            'notas': self.notas,
            'activo': self.activo,
        }
        if incluir_lineas:
            d['lineas'] = [l.to_dict() for l in self.lineas]
        return d

    def __repr__(self):
        return f'<EstructuraRecargosMO {self.nombre}@{self.zona} ({len(self.lineas)} lineas)>'


class RecargoMOLinea(db.Model):
    """Una linea de recargo dentro de una estructura (presentismo, F931, ...)."""
    __tablename__ = 'recargo_mo_linea'
    __table_args__ = (
        db.Index('ix_rml_estructura', 'estructura_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    estructura_id = db.Column(db.Integer,
                              db.ForeignKey('estructura_recargos_mo.id', ondelete='CASCADE'),
                              nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0)

    concepto = db.Column(db.String(80), nullable=False)          # "Presentismo", "F.931", "Comida"
    grupo = db.Column(db.String(30), nullable=False)             # ver GRUPOS_RECARGO
    tipo_calculo = db.Column(db.String(20), nullable=False)      # ver TIPOS_CALCULO
    valor = db.Column(db.Numeric(14, 4), nullable=False, default=0)  # % o monto segun tipo

    notas = db.Column(db.String(200), nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True, server_default='true')

    estructura = db.relationship('EstructuraRecargosMO', back_populates='lineas')

    def to_dict(self):
        return {
            'id': self.id,
            'estructura_id': self.estructura_id,
            'orden': self.orden,
            'concepto': self.concepto,
            'grupo': self.grupo,
            'tipo_calculo': self.tipo_calculo,
            'valor': float(self.valor or 0),
            'notas': self.notas,
            'activo': self.activo,
        }

    def __repr__(self):
        return f'<RecargoMOLinea {self.concepto} {self.tipo_calculo}={self.valor}>'


class IndiceActualizacion(db.Model):
    """Serie de indices para reindexar presupuestos viejos (ICAC/ICP/ICC).

    Uso (Fase 2.0e): precio_hoy = precio_congelado * (indice[hoy]/indice[base]),
    por capitulo (MO con ICAC-MO, materiales con ICAC-materiales).
    """
    __tablename__ = 'indice_actualizacion'
    __table_args__ = (
        db.UniqueConstraint('organizacion_id', 'tipo', 'capitulo', 'periodo',
                            name='uq_indice_org_tipo_cap_periodo'),
        db.Index('ix_indice_tipo_cap', 'tipo', 'capitulo'),
    )

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                nullable=True, index=True)  # NULL = global

    tipo = db.Column(db.String(10), nullable=False)             # 'ICAC' | 'ICP' | 'ICC'
    capitulo = db.Column(db.String(30), nullable=False, default='general')  # general|mano_de_obra|materiales
    periodo = db.Column(db.String(7), nullable=False)           # 'YYYY-MM'
    valor_indice = db.Column(db.Numeric(16, 4), nullable=False)

    fuente = db.Column(db.String(60), nullable=False, default='manual')
    notas = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                           nullable=False)

    @property
    def is_global(self):
        return self.organizacion_id is None

    def to_dict(self):
        return {
            'id': self.id,
            'organizacion_id': self.organizacion_id,
            'tipo': self.tipo,
            'capitulo': self.capitulo,
            'periodo': self.periodo,
            'valor_indice': float(self.valor_indice or 0),
            'fuente': self.fuente,
        }

    def __repr__(self):
        return f'<IndiceActualizacion {self.tipo}/{self.capitulo} {self.periodo}={self.valor_indice}>'
