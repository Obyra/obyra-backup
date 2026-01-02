"""
Script para importar los datos del Excel (ya procesados en JSON) al inventario de la base de datos.
Importa items a la tabla InventoryItem y categorías a InventoryCategory.
"""
import json
import os
import sys
from decimal import Decimal

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from models.inventory import InventoryCategory, InventoryItem


def cargar_datos_json():
    """Carga los datos del archivo JSON generado desde los Excel."""
    json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'calculadora_ia_datos.json')

    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def obtener_o_crear_categoria(org_id, nombre_categoria, parent=None, categorias_cache=None):
    """
    Obtiene o crea una categoría de inventario.
    Usa cache para evitar queries repetidas.
    """
    if categorias_cache is None:
        categorias_cache = {}

    # Crear key para el cache
    cache_key = f"{org_id}:{nombre_categoria}:{parent.id if parent else 'root'}"

    if cache_key in categorias_cache:
        return categorias_cache[cache_key]

    # Buscar categoría existente
    query = InventoryCategory.query.filter_by(
        company_id=org_id,
        nombre=nombre_categoria,
        parent_id=parent.id if parent else None
    )

    categoria = query.first()

    if not categoria:
        categoria = InventoryCategory(
            company_id=org_id,
            nombre=nombre_categoria,
            parent_id=parent.id if parent else None,
            is_active=True,
            is_global=True,  # Marcamos como global para que esté disponible para todas las orgs
            sort_order=0
        )
        db.session.add(categoria)
        db.session.flush()  # Para obtener el ID
        print(f"  + Categoría creada: {nombre_categoria}")

    categorias_cache[cache_key] = categoria
    return categoria


def generar_sku(nombre, categoria, contador):
    """Genera un SKU único basado en nombre y categoría."""
    # Limpiar nombre para SKU
    import re

    # Tomar primeras palabras significativas
    palabras = re.sub(r'[^a-zA-Z0-9\s]', '', nombre).upper().split()
    prefijo = ''.join([p[:3] for p in palabras[:3]])[:9]  # Max 9 caracteres

    # Prefijo de categoría
    cat_prefijo = re.sub(r'[^A-Z]', '', categoria.upper())[:3]

    return f"{cat_prefijo}-{prefijo}-{contador:04d}"


def importar_items(org_id, datos, tipo_construccion='Económica'):
    """
    Importa los items de un tipo de construcción específico al inventario.
    Solo usa el tipo Económica ya que todos tienen los mismos items base.
    """
    categorias_cache = {}
    items_creados = 0
    items_actualizados = 0
    items_omitidos = 0
    contador_sku = 1

    tipo_data = datos.get('tipos_construccion', {}).get(tipo_construccion, {})
    categorias = tipo_data.get('categorias', {})

    print(f"\nProcesando {len(categorias)} categorías...")

    # Conjunto para rastrear items ya procesados (evitar duplicados)
    items_procesados = set()

    for cat_path, items in categorias.items():
        # cat_path tiene formato "Categoria/Subcategoria"
        partes = cat_path.split('/')
        categoria_nombre = partes[0]
        subcategoria_nombre = partes[1] if len(partes) > 1 else None

        # Crear/obtener categoría principal
        categoria_principal = obtener_o_crear_categoria(
            org_id, categoria_nombre, parent=None, categorias_cache=categorias_cache
        )

        # Crear/obtener subcategoría si existe
        categoria_final = categoria_principal
        if subcategoria_nombre:
            categoria_final = obtener_o_crear_categoria(
                org_id, subcategoria_nombre, parent=categoria_principal, categorias_cache=categorias_cache
            )

        # Procesar items
        for item_data in items:
            nombre = item_data.get('nombre', '').strip()
            if not nombre:
                continue

            # Crear key única para evitar duplicados
            item_key = f"{nombre.lower()}:{categoria_final.id}"
            if item_key in items_procesados:
                items_omitidos += 1
                continue
            items_procesados.add(item_key)

            precio_usd = item_data.get('precio_usd')
            unidad = item_data.get('unidad', 'unidad')

            # Normalizar unidad
            unidad_normalizada = normalizar_unidad(unidad)

            # Verificar si ya existe el item (por nombre y categoría)
            item_existente = InventoryItem.query.filter_by(
                company_id=org_id,
                nombre=nombre,
                categoria_id=categoria_final.id
            ).first()

            if item_existente:
                # Actualizar precio si es diferente
                if precio_usd and item_existente.descripcion != f"Precio USD: ${precio_usd}":
                    item_existente.descripcion = f"Precio USD: ${precio_usd}" if precio_usd else None
                    items_actualizados += 1
                else:
                    items_omitidos += 1
                continue

            # Generar SKU único
            sku = generar_sku(nombre, categoria_nombre, contador_sku)

            # Verificar que el SKU sea único
            while InventoryItem.query.filter_by(sku=sku).first():
                contador_sku += 1
                sku = generar_sku(nombre, categoria_nombre, contador_sku)

            # Crear nuevo item
            nuevo_item = InventoryItem(
                company_id=org_id,
                sku=sku,
                nombre=nombre,
                categoria_id=categoria_final.id,
                unidad=unidad_normalizada,
                descripcion=f"Precio referencia USD: ${precio_usd}" if precio_usd else None,
                activo=True,
                min_stock=0
            )

            db.session.add(nuevo_item)
            items_creados += 1
            contador_sku += 1

            # Commit periódico para no sobrecargar memoria
            if items_creados % 500 == 0:
                db.session.commit()
                print(f"  ... {items_creados} items creados")

    # Commit final
    db.session.commit()

    return items_creados, items_actualizados, items_omitidos


def normalizar_unidad(unidad):
    """Normaliza las unidades a formato estándar."""
    unidad_lower = unidad.lower().strip()

    # Mapa de normalización
    mapa = {
        'unidad': 'u',
        'unidades': 'u',
        'u': 'u',
        'un': 'u',
        'und': 'u',
        'kg': 'kg',
        'kilogramo': 'kg',
        'kilogramos': 'kg',
        'kilo': 'kg',
        'm': 'm',
        'metro': 'm',
        'metros': 'm',
        'ml': 'm',
        'm2': 'm2',
        'metro cuadrado': 'm2',
        'metros cuadrados': 'm2',
        'm²': 'm2',
        'm3': 'm3',
        'metro cúbico': 'm3',
        'metros cúbicos': 'm3',
        'm³': 'm3',
        'lt': 'l',
        'lts': 'l',
        'litro': 'l',
        'litros': 'l',
        'l': 'l',
        'bolsa': 'bolsa',
        'bolsas': 'bolsa',
        'rollo': 'rollo',
        'rollos': 'rollo',
        'caja': 'caja',
        'cajas': 'caja',
        'paquete': 'paq',
        'paquetes': 'paq',
        'juego': 'juego',
        'juegos': 'juego',
        'set': 'set',
        'par': 'par',
        'pares': 'par',
        'global': 'gl',
        'gl': 'gl',
    }

    return mapa.get(unidad_lower, unidad_lower)


def main():
    """Función principal de importación."""
    print("=" * 60)
    print("IMPORTACIÓN DE EXCEL A INVENTARIO")
    print("=" * 60)

    with app.app_context():
        # Cargar datos JSON
        print("\n1. Cargando datos del JSON...")
        datos = cargar_datos_json()
        print(f"   Versión: {datos.get('version')}")
        print(f"   Fecha: {datos.get('fecha_actualizacion')}")

        # Obtener organización ID 1 (o la primera disponible)
        from models import Organizacion
        org = Organizacion.query.first()

        if not org:
            print("\n❌ ERROR: No hay organizaciones en la base de datos.")
            print("   Crea una organización primero.")
            return

        print(f"\n2. Usando organización: {org.name} (ID: {org.id})")

        # Contar items antes
        items_antes = InventoryItem.query.filter_by(company_id=org.id).count()
        categorias_antes = InventoryCategory.query.filter_by(company_id=org.id).count()
        print(f"   Items actuales: {items_antes}")
        print(f"   Categorías actuales: {categorias_antes}")

        # Importar items
        print("\n3. Importando items...")
        creados, actualizados, omitidos = importar_items(org.id, datos)

        # Contar items después
        items_despues = InventoryItem.query.filter_by(company_id=org.id).count()
        categorias_despues = InventoryCategory.query.filter_by(company_id=org.id).count()

        print("\n" + "=" * 60)
        print("RESUMEN DE IMPORTACIÓN")
        print("=" * 60)
        print(f"Items creados:      {creados}")
        print(f"Items actualizados: {actualizados}")
        print(f"Items omitidos:     {omitidos}")
        print(f"")
        print(f"Total items ahora:      {items_despues}")
        print(f"Total categorías ahora: {categorias_despues}")
        print("=" * 60)
        print("✅ Importación completada exitosamente!")


if __name__ == '__main__':
    main()
