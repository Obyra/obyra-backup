#!/usr/bin/env python3
"""
Script para poblar la base de datos con proveedores de ejemplo
"""

from datetime import datetime
from decimal import Decimal
from app import app, db
from models import Proveedor, Organizacion

def seed_proveedores():
    """Crear proveedores de ejemplo para el marketplace"""
    
    with app.app_context():
        # Obtener la primera organización para los proveedores
        organizacion = Organizacion.query.first()
        if not organizacion:
            print("❌ No se encontró ninguna organización. Crea un usuario primero.")
            return
        
        # Verificar si ya existen proveedores
        if Proveedor.query.count() > 0:
            print("ℹ️  Ya existen proveedores en la base de datos.")
            return
        
        proveedores_ejemplo = [
            # Materiales de Construcción
            {
                'nombre': 'Corralón San Martín',
                'descripcion': 'Proveedor integral de materiales de construcción con más de 20 años de experiencia. Especialistas en cemento, ladrillos, hierro y materiales de primera calidad.',
                'categoria': 'materiales',
                'especialidad': 'Cemento y Hormigón',
                'ubicacion': 'San Martín, Buenos Aires',
                'telefono': '+54 11 4755-8900',
                'email': 'ventas@corralonsan.com.ar',
                'sitio_web': 'https://corralonsan.com.ar',
                'precio_promedio': Decimal('25000.00'),
                'calificacion': Decimal('4.8'),
                'trabajos_completados': 145,
                'verificado': True
            },
            {
                'nombre': 'Hierros del Norte',
                'descripcion': 'Distribuidores oficiales de Acindar y Siderca. Hierro para construcción, barras, mallas, estructuras metálicas y soldaduras especiales.',
                'categoria': 'materiales',
                'especialidad': 'Hierro y Acero',
                'ubicacion': 'Tigre, Buenos Aires',
                'telefono': '+54 11 4749-2100',
                'email': 'info@hierrosdelnorte.com',
                'precio_promedio': Decimal('85000.00'),
                'calificacion': Decimal('4.9'),
                'trabajos_completados': 89,
                'verificado': True
            },
            {
                'nombre': 'Ladrillos Premium SA',
                'descripcion': 'Fabricantes de ladrillos huecos, macizos, refractarios y bloques de hormigón. Calidad garantizada y entrega en obra.',
                'categoria': 'materiales',
                'especialidad': 'Ladrillos y Bloques',
                'ubicacion': 'Moreno, Buenos Aires',
                'telefono': '+54 11 4629-7500',
                'email': 'comercial@ladrillospremium.com.ar',
                'precio_promedio': Decimal('15000.00'),
                'calificacion': Decimal('4.6'),
                'trabajos_completados': 234,
                'verificado': True
            },
            
            # Equipos y Maquinaria
            {
                'nombre': 'Maquinarias del Sur',
                'descripcion': 'Alquiler y venta de maquinaria pesada para construcción. Excavadoras, retroexcavadoras, grúas y equipos especializados.',
                'categoria': 'equipos',
                'especialidad': 'Excavadoras y Retroexcavadoras',
                'ubicacion': 'La Plata, Buenos Aires',
                'telefono': '+54 221 423-8900',
                'email': 'alquiler@maquinariassur.com.ar',
                'sitio_web': 'https://maquinariassur.com.ar',
                'precio_promedio': Decimal('120000.00'),
                'calificacion': Decimal('4.7'),
                'trabajos_completados': 67,
                'verificado': True
            },
            {
                'nombre': 'Grúas Capital',
                'descripcion': 'Servicios de grúas móviles y torre para construcción. Operadores certificados, seguros completos y asistencia 24hs.',
                'categoria': 'equipos',
                'especialidad': 'Grúas y Montacargas',
                'ubicacion': 'CABA, Buenos Aires',
                'telefono': '+54 11 4861-3400',
                'email': 'servicios@gruascapital.com.ar',
                'precio_promedio': Decimal('95000.00'),
                'calificacion': Decimal('4.9'),
                'trabajos_completados': 123,
                'verificado': True
            },
            
            # Servicios Especializados
            {
                'nombre': 'Excavaciones Rodríguez',
                'descripcion': 'Empresa familiar especializada en movimiento de suelos, excavaciones, demoliciones y nivelación de terrenos.',
                'categoria': 'servicios',
                'especialidad': 'Movimiento de Suelos',
                'ubicacion': 'San Isidro, Buenos Aires',
                'telefono': '+54 11 4747-9200',
                'email': 'contacto@excavacionesrodriguez.com.ar',
                'precio_promedio': Decimal('75000.00'),
                'calificacion': Decimal('4.5'),
                'trabajos_completados': 156,
                'verificado': False
            },
            {
                'nombre': 'Instalaciones Integrales JM',
                'descripcion': 'Instalaciones eléctricas, sanitarias y gas. Profesionales matriculados, garantía extendida y cumplimiento normativo.',
                'categoria': 'servicios',
                'especialidad': 'Instalaciones Eléctricas',
                'ubicacion': 'Vicente López, Buenos Aires',
                'telefono': '+54 11 4837-5600',
                'email': 'info@instalacionesjm.com.ar',
                'precio_promedio': Decimal('65000.00'),
                'calificacion': Decimal('4.8'),
                'trabajos_completados': 198,
                'verificado': True
            },
            
            # Profesionales
            {
                'nombre': 'Arq. María Elena Vásquez',
                'descripcion': 'Arquitecta especializada en proyectos residenciales y comerciales. Registro profesional vigente, experiencia en obras complejas.',
                'categoria': 'profesionales',
                'especialidad': 'Arquitectos',
                'ubicacion': 'Belgrano, CABA',
                'telefono': '+54 11 4784-2100',
                'email': 'mariaelena.arq@gmail.com',
                'precio_promedio': Decimal('45000.00'),
                'calificacion': Decimal('4.9'),
                'trabajos_completados': 78,
                'verificado': True
            },
            {
                'nombre': 'Ing. Carlos Mendoza',
                'descripcion': 'Ingeniero Civil con 15 años de experiencia. Especialista en estructuras de hormigón, cálculos sísmicos y dirección técnica.',
                'categoria': 'profesionales',
                'especialidad': 'Ingenieros Civiles',
                'ubicacion': 'Quilmes, Buenos Aires',
                'telefono': '+54 11 4253-7800',
                'email': 'ing.carlosmendoza@outlook.com',
                'precio_promedio': Decimal('55000.00'),
                'calificacion': Decimal('4.7'),
                'trabajos_completados': 92,
                'verificado': True
            },
            {
                'nombre': 'Maestro Juan Pérez',
                'descripcion': 'Maestro Mayor de Obra con registro habilitante. Más de 25 años dirigiendo obras de envergadura, especialista en albañilería.',
                'categoria': 'profesionales',
                'especialidad': 'Maestros Mayor de Obra',
                'ubicacion': 'Avellaneda, Buenos Aires',
                'telefono': '+54 11 4201-9500',
                'email': 'maestrojuanperez@gmail.com',
                'precio_promedio': Decimal('40000.00'),
                'calificacion': Decimal('4.6'),
                'trabajos_completados': 201,
                'verificado': False
            }
        ]
        
        print("🌱 Creando proveedores de ejemplo...")
        
        for prov_data in proveedores_ejemplo:
            proveedor = Proveedor(
                organizacion_id=organizacion.id,
                nombre=prov_data['nombre'],
                descripcion=prov_data['descripcion'],
                categoria=prov_data['categoria'],
                especialidad=prov_data['especialidad'],
                ubicacion=prov_data['ubicacion'],
                telefono=prov_data['telefono'],
                email=prov_data['email'],
                sitio_web=prov_data.get('sitio_web'),
                precio_promedio=prov_data['precio_promedio'],
                calificacion=prov_data['calificacion'],
                trabajos_completados=prov_data['trabajos_completados'],
                verificado=prov_data['verificado'],
                activo=True,
                fecha_registro=datetime.utcnow()
            )
            
            db.session.add(proveedor)
            print(f"✅ Creado: {proveedor.nombre} ({proveedor.categoria})")
        
        db.session.commit()
        print(f"\n🎉 {len(proveedores_ejemplo)} proveedores creados exitosamente!")
        print("🔗 Accede al marketplace desde: /marketplaces")

if __name__ == '__main__':
    seed_proveedores()