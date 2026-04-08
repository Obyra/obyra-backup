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
    get_organizaciones_detalle,
    get_usuarios_detalle,
    get_obras_detalle,
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
    from services.metrics_service import get_subscriptions_detalle
    metrics = get_cached_metrics()
    organizaciones = get_organizaciones_detalle()
    usuarios = get_usuarios_detalle(limit=200)
    obras = get_obras_detalle(limit=200)
    suscripciones = get_subscriptions_detalle(limit=200)
    return render_template(
        'admin/metrics.html',
        metrics=metrics,
        organizaciones=organizaciones,
        usuarios=usuarios,
        obras=obras,
        suscripciones=suscripciones,
    )


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


@admin_metrics_bp.route('/rls-status')
@login_required
def rls_status():
    """
    Diagnóstico del estado de Row Level Security (RLS).
    Verifica si las funciones helper y policies están aplicadas.
    Solo super admin.
    """
    _require_super_admin()
    from extensions import db
    from sqlalchemy import text
    import os

    result = {
        'rls_enabled_env': os.environ.get('RLS_ENABLED', 'false'),
        'middleware_active': os.environ.get('RLS_ENABLED', 'false').lower() == 'true',
        'helper_functions': {},
        'tables_with_rls': [],
        'tables_without_rls': [],
        'policies': [],
    }

    try:
        # 1. Verificar funciones helper
        for func_name in ['app_current_org_id', 'app_is_super_admin']:
            try:
                row = db.session.execute(text(
                    "SELECT proname FROM pg_proc WHERE proname = :n"
                ), {'n': func_name}).fetchone()
                result['helper_functions'][func_name] = row is not None
            except Exception as e:
                result['helper_functions'][func_name] = f'error: {e}'

        # 2. Listar tablas tenant-scoped y verificar RLS
        tenant_tables = [
            'audit_log', 'clientes', 'cuadrillas_tipo', 'escala_salarial_uocra',
            'items_inventario', 'items_referencia_constructora', 'liquidaciones_mo',
            'locations', 'movimientos_caja', 'notificaciones', 'obras',
            'ordenes_compra', 'presupuestos', 'proveedores', 'proveedores_oc',
            'remitos', 'requerimientos_compra', 'work_certifications', 'work_payments',
        ]
        for table in tenant_tables:
            try:
                row = db.session.execute(text("""
                    SELECT relrowsecurity FROM pg_class
                    WHERE relname = :t AND relkind = 'r'
                """), {'t': table}).fetchone()
                if row is None:
                    continue
                if row[0]:
                    result['tables_with_rls'].append(table)
                else:
                    result['tables_without_rls'].append(table)
            except Exception:
                pass

        # 3. Listar policies activas
        try:
            rows = db.session.execute(text("""
                SELECT tablename, policyname FROM pg_policies
                WHERE policyname = 'tenant_isolation'
                ORDER BY tablename
            """)).fetchall()
            result['policies'] = [{'table': r[0], 'name': r[1]} for r in rows]
        except Exception as e:
            result['policies'] = f'error: {e}'

        # 4. Test de variable de sesión actual (si middleware está activo)
        try:
            row = db.session.execute(text(
                "SELECT current_setting('app.current_org_id', true)"
            )).fetchone()
            result['current_session_org_id'] = row[0] if row else None
        except Exception as e:
            result['current_session_org_id'] = f'error: {e}'

        # 5. Resumen
        result['summary'] = {
            'helper_functions_ok': all(v is True for v in result['helper_functions'].values()),
            'tables_with_rls_count': len(result['tables_with_rls']),
            'tables_without_rls_count': len(result['tables_without_rls']),
            'policies_count': len(result['policies']) if isinstance(result['policies'], list) else 0,
        }

        # Diagnóstico final
        if result['summary']['helper_functions_ok'] and result['summary']['policies_count'] >= 15:
            result['status'] = 'RLS APLICADO Y FUNCIONANDO'
        elif result['summary']['policies_count'] == 0:
            result['status'] = 'RLS NO APLICADO (migración pendiente)'
        else:
            result['status'] = 'RLS PARCIALMENTE APLICADO'

    except Exception as e:
        result['error'] = str(e)

    return jsonify(result)
