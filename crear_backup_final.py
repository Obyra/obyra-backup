#!/usr/bin/env python3
"""
Script para crear un backup limpio y funcional del proyecto OBYRA IA
"""

import os
import zipfile
import fnmatch
from datetime import datetime

def crear_backup_limpio():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"obyra_limpio_{timestamp}.zip"
    
    # Solo incluir archivos esenciales del proyecto
    archivos_esenciales = [
        '*.py',           # Todos los archivos Python
        '*.html',         # Templates
        '*.css',          # Estilos
        '*.js',           # JavaScript
        '*.md',           # Documentación
        '*.toml',         # Configuración
        '*.lock',         # Dependencias
        '.replit'         # Configuración Replit
    ]
    
    # Directorios importantes
    directorios_incluir = [
        'templates',
        'static', 
        'static/css',
        'static/js',
        'static/img'
    ]
    
    def es_archivo_esencial(archivo):
        for patron in archivos_esenciales:
            if fnmatch.fnmatch(archivo, patron):
                return True
        return False
    
    def es_directorio_valido(directorio):
        # Excluir directorios problemáticos
        excluidos = ['__pycache__', '.cache', '.pythonlibs', 'instance', 'uploads', '.git', 'attached_assets']
        return not any(exc in directorio for exc in excluidos)
    
    archivos_incluidos = []
    
    try:
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Incluir archivos de la raíz
            for archivo in os.listdir('.'):
                if os.path.isfile(archivo) and es_archivo_esencial(archivo):
                    try:
                        zipf.write(archivo, archivo)
                        archivos_incluidos.append(archivo)
                        print(f"✓ {archivo}")
                    except Exception as e:
                        print(f"✗ Error con {archivo}: {e}")
            
            # Incluir directorios importantes
            for root, dirs, files in os.walk('.'):
                # Filtrar directorios válidos
                if not es_directorio_valido(root):
                    continue
                    
                for archivo in files:
                    if es_archivo_esencial(archivo):
                        ruta_completa = os.path.join(root, archivo)
                        ruta_relativa = os.path.relpath(ruta_completa, '.')
                        
                        try:
                            zipf.write(ruta_completa, ruta_relativa)
                            archivos_incluidos.append(ruta_relativa)
                            print(f"✓ {ruta_relativa}")
                        except Exception as e:
                            print(f"✗ Error con {ruta_relativa}: {e}")
        
        # Verificar integridad
        with zipfile.ZipFile(zip_filename, 'r') as zipf:
            bad_file = zipf.testzip()
            if bad_file:
                print(f"❌ Archivo corrupto: {bad_file}")
                return None
        
        tamaño_mb = os.path.getsize(zip_filename) / 1024 / 1024
        print(f"\n🎉 Backup limpio creado: {zip_filename}")
        print(f"📁 Archivos incluidos: {len(archivos_incluidos)}")
        print(f"📦 Tamaño: {tamaño_mb:.2f} MB")
        print(f"✅ Integridad verificada")
        
        return zip_filename
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

if __name__ == "__main__":
    crear_backup_limpio()