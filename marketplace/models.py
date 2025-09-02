"""
OBYRA Marketplace Models - ISOLATED TABLES WITH mk_ PREFIX
Following strict instructions - NO modification of existing tables
"""

from app import db
from datetime import datetime
from sqlalchemy import func
import json

class MkProduct(db.Model):
    __tablename__ = 'mk_products'
    
    id = db.Column(db.Integer, primary_key=True)
    seller_company_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    category_id = db.Column(db.Integer, nullable=True)
    description_html = db.Column(db.Text)
    is_masked_seller = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    variants = db.relationship('MkProductVariant', backref='product', lazy='dynamic')

class MkProductVariant(db.Model):
    __tablename__ = 'mk_product_variants'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('mk_products.id'), nullable=False)
    sku = db.Column(db.String(100), nullable=False, unique=True)
    price = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS', nullable=False)
    stock_qty = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MkCart(db.Model):
    __tablename__ = 'mk_carts'
    
    id = db.Column(db.Integer, primary_key=True)
    buyer_company_id = db.Column(db.Integer, nullable=False)
    buyer_user_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    items = db.relationship('MkCartItem', backref='cart', lazy='dynamic', cascade='all, delete-orphan')
    
    @property
    def total_amount(self):
        return sum(item.total_price for item in self.items)
    
    @property
    def items_by_seller(self):
        """Group cart items by seller company for display"""
        groups = {}
        for item in self.items:
            seller_id = item.variant.product.seller_company_id
            if seller_id not in groups:
                groups[seller_id] = []
            groups[seller_id].append(item)
        return groups

class MkCartItem(db.Model):
    __tablename__ = 'mk_cart_items'
    
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('mk_carts.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('mk_product_variants.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    price_snapshot = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    variant = db.relationship('MkProductVariant', backref='cart_items')
    
    @property
    def total_price(self):
        return self.price_snapshot * self.qty

class MkOrder(db.Model):
    __tablename__ = 'mk_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    buyer_company_id = db.Column(db.Integer, nullable=False)
    buyer_user_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='pending', nullable=False)  # pending, paid, shipped, delivered, cancelled
    total = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS', nullable=False)
    billing_json = db.Column(db.Text)
    shipping_json = db.Column(db.Text)
    payment_status = db.Column(db.String(50), default='pending')  # pending, approved, rejected
    payment_method = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    items = db.relationship('MkOrderItem', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    payments = db.relationship('MkPayment', backref='order', lazy='dynamic')
    purchase_orders = db.relationship('MkPurchaseOrder', backref='order', lazy='dynamic')
    
    @property
    def order_number(self):
        return f"ORD-{self.id:06d}"
    
    @property
    def billing_data(self):
        return json.loads(self.billing_json) if self.billing_json else {}
    
    @property
    def shipping_data(self):
        return json.loads(self.shipping_json) if self.shipping_json else {}

class MkOrderItem(db.Model):
    __tablename__ = 'mk_order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('mk_orders.id'), nullable=False)
    seller_company_id = db.Column(db.Integer, nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('mk_product_variants.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS', nullable=False)
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    commission_amount = db.Column(db.Numeric(12, 2), default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    variant = db.relationship('MkProductVariant', backref='order_items')
    
    @property
    def total_amount(self):
        return self.unit_price * self.qty

class MkPayment(db.Model):
    __tablename__ = 'mk_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('mk_orders.id'), nullable=False)
    provider = db.Column(db.String(50), nullable=False)  # mercadopago, stripe, etc
    provider_ref = db.Column(db.String(255))  # external payment ID
    status = db.Column(db.String(50), nullable=False)  # pending, approved, rejected
    paid_at = db.Column(db.DateTime)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default='ARS', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MkPurchaseOrder(db.Model):
    __tablename__ = 'mk_purchase_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('mk_orders.id'), nullable=False)
    seller_company_id = db.Column(db.Integer, nullable=False)
    buyer_company_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='created')  # created, sent, confirmed, shipped
    oc_number = db.Column(db.String(100), nullable=False, unique=True)
    pdf_url = db.Column(db.String(500))
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MkCommission(db.Model):
    __tablename__ = 'mk_commissions'
    
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, nullable=False)
    exposure = db.Column(db.String(20), nullable=False)  # standard, premium
    take_rate_pct = db.Column(db.Numeric(5, 2), nullable=False)  # e.g., 10.50 for 10.5%
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('category_id', 'exposure', name='unique_category_exposure'),)