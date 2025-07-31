"""
Módulo Asistente Inteligente - OBYRA IA (SIMPLIFICADO)
Todas las funciones del asistente han sido integradas al dashboard principal
"""

from flask import Blueprint, redirect, url_for
from flask_login import login_required

asistente_bp = Blueprint('asistente', __name__)

@asistente_bp.route('/')
@asistente_bp.route('/dashboard') 
@asistente_bp.route('/control')
@login_required
def dashboard():
    """Redirigir al dashboard principal del sistema"""
    return redirect(url_for('reportes.dashboard'))

# Eliminar cualquier otra ruta relacionada con configuración inicial o asistente