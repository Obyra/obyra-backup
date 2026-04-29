"""Scraper del Indicador Camarco mensual.

Estrategia (best-effort):
  1. Visita la pagina de Economia y Estadistica de Camarco para encontrar
     el link al ultimo Indicador.
  2. Si falla, prueba URLs candidatas conocidas con patron mensual.
  3. Parsea el contenido buscando porcentajes y referencias al componente
     Mano de Obra.

Si el sitio cambia y el parser falla, devuelve None y loggea. NUNCA muta BD
desde acá: solo retorna datos para que el endpoint los procese.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional, Dict
import locale

logger = logging.getLogger(__name__)

CAMARCO_HOME = 'https://www.camarco.org.ar/economia-y-estadistica/'
CAMARCO_BASE = 'https://www.camarco.org.ar'

# Mapa de meses para parsear titulos en español
MESES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
}


def _http_get(url: str, timeout: int = 15) -> Optional[str]:
    """GET defensivo: devuelve el HTML o None."""
    try:
        import requests
    except ImportError:
        logger.error("[CAC] requests no esta instalado")
        return None

    try:
        # User-Agent normal para evitar bloqueos. Verify=True por defecto.
        r = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; OBYRA/1.0; +https://app.obyra.com.ar)',
            'Accept': 'text/html,application/xhtml+xml',
        })
        if r.status_code == 200:
            return r.text
        logger.warning(f"[CAC] {url} -> HTTP {r.status_code}")
        return None
    except Exception as e:
        logger.warning(f"[CAC] error fetching {url}: {e}")
        return None


def _parsear_indicador(html: str, fuente_url: str) -> Optional[Dict]:
    """Extrae los datos del Indicador a partir del HTML de la nota.

    Busca patrones tipicos como:
      - "registró un aumento de X,Y% respecto al mes anterior"
      - "componente Mano de Obra ... X,Y% mensual"
      - "X.XXX,X puntos"

    Retorna dict o None si no encuentra suficiente info.
    """
    if not html:
        return None

    # Buscar titulo de la nota para extraer mes/año
    titulo_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
    titulo = (titulo_match.group(1) if titulo_match else '').strip()

    # Buscar mes y año en el titulo (ej "Indicador CAMARCO Marzo 2026")
    mes = anio = None
    for nombre_mes, num in MESES.items():
        m = re.search(rf'{nombre_mes}\s+(\d{{4}})', titulo, re.IGNORECASE)
        if m:
            mes = num
            anio = int(m.group(1))
            break

    if not mes or not anio:
        # Probar buscar en h1 del cuerpo
        h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
        h1 = (h1_match.group(1) if h1_match else '')
        for nombre_mes, num in MESES.items():
            m = re.search(rf'{nombre_mes}\s+(\d{{4}})', h1, re.IGNORECASE)
            if m:
                mes = num
                anio = int(m.group(1))
                break

    # Limpiar HTML para parsear texto plano
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)

    # Buscar variacion general mensual
    porcentaje_general = None
    m = re.search(r'(?:registr[oó]\s+(?:un\s+)?(?:aumento|incremento|var)?[^\d-]{0,30})?'
                  r'(-?\d+[,.]?\d*)\s*%\s*(?:respecto\s+al?\s+mes\s+anterior|mensual|en\s+(?:el\s+)?mes)',
                  text, re.IGNORECASE)
    if m:
        try:
            porcentaje_general = float(m.group(1).replace(',', '.'))
        except ValueError:
            pass

    # Buscar variacion del componente Mano de Obra
    porcentaje_mo = None
    # Patrones tipicos:
    # "Mano de Obra ... 3,2%"
    # "componente Mano de Obra registró un aumento de 3,2%"
    mo_patterns = [
        r'(?:componente\s+|costo\s+(?:de\s+)?|el\s+rubro\s+)?[Mm]ano\s+de\s+[Oo]bra'
        r'[^\.\n]*?(-?\d+[,.]\d+)\s*%',
        r'[Mm]ano\s+de\s+[Oo]bra\s+[^\.]*?aumento\s+de\s+(-?\d+[,.]\d+)\s*%',
        r'[Mm]ano\s+de\s+[Oo]bra\s*[:\-]\s*(-?\d+[,.]\d+)\s*%',
    ]
    for pat in mo_patterns:
        m = re.search(pat, text)
        if m:
            try:
                porcentaje_mo = float(m.group(1).replace(',', '.'))
                break
            except ValueError:
                continue

    # Buscar valor en puntos del indice general (ej "19.771,2 puntos")
    indice_general = None
    m = re.search(r'(\d{1,3}(?:\.\d{3})+,\d+)\s*puntos', text)
    if m:
        try:
            indice_general = float(m.group(1).replace('.', '').replace(',', '.'))
        except ValueError:
            pass

    # Si no tenemos al menos el % de MO o periodo, fallamos
    if porcentaje_mo is None and porcentaje_general is None:
        logger.warning(f"[CAC] No se pudo parsear ningun porcentaje en {fuente_url}")
        return None

    if not mes or not anio:
        logger.warning(f"[CAC] No se pudo determinar mes/anio en {fuente_url}")
        return None

    return {
        'periodo': date(anio, mes, 1),
        'porcentaje_mo': porcentaje_mo,
        'porcentaje_general': porcentaje_general,
        'indice_general': indice_general,
        'indice_mo': None,  # raramente parsearia bien, lo dejamos en None
        'fuente_url': fuente_url,
        'fuente_titulo': titulo[:255] if titulo else None,
    }


def _encontrar_link_ultimo_indicador(html_home: str) -> Optional[str]:
    """Busca el link mas reciente al Indicador desde la pagina home."""
    if not html_home:
        return None
    # Buscar enlaces tipo /YYYY/MM/DD/indicador-camarco-...
    # El sitio publica con slug como "indicador-camarco-marzo-2026"
    matches = re.findall(
        r'href="(https?://[^"]*/\d{4}/\d{2}/\d{2}/indicador-camarco[^"]+)"',
        html_home,
        re.IGNORECASE,
    )
    if not matches:
        # Tambien probar links relativos
        matches = re.findall(
            r'href="(/\d{4}/\d{2}/\d{2}/indicador-camarco[^"]+)"',
            html_home,
            re.IGNORECASE,
        )
        matches = [CAMARCO_BASE + m if m.startswith('/') else m for m in matches]

    if not matches:
        return None

    # Tomar el primero (suelen estar ordenados desc por fecha)
    return matches[0]


def buscar_ultimo_indicador() -> Optional[Dict]:
    """Devuelve el dict con la info del ultimo Indicador Camarco, o None.

    Estrategia:
      1. Busca en home page un link a indicador.
      2. Hace fetch de ese link.
      3. Parsea.
    """
    home_html = _http_get(CAMARCO_HOME)
    if not home_html:
        return None

    link = _encontrar_link_ultimo_indicador(home_html)
    if not link:
        logger.warning("[CAC] No se encontro link al ultimo indicador en home")
        return None

    logger.info(f"[CAC] Probando link: {link}")
    nota_html = _http_get(link)
    if not nota_html:
        return None

    return _parsear_indicador(nota_html, link)


def buscar_indicador_por_url(url: str) -> Optional[Dict]:
    """Permite probar manualmente con una URL especifica."""
    html = _http_get(url)
    if not html:
        return None
    return _parsear_indicador(html, url)
