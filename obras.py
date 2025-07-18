from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from app import db
from models import Obra, EtapaObra, TareaEtapa, AsignacionObra, Usuario

obras_bp = Blueprint('obras', __name__)

@obras_bp.route('/')
@login_required
def lista():
    if not current_user.puede_acceder_modulo('obras'):
        flash('No tienes permisos para acceder a este módulo.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    estado = request.args.get('estado', '')
    buscar = request.args.get('buscar', '')
    
    query = Obra.query
    
    if estado:
        query = query.filter(Obra.estado == estado)
    
    if buscar:
        query = query.filter(
            db.or_(
                Obra.nombre.contains(buscar),
                Obra.cliente.contains(buscar),
                Obra.direccion.contains(buscar)
            )
        )
    
    obras = query.order_by(Obra.fecha_creacion.desc()).all()
    
    return render_template('obras/lista.html', obras=obras, estado=estado, buscar=buscar)

@obras_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    if not current_user.puede_acceder_modulo('obras'):
        flash('No tienes permisos para crear obras.', 'danger')
        return redirect(url_for('obras.lista'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        direccion = request.form.get('direccion')
        cliente = request.form.get('cliente')
        telefono_cliente = request.form.get('telefono_cliente')
        email_cliente = request.form.get('email_cliente')
        fecha_inicio = request.form.get('fecha_inicio')
        fecha_fin_estimada = request.form.get('fecha_fin_estimada')
        presupuesto_total = request.form.get('presupuesto_total')
        
        # Validaciones
        if not all([nombre, cliente]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            return render_template('obras/crear.html')
        
        # Convertir fechas
        fecha_inicio_obj = None
        fecha_fin_estimada_obj = None
        
        if fecha_inicio:
            try:
                fecha_inicio_obj = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
            except ValueError:
                flash('Formato de fecha de inicio inválido.', 'danger')
                return render_template('obras/crear.html')
        
        if fecha_fin_estimada:
            try:
                fecha_fin_estimada_obj = datetime.strptime(fecha_fin_estimada, '%Y-%m-%d').date()
            except ValueError:
                flash('Formato de fecha de fin estimada inválido.', 'danger')
                return render_template('obras/crear.html')
        
        # Validar que fecha fin sea posterior a fecha inicio
        if fecha_inicio_obj and fecha_fin_estimada_obj and fecha_fin_estimada_obj <= fecha_inicio_obj:
            flash('La fecha de fin debe ser posterior a la fecha de inicio.', 'danger')
            return render_template('obras/crear.html')
        
        # Crear obra
        nueva_obra = Obra(
            nombre=nombre,
            descripcion=descripcion,
            direccion=direccion,
            cliente=cliente,
            telefono_cliente=telefono_cliente,
            email_cliente=email_cliente,
            fecha_inicio=fecha_inicio_obj,
            fecha_fin_estimada=fecha_fin_estimada_obj,
            presupuesto_total=float(presupuesto_total) if presupuesto_total else 0,
            estado='planificacion'
        )
        
        try:
            db.session.add(nueva_obra)
            db.session.commit()
            flash(f'Obra "{nombre}" creada exitosamente.', 'success')
            return redirect(url_for('obras.detalle', id=nueva_obra.id))
        except Exception as e:
            db.session.rollback()
            flash('Error al crear la obra. Intenta nuevamente.', 'danger')
    
    return render_template('obras/crear.html')

@obras_bp.route('/<int:id>')
@login_required
def detalle(id):
    if not current_user.puede_acceder_modulo('obras'):
        flash('No tienes permisos para ver obras.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    obra = Obra.query.get_or_404(id)
    etapas = obra.etapas.order_by(EtapaObra.orden).all()
    asignaciones = obra.asignaciones.filter_by(activo=True).all()
    usuarios_disponibles = Usuario.query.filter_by(activo=True).all()
    
    return render_template('obras/detalle.html', 
                         obra=obra, 
                         etapas=etapas, 
                         asignaciones=asignaciones,
                         usuarios_disponibles=usuarios_disponibles)

@obras_bp.route('/<int:id>/editar', methods=['POST'])
@login_required
def editar(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para editar obras.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    obra = Obra.query.get_or_404(id)
    
    obra.nombre = request.form.get('nombre', obra.nombre)
    obra.descripcion = request.form.get('descripcion', obra.descripcion)
    obra.direccion = request.form.get('direccion', obra.direccion)
    obra.cliente = request.form.get('cliente', obra.cliente)
    obra.telefono_cliente = request.form.get('telefono_cliente', obra.telefono_cliente)
    obra.email_cliente = request.form.get('email_cliente', obra.email_cliente)
    obra.estado = request.form.get('estado', obra.estado)
    obra.progreso = int(request.form.get('progreso', obra.progreso))
    
    # Actualizar fechas si se proporcionan
    fecha_inicio = request.form.get('fecha_inicio')
    if fecha_inicio:
        try:
            obra.fecha_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    fecha_fin_estimada = request.form.get('fecha_fin_estimada')
    if fecha_fin_estimada:
        try:
            obra.fecha_fin_estimada = datetime.strptime(fecha_fin_estimada, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    presupuesto_total = request.form.get('presupuesto_total')
    if presupuesto_total:
        try:
            obra.presupuesto_total = float(presupuesto_total)
        except ValueError:
            pass
    
    try:
        db.session.commit()
        flash('Obra actualizada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al actualizar la obra.', 'danger')
    
    return redirect(url_for('obras.detalle', id=id))

@obras_bp.route('/<int:id>/etapa', methods=['POST'])
@login_required
def agregar_etapa(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para agregar etapas.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    obra = Obra.query.get_or_404(id)
    
    nombre = request.form.get('nombre')
    descripcion = request.form.get('descripcion')
    
    if not nombre:
        flash('El nombre de la etapa es obligatorio.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    # Obtener el próximo orden
    ultimo_orden = db.session.query(db.func.max(EtapaObra.orden)).filter_by(obra_id=id).scalar() or 0
    
    nueva_etapa = EtapaObra(
        obra_id=id,
        nombre=nombre,
        descripcion=descripcion,
        orden=ultimo_orden + 1
    )
    
    try:
        db.session.add(nueva_etapa)
        db.session.commit()
        flash(f'Etapa "{nombre}" agregada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al agregar la etapa.', 'danger')
    
    return redirect(url_for('obras.detalle', id=id))

@obras_bp.route('/etapa/<int:id>/tarea', methods=['POST'])
@login_required
def agregar_tarea(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para agregar tareas.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    etapa = EtapaObra.query.get_or_404(id)
    
    nombre = request.form.get('nombre')
    descripcion = request.form.get('descripcion')
    horas_estimadas = request.form.get('horas_estimadas')
    responsable_id = request.form.get('responsable_id')
    
    if not nombre:
        flash('El nombre de la tarea es obligatorio.', 'danger')
        return redirect(url_for('obras.detalle', id=etapa.obra_id))
    
    nueva_tarea = TareaEtapa(
        etapa_id=id,
        nombre=nombre,
        descripcion=descripcion,
        horas_estimadas=float(horas_estimadas) if horas_estimadas else None,
        responsable_id=int(responsable_id) if responsable_id else None
    )
    
    try:
        db.session.add(nueva_tarea)
        db.session.commit()
        flash(f'Tarea "{nombre}" agregada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al agregar la tarea.', 'danger')
    
    return redirect(url_for('obras.detalle', id=etapa.obra_id))

@obras_bp.route('/<int:id>/asignar', methods=['POST'])
@login_required
def asignar_usuario(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para asignar usuarios.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    obra = Obra.query.get_or_404(id)
    
    usuario_id = request.form.get('usuario_id')
    rol_en_obra = request.form.get('rol_en_obra')
    
    if not all([usuario_id, rol_en_obra]):
        flash('Selecciona un usuario y un rol.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    # Verificar que no esté ya asignado
    asignacion_existente = AsignacionObra.query.filter_by(
        obra_id=id,
        usuario_id=usuario_id,
        activo=True
    ).first()
    
    if asignacion_existente:
        flash('El usuario ya está asignado a esta obra.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    nueva_asignacion = AsignacionObra(
        obra_id=id,
        usuario_id=usuario_id,
        rol_en_obra=rol_en_obra
    )
    
    try:
        db.session.add(nueva_asignacion)
        db.session.commit()
        flash('Usuario asignado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al asignar el usuario.', 'danger')
    
    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/eliminar/<int:obra_id>', methods=['POST'])
@login_required
def eliminar_obra(obra_id):
    """Eliminar obra - Solo para superadministradores"""
    if current_user.email not in ['brenda@gmail.com', 'admin@obyra.com']:
        flash('No tienes permisos para eliminar obras.', 'danger')
        return redirect(url_for('obras.lista'))
    
    obra = Obra.query.filter_by(id=obra_id, organizacion_id=current_user.organizacion_id).first_or_404()
    nombre_obra = obra.nombre
    
    try:
        # Eliminar asignaciones relacionadas
        AsignacionObra.query.filter_by(obra_id=obra_id).delete()
        
        # Eliminar tareas relacionadas
        for etapa in obra.etapas:
            TareaEtapa.query.filter_by(etapa_id=etapa.id).delete()
        
        # Eliminar etapas relacionadas
        EtapaObra.query.filter_by(obra_id=obra_id).delete()
        
        # Eliminar la obra
        db.session.delete(obra)
        db.session.commit()
        
        flash(f'La obra "{nombre_obra}" ha sido eliminada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al eliminar la obra. Inténtalo nuevamente.', 'danger')
    
    return redirect(url_for('obras.lista'))


@obras_bp.route('/super-admin/reiniciar-sistema', methods=['POST'])
@login_required
def reiniciar_sistema():
    """Reiniciar sistema eliminando todas las obras - Solo para superadministradores"""
    if current_user.email not in ['brenda@gmail.com', 'admin@obyra.com']:
        flash('No tienes permisos para reiniciar el sistema.', 'danger')
        return redirect(url_for('obras.lista'))
    
    try:
        # Eliminar todas las asignaciones
        AsignacionObra.query.delete()
        
        # Eliminar todas las tareas
        TareaEtapa.query.delete()
        
        # Eliminar todas las etapas
        EtapaObra.query.delete()
        
        # Eliminar todas las obras
        Obra.query.delete()
        
        db.session.commit()
        flash('Sistema reiniciado exitosamente. Todas las obras han sido eliminadas.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al reiniciar el sistema. Inténtalo nuevamente.', 'danger')
    
    return redirect(url_for('obras.lista'))
