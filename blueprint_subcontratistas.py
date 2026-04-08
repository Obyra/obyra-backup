"""
Blueprint de Subcontratistas - CRUD + gestion documental con alertas de vencimiento.
"""
from datetime import datetime, date
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app, send_file)
from flask_login import login_required, current_user
from sqlalchemy import or_

from extensions import db
from models.subcontratista import Subcontratista, DocumentoSubcontratista
from services.memberships import get_current_org_id
from services.storage_service import storage


subcontratistas_bp = Blueprint('subcontratistas', __name__, url_prefix='/subcontratistas')


ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'webp', 'doc', 'docx'}
TIPOS_DOCUMENTO = [
    ('seguro_art', 'Seguro ART'),
    ('contrato', 'Contrato'),
    ('poliza', 'Poliza de Responsabilidad Civil'),
    ('habilitacion', 'Habilitacion / Matricula'),
    ('constancia_afip', 'Constancia AFIP'),
    ('otro', 'Otro'),
]


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _require_org():
    org_id = get_current_org_id()
    if not org_id:
        flash('No tienes una organizacion activa', 'warning')
        return None
    return org_id


def _get_sub_or_404(sub_id, org_id):
    sub = Subcontratista.query.get_or_404(sub_id)
    if sub.organizacion_id != org_id:
        return None
    return sub


@subcontratistas_bp.route('/')
@login_required
def lista():
    org_id = _require_org()
    if not org_id:
        return redirect(url_for('index'))

    buscar = request.args.get('buscar', '').strip()
    rubro = request.args.get('rubro', '').strip()
    estado = request.args.get('estado', '').strip()  # activo / inactivo / todos

    query = Subcontratista.query.filter_by(organizacion_id=org_id)

    if buscar:
        like = f'%{buscar}%'
        query = query.filter(or_(
            Subcontratista.razon_social.ilike(like),
            Subcontratista.nombre_contacto.ilike(like),
            Subcontratista.cuit.ilike(like),
            Subcontratista.email.ilike(like),
        ))

    if rubro:
        query = query.filter(Subcontratista.rubro.ilike(f'%{rubro}%'))

    if estado == 'activo':
        query = query.filter_by(activo=True)
    elif estado == 'inactivo':
        query = query.filter_by(activo=False)

    query = query.order_by(Subcontratista.razon_social.asc())

    page = request.args.get('page', 1, type=int)
    pagination = query.paginate(page=page, per_page=20, error_out=False)

    return render_template(
        'subcontratistas/lista.html',
        subcontratistas=pagination.items,
        pagination=pagination,
        buscar=buscar,
        rubro=rubro,
        estado=estado,
    )


@subcontratistas_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    org_id = _require_org()
    if not org_id:
        return redirect(url_for('index'))

    if request.method == 'POST':
        razon_social = request.form.get('razon_social', '').strip()
        if not razon_social:
            flash('La razon social es obligatoria', 'danger')
            return redirect(url_for('subcontratistas.crear'))

        sub = Subcontratista(
            organizacion_id=org_id,
            razon_social=razon_social,
            nombre_contacto=request.form.get('nombre_contacto', '').strip() or None,
            cuit=request.form.get('cuit', '').strip() or None,
            rubro=request.form.get('rubro', '').strip() or None,
            email=request.form.get('email', '').strip() or None,
            telefono=request.form.get('telefono', '').strip() or None,
            direccion=request.form.get('direccion', '').strip() or None,
            ciudad=request.form.get('ciudad', '').strip() or None,
            provincia=request.form.get('provincia', '').strip() or None,
            notas=request.form.get('notas', '').strip() or None,
        )
        try:
            db.session.add(sub)
            db.session.commit()
            flash(f'Subcontratista "{sub.razon_social}" creado correctamente', 'success')
            return redirect(url_for('subcontratistas.detalle', sub_id=sub.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error creando subcontratista')
            flash(f'Error al crear: {e}', 'danger')

    return render_template('subcontratistas/crear.html')


@subcontratistas_bp.route('/<int:sub_id>')
@login_required
def detalle(sub_id):
    org_id = _require_org()
    if not org_id:
        return redirect(url_for('index'))

    sub = _get_sub_or_404(sub_id, org_id)
    if not sub:
        flash('No tienes permiso para ver este subcontratista', 'danger')
        return redirect(url_for('subcontratistas.lista'))

    documentos = sub.documentos.order_by(DocumentoSubcontratista.fecha_vencimiento.asc().nullslast()).all()
    return render_template(
        'subcontratistas/detalle.html',
        sub=sub,
        documentos=documentos,
        tipos_documento=TIPOS_DOCUMENTO,
    )


@subcontratistas_bp.route('/<int:sub_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(sub_id):
    org_id = _require_org()
    if not org_id:
        return redirect(url_for('index'))

    sub = _get_sub_or_404(sub_id, org_id)
    if not sub:
        flash('No tienes permiso para editar este subcontratista', 'danger')
        return redirect(url_for('subcontratistas.lista'))

    if request.method == 'POST':
        sub.razon_social = request.form.get('razon_social', '').strip() or sub.razon_social
        sub.nombre_contacto = request.form.get('nombre_contacto', '').strip() or None
        sub.cuit = request.form.get('cuit', '').strip() or None
        sub.rubro = request.form.get('rubro', '').strip() or None
        sub.email = request.form.get('email', '').strip() or None
        sub.telefono = request.form.get('telefono', '').strip() or None
        sub.direccion = request.form.get('direccion', '').strip() or None
        sub.ciudad = request.form.get('ciudad', '').strip() or None
        sub.provincia = request.form.get('provincia', '').strip() or None
        sub.notas = request.form.get('notas', '').strip() or None
        sub.activo = request.form.get('activo') == 'on'

        try:
            db.session.commit()
            flash('Subcontratista actualizado correctamente', 'success')
            return redirect(url_for('subcontratistas.detalle', sub_id=sub.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error actualizando subcontratista')
            flash(f'Error: {e}', 'danger')

    return render_template('subcontratistas/editar.html', sub=sub)


@subcontratistas_bp.route('/<int:sub_id>/eliminar', methods=['POST'])
@login_required
def eliminar(sub_id):
    org_id = _require_org()
    if not org_id:
        return jsonify(ok=False, error='Sin organizacion'), 400

    sub = _get_sub_or_404(sub_id, org_id)
    if not sub:
        return jsonify(ok=False, error='No autorizado'), 403

    try:
        # Eliminar archivos del storage
        for doc in sub.documentos.all():
            if doc.archivo_url:
                try:
                    storage.delete(doc.archivo_url)
                except Exception:
                    pass
        db.session.delete(sub)
        db.session.commit()
        flash('Subcontratista eliminado correctamente', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error eliminando subcontratista')
        return jsonify(ok=False, error=str(e)), 500


@subcontratistas_bp.route('/<int:sub_id>/documentos', methods=['POST'])
@login_required
def subir_documento(sub_id):
    org_id = _require_org()
    if not org_id:
        return redirect(url_for('index'))

    sub = _get_sub_or_404(sub_id, org_id)
    if not sub:
        flash('No autorizado', 'danger')
        return redirect(url_for('subcontratistas.lista'))

    archivo = request.files.get('archivo')
    tipo = request.form.get('tipo', 'otro').strip()
    descripcion = request.form.get('descripcion', '').strip() or None
    fecha_emision_str = request.form.get('fecha_emision', '').strip()
    fecha_venc_str = request.form.get('fecha_vencimiento', '').strip()

    if not archivo or not archivo.filename:
        flash('Debes seleccionar un archivo', 'warning')
        return redirect(url_for('subcontratistas.detalle', sub_id=sub_id))

    if not _allowed_file(archivo.filename):
        flash('Tipo de archivo no permitido (PDF, JPG, PNG, DOCX)', 'danger')
        return redirect(url_for('subcontratistas.detalle', sub_id=sub_id))

    try:
        ext = archivo.filename.rsplit('.', 1)[1].lower()
        from werkzeug.utils import secure_filename
        safe_name = secure_filename(archivo.filename)
        key = f'subcontratistas/{org_id}/{sub_id}/{int(datetime.utcnow().timestamp())}_{safe_name}'

        storage.save(archivo, key=key, content_type=archivo.content_type)

        fecha_emision = datetime.strptime(fecha_emision_str, '%Y-%m-%d').date() if fecha_emision_str else None
        fecha_venc = datetime.strptime(fecha_venc_str, '%Y-%m-%d').date() if fecha_venc_str else None

        doc = DocumentoSubcontratista(
            subcontratista_id=sub.id,
            tipo=tipo,
            descripcion=descripcion,
            archivo_url=key,
            archivo_nombre=safe_name,
            fecha_emision=fecha_emision,
            fecha_vencimiento=fecha_venc,
            uploaded_by_id=current_user.id,
        )
        db.session.add(doc)
        db.session.commit()
        flash('Documento subido correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error subiendo documento')
        flash(f'Error al subir documento: {e}', 'danger')

    return redirect(url_for('subcontratistas.detalle', sub_id=sub_id))


@subcontratistas_bp.route('/<int:sub_id>/documentos/<int:doc_id>/eliminar', methods=['POST'])
@login_required
def eliminar_documento(sub_id, doc_id):
    org_id = _require_org()
    if not org_id:
        return jsonify(ok=False, error='Sin organizacion'), 400

    sub = _get_sub_or_404(sub_id, org_id)
    if not sub:
        return jsonify(ok=False, error='No autorizado'), 403

    doc = DocumentoSubcontratista.query.filter_by(id=doc_id, subcontratista_id=sub_id).first_or_404()
    try:
        if doc.archivo_url:
            try:
                storage.delete(doc.archivo_url)
            except Exception:
                pass
        db.session.delete(doc)
        db.session.commit()
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@subcontratistas_bp.route('/<int:sub_id>/documentos/<int:doc_id>/descargar')
@login_required
def descargar_documento(sub_id, doc_id):
    org_id = _require_org()
    if not org_id:
        return redirect(url_for('index'))

    sub = _get_sub_or_404(sub_id, org_id)
    if not sub:
        flash('No autorizado', 'danger')
        return redirect(url_for('subcontratistas.lista'))

    doc = DocumentoSubcontratista.query.filter_by(id=doc_id, subcontratista_id=sub_id).first_or_404()
    if not doc.archivo_url:
        flash('Documento sin archivo asociado', 'warning')
        return redirect(url_for('subcontratistas.detalle', sub_id=sub_id))

    try:
        content = storage.read(doc.archivo_url)
        if not content:
            flash('No se pudo leer el archivo', 'danger')
            return redirect(url_for('subcontratistas.detalle', sub_id=sub_id))

        from io import BytesIO
        return send_file(
            BytesIO(content),
            download_name=doc.archivo_nombre or 'documento',
            as_attachment=True,
        )
    except Exception as e:
        current_app.logger.exception('Error descargando documento')
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('subcontratistas.detalle', sub_id=sub_id))
