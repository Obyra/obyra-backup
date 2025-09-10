from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import requests
from app import db
from models import Obra, EtapaObra, TareaEtapa, AsignacionObra, Usuario, CertificacionAvance, TareaResponsables, ObraMiembro, TareaMiembro, TareaAvance, TareaAdjunto
from etapas_predefinidas import obtener_etapas_disponibles, crear_etapas_para_obra
from tareas_predefinidas import TAREAS_POR_ETAPA
from geocoding import geocodificar_direccion, normalizar_direccion_argentina
from roles_construccion import obtener_roles_por_categoria, obtener_nombre_rol

obras_bp = Blueprint('obras', __name__)

# Helpers de permisos
def is_admin():
    """Verifica si el usuario actual es admin"""
    return getattr(current_user, "role", "") == "admin"

def is_pm_global():
    """Verifica si el usuario actual es admin o PM global"""
    return getattr(current_user, "role", "") in ("admin", "pm")

def can_manage_obra(obra):
    """Verifica si el usuario puede gestionar la obra (crear/editar/eliminar etapas y tareas)"""
    if is_admin():
        return True
    if is_pm_global():
        return True
    
    # Verificar si es miembro PM específico de esta obra
    miembro = ObraMiembro.query.filter_by(
        obra_id=obra.id, 
        user_id=current_user.id, 
        rol='pm'
    ).first()
    return miembro is not None

def can_log_avance(tarea):
    """Verifica si el usuario puede registrar avances en una tarea"""
    if is_admin():
        return True
    
    # PM puede registrar correcciones si es necesario
    if getattr(current_user, "role", "") == "pm":
        return True
    
    # Operario: debe ser responsable o estar asignado en tarea_miembros
    if tarea.responsable_id == current_user.id:
        return True
    
    # Verificar si está en tarea_miembros
    miembro = TareaMiembro.query.filter_by(
        tarea_id=tarea.id,
        user_id=current_user.id
    ).first()
    return miembro is not None

def es_miembro_obra(obra_id, user_id):
    """Verificar si el usuario es miembro de la obra (cualquier rol)"""
    # Admin/PM siempre tienen acceso
    if is_pm_global():
        return True
    
    from models import ObraMiembro
    # Verificar membresía directa en la obra
    miembro = db.session.query(ObraMiembro.id)\
        .filter_by(obra_id=obra_id, user_id=user_id).first()
    if miembro:
        return True
    
    # Para operarios, también verificar si tienen tareas asignadas en la obra
    tiene_tareas = (db.session.query(TareaMiembro.id)
                   .join(TareaEtapa, TareaMiembro.tarea_id == TareaEtapa.id)
                   .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
                   .filter(EtapaObra.obra_id == obra_id, 
                          TareaMiembro.user_id == user_id)
                   .first())
    return tiene_tareas is not None

def resumen_tarea(t):
    """Calcular métricas de una tarea a prueba de nulos"""
    plan = float(t.cantidad_planificada or 0)
    
    # Obtener suma de avances aprobados
    ejec = float(
        db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
        .filter(TareaAvance.tarea_id == t.id, TareaAvance.status == 'aprobado')
        .scalar() or 0
    )
    
    pct = (ejec/plan*100.0) if plan > 0 else 0.0
    restante = max(plan - ejec, 0.0)
    
    # Verificar si está atrasada
    from datetime import date
    atrasada = bool(t.fecha_fin_plan and date.today() > t.fecha_fin_plan and restante > 0)
    
    return {
        'plan': plan, 
        'ejec': ejec, 
        'pct': pct, 
        'restante': restante, 
        'atrasada': atrasada
    }

def D(x):
    """Helper para conversión segura a Decimal"""
    if x is None:
        return Decimal('0')
    return x if isinstance(x, Decimal) else Decimal(str(x))

def seed_tareas_para_etapa(nueva_etapa):
    """Función idempotente para crear tareas predefinidas en una etapa"""
    try:
        tareas = TAREAS_POR_ETAPA.get(nueva_etapa.nombre, [])
        tareas_creadas = 0
        
        for t in tareas:
            # Manejar formato string o diccionario
            if isinstance(t, str):
                # Formato string (antiguo)
                nombre_tarea = t
                descripcion_tarea = ""
                horas_tarea = 0
            elif isinstance(t, dict):
                # Formato diccionario (nuevo)
                nombre_tarea = t.get("nombre", "")
                descripcion_tarea = t.get("descripcion", "")
                horas_tarea = t.get("horas", 0)
            else:
                print(f"⚠️ Formato de tarea no reconocido: {t}")
                continue
                
            if not nombre_tarea:
                continue
            
            # Verificar si ya existe (idempotente)
            ya = TareaEtapa.query.filter_by(etapa_id=nueva_etapa.id, nombre=nombre_tarea).first()
            if ya:
                continue
                
            # Crear nueva tarea
            nueva_tarea = TareaEtapa(
                etapa_id=nueva_etapa.id,
                nombre=nombre_tarea,
                descripcion=descripcion_tarea,
                horas_estimadas=horas_tarea,
                estado="pendiente"
            )
            db.session.add(nueva_tarea)
            tareas_creadas += 1
            print(f"✅ Tarea creada: {nombre_tarea}")
        
        print(f"🎯 Total tareas creadas para {nueva_etapa.nombre}: {tareas_creadas}")
        db.session.commit()
        return tareas_creadas
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERROR en seed_tareas_para_etapa: {str(e)}")
        return 0

@obras_bp.route("/obras")
@login_required
def obras_root():
    """Redirect /obras to the map view"""
    return redirect(url_for("obras.lista"))

@obras_bp.route('/')
@login_required
def lista():
    # Operarios pueden acceder para ver sus obras asignadas
    if not current_user.puede_acceder_modulo('obras') and current_user.rol != 'operario':
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
    # Operarios pueden acceder si son miembros de la obra
    if not current_user.puede_acceder_modulo('obras') and current_user.rol != 'operario':
        flash('No tienes permisos para ver obras.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    # Para operarios, verificar membresía en la obra
    if current_user.rol == 'operario' and not es_miembro_obra(id, current_user.id):
        flash('No tienes permisos para ver esta obra.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    obra = Obra.query.get_or_404(id)
    etapas = obra.etapas.order_by(EtapaObra.orden).all()
    asignaciones = obra.asignaciones.filter_by(activo=True).all()
    usuarios_disponibles = Usuario.query.filter_by(activo=True, organizacion_id=current_user.organizacion_id).all()
    etapas_disponibles = obtener_etapas_disponibles()
    
    from tareas_predefinidas import TAREAS_POR_ETAPA
    
    return render_template('obras/detalle.html', 
                         obra=obra, 
                         etapas=etapas, 
                         asignaciones=asignaciones,
                         usuarios_disponibles=usuarios_disponibles,
                         etapas_disponibles=etapas_disponibles,
                         roles_por_categoria=obtener_roles_por_categoria(),
                         TAREAS_POR_ETAPA=TAREAS_POR_ETAPA,
                         can_manage=can_manage_obra(obra),
                         current_user_id=current_user.id)

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
                    
                # Verificar que no exista ya una etapa con el mismo nombre y orden
                existe = EtapaObra.query.filter_by(obra_id=obra.id, nombre=nombre).first()
                if existe:
                    print(f"⚠️ DEBUG: Etapa '{nombre}' ya existe en obra {obra.id}, saltando...")
                    continue
                
                print(f"✅ DEBUG: Creando etapa '{nombre}' en obra {obra.id}")
                
                nueva_etapa = EtapaObra(
                    obra_id=obra.id,
                    nombre=nombre,
                    descripcion=descripcion,
                    orden=orden,
                    estado='pendiente'
                )
                
                db.session.add(nueva_etapa)
                db.session.flush()  # Para obtener el ID de la etapa
                
                # Crear tareas predefinidas automáticamente usando la función seed
                seed_tareas_para_etapa(nueva_etapa)
                
                # Crear tareas adicionales del formulario si las hay
                tareas_adicionales = etapa_data.get('tareas', [])
                for tarea_data in tareas_adicionales:
                    nombre_tarea = tarea_data.get('nombre', '').strip()
                    if nombre_tarea:
                        nueva_tarea = TareaEtapa(
                            etapa_id=nueva_etapa.id,
                            nombre=nombre_tarea,
                            descripcion=f"Tarea personalizada para {nombre}",
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
        db.session.flush()  # Para obtener el ID de la etapa
        
        print(f"✅ DEBUG: Creando etapa '{nombre}' en obra {id}")
        
        # AUTO-CREAR TAREAS PREDEFINIDAS PARA LA ETAPA
        seed_tareas_para_etapa(nueva_etapa)
        
        db.session.commit()
        flash(f'Etapa "{nombre}" agregada exitosamente con tareas predefinidas.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERROR al crear etapa: {str(e)}")
        flash('Error al agregar la etapa.', 'danger')
    
    return redirect(url_for('obras.detalle', id=id))

@obras_bp.route("/tareas/crear", methods=['POST'])
@login_required
def crear_tareas():
    """Nuevo endpoint para crear una o múltiples tareas según especificación"""
    try:
        obra_id = request.form.get("obra_id", type=int)
        obra = Obra.query.get_or_404(obra_id)
        
        # Verificar permisos
        if not can_manage_obra(obra):
            return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403
        etapa_id = request.form.get("etapa_id", type=int)
        horas = request.form.get("horas_estimadas", type=float)
        resp_id = request.form.get("responsable_id", type=int) or None
        fi = parse_date(request.form.get("fecha_inicio_plan"))
        ff = parse_date(request.form.get("fecha_fin_plan"))

        sugeridas = request.form.getlist("sugeridas[]")  # Array de IDs numéricos

        # Validación básica
        if not etapa_id:
            return jsonify(ok=False, error="Falta el ID de etapa"), 400

        # Verificar que la etapa existe y pertenece al usuario
        etapa = EtapaObra.query.get_or_404(etapa_id)
        if etapa.obra.organizacion_id != current_user.organizacion_id:
            return jsonify(ok=False, error="Sin permisos"), 403

        # Caso simple: sin sugeridas
        if not sugeridas:
            nombre = request.form.get("nombre", "").strip()
            if not nombre:
                return jsonify(ok=False, error="Falta el nombre"), 400
            
            # Validate unit against whitelist
            VALID_UNITS = {'m2', 'ml', 'm3', 'un', 'h', 'kg'}
            unidad_input = request.form.get("unidad", "un").lower()
            unidad = unidad_input if unidad_input in VALID_UNITS else "un"
            
            t = TareaEtapa(
                etapa_id=etapa_id,
                nombre=nombre,
                responsable_id=resp_id,
                horas_estimadas=horas,
                fecha_inicio_plan=fi,
                fecha_fin_plan=ff,
                unidad=unidad
            )
            db.session.add(t)
            db.session.commit()
            return jsonify(ok=True, created=1)

        # Caso múltiple: con sugeridas  
        # Note: For suggested tasks, we let them keep their natural units from TAREAS_POR_ETAPA
        # Only custom tasks use the form's unit selection
        created = 0
        for sid in sugeridas:
            try:
                # sid es el índice en el array de tareas predefinidas
                index = int(sid)
                # Obtener tareas predefinidas para esta etapa
                nombre_etapa = etapa.nombre
                tareas_disponibles = TAREAS_POR_ETAPA.get(nombre_etapa, [])
                
                if index >= len(tareas_disponibles):
                    continue
                    
                tarea_data = tareas_disponibles[index]
                
                # Manejar formato string o diccionario
                if isinstance(tarea_data, str):
                    nombre_tarea = tarea_data
                    tarea_unidad = "un"  # Default for string format
                elif isinstance(tarea_data, dict):
                    nombre_tarea = tarea_data.get("nombre", "")
                    tarea_unidad = tarea_data.get("unidad", "un")  # Use task's natural unit
                else:
                    continue
                
                if not nombre_tarea:
                    continue
                
                t = TareaEtapa(
                    etapa_id=etapa_id,
                    nombre=nombre_tarea,
                    responsable_id=resp_id,
                    horas_estimadas=horas,
                    fecha_inicio_plan=fi,
                    fecha_fin_plan=ff,
                    unidad=tarea_unidad  # Use task's natural unit, not form unit
                )
                db.session.add(t)
                created += 1
                
            except (ValueError, IndexError):
                continue

        if created == 0:
            db.session.rollback()
            return jsonify(ok=False, error="No se pudo crear ninguna tarea"), 400

        db.session.commit()
        return jsonify(ok=True, created=created)

    except Exception as e:
        print(f"❌ Error en crear_tareas: {str(e)}")
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


def parse_date(s):
    """Función auxiliar para parsear fechas en múltiples formatos"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            pass
    return None


@obras_bp.route("/asignar-usuarios", methods=['POST'])
def asignar_usuarios():
    """Asignar usuarios a múltiples tareas - Always returns JSON"""
    try:
        from models import TareaMiembro, Usuario
        from flask import current_app
        
        # Check authentication first and return JSON error if not authenticated
        if not current_user.is_authenticated:
            return jsonify(ok=False, error="Usuario no autenticado"), 401
        
        # Parse form data
        try:
            tarea_ids = request.form.getlist('tarea_ids[]')
            user_ids = request.form.getlist('user_ids[]')
            cuota = request.form.get('cuota_objetivo', type=int)
            
            current_app.logger.info(f"asignar_usuarios user={current_user.id} tareas={tarea_ids} users={user_ids} cuota={cuota}")
            
        except Exception as e:
            current_app.logger.exception("Error parsing form data")
            return jsonify(ok=False, error=f"Error parsing request: {str(e)}"), 400
        
        # Validate inputs
        if not tarea_ids or not user_ids:
            return jsonify(ok=False, error='Faltan tareas o usuarios'), 400
        
        # Verificar permisos en la primera tarea
        primera_tarea = TareaEtapa.query.get(int(tarea_ids[0]))
        if not primera_tarea:
            return jsonify(ok=False, error="Tarea no encontrada"), 404
        
        obra = primera_tarea.etapa.obra
        if not can_manage_obra(obra):
            return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403
        
        # Verificar que todos los usuarios pertenecen a la misma organización
        for uid in user_ids:
            user = Usuario.query.get(int(uid))
            if not user or user.organizacion_id != current_user.organizacion_id:
                return jsonify(ok=False, error=f"Usuario {uid} no pertenece a la organización"), 403
        
        # Realizar upsert de asignaciones
        asignaciones_creadas = 0
        
        for tid in tarea_ids:
            tarea = TareaEtapa.query.get(int(tid))
            if not tarea or tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
                current_app.logger.warning(f"Skipping invalid task {tid}")
                continue
                
            for uid in set(user_ids):  # set() evita duplicados
                # Upsert: verificar si existe, crear si no
                existing = TareaMiembro.query.filter_by(tarea_id=int(tid), user_id=int(uid)).first()
                if not existing:
                    nueva_asignacion = TareaMiembro(
                        tarea_id=int(tid), 
                        user_id=int(uid), 
                        cuota_objetivo=cuota
                    )
                    db.session.add(nueva_asignacion)
                    asignaciones_creadas += 1
                    current_app.logger.info(f"Created assignment: task={tid}, user={uid}")
                else:
                    # Actualizar cuota si existe
                    existing.cuota_objetivo = cuota
                    current_app.logger.info(f"Updated assignment: task={tid}, user={uid}")
        
        db.session.commit()
        current_app.logger.info(f"asignar_usuarios success: created={asignaciones_creadas}")
        return jsonify(ok=True, creados=asignaciones_creadas)
        
    except Exception as e:
        # Catch-all for any unexpected errors to ensure JSON response
        try:
            db.session.rollback()
            from flask import current_app
            current_app.logger.exception('Unexpected error in asignar_usuarios')
        except:
            pass
        return jsonify(ok=False, error="Error interno del servidor"), 500


@obras_bp.route("/tareas/<int:tarea_id>/avances", methods=['POST'])
@login_required
def crear_avance(tarea_id):
    """Registrar avance con fotos"""
    from models import TareaMiembro, TareaAvance, TareaAdjunto
    from werkzeug.utils import secure_filename
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    
    # Verificar permisos para registrar avance
    if not can_log_avance(tarea):
        return jsonify(ok=False, error="Sin permisos para registrar avances en esta tarea"), 403
    
    from pathlib import Path
    
    cantidad = request.form.get("cantidad", type=float)
    if not cantidad or cantidad <= 0: 
        return jsonify(ok=False, error="Cantidad inválida"), 400
    
    unidad = tarea.unidad or 'un'  # Always use server-side unit, ignore client value
    horas = request.form.get("horas", type=float)  # Optional hours worked
    notas = request.form.get("notas")

    try:
        # Crear avance
        av = TareaAvance(
            tarea_id=tarea.id, 
            user_id=current_user.id, 
            cantidad=cantidad, 
            unidad=unidad, 
            horas=horas,
            notas=notas
        )
        
        # Regla barata: Operario necesita aprobación, PM/Admin auto-aprueban
        if getattr(current_user, 'role', None) in ("admin", "pm"):
            av.status = "aprobado"
            av.confirmed_by = current_user.id
            av.confirmed_at = datetime.utcnow()
        # else: status = "pendiente" (default)
        
        db.session.add(av)
        
        # Si es el primer avance APROBADO, marcar fecha de inicio real
        if not tarea.fecha_inicio_real and av.status == "aprobado": 
            tarea.fecha_inicio_real = datetime.utcnow()

        # Manejar fotos
        uploaded_files = request.files.getlist("fotos")
        for f in uploaded_files:
            if f.filename:
                fname = secure_filename(f.filename)
                base = Path(current_app.static_folder) / "uploads" / "obras" / str(tarea.etapa.obra_id) / "tareas" / str(tarea.id)
                base.mkdir(parents=True, exist_ok=True)
                file_path = base / fname
                f.save(file_path)
                
                # Crear registro de adjunto
                adjunto = TareaAdjunto(
                    tarea_id=tarea.id,
                    avance_id=av.id,
                    uploaded_by=current_user.id,
                    path=f"/static/uploads/obras/{tarea.etapa.obra_id}/tareas/{tarea.id}/{fname}"
                )
                db.session.add(adjunto)

        db.session.commit()
        return jsonify(ok=True)
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en crear_avance: {str(e)}")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route("/tareas/<int:tarea_id>/complete", methods=['POST'])
@login_required
def completar_tarea(tarea_id):
    """Completar tarea - solo admin si restante = 0"""
    from models import resumen_tarea
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra
    
    # Verificar permisos para completar tarea
    if not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403
    
    # Verificar que la tarea pertenezca a la organización
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403
    
    try:
        m = resumen_tarea(tarea)
        if m["restante"] > 0: 
            return jsonify(ok=False, error="Aún faltan cantidades"), 400
        
        tarea.estado = "completada"
        tarea.fecha_fin_real = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en completar_tarea: {str(e)}")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route('/mis-tareas')
@login_required  
def mis_tareas():
    """Página que lista las tareas asignadas al usuario actual (operarios)"""
    from flask import current_app
    
    q = (
        db.session.query(TareaEtapa)
        .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
        .join(EtapaObra, EtapaObra.id == TareaEtapa.etapa_id)
        .join(Obra, Obra.id == EtapaObra.obra_id)
        .filter(TareaMiembro.user_id == current_user.id)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
        .order_by(Obra.nombre, EtapaObra.orden, TareaEtapa.id.desc())
    )
    tareas = q.all()
    current_app.logger.info("mis_tareas user=%s unidades=%s",
                            current_user.id, [(t.id, t.unidad, t.rendimiento) for t in tareas])
    return render_template('obras/mis_tareas.html', tareas=tareas)


@obras_bp.route('/etapa/<int:id>/tarea', methods=['POST'])
@login_required
def agregar_tarea(id):
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para agregar tareas.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    etapa = EtapaObra.query.get_or_404(id)
    
    # Obtener datos comunes
    horas_estimadas = request.form.get('horas_estimadas')
    responsable_id = request.form.get('responsable_id')
    fecha_inicio_plan = request.form.get('fecha_inicio_plan')
    fecha_fin_plan = request.form.get('fecha_fin_plan')
    
    # Convertir fechas si están presentes
    fecha_inicio_plan_date = None
    fecha_fin_plan_date = None
    if fecha_inicio_plan:
        try:
            fecha_inicio_plan_date = datetime.strptime(fecha_inicio_plan, '%Y-%m-%d').date()
        except ValueError:
            pass
    if fecha_fin_plan:
        try:
            fecha_fin_plan_date = datetime.strptime(fecha_fin_plan, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    # Verificar si hay tareas sugeridas múltiples
    tareas_sugeridas = []
    form_keys = list(request.form.keys())
    for key in form_keys:
        if key.startswith('sugeridas[') and key.endswith('][nombre]'):
            index = key.split('[')[1].split(']')[0]
            nombre_sugerida = request.form.get(f'sugeridas[{index}][nombre]')
            descripcion_sugerida = request.form.get(f'sugeridas[{index}][descripcion]', '')
            if nombre_sugerida:
                tareas_sugeridas.append({
                    'nombre': nombre_sugerida,
                    'descripcion': descripcion_sugerida
                })
    
    # Si hay tareas sugeridas, crear múltiples tareas
    if tareas_sugeridas:
        tareas_creadas = 0
        try:
            for tarea_data in tareas_sugeridas:
                nueva_tarea = TareaEtapa(
                    etapa_id=id,
                    nombre=tarea_data['nombre'],
                    descripcion=tarea_data['descripcion'],
                    horas_estimadas=float(horas_estimadas) if horas_estimadas else None,
                    responsable_id=int(responsable_id) if responsable_id else None,
                    fecha_inicio_plan=fecha_inicio_plan_date,
                    fecha_fin_plan=fecha_fin_plan_date
                )
                db.session.add(nueva_tarea)
                tareas_creadas += 1
            
            db.session.commit()
            return jsonify({'ok': True, 'created': tareas_creadas})
        except Exception as e:
            db.session.rollback()
            return jsonify({'ok': False, 'error': 'Error al crear las tareas múltiples'})
    
    # Si no hay tareas sugeridas, crear una tarea individual
    else:
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        
        if not nombre:
            flash('El nombre de la tarea es obligatorio.', 'danger')
            return redirect(url_for('obras.detalle', id=etapa.obra_id))
        
        nueva_tarea = TareaEtapa(
            etapa_id=id,
            nombre=nombre,
            descripcion=descripcion,
            horas_estimadas=float(horas_estimadas) if horas_estimadas else None,
            responsable_id=int(responsable_id) if responsable_id else None,
            fecha_inicio_plan=fecha_inicio_plan_date,
            fecha_fin_plan=fecha_fin_plan_date
        )
        
        try:
            db.session.add(nueva_tarea)
            db.session.commit()
            flash(f'Tarea "{nombre}" agregada exitosamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Error al agregar la tarea.', 'danger')
        
        return redirect(url_for('obras.detalle', id=etapa.obra_id))


@obras_bp.route('/admin/backfill_tareas', methods=['POST'])
@login_required
def admin_backfill_tareas():
    """Función de backfill para crear tareas faltantes en etapas existentes"""
    # Solo super administradores
    if current_user.email not in ['brenda@gmail.com', 'admin@obyra.com']:
        flash('No tienes permisos para ejecutar el backfill.', 'danger')
        return redirect(url_for('obras.lista'))
    
    try:
        print("🚀 Iniciando backfill de tareas predefinidas...")
        etapas_procesadas = 0
        tareas_creadas_total = 0
        
        # Recorrer todas las etapas existentes
        etapas = EtapaObra.query.all()
        
        for etapa in etapas:
            print(f"📋 Procesando etapa: {etapa.nombre} (ID: {etapa.id})")
            
            # Contar tareas existentes
            tareas_existentes = TareaEtapa.query.filter_by(etapa_id=etapa.id).count()
            print(f"   Tareas existentes: {tareas_existentes}")
            
            # Si tiene menos de 5 tareas, ejecutar seed
            if tareas_existentes < 5:
                print(f"   🔧 Ejecutando seed para {etapa.nombre}...")
                tareas_nuevas = seed_tareas_para_etapa(etapa)
                tareas_creadas_total += tareas_nuevas
                etapas_procesadas += 1
            else:
                print(f"   ✅ Etapa {etapa.nombre} ya tiene suficientes tareas")
        
        db.session.commit()
        
        flash(f'Backfill completado: {etapas_procesadas} etapas procesadas, {tareas_creadas_total} tareas creadas.', 'success')
        print(f"🎯 BACKFILL COMPLETADO: {etapas_procesadas} etapas, {tareas_creadas_total} tareas")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERROR en backfill: {str(e)}")
        flash(f'Error en backfill: {str(e)}', 'danger')
    
    return redirect(url_for('obras.lista'))

@obras_bp.route('/etapas/<int:etapa_id>/tareas')
@login_required
def api_listar_tareas(etapa_id):
    """API para listar tareas de una etapa con filtrado por rol"""
    etapa = EtapaObra.query.get_or_404(etapa_id)
    
    # Verificar que la etapa pertenezca a la organización del usuario
    if etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    
    # Filtrar tareas según rol del usuario
    if is_pm_global():
        # Admin/PM ven todas las tareas de la etapa
        q = (TareaEtapa.query
             .filter(TareaEtapa.etapa_id == etapa_id)
             .options(db.joinedload(TareaEtapa.miembros).joinedload(TareaMiembro.usuario)))
    else:
        # Operarios solo ven tareas donde están asignados
        if not es_miembro_obra(etapa.obra_id, current_user.id):
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
        
        # JOIN con tarea_miembros para filtrar solo las asignadas
        q = (TareaEtapa.query
             .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
             .filter(TareaEtapa.etapa_id == etapa_id,
                     TareaMiembro.user_id == current_user.id)
             .options(db.joinedload(TareaEtapa.miembros).joinedload(TareaMiembro.usuario)))
    
    tareas = q.order_by(TareaEtapa.id.asc()).all()
    
    # Renderizar template parcial (las métricas se calculan automáticamente via property)
    html = render_template('obras/_tareas_lista.html', tareas=tareas)
    return jsonify({'ok': True, 'html': html})

@obras_bp.route('/tareas/eliminar/<int:tarea_id>', methods=['POST'])
@login_required
def eliminar_tarea(tarea_id):
    """Eliminar una tarea específica"""
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra
    
    if not can_manage_obra(obra):
        return jsonify({'success': False, 'error': 'Sin permisos para gestionar esta obra'}), 403
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    
    # Verificar que la tarea pertenezca a la organización del usuario
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403
    
    try:
        obra = tarea.etapa.obra
        db.session.delete(tarea)
        
        # Recalcular progreso automático de la obra
        obra.calcular_progreso_automatico()
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@obras_bp.route('/tareas/bulk_delete', methods=['POST'])
@login_required
def tareas_bulk_delete():
    """Eliminar múltiples tareas en lote"""
    data = request.get_json()
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'error': 'No se proporcionaron IDs', 'ok': False}), 400
    
    # Verificar permisos en la primera tarea
    primera_tarea = TareaEtapa.query.get(ids[0])
    if not primera_tarea:
        return jsonify({'error': 'Tarea no encontrada', 'ok': False}), 404
    
    obra = primera_tarea.etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'error': 'Sin permisos para gestionar esta obra', 'ok': False}), 403
    
    data = request.get_json() or {}
    ids = data.get("ids") or []
    
    if not ids:
        return jsonify({'error': 'IDs requeridos', 'ok': False}), 400

    try:
        # Convertir IDs a enteros para evitar problemas de tipo
        task_ids = []
        for task_id in ids:
            try:
                task_ids.append(int(task_id))
            except (ValueError, TypeError):
                continue
                
        if not task_ids:
            return jsonify({'error': 'IDs inválidos', 'ok': False}), 400
        
        # Obtener tareas y verificar permisos
        tareas = TareaEtapa.query.filter(TareaEtapa.id.in_(task_ids)).all()
        
        if not tareas:
            return jsonify({'error': 'No se encontraron tareas', 'ok': False}), 404
        
        # Verificar que todas las tareas pertenezcan a la organización del usuario
        obras_a_actualizar = set()
        for tarea in tareas:
            try:
                if tarea.etapa and tarea.etapa.obra and tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
                    return jsonify({'error': 'Sin permisos para algunas tareas', 'ok': False}), 403
                if tarea.etapa and tarea.etapa.obra:
                    obras_a_actualizar.add(tarea.etapa.obra)
            except AttributeError as e:
                print(f"⚠️ Error accediendo a relaciones de tarea {tarea.id}: {str(e)}")
                continue
        
        # Eliminar tareas
        deleted = 0
        for tarea in tareas:
            try:
                db.session.delete(tarea)
                deleted += 1
            except Exception as e:
                print(f"⚠️ Error eliminando tarea {tarea.id}: {str(e)}")
                continue
        
        # Recalcular progreso para todas las obras afectadas
        for obra in obras_a_actualizar:
            try:
                obra.calcular_progreso_automatico()
            except Exception as e:
                print(f"⚠️ Error recalculando progreso para obra {obra.id}: {str(e)}")
                continue
        
        db.session.commit()
        print(f"✅ Eliminadas {deleted} tareas exitosamente")
        return jsonify({'ok': True, 'deleted': deleted})
        
    except Exception as e:
        print(f"❌ Error en tareas_bulk_delete: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor', 'ok': False}), 500

@obras_bp.route('/etapas/bulk_delete', methods=['POST'])
@login_required
def etapas_bulk_delete():
    """Eliminar múltiples etapas en lote"""
    data = request.get_json()
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'error': 'No se proporcionaron IDs', 'ok': False}), 400
    
    # Verificar permisos en la primera etapa
    primera_etapa = EtapaObra.query.get(ids[0])
    if not primera_etapa:
        return jsonify({'error': 'Etapa no encontrada', 'ok': False}), 404
    
    obra = primera_etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'error': 'Sin permisos para gestionar esta obra', 'ok': False}), 403
    
    data = request.get_json() or {}
    ids = data.get("ids") or []
    
    if not ids:
        return jsonify({'error': 'IDs requeridos', 'ok': False}), 400

    try:
        # Obtener etapas y verificar permisos
        etapas = EtapaObra.query.filter(EtapaObra.id.in_(ids)).all()
        
        # Verificar que todas las etapas pertenezcan a la organización del usuario
        obras_a_actualizar = set()
        for etapa in etapas:
            if etapa.obra.organizacion_id != current_user.organizacion_id:
                return jsonify({'error': 'Sin permisos para algunas etapas', 'ok': False}), 403
            obras_a_actualizar.add(etapa.obra)
        
        # Eliminar etapas (y sus tareas en cascada)
        deleted = 0
        for etapa in etapas:
            db.session.delete(etapa)
            deleted += 1
        
        # Recalcular progreso para todas las obras afectadas
        for obra in obras_a_actualizar:
            obra.calcular_progreso_automatico()
        
        db.session.commit()
        return jsonify({'ok': True, 'deleted': deleted})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e), 'ok': False}), 500

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
    
    # Verificar permisos: admin, técnico, responsable titular o usuario asignado
    is_admin = getattr(current_user, 'is_admin', False) or current_user.rol in ['administrador', 'tecnico']
    is_responsible = tarea.responsable_id == current_user.id
    
    # Verificar si el usuario está asignado a esta tarea
    asignado = db.session.query(TareaResponsables.id)\
        .filter_by(tarea_id=tarea.id, user_id=current_user.id).first()
    
    if not (is_admin or is_responsible or asignado):
        flash('No tienes permisos para actualizar esta tarea.', 'danger')
        return redirect(url_for('obras.detalle', id=obra.id))
    
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


@obras_bp.route('/tareas/<int:tarea_id>/asignar', methods=['POST'])
@login_required
def tarea_asignar(tarea_id):
    """Asignar múltiples usuarios a una tarea"""
    if current_user.rol not in ['administrador', 'tecnico']:
        return jsonify(ok=False, error="Sin permiso"), 403
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    
    # Verificar que la tarea pertenezca a la organización del usuario
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403

    data = request.get_json(force=True) or {}
    user_ids = list({int(x) for x in data.get("user_ids", [])})

    try:
        # Limpiar asignaciones existentes y volver a grabar
        TareaResponsables.query.filter_by(tarea_id=tarea.id).delete()
        
        # Crear nuevas asignaciones
        for uid in user_ids:
            # Verificar que el usuario exista y pertenezca a la misma organización
            usuario = Usuario.query.filter_by(id=uid, organizacion_id=current_user.organizacion_id).first()
            if usuario:
                asignacion = TareaResponsables(tarea_id=tarea.id, user_id=uid)
                db.session.add(asignacion)

        db.session.commit()
        return jsonify(ok=True, count=len(user_ids))
        
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


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

@obras_bp.route('/etapa/<int:etapa_id>/cambiar_estado', methods=['POST'])
@login_required
def cambiar_estado_etapa(etapa_id):
    """Cambiar estado de una etapa"""
    if current_user.rol not in ['administrador', 'tecnico']:
        flash('No tienes permisos para cambiar el estado de etapas.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    etapa = EtapaObra.query.get_or_404(etapa_id)
    nuevo_estado = request.form.get('estado')
    
    estados_validos = ['pendiente', 'en_curso', 'pausada', 'finalizada']
    if nuevo_estado not in estados_validos:
        flash('Estado no válido.', 'danger')
        return redirect(url_for('obras.detalle', id=etapa.obra_id))
    
    try:
        estado_anterior = etapa.estado
        etapa.estado = nuevo_estado
        
        # Si se marca como finalizada, completar todas las tareas pendientes
        if nuevo_estado == 'finalizada':
            for tarea in etapa.tareas.filter_by(estado='pendiente'):
                tarea.estado = 'completada'
        
        # Recalcular progreso de la obra
        etapa.obra.calcular_progreso_automatico()
        
        db.session.commit()
        flash(f'Estado de etapa "{etapa.nombre}" cambiado de "{estado_anterior}" a "{nuevo_estado}".', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar estado: {str(e)}', 'danger')
    
    return redirect(url_for('obras.detalle', id=etapa.obra_id))

# Función duplicada eliminada - usando admin_backfill_tareas arriba


# ===== ENDPOINTS PARA SISTEMA DE APROBACIONES =====

@obras_bp.route("/avances/<int:avance_id>/aprobar", methods=['POST'])
@login_required
def aprobar_avance(avance_id):
    """Aprobar un avance pendiente (solo PM/Admin)"""
    from utils.permissions import can_approve_avance
    
    av = TareaAvance.query.get_or_404(avance_id)
    
    if not can_approve_avance(current_user, av):
        return jsonify(ok=False, error="Sin permiso"), 403
    
    if av.status == "aprobado":
        return jsonify(ok=True)  # idempotente

    try:
        av.status = "aprobado"
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()

        # Si es el primer aprobado de la tarea → fecha inicio real
        t = TareaEtapa.query.get(av.tarea_id)
        if t and not t.fecha_inicio_real:
            t.fecha_inicio_real = datetime.utcnow()

        db.session.commit()
        return jsonify(ok=True)
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en aprobar_avance: {str(e)}")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route("/avances/<int:avance_id>/rechazar", methods=['POST'])
@login_required
def rechazar_avance(avance_id):
    """Rechazar un avance pendiente (solo PM/Admin)"""
    from utils.permissions import can_approve_avance
    
    av = TareaAvance.query.get_or_404(avance_id)
    
    if not can_approve_avance(current_user, av):
        return jsonify(ok=False, error="Sin permiso"), 403

    try:
        av.status = "rechazado"
        av.reject_reason = request.form.get("motivo")  # opcional
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()
        
        db.session.commit()
        return jsonify(ok=True)
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en rechazar_avance: {str(e)}")
        return jsonify(ok=False, error="Error interno"), 500
