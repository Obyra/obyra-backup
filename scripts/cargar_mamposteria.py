"""
Script para cargar artículos de MAMPOSTERIA Y TERMINACIONES COMPLETO.xlsx
"""
import pandas as pd
import sys
import os

# Agregar path de la app
sys.path.insert(0, '/app')

def cargar_articulos():
    from app import app
    with app.app_context():
        from models import ItemInventario, InventoryCategory
        from extensions import db
        
        ORG_ID = 2  # Organización destino
        
        # Leer Excel
        df = pd.read_excel('/app/CALCULADORA IA-NEGRO/MAMPOSTERIA Y TERMINACIONES COMPLETO.xlsx', engine='openpyxl')
        
        # Limpiar nombres de columnas
        df.columns = ['categoria', 'subcategoria', 'articulo', 'precio_usd', 'economica', 'standard', 'premium', 'unidad']
        
        print(f"Total de artículos a cargar: {len(df)}")
        
        # Obtener último código
        ultimo = ItemInventario.query.filter_by(organizacion_id=ORG_ID).order_by(ItemInventario.codigo.desc()).first()
        if ultimo and ultimo.codigo:
            import re
            match = re.search(r'(\d+)$', ultimo.codigo)
            ultimo_num = int(match.group(1)) if match else 11480
        else:
            ultimo_num = 11480
        
        print(f"Último código: {ultimo_num}")
        
        # Cache de categorías
        categorias_cache = {}
        
        creados = 0
        existentes = 0
        
        for idx, row in df.iterrows():
            nombre = str(row['articulo']).strip() if pd.notna(row['articulo']) else ''
            if not nombre:
                continue
            
            # Verificar si ya existe
            existe = ItemInventario.query.filter_by(
                organizacion_id=ORG_ID,
                nombre=nombre
            ).first()
            
            if existe:
                existentes += 1
                continue
            
            # Obtener o crear categoría
            cat_nombre = str(row['categoria']).strip() if pd.notna(row['categoria']) else 'Sin categoría'
            
            if cat_nombre not in categorias_cache:
                cat = InventoryCategory.query.filter_by(
                    company_id=ORG_ID,
                    nombre=cat_nombre
                ).first()
                
                if not cat:
                    cat = InventoryCategory(
                        company_id=ORG_ID,
                        nombre=cat_nombre,
                        descripcion=f'Categoría: {cat_nombre}',
                        is_active=True
                    )
                    db.session.add(cat)
                    db.session.flush()
                
                categorias_cache[cat_nombre] = cat.id
            
            cat_id = categorias_cache[cat_nombre]
            
            # Generar código
            ultimo_num += 1
            codigo = f"MYT-{ultimo_num:05d}"
            
            # Crear item
            item = ItemInventario(
                codigo=codigo,
                nombre=nombre,
                descripcion=str(row['subcategoria']).strip() if pd.notna(row['subcategoria']) else '',
                unidad=str(row['unidad']).strip().lower() if pd.notna(row['unidad']) else 'unidad',
                precio_unitario=float(row['precio_usd']) if pd.notna(row['precio_usd']) else 0,
                categoria_id=cat_id,
                organizacion_id=ORG_ID,
                activo=True,
                stock_actual=0,
                stock_minimo=0
            )
            db.session.add(item)
            creados += 1
            
            if creados % 50 == 0:
                print(f"  Creados: {creados}...")
                db.session.commit()
        
        db.session.commit()
        print(f"\n=== RESULTADO ===")
        print(f"Creados: {creados}")
        print(f"Ya existían: {existentes}")
        print(f"Total en BD ahora: {ItemInventario.query.filter_by(organizacion_id=ORG_ID, activo=True).count()}")

if __name__ == '__main__':
    cargar_articulos()
