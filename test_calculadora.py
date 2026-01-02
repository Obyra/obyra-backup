#!/usr/bin/env python
"""Test de la calculadora IA mejorada."""

from app import app

with app.app_context():
    from services.calculadora_ia_mejorada import calcular_presupuesto_completo, obtener_resumen_etapas

    # Test resumen de etapas
    print('=== RESUMEN DE ETAPAS CON ITEMS ===')
    etapas = obtener_resumen_etapas()
    total_items = 0
    for e in etapas:
        total_items += e['items_disponibles']
        nombre = e['nombre'][:35].ljust(35)
        print(f"  {e['orden']:2}. {nombre} | {e['items_disponibles']:5} items | {e['porcentaje_obra']}%")
    print(f'\n  TOTAL ITEMS EN INVENTARIO: {total_items}')
    print()

    # Test cálculo completo para 150m² Estándar
    print('=== CALCULO 150m2 CONSTRUCCION ESTANDAR ===')
    resultado = calcular_presupuesto_completo(
        metros_cuadrados=150,
        tipo_construccion='Estándar',
        etapas_seleccionadas=None,  # Todas las etapas
        org_id=2,
        tipo_cambio_usd=1200
    )

    print(f"\nEtapas calculadas: {resultado['resumen']['cantidad_etapas']}")
    print(f"Items de inventario: {resultado['resumen']['total_items_inventario']}")
    print()
    print('TOTALES:')
    print(f"  Materiales:      ${resultado['totales']['materiales']['usd']:>12,.2f} USD")
    print(f"  Mano de obra:    ${resultado['totales']['mano_obra']['usd']:>12,.2f} USD")
    print(f"  Equipos:         ${resultado['totales']['equipos']['usd']:>12,.2f} USD")
    print(f"  Subtotal:        ${resultado['totales']['subtotal']['usd']:>12,.2f} USD")
    print(f"  Gastos gen (8%): ${resultado['totales']['gastos_generales']['usd']:>12,.2f} USD")
    print(f"  Beneficio (10%): ${resultado['totales']['beneficio']['usd']:>12,.2f} USD")
    print(f"  IVA (21%):       ${resultado['totales']['iva']['usd']:>12,.2f} USD")
    print(f"  ---------------------------------")
    print(f"  TOTAL:           ${resultado['totales']['total']['usd']:>12,.2f} USD")
    print(f"  Costo por m2:    ${resultado['totales']['costo_m2']['usd']:>12,.2f} USD/m2")
