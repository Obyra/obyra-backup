from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from supplier_auth import supplier_login_required, get_current_supplier_user, get_current_supplier
from app.extensions import db
from models import (
    Supplier, Product, ProductVariant, ProductImage, ProductQNA, 
    Order, OrderCommission, Category
)
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import json
from sqlalchemy import func

supplier_portal_bp = Blueprint('supplier_portal', __name__, url_prefix='/proveedor')

@supplier_portal_bp.route('/')
@supplier_login_required
def dashboard():
    """Dashboard principal del proveedor"""
    supplier = get_current_supplier()
    
    # Métricas básicas
    total_productos = Product.query.filter_by(supplier_id=supplier.id).count()
    productos_publicados = Product.query.filter_by(supplier_id=supplier.id, estado='publicado').count()
    
    # Órdenes recientes
    ordenes_recientes = Order.query.filter_by(supplier_id=supplier.id).order_by(Order.created_at.desc()).limit(5).all()
    
    # Ventas del mes
    inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ventas_mes = db.session.query(func.sum(Order.total)).filter(
        Order.supplier_id == supplier.id,
        Order.payment_status == 'approved',
        Order.created_at >= inicio_mes
    ).scalar() or 0
    
    # Q&A pendientes
    qna_pendientes = db.session.query(ProductQNA).join(Product).filter(
        Product.supplier_id == supplier.id,
        ProductQNA.respuesta == None
    ).count()
    
    return render_template('supplier_portal/dashboard.html',
                         supplier=supplier,
                         total_productos=total_productos,
                         productos_publicados=productos_publicados,
                         ordenes_recientes=ordenes_recientes,
                         ventas_mes=ventas_mes,
                         qna_pendientes=qna_pendientes)

@supplier_portal_bp.route('/perfil', methods=['GET', 'POST'])
@supplier_login_required
def perfil():
    """Gestión del perfil del proveedor"""
    supplier = get_current_supplier()
    
    if request.method == 'POST':
        try:
            # Actualizar datos del proveedor
            supplier.razon_social = request.form.get('razon_social', '').strip()
            supplier.email = request.form.get('email', '').strip()
            supplier.phone = request.form.get('phone', '').strip()
            supplier.direccion = request.form.get('direccion', '').strip()
            supplier.descripcion = request.form.get('descripcion', '').strip()
            supplier.ubicacion = request.form.get('ubicacion', '').strip()
            
            # TODO: Manejar subida de logo
            
            db.session.commit()
            flash('Perfil actualizado exitosamente.', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash('Error al actualizar el perfil.', 'danger')
    
    return render_template('supplier_portal/perfil_form.html', supplier=supplier)

@supplier_portal_bp.route('/productos')
@supplier_login_required
def productos():
    """Lista de productos del proveedor"""
    supplier = get_current_supplier()
    
    # Filtros
    estado = request.args.get('estado')
    categoria_id = request.args.get('categoria')
    
    query = Product.query.filter_by(supplier_id=supplier.id)
    
    if estado:
        query = query.filter(Product.estado == estado)
    
    if categoria_id:
        query = query.filter(Product.category_id == categoria_id)
    
    productos = query.order_by(Product.updated_at.desc()).all()
    
    # Obtener categorías para filtros
    categorias = Category.query.all()
    
    return render_template('supplier_portal/productos_list.html',
                         productos=productos,
                         categorias=categorias,
                         filtros={'estado': estado, 'categoria': categoria_id})

@supplier_portal_bp.route('/productos/nuevo', methods=['GET', 'POST'])
@supplier_login_required
def nuevo_producto():
    """Crear nuevo producto"""
    supplier = get_current_supplier()
    categorias = Category.query.all()
    
    if request.method == 'POST':
        try:
            producto = Product(
                supplier_id=supplier.id,
                category_id=request.form.get('category_id'),
                nombre=request.form.get('nombre', '').strip(),
                descripcion=request.form.get('descripcion', '').strip()
            )
            
            db.session.add(producto)
            db.session.commit()
            
            flash('Producto creado exitosamente.', 'success')
            return redirect(url_for('supplier_portal.editar_producto', id=producto.id))
            
        except Exception as e:
            db.session.rollback()
            flash('Error al crear el producto.', 'danger')
    
    return render_template('supplier_portal/producto_form.html',
                         producto=None,
                         categorias=categorias)

@supplier_portal_bp.route('/productos/<int:id>/editar', methods=['GET', 'POST'])
@supplier_login_required
def editar_producto(id):
    """Editar producto existente"""
    supplier = get_current_supplier()
    producto = Product.query.filter_by(id=id, supplier_id=supplier.id).first_or_404()
    categorias = Category.query.all()
    
    if request.method == 'POST':
        try:
            producto.category_id = request.form.get('category_id')
            producto.nombre = request.form.get('nombre', '').strip()
            producto.descripcion = request.form.get('descripcion', '').strip()
            producto.updated_at = datetime.utcnow()
            
            db.session.commit()
            flash('Producto actualizado exitosamente.', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash('Error al actualizar el producto.', 'danger')
    
    return render_template('supplier_portal/producto_form.html',
                         producto=producto,
                         categorias=categorias)

@supplier_portal_bp.route('/productos/<int:id>/variantes/nueva', methods=['POST'])
@supplier_login_required
def nueva_variante(id):
    """Crear nueva variante de producto"""
    supplier = get_current_supplier()
    producto = Product.query.filter_by(id=id, supplier_id=supplier.id).first_or_404()
    
    try:
        # Procesar atributos JSON
        atributos = {}
        for key in request.form:
            if key.startswith('attr_'):
                attr_name = key[5:]  # Remover 'attr_'
                attr_value = request.form.get(key, '').strip()
                if attr_value:
                    atributos[attr_name] = attr_value
        
        variante = ProductVariant(
            product_id=producto.id,
            sku=request.form.get('sku', '').strip(),
            atributos_json=atributos if atributos else None,
            unidad=request.form.get('unidad', '').strip(),
            precio=float(request.form.get('precio', 0)),
            stock=float(request.form.get('stock', 0))
        )
        
        db.session.add(variante)
        db.session.commit()
        
        flash('Variante creada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al crear la variante.', 'danger')
    
    return redirect(url_for('supplier_portal.editar_producto', id=id))

@supplier_portal_bp.route('/variantes/<int:var_id>/editar', methods=['POST'])
@supplier_login_required
def editar_variante(var_id):
    """Editar variante existente"""
    supplier = get_current_supplier()
    variante = ProductVariant.query.join(Product).filter(
        ProductVariant.id == var_id,
        Product.supplier_id == supplier.id
    ).first_or_404()
    
    try:
        # Procesar atributos JSON
        atributos = {}
        for key in request.form:
            if key.startswith('attr_'):
                attr_name = key[5:]
                attr_value = request.form.get(key, '').strip()
                if attr_value:
                    atributos[attr_name] = attr_value
        
        variante.sku = request.form.get('sku', '').strip()
        variante.atributos_json = atributos if atributos else None
        variante.unidad = request.form.get('unidad', '').strip()
        variante.precio = float(request.form.get('precio', 0))
        variante.stock = float(request.form.get('stock', 0))
        variante.visible = bool(request.form.get('visible'))
        
        db.session.commit()
        flash('Variante actualizada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al actualizar la variante.', 'danger')
    
    return redirect(url_for('supplier_portal.editar_producto', id=variante.product_id))

@supplier_portal_bp.route('/variantes/<int:var_id>/pausar', methods=['POST'])
@supplier_login_required
def pausar_variante(var_id):
    """Pausar/despausar variante"""
    supplier = get_current_supplier()
    variante = ProductVariant.query.join(Product).filter(
        ProductVariant.id == var_id,
        Product.supplier_id == supplier.id
    ).first_or_404()
    
    try:
        variante.visible = not variante.visible
        db.session.commit()
        
        estado = "pausada" if not variante.visible else "activada"
        flash(f'Variante {estado} exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al cambiar el estado de la variante.', 'danger')
    
    return redirect(url_for('supplier_portal.editar_producto', id=variante.product_id))

@supplier_portal_bp.route('/variantes/<int:var_id>/eliminar', methods=['POST'])
@supplier_login_required
def eliminar_variante(var_id):
    """Eliminar variante"""
    supplier = get_current_supplier()
    variante = ProductVariant.query.join(Product).filter(
        ProductVariant.id == var_id,
        Product.supplier_id == supplier.id
    ).first_or_404()
    
    try:
        product_id = variante.product_id
        db.session.delete(variante)
        db.session.commit()
        
        flash('Variante eliminada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al eliminar la variante.', 'danger')
    
    return redirect(url_for('supplier_portal.editar_producto', id=product_id))

@supplier_portal_bp.route('/productos/<int:id>/publicar', methods=['POST'])
@supplier_login_required
def publicar_producto(id):
    """Publicar producto"""
    supplier = get_current_supplier()
    producto = Product.query.filter_by(id=id, supplier_id=supplier.id).first_or_404()
    
    if not producto.can_publish:
        flash('El producto debe tener al menos una variante visible con stock y precio, y una imagen.', 'warning')
        return redirect(url_for('supplier_portal.editar_producto', id=id))
    
    try:
        producto.estado = 'publicado'
        producto.updated_at = datetime.utcnow()
        db.session.commit()
        
        flash('Producto publicado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al publicar el producto.', 'danger')
    
    return redirect(url_for('supplier_portal.productos'))

@supplier_portal_bp.route('/productos/<int:id>/pausar', methods=['POST'])
@supplier_login_required
def pausar_producto(id):
    """Pausar producto"""
    supplier = get_current_supplier()
    producto = Product.query.filter_by(id=id, supplier_id=supplier.id).first_or_404()
    
    try:
        producto.estado = 'pausado'
        producto.updated_at = datetime.utcnow()
        db.session.commit()
        
        flash('Producto pausado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al pausar el producto.', 'danger')
    
    return redirect(url_for('supplier_portal.productos'))

@supplier_portal_bp.route('/qna')
@supplier_login_required
def qna_list():
    """Lista de preguntas y respuestas"""
    supplier = get_current_supplier()
    
    # Obtener Q&A de todos los productos del proveedor
    qnas = db.session.query(ProductQNA).join(Product).filter(
        Product.supplier_id == supplier.id
    ).order_by(ProductQNA.created_at.desc()).all()
    
    return render_template('supplier_portal/qna_list.html', qnas=qnas)

@supplier_portal_bp.route('/qna/<int:qna_id>/responder', methods=['POST'])
@supplier_login_required
def responder_qna(qna_id):
    """Responder una pregunta"""
    supplier = get_current_supplier()
    qna = db.session.query(ProductQNA).join(Product).filter(
        ProductQNA.id == qna_id,
        Product.supplier_id == supplier.id
    ).first_or_404()
    
    try:
        respuesta = request.form.get('respuesta', '').strip()
        if not respuesta:
            flash('La respuesta no puede estar vacía.', 'danger')
            return redirect(url_for('supplier_portal.qna_list'))
        
        qna.respuesta = respuesta
        qna.answered_at = datetime.utcnow()
        db.session.commit()
        
        flash('Respuesta enviada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al enviar la respuesta.', 'danger')
    
    return redirect(url_for('supplier_portal.qna_list'))

@supplier_portal_bp.route('/ordenes')
@supplier_login_required
def ordenes():
    """Lista de órdenes del proveedor"""
    supplier = get_current_supplier()
    
    # Filtros
    estado = request.args.get('estado')
    
    query = Order.query.filter_by(supplier_id=supplier.id)
    
    if estado:
        query = query.filter(Order.estado == estado)
    
    ordenes = query.order_by(Order.created_at.desc()).all()
    
    return render_template('supplier_portal/ordenes_list.html',
                         ordenes=ordenes,
                         filtro_estado=estado)

@supplier_portal_bp.route('/ordenes/<int:id>')
@supplier_login_required
def orden_detail(id):
    """Detalle de una orden"""
    supplier = get_current_supplier()
    orden = Order.query.filter_by(id=id, supplier_id=supplier.id).first_or_404()
    
    return render_template('supplier_portal/orden_detail.html', orden=orden)

@supplier_portal_bp.route('/ordenes/<int:id>/marcar-pago', methods=['POST'])
@supplier_login_required
def marcar_pago_orden(id):
    """Marcar orden como pagada (flujo offline)"""
    supplier = get_current_supplier()
    orden = Order.query.filter_by(id=id, supplier_id=supplier.id).first_or_404()
    
    if orden.payment_method != 'offline':
        flash('Esta acción solo está disponible para pagos offline.', 'warning')
        return redirect(url_for('supplier_portal.orden_detail', id=id))
    
    try:
        orden.payment_status = 'approved'
        orden.estado = 'pagado'
        
        # Crear/actualizar comisión
        if not orden.commission:
            commission_data = OrderCommission.compute_commission(orden.total)
            commission = OrderCommission(
                order_id=orden.id,
                base=orden.total,
                **commission_data,
                status='pendiente'
            )
            db.session.add(commission)
        
        db.session.commit()
        flash('Pago marcado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al marcar el pago.', 'danger')
    
    return redirect(url_for('supplier_portal.orden_detail', id=id))

# Funciones auxiliares
def allowed_file(filename):
    """Verifica si el archivo es permitido"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_file(file, folder='products'):
    """Sube un archivo y retorna la URL"""
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Agregar timestamp para evitar duplicados
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        filename = timestamp + filename
        
        # TODO: Implementar subida a S3 o directorio local según configuración
        upload_folder = os.path.join('static', 'uploads', folder)
        os.makedirs(upload_folder, exist_ok=True)
        
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        
        # Retornar URL relativa
        return f'/static/uploads/{folder}/{filename}'
    
    return None