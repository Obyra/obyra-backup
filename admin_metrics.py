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
    metrics = get_cached_metrics()
    organizaciones = get_organizaciones_detalle()
    usuarios = get_usuarios_detalle(limit=200)
    obras = get_obras_detalle(limit=200)
    return render_template(
        'admin/metrics.html',
        metrics=metrics,
        organizaciones=organizaciones,
        usuarios=usuarios,
        obras=obras,
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


@admin_metrics_bp.route('/rls-apply')
@login_required
def rls_apply():
    """
    Aplica la migración RLS de forma controlada paso a paso.
    Solo super admin. Idempotente: puede ejecutarse múltiples veces sin problema.

    Para revertir: GET /admin/metrics/rls-rollback
    """
    _require_super_admin()
    from extensions import db
    from sqlalchemy import text

    log = []
    errors = []

    try:
        # ─────────────────────────────────────────────────────────────
        # PASO 1: Crear funciones helper
        # ─────────────────────────────────────────────────────────────
        log.append("=== PASO 1: Creando funciones helper ===")

        try:
            db.session.execute(text("""
                CREATE OR REPLACE FUNCTION app_current_org_id()
                RETURNS INTEGER AS $$
                BEGIN
                    RETURN NULLIF(current_setting('app.current_org_id', true), '')::INTEGER;
                EXCEPTION WHEN OTHERS THEN
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql STABLE;
            """))
            db.session.commit()
            log.append("[OK] Función app_current_org_id() creada")
        except Exception as e:
            db.session.rollback()
            errors.append(f"app_current_org_id: {e}")
            log.append(f"[ERROR] app_current_org_id: {e}")

        try:
            db.session.execute(text("""
                CREATE OR REPLACE FUNCTION app_is_super_admin()
                RETURNS BOOLEAN AS $$
                BEGIN
                    RETURN COALESCE(current_setting('app.is_super_admin', true), 'false')::BOOLEAN;
                EXCEPTION WHEN OTHERS THEN
                    RETURN FALSE;
                END;
                $$ LANGUAGE plpgsql STABLE;
            """))
            db.session.commit()
            log.append("[OK] Función app_is_super_admin() creada")
        except Exception as e:
            db.session.rollback()
            errors.append(f"app_is_super_admin: {e}")
            log.append(f"[ERROR] app_is_super_admin: {e}")

        # ─────────────────────────────────────────────────────────────
        # PASO 2: Aplicar RLS a tablas con organizacion_id
        # ─────────────────────────────────────────────────────────────
        log.append("")
        log.append("=== PASO 2: Habilitando RLS en tablas con organizacion_id ===")

        tables_org = [
            'audit_log', 'clientes', 'consultas_agente', 'cotizaciones_proveedor',
            'cuadrillas_tipo', 'escala_salarial_uocra', 'global_material_usage',
            'items_inventario', 'items_referencia_constructora', 'liquidaciones_mo',
            'locations', 'movimientos_caja', 'notificaciones', 'obras',
            'ordenes_compra', 'presupuestos', 'proveedores', 'proveedores_oc',
            'remitos', 'requerimientos_compra', 'work_certifications', 'work_payments',
        ]

        ok_org = 0
        for table in tables_org:
            try:
                # Verificar que la tabla existe
                exists = db.session.execute(text(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
                ), {'t': table}).fetchone()
                if not exists:
                    log.append(f"[SKIP] Tabla no existe: {table}")
                    continue

                # Habilitar RLS
                db.session.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))

                # Crear policy (drop si existe)
                db.session.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table};"))
                db.session.execute(text(f"""
                    CREATE POLICY tenant_isolation ON {table}
                        USING (
                            app_is_super_admin()
                            OR organizacion_id = app_current_org_id()
                            OR app_current_org_id() IS NULL
                        );
                """))
                db.session.commit()
                log.append(f"[OK] {table}")
                ok_org += 1
            except Exception as e:
                db.session.rollback()
                errors.append(f"{table}: {e}")
                log.append(f"[ERROR] {table}: {str(e)[:100]}")

        log.append(f"[INFO] {ok_org}/{len(tables_org)} tablas con organizacion_id aplicadas")

        # ─────────────────────────────────────────────────────────────
        # PASO 3: Aplicar RLS a tablas con company_id
        # ─────────────────────────────────────────────────────────────
        log.append("")
        log.append("=== PASO 3: Habilitando RLS en tablas con company_id ===")

        tables_company = [
            'equipment', 'equipment_movement', 'events', 'inventory_category',
            'inventory_item', 'order', 'warehouse',
        ]

        ok_company = 0
        for table in tables_company:
            try:
                exists = db.session.execute(text(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
                ), {'t': table}).fetchone()
                if not exists:
                    log.append(f"[SKIP] Tabla no existe: {table}")
                    continue

                db.session.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;'))
                db.session.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";'))
                db.session.execute(text(f'''
                    CREATE POLICY tenant_isolation ON "{table}"
                        USING (
                            app_is_super_admin()
                            OR company_id = app_current_org_id()
                            OR app_current_org_id() IS NULL
                        );
                '''))
                db.session.commit()
                log.append(f"[OK] {table}")
                ok_company += 1
            except Exception as e:
                db.session.rollback()
                errors.append(f"{table}: {e}")
                log.append(f"[ERROR] {table}: {str(e)[:100]}")

        log.append(f"[INFO] {ok_company}/{len(tables_company)} tablas con company_id aplicadas")

        # ─────────────────────────────────────────────────────────────
        # RESUMEN
        # ─────────────────────────────────────────────────────────────
        log.append("")
        log.append("=== RESUMEN ===")
        log.append(f"Total tablas con RLS aplicado: {ok_org + ok_company}")
        log.append(f"Errores: {len(errors)}")

        if len(errors) == 0:
            log.append("")
            log.append("✓ RLS APLICADO EXITOSAMENTE")
            log.append("Verificar con: GET /admin/metrics/rls-status")

        return jsonify({
            'ok': len(errors) == 0,
            'tables_org_applied': ok_org,
            'tables_company_applied': ok_company,
            'total_applied': ok_org + ok_company,
            'errors_count': len(errors),
            'errors': errors[:10],  # Primeros 10 errores
            'log': log,
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'ok': False,
            'error': f'Fallo crítico: {e}',
            'log': log,
        }), 500


@admin_metrics_bp.route('/whoami')
@login_required
def whoami():
    """
    Endpoint de diagnóstico personal.
    Cualquier usuario logueado puede ver su propio contexto:
    - user_id, email, role
    - organizacion_id principal
    - membresías activas (si pertenece a múltiples orgs)
    - current_org_id de la sesión
    - app.current_org_id de PostgreSQL (RLS context)
    """
    from extensions import db
    from sqlalchemy import text

    result = {
        'user': {
            'id': current_user.id,
            'email': current_user.email,
            'nombre': f"{current_user.nombre or ''} {current_user.apellido or ''}".strip(),
            'role': getattr(current_user, 'role', None),
            'rol': getattr(current_user, 'rol', None),
            'is_super_admin': bool(getattr(current_user, 'is_super_admin', False)),
            'organizacion_id': getattr(current_user, 'organizacion_id', None),
            'primary_org_id': getattr(current_user, 'primary_org_id', None),
        },
        'session': {},
        'memberships': [],
        'postgres_context': {},
    }

    # Sesión
    try:
        from flask import session
        result['session']['current_org_id'] = session.get('current_org_id')
        result['session']['_user_id'] = session.get('_user_id')
    except Exception as e:
        result['session']['error'] = str(e)

    # get_current_org_id()
    try:
        from services.memberships import get_current_org_id
        result['session']['get_current_org_id_result'] = get_current_org_id()
    except Exception as e:
        result['session']['get_current_org_id_error'] = str(e)

    # Membresías del usuario
    try:
        from models import OrgMembership, Organizacion
        memberships = db.session.query(OrgMembership).filter_by(
            user_id=current_user.id
        ).all()
        for m in memberships:
            org = db.session.get(Organizacion, m.org_id)
            result['memberships'].append({
                'id': m.id,
                'org_id': m.org_id,
                'org_nombre': org.nombre if org else None,
                'role': getattr(m, 'role', None),
                'archived': bool(getattr(m, 'archived', False)),
            })
    except Exception as e:
        result['memberships'] = f'error: {e}'

    # Contexto PostgreSQL (RLS)
    try:
        row = db.session.execute(text(
            "SELECT current_setting('app.current_org_id', true)"
        )).fetchone()
        result['postgres_context']['current_org_id'] = row[0] if row else None
    except Exception as e:
        result['postgres_context']['current_org_id_error'] = str(e)

    try:
        row = db.session.execute(text(
            "SELECT current_setting('app.is_super_admin', true)"
        )).fetchone()
        result['postgres_context']['is_super_admin'] = row[0] if row else None
    except Exception as e:
        result['postgres_context']['is_super_admin_error'] = str(e)

    # Cuántas obras "ve" este usuario
    try:
        from models import Obra
        obras_visibles = db.session.query(Obra).all()
        result['obras_visibles_count'] = len(obras_visibles)
        result['obras_visibles_sample'] = [
            {'id': o.id, 'nombre': o.nombre, 'organizacion_id': o.organizacion_id}
            for o in obras_visibles[:10]
        ]
    except Exception as e:
        result['obras_visibles_error'] = str(e)

    return jsonify(result)


@admin_metrics_bp.route('/rls-rollback')
@login_required
def rls_rollback():
    """
    Revierte completamente RLS: elimina policies y deshabilita RLS.
    Solo super admin. Para emergencias.
    """
    _require_super_admin()
    from extensions import db
    from sqlalchemy import text

    log = []
    errors = []

    all_tables = [
        'audit_log', 'clientes', 'consultas_agente', 'cotizaciones_proveedor',
        'cuadrillas_tipo', 'escala_salarial_uocra', 'global_material_usage',
        'items_inventario', 'items_referencia_constructora', 'liquidaciones_mo',
        'locations', 'movimientos_caja', 'notificaciones', 'obras',
        'ordenes_compra', 'presupuestos', 'proveedores', 'proveedores_oc',
        'remitos', 'requerimientos_compra', 'work_certifications', 'work_payments',
        'equipment', 'equipment_movement', 'events', 'inventory_category',
        'inventory_item', 'order', 'warehouse',
    ]

    for table in all_tables:
        try:
            db.session.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}";'))
            db.session.execute(text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;'))
            db.session.commit()
            log.append(f"[OK] RLS deshabilitado: {table}")
        except Exception as e:
            db.session.rollback()
            errors.append(f"{table}: {str(e)[:100]}")

    # Eliminar funciones helper
    try:
        db.session.execute(text("DROP FUNCTION IF EXISTS app_current_org_id();"))
        db.session.execute(text("DROP FUNCTION IF EXISTS app_is_super_admin();"))
        db.session.commit()
        log.append("[OK] Funciones helper eliminadas")
    except Exception as e:
        db.session.rollback()
        errors.append(f"funciones helper: {e}")

    return jsonify({
        'ok': len(errors) == 0,
        'log': log,
        'errors': errors,
        'message': 'RLS revertido. Verificar con /admin/metrics/rls-status',
    })
