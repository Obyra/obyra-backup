"""Perfil tecnico del proyecto (Fase 2 - asistente de obra).

Vive primero asociado a Presupuesto (estructura comercial). Cuando el
presupuesto se confirma como obra, se replica/clona la relacion a Obra
(en una fase futura: hoy solo se guarda obra_id NULL).

Sirve como contexto adicional para:
  - la Calculadora IA (mejor distribucion de cantidades por piso),
  - el Presupuesto Ejecutivo (organizacion por nivel),
  - la generacion automatica de niveles (NivelPresupuesto).

Multi-tenant: organizacion_id obligatorio. ondelete sigue al presupuesto.
"""
from datetime import datetime
from extensions import db


# Catalogos canonicos (validados a nivel aplicacion, no enum BD para
# permitir crecer sin migracion)
TIPOS_OBRA = (
    'edificio',
    'vivienda_unifamiliar',
    'galpon',
    'local_comercial',
    'remodelacion',
    'obra_publica',
    'infraestructura',
    'otro',
)

TIPOS_ESTRUCTURA = (
    'hormigon_armado',
    'metalica',
    'mixta',
    'mamposteria_portante',
    'no_definida',
)

TIPOS_FUNDACION = (
    'platea',
    'bases_aisladas',
    'bases_corridas',
    'pilotes',
    'pilotines',
    'zapatas',
    'no_definida',
)

CRITERIOS_DISTRIBUCION = (
    'por_piso_automatico',
    'por_piso_manual',
    'por_sector',
    'por_torre',
    'sin_distribuir',
)

CANTIDADES_EXCEL_SON_TOTALES = ('si', 'no', 'no_se')


class ProjectTechnicalProfile(db.Model):
    """Perfil tecnico de obra/proyecto."""
    __tablename__ = 'project_technical_profile'
    __table_args__ = (
        db.UniqueConstraint('presupuesto_id', name='uq_ptp_presupuesto'),
        db.Index('ix_ptp_org', 'organizacion_id'),
        db.Index('ix_ptp_obra', 'obra_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                nullable=False, index=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id', ondelete='CASCADE'),
                               nullable=True, index=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id', ondelete='SET NULL'),
                        nullable=True, index=True)

    # ===== Tipologia =====
    tipo_obra = db.Column(db.String(40), nullable=False, default='edificio', server_default='edificio')
    naturaleza_proyecto = db.Column(db.String(40), nullable=False,
                                    default='obra_nueva', server_default='obra_nueva')
    tipo_estructura = db.Column(db.String(40), nullable=False,
                                default='no_definida', server_default='no_definida')
    tipo_fundacion = db.Column(db.String(40), nullable=False,
                               default='no_definida', server_default='no_definida')
    sistema_constructivo = db.Column(db.String(200), nullable=True)

    # ===== Geometria =====
    cantidad_pisos = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    cantidad_subsuelos = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    tiene_planta_baja = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    tiene_terraza = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    superficie_total_m2 = db.Column(db.Numeric(12, 2), nullable=True)
    superficie_por_planta_m2 = db.Column(db.Numeric(12, 2), nullable=True)
    altura_promedio_piso_m = db.Column(db.Numeric(6, 2), nullable=True)
    espesor_losa_cm = db.Column(db.Numeric(6, 2), nullable=True)

    # ===== Estructura del proyecto =====
    cantidad_torres = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    cantidad_unidades_funcionales = db.Column(db.Integer, nullable=True)
    cantidad_cocheras = db.Column(db.Integer, nullable=True)

    # ===== Criterios de la Calculadora IA =====
    criterio_distribucion = db.Column(db.String(40), nullable=False,
                                      default='sin_distribuir', server_default='sin_distribuir')
    cantidades_excel_son_totales = db.Column(db.String(10), nullable=False,
                                             default='no_se', server_default='no_se')

    # ===== Libre =====
    observaciones_tecnicas_json = db.Column(db.JSON, nullable=True)

    # ===== Auditoria =====
    completado_at = db.Column(db.DateTime, nullable=True)
    completado_por_user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'),
                                       nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    organizacion = db.relationship('Organizacion', foreign_keys=[organizacion_id])
    presupuesto = db.relationship('Presupuesto', foreign_keys=[presupuesto_id], backref=db.backref(
        'perfil_tecnico', uselist=False, cascade='all, delete-orphan', single_parent=True
    ))
    obra = db.relationship('Obra', foreign_keys=[obra_id])
    completado_por = db.relationship('Usuario', foreign_keys=[completado_por_user_id])

    def __repr__(self):
        return f'<ProjectTechnicalProfile presupuesto={self.presupuesto_id} obra={self.obra_id}>'

    @property
    def cantidad_niveles_total(self):
        """Total de niveles teoricos: subsuelos + PB + pisos + terraza."""
        n = (self.cantidad_subsuelos or 0) + (self.cantidad_pisos or 0)
        if self.tiene_planta_baja:
            n += 1
        if self.tiene_terraza:
            n += 1
        return n

    def to_dict(self, include_niveles=False):
        d = {
            'id': self.id,
            'organizacion_id': self.organizacion_id,
            'presupuesto_id': self.presupuesto_id,
            'obra_id': self.obra_id,
            'tipo_obra': self.tipo_obra,
            'naturaleza_proyecto': self.naturaleza_proyecto,
            'tipo_estructura': self.tipo_estructura,
            'tipo_fundacion': self.tipo_fundacion,
            'sistema_constructivo': self.sistema_constructivo,
            'cantidad_pisos': self.cantidad_pisos,
            'cantidad_subsuelos': self.cantidad_subsuelos,
            'tiene_planta_baja': self.tiene_planta_baja,
            'tiene_terraza': self.tiene_terraza,
            'superficie_total_m2': float(self.superficie_total_m2) if self.superficie_total_m2 is not None else None,
            'superficie_por_planta_m2': float(self.superficie_por_planta_m2) if self.superficie_por_planta_m2 is not None else None,
            'altura_promedio_piso_m': float(self.altura_promedio_piso_m) if self.altura_promedio_piso_m is not None else None,
            'espesor_losa_cm': float(self.espesor_losa_cm) if self.espesor_losa_cm is not None else None,
            'cantidad_torres': self.cantidad_torres,
            'cantidad_unidades_funcionales': self.cantidad_unidades_funcionales,
            'cantidad_cocheras': self.cantidad_cocheras,
            'criterio_distribucion': self.criterio_distribucion,
            'cantidades_excel_son_totales': self.cantidades_excel_son_totales,
            'observaciones_tecnicas_json': self.observaciones_tecnicas_json or {},
            'completado_at': self.completado_at.isoformat() if self.completado_at else None,
            'completado_por_user_id': self.completado_por_user_id,
            'cantidad_niveles_total': self.cantidad_niveles_total,
        }
        if include_niveles and self.presupuesto_id:
            from models.budgets import NivelPresupuesto
            niveles = NivelPresupuesto.query.filter_by(presupuesto_id=self.presupuesto_id).order_by(
                NivelPresupuesto.orden
            ).all()
            d['niveles'] = [n.to_dict() for n in niveles]
        return d


def validar_y_normalizar(payload: dict) -> dict:
    """Valida y normaliza un payload para crear/actualizar el perfil.

    Devuelve un dict con valores normalizados. Lanza ValueError si hay datos
    invalidos en campos enum-like.
    """
    out = {}

    def _norm_enum(key, valor, valores_validos, default):
        if valor is None or valor == '':
            out[key] = default
            return
        v = str(valor).strip().lower()
        if v not in valores_validos:
            raise ValueError(f'{key}: "{valor}" no es valido. Valores aceptados: {valores_validos}')
        out[key] = v

    _norm_enum('tipo_obra', payload.get('tipo_obra'), TIPOS_OBRA, 'edificio')
    _norm_enum('naturaleza_proyecto', payload.get('naturaleza_proyecto'),
               ('obra_nueva', 'remodelacion', 'ampliacion'), 'obra_nueva')
    _norm_enum('tipo_estructura', payload.get('tipo_estructura'), TIPOS_ESTRUCTURA, 'no_definida')
    _norm_enum('tipo_fundacion', payload.get('tipo_fundacion'), TIPOS_FUNDACION, 'no_definida')
    _norm_enum('criterio_distribucion', payload.get('criterio_distribucion'),
               CRITERIOS_DISTRIBUCION, 'sin_distribuir')
    _norm_enum('cantidades_excel_son_totales', payload.get('cantidades_excel_son_totales'),
               CANTIDADES_EXCEL_SON_TOTALES, 'no_se')

    # Texto libre
    sc = payload.get('sistema_constructivo')
    out['sistema_constructivo'] = (str(sc).strip()[:200] or None) if sc else None

    # Enteros con bounds razonables
    def _norm_int(key, default=0, lo=0, hi=999):
        v = payload.get(key)
        if v in (None, ''):
            out[key] = default
            return
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValueError(f'{key}: debe ser entero')
        if iv < lo or iv > hi:
            raise ValueError(f'{key}: fuera de rango [{lo}, {hi}]')
        out[key] = iv

    _norm_int('cantidad_pisos', default=0, lo=0, hi=200)
    _norm_int('cantidad_subsuelos', default=0, lo=0, hi=20)
    _norm_int('cantidad_torres', default=1, lo=1, hi=50)

    for opt in ('cantidad_unidades_funcionales', 'cantidad_cocheras'):
        v = payload.get(opt)
        if v in (None, ''):
            out[opt] = None
        else:
            try:
                iv = int(v)
                if iv < 0 or iv > 9999:
                    raise ValueError()
                out[opt] = iv
            except (TypeError, ValueError):
                raise ValueError(f'{opt}: entero invalido')

    # Booleanos
    def _norm_bool(key, default):
        v = payload.get(key)
        if v in (None, ''):
            out[key] = default
            return
        out[key] = str(v).strip().lower() in ('1', 'true', 'on', 'si', 'sí', 'yes')

    _norm_bool('tiene_planta_baja', True)
    _norm_bool('tiene_terraza', False)

    # Numeric (decimal-like) opcionales
    def _norm_dec(key):
        v = payload.get(key)
        if v in (None, ''):
            out[key] = None
            return
        try:
            f = float(str(v).replace(',', '.'))
        except (TypeError, ValueError):
            raise ValueError(f'{key}: numero invalido')
        if f < 0:
            raise ValueError(f'{key}: no puede ser negativo')
        out[key] = f

    _norm_dec('superficie_total_m2')
    _norm_dec('superficie_por_planta_m2')
    _norm_dec('altura_promedio_piso_m')
    _norm_dec('espesor_losa_cm')

    # Observaciones libres
    obs = payload.get('observaciones_tecnicas_json')
    if obs in (None, ''):
        out['observaciones_tecnicas_json'] = None
    elif isinstance(obs, dict):
        out['observaciones_tecnicas_json'] = obs
    else:
        # Si viene texto plano, lo guardamos en una key 'texto'
        out['observaciones_tecnicas_json'] = {'texto': str(obs)[:2000]}

    return out
