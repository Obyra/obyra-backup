"""Obras -- Stage management routes."""
from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
from extensions import db
from extensions import limiter
from models import (
    Obra, EtapaObra, EtapaDependencia, TareaEtapa, TareaAvance, TareaMiembro,
)
from services.memberships import get_current_org_id
from services.permissions import validate_obra_ownership, get_org_id

from obras import (
    obras_bp, _get_roles_usuario, can_manage_obra,
    sincronizar_estado_obra, distribuir_datos_etapa_a_tareas,
    propagar_fechas_etapas, recalc_tarea_pct, pct_etapa,
)


@obras_bp.route('/<int:obra_id>/etapas/<int:etapa_id>/eliminar', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def eliminar_etapa(obra_id, etapa_id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para eliminar etapas.', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))

    obra = Obra.query.filter_by(id=obra_id, organizacion_id=current_user.organizacion_id).first_or_404()
    etapa = EtapaObra.query.filter_by(id=etapa_id, obra_id=obra_id).first_or_404()

    try:
        nombre_etapa = etapa.nombre
        db.session.delete(etapa)
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
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para cambiar el estado de etapas.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    etapa = EtapaObra.query.get_or_404(etapa_id)
    org_id = get_org_id()
    if not org_id or etapa.obra.organizacion_id != org_id:
        abort(404)
    nuevo_estado = request.form.get('estado')

    estados_validos = ['pendiente', 'en_curso', 'pausada', 'finalizada']
    if nuevo_estado not in estados_validos:
        flash('Estado no valido.', 'danger')
        return redirect(url_for('obras.detalle', id=etapa.obra_id))

    try:
        estado_anterior = etapa.estado
        etapa.estado = nuevo_estado

        if nuevo_estado == 'finalizada':
            for tarea in etapa.tareas.filter_by(estado='pendiente'):
                tarea.estado = 'completada'
            if not etapa.fecha_fin_real:
                etapa.fecha_fin_real = date.today()

        etapa.obra.calcular_progreso_automatico()
        sincronizar_estado_obra(etapa.obra)

        db.session.commit()

        if nuevo_estado == 'finalizada':
            result = propagar_fechas_etapas(etapa.obra_id)
            if result['shifted_count'] > 0:
                db.session.commit()
                nombres = ', '.join(d['etapa'] for d in result['details'][:3])
                extra = f' y {result["shifted_count"] - 3} mas' if result['shifted_count'] > 3 else ''
                flash(f'Se actualizaron fechas de: {nombres}{extra}', 'info')

        flash(f'Estado de etapa "{etapa.nombre}" cambiado de "{estado_anterior}" a "{nuevo_estado}".', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar estado: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=etapa.obra_id))


@obras_bp.route('/<int:id>/propagar_fechas', methods=['POST'])
@login_required
def propagar_fechas(id):
    """Recalcular fechas de etapas encadenadas manualmente."""
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para ajustar fechas.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    obra = validate_obra_ownership(id)
    try:
        result = propagar_fechas_etapas(obra.id)
        if result['shifted_count'] > 0:
            db.session.commit()
            flash(f'Se ajustaron las fechas de {result["shifted_count"]} etapa(s).', 'success')
        else:
            flash('No fue necesario ajustar fechas.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al propagar fechas: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/etapas/<int:etapa_id>/editar_fechas', methods=['POST'])
@login_required
def editar_fechas_etapa(etapa_id):
    """Editar fechas de una etapa manualmente (admin/tecnico)."""
    etapa = EtapaObra.query.get_or_404(etapa_id)
    org_id = get_org_id()
    if not org_id or etapa.obra.organizacion_id != org_id:
        abort(404)
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        return jsonify({'error': 'Sin permisos'}), 403

    data = request.get_json(silent=True) or {}

    try:
        fecha_inicio_usuario = date.fromisoformat(data['fecha_inicio']) if data.get('fecha_inicio') else None
        fecha_fin_usuario = date.fromisoformat(data['fecha_fin']) if data.get('fecha_fin') else None

        fi = fecha_inicio_usuario or etapa.fecha_inicio_estimada
        ff = fecha_fin_usuario or etapa.fecha_fin_estimada
        if fi and ff and ff < fi:
            fecha_fin_usuario = fi

        if 'nivel' in data:
            etapa.nivel_encadenamiento = int(data['nivel']) if data['nivel'] is not None else None

        if data.get('forzar_inicio') and etapa.estado == 'pendiente':
            etapa.estado = 'en_curso'
            if not etapa.fecha_inicio_real:
                etapa.fecha_inicio_real = date.today()

        if fecha_inicio_usuario:
            etapa.fecha_inicio_estimada = fecha_inicio_usuario
        if fecha_fin_usuario:
            etapa.fecha_fin_estimada = fecha_fin_usuario

        bloquear = data.get('bloquear_fechas')
        if bloquear is not None:
            etapa.fechas_manuales = bool(bloquear)
        else:
            etapa.fechas_manuales = True

        db.session.commit()

        from services.dependency_service import generar_dependencias_desde_niveles
        deps_creadas = generar_dependencias_desde_niveles(etapa.obra_id)
        db.session.commit()

        result = propagar_fechas_etapas(
            etapa.obra_id,
            force_cascade=True,
            skip_etapa_id=etapa.id
        )
        propagadas = result['shifted_count']
        if propagadas > 0:
            db.session.commit()

        distribuir_datos_etapa_a_tareas(etapa_id, forzar=True)
        db.session.commit()

        todas = EtapaObra.query.filter_by(obra_id=etapa.obra_id).order_by(EtapaObra.orden).all()
        debug_etapas = []
        for e in todas:
            debug_etapas.append({
                'nombre': e.nombre,
                'nivel': e.nivel_encadenamiento,
                'inicio': str(e.fecha_inicio_estimada) if e.fecha_inicio_estimada else None,
                'fin': str(e.fecha_fin_estimada) if e.fecha_fin_estimada else None,
                'manual': e.fechas_manuales,
                'estado': e.estado,
            })

        return jsonify({
            'ok': True,
            'fecha_inicio': str(etapa.fecha_inicio_estimada) if etapa.fecha_inicio_estimada else None,
            'fecha_fin': str(etapa.fecha_fin_estimada) if etapa.fecha_fin_estimada else None,
            'estado': etapa.estado,
            'fechas_manuales': etapa.fechas_manuales,
            'propagadas': propagadas,
            'deps_creadas': deps_creadas,
            'debug_etapas': debug_etapas,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@obras_bp.route('/etapas/<int:etapa_id>/nivel', methods=['POST'])
@login_required
def cambiar_nivel_etapa(etapa_id):
    """Cambiar nivel de encadenamiento de una etapa."""
    etapa = EtapaObra.query.get_or_404(etapa_id)
    org_id = get_org_id()
    if not org_id or etapa.obra.organizacion_id != org_id:
        abort(404)
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        return jsonify({'error': 'Sin permisos'}), 403

    data = request.get_json(silent=True) or {}
    nivel = data.get('nivel')

    try:
        etapa.nivel_encadenamiento = int(nivel) if nivel is not None else None
        db.session.commit()

        from services.dependency_service import generar_dependencias_desde_niveles
        generar_dependencias_desde_niveles(etapa.obra_id)
        result = propagar_fechas_etapas(etapa.obra_id)
        db.session.commit()

        return jsonify({
            'ok': True,
            'nivel': etapa.nivel_encadenamiento,
            'shifted': result['shifted_count'],
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@obras_bp.route('/<int:id>/gantt-data')
@login_required
def gantt_data(id):
    """Retorna datos de etapas en formato compatible con frappe-gantt."""
    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
    etapas = (
        EtapaObra.query
        .filter_by(obra_id=id)
        .order_by(EtapaObra.nivel_encadenamiento.asc().nullslast(), EtapaObra.orden)
        .all()
    )

    etapa_ids = [e.id for e in etapas]
    deps = EtapaDependencia.query.filter(
        EtapaDependencia.etapa_id.in_(etapa_ids)
    ).all() if etapa_ids else []

    deps_map = {}
    for d in deps:
        deps_map.setdefault(d.etapa_id, []).append(str(d.depende_de_id))

    estado_class = {
        'pendiente': 'gantt-pendiente',
        'en_curso': 'gantt-en-curso',
        'finalizada': 'gantt-finalizada',
    }

    tasks = []
    for e in etapas:
        if e.estado in ('en_curso', 'finalizada'):
            inicio = e.fecha_inicio_real or e.fecha_inicio_estimada
            fin = e.fecha_fin_real or e.fecha_fin_estimada
        else:
            inicio = e.fecha_inicio_estimada
            fin = e.fecha_fin_estimada

        if not inicio or not fin:
            tareas = e.tareas.all() if hasattr(e.tareas, 'all') else (e.tareas or [])
            fechas_inicio = [t.fecha_inicio or t.fecha_inicio_plan or t.fecha_inicio_estimada for t in tareas if (t.fecha_inicio or t.fecha_inicio_plan or t.fecha_inicio_estimada)]
            fechas_fin = [t.fecha_fin or t.fecha_fin_plan or t.fecha_fin_estimada for t in tareas if (t.fecha_fin or t.fecha_fin_plan or t.fecha_fin_estimada)]
            if not inicio and fechas_inicio:
                inicio = min(fechas_inicio)
            if not fin and fechas_fin:
                fin = max(fechas_fin)

        if not inicio or not fin:
            continue

        if e.estado == 'finalizada':
            progress = 100
        else:
            progress = pct_etapa(e)

        tasks.append({
            'id': str(e.id),
            'name': e.nombre,
            'start': inicio.strftime('%Y-%m-%d'),
            'end': fin.strftime('%Y-%m-%d'),
            'progress': progress,
            'dependencies': ','.join(deps_map.get(e.id, [])),
            'custom_class': estado_class.get(e.estado, ''),
            'nivel': e.nivel_encadenamiento,
            'estado': e.estado,
            'fechas_manuales': e.fechas_manuales or False,
            'es_opcional': e.es_opcional or False,
        })

    response = jsonify(tasks)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


# ===== ENDPOINTS PARA SISTEMA DE APROBACIONES =====

@obras_bp.route("/avances/<int:avance_id>/aprobar", methods=['POST'])
@login_required
def aprobar_avance(avance_id):
    from utils.permissions import can_approve_avance

    av = TareaAvance.query.get_or_404(avance_id)

    if not can_approve_avance(current_user, av):
        return jsonify(ok=False, error="Sin permiso"), 403

    if av.status == "aprobado":
        return jsonify(ok=True)

    tarea = TareaEtapa.query.get(av.tarea_id)
    plan = float(tarea.cantidad_planificada or 0) if tarea else 0
    if plan > 0:
        ya_aprobado = float(
            db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
            .filter(TareaAvance.tarea_id == av.tarea_id, TareaAvance.status == 'aprobado')
            .scalar() or 0
        )
        if ya_aprobado + float(av.cantidad) > plan:
            disponible = plan - ya_aprobado
            return jsonify(ok=False, error=f"No se puede aprobar: la cantidad ({float(av.cantidad)}) supera lo restante ({disponible:.2f}). Use 'Corregir' para ajustar la cantidad."), 400

    try:
        av.status = "aprobado"
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()

        t = tarea
        if t and not t.fecha_inicio_real:
            t.fecha_inicio_real = datetime.utcnow()

        db.session.commit()

        if av.tarea_id:
            recalc_tarea_pct(av.tarea_id)

        return jsonify(ok=True)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en aprobar_avance")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route("/avances/<int:avance_id>/rechazar", methods=['POST'])
@login_required
def rechazar_avance(avance_id):
    from utils.permissions import can_approve_avance

    av = TareaAvance.query.get_or_404(avance_id)

    if not can_approve_avance(current_user, av):
        return jsonify(ok=False, error="Sin permiso"), 403

    try:
        av.status = "rechazado"
        av.reject_reason = request.form.get("motivo")
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()

        db.session.commit()

        if av.tarea_id:
            recalc_tarea_pct(av.tarea_id)

        return jsonify(ok=True)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en rechazar_avance")
        return jsonify(ok=False, error="Error interno"), 500


@obras_bp.route("/avances/<int:avance_id>/corregir", methods=['POST'])
@login_required
def corregir_avance(avance_id):
    """Corregir la cantidad de un avance y aprobarlo."""
    from utils.permissions import can_approve_avance

    av = TareaAvance.query.get_or_404(avance_id)

    if not can_approve_avance(current_user, av):
        return jsonify(ok=False, error="Sin permiso"), 403

    cantidad_str = request.form.get("cantidad_corregida", "").replace(",", ".")
    motivo = request.form.get("motivo", "")

    try:
        cantidad_corregida = float(cantidad_str)
        if cantidad_corregida < 0:
            return jsonify(ok=False, error="La cantidad no puede ser negativa"), 400
    except (ValueError, TypeError):
        return jsonify(ok=False, error="Cantidad invalida"), 400

    tarea = TareaEtapa.query.get(av.tarea_id)
    plan = float(tarea.cantidad_planificada or 0) if tarea else 0
    if plan > 0:
        otros_aprobados = float(
            db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
            .filter(TareaAvance.tarea_id == av.tarea_id, TareaAvance.status == 'aprobado', TareaAvance.id != av.id)
            .scalar() or 0
        )
        disponible = plan - otros_aprobados
        if cantidad_corregida > disponible:
            return jsonify(ok=False, error=f"La cantidad corregida ({cantidad_corregida}) supera lo disponible ({disponible:.2f}). Maximo: {disponible:.2f}."), 400

    try:
        cantidad_original = float(av.cantidad)

        av.cantidad = cantidad_corregida
        av.status = "aprobado"
        av.confirmed_by = current_user.id
        av.confirmed_at = datetime.utcnow()
        av.reject_reason = f"Corregido por admin: {cantidad_original} -> {cantidad_corregida}. {motivo}"

        t = TareaEtapa.query.get(av.tarea_id)
        if t and not t.fecha_inicio_real:
            t.fecha_inicio_real = datetime.utcnow()

        db.session.commit()

        if av.tarea_id:
            recalc_tarea_pct(av.tarea_id)

        current_app.logger.info(
            "Avance %d corregido: %s -> %s por %s",
            avance_id, cantidad_original, cantidad_corregida, current_user.email
        )
        return jsonify(ok=True)

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en corregir_avance")
        return jsonify(ok=False, error="Error interno"), 500
