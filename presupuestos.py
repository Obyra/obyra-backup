from flask import Blueprint, render_template, request, flash, redirect, url_for, make_response
from flask_login import login_required, current_user
from datetime import date
from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from app import db
from models import Presupuesto, ItemPresupuesto, Obra

presupuestos_bp = Blueprint('presupuestos', __name__)

@presupuestos_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('presupuestos'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    estado = request.args.get('estado', '')
    buscar = request.args.get('buscar', '')
    
    query = Presupuesto.query.join(Obra)
    
    if estado:
        query = query.filter(Presupuesto.estado == estado)
    
    if buscar:
        query = query.filter(
            db.or_(
                Presupuesto.numero.contains(buscar),
                Obra.nombre.contains(buscar),
                Obra.cliente.contains(buscar)
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
    
    obras = Obra.query.filter(Obra.estado.in_(['planificacion', 'en_curso'])).order_by(Obra.nombre).all()
    
    if request.method == 'POST':
        obra_id = request.form.get('obra_id')
        observaciones = request.form.get('observaciones')
        iva_porcentaje = request.form.get('iva_porcentaje', 21)
        
        if not obra_id:
            flash('Selecciona una obra.', 'danger')
            return render_template('presupuestos/crear.html', obras=obras)
        
        # Generar número de presupuesto
        ultimo_numero = db.session.query(db.func.max(Presupuesto.numero)).scalar()
        if ultimo_numero:
            numero = f"PRES-{int(ultimo_numero.split('-')[1]) + 1:04d}"
        else:
            numero = "PRES-0001"
        
        nuevo_presupuesto = Presupuesto(
            obra_id=obra_id,
            numero=numero,
            observaciones=observaciones,
            iva_porcentaje=float(iva_porcentaje)
        )
        
        try:
            db.session.add(nuevo_presupuesto)
            db.session.commit()
            flash(f'Presupuesto {numero} creado exitosamente.', 'success')
            return redirect(url_for('presupuestos.detalle', id=nuevo_presupuesto.id))
        except Exception as e:
            db.session.rollback()
            flash('Error al crear el presupuesto. Intenta nuevamente.', 'danger')
    
    return render_template('presupuestos/crear.html', obras=obras)

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
    
    return render_template('presupuestos/detalle.html', 
                         presupuesto=presupuesto,
                         materiales=materiales,
                         mano_obra=mano_obra,
                         equipos=equipos)

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
        cantidad = float(cantidad)
        precio_unitario = float(precio_unitario)
        total = cantidad * precio_unitario
    except ValueError:
        flash('Cantidad y precio deben ser números válidos.', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))
    
    nuevo_item = ItemPresupuesto(
        presupuesto_id=id,
        tipo=tipo,
        descripcion=descripcion,
        unidad=unidad,
        cantidad=cantidad,
        precio_unitario=precio_unitario,
        total=total
    )
    
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
