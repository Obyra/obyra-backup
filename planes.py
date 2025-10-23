from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app.extensions import db
from models import Usuario

planes_bp = Blueprint('planes', __name__, url_prefix='/planes')

@planes_bp.route('/')
def mostrar_planes():
    """Página de planes de suscripción"""
    return render_template('planes/planes.html')

@planes_bp.route('/standard')
def plan_standard():
    """Redirigir a pago de plan Standard"""
    # Aquí se puede agregar la lógica de tracking o preparación para el pago
    # Por ahora retorna a planes con mensaje
    flash('Redirigiendo a Mercado Pago para Plan Standard...', 'info')
    # TODO: Redirigir a URL de Mercado Pago cuando esté disponible
    return redirect(url_for('planes.mostrar_planes'))

@planes_bp.route('/premium')
def plan_premium():
    """Redirigir a pago de plan Premium"""
    # Aquí se puede agregar la lógica de tracking o preparación para el pago
    flash('Redirigiendo a Mercado Pago para Plan Premium...', 'info')
    # TODO: Redirigir a URL de Mercado Pago cuando esté disponible
    return redirect(url_for('planes.mostrar_planes'))

def verificar_periodo_prueba(usuario):
    """Verifica si el usuario ha cumplido los 30 días de prueba"""
    if not usuario.fecha_registro:
        return False
    
    fecha_limite = usuario.fecha_registro + timedelta(days=30)
    return datetime.utcnow() > fecha_limite

def usuario_requiere_plan():
    """Middleware para verificar si el usuario necesita seleccionar un plan"""
    if not current_user.is_authenticated:
        return False
    
    # Si ya tiene un plan activo, no necesita seleccionar
    if hasattr(current_user, 'plan_activo') and current_user.plan_activo:
        return False
    
    # Verificar si han pasado 30 días desde el registro
    return verificar_periodo_prueba(current_user)