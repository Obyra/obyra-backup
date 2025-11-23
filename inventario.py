import os

from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    redirect,
    url_for,
    current_app,
    jsonify,
)
from flask_login import login_required, current_user
from datetime import date
from collections import defaultdict
from typing import Dict, List, Optional
from jinja2 import TemplateNotFound

from app import db
from models import (
    ItemInventario,
    CategoriaInventario,
    MovimientoInventario,
    UsoInventario,
    Obra,
)
from services.memberships import get_current_org_id

# from inventario_new import nuevo_item as nuevo_item_view  # Commented out - causes import error
from models import InventoryCategory, Organizacion
from seed_inventory_categories import seed_inventory_categories_for_company
from inventory_category_service import (
    ensure_categories_for_company,
    ensure_categories_for_company_id,
    serialize_category,
    render_category_catalog,
    user_can_manage_inventory_categories,
)


def _resolve_company_id() -> Optional[int]:
    org_id = get_current_org_id()
    if org_id:
        return org_id
    return getattr(current_user, 'organizacion_id', None)


def _resolve_company(company_id: int) -> Optional[Organizacion]:
    if getattr(current_user, 'organizacion', None) and current_user.organizacion.id == company_id:
        return current_user.organizacion
    return Organizacion.query.get(company_id)


def _build_category_tree(categorias: List[InventoryCategory]) -> List[Dict[str, object]]:
    children_map: Dict[Optional[int], List[InventoryCategory]] = defaultdict(list)
    for categoria in categorias:
        children_map[categoria.parent_id].append(categoria)

    for bucket in children_map.values():
        bucket.sort(key=lambda cat: ((cat.sort_order or 0), cat.nombre.lower()))

    def build(parent_id: Optional[int] = None) -> List[Dict[str, object]]:
        nodes: List[Dict[str, object]] = []
        for categoria in children_map.get(parent_id, []):
            nodes.append({
                'categoria': categoria,
                'children': build(categoria.id),
            })
        return nodes

    return build()

INVENTARIO_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')

inventario_bp = Blueprint('inventario', __name__, template_folder=INVENTARIO_TEMPLATE_DIR)

@inventario_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    categoria_id = request.args.get('categoria', '')
    buscar = request.args.get('buscar', '')
    stock_bajo = request.args.get('stock_bajo', '')

    query = ItemInventario.query.join(CategoriaInventario)

    if categoria_id:
        query = query.filter(ItemInventario.categoria_id == categoria_id)

    if buscar:
        # Búsqueda flexible: permite búsqueda parcial case-insensitive en código, nombre y descripción
        buscar_pattern = f'%{buscar}%'
        query = query.filter(
            db.or_(
                ItemInventario.codigo.ilike(buscar_pattern),
                ItemInventario.nombre.ilike(buscar_pattern),
                ItemInventario.descripcion.ilike(buscar_pattern)
            )
        )
    
    if stock_bajo:
        query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)
    
    items = query.filter(ItemInventario.activo == True).order_by(ItemInventario.nombre).all()

    # Obtener categorías del nuevo sistema InventoryCategory
    company_id = _resolve_company_id()
    if company_id:
        from models import InventoryCategory
        categorias_nuevas = InventoryCategory.query.filter_by(
            company_id=company_id,
            is_active=True,
            parent_id=None  # Solo categorías raíz
        ).order_by(InventoryCategory.sort_order, InventoryCategory.nombre).all()
    else:
        categorias_nuevas = []

    # Mantener compatibilidad con categorías antiguas
    categorias = CategoriaInventario.query.order_by(CategoriaInventario.nombre).all()

    # Obtener obras confirmadas para cada item
    from models.projects import Obra
    from models.budgets import Presupuesto

    items_con_obras = []
    for item in items:
        # Buscar usos del item en obras con presupuestos confirmados
        obras_confirmadas = db.session.query(Obra).join(
            UsoInventario, Obra.id == UsoInventario.obra_id
        ).join(
            Presupuesto, Obra.id == Presupuesto.obra_id
        ).filter(
            UsoInventario.item_id == item.id,
            db.or_(
                Presupuesto.confirmado_como_obra == True,
                Presupuesto.estado.in_(['aprobado', 'convertido', 'confirmado'])
            )
        ).distinct().all()

        items_con_obras.append({
            'item': item,
            'obras': obras_confirmadas
        })

    # Obtener obras disponibles para traslados
    obras_disponibles = Obra.query.filter(
        Obra.estado.in_(['planificacion', 'en_curso', 'finalizado'])
    ).order_by(Obra.nombre).all()

    return render_template('inventario/lista.html',
                         items_con_obras=items_con_obras,
                         categorias=categorias,
                         categorias_nuevas=categorias_nuevas,
                         categoria_id=categoria_id,
                         buscar=buscar,
                         stock_bajo=stock_bajo,
                         obras_disponibles=obras_disponibles)

@inventario_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para crear items de inventario.', 'danger')
        return redirect(url_for('inventario.lista'))

    # Get categories for the form
    company_id = _resolve_company_id()
    if company_id:
        from models import InventoryCategory
        categorias = InventoryCategory.query.filter_by(
            organizacion_id=company_id,
            activo=True
        ).order_by(InventoryCategory.nombre).all()
    else:
        categorias = []

    can_manage_categories = user_can_manage_inventory_categories(current_user)

    if request.method == 'POST':
        # Get form data
        categoria_id = request.form.get('categoria_id')
        codigo = request.form.get('codigo', '').strip().upper()
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        unidad = request.form.get('unidad')
        stock_actual = request.form.get('stock_actual', 0)
        stock_minimo = request.form.get('stock_minimo', 0)
        precio_promedio = request.form.get('precio_promedio', 0)

        # Validate required fields
        if not all([categoria_id, codigo, nombre, unidad]):
            flash('Categoría, código, nombre y unidad son obligatorios.', 'danger')
            return render_template('inventario/crear.html',
                                 categorias=categorias,
                                 can_manage_categories=can_manage_categories)

        try:
            # Convert numeric fields
            stock_actual = float(stock_actual)
            stock_minimo = float(stock_minimo)
            precio_promedio = float(precio_promedio)

            # Validate numeric values
            if stock_actual < 0 or stock_minimo < 0 or precio_promedio < 0:
                flash('Los valores numéricos no pueden ser negativos.', 'danger')
                return render_template('inventario/crear.html',
                                     categorias=categorias,
                                     can_manage_categories=can_manage_categories)

            # Check if codigo already exists
            existing_item = ItemInventario.query.filter_by(codigo=codigo).first()
            if existing_item:
                flash(f'Ya existe un item con el código {codigo}.', 'danger')
                return render_template('inventario/crear.html',
                                     categorias=categorias,
                                     can_manage_categories=can_manage_categories)

            # Create new item
            nuevo_item = ItemInventario(
                categoria_id=categoria_id,
                codigo=codigo,
                nombre=nombre,
                descripcion=descripcion if descripcion else None,
                unidad=unidad,
                stock_actual=stock_actual,
                stock_minimo=stock_minimo,
                precio_promedio=precio_promedio,
                activo=True
            )

            db.session.add(nuevo_item)
            db.session.flush()  # Get the item ID

            # Create initial stock movement if stock_actual > 0
            if stock_actual > 0:
                movimiento_inicial = MovimientoInventario(
                    item_id=nuevo_item.id,
                    tipo='entrada',
                    cantidad=stock_actual,
                    precio_unitario=precio_promedio,
                    motivo='Inventario inicial',
                    observaciones='Stock inicial al crear el item',
                    usuario_id=current_user.id
                )
                db.session.add(movimiento_inicial)

            db.session.commit()

            flash(f'Item "{nombre}" creado exitosamente.', 'success')
            return redirect(url_for('inventario.lista'))

        except ValueError:
            flash('Los valores de stock y precio deben ser números válidos.', 'danger')
            return render_template('inventario/crear.html',
                                 categorias=categorias,
                                 can_manage_categories=can_manage_categories)
        except Exception as e:
            db.session.rollback()
            flash('Error al crear el item de inventario.', 'danger')
            current_app.logger.error(f'Error creating inventory item: {str(e)}')
            return render_template('inventario/crear.html',
                                 categorias=categorias,
                                 can_manage_categories=can_manage_categories)

    return render_template('inventario/crear.html',
                         categorias=categorias,
                         can_manage_categories=can_manage_categories)

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
    context = {'obras': obras, 'items': items, 'today': date.today()}

    if request.method == 'POST':
        obra_id = request.form.get('obra_id')
        item_id = request.form.get('item_id')
        cantidad_usada = request.form.get('cantidad_usada')
        fecha_uso = request.form.get('fecha_uso')
        observaciones = request.form.get('observaciones')

        if not all([obra_id, item_id, cantidad_usada]):
            flash('Obra, item y cantidad son obligatorios.', 'danger')
            return render_template('inventario/uso_obra.html', **context)

        try:
            cantidad_usada = float(cantidad_usada)
            item = ItemInventario.query.get(item_id)

            if item is None:
                flash('El ítem seleccionado no existe.', 'danger')
                return render_template('inventario/uso_obra.html', **context)

            if cantidad_usada <= 0:
                flash('La cantidad debe ser mayor a cero.', 'danger')
                return render_template('inventario/uso_obra.html', **context)

            stock_actual = item.stock_actual if item.stock_actual is not None else 0
            if cantidad_usada > stock_actual:
                flash('Stock insuficiente.', 'danger')
                return render_template('inventario/uso_obra.html', **context)

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
            item.stock_actual = stock_actual - cantidad_usada

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

    return render_template('inventario/uso_obra.html', **context)

@inventario_bp.route('/categorias')
@login_required
def categorias():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para acceder al catálogo de categorías.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    if not user_can_manage_inventory_categories(current_user):
        flash('No tienes permisos para gestionar el catálogo global de categorías.', 'danger')
        return redirect(url_for('inventario.lista'))

    company_id = _resolve_company_id()
    if not company_id:
        flash('No pudimos determinar la organización actual.', 'warning')
        return redirect(url_for('reportes.dashboard'))

    company = _resolve_company(company_id)
    if not company:
        flash('No pudimos cargar la organización seleccionada.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    categorias, seed_stats, auto_seeded = ensure_categories_for_company(company)

    category_tree = _build_category_tree(categorias)

    context = {
        'categorias': categorias,
        'category_tree': category_tree,
        'auto_seeded': auto_seeded,
        'seed_stats': seed_stats,
        'company': company,
    }

    try:
        return render_template('inventario/categorias.html', **context)
    except TemplateNotFound:
        return render_category_catalog(context)


@inventario_bp.route('/api/categorias', methods=['GET'])
@inventario_bp.route('/api/categorias/', methods=['GET'])
@login_required
def api_categorias():
    company_id = _resolve_company_id()
    if not company_id:
        return jsonify({'error': 'Organización no seleccionada'}), 400

    categorias, seed_stats, auto_seeded, _ = ensure_categories_for_company_id(company_id)

    if auto_seeded or seed_stats.get('created') or seed_stats.get('reactivated'):
        current_app.logger.info(
            "[inventario] categorías auto-sembradas para org=%s (creadas=%s existentes=%s reactivadas=%s)",
            company_id,
            seed_stats.get('created', 0),
            seed_stats.get('existing', 0),
            seed_stats.get('reactivated', 0),
        )

    payload = [serialize_category(categoria) for categoria in categorias]
    payload.sort(key=lambda categoria: (categoria.get('full_path') or '').casefold())

    if not payload:
        current_app.logger.warning(
            "Inventory catalogue empty for org %s despite seeding attempts", company_id
        )

    return jsonify(payload)

@inventario_bp.route('/categoria', methods=['POST'])
@login_required
def crear_categoria():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para actualizar el catálogo.', 'danger')
        return redirect(url_for('inventario.categorias'))

    if not user_can_manage_inventory_categories(current_user):
        flash('No tienes permisos para modificar el catálogo global.', 'danger')
        return redirect(url_for('inventario.lista'))

    company_id = _resolve_company_id()
    if not company_id:
        flash('No pudimos determinar la organización actual.', 'warning')
        return redirect(url_for('inventario.categorias'))

    company = _resolve_company(company_id)
    if not company:
        flash('No encontramos la organización seleccionada.', 'danger')
        return redirect(url_for('inventario.categorias'))

    stats = seed_inventory_categories_for_company(company, mark_global=True)
    db.session.commit()

    created = stats.get('created', 0)
    existing = stats.get('existing', 0)
    reactivated = stats.get('reactivated', 0)
    message = (
        f"Catálogo listo: {created} nuevas, {existing} existentes, {reactivated} reactivadas."
    )

    flash(message, 'success' if created else 'info')
    return redirect(url_for('inventario.categorias'))

@inventario_bp.route('/dar-baja', methods=['POST'])
@login_required
def dar_baja():
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para dar de baja items.', 'danger')
        return redirect(url_for('inventario.lista'))

    item_id = request.form.get('item_id')
    cantidad = request.form.get('cantidad')
    tipo_baja = request.form.get('tipo_baja')
    observaciones = request.form.get('observaciones')

    if not all([item_id, cantidad, tipo_baja]):
        flash('Todos los campos son obligatorios.', 'danger')
        return redirect(url_for('inventario.lista'))

    try:
        cantidad = float(cantidad)
        item = ItemInventario.query.get_or_404(item_id)

        if cantidad <= 0:
            flash('La cantidad debe ser mayor a cero.', 'danger')
            return redirect(url_for('inventario.lista'))

        stock_actual = item.stock_actual if item.stock_actual is not None else 0
        if cantidad > stock_actual:
            flash('Stock insuficiente para dar de baja.', 'danger')
            return redirect(url_for('inventario.lista'))

        # Determinar el motivo según el tipo de baja
        if tipo_baja == 'uso':
            motivo = f'Baja por uso/consumo'
        elif tipo_baja == 'rotura':
            motivo = f'Baja por rotura/daño'
        else:
            motivo = f'Baja de inventario'

        # Crear movimiento de salida
        movimiento = MovimientoInventario(
            item_id=item_id,
            tipo='salida',
            cantidad=cantidad,
            motivo=motivo,
            observaciones=observaciones,
            usuario_id=current_user.id
        )

        # Actualizar stock
        item.stock_actual = stock_actual - cantidad

        db.session.add(movimiento)
        db.session.commit()

        flash(f'Item dado de baja exitosamente. Stock actualizado: {item.stock_actual:.3f} {item.unidad}', 'success')

    except ValueError:
        flash('La cantidad debe ser un número válido.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash('Error al dar de baja el item.', 'danger')
        current_app.logger.error(f'Error en dar_baja: {str(e)}')

    return redirect(url_for('inventario.lista'))

@inventario_bp.route('/trasladar', methods=['POST'])
@login_required
def trasladar():
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para trasladar items.', 'danger')
        return redirect(url_for('inventario.lista'))

    item_id = request.form.get('item_id')
    obra_destino_id = request.form.get('obra_destino_id')
    cantidad = request.form.get('cantidad')
    observaciones = request.form.get('observaciones')

    if not all([item_id, obra_destino_id, cantidad]):
        flash('Todos los campos son obligatorios.', 'danger')
        return redirect(url_for('inventario.lista'))

    try:
        cantidad = float(cantidad)
        item = ItemInventario.query.get_or_404(item_id)
        obra_destino = Obra.query.get_or_404(obra_destino_id)

        if cantidad <= 0:
            flash('La cantidad debe ser mayor a cero.', 'danger')
            return redirect(url_for('inventario.lista'))

        stock_actual = item.stock_actual if item.stock_actual is not None else 0
        if cantidad > stock_actual:
            flash('Stock insuficiente para trasladar.', 'danger')
            return redirect(url_for('inventario.lista'))

        # Crear movimiento de salida del depósito actual
        movimiento_salida = MovimientoInventario(
            item_id=item_id,
            tipo='salida',
            cantidad=cantidad,
            motivo=f'Traslado a: {obra_destino.nombre}',
            observaciones=observaciones,
            usuario_id=current_user.id
        )

        # Crear registro de uso en la obra destino
        uso_obra = UsoInventario(
            obra_id=obra_destino_id,
            item_id=item_id,
            cantidad_usada=cantidad,
            fecha_uso=date.today(),
            observaciones=f'Traslado desde depósito. {observaciones or ""}',
            usuario_id=current_user.id
        )

        # Actualizar stock del item
        item.stock_actual = stock_actual - cantidad

        db.session.add(movimiento_salida)
        db.session.add(uso_obra)
        db.session.commit()

        flash(f'Item trasladado exitosamente a {obra_destino.nombre}. Stock actualizado: {item.stock_actual:.3f} {item.unidad}', 'success')

    except ValueError:
        flash('La cantidad debe ser un número válido.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash('Error al trasladar el item.', 'danger')
        current_app.logger.error(f'Error en trasladar: {str(e)}')

    return redirect(url_for('inventario.lista'))
