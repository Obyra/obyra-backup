import pandas as pd
import psycopg2
import os
from glob import glob
import time

DB_URL = 'postgresql://postgres:HehxgOpoiSobZuebpKmMvXMrfrCEVOHu@caboose.proxy.rlwy.net:13123/railway'

# Mapeo de nombre de archivo a nombre de categoría correcto
NOMBRE_CATEGORIAS = {
    'CARPINTERIA + METALICAS + ABERTURAS COMPLETO': 'CARPINTERIA + METALICAS + ABERTURAS',
    'EQUIPO CONTRA INCENDIOS + MAQUINARIA EDIFICIO COMPLETO': 'EQUIPO CONTRA INCENDIOS + MAQUINARIA EDIFICIO',
    'ESTRUCTURA II COMPLETO': 'ESTRUCTURA',
    'EXCAVACION Y MOVIMIENTO SUELO COMPLETO': 'EXCAVACION Y MOVIMIENTO SUELO',
    'FUNDACIONES COMPLETO': 'FUNDACIONES',
    'HERRERIA DE OBRA COMPLETO': 'HERRERIA DE OBRA',
    'IMPERMEABILIZACION Y AISLACION COMPLETO': 'IMPERMEABILIZACION Y AISLACION',
    'INSTALACIONES CLIMATIZACION COMPLETO': 'INSTALACIONES CLIMATIZACION',
    'INSTALACIONES DE GAS COMPLETO': 'INSTALACIONES DE GAS',
    'INSTALACIONES ELECTRICAS COMPLETO': 'INSTALACIONES ELECTRICAS',
    'INSTALACIONES SANITARIAS COMPLETO': 'INSTALACIONES SANITARIAS',
    'LIMPIEZA FINAL': 'LIMPIEZA FINAL',
    'MAMPOSTERIA': 'MAMPOSTERIA',
    'PINTURAS Y REVESTIMIENTOS COMPLETO': 'PINTURAS Y REVESTIMIENTOS',
    'PISOS COMPLETO': 'PISOS',
    'REVOQUE FINO': 'REVOQUE FINO/YESERIA',
    'REVOQUE GRUESO': 'REVOQUE GRUESO',
    'TECHOS COMPLETO': 'TECHOS',
}

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
conn.close()

path = 'excel_calculadora/YA CARGADO/'
archivos = glob(path + '*.xlsx')
print(f"\nArchivos encontrados: {len(archivos)}")

item_counter = 1
sort_order = 1
total_items_creados = 0

for archivo in sorted(archivos):
    nombre_archivo = os.path.basename(archivo).replace('.xlsx', '').strip()

    # Saltar archivos temporales
    if nombre_archivo.startswith('~'):
        continue

    # Obtener nombre de categoría correcto
    nombre_categoria = NOMBRE_CATEGORIAS.get(nombre_archivo, nombre_archivo)

    print(f'\nProcesando: {nombre_archivo}')
    print(f'  -> Categoría: {nombre_categoria}')

    try:
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

        print(f'  Columnas: articulo={col_articulo}, precio={col_precio}, unidad={col_unidad}')
        print(f'  Filas en Excel: {len(df)}')

        # Crear conexión fresca para cada archivo
        conn = get_connection()
        cur = conn.cursor()

        # Crear categoría
        cur.execute('''
            INSERT INTO inventory_category (company_id, nombre, sort_order, is_active, is_global)
            VALUES (%s, %s, %s, true, false) RETURNING id
        ''', (company_id, nombre_categoria, sort_order))
        cat_id = cur.fetchone()[0]
        conn.commit()
        sort_order += 1
        print(f'  Categoría creada: ID {cat_id}')

        items_archivo = 0
        batch_items = []

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

            batch_items.append((cat_id, codigo, nombre_item, unidad, float(precio) if precio else 0, org_id))
            items_archivo += 1

            # Insertar en batches de 50
            if len(batch_items) >= 50:
                try:
                    cur.executemany('''
                        INSERT INTO items_inventario
                        (categoria_id, codigo, nombre, unidad, precio_promedio_usd, stock_actual, stock_minimo, activo, organizacion_id)
                        VALUES (%s, %s, %s, %s, %s, 0, 0, true, %s)
                    ''', batch_items)
                    conn.commit()
                    batch_items = []
                except Exception as e:
                    print(f'  Error en batch, reconectando: {e}')
                    conn.close()
                    time.sleep(2)
                    conn = get_connection()
                    cur = conn.cursor()
                    # Reintentar
                    cur.executemany('''
                        INSERT INTO items_inventario
                        (categoria_id, codigo, nombre, unidad, precio_promedio_usd, stock_actual, stock_minimo, activo, organizacion_id)
                        VALUES (%s, %s, %s, %s, %s, 0, 0, true, %s)
                    ''', batch_items)
                    conn.commit()
                    batch_items = []

        # Insertar items restantes
        if batch_items:
            cur.executemany('''
                INSERT INTO items_inventario
                (categoria_id, codigo, nombre, unidad, precio_promedio_usd, stock_actual, stock_minimo, activo, organizacion_id)
                VALUES (%s, %s, %s, %s, %s, 0, 0, true, %s)
            ''', batch_items)
            conn.commit()

        total_items_creados += items_archivo
        print(f'  Items creados: {items_archivo}')

        conn.close()
        time.sleep(1)  # Pausa entre archivos

    except Exception as e:
        print(f'  ERROR: {e}')
        try:
            conn.close()
        except:
            pass
        time.sleep(3)

print(f'\n=== RESUMEN ===')
print(f'Categorías creadas: {sort_order - 1}')
print(f'Items totales: {total_items_creados}')
print("Completado!")
