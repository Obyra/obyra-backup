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
    current_app.logger.info(f"[INVENTARIO] Accediendo a lista. User: {current_user.email}")
    if not current_user.puede_acceder_modulo('inventario'):
        current_app.logger.info(f"[INVENTARIO] Usuario sin permisos: {current_user.email}")
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    categoria_id = request.args.get('categoria', '')
    buscar = request.args.get('buscar', '')
    stock_bajo = request.args.get('stock_bajo', '')

    # Obtener org_id del usuario actual
    org_id = get_current_org_id() or current_user.organizacion_id

    # Debug log
    current_app.logger.info(f"[INVENTARIO] org_id={org_id}, user.organizacion_id={current_user.organizacion_id}")

    # Query base - usar outerjoin para incluir items aunque la categoría no exista
    query = ItemInventario.query.outerjoin(ItemInventario.categoria)

    # Filtrar por organización del usuario
    if org_id:
        query = query.filter(ItemInventario.organizacion_id == org_id)
        current_app.logger.info(f"[INVENTARIO] Filtrando por org_id={org_id}")

    if categoria_id:
        query = query.filter(ItemInventario.categoria_id == categoria_id)

    # Improved search with case-insensitive partial matching
    if buscar:
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
    current_app.logger.info(f"[INVENTARIO] Items encontrados: {len(items)}")

    # Get confirmed obras for each item
    from models.projects import Obra
    from models.budgets import Presupuesto

    items_con_obras = []
    for item in items:
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

    # Load new inventory categories
    org_id = get_current_org_id() or current_user.organizacion_id
    categorias_nuevas = []
    if org_id:
        categorias_nuevas = InventoryCategory.query.filter_by(
            company_id=org_id,
            is_active=True,
            parent_id=None
        ).order_by(InventoryCategory.sort_order, InventoryCategory.nombre).all()

    categorias = CategoriaInventario.query.order_by(CategoriaInventario.nombre).all()

    # Get all obras for dropdowns
    obras_disponibles = Obra.query.join(Presupuesto).filter(
        db.or_(
            Presupuesto.confirmado_como_obra == True,
            Presupuesto.estado.in_(['aprobado', 'convertido', 'confirmado'])
        )
    ).distinct().all()

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
    if current_user.role not in ['admin', 'pm', 'tecnico']:
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
            # Validaciones mejoradas para ajustes
            if not motivo or motivo.strip() == '':
                flash('⚠️ El motivo es OBLIGATORIO para ajustes de inventario. Especificá la razón (ej: conteo físico, merma, error sistema).', 'danger')
                return redirect(url_for('inventario.detalle', id=id))

            # Calcular diferencia porcentual
            stock_anterior = float(item.stock_actual) if item.stock_actual else 0
            diferencia = cantidad - stock_anterior
            if stock_anterior > 0:
                diferencia_porcentual = abs(diferencia / stock_anterior * 100)
            else:
                diferencia_porcentual = 100 if cantidad > 0 else 0

            # Alerta si el ajuste es mayor al 20%
            if diferencia_porcentual > 20:
                current_app.logger.warning(
                    f"⚠️ AJUSTE SIGNIFICATIVO: {item.nombre} - "
                    f"Stock anterior: {stock_anterior}, Nuevo: {cantidad}, "
                    f"Diferencia: {diferencia_porcentual:.1f}% - "
                    f"Usuario: {current_user.email}, Motivo: {motivo}"
                )
                flash(
                    f'⚠️ ALERTA: Ajuste significativo de {diferencia_porcentual:.1f}%. '
                    f'Stock anterior: {stock_anterior}, Nuevo stock: {cantidad}. '
                    f'Este ajuste ha sido registrado para auditoría.',
                    'warning'
                )

            # Aplicar ajuste
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

    # Obtener obras de presupuestos aprobados
    from models.budgets import Presupuesto
    obras = Obra.query.join(Presupuesto).filter(
        db.or_(
            Presupuesto.confirmado_como_obra == True,
            Presupuesto.estado.in_(['aprobado', 'convertido', 'confirmado'])
        )
    ).distinct().order_by(Obra.nombre).all()

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

            # Validación flexible de stock - permite negativo con alerta
            stock_insuficiente = cantidad_usada > stock_actual
            if stock_insuficiente:
                stock_resultante = stock_actual - cantidad_usada
                current_app.logger.warning(
                    f"⚠️ Stock insuficiente para {item.nombre}. "
                    f"Disponible: {stock_actual}, Requerido: {cantidad_usada}, "
                    f"Resultante: {stock_resultante}. "
                    f"Permitiendo operación con stock negativo."
                )
                flash(
                    f'⚠️ ALERTA: Stock insuficiente para {item.nombre}. '
                    f'Disponible: {stock_actual}, solicitado: {cantidad_usada}. '
                    f'El stock quedará en {stock_resultante}. '
                    f'Registrá la entrada de material pendiente.',
                    'warning'
                )

            # Convertir fecha
            fecha_uso_obj = date.today()
            if fecha_uso:
                from datetime import datetime
                fecha_uso_obj = datetime.strptime(fecha_uso, '%Y-%m-%d').date()

            # Crear uso con precio histórico
            uso = UsoInventario(
                obra_id=obra_id,
                item_id=item_id,
                cantidad_usada=cantidad_usada,
                fecha_uso=fecha_uso_obj,
                observaciones=observaciones,
                usuario_id=current_user.id,
                # Guardar precio al momento del uso (NO el promedio futuro)
                precio_unitario_al_uso=item.precio_promedio,
                moneda='ARS'  # Por defecto ARS, ajustar según configuración
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


@inventario_bp.route('/api/generar-codigo', methods=['POST'])
@login_required
def api_generar_codigo():
    """
    API para generar código automático correlativo único basado en categoría.
    Formato: PREFIJO + NÚMERO CORRELATIVO (ej: MAT001, HER001, MAQ001)
    """
    import re

    data = request.get_json() or {}
    categoria_id = data.get('categoria_id')

    org_id = get_current_org_id() or current_user.organizacion_id

    if not categoria_id:
        return jsonify({'error': 'La categoría es requerida'}), 400

    try:
        # Obtener categoría
        categoria = InventoryCategory.query.get(categoria_id)
        if not categoria:
            return jsonify({'error': 'Categoría no encontrada'}), 404

        # Generar prefijo de 3 letras basado en el nombre de la categoría
        categoria_nombre = categoria.nombre.upper()
        # Remover caracteres especiales y quedarse con letras
        prefijo = re.sub(r'[^A-Z]', '', categoria_nombre)[:3]

        # Si el prefijo es muy corto, completar
        if len(prefijo) < 3:
            prefijo = prefijo.ljust(3, 'X')

        # Buscar el último código con este prefijo en la organización
        ultimo_item = ItemInventario.query.filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.codigo.like(f'{prefijo}%')
        ).order_by(ItemInventario.codigo.desc()).first()

        # Determinar siguiente número
        siguiente_numero = 1
        if ultimo_item and ultimo_item.codigo:
            # Extraer número del código existente
            match = re.search(r'(\d+)$', ultimo_item.codigo)
            if match:
                siguiente_numero = int(match.group(1)) + 1

        # Generar código con formato PREFIJO + 3 dígitos
        codigo = f"{prefijo}{siguiente_numero:03d}"

        # Verificar que no exista (por si acaso)
        while ItemInventario.query.filter_by(codigo=codigo, organizacion_id=org_id).first():
            siguiente_numero += 1
            codigo = f"{prefijo}{siguiente_numero:03d}"

        return jsonify({
            'codigo': codigo,
            'prefijo': prefijo,
            'numero': siguiente_numero,
            'categoria_nombre': categoria.nombre,
            'mensaje': f'Código generado: {codigo}'
        })

    except Exception as e:
        current_app.logger.error(f"Error generando código: {str(e)}")
        return jsonify({'error': 'Error al generar código automático'}), 500


@inventario_bp.route('/api/tipo-cambio', methods=['GET'])
@login_required
def api_tipo_cambio():
    """
    API para obtener el tipo de cambio actual USD/ARS.
    Obtiene la cotización del Banco Nación Argentina (BNA).
    """
    from models import ExchangeRate
    from datetime import date, datetime, timedelta
    import requests
    from bs4 import BeautifulSoup

    def obtener_cotizacion_bna():
        """Obtiene la cotización del dólar del Banco Nación Argentina"""
        try:
            url = "https://www.bna.com.ar/Personas"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Buscar la tabla de cotizaciones
            tabla = soup.find('table', class_='table')
            if not tabla:
                return None

            # Buscar la fila del dólar estadounidense (Billetes)
            filas = tabla.find_all('tr')
            for fila in filas:
                celdas = fila.find_all('td')
                if len(celdas) >= 3:
                    moneda = celdas[0].get_text(strip=True).lower()
                    # BNA usa "Dolar U.S.A" para el dólar estadounidense
                    if 'dolar' in moneda and ('u.s.a' in moneda or 'estadounidense' in moneda):
                        # Obtener precio de venta (tercera columna)
                        venta_text = celdas[2].get_text(strip=True)
                        # Limpiar y convertir: "1.480,00" -> 1480.00
                        venta_text = venta_text.replace('.', '').replace(',', '.')
                        return float(venta_text)

            return None
        except Exception as e:
            current_app.logger.warning(f"Error obteniendo cotización BNA: {str(e)}")
            return None

    try:
        # Primero intentar obtener cotización en tiempo real del BNA
        cotizacion_bna = obtener_cotizacion_bna()

        if cotizacion_bna:
            # Guardar/actualizar en la base de datos
            try:
                rate = ExchangeRate.query.filter(
                    ExchangeRate.base_currency == 'USD',
                    ExchangeRate.quote_currency == 'ARS',
                    ExchangeRate.provider == 'BNA'
                ).first()

                if rate:
                    rate.value = cotizacion_bna
                    rate.as_of_date = date.today()
                    rate.fetched_at = datetime.utcnow()
                else:
                    rate = ExchangeRate(
                        base_currency='USD',
                        quote_currency='ARS',
                        value=cotizacion_bna,
                        provider='BNA',
                        as_of_date=date.today(),
                        fetched_at=datetime.utcnow()
                    )
                    db.session.add(rate)

                db.session.commit()
            except Exception as db_error:
                current_app.logger.warning(f"Error guardando cotización: {str(db_error)}")
                db.session.rollback()

            return jsonify({
                'success': True,
                'tipo_cambio': cotizacion_bna,
                'provider': 'BNA',
                'fecha': date.today().isoformat(),
                'actualizado': datetime.utcnow().isoformat()
            })

        # Si no se pudo obtener del BNA, buscar en BD
        rate = ExchangeRate.query.filter(
            ExchangeRate.base_currency == 'USD',
            ExchangeRate.quote_currency == 'ARS'
        ).order_by(
            ExchangeRate.as_of_date.desc(),
            ExchangeRate.fetched_at.desc()
        ).first()

        if rate:
            return jsonify({
                'success': True,
                'tipo_cambio': float(rate.value),
                'provider': rate.provider + ' (caché)',
                'fecha': rate.as_of_date.isoformat() if rate.as_of_date else None,
                'actualizado': rate.fetched_at.isoformat() if rate.fetched_at else None
            })
        else:
            # Valor por defecto si todo falla
            return jsonify({
                'success': True,
                'tipo_cambio': 1150.0,
                'provider': 'default',
                'fecha': date.today().isoformat(),
                'actualizado': None,
                'mensaje': 'Usando cotización por defecto - no se pudo conectar al BNA'
            })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo tipo de cambio: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error al obtener tipo de cambio',
            'tipo_cambio': 1150.0
        }), 500


@inventario_bp.route('/api/buscar-similares', methods=['POST'])
@login_required
def api_buscar_similares():
    """
    API para buscar materiales similares en el catálogo global.
    Retorna sugerencias de materiales existentes.
    """
    from models import GlobalMaterialCatalog, InventoryCategory

    data = request.get_json() or {}

    nombre = data.get('nombre', '').strip()
    categoria_id = data.get('categoria_id')
    marca = data.get('marca', '').strip() or None
    limit = int(data.get('limit', 10))

    if not nombre:
        return jsonify({'similares': []})

    # Obtener nombre de categoría si se especifica
    categoria_nombre = None
    if categoria_id:
        categoria = InventoryCategory.query.get(categoria_id)
        if categoria:
            categoria_nombre = categoria.nombre

    # Buscar materiales similares
    try:
        similares = GlobalMaterialCatalog.buscar_similares(
            nombre=nombre,
            categoria_nombre=categoria_nombre,
            marca=marca,
            limit=limit
        )

        resultados = []
        for material in similares:
            resultados.append({
                'id': material.id,
                'codigo': material.codigo,
                'nombre': material.nombre,
                'descripcion_completa': material.descripcion_completa,
                'categoria': material.categoria_nombre,
                'marca': material.marca,
                'unidad': material.unidad,
                'veces_usado': material.veces_usado,
                'precio_promedio_ars': float(material.precio_promedio_ars) if material.precio_promedio_ars else None,
                'precio_promedio_usd': float(material.precio_promedio_usd) if material.precio_promedio_usd else None,
            })

        return jsonify({
            'similares': resultados,
            'total': len(resultados),
            'mensaje': f'Se encontraron {len(resultados)} materiales similares en el catálogo global'
        })

    except Exception as e:
        current_app.logger.error(f"Error buscando similares: {str(e)}")
        return jsonify({'error': 'Error al buscar materiales similares', 'similares': []}), 500


@inventario_bp.route('/api/usar-material-global/<int:material_id>', methods=['POST'])
@login_required
def api_usar_material_global(material_id):
    """
    API para usar un material del catálogo global.
    Crea un item de inventario local y registra el uso.
    """
    from models import GlobalMaterialCatalog, GlobalMaterialUsage, ItemInventario, MovimientoInventario

    org_id = get_current_org_id() or current_user.organizacion_id
    if not org_id:
        return jsonify({'error': 'No tienes una organización activa'}), 400

    # Obtener material del catálogo global
    material = GlobalMaterialCatalog.query.get(material_id)
    if not material:
        return jsonify({'error': 'Material no encontrado en el catálogo global'}), 404

    data = request.get_json() or {}
    stock_inicial = float(data.get('stock_inicial', 0))
    precio_ars = float(data.get('precio_ars', 0))
    precio_usd = float(data.get('precio_usd', 0))

    try:
        # Verificar si ya existe un item con este código
        existing = ItemInventario.query.filter_by(
            codigo=material.codigo,
            organizacion_id=org_id
        ).first()

        if existing:
            return jsonify({
                'error': f'Ya tienes un material con código {material.codigo} en tu inventario',
                'item_id': existing.id
            }), 409

        # Buscar categoría correspondiente
        categoria = InventoryCategory.query.filter_by(
            company_id=org_id,
            nombre=material.categoria_nombre,
            is_active=True
        ).first()

        if not categoria:
            # Crear categoría si no existe
            categoria = InventoryCategory(
                company_id=org_id,
                nombre=material.categoria_nombre,
                is_active=True
            )
            db.session.add(categoria)
            db.session.flush()

        # Crear item de inventario local
        nuevo_item = ItemInventario(
            organizacion_id=org_id,
            categoria_id=categoria.id,
            codigo=material.codigo,
            nombre=material.nombre,
            descripcion=material.descripcion_completa,
            unidad=material.unidad,
            stock_actual=stock_inicial,
            stock_minimo=0,
            precio_promedio=precio_ars or material.precio_promedio_ars or 0,
            precio_promedio_usd=precio_usd or material.precio_promedio_usd or 0,
            activo=True
        )

        db.session.add(nuevo_item)
        db.session.flush()

        # Registrar uso del material global
        uso = GlobalMaterialUsage(
            material_id=material.id,
            organizacion_id=org_id,
            item_inventario_id=nuevo_item.id
        )
        db.session.add(uso)

        # Actualizar contador de usos
        material.veces_usado = (material.veces_usado or 0) + 1

        # Si hay stock inicial, crear movimiento
        if stock_inicial > 0:
            movimiento = MovimientoInventario(
                item_id=nuevo_item.id,
                tipo='entrada',
                cantidad=stock_inicial,
                precio_unitario=precio_ars,
                motivo='Inventario inicial desde catálogo global',
                observaciones=f'Material importado del catálogo global: {material.codigo}',
                usuario_id=current_user.id
            )
            db.session.add(movimiento)

        db.session.commit()

        return jsonify({
            'success': True,
            'item_id': nuevo_item.id,
            'codigo': nuevo_item.codigo,
            'mensaje': f'Material {material.nombre} agregado a tu inventario exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error usando material global: {str(e)}")
        return jsonify({'error': 'Error al agregar material a tu inventario'}), 500


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


@inventario_bp.route('/dar_baja/<int:id>', methods=['POST'])
@login_required
def dar_baja(id):
    """Da de baja un item de inventario por uso o rotura"""
    if not current_user.puede_acceder_modulo('inventario'):
        return jsonify({'success': False, 'message': 'No tienes permisos'}), 403

    try:
        item = ItemInventario.query.get_or_404(id)

        cantidad = float(request.form.get('cantidad', 0))
        motivo = request.form.get('motivo', '')
        obra_id = request.form.get('obra_id')
        observaciones = request.form.get('observaciones', '')

        if cantidad <= 0:
            return jsonify({'success': False, 'message': 'La cantidad debe ser mayor a 0'}), 400

        if cantidad > float(item.stock_actual):
            return jsonify({'success': False, 'message': 'No hay suficiente stock disponible'}), 400

        # Create movement record
        movimiento = MovimientoInventario(
            item_id=item.id,
            tipo='salida',
            cantidad=cantidad,
            motivo=motivo,
            observaciones=observaciones,
            usuario_id=current_user.id
        )
        db.session.add(movimiento)

        # Update stock
        item.stock_actual -= cantidad

        # If it's usage on an obra, record it
        if obra_id and motivo == 'Uso en obra':
            uso = UsoInventario(
                obra_id=int(obra_id),
                item_id=item.id,
                cantidad_usada=cantidad,
                fecha_uso=date.today(),
                observaciones=observaciones,
                usuario_id=current_user.id
            )
            db.session.add(uso)

        db.session.commit()
        flash(f'Se dio de baja {cantidad} {item.unidad} de {item.nombre}', 'success')
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en dar_baja: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@inventario_bp.route('/trasladar/<int:id>', methods=['POST'])
@login_required
def trasladar(id):
    """Traslada un item de inventario a otro depósito"""
    if not current_user.puede_acceder_modulo('inventario'):
        return jsonify({'success': False, 'message': 'No tienes permisos'}), 403

    try:
        item = ItemInventario.query.get_or_404(id)

        cantidad = float(request.form.get('cantidad', 0))
        obra_destino_id = request.form.get('obra_destino_id')
        observaciones = request.form.get('observaciones', '')

        if cantidad <= 0:
            return jsonify({'success': False, 'message': 'La cantidad debe ser mayor a 0'}), 400

        if not obra_destino_id:
            return jsonify({'success': False, 'message': 'Debe seleccionar un depósito destino'}), 400

        # Validación flexible de stock - permite negativo con alerta
        stock_actual = float(item.stock_actual)
        stock_insuficiente = cantidad > stock_actual
        if stock_insuficiente:
            stock_resultante = stock_actual - cantidad
            current_app.logger.warning(
                f"⚠️ Traslado con stock insuficiente para {item.nombre}. "
                f"Disponible: {stock_actual}, Trasladar: {cantidad}, "
                f"Resultante: {stock_resultante}"
            )

        # Create movement record for transfer
        movimiento = MovimientoInventario(
            item_id=item.id,
            tipo='salida',
            cantidad=cantidad,
            motivo=f'Traslado a obra',
            observaciones=observaciones,
            usuario_id=current_user.id
        )
        db.session.add(movimiento)

        # Update stock (subtract from current location)
        item.stock_actual -= cantidad

        # Record usage in destination obra
        uso = UsoInventario(
            obra_id=int(obra_destino_id),
            item_id=item.id,
            cantidad_usada=cantidad,
            fecha_uso=date.today(),
            observaciones=f'Traslado desde depósito. {observaciones}',
            usuario_id=current_user.id
        )
        db.session.add(uso)

        db.session.commit()

        obra_destino = Obra.query.get(obra_destino_id)
        flash(f'Se trasladaron {cantidad} {item.unidad} de {item.nombre} a {obra_destino.nombre}', 'success')
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en trasladar: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
