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

DEFAULT_PROVIDER = "nominatim"
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


def _generate_search_variants(query: str) -> List[str]:
    """
    Genera variantes de búsqueda para mejorar la tasa de éxito.
    Por ejemplo, si una dirección completa falla, intenta sin número de puerta.
    """
    import re
    variants = [query]  # Siempre incluir la original

    # Normalizar "Gral." a "General" y variantes similares
    query_normalized = query
    abreviaturas_calles = {
        r'\bGral\.?\s': 'General ',
        r'\bGte\.?\s': 'General ',
        r'\bAv\.?\s': 'Avenida ',
        r'\bBv\.?\s': 'Boulevard ',
        r'\bBlvd\.?\s': 'Boulevard ',
        r'\bCte\.?\s': 'Coronel ',
        r'\bCnel\.?\s': 'Coronel ',
        r'\bCap\.?\s': 'Capitan ',
        r'\bDr\.?\s': 'Doctor ',
        r'\bPte\.?\s': 'Presidente ',
        r'\bSta\.?\s': 'Santa ',
        r'\bSto\.?\s': 'Santo ',
        r'\bSan\s': 'San ',
    }

    for abrev_pattern, completo in abreviaturas_calles.items():
        query_normalized = re.sub(abrev_pattern, completo, query_normalized, flags=re.IGNORECASE)

    if query_normalized != query:
        variants.append(query_normalized)

    # Trabajar con ambas versiones (original y normalizada)
    for base_query in [query, query_normalized]:
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
            if provider_key in {"nominatim", "osm"}:
                variant_results = _fetch_nominatim(variant, limit=limit)
            else:
                current_app.logger.warning("Proveedor de mapas %s no soportado, usando Nominatim", provider_key)
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

    # Filtrar resultados para priorizar Argentina
    argentina_results = []
    other_results = []

    for result in [r.to_dict() for r in results]:
        display_name = result.get("display_name", "").lower()
        if "argentina" in display_name:
            argentina_results.append(result)
        else:
            other_results.append(result)

    # Retornar primero resultados argentinos
    return argentina_results + other_results


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
