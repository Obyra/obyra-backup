from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import requests
from app import db
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from models import Obra, EtapaObra, TareaEtapa, AsignacionObra, Usuario, CertificacionAvance, TareaResponsables, ObraMiembro, TareaMiembro, TareaAvance, TareaAdjunto, TareaAvanceFoto
from etapas_predefinidas import obtener_etapas_disponibles, crear_etapas_para_obra
from tareas_predefinidas import TAREAS_POR_ETAPA
from geocoding import geocodificar_direccion, normalizar_direccion_argentina
from roles_construccion import obtener_roles_por_categoria, obtener_nombre_rol

obras_bp = Blueprint('obras', __name__)

# Error handlers for AJAX requests to return JSON instead of HTML
@obras_bp.errorhandler(404)
def handle_404(error):
    # Always return JSON for API routes
    if request.path.startswith("/obras/api/"):
        return jsonify({"ok": False, "error": "Not found"}), 404
    # Check if this is an AJAX request (common indicators)
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'ok': False, 'error': 'Recurso no encontrado'}), 404
    # For regular web requests, let Flask handle it normally
    raise error

@obras_bp.errorhandler(500)  
def handle_500(error):
    # Always return JSON for API routes
    if request.path.startswith("/obras/api/"):
        return jsonify({"ok": False, "error": "Internal server error"}), 500
    # Check if this is an AJAX request
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500
    # For regular web requests, let Flask handle it normally
    raise error

@obras_bp.errorhandler(401)
def handle_401(error):
    # Always return JSON for API routes
    if request.path.startswith("/obras/api/"):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 401
    # For regular web requests, let Flask handle it normally  
    raise error


@obras_bp.errorhandler(403)
def handle_403(error):
    # Always return JSON for API routes
    if request.path.startswith("/obras/api/"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    # For regular web requests, let Flask handle it normally  
    raise error

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
        usuario_id=current_user.id, 
        rol_en_obra='pm'
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
        .filter_by(obra_id=obra_id, usuario_id=user_id).first()
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

def seed_tareas_para_etapa(nueva_etapa, auto_commit=True):
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
        if auto_commit:
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
    
    # Load assigned members as specified by user
    miembros = (ObraMiembro.query
                .filter_by(obra_id=obra.id)
                .join(Usuario, ObraMiembro.usuario_id == Usuario.id)
                .order_by(Usuario.nombre.asc())
                .all())
    
    # Also load responsables for dropdown (members of this obra) 
    responsables_query = (ObraMiembro.query
                         .filter_by(obra_id=obra.id)
                         .join(Usuario)
                         .all())
    
    # Convert to JSON-serializable format for wizard
    responsables = [
        {
            'usuario': {
                'id': r.usuario.id,
                'nombre_completo': r.usuario.nombre_completo,
                'rol': r.usuario.rol
            },
            'rol_en_obra': r.rol_en_obra
        }
        for r in responsables_query
    ]
    
    from tareas_predefinidas import TAREAS_POR_ETAPA
    
    return render_template('obras/detalle.html', 
                         obra=obra, 
                         etapas=etapas, 
                         asignaciones=asignaciones,
                         usuarios_disponibles=usuarios_disponibles,
                         miembros=miembros,
                         responsables=responsables_query,  # For template dropdown
                         responsables_json=responsables,   # For wizard JavaScript
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


@obras_bp.route('/<int:obra_id>/asignar_usuario', methods=['POST'])
@login_required
def asignar_usuario(obra_id):
    """HOTFIX: Asignar usuarios a obra - Traditional form submission + AJAX support"""
    from flask import flash, redirect, url_for
    
    if current_user.rol != 'administrador':
        flash('Solo administradores pueden asignar usuarios', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    # Detect if this is an AJAX request
    is_ajax = request.headers.get('Content-Type') == 'application/json' or 'XMLHttpRequest' in str(request.headers.get('X-Requested-With', ''))

    try:
        # HOTFIX: Support both formats as specified
        user_ids = request.form.getlist('user_ids[]')
        if not user_ids:
            uid = request.form.get('usuario_id')
            if uid:
                user_ids = [uid]
        
        if not user_ids:
            if is_ajax:
                return jsonify({"ok": False, "error": "Seleccioná al menos un usuario"}), 400
            else:
                flash('Seleccioná al menos un usuario', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))

        # Validar que los usuarios existen
        usuarios = Usuario.query.filter(Usuario.id.in_(user_ids)).all()
        if not usuarios:
            if is_ajax:
                return jsonify({"ok": False, "error": "Usuarios inválidos"}), 400
            else:
                flash('Usuarios inválidos', 'danger')
                return redirect(url_for('obras.detalle', id=obra_id))

        # Obtener campos opcionales  
        rol_en_obra = request.form.get('rol') or 'operario'  # Default role
        etapa_id = request.form.get('etapa_id') or None
        
        # Insertar evitando duplicados usando raw SQL con usuario_id
        creados = 0
        ya_existian = 0
        for uid in user_ids:
            try:
                result = db.session.execute(
                    text("""
                    INSERT INTO obra_miembros (obra_id, usuario_id, rol_en_obra, etapa_id)
                    VALUES (:o, :u, :rol, :etapa)
                    ON CONFLICT (obra_id, usuario_id) DO NOTHING
                    """), {"o": obra_id, "u": int(uid), "rol": rol_en_obra, "etapa": etapa_id}
                )
                # Check if row was inserted by checking rowcount
                if result.rowcount == 0:
                    ya_existian += 1
                else:
                    creados += 1
            except Exception as e:
                current_app.logger.exception(f"Error inserting user {uid}")
                db.session.rollback()
                if is_ajax:
                    return jsonify({"ok": False, "error": "Error asignando usuario"}), 500
                else:
                    flash('Error asignando usuario', 'danger')
                    return redirect(url_for('obras.detalle', id=obra_id))
                    
        db.session.commit()
        
        # HOTFIX: Different responses for AJAX vs traditional
        if is_ajax:
            return jsonify({"ok": True, "creados": creados, "ya_existian": ya_existian})
        else:
            if creados > 0:
                flash(f'✅ Se asignaron {creados} usuarios a la obra', 'success')
            if ya_existian > 0:
                flash(f'ℹ️ {ya_existian} usuarios ya estaban asignados', 'info')
            return redirect(url_for('obras.detalle', id=obra_id))
        
    except Exception as e:
        from sqlalchemy.exc import ProgrammingError
        current_app.logger.exception("obra_miembros insert error obra_id=%s", obra_id)
        db.session.rollback()
        
        if is_ajax:
            if isinstance(e, ProgrammingError):
                return jsonify({"ok": False, "error": "Error de esquema de base de datos"}), 500
            return jsonify({"ok": False, "error": f"Error interno: {str(e)}"}), 500
        else:
            flash(f'Error al asignar usuarios: {str(e)}', 'danger')
            return redirect(url_for('obras.detalle', id=obra_id))

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


# === PERCENTAGE CALCULATION FUNCTIONS ===

def suma_ejecutado(tarea_id):
    """Calculate total executed quantity for a task"""
    from sqlalchemy import func
    from models import TareaAvance
    total = db.session.query(func.coalesce(func.sum(TareaAvance.cantidad_ingresada), 0)).filter_by(tarea_id=tarea_id).scalar()
    return float(total or 0)

def recalc_tarea_pct(tarea_id):
    """Recalculate and update task percentage"""
    from models import TareaEtapa
    tarea = TareaEtapa.query.get(tarea_id)
    if not tarea:
        return 0
    
    meta = float(tarea.cantidad_planificada or 0)
    if meta <= 0:
        tarea.porcentaje_avance = 0
    else:
        ejecutado = suma_ejecutado(tarea_id)
        tarea.porcentaje_avance = min(100, round((ejecutado / meta) * 100, 2))
    
    db.session.commit()
    return float(tarea.porcentaje_avance or 0)

def pct_etapa(etapa):
    """Calculate stage percentage (weighted average by cantidad_planificada)"""
    tareas = etapa.tareas.all() if hasattr(etapa.tareas, 'all') else etapa.tareas
    if not tareas:
        return 0
    
    total_meta = sum((float(t.cantidad_planificada or 0) for t in tareas))
    if total_meta <= 0:
        # Simple average if no quantities defined
        return round(sum((float(t.porcentaje_avance or 0) for t in tareas)) / max(len(tareas), 1), 2)
    
    weighted_sum = sum((float(t.cantidad_planificada or 0) * float(t.porcentaje_avance or 0) / 100 for t in tareas))
    return round((weighted_sum / total_meta) * 100, 2)

def pct_obra(obra):
    """Calculate project percentage (weighted average across stages)"""
    etapas = obra.etapas.all() if hasattr(obra.etapas, 'all') else obra.etapas
    if not etapas:
        return 0
    
    total_meta = 0
    total_ejecutado = 0
    
    for etapa in etapas:
        etapa_meta = sum((float(t.cantidad_planificada or 0) for t in etapa.tareas))
        etapa_pct = pct_etapa(etapa)
        total_meta += etapa_meta
        total_ejecutado += etapa_meta * (etapa_pct / 100)
    
    if total_meta > 0:
        return round((total_ejecutado / total_meta) * 100, 2)
    else:
        # Simple average if no quantities defined
        etapa_pcts = [pct_etapa(e) for e in etapas]
        return round(sum(etapa_pcts) / max(len(etapa_pcts), 1), 2)

# Unit normalization mapping
UNIT_MAP = {
    "m2": "m2", "m²": "m2", "M2": "m2", "metro2": "m2",
    "m3": "m3", "m³": "m3", "M3": "m3", "metro3": "m3", 
    "ml": "ml", "m": "ml", "metro": "ml",
    "u": "un", "un": "un", "unidad": "un", "uni": "un", "unidades": "un",
    "kg": "kg", "kilo": "kg", "kilos": "kg",
    "h": "h", "hr": "h", "hora": "h", "horas": "h", "hs": "h",
    "lt": "lt", "l": "lt", "lts": "lt", "litro": "lt", "litros": "lt"
}

def normalize_unit(unit):
    """Normalize unit to standard form - defensive against None/empty values"""
    if not unit or not str(unit).strip():
        return "un"  # safe default
    unit_clean = str(unit).strip().lower()
    return UNIT_MAP.get(unit_clean, unit_clean)

@obras_bp.route("/tareas/<int:tarea_id>/avances", methods=['POST'])
@login_required
def crear_avance(tarea_id):
    """Registrar avance con fotos - Operarios solo desde su dashboard"""
    from models import TareaMiembro, TareaAvance, TareaAdjunto
    from werkzeug.utils import secure_filename
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    
    # Role validation: Only operarios and admins/PMs can register progress
    user_role = getattr(current_user, "role", "")
    if user_role not in ["admin", "pm", "operario"]:
        return jsonify(ok=False, error="Solo operarios pueden registrar avances"), 403
    
    # Operarios must be assigned to the task
    if user_role == "operario":
        is_responsible = tarea.responsable_id == current_user.id
        is_assigned = TareaMiembro.query.filter_by(tarea_id=tarea.id, user_id=current_user.id).first()
        if not (is_responsible or is_assigned):
            return jsonify(ok=False, error="No estás asignado a esta tarea"), 403
    
    # Additional permission check
    if not can_log_avance(tarea):
        return jsonify(ok=False, error="Sin permisos para registrar avances en esta tarea"), 403
    
    from pathlib import Path
    
    # Parse quantity
    cantidad_str = str(request.form.get("cantidad", "")).replace(",", ".")
    try:
        cantidad = float(cantidad_str)
        if cantidad <= 0:
            return jsonify(ok=False, error="La cantidad debe ser mayor a 0"), 400
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Cantidad inválida"), 400
    
    # Always use task's unit (ignore client input for security)
    unidad = normalize_unit(tarea.unidad)  # normalize_unit already handles None safely
    horas = request.form.get("horas", type=float)  # Optional hours worked
    notas = request.form.get("notas", "")

    try:
        # Crear avance (always using task's normalized unit)
        av = TareaAvance(
            tarea_id=tarea.id, 
            user_id=current_user.id, 
            cantidad=cantidad,       
            unidad=unidad,          # Always task's normalized unit
            horas=horas,
            notas=notas,
            cantidad_ingresada=cantidad,    # Audit: cantidad original 
            unidad_ingresada=unidad        # Audit: task's unit (not client input)
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


# NEW API ENDPOINT - Specification Compliant Version with Photos
@obras_bp.route("/api/tareas/<int:tarea_id>/avances", methods=['POST'])
@login_required
def api_crear_avance_fotos(tarea_id):
    """Create progress entry with multiple photos - specification compliant"""
    from werkzeug.utils import secure_filename
    from pathlib import Path
    import uuid
    import os
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    
    # Authorization check - admin or assigned operario
    if not can_log_avance(tarea):
        return jsonify(ok=False, error="Sin permisos para registrar avance en esta tarea"), 403
    
    # Operarios MUST register from dashboard with X-From-Dashboard header
    if current_user.rol == 'operario':
        from_dashboard = request.headers.get('X-From-Dashboard') == '1'
        if not from_dashboard:
            return jsonify(ok=False, error="Los operarios solo pueden registrar avances desde su dashboard"), 403
    
    # Organization validation
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403
    
    # Parse and validate input - server ignores unit, always uses task's unit
    cantidad_str = str(request.form.get("cantidad_ingresada", "")).replace(",", ".")
    try:
        cantidad = float(cantidad_str)
        if cantidad <= 0:
            return jsonify(ok=False, error="La cantidad debe ser mayor a 0"), 400
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Cantidad inválida"), 400
    
    # Server always uses task's normalized unit (ignores client input completely)
    unidad_servidor = normalize_unit(tarea.unidad)
    horas_trabajadas = request.form.get("horas_trabajadas", type=float)
    notas = request.form.get("nota", "")

    try:
        # Create progress record
        avance = TareaAvance(
            tarea_id=tarea.id, 
            user_id=current_user.id, 
            cantidad=cantidad,       
            unidad=unidad_servidor,          # Always task's normalized unit
            horas=horas_trabajadas,
            notas=notas,
            cantidad_ingresada=cantidad,     # Audit field
            unidad_ingresada=unidad_servidor, # Server's unit (not client input)
            horas_trabajadas=horas_trabajadas
        )
        
        # Auto-approve for admin/PM, operarios need approval
        if current_user.rol in ['administrador', 'tecnico']:
            avance.status = "aprobado"
            avance.confirmed_by = current_user.id
            avance.confirmed_at = datetime.utcnow()
        # else: status = "pendiente" (default)
        
        db.session.add(avance)
        db.session.flush()  # Get avance.id for photos
        
        # Mark task start if first approved progress
        if not tarea.fecha_inicio_real and avance.status == "aprobado": 
            tarea.fecha_inicio_real = datetime.utcnow()

        # Handle multiple photo uploads using new TareaAvanceFoto model
        media_base = Path(current_app.instance_path) / "media"
        media_base.mkdir(exist_ok=True)
        
        uploaded_files = request.files.getlist("fotos")
        for foto_file in uploaded_files:
            if foto_file.filename:
                # Generate unique filename
                extension = Path(foto_file.filename).suffix.lower()
                unique_name = f"{uuid.uuid4()}{extension}"
                
                # Create directory structure: media/avances/{avance_id}/
                avance_dir = media_base / "avances" / str(avance.id)
                avance_dir.mkdir(parents=True, exist_ok=True)
                
                # Save file
                file_path = avance_dir / unique_name
                foto_file.save(file_path)
                
                # Get image dimensions if possible
                width, height = None, None
                try:
                    from PIL import Image
                    with Image.open(file_path) as img:
                        width, height = img.size
                except Exception:
                    pass  # Skip if can't get dimensions
                
                # Create photo record with relative path for database
                relative_path = f"avances/{avance.id}/{unique_name}"
                foto = TareaAvanceFoto(
                    avance_id=avance.id,
                    file_path=relative_path,
                    mime_type=foto_file.content_type,
                    width=width,
                    height=height
                )
                db.session.add(foto)

        db.session.commit()
        
        # Recalculate task percentage after saving progress
        recalc_tarea_pct(tarea.id)
        
        return jsonify(ok=True, avance_id=avance.id, porcentaje_actualizado=tarea.porcentaje_avance)
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error creating progress with photos: {str(e)}")
        return jsonify(ok=False, error="Error interno del servidor"), 500


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


@obras_bp.route('/api/tareas/<int:tarea_id>/avances-pendientes')
@login_required
def obtener_avances_pendientes(tarea_id):
    """API endpoint para obtener avances pendientes de una tarea con fotos"""
    from utils.permissions import is_admin_or_pm
    
    # Solo admin/PM pueden ver avances pendientes
    if not is_admin_or_pm(current_user):
        return jsonify(ok=False, error="Sin permisos"), 403
    
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    
    # Verificar permisos de organización
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403
    
    try:
        # Obtener avances pendientes con fotos
        avances_pendientes = (
            TareaAvance.query
            .filter_by(tarea_id=tarea_id, status='pendiente')
            .order_by(TareaAvance.created_at.desc())
            .all()
        )
        
        avances_data = []
        for avance in avances_pendientes:
            # Obtener fotos del avance
            fotos = []
            for foto in avance.fotos:
                fotos.append({
                    'id': foto.id,
                    'url': f"/media/{foto.file_path}",  # URL autenticada
                    'thumbnail_url': f"/media/{foto.file_path}",  # Podríamos crear thumbnails después
                    'width': foto.width,
                    'height': foto.height,
                    'mime_type': foto.mime_type
                })
            
            avances_data.append({
                'id': avance.id,
                'cantidad': float(avance.cantidad),
                'unidad': avance.unidad,
                'horas': float(avance.horas or 0),
                'notas': avance.notas or '',
                'fecha': avance.created_at.strftime('%d/%m/%Y %H:%M'),
                'operario': {
                    'id': avance.usuario.id,
                    'nombre': avance.usuario.nombre_completo
                },
                'fotos': fotos,
                'fotos_count': len(fotos)
            })
        
        return jsonify({
            'ok': True,
            'tarea': {
                'id': tarea.id,
                'nombre': tarea.nombre,
                'unidad': tarea.unidad
            },
            'avances': avances_data,
            'total': len(avances_data)
        })
        
    except Exception as e:
        print(f"❌ Error al obtener avances pendientes: {str(e)}")
        return jsonify(ok=False, error="Error interno"), 500


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
    
    try:
        tareas = q.order_by(TareaEtapa.id.asc()).all()
        
        # Renderizar template parcial (las métricas se calculan automáticamente via property)
        html = render_template('obras/_tareas_lista.html', tareas=tareas)
        return jsonify({'ok': True, 'html': html})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error al cargar tareas: {str(e)}'}), 500


@obras_bp.route('/api/tareas/<int:tarea_id>/curva-s')
@login_required
def api_curva_s_tarea(tarea_id):
    """API para obtener datos de curva S (PV/EV/AC) de una tarea"""
    from evm_utils import curva_s_tarea
    from datetime import datetime
    
    # Obtener la tarea y verificar permisos
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    
    # Verificar que la tarea pertenezca a la organización del usuario
    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    
    # Para operarios, verificar que esté asignado a la tarea
    if current_user.rol == 'operario':
        es_miembro = TareaMiembro.query.filter_by(
            tarea_id=tarea_id, 
            user_id=current_user.id
        ).first()
        if not es_miembro:
            return jsonify({'ok': False, 'error': 'Sin permisos para esta tarea'}), 403
    
    # Obtener parámetros de fecha opcionales
    desde_str = request.args.get('desde')  # YYYY-MM-DD
    hasta_str = request.args.get('hasta')  # YYYY-MM-DD
    
    desde = hasta = None
    try:
        if desde_str:
            desde = datetime.strptime(desde_str, '%Y-%m-%d').date()
        if hasta_str:
            hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'ok': False, 'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}), 400
    
    try:
        # Obtener datos de curva S
        curve_data = curva_s_tarea(tarea_id, desde, hasta)
        
        # Información adicional de la tarea
        task_info = {
            'id': tarea.id,
            'nombre': tarea.nombre,
            'fecha_inicio': tarea.fecha_inicio.isoformat() if tarea.fecha_inicio else None,
            'fecha_fin': tarea.fecha_fin.isoformat() if tarea.fecha_fin else None,
            'presupuesto_mo': float(tarea.presupuesto_mo) if tarea.presupuesto_mo else 0,
            'unidad': tarea.unidad,
            'pct_completado': round(tarea.pct_completado, 2)
        }
        
        return jsonify({
            'ok': True,
            'tarea': task_info,
            'curva_s': curve_data,
            'fecha_consulta': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error al calcular curva S: {str(e)}'}), 500

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

@obras_bp.route('/api/tareas/bulk_delete', methods=['POST'])
@login_required  
def api_tareas_bulk_delete():
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

@obras_bp.route('/api/etapas/bulk_delete', methods=['POST'])
@login_required
def api_etapas_bulk_delete():
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


@obras_bp.route('/<int:obra_id>/wizard/tareas', methods=['POST'])
@login_required
def wizard_crear_tareas(obra_id):
    """
    Issue #1 - Backend: Wizard – creación masiva de tareas
    Endpoint para crear varias tareas y asignar responsables en un solo paso
    """
    # Verificar permisos (solo admin/pm)
    obra = Obra.query.get_or_404(obra_id)
    if not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403
    
    try:
        data = request.get_json()
        if not data:
            return jsonify(ok=False, error="JSON requerido"), 400
            
        etapas_data = data.get('etapas', [])
        evitar_duplicados = data.get('evitar_duplicados', True)
        
        if not etapas_data:
            return jsonify(ok=False, error="Se requiere al menos una etapa"), 400
        
        creadas = 0
        ya_existian = 0
        asignaciones_creadas = 0
        
        # Comenzar transacción
        db.session.begin()
        
        current_app.logger.info(f"🧙‍♂️ WIZARD: Creando tareas para obra {obra_id}")
        
        for etapa_data in etapas_data:
            etapa_id = etapa_data.get('etapa_id')
            tareas_data = etapa_data.get('tareas', [])
            
            # Validar que la etapa existe y pertenece a la obra
            etapa = EtapaObra.query.filter_by(
                id=etapa_id, 
                obra_id=obra_id
            ).first()
            
            if not etapa:
                db.session.rollback()
                return jsonify(ok=False, error=f"Etapa {etapa_id} no existe en esta obra"), 400
            
            for tarea_data in tareas_data:
                nombre = tarea_data.get('nombre')
                inicio = tarea_data.get('inicio')  # formato "2025-09-20"
                fin = tarea_data.get('fin')
                horas_estimadas = tarea_data.get('horas_estimadas')
                unidad = tarea_data.get('unidad', 'h')
                responsable_id = tarea_data.get('responsable_id')
                
                # Validaciones básicas
                if not nombre:
                    db.session.rollback()
                    return jsonify(ok=False, error="Nombre de tarea requerido"), 400
                
                if responsable_id:
                    # Validar que el responsable es miembro de la obra
                    miembro = ObraMiembro.query.filter_by(
                        obra_id=obra_id,
                        usuario_id=responsable_id
                    ).first()
                    
                    if not miembro:
                        db.session.rollback()
                        return jsonify(ok=False, error=f"Usuario {responsable_id} no es miembro de esta obra"), 400
                
                # Parsear fechas
                fecha_inicio_plan = None
                fecha_fin_plan = None
                
                if inicio:
                    try:
                        fecha_inicio_plan = datetime.strptime(inicio, '%Y-%m-%d').date()
                    except ValueError:
                        db.session.rollback()
                        return jsonify(ok=False, error=f"Fecha inicio inválida: {inicio}"), 400
                
                if fin:
                    try:
                        fecha_fin_plan = datetime.strptime(fin, '%Y-%m-%d').date()
                    except ValueError:
                        db.session.rollback()
                        return jsonify(ok=False, error=f"Fecha fin inválida: {fin}"), 400
                
                # Verificar si ya existe (upsert por etapa_id, nombre)
                tarea_existente = None
                if evitar_duplicados:
                    tarea_existente = TareaEtapa.query.filter_by(
                        etapa_id=etapa_id,
                        nombre=nombre
                    ).first()
                
                if tarea_existente:
                    # Actualizar tarea existente
                    ya_existian += 1
                    tarea = tarea_existente
                    
                    # Actualizar campos si vienen nuevos valores
                    if fecha_inicio_plan:
                        tarea.fecha_inicio_plan = fecha_inicio_plan
                    if fecha_fin_plan:
                        tarea.fecha_fin_plan = fecha_fin_plan
                    if horas_estimadas:
                        tarea.horas_estimadas = horas_estimadas
                    if unidad:
                        tarea.unidad = unidad
                    if responsable_id:
                        tarea.responsable_id = responsable_id
                        
                    current_app.logger.info(f"📝 WIZARD: Actualizada tarea existente '{nombre}' en etapa {etapa_id}")
                    
                else:
                    # Crear nueva tarea
                    tarea = TareaEtapa(
                        etapa_id=etapa_id,
                        nombre=nombre,
                        descripcion=f"Creada via wizard",
                        estado='pendiente',
                        fecha_inicio_plan=fecha_inicio_plan,
                        fecha_fin_plan=fecha_fin_plan,
                        horas_estimadas=horas_estimadas,
                        unidad=unidad,
                        responsable_id=responsable_id
                    )
                    
                    db.session.add(tarea)
                    db.session.flush()  # Para obtener el ID
                    creadas += 1
                    
                    current_app.logger.info(f"✨ WIZARD: Nueva tarea '{nombre}' creada en etapa {etapa_id}")
                
                # Asignar responsable en tarea_miembros si viene responsable_id
                if responsable_id:
                    # Verificar si ya está asignado
                    asignacion_existente = TareaMiembro.query.filter_by(
                        tarea_id=tarea.id,
                        usuario_id=responsable_id
                    ).first()
                    
                    if not asignacion_existente:
                        asignacion = TareaMiembro(
                            tarea_id=tarea.id,
                            usuario_id=responsable_id,
                            cuota_objetivo=None  # Opcional por ahora
                        )
                        db.session.add(asignacion)
                        asignaciones_creadas += 1
                        
                        current_app.logger.info(f"👤 WIZARD: Asignado usuario {responsable_id} a tarea {tarea.id}")
        
        # Confirmar transacción
        db.session.commit()
        
        current_app.logger.info(f"🎉 WIZARD: Completado - {creadas} creadas, {ya_existian} ya existían, {asignaciones_creadas} asignaciones")
        
        return jsonify(
            ok=True,
            creadas=creadas,
            ya_existian=ya_existian,
            asignaciones_creadas=asignaciones_creadas
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"❌ WIZARD: Error creando tareas")
        return jsonify(ok=False, error=f"Error interno: {str(e)}"), 500


# Catalog API Endpoints (for the new wizard)

@obras_bp.route('/api/catalogo/etapas', methods=['GET'])
@login_required  
def get_catalogo_etapas():
    """Get complete etapas catalog"""
    try:
        from etapas_predefinidas import obtener_etapas_disponibles
        catalogo = obtener_etapas_disponibles()
        response = jsonify({"ok": True, "etapas_catalogo": catalogo})
        response.headers['Content-Type'] = 'application/json'
        return response, 200
    except Exception as e:
        current_app.logger.exception("API Error obteniendo catálogo de etapas")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400


@obras_bp.route('/api/wizard-tareas/etapas', methods=['GET'])
@login_required
def get_wizard_etapas():
    """Get catalog + existing etapas for obra (wizard Step 1)"""
    try:
        obra_id = request.args.get('obra_id', type=int)
        if not obra_id:
            response = jsonify({"ok": False, "error": "obra_id es requerido"})
            response.headers['Content-Type'] = 'application/json'
            return response, 400
            
        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403
        
        # Obtener catálogo completo
        from etapas_predefinidas import obtener_etapas_disponibles
        catalogo = obtener_etapas_disponibles()
        
        # Obtener etapas ya creadas en la obra
        etapas_creadas = EtapaObra.query.filter_by(obra_id=obra_id).order_by(EtapaObra.orden).all()
        etapas_creadas_data = [
            {"id": e.id, "slug": None, "nombre": e.nombre} for e in etapas_creadas
        ]
        
        # Mapear etapas creadas con slugs del catálogo si es posible
        for etapa_creada in etapas_creadas_data:
            etapa_catalogo = next((c for c in catalogo if c['nombre'] == etapa_creada['nombre']), None)
            if etapa_catalogo:
                etapa_creada['slug'] = etapa_catalogo['slug']
        
        response = jsonify({
            "ok": True,
            "etapas_catalogo": catalogo,
            "etapas_creadas": etapas_creadas_data
        })
        response.headers['Content-Type'] = 'application/json'
        return response, 200
        
    except Exception as e:
        current_app.logger.exception("API Error obteniendo etapas para wizard")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400


@obras_bp.route('/api/wizard-tareas/tareas', methods=['POST','GET'])
@login_required
def wizard_tareas_catalogo():
    """Get catalog tareas for selected etapas (wizard Step 2)"""
    try:
        # Soportar POST JSON y GET con query params
        if request.method == 'POST' and request.is_json:
            data = request.get_json(silent=True) or {}
            obra_id = data.get('obra_id')
            etapas  = data.get('etapas')  # lista de slugs
        else:
            obra_id = request.args.get('obra_id', type=int)
            etapas  = request.args.getlist('etapas')

        if not obra_id or not etapas:
            response = jsonify({'ok': False, 'error': 'obra_id y etapas son requeridos'})
            response.headers['Content-Type'] = 'application/json'
            return response, 400

        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403

        # Importar función de catálogo de tareas
        from tareas_predefinidas import obtener_tareas_por_etapa
        from etapas_predefinidas import obtener_etapas_disponibles
        
        # Mapear slugs a nombres completos de etapas
        catalogo_etapas = obtener_etapas_disponibles()
        slug_to_nombre = {e['slug']: e['nombre'] for e in catalogo_etapas}
        
        # Obtener tareas reales del catálogo
        resp = []
        for slug in etapas:
            nombre_etapa = slug_to_nombre.get(slug)
            if nombre_etapa:
                tareas_etapa = obtener_tareas_por_etapa(nombre_etapa)
                for idx, tarea in enumerate(tareas_etapa):
                    resp.append({
                        'id': f'{slug}-{idx+1}',  # ID único: slug + índice
                        'nombre': tarea['nombre'],
                        'descripcion': tarea.get('descripcion', ''),
                        'etapa_slug': slug,
                        'horas': tarea.get('horas', 0)  # Campo adicional útil
                    })
        
        # Ordenar por etapa_slug y nombre para presentación ordenada
        resp.sort(key=lambda t: (t['etapa_slug'], t['nombre']))

        response = jsonify({'ok': True, 'tareas_catalogo': resp})
        response.headers['Content-Type'] = 'application/json'
        return response, 200
        
    except Exception as e:
        current_app.logger.exception("API Error obteniendo tareas para wizard")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400


@obras_bp.route('/api/obras/<int:obra_id>/etapas/bulk_from_catalog', methods=['POST'])
@login_required
def bulk_create_etapas_from_catalog(obra_id):
    """Create etapas in obra from catalog IDs (idempotent)"""
    try:
        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403
        
        data = request.get_json()
        catalogo_ids = data.get("catalogo_ids", [])
        
        if not catalogo_ids:
            response = jsonify({"ok": False, "error": "Se requiere al menos un ID del catálogo"})
            response.headers['Content-Type'] = 'application/json'
            return response, 400
        
        # Atomic transaction: create etapas and seed tasks together
        from etapas_predefinidas import crear_etapas_desde_catalogo
        
        try:
            creadas, existentes = crear_etapas_desde_catalogo(obra_id, catalogo_ids)
            
            # Crear tareas predefinidas para las etapas nuevas (usar función local)
            for etapa_data in creadas:
                etapa = EtapaObra.query.get(etapa_data['id'])
                if etapa:
                    seed_tareas_para_etapa(etapa, auto_commit=False)  # Don't commit individually
            
            # Single commit for both etapas and tasks
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            raise  # Re-raise to be caught by outer try-catch
        
        response = jsonify({
            "ok": True,
            "creadas": creadas,
            "existentes": existentes
        })
        response.headers['Content-Type'] = 'application/json'
        return response, 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"API Error creando etapas desde catálogo para obra {obra_id}")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400


# Etapa Management API Endpoints (existing)

@obras_bp.route('/<int:obra_id>/etapas', methods=['GET'])
@login_required
def get_obra_etapas(obra_id):
    """Get etapas for obra - for wizard Step 1"""
    try:
        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({"error": "Sin permisos"}), 403
        
        # Obtener etapas
        etapas = EtapaObra.query.filter_by(obra_id=obra_id).order_by(EtapaObra.orden).all()
        
        return jsonify({
            "etapas": [{"id": e.id, "nombre": e.nombre} for e in etapas]
        })
        
    except Exception as e:
        current_app.logger.exception(f"Error obteniendo etapas obra {obra_id}")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500


@obras_bp.route('/api/etapas/<int:obra_id>/refresh', methods=['GET'])
@login_required
def get_obra_etapas_full(obra_id):
    """Get complete etapas data for DOM refresh"""
    try:
        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({"ok": False, "error": "Sin permisos"}), 403
        
        # Obtener etapas con datos completos
        etapas = obra.etapas.order_by(EtapaObra.orden).all()
        can_manage = can_manage_obra(obra)
        
        etapas_data = []
        for etapa in etapas:
            etapas_data.append({
                "id": etapa.id,
                "nombre": etapa.nombre,
                "descripcion": etapa.descripcion,
                "orden": etapa.orden,
                "estado": etapa.estado
            })
        
        return jsonify({
            "ok": True,
            "etapas": etapas_data,
            "can_manage": can_manage,
            "has_etapas": len(etapas_data) > 0
        })
        
    except Exception as e:
        current_app.logger.exception(f"Error obteniendo etapas completas obra {obra_id}")
        return jsonify({"ok": False, "error": f"Error interno: {str(e)}"}), 500


@obras_bp.route('/api/dashboard/alerts')
@login_required  
def dashboard_alerts():
    """API: Get dashboard alerts (overdue, due today, upcoming tasks)"""
    try:
        from datetime import date, timedelta
        from sqlalchemy import and_, or_
        
        today = date.today()
        tomorrow = today + timedelta(days=1)
        next_week = today + timedelta(days=7)
        
        # Base query: tareas de la organización del usuario
        base_query = (TareaEtapa.query
                     .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
                     .join(Obra, EtapaObra.obra_id == Obra.id)
                     .filter(Obra.organizacion_id == current_user.organizacion_id))
        
        # Solo tareas activas (no completadas)
        active_tasks = base_query.filter(
            or_(TareaEtapa.estado == 'en_curso', TareaEtapa.estado == 'pendiente')
        )
        
        # 1. OVERDUE: Tareas con fecha_fin_plan vencida
        overdue_count = active_tasks.filter(
            and_(
                TareaEtapa.fecha_fin_plan.isnot(None),
                TareaEtapa.fecha_fin_plan < today
            )
        ).count()
        
        # 2. DUE TODAY: Tareas que vencen hoy
        due_today_count = active_tasks.filter(
            TareaEtapa.fecha_fin_plan == today
        ).count()
        
        # 3. UPCOMING: Tareas que vencen en los próximos 7 días
        upcoming_count = active_tasks.filter(
            and_(
                TareaEtapa.fecha_fin_plan.isnot(None),
                TareaEtapa.fecha_fin_plan > today,
                TareaEtapa.fecha_fin_plan <= next_week
            )
        ).count()
        
        # 4. PENDING APPROVALS: Avances pendientes de aprobación (solo para PM/Admin)
        pending_avances = 0
        if current_user.role in ['admin', 'pm']:
            pending_avances = (TareaAvance.query
                              .join(TareaEtapa, TareaAvance.tarea_id == TareaEtapa.id)
                              .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)  
                              .join(Obra, EtapaObra.obra_id == Obra.id)
                              .filter(
                                  and_(
                                      Obra.organizacion_id == current_user.organizacion_id,
                                      TareaAvance.status == 'pendiente'
                                  )
                              )).count()
        
        # Response con contadores de alertas
        return jsonify({
            'ok': True,
            'alerts': {
                'overdue_count': overdue_count,
                'due_today_count': due_today_count,
                'upcoming_count': upcoming_count,
                'pending_approvals_count': pending_avances,
                'total_alerts': overdue_count + due_today_count + pending_avances
            },
            'generated_at': today.isoformat()
        })
        
    except Exception as e:
        print(f"❌ Error dashboard alerts: {str(e)}")
        return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@obras_bp.route('/<int:obra_id>/etapas', methods=['POST'])
@login_required
def create_obra_etapa(obra_id):
    """Create new etapa for obra - for wizard quick creation"""
    try:
        data = request.get_json()
        nombre = data.get("nombre", "").strip()
        
        if not nombre:
            return jsonify({"error": "Nombre requerido"}), 400
        
        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({"error": "Sin permisos"}), 403
        
        # Verificar que no exista ya
        existe = EtapaObra.query.filter_by(obra_id=obra_id, nombre=nombre).first()
        if existe:
            return jsonify({"error": f"Ya existe una etapa '{nombre}'"}), 400
        
        # Calcular siguiente orden
        max_orden = db.session.query(db.func.max(EtapaObra.orden)).filter_by(obra_id=obra_id).scalar() or 0
        
        # Crear nueva etapa
        nueva_etapa = EtapaObra(
            obra_id=obra_id,
            nombre=nombre,
            orden=max_orden + 1,
            descripcion=f"Etapa creada via wizard",
            estado='planificacion'
        )
        
        db.session.add(nueva_etapa)
        db.session.commit()
        
        current_app.logger.info(f"✨ Etapa creada via wizard: '{nombre}' ID:{nueva_etapa.id}")
        
        return jsonify({
            "id": nueva_etapa.id,
            "nombre": nueva_etapa.nombre
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error creando etapa via wizard")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500


# API Endpoints for Wizard as per user specification

@obras_bp.route('/api/wizard-tareas/preview', methods=['POST'])
@login_required
def wizard_preview():
    """Step 2 - Preview tasks filtered by selected etapas"""
    try:
        data = request.get_json()
        etapa_ids = data.get("etapa_ids", [])
        obra_id = data.get("obra_id")
        
        if not etapa_ids:
            return jsonify({"ok": False, "error": "etapa_ids requeridos"}), 400
            
        if not obra_id:
            return jsonify({"ok": False, "error": "obra_id requerido"}), 400
            
        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({"ok": False, "error": "Sin permisos"}), 403
        
        # Obtener etapas filtradas
        etapas = (EtapaObra.query
                  .filter(EtapaObra.id.in_(etapa_ids), EtapaObra.obra_id == obra_id)
                  .all())
        
        # 🎯 Construir respuesta con esquema exacto que espera el frontend
        etapas_data = []
        for e in etapas:
            # Tareas del catálogo por tipo de etapa (usando TAREAS_POR_ETAPA)
            from tareas_predefinidas import TAREAS_POR_ETAPA
            tareas_catalogo = []
            
            if e.nombre in TAREAS_POR_ETAPA:
                for idx, tarea_def in enumerate(TAREAS_POR_ETAPA[e.nombre]):
                    tareas_catalogo.append({
                        "codigo": f"cat_{e.id}_{idx}",
                        "nombre": tarea_def.get("nombre", "Tarea sin nombre"),
                        "unidad_default": tarea_def.get("unidad", "h")
                    })
            
            # Tareas existentes en esta etapa (opcional, para referencia)
            tareas_existentes = []
            existing_tasks = TareaEtapa.query.filter_by(etapa_id=e.id).all()
            for t in existing_tasks:
                tareas_existentes.append({
                    "id": t.id,
                    "nombre": t.nombre,
                    "unidad": t.unidad or "h"
                })
            
            etapas_data.append({
                "etapa_id": e.id,
                "etapa_nombre": e.nombre,
                "tareas_catalogo": tareas_catalogo,
                "tareas_existentes": tareas_existentes
            })
        
        # 🎯 Respuesta con esquema exacto según especificación del usuario
        return jsonify({
            "ok": True,
            "obra_id": obra_id,
            "etapas": etapas_data
        })
        
    except Exception as e:
        current_app.logger.exception("Error en wizard preview")
        return jsonify({"ok": False, "error": f"Error interno: {str(e)}"}), 500


@obras_bp.route('/api/obras/<int:obra_id>/equipo', methods=['GET'])
@login_required
def get_obra_equipo(obra_id):
    """Get team members for obra (for wizard step 3)"""
    try:
        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({"error": "Sin permisos"}), 403
        
        # Obtener miembros del equipo
        miembros = (ObraMiembro.query
                   .filter_by(obra_id=obra_id)
                   .join(Usuario)
                   .all())
        
        usuarios = []
        for m in miembros:
            usuarios.append({
                "id": m.usuario.id,
                "nombre": m.usuario.nombre_completo,
                "rol": m.rol_en_obra or "operario"
            })
        
        return jsonify({"usuarios": usuarios})
        
    except Exception as e:
        current_app.logger.exception(f"Error obteniendo equipo obra {obra_id}")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500


@obras_bp.route('/api/wizard-tareas/create', methods=['POST'])
@login_required
def wizard_create():
    """Step 4 - Create tasks in batch with assignments"""
    try:
        data = request.get_json()
        obra_id = data.get("obra_id")
        tareas_in = data.get("tareas", [])
        
        if not obra_id:
            return jsonify({"error": "obra_id requerido"}), 400
            
        if not tareas_in:
            return jsonify({"error": "No hay tareas para crear"}), 400
        
        # Verificar permisos
        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            return jsonify({"error": "Sin permisos"}), 403
        
        creadas = []
        duplicados = []
        
        current_app.logger.info(f"🧙‍♂️ WIZARD CREATE: Procesando {len(tareas_in)} tareas para obra {obra_id}")
        
        # Use proper transaction context
        try:
            for t in tareas_in:
                etapa_id = t.get("etapa_id")
                nombre = t.get("nombre")
                
                if not etapa_id or not nombre:
                    continue
                    
                # Verificar si ya existe (idempotencia)
                exists = (TareaEtapa.query
                         .filter_by(etapa_id=etapa_id, nombre=nombre)
                         .first())
                
                if exists:
                    duplicados.append({"etapa_id": etapa_id, "nombre": nombre})
                    current_app.logger.info(f"📋 WIZARD: Tarea duplicada '{nombre}' en etapa {etapa_id}")
                    continue
                
                # Parsear fechas
                fecha_inicio = None
                fecha_fin = None
                
                if t.get("fecha_inicio"):
                    try:
                        fecha_inicio = datetime.strptime(t["fecha_inicio"], '%Y-%m-%d').date()
                    except ValueError:
                        pass
                        
                if t.get("fecha_fin"):
                    try:
                        fecha_fin = datetime.strptime(t["fecha_fin"], '%Y-%m-%d').date()
                    except ValueError:
                        pass
                
                # Crear tarea
                tarea = TareaEtapa(
                    etapa_id=etapa_id,
                    nombre=nombre,
                    descripcion=f"Creada via wizard masivo",
                    estado='pendiente',
                    unidad=t.get("unidad", "h"),
                    fecha_inicio_plan=fecha_inicio,
                    fecha_fin_plan=fecha_fin,
                    horas_estimadas=t.get("horas"),
                    cantidad_planificada=t.get("cantidad"),
                    responsable_id=t.get("asignado_usuario_id")
                )
                
                db.session.add(tarea)
                db.session.flush()  # Para obtener el ID
                
                # Asignar usuario en tarea_miembros si viene asignado_usuario_id
                if t.get("asignado_usuario_id"):
                    asignacion = TareaMiembro(
                        tarea_id=tarea.id,
                        usuario_id=t["asignado_usuario_id"]
                    )
                    db.session.add(asignacion)
                
                creadas.append({"id": tarea.id, "nombre": tarea.nombre})
                current_app.logger.info(f"✨ WIZARD: Tarea creada '{nombre}' ID:{tarea.id}")
            
            # Confirmar transacción
            db.session.commit()
            current_app.logger.info(f"🎉 WIZARD CREATE: {len(creadas)} creadas, {len(duplicados)} duplicadas")
            
            return jsonify({
                "ok": True,
                "creadas": creadas,
                "duplicados": duplicados
            })
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error en transacción wizard create")
            raise e
        
    except Exception as e:
        current_app.logger.exception("Error en wizard create")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500
