"""
Blueprint Admin Metrics
=======================

Expone métricas de negocio para super admins.

Rutas:
- GET /admin/metrics              → Vista HTML
- GET /admin/metrics.json         → JSON para sistemas de monitoreo
- GET /admin/metrics/prometheus   → Formato Prometheus

Acceso: solo super admins (is_super_admin=True).
"""

from flask import Blueprint, render_template, jsonify, abort, Response
from flask_login import login_required, current_user
from services.metrics_service import (
    get_cached_metrics,
    get_business_metrics,
    format_prometheus,
)


admin_metrics_bp = Blueprint('admin_metrics', __name__, url_prefix='/admin/metrics')


def _require_super_admin():
    """Helper: aborta con 403 si no es super admin."""
    if not current_user.is_authenticated:
        abort(401)
    if not getattr(current_user, 'is_super_admin', False):
        abort(403)


@admin_metrics_bp.route('/')
@login_required
def metrics_view():
    """Vista HTML de métricas para super admin."""
    _require_super_admin()
    metrics = get_cached_metrics()
    return render_template('admin/metrics.html', metrics=metrics)


@admin_metrics_bp.route('/json')
@login_required
def metrics_json():
    """Métricas en JSON (para sistemas de monitoreo)."""
    _require_super_admin()
    metrics = get_cached_metrics()
    return jsonify(metrics)


@admin_metrics_bp.route('/refresh')
@login_required
def metrics_refresh():
    """Forzar recálculo de métricas (sin caché)."""
    _require_super_admin()
    metrics = get_business_metrics()
    return jsonify(metrics)


@admin_metrics_bp.route('/prometheus')
@login_required
def metrics_prometheus():
    """Métricas en formato Prometheus."""
    _require_super_admin()
    metrics = get_cached_metrics()
    output = format_prometheus(metrics)
    return Response(output, mimetype='text/plain; version=0.0.4')
