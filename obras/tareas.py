"""Obras -- Task management routes."""
import math
from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
from extensions import db

# Jornada laboral estándar (horas por día) usada para convertir
# horas_estimadas a días hábiles al calcular fecha_fin de una tarea.
JORNADA_HORAS = 8

# Unidades válidas para tareas (debe coincidir con las opciones del
# <select> del modal de edición en templates/obras/detalle.html).
VALID_UNITS = {'m2', 'ml', 'm3', 'un', 'kg', 'h', 'gl'}
from extensions import limiter
from models import (
    Obra, EtapaObra, TareaEtapa, AsignacionObra, Usuario,
    TareaResponsables, ObraMiembro, TareaMiembro, TareaAvance,
    TareaAdjunto, UsoInventario,
)
from tareas_predefinidas import TAREAS_POR_ETAPA
from services.memberships import get_current_org_id
from services.permissions import validate_obra_ownership, validate_tarea_ownership, get_org_id
from services.plan_service import require_active_subscription
from services.project_shared_service import ProjectSharedService

from obras import (
    obras_bp, _get_roles_usuario, is_admin, is_pm_global,
    can_manage_obra, can_log_avance, es_miembro_obra,
    seed_tareas_para_etapa, calcular_costo_materiales,
    sincronizar_estado_obra, distribuir_datos_etapa_a_tareas,
    recalc_tarea_pct, suma_ejecutado, normalize_unit, parse_date,
    _serialize_tarea_detalle, pct_etapa,
)


@obras_bp.route("/tareas/crear", methods=['POST'])
@login_required
@require_active_subscription
def crear_tareas():
    """Crear una o multiples tareas (con o sin sugeridas)."""
    try:
        obra_id = request.form.get("obra_id", type=int)
        obra = validate_obra_ownership(obra_id)

        if not can_manage_obra(obra):
            return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403
        etapa_id = request.form.get("etapa_id", type=int)
        horas = request.form.get("horas_estimadas", type=float)
        resp_id = request.form.get("responsable_id", type=int) or None
        fi = parse_date(request.form.get("fecha_inicio_plan"))
        ff = parse_date(request.form.get("fecha_fin_plan"))
        cantidad_total = request.form.get("cantidad_total", type=float) or None

        sugeridas = request.form.getlist("sugeridas[]")

        if not etapa_id:
            return jsonify(ok=False, error="Falta el ID de etapa"), 400

        etapa = EtapaObra.query.get_or_404(etapa_id)
        if etapa.obra.organizacion_id != current_user.organizacion_id:
            return jsonify(ok=False, error="Sin permisos"), 403

        # Si hay responsable, asegurarse de que este asignado a la obra
        if resp_id:
            from models.projects import AsignacionObra
            asignacion_existente = AsignacionObra.query.filter_by(
                obra_id=obra_id,
                usuario_id=resp_id,
                activo=True
            ).first()

            if not asignacion_existente:
                nueva_asignacion = AsignacionObra(
                    obra_id=obra_id,
                    usuario_id=resp_id,
                    rol_en_obra='operario',
                    activo=True
                )
                db.session.add(nueva_asignacion)
                current_app.logger.info(f"Operario ID {resp_id} asignado automaticamente a obra ID {obra_id}")

        if not sugeridas:
            nombre = request.form.get("nombre", "").strip()
            if not nombre:
                return jsonify(ok=False, error="Falta el nombre"), 400

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
                unidad=unidad,
                cantidad_planificada=cantidad_total,
                objetivo=cantidad_total
            )
            db.session.add(t)
            db.session.commit()
            return jsonify(ok=True, created=1)

        created = 0
        for sid in sugeridas:
            try:
                index = int(sid)
                nombre_etapa = etapa.nombre
                tareas_disponibles = TAREAS_POR_ETAPA.get(nombre_etapa, [])

                if index >= len(tareas_disponibles):
                    continue

                tarea_data = tareas_disponibles[index]

                if isinstance(tarea_data, str):
                    nombre_tarea = tarea_data
                    tarea_unidad = "un"
                elif isinstance(tarea_data, dict):
                    nombre_tarea = tarea_data.get("nombre", "")
                    tarea_unidad = tarea_data.get("unidad", "un")
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
                    unidad=tarea_unidad,
                    cantidad_planificada=cantidad_total,
                    objetivo=cantidad_total
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
        current_app.logger.exception("Error en crear_tareas")
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route("/asignar-usuarios", methods=['POST'])
def asignar_usuarios():
    """Asignar usuarios a multiples tareas - Always returns JSON"""
    try:
        if not current_user.is_authenticated:
            return jsonify(ok=False, error="Usuario no autenticado"), 401

        try:
            tarea_ids = request.form.getlist('tarea_ids[]')
            user_ids = request.form.getlist('user_ids[]')
            cuota = request.form.get('cuota_objetivo', type=int)
            current_app.logger.info(f"asignar_usuarios user={current_user.id} tareas={tarea_ids} users={user_ids} cuota={cuota}")
        except Exception as e:
            current_app.logger.exception("Error parsing form data")
            return jsonify(ok=False, error=f"Error parsing request: {str(e)}"), 400

        if not tarea_ids or not user_ids:
            return jsonify(ok=False, error='Faltan tareas o usuarios'), 400

        primera_tarea = validate_tarea_ownership(int(tarea_ids[0]))

        obra = primera_tarea.etapa.obra
        if not can_manage_obra(obra):
            return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403

        # Validar usuarios - convertir a int primero
        user_ids_int = []
        for uid in user_ids:
            try:
                user_ids_int.append(int(uid))
            except (ValueError, TypeError):
                return jsonify(ok=False, error=f"ID de usuario invalido: {uid}"), 400

        # Verificar que todos los usuarios existen y pertenecen a la organizacion
        usuarios = Usuario.query.filter(Usuario.id.in_(user_ids_int)).all()
        if len(usuarios) != len(user_ids_int):
            return jsonify(ok=False, error="Uno o mas usuarios no existen"), 404

        for user in usuarios:
            if user.organizacion_id != current_user.organizacion_id:
                return jsonify(ok=False, error=f"Usuario {user.id} no pertenece a la organizacion"), 403

        asignaciones_creadas = 0

        for tid in tarea_ids:
            tarea = TareaEtapa.query.get(int(tid))
            if not tarea or tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
                current_app.logger.warning(f"Skipping invalid task {tid}")
                continue

            obra_id = tarea.etapa.obra_id

            for uid in set(user_ids_int):
                existing = TareaMiembro.query.filter_by(tarea_id=int(tid), user_id=uid).first()
                if not existing:
                    nueva_asignacion = TareaMiembro(
                        tarea_id=int(tid),
                        user_id=uid,
                        cuota_objetivo=cuota
                    )
                    db.session.add(nueva_asignacion)
                    asignaciones_creadas += 1
                else:
                    existing.cuota_objetivo = cuota

                # Tambien agregar a ObraMiembro si no existe
                existing_obra_miembro = ObraMiembro.query.filter_by(obra_id=obra_id, usuario_id=uid).first()
                if not existing_obra_miembro:
                    usuario = Usuario.query.get(uid)
                    rol_obra = usuario.rol if usuario else 'operario'
                    nuevo_miembro_obra = ObraMiembro(
                        obra_id=obra_id,
                        usuario_id=uid,
                        rol_en_obra=rol_obra,
                        etapa_id=tarea.etapa_id
                    )
                    db.session.add(nuevo_miembro_obra)
                    current_app.logger.info(f"Usuario {uid} agregado a equipo de obra {obra_id}")

        db.session.commit()
        return jsonify(ok=True, creados=asignaciones_creadas)

    except Exception:
        try:
            db.session.rollback()
            current_app.logger.exception('Unexpected error in asignar_usuarios')
        except Exception:
            pass
        return jsonify(ok=False, error="Error interno del servidor"), 500


@obras_bp.route("/tareas/<int:tarea_id>/avances", methods=['POST'])
@login_required
@require_active_subscription
def crear_avance(tarea_id):
    """Registrar avance con fotos (operarios desde dashboard)."""
    try:
        return _crear_avance_impl(tarea_id)
    except Exception as e:
        db.session.rollback()
        import traceback
        tb = traceback.format_exc()
        current_app.logger.error(f"Error en crear_avance: {tb}")
        return jsonify(ok=False, error=f"Error interno: {str(e)}"), 500


def _crear_avance_impl(tarea_id):
    from werkzeug.utils import secure_filename
    from pathlib import Path

    tarea = TareaEtapa.query.get_or_404(tarea_id)
    if tarea.etapa.obra.organizacion_id != get_current_org_id():
        abort(403)

    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'operario', 'administrador', 'tecnico', 'project_manager'}):
        return jsonify(ok=False, error="Solo usuarios con rol de operario, PM o administrador pueden registrar avances. Contacta a tu administrador para cambiar tu rol."), 403

    if 'operario' in roles:
        is_responsible = tarea.responsable_id == current_user.id
        is_assigned = TareaMiembro.query.filter_by(tarea_id=tarea.id, user_id=current_user.id).first()
        if not (is_responsible or is_assigned):
            return jsonify(ok=False, error="No estas asignado a esta tarea. Pedi al PM o administrador que te asigne para poder registrar avances."), 403

    if not can_log_avance(tarea):
        return jsonify(ok=False, error="No podes registrar avances en esta tarea. Verifica que la tarea este en estado activo."), 403

    cantidad_str = str(request.form.get("cantidad", "")).replace(",", ".")
    try:
        cantidad = float(cantidad_str)
        if cantidad <= 0:
            return jsonify(ok=False, error="La cantidad debe ser mayor a 0. Ingresa un valor positivo para el avance."), 400
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Cantidad invalida. Ingresa un numero valido (ej: 10 o 10.5)."), 400

    unidad_form = request.form.get("unidad_ingresada", "").strip()
    unidad = normalize_unit(unidad_form) if unidad_form else normalize_unit(tarea.unidad)

    plan = float(tarea.cantidad_planificada or 0)
    unidad_tarea = normalize_unit(tarea.unidad) if tarea.unidad else ''
    misma_unidad = (unidad == unidad_tarea) or not unidad_form
    if plan > 0 and misma_unidad:
        ejecutado = float(
            db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
            .filter(TareaAvance.tarea_id == tarea.id, TareaAvance.status == 'aprobado')
            .scalar() or 0
        )
        disponible = plan - ejecutado
        if disponible <= 0:
            return jsonify(ok=False, error=f"Esta tarea ya alcanzo el 100% de avance ({plan} {tarea.unidad}). No se pueden registrar mas avances."), 400
        if cantidad > disponible:
            return jsonify(ok=False, error=f"La cantidad ({cantidad}) supera lo restante ({disponible:.2f} {tarea.unidad}). Maximo permitido: {disponible:.2f}."), 400
    horas = request.form.get("horas", type=float)
    notas = request.form.get("notas", "")

    avance_user_id = current_user.id
    operario_id = request.form.get("operario_id", type=int)
    if operario_id and roles & {'admin', 'pm', 'administrador', 'tecnico', 'project_manager'}:
        obra = tarea.etapa.obra
        is_obra_member = AsignacionObra.query.filter_by(obra_id=obra.id, usuario_id=operario_id).first()
        is_resp = tarea.responsable_id == operario_id
        is_task_member = TareaMiembro.query.filter_by(tarea_id=tarea.id, user_id=operario_id).first()
        if is_resp or is_task_member or is_obra_member:
            avance_user_id = operario_id

    av = TareaAvance(
        tarea_id=tarea.id,
        user_id=avance_user_id,
        cantidad=cantidad,
        unidad=unidad,
        horas=horas,
        notas=notas,
        cantidad_ingresada=cantidad,
        unidad_ingresada=unidad_form or unidad
    )

    if roles & {'admin', 'pm', 'administrador', 'tecnico', 'project_manager'}:
        av.status = "aprobado"
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()
    else:
        av.status = "pendiente"

    db.session.add(av)

    if not tarea.fecha_inicio_real and av.status == "aprobado":
        tarea.fecha_inicio_real = datetime.utcnow()

    uploaded_files = request.files.getlist("fotos")
    for f in uploaded_files:
        if f.filename:
            fname = secure_filename(f.filename)
            base = Path(current_app.static_folder) / "uploads" / "obras" / str(tarea.etapa.obra_id) / "tareas" / str(tarea.id)
            base.mkdir(parents=True, exist_ok=True)
            file_path = base / fname
            f.save(file_path)

            adjunto = TareaAdjunto(
                tarea_id=tarea.id,
                avance_id=av.id,
                uploaded_by=current_user.id,
                path=f"/static/uploads/obras/{tarea.etapa.obra_id}/tareas/{tarea.id}/{fname}"
            )
            db.session.add(adjunto)

    # Procesar materiales consumidos y descontar del stock DE LA OBRA
    from models.inventory import StockObra, MovimientoStockObra

    material_ids = request.form.getlist("material_id[]")
    material_cantidades = request.form.getlist("material_cantidad[]")
    obra_id = tarea.etapa.obra_id

    if material_ids and len(material_ids) > 0:
        from models import ItemInventario
        for i, material_id_str in enumerate(material_ids):
            if not material_id_str or material_id_str == '':
                continue

            try:
                material_id = int(material_id_str)
                cantidad_consumida = Decimal(str(material_cantidades[i])) if i < len(material_cantidades) else Decimal("0")

                if cantidad_consumida <= 0:
                    continue

                item = ItemInventario.query.get(material_id)
                if not item:
                    db.session.rollback()
                    return jsonify(ok=False, error=f"Material ID {material_id} no encontrado en inventario."), 400

                stock_obra = StockObra.query.filter_by(
                    obra_id=obra_id,
                    item_inventario_id=material_id
                ).first()

                if stock_obra and float(stock_obra.cantidad_disponible or 0) > 0:
                    disponible_obra = Decimal(str(stock_obra.cantidad_disponible or 0))

                    if disponible_obra >= cantidad_consumida:
                        stock_obra.cantidad_disponible = float(disponible_obra - cantidad_consumida)
                        stock_obra.cantidad_consumida = float(
                            Decimal(str(stock_obra.cantidad_consumida or 0)) + cantidad_consumida
                        )
                        stock_obra.fecha_ultimo_uso = datetime.utcnow()

                        movimiento = MovimientoStockObra(
                            stock_obra_id=stock_obra.id,
                            tipo='consumo',
                            cantidad=float(cantidad_consumida),
                            usuario_id=current_user.id,
                            observaciones=f"Consumido en avance de tarea: {tarea.nombre} (ID:{tarea.id})",
                            precio_unitario=float(item.precio_promedio or 0)
                        )
                        db.session.add(movimiento)
                    else:
                        stock_obra.cantidad_disponible = 0
                        stock_obra.cantidad_consumida = float(
                            Decimal(str(stock_obra.cantidad_consumida or 0)) + disponible_obra
                        )
                        stock_obra.fecha_ultimo_uso = datetime.utcnow()

                        movimiento = MovimientoStockObra(
                            stock_obra_id=stock_obra.id,
                            tipo='consumo',
                            cantidad=float(disponible_obra),
                            usuario_id=current_user.id,
                            observaciones=f"Consumido en avance de tarea: {tarea.nombre} (ID:{tarea.id}, parcial)",
                            precio_unitario=float(item.precio_promedio or 0)
                        )
                        db.session.add(movimiento)

                precio_unitario = float(item.precio_promedio or 0)
                uso = UsoInventario(
                    obra_id=obra_id,
                    item_id=item.id,
                    cantidad_usada=cantidad_consumida,
                    fecha_uso=datetime.utcnow().date(),
                    usuario_id=current_user.id,
                    observaciones=f"Consumido en avance de tarea: {tarea.nombre}",
                    precio_unitario_al_uso=precio_unitario,
                    moneda='ARS'
                )
                db.session.add(uso)

            except (ValueError, IndexError) as e:
                db.session.rollback()
                return jsonify(ok=False, error=f"Error procesando material: {str(e)}"), 400

    db.session.commit()

    nuevo_pct = recalc_tarea_pct(tarea_id)

    obra = tarea.etapa.obra
    obra.calcular_progreso_automatico()

    costo_materiales = calcular_costo_materiales(obra.id)

    from models import LiquidacionMO
    costo_mano_obra = db.session.query(
        db.func.coalesce(db.func.sum(LiquidacionMO.monto_total), 0)
    ).filter(LiquidacionMO.obra_id == obra.id).scalar() or Decimal('0')

    obra.costo_real = Decimal(str(costo_materiales)) + Decimal(str(costo_mano_obra))

    db.session.commit()

    return jsonify(
        ok=True,
        mensaje="Avance registrado y materiales descontados del stock",
        porcentaje_avance=nuevo_pct,
        estado=tarea.estado,
        cantidad_planificada=float(tarea.cantidad_planificada or 0),
        cantidad_ejecutada=suma_ejecutado(tarea_id)
    )



@obras_bp.route("/api/tareas/<int:tarea_id>/avances", methods=['POST'])
@login_required
def api_crear_avance_fotos(tarea_id):
    """Create progress entry with multiple photos - specification compliant"""
    return ProjectSharedService.api_crear_avance_fotos(tarea_id, normalize_unit, recalc_tarea_pct)


@obras_bp.route("/tareas/<int:tarea_id>/complete", methods=['POST'])
@login_required
def completar_tarea(tarea_id):
    """Completar tarea - solo si restante = 0"""
    from models import resumen_tarea as _rt

    tarea = validate_tarea_ownership(tarea_id)
    obra = tarea.etapa.obra

    if not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403

    try:
        m = _rt(tarea)
        if m["restante"] > 0:
            return jsonify(ok=False, error="Aun faltan cantidades"), 400

        tarea.estado = "completada"
        tarea.fecha_fin_real = datetime.utcnow()
        db.session.commit()
        return jsonify(ok=True)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en completar_tarea")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route('/mis-tareas')
@login_required
def mis_tareas():
    from collections import OrderedDict
    from sqlalchemy import or_

    q_responsable = (
        db.session.query(TareaEtapa)
        .join(EtapaObra, EtapaObra.id == TareaEtapa.etapa_id)
        .join(Obra, Obra.id == EtapaObra.obra_id)
        .filter(TareaEtapa.responsable_id == current_user.id)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
    )

    q_miembro = (
        db.session.query(TareaEtapa)
        .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
        .join(EtapaObra, EtapaObra.id == TareaEtapa.etapa_id)
        .join(Obra, Obra.id == EtapaObra.obra_id)
        .filter(TareaMiembro.user_id == current_user.id)
        .filter(Obra.organizacion_id == current_user.organizacion_id)
    )

    tareas = q_responsable.union(q_miembro).order_by(TareaEtapa.id.desc()).all()
    current_app.logger.info(
        "mis_tareas user=%s unidades=%s",
        current_user.id,
        [(t.id, t.unidad, t.rendimiento) for t in tareas],
    )

    estados = OrderedDict([
        ('pendiente', {'label': 'Pendientes', 'icon': 'far fa-circle'}),
        ('en_curso', {'label': 'En curso', 'icon': 'fas fa-play-circle'}),
        ('completada', {'label': 'Finalizadas', 'icon': 'fas fa-check-circle'}),
    ])

    tareas_por_estado = {clave: [] for clave in estados.keys()}
    for tarea in tareas:
        estado_normalizado = (tarea.estado or 'pendiente').lower()
        if estado_normalizado not in tareas_por_estado:
            estado_normalizado = 'pendiente'
        tareas_por_estado[estado_normalizado].append(tarea)

    resumen_estados = {clave: len(valor) for clave, valor in tareas_por_estado.items()}

    return render_template(
        'obras/mis_tareas.html',
        tareas=tareas,
        tareas_por_estado=tareas_por_estado,
        estados=estados,
        resumen_estados=resumen_estados,
    )


@obras_bp.route('/mis-tareas/<int:tarea_id>')
@login_required
def mis_tareas_detalle(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra if tarea.etapa else None

    if not obra or obra.organizacion_id != current_user.organizacion_id:
        flash('No tienes permisos para ver esta tarea.', 'danger')
        return redirect(url_for('obras.mis_tareas'))

    es_responsable = tarea.responsable_id == current_user.id
    es_miembro = any(mi.user_id == current_user.id for mi in tarea.miembros)

    if not (es_responsable or es_miembro or can_manage_obra(obra)):
        flash('No tienes permisos para ver esta tarea.', 'danger')
        return redirect(url_for('obras.mis_tareas'))

    payload = _serialize_tarea_detalle(tarea)

    roles = ProjectSharedService.get_roles_usuario(current_user)
    es_operario = 'operario' in roles
    puede_actualizar_estado = (es_responsable or es_miembro) and not es_operario

    return render_template(
        'obras/mis_tareas_detalle.html',
        tarea=tarea,
        obra=obra,
        detalle=payload['tarea'],
        avances=payload['avances'],
        puede_actualizar_estado=puede_actualizar_estado,
    )


@obras_bp.route('/api/mis-tareas/<int:tarea_id>/estado', methods=['POST'])
@login_required
def api_mis_tareas_estado(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra if tarea.etapa else None

    if not obra or obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    es_responsable = tarea.responsable_id == current_user.id
    es_miembro = any(mi.user_id == current_user.id for mi in tarea.miembros)

    if not (es_responsable or es_miembro or can_manage_obra(obra)):
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    data = request.get_json(silent=True) or {}
    nuevo_estado = (data.get('estado') or '').lower()
    estados_validos = {'pendiente', 'en_curso', 'completada'}

    if nuevo_estado not in estados_validos:
        return jsonify({'ok': False, 'error': 'Estado no valido'}), 400

    try:
        cambio_realizado = tarea.estado != nuevo_estado
        tarea.estado = nuevo_estado

        ahora = datetime.utcnow()
        if nuevo_estado == 'en_curso' and tarea.fecha_inicio_real is None:
            tarea.fecha_inicio_real = ahora
        if nuevo_estado == 'completada':
            if tarea.fecha_inicio_real is None:
                tarea.fecha_inicio_real = ahora
            tarea.fecha_fin_real = ahora

        db.session.commit()
        payload = _serialize_tarea_detalle(tarea)
        return jsonify({
            'ok': True,
            'cambio': cambio_realizado,
            'tarea': payload['tarea'],
        })
    except Exception as exc:
        current_app.logger.exception('Error actualizando estado de tarea %s: %s', tarea_id, exc)
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'No se pudo actualizar la tarea'}), 500


@obras_bp.route('/api/tareas/<int:tarea_id>/avances-pendientes')
@login_required
def obtener_avances_pendientes(tarea_id):
    """API endpoint para obtener avances pendientes de una tarea con fotos"""
    from utils.permissions import is_admin_or_pm

    if not is_admin_or_pm(current_user):
        return jsonify(ok=False, error="Sin permisos"), 403

    tarea = TareaEtapa.query.get_or_404(tarea_id)

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if tarea.etapa.obra.organizacion_id != org_id:
        return jsonify(ok=False, error="Sin permiso"), 403

    recalc_tarea_pct(tarea_id)

    try:
        avances_pendientes = (
            TareaAvance.query
            .filter_by(tarea_id=tarea_id, status='pendiente')
            .order_by(TareaAvance.created_at.desc())
            .all()
        )

        avances_data = []
        for avance in avances_pendientes:
            fotos = []
            for foto in avance.fotos:
                fotos.append({
                    'id': foto.id,
                    'url': f"/media/{foto.file_path}",
                    'thumbnail_url': f"/media/{foto.file_path}",
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

        avances_aprobados = (
            TareaAvance.query
            .filter_by(tarea_id=tarea_id, status='aprobado')
            .order_by(TareaAvance.created_at.desc())
            .all()
        )
        historial = []
        for av in avances_aprobados:
            fotos_h = []
            for foto in av.fotos:
                fotos_h.append({
                    'id': foto.id,
                    'url': f"/media/{foto.file_path}",
                    'thumbnail_url': f"/media/{foto.file_path}",
                })
            historial.append({
                'id': av.id,
                'cantidad': float(av.cantidad),
                'unidad': av.unidad,
                'horas': float(av.horas or 0),
                'notas': av.notas or '',
                'fecha': av.created_at.strftime('%d/%m/%Y %H:%M'),
                'operario': av.usuario.nombre_completo if av.usuario else 'N/A',
                'aprobado_por': av.confirmado_por.nombre_completo if av.confirmado_por else 'Auto',
                'fotos': fotos_h,
            })

        miembros_data = []
        seen_ids = set()

        if tarea.responsable:
            miembros_data.append({'id': tarea.responsable.id, 'nombre': tarea.responsable.nombre_completo})
            seen_ids.add(tarea.responsable.id)

        for m in tarea.miembros:
            if m.usuario and m.user_id not in seen_ids:
                miembros_data.append({'id': m.usuario.id, 'nombre': m.usuario.nombre_completo})
                seen_ids.add(m.user_id)

        obra = tarea.etapa.obra
        for asig in obra.asignaciones:
            if asig.usuario and asig.usuario.id not in seen_ids:
                miembros_data.append({'id': asig.usuario.id, 'nombre': asig.usuario.nombre_completo})
                seen_ids.add(asig.usuario.id)

        if current_user.id not in seen_ids:
            miembros_data.append({'id': current_user.id, 'nombre': current_user.nombre_completo})
            seen_ids.add(current_user.id)

        plan = float(tarea.cantidad_planificada or 0)
        ejecutado = suma_ejecutado(tarea_id)

        # Calcular rendimiento de la tarea
        rendimiento_data = None
        try:
            from services.rendimiento_operario import calcular_rendimiento_tarea
            rendimiento_data = calcular_rendimiento_tarea(tarea_id)
        except Exception:
            pass

        return jsonify({
            'ok': True,
            'tarea': {
                'id': tarea.id,
                'nombre': tarea.nombre,
                'unidad': tarea.unidad,
                'cantidad_planificada': plan,
                'ejecutado': ejecutado,
                'porcentaje': float(tarea.porcentaje_avance or 0),
                'estado': tarea.estado,
                'horas_estimadas': float(tarea.horas_estimadas or 0),
                'rendimiento': float(tarea.rendimiento or 0),
            },
            'avances': avances_data,
            'total': len(avances_data),
            'historial': historial,
            'miembros': miembros_data,
            'responsable_id': tarea.responsable_id,
            'rendimiento_data': rendimiento_data,
        })

    except Exception as e:
        current_app.logger.exception("Error al obtener avances pendientes")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route('/api/obras/<int:obra_id>/rendimiento-operarios')
@login_required
def api_rendimiento_operarios_obra(obra_id):
    """Ranking de eficiencia de operarios en una obra."""
    from services.rendimiento_operario import ranking_operarios_obra
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first()
    if not obra:
        return jsonify(ok=False, error="Obra no encontrada"), 404
    ranking = ranking_operarios_obra(obra_id)
    return jsonify(ok=True, ranking=ranking, obra_nombre=obra.nombre)


@obras_bp.route('/api/avances/<int:avance_id>/editar', methods=['POST'])
@login_required
def api_editar_avance(avance_id):
    """Editar cantidad y horas de un avance aprobado."""
    from utils.permissions import is_admin_or_pm

    if not is_admin_or_pm(current_user):
        return jsonify(ok=False, error="Sin permisos"), 403

    avance = TareaAvance.query.get_or_404(avance_id)
    tarea = avance.tarea
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if tarea.etapa.obra.organizacion_id != org_id:
        return jsonify(ok=False, error="Sin permiso"), 403

    data = request.get_json(silent=True) or {}
    nueva_cantidad = data.get('cantidad')
    nuevas_horas = data.get('horas')

    if nueva_cantidad is not None:
        try:
            avance.cantidad = float(nueva_cantidad)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Cantidad inválida"), 400

    if nuevas_horas is not None:
        try:
            avance.horas = float(nuevas_horas)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Horas inválidas"), 400

    db.session.flush()
    recalc_tarea_pct(tarea.id)
    db.session.commit()

    return jsonify(
        ok=True,
        avance_id=avance.id,
        cantidad=float(avance.cantidad),
        horas=float(avance.horas or 0),
        porcentaje_tarea=float(tarea.porcentaje_avance or 0),
    )


@obras_bp.route('/api/tareas/<int:tarea_id>/galeria')
@login_required
def api_tarea_galeria(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra if tarea.etapa else None

    if not obra or obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    puede_ver = False
    if can_manage_obra(obra):
        puede_ver = True
    elif tarea.responsable_id == current_user.id:
        puede_ver = True
    else:
        for miembro in tarea.miembros:
            if miembro.user_id == current_user.id:
                puede_ver = True
                break

    if not puede_ver:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    return jsonify(_serialize_tarea_detalle(tarea))


@obras_bp.route('/etapa/<int:id>/tarea', methods=['POST'])
@login_required
def agregar_tarea(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para agregar tareas.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    etapa = EtapaObra.query.get_or_404(id)
    if etapa.obra.organizacion_id != get_current_org_id():
        abort(403)

    horas_estimadas = request.form.get('horas_estimadas')
    responsable_id = request.form.get('responsable_id')
    fecha_inicio_plan = request.form.get('fecha_inicio_plan')
    fecha_fin_plan = request.form.get('fecha_fin_plan')

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
        except Exception:
            db.session.rollback()
            return jsonify({'ok': False, 'error': 'Error al crear las tareas multiples'})

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
        except Exception:
            db.session.rollback()
            flash('Error al agregar la tarea.', 'danger')

        return redirect(url_for('obras.detalle', id=etapa.obra_id))


@obras_bp.route('/admin/backfill_tareas', methods=['POST'])
@login_required
def admin_backfill_tareas():
    if not current_user.is_super_admin:
        flash('No tienes permisos para ejecutar el backfill.', 'danger')
        return redirect(url_for('obras.lista'))

    try:
        etapas_procesadas = 0
        tareas_creadas_total = 0

        etapas = EtapaObra.query.all()

        for etapa in etapas:
            tareas_existentes = TareaEtapa.query.filter_by(etapa_id=etapa.id).count()
            if tareas_existentes < 5:
                tareas_nuevas = seed_tareas_para_etapa(etapa)
                tareas_creadas_total += tareas_nuevas
                etapas_procesadas += 1

        db.session.commit()

        flash(f'Backfill completado: {etapas_procesadas} etapas procesadas, {tareas_creadas_total} tareas creadas.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("ERROR en backfill")
        flash(f'Error en backfill: {str(e)}', 'danger')

    return redirect(url_for('obras.lista'))


@obras_bp.route('/etapas/<int:etapa_id>/tareas')
@login_required
def api_listar_tareas(etapa_id):
    etapa = EtapaObra.query.get_or_404(etapa_id)

    if etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    if is_pm_global():
        q = (TareaEtapa.query
             .filter(TareaEtapa.etapa_id == etapa_id)
             .filter(
                 db.or_(
                     TareaEtapa.responsable_id.isnot(None),
                     TareaEtapa.fecha_inicio_plan.isnot(None),
                     TareaEtapa.fecha_fin_plan.isnot(None)
                 )
             )
             .options(db.joinedload(TareaEtapa.miembros).joinedload(TareaMiembro.usuario)))
    else:
        if not es_miembro_obra(etapa.obra_id, current_user.id):
            return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

        q = (TareaEtapa.query
             .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
             .filter(TareaEtapa.etapa_id == etapa_id,
                     TareaMiembro.user_id == current_user.id)
             .filter(
                 db.or_(
                     TareaEtapa.responsable_id.isnot(None),
                     TareaEtapa.fecha_inicio_plan.isnot(None),
                     TareaEtapa.fecha_fin_plan.isnot(None)
                 )
             )
             .options(db.joinedload(TareaEtapa.miembros).joinedload(TareaMiembro.usuario)))

    try:
        tareas = q.order_by(TareaEtapa.id.asc()).all()
        html = render_template('obras/_tareas_lista.html',
                               tareas=tareas,
                               can_manage=can_manage_obra(etapa.obra))
        return jsonify({'ok': True, 'html': html})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Error al cargar tareas: {str(e)}'}), 500


@obras_bp.route('/api/tareas/<int:tarea_id>/curva-s')
@login_required
def api_curva_s_tarea(tarea_id):
    """API para obtener datos de curva S (PV/EV/AC) de una tarea"""
    from evm_utils import curva_s_tarea

    tarea = TareaEtapa.query.get_or_404(tarea_id)

    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    if 'operario' in _get_roles_usuario(current_user):
        es_miembro = TareaMiembro.query.filter_by(
            tarea_id=tarea_id,
            user_id=current_user.id
        ).first()
        if not es_miembro:
            return jsonify({'ok': False, 'error': 'Sin permisos para esta tarea'}), 403

    desde_str = request.args.get('desde')
    hasta_str = request.args.get('hasta')

    desde = hasta = None
    try:
        if desde_str:
            desde = datetime.strptime(desde_str, '%Y-%m-%d').date()
        if hasta_str:
            hasta = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'ok': False, 'error': 'Formato de fecha invalido. Use YYYY-MM-DD'}), 400

    try:
        curve_data = curva_s_tarea(tarea_id, desde, hasta)

        task_info = {
            'id': tarea.id,
            'nombre': tarea.nombre,
            'fecha_inicio': getattr(tarea, 'fecha_inicio', None).isoformat() if getattr(tarea, 'fecha_inicio', None) else None,
            'fecha_fin': getattr(tarea, 'fecha_fin', None).isoformat() if getattr(tarea, 'fecha_fin', None) else None,
            'presupuesto_mo': float(getattr(tarea, 'presupuesto_mo', 0) or 0),
            'unidad': tarea.unidad,
            'pct_completado': round(getattr(tarea, 'pct_completado', 0) or 0, 2)
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
@limiter.limit("20 per minute")
def eliminar_tarea(tarea_id):
    tarea = TareaEtapa.query.get_or_404(tarea_id)
    obra = tarea.etapa.obra

    if not can_manage_obra(obra):
        return jsonify({'success': False, 'error': 'Sin permisos para gestionar esta obra'}), 403

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    if obra.organizacion_id != org_id:
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    try:
        from models.utils import RegistroTiempo
        from models.templates import WorkCertificationItem
        RegistroTiempo.query.filter_by(tarea_id=tarea_id).delete()
        WorkCertificationItem.query.filter_by(tarea_id=tarea_id).delete()
        TareaResponsables.query.filter_by(tarea_id=tarea_id).delete()

        db.session.delete(tarea)
        obra.calcular_progreso_automatico()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error al eliminar tarea %d", tarea_id)
        return jsonify({'success': False, 'error': 'Error al eliminar la tarea. Intente nuevamente.'}), 500


@obras_bp.route('/api/tareas/bulk_delete', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def api_tareas_bulk_delete():
    data = request.get_json()
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'error': 'No se proporcionaron IDs', 'ok': False}), 400

    primera_tarea = validate_tarea_ownership(ids[0])

    obra = primera_tarea.etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'error': 'Sin permisos para gestionar esta obra', 'ok': False}), 403

    data = request.get_json() or {}
    ids = data.get("ids") or []

    if not ids:
        return jsonify({'error': 'IDs requeridos', 'ok': False}), 400

    try:
        task_ids = []
        for task_id in ids:
            try:
                task_ids.append(int(task_id))
            except (ValueError, TypeError):
                continue

        if not task_ids:
            return jsonify({'error': 'IDs invalidos', 'ok': False}), 400

        tareas = TareaEtapa.query.filter(TareaEtapa.id.in_(task_ids)).all()

        if not tareas:
            return jsonify({'error': 'No se encontraron tareas', 'ok': False}), 404

        obras_a_actualizar = set()
        for tarea in tareas:
            try:
                if tarea.etapa and tarea.etapa.obra and tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
                    return jsonify({'error': 'Sin permisos para algunas tareas', 'ok': False}), 403
                if tarea.etapa and tarea.etapa.obra:
                    obras_a_actualizar.add(tarea.etapa.obra)
            except AttributeError as e:
                current_app.logger.warning(f"Error accediendo a relaciones de tarea {tarea.id}: {str(e)}")
                continue

        deleted = 0
        for tarea in tareas:
            try:
                db.session.delete(tarea)
                deleted += 1
            except Exception as e:
                current_app.logger.warning(f"Error eliminando tarea {tarea.id}: {str(e)}")
                continue

        for obra in obras_a_actualizar:
            try:
                obra.calcular_progreso_automatico()
            except Exception as e:
                current_app.logger.warning(f"Error recalculando progreso para obra {obra.id}: {str(e)}")
                continue

        db.session.commit()
        return jsonify({'ok': True, 'deleted': deleted})

    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor', 'ok': False}), 500


@obras_bp.route('/api/etapas/bulk_delete', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def api_etapas_bulk_delete():
    data = request.get_json()
    ids = data.get('ids', [])

    if not ids:
        return jsonify({'error': 'No se proporcionaron IDs', 'ok': False}), 400

    primera_etapa = EtapaObra.query.get(ids[0])
    if not primera_etapa:
        return jsonify({'error': 'Etapa no encontrada', 'ok': False}), 404
    org_id = get_org_id()
    if not org_id or primera_etapa.obra.organizacion_id != org_id:
        return jsonify({'error': 'Etapa no encontrada', 'ok': False}), 404

    obra = primera_etapa.obra
    if not can_manage_obra(obra):
        return jsonify({'error': 'Sin permisos para gestionar esta obra', 'ok': False}), 403

    data = request.get_json() or {}
    ids = data.get("ids") or []

    if not ids:
        return jsonify({'error': 'IDs requeridos', 'ok': False}), 400

    try:
        etapas = EtapaObra.query.filter(EtapaObra.id.in_(ids)).all()

        obras_a_actualizar = set()
        for etapa in etapas:
            if etapa.obra.organizacion_id != current_user.organizacion_id:
                return jsonify({'error': 'Sin permisos para algunas etapas', 'ok': False}), 403
            obras_a_actualizar.add(etapa.obra)

        deleted = 0
        for etapa in etapas:
            db.session.delete(etapa)
            deleted += 1

        for obra in obras_a_actualizar:
            obra.calcular_progreso_automatico()

        db.session.commit()
        return jsonify({'ok': True, 'deleted': deleted})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e), 'ok': False}), 500


@obras_bp.route('/tarea/<int:id>/actualizar_estado', methods=['POST'])
@login_required
def actualizar_estado_tarea(id):
    tarea = TareaEtapa.query.get_or_404(id)
    if tarea.etapa.obra.organizacion_id != get_current_org_id():
        abort(403)
    obra = tarea.etapa.obra

    is_admin_like = is_admin() or ('tecnico' in _get_roles_usuario(current_user))
    is_responsible = tarea.responsable_id == current_user.id

    asignado = db.session.query(TareaResponsables.id)\
        .filter_by(tarea_id=tarea.id, user_id=current_user.id).first()

    if not (is_admin_like or is_responsible or asignado):
        flash('No tienes permisos para actualizar esta tarea.', 'danger')
        return redirect(url_for('obras.detalle', id=obra.id))

    nuevo_estado = request.form.get('estado')
    porcentaje_avance = request.form.get('porcentaje_avance')

    if nuevo_estado not in ['pendiente', 'en_curso', 'completada', 'cancelada']:
        flash('Estado no valido.', 'danger')
        return redirect(url_for('obras.detalle', id=obra.id))

    try:
        tarea.estado = nuevo_estado

        if porcentaje_avance:
            tarea.porcentaje_avance = Decimal(str(porcentaje_avance).replace(',', '.'))

        if nuevo_estado == 'completada':
            tarea.porcentaje_avance = Decimal('100')
            tarea.fecha_fin_real = date.today()
        elif nuevo_estado == 'en_curso' and not tarea.fecha_inicio_real:
            tarea.fecha_inicio_real = date.today()

        etapa = tarea.etapa
        if etapa:
            todas_tareas = etapa.tareas.all() if hasattr(etapa.tareas, 'all') else (etapa.tareas or [])
            if todas_tareas:
                todas_completadas = all(t.estado in ('completada', 'cancelada') for t in todas_tareas)
                alguna_en_curso = any(t.estado in ('en_curso', 'completada') for t in todas_tareas)
                if todas_completadas and etapa.estado != 'finalizada':
                    etapa.estado = 'finalizada'
                    etapa.progreso = 100
                    if not etapa.fecha_fin_real:
                        etapa.fecha_fin_real = date.today()
                elif alguna_en_curso and etapa.estado == 'pendiente':
                    etapa.estado = 'en_curso'
                    if not etapa.fecha_inicio_real:
                        etapa.fecha_inicio_real = date.today()

        obra.calcular_progreso_automatico()
        sincronizar_estado_obra(obra)

        db.session.commit()
        flash('Estado de tarea actualizado exitosamente.', 'success')

    except ValueError:
        flash('Porcentaje de avance no valido.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar tarea: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=obra.id))


@obras_bp.route('/api/tareas/<int:tarea_id>/editar-datos', methods=['POST'])
@login_required
def api_editar_datos_tarea(tarea_id):
    """Editar horas, cantidad, unidad, rendimiento y fechas de una tarea."""
    tarea = validate_tarea_ownership(tarea_id)
    obra = tarea.etapa.obra

    if not can_manage_obra(obra):
        return jsonify(ok=False, error="Sin permisos"), 403

    try:
        data = request.get_json() or request.form

        if 'horas_estimadas' in data and data['horas_estimadas'] is not None:
            tarea.horas_estimadas = float(str(data['horas_estimadas']).replace(',', '.'))

        if 'cantidad_planificada' in data and data['cantidad_planificada'] is not None:
            tarea.cantidad_planificada = float(str(data['cantidad_planificada']).replace(',', '.'))
            tarea.objetivo = tarea.cantidad_planificada

        if 'unidad' in data and data['unidad']:
            unidad_nueva = data['unidad'].strip().lower()
            if unidad_nueva in VALID_UNITS:
                tarea.unidad = unidad_nueva

        if 'rendimiento' in data and data['rendimiento'] is not None:
            tarea.rendimiento = float(str(data['rendimiento']).replace(',', '.'))
        elif tarea.horas_estimadas and float(tarea.horas_estimadas) > 0 and tarea.cantidad_planificada:
            tarea.rendimiento = round(float(tarea.cantidad_planificada) / float(tarea.horas_estimadas), 2)

        if 'fecha_inicio' in data and data['fecha_inicio']:
            from datetime import datetime as dt
            f = dt.strptime(data['fecha_inicio'], '%Y-%m-%d').date()
            tarea.fecha_inicio_plan = f
            tarea.fecha_inicio_estimada = f
        if 'fecha_fin' in data and data['fecha_fin']:
            from datetime import datetime as dt
            f = dt.strptime(data['fecha_fin'], '%Y-%m-%d').date()
            tarea.fecha_fin_plan = f
            tarea.fecha_fin_estimada = f

        if 'responsable_id' in data:
            nuevo_resp = data['responsable_id']
            if nuevo_resp:
                nuevo_resp_id = int(nuevo_resp)
                tarea.responsable_id = nuevo_resp_id
                # Agregar como miembro de la tarea (para aparecer en el listado
                # de asignados de la tarea).
                existe = TareaMiembro.query.filter_by(
                    tarea_id=tarea.id, user_id=nuevo_resp_id
                ).first()
                if not existe:
                    db.session.add(TareaMiembro(
                        tarea_id=tarea.id,
                        user_id=nuevo_resp_id
                    ))
                # Agregar también como miembro de la obra (para aparecer en la
                # pestaña "Equipo Asignado" del detalle de obra). Antes esto
                # quedaba desincronizado: el usuario aparecía en la tarea pero
                # no en el equipo de la obra.
                existe_obra = ObraMiembro.query.filter_by(
                    obra_id=obra.id, usuario_id=nuevo_resp_id
                ).first()
                if not existe_obra:
                    db.session.add(ObraMiembro(
                        obra_id=obra.id,
                        usuario_id=nuevo_resp_id,
                    ))
            else:
                tarea.responsable_id = None

        if tarea.fecha_inicio_plan and tarea.horas_estimadas and float(tarea.horas_estimadas) > 0:
            from services.dependency_service import _sumar_dias_habiles
            horas = float(tarea.horas_estimadas)
            # Usar ceil para que 9h pase al día siguiente (no quede en el mismo
            # día por truncado de int(9/8)=1). Resta 1 porque _sumar_dias_habiles
            # cuenta el día de inicio como día 0.
            dias_necesarios = max(1, math.ceil(horas / JORNADA_HORAS))
            nueva_fin = _sumar_dias_habiles(tarea.fecha_inicio_plan, dias_necesarios - 1)
            tarea.fecha_fin_plan = nueva_fin
            tarea.fecha_fin_estimada = nueva_fin

        # Marcar la tarea como editada manualmente. Esto bloquea que
        # distribuir_datos_etapa_a_tareas() (disparada automáticamente al
        # renderizar el detalle de obra) pise los valores del usuario con
        # los derivados del catálogo de tareas predefinidas o de la etapa.
        tarea.editado_manual = True

        db.session.commit()

        try:
            from services.dependency_service import _siguiente_dia_habil, _sumar_dias_habiles
            tareas_etapa = TareaEtapa.query.filter_by(
                etapa_id=tarea.etapa_id
            ).order_by(TareaEtapa.id).all()

            fecha_cursor = None
            cambios = False
            for t in tareas_etapa:
                if fecha_cursor and t.fecha_inicio_plan != fecha_cursor:
                    t.fecha_inicio_plan = fecha_cursor
                    t.fecha_inicio_estimada = fecha_cursor
                    if t.horas_estimadas and float(t.horas_estimadas) > 0:
                        dias = max(1, math.ceil(float(t.horas_estimadas) / JORNADA_HORAS))
                        t.fecha_fin_plan = _sumar_dias_habiles(fecha_cursor, dias - 1)
                        t.fecha_fin_estimada = t.fecha_fin_plan
                    cambios = True

                if t.fecha_fin_plan:
                    fecha_cursor = _siguiente_dia_habil(t.fecha_fin_plan, 1)
                elif t.fecha_inicio_plan:
                    fecha_cursor = _siguiente_dia_habil(t.fecha_inicio_plan, 1)

            if cambios:
                db.session.commit()
        except Exception as e:
            current_app.logger.warning(f"Error propagando fechas de tareas: {e}")

        return jsonify(
            ok=True,
            tarea={
                'id': tarea.id,
                'horas_estimadas': float(tarea.horas_estimadas or 0),
                'cantidad_planificada': float(tarea.cantidad_planificada or 0),
                'unidad': tarea.unidad,
                'rendimiento': float(tarea.rendimiento or 0),
                'fecha_inicio_plan': tarea.fecha_inicio_plan.isoformat() if tarea.fecha_inicio_plan else None,
                'fecha_fin_plan': tarea.fecha_fin_plan.isoformat() if tarea.fecha_fin_plan else None,
            }
        )

    except (ValueError, TypeError) as e:
        return jsonify(ok=False, error=f"Valor invalido: {str(e)}"), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error al editar datos de tarea")
        return jsonify(ok=False, error=f"Error al guardar: {str(e)[:200]}"), 500


@obras_bp.route('/tareas/<int:tarea_id>/asignar', methods=['POST'])
@login_required
def tarea_asignar(tarea_id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        return jsonify(ok=False, error="Sin permiso"), 403

    tarea = TareaEtapa.query.get_or_404(tarea_id)

    if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
        return jsonify(ok=False, error="Sin permiso"), 403

    data = request.get_json(force=True) or {}
    user_ids = list({int(x) for x in data.get("user_ids", [])})

    try:
        TareaResponsables.query.filter_by(tarea_id=tarea.id).delete()

        for uid in user_ids:
            usuario = Usuario.query.filter_by(id=uid, organizacion_id=current_user.organizacion_id).first()
            if usuario:
                asignacion = TareaResponsables(tarea_id=tarea.id, user_id=uid)
                db.session.add(asignacion)

        db.session.commit()
        return jsonify(ok=True, count=len(user_ids))

    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500
