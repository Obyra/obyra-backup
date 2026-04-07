"""Obras -- Admin routes."""
from flask import flash, redirect, url_for
from flask_login import login_required, current_user
from extensions import db
from extensions import limiter
from models import Obra, EtapaObra, TareaEtapa, AsignacionObra

from obras import obras_bp


@obras_bp.route('/super-admin/reiniciar-sistema', methods=['POST'])
@login_required
@limiter.limit("1 per minute")
def reiniciar_sistema():
    if not current_user.is_super_admin:
        flash('No tienes permisos para reiniciar el sistema.', 'danger')
        return redirect(url_for('obras.lista'))

    try:
        AsignacionObra.query.delete()
        TareaEtapa.query.delete()
        EtapaObra.query.delete()
        Obra.query.delete()

        db.session.commit()
        flash('Sistema reiniciado exitosamente. Todas las obras han sido eliminadas.', 'success')
    except Exception:
        db.session.rollback()
        flash('Error al reiniciar el sistema. Intentalo nuevamente.', 'danger')

    return redirect(url_for('obras.lista'))
