#!/usr/bin/env python3
"""
Script para migrar presupuestos existentes asignando etapas a sus ítems.

Este script:
1. Identifica presupuestos confirmados como obra sin etapas asignadas
2. Crea etapas basándose en el JSON datos_proyecto o descripción de ítems
3. Asigna etapa_id a cada ítem del presupuesto
4. Asocia las etapas a la obra correspondiente

Uso:
    python scripts/migrate_presupuesto_etapas.py
"""

import sys
import os

# Agregar directorio raíz al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importar app directamente
import app as flask_app
from extensions import db
from models.budgets import Presupuesto, ItemPresupuesto
from models.projects import EtapaObra
import json

# Mapeo de palabras clave a etapas
ETAPA_KEYWORDS = {
    'Excavación': ['excavacion', 'movimiento', 'suelo', 'terreno', 'nivelacion'],
    'Fundaciones': ['fundacion', 'cimiento', 'zapata', 'viga de fundacion', 'hormigon armado'],
    'Estructura': ['estructura', 'columna', 'viga', 'losa', 'hormigon', 'acero', 'hierro'],
    'Mampostería': ['muro', 'pared', 'tabique', 'ladrillo', 'bloque'],
    'Techos': ['techo', 'cubierta', 'teja', 'chapa', 'impermeabilizacion'],
    'Instalaciones Eléctricas': ['electric', 'cable', 'tablero', 'luminaria', 'tomacorriente'],
    'Instalaciones Sanitarias': ['sanitari', 'agua', 'desague', 'cañeria', 'inodoro', 'lavabo'],
    'Instalaciones de Gas': ['gas', 'gasoducto', 'artefacto a gas'],
    'Revoque Grueso': ['revoque grueso', 'azotado', 'jaharro'],
    'Revoque Fino': ['revoque fino', 'enlucido', 'terminacion'],
    'Pisos': ['piso', 'ceramica', 'porcelanato', 'carpeta', 'contrapiso'],
    'Carpintería': ['puerta', 'ventana', 'marco', 'madera', 'carpinteria'],
    'Pintura': ['pintura', 'latex', 'esmalte', 'barniz'],
    'Instalaciones Complementarias': ['aire acondicionado', 'calefaccion', 'ventilacion'],
    'Limpieza Final': ['limpieza', 'acondicionamiento final'],
}


def identificar_etapa(descripcion: str) -> str:
    """Identifica la etapa basándose en palabras clave en la descripción."""
    descripcion_lower = descripcion.lower()

    for etapa, keywords in ETAPA_KEYWORDS.items():
        for keyword in keywords:
            if keyword in descripcion_lower:
                return etapa

    # Si no encuentra coincidencia, etapa por defecto
    if 'cemento' in descripcion_lower or 'hormigon' in descripcion_lower:
        return 'Fundaciones'
    elif 'cuadrilla' in descripcion_lower:
        return 'Mano de Obra'
    else:
        return 'Materiales Generales'


def migrar_presupuesto(presupuesto_id: int, dry_run: bool = False):
    """Migra un presupuesto asignando etapas a sus ítems."""
    presupuesto = Presupuesto.query.get(presupuesto_id)
    if not presupuesto:
        print(f"❌ Presupuesto {presupuesto_id} no encontrado")
        return False

    print(f"\n📋 Procesando presupuesto {presupuesto.numero} (ID: {presupuesto.id})")
    print(f"   Obra ID: {presupuesto.obra_id}")
    print(f"   Confirmado como obra: {presupuesto.confirmado_como_obra}")

    # Obtener ítems del presupuesto
    items = ItemPresupuesto.query.filter_by(presupuesto_id=presupuesto.id).all()
    print(f"   Total ítems: {len(items)}")

    # Contar ítems sin etapa
    items_sin_etapa = [item for item in items if item.etapa_id is None]
    print(f"   Ítems sin etapa: {len(items_sin_etapa)}")

    if not items_sin_etapa:
        print("   ✅ Todos los ítems ya tienen etapa asignada")
        return True

    # Agrupar ítems por etapa identificada
    items_por_etapa = {}
    for item in items_sin_etapa:
        etapa_nombre = identificar_etapa(item.descripcion)
        if etapa_nombre not in items_por_etapa:
            items_por_etapa[etapa_nombre] = []
        items_por_etapa[etapa_nombre].append(item)

    print(f"\n   Etapas identificadas: {list(items_por_etapa.keys())}")

    if dry_run:
        print("\n   🔍 MODO DRY-RUN - No se realizarán cambios")
        for etapa_nombre, items_etapa in items_por_etapa.items():
            print(f"\n   📦 {etapa_nombre} ({len(items_etapa)} ítems):")
            for item in items_etapa[:3]:  # Mostrar solo los primeros 3
                print(f"      - {item.descripcion}")
            if len(items_etapa) > 3:
                print(f"      ... y {len(items_etapa) - 3} ítems más")
        return True

    # Crear o buscar etapas
    etapas_map = {}
    orden = 1

    for etapa_nombre, items_etapa in items_por_etapa.items():
        # Buscar si ya existe una etapa con ese nombre para esta obra
        etapa_existente = None
        if presupuesto.obra_id:
            etapa_existente = EtapaObra.query.filter_by(
                obra_id=presupuesto.obra_id,
                nombre=etapa_nombre
            ).first()

        if etapa_existente:
            print(f"   ♻️  Usando etapa existente: {etapa_nombre} (ID: {etapa_existente.id})")
            etapa = etapa_existente
        else:
            # Crear nueva etapa
            etapa = EtapaObra(
                obra_id=presupuesto.obra_id,  # Puede ser None si aún no se confirmó
                nombre=etapa_nombre,
                orden=orden,
                estado='pendiente',
                progreso=0
            )
            db.session.add(etapa)
            db.session.flush()  # Para obtener etapa.id
            print(f"   ✨ Creada nueva etapa: {etapa_nombre} (ID: {etapa.id})")
            orden += 1

        etapas_map[etapa_nombre] = etapa

        # Asignar etapa a los ítems
        for item in items_etapa:
            item.etapa_id = etapa.id

        print(f"      Asignados {len(items_etapa)} ítems a la etapa")

    # Commit cambios
    try:
        db.session.commit()
        print(f"\n   ✅ Presupuesto {presupuesto.numero} migrado exitosamente")
        return True
    except Exception as e:
        db.session.rollback()
        print(f"\n   ❌ Error al migrar presupuesto: {e}")
        return False


def main():
    """Función principal del script."""
    app = flask_app.app

    with app.app_context():
        print("=" * 70)
        print("🔄 MIGRACIÓN DE ETAPAS EN PRESUPUESTOS")
        print("=" * 70)

        # Buscar presupuestos confirmados sin etapas
        presupuestos_query = Presupuesto.query.filter_by(
            confirmado_como_obra=True
        ).all()

        print(f"\n📊 Total de presupuestos confirmados: {len(presupuestos_query)}")

        # Filtrar presupuestos que tienen ítems sin etapa
        presupuestos_a_migrar = []
        for presupuesto in presupuestos_query:
            items_sin_etapa = ItemPresupuesto.query.filter_by(
                presupuesto_id=presupuesto.id,
                etapa_id=None
            ).count()
            if items_sin_etapa > 0:
                presupuestos_a_migrar.append((presupuesto, items_sin_etapa))

        if not presupuestos_a_migrar:
            print("\n✅ No hay presupuestos que requieran migración")
            return

        print(f"\n🔍 Presupuestos que requieren migración: {len(presupuestos_a_migrar)}")
        for presupuesto, items_sin_etapa in presupuestos_a_migrar:
            print(f"   - {presupuesto.numero} (ID: {presupuesto.id}) - {items_sin_etapa} ítems sin etapa")

        # Auto-confirmar migración
        print("\n" + "=" * 70)
        print("✅ Procediendo con la migración automáticamente...")
        print("=" * 70)

        # Ejecutar migración
        print("\n" + "=" * 70)
        print("🚀 Iniciando migración...")
        print("=" * 70)

        exitosos = 0
        fallidos = 0

        for presupuesto, _ in presupuestos_a_migrar:
            if migrar_presupuesto(presupuesto.id, dry_run=False):
                exitosos += 1
            else:
                fallidos += 1

        # Resumen final
        print("\n" + "=" * 70)
        print("📈 RESUMEN DE MIGRACIÓN")
        print("=" * 70)
        print(f"✅ Exitosos: {exitosos}")
        print(f"❌ Fallidos: {fallidos}")
        print(f"📊 Total: {len(presupuestos_a_migrar)}")
        print("=" * 70)


if __name__ == '__main__':
    main()
