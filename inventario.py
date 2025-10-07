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

from app import db
from models import (
    ItemInventario,
    CategoriaInventario,
    MovimientoInventario,
    UsoInventario,
    Obra,
)
from services.memberships import get_current_org_id

from inventario_new import nuevo_item as nuevo_item_view
from models import InventoryCategory, Organizacion
from seed_inventory_categories import seed_inventory_categories_for_company
from inventory_category_service import (
    ensure_categories_for_company,
    ensure_categories_for_company_id,
    serialize_category,
    render_category_catalog,
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

inventario_bp = Blueprint('inventario', __name__, template_folder='templates')

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

    return nuevo_item_view()

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
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para acceder al catálogo de categorías.', 'danger')
        return redirect(url_for('reportes.dashboard'))

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

    return render_category_catalog(context)


@inventario_bp.route('/api/categorias', methods=['GET'])
@login_required
def api_categorias():
    company_id = _resolve_company_id()
    if not company_id:
        return jsonify({'error': 'Organización no seleccionada'}), 400

    categorias, seed_stats, auto_seeded, _ = ensure_categories_for_company_id(company_id)

    if auto_seeded or seed_stats.get('created') or seed_stats.get('reactivated'):
        current_app.logger.info(
            "Inventory catalogue auto-seeded for org %s (created=%s existing=%s reactivated=%s)",
            company_id,
            seed_stats.get('created', 0),
            seed_stats.get('existing', 0),
            seed_stats.get('reactivated', 0),
        )

    payload = [serialize_category(categoria) for categoria in categorias]

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

    company_id = _resolve_company_id()
    if not company_id:
        flash('No pudimos determinar la organización actual.', 'warning')
        return redirect(url_for('inventario.categorias'))

    company = _resolve_company(company_id)
    if not company:
        flash('No encontramos la organización seleccionada.', 'danger')
        return redirect(url_for('inventario.categorias'))

    stats = seed_inventory_categories_for_company(company)
    db.session.commit()

    created = stats.get('created', 0)
    existing = stats.get('existing', 0)
    reactivated = stats.get('reactivated', 0)
    message = (
        f"Catálogo listo: {created} nuevas, {existing} existentes, {reactivated} reactivadas."
    )

    flash(message, 'success' if created else 'info')
    return redirect(url_for('inventario.categorias'))
