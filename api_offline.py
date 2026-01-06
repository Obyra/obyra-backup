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
            # Operarios ven obras donde tienen tareas asignadas
            obras = db.session.query(Obra).join(EtapaObra).join(TareaEtapa).join(TareaResponsables).filter(
                TareaResponsables.usuario_id == current_user.id,
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
                'porcentaje_avance': float(obra.porcentaje_avance) if obra.porcentaje_avance else 0,
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
        # Obtener tareas del usuario a través de TareaResponsables
        tareas = db.session.query(TareaEtapa).join(TareaResponsables).filter(
            TareaResponsables.usuario_id == current_user.id,
            TareaEtapa.estado.in_(['pendiente', 'en_curso'])
        ).all()

        tareas_data = []
        for tarea in tareas:
            # Obtener la obra a través de la etapa
            obra = tarea.etapa.obra if tarea.etapa else None

            tareas_data.append({
                'id': tarea.id,
                'nombre': tarea.nombre,
                'descripcion': tarea.descripcion,
                'estado': tarea.estado,
                'porcentaje_avance': float(tarea.porcentaje_avance) if tarea.porcentaje_avance else 0,
                'obra_id': obra.id if obra else None,
                'obra_nombre': obra.nombre if obra else None,
                'etapa_id': tarea.etapa_id,
                'etapa_nombre': tarea.etapa.nombre if tarea.etapa else None,
                'fecha_inicio': tarea.fecha_inicio.isoformat() if tarea.fecha_inicio else None,
                'fecha_fin': tarea.fecha_fin.isoformat() if tarea.fecha_fin else None,
                'unidad': tarea.unidad,
                'cantidad_planificada': float(tarea.cantidad_planificada) if tarea.cantidad_planificada else None,
                'objetivo': float(tarea.objetivo) if tarea.objetivo else None
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
