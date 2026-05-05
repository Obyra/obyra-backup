"""Servicio de importacion de pliegos de licitacion (Fase 6.A).

Orquesta multi-archivo:
  - Recibe lista de archivos uploaded.
  - Para cada uno: checksum, persistir en disco, parsear, crear items con origen.
  - Si un archivo falla, no aborta los demas.
  - Devuelve resumen con resultados por archivo.

Storage: storage/uploads/presupuestos/<presupuesto_id>/<sha256_short>.xlsx
(fuera de /static/, no servido directamente).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from flask import current_app

from extensions import db


# Limites
MAX_BYTES_POR_ARCHIVO = 10 * 1024 * 1024     # 10 MB
MAX_BYTES_POR_PRESUPUESTO = 50 * 1024 * 1024  # 50 MB

STORAGE_BASE = 'storage'
STORAGE_UPLOADS = os.path.join(STORAGE_BASE, 'uploads', 'presupuestos')


def _asegurar_carpeta(path):
    os.makedirs(path, exist_ok=True)


def _calcular_checksum(file_storage):
    """SHA256 del contenido. Lee en bloques. Resetea el stream al final."""
    h = hashlib.sha256()
    file_storage.stream.seek(0)
    while True:
        buf = file_storage.stream.read(65536)
        if not buf:
            break
        h.update(buf)
    file_storage.stream.seek(0)
    return h.hexdigest()


def _size_of(file_storage):
    """Tamaño en bytes del file_storage (consumiendo stream)."""
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    return size


def _path_storage(presupuesto_id, checksum_short, ext='.xlsx'):
    """Devuelve path absoluto en storage/ para guardar el archivo."""
    carpeta = os.path.join(STORAGE_UPLOADS, str(presupuesto_id))
    _asegurar_carpeta(carpeta)
    return os.path.join(carpeta, f'{checksum_short}{ext}')


def usado_total_presupuesto(presupuesto_id):
    """Suma de size_bytes de archivos no eliminados del presupuesto."""
    from models.presupuesto_archivo import PresupuestoArchivo
    total = (db.session.query(db.func.coalesce(db.func.sum(PresupuestoArchivo.size_bytes), 0))
             .filter(PresupuestoArchivo.presupuesto_id == presupuesto_id,
                     PresupuestoArchivo.deleted_at.is_(None))
             .scalar() or 0)
    return int(total)


def _validar_archivo(file_storage, presupuesto_id, total_acumulado_actual):
    """Valida tamaño individual + total acumulado.

    Returns (ok, error_msg, size).
    """
    if not file_storage or not file_storage.filename:
        return False, 'Archivo vacío.', 0
    nombre = file_storage.filename
    if not nombre.lower().endswith(('.xlsx', '.xls')):
        return False, f'Formato no soportado en "{nombre}". Solo .xlsx o .xls.', 0
    size = _size_of(file_storage)
    if size > MAX_BYTES_POR_ARCHIVO:
        mb = size / (1024 * 1024)
        return False, f'"{nombre}" supera el límite de 10 MB ({mb:.1f} MB).', size
    if total_acumulado_actual + size > MAX_BYTES_POR_PRESUPUESTO:
        return False, (
            f'"{nombre}" excede el límite de 50 MB acumulados por presupuesto.'
        ), size
    return True, None, size


def _persistir_archivo_disco(file_storage, presupuesto_id, checksum):
    """Copia el archivo al storage seguro. Devuelve (path_absoluto, filename_storage)."""
    short = checksum[:16]
    ext = '.xlsx' if file_storage.filename.lower().endswith('.xlsx') else '.xls'
    path_abs = _path_storage(presupuesto_id, short, ext)
    file_storage.stream.seek(0)
    file_storage.save(path_abs)
    return path_abs, f'{short}{ext}'


def _crear_items_con_origen(presupuesto, items_parseados, archivo_pa, modo_licitacion):
    """Crea ItemPresupuesto a partir de parser + archivo origen. Retorna count."""
    from models.budgets import ItemPresupuesto
    from services.etapa_matcher import matchear_etapa_para_item

    creados = 0
    subtotal = Decimal('0')
    for it in items_parseados:
        etapa_excel = it.get('etapa_nombre')
        etapa_estandar = matchear_etapa_para_item(it['descripcion'], etapa_excel)
        etapa_final = etapa_estandar or etapa_excel

        precio = Decimal('0') if modo_licitacion else (it.get('precio_unitario') or Decimal('0'))
        cantidad = it['cantidad']
        total_item = cantidad * precio

        ip = ItemPresupuesto(
            presupuesto_id=presupuesto.id,
            tipo='material',
            descripcion=it['descripcion'],
            unidad=it['unidad'],
            cantidad=cantidad,
            precio_unitario=precio,
            total=total_item,
            origen='importado',
            currency='ARS',
            etapa_nombre=etapa_final,
            archivo_origen_id=archivo_pa.id,
            hoja_origen=it.get('hoja_origen'),
            fila_origen=it.get('fila_origen'),
            columna_descripcion_origen=it.get('columna_descripcion_origen'),
        )
        db.session.add(ip)
        creados += 1
        subtotal += total_item
    return creados, subtotal


def importar_pliego_multi(
    *,
    presupuesto,
    archivos_files,
    user_id,
    modo_licitacion=True,
    parser_func=None,
):
    """Itera N archivos, persiste, parsea y crea items con origen.

    NO commitea el presupuesto principal — el caller lo hace.
    PERO commitea cada archivo individualmente para que un fallo en el N+1
    no rompa los previos.

    Args:
      presupuesto: instancia Presupuesto ya creada y persistida (con id).
      archivos_files: lista de werkzeug FileStorage.
      user_id: id del usuario que sube.
      modo_licitacion: bool. Si True, precios del Excel se ignoran.
      parser_func: callable para parsear un file. Si None, usa
        blueprint_presupuestos.importar_licitacion._parsear_xlsx.

    Returns:
      {
        'archivos': [
          {
            'archivo_id', 'filename', 'estado', 'items_importados',
            'error_message', 'size_bytes', 'duplicado': bool,
          },
          ...
        ],
        'total_items_importados': int,
        'total_archivos_ok': int,
        'total_archivos_error': int,
        'duplicados_skipped': int,
        'total_size_bytes': int,
      }
    """
    from models.presupuesto_archivo import PresupuestoArchivo
    from models.audit import registrar_audit

    if parser_func is None:
        from blueprint_presupuestos.importar_licitacion import _parsear_xlsx
        parser_func = _parsear_xlsx

    resumen = {
        'archivos': [],
        'total_items_importados': 0,
        'total_archivos_ok': 0,
        'total_archivos_error': 0,
        'duplicados_skipped': 0,
        'total_size_bytes': 0,
    }

    # Tamaño usado al inicio (puede haber archivos de uploads previos en este mismo presupuesto)
    total_usado = usado_total_presupuesto(presupuesto.id)

    for fs in archivos_files:
        if not fs or not fs.filename:
            continue

        # 1. Validar tamaño
        ok, err, size = _validar_archivo(fs, presupuesto.id, total_usado)
        if not ok:
            resumen['archivos'].append({
                'filename': fs.filename if fs else '',
                'estado': 'rechazado',
                'items_importados': 0,
                'error_message': err,
                'size_bytes': size,
                'duplicado': False,
            })
            resumen['total_archivos_error'] += 1
            continue

        # 2. Checksum
        try:
            checksum = _calcular_checksum(fs)
        except Exception as e:
            resumen['archivos'].append({
                'filename': fs.filename,
                'estado': 'error',
                'items_importados': 0,
                'error_message': f'Error calculando checksum: {type(e).__name__}',
                'size_bytes': size,
                'duplicado': False,
            })
            resumen['total_archivos_error'] += 1
            continue

        # 3. Detectar duplicado exacto (mismo presupuesto, mismo contenido)
        ya_existe = PresupuestoArchivo.query.filter_by(
            presupuesto_id=presupuesto.id,
            checksum_sha256=checksum,
        ).first()
        if ya_existe:
            resumen['archivos'].append({
                'archivo_id': ya_existe.id,
                'filename': fs.filename,
                'estado': 'duplicado',
                'items_importados': 0,
                'error_message': 'Este archivo ya está cargado en este presupuesto.',
                'size_bytes': size,
                'duplicado': True,
            })
            resumen['duplicados_skipped'] += 1
            continue

        # 4. Persistir en disco
        try:
            path_abs, filename_storage = _persistir_archivo_disco(fs, presupuesto.id, checksum)
        except Exception as e:
            current_app.logger.exception('Error persistiendo archivo')
            resumen['archivos'].append({
                'filename': fs.filename,
                'estado': 'error',
                'items_importados': 0,
                'error_message': f'No se pudo guardar el archivo: {type(e).__name__}',
                'size_bytes': size,
                'duplicado': False,
            })
            resumen['total_archivos_error'] += 1
            continue

        # 5. Crear PresupuestoArchivo en estado pendiente
        archivo_pa = PresupuestoArchivo(
            presupuesto_id=presupuesto.id,
            organizacion_id=presupuesto.organizacion_id,
            uploaded_by_user_id=user_id,
            filename_original=fs.filename[:255],
            filename_storage=filename_storage,
            file_path=path_abs,
            mime_type=fs.mimetype,
            size_bytes=size,
            checksum_sha256=checksum,
            tipo_archivo='pliego_excel',
            estado_importacion='pendiente',
            uploaded_at=datetime.utcnow(),
        )
        db.session.add(archivo_pa)
        try:
            db.session.flush()  # para obtener archivo_pa.id
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creando PresupuestoArchivo')
            resumen['archivos'].append({
                'filename': fs.filename,
                'estado': 'error',
                'items_importados': 0,
                'error_message': f'BD: {type(e).__name__}',
                'size_bytes': size,
                'duplicado': False,
            })
            resumen['total_archivos_error'] += 1
            try:
                os.remove(path_abs)
            except Exception:
                pass
            continue

        try:
            registrar_audit(
                accion='archivo_subido',
                entidad='presupuesto_archivo',
                entidad_id=archivo_pa.id,
                detalle=f'pres={presupuesto.id} file="{fs.filename}" size={size}',
            )
        except Exception:
            pass

        # 6. Parsear
        items_parseados = None
        parse_error = None
        hojas_count = 0
        try:
            with open(path_abs, 'rb') as f:
                items_parseados = parser_func(f)
            # Contar hojas (si el archivo es xlsx)
            try:
                import openpyxl
                with open(path_abs, 'rb') as f:
                    wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
                    hojas_count = len(wb.sheetnames)
            except Exception:
                hojas_count = 0
        except Exception as e:
            parse_error = f'{type(e).__name__}: {str(e)[:200]}'
            current_app.logger.exception(f'Error parseando archivo {fs.filename}')

        if parse_error or not items_parseados:
            archivo_pa.estado_importacion = 'error'
            archivo_pa.error_message = parse_error or 'Sin items detectados.'
            archivo_pa.cantidad_hojas_detectadas = hojas_count
            archivo_pa.metadata_json = {
                'parser': 'auto_xlsx',
                'fallo_en': 'parse',
            }
            try:
                registrar_audit(
                    accion='archivo_error_importacion',
                    entidad='presupuesto_archivo',
                    entidad_id=archivo_pa.id,
                    detalle=archivo_pa.error_message[:200],
                )
            except Exception:
                pass
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            resumen['archivos'].append({
                'archivo_id': archivo_pa.id,
                'filename': fs.filename,
                'estado': 'error',
                'items_importados': 0,
                'error_message': archivo_pa.error_message,
                'size_bytes': size,
                'duplicado': False,
            })
            resumen['total_archivos_error'] += 1
            continue

        # 7. Crear items con origen
        try:
            cantidad_creados, subtotal = _crear_items_con_origen(
                presupuesto, items_parseados, archivo_pa, modo_licitacion,
            )
        except Exception as e:
            db.session.rollback()
            archivo_pa.estado_importacion = 'error'
            archivo_pa.error_message = f'Error creando items: {type(e).__name__}'
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            resumen['archivos'].append({
                'archivo_id': archivo_pa.id,
                'filename': fs.filename,
                'estado': 'error',
                'items_importados': 0,
                'error_message': archivo_pa.error_message,
                'size_bytes': size,
                'duplicado': False,
            })
            resumen['total_archivos_error'] += 1
            continue

        archivo_pa.estado_importacion = 'importado'
        archivo_pa.cantidad_hojas_detectadas = hojas_count
        archivo_pa.cantidad_items_detectados = len(items_parseados)
        archivo_pa.cantidad_items_importados = cantidad_creados
        archivo_pa.imported_at = datetime.utcnow()
        archivo_pa.metadata_json = {
            'parser': 'auto_xlsx',
            'modo_licitacion': modo_licitacion,
            'subtotal_archivo': float(subtotal),
        }

        try:
            registrar_audit(
                accion='archivo_importado',
                entidad='presupuesto_archivo',
                entidad_id=archivo_pa.id,
                detalle=f'pres={presupuesto.id} items={cantidad_creados} hojas={hojas_count}',
            )
        except Exception:
            pass

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error commiteando archivo importado')
            resumen['archivos'].append({
                'archivo_id': archivo_pa.id,
                'filename': fs.filename,
                'estado': 'error',
                'items_importados': 0,
                'error_message': f'BD commit: {type(e).__name__}',
                'size_bytes': size,
                'duplicado': False,
            })
            resumen['total_archivos_error'] += 1
            continue

        resumen['archivos'].append({
            'archivo_id': archivo_pa.id,
            'filename': fs.filename,
            'estado': 'importado',
            'items_importados': cantidad_creados,
            'error_message': None,
            'size_bytes': size,
            'duplicado': False,
        })
        resumen['total_archivos_ok'] += 1
        resumen['total_items_importados'] += cantidad_creados
        resumen['total_size_bytes'] += size
        total_usado += size

    return resumen


def listar_archivos(presupuesto_id):
    """Devuelve los archivos no-eliminados del presupuesto."""
    from models.presupuesto_archivo import PresupuestoArchivo
    return (PresupuestoArchivo.query
            .filter(PresupuestoArchivo.presupuesto_id == presupuesto_id,
                    PresupuestoArchivo.deleted_at.is_(None))
            .order_by(PresupuestoArchivo.uploaded_at)
            .all())


def descargar_archivo_path(archivo_id, organizacion_id_caller, es_super_admin=False):
    """Devuelve (PresupuestoArchivo, path_absoluto) si el caller tiene acceso.
    Lanza PermissionError o FileNotFoundError segun caso.
    """
    from models.presupuesto_archivo import PresupuestoArchivo
    archivo = PresupuestoArchivo.query.get(archivo_id)
    if not archivo or archivo.deleted_at is not None:
        raise FileNotFoundError('Archivo no encontrado.')
    if not es_super_admin and archivo.organizacion_id != organizacion_id_caller:
        raise PermissionError('Sin acceso al archivo (multi-tenant).')
    if not os.path.exists(archivo.file_path):
        raise FileNotFoundError('Archivo no encontrado en storage.')
    return archivo, archivo.file_path
