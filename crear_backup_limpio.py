#!/usr/bin/env python3
"""
Script para crear un backup limpio del proyecto OBYRA IA
Excluye archivos problemáticos y directorios temporales
"""

import os
import zipfile
import fnmatch
from datetime import datetime

def crear_backup_limpio():
    """Crea un archivo ZIP limpio del proyecto"""
    
    # Nombre del archivo de backup con timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"obyra_backup_{timestamp}.zip"
    
    # Directorios y archivos a excluir
    excluidos = [
        '__pycache__',
        '*.pyc',
        '*.pyo',
        '.cache',
        '.pythonlibs',
        'instance',
        'uploads',
        '*.db',
        '*.sqlite',
        '.git',
        '.gitignore',
        'node_modules',
        'attached_assets',  # Excluir assets adjuntos para reducir tamaño
        'google.get*',      # Excluir archivos problemáticos
        '*userinfo*'
    ]
    
    def debe_excluir(ruta):
        """Verifica si un archivo/directorio debe ser excluido"""
        for patron in excluidos:
            if fnmatch.fnmatch(os.path.basename(ruta), patron) or fnmatch.fnmatch(ruta, patron):
                return True
        return False
    
    archivos_incluidos = []
    
    try:
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk('.'):
                # Filtrar directorios
                dirs[:] = [d for d in dirs if not debe_excluir(os.path.join(root, d))]
                
                for file in files:
                    ruta_completa = os.path.join(root, file)
                    ruta_relativa = os.path.relpath(ruta_completa, '.')
                    
                    # Excluir archivos problemáticos
                    if not debe_excluir(ruta_completa) and not debe_excluir(file):
                        try:
                            zipf.write(ruta_completa, ruta_relativa)
                            archivos_incluidos.append(ruta_relativa)
                            print(f"✓ Incluido: {ruta_relativa}")
                        except Exception as e:
                            print(f"✗ Error al incluir {ruta_relativa}: {e}")
                    else:
                        print(f"⚠ Excluido: {ruta_relativa}")
        
        print(f"\n🎉 Backup creado exitosamente: {zip_filename}")
        print(f"📁 Total de archivos incluidos: {len(archivos_incluidos)}")
        print(f"📦 Tamaño del archivo: {os.path.getsize(zip_filename) / 1024 / 1024:.2f} MB")
        
        return zip_filename
        
    except Exception as e:
        print(f"❌ Error al crear backup: {e}")
        return None

if __name__ == "__main__":
    crear_backup_limpio()