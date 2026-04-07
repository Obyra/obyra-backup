"""
Blueprint de Presupuestos - Gestión de presupuestos y cotizaciones
(Package refactor — sub-modules: core, items, estados, pdf_email, calculadora)
"""
import os


def _d(val, default=0):
    """Convierte valor a Decimal de forma segura (para cálculos financieros)."""
    if val is None:
        return Decimal(str(default))
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError):
        return Decimal(str(default))


def _f(val):
    """Convierte Decimal a float para serialización JSON."""
    if val is None:
        return 0
    return float(val)
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort, send_file)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from extensions import db, limiter
from sqlalchemy import desc, or_
from models import Presupuesto, ItemPresupuesto, Obra, Organizacion, Cliente
from services.calculation import BudgetCalculator, BudgetConstants
from services.memberships import get_current_org_id, get_current_membership
from services.plan_service import require_active_subscription
from utils.pagination import Pagination
from utils import safe_int
import io
import re
from weasyprint import HTML
from flask_mail import Message

presupuestos_bp = Blueprint('presupuestos', __name__)


def _limpiar_metadata_pdf(pdf_buffer, presupuesto, organizacion):
    """Reescribe metadatos del PDF para evitar falsos positivos de antivirus.

    Avast y otros antivirus detectan PDFs generados por WeasyPrint como
    'PDF:MalwareX-gen [Phish]' por los metadatos Producer/Creator.
    Esta función los reemplaza con datos legítimos de la empresa.
    """
    try:
        from PyPDF2 import PdfReader, PdfWriter
        reader = PdfReader(pdf_buffer)
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        # Reemplazar metadatos sospechosos con datos de la empresa
        nombre_org = organizacion.nombre if organizacion else 'OBYRA'
        writer.add_metadata({
            '/Title': f'Presupuesto {presupuesto.numero}',
            '/Author': nombre_org,
            '/Creator': nombre_org,
            '/Producer': f'{nombre_org} - Sistema de Gestion',
            '/Subject': f'Presupuesto comercial N° {presupuesto.numero}',
        })

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        return output
    except Exception:
        # Si falla el post-procesado, devolver el PDF original
        pdf_buffer.seek(0)
        return pdf_buffer


def buscar_item_inventario_por_nombre(descripcion, org_id):
    """
    Busca un item de inventario que coincida con la descripción del material.
    Optimizado: primero busca en BD, solo hace fuzzy en memoria si es necesario.

    Args:
        descripcion: Descripción del material del presupuesto
        org_id: ID de la organización

    Returns:
        ItemInventario o None si no encuentra coincidencia
    """
    from models.inventory import ItemInventario
    from sqlalchemy import func

    if not descripcion:
        return None

    descripcion = descripcion.strip()
    if not descripcion:
        return None

    # 1. Búsqueda exacta (case insensitive) - muy rápida con índice
    item = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo == True,
        func.lower(ItemInventario.nombre) == descripcion.lower()
    ).first()
    if item:
        return item

    # 2. Búsqueda parcial: descripción contenida en nombre o viceversa
    item = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo == True,
        func.lower(ItemInventario.nombre).contains(descripcion.lower())
    ).first()
    if item:
        return item

    # 3. Búsqueda por palabras clave (primeras 2-3 palabras significativas)
    palabras = [p for p in descripcion.lower().split() if len(p) > 2][:3]
    if palabras:
        for palabra in palabras:
            item = ItemInventario.query.filter(
                ItemInventario.organizacion_id == org_id,
                ItemInventario.activo == True,
                func.lower(ItemInventario.nombre).contains(palabra)
            ).first()
            if item:
                return item

    # 4. Fuzzy search limitado (solo si las búsquedas anteriores fallaron)
    # Limitar a 100 items para evitar cargar toda la BD en memoria
    items = ItemInventario.query.filter_by(
        organizacion_id=org_id,
        activo=True
    ).limit(100).all()

    def normalizar(texto):
        if not texto:
            return ''
        texto = texto.lower().strip()
        reemplazos = {'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ñ': 'n', 'ü': 'u'}
        for acento, sin_acento in reemplazos.items():
            texto = texto.replace(acento, sin_acento)
        texto = re.sub(r'[^a-z0-9\s]', '', texto)
        return re.sub(r'\s+', ' ', texto)

    desc_normalizada = normalizar(descripcion)
    mejor_match = None
    mejor_score = 0

    for item in items:
        nombre_normalizado = normalizar(item.nombre)
        if not nombre_normalizado:
            continue

        # Coincidencia exacta normalizada
        if desc_normalizada == nombre_normalizado:
            return item

        # Calcular score por palabras en común
        palabras_desc = set(desc_normalizada.split())
        palabras_item = set(nombre_normalizado.split())
        coincidencias = palabras_desc & palabras_item

        if len(coincidencias) >= 2:
            score = len(coincidencias) * 10
            if score > mejor_score:
                mejor_score = score
                mejor_match = item

    return mejor_match if mejor_score >= 5 else None


def identificar_etapa_por_tipo(item):
    """
    Identifica la etapa correspondiente basándose en el tipo y descripción del ítem.
    Utilizado para items sin etapa_id asignada.
    """
    # Mapeo de palabras clave a etapas
    ETAPA_KEYWORDS = {
        'Excavación': ['excavacion', 'movimiento', 'suelo', 'terreno', 'nivelacion'],
        'Fundaciones': ['fundacion', 'cimiento', 'zapata', 'viga de fundacion', 'hormigon armado'],
        'Estructura': ['estructura', 'columna', 'viga', 'losa', 'hormigon', 'acero', 'hierro'],
        'Mampostería': ['muro', 'pared', 'tabique', 'ladrillo', 'bloque'],
        'Techos': ['techo', 'cubierta', 'teja', 'chapa', 'impermeabilizacion'],
        'Instalaciones Eléctricas': ['electric', 'cable', 'tablero', 'luminaria', 'tomacorriente'],
        'Instalaciones Sanitarias': ['sanitari', 'agua', 'desague', 'cañeria', 'inodoro', 'lavabo'],
        'Instalaciones de Gas': ['gas', 'gasoducto', 'artefacto a gas'],
        'Revoque Grueso': ['revoque grueso', 'azotado', 'jaharro'],
        'Revoque Fino': ['revoque fino', 'enlucido', 'terminacion'],
        'Pisos': ['piso', 'ceramica', 'porcelanato', 'carpeta', 'contrapiso'],
        'Carpintería': ['puerta', 'ventana', 'marco', 'madera', 'carpinteria'],
        'Pintura': ['pintura', 'latex', 'esmalte', 'barniz'],
        'Instalaciones Complementarias': ['aire acondicionado', 'calefaccion', 'ventilacion'],
        'Limpieza Final': ['limpieza', 'acondicionamiento final'],
    }

    descripcion_lower = item.descripcion.lower() if item.descripcion else ''

    # Buscar coincidencias por palabras clave
    for etapa_nombre, keywords in ETAPA_KEYWORDS.items():
        for keyword in keywords:
            if keyword in descripcion_lower:
                return etapa_nombre

    # Identificación por tipo de ítem
    if item.tipo == 'material':
        if 'cemento' in descripcion_lower or 'hormigon' in descripcion_lower:
            return 'Fundaciones'
        return 'Materiales Generales'
    elif item.tipo == 'mano_obra':
        return 'Mano de Obra General'
    elif item.tipo == 'maquinaria':
        return 'Maquinaria y Equipos'
    else:
        return 'Otros'


# Import sub-modules to register their routes on presupuestos_bp
from blueprint_presupuestos import core       # noqa: E402, F401
from blueprint_presupuestos import items      # noqa: E402, F401
from blueprint_presupuestos import estados    # noqa: E402, F401
from blueprint_presupuestos import pdf_email  # noqa: E402, F401
from blueprint_presupuestos import calculadora  # noqa: E402, F401
