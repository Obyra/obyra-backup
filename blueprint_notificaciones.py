"""
Blueprint de Notificaciones
Gestiona las notificaciones internas del sistema
"""

from flask import Blueprint, render_template, jsonify, request, url_for
from flask_login import login_required, current_user
from extensions import db
from datetime import datetime

notificaciones_bp = Blueprint('notificaciones', __name__, url_prefix='/notificaciones')


@notificaciones_bp.route('/')
@login_required
def lista():
    """Lista completa de notificaciones del usuario"""
    from models.core import Notificacion

    page = request.args.get('page', 1, type=int)
    per_page = 20

    notificaciones = Notificacion.query.filter_by(
        usuario_id=current_user.id
    ).order_by(
        Notificacion.fecha_creacion.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'notificaciones/lista.html',
        notificaciones=notificaciones
    )


@notificaciones_bp.route('/api/recientes')
@login_required
def api_recientes():
    """API: Obtiene las notificaciones recientes del usuario"""
    from models.core import Notificacion

    try:
        notifs = Notificacion.obtener_recientes(current_user.id, limite=10)
        no_leidas = Notificacion.contar_no_leidas(current_user.id)

        return jsonify({
            'ok': True,
            'notificaciones': [n.to_dict() for n in notifs],
            'no_leidas': no_leidas
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@notificaciones_bp.route('/api/marcar-leida/<int:id>', methods=['POST'])
@login_required
def api_marcar_leida(id):
    """API: Marca una notificación como leída"""
    from models.core import Notificacion

    try:
        notif = Notificacion.query.filter_by(
            id=id,
            usuario_id=current_user.id
        ).first()

        if notif:
            notif.marcar_leida()
            db.session.commit()

        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@notificaciones_bp.route('/api/marcar-todas-leidas', methods=['POST'])
@login_required
def api_marcar_todas_leidas():
    """API: Marca todas las notificaciones del usuario como leídas"""
    from models.core import Notificacion

    try:
        Notificacion.query.filter_by(
            usuario_id=current_user.id,
            leida=False
        ).update({
            'leida': True,
            'fecha_lectura': datetime.utcnow()
        })
        db.session.commit()

        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@notificaciones_bp.route('/api/count')
@login_required
def api_count():
    """API: Cuenta las notificaciones no leídas"""
    from models.core import Notificacion

    try:
        count = Notificacion.contar_no_leidas(current_user.id)
        return jsonify({'ok': True, 'count': count})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@notificaciones_bp.route('/api/eliminar/<int:id>', methods=['POST', 'DELETE'])
@login_required
def api_eliminar(id):
    """API: Elimina una notificación"""
    from models.core import Notificacion

    try:
        notif = Notificacion.query.filter_by(
            id=id,
            usuario_id=current_user.id
        ).first()

        if notif:
            db.session.delete(notif)
            db.session.commit()

        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
