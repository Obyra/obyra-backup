"""
Blueprint Legal - Terminos y Condiciones, Politica de Privacidad, Cookies.
Rutas publicas (no requieren login).
"""
from flask import Blueprint, render_template
from datetime import date

legal_bp = Blueprint('legal', __name__)

VIGENCIA = date(2026, 4, 8)


@legal_bp.route('/terminos')
def terminos():
    return render_template('legal/terminos.html', vigencia=VIGENCIA)


@legal_bp.route('/privacidad')
def privacidad():
    return render_template('legal/privacidad.html', vigencia=VIGENCIA)


@legal_bp.route('/cookies')
def cookies():
    return render_template('legal/cookies.html', vigencia=VIGENCIA)
