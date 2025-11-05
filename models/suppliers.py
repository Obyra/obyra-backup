"""
Modelos de Proveedores y Productos
"""

from datetime import datetime
from decimal import Decimal
from extensions import db
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash


# ===== MODELOS LEGACY DE PROVEEDORES =====

class Proveedor(db.Model):
    """Modelo legacy de Proveedor"""
    __tablename__ = 'proveedores'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    categoria = db.Column(db.String(100), nullable=False)  # materiales, equipos, servicios, profesionales
    especialidad = db.Column(db.String(200))  # subcategoría específica
    ubicacion = db.Column(db.String(300))
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(120))
    sitio_web = db.Column(db.String(200))
    precio_promedio = db.Column(db.Numeric(15, 2))  # Precio promedio por servicio/producto
    calificacion = db.Column(db.Numeric(3, 2), default=5.0)  # Calificación de 1 a 5
    trabajos_completados = db.Column(db.Integer, default=0)
    verificado = db.Column(db.Boolean, default=False)  # Verificado por la plataforma
    activo = db.Column(db.Boolean, default=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion')
    cotizaciones = db.relationship('SolicitudCotizacion', back_populates='proveedor', lazy='dynamic')

    def __repr__(self):
        return f'<Proveedor {self.nombre}>'

    @property
    def calificacion_estrellas(self):
        """Devuelve la calificación en formato de estrellas"""
        return round(float(self.calificacion), 1)


class CategoriaProveedor(db.Model):
    """Modelo legacy de Categoría de Proveedor"""
    __tablename__ = 'categorias_proveedor'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    icono = db.Column(db.String(50))  # Clase de FontAwesome
    activa = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<CategoriaProveedor {self.nombre}>'


class SolicitudCotizacion(db.Model):
    """Modelo legacy de Solicitud de Cotización"""
    __tablename__ = 'solicitudes_cotizacion'

    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores.id'), nullable=False)
    solicitante_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, cotizada, aceptada, rechazada
    fecha_solicitud = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_respuesta = db.Column(db.DateTime)
    precio_cotizado = db.Column(db.Numeric(15, 2))
    notas_proveedor = db.Column(db.Text)
    tiempo_entrega_dias = db.Column(db.Integer)

    # Relaciones
    proveedor = db.relationship('Proveedor', back_populates='cotizaciones')
    solicitante = db.relationship('Usuario')

    def __repr__(self):
        return f'<SolicitudCotizacion {self.id} - {self.estado}>'


# ===== MODELOS NUEVOS DE PROVEEDORES =====

class Supplier(db.Model):
    """Modelo nuevo de Proveedor con soporte para tienda online"""
    __tablename__ = 'supplier'

    id = db.Column(db.Integer, primary_key=True)
    razon_social = db.Column(db.String(200), nullable=False)
    cuit = db.Column(db.String(15), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    direccion = db.Column(db.Text)
    descripcion = db.Column(db.Text)
    ubicacion = db.Column(db.String(100))  # Ciudad/Provincia
    estado = db.Column(db.Enum('activo', 'suspendido', name='supplier_estado'), default='activo')
    verificado = db.Column(db.Boolean, default=False)
    mp_collector_id = db.Column(db.String(50))  # Para Mercado Pago
    logo_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    users = db.relationship('SupplierUser', back_populates='supplier', cascade='all, delete-orphan')
    products = db.relationship('Product', back_populates='supplier', cascade='all, delete-orphan')
    orders = db.relationship('Order', back_populates='supplier')
    payouts = db.relationship('SupplierPayout', back_populates='supplier', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Supplier {self.razon_social}>'

    @property
    def active_products_count(self):
        return Product.query.filter_by(supplier_id=self.id, estado='publicado').count()

    @property
    def total_orders_value(self):
        total = db.session.query(func.sum(Order.total)).filter_by(
            supplier_id=self.id,
            payment_status='approved'
        ).scalar()
        return total or 0


class SupplierUser(db.Model):
    """Usuario de Proveedor con roles específicos"""
    __tablename__ = 'supplier_user'

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.Enum('owner', 'editor', name='supplier_user_rol'), default='editor')
    activo = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    supplier = db.relationship('Supplier', back_populates='users')

    def __repr__(self):
        return f'<SupplierUser {self.email}>'

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    @property
    def is_owner(self):
        return self.rol == 'owner'

    # Compatibilidad con plantillas que consultan current_user.es_admin()
    def es_admin(self):
        return False


# ===== MODELOS DE CATEGORÍAS Y PRODUCTOS =====

class Category(db.Model):
    """Categoría de Productos (estructura jerárquica)"""
    __tablename__ = 'category'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    parent = db.relationship('Category', remote_side=[id], backref='children')
    products = db.relationship('Product', back_populates='category')

    def __repr__(self):
        return f'<Category {self.nombre}>'

    @property
    def full_path(self):
        if self.parent:
            return f"{self.parent.full_path} > {self.nombre}"
        return self.nombre


class Product(db.Model):
    """Producto ofrecido por un Proveedor"""
    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False)  # SEO friendly URL
    descripcion = db.Column(db.Text)
    estado = db.Column(db.Enum('borrador', 'publicado', 'pausado', name='product_estado'), default='borrador')
    rating_prom = db.Column(db.Numeric(2, 1), default=0)
    published_at = db.Column(db.DateTime)  # Fecha de publicación
    visitas = db.Column(db.Integer, default=0)  # Contador de visitas
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    supplier = db.relationship('Supplier', back_populates='products')
    category = db.relationship('Category', back_populates='products')
    variants = db.relationship('ProductVariant', back_populates='product', cascade='all, delete-orphan')
    images = db.relationship('ProductImage', back_populates='product', cascade='all, delete-orphan')
    qnas = db.relationship('ProductQNA', back_populates='product', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Product {self.nombre}>'

    @property
    def can_publish(self):
        """Verifica si el producto puede ser publicado"""
        has_visible_variant = any(v.visible and v.precio > 0 and v.stock > 0 for v in self.variants)
        has_image = len(self.images) > 0
        return has_visible_variant and has_image

    @property
    def main_image(self):
        """Obtiene la imagen principal (primera en orden)"""
        return self.images[0] if self.images else None

    @property
    def min_price(self):
        """Precio mínimo de las variantes visibles"""
        visible_variants = [v for v in self.variants if v.visible and v.precio > 0]
        return min(v.precio for v in visible_variants) if visible_variants else 0

    @property
    def cover_url(self):
        """URL de la imagen principal"""
        main_image = self.main_image
        return main_image.url if main_image else '/static/img/product-placeholder.jpg'

    def increment_visits(self):
        """Incrementa el contador de visitas"""
        self.visitas = (self.visitas or 0) + 1
        db.session.commit()


class ProductVariant(db.Model):
    """Variante de un Producto (color, talla, etc.)"""
    __tablename__ = 'product_variant'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    sku = db.Column(db.String(100), unique=True, nullable=False)
    atributos_json = db.Column(db.JSON)  # Ej: {"color": "rojo", "talla": "M"}
    unidad = db.Column(db.String(20), nullable=False)  # kg, m, u, etc.
    precio = db.Column(db.Numeric(12, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    stock = db.Column(db.Numeric(12, 2), default=0)
    visible = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    product = db.relationship('Product', back_populates='variants')
    order_items = db.relationship('OrderItem', back_populates='variant')

    def __repr__(self):
        return f'<ProductVariant {self.sku}>'

    @property
    def display_name(self):
        """Nombre para mostrar incluyendo atributos"""
        if self.atributos_json:
            attrs = ", ".join(f"{k}: {v}" for k, v in self.atributos_json.items())
            return f"{self.product.nombre} ({attrs})"
        return self.product.nombre

    @property
    def is_available(self):
        return self.visible and self.stock > 0 and self.product.estado == 'publicado'


class ProductImage(db.Model):
    """Imagen de un Producto"""
    __tablename__ = 'product_image'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    orden = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    product = db.relationship('Product', back_populates='images')

    def __repr__(self):
        return f'<ProductImage {self.filename}>'


class ProductQNA(db.Model):
    """Preguntas y Respuestas sobre Productos"""
    __tablename__ = 'product_qna'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))  # Puede ser NULL para anónimos
    pregunta = db.Column(db.Text, nullable=False)
    respuesta = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    answered_at = db.Column(db.DateTime)

    # Relaciones
    product = db.relationship('Product', back_populates='qnas')
    user = db.relationship('Usuario', backref='product_questions')

    def __repr__(self):
        return f'<ProductQNA {self.id}>'

    @property
    def is_answered(self):
        return self.respuesta is not None
