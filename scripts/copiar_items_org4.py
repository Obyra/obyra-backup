#!/usr/bin/env python3
"""Script para copiar items de inventario de org 2 a org 4"""

import os
import sys

# Evitar error de dotenv
os.environ['SKIP_DOTENV'] = '1'

# Configurar path
sys.path.insert(0, '/app')

# Importar después de configurar el entorno
from flask import Flask
from extensions import db
from models.inventory import ItemInventario, CategoriaInventario

def main():
    app = Flask(__name__)

    # Configurar DB directamente
    db_url = os.environ.get('DATABASE_URL', 'postgresql://obyra_user:secret@postgres:5432/obyra_db')
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        # Verificar estado actual
        count_org2 = ItemInventario.query.filter_by(organizacion_id=2).count()
        count_org4 = ItemInventario.query.filter_by(organizacion_id=4).count()
        print(f"Antes - Org2: {count_org2}, Org4: {count_org4}")

        if count_org4 > 0:
            print("Ya hay items en Org 4, saliendo...")
            return

        # Copiar categorías
        print("Copiando categorías...")
        cats = CategoriaInventario.query.filter_by(organizacion_id=2).all()
        cat_map = {}

        for c in cats:
            new_c = CategoriaInventario(
                organizacion_id=4,
                nombre=c.nombre,
                descripcion=c.descripcion,
                activo=True
            )
            db.session.add(new_c)
            db.session.flush()
            cat_map[c.id] = new_c.id

        db.session.commit()
        print(f"Categorías copiadas: {len(cat_map)}")

        # Copiar items
        print("Copiando items...")
        items = ItemInventario.query.filter_by(organizacion_id=2).all()

        for i, item in enumerate(items):
            new_item = ItemInventario(
                organizacion_id=4,
                codigo=item.codigo,
                nombre=item.nombre,
                descripcion=item.descripcion,
                unidad=item.unidad,
                precio_unitario=item.precio_unitario,
                stock_actual=0,
                stock_minimo=item.stock_minimo or 0,
                categoria_id=cat_map.get(item.categoria_id),
                activo=True
            )
            db.session.add(new_item)

            if (i + 1) % 500 == 0:
                db.session.commit()
                print(f"  Procesados: {i + 1}")

        db.session.commit()

        # Verificar
        count_org4_after = ItemInventario.query.filter_by(organizacion_id=4).count()
        print(f"✅ Items en Org 4: {count_org4_after}")

if __name__ == '__main__':
    main()
