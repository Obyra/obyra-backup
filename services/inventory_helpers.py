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

# Nombre de la categoría default para items auto-creados desde OC/Remito
# cuando no se puede detectar una categoría lógica por keywords.
# Los ítems del árbol de inventario se agrupan por categoría; sin esto
# quedaban con categoria_id=NULL e invisibles en la vista principal.
CATEGORIA_AUTO_NOMBRE = 'Ingresos automáticos'

# Mapeo de keywords → nombre de categoría/etapa del árbol de inventario.
# Se busca cada keyword en la descripción normalizada del item auto-creado;
# el primer match decide la categoría. Orden importa: lo más específico va
# primero para evitar falsos positivos (ej: "revoque fino" antes que "revoque").
KEYWORDS_CATEGORIA = [
    # Yesería y Enlucidos
    (['yeso', 'yeseria', 'enlucido', 'enduido', 'guardavivos', 'cantonera'], 'Yesería y Enlucidos'),
    # Revoque (fino antes que grueso por especificidad)
    (['revoque fino', 'enlucido de cal', 'fratas'], 'Revoque Fino'),
    (['revoque', 'jaharro', 'hidrofugo', 'cal hidraulica'], 'Revoque Grueso'),
    # Cielorrasos
    (['cielorraso', 'placa roca', 'durlock', 'suspension'], 'Cielorrasos'),
    # Pisos y Revestimientos
    (['ceramico', 'porcellanato', 'zocalo', 'pastina', 'adhesivo cementicio',
      'baldoson', 'cemento alisado', 'piso vinilico', 'deck'], 'Pisos y Revestimientos'),
    # Pintura
    (['pintura', 'latex', 'barniz', 'esmalte', 'rodillo', 'pincel', 'sellador'], 'Pintura'),
    # Carpintería y Aberturas
    (['puerta', 'ventana', 'marco', 'bisagra', 'cerradura', 'herraje',
      'ventanal', 'mosquitero', 'cristal', 'vidrio'], 'Carpintería y Aberturas'),
    # Herrería de Obra
    (['perfil estructural', 'chapa hierro', 'baranda', 'escalera metalica',
      'hierro redondo', 'caño estructural'], 'Herrería de Obra'),
    # Instalaciones eléctricas
    (['cable', 'conductor', 'tomacorriente', 'interruptor', 'llave termica',
      'disyuntor', 'caño corrugado', 'bandeja portacables', 'tablero electrico',
      'luminaria', 'lampara'], 'Instalaciones Eléctricas'),
    # Instalaciones sanitarias / gas
    (['caño gas', 'regulador gas', 'medidor gas'], 'Instalaciones de Gas'),
    (['caño ppr', 'caño pvc sanitario', 'canilla', 'griferia', 'inodoro',
      'bidet', 'lavatorio', 'bacha', 'flexible', 'sifon'], 'Instalaciones Sanitarias y Provisiones'),
    # Construcción en seco
    (['placa yeso', 'montante', 'solera', 'cinta papel', 'tornillo t1', 'tornillo t2'], 'Construcción en Seco'),
    # Techos y Cubiertas
    (['teja', 'membrana', 'chapa techo', 'aislacion termica', 'lana vidrio',
      'canaleta', 'babeta'], 'Techos y Cubiertas'),
    # Mampostería
    (['ladrillo', 'bloque hormigon', 'bloque ceramico', 'mortero de asiento'], 'Mampostería'),
    # Contrapisos y Carpetas
    (['contrapiso', 'carpeta', 'polietileno', 'malla sima'], 'Contrapisos y Carpetas'),
    # Impermeabilizaciones
    (['asfaltico', 'pintura impermeable', 'emulsion asfaltica'], 'Impermeabilizaciones y Aislaciones'),
    # Estructura / Fundaciones
    (['cemento portland', 'hierro', 'hormigon elaborado', 'estribos'], 'Estructura'),
    (['zapata', 'plateas', 'pilote'], 'Fundaciones'),
    # Excavación / Movimiento de suelos
    (['arena', 'piedra partida', 'tierra'], 'Movimiento de Suelos'),
]


def detectar_categoria_por_descripcion(descripcion, org_id):
    """Intenta matchear la descripción de un item a una categoría existente
    de la organización usando keywords conocidos.

    Returns:
        int|None: ID de la categoría si hay match; None si no.
    """
    from models.inventory import InventoryCategory

    desc_norm = normalize_name(descripcion)
    if not desc_norm:
        return None

    # Iterar en orden (más específico primero) y quedarse con el primer match.
    for keywords, nombre_categoria in KEYWORDS_CATEGORIA:
        for kw in keywords:
            if kw in desc_norm:
                cat = InventoryCategory.query.filter_by(
                    company_id=org_id,
                    nombre=nombre_categoria,
                    is_active=True,
                ).first()
                if cat:
                    return cat.id
                # Si la keyword matcheó pero la categoría no existe en esta
                # org, seguimos buscando otras keywords (puede haber sinónimo).
                break

    return None


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
    # Asignación de categoría en 2 niveles:
    #   a) Detectar categoría lógica por keywords en la descripción
    #      (ej: "Yeso París" → "Yesería y Enlucidos"). Así el item queda
    #      directamente en la etapa correcta, sin necesidad de mover
    #      manualmente desde "Otros".
    #   b) Si no matchea ninguna keyword, caer en "Ingresos automáticos"
    #      como último recurso (mejor que quedar sin categoría).
    codigo = _generate_codigo_auto(org_id)
    categoria_id = detectar_categoria_por_descripcion(nombre_original, org_id)
    if not categoria_id:
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
