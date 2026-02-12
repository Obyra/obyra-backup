#!/usr/bin/env python3
"""
Script de diagnóstico para verificar presupuestos y sus items de IA
"""
from app import create_app
from models import Presupuesto, ItemPresupuesto
from extensions import db
import json

app = create_app()

with app.app_context():
    print("=" * 80)
    print("DIAGNÓSTICO DE PRESUPUESTOS")
    print("=" * 80)

    # Buscar presupuestos recientes
    presupuestos = Presupuesto.query.order_by(Presupuesto.id.desc()).limit(5).all()

    for p in presupuestos:
        print(f'\n📋 Presupuesto: {p.numero} (ID: {p.id})')
        print(f'   Estado: {p.estado}')
        print(f'   Fecha: {p.fecha}')
        print(f'   Items totales: {p.items.count()}')

        # Contar items por origen
        items_manuales = [i for i in p.items if i.origen == 'manual']
        items_ia = [i for i in p.items if i.origen == 'ia']

        print(f'   Items manuales: {len(items_manuales)}')
        print(f'   Items IA: {len(items_ia)}')

        # Verificar datos_proyecto
        if p.datos_proyecto:
            try:
                datos = json.loads(p.datos_proyecto) if isinstance(p.datos_proyecto, str) else p.datos_proyecto
                tiene_ia_payload = 'ia_payload' in datos
                print(f'   Tiene ia_payload en datos_proyecto: {tiene_ia_payload}')

                if tiene_ia_payload:
                    ia_payload = datos['ia_payload']
                    etapas = ia_payload.get('etapas', [])
                    print(f'   Etapas en ia_payload: {len(etapas)}')
                    if etapas:
                        print(f'   Nombres de etapas: {[e.get("nombre") for e in etapas]}')
            except Exception as e:
                print(f'   Error al parsear datos_proyecto: {str(e)}')

        # Mostrar algunos items de IA
        if items_ia:
            print(f'\n   🤖 Primeros {min(3, len(items_ia))} items de IA:')
            for item in items_ia[:3]:
                print(f'      - {item.tipo}: {item.descripcion[:60]}...')
                print(f'        etapa_nombre: {item.etapa_nombre}')
                print(f'        etapa_id: {item.etapa_id}')
                print(f'        currency: {item.currency}')
                print(f'        price_unit_currency: {item.price_unit_currency}')
                print(f'        total_currency: {item.total_currency}')

    print("\n" + "=" * 80)
    print("FIN DEL DIAGNÓSTICO")
    print("=" * 80)
