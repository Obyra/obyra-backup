#!/usr/bin/env python3
"""
Script para configurar acceso de administrador completo
"""

from app import create_app
from app.extensions import db

app = create_app()
from models import Usuario

def configurar_admin_completo():
    with app.app_context():
        print("🔧 Configurando acceso de administrador completo...")
        
        # Buscar todos los usuarios administradores
        admins = Usuario.query.filter_by(rol='administrador').all()
        
        if not admins:
            print("❌ No se encontraron usuarios administradores")
            return
        
        print(f"👥 Encontrados {len(admins)} administradores:")
        
        for admin in admins:
            print(f"   📧 {admin.email} - {admin.nombre} {admin.apellido}")
            
            # Actualizar plan a admin_completo
            admin.plan_activo = 'admin_completo'
            
            print(f"   ✅ Plan actualizado a: {admin.plan_activo}")
            print(f"   🔓 Acceso completo: {admin.es_admin_completo()}")
            print()
        
        # Guardar cambios
        db.session.commit()
        print("💾 Cambios guardados en la base de datos")
        
        # Verificar configuración final
        print("\n🎯 Configuración final:")
        for admin in admins:
            print(f"   {admin.email}: Plan {admin.plan_activo} | Acceso completo: {admin.es_admin_completo()}")

if __name__ == "__main__":
    configurar_admin_completo()