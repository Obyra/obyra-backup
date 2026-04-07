"""
Branding Service
================

Servicio para gestionar el branding (identidad visual) de cada organización:
- Subida y validación de logo
- Generación de paths seguros
- Helpers para acceder al branding desde templates y PDFs
"""

import os
import re
from pathlib import Path
from typing import Optional

from flask import current_app


# Validaciones
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_LOGO_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB
HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


class BrandingError(Exception):
    """Error en operación de branding."""
    pass


def _allowed_file(filename: str) -> bool:
    """Valida que la extensión del archivo sea permitida."""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_LOGO_EXTENSIONS


def _logo_dir_for_org(org_id: int) -> Path:
    """Devuelve el directorio donde se guarda el logo de una org."""
    base = Path(current_app.static_folder or 'static') / 'uploads' / 'orgs' / str(org_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_logo(org_id: int, file_storage) -> str:
    """
    Guarda el archivo de logo en static/uploads/orgs/<org_id>/logo.<ext>

    Args:
        org_id: ID de la organización
        file_storage: FileStorage de Flask (request.files['logo'])

    Returns:
        Ruta relativa del logo (ej: 'uploads/orgs/3/logo.png')
        Esta ruta se guarda en organizacion.logo_url

    Raises:
        BrandingError si la validación falla
    """
    if not file_storage or not file_storage.filename:
        raise BrandingError('No se seleccionó ningún archivo.')

    filename = file_storage.filename
    if not _allowed_file(filename):
        raise BrandingError(
            f'Formato no permitido. Usar: {", ".join(ALLOWED_LOGO_EXTENSIONS).upper()}.'
        )

    # Validar tamaño leyendo el stream
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)

    if size > MAX_LOGO_SIZE_BYTES:
        raise BrandingError(
            f'El archivo es demasiado grande ({size // 1024} KB). Máximo {MAX_LOGO_SIZE_BYTES // 1024} KB.'
        )
    if size == 0:
        raise BrandingError('El archivo está vacío.')

    # Determinar extensión final
    ext = filename.rsplit('.', 1)[1].lower()
    if ext == 'jpeg':
        ext = 'jpg'

    # Path final
    dest_dir = _logo_dir_for_org(org_id)
    dest_filename = f'logo.{ext}'
    dest_path = dest_dir / dest_filename

    # Eliminar logos previos (cualquier extensión)
    for old_ext in ALLOWED_LOGO_EXTENSIONS:
        old_path = dest_dir / f'logo.{old_ext}'
        if old_path.exists() and old_path != dest_path:
            try:
                old_path.unlink()
            except OSError:
                pass

    # Guardar
    file_storage.save(str(dest_path))

    # Devolver ruta relativa al static_folder
    rel_path = f'uploads/orgs/{org_id}/{dest_filename}'
    return rel_path


def delete_logo(org_id: int, logo_url: Optional[str] = None) -> bool:
    """
    Elimina el archivo de logo de una organización.

    Returns:
        True si se eliminó, False si no existía
    """
    deleted = False
    dest_dir = _logo_dir_for_org(org_id)
    for ext in ALLOWED_LOGO_EXTENSIONS:
        path = dest_dir / f'logo.{ext}'
        if path.exists():
            try:
                path.unlink()
                deleted = True
            except OSError:
                pass
    return deleted


def get_logo_absolute_path(logo_url: Optional[str]) -> Optional[str]:
    """
    Convierte una logo_url relativa en path absoluto del filesystem.
    Útil para PDFs (ReportLab necesita path absoluto).

    Returns:
        Path absoluto o None si el logo no existe.
    """
    if not logo_url:
        return None

    # Limpiar el path
    clean = logo_url.lstrip('/')
    if clean.startswith('static/'):
        clean = clean[len('static/'):]

    base = Path(current_app.static_folder or 'static')
    abs_path = base / clean
    if abs_path.exists() and abs_path.is_file():
        return str(abs_path)
    return None


def validate_color(hex_color: Optional[str]) -> Optional[str]:
    """
    Valida un color hexadecimal.

    Args:
        hex_color: '#RRGGBB' o None

    Returns:
        El color limpio si es válido, None si es vacío.

    Raises:
        BrandingError si el formato es inválido.
    """
    if not hex_color:
        return None

    color = hex_color.strip()
    if not color:
        return None

    # Agregar # si falta
    if not color.startswith('#'):
        color = '#' + color

    if not HEX_COLOR_RE.match(color):
        raise BrandingError('Color inválido. Usar formato #RRGGBB (ej: #1a3556).')

    return color.lower()


def get_branding_dict(organizacion) -> dict:
    """
    Devuelve un dict con el branding de una organización para usar en
    templates y PDFs. Si algún campo está vacío, usa defaults.
    """
    if not organizacion:
        return {
            'nombre_display': 'OBYRA',
            'nombre_legal': 'OBYRA',
            'logo_url': None,
            'logo_path': None,
            'color_primario': '#1a3556',
            'cuit': None,
            'direccion': None,
            'telefono': None,
            'email': None,
        }

    nombre_legal = organizacion.nombre or 'OBYRA'
    nombre_fantasia = getattr(organizacion, 'nombre_fantasia', None)
    nombre_display = nombre_fantasia or nombre_legal

    logo_url = getattr(organizacion, 'logo_url', None)
    logo_path = get_logo_absolute_path(logo_url) if logo_url else None

    return {
        'nombre_display': nombre_display,
        'nombre_legal': nombre_legal,
        'nombre_fantasia': nombre_fantasia,
        'logo_url': logo_url,
        'logo_path': logo_path,
        'color_primario': getattr(organizacion, 'color_primario', None) or '#1a3556',
        'cuit': getattr(organizacion, 'cuit', None),
        'direccion': getattr(organizacion, 'direccion', None),
        'telefono': getattr(organizacion, 'telefono', None),
        'email': getattr(organizacion, 'email', None),
    }
