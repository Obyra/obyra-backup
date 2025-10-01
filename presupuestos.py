from flask import Blueprint, render_template, request, flash, redirect, url_for, make_response, jsonify
from flask_login import login_required, current_user
from datetime import date, datetime
from io import BytesIO
import importlib.util
import json
from typing import Any

REPORTLAB_AVAILABLE = importlib.util.find_spec("reportlab") is not None
if REPORTLAB_AVAILABLE:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
else:  # pragma: no cover - executed only when optional deps missing
    letter = A4 = None  # type: ignore[assignment]
    colors = None  # type: ignore[assignment]
    inch = 72  # type: ignore[assignment]

    def _missing_reportlab(*args: Any, **kwargs: Any):
        raise RuntimeError(
            "La librería reportlab no está instalada. Ejecuta 'pip install reportlab' para habilitar la generación de PDFs."
        )

    SimpleDocTemplate = Table = TableStyle = Paragraph = Spacer = _missing_reportlab  # type: ignore[assignment]
    getSampleStyleSheet = ParagraphStyle = _missing_reportlab  # type: ignore[assignment]
    TA_CENTER = TA_RIGHT = None  # type: ignore[assignment]


XLSXWRITER_AVAILABLE = importlib.util.find_spec("xlsxwriter") is not None
if XLSXWRITER_AVAILABLE:
    import xlsxwriter
else:  # pragma: no cover - executed only when optional deps missing
    xlsxwriter = None  # type: ignore[assignment]

from app import db
from models import Presupuesto, ItemPresupuesto, Obra, EtapaObra
from calculadora_ia import procesar_presupuesto_ia, COEFICIENTES_CONSTRUCCION

presupuestos_bp = Blueprint('presupuestos', __name__)

@presupuestos_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    estado = request.args.get('estado', '')
    buscar = request.args.get('buscar', '')
    
    # Modificar query para incluir presupuestos sin obra (LEFT JOIN) y excluir convertidos
    query = Presupuesto.query.outerjoin(Obra).filter(
        Presupuesto.organizacion_id == current_user.organizacion_id,
        Presupuesto.estado != 'convertido'  # Excluir presupuestos ya convertidos en obras
    )
    
    if estado:
        query = query.filter(Presupuesto.estado == estado)
    
    if buscar:
        query = query.filter(
            db.or_(
                Presupuesto.numero.contains(buscar),
                Presupuesto.observaciones.contains(buscar),
                Obra.nombre.contains(buscar) if Obra.nombre else False,
                Obra.cliente.contains(buscar) if Obra.cliente else False
            )
        )
    
    presupuestos = query.order_by(Presupuesto.fecha_creacion.desc()).all()
    
    return render_template('presupuestos/lista.html', 
                         presupuestos=presupuestos, 
                         estado=estado, 
                         buscar=buscar)


@presupuestos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para crear presupuestos.', 'danger')
        return redirect(url_for('presupuestos.lista'))
    
    if request.method == 'POST':
        # Obtener datos del nuevo formulario
        nombre_obra = request.form.get('nombre_obra')
        tipo_obra = request.form.get('tipo_obra')
        ubicacion = request.form.get('ubicacion')
        tipo_construccion = request.form.get('tipo_construccion')
        superficie_m2 = request.form.get('superficie_m2')
        fecha_inicio = request.form.get('fecha_inicio')
        fecha_fin = request.form.get('fecha_fin')
        presupuesto_disponible = request.form.get('presupuesto_disponible')
        moneda = request.form.get('moneda', 'ARS')
        cliente_nombre = request.form.get('cliente_nombre')
        plano_pdf = request.files.get('plano_pdf')
        
        # Validaciones
        if not all([nombre_obra, tipo_obra, ubicacion, tipo_construccion, superficie_m2]):
            flash('Completa todos los campos obligatorios.', 'danger')
            return render_template('presupuestos/crear.html')
        
        try:
            superficie_float = float(superficie_m2)
            if superficie_float <= 0:
                flash('La superficie debe ser mayor a 0.', 'danger')
                return render_template('presupuestos/crear.html')
        except ValueError:
            flash('La superficie debe ser un número válido.', 'danger')
            return render_template('presupuestos/crear.html')
        
        # Crear nueva obra basada en los datos del formulario
        nueva_obra = Obra()
        nueva_obra.nombre = nombre_obra
        nueva_obra.descripcion = f"Obra {tipo_obra.replace('_', ' ').title()} - {tipo_construccion.title()}"
        nueva_obra.direccion = ubicacion
        nueva_obra.cliente = cliente_nombre or "Cliente Sin Especificar"
        nueva_obra.estado = 'planificacion'
        nueva_obra.organizacion_id = current_user.organizacion_id
        
        # Procesar fechas
        if fecha_inicio:
            from datetime import datetime
            nueva_obra.fecha_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
        if fecha_fin:
            nueva_obra.fecha_fin_estimada = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
        
        # Procesar presupuesto disponible
        if presupuesto_disponible:
            try:
                presupuesto_float = float(presupuesto_disponible)
                nueva_obra.presupuesto_total = presupuesto_float
            except ValueError:
                pass
        
        try:
            db.session.add(nueva_obra)
            db.session.flush()  # Para obtener el ID de la obra
            
            # Generar número de presupuesto único
            ultimo_numero = db.session.query(db.func.max(Presupuesto.numero)).scalar()
            if ultimo_numero and ultimo_numero.startswith('PRES-'):
                try:
                    siguiente_num = int(ultimo_numero.split('-')[1]) + 1
                except:
                    siguiente_num = 1
            else:
                siguiente_num = 1
            
            # Asegurar que el número sea único
            while True:
                numero = f"PRES-{siguiente_num:04d}"
                existe = Presupuesto.query.filter_by(numero=numero).first()
                if not existe:
                    break
                siguiente_num += 1
            
            # Crear presupuesto asociado
            nuevo_presupuesto = Presupuesto()
            nuevo_presupuesto.obra_id = nueva_obra.id
            nuevo_presupuesto.numero = numero
            nuevo_presupuesto.iva_porcentaje = 21.0  # Fijo según lo solicitado
            nuevo_presupuesto.organizacion_id = current_user.organizacion_id
            
            # Agregar observaciones con detalles del proyecto
            observaciones_proyecto = []
            observaciones_proyecto.append(f"Tipo de obra: {tipo_obra.replace('_', ' ').title()}")
            observaciones_proyecto.append(f"Tipo de construcción: {tipo_construccion.title()}")
            observaciones_proyecto.append(f"Superficie: {superficie_float} m²")
            if presupuesto_disponible:
                observaciones_proyecto.append(f"Presupuesto disponible: {moneda} {presupuesto_disponible}")
            if plano_pdf and plano_pdf.filename:
                observaciones_proyecto.append(f"Plano PDF: {plano_pdf.filename}")
            
            nuevo_presupuesto.observaciones = " | ".join(observaciones_proyecto)
            
            db.session.add(nuevo_presupuesto)
            db.session.flush()  # Para obtener el ID del presupuesto
            
            # Procesar etapas si se enviaron
            etapas_count = 0
            etapa_index = 0
            while True:
                etapa_nombre = request.form.get(f'etapas[{etapa_index}][nombre]')
                if not etapa_nombre:
                    break
                
                etapa_descripcion = request.form.get(f'etapas[{etapa_index}][descripcion]', '')
                etapa_orden = request.form.get(f'etapas[{etapa_index}][orden]', etapa_index + 1)
                
                try:
                    orden_int = int(etapa_orden)
                except ValueError:
                    orden_int = etapa_index + 1
                
                # Crear etapa para la obra
                nueva_etapa = EtapaObra(
                    obra_id=nueva_obra.id,
                    nombre=etapa_nombre,
                    descripcion=etapa_descripcion,
                    orden=orden_int,
                    estado='pendiente',
                    organizacion_id=current_user.organizacion_id
                )
                
                db.session.add(nueva_etapa)
                etapas_count += 1
                etapa_index += 1
            
            db.session.commit()
            
            mensaje_exito = f'Obra "{nombre_obra}" y presupuesto {numero} creados exitosamente.'
            if etapas_count > 0:
                mensaje_exito += f' Se agregaron {etapas_count} etapas al proyecto.'
            
            flash(mensaje_exito, 'success')
            return redirect(url_for('presupuestos.detalle', id=nuevo_presupuesto.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear la obra y presupuesto: {str(e)}', 'danger')
    
    return render_template('presupuestos/crear.html')

@presupuestos_bp.route('/calculadora-ia')
@login_required
def calculadora_ia():
    """Nueva calculadora IA de presupuestos basada en planos"""
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para acceder a la calculadora IA.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    obras = Obra.query.filter(Obra.estado.in_(['planificacion', 'en_curso'])).order_by(Obra.nombre).all()
    tipos_construccion = list(COEFICIENTES_CONSTRUCCION.keys())
    
    return render_template('presupuestos/calculadora_ia.html', 
                         obras=obras, 
                         tipos_construccion=tipos_construccion)

@presupuestos_bp.route('/procesar-calculadora-ia', methods=['POST'])
@login_required
def procesar_calculadora_ia():
    """Procesa el análisis IA del plano y calcula materiales - Estilo Togal.AI"""
    if not current_user.puede_acceder_modulo('presupuestos'):
        return jsonify({'error': 'Sin permisos'}), 403
    
    try:
        # Obtener datos del formulario
        metros_cuadrados = request.form.get('metros_cuadrados')
        tipo_construccion = request.form.get('tipo_construccion', '').strip()
        archivo_pdf = request.files.get('archivo_pdf')
        
        # Validación: debe tener superficie
        if not metros_cuadrados:
            return jsonify({'error': 'Ingresa los metros cuadrados del proyecto'}), 400
        
        try:
            superficie_m2 = float(metros_cuadrados)
            if superficie_m2 <= 0:
                return jsonify({'error': 'Los metros cuadrados deben ser mayor a 0'}), 400
        except ValueError:
            return jsonify({'error': 'Metros cuadrados inválidos'}), 400
        
        # Si no hay tipo, usar IA para sugerir o usar Estándar
        if not tipo_construccion:
            # IA sugiere tipo basado en superficie
            if superficie_m2 < 80:
                tipo_final = "Económica"
            elif superficie_m2 > 300:
                tipo_final = "Premium"
            else:
                tipo_final = "Estándar"
        else:
            tipo_final = tipo_construccion
        
        # Validar tipo
        if tipo_final not in COEFICIENTES_CONSTRUCCION:
            tipo_final = "Estándar"
        
        # USAR FUNCIÓN COMPLETA CON ETAPAS
        resultado = procesar_presupuesto_ia(
            archivo_pdf=archivo_pdf,
            metros_cuadrados_manual=metros_cuadrados,
            tipo_construccion_forzado=tipo_final
        )
        
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({'error': f'Error procesando calculadora: {str(e)}'}), 500

@presupuestos_bp.route('/crear-desde-ia', methods=['POST'])
@login_required  
def crear_desde_ia():
    """Crea un presupuesto a partir de los resultados de la calculadora IA"""
    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'error': 'No tienes permisos para crear presupuestos'}), 403
    
    try:
        # Obtener datos del JSON enviado
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No se recibieron datos'}), 400
        
        presupuesto_ia = data.get('presupuesto')
        observaciones = data.get('observaciones', '')
        datos_proyecto = data.get('datos_proyecto', {})
        
        if not presupuesto_ia:
            return jsonify({'error': 'Datos del presupuesto incompletos'}), 400
        
        # NO CREAR OBRA AUTOMÁTICAMENTE - Solo guardar datos del proyecto
        # Los presupuestos quedan como "borrador" hasta que se confirmen explícitamente
        
        # Generar número de presupuesto único
        ultimo_numero = db.session.query(db.func.max(Presupuesto.numero)).scalar()
        if ultimo_numero and ultimo_numero.startswith('PRES-'):
            try:
                siguiente_num = int(ultimo_numero.split('-')[1]) + 1
            except:
                siguiente_num = 1
        else:
            siguiente_num = 1
        
        # Asegurar que el número sea único
        while True:
            numero = f"PRES-{siguiente_num:04d}"
            existe = Presupuesto.query.filter_by(numero=numero).first()
            if not existe:
                break
            siguiente_num += 1
        
        # Crear presupuesto base (SIN obra_id)
        nuevo_presupuesto = Presupuesto()
        nuevo_presupuesto.obra_id = None  # Sin obra asociada hasta confirmar
        nuevo_presupuesto.numero = numero
        nuevo_presupuesto.observaciones = f"Calculado con IA - {observaciones}"
        nuevo_presupuesto.iva_porcentaje = 21.0
        nuevo_presupuesto.estado = 'borrador'  # Borrador hasta que se confirme
        nuevo_presupuesto.confirmado_como_obra = False
        nuevo_presupuesto.datos_proyecto = json.dumps(datos_proyecto)  # Guardar datos para posterior conversión
        nuevo_presupuesto.organizacion_id = current_user.organizacion_id
        
        db.session.add(nuevo_presupuesto)
        db.session.flush()  # Para obtener el ID
        
        # Agregar items de materiales
        materiales = presupuesto_ia.get('materiales', {})
        for material, cantidad in materiales.items():
            if cantidad > 0:
                # Mapear nombres técnicos a descripciones legibles expandidas
                descripciones = {
                    # Materiales estructurales
                    'ladrillos': 'Ladrillos comunes',
                    'cemento': 'Bolsas de cemento',
                    'cal': 'Cal hidratada',
                    'arena': 'Arena gruesa',
                    'piedra': 'Piedra partida',
                    'hierro_8': 'Hierro 8mm',
                    'hierro_10': 'Hierro 10mm', 
                    'hierro_12': 'Hierro 12mm',
                    
                    # Revestimientos y pisos
                    'ceramicos': 'Cerámicos esmaltados',
                    'porcelanato': 'Porcelanato rectificado',
                    'azulejos': 'Azulejos para baños',
                    
                    # Instalaciones
                    'cables_electricos': 'Cables eléctricos',
                    'caños_agua': 'Caños para agua',
                    'caños_cloacas': 'Caños cloacales',
                    
                    # Techado
                    'chapas': 'Chapas acanaladas',
                    'tejas': 'Tejas cerámicas',
                    'aislacion_termica': 'Aislación térmica',
                    
                    # Terminaciones
                    'yeso': 'Yeso para terminaciones',
                    'madera_estructural': 'Madera estructural',
                    'vidrios': 'Vidrios templados',
                    'aberturas_metal': 'Aberturas metálicas',
                    
                    # Impermeabilización
                    'membrana': 'Membrana asfáltica',
                    'pintura': 'Pintura látex interior',
                    'pintura_exterior': 'Pintura exterior',
                    'sellador': 'Sellador acrílico'
                }
                
                unidades = {
                    # Estructurales
                    'ladrillos': 'unidades',
                    'cemento': 'bolsas',
                    'cal': 'kg',
                    'arena': 'm³',
                    'piedra': 'm³',
                    'hierro_8': 'kg',
                    'hierro_10': 'kg',
                    'hierro_12': 'kg',
                    
                    # Revestimientos
                    'ceramicos': 'm²',
                    'porcelanato': 'm²',
                    'azulejos': 'm²',
                    
                    # Instalaciones
                    'cables_electricos': 'metros',
                    'caños_agua': 'metros',
                    'caños_cloacas': 'metros',
                    
                    # Techado
                    'chapas': 'm²',
                    'tejas': 'm²',
                    'aislacion_termica': 'm²',
                    
                    # Terminaciones
                    'yeso': 'kg',
                    'madera_estructural': 'm³',
                    'vidrios': 'm²',
                    'aberturas_metal': 'm²',
                    
                    # Impermeabilización
                    'membrana': 'm²',
                    'pintura': 'litros',
                    'pintura_exterior': 'litros',
                    'sellador': 'litros'
                }
                
                item = ItemPresupuesto()
                item.presupuesto_id = nuevo_presupuesto.id
                item.tipo = 'material'
                item.descripcion = descripciones.get(material, material.title())
                item.unidad = unidades.get(material, 'unidades')
                item.cantidad = cantidad
                item.precio_unitario = 0.0  # Se puede actualizar manualmente después
                item.total = 0.0
                db.session.add(item)
        
        # Agregar equipos
        equipos = presupuesto_ia.get('equipos', {})
        for equipo, specs in equipos.items():
            # Manejar tanto diccionarios como valores simples
            if isinstance(specs, dict):
                cantidad = specs.get('cantidad', 0)
                dias_uso = specs.get('dias_uso', 0)
            else:
                # Fallback si no es un diccionario
                cantidad = 1
                dias_uso = 0
                
            if cantidad > 0:
                descripciones_equipos = {
                    'hormigonera': 'Alquiler Hormigonera',
                    'andamios': 'Alquiler Andamios',  
                    'carretilla': 'Carretilla',
                    'nivel_laser': 'Alquiler Nivel Láser',
                    'martillo_demoledor': 'Alquiler Martillo Demoledor',
                    'soldadora': 'Alquiler Soldadora',
                    'compresora': 'Alquiler Compresora',
                    'generador': 'Alquiler Generador',
                    'elevador': 'Alquiler Elevador',
                    'mezcladora': 'Alquiler Mezcladora'
                }
                
                item = ItemPresupuesto()
                item.presupuesto_id = nuevo_presupuesto.id
                item.tipo = 'equipo'
                
                # Descripción con días de uso si aplica
                base_desc = descripciones_equipos.get(equipo, equipo.replace('_', ' ').title())
                if dias_uso > 0:
                    item.descripcion = f"{base_desc} - {dias_uso} días"
                else:
                    item.descripcion = base_desc
                    
                item.unidad = 'días' if equipo in ['hormigonera', 'andamios', 'nivel_laser'] else 'unidades'
                item.cantidad = float(cantidad)
                item.precio_unitario = 0.0
                item.total = 0.0
                db.session.add(item)
        
        # Agregar herramientas
        herramientas = presupuesto_ia.get('herramientas', {})
        for herramienta, cantidad in herramientas.items():
            try:
                cantidad_float = float(cantidad) if cantidad else 0.0
                if cantidad_float > 0:
                    descripciones_herramientas = {
                        'palas': 'Palas',
                        'baldes': 'Baldes',
                        'fratacho': 'Fratacho',
                        'regla': 'Regla de albañil',
                        'llanas': 'Llanas',
                        'martillos': 'Martillos',
                        'serruchos': 'Serruchos',
                        'taladros': 'Taladros',
                        'nivel_burbuja': 'Nivel de burbuja',
                        'flexometros': 'Flexómetros',
                        'amoladoras': 'Amoladoras',
                        'pistola_calor': 'Pistola de calor',
                        'alicates': 'Alicates',
                        'destornilladores': 'Destornilladores',
                        'sierra_circular': 'Sierra circular',
                        'router': 'Router'
                    }
                    
                    item = ItemPresupuesto()
                    item.presupuesto_id = nuevo_presupuesto.id
                    item.tipo = 'herramienta'
                    item.descripcion = descripciones_herramientas.get(herramienta, herramienta.replace('_', ' ').title())
                    item.unidad = 'unidades'
                    item.cantidad = cantidad_float
                    item.precio_unitario = 0.0
                    item.total = 0.0
                    db.session.add(item)
            except (ValueError, TypeError):
                # Omitir herramientas con valores inválidos
                continue
        
        db.session.commit()
        
        return jsonify({
            'exito': True,
            'presupuesto_id': nuevo_presupuesto.id,
            'numero': numero,
            'mensaje': 'Presupuesto creado como borrador. Podrás convertirlo en obra desde la lista de presupuestos.',
            'redirect_url': url_for('presupuestos.detalle', id=nuevo_presupuesto.id)
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error creando presupuesto: {str(e)}'}), 500

@presupuestos_bp.route('/exportar-excel-ia', methods=['POST'])
@login_required
def exportar_excel_ia():
    """Exporta los resultados de la calculadora IA a Excel"""
    if not current_user.puede_acceder_modulo('presupuestos'):
        return jsonify({'error': 'Sin permisos'}), 403

    if not XLSXWRITER_AVAILABLE:
        return (
            jsonify({
                'error': "La exportación a Excel requiere la librería xlsxwriter. Instálala con 'pip install xlsxwriter'."
            }),
            500,
        )

    try:
        data = request.get_json()
        if not data or not data.get('presupuesto'):
            return jsonify({'error': 'No se recibieron datos'}), 400
        
        presupuesto = data['presupuesto']
        
        # Crear archivo Excel en memoria
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        
        # Formatos
        header_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'bg_color': '#2E5BBA',
            'color': 'white',
            'align': 'center'
        })
        
        subheader_format = workbook.add_format({
            'bold': True,
            'font_size': 12,
            'bg_color': '#F0F0F0'
        })
        
        number_format = workbook.add_format({'num_format': '#,##0.00'})
        
        # Hoja principal
        worksheet = workbook.add_worksheet('Presupuesto IA')
        
        # Encabezado
        worksheet.merge_range('A1:E1', 'PRESUPUESTO CALCULADO CON IA', header_format)
        
        row = 3
        
        # Información del proyecto
        metadata = presupuesto.get('metadata', {})
        worksheet.write(row, 0, 'Superficie:', subheader_format)
        worksheet.write(row, 1, f"{metadata.get('superficie_m2', 0)} m²")
        row += 1
        
        worksheet.write(row, 0, 'Tipo de Construcción:', subheader_format)
        worksheet.write(row, 1, metadata.get('tipo_construccion', 'N/A'))
        row += 2
        
        # Materiales
        worksheet.write(row, 0, 'MATERIALES', subheader_format)
        row += 1
        
        worksheet.write(row, 0, 'Material', subheader_format)
        worksheet.write(row, 1, 'Cantidad', subheader_format)
        worksheet.write(row, 2, 'Unidad', subheader_format)
        row += 1
        
        materiales = presupuesto.get('materiales', {})
        unidades_map = {
            'ladrillos': 'unidades', 'cemento': 'bolsas', 'cal': 'kg',
            'arena': 'm³', 'piedra': 'm³', 'hierro_8': 'kg',
            'hierro_10': 'kg', 'hierro_12': 'kg', 'membrana': 'm²',
            'pintura': 'litros'
        }
        
        for material, cantidad in materiales.items():
            worksheet.write(row, 0, material.replace('_', ' ').title())
            worksheet.write(row, 1, cantidad, number_format)
            worksheet.write(row, 2, unidades_map.get(material, 'unidades'))
            row += 1
        
        row += 1
        
        # Equipos
        worksheet.write(row, 0, 'EQUIPOS Y MAQUINARIAS', subheader_format)
        row += 1
        
        worksheet.write(row, 0, 'Equipo', subheader_format)
        worksheet.write(row, 1, 'Cantidad', subheader_format)
        worksheet.write(row, 2, 'Días de Uso', subheader_format)
        row += 1
        
        equipos = presupuesto.get('equipos', {})
        for equipo, specs in equipos.items():
            if specs.get('cantidad', 0) > 0:
                worksheet.write(row, 0, equipo.replace('_', ' ').title())
                worksheet.write(row, 1, specs.get('cantidad', 0))
                worksheet.write(row, 2, specs.get('dias_uso', 0))
                row += 1
        
        workbook.close()
        output.seek(0)
        
        # Crear respuesta
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename=presupuesto_ia_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
        
        return response
        
    except Exception as e:
        return jsonify({'error': f'Error exportando Excel: {str(e)}'}), 500

@presupuestos_bp.route('/<int:id>')
@login_required
def detalle(id):
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para ver presupuestos.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    presupuesto = Presupuesto.query.get_or_404(id)
    items = presupuesto.items.all()
    
    # Agrupar items por tipo
    materiales = [item for item in items if item.tipo == 'material']
    mano_obra = [item for item in items if item.tipo == 'mano_obra']
    equipos = [item for item in items if item.tipo == 'equipo']
    herramientas = [item for item in items if item.tipo == 'herramienta']
    
    return render_template('presupuestos/detalle.html', 
                         presupuesto=presupuesto,
                         materiales=materiales,
                         mano_obra=mano_obra,
                         equipos=equipos,
                         herramientas=herramientas)

@presupuestos_bp.route('/<int:id>/item', methods=['POST'])
@login_required
def agregar_item(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para agregar items.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    presupuesto = Presupuesto.query.get_or_404(id)
    
    if presupuesto.estado != 'borrador':
        flash('Solo se pueden agregar items a presupuestos en borrador.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    tipo = request.form.get('tipo')
    descripcion = request.form.get('descripcion')
    unidad = request.form.get('unidad')
    cantidad = request.form.get('cantidad')
    precio_unitario = request.form.get('precio_unitario')
    
    if not all([tipo, descripcion, unidad, cantidad, precio_unitario]):
        flash('Completa todos los campos.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    try:
        cantidad_float = float(cantidad) if cantidad else 0.0
        precio_unitario_float = float(precio_unitario) if precio_unitario else 0.0
        total = cantidad_float * precio_unitario_float
    except ValueError:
        flash('Cantidad y precio deben ser números válidos.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    nuevo_item = ItemPresupuesto()
    nuevo_item.presupuesto_id = id
    nuevo_item.tipo = tipo
    nuevo_item.descripcion = descripcion
    nuevo_item.unidad = unidad
    nuevo_item.cantidad = cantidad_float
    nuevo_item.precio_unitario = precio_unitario_float
    nuevo_item.total = total
    
    try:
        db.session.add(nuevo_item)
        presupuesto.calcular_totales()
        db.session.commit()
        flash('Item agregado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al agregar el item.', 'danger')
    
    return redirect(url_for('presupuestos.detalle', id=id))

@presupuestos_bp.route('/item/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_item(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para eliminar items.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    item = ItemPresupuesto.query.get_or_404(id)
    presupuesto = item.presupuesto
    
    if presupuesto.estado != 'borrador':
        flash('Solo se pueden eliminar items de presupuestos en borrador.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=presupuesto.id))
    
    try:
        db.session.delete(item)
        presupuesto.calcular_totales()
        db.session.commit()
        flash('Item eliminado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al eliminar el item.', 'danger')
    
    return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

@presupuestos_bp.route('/<int:id>/estado', methods=['POST'])
@login_required
def cambiar_estado(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para cambiar el estado.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    presupuesto = Presupuesto.query.get_or_404(id)
    nuevo_estado = request.form.get('estado')
    
    if nuevo_estado not in ['borrador', 'enviado', 'aprobado', 'rechazado']:
        flash('Estado no válido.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    presupuesto.estado = nuevo_estado
    
    try:
        db.session.commit()
        flash(f'Estado cambiado a {nuevo_estado} exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al cambiar el estado.', 'danger')
    
    return redirect(url_for('presupuestos.detalle', id=id))

@presupuestos_bp.route('/<int:id>/pdf')
@login_required
def generar_pdf(id):
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para generar PDFs.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    if not REPORTLAB_AVAILABLE:
        flash(
            "La generación de PDF requiere la librería reportlab. Instálala ejecutando 'pip install reportlab'.",
            'danger'
        )
        return redirect(url_for('presupuestos.detalle', id=id))

    presupuesto = Presupuesto.query.get_or_404(id)
    items = presupuesto.items.all()

    # Crear buffer para el PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    
    # Estilos
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    # Título
    story.append(Paragraph('PRESUPUESTO DE OBRA', title_style))
    story.append(Spacer(1, 20))
    
    # Información del presupuesto
    info_data = [
        ['Número:', presupuesto.numero],
        ['Fecha:', presupuesto.fecha.strftime('%d/%m/%Y')],
        ['Obra:', presupuesto.obra.nombre],
        ['Cliente:', presupuesto.obra.cliente],
        ['Estado:', presupuesto.estado.upper()]
    ]
    
    info_table = Table(info_data, colWidths=[2*inch, 4*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    story.append(info_table)
    story.append(Spacer(1, 30))
    
    # Tabla de items
    if items:
        # Encabezados
        data = [['Descripción', 'Unidad', 'Cantidad', 'P. Unit.', 'Total']]
        
        # Materiales
        materiales = [item for item in items if item.tipo == 'material']
        if materiales:
            data.append(['MATERIALES', '', '', '', ''])
            for item in materiales:
                data.append([
                    item.descripcion,
                    item.unidad,
                    f"{item.cantidad:.2f}",
                    f"${item.precio_unitario:.2f}",
                    f"${item.total:.2f}"
                ])
            data.append(['', '', '', 'Subtotal Materiales:', f"${presupuesto.subtotal_materiales:.2f}"])
        
        # Mano de obra
        mano_obra = [item for item in items if item.tipo == 'mano_obra']
        if mano_obra:
            data.append(['', '', '', '', ''])
            data.append(['MANO DE OBRA', '', '', '', ''])
            for item in mano_obra:
                data.append([
                    item.descripcion,
                    item.unidad,
                    f"{item.cantidad:.2f}",
                    f"${item.precio_unitario:.2f}",
                    f"${item.total:.2f}"
                ])
            data.append(['', '', '', 'Subtotal Mano de Obra:', f"${presupuesto.subtotal_mano_obra:.2f}"])
        
        # Equipos
        equipos = [item for item in items if item.tipo == 'equipo']
        if equipos:
            data.append(['', '', '', '', ''])
            data.append(['EQUIPOS', '', '', '', ''])
            for item in equipos:
                data.append([
                    item.descripcion,
                    item.unidad,
                    f"{item.cantidad:.2f}",
                    f"${item.precio_unitario:.2f}",
                    f"${item.total:.2f}"
                ])
            data.append(['', '', '', 'Subtotal Equipos:', f"${presupuesto.subtotal_equipos:.2f}"])
        
        # Totales
        data.append(['', '', '', '', ''])
        data.append(['', '', '', 'TOTAL SIN IVA:', f"${presupuesto.total_sin_iva:.2f}"])
        data.append(['', '', '', f'IVA ({presupuesto.iva_porcentaje}%):', f"${(presupuesto.total_con_iva - presupuesto.total_sin_iva):.2f}"])
        data.append(['', '', '', 'TOTAL CON IVA:', f"${presupuesto.total_con_iva:.2f}"])
        
        table = Table(data, colWidths=[3*inch, 0.8*inch, 0.8*inch, 1.2*inch, 1.2*inch])
        table.setStyle(TableStyle([
            # Encabezado
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            
            # Cuerpo
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            
            # Subtotales y totales en negrita
            ('FONTNAME', (3, -4), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        story.append(table)
    
    # Observaciones
    if presupuesto.observaciones:
        story.append(Spacer(1, 30))
        story.append(Paragraph('Observaciones:', styles['Heading2']))
        story.append(Paragraph(presupuesto.observaciones, styles['Normal']))
    
    # Generar PDF
    doc.build(story)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=presupuesto_{presupuesto.numero}.pdf'
    
    return response

@presupuestos_bp.route('/<int:id>/editar-obra', methods=['POST'])
@login_required
def editar_obra(id):
    """Editar información de la obra asociada al presupuesto"""
    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'error': 'Sin permisos'}), 403
    
    presupuesto = Presupuesto.query.get_or_404(id)
    obra = presupuesto.obra
    
    data = request.get_json()
    
    try:
        # Actualizar campos de la obra
        if 'nombre' in data:
            obra.nombre = data['nombre']
        if 'cliente' in data:
            obra.cliente = data['cliente']
        if 'descripcion' in data:
            obra.descripcion = data['descripcion']
        if 'direccion' in data:
            obra.direccion = data['direccion']
        if 'fecha_inicio' in data and data['fecha_inicio']:
            obra.fecha_inicio = datetime.strptime(data['fecha_inicio'], '%Y-%m-%d').date()
        if 'fecha_fin_estimada' in data and data['fecha_fin_estimada']:
            obra.fecha_fin_estimada = datetime.strptime(data['fecha_fin_estimada'], '%Y-%m-%d').date()
        if 'presupuesto_total' in data and data['presupuesto_total']:
            obra.presupuesto_total = float(data['presupuesto_total'])
        
        db.session.commit()
        return jsonify({'exito': True, 'mensaje': 'Obra actualizada correctamente'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error actualizando obra: {str(e)}'}), 500

@presupuestos_bp.route('/item/<int:item_id>/editar', methods=['POST'])
@login_required
def editar_item(item_id):
    """Editar un item específico del presupuesto"""
    if not current_user.puede_acceder_modulo('presupuestos') or current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'error': 'Sin permisos'}), 403
    
    item = ItemPresupuesto.query.get_or_404(item_id)
    presupuesto = item.presupuesto
    
    data = request.get_json()
    
    try:
        # Actualizar campos del item
        if 'descripcion' in data:
            item.descripcion = data['descripcion']
        if 'unidad' in data:
            item.unidad = data['unidad']
        if 'cantidad' in data:
            item.cantidad = float(data['cantidad'])
        if 'precio_unitario' in data:
            item.precio_unitario = float(data['precio_unitario'])
        
        # Recalcular total
        item.total = item.cantidad * item.precio_unitario
        
        # Recalcular totales del presupuesto
        presupuesto.calcular_totales()
        
        db.session.commit()
        return jsonify({
            'exito': True, 
            'mensaje': 'Item actualizado correctamente',
            'nuevo_total': float(item.total),
            'subtotal_materiales': float(presupuesto.subtotal_materiales),
            'subtotal_mano_obra': float(presupuesto.subtotal_mano_obra),
            'subtotal_equipos': float(presupuesto.subtotal_equipos),
            'total_sin_iva': float(presupuesto.total_sin_iva),
            'total_con_iva': float(presupuesto.total_con_iva)
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error actualizando item: {str(e)}'}), 500


@presupuestos_bp.route('/<int:id>/confirmar-obra', methods=['POST'])
@login_required
def confirmar_como_obra(id):
    """Convierte un presupuesto borrador en una obra confirmada"""
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para confirmar obras.', 'danger')
        return redirect(url_for('presupuestos.lista'))
    
    presupuesto = Presupuesto.query.get_or_404(id)
    
    if presupuesto.organizacion_id != current_user.organizacion_id:
        flash('No tienes permisos para acceder a este presupuesto.', 'danger')
        return redirect(url_for('presupuestos.lista'))
    
    if presupuesto.confirmado_como_obra:
        flash('Este presupuesto ya fue confirmado como obra.', 'warning')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    try:
        # Recuperar datos del proyecto
        datos_proyecto = {}
        if presupuesto.datos_proyecto:
            datos_proyecto = json.loads(presupuesto.datos_proyecto)
        
        # Crear nueva obra desde los datos del presupuesto
        nombre_obra = datos_proyecto.get('nombre', f'Obra desde Presupuesto {presupuesto.numero}')
        
        nueva_obra = Obra()
        nueva_obra.nombre = nombre_obra
        nueva_obra.cliente = datos_proyecto.get('cliente', 'Cliente desde presupuesto')
        nueva_obra.descripcion = f"Superficie: {datos_proyecto.get('superficie', 0)}m² - {datos_proyecto.get('ubicacion', 'Ubicación no especificada')} - Tipo: {datos_proyecto.get('tipo_construccion', 'Estándar')}"
        nueva_obra.direccion = datos_proyecto.get('ubicacion', 'Por especificar')
        nueva_obra.estado = 'planificacion'
        nueva_obra.presupuesto_total = float(presupuesto.total_con_iva)
        nueva_obra.organizacion_id = current_user.organizacion_id
        
        # Geocodificar si hay ubicación
        if datos_proyecto.get('ubicacion'):
            try:
                from geocoding import geocodificar_direccion
                coords = geocodificar_direccion(datos_proyecto['ubicacion'])
                if coords:
                    nueva_obra.latitud = coords['lat']
                    nueva_obra.longitud = coords['lng']
            except:
                pass  # Si falla geocodificación, continúa sin coordenadas
        
        db.session.add(nueva_obra)
        db.session.flush()  # Para obtener el ID
        
        # Asociar presupuesto con la obra y marcarlo como convertido
        presupuesto.obra_id = nueva_obra.id
        presupuesto.confirmado_como_obra = True
        presupuesto.estado = 'convertido'  # Cambiar estado para ocultarlo de la lista
        
        # Verificar si la obra ya tiene etapas para evitar duplicados
        etapas_existentes = EtapaObra.query.filter_by(obra_id=nueva_obra.id).count()
        
        if etapas_existentes == 0:
            # Solo crear etapas si no existen
            etapas_basicas = [
                {'nombre': 'Excavación', 'descripcion': 'Preparación del terreno y excavaciones', 'orden': 1},
                {'nombre': 'Fundaciones', 'descripcion': 'Construcción de fundaciones y bases', 'orden': 2},
                {'nombre': 'Estructura', 'descripcion': 'Construcción de estructura principal', 'orden': 3},
                {'nombre': 'Mampostería', 'descripcion': 'Construcción de muros y paredes', 'orden': 4},
                {'nombre': 'Techos', 'descripcion': 'Construcción de techos y cubiertas', 'orden': 5},
                {'nombre': 'Instalaciones', 'descripcion': 'Instalaciones eléctricas, sanitarias y gas', 'orden': 6},
                {'nombre': 'Terminaciones', 'descripcion': 'Acabados y terminaciones finales', 'orden': 7}
            ]
        
            from tareas_predefinidas import TAREAS_POR_ETAPA
            
            for etapa_data in etapas_basicas:
                nueva_etapa = EtapaObra(
                    obra_id=nueva_obra.id,
                    nombre=etapa_data['nombre'],
                    descripcion=etapa_data['descripcion'],
                    orden=etapa_data['orden'],
                    estado='pendiente'
                )
                
                db.session.add(nueva_etapa)
                db.session.flush()  # Para obtener el ID de la etapa
                
                # Agregar tareas predefinidas si existen
                tareas_etapa = TAREAS_POR_ETAPA.get(etapa_data['nombre'], [])
                for idx, nombre_tarea in enumerate(tareas_etapa[:10]):  # Limitar a 10 tareas por etapa
                    from models import TareaEtapa
                    nueva_tarea = TareaEtapa(
                        etapa_id=nueva_etapa.id,
                        nombre=nombre_tarea,
                        descripcion=f"Tarea predefinida para {etapa_data['nombre']}",
                        estado='pendiente'
                    )
                    db.session.add(nueva_tarea)
        
        db.session.commit()
        
        flash(f'¡Presupuesto convertido exitosamente en obra "{nombre_obra}"!', 'success')
        return redirect(url_for('obras.detalle', id=nueva_obra.id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al confirmar obra: {str(e)}', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route("/guardar", methods=["POST"])
@login_required
def guardar_presupuesto():
    """Guarda presupuesto con opción de crear obra nueva o usar existente"""
    if not current_user.puede_acceder_modulo('presupuestos'):
        return jsonify({'error': 'Sin permisos'}), 403
    
    data = request.form or request.json
    
    obra_id = data.get("obra_id")  # id si seleccionó obra existente
    crear_nueva = data.get("crear_nueva_obra") == "1"
    
    try:
        if crear_nueva:
            # Crear nueva obra con los datos del formulario
            obra = Obra(
                nombre = data.get("obra_nombre") or "Obra sin nombre",
                organizacion_id = current_user.organizacion_id,  # Usar organizacion_id del sistema actual
                cliente_nombre = data.get("cliente_nombre"),
                cliente_email  = data.get("cliente_email"),
                cliente_telefono = data.get("cliente_telefono"),
                direccion = data.get("direccion"),
                ciudad    = data.get("ciudad"),
                provincia = data.get("provincia"),
                pais      = data.get("pais") or "Argentina",
                codigo_postal = data.get("codigo_postal"),
                referencia = data.get("referencia"),
                notas = data.get("obra_notas"),
                estado = 'planificacion'
            )
            db.session.add(obra)
            db.session.flush()   # obtiene obra.id
            obra_id = obra.id
        else:
            obra = Obra.query.get(obra_id) if obra_id else None
        
        # Generar número de presupuesto único
        ultimo_numero = db.session.query(db.func.max(Presupuesto.numero)).scalar()
        if ultimo_numero and ultimo_numero.startswith('PRES-'):
            try:
                siguiente_num = int(ultimo_numero.split('-')[1]) + 1
            except:
                siguiente_num = 1
        else:
            siguiente_num = 1
        
        # Asegurar que el número sea único
        while True:
            numero = f"PRES-{siguiente_num:04d}"
            existe = Presupuesto.query.filter_by(numero=numero).first()
            if not existe:
                break
            siguiente_num += 1
        
        # Crear presupuesto asociado
        p = Presupuesto(
            obra_id = obra_id,
            numero = numero,
            organizacion_id = current_user.organizacion_id,
            observaciones = data.get("observaciones"),
            iva_porcentaje = 21.0,
            estado = 'borrador'
        )
        
        # Agregar campos adicionales si están disponibles
        if data.get("superficie"):
            try:
                superficie_float = float(data.get("superficie"))
                p.observaciones = f"{p.observaciones or ''} | Superficie: {superficie_float} m²"
            except ValueError:
                pass
        
        if data.get("tipo_construccion"):
            p.observaciones = f"{p.observaciones or ''} | Tipo: {data.get('tipo_construccion')}"
        
        if data.get("calculo_json"):
            p.datos_proyecto = data.get("calculo_json")
        
        if data.get("total_estimado"):
            try:
                p.total_con_iva = float(data.get("total_estimado"))
            except ValueError:
                pass
        
        db.session.add(p)
        db.session.commit()
        
        return jsonify({"ok": True, "presupuesto_id": p.id, "obra_id": obra_id})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
