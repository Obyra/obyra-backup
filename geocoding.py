"""
Módulo de geolocalización para OBYRA IA
Convierte direcciones en coordenadas geográficas usando Nominatim OpenStreetMap
"""

import requests
import time
from urllib.parse import urlencode

def geocodificar_direccion(direccion):
    """
    Convierte una dirección en coordenadas geográficas usando Nominatim
    
    Args:
        direccion (str): Dirección a geocodificar
        
    Returns:
        tuple: (latitud, longitud) o (None, None) si falla
    """
    if not direccion or direccion.strip() == '':
        return None, None
    
    try:
        # URL de Nominatim
        base_url = "https://nominatim.openstreetmap.org/search"
        
        # Parámetros de búsqueda
        params = {
            'q': direccion,
            'format': 'json',
            'limit': 1,
            'countrycodes': 'ar',  # Limitar a Argentina
            'addressdetails': 1
        }
        
        # Headers para identificarnos
        headers = {
            'User-Agent': 'OBYRA-IA/1.0 (https://obyra-ia.replit.app)'
        }
        
        # Hacer la petición
        url = f"{base_url}?{urlencode(params)}"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if data and len(data) > 0:
                resultado = data[0]
                latitud = float(resultado['lat'])
                longitud = float(resultado['lon'])
                
                print(f"✅ Geocodificado exitoso: {direccion} -> ({latitud}, {longitud})")
                return latitud, longitud
            else:
                print(f"❌ No se encontraron resultados para: {direccion}")
                return None, None
        else:
            print(f"❌ Error en la API de geocodificación: {response.status_code}")
            return None, None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error de conexión al geocodificar {direccion}: {e}")
        return None, None
    except Exception as e:
        print(f"❌ Error inesperado al geocodificar {direccion}: {e}")
        return None, None

def geocodificar_obras_existentes():
    """
    Geocodifica todas las obras que no tienen coordenadas
    """
    from app import db
    from models import Obra
    
    print("🗺️ Iniciando geocodificación de obras existentes...")
    
    # Buscar obras sin coordenadas
    obras_sin_coordenadas = Obra.query.filter(
        Obra.direccion.isnot(None),
        Obra.direccion != '',
        db.or_(
            Obra.latitud.is_(None),
            Obra.longitud.is_(None)
        )
    ).all()
    
    print(f"📍 Encontradas {len(obras_sin_coordenadas)} obras para geocodificar")
    
    geocodificadas = 0
    fallidas = 0
    
    for obra in obras_sin_coordenadas:
        print(f"🔍 Geocodificando: {obra.nombre} - {obra.direccion}")
        
        latitud, longitud = geocodificar_direccion(obra.direccion)
        
        if latitud and longitud:
            obra.latitud = latitud
            obra.longitud = longitud
            geocodificadas += 1
            print(f"✅ Obra geocodificada: {obra.nombre}")
        else:
            fallidas += 1
            print(f"❌ Falló geocodificación: {obra.nombre}")
        
        # Pausa para respetar límites de la API
        time.sleep(1)
    
    try:
        db.session.commit()
        print(f"💾 Cambios guardados en base de datos")
        print(f"📊 Resumen: {geocodificadas} exitosas, {fallidas} fallidas")
        return geocodificadas, fallidas
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error al guardar en base de datos: {e}")
        return 0, len(obras_sin_coordenadas)

def normalizar_direccion_argentina(direccion):
    """
    Normaliza direcciones argentinas para mejor geocodificación
    """
    if not direccion:
        return direccion
    
    # Agregar Argentina al final si no está presente
    direccion_lower = direccion.lower()
    if 'argentina' not in direccion_lower and 'buenos aires' not in direccion_lower:
        direccion += ', Argentina'
    
    return direccion