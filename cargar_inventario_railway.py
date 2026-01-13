import pandas as pd
import psycopg2
import os
from glob import glob
import time

DB_URL = 'postgresql://postgres:HehxgOpoiSobZuebpKmMvXMrfrCEVOHu@caboose.proxy.rlwy.net:13123/railway'

def get_connection():
    return psycopg2.connect(DB_URL)

print("Conectando a Railway...")
conn = get_connection()
cur = conn.cursor()

# Obtener org_id
cur.execute('SELECT id FROM organizaciones LIMIT 1')
org_id = cur.fetchone()[0]
company_id = org_id
print(f'Org/Company ID: {org_id}')

# Obtener categorías ya existentes
cur.execute('SELECT id, nombre FROM inventory_category')
categorias_existentes = {row[1]: row[0] for row in cur.fetchall()}
print(f"Categorías ya existentes: {len(categorias_existentes)}")
for nombre in categorias_existentes.keys():
    print(f"  - {nombre}")

# Obtener último código de item
cur.execute("SELECT codigo FROM items_inventario ORDER BY id DESC LIMIT 1")
ultimo = cur.fetchone()
if ultimo:
    item_counter = int(ultimo[0].replace('INV-', '')) + 1
else:
    item_counter = 1
print(f"Continuando desde item: INV-{item_counter:05d}")

conn.close()

path = 'excel_calculadora/YA CARGADO/'
archivos = glob(path + '*.xlsx')
print(f"\nArchivos encontrados: {len(archivos)}")

categorias_creadas = dict(categorias_existentes)
items_creados = 0
sort_order = len(categorias_existentes) + 1

for archivo in sorted(archivos):
    nombre_archivo = os.path.basename(archivo).replace('.xlsx', '').replace(' COMPLETO', '').strip()

    # Saltar categorías ya procesadas
    if nombre_archivo in categorias_existentes:
        print(f'Saltando (ya existe): {nombre_archivo}')
        continue

    print(f'\nProcesando: {nombre_archivo}')

    try:
        conn = get_connection()
        cur = conn.cursor()

        df = pd.read_excel(archivo)
        df.columns = [c.strip() for c in df.columns]

        col_articulo = None
        col_precio = None
        col_unidad = None

        for col in df.columns:
            col_lower = col.lower()
            if 'art' in col_lower:
                col_articulo = col
            elif 'precio' in col_lower and 'ref' in col_lower:
                col_precio = col
            elif 'unidad' in col_lower:
                col_unidad = col

        # Crear categoría
        cur.execute('''
            INSERT INTO inventory_category (company_id, nombre, sort_order, is_active, is_global)
            VALUES (%s, %s, %s, true, false) RETURNING id
        ''', (company_id, nombre_archivo, sort_order))
        cat_id = cur.fetchone()[0]
        conn.commit()
        categorias_creadas[nombre_archivo] = cat_id
        sort_order += 1
        print(f'  Categoría creada: ID {cat_id}')

        items_archivo = 0
        for idx, row in df.iterrows():
            nombre_item = str(row.get(col_articulo, '')) if col_articulo else ''
            if pd.isna(nombre_item) or nombre_item == 'nan' or not nombre_item.strip():
                continue

            nombre_item = nombre_item.strip()[:200]

            precio = row.get(col_precio, 0) if col_precio else 0
            if pd.isna(precio):
                precio = 0

            unidad = str(row.get(col_unidad, 'UN')) if col_unidad else 'UN'
            if pd.isna(unidad) or unidad == 'nan':
                unidad = 'UN'
            unidad = unidad.strip()[:20]

            codigo = f'INV-{item_counter:05d}'
            item_counter += 1

            cur.execute('''
                INSERT INTO items_inventario
                (categoria_id, codigo, nombre, unidad, precio_promedio_usd, stock_actual, stock_minimo, activo, organizacion_id)
                VALUES (%s, %s, %s, %s, %s, 0, 0, true, %s)
            ''', (cat_id, codigo, nombre_item, unidad, float(precio) if precio else 0, org_id))
            items_archivo += 1

            # Commit cada 20 items
            if items_archivo % 20 == 0:
                conn.commit()

        conn.commit()
        items_creados += items_archivo
        print(f'  Items: {items_archivo}')

        conn.close()
        time.sleep(1)

    except Exception as e:
        print(f'  Error: {e}')
        try:
            conn.close()
        except:
            pass
        time.sleep(2)

print(f'\n=== RESUMEN ===')
print(f'Categorias totales: {len(categorias_creadas)}')
print(f'Items nuevos: {items_creados}')
print("Completado!")
