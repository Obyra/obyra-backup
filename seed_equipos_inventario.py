#!/usr/bin/env python3
"""
Script para poblar la base de datos con datos demo de Equipos e Inventario
"""

from app import app, db
from models import (
    Organizacion, Equipment, EquipmentAssignment, EquipmentUsage,
    MaintenanceTask, InventoryCategory, InventoryItem, Warehouse,
    Stock, StockMovement, StockReservation, Obra, Usuario
)
from seed_inventory_categories import seed_inventory_categories_for_company
from datetime import date, datetime, timedelta
import random

def seed_equipos_inventario():
    """Función principal para poblar equipos e inventario"""
    
    with app.app_context():
        print("🛠️  Iniciando seed de Equipos e Inventario...")
        
        # Obtener organización demo (asumimos que existe)
        org = Organizacion.query.first()
        if not org:
            print("❌ No se encontró organización. Crea una organización primero.")
            return
        
        print(f"📍 Usando organización: {org.nombre}")
        
        # 1. Crear depósitos
        print("\n🏢 Creando depósitos...")
        depositos = crear_depositos(org.id)
        
        # 2. Crear categorías de inventario
        print("\n📂 Creando categorías de inventario...")
        crear_categorias_inventario(org.id)

        # 3. Crear items de inventario
        print("\n📦 Creando items de inventario...")
        items = crear_items_inventario(org.id)
        
        # 4. Crear stock inicial
        print("\n📊 Creando stock inicial...")
        crear_stock_inicial(items, depositos)
        
        # 5. Crear equipos
        print("\n🔧 Creando equipos...")
        equipos = crear_equipos(org.id)
        
        # 6. Crear algunas asignaciones y uso de equipos
        print("\n📋 Creando asignaciones y uso de equipos...")
        crear_asignaciones_uso(equipos, org.id)
        
        # 7. Crear algunos movimientos de inventario
        print("\n🔄 Creando movimientos de inventario...")
        crear_movimientos_inventario(items, depositos, org.id)
        
        # 8. Crear algunas reservas
        print("\n🔖 Creando reservas de stock...")
        crear_reservas_stock(items, org.id)
        
        db.session.commit()
        print("\n✅ Seed completado exitosamente!")
        
        # Mostrar resumen
        mostrar_resumen(org.id)

def crear_depositos(company_id):
    """Crear depósitos demo"""
    depositos_data = [
        {"nombre": "Depósito Central", "direccion": "Av. Industrial 123, Buenos Aires"},
        {"nombre": "Almacén Obra Norte", "direccion": "Zona Norte - Móvil"}
    ]
    
    depositos = []
    for data in depositos_data:
        deposito = Warehouse(
            company_id=company_id,
            **data
        )
        db.session.add(deposito)
        depositos.append(deposito)
        print(f"  ✓ {data['nombre']}")
    
    db.session.flush()  # Para obtener IDs
    return depositos

def crear_categorias_inventario(company_id):
    """Asegura que la organización tenga el árbol completo de categorías."""

    organizacion = Organizacion.query.get(company_id)
    if not organizacion:
        raise ValueError("La organización indicada no existe")

    creadas = seed_inventory_categories_for_company(organizacion)
    if creadas:
        print(f"  ✓ Se crearon {creadas} categorías nuevas")
    else:
        print("  • Categorías ya existentes, no se crearon registros nuevos")

def _obtener_categoria_por_path(company_id, path, cache):
    if path not in cache:
        nombres = [segment.strip() for segment in path.split('>')]
        parent_id = None
        categoria = None
        for nombre in nombres:
            categoria = InventoryCategory.query.filter_by(
                company_id=company_id,
                nombre=nombre,
                parent_id=parent_id,
            ).first()
            if not categoria:
                raise ValueError(f"No se encontró la categoría para la ruta '{path}'")
            parent_id = categoria.id
        cache[path] = categoria
    return cache[path]


def crear_items_inventario(company_id):
    """Crear items de inventario demo"""
    items_data = [
        # Cementos y aglomerantes
        {
            "sku": "CEM-001",
            "nombre": "Cemento Portland",
            "categoria_path": "Materiales de Obra > Cementos y aglomerantes > Cemento Portland",
            "unidad": "bolsa",
            "min_stock": 50,
        },
        {
            "sku": "CEM-002",
            "nombre": "Cal Hidráulica",
            "categoria_path": "Materiales de Obra > Cementos y aglomerantes > Cal hidráulica",
            "unidad": "bolsa",
            "min_stock": 20,
        },
        {
            "sku": "HOR-001",
            "nombre": "Hormigón H17",
            "categoria_path": "Materiales de Obra > Cementos y aglomerantes > Morteros premezclados",
            "unidad": "m3",
            "min_stock": 5,
        },

        # Acero y estructuras
        {
            "sku": "HIE-010",
            "nombre": "Hierro 10mm",
            "categoria_path": "Materiales de Obra > Acero y estructuras > Barras corrugadas",
            "unidad": "kg",
            "min_stock": 500,
        },
        {
            "sku": "HIE-012",
            "nombre": "Hierro 12mm",
            "categoria_path": "Materiales de Obra > Acero y estructuras > Barras corrugadas",
            "unidad": "kg",
            "min_stock": 300,
        },
        {
            "sku": "HIE-016",
            "nombre": "Hierro 16mm",
            "categoria_path": "Materiales de Obra > Acero y estructuras > Barras corrugadas",
            "unidad": "kg",
            "min_stock": 200,
        },

        # Mampostería y áridos
        {
            "sku": "LAD-001",
            "nombre": "Ladrillos Comunes",
            "categoria_path": "Materiales de Obra > Mampostería > Ladrillos cerámicos comunes",
            "unidad": "u",
            "min_stock": 1000,
        },
        {
            "sku": "BLO-001",
            "nombre": "Bloques de Hormigón",
            "categoria_path": "Materiales de Obra > Mampostería > Bloques de hormigón",
            "unidad": "u",
            "min_stock": 200,
        },
        {
            "sku": "ARE-001",
            "nombre": "Arena Gruesa",
            "categoria_path": "Materiales de Obra > Áridos > Arena gruesa",
            "unidad": "m3",
            "min_stock": 10,
        },
        {
            "sku": "PIE-001",
            "nombre": "Piedra Partida",
            "categoria_path": "Materiales de Obra > Áridos > Piedra partida",
            "unidad": "m3",
            "min_stock": 8,
        },

        # Herramientas manuales y eléctricas
        {
            "sku": "HER-001",
            "nombre": "Pala Punta",
            "categoria_path": "Maquinarias y Equipos > Herramientas manuales > Palas y picos",
            "unidad": "u",
            "min_stock": 5,
        },
        {
            "sku": "HER-002",
            "nombre": "Martillo 500g",
            "categoria_path": "Maquinarias y Equipos > Herramientas manuales > Mazas y martillos",
            "unidad": "u",
            "min_stock": 3,
        },
        {
            "sku": "HER-003",
            "nombre": "Nivel de Burbuja",
            "categoria_path": "Maquinarias y Equipos > Herramientas manuales > Niveles manuales",
            "unidad": "u",
            "min_stock": 2,
        },

        # EPP
        {
            "sku": "EPP-001",
            "nombre": "Casco de Seguridad",
            "categoria_path": "Seguridad e Higiene > Equipos de protección personal > Cascos",
            "unidad": "u",
            "min_stock": 20,
        },
        {
            "sku": "EPP-002",
            "nombre": "Guantes de Trabajo",
            "categoria_path": "Seguridad e Higiene > Equipos de protección personal > Guantes",
            "unidad": "u",
            "min_stock": 50,
        },
        {
            "sku": "EPP-003",
            "nombre": "Botas de Seguridad",
            "categoria_path": "Seguridad e Higiene > Equipos de protección personal > Calzado",
            "unidad": "u",
            "min_stock": 15,
        },

        # Instalaciones eléctricas
        {
            "sku": "ELE-001",
            "nombre": "Cable 2.5mm",
            "categoria_path": "Instalaciones > Instalaciones eléctricas > Conductores de baja tensión",
            "unidad": "m",
            "min_stock": 100,
        },
        {
            "sku": "ELE-002",
            "nombre": "Toma Corriente",
            "categoria_path": "Instalaciones > Instalaciones eléctricas > Tomacorrientes y fichas",
            "unidad": "u",
            "min_stock": 20,
        },
    ]

    cache = {}
    items = []
    for data in items_data:
        path = data.pop("categoria_path")
        categoria = _obtener_categoria_por_path(company_id, path, cache)
        item = InventoryItem(
            company_id=company_id,
            categoria_id=categoria.id,
            descripcion=f"Item de inventario para construcción - {data['nombre']}",
            **data,
        )
        db.session.add(item)
        items.append(item)
        print(f"  ✓ {item.sku} - {item.nombre} ({categoria.full_path})")

    db.session.flush()
    return items

def crear_stock_inicial(items, depositos):
    """Crear stock inicial en depósitos"""
    for item in items:
        for i, deposito in enumerate(depositos):
            # Crear stock en cada depósito con cantidades aleatorias
            if i == 0:  # Depósito central - más stock
                cantidad = random.randint(int(item.min_stock * 2), int(item.min_stock * 5))
            else:  # Depósitos secundarios - menos stock
                cantidad = random.randint(int(item.min_stock * 0.5), int(item.min_stock * 1.5))
            
            stock = Stock(
                item_id=item.id,
                warehouse_id=deposito.id,
                cantidad=cantidad
            )
            db.session.add(stock)
            print(f"  ✓ {item.sku}: {cantidad} {item.unidad} en {deposito.nombre}")
    
    db.session.flush()

def crear_equipos(company_id):
    """Crear equipos demo"""
    equipos_data = [
        {"nombre": "Hormigonera Grande", "tipo": "hormigonera", "marca": "Menegotti", "modelo": "400L", "costo_hora": 1500.00},
        {"nombre": "Guinche Eléctrico", "tipo": "guinche", "marca": "Yale", "modelo": "CPV-1000", "costo_hora": 2500.00},
        {"nombre": "Martillo Demoledor", "tipo": "martillo", "marca": "Bosch", "modelo": "GSH27VC", "costo_hora": 800.00},
        {"nombre": "Compresor 50L", "tipo": "compresor", "marca": "Schulz", "modelo": "CSV-10/50", "costo_hora": 600.00},
        {"nombre": "Soldadora Inverter", "tipo": "soldadora", "marca": "Lincoln", "modelo": "Invertec 160S", "costo_hora": 750.00},
        {"nombre": "Generador 5KW", "tipo": "generador", "marca": "Honda", "modelo": "EU50is", "costo_hora": 1200.00}
    ]
    
    equipos = []
    for data in equipos_data:
        equipo = Equipment(
            company_id=company_id,
            nro_serie=f"EQ{random.randint(1000, 9999)}",
            **data
        )
        db.session.add(equipo)
        equipos.append(equipo)
        print(f"  ✓ {equipo.nombre} - {equipo.marca} {equipo.modelo}")
    
    db.session.flush()
    return equipos

def crear_asignaciones_uso(equipos, company_id):
    """Crear asignaciones y partes de uso demo"""
    # Obtener obras de la organización
    obras = Obra.query.filter_by(organizacion_id=company_id).limit(3).all()
    if not obras:
        print("  ⚠️  No hay obras disponibles para asignar equipos")
        return
    
    usuario = Usuario.query.filter_by(organizacion_id=company_id).first()
    if not usuario:
        print("  ⚠️  No hay usuarios disponibles")
        return
    
    # Asignar algunos equipos a obras
    for i, equipo in enumerate(equipos[:3]):  # Solo los primeros 3 equipos
        obra = obras[i % len(obras)]
        
        # Crear asignación
        asignacion = EquipmentAssignment(
            equipment_id=equipo.id,
            project_id=obra.id,
            fecha_desde=date.today() - timedelta(days=random.randint(1, 30))
        )
        db.session.add(asignacion)
        print(f"  ✓ {equipo.nombre} asignado a {obra.nombre}")
        
        # Crear algunos partes de uso
        for j in range(random.randint(2, 5)):
            uso_fecha = date.today() - timedelta(days=random.randint(1, 15))
            uso = EquipmentUsage(
                equipment_id=equipo.id,
                project_id=obra.id,
                fecha=uso_fecha,
                horas=random.uniform(2, 8),
                avance_m2=random.uniform(10, 50) if random.choice([True, False]) else None,
                notas=f"Uso normal del equipo - {uso_fecha}",
                user_id=usuario.id,
                estado=random.choice(['pendiente', 'aprobado'])
            )
            db.session.add(uso)
    
    # Crear algunas tareas de mantenimiento
    for equipo in equipos[:4]:  # Para los primeros 4 equipos
        mantenimiento = MaintenanceTask(
            equipment_id=equipo.id,
            tipo=random.choice(['programado', 'correctivo']),
            fecha_prog=date.today() + timedelta(days=random.randint(7, 60)),
            notas=f"Mantenimiento {random.choice(['preventivo', 'correctivo'])} programado",
            created_by=usuario.id
        )
        db.session.add(mantenimiento)
        print(f"  ✓ Mantenimiento programado para {equipo.nombre}")
    
    db.session.flush()

def crear_movimientos_inventario(items, depositos, company_id):
    """Crear movimientos demo"""
    usuario = Usuario.query.filter_by(organizacion_id=company_id).first()
    if not usuario:
        return
    
    # Crear algunos movimientos de prueba
    for _ in range(10):
        item = random.choice(items)
        deposito = random.choice(depositos)
        tipo_mov = random.choice(['ingreso', 'egreso'])
        
        if tipo_mov == 'ingreso':
            movimiento = StockMovement(
                item_id=item.id,
                tipo='ingreso',
                qty=random.uniform(5, 50),
                destino_warehouse_id=deposito.id,
                motivo="Compra de materiales - Ingreso demo",
                user_id=usuario.id,
                fecha=datetime.now() - timedelta(days=random.randint(1, 15))
            )
        else:
            movimiento = StockMovement(
                item_id=item.id,
                tipo='egreso',
                qty=random.uniform(1, 10),
                origen_warehouse_id=deposito.id,
                motivo="Uso en obra - Egreso demo",
                user_id=usuario.id,
                fecha=datetime.now() - timedelta(days=random.randint(1, 10))
            )
        
        db.session.add(movimiento)
        print(f"  ✓ {tipo_mov.title()}: {movimiento.qty} {item.unidad} de {item.nombre}")
    
    db.session.flush()

def crear_reservas_stock(items, company_id):
    """Crear reservas demo"""
    obras = Obra.query.filter_by(organizacion_id=company_id).limit(2).all()
    usuario = Usuario.query.filter_by(organizacion_id=company_id).first()
    
    if not obras or not usuario:
        return
    
    # Crear algunas reservas
    for _ in range(5):
        item = random.choice(items)
        obra = random.choice(obras)
        
        # Solo reservar si hay stock disponible
        if item.available_stock > 0:
            qty_reserva = min(random.uniform(1, 10), float(item.available_stock))
            
            reserva = StockReservation(
                item_id=item.id,
                project_id=obra.id,
                qty=qty_reserva,
                created_by=usuario.id
            )
            db.session.add(reserva)
            print(f"  ✓ Reserva: {qty_reserva} {item.unidad} de {item.nombre} para {obra.nombre}")
    
    db.session.flush()

def mostrar_resumen(company_id):
    """Mostrar resumen de datos creados"""
    print("\n" + "="*50)
    print("📊 RESUMEN DE DATOS CREADOS")
    print("="*50)
    
    # Equipos
    equipos_count = Equipment.query.filter_by(company_id=company_id).count()
    asignaciones_count = EquipmentAssignment.query.join(Equipment).filter(Equipment.company_id == company_id).count()
    usos_count = EquipmentUsage.query.join(Equipment).filter(Equipment.company_id == company_id).count()
    mantenimientos_count = MaintenanceTask.query.join(Equipment).filter(Equipment.company_id == company_id).count()
    
    print(f"🔧 EQUIPOS:")
    print(f"   • {equipos_count} equipos creados")
    print(f"   • {asignaciones_count} asignaciones")
    print(f"   • {usos_count} partes de uso")
    print(f"   • {mantenimientos_count} tareas de mantenimiento")
    
    # Inventario
    depositos_count = Warehouse.query.filter_by(company_id=company_id).count()
    categorias_count = InventoryCategory.query.filter_by(company_id=company_id).count()
    items_count = InventoryItem.query.filter_by(company_id=company_id).count()
    movimientos_count = StockMovement.query.join(InventoryItem).filter(InventoryItem.company_id == company_id).count()
    reservas_count = StockReservation.query.join(InventoryItem).filter(InventoryItem.company_id == company_id).count()
    
    print(f"\n📦 INVENTARIO:")
    print(f"   • {depositos_count} depósitos")
    print(f"   • {categorias_count} categorías")
    print(f"   • {items_count} items")
    print(f"   • {movimientos_count} movimientos de stock")
    print(f"   • {reservas_count} reservas activas")
    
    # Items con stock bajo
    items_stock_bajo = InventoryItem.query.filter_by(company_id=company_id).all()
    items_stock_bajo = [item for item in items_stock_bajo if item.is_low_stock]
    
    if items_stock_bajo:
        print(f"\n⚠️  ALERTAS DE STOCK BAJO: {len(items_stock_bajo)} items")
        for item in items_stock_bajo:
            print(f"   • {item.sku}: {item.total_stock} {item.unidad} (mín: {item.min_stock})")
    
    print("\n" + "="*50)
    print("✅ Equipos e Inventario listos para usar!")
    print(f"🌐 Accede a:")
    print(f"   • Equipos: /equipos-new")
    print(f"   • Inventario: /inventario-new")
    print("="*50)

if __name__ == "__main__":
    seed_equipos_inventario()