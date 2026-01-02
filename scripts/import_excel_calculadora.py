#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para importar datos de Excel al inventario y calculadora IA de OBYRA.
Lee los archivos Excel de la carpeta excel_calculadora y:
1. Crea categorías en el inventario
2. Importa artículos con precios en USD
3. Genera archivo JSON para la calculadora IA con datos por tipo de construcción
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime
from decimal import Decimal
from collections import defaultdict

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mapeo de archivos Excel a categorías principales
EXCEL_TO_CATEGORY = {
    'CARPINTERIA + METALICAS + ABERTURAS COMPLETO.xlsx': 'Carpintería y Aberturas',
    'EQUIPO CONTRA INCENDIOS + MAQUINARIA EDIFICIO COMPLETO.xlsx': 'Equipos y Maquinaria',
    'ESTRUCTURA II COMPLETO.xlsx': 'Estructura',
    'EXCAVACION Y MOVIMIENTO SUELO COMPLETO.xlsx': 'Excavación y Movimiento de Suelo',
    'FUNDACIONES COMPLETO.xlsx': 'Fundaciones',
    'HERRERIA DE OBRA COMPLETO.xlsx': 'Herrería de Obra',
    'IMPERMEABILIZACION Y AISLACION COMPLETO.xlsx': 'Impermeabilización y Aislación',
    'INSTALACIONES CLIMATIZACION COMPLETO.xlsx': 'Climatización',
    'INSTALACIONES DE GAS COMPLETO.xlsx': 'Instalaciones de Gas',
    'INSTALACIONES ELECTRICAS COMPLETO.xlsx': 'Instalaciones Eléctricas',
    'INSTALACIONES SANITARIAS COMPLETO.xlsx': 'Instalaciones Sanitarias',
    'MAMPOSTERIA Y TERMINACIONES COMPLETO.xlsx': 'Mampostería y Terminaciones',
    'PINTURAS Y REVESTIMIENTOS COMPLETO.xlsx': 'Pinturas y Revestimientos',
    'PISOS COMPLETO.xlsx': 'Pisos',
    'TECHOS COMPLETO.xlsx': 'Techos',
}

# Mapeo de unidades Excel a unidades del sistema
UNIDAD_MAPPING = {
    'M2': 'm²',
    'M3': 'm³',
    'ML': 'ml',
    'UNI': 'unidad',
    'KG': 'kg',
    'LTS': 'lts',
    'BOLSA': 'bolsa',
    'ROLLO': 'rollo',
    'BARRA': 'barra',
    'PAR': 'par',
    'JUEGO': 'juego',
    'SET': 'set',
    'CAJA': 'caja',
    'PACK': 'pack',
}


def normalizar_unidad(unidad_excel):
    """Normaliza la unidad del Excel al formato del sistema."""
    if pd.isna(unidad_excel):
        return 'unidad'
    unidad_upper = str(unidad_excel).strip().upper()
    return UNIDAD_MAPPING.get(unidad_upper, unidad_upper.lower())


def leer_excel(filepath):
    """Lee un archivo Excel y retorna un DataFrame normalizado."""
    try:
        df = pd.read_excel(filepath, sheet_name=0, header=0)

        # Normalizar nombres de columnas
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower().strip()
            if 'categor' in col_lower:
                column_mapping[col] = 'categoria'
            elif 'subcategor' in col_lower:
                column_mapping[col] = 'subcategoria'
            elif 'art' in col_lower and 'culo' in col_lower:
                column_mapping[col] = 'articulo'
            elif 'precio' in col_lower:
                column_mapping[col] = 'precio_usd'
            elif 'econ' in col_lower:
                column_mapping[col] = 'economica'
            elif 'standard' in col_lower or 'standar' in col_lower or 'estándar' in col_lower:
                column_mapping[col] = 'estandar'
            elif 'premium' in col_lower:
                column_mapping[col] = 'premium'
            elif 'unidad' in col_lower:
                column_mapping[col] = 'unidad'

        df = df.rename(columns=column_mapping)
        return df
    except Exception as e:
        print(f"Error leyendo {filepath}: {e}")
        return None


def procesar_archivos_excel(excel_dir):
    """Procesa todos los archivos Excel y retorna los datos estructurados."""
    datos_completos = {
        'categorias': {},
        'articulos': [],
        'por_tipo_construccion': {
            'Económica': defaultdict(list),
            'Estándar': defaultdict(list),
            'Premium': defaultdict(list),
        },
        'estadisticas': {
            'total_archivos': 0,
            'total_articulos': 0,
            'articulos_con_precio': 0,
            'categorias_unicas': set(),
        }
    }

    files = [f for f in os.listdir(excel_dir) if f.endswith('.xlsx')]

    for filename in files:
        if filename not in EXCEL_TO_CATEGORY:
            print(f"[!] Archivo no mapeado: {filename}")
            continue

        filepath = os.path.join(excel_dir, filename)
        categoria_principal = EXCEL_TO_CATEGORY[filename]

        print(f"\n[+] Procesando: {filename}")
        print(f"    Categoria principal: {categoria_principal}")

        df = leer_excel(filepath)
        if df is None:
            continue

        datos_completos['estadisticas']['total_archivos'] += 1

        # Inicializar categoría principal
        if categoria_principal not in datos_completos['categorias']:
            datos_completos['categorias'][categoria_principal] = {
                'subcategorias': set(),
                'total_articulos': 0,
            }

        # Helper para obtener valor de una columna de forma segura
        def get_value(row_data, col_name, default=''):
            if col_name not in row_data.index:
                return default
            val = row_data[col_name]
            # Si es una Serie (columna duplicada), tomar el primer valor
            if isinstance(val, pd.Series):
                val = val.iloc[0] if len(val) > 0 else None
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return default
            return val

        # Procesar cada fila
        for idx, row in df.iterrows():
            # Obtener valores
            categoria = str(get_value(row, 'categoria', '')).strip()
            subcategoria = str(get_value(row, 'subcategoria', '')).strip()
            articulo = str(get_value(row, 'articulo', '')).strip()

            if not articulo:
                continue

            # Precio
            precio_raw = get_value(row, 'precio_usd', None)
            precio_usd = None
            if precio_raw is not None:
                try:
                    precio_usd = float(precio_raw)
                except (ValueError, TypeError):
                    pass

            # Unidad
            unidad_val = get_value(row, 'unidad', None)
            unidad = normalizar_unidad(unidad_val)

            # Tipos de construcción
            eco_val = get_value(row, 'economica', '')
            aplica_economica = str(eco_val).strip().upper() == 'X'

            est_val = get_value(row, 'estandar', '')
            aplica_estandar = str(est_val).strip().upper() == 'X'

            pre_val = get_value(row, 'premium', '')
            aplica_premium = str(pre_val).strip().upper() == 'X'

            # Crear artículo
            articulo_data = {
                'nombre': articulo,
                'categoria_principal': categoria_principal,
                'categoria': categoria or categoria_principal,
                'subcategoria': subcategoria,
                'precio_usd': precio_usd,
                'unidad': unidad,
                'aplica_economica': aplica_economica,
                'aplica_estandar': aplica_estandar,
                'aplica_premium': aplica_premium,
                'archivo_origen': filename,
            }

            datos_completos['articulos'].append(articulo_data)
            datos_completos['estadisticas']['total_articulos'] += 1

            if precio_usd:
                datos_completos['estadisticas']['articulos_con_precio'] += 1

            # Agregar a categorías
            datos_completos['categorias'][categoria_principal]['subcategorias'].add(categoria or 'General')
            datos_completos['categorias'][categoria_principal]['total_articulos'] += 1
            datos_completos['estadisticas']['categorias_unicas'].add(categoria or categoria_principal)

            # Agregar a tipos de construcción
            cat_key = f"{categoria_principal}/{categoria}" if categoria else categoria_principal

            if aplica_economica:
                datos_completos['por_tipo_construccion']['Económica'][cat_key].append(articulo_data)
            if aplica_estandar:
                datos_completos['por_tipo_construccion']['Estándar'][cat_key].append(articulo_data)
            if aplica_premium:
                datos_completos['por_tipo_construccion']['Premium'][cat_key].append(articulo_data)

    # Convertir sets a listas para JSON
    for cat in datos_completos['categorias']:
        datos_completos['categorias'][cat]['subcategorias'] = list(datos_completos['categorias'][cat]['subcategorias'])
    datos_completos['estadisticas']['categorias_unicas'] = len(datos_completos['estadisticas']['categorias_unicas'])

    # Convertir defaultdicts a dicts normales
    for tipo in datos_completos['por_tipo_construccion']:
        datos_completos['por_tipo_construccion'][tipo] = dict(datos_completos['por_tipo_construccion'][tipo])

    return datos_completos


def generar_json_calculadora(datos, output_path):
    """Genera el archivo JSON para la calculadora IA."""

    # Estructura para la calculadora IA
    calculadora_data = {
        'version': '2.0',
        'fecha_actualizacion': datetime.now().isoformat(),
        'moneda': 'USD',
        'tipos_construccion': {
            'Económica': {
                'descripcion': 'Construcción básica con materiales estándar',
                'factor_precio': 1.0,
                'categorias': {},
            },
            'Estándar': {
                'descripcion': 'Construcción media con buenos materiales',
                'factor_precio': 1.23,
                'categorias': {},
            },
            'Premium': {
                'descripcion': 'Construcción de alta gama con materiales premium',
                'factor_precio': 1.54,
                'categorias': {},
            }
        },
        'precios_referencia': {},
        'estadisticas': datos['estadisticas'],
    }

    # Procesar por tipo de construcción
    for tipo, categorias in datos['por_tipo_construccion'].items():
        for cat_key, articulos in categorias.items():
            if cat_key not in calculadora_data['tipos_construccion'][tipo]['categorias']:
                calculadora_data['tipos_construccion'][tipo]['categorias'][cat_key] = []

            for art in articulos:
                item = {
                    'nombre': art['nombre'],
                    'precio_usd': art['precio_usd'],
                    'unidad': art['unidad'],
                    'subcategoria': art['subcategoria'],
                }
                calculadora_data['tipos_construccion'][tipo]['categorias'][cat_key].append(item)

                # Agregar a precios de referencia si tiene precio
                if art['precio_usd']:
                    # Crear código único
                    codigo = f"{cat_key[:20]}-{art['nombre'][:30]}".upper()
                    codigo = ''.join(c if c.isalnum() or c == '-' else '_' for c in codigo)
                    calculadora_data['precios_referencia'][codigo] = {
                        'precio_usd': art['precio_usd'],
                        'unidad': art['unidad'],
                        'categoria': cat_key,
                    }

    # Guardar JSON
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(calculadora_data, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] JSON de calculadora guardado en: {output_path}")
    return calculadora_data


def generar_sql_inventario(datos, output_path, org_id=1):
    """Genera SQL para importar al inventario."""

    sql_lines = [
        "-- SQL generado automáticamente para importar artículos al inventario",
        f"-- Fecha: {datetime.now().isoformat()}",
        f"-- Total artículos: {datos['estadisticas']['total_articulos']}",
        "",
        "BEGIN;",
        "",
        "-- Crear categorías principales",
    ]

    cat_id = 1000  # Empezar desde un ID alto para no colisionar
    categoria_ids = {}

    for cat_principal in datos['categorias']:
        sql_lines.append(f"""
INSERT INTO inventory_category (id, company_id, nombre, parent_id, sort_order, is_active, is_global, created_at)
VALUES ({cat_id}, {org_id}, '{cat_principal.replace("'", "''")}', NULL, {cat_id}, true, true, NOW())
ON CONFLICT (id) DO UPDATE SET nombre = EXCLUDED.nombre;
""")
        categoria_ids[cat_principal] = cat_id
        cat_id += 1

        # Subcategorías
        for subcat in datos['categorias'][cat_principal]['subcategorias']:
            sql_lines.append(f"""
INSERT INTO inventory_category (id, company_id, nombre, parent_id, sort_order, is_active, is_global, created_at)
VALUES ({cat_id}, {org_id}, '{subcat.replace("'", "''")}', {categoria_ids[cat_principal]}, {cat_id}, true, true, NOW())
ON CONFLICT (id) DO UPDATE SET nombre = EXCLUDED.nombre;
""")
            categoria_ids[f"{cat_principal}/{subcat}"] = cat_id
            cat_id += 1

    sql_lines.append("")
    sql_lines.append("-- Crear artículos")

    item_id = 10000  # Empezar desde un ID alto
    sku_counter = 1

    for art in datos['articulos']:
        if not art['precio_usd']:
            continue  # Solo importar artículos con precio

        cat_key = f"{art['categoria_principal']}/{art['categoria']}" if art['categoria'] else art['categoria_principal']
        cat_id_ref = categoria_ids.get(cat_key, categoria_ids.get(art['categoria_principal'], 1000))

        # Generar SKU único
        sku = f"IMP-{sku_counter:06d}"
        sku_counter += 1

        nombre_safe = art['nombre'].replace("'", "''")[:200]

        sql_lines.append(f"""
INSERT INTO inventory_item (id, company_id, sku, nombre, categoria_id, unidad, min_stock, descripcion, created_at, activo)
VALUES ({item_id}, {org_id}, '{sku}', '{nombre_safe}', {cat_id_ref}, '{art['unidad']}', 0,
        'Precio USD: ${art["precio_usd"]:.2f}. Importado desde Excel.', NOW(), true)
ON CONFLICT (sku) DO UPDATE SET nombre = EXCLUDED.nombre, categoria_id = EXCLUDED.categoria_id;
""")
        item_id += 1

    sql_lines.append("")
    sql_lines.append("COMMIT;")

    # Guardar SQL
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sql_lines))

    print(f"[OK] SQL de inventario guardado en: {output_path}")


def importar_a_base_datos(datos):
    """Importa directamente a la base de datos usando Flask app context."""
    try:
        from app import create_app
        from extensions import db
        from models.inventory import InventoryCategory, InventoryItem

        app = create_app()

        with app.app_context():
            org_id = 1  # Organización por defecto

            print("\n[...] Importando a base de datos...")

            # Obtener o crear categorías
            categoria_ids = {}

            for cat_principal in datos['categorias']:
                # Buscar categoría existente
                cat = InventoryCategory.query.filter_by(
                    company_id=org_id,
                    nombre=cat_principal,
                    parent_id=None
                ).first()

                if not cat:
                    cat = InventoryCategory(
                        company_id=org_id,
                        nombre=cat_principal,
                        is_global=True,
                        is_active=True
                    )
                    db.session.add(cat)
                    db.session.flush()

                categoria_ids[cat_principal] = cat.id

                # Subcategorías
                for subcat in datos['categorias'][cat_principal]['subcategorias']:
                    subcat_obj = InventoryCategory.query.filter_by(
                        company_id=org_id,
                        nombre=subcat,
                        parent_id=cat.id
                    ).first()

                    if not subcat_obj:
                        subcat_obj = InventoryCategory(
                            company_id=org_id,
                            nombre=subcat,
                            parent_id=cat.id,
                            is_global=True,
                            is_active=True
                        )
                        db.session.add(subcat_obj)
                        db.session.flush()

                    categoria_ids[f"{cat_principal}/{subcat}"] = subcat_obj.id

            db.session.commit()
            print(f"   [OK] {len(categoria_ids)} categorias creadas/actualizadas")

            # Importar artículos
            articulos_creados = 0
            sku_counter = 1

            for art in datos['articulos']:
                if not art['precio_usd']:
                    continue

                cat_key = f"{art['categoria_principal']}/{art['categoria']}" if art['categoria'] else art['categoria_principal']
                cat_id = categoria_ids.get(cat_key, categoria_ids.get(art['categoria_principal']))

                if not cat_id:
                    continue

                # Generar SKU único
                sku = f"IMP-{sku_counter:06d}"

                # Verificar si existe
                item = InventoryItem.query.filter_by(sku=sku).first()
                if not item:
                    item = InventoryItem(
                        company_id=org_id,
                        sku=sku,
                        nombre=art['nombre'][:200],
                        categoria_id=cat_id,
                        unidad=art['unidad'],
                        min_stock=0,
                        descripcion=f"Precio USD: ${art['precio_usd']:.2f}. Tipos: {'E' if art['aplica_economica'] else ''}"
                                   f"{'S' if art['aplica_estandar'] else ''}{'P' if art['aplica_premium'] else ''}",
                        activo=True
                    )
                    db.session.add(item)
                    articulos_creados += 1

                sku_counter += 1

                # Commit cada 500 artículos
                if sku_counter % 500 == 0:
                    db.session.commit()
                    print(f"   ... {sku_counter} artículos procesados")

            db.session.commit()
            print(f"   [OK] {articulos_creados} articulos nuevos creados")

            return True

    except Exception as e:
        print(f"[ERROR] Error importando a BD: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Función principal."""
    print("=" * 60)
    print("IMPORTADOR DE DATOS EXCEL - CALCULADORA IA OBYRA")
    print("=" * 60)

    # Directorio de archivos Excel
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    excel_dir = os.path.join(base_dir, 'excel_calculadora')

    if not os.path.exists(excel_dir):
        print(f"[ERROR] No se encontro el directorio: {excel_dir}")
        return

    # Procesar archivos
    print(f"\nDirectorio: {excel_dir}")
    datos = procesar_archivos_excel(excel_dir)

    # Mostrar estadísticas
    print("\n" + "=" * 60)
    print("ESTADISTICAS")
    print("=" * 60)
    print(f"Archivos procesados: {datos['estadisticas']['total_archivos']}")
    print(f"Total articulos: {datos['estadisticas']['total_articulos']}")
    print(f"Articulos con precio: {datos['estadisticas']['articulos_con_precio']}")
    print(f"Categorias unicas: {datos['estadisticas']['categorias_unicas']}")

    # Por tipo de construcción
    print("\nArticulos por tipo de construccion:")
    for tipo, cats in datos['por_tipo_construccion'].items():
        total = sum(len(arts) for arts in cats.values())
        print(f"   - {tipo}: {total} articulos")

    # Generar archivos de salida
    output_dir = os.path.join(base_dir, 'data')
    os.makedirs(output_dir, exist_ok=True)

    # JSON para calculadora IA
    json_path = os.path.join(output_dir, 'calculadora_ia_datos.json')
    generar_json_calculadora(datos, json_path)

    # SQL para inventario
    sql_path = os.path.join(output_dir, 'import_inventario.sql')
    generar_sql_inventario(datos, sql_path)

    # Preguntar si importar a BD
    print("\n" + "=" * 60)
    respuesta = input("¿Desea importar directamente a la base de datos? (s/N): ").strip().lower()
    if respuesta == 's':
        importar_a_base_datos(datos)

    print("\n[OK] Proceso completado!")
    print(f"   - JSON calculadora: {json_path}")
    print(f"   - SQL inventario: {sql_path}")


if __name__ == '__main__':
    main()
