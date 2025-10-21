"""
Blueprint del Marketplace público - Listado de productos y detalle
"""

from flask import Blueprint, render_template, request, abort, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy import or_, and_, desc
from app.extensions import db
from models import Product, ProductVariant, Category, Supplier
from decimal import Decimal
import re

marketplace_bp = Blueprint('marketplace', __name__, url_prefix='/market')


@marketplace_bp.route('/productos')
def productos():
    """Listado público de productos con filtros y búsqueda"""
    # Parámetros de búsqueda y filtros
    q = request.args.get('q', '').strip()
    categoria_id = request.args.get('categoria', type=int)
    precio_min = request.args.get('precio_min', type=float)
    precio_max = request.args.get('precio_max', type=float)
    ubicacion = request.args.get('ubicacion', '').strip()
    verificado = request.args.get('verificado', type=bool)
    rating_min = request.args.get('rating_min', type=float)
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    # Query base: solo productos publicados
    query = Product.query.filter(Product.estado == 'publicado').join(Supplier)
    
    # Búsqueda por texto
    if q:
        search_filter = or_(
            Product.nombre.ilike(f'%{q}%'),
            Product.descripcion.ilike(f'%{q}%'),
            Supplier.razon_social.ilike(f'%{q}%')
        )
        query = query.filter(search_filter)
    
    # Filtro por categoría
    if categoria_id:
        query = query.filter(Product.category_id == categoria_id)
    
    # Filtro por ubicación del proveedor
    if ubicacion:
        query = query.filter(Supplier.ubicacion.ilike(f'%{ubicacion}%'))
    
    # Filtro por verificación del proveedor
    if verificado:
        query = query.filter(Supplier.verificado == True)
    
    # Filtro por rating mínimo del proveedor
    if rating_min:
        # Note: Aquí asumo que hay un campo rating en Supplier, ajustar según el modelo real
        pass  # query = query.filter(Supplier.rating >= rating_min)
    
    # Filtros de precio requieren subconsulta a variantes
    if precio_min or precio_max:
        variant_subquery = db.session.query(ProductVariant.product_id).filter(
            ProductVariant.visible == True,
            ProductVariant.precio > 0
        )
        
        if precio_min:
            variant_subquery = variant_subquery.filter(ProductVariant.precio >= precio_min)
        if precio_max:
            variant_subquery = variant_subquery.filter(ProductVariant.precio <= precio_max)
        
        query = query.filter(Product.id.in_(variant_subquery))
    
    # Ordenamiento por relevancia/fecha
    query = query.order_by(desc(Product.published_at), desc(Product.visitas))
    
    # Paginación
    productos_paginados = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    
    # Obtener categorías para el filtro
    categorias = Category.query.order_by(Category.nombre).all()
    
    return render_template('marketplace/productos.html',
                         productos=productos_paginados.items,
                         pagination=productos_paginados,
                         categorias=categorias,
                         filtros={
                             'q': q,
                             'categoria_id': categoria_id,
                             'precio_min': precio_min,
                             'precio_max': precio_max,
                             'ubicacion': ubicacion,
                             'verificado': verificado,
                             'rating_min': rating_min
                         })


@marketplace_bp.route('/p/<slug>')
def producto_detalle(slug):
    """Detalle de producto por slug"""
    producto = Product.query.filter_by(slug=slug, estado='publicado').first_or_404()
    
    # Incrementar contador de visitas
    producto.increment_visits()
    
    # Obtener variantes visibles con stock
    variantes = ProductVariant.query.filter_by(
        product_id=producto.id,
        visible=True
    ).filter(ProductVariant.stock > 0).all()
    
    # Q&A del producto
    qnas = producto.qnas[:10]  # Limitamos a 10 Q&A más recientes
    
    # Productos relacionados (misma categoría, mismo proveedor)
    productos_relacionados = Product.query.filter(
        and_(
            Product.estado == 'publicado',
            Product.id != producto.id,
            or_(
                Product.category_id == producto.category_id,
                Product.supplier_id == producto.supplier_id
            )
        )
    ).limit(4).all()
    
    return render_template('marketplace/producto_detalle.html',
                         producto=producto,
                         variantes=variantes,
                         qnas=qnas,
                         productos_relacionados=productos_relacionados)


@marketplace_bp.route('/categoria/<int:categoria_id>')
def categoria(categoria_id):
    """Productos de una categoría específica"""
    categoria = Category.query.get_or_404(categoria_id)
    
    return redirect(url_for('marketplace.productos', categoria=categoria_id))


@marketplace_bp.route('/proveedor/<int:supplier_id>')
def proveedor_tienda(supplier_id):
    """Tienda del proveedor con sus productos"""
    proveedor = Supplier.query.get_or_404(supplier_id)
    
    # Solo productos publicados del proveedor
    productos = Product.query.filter_by(
        supplier_id=supplier_id,
        estado='publicado'
    ).order_by(desc(Product.published_at)).all()
    
    return render_template('marketplace/proveedor_tienda.html',
                         proveedor=proveedor,
                         productos=productos)


def generate_slug(nombre):
    """Genera un slug SEO-friendly desde el nombre del producto"""
    # Convertir a minúsculas y quitar caracteres especiales
    slug = re.sub(r'[^\w\s-]', '', nombre.lower())
    # Reemplazar espacios y guiones múltiples por un solo guión
    slug = re.sub(r'[-\s]+', '-', slug)
    # Quitar guiones al inicio y final
    slug = slug.strip('-')
    
    # Verificar unicidad
    original_slug = slug
    counter = 1
    while Product.query.filter_by(slug=slug).first():
        slug = f"{original_slug}-{counter}"
        counter += 1
    
    return slug