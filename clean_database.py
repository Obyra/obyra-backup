#!/usr/bin/env python3
"""
Script para limpiar la base de datos
- Elimina todos los presupuestos y sus dependencias
- Elimina todos los clientes
- Elimina todos los usuarios EXCEPTO el super administrador
"""
import os
# Forzar el puerto correcto antes de importar app
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
print("LIMPIEZA DE BASE DE DATOS")
print("=" * 80)
print()

with app.app_context():
    try:
        # Identificar super administrador PRIMERO
        super_admin = Usuario.query.filter_by(is_super_admin=True).first()
        if not super_admin:
            print("⚠️  No se encontró super administrador, buscando admin@obyra.com")
            super_admin = Usuario.query.filter_by(email='admin@obyra.com').first()

        if not super_admin:
            print("❌ ERROR: No se encontró super administrador")
            print("   No se eliminarán datos para evitar quedar sin acceso")
            exit(1)

        super_admin_id = super_admin.id
        print(f"🔒 Super admin identificado: {super_admin.email} (ID: {super_admin_id})")
        print()

        # Lista de tablas a limpiar en orden (de dependencias a principales)
        tablas_limpiar = [
            ('tarea_avances', None),
            ('tareas_etapa', None),
            ('items_presupuesto', None),
            ('presupuestos', None),
            # Tablas relacionadas con obras
            ('etapas_obra', None),
            ('obra_miembros', None),
            ('uso_inventario', None),
            ('equipment_assignment', None),
            ('equipment_usage', None),
            ('events', None),
            ('configuraciones_inteligentes', None),
            ('certificaciones_avance', None),
            ('work_certifications', None),
            ('documentos_obra', None),
            ('checklists_seguridad', None),
            ('incidentes_seguridad', None),
            ('auditorias_seguridad', None),
            ('asignaciones_obra', None),
            ('stock_movement', None),
            ('stock_reservation', None),
            ('work_payments', None),
            ('reservas_stock', None),
            ('movimientos_stock_obra', None),
            ('stock_obra', None),
            ('locations', None),
            ('requerimientos_compra', None),
            ('obras', None),  # Obras
            ('clientes', None),  # Clientes
            # Tablas relacionadas con usuarios
            ('perfiles_usuario', f'usuario_id != {super_admin_id}'),
            ('onboarding_status', f'usuario_id != {super_admin_id}'),
            ('billing_profiles', f'usuario_id != {super_admin_id}'),
            ('user_modules', f'user_id != {super_admin_id}'),
            ('movimientos_inventario', f'usuario_id != {super_admin_id}'),
            ('maintenance_task', f'created_by != {super_admin_id}'),
            ('solicitudes_cotizacion', f'solicitante_id != {super_admin_id}'),
            ('product_qna', f'user_id != {super_admin_id}'),
            ('cart', f'user_id != {super_admin_id}'),
            ('consultas_agente', f'usuario_id != {super_admin_id}'),
            ('certificaciones_personal', f'usuario_id != {super_admin_id}'),
            ('org_memberships', f'user_id != {super_admin_id}'),
            ('usuarios', f'id != {super_admin_id}'),
        ]

        resultados = {}

        for tabla, condicion in tablas_limpiar:
            try:
                if condicion:
                    sql = f"DELETE FROM {tabla} WHERE {condicion}"
                else:
                    sql = f"DELETE FROM {tabla}"

                result = db.session.execute(db.text(sql))
                count = result.rowcount
                resultados[tabla] = count
                # Commit inmediatamente después de cada tabla exitosa
                db.session.commit()
                print(f"✅ {tabla}: {count} registros eliminados")

            except Exception as e:
                print(f"⚠️  {tabla}: Error - {str(e)[:100]}")
                resultados[tabla] = f"Error: {str(e)[:50]}"
                # Rollback y continuar
                db.session.rollback()

        print()
        print("=" * 80)
        print("LIMPIEZA COMPLETADA")
        print("=" * 80)
        print()
        print(f"📊 Resumen:")
        for tabla, resultado in resultados.items():
            if isinstance(resultado, int):
                print(f"   - {tabla}: {resultado} eliminados")
            else:
                print(f"   - {tabla}: {resultado}")
        print()
        print(f"🔒 Super admin preservado: {super_admin.email}")
        print()

    except Exception as e:
        print()
        print(f"❌ ERROR CRÍTICO durante la limpieza: {str(e)}")
        print()
        import traceback
        traceback.print_exc()
        db.session.rollback()
        exit(1)
