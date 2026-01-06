"""
Administración de Precios de Equipos - Integración Leiten
Permite cargar, editar y gestionar precios de equipos de proveedores
"""

import os
import io
from datetime import datetime
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from functools import wraps

from extensions import db
from models.equipment import CategoriaEquipoProveedor, EquipoProveedor, HistorialPrecioEquipo

admin_equipos_bp = Blueprint('admin_equipos', __name__, url_prefix='/admin/equipos-proveedor')


def admin_required(f):
    """Decorador para requerir permisos de admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Debe iniciar sesión', 'warning')
            return redirect(url_for('index'))
        if not (current_user.is_super_admin or current_user.role in ('admin', 'pm')):
            flash('No tiene permisos para acceder a esta sección', 'danger')
            return redirect(url_for('reportes.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# VISTAS PRINCIPALES
# =============================================================================

@admin_equipos_bp.route('/')
@login_required
@admin_required
def lista():
    """Lista de equipos de proveedores"""
    # Filtros
    categoria_id = request.args.get('categoria', type=int)
    proveedor = request.args.get('proveedor', 'leiten')
    busqueda = request.args.get('q', '')
    solo_alquiler = request.args.get('alquiler') == '1'
    solo_venta = request.args.get('venta') == '1'

    # Query base
    query = EquipoProveedor.query.filter_by(activo=True, proveedor=proveedor)

    if categoria_id:
        query = query.filter_by(categoria_id=categoria_id)

    if busqueda:
        search = f"%{busqueda}%"
        query = query.filter(db.or_(
            EquipoProveedor.nombre.ilike(search),
            EquipoProveedor.marca.ilike(search),
            EquipoProveedor.modelo.ilike(search),
            EquipoProveedor.codigo.ilike(search)
        ))

    if solo_alquiler:
        query = query.filter(EquipoProveedor.precio_alquiler_usd.isnot(None))

    if solo_venta:
        query = query.filter(db.or_(
            EquipoProveedor.precio_venta_usd.isnot(None),
            EquipoProveedor.precio_venta_ars.isnot(None)
        ))

    # Paginación
    page = request.args.get('page', 1, type=int)
    per_page = 50
    equipos = query.order_by(EquipoProveedor.nombre).paginate(page=page, per_page=per_page)

    # Categorías para filtro
    categorias = CategoriaEquipoProveedor.query.filter_by(
        activo=True, proveedor=proveedor
    ).order_by(CategoriaEquipoProveedor.nombre).all()

    # Estadísticas
    stats = {
        'total': EquipoProveedor.query.filter_by(activo=True, proveedor=proveedor).count(),
        'con_alquiler': EquipoProveedor.query.filter_by(activo=True, proveedor=proveedor).filter(
            EquipoProveedor.precio_alquiler_usd.isnot(None)
        ).count(),
        'con_venta': EquipoProveedor.query.filter_by(activo=True, proveedor=proveedor).filter(
            db.or_(
                EquipoProveedor.precio_venta_usd.isnot(None),
                EquipoProveedor.precio_venta_ars.isnot(None)
            )
        ).count(),
        'categorias': len(categorias)
    }

    return render_template('admin/equipos_proveedor/lista.html',
                           equipos=equipos,
                           categorias=categorias,
                           stats=stats,
                           filtros={
                               'categoria_id': categoria_id,
                               'proveedor': proveedor,
                               'busqueda': busqueda,
                               'solo_alquiler': solo_alquiler,
                               'solo_venta': solo_venta
                           })


@admin_equipos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
@admin_required
def crear():
    """Crear nuevo equipo"""
    if request.method == 'POST':
        try:
            # Obtener o crear categoría
            categoria_nombre = request.form.get('categoria_nombre', '').strip()
            categoria_id = request.form.get('categoria_id', type=int)

            if categoria_nombre and not categoria_id:
                categoria = CategoriaEquipoProveedor.get_or_create(categoria_nombre)
                db.session.flush()
                categoria_id = categoria.id

            if not categoria_id:
                flash('Debe seleccionar o crear una categoría', 'danger')
                return redirect(request.url)

            equipo = EquipoProveedor(
                categoria_id=categoria_id,
                proveedor=request.form.get('proveedor', 'leiten'),
                codigo=request.form.get('codigo', '').strip() or None,
                nombre=request.form.get('nombre', '').strip(),
                marca=request.form.get('marca', '').strip() or None,
                modelo=request.form.get('modelo', '').strip() or None,
                potencia=request.form.get('potencia', '').strip() or None,
                capacidad=request.form.get('capacidad', '').strip() or None,
                peso=request.form.get('peso', '').strip() or None,
                motor=request.form.get('motor', '').strip() or None,
                precio_alquiler_usd=parse_decimal(request.form.get('precio_alquiler_usd')),
                periodo_alquiler_dias=request.form.get('periodo_alquiler_dias', 28, type=int),
                precio_venta_usd=parse_decimal(request.form.get('precio_venta_usd')),
                precio_venta_ars=parse_decimal(request.form.get('precio_venta_ars')),
                iva_porcentaje=parse_decimal(request.form.get('iva_porcentaje')) or Decimal('10.5'),
                disponible_alquiler=request.form.get('disponible_alquiler') == 'on',
                disponible_venta=request.form.get('disponible_venta') == 'on',
                url_producto=request.form.get('url_producto', '').strip() or None,
                imagen_url=request.form.get('imagen_url', '').strip() or None,
                etapa_construccion=request.form.get('etapa_construccion', '').strip() or None,
                notas=request.form.get('notas', '').strip() or None,
                fecha_actualizacion_precio=datetime.utcnow()
            )

            db.session.add(equipo)
            db.session.commit()

            flash(f'Equipo "{equipo.nombre}" creado correctamente', 'success')
            return redirect(url_for('admin_equipos.lista'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creando equipo: {e}")
            flash(f'Error al crear equipo: {str(e)}', 'danger')

    categorias = CategoriaEquipoProveedor.query.filter_by(activo=True).order_by(CategoriaEquipoProveedor.nombre).all()

    return render_template('admin/equipos_proveedor/form.html',
                           equipo=None,
                           categorias=categorias,
                           etapas=ETAPAS_CONSTRUCCION)


@admin_equipos_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Editar equipo existente"""
    equipo = EquipoProveedor.query.get_or_404(id)

    if request.method == 'POST':
        try:
            # Guardar precios anteriores para historial
            precios_anteriores = {
                'alquiler_usd': equipo.precio_alquiler_usd,
                'venta_usd': equipo.precio_venta_usd,
                'venta_ars': equipo.precio_venta_ars
            }

            # Actualizar campos
            equipo.categoria_id = request.form.get('categoria_id', type=int) or equipo.categoria_id
            equipo.codigo = request.form.get('codigo', '').strip() or None
            equipo.nombre = request.form.get('nombre', '').strip()
            equipo.marca = request.form.get('marca', '').strip() or None
            equipo.modelo = request.form.get('modelo', '').strip() or None
            equipo.potencia = request.form.get('potencia', '').strip() or None
            equipo.capacidad = request.form.get('capacidad', '').strip() or None
            equipo.peso = request.form.get('peso', '').strip() or None
            equipo.motor = request.form.get('motor', '').strip() or None

            nuevo_alquiler = parse_decimal(request.form.get('precio_alquiler_usd'))
            nuevo_venta_usd = parse_decimal(request.form.get('precio_venta_usd'))
            nuevo_venta_ars = parse_decimal(request.form.get('precio_venta_ars'))

            # Registrar cambios de precio
            if nuevo_alquiler != precios_anteriores['alquiler_usd']:
                registrar_cambio_precio(equipo.id, 'alquiler_usd',
                                        precios_anteriores['alquiler_usd'], nuevo_alquiler)
            if nuevo_venta_usd != precios_anteriores['venta_usd']:
                registrar_cambio_precio(equipo.id, 'venta_usd',
                                        precios_anteriores['venta_usd'], nuevo_venta_usd)
            if nuevo_venta_ars != precios_anteriores['venta_ars']:
                registrar_cambio_precio(equipo.id, 'venta_ars',
                                        precios_anteriores['venta_ars'], nuevo_venta_ars)

            equipo.precio_alquiler_usd = nuevo_alquiler
            equipo.precio_venta_usd = nuevo_venta_usd
            equipo.precio_venta_ars = nuevo_venta_ars
            equipo.periodo_alquiler_dias = request.form.get('periodo_alquiler_dias', 28, type=int)
            equipo.iva_porcentaje = parse_decimal(request.form.get('iva_porcentaje')) or Decimal('10.5')
            equipo.disponible_alquiler = request.form.get('disponible_alquiler') == 'on'
            equipo.disponible_venta = request.form.get('disponible_venta') == 'on'
            equipo.url_producto = request.form.get('url_producto', '').strip() or None
            equipo.imagen_url = request.form.get('imagen_url', '').strip() or None
            equipo.etapa_construccion = request.form.get('etapa_construccion', '').strip() or None
            equipo.notas = request.form.get('notas', '').strip() or None
            equipo.fecha_actualizacion_precio = datetime.utcnow()

            db.session.commit()

            flash(f'Equipo "{equipo.nombre}" actualizado correctamente', 'success')
            return redirect(url_for('admin_equipos.lista'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error actualizando equipo: {e}")
            flash(f'Error al actualizar equipo: {str(e)}', 'danger')

    categorias = CategoriaEquipoProveedor.query.filter_by(activo=True).order_by(CategoriaEquipoProveedor.nombre).all()

    return render_template('admin/equipos_proveedor/form.html',
                           equipo=equipo,
                           categorias=categorias,
                           etapas=ETAPAS_CONSTRUCCION)


@admin_equipos_bp.route('/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def eliminar(id):
    """Eliminar (desactivar) equipo"""
    equipo = EquipoProveedor.query.get_or_404(id)

    try:
        equipo.activo = False
        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" eliminado', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar: {str(e)}', 'danger')

    return redirect(url_for('admin_equipos.lista'))


# =============================================================================
# IMPORTACIÓN DESDE EXCEL
# =============================================================================

@admin_equipos_bp.route('/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def importar_excel():
    """Importar equipos desde Excel"""
    if request.method == 'POST':
        if 'archivo' not in request.files:
            flash('No se seleccionó archivo', 'danger')
            return redirect(request.url)

        archivo = request.files['archivo']
        if archivo.filename == '':
            flash('No se seleccionó archivo', 'danger')
            return redirect(request.url)

        if not archivo.filename.endswith(('.xlsx', '.xls')):
            flash('El archivo debe ser Excel (.xlsx o .xls)', 'danger')
            return redirect(request.url)

        try:
            import pandas as pd

            # Leer Excel
            df = pd.read_excel(archivo)

            # Normalizar nombres de columnas
            df.columns = [col.strip().lower().replace(' ', '_') for col in df.columns]

            # Mapeo de columnas esperadas
            columnas_map = {
                'categoria': ['categoria', 'categoría', 'category'],
                'nombre': ['nombre', 'name', 'descripcion', 'descripción', 'equipo'],
                'marca': ['marca', 'brand'],
                'modelo': ['modelo', 'model'],
                'codigo': ['codigo', 'código', 'code', 'sku'],
                'precio_alquiler_usd': ['precio_alquiler_usd', 'alquiler_usd', 'rent_usd', 'alquiler'],
                'precio_venta_usd': ['precio_venta_usd', 'venta_usd', 'sale_usd'],
                'precio_venta_ars': ['precio_venta_ars', 'venta_ars', 'precio_ars', 'venta'],
                'potencia': ['potencia', 'power', 'hp', 'kw'],
                'capacidad': ['capacidad', 'capacity'],
                'peso': ['peso', 'weight', 'kg'],
                'motor': ['motor', 'engine'],
                'etapa': ['etapa', 'etapa_construccion', 'stage']
            }

            def find_column(df, options):
                for opt in options:
                    if opt in df.columns:
                        return opt
                return None

            proveedor = request.form.get('proveedor', 'leiten')
            actualizar_existentes = request.form.get('actualizar_existentes') == 'on'

            creados = 0
            actualizados = 0
            errores = []

            for idx, row in df.iterrows():
                try:
                    # Obtener valores
                    categoria_nombre = str(row.get(find_column(df, columnas_map['categoria']), '')).strip()
                    nombre = str(row.get(find_column(df, columnas_map['nombre']), '')).strip()

                    if not nombre:
                        continue

                    # Obtener o crear categoría
                    if categoria_nombre:
                        categoria = CategoriaEquipoProveedor.get_or_create(categoria_nombre, proveedor)
                        db.session.flush()
                        categoria_id = categoria.id
                    else:
                        # Categoría por defecto
                        categoria = CategoriaEquipoProveedor.get_or_create('Sin Categoría', proveedor)
                        db.session.flush()
                        categoria_id = categoria.id

                    # Buscar si existe por código o nombre
                    codigo_col = find_column(df, columnas_map['codigo'])
                    codigo = str(row.get(codigo_col, '')).strip() if codigo_col else None

                    equipo_existente = None
                    if codigo:
                        equipo_existente = EquipoProveedor.query.filter_by(
                            codigo=codigo, proveedor=proveedor
                        ).first()

                    if not equipo_existente:
                        equipo_existente = EquipoProveedor.query.filter_by(
                            nombre=nombre, proveedor=proveedor
                        ).first()

                    if equipo_existente and actualizar_existentes:
                        # Actualizar existente
                        equipo = equipo_existente
                        actualizados += 1
                    elif equipo_existente:
                        # Saltar si existe y no actualizar
                        continue
                    else:
                        # Crear nuevo
                        equipo = EquipoProveedor(proveedor=proveedor)
                        creados += 1

                    # Asignar valores
                    equipo.categoria_id = categoria_id
                    equipo.nombre = nombre
                    equipo.codigo = codigo if codigo else None

                    marca_col = find_column(df, columnas_map['marca'])
                    if marca_col:
                        equipo.marca = str(row.get(marca_col, '')).strip() or None

                    modelo_col = find_column(df, columnas_map['modelo'])
                    if modelo_col:
                        equipo.modelo = str(row.get(modelo_col, '')).strip() or None

                    # Precios
                    alquiler_col = find_column(df, columnas_map['precio_alquiler_usd'])
                    if alquiler_col:
                        equipo.precio_alquiler_usd = parse_decimal(row.get(alquiler_col))

                    venta_usd_col = find_column(df, columnas_map['precio_venta_usd'])
                    if venta_usd_col:
                        equipo.precio_venta_usd = parse_decimal(row.get(venta_usd_col))

                    venta_ars_col = find_column(df, columnas_map['precio_venta_ars'])
                    if venta_ars_col:
                        equipo.precio_venta_ars = parse_decimal(row.get(venta_ars_col))

                    # Especificaciones
                    potencia_col = find_column(df, columnas_map['potencia'])
                    if potencia_col:
                        equipo.potencia = str(row.get(potencia_col, '')).strip() or None

                    capacidad_col = find_column(df, columnas_map['capacidad'])
                    if capacidad_col:
                        equipo.capacidad = str(row.get(capacidad_col, '')).strip() or None

                    peso_col = find_column(df, columnas_map['peso'])
                    if peso_col:
                        equipo.peso = str(row.get(peso_col, '')).strip() or None

                    motor_col = find_column(df, columnas_map['motor'])
                    if motor_col:
                        equipo.motor = str(row.get(motor_col, '')).strip() or None

                    etapa_col = find_column(df, columnas_map['etapa'])
                    if etapa_col:
                        equipo.etapa_construccion = str(row.get(etapa_col, '')).strip() or None

                    equipo.fecha_actualizacion_precio = datetime.utcnow()
                    equipo.activo = True

                    if not equipo_existente:
                        db.session.add(equipo)

                except Exception as row_error:
                    errores.append(f"Fila {idx + 2}: {str(row_error)}")

            db.session.commit()

            mensaje = f'Importación completada: {creados} creados, {actualizados} actualizados'
            if errores:
                mensaje += f', {len(errores)} errores'
                for error in errores[:5]:  # Mostrar máximo 5 errores
                    flash(error, 'warning')

            flash(mensaje, 'success')
            return redirect(url_for('admin_equipos.lista'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error importando Excel: {e}")
            flash(f'Error al importar: {str(e)}', 'danger')

    return render_template('admin/equipos_proveedor/importar.html')


@admin_equipos_bp.route('/plantilla-excel')
@login_required
@admin_required
def descargar_plantilla():
    """Descargar plantilla Excel para importación"""
    import pandas as pd
    from flask import send_file

    # Crear DataFrame con estructura esperada
    data = {
        'Categoria': ['Compactación', 'Hormigoneras', 'Vibrado'],
        'Nombre': ['Pisón Masalta EMR70H', 'Hormigonera 150L', 'Vibrador de Inmersión'],
        'Marca': ['Masalta', 'Leiten', 'Wacker'],
        'Modelo': ['EMR70H', 'HL-150', 'M2000'],
        'Codigo': ['COMP-001', 'HORM-001', 'VIB-001'],
        'Precio_Alquiler_USD': [1507.00, 890.00, 450.00],
        'Precio_Venta_USD': [None, None, 2500.00],
        'Precio_Venta_ARS': [2222825.00, 1500000.00, None],
        'Potencia': ['5.5 hp', '1 hp', '2 hp'],
        'Capacidad': ['', '150 litros', ''],
        'Peso': ['70 kg', '85 kg', '15 kg'],
        'Motor': ['Honda GX160 Nafta', 'Eléctrico', 'Eléctrico'],
        'Etapa': ['excavacion', 'estructura', 'estructura']
    }

    df = pd.DataFrame(data)

    # Guardar en buffer
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Equipos')

    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='plantilla_equipos_leiten.xlsx'
    )


# =============================================================================
# API ENDPOINTS
# =============================================================================

@admin_equipos_bp.route('/api/buscar')
@login_required
def api_buscar():
    """API para buscar equipos"""
    query = request.args.get('q', '')
    categoria_id = request.args.get('categoria', type=int)
    proveedor = request.args.get('proveedor', 'leiten')
    solo_alquiler = request.args.get('alquiler') == '1'
    solo_venta = request.args.get('venta') == '1'
    limit = request.args.get('limit', 50, type=int)

    equipos = EquipoProveedor.buscar(
        query=query,
        categoria_id=categoria_id,
        proveedor=proveedor,
        solo_alquiler=solo_alquiler,
        solo_venta=solo_venta
    )[:limit]

    return jsonify({
        'ok': True,
        'equipos': [e.to_dict() for e in equipos],
        'total': len(equipos)
    })


@admin_equipos_bp.route('/api/categorias')
@login_required
def api_categorias():
    """API para obtener categorías"""
    proveedor = request.args.get('proveedor', 'leiten')

    categorias = CategoriaEquipoProveedor.query.filter_by(
        activo=True, proveedor=proveedor
    ).order_by(CategoriaEquipoProveedor.nombre).all()

    return jsonify({
        'ok': True,
        'categorias': [{
            'id': c.id,
            'nombre': c.nombre,
            'slug': c.slug,
            'equipos_count': c.equipos.filter_by(activo=True).count()
        } for c in categorias]
    })


@admin_equipos_bp.route('/api/equipo/<int:id>')
@login_required
def api_equipo(id):
    """API para obtener detalle de un equipo"""
    equipo = EquipoProveedor.query.get_or_404(id)
    return jsonify({
        'ok': True,
        'equipo': equipo.to_dict()
    })


@admin_equipos_bp.route('/api/estadisticas')
@login_required
def api_estadisticas():
    """API para obtener estadísticas"""
    proveedor = request.args.get('proveedor', 'leiten')

    stats = {
        'total_equipos': EquipoProveedor.query.filter_by(activo=True, proveedor=proveedor).count(),
        'con_precio_alquiler': EquipoProveedor.query.filter_by(activo=True, proveedor=proveedor).filter(
            EquipoProveedor.precio_alquiler_usd.isnot(None)
        ).count(),
        'con_precio_venta': EquipoProveedor.query.filter_by(activo=True, proveedor=proveedor).filter(
            db.or_(
                EquipoProveedor.precio_venta_usd.isnot(None),
                EquipoProveedor.precio_venta_ars.isnot(None)
            )
        ).count(),
        'categorias': CategoriaEquipoProveedor.query.filter_by(activo=True, proveedor=proveedor).count(),
        'por_etapa': {}
    }

    # Contar por etapa
    for etapa in ETAPAS_CONSTRUCCION:
        count = EquipoProveedor.query.filter_by(
            activo=True, proveedor=proveedor, etapa_construccion=etapa['slug']
        ).count()
        if count > 0:
            stats['por_etapa'][etapa['nombre']] = count

    return jsonify({'ok': True, 'stats': stats})


# =============================================================================
# CATEGORÍAS
# =============================================================================

@admin_equipos_bp.route('/categorias')
@login_required
@admin_required
def lista_categorias():
    """Lista de categorías"""
    proveedor = request.args.get('proveedor', 'leiten')

    categorias = CategoriaEquipoProveedor.query.filter_by(
        proveedor=proveedor
    ).order_by(CategoriaEquipoProveedor.nombre).all()

    return render_template('admin/equipos_proveedor/categorias.html',
                           categorias=categorias,
                           proveedor=proveedor)


@admin_equipos_bp.route('/categorias/crear', methods=['POST'])
@login_required
@admin_required
def crear_categoria():
    """Crear nueva categoría"""
    try:
        nombre = request.form.get('nombre', '').strip()
        proveedor = request.form.get('proveedor', 'leiten')

        if not nombre:
            flash('El nombre es requerido', 'danger')
            return redirect(url_for('admin_equipos.lista_categorias'))

        categoria = CategoriaEquipoProveedor.get_or_create(nombre, proveedor)
        categoria.descripcion = request.form.get('descripcion', '').strip() or None
        db.session.commit()

        flash(f'Categoría "{nombre}" creada', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('admin_equipos.lista_categorias'))


# =============================================================================
# UTILIDADES
# =============================================================================

def parse_decimal(value):
    """Convierte valor a Decimal de forma segura"""
    if value is None or value == '' or (isinstance(value, float) and pd.isna(value) if 'pd' in dir() else False):
        return None
    try:
        # Limpiar formato
        if isinstance(value, str):
            value = value.replace('$', '').replace(',', '').replace(' ', '').strip()
        return Decimal(str(value))
    except:
        return None


def registrar_cambio_precio(equipo_id, tipo_precio, precio_anterior, precio_nuevo):
    """Registra cambio de precio en historial"""
    if precio_anterior == precio_nuevo:
        return

    historial = HistorialPrecioEquipo(
        equipo_id=equipo_id,
        tipo_precio=tipo_precio,
        precio_anterior=precio_anterior,
        precio_nuevo=precio_nuevo,
        usuario_id=current_user.id if current_user.is_authenticated else None
    )
    db.session.add(historial)


# Etapas de construcción para el selector
ETAPAS_CONSTRUCCION = [
    {'slug': 'excavacion', 'nombre': 'Excavación y Movimiento de Suelos'},
    {'slug': 'fundaciones', 'nombre': 'Fundaciones'},
    {'slug': 'estructura', 'nombre': 'Estructura'},
    {'slug': 'mamposteria', 'nombre': 'Mampostería'},
    {'slug': 'techos', 'nombre': 'Techos e Impermeabilización'},
    {'slug': 'instalaciones-electricas', 'nombre': 'Instalaciones Eléctricas'},
    {'slug': 'instalaciones-sanitarias', 'nombre': 'Instalaciones Sanitarias'},
    {'slug': 'instalaciones-gas', 'nombre': 'Instalaciones de Gas'},
    {'slug': 'revoque-grueso', 'nombre': 'Revoque Grueso'},
    {'slug': 'revoque-fino', 'nombre': 'Revoque Fino'},
    {'slug': 'pisos', 'nombre': 'Pisos y Revestimientos'},
    {'slug': 'carpinteria', 'nombre': 'Carpintería y Aberturas'},
    {'slug': 'pintura', 'nombre': 'Pintura'},
    {'slug': 'herreria', 'nombre': 'Herrería de Obra'},
    {'slug': 'seguridad', 'nombre': 'Seguridad'},
    {'slug': 'instalaciones-complementarias', 'nombre': 'Instalaciones Complementarias'},
    {'slug': 'limpieza', 'nombre': 'Limpieza Final'},
]


# Importar pandas solo si está disponible
try:
    import pandas as pd
except ImportError:
    pd = None
