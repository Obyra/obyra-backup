"""
Utils package for OBYRA IA
"""

from flask import current_app
import os
import uuid
from datetime import datetime, date
from werkzeug.utils import secure_filename


def generar_nombre_archivo_seguro(filename):
    """Genera un nombre de archivo seguro con timestamp"""
    if filename:
        filename = secure_filename(filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name, ext = os.path.splitext(filename)
        return f"{timestamp}_{name[:50]}{ext}"
    return None


def crear_directorio_si_no_existe(path):
    """Crea un directorio si no existe"""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path


def formatear_moneda(cantidad):
    """Formatea cantidad como moneda argentina"""
    if cantidad is None:
        return "$0"
    return f"${cantidad:,.0f}".replace(",", ".")


def validar_email(email):
    """Validación básica de email"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def safe_decimal(value, default=0):
    """Convierte a Decimal de forma segura

    Args:
        value: Valor a convertir
        default: Valor por defecto si falla la conversión

    Returns:
        Decimal: Valor convertido o default
    """
    from decimal import Decimal, InvalidOperation
    try:
        if value is None or value == '':
            return Decimal(default)
        result = Decimal(str(value))
        if result < 0:
            return Decimal(default)
        return result
    except (ValueError, InvalidOperation, TypeError):
        return Decimal(default)


def safe_float(value, default=0.0):
    """Convierte a float de forma segura

    Args:
        value: Valor a convertir
        default: Valor por defecto si falla la conversión

    Returns:
        float: Valor convertido o default
    """
    try:
        if value is None or value == '':
            return default
        result = float(value)
        if result < 0:
            return default
        return result
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    """Convierte a int de forma segura

    Args:
        value: Valor a convertir
        default: Valor por defecto si falla la conversión

    Returns:
        int: Valor convertido o default
    """
    try:
        if value is None or value == '':
            return default
        result = int(value)
        if result < 0:
            return default
        return result
    except (ValueError, TypeError):
        return default
