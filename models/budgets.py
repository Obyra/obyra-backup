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
    __table_args__ = (
        db.UniqueConstraint('organizacion_id', 'numero', name='uq_presupuesto_org_numero'),
    )

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)  # Ahora puede ser NULL
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)  # Cliente del presupuesto
    numero = db.Column(db.String(50), nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    estado = db.Column(db.String(20), default='borrador')  # borrador, enviado, aprobado, rechazado, perdido, eliminado
    confirmado_como_obra = db.Column(db.Boolean, default=False)  # NUEVO: Si ya se convirtió en obra
    # Presupuesto Ejecutivo (APU): cuando se aprueba, el desglose interno queda
    # congelado y no se pueden agregar/editar composiciones sin revertir primero.
    ejecutivo_aprobado = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    ejecutivo_aprobado_at = db.Column(db.DateTime, nullable=True)
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
    IVA_VALIDOS = [Decimal('0'), Decimal('10.5'), Decimal('21'), Decimal('27')]
    iva_porcentaje = db.Column(db.Numeric(5, 2), default=21)  # Default IVA Argentina

    @staticmethod
    def validar_iva(valor):
        """Valida que el IVA sea un porcentaje válido en Argentina."""
        try:
            v = Decimal(str(valor))
        except Exception:
            return False
        return v >= Decimal('0') and v <= Decimal('100')
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

    def soft_delete(self):
        """Marca el presupuesto como eliminado sin borrar datos."""
        self.deleted_at = datetime.utcnow()
        self.estado = 'eliminado'

    def restore(self):
        """Restaura un presupuesto eliminado."""
        self.deleted_at = None
        self.estado = 'borrador'

    @classmethod
    def query_active(cls):
        """Query que excluye presupuestos soft-deleted."""
        return cls.query.filter(cls.deleted_at.is_(None))

    def calcular_totales(self):
        """
        Calcula todos los totales del presupuesto usando el calculador centralizado.

        Actualiza:
        - subtotal_materiales
        - subtotal_mano_obra
        - subtotal_equipos
        - total_sin_iva
        - total_con_iva

        Los ítems con `solo_interno=True` pertenecen al ejecutivo (APU) y NO
        suman al precio vendido al cliente. Se excluyen explícitamente acá.
        """
        # Import local para evitar circular import
        from services.calculation import BudgetCalculator, BudgetConstants

        items_raw = self.items.all() if hasattr(self.items, 'all') else list(self.items)
        # Filtrar ítems internos del ejecutivo antes de calcular el precio al cliente
        items = [i for i in items_raw if not getattr(i, 'solo_interno', False)]

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
    cantidad = db.Column(db.Numeric(15, 3), nullable=False)
    precio_unitario = db.Column(db.Numeric(15, 2), nullable=False)
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

    # Modalidad de costo (solo aplica para tipo='equipo'): compra | alquiler
    # Para 'compra': cantidad=unidades físicas, precio=precio unitario de compra
    # Para 'alquiler': cantidad=cantidad de períodos, unidad=período (día/semana/mes/hora/jornal),
    #                  precio=precio por período. Total sigue siendo cantidad*precio_unitario.
    modalidad_costo = db.Column(db.String(20), default='compra', nullable=True)

    # Solo-interno: el item pertenece al ejecutivo (APU) como parte de una etapa
    # interna que NO está en el pliego. NO se muestra en el PDF del cliente ni
    # suma al precio vendido, pero sí suma al costo estimado del ejecutivo.
    # Típicamente usado para planificar Mampostería, Pisos, Pintura, etc. que el PM
    # necesita ejecutar pero que no se facturan como renglón separado al cliente.
    solo_interno = db.Column(db.Boolean, default=False, nullable=False, server_default='false')

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


# ============================================================
# ESCALA SALARIAL UOCRA
# ============================================================

class EscalaSalarialUOCRA(db.Model):
    """Escala salarial UOCRA por categoría. Se actualiza cuando sale nueva escala."""
    __tablename__ = 'escala_salarial_uocra'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    categoria = db.Column(db.String(50), nullable=False)  # oficial, medio_oficial, ayudante, oficial_especializado
    descripcion = db.Column(db.String(100))                # "Oficial albañil", "Ayudante", etc.
    jornal = db.Column(db.Numeric(12, 2), nullable=False)  # Valor del jornal (8hs)
    tarifa_hora = db.Column(db.Numeric(12, 2))             # jornal / 8 (calculado)
    vigencia_desde = db.Column(db.Date, nullable=False)    # Desde cuándo rige
    vigencia_hasta = db.Column(db.Date)                    # Hasta cuándo (null = vigente)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organizacion = db.relationship('Organizacion')

    __table_args__ = (
        db.Index('ix_escala_org_cat', 'organizacion_id', 'categoria'),
    )

    def save(self):
        """Auto-calcula tarifa_hora al guardar."""
        if self.jornal:
            self.tarifa_hora = Decimal(str(self.jornal)) / Decimal('8')


# ============================================================
# CUADRILLAS TIPO
# ============================================================

class CuadrillaTipo(db.Model):
    """Template de cuadrilla reutilizable entre obras."""
    __tablename__ = 'cuadrillas_tipo'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)           # "Cuadrilla estructura estándar"
    etapa_tipo = db.Column(db.String(50), nullable=False)        # excavacion, fundaciones, estructura, etc.
    tipo_obra = db.Column(db.String(20), default='estandar')     # economica, estandar, premium
    rendimiento_diario = db.Column(db.Numeric(10, 3))            # Ej: 5.0 m3/día, 12.0 m2/día
    unidad_rendimiento = db.Column(db.String(20), default='m2')  # m2, m3, ml, gl, u
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion')
    miembros = db.relationship('MiembroCuadrilla', back_populates='cuadrilla',
                               cascade='all, delete-orphan', lazy='joined')

    __table_args__ = (
        db.Index('ix_cuadrilla_org_etapa', 'organizacion_id', 'etapa_tipo', 'tipo_obra'),
    )

    @property
    def costo_diario(self):
        """Costo diario total de la cuadrilla (suma de jornales de miembros)."""
        total = Decimal('0')
        for m in self.miembros:
            jornal = m.jornal_override or (m.escala.jornal if m.escala else Decimal('0'))
            total += jornal * Decimal(str(m.cantidad))
        return total

    @property
    def cantidad_personas(self):
        """Total de personas en la cuadrilla."""
        return sum(float(m.cantidad) for m in self.miembros)

    def calcular_jornales(self, cantidad_trabajo):
        """Calcula jornales necesarios para una cantidad de trabajo.

        Args:
            cantidad_trabajo: m2, m3, ml, etc. según unidad_rendimiento
        Returns:
            dict con jornales, dias, costo_total
        """
        if not self.rendimiento_diario or self.rendimiento_diario <= 0:
            return {'jornales': 0, 'dias': 0, 'costo_total': Decimal('0')}

        dias = Decimal(str(cantidad_trabajo)) / self.rendimiento_diario
        jornales = dias * Decimal(str(self.cantidad_personas))
        costo = dias * self.costo_diario

        return {
            'jornales': float(jornales.quantize(Decimal('0.01'))),
            'dias': float(dias.quantize(Decimal('0.01'))),
            'costo_total': costo.quantize(Decimal('0.01')),
            'costo_diario': float(self.costo_diario),
            'personas': self.cantidad_personas,
        }


class MiembroCuadrilla(db.Model):
    """Un rol/persona dentro de una cuadrilla tipo."""
    __tablename__ = 'miembros_cuadrilla'

    id = db.Column(db.Integer, primary_key=True)
    cuadrilla_id = db.Column(db.Integer, db.ForeignKey('cuadrillas_tipo.id'), nullable=False)
    escala_id = db.Column(db.Integer, db.ForeignKey('escala_salarial_uocra.id'), nullable=True)
    rol = db.Column(db.String(50), nullable=False)       # "Oficial", "Ayudante", "Encofrador"
    cantidad = db.Column(db.Numeric(5, 2), default=1)    # 1, 2, 0.5 (compartido)
    jornal_override = db.Column(db.Numeric(12, 2))       # Si se quiere pisar el valor de escala

    # Relaciones
    cuadrilla = db.relationship('CuadrillaTipo', back_populates='miembros')
    escala = db.relationship('EscalaSalarialUOCRA', lazy='joined')


class ItemPresupuestoComposicion(db.Model):
    """Composicion (APU) de un item del pliego.

    Cada item del presupuesto comercial (los 168 del pliego) se descompone
    internamente en N recursos: materiales, mano de obra y equipos.
    La suma de las composiciones es el costo estimado del item; comparado
    contra el precio_unitario del item da el margen interno.

    El cliente ve solo el item del pliego; la composicion queda interna.
    """
    __tablename__ = 'items_presupuesto_composicion'

    id = db.Column(db.Integer, primary_key=True)
    item_presupuesto_id = db.Column(
        db.Integer,
        db.ForeignKey('items_presupuesto.id', ondelete='CASCADE'),
        nullable=False,
    )
    tipo = db.Column(db.String(20), nullable=False)  # material | mano_obra | equipo
    descripcion = db.Column(db.String(300), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    cantidad = db.Column(db.Numeric(15, 3), nullable=False, default=0)
    precio_unitario = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=True)
    # Solo aplica a tipo='equipo'. 'compra' = precio total del equipo; 'alquiler' = precio por período.
    modalidad_costo = db.Column(db.String(20), nullable=True)
    # Agrupador de cotización: vincula esta composición con un MaterialCotizable
    # que consolida todas las composiciones equivalentes (misma desc+unidad) del
    # presupuesto para pedir cotización única a proveedores.
    material_cotizable_id = db.Column(
        db.Integer,
        db.ForeignKey('materiales_cotizables.id', ondelete='SET NULL'),
        nullable=True,
    )
    notas = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    item_presupuesto = db.relationship(
        'ItemPresupuesto',
        backref=db.backref('composiciones', cascade='all, delete-orphan', lazy='dynamic'),
    )
    item_inventario = db.relationship('ItemInventario', foreign_keys=[item_inventario_id])

    __table_args__ = (
        db.Index('ix_ipc_item_presupuesto', 'item_presupuesto_id'),
    )

    def __repr__(self):
        return f'<ItemPresupuestoComposicion {self.tipo} {self.descripcion[:40]}>'

    def recalcular_total(self):
        try:
            self.total = Decimal(str(self.cantidad or 0)) * Decimal(str(self.precio_unitario or 0))
        except (InvalidOperation, TypeError):
            self.total = Decimal('0')


class MaterialCotizable(db.Model):
    """Material consolidado del ejecutivo para pedir cotización a proveedores.

    Si el mismo material (ej: 'Cemento 50kg') aparece en 3 tareas distintas,
    acá se agrega UNA sola vez con cantidad_total = suma. Los proveedores
    cotizan este material unificado; el precio ganador se propaga a todas
    las composiciones que lo componen.

    grupo_hash es la clave de consolidación: normaliza (descripcion + unidad
    + item_inventario_id) para deduplicar exacto.
    """
    __tablename__ = 'materiales_cotizables'

    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(
        db.Integer,
        db.ForeignKey('presupuestos.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Tipo de recurso: 'material' (se compra) o 'equipo' (alquiler/compra).
    # MO no entra porque es costo interno, no se cotiza a proveedores.
    tipo = db.Column(db.String(20), nullable=False, default='material', server_default='material')
    # Descripción representativa (la más larga / clara entre las composiciones del grupo)
    descripcion = db.Column(db.String(300), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    cantidad_total = db.Column(db.Numeric(15, 3), nullable=False, default=0)
    # Vínculo opcional a inventario (si las composiciones estaban linkeadas)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=True)
    # Hash determinístico usado para dedup al sincronizar composiciones → materiales.
    grupo_hash = db.Column(db.String(64), nullable=False)
    # Estado del ciclo de cotización
    #   nuevo          -> recién consolidado, sin cotizar
    #   cotizando      -> ya se enviaron solicitudes a proveedores
    #   con_respuestas -> al menos un proveedor respondió
    #   elegido        -> se eligió proveedor ganador
    estado = db.Column(db.String(20), nullable=False, default='nuevo', server_default='nuevo')
    # Proveedor ganador (si hay) y su precio elegido
    proveedor_elegido_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id'), nullable=True)
    precio_elegido = db.Column(db.Numeric(15, 2), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    presupuesto = db.relationship('Presupuesto')
    item_inventario = db.relationship('ItemInventario', foreign_keys=[item_inventario_id])
    proveedor_elegido = db.relationship('ProveedorOC', foreign_keys=[proveedor_elegido_id])
    composiciones = db.relationship(
        'ItemPresupuestoComposicion',
        backref='material_cotizable',
        foreign_keys=[ItemPresupuestoComposicion.material_cotizable_id],
        lazy='dynamic',
    )

    __table_args__ = (
        db.UniqueConstraint('presupuesto_id', 'grupo_hash', name='uq_material_cotizable_pres_hash'),
        db.Index('ix_materiales_cotizables_presupuesto', 'presupuesto_id'),
    )

    def __repr__(self):
        return f'<MaterialCotizable {self.descripcion[:40]} ({self.cantidad_total} {self.unidad})>'


class ProveedorAsignadoMaterial(db.Model):
    """Asignación de un proveedor a un material cotizable (intención, antes de enviar).

    El PM arma la lista de "a qué proveedor quiero pedirle cotización de qué".
    Cuando termina, toca 'Generar solicitudes' y el sistema agrupa todas las
    asignaciones por proveedor en 1 solo mensaje de WhatsApp por proveedor.
    """
    __tablename__ = 'proveedores_asignados_material'

    id = db.Column(db.Integer, primary_key=True)
    material_cotizable_id = db.Column(
        db.Integer,
        db.ForeignKey('materiales_cotizables.id', ondelete='CASCADE'),
        nullable=False,
    )
    proveedor_id = db.Column(
        db.Integer,
        db.ForeignKey('proveedores_oc.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Una vez generada la solicitud, se asocia acá para no duplicar envíos.
    # Si es NULL, la asignación está "pendiente de enviar".
    solicitud_item_id = db.Column(
        db.Integer,
        db.ForeignKey('solicitud_cotizacion_material_items.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    material_cotizable = db.relationship('MaterialCotizable', backref=db.backref('asignaciones', cascade='all, delete-orphan', lazy='dynamic'))
    proveedor = db.relationship('ProveedorOC')

    __table_args__ = (
        db.UniqueConstraint('material_cotizable_id', 'proveedor_id', name='uq_asignacion_material_proveedor'),
        db.Index('ix_proveedores_asignados_material', 'material_cotizable_id'),
    )


class SolicitudCotizacionMaterial(db.Model):
    """Solicitud de cotización enviada a UN proveedor (con N recursos).

    Agrupa todos los materiales/equipos que se le piden a ese proveedor en un
    solo mensaje de WhatsApp. Versionada: si hacés otra ronda de cotización
    al mismo proveedor, version=2, 3, etc.
    """
    __tablename__ = 'solicitudes_cotizacion_material'

    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(
        db.Integer,
        db.ForeignKey('presupuestos.id', ondelete='CASCADE'),
        nullable=False,
    )
    proveedor_id = db.Column(
        db.Integer,
        db.ForeignKey('proveedores_oc.id', ondelete='CASCADE'),
        nullable=False,
    )
    version = db.Column(db.Integer, nullable=False, default=1)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_enviado = db.Column(db.DateTime, nullable=True)
    fecha_respondido = db.Column(db.DateTime, nullable=True)
    # pendiente (creada) | enviado (el PM tocó el link WA) | respondido (el PM cargó precios) | descartado
    estado = db.Column(db.String(20), nullable=False, default='pendiente', server_default='pendiente')
    mensaje_texto = db.Column(db.Text, nullable=True)
    wa_url = db.Column(db.Text, nullable=True)
    notas = db.Column(db.Text, nullable=True)

    presupuesto = db.relationship('Presupuesto')
    proveedor = db.relationship('ProveedorOC')

    __table_args__ = (
        db.Index('ix_solicitudes_cot_mat_presupuesto', 'presupuesto_id'),
        db.Index('ix_solicitudes_cot_mat_proveedor', 'proveedor_id'),
    )


class SolicitudCotizacionMaterialItem(db.Model):
    """Item dentro de una solicitud (un recurso cotizado a un proveedor).

    Guarda snapshot de cantidad/descripción al momento de enviar (por si el
    material cambia después). Cuando el proveedor responde, se carga
    precio_respuesta. Si se elige como ganador, elegido=True.
    """
    __tablename__ = 'solicitud_cotizacion_material_items'

    id = db.Column(db.Integer, primary_key=True)
    solicitud_id = db.Column(
        db.Integer,
        db.ForeignKey('solicitudes_cotizacion_material.id', ondelete='CASCADE'),
        nullable=False,
    )
    material_cotizable_id = db.Column(
        db.Integer,
        db.ForeignKey('materiales_cotizables.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Snapshot al momento de envío
    descripcion_snapshot = db.Column(db.String(300), nullable=False)
    unidad_snapshot = db.Column(db.String(20), nullable=False)
    cantidad_snapshot = db.Column(db.Numeric(15, 3), nullable=False, default=0)
    # Respuesta del proveedor (se completa en Fase C)
    precio_respuesta = db.Column(db.Numeric(15, 2), nullable=True)
    notas_respuesta = db.Column(db.Text, nullable=True)
    # True si este item fue el ganador para el MaterialCotizable
    elegido = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    solicitud = db.relationship('SolicitudCotizacionMaterial', backref=db.backref('items', cascade='all, delete-orphan', lazy='dynamic'))
    material_cotizable = db.relationship('MaterialCotizable', backref=db.backref('respuestas', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_solicitud_cot_mat_items_solicitud', 'solicitud_id'),
        db.Index('ix_solicitud_cot_mat_items_material', 'material_cotizable_id'),
    )
