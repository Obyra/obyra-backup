# Modelos para el módulo de Inventario
from app import db
from datetime import datetime
from sqlalchemy import Index, UniqueConstraint

class InventoryCategory(db.Model):
    __tablename__ = 'inventory_category'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
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
            current_id = getattr(current, "id", None)
            if current_id is not None:
                if current_id in visited:
                    break
                visited.add(current_id)

            parts.append(current.nombre)
            current = current.parent

        return " \u2192 ".join(reversed(parts))

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


class Warehouse(db.Model):
    __tablename__ = 'warehouse'
    
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)
    
    # Relaciones
    company = db.relationship('Organizacion', backref='warehouses')
    stocks = db.relationship('Stock', back_populates='warehouse', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Warehouse {self.nombre}>'


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
        UniqueConstraint('item_id', 'warehouse_id', name='uq_stock_item_warehouse'),
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


# Índices para optimización
Index('idx_stock_item_warehouse', Stock.item_id, Stock.warehouse_id)
Index('idx_stock_movement_item_fecha', StockMovement.item_id, StockMovement.fecha)
Index('idx_inventory_item_sku', InventoryItem.sku)
Index('idx_inventory_item_nombre', InventoryItem.nombre)