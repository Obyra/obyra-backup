"""Modelos de Inventario y Gestión de Stock"""

from datetime import datetime, date
from extensions import db
from sqlalchemy.dialects.postgresql import JSONB
import json


# ============================================================
# SISTEMA DE UBICACIONES (Location-based Inventory)
# ============================================================

class Location(db.Model):
    """
    Ubicación genérica para almacenar stock.
    Puede ser un depósito (WAREHOUSE) o una obra (WORKSITE).
    """
    __tablename__ = 'locations'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # WAREHOUSE, WORKSITE
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    direccion = db.Column(db.String(300))
    es_principal = db.Column(db.Boolean, default=False)  # True para depósito principal
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    # Si es WORKSITE, referencia a la obra
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)

    # Relaciones
    organizacion = db.relationship('Organizacion', backref='locations')
    obra = db.relationship('Obra', backref='location', uselist=False)
    stock_items = db.relationship('StockUbicacion', back_populates='location', lazy='dynamic')

    __table_args__ = (
        # Solo puede haber un depósito principal por organización
        db.Index('ix_location_principal', 'organizacion_id', 'es_principal',
                 postgresql_where=db.text('es_principal = true'), unique=True),
    )

    def __repr__(self):
        return f'<Location {self.tipo}: {self.nombre}>'

    @property
    def icono(self):
        """Retorna el ícono apropiado según el tipo"""
        if self.tipo == 'WAREHOUSE':
            return '📦'
        return '🏗️'

    @property
    def tipo_display(self):
        """Nombre legible del tipo"""
        tipos = {
            'WAREHOUSE': 'Depósito',
            'WORKSITE': 'Obra'
        }
        return tipos.get(self.tipo, self.tipo)

    @classmethod
    def get_or_create_deposito_general(cls, organizacion_id):
        """Obtiene o crea el depósito general de una organización"""
        deposito = cls.query.filter_by(
            organizacion_id=organizacion_id,
            tipo='WAREHOUSE',
            es_principal=True
        ).first()

        if not deposito:
            deposito = cls(
                organizacion_id=organizacion_id,
                tipo='WAREHOUSE',
                nombre='Depósito General',
                descripcion='Depósito central de la organización',
                es_principal=True,
                activo=True
            )
            db.session.add(deposito)
            db.session.commit()

        return deposito

    @classmethod
    def get_or_create_for_obra(cls, obra):
        """Obtiene o crea una ubicación para una obra"""
        location = cls.query.filter_by(obra_id=obra.id).first()

        if not location:
            location = cls(
                organizacion_id=obra.organizacion_id,
                tipo='WORKSITE',
                nombre=obra.nombre,
                obra_id=obra.id,
                activo=True
            )
            db.session.add(location)
            db.session.commit()

        return location


class StockUbicacion(db.Model):
    """
    Stock de un item en una ubicación específica.
    Reemplaza conceptualmente a StockObra con un enfoque más genérico.
    """
    __tablename__ = 'stock_ubicacion'

    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=False)
    cantidad_disponible = db.Column(db.Numeric(10, 3), default=0)
    cantidad_reservada = db.Column(db.Numeric(10, 3), default=0)  # Reservado pero no movido
    cantidad_consumida = db.Column(db.Numeric(10, 3), default=0)  # Total usado/consumido
    fecha_ultima_entrada = db.Column(db.DateTime)
    fecha_ultimo_consumo = db.Column(db.DateTime)

    # Relaciones
    location = db.relationship('Location', back_populates='stock_items')
    item = db.relationship('ItemInventario', backref='stock_ubicaciones')
    movimientos = db.relationship('MovimientoStock', back_populates='stock_ubicacion', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('location_id', 'item_inventario_id', name='uq_stock_ubicacion_item'),
    )

    def __repr__(self):
        return f'<StockUbicacion {self.item.nombre} en {self.location.nombre}: {self.cantidad_disponible}>'

    @property
    def cantidad_real_disponible(self):
        """Stock disponible menos reservado"""
        return float(self.cantidad_disponible or 0) - float(self.cantidad_reservada or 0)

    @property
    def cantidad_total_recibida(self):
        """Total recibido = disponible + consumido"""
        return float(self.cantidad_disponible or 0) + float(self.cantidad_consumida or 0)


class MovimientoStock(db.Model):
    """
    Registro de todos los movimientos de stock (entradas, salidas, traslados, consumos).
    Proporciona trazabilidad completa del inventario.
    """
    __tablename__ = 'movimientos_stock'

    id = db.Column(db.Integer, primary_key=True)
    stock_ubicacion_id = db.Column(db.Integer, db.ForeignKey('stock_ubicacion.id'), nullable=False)
    tipo = db.Column(db.String(30), nullable=False)  # entrada, salida, traslado_entrada, traslado_salida, consumo, ajuste
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Información adicional
    motivo = db.Column(db.String(200))
    observaciones = db.Column(db.Text)
    proveedor = db.Column(db.String(200))
    remito = db.Column(db.String(100))

    # Para traslados: referencia al movimiento relacionado
    traslado_relacionado_id = db.Column(db.Integer, db.ForeignKey('movimientos_stock.id'), nullable=True)

    # Precio al momento del movimiento (para calcular costos)
    precio_unitario = db.Column(db.Numeric(10, 2))
    moneda = db.Column(db.String(3), default='ARS')

    # Relaciones
    stock_ubicacion = db.relationship('StockUbicacion', back_populates='movimientos')
    usuario = db.relationship('Usuario')
    traslado_relacionado = db.relationship('MovimientoStock', remote_side=[id])

    def __repr__(self):
        return f'<MovimientoStock {self.tipo} {self.cantidad}>'

    @property
    def costo_total(self):
        if self.precio_unitario and self.cantidad:
            return float(self.precio_unitario) * float(self.cantidad)
        return 0


# ============================================================
# MODELOS LEGACY (mantenidos para compatibilidad)
# ============================================================

class CategoriaInventario(db.Model):
    """DEPRECATED: Usar InventoryCategory en su lugar.
    Mantenido por compatibilidad con datos existentes."""
    __tablename__ = 'categorias_inventario'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    tipo = db.Column(db.String(20), nullable=False)  # material, herramienta, maquinaria

    # Relaciones - sin back_populates porque ItemInventario ahora usa InventoryCategory
    # items = db.relationship('ItemInventario', ...) - REMOVIDO para evitar conflicto

    def __repr__(self):
        return f'<CategoriaInventario {self.nombre}>'


class ItemInventario(db.Model):
    __tablename__ = 'items_inventario'

    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(200), nullable=False)  # Nombre genérico del artículo
    descripcion = db.Column(db.Text)
    unidad = db.Column(db.String(20), nullable=False)

    # Campos opcionales para diferenciar variantes del mismo artículo genérico
    marca = db.Column(db.String(100), nullable=True)
    modelo = db.Column(db.String(100), nullable=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores.id'), nullable=True)

    stock_actual = db.Column(db.Numeric(10, 3), default=0)
    stock_minimo = db.Column(db.Numeric(10, 3), default=0)
    precio_promedio = db.Column(db.Numeric(10, 2), default=0)  # Precio en ARS
    precio_promedio_usd = db.Column(db.Numeric(10, 2), default=0)  # Precio en USD
    activo = db.Column(db.Boolean, default=True)

    # Tipo de construcción al que aplica (para calculadora IA)
    aplica_economica = db.Column(db.Boolean, default=False)
    aplica_estandar = db.Column(db.Boolean, default=False)
    aplica_premium = db.Column(db.Boolean, default=False)

    # Campos para redondeo de compras
    # presentaciones: JSON con tamaños de pack disponibles
    # Formato: [{"size": 20, "name": "Balde 20L", "price": 15000}, {"size": 10, "name": "Balde 10L"}]
    presentaciones = db.Column(db.Text, nullable=True)
    # factor_conversion: para convertir m² a unidades (ej: 0.0225 para cerámico 15x15)
    factor_conversion = db.Column(db.Numeric(10, 6), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)

    # Relaciones
    categoria = db.relationship('InventoryCategory', backref='items_inventario')
    organizacion = db.relationship('Organizacion', back_populates='inventario')
    movimientos = db.relationship('MovimientoInventario', back_populates='item', lazy='dynamic')
    usos = db.relationship('UsoInventario', back_populates='item', lazy='dynamic')
    proveedor = db.relationship('Proveedor', backref='items_inventario')

    def __repr__(self):
        return f'<ItemInventario {self.codigo} - {self.nombre}>'

    @property
    def necesita_reposicion(self):
        return self.stock_actual <= self.stock_minimo

    @property
    def presentaciones_lista(self):
        """Retorna las presentaciones como lista de dicts"""
        if not self.presentaciones:
            return self._presentaciones_default()
        try:
            data = json.loads(self.presentaciones)
            if isinstance(data, list) and data:
                return data
            return self._presentaciones_default()
        except (TypeError, ValueError):
            return self._presentaciones_default()

    def _presentaciones_default(self):
        """Retorna presentaciones por defecto según la unidad"""
        defaults = {
            'lts': [
                {'size': 20, 'name': 'Balde 20L'},
                {'size': 10, 'name': 'Balde 10L'},
                {'size': 4, 'name': 'Balde 4L'},
                {'size': 1, 'name': 'Litro'}
            ],
            'kg': [
                {'size': 50, 'name': 'Bolsa 50kg'},
                {'size': 25, 'name': 'Bolsa 25kg'},
                {'size': 10, 'name': 'Bolsa 10kg'},
                {'size': 1, 'name': 'Kg'}
            ],
            'ml': [{'size': 1, 'name': 'Metro'}],
            'm2': [{'size': 1, 'name': 'm²'}],
            'm3': [{'size': 1, 'name': 'm³'}],
            'bolsa': [{'size': 1, 'name': 'Bolsa'}],
            'unidad': [{'size': 1, 'name': 'Unidad'}],
        }
        unidad_lower = (self.unidad or 'unidad').lower()
        return defaults.get(unidad_lower, [{'size': 1, 'name': 'Unidad'}])

    @presentaciones_lista.setter
    def presentaciones_lista(self, value):
        """Guarda las presentaciones como JSON"""
        if value:
            self.presentaciones = json.dumps(value)
        else:
            self.presentaciones = None

    def get_pack_sizes(self):
        """Retorna solo los tamaños de pack para el motor de redondeo"""
        return [p.get('size', 1) for p in self.presentaciones_lista]

    def get_pack_prices(self):
        """Retorna dict de precios por tamaño si están definidos"""
        prices = {}
        for p in self.presentaciones_lista:
            if 'price' in p:
                prices[p['size']] = p['price']
        return prices if prices else None


class MovimientoInventario(db.Model):
    __tablename__ = 'movimientos_inventario'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # entrada, salida, ajuste
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    precio_unitario = db.Column(db.Numeric(10, 2))
    motivo = db.Column(db.String(200))
    observaciones = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    item = db.relationship('ItemInventario', back_populates='movimientos')
    usuario = db.relationship('Usuario')

    def __repr__(self):
        return f'<MovimientoInventario {self.tipo} - {self.item.nombre}>'


class UsoInventario(db.Model):
    __tablename__ = 'uso_inventario'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=False)
    cantidad_usada = db.Column(db.Numeric(10, 3), nullable=False)
    fecha_uso = db.Column(db.Date, default=date.today)
    observaciones = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Precio histórico - guarda el precio al momento del uso (NO el promedio actual)
    # Esto permite calcular costos reales sin que varíen por cambios futuros de precio
    precio_unitario_al_uso = db.Column(db.Numeric(10, 2), nullable=True)
    moneda = db.Column(db.String(3), default='ARS')  # ARS o USD

    # Relaciones
    obra = db.relationship('Obra', back_populates='uso_inventario')
    item = db.relationship('ItemInventario', back_populates='usos')
    usuario = db.relationship('Usuario')

    def __repr__(self):
        return f'<UsoInventario {self.obra.nombre} - {self.item.nombre}>'


class ReservaStock(db.Model):
    """Reserva de stock para una obra. Permite apartar materiales del inventario sin moverlos."""
    __tablename__ = 'reservas_stock'

    id = db.Column(db.Integer, primary_key=True)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=False)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    estado = db.Column(db.String(20), default='activa')  # activa, trasladada, cancelada
    fecha_reserva = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_traslado = db.Column(db.DateTime, nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    notas = db.Column(db.Text)

    # Relaciones
    item = db.relationship('ItemInventario', backref='reservas')
    obra = db.relationship('Obra', backref='reservas_stock')
    usuario = db.relationship('Usuario')

    def __repr__(self):
        return f'<ReservaStock {self.item.nombre} - {self.cantidad} para {self.obra.nombre}>'


class StockObra(db.Model):
    """Stock físico presente en una obra. Inventario local del sitio de construcción."""
    __tablename__ = 'stock_obra'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=False)
    cantidad_disponible = db.Column(db.Numeric(10, 3), default=0)  # Stock actual en obra
    cantidad_consumida = db.Column(db.Numeric(10, 3), default=0)   # Total consumido
    fecha_ultimo_traslado = db.Column(db.DateTime)
    fecha_ultimo_uso = db.Column(db.DateTime)

    # Relaciones
    obra = db.relationship('Obra', backref='stock_obra')
    item = db.relationship('ItemInventario', backref='stock_en_obras')

    # Constraint único: un item solo puede tener un registro por obra
    __table_args__ = (
        db.UniqueConstraint('obra_id', 'item_inventario_id', name='uq_stock_obra_item'),
    )

    def __repr__(self):
        return f'<StockObra {self.item.nombre} en {self.obra.nombre}: {self.cantidad_disponible}>'

    @property
    def cantidad_total_recibida(self):
        """Total recibido = disponible + consumido"""
        return float(self.cantidad_disponible or 0) + float(self.cantidad_consumida or 0)


class MovimientoStockObra(db.Model):
    """Registro de movimientos de stock en una obra (entradas y consumos)."""
    __tablename__ = 'movimientos_stock_obra'

    id = db.Column(db.Integer, primary_key=True)
    stock_obra_id = db.Column(db.Integer, db.ForeignKey('stock_obra.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # entrada, consumo, devolucion
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    observaciones = db.Column(db.Text)

    # Para consumos: registrar costo
    precio_unitario = db.Column(db.Numeric(10, 2))
    moneda = db.Column(db.String(3), default='ARS')

    # Referencia a reserva si viene de una
    reserva_id = db.Column(db.Integer, db.ForeignKey('reservas_stock.id'), nullable=True)

    # Relaciones
    stock_obra = db.relationship('StockObra', backref='movimientos')
    usuario = db.relationship('Usuario')
    reserva = db.relationship('ReservaStock')

    def __repr__(self):
        return f'<MovimientoStockObra {self.tipo} {self.cantidad}>'

    @property
    def costo_total(self):
        if self.precio_unitario and self.cantidad:
            return float(self.precio_unitario) * float(self.cantidad)
        return 0


class InventoryCategory(db.Model):
    __tablename__ = 'inventory_category'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_global = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    company = db.relationship('Organizacion', backref='inventory_categories')
    parent = db.relationship('InventoryCategory', remote_side=[id], backref='children')
    items = db.relationship('InventoryItem', back_populates='categoria')

    def __repr__(self):
        return f'<InventoryCategory {self.nombre}>'

    @property
    def full_path(self):
        """Obtiene la ruta completa de la categoría con separadores jerárquicos."""

        parts = []
        current = self
        visited = set()

        while current is not None:
            # Evitar ciclos en casos de datos inconsistentes
            current_id = getattr(current, "id", None)
            if current_id is not None:
                if current_id in visited:
                    break
                visited.add(current_id)

            parts.append(current.nombre)
            current = current.parent

        return " → ".join(reversed(parts))

    @property
    def org_id(self):
        """Alias compatible con nomenclatura org_id"""
        return self.company_id


class InventoryItem(db.Model):
    __tablename__ = 'inventory_item'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    sku = db.Column(db.String(100), nullable=False, unique=True)
    nombre = db.Column(db.String(200), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)  # kg, m, u, m2, m3, etc.
    package_options_raw = db.Column('package_options', db.Text)
    min_stock = db.Column(db.Numeric(12, 2), default=0)
    descripcion = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)

    # Relaciones
    company = db.relationship('Organizacion', backref='inventory_items')
    categoria = db.relationship('InventoryCategory', back_populates='items')
    stocks = db.relationship('Stock', back_populates='item', cascade='all, delete-orphan')
    movements = db.relationship('StockMovement', back_populates='item', cascade='all, delete-orphan')
    reservations = db.relationship('StockReservation', back_populates='item', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<InventoryItem {self.sku} - {self.nombre}>'

    @property
    def total_stock(self):
        """Stock total en todos los depósitos"""
        return sum(stock.cantidad for stock in self.stocks)

    @property
    def reserved_stock(self):
        """Stock reservado activo"""
        return sum(res.qty for res in self.reservations if res.estado == 'activa')

    @property
    def available_stock(self):
        """Stock disponible (total - reservado)"""
        return self.total_stock - self.reserved_stock

    @property
    def is_low_stock(self):
        """Verifica si el stock está bajo"""
        return self.total_stock <= self.min_stock

    @property
    def package_options(self):
        """Opciones de presentación configuradas para el item."""
        raw = self.package_options_raw
        if not raw:
            return []

        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []

        normalized = []
        if isinstance(data, list):
            for entry in data:
                option = self._normalize_package_option(entry)
                if option:
                    normalized.append(option)
        elif isinstance(data, dict):
            option = self._normalize_package_option(data)
            if option:
                normalized.append(option)

        return normalized

    @package_options.setter
    def package_options(self, value):
        options = []
        if isinstance(value, dict):
            maybe_option = self._normalize_package_option(value)
            if maybe_option:
                options.append(maybe_option)
        elif isinstance(value, list):
            for entry in value:
                maybe_option = self._normalize_package_option(entry)
                if maybe_option:
                    options.append(maybe_option)

        if options:
            self.package_options_raw = json.dumps(options)
        else:
            self.package_options_raw = None

    @staticmethod
    def _normalize_package_option(entry):
        if not isinstance(entry, dict):
            return None

        label = (entry.get('label') or entry.get('nombre') or entry.get('name') or '').strip()
        if not label:
            return None

        unit = (entry.get('unit') or entry.get('unidad') or entry.get('presentation_unit') or '').strip()
        multiplier = entry.get('multiplier') or entry.get('factor') or entry.get('cantidad')

        try:
            multiplier_val = float(multiplier)
        except (TypeError, ValueError):
            return None

        key = (entry.get('key') or entry.get('id') or label.lower())
        key = ''.join(ch for ch in key if ch.isalnum() or ch in ('_', '-')).strip('_-')
        if not key:
            key = label.lower().replace(' ', '_')

        return {
            'key': key,
            'label': label,
            'unit': unit or 'unidad',
            'multiplier': multiplier_val,
        }

    @property
    def package_summary(self):
        options = self.package_options
        if not options:
            return ''
        return ', '.join(option['label'] for option in options)


class Warehouse(db.Model):
    __tablename__ = 'warehouse'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.String(500))
    tipo = db.Column(db.String(20), nullable=False, default='deposito')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)

    # Relaciones
    company = db.relationship('Organizacion', backref='warehouses')
    stocks = db.relationship('Stock', back_populates='warehouse', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Warehouse {self.nombre}>'

    @property
    def tipo_normalizado(self) -> str:
        value = (self.tipo or 'deposito').lower()
        return 'obra' if value == 'obra' else 'deposito'

    @property
    def grupo_display(self) -> str:
        return 'Obras' if self.tipo_normalizado == 'obra' else 'Depósitos'


class Stock(db.Model):
    __tablename__ = 'stock'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=False)
    cantidad = db.Column(db.Numeric(14, 3), default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    item = db.relationship('InventoryItem', back_populates='stocks')
    warehouse = db.relationship('Warehouse', back_populates='stocks')

    __table_args__ = (
        db.UniqueConstraint('item_id', 'warehouse_id', name='uq_stock_item_warehouse'),
    )

    def __repr__(self):
        return f'<Stock {self.item.nombre} @ {self.warehouse.nombre}: {self.cantidad}>'


class StockMovement(db.Model):
    __tablename__ = 'stock_movement'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    tipo = db.Column(db.Enum('ingreso', 'egreso', 'transferencia', 'ajuste', name='movement_tipo'), nullable=False)
    qty = db.Column(db.Numeric(14, 3), nullable=False)
    origen_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    destino_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    project_id = db.Column(db.Integer, db.ForeignKey('obras.id'))
    motivo = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    item = db.relationship('InventoryItem', back_populates='movements')
    origen_warehouse = db.relationship('Warehouse', foreign_keys=[origen_warehouse_id])
    destino_warehouse = db.relationship('Warehouse', foreign_keys=[destino_warehouse_id])
    project = db.relationship('Obra', backref='inventory_movements')
    user = db.relationship('Usuario', backref='inventory_movements')

    def __repr__(self):
        return f'<StockMovement {self.tipo} - {self.item.nombre}>'

    @property
    def warehouse_display(self):
        """Muestra el depósito relevante según el tipo de movimiento"""
        if self.tipo == 'ingreso':
            return self.destino_warehouse.nombre if self.destino_warehouse else 'N/A'
        elif self.tipo == 'egreso':
            return self.origen_warehouse.nombre if self.origen_warehouse else 'N/A'
        elif self.tipo == 'transferencia':
            return f"{self.origen_warehouse.nombre} → {self.destino_warehouse.nombre}"
        else:  # ajuste
            return self.destino_warehouse.nombre if self.destino_warehouse else 'N/A'


class StockReservation(db.Model):
    __tablename__ = 'stock_reservation'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    qty = db.Column(db.Numeric(14, 3), nullable=False)
    estado = db.Column(db.Enum('activa', 'liberada', 'consumida', name='reservation_estado'), default='activa')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    item = db.relationship('InventoryItem', back_populates='reservations')
    project = db.relationship('Obra', backref='inventory_reservations')
    creator = db.relationship('Usuario', backref='inventory_reservations')

    def __repr__(self):
        return f'<StockReservation {self.item.nombre} - {self.project.nombre}>'


class GlobalMaterialCatalog(db.Model):
    """
    Catálogo global de materiales compartido entre todas las organizaciones.
    Permite estandarización de códigos y comparación de precios.
    """
    __tablename__ = 'global_material_catalog'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(200), nullable=False)
    categoria_nombre = db.Column(db.String(100), nullable=False, index=True)
    descripcion = db.Column(db.Text)
    unidad = db.Column(db.String(20), nullable=False)

    # Metadatos para variantes
    marca = db.Column(db.String(100), index=True)
    peso_cantidad = db.Column(db.Numeric(10, 3))
    peso_unidad = db.Column(db.String(20))
    especificaciones = db.Column(JSONB)

    # Estadísticas de uso
    veces_usado = db.Column(db.Integer, default=0)
    precio_promedio_ars = db.Column(db.Numeric(10, 2))
    precio_promedio_usd = db.Column(db.Numeric(10, 2))

    # Auditoría
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_org_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'))

    # Relaciones
    created_by_org = db.relationship('Organizacion', foreign_keys=[created_by_org_id])
    usages = db.relationship('GlobalMaterialUsage', back_populates='material', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<GlobalMaterialCatalog {self.codigo} - {self.nombre}>'

    @property
    def descripcion_completa(self):
        """Genera descripción completa incluyendo marca y especificaciones"""
        parts = [self.nombre]

        if self.marca:
            parts.append(f"marca {self.marca}")

        if self.peso_cantidad and self.peso_unidad:
            parts.append(f"{self.peso_cantidad}{self.peso_unidad}")

        if self.descripcion:
            parts.append(self.descripcion)

        return ", ".join(parts)

    @classmethod
    def generar_codigo_automatico(cls, categoria_nombre, nombre, marca=None, especificaciones=None):
        """
        Genera código automático único basado en categoría, nombre y variantes.

        Formato: CATEGORIA-NOMBRE-VARIANTES
        Ejemplo: CEM-PORT-50KG-LN (Cemento Portland 50kg Loma Negra)
        """
        import re

        # Prefijo de categoría (primeras 3 letras)
        cat_prefix = re.sub(r'[^A-Z]', '', categoria_nombre.upper())[:3]

        # Nombre abreviado (primeras 4 letras significativas)
        nombre_words = nombre.upper().split()
        nombre_prefix = ''.join([w[:4] for w in nombre_words[:2]])[:4]

        # Construir código base
        codigo_base = f"{cat_prefix}-{nombre_prefix}"

        # Agregar variantes si existen
        if especificaciones:
            if isinstance(especificaciones, str):
                try:
                    especificaciones = json.loads(especificaciones)
                except:
                    especificaciones = {}

            # Extraer peso/medida
            if 'peso' in especificaciones or 'medidas' in especificaciones:
                medida = especificaciones.get('peso') or especificaciones.get('medidas', '')
                if medida:
                    medida_clean = re.sub(r'[^A-Z0-9]', '', str(medida).upper())
                    codigo_base += f"-{medida_clean[:5]}"

        # Agregar marca si existe
        if marca:
            marca_prefix = re.sub(r'[^A-Z]', '', marca.upper())[:2]
            codigo_base += f"-{marca_prefix}"

        # Verificar si ya existe y agregar sufijo numérico si es necesario
        codigo_final = codigo_base
        contador = 1

        while cls.query.filter_by(codigo=codigo_final).first():
            codigo_final = f"{codigo_base}-{contador}"
            contador += 1

        return codigo_final

    @classmethod
    def buscar_similares(cls, nombre, categoria_nombre=None, marca=None, limit=10):
        """
        Busca materiales similares en el catálogo global.
        Usa búsqueda por similitud de texto.
        """
        from sqlalchemy import func, or_

        query = cls.query

        # Filtrar por categoría si se especifica
        if categoria_nombre:
            query = query.filter(cls.categoria_nombre.ilike(f'%{categoria_nombre}%'))

        # Búsqueda por similitud de nombre usando trigram
        if nombre:
            search_term = f'%{nombre}%'
            query = query.filter(
                or_(
                    cls.nombre.ilike(search_term),
                    cls.descripcion.ilike(search_term)
                )
            )

        # Filtrar por marca si se especifica
        if marca:
            query = query.filter(cls.marca.ilike(f'%{marca}%'))

        # Ordenar por veces usado (más popular primero)
        query = query.order_by(cls.veces_usado.desc())

        return query.limit(limit).all()


class GlobalMaterialUsage(db.Model):
    """
    Trackea qué organizaciones usan cada material del catálogo global.
    Permite análisis de mercado y estadísticas.
    """
    __tablename__ = 'global_material_usage'

    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey('global_material_catalog.id', ondelete='CASCADE'), nullable=False)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='CASCADE'), nullable=False)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id', ondelete='CASCADE'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    material = db.relationship('GlobalMaterialCatalog', back_populates='usages')
    organizacion = db.relationship('Organizacion')
    item_inventario = db.relationship('ItemInventario')

    __table_args__ = (
        db.UniqueConstraint('material_id', 'organizacion_id', 'item_inventario_id'),
    )

    def __repr__(self):
        return f'<GlobalMaterialUsage {self.material.codigo} by org {self.organizacion_id}>'


# ============================================================
# SISTEMA DE REQUERIMIENTOS DE COMPRA
# ============================================================

class RequerimientoCompra(db.Model):
    """
    Solicitud de compra originada desde una obra cuando falta material/maquinaria.
    Permite trackear el ciclo completo desde la solicitud hasta la entrega.
    """
    __tablename__ = 'requerimientos_compra'

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), unique=True, nullable=False)  # RC-2024-0001
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    solicitante_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Estado del requerimiento
    estado = db.Column(db.String(20), default='pendiente')
    # Estados: pendiente, aprobado, rechazado, en_proceso, completado, cancelado

    # Prioridad
    prioridad = db.Column(db.String(20), default='normal')  # baja, normal, alta, urgente

    # Motivo/descripción
    motivo = db.Column(db.Text, nullable=False)
    notas_aprobacion = db.Column(db.Text)  # Notas del administrador al aprobar/rechazar

    # Fechas
    fecha_solicitud = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_necesidad = db.Column(db.Date)  # Cuándo se necesita el material
    fecha_aprobacion = db.Column(db.DateTime)
    fecha_completado = db.Column(db.DateTime)

    # Usuario que aprobó/rechazó
    aprobador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))

    # Relaciones
    organizacion = db.relationship('Organizacion', backref='requerimientos_compra')
    obra = db.relationship('Obra', backref='requerimientos_compra')
    solicitante = db.relationship('Usuario', foreign_keys=[solicitante_id], backref='requerimientos_solicitados')
    aprobador = db.relationship('Usuario', foreign_keys=[aprobador_id], backref='requerimientos_aprobados')
    items = db.relationship('RequerimientoCompraItem', back_populates='requerimiento',
                           cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<RequerimientoCompra {self.numero}>'

    @classmethod
    def generar_numero(cls, organizacion_id):
        """Genera un número único para el requerimiento"""
        year = datetime.utcnow().year
        ultimo = cls.query.filter(
            cls.organizacion_id == organizacion_id,
            cls.numero.like(f'RC-{year}-%')
        ).order_by(cls.id.desc()).first()

        if ultimo and ultimo.numero:
            try:
                ultimo_num = int(ultimo.numero.split('-')[-1])
            except:
                ultimo_num = 0
        else:
            ultimo_num = 0

        return f'RC-{year}-{str(ultimo_num + 1).zfill(4)}'

    @property
    def estado_display(self):
        """Retorna el nombre legible del estado"""
        estados = {
            'pendiente': 'Pendiente de Aprobación',
            'aprobado': 'Aprobado',
            'rechazado': 'Rechazado',
            'en_proceso': 'En Proceso de Compra',
            'completado': 'Completado',
            'cancelado': 'Cancelado'
        }
        return estados.get(self.estado, self.estado)

    @property
    def estado_color(self):
        """Retorna el color Bootstrap para el estado"""
        colores = {
            'pendiente': 'warning',
            'aprobado': 'info',
            'rechazado': 'danger',
            'en_proceso': 'primary',
            'completado': 'success',
            'cancelado': 'secondary'
        }
        return colores.get(self.estado, 'secondary')

    @property
    def prioridad_display(self):
        """Retorna el nombre legible de la prioridad"""
        prioridades = {
            'baja': 'Baja',
            'normal': 'Normal',
            'alta': 'Alta',
            'urgente': 'Urgente'
        }
        return prioridades.get(self.prioridad, self.prioridad)

    @property
    def prioridad_color(self):
        """Retorna el color Bootstrap para la prioridad"""
        colores = {
            'baja': 'secondary',
            'normal': 'info',
            'alta': 'warning',
            'urgente': 'danger'
        }
        return colores.get(self.prioridad, 'secondary')

    @property
    def total_items(self):
        """Retorna la cantidad de items en el requerimiento"""
        return self.items.count()

    @property
    def costo_estimado_total(self):
        """Calcula el costo estimado total del requerimiento"""
        total = 0
        for item in self.items:
            if item.costo_estimado:
                total += float(item.costo_estimado) * float(item.cantidad)
        return total

    @property
    def costo_compra_total(self):
        """Calcula el costo real total de compra"""
        total = 0
        for item in self.items:
            total += item.subtotal_compra
        return total

    @property
    def tiene_precios_compra(self):
        """Verifica si al menos un item tiene precio de compra cargado"""
        return any(item.precio_unitario_compra for item in self.items)

    def aprobar(self, aprobador_id, notas=None):
        """Aprueba el requerimiento"""
        self.estado = 'aprobado'
        self.aprobador_id = aprobador_id
        self.fecha_aprobacion = datetime.utcnow()
        if notas:
            self.notas_aprobacion = notas

    def rechazar(self, aprobador_id, notas=None):
        """Rechaza el requerimiento"""
        self.estado = 'rechazado'
        self.aprobador_id = aprobador_id
        self.fecha_aprobacion = datetime.utcnow()
        if notas:
            self.notas_aprobacion = notas

    def marcar_en_proceso(self):
        """Marca el requerimiento como en proceso de compra"""
        self.estado = 'en_proceso'

    def completar(self):
        """Marca el requerimiento como completado"""
        self.estado = 'completado'
        self.fecha_completado = datetime.utcnow()


class RequerimientoCompraItem(db.Model):
    """
    Ítem individual dentro de un requerimiento de compra.
    """
    __tablename__ = 'requerimiento_compra_items'

    id = db.Column(db.Integer, primary_key=True)
    requerimiento_id = db.Column(db.Integer, db.ForeignKey('requerimientos_compra.id', ondelete='CASCADE'), nullable=False)

    # Puede estar vinculado a un item de inventario o ser texto libre
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=True)
    descripcion = db.Column(db.String(300), nullable=False)  # Descripción del material/equipo
    codigo = db.Column(db.String(50))  # Código si existe

    # Cantidades
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    unidad = db.Column(db.String(30), default='unidad')

    # Cantidad planificada (del presupuesto) vs cantidad actual en obra
    cantidad_planificada = db.Column(db.Numeric(10, 3), default=0)
    cantidad_actual_obra = db.Column(db.Numeric(10, 3), default=0)

    # Costo estimado (opcional)
    costo_estimado = db.Column(db.Numeric(15, 2))
    moneda = db.Column(db.String(3), default='ARS')

    # Costo real de compra (se carga cuando se compra)
    precio_unitario_compra = db.Column(db.Numeric(15, 2))
    cantidad_comprada = db.Column(db.Numeric(10, 3))
    proveedor_compra = db.Column(db.String(200))
    factura_compra = db.Column(db.String(100))
    fecha_compra = db.Column(db.Date)

    # Notas adicionales
    notas = db.Column(db.Text)

    # Tipo: material, maquinaria, herramienta, equipo
    tipo = db.Column(db.String(30), default='material')

    # Relaciones
    requerimiento = db.relationship('RequerimientoCompra', back_populates='items')
    item_inventario = db.relationship('ItemInventario', backref='requerimientos')

    def __repr__(self):
        return f'<RequerimientoCompraItem {self.descripcion}>'

    @property
    def deficit(self):
        """Calcula el déficit (cantidad planificada - cantidad actual en obra)"""
        plan = float(self.cantidad_planificada or 0)
        actual = float(self.cantidad_actual_obra or 0)
        return max(0, plan - actual)

    @property
    def subtotal_estimado(self):
        """Calcula el subtotal estimado"""
        if self.costo_estimado and self.cantidad:
            return float(self.costo_estimado) * float(self.cantidad)
        return 0

    @property
    def subtotal_compra(self):
        """Calcula el subtotal real de compra"""
        precio = float(self.precio_unitario_compra or 0)
        cant = float(self.cantidad_comprada or self.cantidad or 0)
        return precio * cant if precio > 0 else 0


# ============================================================
# ORDENES DE COMPRA
# ============================================================

class OrdenCompra(db.Model):
    """Orden de compra formal generada a partir de un requerimiento aprobado."""
    __tablename__ = 'ordenes_compra'

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), unique=True, nullable=False)  # OC-2026-0001
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    requerimiento_id = db.Column(db.Integer, db.ForeignKey('requerimientos_compra.id'), nullable=True)

    # Proveedor (FK a ProveedorOC + campos texto como snapshot/fallback)
    proveedor_oc_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id'), nullable=True)
    proveedor = db.Column(db.String(200), nullable=False)
    proveedor_cuit = db.Column(db.String(20))
    proveedor_contacto = db.Column(db.String(200))

    # Estado: borrador, emitida, recibida_parcial, completada, cancelada
    estado = db.Column(db.String(20), default='borrador')

    # Montos
    moneda = db.Column(db.String(3), default='ARS')
    subtotal = db.Column(db.Numeric(15, 2), default=0)
    iva = db.Column(db.Numeric(15, 2), default=0)
    total = db.Column(db.Numeric(15, 2), default=0)

    # Fechas
    fecha_emision = db.Column(db.Date)
    fecha_entrega_estimada = db.Column(db.Date)
    fecha_entrega_real = db.Column(db.Date)

    # Condiciones
    condicion_pago = db.Column(db.String(100))
    notas = db.Column(db.Text)

    # Auditoría
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion', backref='ordenes_compra')
    obra = db.relationship('Obra', backref='ordenes_compra')
    requerimiento = db.relationship('RequerimientoCompra', backref='ordenes_compra')
    proveedor_oc = db.relationship('ProveedorOC', foreign_keys=[proveedor_oc_id])
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])
    items = db.relationship('OrdenCompraItem', back_populates='orden_compra',
                           cascade='all, delete-orphan', lazy='dynamic')
    recepciones = db.relationship('RecepcionOC', back_populates='orden_compra',
                                 cascade='all, delete-orphan', lazy='dynamic')

    @classmethod
    def generar_numero(cls, organizacion_id):
        year = datetime.utcnow().year
        ultimo = cls.query.filter(
            cls.organizacion_id == organizacion_id,
            cls.numero.like(f'OC-{year}-%')
        ).order_by(cls.id.desc()).first()
        if ultimo and ultimo.numero:
            try:
                ultimo_num = int(ultimo.numero.split('-')[-1])
            except Exception:
                ultimo_num = 0
        else:
            ultimo_num = 0
        return f'OC-{year}-{str(ultimo_num + 1).zfill(4)}'

    @property
    def estado_display(self):
        estados = {
            'borrador': 'Borrador',
            'emitida': 'Emitida',
            'recibida_parcial': 'Recibida Parcial',
            'completada': 'Completada',
            'cancelada': 'Cancelada'
        }
        return estados.get(self.estado, self.estado)

    @property
    def estado_color(self):
        colores = {
            'borrador': 'secondary',
            'emitida': 'primary',
            'recibida_parcial': 'warning',
            'completada': 'success',
            'cancelada': 'danger'
        }
        return colores.get(self.estado, 'secondary')

    @property
    def total_items(self):
        return self.items.count()

    def recalcular_totales(self):
        """Recalcula subtotal, IVA y total desde los items."""
        sub = sum(float(i.subtotal or 0) for i in self.items)
        self.subtotal = sub
        self.iva = sub * 0.21
        self.total = sub * 1.21

    def porcentaje_recepcion(self):
        """Porcentaje de recepción global."""
        total_q = sum(float(i.cantidad or 0) for i in self.items)
        recibido_q = sum(float(i.cantidad_recibida or 0) for i in self.items)
        if total_q <= 0:
            return 0
        return round((recibido_q / total_q) * 100, 1)


class OrdenCompraItem(db.Model):
    """Ítem individual de una orden de compra."""
    __tablename__ = 'orden_compra_items'

    id = db.Column(db.Integer, primary_key=True)
    orden_compra_id = db.Column(db.Integer, db.ForeignKey('ordenes_compra.id', ondelete='CASCADE'), nullable=False)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=True)
    descripcion = db.Column(db.String(300), nullable=False)
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    unidad = db.Column(db.String(30), default='unidad')
    precio_unitario = db.Column(db.Numeric(15, 2), default=0)
    subtotal = db.Column(db.Numeric(15, 2), default=0)
    cantidad_recibida = db.Column(db.Numeric(10, 3), default=0)

    # Relaciones
    orden_compra = db.relationship('OrdenCompra', back_populates='items')
    item_inventario = db.relationship('ItemInventario')

    @property
    def recepcion_completa(self):
        return float(self.cantidad_recibida or 0) >= float(self.cantidad or 0)

    @property
    def pendiente_recibir(self):
        return max(0, float(self.cantidad or 0) - float(self.cantidad_recibida or 0))


class RecepcionOC(db.Model):
    """Registro de recepción de materiales de una OC."""
    __tablename__ = 'recepciones_oc'

    id = db.Column(db.Integer, primary_key=True)
    orden_compra_id = db.Column(db.Integer, db.ForeignKey('ordenes_compra.id', ondelete='CASCADE'), nullable=False)
    fecha_recepcion = db.Column(db.Date, nullable=False)
    recibido_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    remito_numero = db.Column(db.String(100))
    notas = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    orden_compra = db.relationship('OrdenCompra', back_populates='recepciones')
    recibido_por = db.relationship('Usuario')
    items = db.relationship('RecepcionOCItem', back_populates='recepcion',
                           cascade='all, delete-orphan')


class RecepcionOCItem(db.Model):
    """Ítem recibido en una recepción de OC."""
    __tablename__ = 'recepcion_oc_items'

    id = db.Column(db.Integer, primary_key=True)
    recepcion_id = db.Column(db.Integer, db.ForeignKey('recepciones_oc.id', ondelete='CASCADE'), nullable=False)
    oc_item_id = db.Column(db.Integer, db.ForeignKey('orden_compra_items.id'), nullable=False)
    cantidad_recibida = db.Column(db.Numeric(10, 3), nullable=False)

    # Relaciones
    recepcion = db.relationship('RecepcionOC', back_populates='items')
    oc_item = db.relationship('OrdenCompraItem')


# ============================================================
# REMITOS
# ============================================================

class Remito(db.Model):
    """Remito de proveedor recibido en obra."""
    __tablename__ = 'remitos'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    orden_compra_id = db.Column(db.Integer, db.ForeignKey('ordenes_compra.id'), nullable=True)

    numero_remito = db.Column(db.String(50), nullable=False)       # Nro del proveedor
    proveedor = db.Column(db.String(200), nullable=False)
    proveedor_oc_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id'), nullable=True)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    estado = db.Column(db.String(20), default='recibido')          # recibido, con_observaciones, rechazado
    recibido_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    notas = db.Column(db.Text)
    archivo_url = db.Column(db.String(500))                        # Foto/PDF del remito físico

    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion')
    obra = db.relationship('Obra', backref=db.backref('remitos', lazy='dynamic'))
    orden_compra = db.relationship('OrdenCompra')
    proveedor_ref = db.relationship('ProveedorOC', foreign_keys=[proveedor_oc_id])
    recibido_por = db.relationship('Usuario', foreign_keys=[recibido_por_id])
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])
    items = db.relationship('RemitoItem', back_populates='remito',
                            cascade='all, delete-orphan', lazy='joined')

    __table_args__ = (
        db.Index('ix_remito_obra', 'obra_id'),
        db.Index('ix_remito_oc', 'orden_compra_id'),
    )

    @property
    def estado_display(self):
        return {'recibido': 'Recibido', 'con_observaciones': 'Con observaciones',
                'rechazado': 'Rechazado'}.get(self.estado, self.estado)

    @property
    def estado_color(self):
        return {'recibido': 'success', 'con_observaciones': 'warning',
                'rechazado': 'danger'}.get(self.estado, 'secondary')

    @property
    def total_items(self):
        return len(self.items)


class RemitoItem(db.Model):
    """Item dentro de un remito."""
    __tablename__ = 'remito_items'

    id = db.Column(db.Integer, primary_key=True)
    remito_id = db.Column(db.Integer, db.ForeignKey('remitos.id', ondelete='CASCADE'), nullable=False)
    descripcion = db.Column(db.String(300), nullable=False)
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    unidad = db.Column(db.String(20), default='u')                # u, kg, m2, m3, ml, l, bolsa, etc.
    observacion = db.Column(db.String(300))                        # Observación por item

    # Relaciones
    remito = db.relationship('Remito', back_populates='items')
