"""Helpers para resolución y auto-creación de ItemInventario.

Usado por el flujo:
    Requerimiento -> OC -> Remito -> StockObra -> Consumo -> Costo real

Asegura que cada línea de OC y cada RemitoItem tenga un ItemInventario
vinculado, creándolo automáticamente si no existe.
"""
import re
import unicodedata
from sqlalchemy import func

from extensions import db

# Nombre de la categoría default para items auto-creados desde OC/Remito.
# Los ítems del árbol de inventario se agrupan por categoría; sin esto
# quedaban con categoria_id=NULL e invisibles en la vista principal.
CATEGORIA_AUTO_NOMBRE = 'Ingresos automáticos'


def normalize_name(s):
    """Normaliza un nombre para comparación: lowercase, sin acentos, sin signos,
    espacios colapsados. Preserva números y palabras completas.

    'Cemento Portland 50kg' -> 'cemento portland 50kg'
    'CEMENTO  Pórtland 50Kg' -> 'cemento portland 50kg'
    """
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = s.lower()
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def find_or_create_item_inventario(descripcion, unidad, precio_unitario, org_id):
    """Busca un ItemInventario por nombre normalizado; si no existe, lo crea.

    Matching conservador: solo exact-match sobre nombre normalizado dentro
    de la misma organización. Esto evita mergear productos distintos
    (ej: "Clavo 2 pulg" vs "Clavo 3 pulg").

    Para prevenir duplicados por variantes ligeras ("Cemento 50kg" vs
    "Cemento x 50kg") se debe usar el endpoint de búsqueda desde el
    frontend como autocomplete al escribir la descripción.

    Args:
        descripcion: Nombre/descripción del artículo
        unidad: Unidad de medida (ej: 'u', 'kg', 'm')
        precio_unitario: Precio unitario en ARS
        org_id: ID de la organización

    Returns:
        int: ID del ItemInventario (existente o recién creado)
        None: si descripcion está vacía
    """
    from models.inventory import ItemInventario

    if not descripcion or not descripcion.strip():
        return None

    nombre_original = descripcion.strip()
    nombre_norm = normalize_name(nombre_original)

    # 1. Buscar existente por nombre normalizado
    candidatos = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo.is_(True),
    ).all()

    for item in candidatos:
        if normalize_name(item.nombre) == nombre_norm:
            # Backfill de precio si el existente no tiene
            if precio_unitario and float(precio_unitario) > 0:
                if not item.precio_promedio or float(item.precio_promedio) == 0:
                    item.precio_promedio = float(precio_unitario)
            return item.id

    # 2. No existe: crear nuevo con código autogenerado.
    # Asignamos categoría "Ingresos automáticos" para que el item aparezca
    # en el árbol del inventario (los items sin categoría quedan invisibles
    # en la vista principal y solo se encuentran por búsqueda textual).
    codigo = _generate_codigo_auto(org_id)
    categoria_id = _ensure_categoria_auto(org_id)

    nuevo = ItemInventario(
        codigo=codigo,
        nombre=nombre_original,
        descripcion='Creado automáticamente desde OC/Remito',
        unidad=unidad or 'u',
        stock_actual=0,
        stock_minimo=0,
        precio_promedio=float(precio_unitario) if precio_unitario else 0,
        activo=True,
        organizacion_id=org_id,
        categoria_id=categoria_id,
    )
    db.session.add(nuevo)
    db.session.flush()
    return nuevo.id


def _ensure_categoria_auto(org_id):
    """Obtiene (o crea lazy) la categoría default para items auto-creados.

    La categoría se crea bajo demanda la primera vez que una organización
    auto-crea un item desde OC/Remito. El usuario puede mover los items
    a la categoría correcta después desde el detalle del item.

    Returns:
        int: ID de la categoría 'Ingresos automáticos' de esa org.
    """
    from models.inventory import InventoryCategory

    cat = InventoryCategory.query.filter_by(
        company_id=org_id,
        nombre=CATEGORIA_AUTO_NOMBRE,
        is_active=True,
    ).first()

    if cat:
        return cat.id

    cat = InventoryCategory(
        company_id=org_id,
        nombre=CATEGORIA_AUTO_NOMBRE,
        sort_order=999,  # Al final del árbol
        is_active=True,
        is_global=False,
    )
    db.session.add(cat)
    db.session.flush()
    return cat.id


def _generate_codigo_auto(org_id, prefijo='AUTO-'):
    """Genera un código único tipo AUTO-0001 para la organización."""
    from models.inventory import ItemInventario

    ultimo = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.codigo.like(f'{prefijo}%'),
    ).order_by(ItemInventario.codigo.desc()).first()

    siguiente = 1
    if ultimo and ultimo.codigo:
        match = re.search(r'(\d+)$', ultimo.codigo)
        if match:
            siguiente = int(match.group(1)) + 1

    codigo = f"{prefijo}{siguiente:04d}"
    while ItemInventario.query.filter_by(codigo=codigo, organizacion_id=org_id).first():
        siguiente += 1
        codigo = f"{prefijo}{siguiente:04d}"

    return codigo


def buscar_items_inventario(query_text, org_id, limit=20):
    """Busca ItemInventario por substring en nombre o código.

    Usado por el autocomplete del frontend al tipear en descripción de
    requerimiento/OC/remito. Previene duplicados mostrando candidatos
    existentes antes de que el usuario cree uno nuevo.
    """
    from models.inventory import ItemInventario

    q = (query_text or '').strip()
    if len(q) < 2:
        return []

    like = f'%{q}%'
    items = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo.is_(True),
        db.or_(
            ItemInventario.nombre.ilike(like),
            ItemInventario.codigo.ilike(like),
        )
    ).order_by(ItemInventario.nombre).limit(limit).all()

    return items
