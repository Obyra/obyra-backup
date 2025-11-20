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

    org_id = get_current_org_id() or current_user.organizacion_id

    if not org_id:
        flash('No tienes una organización activa', 'warning')
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            categoria_id = request.form.get('categoria_id')
            codigo = request.form.get('codigo', '').strip().upper()
            nombre = request.form.get('nombre', '').strip()
            descripcion = request.form.get('descripcion', '').strip()
            unidad = request.form.get('unidad', '').strip()
            stock_actual = request.form.get('stock_actual', 0)
            stock_minimo = request.form.get('stock_minimo', 0)
            precio_promedio = request.form.get('precio_promedio', 0)
            precio_promedio_usd = request.form.get('precio_promedio_usd', 0)

            # Validaciones
            if not all([categoria_id, codigo, nombre, unidad]):
                flash('Categoría, código, nombre y unidad son campos obligatorios.', 'danger')
                categorias = InventoryCategory.query.filter_by(company_id=org_id, is_active=True).all()
                return render_template('inventario/crear.html', categorias=categorias)

            # Verificar si el código ya existe
            existing = ItemInventario.query.filter_by(codigo=codigo).first()
            if existing:
                flash(f'Ya existe un item con el código {codigo}', 'warning')
                categorias = InventoryCategory.query.filter_by(company_id=org_id, is_active=True).all()
                return render_template('inventario/crear.html', categorias=categorias)

            # Convertir valores numéricos
            stock_actual = float(stock_actual)
            stock_minimo = float(stock_minimo)
            precio_promedio = float(precio_promedio)
            precio_promedio_usd = float(precio_promedio_usd)

            # Crear el item
            nuevo_item = ItemInventario(
                organizacion_id=org_id,
                categoria_id=categoria_id,
                codigo=codigo,
                nombre=nombre,
                descripcion=descripcion or None,
                unidad=unidad,
                stock_actual=stock_actual,
                stock_minimo=stock_minimo,
                precio_promedio=precio_promedio,
                precio_promedio_usd=precio_promedio_usd,
                activo=True
            )

            db.session.add(nuevo_item)
            db.session.flush()  # Para obtener el ID

            # Si hay stock inicial, crear movimiento de entrada
            if stock_actual > 0:
                movimiento = MovimientoInventario(
                    item_id=nuevo_item.id,
                    tipo='entrada',
                    cantidad=stock_actual,
                    precio_unitario=precio_promedio,
                    motivo='Inventario inicial',
                    observaciones='Stock inicial al crear el item',
                    usuario_id=current_user.id
                )
                db.session.add(movimiento)

            db.session.commit()

            flash(f'Item {nuevo_item.nombre} creado exitosamente', 'success')
            return redirect(url_for('inventario.lista'))

        except ValueError as e:
            db.session.rollback()
            flash('Error: Los valores numéricos no son válidos', 'danger')
            categorias = InventoryCategory.query.filter_by(company_id=org_id, is_active=True).all()
            return render_template('inventario/crear.html', categorias=categorias)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error al crear item de inventario: {str(e)}")
            flash('Error al crear el item de inventario', 'danger')
            categorias = InventoryCategory.query.filter_by(company_id=org_id, is_active=True).all()
            return render_template('inventario/crear.html', categorias=categorias)

    # GET request
    categorias = InventoryCategory.query.filter_by(company_id=org_id, is_active=True).order_by(InventoryCategory.nombre).all()
    can_manage_categories = user_can_manage_inventory_categories(current_user)

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

@inventario_bp.route('/items-disponibles', methods=['GET'])
@login_required
def items_disponibles():
    """
    Endpoint para obtener items del inventario disponibles para una obra.
    Retorna lista de materiales con stock actual para selector de consumo.
    """
    try:
        obra_id = request.args.get('obra_id', type=int)
        org_id = get_current_org_id() or current_user.organizacion_id

        if not org_id:
            return jsonify({'ok': False, 'error': 'No tienes una organización activa'}), 400

        # Obtener todos los items del inventario de la organización con stock > 0
        items = ItemInventario.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).filter(
            ItemInventario.stock_actual > 0
        ).order_by(ItemInventario.descripcion).all()

        items_data = []
        for item in items:
            items_data.append({
                'id': item.id,
                'descripcion': item.descripcion,
                'stock_actual': float(item.stock_actual or 0),
                'unidad': item.unidad or 'un',
                'categoria': item.categoria.nombre if item.categoria else 'Sin categoría'
            })

        return jsonify({
            'ok': True,
            'items': items_data
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo items disponibles: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500


@inventario_bp.route('/analisis', methods=['GET'])
@login_required
def analisis():
    """
    Análisis de consumo de inventario:
    - Artículos más consumidos
    - Consumo por obra
    - Costos reales de materiales
    - Tendencias de consumo
    """
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    try:
        from datetime import datetime, timedelta
        from sqlalchemy import func, desc

        org_id = get_current_org_id() or current_user.organizacion_id

        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        # Filtros de fecha (por defecto últimos 30 días)
        fecha_desde = request.args.get('fecha_desde')
        fecha_hasta = request.args.get('fecha_hasta')
        obra_id = request.args.get('obra_id', type=int)

        if not fecha_desde:
            fecha_desde = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not fecha_hasta:
            fecha_hasta = datetime.now().strftime('%Y-%m-%d')

        fecha_desde_dt = datetime.strptime(fecha_desde, '%Y-%m-%d')
        fecha_hasta_dt = datetime.strptime(fecha_hasta, '%Y-%m-%d')

        # 1. ARTÍCULOS MÁS CONSUMIDOS (Top 10)
        query_top_items = db.session.query(
            ItemInventario.id,
            ItemInventario.descripcion,
            ItemInventario.unidad,
            func.sum(UsoInventario.cantidad).label('total_consumido'),
            func.count(UsoInventario.id).label('num_usos'),
            func.avg(ItemInventario.precio_promedio).label('precio_promedio')
        ).join(
            UsoInventario, ItemInventario.id == UsoInventario.item_id
        ).filter(
            ItemInventario.organizacion_id == org_id,
            UsoInventario.fecha >= fecha_desde_dt,
            UsoInventario.fecha <= fecha_hasta_dt
        )

        if obra_id:
            query_top_items = query_top_items.filter(UsoInventario.obra_id == obra_id)

        top_items = query_top_items.group_by(
            ItemInventario.id,
            ItemInventario.descripcion,
            ItemInventario.unidad
        ).order_by(desc('total_consumido')).limit(10).all()

        # Calcular costo total de cada item
        top_items_data = []
        for item in top_items:
            costo_total = float(item.total_consumido) * (float(item.precio_promedio) if item.precio_promedio else 0)
            top_items_data.append({
                'id': item.id,
                'descripcion': item.descripcion,
                'unidad': item.unidad,
                'total_consumido': float(item.total_consumido),
                'num_usos': item.num_usos,
                'precio_promedio': float(item.precio_promedio) if item.precio_promedio else 0,
                'costo_total': costo_total
            })

        # 2. CONSUMO POR OBRA
        query_obras = db.session.query(
            Obra.id,
            Obra.nombre,
            Obra.direccion,
            func.count(UsoInventario.id).label('num_consumos'),
            func.sum(UsoInventario.cantidad * ItemInventario.precio_promedio).label('costo_total')
        ).join(
            UsoInventario, Obra.id == UsoInventario.obra_id
        ).join(
            ItemInventario, UsoInventario.item_id == ItemInventario.id
        ).filter(
            Obra.organizacion_id == org_id,
            UsoInventario.fecha >= fecha_desde_dt,
            UsoInventario.fecha <= fecha_hasta_dt
        )

        if obra_id:
            query_obras = query_obras.filter(Obra.id == obra_id)

        consumo_obras = query_obras.group_by(
            Obra.id,
            Obra.nombre,
            Obra.direccion
        ).order_by(desc('costo_total')).all()

        consumo_obras_data = []
        for obra in consumo_obras:
            consumo_obras_data.append({
                'id': obra.id,
                'nombre': obra.nombre,
                'direccion': obra.direccion,
                'num_consumos': obra.num_consumos,
                'costo_total': float(obra.costo_total) if obra.costo_total else 0
            })

        # 3. ITEMS CON STOCK BAJO (alertas)
        items_stock_bajo = ItemInventario.query.filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.activo == True,
            ItemInventario.stock_actual <= ItemInventario.stock_minimo
        ).order_by(ItemInventario.stock_actual).all()

        # 4. RESUMEN GENERAL
        total_items_activos = ItemInventario.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).count()

        valor_total_inventario = db.session.query(
            func.sum(ItemInventario.stock_actual * ItemInventario.precio_promedio)
        ).filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.activo == True
        ).scalar() or 0

        total_consumos_periodo = UsoInventario.query.filter(
            UsoInventario.fecha >= fecha_desde_dt,
            UsoInventario.fecha <= fecha_hasta_dt
        ).join(ItemInventario).filter(
            ItemInventario.organizacion_id == org_id
        ).count()

        costo_total_periodo = db.session.query(
            func.sum(UsoInventario.cantidad * ItemInventario.precio_promedio)
        ).join(
            ItemInventario, UsoInventario.item_id == ItemInventario.id
        ).filter(
            ItemInventario.organizacion_id == org_id,
            UsoInventario.fecha >= fecha_desde_dt,
            UsoInventario.fecha <= fecha_hasta_dt
        ).scalar() or 0

        # Obtener todas las obras para el filtro
        todas_obras = Obra.query.filter_by(organizacion_id=org_id).order_by(Obra.nombre).all()

        return render_template('inventario/analisis.html',
                             top_items=top_items_data,
                             consumo_obras=consumo_obras_data,
                             items_stock_bajo=items_stock_bajo,
                             total_items_activos=total_items_activos,
                             valor_total_inventario=float(valor_total_inventario),
                             total_consumos_periodo=total_consumos_periodo,
                             costo_total_periodo=float(costo_total_periodo),
                             fecha_desde=fecha_desde,
                             fecha_hasta=fecha_hasta,
                             obra_id=obra_id,
                             todas_obras=todas_obras)

    except Exception as e:
        current_app.logger.error(f"Error en análisis de inventario: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        flash('Error al generar el análisis de inventario', 'danger')
        return redirect(url_for('inventario.lista'))
