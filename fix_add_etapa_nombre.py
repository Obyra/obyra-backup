"""
Script de emergencia para agregar columna etapa_nombre en Railway.
Ejecutar con: railway run python fix_add_etapa_nombre.py
O desde local: python fix_add_etapa_nombre.py
"""

from app import app, db
from sqlalchemy import text
import sys

def add_etapa_nombre_column():
    """Agrega la columna etapa_nombre si no existe."""
    with app.app_context():
        try:
            # Verificar si la columna existe
            result = db.session.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'items_presupuesto'
                AND column_name = 'etapa_nombre'
            """))

            if result.fetchone():
                print("✅ La columna 'etapa_nombre' ya existe")
                return True

            # Agregar la columna
            print("🔧 Agregando columna 'etapa_nombre'...")
            db.session.execute(text("""
                ALTER TABLE items_presupuesto
                ADD COLUMN etapa_nombre VARCHAR(100)
            """))
            db.session.commit()

            print("✅ Columna 'etapa_nombre' agregada exitosamente!")

            # Verificar que se agregó
            result = db.session.execute(text("""
                SELECT column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'items_presupuesto'
                AND column_name = 'etapa_nombre'
            """))

            row = result.fetchone()
            if row:
                print(f"✅ Verificado: {row[0]} ({row[1]}, max: {row[2]})")
                return True
            else:
                print("❌ Error: No se pudo verificar la columna")
                return False

        except Exception as e:
            print(f"❌ Error: {e}")
            db.session.rollback()
            return False

if __name__ == "__main__":
    print("=" * 60)
    print("Fix: Agregar columna etapa_nombre a items_presupuesto")
    print("=" * 60)

    success = add_etapa_nombre_column()

    if success:
        print("\n✅ ¡Éxito! Ya puedes crear presupuestos.")
        sys.exit(0)
    else:
        print("\n❌ Error al agregar la columna. Ver logs arriba.")
        sys.exit(1)
