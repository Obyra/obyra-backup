from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
import requests
from app import db
from models import Obra, EtapaObra, TareaEtapa, AsignacionObra, Usuario, CertificacionAvance
from etapas_predefinidas import obtener_etapas_disponibles, crear_etapas_para_obra
from geocoding import geocodificar_direccion, normalizar_direccion_argentina

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
        
        # Geolocalizar dirección si se proporciona
        latitud, longitud = None, None
        if direccion:
            direccion_normalizada = normalizar_direccion_argentina(direccion)
            latitud, longitud = geocodificar_direccion(direccion_normalizada)
        
        # Crear obra
        nueva_obra = Obra(
            nombre=nombre,
            descripcion=descripcion if 'descripcion' in request.form else None,
            direccion=direccion,
            latitud=latitud,
            longitud=longitud,
            cliente=cliente,
            telefono_cliente=telefono_cliente,
            email_cliente=email_cliente,
            fecha_inicio=fecha_inicio_obj,
            fecha_fin_estimada=fecha_fin_estimada_obj,
            presupuesto_total=float(presupuesto_total) if presupuesto_total else 0,
            estado='planificacion',
            organizacion_id=current_user.organizacion_id
        )
        
        try:
            db.session.add(nueva_obra)
            db.session.commit()
            flash(f'Obra "{nombre}" creada exitosamente.', 'success')
            return redirect(url_for('obras.detalle', id=nueva_obra.id))
        except Exception as e:
            db.session.rollback()
            # Mostrar el error específico para debug
            flash(f'Error al crear la obra: {str(e)}', 'danger')
            print(f"Error creating obra: {str(e)}")  # Para logs del servidor
    
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
    usuarios_disponibles = Usuario.query.filter_by(activo=True, organizacion_id=current_user.organizacion_id).all()
    etapas_disponibles = obtener_etapas_disponibles()
    
    return render_template('obras/detalle.html', 
                         obra=obra, 
                         etapas=etapas, 
                         asignaciones=asignaciones,
                         usuarios_disponibles=usuarios_disponibles,
                         etapas_disponibles=etapas_disponibles)

@obras_bp.route('/<int:id>/editar', methods=['POST'])
@login_required
def editar(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para editar obras.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    obra = Obra.query.get_or_404(id)
    
    # Verificar permisos para pausar obra
    nuevo_estado = request.form.get('estado', obra.estado)
    if nuevo_estado == 'pausada' and not obra.puede_ser_pausada_por(current_user):
        flash('No tienes permisos para pausar esta obra.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    # Actualizar datos básicos
    obra.nombre = request.form.get('nombre', obra.nombre)
    obra.descripcion = request.form.get('descripcion', obra.descripcion)
    nueva_direccion = request.form.get('direccion', obra.direccion)
    obra.estado = nuevo_estado
    obra.cliente = request.form.get('cliente', obra.cliente)
    obra.telefono_cliente = request.form.get('telefono_cliente', obra.telefono_cliente)
    obra.email_cliente = request.form.get('email_cliente', obra.email_cliente)
    
    # Si cambió la dirección, geolocalizar nuevamente
    if nueva_direccion != obra.direccion:
        obra.direccion = nueva_direccion
        if nueva_direccion:
            coords = geolocalizar_direccion(nueva_direccion)
            if coords:
                obra.latitud, obra.longitud = coords
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


def geolocalizar_direccion(direccion):
    """Geolocaliza una dirección usando OpenStreetMap Nominatim API"""
    try:
        # Usar API gratuita de OpenStreetMap
        url = f"https://nominatim.openstreetmap.org/search"
        params = {
            'q': f"{direccion}, Argentina",
            'format': 'json',
            'limit': 1,
            'addressdetails': 1
        }
        
        headers = {
            'User-Agent': 'OBYRA-IA-Construction-Management'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data:
                lat = float(data[0]['lat'])
                lon = float(data[0]['lon'])
                return (lat, lon)
    except Exception as e:
        print(f"Error geolocalizando {direccion}: {str(e)}")
    
    return None


@obras_bp.route('/<int:id>/agregar_etapas', methods=['POST'])
@login_required
def agregar_etapas(id):
    """Agregar etapas predefinidas a una obra"""
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para gestionar etapas.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    obra = Obra.query.get_or_404(id)
    etapas_json = request.form.getlist('etapas[]')
    
    if not etapas_json:
        flash('Selecciona al menos una etapa.', 'warning')
        return redirect(url_for('obras.detalle', id=id))
    
    try:
        import json
        etapas_creadas = 0
        
        for etapa_json in etapas_json:
            try:
                etapa_data = json.loads(etapa_json)
                nombre = etapa_data.get('nombre', '').strip()
                descripcion = etapa_data.get('descripcion', '').strip()
                orden = int(etapa_data.get('orden', 1))
                
                if not nombre:
                    continue
                    
                # Verificar que no exista ya una etapa con el mismo nombre
                existe = EtapaObra.query.filter_by(obra_id=obra.id, nombre=nombre).first()
                if existe:
                    print(f"⚠️ Etapa {nombre} ya existe en obra {obra.id}, saltando...")
                    continue
                
                nueva_etapa = EtapaObra(
                    obra_id=obra.id,
                    nombre=nombre,
                    descripcion=descripcion,
                    orden=orden,
                    estado='pendiente',
                    organizacion_id=current_user.organizacion_id
                )
                
                db.session.add(nueva_etapa)
                db.session.flush()  # Para obtener el ID de la etapa
                
                # Crear tareas asociadas si las hay
                tareas = etapa_data.get('tareas', [])
                for tarea_data in tareas:
                    nombre_tarea = tarea_data.get('nombre', '').strip()
                    if nombre_tarea:
                        nueva_tarea = TareaEtapa(
                            etapa_id=nueva_etapa.id,
                            nombre=nombre_tarea,
                            descripcion=f"Tarea {'personalizada' if tarea_data.get('personalizada') else 'predefinida'} para {nombre}",
                            estado='pendiente'
                        )
                        db.session.add(nueva_tarea)
                
                etapas_creadas += 1
                
            except (json.JSONDecodeError, ValueError) as e:
                continue
        
        if etapas_creadas > 0:
            db.session.commit()
            flash(f'Se agregaron {etapas_creadas} etapas con sus tareas correspondientes a la obra.', 'success')
        else:
            flash('No se agregaron etapas nuevas. Las etapas seleccionadas ya existen en esta obra.', 'info')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error al agregar etapas: {str(e)}', 'danger')
    
    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/<int:id>/asignar_usuario', methods=['POST'])
@login_required
def asignar_usuario(id):
    """Asignar usuario a obra con etapa específica"""
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para gestionar asignaciones.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    obra = Obra.query.get_or_404(id)
    usuario_id = request.form.get('usuario_id')
    etapa_id = request.form.get('etapa_id')  # Puede ser None para asignación general
    rol_en_obra = request.form.get('rol_en_obra', 'operario')
    
    if not usuario_id:
        flash('Selecciona un usuario.', 'warning')
        return redirect(url_for('obras.detalle', id=id))
    
    # Verificar si ya existe asignación
    asignacion_existente = AsignacionObra.query.filter_by(
        obra_id=obra.id,
        usuario_id=usuario_id,
        etapa_id=etapa_id,
        activo=True
    ).first()
    
    if asignacion_existente:
        flash('El usuario ya está asignado a esta obra/etapa.', 'warning')
        return redirect(url_for('obras.detalle', id=id))
    
    try:
        nueva_asignacion = AsignacionObra(
            obra_id=obra.id,
            usuario_id=usuario_id,
            etapa_id=etapa_id if etapa_id else None,
            rol_en_obra=rol_en_obra
        )
        
        db.session.add(nueva_asignacion)
        db.session.commit()
        
        usuario = Usuario.query.get(usuario_id)
        etapa_nombre = ""
        if etapa_id:
            etapa = EtapaObra.query.get(etapa_id)
            etapa_nombre = f" - Etapa: {etapa.nombre}"
            
        flash(f'Usuario {usuario.nombre_completo} asignado exitosamente{etapa_nombre}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al asignar usuario: {str(e)}', 'danger')
    
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

@obras_bp.route('/geocodificar-todas', methods=['POST'])
@login_required
def geocodificar_todas():
    """Geocodifica todas las obras existentes que no tienen coordenadas"""
    if current_user.rol != 'administrador':
        flash('Solo los administradores pueden ejecutar esta acción.', 'danger')
        return redirect(url_for('obras.lista'))
    
    try:
        from geocoding import geocodificar_obras_existentes
        exitosas, fallidas = geocodificar_obras_existentes()
        
        if exitosas > 0:
            flash(f'Geocodificación completada: {exitosas} obras actualizadas, {fallidas} fallaron.', 'success')
        else:
            flash('No se pudieron geocodificar las obras. Verifica las direcciones.', 'warning')
            
    except Exception as e:
        flash(f'Error en la geocodificación: {str(e)}', 'danger')
    
    return redirect(url_for('obras.lista'))


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


# NUEVAS FUNCIONES PARA SISTEMA DE CERTIFICACIONES Y AVANCE AUTOMÁTICO

@obras_bp.route('/<int:id>/certificar_avance', methods=['POST'])
@login_required
def certificar_avance(id):
    """Crear nueva certificación de avance para una obra"""
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para certificar avances.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    obra = Obra.query.get_or_404(id)
    
    porcentaje_avance = request.form.get('porcentaje_avance')
    costo_certificado = request.form.get('costo_certificado')
    notas = request.form.get('notas')
    
    if not porcentaje_avance:
        flash('El porcentaje de avance es obligatorio.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    try:
        porcentaje = Decimal(porcentaje_avance)
        costo = Decimal(costo_certificado) if costo_certificado else Decimal('0')
        
        # Validar certificación
        valida, mensaje = CertificacionAvance.validar_certificacion(id, porcentaje)
        if not valida:
            flash(mensaje, 'danger')
            return redirect(url_for('obras.detalle', id=id))
        
        # Crear certificación
        certificacion = CertificacionAvance(
            obra_id=id,
            usuario_id=current_user.id,
            porcentaje_avance=porcentaje,
            costo_certificado=costo,
            notas=notas
        )
        
        db.session.add(certificacion)
        
        # Actualizar costo real de la obra
        obra.costo_real += costo
        
        # Recalcular progreso automático
        obra.calcular_progreso_automatico()
        
        db.session.commit()
        flash(f'Certificación de {porcentaje}% registrada exitosamente.', 'success')
        
    except ValueError:
        flash('Los valores numéricos no son válidos.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al registrar certificación: {str(e)}', 'danger')
    
    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/<int:id>/actualizar_progreso', methods=['POST'])
@login_required
def actualizar_progreso_automatico(id):
    """Recalcular el progreso automático de una obra"""
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para actualizar el progreso.', 'danger')
        return redirect(url_for('obras.detalle', id=id))
    
    obra = Obra.query.get_or_404(id)
    
    try:
        progreso_anterior = obra.progreso
        nuevo_progreso = obra.calcular_progreso_automatico()
        
        db.session.commit()
        
        flash(f'Progreso actualizado de {progreso_anterior}% a {nuevo_progreso}%.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar progreso: {str(e)}', 'danger')
    
    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/tarea/<int:id>/actualizar_estado', methods=['POST'])
@login_required
def actualizar_estado_tarea(id):
    """Actualizar estado y progreso de una tarea"""
    tarea = TareaEtapa.query.get_or_404(id)
    obra = tarea.etapa.obra
    
    nuevo_estado = request.form.get('estado')
    porcentaje_avance = request.form.get('porcentaje_avance')
    
    if nuevo_estado not in ['pendiente', 'en_curso', 'completada', 'cancelada']:
        flash('Estado no válido.', 'danger')
        return redirect(url_for('obras.detalle', id=obra.id))
    
    try:
        tarea.estado = nuevo_estado
        
        if porcentaje_avance:
            tarea.porcentaje_avance = Decimal(porcentaje_avance)
        
        # Si se marca como completada, establecer el avance al 100%
        if nuevo_estado == 'completada':
            tarea.porcentaje_avance = Decimal('100')
            tarea.fecha_fin_real = date.today()
        elif nuevo_estado == 'en_curso' and not tarea.fecha_inicio_real:
            tarea.fecha_inicio_real = date.today()
        
        # Recalcular progreso automático de la obra
        obra.calcular_progreso_automatico()
        
        db.session.commit()
        flash('Estado de tarea actualizado exitosamente.', 'success')
        
    except ValueError:
        flash('Porcentaje de avance no válido.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar tarea: {str(e)}', 'danger')
    
    return redirect(url_for('obras.detalle', id=obra.id))


@obras_bp.route('/<int:id>/certificaciones')
@login_required
def historial_certificaciones(id):
    """Ver historial de certificaciones de una obra"""
    obra = Obra.query.get_or_404(id)
    certificaciones = obra.certificaciones.order_by(CertificacionAvance.fecha.desc()).all()
    
    return render_template('obras/certificaciones.html', 
                         obra=obra, 
                         certificaciones=certificaciones)


@obras_bp.route('/certificacion/<int:id>/desactivar', methods=['POST'])
@login_required
def desactivar_certificacion(id):
    """Desactivar una certificación (solo administradores)"""
    if current_user.rol != 'administrador':
        flash('Solo los administradores pueden desactivar certificaciones.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    certificacion = CertificacionAvance.query.get_or_404(id)
    obra = certificacion.obra
    
    try:
        # Desactivar certificación
        certificacion.activa = False
        
        # Restar el costo certificado del costo real
        obra.costo_real -= certificacion.costo_certificado
        
        # Recalcular progreso
        obra.calcular_progreso_automatico()
        
        db.session.commit()
        flash('Certificación desactivada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al desactivar certificación: {str(e)}', 'danger')
    
    return redirect(url_for('obras.historial_certificaciones', id=obra.id))


@obras_bp.route('/<int:obra_id>/etapas/<int:etapa_id>/eliminar', methods=['POST'])
@login_required
def eliminar_etapa(obra_id, etapa_id):
    """Eliminar una etapa de una obra (solo administradores y técnicos)"""
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para eliminar etapas.', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))
    
    # Verificar que la obra pertenece a la organización del usuario
    obra = Obra.query.filter_by(id=obra_id, organizacion_id=current_user.organizacion_id).first_or_404()
    etapa = EtapaObra.query.filter_by(id=etapa_id, obra_id=obra_id).first_or_404()
    
    try:
        # Obtener nombre de la etapa para el mensaje
        nombre_etapa = etapa.nombre
        
        # Eliminar la etapa (las tareas se eliminan automáticamente por cascade)
        db.session.delete(etapa)
        
        # Recalcular progreso de la obra
        obra.calcular_progreso_automatico()
        
        db.session.commit()
        flash(f'Etapa "{nombre_etapa}" eliminada exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar etapa: {str(e)}', 'danger')
    
    return redirect(url_for('obras.detalle', id=obra_id))
