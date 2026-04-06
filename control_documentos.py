"""
Blueprint de Documentos de Obra (Legajo Digital)

Gestión de documentos vinculados a obras: contratos, planos, renders,
pliego de especificaciones, memoria de cálculo, etc.
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file, abort, current_app
from flask_login import login_required, current_user
from datetime import datetime
import os
import uuid
from werkzeug.utils import secure_filename
from extensions import db

documentos_bp = Blueprint('documentos', __name__, url_prefix='/documentos')

ALLOWED_DOC_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'csv',
    'jpg', 'jpeg', 'png', 'gif', 'webp',
    'dwg', 'dxf', 'zip', 'rar',
}


def _tiene_permiso_docs():
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin', 'tecnico') or role in ('admin', 'pm', 'tecnico')


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_DOC_EXTENSIONS


# ============================================================
# API: Listar documentos de una obra (JSON)
# ============================================================

@documentos_bp.route('/obra/<int:obra_id>/listar')
@login_required
def listar_por_obra(obra_id):
    from models.projects import Obra

    obra = Obra.query.get_or_404(obra_id)
    if obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error='Sin acceso'), 403

    docs = db.session.execute(
        db.text("""
            SELECT d.id, d.nombre, d.descripcion, d.archivo_path, d.version,
                   d.estado, d.fecha_creacion, d.tags,
                   t.nombre as tipo_nombre, t.categoria as tipo_categoria,
                   u.nombre as creador_nombre
            FROM documentos_obra d
            LEFT JOIN tipos_documento t ON d.tipo_documento_id = t.id
            LEFT JOIN usuarios u ON d.creado_por_id = u.id
            WHERE d.obra_id = :obra_id
            ORDER BY t.categoria, d.fecha_creacion DESC
        """),
        {'obra_id': obra_id}
    ).fetchall()

    result = []
    for d in docs:
        result.append({
            'id': d.id,
            'nombre': d.nombre,
            'descripcion': d.descripcion,
            'archivo_path': d.archivo_path,
            'version': d.version,
            'estado': d.estado,
            'fecha': d.fecha_creacion.strftime('%d/%m/%Y') if d.fecha_creacion else '',
            'tipo_nombre': d.tipo_nombre,
            'tipo_categoria': d.tipo_categoria,
            'creador': d.creador_nombre,
            'tags': d.tags,
        })

    return jsonify(ok=True, documentos=result)


# ============================================================
# API: Listar tipos de documento
# ============================================================

@documentos_bp.route('/tipos')
@login_required
def listar_tipos():
    tipos = db.session.execute(
        db.text("SELECT id, nombre, categoria FROM tipos_documento WHERE activo = true ORDER BY categoria, nombre")
    ).fetchall()

    result = [{'id': t.id, 'nombre': t.nombre, 'categoria': t.categoria} for t in tipos]
    return jsonify(ok=True, tipos=result)


# ============================================================
# SUBIR DOCUMENTO
# ============================================================

@documentos_bp.route('/obra/<int:obra_id>/subir', methods=['POST'])
@login_required
def subir(obra_id):
    from models.projects import Obra

    if not _tiene_permiso_docs():
        flash('No tiene permisos para subir documentos.', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    obra = Obra.query.get_or_404(obra_id)
    if obra.organizacion_id != current_user.organizacion_id:
        flash('Sin acceso.', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    if 'archivo' not in request.files:
        flash('No se selecciono ningun archivo.', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    archivo = request.files['archivo']
    if archivo.filename == '':
        flash('No se selecciono ningun archivo.', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    if not _allowed_file(archivo.filename):
        flash('Tipo de archivo no permitido.', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    try:
        tipo_doc_id = request.form.get('tipo_documento_id', type=int)
        nombre = request.form.get('nombre', '').strip() or archivo.filename
        descripcion = request.form.get('descripcion', '').strip()

        # Crear directorio de uploads
        upload_dir = os.path.join(current_app.static_folder, 'uploads', 'obras', str(obra_id), 'documentos')
        os.makedirs(upload_dir, exist_ok=True)

        # Nombre único
        filename = secure_filename(archivo.filename)
        unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        filepath = os.path.join(upload_dir, unique_name)
        archivo.save(filepath)

        # Path relativo para guardar en DB
        relative_path = f"uploads/obras/{obra_id}/documentos/{unique_name}"

        # Insertar en BD
        org_id = current_user.organizacion_id
        db.session.execute(
            db.text("""
                INSERT INTO documentos_obra
                    (obra_id, tipo_documento_id, organizacion_id, nombre, descripcion,
                     archivo_path, creado_por_id, fecha_creacion, fecha_modificacion, estado)
                VALUES
                    (:obra_id, :tipo_id, :org_id, :nombre, :desc,
                     :path, :user_id, NOW(), NOW(), 'activo')
            """),
            {
                'obra_id': obra_id, 'tipo_id': tipo_doc_id, 'org_id': org_id,
                'nombre': nombre, 'desc': descripcion,
                'path': relative_path, 'user_id': current_user.id,
            }
        )
        db.session.commit()

        flash(f'Documento "{nombre}" subido exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error subiendo documento: {e}")
        flash(f'Error al subir documento: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=obra_id))


# ============================================================
# DESCARGAR DOCUMENTO
# ============================================================

@documentos_bp.route('/<int:id>/descargar')
@login_required
def descargar(id):
    doc = db.session.execute(
        db.text("""
            SELECT d.archivo_path, d.nombre, d.obra_id, o.organizacion_id
            FROM documentos_obra d
            JOIN obras o ON d.obra_id = o.id
            WHERE d.id = :id
        """), {'id': id}
    ).fetchone()

    if not doc:
        abort(404)

    from services.memberships import get_current_org_id
    if doc.organizacion_id != get_current_org_id():
        abort(403)

    filepath = os.path.join(current_app.static_folder, doc.archivo_path)
    if not os.path.exists(filepath):
        flash('Archivo no encontrado en el servidor.', 'danger')
        return redirect(url_for('obras.detalle', id=doc.obra_id))

    return send_file(filepath, as_attachment=True, download_name=doc.nombre)


# ============================================================
# ELIMINAR DOCUMENTO
# ============================================================

@documentos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar(id):
    if not _tiene_permiso_docs():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('main.dashboard'))

    doc = db.session.execute(
        db.text("""
            SELECT d.id, d.archivo_path, d.obra_id, o.organizacion_id
            FROM documentos_obra d
            JOIN obras o ON d.obra_id = o.id
            WHERE d.id = :id
        """), {'id': id}
    ).fetchone()

    if not doc:
        abort(404)

    from services.memberships import get_current_org_id
    if doc.organizacion_id != get_current_org_id():
        abort(403)

    # Eliminar archivo físico
    filepath = os.path.join(current_app.static_folder, doc.archivo_path)
    if os.path.exists(filepath):
        os.remove(filepath)

    # Eliminar registro
    db.session.execute(db.text("DELETE FROM documentos_obra WHERE id = :id"), {'id': id})
    db.session.commit()

    flash('Documento eliminado.', 'info')
    return redirect(url_for('obras.detalle', id=doc.obra_id))
