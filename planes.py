from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta, date
from decimal import Decimal
from app import db
from models import Usuario
from config.billing_config import BILLING

planes_bp = Blueprint('planes', __name__, url_prefix='/planes')

# Precio del plan en USD
PLAN_PRECIO_USD = Decimal('250.00')


def obtener_cotizacion_bna():
    """
    Obtiene la cotización del dólar vendedor del Banco Nación.
    Retorna la tasa y la fecha.
    """
    try:
        from services.exchange.providers.bna import fetch_official_rate
        from services.exchange.base import ensure_rate

        snapshot = ensure_rate(
            provider='bna_html',
            base_currency='ARS',
            quote_currency='USD',
            fetcher=fetch_official_rate,
            fallback_rate=Decimal('1100.0')  # Fallback en caso de error
        )
        return {
            'value': float(snapshot.value),
            'as_of_date': snapshot.as_of_date.isoformat() if snapshot.as_of_date else date.today().isoformat(),
            'provider': snapshot.provider,
            'success': True
        }
    except Exception as e:
        # Retornar un fallback si hay error
        return {
            'value': 1100.0,
            'as_of_date': date.today().isoformat(),
            'provider': 'fallback',
            'success': False,
            'error': str(e)
        }


@planes_bp.route('/api/cotizacion')
def api_cotizacion():
    """API endpoint para obtener cotización USD/ARS del BNA."""
    cotizacion = obtener_cotizacion_bna()

    # Calcular precio en ARS
    precio_ars = PLAN_PRECIO_USD * Decimal(str(cotizacion['value']))

    return jsonify({
        'cotizacion': cotizacion,
        'plan': {
            'nombre': 'OBYRA Pro',
            'precio_usd': float(PLAN_PRECIO_USD),
            'precio_ars': float(precio_ars.quantize(Decimal('0.01'))),
        }
    })


@planes_bp.route('/')
def mostrar_planes():
    """Página de planes de suscripción"""
    # Obtener cotización actual
    cotizacion = obtener_cotizacion_bna()
    precio_ars = PLAN_PRECIO_USD * Decimal(str(cotizacion['value']))

    return render_template('planes/planes.html',
        precio_usd=float(PLAN_PRECIO_USD),
        precio_ars=float(precio_ars.quantize(Decimal('0.01'))),
        cotizacion=cotizacion
    )


@planes_bp.route('/pagar')
@login_required
def instrucciones_pago():
    """Página con instrucciones de pago por transferencia bancaria."""
    # Obtener cotización actual
    cotizacion = obtener_cotizacion_bna()
    precio_ars = PLAN_PRECIO_USD * Decimal(str(cotizacion['value']))

    # Obtener datos bancarios
    bank_info = BILLING.get_bank_info()

    return render_template('planes/instrucciones_pago.html',
        precio_usd=float(PLAN_PRECIO_USD),
        precio_ars=float(precio_ars.quantize(Decimal('0.01'))),
        cotizacion=cotizacion,
        bank_info=bank_info,
        user=current_user
    )


@planes_bp.route('/standard')
def plan_standard():
    """Redirigir a instrucciones de pago"""
    return redirect(url_for('planes.instrucciones_pago'))


@planes_bp.route('/premium')
def plan_premium():
    """Redirigir a instrucciones de pago"""
    return redirect(url_for('planes.instrucciones_pago'))

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