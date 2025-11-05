"""
Módulo de Control de Documentos y Datos - OBYRA IA
Gestión digital de documentos, control de versiones y data management
para proyectos de construcción.
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file, abort
from flask_login import login_required, current_user
from datetime import datetime, date
import json
import os
from werkzeug.utils import secure_filename
from utils.pagination import Pagination
from app import db
from models import *
from utils import *

documentos_bp = Blueprint('documentos', __name__)

@documentos_bp.before_request
@login_required
def _block_operario_docs():
    """Bloquear acceso a documentos para operarios"""
    if getattr(current_user, 'role', None) == 'operario':
        abort(403)

class TipoDocumento(db.Model):
    __tablename__ = 'tipos_documento'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), nullable=False)  # contractual, tecnico, administrativo, legal
    requiere_aprobacion = db.Column(db.Boolean, default=False)
    retención_años = db.Column(db.Integer, default=10)
    activo = db.Column(db.Boolean, default=True)

class DocumentoObra(db.Model):
    __tablename__ = 'documentos_obra'
    
    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    tipo_documento_id = db.Column(db.Integer, db.ForeignKey('tipos_documento.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    archivo_path = db.Column(db.String(500), nullable=False)
    version = db.Column(db.String(10), default='1.0')
    estado = db.Column(db.String(20), default='borrador')  # borrador, revision, aprobado, obsoleto
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_modificacion = db.Column(db.DateTime, default=datetime.utcnow)
    creado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    aprobado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    fecha_aprobacion = db.Column(db.DateTime)
    tags = db.Column(db.String(500))  # Tags separados por comas
    
    # Relaciones
    obra = db.relationship('Obra')
    tipo_documento = db.relationship('TipoDocumento')
    creado_por = db.relationship('Usuario', foreign_keys=[creado_por_id])
    aprobado_por = db.relationship('Usuario', foreign_keys=[aprobado_por_id])

class VersionDocumento(db.Model):
    __tablename__ = 'versiones_documento'
    
    id = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey('documentos_obra.id'), nullable=False)
    version = db.Column(db.String(10), nullable=False)
    archivo_path = db.Column(db.String(500), nullable=False)
    comentarios = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    creado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    # Relaciones
    documento = db.relationship('DocumentoObra')
    creado_por = db.relationship('Usuario')

class PermisoDocumento(db.Model):
    __tablename__ = 'permisos_documento'
    
    id = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey('documentos_obra.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    permiso = db.Column(db.String(20), nullable=False)  # lectura, escritura, aprobacion
    fecha_otorgado = db.Column(db.DateTime, default=datetime.utcnow)
    otorgado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    # Relaciones
    documento = db.relationship('DocumentoObra')
    usuario = db.relationship('Usuario', foreign_keys=[usuario_id])
    otorgado_por = db.relationship('Usuario', foreign_keys=[otorgado_por_id])

@documentos_bp.route('/')
@login_required
def dashboard():
    """Dashboard principal del control de documentos"""
    # Estadísticas
    total_documentos = DocumentoObra.query.count()
    documentos_pendientes = DocumentoObra.query.filter_by(estado='revision').count()
    documentos_mes = DocumentoObra.query.filter(
        DocumentoObra.fecha_creacion >= datetime.now().replace(day=1)
    ).count()
    
    # Documentos recientes
    documentos_recientes = DocumentoObra.query.order_by(
        DocumentoObra.fecha_modificacion.desc()
    ).limit(10).all()
    
    # Documentos por aprobar
    documentos_aprobar = DocumentoObra.query.filter_by(estado='revision').limit(5).all()
    
    return render_template('documentos/dashboard.html',
                         total_documentos=total_documentos,
                         documentos_pendientes=documentos_pendientes,
                         documentos_mes=documentos_mes,
                         documentos_recientes=documentos_recientes,
                         documentos_aprobar=documentos_aprobar)

@documentos_bp.route('/biblioteca')
@login_required
def biblioteca():
    """Biblioteca digital de documentos"""
    # Filtros
    obra_id = request.args.get('obra_id', type=int)
    tipo_id = request.args.get('tipo_id', type=int)
    estado = request.args.get('estado')
    busqueda = request.args.get('q')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    # Query base
    query = DocumentoObra.query
    
    # Aplicar filtros
    if obra_id:
        query = query.filter_by(obra_id=obra_id)
    if tipo_id:
        query = query.filter_by(tipo_documento_id=tipo_id)
    if estado:
        query = query.filter_by(estado=estado)
    if busqueda:
        query = query.filter(DocumentoObra.nombre.contains(busqueda))

    documentos = query.order_by(DocumentoObra.fecha_modificacion.desc()).paginate(page=page, per_page=per_page, error_out=False)

    # Datos para filtros
    obras = Obra.query.all()
    tipos_documento = TipoDocumento.query.filter_by(activo=True).all()

    return render_template('documentos/biblioteca.html',
                         documentos=documentos,
                         obras=obras,
                         tipos_documento=tipos_documento)

@documentos_bp.route('/subir_documento')
@login_required
def subir_documento():
    """Formulario para subir nuevo documento"""
    obras = Obra.query.all()
    tipos_documento = TipoDocumento.query.filter_by(activo=True).all()
    return render_template('documentos/subir.html', obras=obras, tipos_documento=tipos_documento)

@documentos_bp.route('/subir_documento', methods=['POST'])
@login_required
def procesar_subida():
    """Procesa la subida de un nuevo documento"""
    try:
        if 'archivo' not in request.files:
            flash('No se seleccionó ningún archivo', 'danger')
            return redirect(request.url)
        
        archivo = request.files['archivo']
        if archivo.filename == '':
            flash('No se seleccionó ningún archivo', 'danger')
            return redirect(request.url)
        
        if archivo:
            # Crear directorio si no existe
            upload_dir = os.path.join('uploads', 'documentos')
            os.makedirs(upload_dir, exist_ok=True)
            
            # Generar nombre seguro
            filename = secure_filename(archivo.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{filename}"
            filepath = os.path.join(upload_dir, filename)
            
            # Guardar archivo
            archivo.save(filepath)
            
            # Crear registro en base de datos
            documento = DocumentoObra(
                obra_id=request.form.get('obra_id'),
                tipo_documento_id=request.form.get('tipo_documento_id'),
                nombre=request.form.get('nombre'),
                descripcion=request.form.get('descripcion'),
                archivo_path=filepath,
                creado_por_id=current_user.id,
                tags=request.form.get('tags')
            )
            
            db.session.add(documento)
            db.session.commit()
            
            flash('Documento subido correctamente', 'success')
            return redirect(url_for('documentos.biblioteca'))
    
    except Exception as e:
        db.session.rollback()
        flash(f'Error al subir documento: {str(e)}', 'danger')
        return redirect(url_for('documentos.subir_documento'))

@documentos_bp.route('/documento/<int:documento_id>')
@login_required
def ver_documento(documento_id):
    """Vista detallada de un documento"""
    documento = DocumentoObra.query.get_or_404(documento_id)
    versiones = VersionDocumento.query.filter_by(documento_id=documento_id).order_by(
        VersionDocumento.fecha_creacion.desc()
    ).all()
    
    return render_template('documentos/detalle.html', documento=documento, versiones=versiones)

@documentos_bp.route('/descargar/<int:documento_id>')
@login_required
def descargar_documento(documento_id):
    """Descarga un documento"""
    documento = DocumentoObra.query.get_or_404(documento_id)
    
    # Verificar permisos (implementar lógica según necesidad)
    if not verificar_permiso_documento(documento_id, current_user.id, 'lectura'):
        flash('No tienes permisos para acceder a este documento', 'danger')
        return redirect(url_for('documentos.biblioteca'))
    
    return send_file(documento.archivo_path, as_attachment=True)

@documentos_bp.route('/aprobar_documento/<int:documento_id>', methods=['POST'])
@login_required
def aprobar_documento(documento_id):
    """Aprueba un documento"""
    documento = DocumentoObra.query.get_or_404(documento_id)
    
    # Verificar permisos de aprobación
    if not current_user.rol in ['administrador', 'tecnico']:
        flash('No tienes permisos para aprobar documentos', 'danger')
        return redirect(url_for('documentos.ver_documento', documento_id=documento_id))
    
    documento.estado = 'aprobado'
    documento.aprobado_por_id = current_user.id
    documento.fecha_aprobacion = datetime.utcnow()
    
    db.session.commit()
    flash('Documento aprobado correctamente', 'success')
    
    return redirect(url_for('documentos.ver_documento', documento_id=documento_id))

@documentos_bp.route('/nueva_version/<int:documento_id>')
@login_required
def nueva_version(documento_id):
    """Formulario para nueva versión de documento"""
    documento = DocumentoObra.query.get_or_404(documento_id)
    return render_template('documentos/nueva_version.html', documento=documento)

@documentos_bp.route('/control_versiones')
@login_required
def control_versiones():
    """Panel de control de versiones"""
    documentos_multiples_versiones = db.session.query(DocumentoObra).join(VersionDocumento).group_by(
        DocumentoObra.id
    ).having(db.func.count(VersionDocumento.id) > 1).all()
    
    return render_template('documentos/versiones.html', documentos=documentos_multiples_versiones)

@documentos_bp.route('/configuracion_tipos')
@login_required
def configuracion_tipos():
    """Configuración de tipos de documento"""
    if current_user.rol != 'administrador':
        flash('Solo los administradores pueden configurar tipos de documento', 'danger')
        return redirect(url_for('documentos.dashboard'))
    
    tipos = TipoDocumento.query.all()
    return render_template('documentos/configuracion_tipos.html', tipos=tipos)

@documentos_bp.route('/reportes_documentos')
@login_required
def reportes():
    """Reportes y analytics de documentos"""
    reporte_data = generar_reporte_documentos()
    return render_template('documentos/reportes.html', reporte=reporte_data)

def verificar_permiso_documento(documento_id, usuario_id, tipo_permiso):
    """Verifica si un usuario tiene permiso específico sobre un documento"""
    # Administradores tienen acceso total
    usuario = Usuario.query.get(usuario_id)
    if usuario.rol == 'administrador':
        return True
    
    # Verificar permiso específico
    permiso = PermisoDocumento.query.filter_by(
        documento_id=documento_id,
        usuario_id=usuario_id,
        permiso=tipo_permiso
    ).first()
    
    return permiso is not None

def generar_reporte_documentos():
    """Genera reporte estadístico de documentos"""
    return {
        'documentos_por_obra': db.session.query(
            Obra.nombre, db.func.count(DocumentoObra.id)
        ).join(DocumentoObra).group_by(Obra.id).all(),
        
        'documentos_por_tipo': db.session.query(
            TipoDocumento.nombre, db.func.count(DocumentoObra.id)
        ).join(DocumentoObra).group_by(TipoDocumento.id).all(),
        
        'documentos_por_estado': db.session.query(
            DocumentoObra.estado, db.func.count(DocumentoObra.id)
        ).group_by(DocumentoObra.estado).all(),
        
        'actividad_mensual': generar_actividad_mensual()
    }

def generar_actividad_mensual():
    """Genera estadísticas de actividad por mes"""
    # Implementar lógica para obtener actividad mensual
    return []