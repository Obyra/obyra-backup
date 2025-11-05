"""
Modelos de Marketplace y Comercio

Este módulo contiene todos los modelos relacionados con:
- Órdenes de compra y sus items
- Comisiones de órdenes
- Carrito de compras
- Pagos a proveedores
- Sistema de eventos y actividades
"""

from datetime import datetime
import os
from extensions import db


class Order(db.Model):
    __tablename__ = 'order'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    estado = db.Column(db.Enum('pendiente', 'pagado', 'entregado', 'cancelado', name='order_estado'), default='pendiente')
    payment_method = db.Column(db.Enum('online', 'offline', name='payment_method'))
    payment_status = db.Column(db.Enum('init', 'approved', 'rejected', 'refunded', name='payment_status'), default='init')
    payment_ref = db.Column(db.String(100))  # ID de pago de MP
    buyer_invoice_url = db.Column(db.String(500))  # Factura del proveedor al comprador
    supplier_invoice_number = db.Column(db.String(50))
    supplier_invoice_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    company = db.relationship('Organizacion', backref='supplier_orders')
    supplier = db.relationship('Supplier', back_populates='orders')
    items = db.relationship('OrderItem', back_populates='order', cascade='all, delete-orphan')
    commission = db.relationship('OrderCommission', back_populates='order', uselist=False, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Order {self.id}>'

    @property
    def commission_amount(self):
        """Calcula la comisión (2% del total)"""
        rate = float(os.environ.get('PLATFORM_COMMISSION_RATE', '0.02'))
        return round(float(self.total) * rate, 2)

    @property
    def is_paid(self):
        return self.payment_status == 'approved'


class OrderItem(db.Model):
    __tablename__ = 'order_item'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=False)
    qty = db.Column(db.Numeric(12, 2), nullable=False)
    precio_unit = db.Column(db.Numeric(12, 2), nullable=False)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)

    # Relaciones
    order = db.relationship('Order', back_populates='items')
    variant = db.relationship('ProductVariant', back_populates='order_items')

    def __repr__(self):
        return f'<OrderItem {self.order_id}-{self.variant.sku}>'


class OrderCommission(db.Model):
    __tablename__ = 'order_commission'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    base = db.Column(db.Numeric(12, 2), nullable=False)  # Total del pedido
    rate = db.Column(db.Numeric(5, 4), default=0.02)  # 2%
    monto = db.Column(db.Numeric(12, 2), nullable=False)  # Comisión sin IVA
    iva = db.Column(db.Numeric(12, 2), default=0)  # IVA sobre la comisión
    total = db.Column(db.Numeric(12, 2), nullable=False)  # Comisión + IVA
    status = db.Column(db.Enum('pendiente', 'facturado', 'cobrado', 'anulado', name='commission_status'), default='pendiente')
    invoice_number = db.Column(db.String(50))
    invoice_pdf_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    order = db.relationship('Order', back_populates='commission')

    def __repr__(self):
        return f'<OrderCommission {self.order_id}>'

    @staticmethod
    def compute_commission(base, rate=0.02, iva_included=False):
        """Calcula la comisión con o sin IVA"""
        monto = round(float(base) * rate, 2)
        if iva_included:
            # Aplicar gross-up para IVA (21%)
            iva = round(monto * 0.21, 2)
            total = monto + iva
        else:
            iva = 0
            total = monto

        return {
            'monto': monto,
            'iva': iva,
            'total': total
        }


class Cart(db.Model):
    __tablename__ = 'cart'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))  # Usuario logueado (opcional)
    session_id = db.Column(db.String(64))  # Para usuarios anónimos
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    user = db.relationship('Usuario', backref='carts')
    items = db.relationship('CartItem', back_populates='cart', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Cart {self.id}>'

    @property
    def total_items(self):
        return sum(item.qty for item in self.items)

    @property
    def total_amount(self):
        return sum(item.subtotal for item in self.items)

    def clear(self):
        """Vacía el carrito"""
        CartItem.query.filter_by(cart_id=self.id).delete()
        db.session.commit()


class CartItem(db.Model):
    __tablename__ = 'cart_item'

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('cart.id'), nullable=False)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    qty = db.Column(db.Numeric(12, 2), nullable=False)
    precio_snapshot = db.Column(db.Numeric(12, 2), nullable=False)  # Precio al momento de agregar
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    cart = db.relationship('Cart', back_populates='items')
    variant = db.relationship('ProductVariant', backref='cart_items')
    supplier = db.relationship('Supplier', backref='cart_items')

    def __repr__(self):
        return f'<CartItem {self.variant.sku} x{self.qty}>'

    @property
    def subtotal(self):
        return self.precio_snapshot * self.qty


class SupplierPayout(db.Model):
    __tablename__ = 'supplier_payout'

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))  # Puede ser NULL
    tipo = db.Column(db.Enum('ingreso', 'deuda', 'pago_comision', name='payout_tipo'), nullable=False)
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    saldo_resultante = db.Column(db.Numeric(12, 2), nullable=False)
    nota = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    supplier = db.relationship('Supplier', back_populates='payouts')
    order = db.relationship('Order', backref='payouts')

    def __repr__(self):
        return f'<SupplierPayout {self.supplier_id}-{self.tipo}>'


class Event(db.Model):
    """
    Modelo para registrar eventos del sistema que alimentan el feed de actividad.
    Incluye alertas, cambios de estado, hitos, etc.
    """
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)  # Nullable para eventos globales
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)  # Usuario que generó el evento

    # Tipo de evento
    type = db.Column(db.Enum(
        'alert', 'milestone', 'delay', 'cost_overrun', 'stock_low',
        'status_change', 'budget_created', 'inventory_alert', 'custom',
        name='event_type'
    ), nullable=False)

    # Severidad del evento
    severity = db.Column(db.Enum(
        'baja', 'media', 'alta', 'critica',
        name='event_severity'
    ), nullable=True)

    # Contenido del evento
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    meta = db.Column(db.JSON)  # Metadata adicional del evento

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    # Relaciones
    company = db.relationship('Organizacion', backref='events')
    project = db.relationship('Obra', backref='events')
    user = db.relationship('Usuario', foreign_keys=[user_id], backref='generated_events')
    creator = db.relationship('Usuario', foreign_keys=[created_by], backref='created_events')

    # Índices
    __table_args__ = (
        db.Index('idx_events_company_created', 'company_id', 'created_at'),
        db.Index('idx_events_project', 'project_id'),
        db.Index('idx_events_type', 'type'),
    )

    @property
    def type_icon(self):
        """Retorna el icono FontAwesome correspondiente al tipo de evento"""
        icons = {
            'alert': 'fas fa-exclamation-triangle',
            'milestone': 'fas fa-flag-checkered',
            'delay': 'fas fa-clock',
            'cost_overrun': 'fas fa-dollar-sign',
            'stock_low': 'fas fa-boxes',
            'status_change': 'fas fa-exchange-alt',
            'budget_created': 'fas fa-calculator',
            'inventory_alert': 'fas fa-warehouse',
            'custom': 'fas fa-info-circle'
        }
        return icons.get(self.type, 'fas fa-bell')

    @property
    def severity_badge_class(self):
        """Retorna la clase CSS Bootstrap para el badge de severidad"""
        classes = {
            'critica': 'badge bg-danger',
            'alta': 'badge bg-warning',
            'media': 'badge bg-warning text-dark',
            'baja': 'badge bg-secondary'
        }
        return classes.get(self.severity, 'badge bg-secondary')

    @property
    def time_ago(self):
        """Retorna tiempo transcurrido en formato legible"""
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        diff = now - self.created_at

        if diff.days > 7:
            return self.created_at.strftime('%d/%m/%Y')
        elif diff.days > 0:
            return f'hace {diff.days} día{"s" if diff.days > 1 else ""}'
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f'hace {hours} hora{"s" if hours > 1 else ""}'
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f'hace {minutes} min'
        else:
            return 'hace un momento'

    def __repr__(self):
        return f'<Event {self.id}: {self.title}>'
