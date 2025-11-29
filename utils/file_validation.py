"""
File Validation Utilities
=========================

Validación segura de archivos subidos.
Incluye verificación de extensiones, MIME types y contenido.

Uso:
    from utils.file_validation import validate_upload, is_safe_filename

    if validate_upload(file, allowed_types=['image', 'document']):
        filename = secure_save(file, upload_folder)
"""

import os
import re
import magic  # python-magic para detección de MIME type real
from werkzeug.utils import secure_filename
from typing import Optional, Set, Tuple, List


# Extensiones permitidas por categoría
ALLOWED_EXTENSIONS = {
    'image': {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'},
    'document': {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'csv', 'odt', 'ods'},
    'archive': {'zip', 'rar', '7z', 'tar', 'gz'},
    'cad': {'dwg', 'dxf'},
}

# MIME types válidos por extensión
MIME_TYPE_MAP = {
    # Imágenes
    'jpg': ['image/jpeg'],
    'jpeg': ['image/jpeg'],
    'png': ['image/png'],
    'gif': ['image/gif'],
    'bmp': ['image/bmp', 'image/x-ms-bmp'],
    'webp': ['image/webp'],
    'svg': ['image/svg+xml'],

    # Documentos
    'pdf': ['application/pdf'],
    'doc': ['application/msword'],
    'docx': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    'xls': ['application/vnd.ms-excel'],
    'xlsx': ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
    'txt': ['text/plain'],
    'csv': ['text/csv', 'text/plain', 'application/csv'],
    'odt': ['application/vnd.oasis.opendocument.text'],
    'ods': ['application/vnd.oasis.opendocument.spreadsheet'],

    # Archivos comprimidos
    'zip': ['application/zip', 'application/x-zip-compressed'],
    'rar': ['application/x-rar-compressed', 'application/vnd.rar'],
    '7z': ['application/x-7z-compressed'],
    'tar': ['application/x-tar'],
    'gz': ['application/gzip', 'application/x-gzip'],

    # CAD
    'dwg': ['application/acad', 'application/x-acad', 'image/vnd.dwg'],
    'dxf': ['application/dxf', 'image/vnd.dxf'],
}

# Patrones peligrosos en nombres de archivo
DANGEROUS_PATTERNS = [
    r'\.\./',           # Path traversal
    r'\.\.\\',          # Path traversal Windows
    r'^/',              # Absolute path Unix
    r'^[A-Za-z]:',      # Absolute path Windows
    r'\x00',            # Null byte
    r'<script',         # XSS attempt
    r'\.php$',          # PHP files
    r'\.exe$',          # Executables
    r'\.bat$',          # Batch files
    r'\.cmd$',          # Command files
    r'\.sh$',           # Shell scripts
    r'\.ps1$',          # PowerShell
    r'\.vbs$',          # VBScript
    r'\.js$',           # JavaScript (server-side)
    r'\.py$',           # Python
    r'\.rb$',           # Ruby
    r'\.pl$',           # Perl
]

# Tamaño máximo por tipo (en bytes)
MAX_SIZE_BY_TYPE = {
    'image': 10 * 1024 * 1024,      # 10 MB
    'document': 50 * 1024 * 1024,   # 50 MB
    'archive': 100 * 1024 * 1024,   # 100 MB
    'cad': 100 * 1024 * 1024,       # 100 MB
    'default': 16 * 1024 * 1024,    # 16 MB
}


def get_file_extension(filename: str) -> str:
    """Obtiene la extensión del archivo en minúsculas."""
    if '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def is_allowed_extension(filename: str, allowed_types: List[str] = None) -> bool:
    """
    Verifica si la extensión del archivo está permitida.

    Args:
        filename: Nombre del archivo
        allowed_types: Lista de categorías permitidas ('image', 'document', etc.)
                      Si es None, permite todas las categorías.

    Returns:
        bool: True si la extensión está permitida
    """
    ext = get_file_extension(filename)
    if not ext:
        return False

    if allowed_types is None:
        # Permitir todas las extensiones conocidas
        all_extensions = set()
        for exts in ALLOWED_EXTENSIONS.values():
            all_extensions.update(exts)
        return ext in all_extensions

    # Verificar si la extensión está en alguna de las categorías permitidas
    for type_name in allowed_types:
        if type_name in ALLOWED_EXTENSIONS:
            if ext in ALLOWED_EXTENSIONS[type_name]:
                return True

    return False


def is_safe_filename(filename: str) -> Tuple[bool, str]:
    """
    Verifica si el nombre de archivo es seguro.

    Args:
        filename: Nombre del archivo a verificar

    Returns:
        Tuple[bool, str]: (es_seguro, mensaje_error)
    """
    if not filename:
        return False, "Nombre de archivo vacío"

    # Verificar patrones peligrosos
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, filename, re.IGNORECASE):
            return False, f"Nombre de archivo contiene patrón peligroso"

    # Verificar longitud
    if len(filename) > 255:
        return False, "Nombre de archivo demasiado largo"

    # Verificar caracteres no permitidos
    safe_name = secure_filename(filename)
    if not safe_name:
        return False, "Nombre de archivo contiene caracteres no válidos"

    return True, ""


def detect_mime_type(file_content: bytes) -> str:
    """
    Detecta el MIME type real del archivo basándose en su contenido.

    Args:
        file_content: Contenido del archivo (primeros bytes)

    Returns:
        str: MIME type detectado
    """
    try:
        mime = magic.Magic(mime=True)
        return mime.from_buffer(file_content)
    except Exception:
        # Fallback si python-magic no está disponible
        return 'application/octet-stream'


def validate_mime_type(filename: str, file_content: bytes) -> Tuple[bool, str]:
    """
    Valida que el MIME type real coincida con la extensión.

    Args:
        filename: Nombre del archivo
        file_content: Contenido del archivo (primeros bytes)

    Returns:
        Tuple[bool, str]: (es_válido, mensaje_error)
    """
    ext = get_file_extension(filename)
    if not ext:
        return False, "Archivo sin extensión"

    # Obtener MIME type esperado
    expected_mimes = MIME_TYPE_MAP.get(ext, [])
    if not expected_mimes:
        # Extensión desconocida pero permitida
        return True, ""

    # Detectar MIME type real
    try:
        actual_mime = detect_mime_type(file_content)

        # Verificar si coincide
        if actual_mime in expected_mimes:
            return True, ""

        # Algunos MIME types son equivalentes
        if actual_mime.startswith('text/') and any(m.startswith('text/') for m in expected_mimes):
            return True, ""

        return False, f"Tipo de archivo no coincide con extensión (esperado: {expected_mimes}, detectado: {actual_mime})"

    except Exception as e:
        # Si no podemos verificar, permitir pero loguear
        return True, f"No se pudo verificar MIME type: {str(e)}"


def validate_upload(file, allowed_types: List[str] = None,
                   max_size: int = None) -> Tuple[bool, str]:
    """
    Validación completa de archivo subido.

    Args:
        file: Objeto FileStorage de werkzeug
        allowed_types: Lista de categorías permitidas
        max_size: Tamaño máximo en bytes (opcional)

    Returns:
        Tuple[bool, str]: (es_válido, mensaje_error)
    """
    if not file:
        return False, "No se recibió archivo"

    if not file.filename:
        return False, "Archivo sin nombre"

    filename = file.filename

    # 1. Verificar nombre seguro
    is_safe, error = is_safe_filename(filename)
    if not is_safe:
        return False, error

    # 2. Verificar extensión
    if not is_allowed_extension(filename, allowed_types):
        return False, f"Extensión de archivo no permitida: {get_file_extension(filename)}"

    # 3. Leer contenido para validación
    try:
        file.seek(0)
        content = file.read(8192)  # Leer primeros 8KB para detección
        file.seek(0)  # Resetear posición
    except Exception:
        return False, "No se pudo leer el archivo"

    # 4. Verificar que no esté vacío
    if len(content) == 0:
        return False, "Archivo vacío"

    # 5. Verificar MIME type
    is_valid_mime, mime_error = validate_mime_type(filename, content)
    if not is_valid_mime:
        return False, mime_error

    # 6. Verificar tamaño
    if max_size:
        file.seek(0, 2)  # Ir al final
        size = file.tell()
        file.seek(0)  # Resetear

        if size > max_size:
            max_mb = max_size / (1024 * 1024)
            return False, f"Archivo demasiado grande (máximo {max_mb:.1f} MB)"

    return True, ""


def secure_save(file, upload_folder: str, filename: str = None) -> Optional[str]:
    """
    Guarda un archivo de forma segura.

    Args:
        file: Objeto FileStorage
        upload_folder: Carpeta de destino
        filename: Nombre personalizado (opcional)

    Returns:
        str: Ruta completa del archivo guardado, o None si falla
    """
    if filename is None:
        filename = file.filename

    # Sanitizar nombre
    safe_name = secure_filename(filename)
    if not safe_name:
        return None

    # Crear carpeta si no existe
    os.makedirs(upload_folder, exist_ok=True)

    # Generar nombre único si ya existe
    filepath = os.path.join(upload_folder, safe_name)
    if os.path.exists(filepath):
        name, ext = os.path.splitext(safe_name)
        import uuid
        safe_name = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = os.path.join(upload_folder, safe_name)

    try:
        file.save(filepath)
        return filepath
    except Exception:
        return None


def get_max_size_for_type(file_type: str) -> int:
    """Obtiene el tamaño máximo permitido para un tipo de archivo."""
    return MAX_SIZE_BY_TYPE.get(file_type, MAX_SIZE_BY_TYPE['default'])
