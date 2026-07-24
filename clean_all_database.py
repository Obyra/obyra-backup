#!/usr/bin/env python3
"""
Script para eliminar ABSOLUTAMENTE TODO excepto:
- Super admin (admin@obyra.com)
- Su organización
- Su membresía
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
from models import Usuario, Organizacion
from extensions import db

print("=" * 80)
print("LIMPIEZA TOTAL DE BASE DE DATOS")
print("=" * 80)
print()

with app.app_context():
    # Identificar super admin y su organización
    super_admin = Usuario.query.filter_by(is_super_admin=True).first()
    if not super_admin:
        super_admin = Usuario.query.filter_by(email='admin@obyra.com').first()

    if not super_admin:
        print("❌ No se encontró super administrador")
        exit(1)

    # Obtener la organización del super admin
    super_admin_org = db.session.execute(
        db.text(f"SELECT org_id FROM org_memberships WHERE user_id = {super_admin.id} LIMIT 1")
    ).scalar()

    print(f"🔒 Super admin: {super_admin.email} (ID: {super_admin.id})")
    print(f"🏢 Organización del admin: ID {super_admin_org}")
    print()
    print("🗑️  Eliminando TODO excepto el super admin y su organización...")
    print()

    # Deshabilitar triggers y constraints temporalmente
    db.session.execute(db.text("SET session_replication_role = 'replica'"))

    # Lista de TODAS las tablas a limpiar completamente
    tablas_completas = [
        'tarea_avances',
        'tareas_etapa',
        'items_presupuesto',
        'presupuestos',
        'etapas_obra',
        'obra_miembros',
        'uso_inventario',
        'equipment_assignment',
        'equipment_usage',
        'events',
        'configuraciones_inteligentes',
        'certificaciones_avance',
        'work_certifications',
        'documentos_obra',
        'checklists_seguridad',
        'incidentes_seguridad',
        'auditorias_seguridad',
        'asignaciones_obra',
        'stock_movement',
        'stock_reservation',
        'work_payments',
        'reservas_stock',
        'movimientos_stock_obra',
        'stock_obra',
        'locations',
        'requerimientos_compra',
        'obras',
        'clientes',
        'perfiles_usuario',
        'onboarding_status',
        'billing_profiles',
        'user_modules',
        'movimientos_inventario',
        'maintenance_task',
        'solicitudes_cotizacion',
        'product_qna',
        'cart',
        'consultas_agente',
        'certificaciones_personal',
        'items_inventario',
        'categorias_inventario',
        'solicitudes_compra',
        'ordenes_compra',
    ]

    # Eliminar TODO de estas tablas
    for tabla in tablas_completas:
        try:
            result = db.session.execute(db.text(f"DELETE FROM {tabla}"))
            db.session.commit()  # Commit después de cada tabla
            print(f"✅ {tabla}: {result.rowcount} eliminados")
        except Exception as e:
            print(f"⚠️  {tabla}: {str(e)[:80]}")
            db.session.rollback()  # Rollback y continuar

    # Eliminar membresías de otros usuarios
    try:
        result = db.session.execute(db.text(f"DELETE FROM org_memberships WHERE user_id != {super_admin.id}"))
        db.session.commit()
        print(f"✅ org_memberships: {result.rowcount} eliminados")
    except Exception as e:
        print(f"⚠️  org_memberships: {str(e)[:80]}")
        db.session.rollback()

    # Eliminar usuarios excepto super admin
    try:
        result = db.session.execute(db.text(f"DELETE FROM usuarios WHERE id != {super_admin.id}"))
        db.session.commit()
        print(f"✅ usuarios: {result.rowcount} eliminados")
    except Exception as e:
        print(f"⚠️  usuarios: {str(e)[:80]}")
        db.session.rollback()

    # Eliminar organizaciones excepto la del super admin
    if super_admin_org:
        try:
            result = db.session.execute(db.text(f"DELETE FROM organizaciones WHERE id != {super_admin_org}"))
            db.session.commit()
            print(f"✅ organizaciones: {result.rowcount} eliminadas")
        except Exception as e:
            print(f"⚠️  organizaciones: {str(e)[:80]}")
            db.session.rollback()
    else:
        print("⚠️  No se pudo identificar organización del admin, no se eliminan organizaciones")

    # Re-habilitar triggers
    db.session.execute(db.text("SET session_replication_role = 'origin'"))
    db.session.commit()

    print()
    print("=" * 80)
    print("LIMPIEZA TOTAL COMPLETADA")
    print("=" * 80)
    print()

    # Verificar resultado
    print("📊 Resultado final:")
    print(f"   - Usuarios: {Usuario.query.count()}")
    print(f"   - Organizaciones: {Organizacion.query.count()}")
    print(f"   - Super admin: {super_admin.email}")
    print()
