#!/usr/bin/env python3
"""
Script para corregir presupuestos existentes:
1. Agregar etapa_nombre a items de IA que no lo tienen
2. Agregar price_unit_currency y total_currency para items en USD
"""
import os
# Forzar el puerto correcto antes de importar app
os.environ['DATABASE_URL'] = 'postgresql+psycopg://obyra:obyra_dev_password@localhost:5436/obyra_dev'
os.environ['ALEMBIC_DATABASE_URL'] = 'postgresql+psycopg://obyra_migrator:migrator_dev_password@localhost:5436/obyra_dev'

from app import app
from models import Presupuesto, ItemPresupuesto
from extensions import db
from decimal import Decimal
import json

with app.app_context():
    print("=" * 80)
    print("CORRECCIÓN DE PRESUPUESTOS CON ITEMS DE IA")
    print("=" * 80)

    # Buscar todos los presupuestos con items de IA
    presupuestos = Presupuesto.query.all()
    presupuestos_actualizados = 0
    items_actualizados = 0

    for p in presupuestos:
        items_ia = [i for i in p.items if i.origen == 'ia']

        if not items_ia:
            continue  # Skip si no tiene items de IA

        print(f'\n📋 Procesando presupuesto: {p.numero} (ID: {p.id})')
        print(f'   Items IA encontrados: {len(items_ia)}')

        presupuesto_modificado = False

        # Intentar obtener el payload de IA
        etapas_dict = {}
        if p.datos_proyecto:
            try:
                datos = json.loads(p.datos_proyecto) if isinstance(p.datos_proyecto, str) else p.datos_proyecto
                ia_payload = datos.get('ia_payload')

                if ia_payload and ia_payload.get('etapas'):
                    # Crear un mapeo de items por descripción a etapa
                    for etapa_data in ia_payload['etapas']:
                        etapa_nombre = etapa_data.get('nombre', 'Sin nombre')
                        items_etapa = etapa_data.get('items', [])

                        for item_data in items_etapa:
                            descripcion = item_data.get('descripcion', '')
                            etapas_dict[descripcion] = etapa_nombre

                    print(f'   Payload IA encontrado con {len(ia_payload["etapas"])} etapas')
            except Exception as e:
                print(f'   ⚠️ Error al parsear datos_proyecto: {str(e)}')

        # Actualizar items
        for item in items_ia:
            item_modificado = False

            # 1. Agregar etapa_nombre si no lo tiene
            if not item.etapa_nombre and item.descripcion in etapas_dict:
                item.etapa_nombre = etapas_dict[item.descripcion]
                item_modificado = True
                print(f'   ✅ Agregado etapa_nombre "{item.etapa_nombre}" a item: {item.descripcion[:50]}...')

            # 2. Agregar price_unit_currency y total_currency para items en USD
            if item.currency == 'USD':
                if item.price_unit_currency is None and item.precio_unitario:
                    item.price_unit_currency = item.precio_unitario
                    item_modificado = True
                    print(f'   ✅ Agregado price_unit_currency ${item.precio_unitario} a item: {item.descripcion[:50]}...')

                if item.total_currency is None and item.total:
                    item.total_currency = item.total
                    item_modificado = True
                    print(f'   ✅ Agregado total_currency ${item.total} a item: {item.descripcion[:50]}...')

            if item_modificado:
                items_actualizados += 1
                presupuesto_modificado = True

        if presupuesto_modificado:
            presupuestos_actualizados += 1

    # Commit cambios
    if items_actualizados > 0:
        try:
            db.session.commit()
            print(f'\n✅ Actualización exitosa:')
            print(f'   - {presupuestos_actualizados} presupuestos actualizados')
            print(f'   - {items_actualizados} items corregidos')
        except Exception as e:
            db.session.rollback()
            print(f'\n❌ Error al guardar cambios: {str(e)}')
    else:
        print(f'\nℹ️ No se encontraron items para actualizar')

    print("\n" + "=" * 80)
    print("FIN DE LA CORRECCIÓN")
    print("=" * 80)
