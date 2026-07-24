#!/usr/bin/env python3
"""
Script simple para limpiar la base de datos
Elimina TODO excepto el super admin
"""
import os
os.environ['DATABASE_URL'] = 'postgresql+psycopg://obyra:obyra_dev_password@localhost:5436/obyra_dev'


# --- Guardia anti-producción (defensa en profundidad) ---
# Este script BORRA datos en masa. Se valida DESPUÉS del override de arriba para
# chequear la URL efectiva que el script va a usar de verdad. Fail-closed: ante la
# duda no borra. Override explícito con ALLOW_DB_WIPE=1.
def _check_not_production():
    import sys
    db_url = os.getenv("DATABASE_URL", "").lower()
    prod_markers = ("railway", "rlwy.net", "neon.tech", "amazonaws",
                    "supabase", "render.com", "prod")
    hit = next((m for m in prod_markers if m in db_url), None)
    if hit:
        print(f"❌ ABORT: DATABASE_URL parece producción (marcador '{hit}'). "
              "Este script solo corre en local/staging.")
        sys.exit(1)
    local_markers = ("localhost", "127.0.0.1", "@postgres", "@db")
    if not any(m in db_url for m in local_markers) and os.getenv("ALLOW_DB_WIPE") != "1":
        print("❌ ABORT: DATABASE_URL no parece local y ALLOW_DB_WIPE!=1. "
              "Seteá ALLOW_DB_WIPE=1 sólo si estás 100% seguro.")
        sys.exit(1)


_check_not_production()
# --- fin guardia ---

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
