from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import date
from app import db
from models import (ItemInventario, CategoriaInventario, MovimientoInventario, 
                   UsoInventario, Obra)

inventario_bp = Blueprint('inventario', __name__)

@inventario_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    categoria_id = request.args.get('categoria', '')
    buscar = request.args.get('buscar', '')
    tipo = request.args.get('tipo', '')
    stock_bajo = request.args.get('stock_bajo', '')
    
    query = ItemInventario.query.join(CategoriaInventario)
    
    if categoria_id:
        query = query.filter(ItemInventario.categoria_id == categoria_id)
    
    if tipo:
        query = query.filter(CategoriaInventario.tipo == tipo)
    
    if buscar:
        query = query.filter(
            db.or_(
                ItemInventario.codigo.contains(buscar),
                ItemInventario.nombre.contains(buscar),
                ItemInventario.descripcion.contains(buscar)
            )
        )
    
    if stock_bajo:
        query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)
    
    items = query.filter(ItemInventario.activo == True).order_by(ItemInventario.nombre).all()
    categorias = CategoriaInventario.query.order_by(CategoriaInventario.nombre).all()
    
    return render_template('inventario/lista.html', 
                         items=items, 
                         categorias=categorias,
                         categoria_id=categoria_id,
                         buscar=buscar,
                         tipo=tipo,
                         stock_bajo=stock_bajo)

@inventario_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para crear items de inventario.', 'danger')
        return redirect(url_for('inventario.lista'))
    
    categorias = CategoriaInventario.query.order_by(CategoriaInventario.nombre).all()
    
    if request.method == 'POST':
        categoria_id = request.form.get('categoria_id')
        codigo = request.form.get('codigo')
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        unidad = request.form.get('unidad')
        stock_actual = request.form.get('stock_actual', 0)
        stock_minimo = request.form.get('stock_minimo', 0)
        precio_promedio = request.form.get('precio_promedio', 0)
        
        # Validaciones
        if not all([categoria_id, codigo, nombre, unidad]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            return render_template('inventario/crear.html', categorias=categorias)
        
        # Verificar que el código no exista
        if ItemInventario.query.filter_by(codigo=codigo).first():
            flash('Ya existe un item con ese código.', 'danger')
            return render_template('inventario/crear.html', categorias=categorias)
        
        try:
            nuevo_item = ItemInventario(
                categoria_id=categoria_id,
                codigo=codigo,
                nombre=nombre,
                descripcion=descripcion,
                unidad=unidad,
                stock_actual=float(stock_actual),
                stock_minimo=float(stock_minimo),
                precio_promedio=float(precio_promedio)
            )
            
            db.session.add(nuevo_item)
            db.session.commit()
            
            # Registrar movimiento inicial si hay stock
            if float(stock_actual) > 0:
                movimiento = MovimientoInventario(
                    item_id=nuevo_item.id,
                    tipo='entrada',
                    cantidad=float(stock_actual),
                    precio_unitario=float(precio_promedio),
                    motivo='Stock inicial',
                    usuario_id=current_user.id
                )
                db.session.add(movimiento)
                db.session.commit()
            
            flash(f'Item "{nombre}" creado exitosamente.', 'success')
            return redirect(url_for('inventario.detalle', id=nuevo_item.id))
            
        except Exception as e:
            db.session.rollback()
            flash('Error al crear el item. Intenta nuevamente.', 'danger')
    
    return render_template('inventario/crear.html', categorias=categorias)

@inventario_bp.route('/<int:id>')
@login_required
def detalle(id):
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para ver detalles de inventario.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    item = ItemInventario.query.get_or_404(id)
    
    # Obtener últimos movimientos
    movimientos = item.movimientos.order_by(MovimientoInventario.fecha.desc()).limit(10).all()
    
    # Obtener uso en obras
    usos_obra = item.usos.join(Obra).order_by(UsoInventario.fecha_uso.desc()).limit(10).all()
    
    return render_template('inventario/detalle.html', 
                         item=item, 
                         movimientos=movimientos,
                         usos_obra=usos_obra)

@inventario_bp.route('/<int:id>/movimiento', methods=['POST'])
@login_required
def registrar_movimiento(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para registrar movimientos.', 'danger')
        return redirect(url_for('inventario.detalle', id=id))
    
    item = ItemInventario.query.get_or_404(id)
    
    tipo = request.form.get('tipo')
    cantidad = request.form.get('cantidad')
    precio_unitario = request.form.get('precio_unitario', 0)
    motivo = request.form.get('motivo')
    observaciones = request.form.get('observaciones')
    
    if not all([tipo, cantidad]):
        flash('Tipo y cantidad son obligatorios.', 'danger')
        return redirect(url_for('inventario.detalle', id=id))
    
    try:
        cantidad = float(cantidad)
        precio_unitario = float(precio_unitario)
        
        if cantidad <= 0:
            flash('La cantidad debe ser mayor a cero.', 'danger')
            return redirect(url_for('inventario.detalle', id=id))
        
        # Verificar stock para salidas
        if tipo == 'salida' and cantidad > item.stock_actual:
            flash('Stock insuficiente para la salida solicitada.', 'danger')
            return redirect(url_for('inventario.detalle', id=id))
        
        # Crear movimiento
        movimiento = MovimientoInventario(
            item_id=id,
            tipo=tipo,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            motivo=motivo,
            observaciones=observaciones,
            usuario_id=current_user.id
        )
        
        # Actualizar stock
        if tipo == 'entrada':
            item.stock_actual += cantidad
            # Actualizar precio promedio
            if precio_unitario > 0:
                total_valor = (item.stock_actual - cantidad) * item.precio_promedio + cantidad * precio_unitario
                item.precio_promedio = total_valor / item.stock_actual
        elif tipo == 'salida':
            item.stock_actual -= cantidad
        elif tipo == 'ajuste':
            item.stock_actual = cantidad
        
        db.session.add(movimiento)
        db.session.commit()
        
        flash('Movimiento registrado exitosamente.', 'success')
        
    except ValueError:
        flash('Cantidad y precio deben ser números válidos.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash('Error al registrar el movimiento.', 'danger')
    
    return redirect(url_for('inventario.detalle', id=id))

@inventario_bp.route('/uso-obra', methods=['GET', 'POST'])
@login_required
def uso_obra():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para registrar uso en obra.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    obras = Obra.query.filter(Obra.estado.in_(['planificacion', 'en_curso'])).order_by(Obra.nombre).all()
    items = ItemInventario.query.filter_by(activo=True).order_by(ItemInventario.nombre).all()
    
    if request.method == 'POST':
        obra_id = request.form.get('obra_id')
        item_id = request.form.get('item_id')
        cantidad_usada = request.form.get('cantidad_usada')
        fecha_uso = request.form.get('fecha_uso')
        observaciones = request.form.get('observaciones')
        
        if not all([obra_id, item_id, cantidad_usada]):
            flash('Obra, item y cantidad son obligatorios.', 'danger')
            return render_template('inventario/uso_obra.html', obras=obras, items=items)
        
        try:
            cantidad_usada = float(cantidad_usada)
            item = ItemInventario.query.get(item_id)
            
            if cantidad_usada <= 0:
                flash('La cantidad debe ser mayor a cero.', 'danger')
                return render_template('inventario/uso_obra.html', obras=obras, items=items)
            
            if cantidad_usada > item.stock_actual:
                flash('Stock insuficiente.', 'danger')
                return render_template('inventario/uso_obra.html', obras=obras, items=items)
            
            # Convertir fecha
            fecha_uso_obj = date.today()
            if fecha_uso:
                from datetime import datetime
                fecha_uso_obj = datetime.strptime(fecha_uso, '%Y-%m-%d').date()
            
            # Crear uso
            uso = UsoInventario(
                obra_id=obra_id,
                item_id=item_id,
                cantidad_usada=cantidad_usada,
                fecha_uso=fecha_uso_obj,
                observaciones=observaciones,
                usuario_id=current_user.id
            )
            
            # Crear movimiento de salida
            movimiento = MovimientoInventario(
                item_id=item_id,
                tipo='salida',
                cantidad=cantidad_usada,
                motivo=f'Uso en obra: {Obra.query.get(obra_id).nombre}',
                observaciones=observaciones,
                usuario_id=current_user.id
            )
            
            # Actualizar stock
            item.stock_actual -= cantidad_usada
            
            db.session.add(uso)
            db.session.add(movimiento)
            db.session.commit()
            
            flash('Uso en obra registrado exitosamente.', 'success')
            return redirect(url_for('inventario.lista'))
            
        except ValueError:
            flash('La cantidad debe ser un número válido.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash('Error al registrar el uso en obra.', 'danger')
    
    return render_template('inventario/uso_obra.html', obras=obras, items=items)

@inventario_bp.route('/categorias')
@login_required
def categorias():
    if current_user.rol != 'administrador':
        flash('No tienes permisos para gestionar categorías.', 'danger')
        return redirect(url_for('inventario.lista'))
    
    categorias = CategoriaInventario.query.order_by(CategoriaInventario.nombre).all()
    return render_template('inventario/categorias.html', categorias=categorias)

@inventario_bp.route('/categoria', methods=['POST'])
@login_required
def crear_categoria():
    if current_user.rol != 'administrador':
        flash('No tienes permisos para crear categorías.', 'danger')
        return redirect(url_for('inventario.categorias'))
    
    nombre = request.form.get('nombre')
    descripcion = request.form.get('descripcion')
    tipo = request.form.get('tipo')
    
    if not all([nombre, tipo]):
        flash('Nombre y tipo son obligatorios.', 'danger')
        return redirect(url_for('inventario.categorias'))
    
    if CategoriaInventario.query.filter_by(nombre=nombre).first():
        flash('Ya existe una categoría con ese nombre.', 'danger')
        return redirect(url_for('inventario.categorias'))
    
    nueva_categoria = CategoriaInventario(
        nombre=nombre,
        descripcion=descripcion,
        tipo=tipo
    )
    
    try:
        db.session.add(nueva_categoria)
        db.session.commit()
        flash(f'Categoría "{nombre}" creada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al crear la categoría.', 'danger')
    
    return redirect(url_for('inventario.categorias'))
