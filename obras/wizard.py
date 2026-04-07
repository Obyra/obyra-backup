"""Obras -- Wizard for tasks routes."""
from flask import request, jsonify, current_app, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, date
from extensions import db
from models import (
    Obra, EtapaObra, TareaEtapa, AsignacionObra, TareaMiembro, TareaAvance,
    ObraMiembro, Usuario,
)
from etapas_predefinidas import obtener_etapas_disponibles
from tareas_predefinidas import obtener_tareas_por_etapa
from calculadora_ia import (
    calcular_superficie_etapa, obtener_factores_todas_etapas,
    FACTORES_SUPERFICIE_ETAPA,
)
from services.permissions import validate_obra_ownership
from services.plan_service import require_active_subscription
from services.project_shared_service import ProjectSharedService

from obras import (
    obras_bp, _get_roles_usuario, can_manage_obra,
    seed_tareas_para_etapa, distribuir_datos_etapa_a_tareas,
    parse_date,
)


@obras_bp.route('/<int:obra_id>/wizard/tareas', methods=['POST'])
@login_required
def wizard_crear_tareas(obra_id):
    """Wizard: creacion masiva de tareas/miembros en un paso."""
    return ProjectSharedService.wizard_crear_tareas(obra_id)


# ==== Wizard: catalogos ====

@obras_bp.route('/api/catalogo/etapas', methods=['GET'])
@login_required
def get_catalogo_etapas():
    try:
        catalogo = obtener_etapas_disponibles()
        response = jsonify({"ok": True, "etapas_catalogo": catalogo})
        response.headers['Content-Type'] = 'application/json'
        return response, 200
    except Exception as e:
        current_app.logger.exception("API Error obteniendo catalogo de etapas")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400


@obras_bp.route('/api/wizard-tareas/etapas', methods=['GET'])
@login_required
def get_wizard_etapas():
    try:
        obra_id = request.args.get('obra_id', type=int)
        if not obra_id:
            response = jsonify({"ok": False, "error": "obra_id es requerido"})
            response.headers['Content-Type'] = 'application/json'
            return response, 400

        obra = validate_obra_ownership(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403

        catalogo = obtener_etapas_disponibles()

        etapas_creadas = EtapaObra.query.filter_by(obra_id=obra_id).order_by(EtapaObra.orden).all()
        etapas_creadas_data = [{"id": e.id, "slug": None, "nombre": e.nombre} for e in etapas_creadas]

        for etapa_creada in etapas_creadas_data:
            etapa_catalogo = next((c for c in catalogo if c['nombre'] == etapa_creada['nombre']), None)
            if etapa_catalogo:
                etapa_creada['slug'] = etapa_catalogo['slug']

        etapas_preseleccionadas = []

        response = jsonify({
            "ok": True,
            "etapas_catalogo": catalogo,
            "etapas_creadas": etapas_creadas_data,
            "etapas_preseleccionadas": etapas_preseleccionadas
        })
        response.headers['Content-Type'] = 'application/json'
        return response, 200

    except Exception as e:
        current_app.logger.exception("API Error obteniendo etapas para wizard")
        response = jsonify({"ok": False, "error": str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 400


@obras_bp.route('/api/calcular-superficie-etapa', methods=['POST'])
@login_required
def api_calcular_superficie_etapa():
    """Calcula la superficie real de trabajo para una etapa especifica."""
    try:
        data = request.get_json(silent=True) or {}

        obra_id = data.get('obra_id')
        etapa_slug = data.get('etapa_slug', '').strip()
        superficie_cubierta = data.get('superficie_cubierta')

        if not etapa_slug:
            return jsonify({"ok": False, "error": "etapa_slug es requerido"}), 400

        if superficie_cubierta is None and obra_id:
            obra = validate_obra_ownership(obra_id)
            if obra.superficie_cubierta:
                superficie_cubierta = float(obra.superficie_cubierta)
            else:
                return jsonify({
                    "ok": False,
                    "error": "No se pudo obtener la superficie cubierta de la obra"
                }), 400
        elif superficie_cubierta is None:
            return jsonify({
                "ok": False,
                "error": "Se requiere obra_id o superficie_cubierta"
            }), 400

        resultado = calcular_superficie_etapa(float(superficie_cubierta), etapa_slug)

        return jsonify({
            "ok": True,
            "etapa_slug": etapa_slug,
            "superficie_cubierta_obra": superficie_cubierta,
            **resultado
        }), 200

    except Exception as e:
        current_app.logger.exception("Error en api_calcular_superficie_etapa")
        return jsonify({"ok": False, "error": str(e)}), 500


@obras_bp.route('/api/factores-superficie', methods=['GET'])
@login_required
def api_get_factores_superficie():
    """Devuelve todos los factores de superficie disponibles."""
    try:
        obra_id = request.args.get('obra_id', type=int)
        superficie_cubierta = request.args.get('superficie', type=float)

        if obra_id and not superficie_cubierta:
            obra = validate_obra_ownership(obra_id)
            if obra.superficie_cubierta:
                superficie_cubierta = float(obra.superficie_cubierta)

        if superficie_cubierta:
            resultado = obtener_factores_todas_etapas(superficie_cubierta)
            return jsonify({
                "ok": True,
                "superficie_cubierta": superficie_cubierta,
                "factores": resultado
            }), 200

        factores_base = {}
        for slug, config in FACTORES_SUPERFICIE_ETAPA.items():
            factores_base[slug] = {
                'nombre': slug.replace('-', ' ').title(),
                'factor': config['factor'],
                'unidad': config['unidad_default'],
                'descripcion': config['descripcion'],
                'notas': config.get('notas', '')
            }

        return jsonify({
            "ok": True,
            "factores": factores_base
        }), 200

    except Exception as e:
        current_app.logger.exception("Error en api_get_factores_superficie")
        return jsonify({"ok": False, "error": str(e)}), 500


@obras_bp.route('/api/wizard-tareas/tareas', methods=['POST','GET'])
@login_required
def wizard_tareas_catalogo():
    try:
        if request.method == 'POST' and request.is_json:
            data = request.get_json(silent=True) or {}
            obra_id = data.get('obra_id')
            etapas  = data.get('etapas')
        else:
            obra_id = request.args.get('obra_id', type=int)
            etapas  = request.args.getlist('etapas')

        if not obra_id or not etapas:
            response = jsonify({'ok': False, 'error': 'obra_id y etapas son requeridos'})
            response.headers['Content-Type'] = 'application/json'
            return response, 400

        obra = Obra.query.get_or_404(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403

        catalogo_etapas = obtener_etapas_disponibles()
        slug_to_nombre = {e['slug']: e['nombre'] for e in catalogo_etapas}

        resp = []
        for slug in etapas:
            nombre_etapa = slug_to_nombre.get(slug)
            if nombre_etapa:
                tareas_etapa = obtener_tareas_por_etapa(nombre_etapa)
                for idx, tarea in enumerate(tareas_etapa):
                    resp.append({
                        'id': f'{slug}-{idx+1}',
                        'nombre': tarea['nombre'],
                        'descripcion': tarea.get('descripcion', ''),
                        'etapa_slug': slug,
                        'horas': tarea.get('horas', 0)
                    })

        resp.sort(key=lambda t: (t['etapa_slug'], t['nombre']))

        response = jsonify({'ok': True, 'tareas_catalogo': resp})
        response.headers['Content-Type'] = 'application/json'
        return response, 200

    except Exception as e:
        current_app.logger.error(f"Error en wizard_tareas_endpoint: {e}")
        response = jsonify({"ok": False, "error": "Error interno del servidor"})
        response.headers['Content-Type'] = 'application/json'
        return response, 500


@obras_bp.route('/api/wizard-tareas/opciones')
@login_required
def wizard_tareas_opciones():
    """Paso 3 del wizard: devuelve unidades sugeridas y equipo de la obra."""
    try:
        obra_id = request.args.get('obra_id', type=int)
        if not obra_id:
            response = jsonify({"ok": False, "error": "obra_id requerido"})
            response.headers['Content-Type'] = 'application/json'
            return response, 400

        obra = validate_obra_ownership(obra_id)
        if not can_manage_obra(obra):
            response = jsonify({"ok": False, "error": "Sin permisos para gestionar esta obra"})
            response.headers['Content-Type'] = 'application/json'
            return response, 403

        unidades = ['m2', 'ml', 'm3', 'un', 'kg', 'h']

        usuarios = []
        try:
            query_result = (db.session.query(Usuario.id, Usuario.nombre, Usuario.apellido, ObraMiembro.rol_en_obra)
                           .join(ObraMiembro, ObraMiembro.usuario_id == Usuario.id)
                           .filter(ObraMiembro.obra_id == obra_id)
                           .filter(Usuario.activo == True)
                           .order_by(ObraMiembro.rol_en_obra)
                           .all())

            for user_id, nombre, apellido, rol in query_result:
                nombre_completo = f"{(nombre or '').strip()} {(apellido or '').strip()}".strip() or "Sin nombre"
                rol_display = rol or 'Sin rol'
                nombre_con_rol = f"{nombre_completo} ({rol_display})"
                usuarios.append({
                    'id': user_id,
                    'nombre': nombre_con_rol,
                    'rol': rol_display
                })
        except Exception as e:
            current_app.logger.warning(f"Error al obtener equipo de obra {obra_id}: {e}")

        return jsonify({"ok": True, "unidades": unidades, "usuarios": usuarios}), 200

    except Exception as e:
        current_app.logger.exception("API Error wizard_tareas_opciones")
        return jsonify({"ok": False, "error": str(e)}), 400


@obras_bp.route('/<int:obra_id>/recargar-tareas', methods=['POST'])
@login_required
@require_active_subscription
def recargar_tareas_predefinidas(obra_id):
    """Elimina tareas existentes y las reemplaza con las predefinidas correctas."""
    try:
        obra = validate_obra_ownership(obra_id)
        if not can_manage_obra(obra):
            flash('Sin permisos para gestionar esta obra.', 'danger')
            return redirect(url_for('obras.detalle', id=obra_id))

        etapas = EtapaObra.query.filter_by(obra_id=obra_id).all()
        total_eliminadas = 0
        total_creadas = 0

        for etapa in etapas:
            tareas_predefinidas = obtener_tareas_por_etapa(etapa.nombre)
            if not tareas_predefinidas:
                continue

            asignacion_etapa = AsignacionObra.query.filter_by(
                obra_id=obra_id, etapa_id=etapa.id, activo=True
            ).first()
            responsable_id = asignacion_etapa.usuario_id if asignacion_etapa else None

            if not responsable_id:
                tareas_con_resp = TareaEtapa.query.filter(
                    TareaEtapa.etapa_id == etapa.id,
                    TareaEtapa.responsable_id.isnot(None)
                ).first()
                if tareas_con_resp:
                    responsable_id = tareas_con_resp.responsable_id

            tareas_actuales = TareaEtapa.query.filter_by(etapa_id=etapa.id).all()

            for tarea in tareas_actuales:
                try:
                    avances_count = TareaAvance.query.filter_by(tarea_id=tarea.id).count()
                except Exception:
                    avances_count = 0
                if avances_count == 0 and tarea.porcentaje_avance in (None, 0):
                    TareaMiembro.query.filter_by(tarea_id=tarea.id).delete()
                    db.session.delete(tarea)
                    total_eliminadas += 1

            db.session.flush()

            nombres_existentes = {t.nombre for t in TareaEtapa.query.filter_by(etapa_id=etapa.id).all()}

            for tarea_def in tareas_predefinidas:
                if tarea_def.get('si_aplica'):
                    continue
                if tarea_def['nombre'] in nombres_existentes:
                    continue

                nueva = TareaEtapa(
                    etapa_id=etapa.id,
                    nombre=tarea_def['nombre'],
                    estado='pendiente',
                    horas_estimadas=tarea_def.get('horas', 0),
                    unidad='un' if tarea_def.get('aplica_cantidad') is False else 'h',
                    responsable_id=responsable_id,
                )
                db.session.add(nueva)
                db.session.flush()

                if responsable_id:
                    db.session.add(TareaMiembro(tarea_id=nueva.id, user_id=responsable_id))

                total_creadas += 1

        db.session.commit()

        for etapa in etapas:
            try:
                distribuir_datos_etapa_a_tareas(etapa.id, forzar=True)
            except Exception:
                pass
        db.session.commit()

        flash(f'Tareas actualizadas: {total_eliminadas} eliminadas, {total_creadas} creadas con fechas encadenadas.', 'success')
        return redirect(url_for('obras.detalle', id=obra_id))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error recargando tareas: {e}", exc_info=True)
        flash(f'Error al recargar tareas: {str(e)[:200]}', 'danger')
        return redirect(url_for('obras.detalle', id=obra_id))


@obras_bp.route('/api/wizard-tareas/budget-preview', methods=['POST'])
@login_required
def wizard_budget_preview():
    """Endpoint stub para preview de presupuesto en wizard"""
    current_app.logger.warning("Intento de usar /api/wizard-tareas/budget-preview - funcionalidad no implementada")

    return jsonify({
        'ok': True,
        'total_estimado': 0,
        'mensaje': 'La estimacion de presupuesto no esta disponible. Continua con la creacion de tareas.'
    }), 200


@obras_bp.route('/api/wizard-tareas/create', methods=['POST'])
@login_required
def wizard_create_tasks():
    """Creacion masiva de tareas desde wizard"""
    try:
        data = request.get_json() or {}
        obra_id = data.get('obra_id')
        tareas_data = data.get('tareas', [])
        evitar_duplicados = data.get('evitar_duplicados', True)

        if not obra_id:
            return jsonify({'ok': False, 'error': 'obra_id requerido'}), 400

        if not tareas_data:
            return jsonify({'ok': False, 'error': 'No hay tareas para crear'}), 400

        obra = validate_obra_ownership(obra_id)
        if not can_manage_obra(obra):
            return jsonify({'ok': False, 'error': 'Sin permisos para gestionar esta obra'}), 403

        tareas_por_etapa = {}
        for tarea in tareas_data:
            etapa_key = tarea.get('etapa_slug') or tarea.get('etapa_nombre', '')
            if not etapa_key:
                continue
            if etapa_key not in tareas_por_etapa:
                tareas_por_etapa[etapa_key] = {
                    'nombre': tarea.get('etapa_nombre', etapa_key),
                    'slug': tarea.get('etapa_slug'),
                    'tareas': []
                }
            tareas_por_etapa[etapa_key]['tareas'].append(tarea)

        created_count = 0
        skipped_count = 0
        etapas_created = 0

        for etapa_key, etapa_info in tareas_por_etapa.items():
            etapa = EtapaObra.query.filter_by(
                obra_id=obra_id,
                nombre=etapa_info['nombre']
            ).first()

            if not etapa:
                ultimo_orden = db.session.query(db.func.max(EtapaObra.orden)).filter_by(obra_id=obra_id).scalar() or 0
                etapa = EtapaObra(
                    obra_id=obra_id,
                    nombre=etapa_info['nombre'],
                    descripcion=f"Etapa creada desde wizard",
                    orden=ultimo_orden + 1
                )
                db.session.add(etapa)
                db.session.flush()
                etapas_created += 1

            for tarea_data in etapa_info['tareas']:
                nombre_tarea = tarea_data.get('nombre', '').strip()
                if not nombre_tarea:
                    continue

                if evitar_duplicados:
                    existe = TareaEtapa.query.filter_by(
                        etapa_id=etapa.id,
                        nombre=nombre_tarea
                    ).first()
                    if existe:
                        skipped_count += 1
                        continue

                fecha_inicio = parse_date(tarea_data.get('fecha_inicio'))
                fecha_fin = parse_date(tarea_data.get('fecha_fin'))

                VALID_UNITS = {'m2', 'ml', 'm3', 'un', 'h', 'kg'}
                unidad = tarea_data.get('unidad', 'h').lower()
                if unidad not in VALID_UNITS:
                    unidad = 'h'

                nueva_tarea = TareaEtapa(
                    etapa_id=etapa.id,
                    nombre=nombre_tarea,
                    horas_estimadas=tarea_data.get('horas'),
                    cantidad_planificada=tarea_data.get('cantidad'),
                    unidad=unidad,
                    fecha_inicio_plan=fecha_inicio,
                    fecha_fin_plan=fecha_fin,
                    prioridad=tarea_data.get('prioridad', 'media'),
                    responsable_id=tarea_data.get('asignado_usuario_id')
                )
                db.session.add(nueva_tarea)
                db.session.flush()

                asignado_id = tarea_data.get('asignado_usuario_id')
                if asignado_id:
                    try:
                        asignacion = TareaMiembro(
                            tarea_id=nueva_tarea.id,
                            user_id=int(asignado_id)
                        )
                        db.session.add(asignacion)
                    except Exception as e:
                        current_app.logger.warning(f"No se pudo asignar usuario {asignado_id} a tarea: {e}")

                created_count += 1

        db.session.commit()

        if etapas_created > 0:
            try:
                from services.dependency_service import asignar_niveles_por_defecto
                asignar_niveles_por_defecto(obra_id)
                db.session.commit()
            except Exception as e_dep:
                current_app.logger.warning(f"No se pudieron asignar niveles: {e_dep}")

        return jsonify({
            'ok': True,
            'creadas': created_count,
            'omitidas': skipped_count,
            'etapas_creadas': etapas_created,
            'mensaje': f'Se crearon {created_count} tareas en {etapas_created} etapas. {skipped_count} tareas omitidas por duplicados.'
        }), 200

    except Exception as e:
        current_app.logger.exception("Error en wizard_create_tasks")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
