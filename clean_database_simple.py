#!/usr/bin/env python3
"""
Script simple para limpiar la base de datos
Elimina TODO excepto el super admin
"""
import os
os.environ['DATABASE_URL'] = 'postgresql+psycopg://obyra:obyra_dev_password@localhost:5436/obyra_dev'

from app import app
from models import Usuario, Presupuesto, Cliente, Obra
from extensions import db

print("=" * 80)
print("LIMPIEZA SIMPLE DE BASE DE DATOS")
print("=" * 80)
print()

with app.app_context():
    # Identificar super admin
    super_admin = Usuario.query.filter_by(is_super_admin=True).first()
    if not super_admin:
        super_admin = Usuario.query.filter_by(email='admin@obyra.com').first()

    if not super_admin:
        print("❌ No se encontró super administrador")
        exit(1)

    super_admin_id = super_admin.id
    print(f"🔒 Super admin: {super_admin.email} (ID: {super_admin_id})")
    print()

    # Eliminar TODO usando TRUNCATE CASCADE
    print("🗑️  Vaciando todas las tablas...")
    try:
        # Deshabilitar triggers temporalmente
        db.session.execute(db.text("SET session_replication_role = 'replica'"))

        # Eliminar todos los registros de las tablas principales
        db.session.execute(db.text("DELETE FROM presupuestos"))
        db.session.execute(db.text("DELETE FROM obras"))
        db.session.execute(db.text("DELETE FROM clientes"))
        db.session.execute(db.text(f"DELETE FROM org_memberships WHERE user_id != {super_admin_id}"))
        db.session.execute(db.text(f"DELETE FROM usuarios WHERE id != {super_admin_id}"))

        # Re-habilitar triggers
        db.session.execute(db.text("SET session_replication_role = 'origin'"))

        db.session.commit()

        print("✅ Limpieza completada")
        print()
        print("📊 Verificación:")
        print(f"   - Presupuestos: {Presupuesto.query.count()}")
        print(f"   - Clientes: {Cliente.query.count()}")
        print(f"   - Obras: {Obra.query.count()}")
        print(f"   - Usuarios: {Usuario.query.count()}")
        print()
        print(f"🔒 Super admin preservado: {super_admin.email}")

    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        db.session.rollback()
        raise
