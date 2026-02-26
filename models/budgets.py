"""Modelos de Presupuestos, Cotizaciones y Precios"""
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from extensions import db
from sqlalchemy import inspect
import json

# NOTE: BudgetCalculator se importa dentro de los métodos para evitar import circular


class ExchangeRate(db.Model):
    __tablename__ = 'exchange_rates'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False)
    base_currency = db.Column(db.String(3), nullable=False, default='ARS')
    quote_currency = db.Column(db.String(3), nullable=False, default='USD')
    value = db.Column('rate', db.Numeric(18, 6), nullable=False)
    as_of_date = db.Column(db.Date, nullable=False, default=date.today)
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    source_url = db.Column(db.String(255))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('provider', 'base_currency', 'quote_currency', 'as_of_date', name='uq_exchange_rate_daily'),
    )

    presupuestos = db.relationship('Presupuesto', back_populates='exchange_rate', lazy='dynamic')

    def __repr__(self):
        return (
            f"<ExchangeRate {self.provider} {self.base_currency}/{self.quote_currency} "
            f"{self.value} ({self.as_of_date})>"
        )


class CACIndex(db.Model):
    __tablename__ = 'cac_indices'

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    value = db.Column(db.Numeric(12, 2), nullable=False)
    provider = db.Column(db.String(50), nullable=False)
    source_url = db.Column(db.String(255))
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('year', 'month', 'provider', name='uq_cac_index_period_provider'),
    )

    def __repr__(self):
        return f"<CACIndex {self.year}-{self.month:02d} {self.value} ({self.provider})>"


class PricingIndex(db.Model):
    __tablename__ = 'pricing_indices'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Numeric(18, 6), nullable=False)
    valid_from = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('name', 'valid_from', name='uq_pricing_indices_name_valid_from'),
    )

    def __repr__(self):
        return f"<PricingIndex {self.name} {self.value} ({self.valid_from})>"


class Presupuesto(db.Model):
    __tablename__ = 'presupuestos'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)  # Ahora puede ser NULL
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)  # Cliente del presupuesto
    numero = db.Column(db.String(50), unique=True, nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    estado = db.Column(db.String(20), default='borrador')  # borrador, enviado, aprobado, rechazado, perdido, eliminado
    confirmado_como_obra = db.Column(db.Boolean, default=False)  # NUEVO: Si ya se convirtió en obra
    datos_proyecto = db.Column(db.Text)  # NUEVO: Datos del proyecto en JSON
    ubicacion_texto = db.Column(db.String(300))
    ubicacion_normalizada = db.Column(db.String(300))
    geo_latitud = db.Column(db.Numeric(10, 8))
    geo_longitud = db.Column(db.Numeric(11, 8))
    geocode_place_id = db.Column(db.String(120))
    geocode_provider = db.Column(db.String(50))
    geocode_status = db.Column(db.String(20))
    geocode_raw = db.Column(db.Text)
    geocode_actualizado = db.Column(db.DateTime)
    subtotal_materiales = db.Column(db.Numeric(15, 2), default=0)
    subtotal_mano_obra = db.Column(db.Numeric(15, 2), default=0)
    subtotal_equipos = db.Column(db.Numeric(15, 2), default=0)
    total_sin_iva = db.Column(db.Numeric(15, 2), default=0)
    iva_porcentaje = db.Column(db.Numeric(5, 2), default=21)  # Default IVA Argentina
    total_con_iva = db.Column(db.Numeric(15, 2), default=0)
    observaciones = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    perdido_motivo = db.Column(db.Text)
    perdido_fecha = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)
    vigencia_dias = db.Column(db.Integer, default=30)
    fecha_vigencia = db.Column(db.Date)
    vigencia_bloqueada = db.Column(db.Boolean, nullable=False, default=True)
    currency = db.Column(db.String(3), nullable=False, default='ARS')
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.id'))
    exchange_rate_value = db.Column(db.Numeric(18, 6))
    exchange_rate_provider = db.Column(db.String(50))
    exchange_rate_fetched_at = db.Column(db.DateTime)
    exchange_rate_as_of = db.Column(db.Date)
    tasa_usd_venta = db.Column(db.Numeric(10, 4))
    indice_cac_valor = db.Column(db.Numeric(12, 2))
    indice_cac_fecha = db.Column(db.Date)

    # Relaciones
    obra = db.relationship('Obra', back_populates='presupuestos')
    organizacion = db.relationship('Organizacion', overlaps="presupuestos")
    cliente = db.relationship('Cliente', back_populates='presupuestos')
    items = db.relationship('ItemPresupuesto', back_populates='presupuesto', cascade='all, delete-orphan', lazy='dynamic')
    niveles = db.relationship('NivelPresupuesto', back_populates='presupuesto', cascade='all, delete-orphan', lazy='dynamic')
    exchange_rate = db.relationship('ExchangeRate', back_populates='presupuestos', lazy='joined')

    def __repr__(self):
        return f'<Presupuesto {self.numero}>'

    def calcular_totales(self):
        """
        Calcula todos los totales del presupuesto usando el calculador centralizado.

        Actualiza:
        - subtotal_materiales
        - subtotal_mano_obra
        - subtotal_equipos
        - total_sin_iva
        - total_con_iva
        """
        # Import local para evitar circular import
        from services.calculation import BudgetCalculator, BudgetConstants

        items = self.items.all() if hasattr(self.items, 'all') else list(self.items)

        # Usar calculadora centralizada
        iva_rate = Decimal(self.iva_porcentaje) if self.iva_porcentaje else BudgetConstants.DEFAULT_IVA_RATE
        totales = BudgetCalculator.calcular_totales_presupuesto(items, iva_rate)

        # Actualizar campos del modelo
        self.subtotal_materiales = totales['subtotal_materiales']
        self.subtotal_mano_obra = totales['subtotal_mano_obra']
        self.subtotal_equipos = totales['subtotal_equipos']
        self.total_sin_iva = totales['total_sin_iva']
        self.total_con_iva = totales['total_con_iva']

        self.asegurar_vigencia()

    def asegurar_vigencia(self, fecha_base=None):
        dias = self.vigencia_dias if self.vigencia_dias and self.vigencia_dias > 0 else 30
        if dias < 1:
            dias = 1
        elif dias > 180:
            dias = 180
        if self.vigencia_dias != dias:
            self.vigencia_dias = dias
        if fecha_base is None:
            if self.fecha:
                fecha_base = self.fecha
            elif self.fecha_creacion:
                fecha_base = self.fecha_creacion.date()
            else:
                fecha_base = date.today()
        if not self.fecha_vigencia or fecha_base + timedelta(days=dias) != self.fecha_vigencia:
            self.fecha_vigencia = fecha_base + timedelta(days=dias)
        return self.fecha_vigencia

    @property
    def esta_vencido(self):
        if not self.fecha_vigencia:
            return False
        return self.fecha_vigencia < date.today()

    @property
    def dias_restantes_vigencia(self):
        if not self.fecha_vigencia:
            return None
        return (self.fecha_vigencia - date.today()).days

    @property
    def estado_vigencia(self):
        dias = self.dias_restantes_vigencia
        if dias is None:
            return None
        if dias < 0:
            return 'vencido'
        if dias <= 3:
            return 'critico'
        if dias <= 15:
            return 'alerta'
        return 'normal'

    @property
    def clase_vigencia_badge(self):
        estado = self.estado_vigencia
        mapping = {
            'critico': 'bg-danger text-white',
            'alerta': 'bg-warning text-dark',
            'normal': 'bg-success text-white',
            'vencido': 'bg-secondary text-white',
        }
        return mapping.get(estado, 'bg-secondary text-white')

    @property
    def cliente_nombre(self):
        """Retorna el nombre del cliente asociado al presupuesto"""
        if self.cliente:
            return self.cliente.nombre_completo
        return None

    def registrar_tipo_cambio(self, snapshot):
        """Actualiza los metadatos de tipo de cambio según el snapshot recibido."""

        if snapshot is None:
            self.exchange_rate_id = None
            self.exchange_rate_value = None
            self.exchange_rate_provider = None
            self.exchange_rate_fetched_at = None
            return

        self.exchange_rate_id = snapshot.id
        self.exchange_rate_value = snapshot.value
        self.exchange_rate_provider = snapshot.provider
        self.exchange_rate_fetched_at = snapshot.fetched_at
        self.exchange_rate_as_of = snapshot.as_of_date
        if snapshot.quote_currency.upper() == 'USD' and snapshot.base_currency.upper() == 'ARS':
            self.tasa_usd_venta = snapshot.value


class ItemPresupuesto(db.Model):
    __tablename__ = 'items_presupuesto'

    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # material, mano_obra, equipo
    descripcion = db.Column(db.String(300), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(15, 2), nullable=False)
    etapa_id = db.Column(db.Integer, db.ForeignKey('etapas_obra.id'), nullable=True)
    etapa_nombre = db.Column(db.String(100), nullable=True)  # Nombre de etapa para presupuestos sin obra
    origen = db.Column(db.String(20), default='manual')  # manual, ia, importado
    currency = db.Column(db.String(3), nullable=False, default='ARS')
    price_unit_currency = db.Column(db.Numeric(15, 2))
    total_currency = db.Column(db.Numeric(15, 2))
    price_unit_ars = db.Column(db.Numeric(15, 2))
    total_ars = db.Column(db.Numeric(15, 2))

    # Vinculación directa con inventario (elimina match impreciso por nombre)
    # Si el material existe en inventario, se vincula directamente por ID
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=True)

    # Nivel del edificio al que pertenece este item (para presupuestos por niveles)
    nivel_nombre = db.Column(db.String(100), nullable=True)

    # Relaciones
    presupuesto = db.relationship('Presupuesto', back_populates='items')
    etapa = db.relationship('EtapaObra', lazy='joined')
    item_inventario = db.relationship('ItemInventario', foreign_keys=[item_inventario_id])

    def __repr__(self):
        return f'<ItemPresupuesto {self.descripcion}>'


class NivelPresupuesto(db.Model):
    """Configuracion de niveles para presupuestos de edificios."""
    __tablename__ = 'niveles_presupuesto'

    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=False)

    tipo_nivel = db.Column(db.String(30), nullable=False)  # subsuelo, pb, piso_tipo, piso_especial, terraza
    nombre = db.Column(db.String(100), nullable=False)  # "S-1", "PB", "Pisos Tipo", "Terraza"
    orden = db.Column(db.Integer, nullable=False, default=0)
    repeticiones = db.Column(db.Integer, nullable=False, default=1)
    area_m2 = db.Column(db.Numeric(10, 2), nullable=False)
    sistema_constructivo = db.Column(db.String(30), nullable=False, default='hormigon')  # legacy, se mantiene por compat
    hormigon_m3 = db.Column(db.Numeric(10, 2), nullable=True, default=0)  # m³ de hormigón para este nivel
    albanileria_m2 = db.Column(db.Numeric(10, 2), nullable=True, default=0)  # m² de albañilería para este nivel
    atributos = db.Column(db.JSON, default=dict)  # napa, cocheras, altura_libre, espesor_losa, complejidad

    presupuesto = db.relationship('Presupuesto', back_populates='niveles')

    __table_args__ = (
        db.Index('ix_niveles_pres_id', 'presupuesto_id'),
    )

    @property
    def superficie_total(self):
        return float(self.area_m2 or 0) * (self.repeticiones or 1)

    def to_dict(self):
        return {
            'id': self.id,
            'tipo_nivel': self.tipo_nivel,
            'nombre': self.nombre,
            'orden': self.orden,
            'repeticiones': self.repeticiones,
            'area_m2': float(self.area_m2),
            'superficie_total': self.superficie_total,
            'sistema_constructivo': self.sistema_constructivo,
            'hormigon_m3': float(self.hormigon_m3 or 0),
            'albanileria_m2': float(self.albanileria_m2 or 0),
            'atributos': self.atributos or {},
        }

    def __repr__(self):
        return f'<NivelPresupuesto {self.nombre} ({self.area_m2}m2 x{self.repeticiones})>'


class ItemReferenciaConstructora(db.Model):
    """Items de obra cotizados por constructoras reales (parseados de Excel).
    Sirven como referencia de mercado para la calculadora IA."""
    __tablename__ = 'items_referencia_constructora'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    constructora = db.Column(db.String(200), nullable=False)
    etapa_nombre = db.Column(db.String(100), nullable=False)
    codigo_excel = db.Column(db.String(50))
    descripcion = db.Column(db.String(500), nullable=False)
    unidad = db.Column(db.String(20))
    precio_unitario = db.Column(db.Numeric(15, 2), default=0)
    planilla = db.Column(db.String(50))
    fecha_carga = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)

    organizacion = db.relationship('Organizacion', backref='items_referencia_constructora')

    __table_args__ = (
        db.Index('ix_ref_constr_org_etapa', 'organizacion_id', 'etapa_nombre'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'constructora': self.constructora,
            'etapa_nombre': self.etapa_nombre,
            'codigo': self.codigo_excel,
            'descripcion': self.descripcion,
            'unidad': self.unidad,
            'precio_unitario': float(self.precio_unitario or 0),
        }

    def __repr__(self):
        return f'<ItemRefConstructora {self.constructora}: {self.descripcion[:40]}>'


class GeocodeCache(db.Model):
    __tablename__ = 'geocode_cache'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False)
    query_text = db.Column(db.String(400), nullable=False)
    normalized_text = db.Column(db.String(400), nullable=False)
    display_name = db.Column(db.String(400))
    place_id = db.Column(db.String(120))
    latitud = db.Column(db.Numeric(10, 8))
    longitud = db.Column(db.Numeric(11, 8))
    raw_response = db.Column(db.Text)
    status = db.Column(db.String(20), default='ok')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('provider', 'normalized_text', name='uq_geocode_provider_norm'),
        db.Index('ix_geocode_norm', 'normalized_text'),
    )

    def to_payload(self) -> dict:
        def _to_float(value):
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        payload = {
            'provider': self.provider,
            'query': self.query_text,
            'normalized': self.normalized_text,
            'display_name': self.display_name,
            'place_id': self.place_id,
            'lat': _to_float(self.latitud),
            'lng': _to_float(self.longitud),
            'status': self.status or 'ok',
        }

        if self.raw_response:
            try:
                payload['raw'] = json.loads(self.raw_response)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload['raw'] = None
        else:
            payload['raw'] = None

        payload['created_at'] = self.created_at
        payload['updated_at'] = self.updated_at
        return payload


class WizardStageVariant(db.Model):
    __tablename__ = 'wizard_stage_variants'

    id = db.Column(db.Integer, primary_key=True)
    stage_slug = db.Column(db.String(80), nullable=False, index=True)
    variant_key = db.Column(db.String(80), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.String(255))
    is_default = db.Column(db.Boolean, default=False)
    metadata_raw = db.Column('metadata', db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    coefficients = db.relationship(
        'WizardStageCoefficient',
        back_populates='variant',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('stage_slug', 'variant_key', name='uq_wizard_stage_variant'),
    )

    @property
    def meta(self):
        """Return metadata as dict. db.JSON already handles serialization."""
        if self.metadata_raw is None:
            return {}
        if isinstance(self.metadata_raw, dict):
            return self.metadata_raw
        # Fallback for legacy string data
        try:
            return json.loads(self.metadata_raw)
        except (ValueError, TypeError):
            return {}

    @meta.setter
    def meta(self, value):
        """Set metadata as dict. db.JSON will handle serialization."""
        self.metadata_raw = value or {}

    def __repr__(self):
        return f"<WizardStageVariant stage={self.stage_slug} variant={self.variant_key}>"


class WizardStageCoefficient(db.Model):
    __tablename__ = 'wizard_stage_coefficients'

    id = db.Column(db.Integer, primary_key=True)
    stage_slug = db.Column(db.String(80), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('wizard_stage_variants.id'), nullable=True)
    unit = db.Column(db.String(20), nullable=False, default='u')
    quantity_metric = db.Column(db.String(50), nullable=False, default='cantidad')
    materials_per_unit = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    labor_per_unit = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    equipment_per_unit = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default='ARS')
    source = db.Column(db.String(80))
    notes = db.Column(db.String(255))
    is_baseline = db.Column(db.Boolean, default=False)
    metadata_raw = db.Column('metadata', db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variant = db.relationship('WizardStageVariant', back_populates='coefficients')

    __table_args__ = (
        db.UniqueConstraint('stage_slug', 'variant_id', name='uq_wizard_stage_coeff_variant'),
    )

    @property
    def meta(self):
        """Return metadata as dict. db.JSON already handles serialization."""
        if self.metadata_raw is None:
            return {}
        if isinstance(self.metadata_raw, dict):
            return self.metadata_raw
        # Fallback for legacy string data
        try:
            return json.loads(self.metadata_raw)
        except (ValueError, TypeError):
            return {}

    @meta.setter
    def meta(self, value):
        """Set metadata as dict. db.JSON will handle serialization."""
        self.metadata_raw = value or {}

    def __repr__(self):
        return (
            f"<WizardStageCoefficient stage={self.stage_slug} variant={self.variant_id} "
            f"mat={self.materials_per_unit} labor={self.labor_per_unit}>"
        )


@db.event.listens_for(Presupuesto, 'before_insert')
def _presupuesto_before_insert(mapper, connection, target):
    if target.vigencia_bloqueada is None:
        target.vigencia_bloqueada = True
    target.asegurar_vigencia()


@db.event.listens_for(Presupuesto, 'before_update')
def _presupuesto_before_update(mapper, connection, target):
    state = inspect(target)
    if target.vigencia_bloqueada:
        cambios_vigencia = (
            state.attrs['vigencia_dias'].history.has_changes()
            or state.attrs['fecha_vigencia'].history.has_changes()
        )
        if cambios_vigencia:
            raise ValueError('La vigencia del presupuesto está bloqueada y no puede modificarse.')
