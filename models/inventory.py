"""Modelos de Inventario y Gestión de Stock"""

from datetime import datetime, date
from extensions import db
import json


class CategoriaInventario(db.Model):
    __tablename__ = 'categorias_inventario'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    tipo = db.Column(db.String(20), nullable=False)  # material, herramienta, maquinaria

    # Relaciones
    items = db.relationship('ItemInventario', back_populates='categoria', lazy='dynamic')

    def __repr__(self):
        return f'<CategoriaInventario {self.nombre}>'


class ItemInventario(db.Model):
    __tablename__ = 'items_inventario'

    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias_inventario.id'), nullable=False)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    unidad = db.Column(db.String(20), nullable=False)
    stock_actual = db.Column(db.Numeric(10, 3), default=0)
    stock_minimo = db.Column(db.Numeric(10, 3), default=0)
    precio_promedio = db.Column(db.Numeric(10, 2), default=0)  # Precio en ARS
    precio_promedio_usd = db.Column(db.Numeric(10, 2), default=0)  # Precio en USD
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)

    # Relaciones
    categoria = db.relationship('CategoriaInventario', back_populates='items')
    organizacion = db.relationship('Organizacion', back_populates='inventario')
    movimientos = db.relationship('MovimientoInventario', back_populates='item', lazy='dynamic')
    usos = db.relationship('UsoInventario', back_populates='item', lazy='dynamic')

    def __repr__(self):
        return f'<ItemInventario {self.codigo} - {self.nombre}>'

    @property
    def necesita_reposicion(self):
        return self.stock_actual <= self.stock_minimo


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

    # Relaciones
    obra = db.relationship('Obra', back_populates='uso_inventario')
    item = db.relationship('ItemInventario', back_populates='usos')
    usuario = db.relationship('Usuario')

    def __repr__(self):
        return f'<UsoInventario {self.obra.nombre} - {self.item.nombre}>'


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
