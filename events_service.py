"""
Service para gestión de eventos del sistema.
Maneja la creación de eventos desde otros módulos y API endpoints para consultar eventos.
"""

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from models import Event, Obra, db
from sqlalchemy import desc
from datetime import datetime, timedelta
import logging

# Blueprint para endpoints de eventos
events_bp = Blueprint('events', __name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@events_bp.route('/api/events')
@login_required
def get_events():
    """
    Endpoint GET /api/events para obtener eventos del feed de actividad
    Parámetros de query:
    - limit: cantidad de eventos (default: 25, max: 100)
    - offset: paginación (default: 0)
    - project_id: filtrar por obra específica
    - type: filtrar por tipo de evento
    - severity: filtrar por severidad
    """
    try:
        # Parámetros con validación
        limit = min(int(request.args.get('limit', 25)), 100)
        offset = max(int(request.args.get('offset', 0)), 0)
        project_id = request.args.get('project_id', type=int)
        event_type = request.args.get('type')
        severity = request.args.get('severity')
        
        # Query base filtrado por company_id del usuario
        query = Event.query.filter(Event.company_id == current_user.organizacion_id)
        
        # Aplicar filtros opcionales
        if project_id:
            query = query.filter(Event.project_id == project_id)
        
        if event_type:
            valid_types = ['alert', 'milestone', 'delay', 'cost_overrun', 'stock_low', 
                          'status_change', 'budget_created', 'inventory_alert', 'custom']
            if event_type in valid_types:
                query = query.filter(Event.type == event_type)
            else:
                return jsonify({'error': 'Tipo de evento inválido'}), 400
        
        if severity:
            valid_severities = ['baja', 'media', 'alta', 'critica']
            if severity in valid_severities:
                query = query.filter(Event.severity == severity)
            else:
                return jsonify({'error': 'Severidad inválida'}), 400
        
        # Ejecutar query con paginación
        events = query.order_by(desc(Event.created_at)).offset(offset).limit(limit).all()
        total = query.count()
        
        # Serializar eventos
        events_data = []
        for event in events:
            event_data = {
                'id': event.id,
                'type': event.type,
                'severity': event.severity,
                'title': event.title,
                'description': event.description,
                'created_at': event.created_at.isoformat(),
                'time_ago': event.time_ago,
                'meta': event.meta,
                'project': None,
                'user': None
            }
            
            # Incluir información de la obra si existe
            if event.project:
                event_data['project'] = {
                    'id': event.project.id,
                    'nombre': event.project.nombre,
                    'direccion': event.project.direccion
                }
            
            # Incluir información del usuario si existe
            if event.user:
                event_data['user'] = {
                    'id': event.user.id,
                    'nombre': f"{event.user.nombre} {event.user.apellido}",
                    'rol': event.user.rol
                }
            
            events_data.append(event_data)
        
        return jsonify({
            'events': events_data,
            'total': total,
            'limit': limit,
            'offset': offset,
            'has_more': offset + limit < total
        })
        
    except ValueError as e:
        return jsonify({'error': 'Parámetros inválidos'}), 400
    except Exception as e:
        logger.error(f"Error en get_events: {str(e)}")
        return jsonify({'error': 'Error interno del servidor'}), 500


@events_bp.route('/api/events/custom', methods=['POST'])
@login_required
def create_custom_event():
    """
    Endpoint POST /api/events/custom para crear eventos personalizados
    Solo disponible para administradores de empresa
    """
    try:
        # Verificar permisos
        if current_user.rol not in ['administrador']:
            return jsonify({'error': 'Sin permisos para crear eventos personalizados'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Datos JSON requeridos'}), 400
        
        # Validar datos requeridos
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        
        if not title:
            return jsonify({'error': 'Título requerido'}), 400
        
        # Validar datos opcionales
        project_id = data.get('project_id', type=int)
        severity = data.get('severity', 'media')
        meta = data.get('meta', {})
        
        if severity not in ['baja', 'media', 'alta', 'critica']:
            severity = 'media'
        
        # Verificar que el proyecto pertenece a la organización si se especifica
        if project_id:
            obra = Obra.query.filter_by(
                id=project_id, 
                organizacion_id=current_user.organizacion_id
            ).first()
            if not obra:
                return jsonify({'error': 'Obra no encontrada o sin acceso'}), 404
        
        # Crear evento
        event = Event(
            company_id=current_user.organizacion_id,
            project_id=project_id,
            user_id=current_user.id,
            type='custom',
            severity=severity,
            title=title,
            description=description,
            meta=meta,
            created_by=current_user.id
        )
        
        db.session.add(event)
        db.session.commit()
        
        logger.info(f"Evento personalizado creado por usuario {current_user.id}: {title}")
        
        return jsonify({
            'message': 'Evento creado exitosamente',
            'event_id': event.id
        }), 201
        
    except Exception as e:
        logger.error(f"Error en create_custom_event: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor'}), 500


# Funciones helper para crear eventos desde otros módulos

def create_obra_status_change_event(obra_id, old_status, new_status, user_id=None):
    """Crear evento cuando cambia el estado de una obra"""
    try:
        obra = Obra.query.get(obra_id)
        if not obra:
            logger.warning(f"Obra {obra_id} no encontrada para evento de cambio de estado")
            return None
        
        event = Event.create_status_change_event(
            company_id=obra.organizacion_id,
            project_id=obra_id,
            old_status=old_status,
            new_status=new_status,
            user_id=user_id
        )
        
        db.session.commit()
        logger.info(f"Evento de cambio de estado creado para obra {obra_id}")
        return event
        
    except Exception as e:
        logger.error(f"Error creando evento de cambio de estado: {str(e)}")
        db.session.rollback()
        return None


def create_presupuesto_created_event(presupuesto_id, obra_id, total, user_id=None):
    """Crear evento cuando se crea un nuevo presupuesto"""
    try:
        obra = Obra.query.get(obra_id)
        if not obra:
            logger.warning(f"Obra {obra_id} no encontrada para evento de presupuesto")
            return None
        
        event = Event.create_budget_event(
            company_id=obra.organizacion_id,
            project_id=obra_id,
            budget_id=presupuesto_id,
            budget_total=total,
            user_id=user_id
        )
        
        db.session.commit()
        logger.info(f"Evento de presupuesto creado para obra {obra_id}")
        return event
        
    except Exception as e:
        logger.error(f"Error creando evento de presupuesto: {str(e)}")
        db.session.rollback()
        return None


def create_stock_alert_event(company_id, item_name, current_stock, min_stock, user_id=None):
    """Crear evento de alerta de stock bajo"""
    try:
        event = Event.create_inventory_alert_event(
            company_id=company_id,
            item_name=item_name,
            current_stock=current_stock,
            min_stock=min_stock,
            user_id=user_id
        )
        
        db.session.commit()
        logger.info(f"Evento de stock bajo creado para {item_name}")
        return event
        
    except Exception as e:
        logger.error(f"Error creando evento de stock bajo: {str(e)}")
        db.session.rollback()
        return None


def create_alert_event(company_id, project_id, title, description, severity='media', user_id=None, meta=None):
    """Crear evento de alerta general"""
    try:
        event = Event.create_alert_event(
            company_id=company_id,
            project_id=project_id,
            title=title,
            description=description,
            severity=severity,
            user_id=user_id,
            meta=meta
        )
        
        db.session.commit()
        logger.info(f"Evento de alerta creado: {title}")
        return event
        
    except Exception as e:
        logger.error(f"Error creando evento de alerta: {str(e)}")
        db.session.rollback()
        return None