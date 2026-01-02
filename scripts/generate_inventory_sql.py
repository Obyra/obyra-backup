"""
Genera un script SQL para importar los items del Excel al inventario.
Este script se ejecuta localmente y genera un archivo SQL para ejecutar en Docker.
"""
import json
import os
import re

def cargar_datos_json():
    """Carga los datos del archivo JSON."""
    json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'calculadora_ia_datos.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def normalizar_unidad(unidad):
    """Normaliza las unidades a formato estándar."""
    unidad_lower = unidad.lower().strip()
    mapa = {
        'unidad': 'u', 'unidades': 'u', 'u': 'u', 'un': 'u', 'und': 'u',
        'kg': 'kg', 'kilogramo': 'kg', 'kilogramos': 'kg', 'kilo': 'kg',
        'm': 'm', 'metro': 'm', 'metros': 'm', 'ml': 'm',
        'm2': 'm2', 'metro cuadrado': 'm2', 'metros cuadrados': 'm2', 'm²': 'm2',
        'm3': 'm3', 'metro cúbico': 'm3', 'metros cúbicos': 'm3', 'm³': 'm3',
        'lt': 'l', 'lts': 'l', 'litro': 'l', 'litros': 'l', 'l': 'l',
        'bolsa': 'bolsa', 'bolsas': 'bolsa',
        'rollo': 'rollo', 'rollos': 'rollo',
        'caja': 'caja', 'cajas': 'caja',
        'paquete': 'paq', 'paquetes': 'paq',
        'juego': 'juego', 'juegos': 'juego',
        'set': 'set', 'par': 'par', 'pares': 'par',
        'global': 'gl', 'gl': 'gl',
    }
    return mapa.get(unidad_lower, unidad_lower)


def escape_sql(s):
    """Escapa strings para SQL."""
    if s is None:
        return 'NULL'
    return "'" + str(s).replace("'", "''") + "'"


def generar_sku(nombre, categoria, contador):
    """Genera un SKU único."""
    palabras = re.sub(r'[^a-zA-Z0-9\s]', '', nombre).upper().split()
    prefijo = ''.join([p[:3] for p in palabras[:3]])[:9]
    cat_prefijo = re.sub(r'[^A-Z]', '', categoria.upper())[:3]
    return f"{cat_prefijo}-{prefijo}-{contador:04d}"


def main():
    print("Cargando datos del JSON...")
    datos = cargar_datos_json()

    # Recopilar todas las categorías y items únicos
    categorias = {}  # nombre -> {subcategorias: {nombre -> id}}
    items = []  # lista de (nombre, categoria, subcategoria, unidad, precio_usd)

    tipo_data = datos.get('tipos_construccion', {}).get('Económica', {})
    for cat_path, items_data in tipo_data.get('categorias', {}).items():
        partes = cat_path.split('/')
        cat_nombre = partes[0]
        subcat_nombre = partes[1] if len(partes) > 1 else None

        if cat_nombre not in categorias:
            categorias[cat_nombre] = {'subcategorias': {}}

        if subcat_nombre and subcat_nombre not in categorias[cat_nombre]['subcategorias']:
            categorias[cat_nombre]['subcategorias'][subcat_nombre] = None

        for item in items_data:
            nombre = item.get('nombre', '').strip()
            if nombre:
                items.append({
                    'nombre': nombre,
                    'categoria': cat_nombre,
                    'subcategoria': subcat_nombre,
                    'unidad': normalizar_unidad(item.get('unidad', 'unidad')),
                    'precio_usd': item.get('precio_usd')
                })

    # Eliminar duplicados de items (por nombre + categoria + subcategoria)
    items_unicos = {}
    for item in items:
        key = f"{item['nombre'].lower()}:{item['categoria']}:{item['subcategoria']}"
        if key not in items_unicos:
            items_unicos[key] = item
        elif item['precio_usd'] and not items_unicos[key]['precio_usd']:
            # Preferir el que tiene precio
            items_unicos[key] = item

    items = list(items_unicos.values())
    print(f"Total categorías: {len(categorias)}")
    print(f"Total items únicos: {len(items)}")

    # Generar SQL
    output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'import_inventory.sql')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("-- Script generado automáticamente para importar inventario desde Excel\n")
        f.write("-- Fecha: " + str(os.popen('date /t').read().strip()) + "\n\n")

        f.write("BEGIN;\n\n")

        # Obtener org_id (asumimos 1, se puede cambiar)
        f.write("-- Usando company_id = 1 (primera organización)\n\n")

        # Crear categorías principales
        f.write("-- === CATEGORÍAS PRINCIPALES ===\n")
        cat_id = 100  # Empezamos desde 100 para evitar colisiones
        for cat_nombre in sorted(categorias.keys()):
            f.write(f"INSERT INTO inventory_category (id, company_id, nombre, parent_id, sort_order, is_active, is_global, created_at)\n")
            f.write(f"SELECT {cat_id}, 1, {escape_sql(cat_nombre)}, NULL, 0, true, true, NOW()\n")
            f.write(f"WHERE NOT EXISTS (SELECT 1 FROM inventory_category WHERE company_id = 1 AND nombre = {escape_sql(cat_nombre)} AND parent_id IS NULL);\n\n")
            categorias[cat_nombre]['id'] = cat_id
            cat_id += 1

        # Crear subcategorías
        f.write("\n-- === SUBCATEGORÍAS ===\n")
        for cat_nombre, cat_data in sorted(categorias.items()):
            parent_id = cat_data['id']
            for subcat_nombre in sorted(cat_data['subcategorias'].keys()):
                if subcat_nombre:
                    f.write(f"INSERT INTO inventory_category (id, company_id, nombre, parent_id, sort_order, is_active, is_global, created_at)\n")
                    f.write(f"SELECT {cat_id}, 1, {escape_sql(subcat_nombre)}, ")
                    f.write(f"(SELECT id FROM inventory_category WHERE company_id = 1 AND nombre = {escape_sql(cat_nombre)} AND parent_id IS NULL LIMIT 1), ")
                    f.write(f"0, true, true, NOW()\n")
                    f.write(f"WHERE NOT EXISTS (SELECT 1 FROM inventory_category ic ")
                    f.write(f"JOIN inventory_category pc ON ic.parent_id = pc.id ")
                    f.write(f"WHERE ic.company_id = 1 AND ic.nombre = {escape_sql(subcat_nombre)} AND pc.nombre = {escape_sql(cat_nombre)});\n\n")
                    cat_data['subcategorias'][subcat_nombre] = cat_id
                    cat_id += 1

        # Crear items
        f.write("\n-- === ITEMS DE INVENTARIO ===\n")
        contador_sku = 1
        for item in items:
            nombre = item['nombre']
            cat_nombre = item['categoria']
            subcat_nombre = item['subcategoria']
            unidad = item['unidad']
            precio_usd = item['precio_usd']

            sku = generar_sku(nombre, cat_nombre, contador_sku)
            descripcion = f"Precio ref USD: ${precio_usd}" if precio_usd else None

            # Determinar categoria_id usando subquery
            if subcat_nombre:
                cat_select = f"(SELECT ic.id FROM inventory_category ic JOIN inventory_category pc ON ic.parent_id = pc.id WHERE ic.company_id = 1 AND ic.nombre = {escape_sql(subcat_nombre)} AND pc.nombre = {escape_sql(cat_nombre)} LIMIT 1)"
            else:
                cat_select = f"(SELECT id FROM inventory_category WHERE company_id = 1 AND nombre = {escape_sql(cat_nombre)} AND parent_id IS NULL LIMIT 1)"

            f.write(f"INSERT INTO inventory_item (company_id, sku, nombre, categoria_id, unidad, descripcion, activo, min_stock, created_at)\n")
            f.write(f"SELECT 1, {escape_sql(sku)}, {escape_sql(nombre)}, {cat_select}, {escape_sql(unidad)}, {escape_sql(descripcion)}, true, 0, NOW()\n")
            f.write(f"WHERE NOT EXISTS (SELECT 1 FROM inventory_item WHERE sku = {escape_sql(sku)});\n\n")

            contador_sku += 1

        f.write("\nCOMMIT;\n")

    print(f"\nArchivo SQL generado: {output_path}")
    print(f"Total líneas SQL generadas para {len(items)} items")


if __name__ == '__main__':
    main()
