#!/usr/bin/env python3
"""
Script para limpiar la base de datos usando SET CONSTRAINTS DEFERRED
Esto permite eliminar registros sin preocuparse por el orden de las FK
"""
import os
os.environ['DATABASE_URL'] = 'postgresql+psycopg://obyra:obyra_dev_password@localhost:5436/obyra_dev'
os.environ['ALEMBIC_DATABASE_URL'] = 'postgresql+psycopg://obyra_migrator:migrator_dev_password@localhost:5436/obyra_dev'


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
from models import Usuario
from extensions import db

print("=" * 80)
print("LIMPIEZA FORZADA DE BASE DE DATOS")
print("=" * 80)
print()

with app.app_context():
    try:
        # Identificar super administrador
        super_admin = Usuario.query.filter_by(is_super_admin=True).first()
        if not super_admin:
            super_admin = Usuario.query.filter_by(email='admin@obyra.com').first()

        if not super_admin:
            print("❌ ERROR: No se encontró super administrador")
            exit(1)

        super_admin_id = super_admin.id
        super_admin_org_id = db.session.execute(
            db.text(f"SELECT organization_id FROM org_memberships WHERE user_id = {super_admin_id} LIMIT 1")
        ).scalar()

        print(f"🔒 Super admin: {super_admin.email} (ID: {super_admin_id}, Org: {super_admin_org_id})")
        print()

        print("🗑️  Eliminando TODOS los datos excepto super admin...")
        print()

        # Obtener lista de todas las tablas
        result = db.session.execute(db.text("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename NOT IN ('alembic_version', 'organizaciones')
            ORDER BY tablename
        """))

        todas_tablas = [row[0] for row in result]

        # Usar TRUNCATE CASCADE para la mayoría de las tablas
        tablas_a_truncar = [t for t in todas_tablas if t not in ['usuarios', 'clientes', 'obras', 'presupuestos', 'org_memberships']]

        for tabla in tablas_a_truncar:
            try:
                db.session.execute(db.text(f"TRUNCATE TABLE {tabla} RESTART IDENTITY CASCADE"))
                print(f"✅ {tabla}: TRUNCATED")
            except Exception as e:
                print(f"⚠️  {tabla}: {str(e)[:80]}")

        # Eliminar registros específicos preservando super admin
        tablas_especificas = [
            (f"DELETE FROM presupuestos WHERE organizacion_id != {super_admin_org_id} OR organizacion_id IS NULL", 'presupuestos (otros)'),
            (f"DELETE FROM presupuestos WHERE organizacion_id = {super_admin_org_id}", 'presupuestos (org admin)'),
            (f"DELETE FROM clientes WHERE organizacion_id != {super_admin_org_id} OR organizacion_id IS NULL", 'clientes (otros)'),
            (f"DELETE FROM clientes WHERE organizacion_id = {super_admin_org_id}", 'clientes (org admin)'),
            (f"DELETE FROM obras WHERE organizacion_id != {super_admin_org_id} OR organizacion_id IS NULL", 'obras (otros)'),
            (f"DELETE FROM obras WHERE organizacion_id = {super_admin_org_id}", 'obras (org admin)'),
            (f"DELETE FROM org_memberships WHERE user_id != {super_admin_id}", 'memberships (otros usuarios)'),
            (f"DELETE FROM usuarios WHERE id != {super_admin_id}", 'usuarios (todos excepto super admin)'),
        ]

        for sql, nombre in tablas_especificas:
            try:
                result = db.session.execute(db.text(sql))
                print(f"✅ {nombre}: {result.rowcount} eliminados")
            except Exception as e:
                print(f"⚠️  {nombre}: {str(e)[:80]}")

        # Commit
        db.session.commit()

        print()
        print("=" * 80)
        print("LIMPIEZA COMPLETADA")
        print("=" * 80)
        print()
        print(f"🔒 Super admin preservado: {super_admin.email}")
        print()

        # Verificar
        print("📊 Verificación final:")
        for modelo, nombre in [(Usuario, 'Usuarios'), (Obra, 'Obras'), (Cliente, 'Clientes'), (Presupuesto, 'Presupuestos')]:
            try:
                from models import Presupuesto, Cliente, Obra
                count = modelo.query.count()
                print(f"   - {nombre}: {count}")
            except:
                pass

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}\n")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        exit(1)
