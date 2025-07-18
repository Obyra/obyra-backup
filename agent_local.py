from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user, login_required

agent_bp = Blueprint('agent_local', __name__)


@agent_bp.route('/diagnostico-agent')
@login_required
def diagnostico_agent():
    if not current_user.rol == 'administrador':
        return redirect(url_for('reportes.dashboard'))  # Redirige si no es admin

    return render_template('asistente/diagnostico_agent.html', user=current_user)
