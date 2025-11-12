"""
Utilidades de validación para inputs de usuario
"""
import re
from typing import Optional, Tuple


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Valida formato de email

    Returns:
        (is_valid, error_message)
    """
    if not email or not email.strip():
        return False, "El email es requerido"

    email = email.strip()

    # Longitud máxima razonable
    if len(email) > 254:
        return False, "El email es demasiado largo"

    # Regex simple pero efectivo para emails
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if not re.match(email_regex, email):
        return False, "Formato de email inválido"

    return True, None


def validate_string_length(value: str, field_name: str, min_length: int = 1, max_length: int = 255) -> Tuple[bool, Optional[str]]:
    """
    Valida longitud de string

    Args:
        value: Valor a validar
        field_name: Nombre del campo (para mensaje de error)
        min_length: Longitud mínima
        max_length: Longitud máxima

    Returns:
        (is_valid, error_message)
    """
    if not value or not value.strip():
        if min_length > 0:
            return False, f"{field_name} es requerido"
        return True, None

    value = value.strip()
    length = len(value)

    if length < min_length:
        return False, f"{field_name} debe tener al menos {min_length} caracteres"

    if length > max_length:
        return False, f"{field_name} no puede exceder {max_length} caracteres"

    return True, None


def validate_phone(phone: str) -> Tuple[bool, Optional[str]]:
    """
    Valida formato de teléfono (flexible para diferentes formatos)

    Returns:
        (is_valid, error_message)
    """
    if not phone or not phone.strip():
        return True, None  # Opcional

    phone = phone.strip()

    # Remover espacios, guiones, paréntesis comunes
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)

    # Debe tener entre 8 y 15 dígitos (con posible + al inicio)
    if not re.match(r'^\+?[0-9]{8,15}$', cleaned):
        return False, "Formato de teléfono inválido (debe contener 8-15 dígitos)"

    return True, None


def validate_numeric(value: str, field_name: str, min_value: Optional[float] = None, max_value: Optional[float] = None) -> Tuple[bool, Optional[str]]:
    """
    Valida valor numérico

    Args:
        value: Valor a validar
        field_name: Nombre del campo
        min_value: Valor mínimo permitido
        max_value: Valor máximo permitido

    Returns:
        (is_valid, error_message)
    """
    try:
        num = float(value)
    except (ValueError, TypeError):
        return False, f"{field_name} debe ser un número válido"

    if min_value is not None and num < min_value:
        return False, f"{field_name} debe ser mayor o igual a {min_value}"

    if max_value is not None and num > max_value:
        return False, f"{field_name} debe ser menor o igual a {max_value}"

    return True, None


def sanitize_string(value: str, max_length: int = 255) -> str:
    """
    Sanitiza un string: elimina espacios extras, limita longitud

    Args:
        value: String a sanitizar
        max_length: Longitud máxima

    Returns:
        String sanitizado
    """
    if not value:
        return ''

    # Eliminar espacios extras
    sanitized = ' '.join(value.split())

    # Limitar longitud
    return sanitized[:max_length]


def validate_percentage(value: str, field_name: str = "Porcentaje") -> Tuple[bool, Optional[str]]:
    """
    Valida que un valor esté entre 0 y 100

    Returns:
        (is_valid, error_message)
    """
    return validate_numeric(value, field_name, min_value=0, max_value=100)


def validate_positive_number(value: str, field_name: str) -> Tuple[bool, Optional[str]]:
    """
    Valida que un número sea positivo

    Returns:
        (is_valid, error_message)
    """
    return validate_numeric(value, field_name, min_value=0)


def validate_file_extension(filename: str, allowed_extensions: set) -> Tuple[bool, Optional[str]]:
    """
    Valida la extensión de un archivo

    Args:
        filename: Nombre del archivo
        allowed_extensions: Set de extensiones permitidas (sin punto)

    Returns:
        (is_valid, error_message)
    """
    if not filename or '.' not in filename:
        return False, "El archivo debe tener una extensión válida"

    extension = filename.rsplit('.', 1)[1].lower()

    if extension not in allowed_extensions:
        allowed_str = ', '.join(sorted(allowed_extensions))
        return False, f"Extensión de archivo no permitida. Extensiones válidas: {allowed_str}"

    return True, None


def validate_file_size(file_size: int, max_size_mb: int = 16) -> Tuple[bool, Optional[str]]:
    """
    Valida el tamaño de un archivo

    Args:
        file_size: Tamaño del archivo en bytes
        max_size_mb: Tamaño máximo en megabytes

    Returns:
        (is_valid, error_message)
    """
    max_size_bytes = max_size_mb * 1024 * 1024

    if file_size > max_size_bytes:
        return False, f"El archivo excede el tamaño máximo permitido de {max_size_mb}MB"

    if file_size == 0:
        return False, "El archivo está vacío"

    return True, None
