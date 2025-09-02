"""
OBYRA Market - Comprehensive Marketplace Models
Following ML-like B2B marketplace specification with seller masking
"""
from datetime import datetime, date
from flask_login import UserMixin
from app import db
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import JSON
import uuid
import json


# ===== EMPRESAS Y USUARIOS =====

class MarketCompany(db.Model):
    """Empresas compradoras y vendedoras del marketplace"""
    __tablename__ = 'market_companies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    cuit = db.Column(db.String(13), unique=True, nullable=False)
    type = db.Column(db.Enum('buyer', 'seller', 'both', name='company_type'), nullable=False)
    iva_condition = db.Column(db.String(50), nullable=False)  # RI, EXENTO, MONOTRIBUTO
    billing_email = db.Column(db.String(120), nullable=False)
    address_json = db.Column(JSON)
    is_active = db.Column(db.Boolean, default=True)
    kyc_status = db.Column(db.Enum('pending', 'approved', 'rejected', name='kyc_status'), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    users = db.relationship('MarketUser', back_populates='company', lazy='dynamic')
    seller_products = db.relationship('MarketProduct', foreign_keys='MarketProduct.seller_company_id', lazy='dynamic')
    buyer_orders = db.relationship('MarketOrder', foreign_keys='MarketOrder.buyer_company_id', lazy='dynamic')
    
    def __repr__(self):
        return f'<MarketCompany {self.name}>'


class MarketUser(UserMixin, db.Model):
    """Usuarios del marketplace"""
    __tablename__ = 'market_users'
    
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.Enum('buyer_admin', 'buyer_user', 'seller_admin', 'seller_operator', 'backoffice_admin', name='market_role'), nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    company = db.relationship('MarketCompany', back_populates='users')
    
    def __repr__(self):
        return f'<MarketUser {self.name}>'


# ===== CATÁLOGO =====

class MarketCategory(db.Model):
    """Categorías del marketplace"""
    __tablename__ = 'market_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('market_categories.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    parent = db.relationship('MarketCategory', remote_side=[id], backref='children')
    products = db.relationship('MarketProduct', back_populates='category')
    attributes = db.relationship('MarketAttribute', back_populates='category')
    commissions = db.relationship('MarketCommission', back_populates='category')
    
    def __repr__(self):
        return f'<MarketCategory {self.name}>'
    
    @property
    def full_path(self):
        if self.parent:
            return f"{self.parent.full_path} > {self.name}"
        return self.name


class MarketAttribute(db.Model):
    """Atributos por categoría"""
    __tablename__ = 'market_attributes'
    
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('market_categories.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), nullable=False)
    data_type = db.Column(db.Enum('text', 'number', 'boolean', 'select', name='attr_type'), nullable=False)
    is_required = db.Column(db.Boolean, default=False)
    options_json = db.Column(JSON)  # Para select
    
    # Relaciones
    category = db.relationship('MarketCategory', back_populates='attributes')
    
    def __repr__(self):
        return f'<MarketAttribute {self.code}>'


class MarketBrand(db.Model):
    """Marcas de productos"""
    __tablename__ = 'market_brands'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    logo_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    
    # Relaciones
    products = db.relationship('MarketProduct', back_populates='brand')
    
    def __repr__(self):
        return f'<MarketBrand {self.name}>'


class MarketProduct(db.Model):
    """Productos del marketplace"""
    __tablename__ = 'market_products'
    
    id = db.Column(db.Integer, primary_key=True)
    seller_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey('market_brands.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('market_categories.id'), nullable=False)
    description_html = db.Column(db.Text)
    warranty_months = db.Column(db.Integer, default=0)
    is_masked_seller = db.Column(db.Boolean, default=True)  # Seller masking
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    seller = db.relationship('MarketCompany', foreign_keys=[seller_company_id])
    brand = db.relationship('MarketBrand', back_populates='products')
    category = db.relationship('MarketCategory', back_populates='products')
    images = db.relationship('MarketProductImage', back_populates='product', cascade='all, delete-orphan')
    files = db.relationship('MarketProductFile', back_populates='product', cascade='all, delete-orphan')
    variants = db.relationship('MarketProductVariant', back_populates='product', cascade='all, delete-orphan')
    publications = db.relationship('MarketPublication', back_populates='product', cascade='all, delete-orphan')
    questions = db.relationship('MarketQuestion', back_populates='product', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<MarketProduct {self.name}>'
    
    @property
    def masked_seller_name(self):
        """Retorna nombre del vendedor enmascarado"""
        return "OBYRA Partner" if self.is_masked_seller else self.seller.name


class MarketProductImage(db.Model):
    """Imágenes de productos"""
    __tablename__ = 'market_product_images'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('market_products.id'), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    position = db.Column(db.Integer, default=0)
    
    # Relaciones
    product = db.relationship('MarketProduct', back_populates='images')
    
    def __repr__(self):
        return f'<MarketProductImage {self.url}>'


class MarketProductFile(db.Model):
    """Archivos técnicos de productos"""
    __tablename__ = 'market_product_files'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('market_products.id'), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.Enum('techsheet', 'manual', 'certificate', name='file_type'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    
    # Relaciones
    product = db.relationship('MarketProduct', back_populates='files')
    
    def __repr__(self):
        return f'<MarketProductFile {self.filename}>'


class MarketProductVariant(db.Model):
    """Variantes de productos (SKUs)"""
    __tablename__ = 'market_product_variants'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('market_products.id'), nullable=False)
    sku = db.Column(db.String(100), unique=True, nullable=False)
    gtin = db.Column(db.String(14))  # Código de barras
    price = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS')
    compare_at_price = db.Column(db.Numeric(12, 2))  # Precio tachado
    tax_class = db.Column(db.String(20), default='IVA_21')
    
    # Dimensiones para envíos
    weight_kg = db.Column(db.Numeric(8, 3), nullable=False)
    length_cm = db.Column(db.Numeric(6, 2), nullable=False)
    width_cm = db.Column(db.Numeric(6, 2), nullable=False)
    height_cm = db.Column(db.Numeric(6, 2), nullable=False)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    product = db.relationship('MarketProduct', back_populates='variants')
    attributes = db.relationship('MarketVariantAttribute', back_populates='variant', cascade='all, delete-orphan')
    inventories = db.relationship('MarketInventory', back_populates='variant', cascade='all, delete-orphan')
    cart_items = db.relationship('MarketCartItem', back_populates='variant')
    
    def __repr__(self):
        return f'<MarketProductVariant {self.sku}>'
    
    @property
    def total_stock(self):
        """Stock total en todas las ubicaciones"""
        return sum(inv.stock_on_hand for inv in self.inventories)
    
    @property
    def available_stock(self):
        """Stock disponible (total - reservado)"""
        return sum(inv.stock_on_hand - inv.stock_reserved for inv in self.inventories)


class MarketVariantAttribute(db.Model):
    """Atributos específicos de cada variante"""
    __tablename__ = 'market_variant_attributes'
    
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('market_product_variants.id'), nullable=False)
    attr_id = db.Column(db.Integer, db.ForeignKey('market_attributes.id'), nullable=False)
    value = db.Column(db.String(500), nullable=False)
    
    # Relaciones
    variant = db.relationship('MarketProductVariant', back_populates='attributes')
    attribute = db.relationship('MarketAttribute')
    
    def __repr__(self):
        return f'<MarketVariantAttribute {self.attribute.code}: {self.value}>'


class MarketInventoryLocation(db.Model):
    """Ubicaciones/sucursales de inventario"""
    __tablename__ = 'market_inventory_locations'
    
    id = db.Column(db.Integer, primary_key=True)
    seller_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    address_json = db.Column(JSON)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relaciones
    seller = db.relationship('MarketCompany')
    inventories = db.relationship('MarketInventory', back_populates='location')
    
    def __repr__(self):
        return f'<MarketInventoryLocation {self.name}>'


class MarketInventory(db.Model):
    """Stock por variante y ubicación"""
    __tablename__ = 'market_inventories'
    
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('market_product_variants.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('market_inventory_locations.id'), nullable=False)
    stock_on_hand = db.Column(db.Integer, default=0)
    stock_reserved = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    variant = db.relationship('MarketProductVariant', back_populates='inventories')
    location = db.relationship('MarketInventoryLocation', back_populates='inventories')
    
    __table_args__ = (db.UniqueConstraint('variant_id', 'location_id', name='uq_inventory_variant_location'),)
    
    def __repr__(self):
        return f'<MarketInventory {self.variant.sku}@{self.location.name}: {self.stock_on_hand}>'


class MarketPublication(db.Model):
    """Publicaciones de productos"""
    __tablename__ = 'market_publications'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('market_products.id'), nullable=False)
    exposure = db.Column(db.Enum('clasica', 'premium', name='publication_exposure'), default='clasica')
    status = db.Column(db.Enum('draft', 'active', 'paused', 'banned', name='publication_status'), default='draft')
    start_at = db.Column(db.DateTime, default=datetime.utcnow)
    end_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    product = db.relationship('MarketProduct', back_populates='publications')
    
    def __repr__(self):
        return f'<MarketPublication {self.product.name} - {self.status}>'


# ===== CARRITO Y ÓRDENES =====

class MarketCart(db.Model):
    """Carritos de compra"""
    __tablename__ = 'market_carts'
    
    id = db.Column(db.Integer, primary_key=True)
    buyer_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    buyer_user_id = db.Column(db.Integer, db.ForeignKey('market_users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    buyer_company = db.relationship('MarketCompany')
    buyer_user = db.relationship('MarketUser')
    items = db.relationship('MarketCartItem', back_populates='cart', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<MarketCart {self.buyer_company.name}>'
    
    @property
    def total_amount(self):
        """Total del carrito"""
        return sum(item.total_price for item in self.items)
    
    @property
    def items_by_seller(self):
        """Agrupa items por vendedor"""
        sellers = {}
        for item in self.items:
            seller_id = item.variant.product.seller_company_id
            if seller_id not in sellers:
                sellers[seller_id] = []
            sellers[seller_id].append(item)
        return sellers


class MarketCartItem(db.Model):
    """Items del carrito"""
    __tablename__ = 'market_cart_items'
    
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('market_carts.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('market_product_variants.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    price_snapshot = db.Column(db.Numeric(12, 2), nullable=False)  # Precio al momento de agregar
    currency = db.Column(db.String(3), default='ARS')
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    cart = db.relationship('MarketCart', back_populates='items')
    variant = db.relationship('MarketProductVariant', back_populates='cart_items')
    
    def __repr__(self):
        return f'<MarketCartItem {self.variant.sku} x{self.qty}>'
    
    @property
    def total_price(self):
        return self.price_snapshot * self.qty


class MarketOrder(db.Model):
    """Órdenes de compra"""
    __tablename__ = 'market_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    buyer_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    buyer_user_id = db.Column(db.Integer, db.ForeignKey('market_users.id'), nullable=False)
    
    # Estados de orden
    status = db.Column(db.Enum('pending', 'paid', 'processing', 'shipped', 'delivered', 'cancelled', 'refunded', name='order_status'), default='pending')
    
    # Totales
    total = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS')
    
    # Datos de facturación y envío
    billing_json = db.Column(JSON, nullable=False)
    shipping_json = db.Column(JSON, nullable=False)
    
    # Pagos
    payment_status = db.Column(db.Enum('pending', 'paid', 'failed', 'refunded', name='payment_status'), default='pending')
    payment_method = db.Column(db.String(50))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    buyer_company = db.relationship('MarketCompany', foreign_keys=[buyer_company_id])
    buyer_user = db.relationship('MarketUser')
    items = db.relationship('MarketOrderItem', back_populates='order', cascade='all, delete-orphan')
    status_history = db.relationship('MarketOrderStatusHistory', back_populates='order', cascade='all, delete-orphan')
    payments = db.relationship('MarketPayment', back_populates='order', cascade='all, delete-orphan')
    purchase_orders = db.relationship('MarketPurchaseOrder', back_populates='order', cascade='all, delete-orphan')
    shipments = db.relationship('MarketShipment', back_populates='order', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<MarketOrder #{self.id}>'
    
    @property
    def order_number(self):
        """Número de orden formateado"""
        return f"OBY-{self.id:06d}"


class MarketOrderItem(db.Model):
    """Items de la orden"""
    __tablename__ = 'market_order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('market_orders.id'), nullable=False)
    seller_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('market_product_variants.id'), nullable=False)
    
    qty = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS')
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    commission_amount = db.Column(db.Numeric(12, 2), default=0)
    
    # Seller masking - se revela después del pago
    seller_revealed = db.Column(db.Boolean, default=False)
    
    # Relaciones
    order = db.relationship('MarketOrder', back_populates='items')
    seller = db.relationship('MarketCompany', foreign_keys=[seller_company_id])
    variant = db.relationship('MarketProductVariant')
    
    def __repr__(self):
        return f'<MarketOrderItem {self.variant.sku} x{self.qty}>'
    
    @property
    def total_price(self):
        return self.unit_price * self.qty


class MarketOrderStatusHistory(db.Model):
    """Historial de estados de orden"""
    __tablename__ = 'market_order_status_history'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('market_orders.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    actor = db.Column(db.String(100))  # Quien hizo el cambio
    
    # Relaciones
    order = db.relationship('MarketOrder', back_populates='status_history')
    
    def __repr__(self):
        return f'<MarketOrderStatusHistory {self.status}>'


class MarketPurchaseOrder(db.Model):
    """Órdenes de Compra generadas para cada seller"""
    __tablename__ = 'market_purchase_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('market_orders.id'), nullable=False)
    seller_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    buyer_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    
    status = db.Column(db.Enum('created', 'sent', 'acknowledged', 'fulfilled', name='po_status'), default='created')
    oc_number = db.Column(db.String(50), unique=True)
    pdf_url = db.Column(db.String(500))
    sent_at = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    order = db.relationship('MarketOrder', back_populates='purchase_orders')
    seller = db.relationship('MarketCompany', foreign_keys=[seller_company_id])
    buyer = db.relationship('MarketCompany', foreign_keys=[buyer_company_id])
    
    def __repr__(self):
        return f'<MarketPurchaseOrder {self.oc_number}>'


# ===== ENVÍOS =====

class MarketShipment(db.Model):
    """Envíos"""
    __tablename__ = 'market_shipments'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('market_orders.id'), nullable=False)
    seller_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    
    carrier = db.Column(db.String(50))  # Andreani, OCA, etc.
    tracking_code = db.Column(db.String(100))
    cost = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.Enum('preparing', 'shipped', 'in_transit', 'delivered', 'failed', name='shipment_status'), default='preparing')
    label_url = db.Column(db.String(500))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    shipped_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    
    # Relaciones
    order = db.relationship('MarketOrder', back_populates='shipments')
    seller = db.relationship('MarketCompany')
    items = db.relationship('MarketShipmentItem', back_populates='shipment', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<MarketShipment {self.tracking_code}>'


class MarketShipmentItem(db.Model):
    """Items en cada envío"""
    __tablename__ = 'market_shipment_items'
    
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('market_shipments.id'), nullable=False)
    order_item_id = db.Column(db.Integer, db.ForeignKey('market_order_items.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    
    # Relaciones
    shipment = db.relationship('MarketShipment', back_populates='items')
    order_item = db.relationship('MarketOrderItem')
    
    def __repr__(self):
        return f'<MarketShipmentItem x{self.qty}>'


# ===== COMISIONES Y PAGOS =====

class MarketCommission(db.Model):
    """Configuración de comisiones por categoría"""
    __tablename__ = 'market_commissions'
    
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('market_categories.id'), nullable=False)
    exposure = db.Column(db.Enum('clasica', 'premium', name='commission_exposure'), nullable=False)
    take_rate_pct = db.Column(db.Numeric(5, 2), nullable=False)  # Porcentaje de comisión
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    category = db.relationship('MarketCategory', back_populates='commissions')
    
    __table_args__ = (db.UniqueConstraint('category_id', 'exposure', name='uq_commission_cat_exp'),)
    
    def __repr__(self):
        return f'<MarketCommission {self.category.name} {self.exposure}: {self.take_rate_pct}%>'


class MarketFee(db.Model):
    """Fees adicionales"""
    __tablename__ = 'market_fees'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    amount_fixed = db.Column(db.Numeric(10, 2), default=0)
    amount_pct = db.Column(db.Numeric(5, 4), default=0)  # Porcentaje con 4 decimales
    applies_to = db.Column(db.String(50))  # order, installment, etc.
    is_active = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f'<MarketFee {self.name}>'


class MarketPayment(db.Model):
    """Pagos de órdenes"""
    __tablename__ = 'market_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('market_orders.id'), nullable=False)
    provider = db.Column(db.Enum('mercadopago', 'bank', 'manual', name='payment_provider'), nullable=False)
    provider_ref = db.Column(db.String(100))  # ID del proveedor
    status = db.Column(db.Enum('pending', 'approved', 'rejected', 'cancelled', 'refunded', name='payment_status'), default='pending')
    paid_at = db.Column(db.DateTime)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    order = db.relationship('MarketOrder', back_populates='payments')
    
    def __repr__(self):
        return f'<MarketPayment {self.provider_ref}>'


class MarketPayout(db.Model):
    """Liquidaciones a sellers"""
    __tablename__ = 'market_payouts'
    
    id = db.Column(db.Integer, primary_key=True)
    seller_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    cycle_month = db.Column(db.String(7), nullable=False)  # YYYY-MM
    
    total_gross = db.Column(db.Numeric(12, 2), default=0)
    total_commissions = db.Column(db.Numeric(12, 2), default=0)
    total_fees = db.Column(db.Numeric(12, 2), default=0)
    total_net = db.Column(db.Numeric(12, 2), default=0)
    
    status = db.Column(db.Enum('calculating', 'ready', 'paid', name='payout_status'), default='calculating')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)
    
    # Relaciones
    seller = db.relationship('MarketCompany')
    items = db.relationship('MarketPayoutItem', back_populates='payout', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<MarketPayout {self.seller.name} {self.cycle_month}>'


class MarketPayoutItem(db.Model):
    """Items de liquidación"""
    __tablename__ = 'market_payout_items'
    
    id = db.Column(db.Integer, primary_key=True)
    payout_id = db.Column(db.Integer, db.ForeignKey('market_payouts.id'), nullable=False)
    order_item_id = db.Column(db.Integer, db.ForeignKey('market_order_items.id'), nullable=False)
    net_amount = db.Column(db.Numeric(12, 2), nullable=False)
    
    # Relaciones
    payout = db.relationship('MarketPayout', back_populates='items')
    order_item = db.relationship('MarketOrderItem')
    
    def __repr__(self):
        return f'<MarketPayoutItem ${self.net_amount}>'


# ===== Q&A Y REPUTACIÓN =====

class MarketQuestion(db.Model):
    """Preguntas sobre productos"""
    __tablename__ = 'market_questions'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('market_products.id'), nullable=False)
    buyer_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    buyer_user_id = db.Column(db.Integer, db.ForeignKey('market_users.id'), nullable=False)
    
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    answered_at = db.Column(db.DateTime)
    
    # Relaciones
    product = db.relationship('MarketProduct', back_populates='questions')
    buyer = db.relationship('MarketCompany', foreign_keys=[buyer_company_id])
    user = db.relationship('MarketUser')
    
    def __repr__(self):
        return f'<MarketQuestion #{self.id}>'


class MarketRating(db.Model):
    """Calificaciones de productos y sellers"""
    __tablename__ = 'market_ratings'
    
    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey('market_order_items.id'), nullable=False)
    buyer_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    seller_company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('market_products.id'), nullable=False)
    
    # Calificaciones
    product_rating = db.Column(db.Integer, nullable=False)  # 1-5 estrellas
    seller_rating = db.Column(db.Integer, nullable=False)   # 1-5 estrellas
    
    # Comentarios
    product_comment = db.Column(db.Text)
    seller_comment = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    order_item = db.relationship('MarketOrderItem')
    buyer = db.relationship('MarketCompany', foreign_keys=[buyer_company_id])
    seller = db.relationship('MarketCompany', foreign_keys=[seller_company_id])
    product = db.relationship('MarketProduct')
    
    def __repr__(self):
        return f'<MarketRating P:{self.product_rating} S:{self.seller_rating}>'


# ===== EVENTOS =====

class MarketEvent(db.Model):
    """Log de eventos del marketplace"""
    __tablename__ = 'market_events'
    
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('market_companies.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('market_users.id'), nullable=True)
    
    entity_type = db.Column(db.String(50))  # product, order, shipment, etc.
    entity_id = db.Column(db.Integer)
    
    data = db.Column(JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    company = db.relationship('MarketCompany')
    user = db.relationship('MarketUser')
    
    def __repr__(self):
        return f'<MarketEvent {self.event_type}>'