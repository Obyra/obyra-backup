from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from decimal import Decimal
from app import db
from models import Proveedor, CategoriaProveedor, SolicitudCotizacion, Usuario

marketplaces_bp = Blueprint('marketplaces', __name__)

# Categorías predefinidas para proveedores
CATEGORIAS_PROVEEDOR = {
    'materiales': {
        'nombre': 'Materiales de Construcción',
        'subcategorias': [
            'Cemento y Hormigón',
            'Ladrillos y Bloques',
            'Hierro y Acero',
            'Madera y Derivados',
            'Sanitarios y Grifería',
            'Pisos y Revestimientos',
            'Pintura y Impermeabilizantes',
            'Aislantes Térmicos',
            'Vidrios y Cristales'
        ]
    },
    'equipos': {
        'nombre': 'Equipos y Maquinaria',
        'subcategorias': [
            'Excavadoras y Retroexcavadoras',
            'Grúas y Montacargas',
            'Compactadores',
            'Mezcladoras de Concreto',
            'Herramientas Eléctricas',
            'Andamios y Estructuras',
            'Generadores Eléctricos',
            'Equipos de Soldadura'
        ]
    },
    'servicios': {
        'nombre': 'Servicios Especializados',
        'subcategorias': [
            'Movimiento de Suelos',
            'Instalaciones Eléctricas',
            'Instalaciones Sanitarias',
            'Climatización',
            'Seguridad e Higiene',
            'Transporte de Materiales',
            'Consultoría Técnica',
            'Certificaciones'
        ]
    },
    'profesionales': {
        'nombre': 'Profesionales',
        'subcategorias': [
            'Arquitectos',
            'Ingenieros Civiles',
            'Maestros Mayor de Obra',
            'Electricistas',
            'Plomeros',
            'Albañiles Especializados',
            'Pintores',
            'Carpinteros'
        ]
    }
}

@marketplaces_bp.route('/')
@login_required
def index():
    """Dashboard principal de Marketplaces"""
    if not current_user.puede_acceder_modulo('marketplaces'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    # Obtener filtros
    categoria = request.args.get('categoria', '')
    ubicacion = request.args.get('ubicacion', '')
    buscar = request.args.get('buscar', '')
    
    # Query base
    query = Proveedor.query.filter_by(organizacion_id=current_user.organizacion_id, activo=True)
    
    if categoria:
        query = query.filter(Proveedor.categoria == categoria)
    
    if ubicacion:
        query = query.filter(Proveedor.ubicacion.contains(ubicacion))
    
    if buscar:
        query = query.filter(
            db.or_(
                Proveedor.nombre.contains(buscar),
                Proveedor.descripcion.contains(buscar),
                Proveedor.especialidad.contains(buscar)
            )
        )
    
    proveedores = query.order_by(Proveedor.calificacion.desc()).limit(20).all()
    
    # Estadísticas
    total_proveedores = Proveedor.query.filter_by(organizacion_id=current_user.organizacion_id, activo=True).count()
    cotizaciones_pendientes = SolicitudCotizacion.query.filter_by(
        solicitante_id=current_user.id, 
        estado='pendiente'
    ).count()
    
    return render_template('marketplaces/index.html', 
                         proveedores=proveedores,
                         categorias=CATEGORIAS_PROVEEDOR,
                         total_proveedores=total_proveedores,
                         cotizaciones_pendientes=cotizaciones_pendientes,
                         categoria=categoria,
                         ubicacion=ubicacion,
                         buscar=buscar)

@marketplaces_bp.route('/buscar')
@login_required
def buscar():
    """Búsqueda avanzada de proveedores"""
    if not current_user.puede_acceder_modulo('marketplaces'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    return render_template('marketplaces/buscar.html', categorias=CATEGORIAS_PROVEEDOR)

@marketplaces_bp.route('/api/buscar')
@login_required
def api_buscar():
    """API para búsqueda de proveedores"""
    try:
        # Parámetros de búsqueda
        termino = request.args.get('q', '').strip()
        categoria = request.args.get('categoria', '')
        ubicacion = request.args.get('ubicacion', '')
        calificacion_min = request.args.get('calificacion', 0, type=float)
        
        # Query base
        query = Proveedor.query.filter_by(organizacion_id=current_user.organizacion_id, activo=True)
        
        # Filtros
        if termino:
            query = query.filter(
                db.or_(
                    Proveedor.nombre.contains(termino),
                    Proveedor.descripcion.contains(termino),
                    Proveedor.especialidad.contains(termino)
                )
            )
        
        if categoria:
            query = query.filter(Proveedor.categoria == categoria)
        
        if ubicacion:
            query = query.filter(Proveedor.ubicacion.contains(ubicacion))
        
        if calificacion_min > 0:
            query = query.filter(Proveedor.calificacion >= calificacion_min)
        
        # Ordenar por calificación
        proveedores = query.order_by(Proveedor.calificacion.desc()).limit(50).all()
        
        # Formatear resultados
        resultados = []
        for proveedor in proveedores:
            resultados.append({
                'id': proveedor.id,
                'nombre': proveedor.nombre,
                'descripcion': proveedor.descripcion,
                'categoria': proveedor.categoria,
                'especialidad': proveedor.especialidad,
                'ubicacion': proveedor.ubicacion,
                'calificacion': float(proveedor.calificacion),
                'telefono': proveedor.telefono,
                'email': proveedor.email,
                'precio_promedio': float(proveedor.precio_promedio) if proveedor.precio_promedio else None,
                'trabajos_completados': proveedor.trabajos_completados,
                'verificado': proveedor.verificado
            })
        
        return jsonify({
            'success': True,
            'proveedores': resultados,
            'total': len(resultados)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@marketplaces_bp.route('/proveedor/<int:proveedor_id>')
@login_required
def detalle_proveedor(proveedor_id):
    """Detalle completo de un proveedor"""
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    
    if proveedor.organizacion_id != current_user.organizacion_id:
        flash('Proveedor no encontrado.', 'danger')
        return redirect(url_for('marketplaces.index'))
    
    return render_template('marketplaces/detalle_proveedor.html', proveedor=proveedor)

@marketplaces_bp.route('/solicitar_cotizacion/<int:proveedor_id>', methods=['POST'])
@login_required
def solicitar_cotizacion(proveedor_id):
    """Solicitar cotización a un proveedor"""
    try:
        proveedor = Proveedor.query.get_or_404(proveedor_id)
        
        if proveedor.organizacion_id != current_user.organizacion_id:
            return jsonify({'success': False, 'error': 'Proveedor no encontrado'}), 404
        
        descripcion = request.form.get('descripcion', '').strip()
        if not descripcion:
            return jsonify({'success': False, 'error': 'La descripción es obligatoria'}), 400
        
        # Crear solicitud de cotización
        solicitud = SolicitudCotizacion(
            proveedor_id=proveedor_id,
            solicitante_id=current_user.id,
            descripcion=descripcion,
            estado='pendiente',
            fecha_solicitud=datetime.utcnow()
        )
        
        db.session.add(solicitud)
        db.session.commit()
        
        flash(f'Solicitud de cotización enviada a {proveedor.nombre}', 'success')
        return jsonify({'success': True, 'message': 'Cotización solicitada exitosamente'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@marketplaces_bp.route('/mis_cotizaciones')
@login_required
def mis_cotizaciones():
    """Ver mis solicitudes de cotización"""
    if not current_user.puede_acceder_modulo('marketplaces'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    estado = request.args.get('estado', '')
    
    query = SolicitudCotizacion.query.filter_by(solicitante_id=current_user.id)
    
    if estado:
        query = query.filter(SolicitudCotizacion.estado == estado)
    
    cotizaciones = query.order_by(SolicitudCotizacion.fecha_solicitud.desc()).all()
    
    return render_template('marketplaces/mis_cotizaciones.html', cotizaciones=cotizaciones, estado=estado)

@marketplaces_bp.route('/admin/proveedores')
@login_required
def admin_proveedores():
    """Administrar proveedores (solo para admins)"""
    if not current_user.es_admin():
        flash('No tienes permisos para acceder a esta sección.', 'danger')
        return redirect(url_for('marketplaces.index'))
    
    proveedores = Proveedor.query.filter_by(organizacion_id=current_user.organizacion_id).order_by(Proveedor.nombre).all()
    
    return render_template('marketplaces/admin_proveedores.html', 
                         proveedores=proveedores,
                         categorias=CATEGORIAS_PROVEEDOR)

@marketplaces_bp.route('/admin/proveedores/crear', methods=['GET', 'POST'])
@login_required
def crear_proveedor():
    """Crear nuevo proveedor (solo para admins)"""
    if not current_user.es_admin():
        flash('No tienes permisos para realizar esta acción.', 'danger')
        return redirect(url_for('marketplaces.index'))
    
    if request.method == 'POST':
        try:
            proveedor = Proveedor(
                organizacion_id=current_user.organizacion_id,
                nombre=request.form['nombre'].strip(),
                descripcion=request.form.get('descripcion', '').strip(),
                categoria=request.form['categoria'],
                especialidad=request.form.get('especialidad', '').strip(),
                ubicacion=request.form.get('ubicacion', '').strip(),
                telefono=request.form.get('telefono', '').strip(),
                email=request.form.get('email', '').strip(),
                precio_promedio=Decimal(request.form.get('precio_promedio', 0) or 0),
                calificacion=Decimal(request.form.get('calificacion', 5.0) or 5.0),
                verificado=request.form.get('verificado') == 'on',
                activo=True,
                fecha_registro=datetime.utcnow()
            )
            
            db.session.add(proveedor)
            db.session.commit()
            
            flash(f'Proveedor {proveedor.nombre} creado exitosamente.', 'success')
            return redirect(url_for('marketplaces.admin_proveedores'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear proveedor: {str(e)}', 'danger')
    
    return render_template('marketplaces/crear_proveedor.html', categorias=CATEGORIAS_PROVEEDOR)