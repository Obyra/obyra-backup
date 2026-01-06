"""
API endpoints para modo offline
Permite sincronización de datos para operarios sin conexión
"""

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from models import db
from models.core import Usuario, Organizacion
from models.projects import Obra, Tarea, AvanceTarea

api_offline_bp = Blueprint('api_offline', __name__, url_prefix='/api/offline')


def get_current_org_id():
    """Obtener ID de organización actual del usuario."""
    from flask import session
    return session.get('current_org_id') or getattr(current_user, 'organizacion_id', None)


@api_offline_bp.route('/mis-obras')
@login_required
def mis_obras():
    """
    Obtener obras del usuario para modo offline.
    Retorna obras con información básica para cache local.
    """
    try:
        org_id = get_current_org_id()

        # Obtener obras según rol
        if current_user.is_super_admin or current_user.role in ('admin', 'pm'):
            obras = Obra.query.filter_by(organizacion_id=org_id, activo=True).all()
        else:
            # Operarios solo ven obras donde tienen tareas asignadas
            obras = db.session.query(Obra).join(Tarea).filter(
                Tarea.asignado_a_id == current_user.id,
                Obra.activo == True
            ).distinct().all()

        obras_data = []
        for obra in obras:
            obras_data.append({
                'id': obra.id,
                'nombre': obra.nombre,
                'direccion': obra.direccion,
                'estado': obra.estado,
                'fecha_inicio': obra.fecha_inicio.isoformat() if obra.fecha_inicio else None,
                'fecha_fin_estimada': obra.fecha_fin_estimada.isoformat() if obra.fecha_fin_estimada else None,
                'porcentaje_avance': obra.porcentaje_avance or 0,
                'cliente_nombre': obra.cliente.nombre if obra.cliente else None,
                'updated_at': obra.updated_at.isoformat() if hasattr(obra, 'updated_at') and obra.updated_at else None
            })

        return jsonify({
            'ok': True,
            'obras': obras_data,
            'total': len(obras_data)
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo obras offline: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_offline_bp.route('/mis-tareas')
@login_required
def mis_tareas():
    """
    Obtener tareas asignadas al usuario para modo offline.
    """
    try:
        # Obtener tareas del usuario
        tareas = Tarea.query.filter_by(
            asignado_a_id=current_user.id
        ).filter(
            Tarea.estado.in_(['pendiente', 'en_progreso'])
        ).all()

        tareas_data = []
        for tarea in tareas:
            tareas_data.append({
                'id': tarea.id,
                'titulo': tarea.titulo,
                'descripcion': tarea.descripcion,
                'estado': tarea.estado,
                'prioridad': tarea.prioridad,
                'porcentaje_avance': tarea.porcentaje_avance or 0,
                'obra_id': tarea.obra_id,
                'obra_nombre': tarea.obra.nombre if tarea.obra else None,
                'fecha_inicio': tarea.fecha_inicio.isoformat() if tarea.fecha_inicio else None,
                'fecha_fin': tarea.fecha_fin.isoformat() if tarea.fecha_fin else None,
                'asignado_a': current_user.id,
                'etapa': tarea.etapa,
                'unidad': tarea.unidad,
                'cantidad_total': float(tarea.cantidad_total) if tarea.cantidad_total else None,
                'cantidad_ejecutada': float(tarea.cantidad_ejecutada) if tarea.cantidad_ejecutada else 0
            })

        return jsonify({
            'ok': True,
            'tareas': tareas_data,
            'total': len(tareas_data)
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo tareas offline: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@api_offline_bp.route('/tareas-obra/<int:obra_id>')
@login_required
def tareas_por_obra(obra_id):
    """
    Obtener todas las tareas de una obra específica.
    """
    try:
        tareas = Tarea.query.filter_by(obra_id=obra_id).all()

        tareas_data = []
        for tarea in tareas:
            asignado = None
            if tarea.asignado_a:
                asignado = {
                    'id': tarea.asignado_a.id,
                    'nombre': tarea.asignado_a.nombre
                }

            tareas_data.append({
                'id': tarea.id,
                'titulo': tarea.titulo,
                'descripcion': tarea.descripcion,
                'estado': tarea.estado,
                'prioridad': tarea.prioridad,
                'porcentaje_avance': tarea.porcentaje_avance or 0,
                'obra_id': tarea.obra_id,
                'fecha_inicio': tarea.fecha_inicio.isoformat() if tarea.fecha_inicio else None,
                'fecha_fin': tarea.fecha_fin.isoformat() if tarea.fecha_fin else None,
                'asignado_a': tarea.asignado_a_id,
                'asignado_info': asignado,
                'etapa': tarea.etapa,
                'unidad': tarea.unidad,
                'cantidad_total': float(tarea.cantidad_total) if tarea.cantidad_total else None,
                'cantidad_ejecutada': float(tarea.cantidad_ejecutada) if tarea.cantidad_ejecutada else 0
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

        tarea = Tarea.query.get(tarea_id)
        if not tarea:
            return jsonify({'ok': False, 'error': 'Tarea no encontrada'}), 404

        # Crear avance
        avance = AvanceTarea(
            tarea_id=tarea_id,
            usuario_id=current_user.id,
            descripcion=data.get('descripcion', ''),
            porcentaje=data.get('porcentaje', 0),
            horas_trabajadas=data.get('horas_trabajadas'),
            observaciones=data.get('observaciones'),
            cantidad_ejecutada=data.get('cantidad_ejecutada')
        )

        db.session.add(avance)

        # Actualizar porcentaje de la tarea
        if data.get('porcentaje'):
            tarea.porcentaje_avance = data.get('porcentaje')
            if data.get('porcentaje') >= 100:
                tarea.estado = 'completada'
            elif data.get('porcentaje') > 0:
                tarea.estado = 'en_progreso'

        # Actualizar cantidad ejecutada
        if data.get('cantidad_ejecutada'):
            tarea.cantidad_ejecutada = (tarea.cantidad_ejecutada or 0) + float(data.get('cantidad_ejecutada'))

        db.session.commit()

        return jsonify({
            'ok': True,
            'avance_id': avance.id,
            'message': 'Avance registrado correctamente',
            'offline_id': data.get('offline_id')  # Para matching en sincronización
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
        tarea = Tarea.query.get(tarea_id)
        if not tarea:
            return jsonify({'ok': False, 'error': 'Tarea no encontrada'}), 404

        data = request.get_json() or {}

        if 'estado' in data:
            tarea.estado = data['estado']

        if 'porcentaje_avance' in data:
            tarea.porcentaje_avance = data['porcentaje_avance']

        if 'cantidad_ejecutada' in data:
            tarea.cantidad_ejecutada = data['cantidad_ejecutada']

        if 'observaciones' in data:
            tarea.observaciones = data['observaciones']

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
    Solo nombres, códigos y unidades (sin precios para optimizar).
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

        # Contar datos disponibles
        from models.inventory import ItemInventario

        stats = {
            'obras': Obra.query.filter_by(organizacion_id=org_id, activo=True).count(),
            'tareas_pendientes': Tarea.query.filter_by(asignado_a_id=current_user.id).filter(
                Tarea.estado.in_(['pendiente', 'en_progreso'])
            ).count(),
            'inventario': ItemInventario.query.filter_by(organizacion_id=org_id, activo=True).count(),
            'server_time': db.func.now()
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
    Útil para cuando el operario vuelve a tener conexión.
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
                    # Crear avance
                    tarea = Tarea.query.get(op_data.get('tarea_id'))
                    if tarea:
                        avance = AvanceTarea(
                            tarea_id=op_data.get('tarea_id'),
                            usuario_id=current_user.id,
                            descripcion=op_data.get('descripcion', ''),
                            porcentaje=op_data.get('porcentaje', 0),
                            horas_trabajadas=op_data.get('horas_trabajadas'),
                            observaciones=op_data.get('observaciones')
                        )
                        db.session.add(avance)

                        # Actualizar tarea
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
                    tarea = Tarea.query.get(op_data.get('id'))
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
