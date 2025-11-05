#!/usr/bin/env python3
"""
Script de inicialización de base de datos OBYRA
==================================================
Crea todas las tablas, datos iniciales y usuario super admin

Uso:
    python scripts/init_database.py [--admin-email EMAIL] [--admin-password PASSWORD]

Ejemplo:
    python scripts/init_database.py --admin-email admin@obyra.com --admin-password admin123
"""

import sys
import os
import argparse
from getpass import getpass

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from models import Usuario, Organizacion, RoleModule
from werkzeug.security import generate_password_hash
from datetime import datetime


def create_all_tables():
    """Crear todas las tablas de base de datos"""
    print("📦 Creando tablas de base de datos...")
    try:
        with app.app_context():
            db.create_all()
        print("✅ Tablas creadas exitosamente")
        return True
    except Exception as e:
        print(f"❌ Error creando tablas: {e}")
        return False


def create_default_organization():
    """Crear organización por defecto"""
    print("\n🏢 Creando organización por defecto...")
    try:
        with app.app_context():
            # Verificar si ya existe alguna organización
            if Organizacion.query.first():
                print("ℹ️  Ya existe una organización, saltando...")
                return Organizacion.query.first()

            # Crear organización por defecto
            org = Organizacion(
                nombre="OBYRA",
                fecha_creacion=datetime.utcnow(),
                activa=True
            )
            db.session.add(org)
            db.session.commit()
            print(f"✅ Organización '{org.nombre}' creada con ID: {org.id}")
            return org
    except Exception as e:
        print(f"❌ Error creando organización: {e}")
        db.session.rollback()
        return None


def create_role_modules():
    """Crear módulos de roles por defecto"""
    print("\n🔐 Creando módulos de roles...")
    try:
        with app.app_context():
            # Verificar si ya existen módulos
            if RoleModule.query.first():
                print("ℹ️  Ya existen módulos, saltando...")
                return True

            # Módulos por defecto
            modules = [
                {'role': 'admin', 'module': 'obras', 'can_view': True, 'can_edit': True},
                {'role': 'admin', 'module': 'presupuestos', 'can_view': True, 'can_edit': True},
                {'role': 'admin', 'module': 'inventario', 'can_view': True, 'can_edit': True},
                {'role': 'admin', 'module': 'equipos', 'can_view': True, 'can_edit': True},
                {'role': 'admin', 'module': 'usuarios', 'can_view': True, 'can_edit': True},
                {'role': 'admin', 'module': 'reportes', 'can_view': True, 'can_edit': True},
                {'role': 'admin', 'module': 'marketplace', 'can_view': True, 'can_edit': True},

                {'role': 'manager', 'module': 'obras', 'can_view': True, 'can_edit': True},
                {'role': 'manager', 'module': 'presupuestos', 'can_view': True, 'can_edit': True},
                {'role': 'manager', 'module': 'inventario', 'can_view': True, 'can_edit': True},
                {'role': 'manager', 'module': 'equipos', 'can_view': True, 'can_edit': True},
                {'role': 'manager', 'module': 'reportes', 'can_view': True, 'can_edit': False},

                {'role': 'user', 'module': 'obras', 'can_view': True, 'can_edit': False},
                {'role': 'user', 'module': 'presupuestos', 'can_view': True, 'can_edit': False},
                {'role': 'user', 'module': 'inventario', 'can_view': True, 'can_edit': False},
                {'role': 'user', 'module': 'reportes', 'can_view': True, 'can_edit': False},
            ]

            for mod_data in modules:
                rm = RoleModule(**mod_data)
                db.session.add(rm)

            db.session.commit()
            print(f"✅ {len(modules)} módulos de roles creados")
            return True
    except Exception as e:
        print(f"❌ Error creando módulos: {e}")
        db.session.rollback()
        return False


def create_super_admin(email, password, org_id):
    """Crear usuario super admin"""
    print(f"\n👤 Creando usuario super admin ({email})...")
    try:
        with app.app_context():
            # Verificar si ya existe el usuario
            existing = Usuario.query.filter_by(email=email).first()
            if existing:
                print(f"ℹ️  Usuario {email} ya existe")
                # Actualizar a super admin si no lo es
                if not existing.is_super_admin:
                    existing.is_super_admin = True
                    existing.rol = 'admin'
                    existing.activo = True
                    db.session.commit()
                    print(f"✅ Usuario actualizado a super admin")
                return existing

            # Crear nuevo usuario super admin
            user = Usuario(
                email=email,
                password_hash=generate_password_hash(password),
                nombre="Super",
                apellido="Admin",
                rol="admin",
                role="admin",
                is_super_admin=True,
                activo=True,
                organizacion_id=org_id,
                primary_org_id=org_id,
                fecha_creacion=datetime.utcnow(),
                auth_provider='local'
            )
            db.session.add(user)
            db.session.commit()
            print(f"✅ Usuario super admin creado con ID: {user.id}")
            print(f"   Email: {email}")
            print(f"   Password: {'*' * len(password)}")
            return user
    except Exception as e:
        print(f"❌ Error creando usuario: {e}")
        db.session.rollback()
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Inicializar base de datos OBYRA',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--admin-email',
                       default='admin@obyra.com',
                       help='Email del super admin (default: admin@obyra.com)')
    parser.add_argument('--admin-password',
                       help='Password del super admin (si no se provee, se pedirá interactivamente)')
    parser.add_argument('--skip-tables',
                       action='store_true',
                       help='Saltar creación de tablas (útil si ya existen)')

    args = parser.parse_args()

    print("=" * 70)
    print("   OBYRA - Inicialización de Base de Datos")
    print("=" * 70)

    # 1. Crear tablas
    if not args.skip_tables:
        if not create_all_tables():
            print("\n❌ Error fatal: No se pudieron crear las tablas")
            return 1
    else:
        print("⏭️  Saltando creación de tablas...")

    # 2. Crear organización por defecto
    org = create_default_organization()
    if not org:
        print("\n❌ Error fatal: No se pudo crear la organización")
        return 1

    # 3. Crear módulos de roles
    if not create_role_modules():
        print("\n❌ Error fatal: No se pudieron crear los módulos de roles")
        return 1

    # 4. Crear super admin
    admin_password = args.admin_password
    if not admin_password:
        print(f"\n🔑 Crear password para {args.admin_email}")
        admin_password = getpass("Password: ")
        if not admin_password:
            print("❌ Password no puede estar vacío")
            return 1
        confirm_password = getpass("Confirmar password: ")
        if admin_password != confirm_password:
            print("❌ Las passwords no coinciden")
            return 1

    user = create_super_admin(args.admin_email, admin_password, org.id)
    if not user:
        print("\n❌ Error fatal: No se pudo crear el usuario super admin")
        return 1

    # Resumen final
    print("\n" + "=" * 70)
    print("✅ INICIALIZACIÓN COMPLETADA")
    print("=" * 70)
    print(f"\n📊 Base de datos inicializada correctamente")
    print(f"\n🔑 Credenciales de acceso:")
    print(f"   Email:    {args.admin_email}")
    print(f"   Password: (la que configuraste)")
    print(f"\n🌐 Puedes acceder a la aplicación en:")
    print(f"   - http://localhost:5003 (directo)")
    print(f"   - http://localhost:8080 (vía Nginx)")
    print("\n" + "=" * 70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
