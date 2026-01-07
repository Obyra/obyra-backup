"""Geocoding helpers for resolving addresses with caching support."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from flask import current_app

from extensions import db
from models import GeocodeCache

# Usar Google Maps si está configurado, sino Nominatim como fallback
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
DEFAULT_PROVIDER = "google" if GOOGLE_MAPS_API_KEY else "nominatim"
DEFAULT_USER_AGENT = os.environ.get("MAPS_USER_AGENT", "OBYRA-IA/1.0 (+https://obyra.com)")
DEFAULT_TIMEOUT = 10
CACHE_TTL_SECONDS = int(os.environ.get("GEOCODE_CACHE_TTL", "86400"))  # 24h


@dataclass
class GeocodeResult:
    display_name: str
    lat: float
    lng: float
    provider: str
    place_id: Optional[str] = None
    normalized: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None
    status: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "display_name": self.display_name,
            "lat": self.lat,
            "lng": self.lng,
            "provider": self.provider,
            "place_id": self.place_id,
            "normalized": self.normalized or _normalize_query(self.display_name),
            "raw": self.raw,
            "status": self.status,
        }


def _normalize_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def _normalize_argentina_address(query: str) -> str:
    """
    Normaliza direcciones argentinas para mejorar precisión de búsqueda.
    Agrega contexto geográfico si no está presente.
    """
    if not query:
        return query

    query = query.strip()
    query_lower = query.lower()

    # Si ya tiene "argentina", retornar tal cual
    if "argentina" in query_lower:
        return query

    # Mapa de abreviaturas comunes a nombres completos
    abreviaturas = {
        "hur": "hurlingham",
        "hurli": "hurlingham",
        "san mar": "san martin",
        "vic lop": "vicente lopez",
        "v lop": "vicente lopez",
        "v lopez": "vicente lopez",
        "la mat": "la matanza",
        "lomas": "lomas de zamora",
        "avel": "avellaneda",
        "quilm": "quilmes",
        "lan": "lanus",
        "mor": "moron",
        "itu": "ituzaingo",
        "s isid": "san isidro",
        "san isi": "san isidro",
        "tig": "tigre",
        "s fer": "san fernando",
        "san fer": "san fernando",
        "esc": "escobar",
        "pil": "pilar",
        "mor": "moreno",
        "merl": "merlo",
        "bera": "berazategui",
        "f var": "florencio varela",
        "flo var": "florencio varela",
        "ez": "ezeiza",
        "ciud": "ciudadela",
        "ram": "ramos mejia",
        "r mejia": "ramos mejia",
        "cast": "castelar",
        "hae": "haedo",
        "mart": "martinez",
        "mun": "munro",
        "flo": "florida",
        "oli": "olivos",
        "bou": "boulogne",
        "s mig": "san miguel",
        "san mig": "san miguel",
        "bell vist": "bella vista",
        "b vista": "bella vista",
        "cord": "cordoba",
        "ros": "rosario",
        "mdq": "mar del plata",
        "mza": "mendoza",
        "tuc": "tucuman",
        "lp": "la plata",
    }

    # Expandir abreviaturas
    for abrev, completo in abreviaturas.items():
        # Buscar abreviatura como palabra completa o al final después de coma
        import re
        # Patrón: abreviatura al final, posiblemente después de coma/espacio
        pattern = r'(.*?)[\s,]+(' + re.escape(abrev) + r')[\s,]*$'
        match = re.search(pattern, query_lower)
        if match:
            parte_antes = match.group(1)
            query = f"{parte_antes}, {completo}"
            query_lower = query.lower()
            break

    # Mapeo de localidades a sus partidos del GBA (para mejorar precision)
    # Esto ayuda a Nominatim a encontrar la ubicacion correcta
    localidades_a_partidos = {
        "caseros": "Tres de Febrero",
        "ciudadela": "Tres de Febrero",
        "santos lugares": "Tres de Febrero",
        "saenz peña": "Tres de Febrero",
        "martin coronado": "Tres de Febrero",
        "villa bosch": "Tres de Febrero",
        "pablo podesta": "Tres de Febrero",
        "loma hermosa": "Tres de Febrero",
        "el libertador": "Tres de Febrero",
        "churruca": "Tres de Febrero",
        "ramos mejia": "La Matanza",
        "haedo": "Moron",
        "castelar": "Moron",
        "el palomar": "Moron",
        "villa sarmiento": "Moron",
        "villa luzuriaga": "La Matanza",
        "san justo": "La Matanza",
        "isidro casanova": "La Matanza",
        "gonzalez catan": "La Matanza",
        "laferrere": "La Matanza",
        "villa ballester": "General San Martin",
        "villa adelina": "San Fernando",
        "munro": "Vicente Lopez",
        "florida": "Vicente Lopez",
        "olivos": "Vicente Lopez",
        "martinez": "San Isidro",
        "beccar": "San Isidro",
        "villa martelli": "Vicente Lopez",
        "villa lynch": "General San Martin",
        "don torcuato": "Tigre",
        "boulogne": "San Isidro",
        "bella vista": "San Miguel",
        "jose c paz": "Jose C. Paz",
        "jose c. paz": "Jose C. Paz",
        "grand bourg": "Malvinas Argentinas",
        "pablo nogues": "Malvinas Argentinas",
        "tortuguitas": "Malvinas Argentinas",
        "la reja": "Moreno",
        "benavidez": "Tigre",
        "pacheco": "Tigre",
        "general pacheco": "Tigre",
        "carapachay": "Vicente Lopez",
        "muniz": "San Miguel",
        "derqui": "Pilar",
        "del viso": "Pilar",
        "william morris": "Hurlingham",
        "villa tesei": "Hurlingham",
        "temperley": "Lomas de Zamora",
        "banfield": "Lomas de Zamora",
        "lanus este": "Lanus",
        "lanus oeste": "Lanus",
        "remedios de escalada": "Lanus",
        "valentin alsina": "Lanus",
        "gerli": "Avellaneda",
        "wilde": "Avellaneda",
        "sarandi": "Avellaneda",
        "dock sud": "Avellaneda",
        "bernal": "Quilmes",
        "ezpeleta": "Quilmes",
        "berazategui": "Berazategui",
        "hudson": "Berazategui",
        "ranelagh": "Berazategui",
        "platanos": "Berazategui",
        "claypole": "Almirante Brown",
        "burzaco": "Almirante Brown",
        "adrogue": "Almirante Brown",
        "longchamps": "Almirante Brown",
        "monte grande": "Esteban Echeverria",
        "ezeiza": "Ezeiza",
        "canning": "Esteban Echeverria",
        "luis guillon": "Esteban Echeverria",
        "tristan suarez": "Ezeiza",
    }

    # Lista de partidos/localidades comunes de Buenos Aires (expandida)
    partidos_ba = [
        "tres de febrero", "caseros", "san martin", "vicente lopez", "la matanza",
        "lomas de zamora", "quilmes", "avellaneda", "lanus", "moron", "ituzaingo",
        "hurlingham", "san isidro", "tigre", "san fernando", "escobar", "pilar",
        "moreno", "merlo", "general rodriguez", "lujan", "campana", "zarate",
        "berazategui", "florencio varela", "almirante brown", "esteban echeverria",
        "ezeiza", "san vicente", "cañuelas", "brandsen", "marcos paz", "ciudadela",
        "ramos mejia", "haedo", "castelar", "villa luzuriaga", "villa sarmiento",
        "santos lugares", "saenz peña", "martin coronado", "villa bosch", "pablo podesta",
        "villa ballester", "villa adelina", "munro", "florida", "olivos", "martinez",
        "beccar", "san isidro", "villa martelli", "villa lynch", "don torcuato",
        "boulogne", "san miguel", "bella vista", "jose c paz", "malvinas argentinas",
        "grand bourg", "pablo nogues", "tortuguitas", "la reja", "ciudadela",
        "benavidez", "pacheco", "carapachay", "muniz", "derqui"
    ]

    # Verificar si menciona alguna localidad que podemos mapear a su partido
    for localidad, partido in localidades_a_partidos.items():
        if localidad in query_lower:
            # Reemplazar solo la localidad por "localidad, partido"
            import re
            # Buscar la localidad y agregar el partido
            pattern = r'\b' + re.escape(localidad) + r'\b'
            # Verificar si ya tiene el partido mencionado
            if partido.lower() not in query_lower:
                query = re.sub(pattern, f"{localidad.title()}, {partido}", query, flags=re.IGNORECASE)
                query_lower = query.lower()
            break

    # Provincias y ciudades importantes
    provincias_ciudades = [
        "cordoba", "rosario", "santa fe", "mendoza", "tucuman", "salta",
        "la plata", "mar del plata", "neuquen", "parana", "resistencia",
        "corrientes", "posadas", "formosa", "rio gallegos", "ushuaia",
        "san juan", "san luis", "catamarca", "la rioja", "santiago del estero",
        "jujuy", "santa rosa", "rawson", "viedma", "bahia blanca"
    ]

    # Verificar si menciona algún partido/localidad de Buenos Aires
    tiene_partido_ba = any(partido in query_lower for partido in partidos_ba)

    # Verificar si menciona provincia/ciudad
    tiene_provincia = any(provincia in query_lower for provincia in provincias_ciudades)

    # Si menciona un partido de Buenos Aires, agregar "Buenos Aires, Argentina"
    if tiene_partido_ba:
        return f"{query}, Buenos Aires, Argentina"

    # Si menciona "buenos aires" explícitamente
    if "buenos aires" in query_lower:
        return f"{query}, Argentina"

    # Si menciona una provincia/ciudad, agregar solo "Argentina"
    if tiene_provincia:
        return f"{query}, Argentina"

    # Por defecto, asumir que es de Buenos Aires (la mayoría de construcciones están ahí)
    return f"{query}, Buenos Aires, Argentina"


def _expand_common_street_names(query: str) -> str:
    """
    Expande nombres de calles comunes que tienen nombres oficiales largos.
    Por ejemplo: "Av San Martin" en muchos partidos del GBA es en realidad
    "Avenida del Libertador General José de San Martín".
    """
    import re
    result = query.strip()
    query_lower = result.lower()

    # Mapeo de nombres comunes a nombres oficiales (con variantes)
    # Formato: (patron_regex, reemplazo)
    calles_comunes = [
        # San Martin - muy comun en GBA
        (r'\b(av\.?|avenida)\s+(san\s+martin|san\s+martín)\b',
         'Avenida del Libertador General José de San Martín', re.IGNORECASE),

        # Rivadavia
        (r'\b(av\.?|avenida)\s+rivadavia\b',
         'Avenida Rivadavia', re.IGNORECASE),

        # Corrientes
        (r'\b(av\.?|avenida)\s+corrientes\b',
         'Avenida Corrientes', re.IGNORECASE),

        # Santa Fe
        (r'\b(av\.?|avenida)\s+santa\s+fe\b',
         'Avenida Santa Fe', re.IGNORECASE),

        # Cabildo
        (r'\b(av\.?|avenida)\s+cabildo\b',
         'Avenida Cabildo', re.IGNORECASE),

        # Libertador
        (r'\b(av\.?|avenida)\s+(del\s+)?libertador\b',
         'Avenida del Libertador', re.IGNORECASE),

        # 9 de Julio
        (r'\b(av\.?|avenida)\s+9\s+de\s+julio\b',
         'Avenida 9 de Julio', re.IGNORECASE),

        # Belgrano
        (r'\b(av\.?|avenida)\s+belgrano\b',
         'Avenida Belgrano', re.IGNORECASE),

        # Maipu
        (r'\b(av\.?|avenida)\s+maipu\b',
         'Avenida Maipú', re.IGNORECASE),

        # Ruta 8
        (r'\bruta\s+8\b', 'Ruta Nacional 8', re.IGNORECASE),
        (r'\bruta\s+nacional\s+8\b', 'Ruta Nacional 8', re.IGNORECASE),

        # Acceso Oeste
        (r'\bacceso\s+oeste\b', 'Acceso Oeste', re.IGNORECASE),

        # Panamericana
        (r'\bpanamericana\b', 'Autopista Panamericana', re.IGNORECASE),
    ]

    for pattern, replacement, flags in calles_comunes:
        if re.search(pattern, result, flags=flags):
            # Extraer el numero de altura si existe
            match_altura = re.search(r'\b(\d{2,5})\b', result)
            altura = match_altura.group(1) if match_altura else None

            # Extraer localidad (despues de la coma)
            match_localidad = re.search(r',\s*(.+)$', result)
            localidad = match_localidad.group(1) if match_localidad else None

            # Construir direccion expandida
            result = replacement
            if altura:
                result = f"{result} {altura}"
            if localidad:
                result = f"{result}, {localidad}"

            break  # Solo aplicar la primera coincidencia

    return result


def _expand_abbreviations(query: str) -> str:
    """
    Expande abreviaturas comunes de calles argentinas.
    """
    import re

    # Primero intentar expandir nombres de calles comunes
    result = _expand_common_street_names(query)

    # Abreviaturas de tipos de via (orden importa - mas especificas primero)
    abreviaturas_via = [
        # Avenida - varias formas
        (r'\bav\.?\s+', 'Avenida ', re.IGNORECASE),
        (r'\bavda\.?\s+', 'Avenida ', re.IGNORECASE),
        (r'\bavenida\s+', 'Avenida ', re.IGNORECASE),
        # Boulevard
        (r'\bbv\.?\s+', 'Boulevard ', re.IGNORECASE),
        (r'\bblvd\.?\s+', 'Boulevard ', re.IGNORECASE),
        (r'\bboul\.?\s+', 'Boulevard ', re.IGNORECASE),
        # Calle
        (r'\bclle\.?\s+', 'Calle ', re.IGNORECASE),
        # Pasaje
        (r'\bpje\.?\s+', 'Pasaje ', re.IGNORECASE),
        (r'\bpsje\.?\s+', 'Pasaje ', re.IGNORECASE),
        # Diagonal
        (r'\bdiag\.?\s+', 'Diagonal ', re.IGNORECASE),
    ]

    # Abreviaturas de titulos/rangos militares
    abreviaturas_titulos = [
        (r'\bgral\.?\s+', 'General ', re.IGNORECASE),
        (r'\bgeneral\s+', 'General ', re.IGNORECASE),
        (r'\bgen\.?\s+', 'General ', re.IGNORECASE),
        (r'\bgte\.?\s+', 'General ', re.IGNORECASE),
        (r'\bcnel\.?\s+', 'Coronel ', re.IGNORECASE),
        (r'\bcte\.?\s+', 'Comandante ', re.IGNORECASE),
        (r'\bcap\.?\s+', 'Capitan ', re.IGNORECASE),
        (r'\btte\.?\s+', 'Teniente ', re.IGNORECASE),
        (r'\bsgto\.?\s+', 'Sargento ', re.IGNORECASE),
        (r'\balte\.?\s+', 'Almirante ', re.IGNORECASE),
        (r'\bcomod\.?\s+', 'Comodoro ', re.IGNORECASE),
        (r'\bbrig\.?\s+', 'Brigadier ', re.IGNORECASE),
    ]

    # Abreviaturas de titulos civiles
    abreviaturas_civiles = [
        (r'\bdr\.?\s+', 'Doctor ', re.IGNORECASE),
        (r'\bdra\.?\s+', 'Doctora ', re.IGNORECASE),
        (r'\bing\.?\s+', 'Ingeniero ', re.IGNORECASE),
        (r'\blic\.?\s+', 'Licenciado ', re.IGNORECASE),
        (r'\bprof\.?\s+', 'Profesor ', re.IGNORECASE),
        (r'\bpte\.?\s+', 'Presidente ', re.IGNORECASE),
        (r'\bpresidente\s+', 'Presidente ', re.IGNORECASE),
        (r'\bintendente\s+', 'Intendente ', re.IGNORECASE),
        (r'\bint\.?\s+', 'Intendente ', re.IGNORECASE),
    ]

    # Abreviaturas religiosas/santos
    abreviaturas_santos = [
        (r'\bsta\.?\s+', 'Santa ', re.IGNORECASE),
        (r'\bsto\.?\s+', 'Santo ', re.IGNORECASE),
        (r'\bs\.?\s+', 'San ', re.IGNORECASE),  # Solo 's' seguido de espacio
    ]

    # Aplicar todas las expansiones
    for pattern, replacement, flags in (abreviaturas_via + abreviaturas_titulos +
                                         abreviaturas_civiles + abreviaturas_santos):
        result = re.sub(pattern, replacement, result, flags=flags)

    return result


def _generate_search_variants(query: str) -> List[str]:
    """
    Genera variantes de búsqueda para mejorar la tasa de éxito.
    Por ejemplo, si una dirección completa falla, intenta sin número de puerta.
    """
    import re

    # Primero expandir abreviaturas
    query_expanded = _expand_abbreviations(query)

    # Si la expansion cambio algo, poner la version expandida primero
    if query_expanded.lower() != query.lower():
        variants = [query_expanded, query]
    else:
        variants = [query]

    # Trabajar con la version expandida
    for base_query in [query_expanded]:
        # Si tiene número de puerta al inicio (ej: "1234 Calle Principal"), invertir
        match = re.match(r'^(\d+)\s+(.+)$', base_query.strip())
        if match:
            numero = match.group(1)
            resto = match.group(2)
            # Agregar variante sin número
            if resto not in variants:
                variants.append(resto)
            # Agregar variante con formato argentino (Calle Numero)
            variante_argentina = f"{resto} {numero}"
            if variante_argentina not in variants:
                variants.append(variante_argentina)

        # Si tiene formato "Calle Numero, Localidad", probar variantes
        match = re.match(r'^(.+?)\s+(\d+)\s*,\s*(.+)$', base_query.strip())
        if match:
            calle = match.group(1)
            numero = match.group(2)
            localidad = match.group(3)

            # Sin número
            variante = f"{calle}, {localidad}"
            if variante not in variants:
                variants.append(variante)

            # Calle con localidad, sin coma
            variante = f"{calle} {localidad}"
            if variante not in variants:
                variants.append(variante)

            # Número al final en lugar de en medio
            variante = f"{calle}, {numero}, {localidad}"
            if variante not in variants:
                variants.append(variante)

        # Si tiene altura (números al final), probar sin ellos
        match = re.match(r'^(.+?)\s+\d+\s*$', base_query.strip())
        if match:
            sin_altura = match.group(1)
            if sin_altura not in variants:
                variants.append(sin_altura)

    # Eliminar duplicados manteniendo el orden
    seen = set()
    unique_variants = []
    for v in variants:
        v_lower = v.lower().strip()
        if v_lower not in seen:
            seen.add(v_lower)
            unique_variants.append(v)

    return unique_variants


def _should_refresh(entry: GeocodeCache) -> bool:
    if CACHE_TTL_SECONDS <= 0:
        return False
    if not entry.updated_at:
        return True
    delta = datetime.utcnow() - entry.updated_at
    return delta.total_seconds() > CACHE_TTL_SECONDS


def _detect_localidad_gba(query: str) -> Optional[str]:
    """
    Detecta si la query menciona una localidad del GBA y retorna su nombre normalizado.
    Busca la localidad en cualquier posición de la query.
    """
    query_lower = query.lower()

    # Localidades del GBA con sus variantes (ordenadas por longitud descendente para evitar matches parciales)
    localidades_gba = {
        "villa ballester": "Villa Ballester, General San Martín",
        "isidro casanova": "Isidro Casanova, La Matanza",
        "martin coronado": "Martín Coronado, Tres de Febrero",
        "santos lugares": "Santos Lugares, Tres de Febrero",
        "florencio varela": "Florencio Varela, Buenos Aires",
        "monte grande": "Monte Grande, Esteban Echeverría",
        "lomas de zamora": "Lomas de Zamora, Buenos Aires",
        "william morris": "William Morris, Hurlingham",
        "vicente lopez": "Vicente López, Buenos Aires",
        "vicente lópez": "Vicente López, Buenos Aires",
        "villa adelina": "Villa Adelina, San Fernando",
        "don torcuato": "Don Torcuato, Tigre",
        "villa tesei": "Villa Tesei, Hurlingham",
        "paso del rey": "Paso del Rey, Moreno",
        "grand bourg": "Grand Bourg, Malvinas Argentinas",
        "bella vista": "Bella Vista, San Miguel",
        "jose c. paz": "José C. Paz, Buenos Aires",
        "jose c paz": "José C. Paz, Buenos Aires",
        "ramos mejía": "Ramos Mejía, La Matanza",
        "ramos mejia": "Ramos Mejía, La Matanza",
        "tortuguitas": "Tortuguitas, Malvinas Argentinas",
        "el palomar": "El Palomar, Morón",
        "san miguel": "San Miguel, Buenos Aires",
        "san isidro": "San Isidro, Buenos Aires",
        "san martin": "San Martín, General San Martín",
        "san martín": "San Martín, General San Martín",
        "san justo": "San Justo, La Matanza",
        "saenz peña": "Sáenz Peña, Tres de Febrero",
        "berazategui": "Berazategui, Buenos Aires",
        "hurlingham": "Hurlingham, Buenos Aires",
        "ituzaingo": "Ituzaingó, Buenos Aires",
        "ituzaingó": "Ituzaingó, Buenos Aires",
        "ciudadela": "Ciudadela, Tres de Febrero",
        "avellaneda": "Avellaneda, Buenos Aires",
        "temperley": "Temperley, Lomas de Zamora",
        "boulogne": "Boulogne, San Isidro",
        "martinez": "Martínez, San Isidro",
        "martínez": "Martínez, San Isidro",
        "caseros": "Caseros, Tres de Febrero",
        "quilmes": "Quilmes, Buenos Aires",
        "banfield": "Banfield, Lomas de Zamora",
        "adrogué": "Adrogué, Almirante Brown",
        "adrogue": "Adrogué, Almirante Brown",
        "escobar": "Escobar, Buenos Aires",
        "burzaco": "Burzaco, Almirante Brown",
        "castelar": "Castelar, Morón",
        "ezeiza": "Ezeiza, Buenos Aires",
        "moreno": "Moreno, Buenos Aires",
        "olivos": "Olivos, Vicente López",
        "beccar": "Beccar, San Isidro",
        "bernal": "Bernal, Quilmes",
        "florida": "Florida, Vicente López",
        "tigre": "Tigre, Buenos Aires",
        "pilar": "Pilar, Buenos Aires",
        "haedo": "Haedo, Morón",
        "moron": "Morón, Buenos Aires",
        "morón": "Morón, Buenos Aires",
        "lanus": "Lanús, Buenos Aires",
        "lanús": "Lanús, Buenos Aires",
        "merlo": "Merlo, Buenos Aires",
        "munro": "Munro, Vicente López",
    }

    import re
    # Ordenar por longitud descendente para evitar matches parciales (ej: "san martin" antes que "san")
    localidades_ordenadas = sorted(localidades_gba.items(), key=lambda x: len(x[0]), reverse=True)

    for localidad, nombre_completo in localidades_ordenadas:
        # Patrones más flexibles que detectan la localidad en cualquier posición:
        # 1. Después de coma: ",caseros" o ", caseros"
        # 2. Antes de coma: "caseros,"
        # 3. Como palabra independiente con word boundaries
        patterns = [
            r',\s*' + re.escape(localidad) + r'(?:\s*,|\s*$)',  # ",caseros," o ",caseros" al final
            r'\b' + re.escape(localidad) + r'\s*,',             # "caseros," con word boundary
            r',\s*' + re.escape(localidad) + r'\b',             # ", caseros" seguido de word boundary
        ]
        for pattern in patterns:
            if re.search(pattern, query_lower):
                return nombre_completo

    return None


def _fetch_google_maps(query: str, *, limit: int = 5) -> List[GeocodeResult]:
    """
    Busca direcciones usando Google Maps Geocoding API.
    Documentación: https://developers.google.com/maps/documentation/geocoding
    """
    if not GOOGLE_MAPS_API_KEY:
        current_app.logger.warning("Google Maps API Key no configurada")
        return []

    # Detectar si hay una localidad del GBA en la query
    localidad_detectada = _detect_localidad_gba(query)

    # Si detectamos una localidad, reformatear la query para ser más específica
    if localidad_detectada:
        import re
        # Extraer la parte de la dirección antes/después de la localidad
        localidad_key = localidad_detectada.split(",")[0].lower()  # "Caseros" -> "caseros"

        # Remover la localidad de la query para obtener solo calle y número
        # También remover "buenos aires" y "argentina" que pudo agregar _normalize_argentina_address
        direccion_base = query.strip()

        # Patrones a remover (en orden de más específico a menos)
        patrones_remover = [
            r',\s*buenos\s+aires\s*,\s*argentina\s*$',  # ", Buenos Aires, Argentina" al final
            r',\s*argentina\s*$',                        # ", Argentina" al final
            r',\s*' + re.escape(localidad_key) + r'\b',  # ", caseros"
            r'\b' + re.escape(localidad_key) + r'\s*,',  # "caseros,"
        ]

        for patron in patrones_remover:
            direccion_base = re.sub(patron, '', direccion_base, flags=re.IGNORECASE)

        direccion_base = direccion_base.strip().strip(',').strip()

        if direccion_base:
            # Construir query específica: "calle número, Localidad, Partido, Buenos Aires"
            query_mejorada = f"{direccion_base}, {localidad_detectada}, Buenos Aires, Argentina"
            current_app.logger.info(f"🎯 Localidad detectada: {localidad_detectada}")
            current_app.logger.info(f"🔄 Query original: {query}")
            current_app.logger.info(f"🔄 Query mejorada: {query_mejorada}")
            query = query_mejorada

    params = {
        "address": query,
        "key": GOOGLE_MAPS_API_KEY,
        "language": "es",
        "region": "ar",
        "components": "country:AR",
    }

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "REQUEST_DENIED":
            current_app.logger.error(f"Google Maps API denegada: {data.get('error_message', 'Sin mensaje')}")
            return []

        if data.get("status") == "ZERO_RESULTS":
            current_app.logger.info(f"Google Maps no encontró resultados para: {query}")
            return []

        if data.get("status") != "OK":
            current_app.logger.warning(f"Google Maps status: {data.get('status')} - {data.get('error_message', '')}")
            return []

        results: List[GeocodeResult] = []
        for item in data.get("results", [])[:limit]:
            try:
                geometry = item.get("geometry", {})
                location = geometry.get("location", {})
                lat = float(location.get("lat", 0))
                lng = float(location.get("lng", 0))

                if lat == 0 and lng == 0:
                    continue

                display_name = item.get("formatted_address", query)
                place_id = item.get("place_id")

                results.append(
                    GeocodeResult(
                        display_name=display_name,
                        lat=lat,
                        lng=lng,
                        provider="google",
                        place_id=place_id,
                        normalized=_normalize_query(display_name),
                        raw=item,
                    )
                )
            except (TypeError, ValueError) as e:
                current_app.logger.warning(f"Error procesando resultado de Google Maps: {e}")
                continue

        # Si teníamos una localidad detectada, priorizar resultados que la contengan
        if localidad_detectada and results:
            localidad_lower = localidad_detectada.split(",")[0].lower()
            resultados_priorizados = []
            otros_resultados = []

            for r in results:
                if localidad_lower in r.display_name.lower():
                    resultados_priorizados.append(r)
                else:
                    otros_resultados.append(r)

            results = resultados_priorizados + otros_resultados

        current_app.logger.info(f"✅ Google Maps encontró {len(results)} resultados para: {query}")
        return results

    except requests.RequestException as exc:
        current_app.logger.error(f"Error al consultar Google Maps API: {exc}")
        return []


def _fetch_nominatim(query: str, *, limit: int = 5) -> List[GeocodeResult]:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": max(1, min(limit, 10)),
        "addressdetails": 1,
        "countrycodes": "ar",  # Limitar búsqueda a Argentina
        "accept-language": "es",  # Preferir resultados en español
    }
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }

    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json() or []

    results: List[GeocodeResult] = []
    for item in data:
        try:
            lat = float(item.get("lat"))
            lng = float(item.get("lon"))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            continue
        display_name = item.get("display_name") or query
        place_id = str(item.get("place_id") or "") or None
        normalized = _normalize_query(display_name)

        # Calcular score de relevancia para ordenar resultados
        address = item.get("address", {})
        importance = float(item.get("importance", 0))

        results.append(
            GeocodeResult(
                display_name=display_name,
                lat=lat,
                lng=lng,
                provider="nominatim",
                place_id=place_id,
                normalized=normalized,
                raw=item,
            )
        )

    # Ordenar por importancia (Nominatim ya lo hace, pero aseguramos)
    return results


def search(query: str, *, provider: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Returns a list of candidate addresses for the given query."""

    if not query or not query.strip():
        return []

    # Normalizar dirección argentina para mejorar precisión
    normalized_query = _normalize_argentina_address(query)

    # Generar variantes de búsqueda
    variants = _generate_search_variants(normalized_query)

    current_app.logger.info(f"🔍 Buscando dirección con {len(variants)} variantes: {variants}")

    provider_key = (provider or current_app.config.get("MAPS_PROVIDER") or DEFAULT_PROVIDER).lower()

    results = []
    # Intentar cada variante hasta obtener resultados
    for i, variant in enumerate(variants, 1):
        try:
            current_app.logger.info(f"🔍 Intentando variante {i}/{len(variants)}: {variant}")

            # Usar Google Maps como proveedor principal si está configurado
            if provider_key == "google" and GOOGLE_MAPS_API_KEY:
                variant_results = _fetch_google_maps(variant, limit=limit)
            elif provider_key in {"nominatim", "osm"}:
                variant_results = _fetch_nominatim(variant, limit=limit)
            else:
                # Fallback: intentar Google primero, luego Nominatim
                if GOOGLE_MAPS_API_KEY:
                    current_app.logger.info("Usando Google Maps como proveedor principal")
                    variant_results = _fetch_google_maps(variant, limit=limit)
                else:
                    current_app.logger.info("Google Maps no configurado, usando Nominatim")
                    variant_results = _fetch_nominatim(variant, limit=limit)

            if variant_results:
                current_app.logger.info(f"✅ Variante {i} encontró {len(variant_results)} resultados")
                results = variant_results
                break  # Si encontramos resultados, usarlos y detener búsqueda
            else:
                current_app.logger.info(f"⚠️ Variante {i} no encontró resultados")

        except requests.RequestException as exc:  # pragma: no cover - network errors
            current_app.logger.warning(f"Fallo al consultar geocodificador con variante {i}: {exc}")
            continue  # Intentar siguiente variante

    if not results:
        current_app.logger.warning(f"❌ No se encontraron resultados para ninguna variante de: {query}")
        return []

    # Filtrar y ordenar resultados para priorizar GBA y Provincia de Buenos Aires
    gba_results = []
    pba_results = []
    caba_results = []
    argentina_results = []
    other_results = []

    # Partidos del GBA para identificar resultados
    partidos_gba = [
        "tres de febrero", "la matanza", "moron", "hurlingham", "ituzaingo",
        "san martin", "general san martin", "vicente lopez", "san isidro",
        "san fernando", "tigre", "escobar", "pilar", "moreno", "merlo",
        "quilmes", "avellaneda", "lanus", "lomas de zamora", "almirante brown",
        "esteban echeverria", "ezeiza", "berazategui", "florencio varela",
        "malvinas argentinas", "jose c. paz", "san miguel"
    ]

    for result in [r.to_dict() for r in results]:
        display_name = result.get("display_name", "").lower()

        if "argentina" not in display_name:
            other_results.append(result)
            continue

        # Verificar si es del GBA (partidos específicos)
        is_gba = any(partido in display_name for partido in partidos_gba)

        # Verificar si es Provincia de Buenos Aires (no CABA)
        is_pba = "provincia de buenos aires" in display_name or "buenos aires" in display_name
        is_caba = "ciudad autónoma" in display_name or "ciudad autonoma" in display_name or "caba" in display_name

        # Verificar que NO sea de otras provincias (Salta, Córdoba, etc.)
        otras_provincias = ["salta", "córdoba", "cordoba", "santa fe", "mendoza", "tucumán", "tucuman",
                          "entre ríos", "entre rios", "chaco", "corrientes", "misiones", "formosa",
                          "jujuy", "catamarca", "la rioja", "san juan", "san luis", "neuquén", "neuquen",
                          "río negro", "rio negro", "chubut", "santa cruz", "tierra del fuego", "la pampa"]

        is_otra_provincia = any(prov in display_name for prov in otras_provincias)

        if is_gba and not is_otra_provincia:
            gba_results.append(result)
        elif is_caba:
            caba_results.append(result)
        elif is_pba and not is_otra_provincia:
            pba_results.append(result)
        elif not is_otra_provincia:
            argentina_results.append(result)
        else:
            # Es de otra provincia, ponerlo al final
            argentina_results.append(result)

    # Retornar en orden de prioridad: GBA > CABA > Prov. Buenos Aires > Otros Argentina > Resto
    return gba_results + caba_results + pba_results + argentina_results + other_results


def resolve(query: str, *, provider: Optional[str] = None, use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """Resolves a single address, caching the result for future calls."""

    if not query or not query.strip():
        return None

    provider_key = (provider or current_app.config.get("MAPS_PROVIDER") or DEFAULT_PROVIDER).lower()
    normalized = _normalize_query(query)

    cache_entry: Optional[GeocodeCache] = None
    if use_cache:
        cache_entry = GeocodeCache.query.filter_by(provider=provider_key, normalized_text=normalized).first()
        if cache_entry and not _should_refresh(cache_entry):
            payload = cache_entry.to_payload()
            payload["cached"] = True
            return payload

    results = search(query, provider=provider_key, limit=1)
    if not results:
        if cache_entry and cache_entry.status != "fail":
            cache_entry.status = "fail"
            cache_entry.updated_at = datetime.utcnow()
            db.session.flush()
        return None

    result = results[0]
    _store_in_cache(query, normalized, provider_key, result)
    result["cached"] = False
    return result


def _store_in_cache(original_query: str, normalized: str, provider: str, result: Dict[str, Any]) -> None:
    now = datetime.utcnow()
    entry = GeocodeCache.query.filter_by(provider=provider, normalized_text=normalized).first()
    raw_payload = result.get("raw")
    raw_text = json.dumps(raw_payload) if raw_payload else None

    if entry is None:
        entry = GeocodeCache(
            provider=provider,
            query_text=original_query.strip(),
            normalized_text=normalized,
        )
        db.session.add(entry)

    entry.display_name = result.get("display_name") or original_query
    entry.place_id = result.get("place_id")
    entry.latitud = result.get("lat")
    entry.longitud = result.get("lng")
    entry.raw_response = raw_text
    entry.status = result.get("status") or "ok"
    entry.updated_at = now
    if not entry.created_at:
        entry.created_at = now

    # Nominatim impone límites estrictos, respetar un pequeño delay al insertar masivamente
    time.sleep(0.0)

    db.session.flush()


__all__ = ["search", "resolve"]
