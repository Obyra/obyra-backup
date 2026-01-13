"""
API endpoints para modo offline
Permite sincronización de datos para operarios sin conexión
"""

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from models import db
from models.core import Usuario, Organizacion
from models.projects import Obra, TareaEtapa, TareaAvance, EtapaObra, TareaResponsables

api_offline_bp = Blueprint('api_offline', __name__, url_prefix='/api/offline')


def get_current_org_id():
    """Obtener ID de organización actual del usuario."""
    from flask import session

    # Intentar obtener de session primero
    org_id = session.get('current_org_id')
    if org_id:
        return org_id

    # Fallback a organizacion_id del usuario
    if hasattr(current_user, 'organizacion_id'):
        return current_user.organizacion_id

    # Si el usuario no tiene organización, retornar None
    return None


@api_offline_bp.route('/mis-obras')
@login_required
def mis_obras():
    """
    Obtener obras del usuario para modo offline.
    Retorna obras con información básica para cache local.
    """
    try:
        org_id = get_current_org_id()

        # Si no hay org_id y no es super admin, retornar lista vacía
        if not org_id and not (hasattr(current_user, 'is_super_admin') and current_user.is_super_admin):
            current_app.logger.warning(f"Usuario {current_user.id} no tiene organización asignada")
            return jsonify({
                'ok': True,
                'obras': [],
                'total': 0,
                'message': 'Usuario sin organización asignada'
            })

        # Obtener obras según rol
        try:
            if hasattr(current_user, 'is_super_admin') and current_user.is_super_admin:
                # Super admin ve todas las obras activas
                if org_id:
                    obras = Obra.query.filter_by(organizacion_id=org_id, activo=True).all()
                else:
                    obras = Obra.query.filter_by(activo=True).limit(100).all()
            elif current_user.role in ('admin', 'pm'):
                obras = Obra.query.filter_by(organizacion_id=org_id, activo=True).all()
            else:
                # Operarios ven obras donde tienen tareas asignadas
                obras = db.session.query(Obra).join(EtapaObra).join(TareaEtapa).join(TareaResponsables).filter(
                    TareaResponsables.usuario_id == current_user.id,
                    Obra.activo == True
                ).distinct().all()
        except Exception as query_error:
            current_app.logger.error(f"Error en query de obras: {query_error}")
            return jsonify({
                'ok': True,
                'obras': [],
                'total': 0,
                'error': 'Error consultando obras'
            })

        obras_data = []
        for obra in obras:
            try:
                # Construir objeto de forma segura
                obra_dict = {
                    'id': obra.id,
                    'nombre': obra.nombre if obra.nombre else 'Sin nombre',
                    'direccion': obra.direccion if hasattr(obra, 'direccion') else '',
                    'estado': obra.estado if hasattr(obra, 'estado') else 'desconocido',
                }

                # Agregar campos opcionales de forma segura
                if hasattr(obra, 'fecha_inicio') and obra.fecha_inicio:
                    obra_dict['fecha_inicio'] = obra.fecha_inicio.isoformat()
                else:
                    obra_dict['fecha_inicio'] = None

                if hasattr(obra, 'fecha_fin_estimada') and obra.fecha_fin_estimada:
                    obra_dict['fecha_fin_estimada'] = obra.fecha_fin_estimada.isoformat()
                else:
                    obra_dict['fecha_fin_estimada'] = None

                if hasattr(obra, 'porcentaje_avance') and obra.porcentaje_avance:
                    obra_dict['porcentaje_avance'] = float(obra.porcentaje_avance)
                else:
                    obra_dict['porcentaje_avance'] = 0

                # Cliente nombre - manejar relación
                try:
                    if hasattr(obra, 'cliente') and obra.cliente:
                        obra_dict['cliente_nombre'] = obra.cliente.nombre
                    else:
                        obra_dict['cliente_nombre'] = None
                except Exception:
                    obra_dict['cliente_nombre'] = None

                # Updated at
                if hasattr(obra, 'updated_at') and obra.updated_at:
                    obra_dict['updated_at'] = obra.updated_at.isoformat()
                else:
                    obra_dict['updated_at'] = None

                obras_data.append(obra_dict)
            except Exception as obra_error:
                current_app.logger.error(f"Error procesando obra {obra.id}: {obra_error}")
                continue

        return jsonify({
            'ok': True,
            'obras': obras_data,
            'total': len(obras_data)
        })

    except Exception as e:
        import traceback
        current_app.logger.error(f"Error obteniendo obras offline: {e}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            'ok': False,
            'error': str(e),
            'traceback': traceback.format_exc() if current_app.debug else None
        }), 500


@api_offline_bp.route('/mis-tareas')
@login_required
def mis_tareas():
    """
    Obtener tareas asignadas al usuario para modo offline.
    """
    try:
        # Obtener tareas del usuario a través de TareaResponsables
        try:
            tareas = db.session.query(TareaEtapa).join(TareaResponsables).filter(
                TareaResponsables.usuario_id == current_user.id,
                TareaEtapa.estado.in_(['pendiente', 'en_curso'])
            ).all()
        except Exception as query_error:
            current_app.logger.error(f"Error en query de tareas: {query_error}")
            return jsonify({
                'ok': True,
                'tareas': [],
                'total': 0,
                'error': 'Error consultando tareas'
            })

        tareas_data = []
        for tarea in tareas:
            try:
                # Obtener la obra a través de la etapa de forma segura
                obra = None
                try:
                    if hasattr(tarea, 'etapa') and tarea.etapa:
                        if hasattr(tarea.etapa, 'obra'):
                            obra = tarea.etapa.obra
                except Exception:
                    pass

                tarea_dict = {
                    'id': tarea.id,
                    'nombre': tarea.nombre if hasattr(tarea, 'nombre') and tarea.nombre else 'Sin nombre',
                    'descripcion': tarea.descripcion if hasattr(tarea, 'descripcion') else '',
                    'estado': tarea.estado if hasattr(tarea, 'estado') else 'pendiente',
                    'porcentaje_avance': float(tarea.porcentaje_avance) if hasattr(tarea, 'porcentaje_avance') and tarea.porcentaje_avance else 0,
                    'obra_id': obra.id if obra else None,
                    'obra_nombre': obra.nombre if obra and hasattr(obra, 'nombre') else None,
                    'etapa_id': tarea.etapa_id if hasattr(tarea, 'etapa_id') else None,
                }

                # Etapa nombre
                try:
                    if hasattr(tarea, 'etapa') and tarea.etapa and hasattr(tarea.etapa, 'nombre'):
                        tarea_dict['etapa_nombre'] = tarea.etapa.nombre
                    else:
                        tarea_dict['etapa_nombre'] = None
                except Exception:
                    tarea_dict['etapa_nombre'] = None

                # Fechas
                if hasattr(tarea, 'fecha_inicio') and tarea.fecha_inicio:
                    tarea_dict['fecha_inicio'] = tarea.fecha_inicio.isoformat()
                else:
                    tarea_dict['fecha_inicio'] = None

                if hasattr(tarea, 'fecha_fin') and tarea.fecha_fin:
                    tarea_dict['fecha_fin'] = tarea.fecha_fin.isoformat()
                else:
                    tarea_dict['fecha_fin'] = None

                # Campos numéricos
                tarea_dict['unidad'] = tarea.unidad if hasattr(tarea, 'unidad') else None
                tarea_dict['cantidad_planificada'] = float(tarea.cantidad_planificada) if hasattr(tarea, 'cantidad_planificada') and tarea.cantidad_planificada else None
                tarea_dict['objetivo'] = float(tarea.objetivo) if hasattr(tarea, 'objetivo') and tarea.objetivo else None

                tareas_data.append(tarea_dict)
            except Exception as tarea_error:
                current_app.logger.error(f"Error procesando tarea {tarea.id}: {tarea_error}")
                continue

        return jsonify({
            'ok': True,
            'tareas': tareas_data,
            'total': len(tareas_data)
        })

    except Exception as e:
        import traceback
        current_app.logger.error(f"Error obteniendo tareas offline: {e}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            'ok': False,
            'error': str(e),
            'traceback': traceback.format_exc() if current_app.debug else None
        }), 500


@api_offline_bp.route('/tareas-obra/<int:obra_id>')
@login_required
def tareas_por_obra(obra_id):
    """
    Obtener todas las tareas de una obra específica.
    """
    try:
        # Obtener tareas a través de las etapas de la obra
        tareas = db.session.query(TareaEtapa).join(EtapaObra).filter(
            EtapaObra.obra_id == obra_id
        ).all()

        tareas_data = []
        for tarea in tareas:
            # Obtener responsables
            responsables = []
            for asig in tarea.asignaciones:
                if asig.usuario:
                    responsables.append({
                        'id': asig.usuario.id,
                        'nombre': asig.usuario.nombre
                    })

            tareas_data.append({
                'id': tarea.id,
                'nombre': tarea.nombre,
                'descripcion': tarea.descripcion,
                'estado': tarea.estado,
                'porcentaje_avance': float(tarea.porcentaje_avance) if tarea.porcentaje_avance else 0,
                'etapa_id': tarea.etapa_id,
                'etapa_nombre': tarea.etapa.nombre if tarea.etapa else None,
                'fecha_inicio': tarea.fecha_inicio.isoformat() if tarea.fecha_inicio else None,
                'fecha_fin': tarea.fecha_fin.isoformat() if tarea.fecha_fin else None,
                'responsables': responsables,
                'unidad': tarea.unidad,
                'cantidad_planificada': float(tarea.cantidad_planificada) if tarea.cantidad_planificada else None
            })

        return jsonify({
            'ok': True,
            'tareas': tareas_data,
            'obra_id': obra_id,
            'total': len(tareas_data)
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo tareas de obra: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_offline_bp.route('/crear-avance', methods=['POST'])
@login_required
def crear_avance():
    """
    Crear un avance de tarea (funciona para sincronización offline).
    """
    try:
        data = request.get_json() or {}

        tarea_id = data.get('tarea_id')
        if not tarea_id:
            return jsonify({'ok': False, 'error': 'tarea_id es requerido'}), 400

        tarea = TareaEtapa.query.get(tarea_id)
        if not tarea:
            return jsonify({'ok': False, 'error': 'Tarea no encontrada'}), 404

        # Crear avance
        avance = TareaAvance(
            tarea_id=tarea_id,
            usuario_id=current_user.id,
            descripcion=data.get('descripcion', ''),
            cantidad_ingresada=data.get('cantidad_ingresada', 0),
            unidad_ingresada=data.get('unidad', tarea.unidad),
            status='pendiente'
        )

        db.session.add(avance)

        # Actualizar porcentaje de la tarea si se proporciona
        if data.get('porcentaje'):
            tarea.porcentaje_avance = data.get('porcentaje')
            if float(data.get('porcentaje')) >= 100:
                tarea.estado = 'completada'
            elif float(data.get('porcentaje')) > 0:
                tarea.estado = 'en_curso'

        db.session.commit()

        return jsonify({
            'ok': True,
            'avance_id': avance.id,
            'message': 'Avance registrado correctamente',
            'offline_id': data.get('offline_id')
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creando avance: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_offline_bp.route('/actualizar-tarea/<int:tarea_id>', methods=['PUT'])
@login_required
def actualizar_tarea(tarea_id):
    """
    Actualizar estado/progreso de una tarea.
    """
    try:
        tarea = TareaEtapa.query.get(tarea_id)
        if not tarea:
            return jsonify({'ok': False, 'error': 'Tarea no encontrada'}), 404

        data = request.get_json() or {}

        if 'estado' in data:
            tarea.estado = data['estado']

        if 'porcentaje_avance' in data:
            tarea.porcentaje_avance = data['porcentaje_avance']

        db.session.commit()

        return jsonify({
            'ok': True,
            'message': 'Tarea actualizada',
            'tarea_id': tarea_id
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error actualizando tarea: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_offline_bp.route('/inventario-basico')
@login_required
def inventario_basico():
    """
    Obtener lista básica de inventario para búsqueda offline.
    """
    try:
        from models.inventory import ItemInventario

        org_id = get_current_org_id()
        limit = request.args.get('limit', 1000, type=int)

        items = ItemInventario.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).limit(limit).all()

        items_data = []
        for item in items:
            items_data.append({
                'id': item.id,
                'codigo': item.codigo,
                'nombre': item.nombre,
                'unidad': item.unidad,
                'categoria_id': item.categoria_id
            })

        return jsonify({
            'ok': True,
            'items': items_data,
            'total': len(items_data)
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo inventario: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_offline_bp.route('/sync-status')
@login_required
def sync_status():
    """
    Obtener estado de última sincronización y datos disponibles.
    """
    try:
        org_id = get_current_org_id()
        from models.inventory import ItemInventario
        from datetime import datetime

        # Contar tareas del usuario
        tareas_count = db.session.query(TareaEtapa).join(TareaResponsables).filter(
            TareaResponsables.usuario_id == current_user.id,
            TareaEtapa.estado.in_(['pendiente', 'en_curso'])
        ).count()

        stats = {
            'obras': Obra.query.filter_by(organizacion_id=org_id, activo=True).count(),
            'tareas_pendientes': tareas_count,
            'inventario': ItemInventario.query.filter_by(organizacion_id=org_id, activo=True).count(),
            'server_time': datetime.utcnow().isoformat()
        }

        return jsonify({
            'ok': True,
            'stats': stats,
            'user_id': current_user.id,
            'org_id': org_id
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo estado sync: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_offline_bp.route('/sync-batch', methods=['POST'])
@login_required
def sync_batch():
    """
    Sincronizar múltiples operaciones en un solo request.
    """
    try:
        data = request.get_json() or {}
        operations = data.get('operations', [])

        results = []

        for op in operations:
            op_type = op.get('type')
            op_data = op.get('data', {})

            try:
                if op_type == 'CREATE_AVANCE':
                    tarea = TareaEtapa.query.get(op_data.get('tarea_id'))
                    if tarea:
                        avance = TareaAvance(
                            tarea_id=op_data.get('tarea_id'),
                            usuario_id=current_user.id,
                            descripcion=op_data.get('descripcion', ''),
                            cantidad_ingresada=op_data.get('cantidad_ingresada', 0),
                            status='pendiente'
                        )
                        db.session.add(avance)

                        if op_data.get('porcentaje'):
                            tarea.porcentaje_avance = op_data.get('porcentaje')

                        results.append({
                            'offline_id': op_data.get('offline_id'),
                            'success': True,
                            'server_id': avance.id
                        })
                    else:
                        results.append({
                            'offline_id': op_data.get('offline_id'),
                            'success': False,
                            'error': 'Tarea no encontrada'
                        })

                elif op_type == 'UPDATE_TAREA':
                    tarea = TareaEtapa.query.get(op_data.get('id'))
                    if tarea:
                        if 'estado' in op_data:
                            tarea.estado = op_data['estado']
                        if 'porcentaje_avance' in op_data:
                            tarea.porcentaje_avance = op_data['porcentaje_avance']

                        results.append({
                            'offline_id': op_data.get('offline_id'),
                            'success': True
                        })
                    else:
                        results.append({
                            'offline_id': op_data.get('offline_id'),
                            'success': False,
                            'error': 'Tarea no encontrada'
                        })

            except Exception as op_error:
                results.append({
                    'offline_id': op_data.get('offline_id'),
                    'success': False,
                    'error': str(op_error)
                })

        db.session.commit()

        return jsonify({
            'ok': True,
            'results': results,
            'synced': len([r for r in results if r.get('success')]),
            'failed': len([r for r in results if not r.get('success')])
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en sync batch: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
