"""
Plan Service — Sistema centralizado de suscripciones, licencias y control de acceso por plan.

Maneja:
- Matriz de features por plan
- Verificación de acceso a módulos/features
- Enforcement de límites (obras, usuarios)
- Control de vigencia (suscripción mensual, licencia 5 años)
- Lógica de downgrade segura
- Helpers y decorators para rutas

Uso:
    from services.plan_service import require_feature, require_plan, can_access_feature

    @app.route('/inventario')
    @login_required
    @require_feature('inventory.full')
    def inventario():
        ...

    if can_access_feature('reports.advanced'):
        # mostrar reporte avanzado
"""

from functools import wraps
from datetime import datetime, timedelta
from flask import abort, flash, redirect, url_for, request, jsonify, current_app
from flask_login import current_user
from extensions import db


# ============================================================================
# MATRIZ DE FEATURES POR PLAN
# ============================================================================

_STANDARD_FEATURES = {
    'budgets.basic', 'budgets.manual', 'budgets.pdf',
    'works.basic', 'works.stages', 'works.tasks', 'works.advances',
    'works.certifications', 'works.cronograma',
    'clients.manage',
    'orders.basic', 'orders.create',
    'inventory.full', 'inventory.deposito', 'inventory.alertas',
    'inventory.categorias', 'inventory.consumo',
    'teams.basic', 'teams.invite',
    'manual.access',
}

_PREMIUM_FEATURES = _STANDARD_FEATURES | {
    'budgets.ai_basic', 'budgets.ai_full', 'budgets.excel_import',
    'works.remitos', 'works.caja',
    'requirements.basic', 'requirements.create',
    'orders.cotizaciones', 'orders.comparativa',
    'providers.basic', 'providers.manage', 'providers.history',
    'reports.basic', 'reports.obras', 'reports.costos',
    'reports.inventario', 'reports.financiero', 'reports.pdf_export',
    'teams.rendimiento',
    'security.basic', 'security.checklists', 'security.incidents', 'security.protocols',
    'attendance.geo', 'attendance.alerts',
    'automation.basic',
    'dashboard.costos',
}

_FULL_PREMIUM_FEATURES = _PREMIUM_FEATURES | {
    'works.gantt',
    'teams.advanced_roles',
    'security.certifications', 'security.audit_advanced',
    'reports.audit_log',
    'automation.advanced',
    'api.access',
    'offline.basic', 'offline.sync',
    'dashboard.financiero',
}

PLAN_FEATURES = {
    'prueba': {
        'nombre': 'Prueba Gratuita',
        'precio_usd': 0,
        'max_obras': 999,
        'max_usuarios': 999,
        'duracion_dias': 30,
        'contract_type': 'trial',
        'features': set(_STANDARD_FEATURES),
    },
    'estandar': {
        'nombre': 'Plan Standard',
        'precio_usd': 199,
        'max_obras': 999,
        'max_usuarios': 999,
        'duracion_dias': 365,
        'contract_type': 'subscription',
        'features': set(_STANDARD_FEATURES),
    },
    'premium': {
        'nombre': 'OBYRA Profesional',
        'precio_usd': 399,
        'max_obras': 999,
        'max_usuarios': 999,
        'duracion_dias': 365,
        'contract_type': 'subscription',
        'features': set(_PREMIUM_FEATURES),
    },
    'full_premium': {
        'nombre': 'Plan Full Premium',
        'precio_usd': 799,
        'max_obras': 999,
        'max_usuarios': 999,
        'duracion_dias': 365,
        'contract_type': 'subscription',
        'features': set(_FULL_PREMIUM_FEATURES),
    },
}

LICENSE_PRICES = {
    'estandar': {'licencia_usd': 6900, 'renovacion_anual_pct': 20},
    'premium': {'licencia_usd': 14900, 'renovacion_anual_pct': 20},
    'full_premium': {'licencia_usd': 29900, 'renovacion_anual_pct': 20},
}

# Features que se mantienen activas en licencia 5 años con renovación anual impaga
LICENSE_BASE_FEATURES = {
    'budgets.basic', 'budgets.manual', 'budgets.pdf',
    'works.basic', 'works.stages', 'works.tasks', 'works.advances',
    'works.certifications', 'works.remitos', 'works.caja',
    'clients.manage',
    'requirements.basic', 'requirements.create',
    'orders.basic', 'orders.create',
    'providers.basic',
    'reports.basic', 'reports.obras',
    'teams.basic', 'teams.invite',
    'security.basic',
    'manual.access',
    'offline.basic',
}

# Mapeo de módulo de menú → features requeridas (cualquiera)
MODULE_FEATURE_MAP = {
    'presupuestos': ['budgets.basic'],
    'obras': ['works.basic'],
    'inventario': ['inventory.full'],
    'equipos': ['teams.basic'],
    'reportes': ['reports.basic'],
    'seguridad': ['security.basic'],
    'requerimientos': ['requirements.basic'],
    'ordenes_compra': ['orders.basic'],
    'proveedores': ['providers.basic'],
    'fichadas': ['attendance.geo'],
}


# ============================================================================
# ESTADO DE SUSCRIPCIÓN
# ============================================================================

SUBSCRIPTION_STATES = {
    'active': 'Activa',
    'trial': 'Prueba',
    'past_due': 'Pago pendiente',
    'grace_period': 'Período de gracia',
    'read_only': 'Solo lectura',
    'suspended': 'Suspendida',
    'cancelled': 'Cancelada',
}

LICENSE_STATES = {
    'active': 'Vigente',
    'annual_due': 'Renovación anual pendiente',
    'annual_overdue': 'Renovación anual vencida',
    'expired': 'Licencia vencida',
}


# ============================================================================
# FUNCIONES CORE
# ============================================================================

def get_org():
    """Obtiene la organización del usuario actual."""
    if not current_user or not current_user.is_authenticated:
        return None
    org_id = None
    from flask import session
    org_id = session.get('current_org_id') or getattr(current_user, 'organizacion_id', None)
    if not org_id:
        return None
    from models.core import Organizacion
    return Organizacion.query.get(org_id)


def get_plan_config(plan_tipo=None):
    """Obtiene la configuración del plan."""
    if plan_tipo is None:
        org = get_org()
        plan_tipo = org.plan_tipo if org else 'prueba'
    return PLAN_FEATURES.get(plan_tipo, PLAN_FEATURES['prueba'])


def get_plan_features(plan_tipo=None):
    """Retorna el set de features habilitadas para un plan."""
    config = get_plan_config(plan_tipo)
    return config.get('features', set())


def get_subscription_status(org=None):
    """
    Determina el estado actual de la suscripción/licencia de una organización.
    Retorna: (status, days_remaining, is_writable)
    """
    if org is None:
        org = get_org()
    if not org:
        return 'suspended', 0, False

    plan = org.plan_tipo or 'prueba'
    contract_type = getattr(org, 'contract_type', None) or 'subscription'
    now = datetime.utcnow()

    # Sin fecha de fin → trial o nunca activado
    if not org.fecha_fin_plan:
        if plan == 'prueba':
            # Prueba de 30 días desde creación
            if org.fecha_creacion:
                fin_trial = org.fecha_creacion + timedelta(days=30)
                days_left = (fin_trial - now).days
                if days_left > 0:
                    return 'trial', days_left, True
                elif days_left > -7:
                    return 'grace_period', days_left, True
                else:
                    return 'read_only', days_left, False
            return 'trial', 30, True
        # Plan pago sin fecha → asumir activo (migración)
        return 'active', 365, True

    days_remaining = (org.fecha_fin_plan - now).days

    if contract_type == 'license_5y':
        # Licencia de 5 años
        if days_remaining > 0:
            # Verificar renovación anual
            annual_due = getattr(org, 'annual_service_due_date', None)
            if annual_due and now > annual_due:
                overdue_days = (now - annual_due).days
                if overdue_days > 90:
                    return 'annual_overdue', days_remaining, True  # Funciona pero limitado
                return 'annual_due', days_remaining, True
            return 'active', days_remaining, True
        elif days_remaining > -30:
            return 'grace_period', days_remaining, False
        else:
            return 'expired', days_remaining, False
    else:
        # Suscripción mensual/anual
        if days_remaining > 0:
            return 'active', days_remaining, True
        elif days_remaining > -7:
            # 7 días de gracia
            return 'grace_period', days_remaining, True
        elif days_remaining > -37:
            # 30 días más en solo lectura
            return 'read_only', days_remaining, False
        else:
            return 'suspended', days_remaining, False


def can_access_feature(feature_name, org=None):
    """
    Verifica si la organización tiene acceso a una feature específica.
    Considera: plan, vigencia, estado de suscripción, licencia.
    """
    if org is None:
        org = get_org()
    if not org:
        return False

    # Superadmin siempre tiene acceso
    if getattr(current_user, 'is_super_admin', False):
        return True

    plan = org.plan_tipo or 'prueba'
    status, _, _ = get_subscription_status(org)

    # Suspendido → sin acceso a nada
    if status == 'suspended':
        return False

    # Solo lectura → solo features de lectura (no crear/editar)
    if status == 'read_only':
        read_features = {'reports.basic', 'reports.obras', 'manual.access', 'dashboard.costos'}
        return feature_name in read_features

    # Licencia con renovación anual vencida → solo features base
    if status == 'annual_overdue':
        return feature_name in LICENSE_BASE_FEATURES

    # Plan activo → verificar features del plan
    plan_features = get_plan_features(plan)
    return feature_name in plan_features


def can_access_module(module_name, org=None):
    """Verifica si la organización tiene acceso a un módulo."""
    features_needed = MODULE_FEATURE_MAP.get(module_name, [])
    if not features_needed:
        return True  # Módulo sin restricción
    return any(can_access_feature(f, org) for f in features_needed)


def check_limit(limit_type, org=None):
    """
    Verifica si la organización puede crear más recursos del tipo dado.
    Retorna: (puede_crear, mensaje, actual, limite)
    """
    if org is None:
        org = get_org()
    if not org:
        return False, 'Sin organización', 0, 0

    # Superadmin sin límites
    if getattr(current_user, 'is_super_admin', False):
        return True, '', 0, 999

    # Verificar vigencia
    status, _, is_writable = get_subscription_status(org)
    if not is_writable:
        return False, f'Tu suscripción está en estado: {SUBSCRIPTION_STATES.get(status, status)}. Contactá soporte.', 0, 0

    if limit_type == 'obras':
        from models.projects import Obra
        # Lock la org para evitar race condition (dos usuarios creando obra al mismo tiempo)
        from extensions import db
        db.session.execute(
            db.text('SELECT 1 FROM organizaciones WHERE id = :oid FOR UPDATE'),
            {'oid': org.id}
        )
        limite = org.max_obras or 1
        actual = Obra.query.filter(
            Obra.organizacion_id == org.id,
            Obra.estado.notin_(['cancelada']),
            Obra.deleted_at.is_(None)
        ).count()
        if actual >= limite:
            return False, f'Alcanzaste el límite de {limite} obras de tu plan {org.plan_tipo}. Actualizá tu plan para crear más.', actual, limite
        return True, '', actual, limite

    elif limit_type == 'usuarios':
        limite = org.max_usuarios or 5
        actual = org.usuarios_activos_count
        if actual >= limite:
            return False, f'Alcanzaste el límite de {limite} usuarios de tu plan {org.plan_tipo}. Actualizá tu plan para invitar más.', actual, limite
        return True, '', actual, limite

    return True, '', 0, 0


def get_plan_summary(org=None):
    """
    Retorna un diccionario resumen del plan para mostrar en UI.
    Útil para templates y API.
    """
    if org is None:
        org = get_org()
    if not org:
        return {}

    plan = org.plan_tipo or 'prueba'
    config = get_plan_config(plan)
    status, days_remaining, is_writable = get_subscription_status(org)
    contract_type = getattr(org, 'contract_type', None) or 'subscription'

    from models.projects import Obra
    obras_activas = Obra.query.filter(
        Obra.organizacion_id == org.id,
        Obra.estado.notin_(['cancelada']),
        Obra.deleted_at.is_(None)
    ).count()

    return {
        'plan_tipo': plan,
        'plan_nombre': config.get('nombre', plan),
        'contract_type': contract_type,
        'status': status,
        'status_label': SUBSCRIPTION_STATES.get(status, LICENSE_STATES.get(status, status)),
        'days_remaining': days_remaining,
        'is_writable': is_writable,
        'max_obras': org.max_obras or config.get('max_obras', 1),
        'max_usuarios': org.max_usuarios or config.get('max_usuarios', 5),
        'obras_activas': obras_activas,
        'usuarios_activos': org.usuarios_activos_count,
        'fecha_inicio': org.fecha_inicio_plan,
        'fecha_fin': org.fecha_fin_plan,
        'features': list(get_plan_features(plan)),
    }


# ============================================================================
# DECORATORS PARA RUTAS
# ============================================================================

def require_feature(feature_name):
    """
    Decorator que requiere una feature específica del plan.

    Uso:
        @require_feature('inventory.full')
        def inventario():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if not can_access_feature(feature_name):
                return _handle_plan_blocked(feature_name)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_plan(*allowed_plans):
    """
    Decorator que requiere un plan mínimo.

    Uso:
        @require_plan('premium', 'full_premium')
        def reporte_avanzado():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            org = get_org()
            if not org:
                abort(403)

            # Superadmin pasa siempre
            if getattr(current_user, 'is_super_admin', False):
                return f(*args, **kwargs)

            if org.plan_tipo not in allowed_plans:
                return _handle_plan_blocked(f'plan:{",".join(allowed_plans)}')

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_active_subscription(f):
    """
    Decorator que verifica que la suscripción esté activa (no vencida/suspendida).
    Permite: active, trial, grace_period
    Bloquea: read_only, suspended, cancelled, expired
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)

        # Superadmin pasa siempre
        if getattr(current_user, 'is_super_admin', False):
            return f(*args, **kwargs)

        org = get_org()
        if not org:
            abort(403)

        status, days, is_writable = get_subscription_status(org)

        if not is_writable:
            return _handle_subscription_expired(status, days)

        return f(*args, **kwargs)
    return decorated_function


def _handle_plan_blocked(feature_name):
    """Maneja respuesta cuando el plan no tiene acceso a una feature."""
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'ok': False,
            'error': 'Tu plan actual no incluye esta función.',
            'upgrade_url': url_for('planes.mostrar_planes'),
            'feature': feature_name,
        }), 403

    flash('Esta función no está incluida en tu plan actual. Actualizá tu plan para acceder.', 'warning')
    return redirect(url_for('planes.mostrar_planes'))


def _handle_subscription_expired(status, days):
    """Maneja respuesta cuando la suscripción está vencida."""
    messages = {
        'read_only': 'Tu suscripción venció. El sistema está en modo solo lectura. Renová tu plan para continuar operando.',
        'suspended': 'Tu cuenta está suspendida. Contactá a soporte para reactivarla.',
        'cancelled': 'Tu suscripción fue cancelada. Contactá a soporte.',
        'expired': 'Tu licencia expiró. Contactá a soporte para renovarla.',
    }
    msg = messages.get(status, 'Tu suscripción requiere atención.')

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': False, 'error': msg, 'status': status}), 403

    flash(msg, 'danger')
    return redirect(url_for('planes.mostrar_planes'))


# ============================================================================
# CAMBIO DE PLAN / DOWNGRADE
# ============================================================================

def change_plan(org, new_plan_tipo, days=365, contract_type='subscription', changed_by=None):
    """
    Cambia el plan de una organización de forma segura.
    Maneja upgrade y downgrade.

    Retorna: (success, message, warnings)
    """
    if new_plan_tipo not in PLAN_FEATURES:
        return False, f'Plan "{new_plan_tipo}" no existe.', []

    config = PLAN_FEATURES[new_plan_tipo]
    old_plan = org.plan_tipo
    warnings = []

    # Verificar excedentes en downgrade
    new_max_obras = config['max_obras']
    new_max_usuarios = config['max_usuarios']

    from models.projects import Obra
    obras_activas = Obra.query.filter(
        Obra.organizacion_id == org.id,
        Obra.estado.notin_(['cancelada']),
        Obra.deleted_at.is_(None)
    ).count()

    usuarios_activos = org.usuarios_activos_count

    if obras_activas > new_max_obras:
        warnings.append(
            f'La organización tiene {obras_activas} obras activas pero el nuevo plan permite {new_max_obras}. '
            f'No se podrán crear nuevas obras hasta regularizar.'
        )

    if usuarios_activos > new_max_usuarios:
        warnings.append(
            f'La organización tiene {usuarios_activos} usuarios activos pero el nuevo plan permite {new_max_usuarios}. '
            f'No se podrán invitar nuevos usuarios hasta regularizar.'
        )

    # Aplicar cambio
    org.plan_tipo = new_plan_tipo
    org.max_obras = new_max_obras
    org.max_usuarios = new_max_usuarios
    org.fecha_inicio_plan = datetime.utcnow()
    org.fecha_fin_plan = datetime.utcnow() + timedelta(days=days)

    if hasattr(org, 'contract_type'):
        org.contract_type = contract_type

    # Sincronizar campo legacy plan_activo en TODOS los usuarios de la org
    # Esto evita la inconsistencia "Plan Full Premium" en navbar vs "Prueba: 0 días" en dropdown
    try:
        from models.core import Usuario
        Usuario.query.filter_by(organizacion_id=org.id).update(
            {
                Usuario.plan_activo: new_plan_tipo,
                Usuario.fecha_expiracion_plan: org.fecha_fin_plan,
            },
            synchronize_session=False,
        )
    except Exception as _sync_err:
        # No bloquear el cambio de plan si el sync falla
        try:
            from flask import current_app
            current_app.logger.warning(f'No se pudo sincronizar plan_activo de usuarios: {_sync_err}')
        except Exception:
            pass

    db.session.commit()

    # Log del cambio
    try:
        from models.audit import AuditLog
        AuditLog.registrar(
            usuario_id=changed_by or (current_user.id if current_user and current_user.is_authenticated else None),
            organizacion_id=org.id,
            accion='cambio_plan',
            entidad='organizacion',
            entidad_id=org.id,
            detalles=f'{old_plan} → {new_plan_tipo} ({contract_type}, {days} días)',
        )
    except Exception:
        pass

    action = 'upgrade' if PLAN_FEATURES.get(new_plan_tipo, {}).get('precio_usd', 0) > PLAN_FEATURES.get(old_plan, {}).get('precio_usd', 0) else 'downgrade'
    return True, f'Plan cambiado de {old_plan} a {new_plan_tipo} ({action}).', warnings


# ============================================================================
# CONTEXT PROCESSOR — Inyecta datos de plan en TODOS los templates
# ============================================================================

def inject_plan_context():
    """
    Context processor para inyectar datos del plan en templates.
    Registrar con: app.context_processor(inject_plan_context)
    """
    if not current_user or not current_user.is_authenticated:
        return {}

    try:
        org = get_org()
        if not org:
            return {'plan_info': {}, 'can_feature': lambda f: getattr(current_user, 'is_super_admin', False)}

        plan = org.plan_tipo or 'prueba'
        status, days, is_writable = get_subscription_status(org)
        features = get_plan_features(plan)

        # Si licencia con renovación vencida, limitar features
        if status == 'annual_overdue':
            features = LICENSE_BASE_FEATURES

        return {
            'plan_info': {
                'tipo': plan,
                'nombre': PLAN_FEATURES.get(plan, {}).get('nombre', plan),
                'status': status,
                'status_label': SUBSCRIPTION_STATES.get(status, LICENSE_STATES.get(status, status)),
                'days_remaining': days,
                'is_writable': is_writable,
                'is_trial': plan == 'prueba',
                'is_expired': status in ('read_only', 'suspended', 'expired'),
            },
            'can_feature': lambda f: f in features or getattr(current_user, 'is_super_admin', False),
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error en inject_plan_context: {e}")
        return {'plan_info': {}, 'can_feature': lambda f: False}
