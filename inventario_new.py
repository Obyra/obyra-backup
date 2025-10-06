from collections import defaultdict
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app import db
from models import (
    InventoryCategory,
    InventoryItem,
    ItemInventario,
    Organizacion,
    Obra,
    Stock,
    StockMovement,
    StockReservation,
    Warehouse,
)
from sqlalchemy import func
from sqlalchemy.orm import aliased

from services.memberships import get_current_org_id
from seed_inventory_categories import seed_inventory_categories_for_company
from inventory_category_service import (
    ensure_categories_for_company,
    ensure_categories_for_company_id,
    get_active_categories,
    get_active_category_options,
)

WASTE_KEYWORDS = (
    'desperd',
    'merma',
    'pérd',
    'perdida',
    'perdido',
    'rotur',
    'dañ',
    'avería',
    'averia',
)

inventario_new_bp = Blueprint(
    'inventario_new',
    __name__,
    url_prefix='/inventario',
    template_folder='templates',
)

def requires_role(*roles):
    """Decorator para verificar roles"""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.rol not in roles and not current_user.es_admin():
                flash('No tienes permisos para esta acción.', 'danger')
                return redirect(url_for('inventario_new.items'))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator

def get_json_response(data, status=200, error=None):
    """Genera respuesta JSON estándar"""
    if request.accept_mimetypes['application/json'] >= request.accept_mimetypes['text/html'] or request.args.get('format') == 'json':
        if error:
            return jsonify({'error': error}), status
        return jsonify(data), status
    return None


def _build_category_tree(
    categorias: List[InventoryCategory],
) -> List[Dict[str, object]]:
    """Arma un árbol jerárquico para renderizado."""

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


def _resolve_company(company_id: int) -> Optional[Organizacion]:
    """Obtiene la organización asociada al id."""

    if getattr(current_user, 'organizacion', None) and current_user.organizacion.id == company_id:
        return current_user.organizacion

    return Organizacion.query.get(company_id)


def _resolve_company_id() -> int | None:
    """Obtiene la organización actual respetando multi-tenant."""
    org_id = get_current_org_id()
    if org_id:
        return org_id
    return getattr(current_user, 'organizacion_id', None)


def _build_stock_summary(
    company_id: int,
    *,
    warehouse_id: int | None = None,
    categoria_id: int | None = None,
    buscar: str | None = None,
):
    """Devuelve un resumen de stock por item y depósito."""
    item_alias = aliased(InventoryItem)
    warehouse_alias = aliased(Warehouse)

    query = (
        db.session.query(
            item_alias.id.label('item_id'),
            item_alias.sku.label('sku'),
            item_alias.nombre.label('item_nombre'),
            item_alias.unidad.label('unidad'),
            InventoryCategory.nombre.label('categoria'),
            warehouse_alias.id.label('warehouse_id'),
            warehouse_alias.nombre.label('warehouse_nombre'),
            func.coalesce(func.sum(Stock.cantidad), 0).label('cantidad'),
            func.coalesce(func.max(item_alias.min_stock), 0).label('min_stock')
        )
        .select_from(item_alias)
        .join(InventoryCategory, InventoryCategory.id == item_alias.categoria_id)
        .outerjoin(Stock, Stock.item_id == item_alias.id)
        .outerjoin(warehouse_alias, warehouse_alias.id == Stock.warehouse_id)
        .filter(item_alias.company_id == company_id)
    )

    if warehouse_id:
        query = query.filter(warehouse_alias.id == warehouse_id)

    if categoria_id:
        query = query.filter(item_alias.categoria_id == categoria_id)

    if buscar:
        like_pattern = f"%{buscar.lower()}%"
        query = query.filter(
            db.or_(
                func.lower(item_alias.sku).like(like_pattern),
                func.lower(item_alias.nombre).like(like_pattern)
            )
        )

    query = query.group_by(
        item_alias.id,
        item_alias.sku,
        item_alias.nombre,
        item_alias.unidad,
        InventoryCategory.nombre,
        warehouse_alias.id,
        warehouse_alias.nombre,
    ).order_by(item_alias.nombre.asc(), warehouse_alias.nombre.asc())

    rows = query.all()

    if not rows:
        return []

    item_ids = {row.item_id for row in rows}
    last_movement_map = {
        item_id: last_date
        for item_id, last_date in (
            db.session.query(
                StockMovement.item_id,
                func.max(StockMovement.fecha)
            )
            .filter(StockMovement.item_id.in_(item_ids))
            .group_by(StockMovement.item_id)
            .all()
        )
    }

    summary = []
    for row in rows:
        last_date = last_movement_map.get(row.item_id)
        summary.append(
            {
                'item_id': row.item_id,
                'sku': row.sku,
                'item_nombre': row.item_nombre,
                'categoria': row.categoria,
                'unidad': row.unidad,
                'warehouse_id': row.warehouse_id,
                'warehouse_nombre': row.warehouse_nombre or 'Sin depósito asignado',
                'cantidad': float(row.cantidad or 0),
                'min_stock': float(row.min_stock or 0),
                'is_low_stock': (row.cantidad or 0) <= (row.min_stock or 0),
                'last_movement': last_date,
            }
        )

    return summary


def _extract_adjustment_delta(movement: StockMovement) -> Decimal:
    """Recupera la diferencia real de un ajuste para identificar pérdidas."""

    if movement.tipo != 'ajuste' or not movement.motivo:
        return Decimal('0')

    motivo = movement.motivo
    if '→' not in motivo:
        return Decimal('0')

    try:
        _, payload = motivo.split('Ajuste:', 1)
        origen_raw, destino_raw = payload.split('→', 1)
        origen = Decimal(origen_raw.strip().replace(',', '.'))
        destino_text = destino_raw.split('.', 1)[0].strip()
        destino = Decimal(destino_text.replace(',', '.'))
        return destino - origen
    except (ValueError, InvalidOperation):
        return Decimal('0')


def _movement_is_waste(movement: StockMovement) -> bool:
    """Clasifica un movimiento para detectar desperdicios."""

    if movement.tipo == 'ajuste':
        return _extract_adjustment_delta(movement) < 0

    if movement.tipo != 'egreso':
        return False

    motivo = (movement.motivo or '').lower()
    if any(keyword in motivo for keyword in WASTE_KEYWORDS):
        return True

    # Si no está asociado a una obra, se interpreta como merma general.
    return movement.project_id is None


def _build_cost_map(company_id: int, items: list[InventoryItem]) -> dict[str, float]:
    """Obtiene valores de costo promedio basados en códigos históricos."""

    skus = {item.sku for item in items if item.sku}
    if not skus:
        return {}

    historic_items = ItemInventario.query.filter(
        ItemInventario.organizacion_id == company_id,
        ItemInventario.codigo.in_(skus),
    ).all()

    cost_map = {hist.codigo: float(hist.precio_promedio or 0) for hist in historic_items}

    # Intento adicional por nombre cuando no existe código coincidente.
    missing = {item for item in items if item.sku not in cost_map}
    if missing:
        names = [item.nombre for item in missing]
        name_lookup = {
            hist.nombre: float(hist.precio_promedio or 0)
            for hist in ItemInventario.query.filter(
                ItemInventario.organizacion_id == company_id,
                ItemInventario.nombre.in_(names),
            ).all()
        }
        for item in missing:
            if item.nombre in name_lookup:
                cost_map[item.sku] = name_lookup[item.nombre]

    return cost_map


def _collect_reservation_metrics(item_ids: set[int]):
    """Agrupa métricas clave de reservas activas y consumidas."""

    if not item_ids:
        return defaultdict(
            lambda: {
                'activa': 0.0,
                'consumida': 0.0,
                'liberada': 0.0,
                'ultima_actualizacion': None,
                'overdue': [],
            }
        ), []

    reservations = (
        StockReservation.query
        .filter(StockReservation.item_id.in_(item_ids))
        .all()
    )

    metrics = defaultdict(
        lambda: {
            'activa': 0.0,
            'consumida': 0.0,
            'liberada': 0.0,
            'ultima_actualizacion': None,
            'overdue': [],
        }
    )
    overdue_entries = []
    threshold = datetime.utcnow() - timedelta(days=3)

    for reserva in reservations:
        data = metrics[reserva.item_id]
        qty = float(reserva.qty or 0)
        if reserva.estado == 'activa':
            data['activa'] += qty
            if reserva.created_at and reserva.created_at < threshold:
                overdue_entries.append(reserva)
                data['overdue'].append(reserva)
        elif reserva.estado == 'consumida':
            data['consumida'] += qty
        elif reserva.estado == 'liberada':
            data['liberada'] += qty

        last_update = reserva.updated_at or reserva.created_at
        if last_update:
            if not data['ultima_actualizacion'] or last_update > data['ultima_actualizacion']:
                data['ultima_actualizacion'] = last_update

    return metrics, overdue_entries


def _collect_movement_metrics(company_id: int, item_ids: set[int]):
    """Calcula consumo, desperdicio y responsables por item."""

    if not item_ids:
        return (
            defaultdict(
                lambda: {
                    'consumido': 0.0,
                    'desperdicio': 0.0,
                    'recuperado': 0.0,
                    'ultimo_movimiento': None,
                    'ultimo_motivo': None,
                    'ultimo_usuario': None,
                    'ultimo_tipo': None,
                }
            ),
            {},
            {},
        )

    movements = (
        StockMovement.query
        .join(InventoryItem)
        .filter(
            InventoryItem.company_id == company_id,
            StockMovement.item_id.in_(item_ids),
        )
        .order_by(StockMovement.fecha.desc())
        .all()
    )

    item_metrics = defaultdict(
        lambda: {
            'consumido': 0.0,
            'desperdicio': 0.0,
            'recuperado': 0.0,
            'ultimo_movimiento': None,
            'ultimo_motivo': None,
            'ultimo_usuario': None,
            'ultimo_tipo': None,
        }
    )
    project_metrics = defaultdict(
        lambda: {
            'nombre': '',
            'consumido': 0.0,
            'desperdicio': 0.0,
            'movimientos': 0,
        }
    )
    operator_metrics = defaultdict(
        lambda: {
            'nombre': 'Sin usuario',
            'consumido': 0.0,
            'desperdicio': 0.0,
            'movimientos': 0,
        }
    )

    for movimiento in movements:
        data = item_metrics[movimiento.item_id]
        qty = float(movimiento.qty or 0)

        if movimiento.tipo == 'egreso':
            if _movement_is_waste(movimiento):
                data['desperdicio'] += qty
            else:
                data['consumido'] += qty
        elif movimiento.tipo == 'ajuste':
            delta = _extract_adjustment_delta(movimiento)
            if delta < 0:
                data['desperdicio'] += float(abs(delta))
            else:
                data['recuperado'] += float(delta)

        if not data['ultimo_movimiento'] or movimiento.fecha > data['ultimo_movimiento']:
            data['ultimo_movimiento'] = movimiento.fecha
            data['ultimo_motivo'] = movimiento.motivo
            data['ultimo_usuario'] = (
                movimiento.user.nombre_completo
                if movimiento.user and getattr(movimiento.user, 'nombre_completo', None)
                else getattr(movimiento.user, 'email', None)
            )
            data['ultimo_tipo'] = movimiento.tipo

        if movimiento.project_id and movimiento.project:
            project = project_metrics[movimiento.project_id]
            project['nombre'] = movimiento.project.nombre
            project['movimientos'] += 1
            if _movement_is_waste(movimiento):
                project['desperdicio'] += qty
            else:
                project['consumido'] += qty

        if movimiento.user_id and movimiento.user:
            operator = operator_metrics[movimiento.user_id]
            operator['nombre'] = (
                movimiento.user.nombre_completo
                if getattr(movimiento.user, 'nombre_completo', None)
                else movimiento.user.email
            )
            operator['movimientos'] += 1
            if _movement_is_waste(movimiento):
                operator['desperdicio'] += qty
            else:
                operator['consumido'] += qty

    return item_metrics, project_metrics, operator_metrics

@inventario_new_bp.route('/')
@inventario_new_bp.route('/items')
@login_required
def items():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    # Filtros
    categoria_id = request.args.get('categoria')
    buscar = request.args.get('buscar')
    stock_bajo = request.args.get('stock_bajo')

    company_id = _resolve_company_id()
    if not company_id:
        flash('No pudimos determinar la organización actual.', 'warning')
        return redirect(url_for('reportes.dashboard'))

    query = InventoryItem.query.filter_by(company_id=company_id, activo=True)
    
    if categoria_id:
        query = query.filter(InventoryItem.categoria_id == categoria_id)
    
    if buscar:
        query = query.filter(
            db.or_(
                InventoryItem.sku.contains(buscar),
                InventoryItem.nombre.contains(buscar),
                InventoryItem.descripcion.contains(buscar)
            )
        )
    
    items = query.order_by(InventoryItem.nombre).all()
    
    # Filtrar por stock bajo si se solicita
    if stock_bajo:
        items = [item for item in items if item.is_low_stock]
    
    # Para JSON
    json_resp = get_json_response({
        'data': [
            {
                'id': item.id,
                'sku': item.sku,
                'nombre': item.nombre,
                'categoria': item.categoria.nombre,
                'total_stock': float(item.total_stock),
                'min_stock': float(item.min_stock),
                'is_low_stock': item.is_low_stock
            } for item in items
        ]
    })
    if json_resp:
        return json_resp
    
    # Obtener categorías para filtros
    categorias = get_active_categories(company_id)

    return render_template('inventario_new/items.html',
                         items=items,
                         categorias=categorias,
                         filtros={'categoria': categoria_id, 'buscar': buscar, 'stock_bajo': stock_bajo})


@inventario_new_bp.route('/cuadro-stock')
@login_required
def cuadro_stock():
    if not current_user.puede_acceder_modulo('inventario'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    company_id = _resolve_company_id()
    if not company_id:
        flash('No pudimos determinar la organización actual.', 'warning')
        return redirect(url_for('inventario_new.items'))

    warehouse_id = request.args.get('warehouse', type=int)
    categoria_id = request.args.get('categoria', type=int)
    buscar = request.args.get('buscar', type=str)

    summary = _build_stock_summary(
        company_id,
        warehouse_id=warehouse_id,
        categoria_id=categoria_id,
        buscar=buscar,
    )

    item_ids = {row['item_id'] for row in summary}
    inventory_items = []
    if item_ids:
        inventory_items = InventoryItem.query.filter(InventoryItem.id.in_(item_ids)).all()

    cost_map = _build_cost_map(company_id, inventory_items)
    reservation_metrics, overdue_reservations = _collect_reservation_metrics(item_ids)
    movement_metrics, project_metrics, operator_metrics = _collect_movement_metrics(company_id, item_ids)

    items_by_id = {item.id: item for item in inventory_items}
    grouped_summary: dict[int, list[dict]] = defaultdict(list)
    for row in summary:
        grouped_summary[row['item_id']].append(row)

    board_rows = []
    total_disponible = 0.0
    total_alertas = 0
    perdidas_acumuladas = 0.0
    ahorros_acumulados = 0.0
    consumo_porcentajes = []

    for item_id, rows in grouped_summary.items():
        item = items_by_id.get(item_id)
        if not item:
            continue

        ubicaciones = []
        stock_total = 0.0
        low_stock_flag = False
        for row in rows:
            stock_total += row['cantidad']
            low_stock_flag = low_stock_flag or row['is_low_stock']
            ubicaciones.append(
                {
                    'nombre': row['warehouse_nombre'],
                    'cantidad': row['cantidad'],
                    'minimo': row['min_stock'],
                    'is_low': row['is_low_stock'],
                }
            )

        metrics = movement_metrics.get(item_id, {})
        reservas = reservation_metrics.get(item_id, {
            'activa': 0.0,
            'consumida': 0.0,
            'liberada': 0.0,
            'ultima_actualizacion': None,
            'overdue': [],
        })

        consumido = metrics.get('consumido', 0.0)
        desperdicio = metrics.get('desperdicio', 0.0)
        reservado_activo = reservas['activa']
        programado = reservas['activa'] + reservas['consumida']

        costo_unitario = cost_map.get(item.sku) or float(getattr(item, 'precio_promedio', 0) or 0)
        costo_total = costo_unitario * stock_total if costo_unitario else 0.0
        costo_desperdicio = costo_unitario * desperdicio if costo_unitario else 0.0

        consumo_presupuesto_pct = None
        if programado:
            consumo_presupuesto_pct = (consumido / programado) * 100 if programado else 0
        elif item.min_stock:
            consumo_presupuesto_pct = (consumido / float(item.min_stock)) * 100 if float(item.min_stock) else None

        desperdicio_pct = (desperdicio / (consumido + desperdicio) * 100) if (consumido + desperdicio) else 0

        estado_actual = 'Disponible'
        ultimo_tipo = metrics.get('ultimo_tipo')
        if low_stock_flag or (float(item.min_stock or 0) and stock_total <= float(item.min_stock)):
            estado_actual = 'Crítico'
        elif reservado_activo > 0:
            estado_actual = 'En uso'
        elif ultimo_tipo == 'transferencia':
            estado_actual = 'En tránsito'

        ultimo_movimiento = metrics.get('ultimo_movimiento') or reservas.get('ultima_actualizacion')
        responsable = metrics.get('ultimo_usuario') or 'Sin registros'
        observacion = metrics.get('ultimo_motivo')

        ahorro_estimado = 0.0
        if costo_unitario:
            saldo_planificado = max(programado - consumido - desperdicio, 0)
            ahorro_estimado = saldo_planificado * costo_unitario

        board_rows.append(
            {
                'item_id': item_id,
                'sku': item.sku,
                'item_nombre': item.nombre,
                'categoria': item.categoria.full_path if item.categoria else '',
                'unidad': item.unidad,
                'ubicaciones': ubicaciones,
                'total_disponible': stock_total,
                'reservado_activo': reservado_activo,
                'consumido': consumido,
                'desperdicio': desperdicio,
                'costo_unitario': costo_unitario,
                'costo_total': costo_total,
                'costo_desperdicio': costo_desperdicio,
                'consumo_presupuesto_pct': consumo_presupuesto_pct,
                'desperdicio_pct': desperdicio_pct,
                'responsable': responsable,
                'ultimo_movimiento': ultimo_movimiento,
                'observacion': observacion,
                'estado': estado_actual,
                'ahorro_estimado': ahorro_estimado,
                'is_low_stock': low_stock_flag,
                'programado': programado,
            }
        )

        total_disponible += stock_total
        perdidas_acumuladas += costo_desperdicio
        ahorros_acumulados += ahorro_estimado
        if consumo_presupuesto_pct is not None:
            consumo_porcentajes.append(consumo_presupuesto_pct)
        if low_stock_flag:
            total_alertas += 1

    waste_threshold = 15
    alertas = []
    for row in board_rows:
        if row['desperdicio_pct'] >= waste_threshold:
            alertas.append(
                {
                    'tipo': 'Desperdicio alto',
                    'mensaje': f"{row['item_nombre']} registra {row['desperdicio_pct']:.1f}% de mermas",
                    'nivel': 'danger',
                }
            )
        if row['is_low_stock']:
            alertas.append(
                {
                    'tipo': 'Stock crítico',
                    'mensaje': f"{row['item_nombre']} quedó por debajo del mínimo operativo",
                    'nivel': 'warning',
                }
            )

    for reserva in overdue_reservations:
        alertas.append(
            {
                'tipo': 'Devolución pendiente',
                'mensaje': f"{reserva.item.nombre} asignado a {reserva.project.nombre} no se devuelve hace más de 3 días",
                'nivel': 'info',
            }
        )

    ranking_obras = []
    for datos in project_metrics.values():
        total = datos['consumido'] + datos['desperdicio']
        eficiencia = (datos['consumido'] / total * 100) if total else 0
        ranking_obras.append(
            {
                'nombre': datos['nombre'],
                'consumido': datos['consumido'],
                'desperdicio': datos['desperdicio'],
                'eficiencia': eficiencia,
            }
        )
    ranking_obras.sort(key=lambda item: (-(item['eficiencia']), -item['consumido']))

    operarios_top = []
    for datos in operator_metrics.values():
        total = datos['consumido'] + datos['desperdicio']
        eficiencia = (datos['consumido'] / total * 100) if total else 100
        puntos = datos['consumido'] - datos['desperdicio']
        operarios_top.append(
            {
                'nombre': datos['nombre'],
                'movimientos': datos['movimientos'],
                'eficiencia': eficiencia,
                'puntos': puntos,
            }
        )
    operarios_top.sort(key=lambda entry: (-entry['puntos'], -entry['eficiencia']))

    consumo_promedio = sum(consumo_porcentajes) / len(consumo_porcentajes) if consumo_porcentajes else 0

    json_rows = []
    for row in board_rows:
        json_row = row.copy()
        json_row['ultimo_movimiento'] = (
            row['ultimo_movimiento'].isoformat() if row['ultimo_movimiento'] else None
        )
        json_row['ubicaciones'] = [
            {
                'nombre': ubicacion['nombre'],
                'cantidad': ubicacion['cantidad'],
                'minimo': ubicacion['minimo'],
                'is_low': ubicacion['is_low'],
            }
            for ubicacion in row['ubicaciones']
        ]
        json_rows.append(json_row)

    json_resp = get_json_response(
        {
            'data': json_rows,
            'meta': {
                'total_disponible': total_disponible,
                'items': len(board_rows),
                'alertas': len(alertas),
                'perdidas': perdidas_acumuladas,
                'ahorros': ahorros_acumulados,
            },
            'alertas': alertas,
            'ranking': ranking_obras,
            'operarios': operarios_top[:5],
        }
    )
    if json_resp:
        return json_resp

    warehouses = (
        Warehouse.query
        .filter_by(company_id=company_id, activo=True)
        .order_by(Warehouse.nombre)
        .all()
    )
    categorias = get_active_categories(company_id)

    filtros = {
        'warehouse': warehouse_id,
        'categoria': categoria_id,
        'buscar': buscar or '',
    }

    dashboard = {
        'perdidas': perdidas_acumuladas,
        'ahorros': ahorros_acumulados,
        'stock_critico': total_alertas,
        'consumo_promedio': consumo_promedio,
        'items': len(board_rows),
    }

    return render_template(
        'inventario_new/cuadro_stock.html',
        resumen=board_rows,
        filtros=filtros,
        warehouses=warehouses,
        categorias=categorias,
        total_disponible=total_disponible,
        total_bajo=total_alertas,
        alertas=alertas,
        dashboard=dashboard,
        ranking_obras=ranking_obras,
        operarios_top=operarios_top[:5],
        waste_threshold=waste_threshold,
    )


@inventario_new_bp.route('/categorias', methods=['GET'])
@login_required
@requires_role('administrador', 'compras')
def categorias():
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

    return render_template(
        'inventario/categorias.html',
        categorias=categorias,
        category_tree=category_tree,
        auto_seeded=auto_seeded,
        seed_stats=seed_stats,
        company=company,
    )


@inventario_new_bp.post('/categorias/seed')
@login_required
@requires_role('administrador', 'compras')
def seed_categorias_manual():
    company_id = _resolve_company_id()
    if not company_id:
        flash('No pudimos determinar la organización actual.', 'warning')
        return redirect(url_for('inventario_new.categorias'))

    company = _resolve_company(company_id)
    if not company:
        flash('No encontramos la organización seleccionada.', 'danger')
        return redirect(url_for('inventario_new.categorias'))

    stats = seed_inventory_categories_for_company(company)
    db.session.commit()

    created = stats.get('created', 0)
    existing = stats.get('existing', 0)
    reactivated = stats.get('reactivated', 0)

    message = (
        f"Catálogo listo: {created} nuevas, {existing} existentes, {reactivated} reactivadas."
    )
    flash(message, 'success' if created else 'info')

    return redirect(url_for('inventario_new.categorias'))


@inventario_new_bp.get('/api/categorias')
@login_required
def api_categorias():
    company_id = _resolve_company_id()
    if not company_id:
        return jsonify({'error': 'Organización no seleccionada'}), 400

    categorias = get_active_category_options(company_id)

    payload = [
        {
            'id': categoria.id,
            'nombre': categoria.nombre,
            'full_path': categoria.full_path,
            'parent_id': categoria.parent_id,
        }
        for categoria in categorias
    ]

    return jsonify({'categorias': payload})


@inventario_new_bp.route('/items/nuevo', methods=['GET', 'POST'])
@login_required
@requires_role('administrador', 'compras')
def nuevo_item():
    company_id = _resolve_company_id()
    if not company_id:
        flash('No pudimos determinar la organización actual.', 'warning')
        return redirect(url_for('inventario_new.items'))

    categorias, seed_stats, auto_seeded, company = ensure_categories_for_company_id(company_id)
    if auto_seeded:
        created = seed_stats.get('created', 0)
        reactivated = seed_stats.get('reactivated', 0)
        flash(
            f'Se inicializó el catálogo (creadas: {created}, reactivadas: {reactivated}).',
            'info',
        )

    if request.method == 'POST':
        # Validaciones
        required_fields = ['sku', 'nombre', 'categoria_id', 'unidad']
        for field in required_fields:
            if not request.form.get(field):
                error = f'El campo {field} es obligatorio.'
                json_resp = get_json_response(None, 400, error)
                if json_resp:
                    return json_resp
                flash(error, 'danger')
                return render_template('inventario_new/item_form.html', categorias=categorias)
        
        # Verificar SKU único
        sku = request.form.get('sku')
        if InventoryItem.query.filter_by(sku=sku).first():
            error = 'Ya existe un item con ese SKU.'
            json_resp = get_json_response(None, 400, error)
            if json_resp:
                return json_resp
            flash(error, 'danger')
            return render_template('inventario_new/item_form.html', categorias=categorias)
        
        try:
            item = InventoryItem(
                company_id=current_user.organizacion_id,
                sku=sku,
                nombre=request.form.get('nombre'),
                categoria_id=request.form.get('categoria_id'),
                unidad=request.form.get('unidad'),
                min_stock=float(request.form.get('min_stock', 0)),
                descripcion=request.form.get('descripcion')
            )
            
            db.session.add(item)
            db.session.commit()
            
            json_resp = get_json_response({'id': item.id, 'mensaje': 'Item creado exitosamente'})
            if json_resp:
                return json_resp
                
            flash('Item creado exitosamente.', 'success')
            return redirect(url_for('inventario_new.detalle_item', id=item.id))
            
        except Exception as e:
            db.session.rollback()
            error = 'Error al crear el item.'
            json_resp = get_json_response(None, 500, error)
            if json_resp:
                return json_resp
            flash(error, 'danger')
    
    return render_template('inventario_new/item_form.html', categorias=categorias, item=None)

@inventario_new_bp.route('/items/<int:id>')
@login_required
def detalle_item(id):
    item = InventoryItem.query.filter_by(id=id, company_id=current_user.organizacion_id).first_or_404()
    
    # Obtener stocks por depósito
    stocks = Stock.query.filter_by(item_id=id).join(Warehouse).all()
    
    # Obtener movimientos recientes
    movimientos = StockMovement.query.filter_by(item_id=id).order_by(StockMovement.fecha.desc()).limit(20).all()
    
    # Obtener reservas activas
    reservas = StockReservation.query.filter_by(item_id=id, estado='activa').all()
    
    json_resp = get_json_response({
        'item': {
            'id': item.id,
            'sku': item.sku,
            'nombre': item.nombre,
            'total_stock': float(item.total_stock),
            'reserved_stock': float(item.reserved_stock),
            'available_stock': float(item.available_stock),
            'is_low_stock': item.is_low_stock
        },
        'stocks': [
            {
                'warehouse': stock.warehouse.nombre,
                'cantidad': float(stock.cantidad)
            } for stock in stocks
        ]
    })
    if json_resp:
        return json_resp
    
    return render_template('inventario_new/item_detalle.html', 
                         item=item, 
                         stocks=stocks,
                         movimientos=movimientos,
                         reservas=reservas)

@inventario_new_bp.route('/warehouses')
@login_required
def warehouses():
    warehouses = Warehouse.query.filter_by(company_id=current_user.organizacion_id, activo=True).all()
    
    json_resp = get_json_response({
        'data': [
            {
                'id': wh.id,
                'nombre': wh.nombre,
                'direccion': wh.direccion,
                'items_count': len(wh.stocks)
            } for wh in warehouses
        ]
    })
    if json_resp:
        return json_resp
    
    return render_template('inventario_new/warehouses.html', warehouses=warehouses)

@inventario_new_bp.route('/warehouses/nuevo', methods=['POST'])
@login_required
@requires_role('administrador', 'compras')
def nuevo_warehouse():
    nombre = request.form.get('nombre')
    
    if not nombre:
        error = 'El nombre del depósito es obligatorio.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
        return redirect(url_for('inventario_new.warehouses'))
    
    try:
        warehouse = Warehouse(
            company_id=current_user.organizacion_id,
            nombre=nombre,
            direccion=request.form.get('direccion')
        )
        
        db.session.add(warehouse)
        db.session.commit()
        
        json_resp = get_json_response({'id': warehouse.id, 'mensaje': 'Depósito creado exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Depósito creado exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al crear el depósito.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.warehouses'))

@inventario_new_bp.route('/movimientos', methods=['GET', 'POST'])
@login_required
def movimientos():
    if request.method == 'POST' and current_user.rol in ['administrador', 'compras']:
        return crear_movimiento()
    
    # Listar movimientos
    movimientos = StockMovement.query.join(InventoryItem).filter(
        InventoryItem.company_id == current_user.organizacion_id
    ).order_by(StockMovement.fecha.desc()).limit(50).all()
    
    json_resp = get_json_response({
        'data': [
            {
                'id': mov.id,
                'item': mov.item.nombre,
                'tipo': mov.tipo,
                'cantidad': float(mov.qty),
                'warehouse': mov.warehouse_display,
                'fecha': mov.fecha.isoformat(),
                'usuario': mov.user.nombre_completo
            } for mov in movimientos
        ]
    })
    if json_resp:
        return json_resp
    
    # Obtener datos para el formulario
    items = InventoryItem.query.filter_by(company_id=current_user.organizacion_id, activo=True).all()
    warehouses = Warehouse.query.filter_by(company_id=current_user.organizacion_id, activo=True).all()
    projects = Obra.query.filter_by(organizacion_id=current_user.organizacion_id).all()
    
    return render_template('inventario_new/movimientos.html', 
                         movimientos=movimientos,
                         items=items,
                         warehouses=warehouses,
                         projects=projects)

def crear_movimiento():
    """Crea un nuevo movimiento de stock"""
    item_id = request.form.get('item_id')
    tipo = request.form.get('tipo')
    qty = request.form.get('qty')
    motivo = request.form.get('motivo')
    
    if not all([item_id, tipo, qty, motivo]):
        error = 'Todos los campos son obligatorios.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
        return redirect(url_for('inventario_new.movimientos'))
    
    try:
        qty = float(qty)
        if qty <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")
            
        item = InventoryItem.query.get(item_id)
        
        # Validaciones específicas por tipo
        if tipo == 'ingreso':
            warehouse_id = request.form.get('destino_warehouse_id')
            if not warehouse_id:
                raise ValueError("Depósito destino es obligatorio para ingresos")
            movimiento = crear_movimiento_ingreso(item, qty, warehouse_id, motivo)
            
        elif tipo == 'egreso':
            warehouse_id = request.form.get('origen_warehouse_id')
            if not warehouse_id:
                raise ValueError("Depósito origen es obligatorio para egresos")
            movimiento = crear_movimiento_egreso(item, qty, warehouse_id, motivo)
            
        elif tipo == 'transferencia':
            origen_id = request.form.get('origen_warehouse_id')
            destino_id = request.form.get('destino_warehouse_id')
            if not all([origen_id, destino_id]):
                raise ValueError("Depósitos origen y destino son obligatorios para transferencias")
            if origen_id == destino_id:
                raise ValueError("El depósito origen debe ser diferente al destino")
            movimiento = crear_movimiento_transferencia(item, qty, origen_id, destino_id, motivo)
            
        elif tipo == 'ajuste':
            warehouse_id = request.form.get('destino_warehouse_id')
            nuevo_stock = request.form.get('nuevo_stock')
            if not all([warehouse_id, nuevo_stock]):
                raise ValueError("Depósito y nuevo stock son obligatorios para ajustes")
            movimiento = crear_movimiento_ajuste(item, float(nuevo_stock), warehouse_id, motivo)
        
        else:
            raise ValueError("Tipo de movimiento no válido")
        
        db.session.add(movimiento)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Movimiento registrado exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Movimiento registrado exitosamente.', 'success')
        
    except ValueError as e:
        error = str(e)
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    except Exception as e:
        db.session.rollback()
        error = 'Error al registrar el movimiento.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.movimientos'))

def crear_movimiento_ingreso(item, qty, warehouse_id, motivo):
    """Crea un movimiento de ingreso"""
    # Actualizar o crear stock
    stock = Stock.query.filter_by(item_id=item.id, warehouse_id=warehouse_id).first()
    if not stock:
        stock = Stock(item_id=item.id, warehouse_id=warehouse_id, cantidad=0)
        db.session.add(stock)
    
    stock.cantidad += qty
    
    return StockMovement(
        item_id=item.id,
        tipo='ingreso',
        qty=qty,
        destino_warehouse_id=warehouse_id,
        motivo=motivo,
        user_id=current_user.id
    )

def crear_movimiento_egreso(item, qty, warehouse_id, motivo):
    """Crea un movimiento de egreso"""
    stock = Stock.query.filter_by(item_id=item.id, warehouse_id=warehouse_id).first()
    if not stock or stock.cantidad < qty:
        raise ValueError("Stock insuficiente en el depósito")
    
    stock.cantidad -= qty
    
    return StockMovement(
        item_id=item.id,
        tipo='egreso',
        qty=qty,
        origen_warehouse_id=warehouse_id,
        motivo=motivo,
        user_id=current_user.id
    )

def crear_movimiento_transferencia(item, qty, origen_id, destino_id, motivo):
    """Crea un movimiento de transferencia"""
    # Verificar stock origen
    stock_origen = Stock.query.filter_by(item_id=item.id, warehouse_id=origen_id).first()
    if not stock_origen or stock_origen.cantidad < qty:
        raise ValueError("Stock insuficiente en el depósito origen")
    
    # Actualizar stock origen
    stock_origen.cantidad -= qty
    
    # Actualizar o crear stock destino
    stock_destino = Stock.query.filter_by(item_id=item.id, warehouse_id=destino_id).first()
    if not stock_destino:
        stock_destino = Stock(item_id=item.id, warehouse_id=destino_id, cantidad=0)
        db.session.add(stock_destino)
    
    stock_destino.cantidad += qty
    
    return StockMovement(
        item_id=item.id,
        tipo='transferencia',
        qty=qty,
        origen_warehouse_id=origen_id,
        destino_warehouse_id=destino_id,
        motivo=motivo,
        user_id=current_user.id
    )

def crear_movimiento_ajuste(item, nuevo_stock, warehouse_id, motivo):
    """Crea un movimiento de ajuste"""
    stock = Stock.query.filter_by(item_id=item.id, warehouse_id=warehouse_id).first()
    if not stock:
        stock = Stock(item_id=item.id, warehouse_id=warehouse_id, cantidad=0)
        db.session.add(stock)
    
    stock_anterior = stock.cantidad
    stock.cantidad = nuevo_stock
    qty_ajuste = nuevo_stock - stock_anterior
    
    return StockMovement(
        item_id=item.id,
        tipo='ajuste',
        qty=abs(qty_ajuste),
        destino_warehouse_id=warehouse_id,
        motivo=f"Ajuste: {stock_anterior} → {nuevo_stock}. {motivo}",
        user_id=current_user.id
    )

@inventario_new_bp.route('/alertas')
@login_required
def alertas():
    """Muestra items con stock bajo"""
    items_stock_bajo = InventoryItem.query.filter_by(
        company_id=current_user.organizacion_id, 
        activo=True
    ).all()
    
    items_stock_bajo = [item for item in items_stock_bajo if item.is_low_stock]
    
    json_resp = get_json_response({
        'data': [
            {
                'id': item.id,
                'sku': item.sku,
                'nombre': item.nombre,
                'total_stock': float(item.total_stock),
                'min_stock': float(item.min_stock),
                'diferencia': float(item.min_stock - item.total_stock)
            } for item in items_stock_bajo
        ]
    })
    if json_resp:
        return json_resp
    
    return render_template('inventario_new/alertas.html', items=items_stock_bajo)

@inventario_new_bp.route('/reservas', methods=['GET', 'POST'])
@login_required
def reservas():
    if request.method == 'POST':
        return crear_reserva()
    
    # Listar reservas activas
    reservas = StockReservation.query.join(InventoryItem).filter(
        InventoryItem.company_id == current_user.organizacion_id,
        StockReservation.estado == 'activa'
    ).all()
    
    json_resp = get_json_response({
        'data': [
            {
                'id': res.id,
                'item': res.item.nombre,
                'proyecto': res.project.nombre,
                'cantidad': float(res.qty),
                'fecha': res.created_at.isoformat()
            } for res in reservas
        ]
    })
    if json_resp:
        return json_resp
    
    # Obtener datos para el formulario
    items = InventoryItem.query.filter_by(company_id=current_user.organizacion_id, activo=True).all()
    projects = Obra.query.filter_by(organizacion_id=current_user.organizacion_id).all()
    
    return render_template('inventario_new/reservas.html', 
                         reservas=reservas,
                         items=items,
                         projects=projects)

def crear_reserva():
    """Crea una nueva reserva de stock"""
    item_id = request.form.get('item_id')
    project_id = request.form.get('project_id')
    qty = request.form.get('qty')
    
    if not all([item_id, project_id, qty]):
        error = 'Todos los campos son obligatorios.'
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
        return redirect(url_for('inventario_new.reservas'))
    
    try:
        qty = float(qty)
        item = InventoryItem.query.get(item_id)
        
        if qty > item.available_stock:
            raise ValueError("No hay suficiente stock disponible para reservar")
        
        reserva = StockReservation(
            item_id=item_id,
            project_id=project_id,
            qty=qty,
            created_by=current_user.id
        )
        
        db.session.add(reserva)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Reserva creada exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Reserva creada exitosamente.', 'success')
        
    except ValueError as e:
        error = str(e)
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    except Exception as e:
        db.session.rollback()
        error = 'Error al crear la reserva.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.reservas'))

@inventario_new_bp.route('/reservas/<int:id>/liberar', methods=['POST'])
@login_required
@requires_role('administrador', 'compras')
def liberar_reserva(id):
    reserva = StockReservation.query.get_or_404(id)
    
    try:
        reserva.estado = 'liberada'
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Reserva liberada exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Reserva liberada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        error = 'Error al liberar la reserva.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.reservas'))

@inventario_new_bp.route('/reservas/<int:id>/consumir', methods=['POST'])
@login_required
@requires_role('administrador', 'compras')
def consumir_reserva(id):
    reserva = StockReservation.query.get_or_404(id)
    
    try:
        # Crear movimiento de egreso
        # Buscar el depósito con más stock del item
        stock_disponible = Stock.query.filter_by(item_id=reserva.item_id).order_by(Stock.cantidad.desc()).first()
        
        if not stock_disponible or stock_disponible.cantidad < reserva.qty:
            raise ValueError("No hay suficiente stock disponible para consumir la reserva")
        
        # Crear movimiento de egreso
        movimiento = StockMovement(
            item_id=reserva.item_id,
            tipo='egreso',
            qty=reserva.qty,
            origen_warehouse_id=stock_disponible.warehouse_id,
            project_id=reserva.project_id,
            motivo=f"Consumo de reserva para {reserva.project.nombre}",
            user_id=current_user.id
        )
        
        # Actualizar stock
        stock_disponible.cantidad -= reserva.qty
        
        # Marcar reserva como consumida
        reserva.estado = 'consumida'
        
        db.session.add(movimiento)
        db.session.commit()
        
        json_resp = get_json_response({'mensaje': 'Reserva consumida exitosamente'})
        if json_resp:
            return json_resp
            
        flash('Reserva consumida exitosamente.', 'success')
        
    except ValueError as e:
        error = str(e)
        json_resp = get_json_response(None, 400, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    except Exception as e:
        db.session.rollback()
        error = 'Error al consumir la reserva.'
        json_resp = get_json_response(None, 500, error)
        if json_resp:
            return json_resp
        flash(error, 'danger')
    
    return redirect(url_for('inventario_new.reservas'))