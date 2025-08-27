#!/usr/bin/env python3
"""
Script para poblar la base de datos con datos demo del Portal de Proveedores
"""

from app import app, db
from models import (
    Supplier, SupplierUser, Category, Product, ProductVariant, 
    ProductImage, Order, OrderItem, OrderCommission, Organizacion
)
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random
import os

def seed_suppliers():
    """Función principal para poblar el Portal de Proveedores"""
    
    with app.app_context():
        print("🏪 Iniciando seed del Portal de Proveedores...")
        
        # 1. Crear categorías
        print("\n📂 Creando categorías...")
        categorias = crear_categorias()
        
        # 2. Crear proveedores demo
        print("\n🏢 Creando proveedores...")
        suppliers = crear_suppliers()
        
        # 3. Crear productos con variantes
        print("\n📦 Creando productos...")
        productos = crear_productos(suppliers, categorias)
        
        # 4. Crear orden demo
        print("\n🛒 Creando orden demo...")
        crear_orden_demo(suppliers, productos)
        
        db.session.commit()
        print("\n✅ Seed del Portal de Proveedores completado!")
        
        # Mostrar resumen
        mostrar_resumen()

def crear_categorias():
    """Crear categorías de productos"""
    categorias_data = [
        {"nombre": "Materiales de Construcción"},
        {"nombre": "Maquinarias y Equipos"},
        {"nombre": "Herramientas"},
        {"nombre": "EPP - Equipos de Protección"},
        {"nombre": "Servicios Profesionales"}
    ]
    
    categorias = []
    for data in categorias_data:
        categoria = Category(**data)
        db.session.add(categoria)
        categorias.append(categoria)
        print(f"  ✓ {data['nombre']}")
    
    db.session.flush()
    return categorias

def crear_suppliers():
    """Crear proveedores demo"""
    suppliers_data = [
        {
            "razon_social": "Materiales del Norte S.A.",
            "cuit": "30-12345678-9",
            "email": "ventas@materialesnorte.com.ar",
            "phone": "+54 11 4123-4567",
            "direccion": "Av. Córdoba 1234, CABA",
            "ubicacion": "Buenos Aires",
            "descripcion": "Proveedor líder en materiales de construcción con más de 20 años de experiencia. Especializados en cemento, hierro y agregados.",
            "verificado": True,
            "usuario": {
                "nombre": "Carlos Rodríguez",
                "email": "carlos@materialesnorte.com.ar",
                "password": "123456"
            }
        },
        {
            "razon_social": "Equipos Industriales Córdoba",
            "cuit": "30-98765432-1",
            "email": "info@equiposcordoba.com",
            "phone": "+54 351 456-7890",
            "direccion": "Ruta 9 Km 15, Córdoba",
            "ubicacion": "Córdoba",
            "descripcion": "Venta y alquiler de maquinaria pesada para construcción. Representantes exclusivos de marcas internacionales.",
            "verificado": True,
            "usuario": {
                "nombre": "María González",
                "email": "maria@equiposcordoba.com",
                "password": "123456"
            }
        },
        {
            "razon_social": "Seguridad Laboral SRL",
            "cuit": "30-11223344-5",
            "email": "ventas@seguridadlaboral.com.ar",
            "phone": "+54 11 5555-6666",
            "direccion": "Parque Industrial Pilar",
            "ubicacion": "Buenos Aires",
            "descripcion": "Especialistas en equipos de protección personal y seguridad industrial. Amplio stock y entrega inmediata.",
            "verificado": False,  # Este estará pendiente de verificación
            "usuario": {
                "nombre": "Roberto Silva",
                "email": "roberto@seguridadlaboral.com.ar",
                "password": "123456"
            }
        }
    ]
    
    suppliers = []
    for data in suppliers_data:
        usuario_data = data.pop('usuario')
        
        # Crear proveedor
        supplier = Supplier(**data)
        db.session.add(supplier)
        db.session.flush()  # Para obtener ID
        
        # Crear usuario owner
        supplier_user = SupplierUser(
            supplier_id=supplier.id,
            nombre=usuario_data['nombre'],
            email=usuario_data['email'],
            rol='owner'
        )
        supplier_user.set_password(usuario_data['password'])
        db.session.add(supplier_user)
        
        suppliers.append(supplier)
        print(f"  ✓ {supplier.razon_social} - {usuario_data['email']}")
    
    db.session.flush()
    return suppliers

def crear_productos(suppliers, categorias):
    """Crear productos demo con variantes"""
    productos_data = [
        # Materiales del Norte
        {
            "supplier_idx": 0,
            "categoria_idx": 0,
            "nombre": "Cemento Portland Tipo I",
            "descripcion": "Cemento Portland de alta calidad para construcción general. Cumple normas IRAM 50000.",
            "variantes": [
                {"sku": "CEM-PORT-50", "unidad": "bolsa", "precio": 1250.00, "stock": 500, "atributos": {"peso": "50kg"}},
                {"sku": "CEM-PORT-25", "unidad": "bolsa", "precio": 650.00, "stock": 200, "atributos": {"peso": "25kg"}}
            ]
        },
        {
            "supplier_idx": 0,
            "categoria_idx": 0,
            "nombre": "Hierro Aletado ADN 420",
            "descripcion": "Hierro de construcción aletado de alta resistencia, ideal para estructuras.",
            "variantes": [
                {"sku": "HIE-ADN-8", "unidad": "kg", "precio": 890.00, "stock": 1000, "atributos": {"diametro": "8mm"}},
                {"sku": "HIE-ADN-10", "unidad": "kg", "precio": 920.00, "stock": 800, "atributos": {"diametro": "10mm"}},
                {"sku": "HIE-ADN-12", "unidad": "kg", "precio": 950.00, "stock": 600, "atributos": {"diametro": "12mm"}}
            ]
        },
        
        # Equipos Industriales Córdoba
        {
            "supplier_idx": 1,
            "categoria_idx": 1,
            "nombre": "Hormigonera Autopropulsada",
            "descripcion": "Hormigonera autopropulsada de 400 litros con motor diésel. Ideal para obras medianas.",
            "variantes": [
                {"sku": "HOR-AUTO-400", "unidad": "u", "precio": 2850000.00, "stock": 3, "atributos": {"capacidad": "400L", "motor": "Diesel"}}
            ]
        },
        {
            "supplier_idx": 1,
            "categoria_idx": 1,
            "nombre": "Martillo Demoledor Neumático",
            "descripcion": "Martillo demoledor neumático para trabajos pesados de demolición.",
            "variantes": [
                {"sku": "MAR-NEU-65", "unidad": "u", "precio": 185000.00, "stock": 5, "atributos": {"peso": "65kg", "tipo": "Neumático"}}
            ]
        },
        
        # Seguridad Laboral
        {
            "supplier_idx": 2,
            "categoria_idx": 3,
            "nombre": "Casco de Seguridad",
            "descripcion": "Casco de seguridad industrial con ajuste de carraca. Cumple normas ANSI.",
            "variantes": [
                {"sku": "CAS-SEG-BLA", "unidad": "u", "precio": 3500.00, "stock": 100, "atributos": {"color": "Blanco"}},
                {"sku": "CAS-SEG-AMA", "unidad": "u", "precio": 3500.00, "stock": 80, "atributos": {"color": "Amarillo"}},
                {"sku": "CAS-SEG-AZU", "unidad": "u", "precio": 3500.00, "stock": 60, "atributos": {"color": "Azul"}}
            ]
        },
        {
            "supplier_idx": 2,
            "categoria_idx": 3,
            "nombre": "Botas de Seguridad con Puntera",
            "descripcion": "Botas de seguridad con puntera de acero y suela antideslizante.",
            "variantes": [
                {"sku": "BOT-SEG-39", "unidad": "u", "precio": 12500.00, "stock": 25, "atributos": {"talla": "39"}},
                {"sku": "BOT-SEG-40", "unidad": "u", "precio": 12500.00, "stock": 30, "atributos": {"talla": "40"}},
                {"sku": "BOT-SEG-41", "unidad": "u", "precio": 12500.00, "stock": 28, "atributos": {"talla": "41"}},
                {"sku": "BOT-SEG-42", "unidad": "u", "precio": 12500.00, "stock": 35, "atributos": {"talla": "42"}},
                {"sku": "BOT-SEG-43", "unidad": "u", "precio": 12500.00, "stock": 22, "atributos": {"talla": "43"}}
            ]
        }
    ]
    
    productos = []
    for data in productos_data:
        supplier = suppliers[data['supplier_idx']]
        categoria = categorias[data['categoria_idx']]
        
        # Crear producto
        producto = Product(
            supplier_id=supplier.id,
            category_id=categoria.id,
            nombre=data['nombre'],
            descripcion=data['descripcion'],
            estado='publicado'  # Solo publicamos los de suppliers verificados
        )
        
        # Si el supplier no está verificado, dejar en borrador
        if not supplier.verificado:
            producto.estado = 'borrador'
        
        db.session.add(producto)
        db.session.flush()
        
        # Crear variantes
        for var_data in data['variantes']:
            atributos = var_data.pop('atributos', None)
            variante = ProductVariant(
                product_id=producto.id,
                atributos_json=atributos,
                **var_data
            )
            db.session.add(variante)
        
        # Crear imagen demo (placeholder)
        imagen = ProductImage(
            product_id=producto.id,
            url=f"/static/images/productos/demo_{producto.id}.jpg",
            filename=f"demo_{producto.id}.jpg",
            orden=0
        )
        db.session.add(imagen)
        
        productos.append(producto)
        print(f"  ✓ {producto.nombre} ({len(data['variantes'])} variantes)")
    
    db.session.flush()
    return productos

def crear_orden_demo(suppliers, productos):
    """Crear una orden demo para mostrar el flujo"""
    # Obtener la primera organización
    org = Organizacion.query.first()
    if not org:
        print("  ⚠️  No hay organizaciones para crear orden demo")
        return
    
    # Usar el primer supplier verificado
    supplier = next((s for s in suppliers if s.verificado), None)
    if not supplier:
        print("  ⚠️  No hay suppliers verificados para crear orden demo")
        return
    
    # Obtener algunos productos del supplier
    productos_supplier = [p for p in productos if p.supplier_id == supplier.id and p.estado == 'publicado']
    if not productos_supplier:
        print("  ⚠️  No hay productos publicados para crear orden demo")
        return
    
    # Crear orden
    orden = Order(
        company_id=org.id,
        supplier_id=supplier.id,
        total=0,  # Se calculará después
        payment_method='offline',
        created_at=datetime.now() - timedelta(days=2)
    )
    db.session.add(orden)
    db.session.flush()
    
    total_orden = 0
    
    # Agregar algunos items
    for i, producto in enumerate(productos_supplier[:2]):  # Solo los primeros 2 productos
        if producto.variants:
            variante = producto.variants[0]  # Primera variante
            qty = random.uniform(1, 5)
            precio_unit = variante.precio
            subtotal = float(precio_unit) * qty
            
            order_item = OrderItem(
                order_id=orden.id,
                product_variant_id=variante.id,
                qty=qty,
                precio_unit=precio_unit,
                subtotal=subtotal
            )
            db.session.add(order_item)
            total_orden += subtotal
    
    # Actualizar total
    orden.total = total_orden
    
    # Crear comisión
    commission_data = OrderCommission.compute_commission(orden.total)
    commission = OrderCommission(
        order_id=orden.id,
        base=orden.total,
        **commission_data,
        status='pendiente'
    )
    db.session.add(commission)
    
    print(f"  ✓ Orden #{orden.id} - ${total_orden:,.2f} (Comisión: ${commission.total:,.2f})")

def mostrar_resumen():
    """Mostrar resumen de datos creados"""
    print("\n" + "="*60)
    print("📊 RESUMEN DEL PORTAL DE PROVEEDORES")
    print("="*60)
    
    # Proveedores
    suppliers_count = Supplier.query.count()
    verified_count = Supplier.query.filter_by(verificado=True).count()
    users_count = SupplierUser.query.count()
    
    print(f"🏢 PROVEEDORES:")
    print(f"   • {suppliers_count} proveedores registrados")
    print(f"   • {verified_count} verificados")
    print(f"   • {users_count} usuarios creados")
    
    # Catálogo
    categorias_count = Category.query.count()
    productos_count = Product.query.count()
    productos_publicados = Product.query.filter_by(estado='publicado').count()
    variantes_count = ProductVariant.query.count()
    
    print(f"\n📦 CATÁLOGO:")
    print(f"   • {categorias_count} categorías")
    print(f"   • {productos_count} productos ({productos_publicados} publicados)")
    print(f"   • {variantes_count} variantes de productos")
    
    # Órdenes
    ordenes_count = Order.query.count()
    comisiones_count = OrderCommission.query.count()
    total_ventas = db.session.query(func.sum(Order.total)).scalar() or 0
    total_comisiones = db.session.query(func.sum(OrderCommission.total)).scalar() or 0
    
    print(f"\n🛒 VENTAS:")
    print(f"   • {ordenes_count} órdenes")
    print(f"   • ${total_ventas:,.2f} en ventas totales")
    print(f"   • {comisiones_count} comisiones")
    print(f"   • ${total_comisiones:,.2f} en comisiones")
    
    print("\n" + "="*60)
    print("✅ Portal de Proveedores listo para usar!")
    print(f"🌐 Accesos:")
    print(f"   • Marketplace: /market")
    print(f"   • Registro Proveedores: /proveedor/registro")
    print(f"   • Login Proveedores: /proveedor/login")
    print(f"\n👤 Cuentas de prueba:")
    
    for user in SupplierUser.query.all():
        print(f"   • {user.email} / 123456 ({user.supplier.razon_social})")
    
    print("="*60)

if __name__ == "__main__":
    seed_suppliers()