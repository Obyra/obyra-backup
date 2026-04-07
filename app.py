from dotenv import load_dotenv
load_dotenv(override=True)

import os
import sys
import logging
import importlib
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Optional

import click
from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    flash,
    send_from_directory,
    request,
    g,
    session,
    has_request_context,
)
from flask.cli import AppGroup, with_appcontext
from flask_login import login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.routing import BuildError

from services.memberships import (
    initialize_membership_session,
    load_membership_into_context,
    get_current_membership,
    get_current_org_id,
)

from extensions import db, login_manager, csrf
from flask_migrate import Migrate


def _ensure_utf8_io() -> None:
    """Force UTF-8 aware standard streams so CLI prints never fail."""
    target_encoding = "utf-8"
    os.environ.setdefault("PYTHONIOENCODING", target_encoding)

    if not hasattr(sys, "stdout") or not hasattr(sys, "stderr"):
        return

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding=target_encoding)
            elif hasattr(stream, "buffer"):
                import io

                stream.flush()
                wrapped = io.TextIOWrapper(
                    stream.buffer,
                    encoding=target_encoding,
                    errors="replace",
                )
                setattr(sys, name, wrapped)
        except Exception:
            continue


_ensure_utf8_io()
_builtin_print = print


def _safe_cli_print(*args, **kwargs):
    """Print helper that strips unsupported characters on narrow consoles."""
    target = kwargs.get("file", sys.stdout)
    encoding = getattr(target, "encoding", None) or os.environ.get("PYTHONIOENCODING") or "utf-8"

    safe_args = []
    for arg in args:
        text = str(arg)
        try:
            text.encode(encoding, errors="strict")
        except Exception:
            text = text.encode("ascii", "ignore").decode("ascii")
        safe_args.append(text)

    _builtin_print(*safe_args, **kwargs)


print = _safe_cli_print  # type: ignore[assignment]

# --------------- SENTRY ERROR MONITORING ---------------
try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False

if SENTRY_AVAILABLE:
    sentry_dsn = os.environ.get('SENTRY_DSN', '')
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
            environment=os.environ.get('FLASK_ENV', 'production'),
            send_default_pii=False,  # Don't send personal data
        )

# create the app
app = Flask(__name__)

# Security: Require SECRET_KEY in production
secret_key = os.environ.get("SESSION_SECRET") or os.environ.get("SECRET_KEY")
if not secret_key:
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError(
            "SECRET_KEY environment variable must be set in production! "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    # Development fallback with warning
    secret_key = "dev-secret-key-change-me"
    print("⚠️  WARNING: Using insecure default SECRET_KEY. Set SECRET_KEY environment variable!")

app.secret_key = secret_key
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

def _env_flag(name: str, default: bool = False) -> bool:
    """Helper to parse boolean environment variables"""
    value = os.environ.get(name)
    if value is None:
        return default
    value_lower = value.strip().lower()
    if value_lower in {"false", "0", "no", "n", "off"}:
        return False
    return value_lower in {"1", "true", "t", "yes", "y", "on"}

# configure structured logging
from config.logging_config import setup_logging
setup_logging(app)

# ---------------- POSTGRESQL DATABASE CONFIG ----------------
database_url = os.environ.get("DATABASE_URL")

if not database_url:
    raise RuntimeError(
        "ERROR: DATABASE_URL no está configurado. "
        "Este sistema requiere PostgreSQL. "
        "Por favor configure DATABASE_URL en su archivo .env"
    )

# Convertir URL de Railway/Heroku al formato SQLAlchemy con psycopg
# Railway usa: postgresql://user:pass@host:port/db
# SQLAlchemy necesita: postgresql+psycopg://user:pass@host:port/db
if database_url.startswith("postgresql://") and "+psycopg" not in database_url:
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    print("🔄 URL convertida a formato psycopg para SQLAlchemy")

# Agregar SSL para Neon si falta
if "neon.tech" in database_url and "sslmode=" not in database_url:
    database_url += ("&" if "?" in database_url else "?") + "sslmode=require"
    print("🔒 SSL requerido agregado para Neon")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url

# Connection pooling: PostgreSQL en producción, SQLite simplificado en tests
if database_url.startswith("sqlite"):
    # SQLite no soporta los connect_args de PostgreSQL
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
    }
else:
    # PostgreSQL-optimized connection pooling
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 20,           # Conexiones en el pool (escalable)
        "max_overflow": 50,        # Conexiones adicionales si el pool está lleno
        "pool_timeout": 30,        # Timeout para obtener conexión del pool
        "pool_recycle": 1800,      # Reciclar conexiones cada 30 min
        "pool_pre_ping": True,     # Verificar conexión antes de usarla
        "connect_args": {
            "application_name": "obyra_app",  # Identificar en pg_stat_activity
            "options": "-c statement_timeout=30000",  # 30s timeout por query
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 600,
            "keepalives_interval": 30,
            "keepalives_count": 3,
        }
    }

# Feature flags
app.config["WIZARD_BUDGET_BREAKDOWN_ENABLED"] = _env_flag("WIZARD_BUDGET_BREAKDOWN_ENABLED", False)
app.config["WIZARD_BUDGET_SHADOW_MODE"] = _env_flag("WIZARD_BUDGET_SHADOW_MODE", False)
app.config["SHOW_IA_CALCULATOR_BUTTON"] = _env_flag("SHOW_IA_CALCULATOR_BUTTON", False)
app.config["ENABLE_REPORTS_SERVICE"] = _env_flag("ENABLE_REPORTS", False)
app.config["MAPS_PROVIDER"] = (os.environ.get("MAPS_PROVIDER") or "nominatim").strip().lower()
app.config["MAPS_API_KEY"] = os.environ.get("MAPS_API_KEY")
app.config["MP_ACCESS_TOKEN"] = os.getenv("MP_ACCESS_TOKEN", "").strip()
app.config["MP_WEBHOOK_PUBLIC_URL"] = os.getenv("MP_WEBHOOK_PUBLIC_URL", "").strip()

if not app.config["MP_ACCESS_TOKEN"]:
    app.logger.warning(
        "Mercado Pago access token (MP_ACCESS_TOKEN) is not configured; Mercado Pago operations will fail."
    )

mp_webhook_url = app.config.get("MP_WEBHOOK_PUBLIC_URL")
if mp_webhook_url:
    app.logger.info(f"MP webhook URL: {mp_webhook_url}")
else:
    app.logger.warning(
        "MP_WEBHOOK_PUBLIC_URL is not configured; expected path: /api/payments/mp/webhook"
    )

# Session Security Configuration
from datetime import timedelta
# SESSION_COOKIE_SECURE: True automáticamente en producción (FLASK_ENV=production)
# También se puede forzar con SESSION_COOKIE_SECURE=true
_is_production = os.environ.get('FLASK_ENV', '').lower() == 'production'
app.config["SESSION_COOKIE_SECURE"] = _is_production or _env_flag("SESSION_COOKIE_SECURE", default=False)
app.config["SESSION_COOKIE_HTTPONLY"] = True  # Prevenir acceso desde JavaScript
app.config["SESSION_COOKIE_SAMESITE"] = "Strict" if _is_production else "Lax"  # Más estricto en producción
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=int(os.getenv("SESSION_LIFETIME_HOURS", "24")))
app.config["SESSION_REFRESH_EACH_REQUEST"] = True  # Renovar sesión en cada request

# File Upload Configuration
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_SIZE_MB", "16")) * 1024 * 1024  # Default 16MB
app.config["UPLOAD_ALLOWED_EXTENSIONS"] = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt',
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp',
    'zip', 'rar', '7z'
}

# Flask-Mail Configuration
app.config["MAIL_SERVER"] = os.getenv("SMTP_HOST", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("SMTP_PORT", "465"))
app.config["MAIL_USE_TLS"] = False
app.config["MAIL_USE_SSL"] = True
app.config["MAIL_USERNAME"] = os.getenv("SMTP_USER", "")
app.config["MAIL_PASSWORD"] = os.getenv("SMTP_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("SMTP_USER", "")
app.config["MAIL_SUPPRESS_SEND"] = False

# Resend Configuration (for email_service.py)
app.config["RESEND_API_KEY"] = os.getenv("RESEND_API_KEY", "")
app.config["FROM_EMAIL"] = os.getenv("FROM_EMAIL", "OBYRA <onboarding@resend.dev>")

if app.config["RESEND_API_KEY"]:
    app.logger.info(f"Email configured with Resend API")
else:
    app.logger.warning("RESEND_API_KEY is not configured; email sending will not work.")

# initialize extensions
db.init_app(app)
login_manager.init_app(app)

# CSRF Protection
csrf.init_app(app)

# Flask-Mail
from extensions import mail
mail.init_app(app)

migrate = Migrate(app, db)

# Setup rate limiter
from config.rate_limiter_config import setup_rate_limiter
import extensions
_real_limiter = setup_rate_limiter(app)
extensions.limiter._set_real(_real_limiter)

# Setup request timing middleware
from middleware.request_timing import setup_request_timing
setup_request_timing(app)

# Setup security headers middleware (CSP, X-Frame-Options, etc.)
from middleware.security_headers import setup_security_headers
setup_security_headers(app)

# CORS Configuration - Solo permite orígenes específicos en producción
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_origins:
    try:
        from flask_cors import CORS
        origins_list = [o.strip() for o in _cors_origins.split(",") if o.strip()]
        CORS(app,
             origins=origins_list,
             supports_credentials=True,
             methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
             allow_headers=['Content-Type', 'Authorization', 'X-CSRFToken'])
        app.logger.info(f"CORS configurado para: {origins_list}")
    except ImportError:
        app.logger.warning("flask-cors no instalado, CORS no configurado")
elif _is_production:
    app.logger.warning("CORS_ALLOWED_ORIGINS no configurado en producción")

# ---------------- Login dynamic resolution ----------------
def _resolve_login_endpoint() -> Optional[str]:
    """Return the first available login endpoint, prioritising auth blueprints."""
    candidate_endpoints = (
        "auth.login",
        "supplier_auth.login",
        "auth_login",
        "index",
    )
    for endpoint in candidate_endpoints:
        if endpoint in app.view_functions:
            return endpoint
    return None


def _resolve_login_url() -> str:
    """Return the URL corresponding to the active login endpoint."""
    endpoint = _resolve_login_endpoint()
    if not endpoint:
        return "/"
    try:
        if has_request_context():
            return url_for(endpoint)
        with app.test_request_context():
            return url_for(endpoint)
    except Exception:
        return "/"


def _login_redirect():
    """Redirect users to the most appropriate login page."""
    return redirect(_resolve_login_url())


def _refresh_login_view():
    """Synchronise the login manager with the currently available login endpoint."""
    login_manager.login_view = _resolve_login_endpoint()


login_manager.login_view = None
login_manager.login_message = 'Por favor inicia sesión para acceder a esta página.'
login_manager.login_message_category = 'info'


@app.context_processor
def inject_login_url():
    return {"login_url": _resolve_login_url()}

# ---------------- CLI Commands ----------------
db_cli = AppGroup('db')

@db_cli.command('upgrade')
@with_appcontext
def db_upgrade():
    """Apply pending lightweight database migrations."""
    from flask_migrate import upgrade as alembic_upgrade

    logger = app.logger
    logger.info("Running Alembic upgrade...")
    alembic_upgrade()
    logger.info("Alembic upgrade → OK")

    # Runtime migrations have been converted to Alembic migrations (Phase 4)
    # All schema changes are now managed via: migrations/versions/*.py
    # Run: alembic upgrade head

    click.echo('[OK] Database upgraded successfully.')

app.cli.add_command(db_cli)

fx_cli = AppGroup('fx')

@fx_cli.command('update')
@click.option('--provider', default='bna', help='Proveedor de tipo de cambio (ej. bna)')
def fx_update(provider: str):
    """Actualiza el tipo de cambio almacenado."""
    provider_key = (provider or 'bna').lower()
    with app.app_context():
        from decimal import Decimal
        from services.exchange import base as exchange_base
        from services.exchange.providers import bna as bna_provider

        if provider_key != 'bna':
            click.echo('[WARN] Por ahora solo se admite el proveedor "bna". Se usará Banco Nación.')
            provider_key = 'bna'

        fallback_env = app.config.get('EXCHANGE_FALLBACK_RATE')
        fallback = Decimal(str(fallback_env)) if fallback_env else None

        snapshot = exchange_base.ensure_rate(
            provider_key,
            base_currency='ARS',
            quote_currency='USD',
            fetcher=bna_provider.fetch_official_rate,
            fallback_rate=fallback,
        )

        click.echo(
            "[OK] Tipo de cambio actualizado: {valor} ({prov} {fecha:%d/%m/%Y})".format(
                valor=snapshot.value,
                prov=snapshot.provider.upper(),
                fecha=snapshot.as_of_date,
            )
        )

app.cli.add_command(fx_cli)

cac_cli = AppGroup('cac')

@cac_cli.command('set')
@click.option('--value', required=True, type=float, help='Valor numérico del índice CAC')
@click.option('--valid-from', type=click.DateTime(formats=['%Y-%m-%d']), help='Fecha de vigencia (YYYY-MM-DD)')
@click.option('--notes', default=None, help='Notas opcionales')
def cac_set(value: float, valid_from, notes: Optional[str]):
    """Registra un nuevo valor para el índice CAC."""
    with app.app_context():
        from decimal import Decimal
        from datetime import date
        from services.cac.cac_service import record_manual_index

        valid_date = valid_from.date() if valid_from else date.today().replace(day=1)
        registro = record_manual_index(valid_date.year, valid_date.month, Decimal(str(value)), notes)
        click.echo(
            "[OK] Índice CAC registrado: {valor} ({anio}-{mes:02d}, proveedor {prov})".format(
                valor=registro.value,
                anio=registro.year,
                mes=registro.month,
                prov=registro.provider,
            )
        )

@cac_cli.command('refresh-current')
def cac_refresh_current():
    """Descarga el índice CAC del mes actual utilizando el proveedor configurado."""
    with app.app_context():
        from services.cac.cac_service import get_cac_context, refresh_from_provider

        registro = refresh_from_provider()
        contexto = get_cac_context()
        if registro:
            click.echo(
                "[OK] CAC actualizado automáticamente: {valor} ({anio}-{mes:02d})".format(
                    valor=registro.value,
                    anio=registro.year,
                    mes=registro.month,
                )
            )
        else:
            click.echo('[WARN] No se pudo obtener el índice CAC automáticamente. Se mantiene el valor vigente.')
        click.echo(
            "[INFO] Contexto actual: valor={valor} multiplicador={mult}".format(
                valor=contexto.value,
                mult=contexto.multiplier,
            )
        )

app.cli.add_command(cac_cli)

# ---------------- Login handlers ----------------
@login_manager.user_loader
def load_user(user_id):
    from models import Usuario  # evitar import circular
    return Usuario.query.get(int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    """Custom unauthorized handler that returns JSON for API routes"""
    if request.path.startswith('/obras/api/') or request.path.startswith('/api/'):
        from flask import jsonify
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    return _login_redirect()

# ---------------- Views ----------------
_ultima_alerta_oc = {'fecha': None}

@app.before_request
def alertas_diarias_oc():
    """Ejecuta alertas de entrega de OC una vez al día."""
    from datetime import date
    hoy = date.today()
    if _ultima_alerta_oc['fecha'] == hoy:
        return
    _ultima_alerta_oc['fecha'] = hoy
    try:
        from blueprint_ordenes_compra import notificar_entregas_proximas
        notificar_entregas_proximas()
    except Exception:
        app.logger.debug('Error en alertas diarias OC (no crítico)')


@app.before_request
def sincronizar_membresia_actual():
    """Carga la membresía activa en cada request para usuarios autenticados."""
    try:
        load_membership_into_context()
    except Exception:
        app.logger.exception('No se pudo sincronizar la membresía actual')

@app.before_request
def verificar_periodo_prueba():
    """Middleware para verificar si el usuario necesita seleccionar un plan"""
    # Rutas que no requieren verificación de plan
    rutas_excluidas = [
        'planes.mostrar_planes', 'planes.seleccionar_plan', 'planes.pago_mercadopago',
        'planes.pago_exitoso', 'planes.pago_fallido', 'planes.pago_pendiente',
        'planes.webhook_mercadopago', 'planes.instrucciones_pago', 'planes.enviar_comprobante',
        'planes.plan_standard', 'planes.plan_premium',
        'auth.login', 'auth.register', 'auth.logout',
        'supplier_auth.login', 'static', 'index'
    ]
    if (current_user.is_authenticated and
        request.endpoint and
        request.endpoint not in rutas_excluidas and
        not request.endpoint.startswith('static')):

        # Super admin bypass - uses is_super_admin flag instead of hardcoded emails
        if current_user.is_super_admin:
            app.logger.info(f"Super admin access granted for: {current_user.email}")
            return  # Acceso completo sin restricciones de plan

        # Determinar el plan a verificar: siempre desde la organización
        plan_a_verificar = None
        entidad_con_plan = None

        org = current_user.organizacion
        if org:
            plan_a_verificar = getattr(org, 'plan_tipo', None) or 'prueba'
            entidad_con_plan = org
        else:
            plan_a_verificar = getattr(current_user, "plan_activo", None)
            entidad_con_plan = current_user

        # Verificar si el plan ha expirado (prueba o pago)
        periodo_vencido = False
        if plan_a_verificar == 'prueba' and entidad_con_plan:
            # Plan de prueba: 30 días desde creación
            if hasattr(entidad_con_plan, 'fecha_creacion') and entidad_con_plan.fecha_creacion:
                from datetime import timedelta
                fecha_limite = entidad_con_plan.fecha_creacion + timedelta(days=30)
                periodo_vencido = datetime.utcnow() > fecha_limite
        elif plan_a_verificar in ('estandar', 'premium', 'full_premium') and entidad_con_plan:
            # Planes pagos: verificar fecha_fin_plan
            fecha_fin = getattr(entidad_con_plan, 'fecha_fin_plan', None)
            if fecha_fin and datetime.utcnow() > fecha_fin:
                periodo_vencido = True

        if periodo_vencido:
            if current_user.role == 'admin':
                if not request.endpoint or not request.endpoint.startswith('planes.'):
                    if plan_a_verificar == 'prueba':
                        flash('Tu período de prueba de 30 días ha expirado. Selecciona un plan para continuar.', 'warning')
                    else:
                        flash('Tu plan ha expirado. Renueva tu suscripción para continuar.', 'warning')
                return redirect(url_for('planes.mostrar_planes'))
            else:
                flash('El plan de tu organización ha expirado. Contacta al administrador.', 'warning')
                return redirect(url_for('index'))

@app.route('/offline')
def offline_page():
    """Página para modo offline."""
    return render_template('offline.html')


@app.route('/robots.txt')
def robots_txt():
    """Servir robots.txt para SEO."""
    return app.send_static_file('robots.txt')


@app.route('/sitemap.xml')
def sitemap_xml():
    """Servir sitemap.xml para SEO."""
    return app.send_static_file('sitemap.xml')


@app.route('/', methods=['GET', 'POST'])
def index():
    """Landing principal con acceso a inicio de sesión y portal de proveedores."""
    if current_user.is_authenticated:
        if getattr(current_user, "role", None) == "operario":
            return redirect(url_for("obras.mis_tareas"))
        return redirect(url_for('reportes.dashboard'))

    next_page = request.values.get('next')
    # Validar que next_page sea una URL interna (prevenir open redirect)
    if next_page:
        from urllib.parse import urlparse
        parsed = urlparse(next_page)
        if parsed.netloc and parsed.netloc != request.host:
            next_page = None
    form_data = {
        'email': request.form.get('email', ''),
        'remember': bool(request.form.get('remember')),
    }

    google_available = False
    login_helper = None
    try:
        from auth import google, authenticate_manual_user  # type: ignore
        google_available = bool(google)
        login_helper = authenticate_manual_user
    except ImportError:
        login_helper = None

    if request.method == 'POST':
        if login_helper is None:
            flash('El módulo de autenticación no está disponible en este entorno.', 'danger')
        else:
            success, payload = login_helper(
                form_data['email'],
                request.form.get('password', ''),
                remember=form_data['remember'],
            )
            if success:
                usuario = payload
                if next_page:
                    return redirect(next_page)
                if getattr(usuario, "role", None) == "operario":
                    return redirect(url_for("obras.mis_tareas"))
                return redirect(url_for('reportes.dashboard'))
            else:
                message = ''
                category = 'danger'
                if isinstance(payload, dict):
                    message = payload.get('message', '')
                    category = payload.get('category', category)
                else:
                    message = str(payload)
                if message:
                    flash(message, category)

    return render_template(
        'public/home.html',
        google_available=google_available,
        form_data=form_data,
        next_value=next_page,
    )

@app.route('/login', endpoint='auth_login')
def legacy_login_redirect():
    """Mantener compatibilidad con rutas antiguas /login"""
    return _login_redirect()

@app.route('/dashboard')
def dashboard():
    if current_user.is_authenticated:
        if getattr(current_user, "role", None) == "operario":
            return redirect(url_for("obras.mis_tareas"))
        return redirect(url_for('reportes.dashboard'))
    return _login_redirect()

# ---------------- Template helpers ----------------
@app.context_processor
def utility_processor():
    from tareas_predefinidas import TAREAS_POR_ETAPA

    def obtener_tareas_para_etapa(nombre_etapa):
        return TAREAS_POR_ETAPA.get(nombre_etapa, [])

    def has_endpoint(endpoint_name: str) -> bool:
        return endpoint_name in app.view_functions

    def tiene_rol_helper(rol: str) -> bool:
        if not current_user.is_authenticated:
            return False

        membership = get_current_membership()
        if membership and membership.status == 'active':
            return (membership.role or '').lower() == (rol or '').lower()

        org_id = session.get('current_org_id')
        if not org_id:
            return False

        from models import OrgMembership  # Import perezoso para evitar ciclos
        registro = (
            OrgMembership.query
            .filter(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == current_user.id,
                db.or_(
                    OrgMembership.archived.is_(False),
                    OrgMembership.archived.is_(None),
                ),
            )
            .first()
        )
        if not registro:
            return False
        if registro.status != 'active':
            return False
        return (registro.role or '').lower() == (rol or '').lower()

    membership = get_current_membership()
    current_org = membership.organizacion if membership else getattr(current_user, 'organizacion', None)

    def formatPrecio(valor):
        """Formatea precio: sin decimales si es entero, con 2 si tiene centavos."""
        try:
            v = float(valor or 0)
        except (ValueError, TypeError):
            v = 0.0
        if v == 0:
            return '0'
        if v == int(v):
            return f'{int(v):,}'.replace(',', '.')
        return f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

    # Plan service context
    try:
        from services.plan_service import inject_plan_context
        plan_ctx = inject_plan_context()
    except Exception:
        plan_ctx = {'plan_info': {}, 'can_feature': lambda f: True}

    result = dict(
        obtener_tareas_para_etapa=obtener_tareas_para_etapa,
        has_endpoint=has_endpoint,
        tiene_rol=tiene_rol_helper,
        formatPrecio=formatPrecio,
        mostrar_calculadora_ia_header=app.config.get("SHOW_IA_CALCULATOR_BUTTON", False),
        current_membership=membership,
        current_organization=current_org,
        current_org_id=get_current_org_id,
    )
    result.update(plan_ctx)
    return result

# ---------------- Template filters ----------------
@app.template_filter('fecha')
def fecha_filter(fecha):
    if fecha:
        return fecha.strftime('%d/%m/%Y')
    return ''

@app.template_filter('moneda')
def moneda_filter(valor, currency: str = 'ARS'):
    try:
        monto = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        monto = Decimal('0')
    symbol = 'US$ ' if (currency or 'ARS').upper() == 'USD' else '$ '
    # Formato argentino: punto para miles, coma para decimales
    formatted = f"{monto:,.0f}".replace(',', '.')
    return f"{symbol}{formatted}"

@app.template_filter('porcentaje')
def porcentaje_filter(valor):
    if valor is None:
        return '0%'
    return f'{valor:.1f}%'

@app.template_filter('entero')
def entero_filter(valor):
    """
    Redondea números hacia arriba (ceil) y formatea como entero con separador de miles.
    Usado para cantidades de materiales que deben mostrarse como números enteros.
    """
    import math
    if valor is None:
        return '0'
    try:
        valor = float(valor)
        valor_ceil = math.ceil(valor)
        return f'{valor_ceil:,}'.replace(',', '.')
    except (ValueError, TypeError):
        return '0'


@app.template_filter('numero')
def numero_filter(valor, decimales=2):
    """
    Formatea números con formato argentino (punto miles, coma decimal).
    Si el número es entero o muy cercano a entero, no muestra decimales.
    """
    if valor is None:
        return '0'
    try:
        valor = float(valor)
        # Si es un número entero (o muy cercano), no mostrar decimales
        # Usar round para manejar problemas de precisión de floats
        valor_redondeado = round(valor, decimales)
        if valor_redondeado == int(valor_redondeado):
            # Formato con punto como separador de miles
            return f'{int(valor_redondeado):,}'.replace(',', '.')
        else:
            # Formato con decimales
            formatted = f'{valor_redondeado:,.{decimales}f}'
            # Eliminar ceros innecesarios al final de los decimales
            if '.' in formatted:
                formatted = formatted.rstrip('0').rstrip('.')
                # Si quedó sin decimales, reformatear como entero
                if '.' not in formatted:
                    return f'{int(float(formatted.replace(",", ""))):,}'.replace(',', '.')
            # Convertir a formato argentino: punto para miles, coma para decimales
            formatted = formatted.replace(',', 'TEMP').replace('.', ',').replace('TEMP', '.')
            return formatted
    except (ValueError, TypeError):
        return '0'

@app.template_filter('estado_badge')
def estado_badge_filter(estado):
    badges = {
        'activo': 'bg-success',
        'inactivo': 'bg-secondary',
        'borrador': 'bg-secondary',
        'enviado': 'bg-warning',
        'aprobado': 'bg-success',
        'rechazado': 'bg-danger',
        'perdido': 'bg-dark',
        'vencido': 'bg-danger',
        'eliminado': 'bg-dark',
        'planificacion': 'bg-secondary',
        'en_progreso': 'bg-primary',
        'pausada': 'bg-warning',
        'finalizada': 'bg-success',
        'cancelada': 'bg-danger'
    }
    return badges.get(estado, 'bg-secondary')

@app.template_filter('obtener_nombre_rol')
def obtener_nombre_rol_filter(codigo_rol):
    try:
        from roles_construccion import obtener_nombre_rol
        return obtener_nombre_rol(codigo_rol)
    except (ImportError, AttributeError, KeyError) as e:
        current_app.logger.warning(f"No se pudo obtener nombre de rol para '{codigo_rol}': {e}")
        return codigo_rol.replace('_', ' ').title() if codigo_rol else 'Sin rol'

@app.template_filter('from_json')
def from_json_filter(json_str):
    if not json_str:
        return {}
    try:
        import json
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        current_app.logger.error(f"Error al parsear JSON en filtro: {e}")
        return {}

# ---------------- Startup tasks & blueprints ----------------
with app.app_context():
    # Import models tardíamente
    from models import Usuario, Organizacion

    # Runtime migrations (extracted for maintainability)
    from runtime_migrations import run_runtime_migrations
    run_runtime_migrations(db, app)

def _import_blueprint(module_name, attr_name):
    """Importa un blueprint de manera segura sin interrumpir el resto."""
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)

# Register blueprints
auth_blueprint_registered = False
core_failures = []

try:
    from auth import oauth  # type: ignore
    auth_bp = _import_blueprint('auth', 'auth_bp')
    oauth.init_app(app)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    auth_blueprint_registered = True
except Exception as exc:
    core_failures.append(f"auth ({exc})")

for module_name, attr_name, prefix in [
    ('obras', 'obras_bp', '/obras'),
    ('equipos', 'equipos_bp', '/equipos'),
    ('inventario', 'inventario_bp', '/inventario'),
    ('marketplaces', 'marketplaces_bp', '/marketplaces'),
    ('reportes', 'reportes_bp', '/reportes'),
    ('asistente_ia', 'asistente_bp', '/asistente'),
    ('cotizacion_inteligente', 'cotizacion_bp', '/cotizacion'),
    ('seguridad_cumplimiento', 'seguridad_bp', '/seguridad'),
    ('planes', 'planes_bp', None),
    ('events_service', 'events_bp', None),
    ('account', 'account_bp', None),
    ('onboarding', 'onboarding_bp', '/onboarding'),
]:
    try:
        blueprint = _import_blueprint(module_name, attr_name)
        app.register_blueprint(blueprint, url_prefix=prefix)
    except Exception as exc:
        core_failures.append(f"{module_name} ({exc})")

if core_failures:
    print("[WARN] Some core blueprints not available: " + "; ".join(core_failures))
else:
    print("[OK] Core blueprints registered successfully")

for module_name, attr_name, prefix in [
    ('blueprint_presupuestos', 'presupuestos_bp', '/presupuestos'),
    ('blueprint_clientes', 'clientes_bp', None),  # usa el prefijo definido en el blueprint
    ('blueprint_requerimientos', 'requerimientos_bp', None),  # Requerimientos de compra desde obras
    ('blueprint_notificaciones', 'notificaciones_bp', None),  # Sistema de notificaciones
    ('agent_local', 'agent_bp', None),
    ('admin_metrics', 'admin_metrics_bp', None),  # Métricas de negocio para super admin
]:
    try:
        blueprint = _import_blueprint(module_name, attr_name)
        app.register_blueprint(blueprint, url_prefix=prefix)

        # CSRF protection is now handled globally via the fetch interceptor
        # in base.html which auto-injects X-CSRFToken on all non-GET requests.
    except Exception as exc:
        app.logger.warning(
            "Blueprint opcional %s no disponible: %s", module_name, exc
        )

_refresh_login_view()

if app.config.get("ENABLE_REPORTS_SERVICE"):
    try:
        import matplotlib  # noqa: F401
        reports_service_bp = _import_blueprint('reports_service', 'reports_bp')
        app.register_blueprint(reports_service_bp)
        print("[OK] Reports service enabled")
    except Exception as exc:
        app.logger.warning("Reports service disabled: %s", exc)
        app.config["ENABLE_REPORTS_SERVICE"] = False
else:
    app.logger.info("Reports service disabled (set ENABLE_REPORTS=1 to enable)")

if not auth_blueprint_registered:

    @app.route('/auth/login', endpoint='auth.login')
    def fallback_auth_login():
        """Fallback login that routes to the supplier portal when auth blueprint is missing."""
        try:
            return redirect(url_for('supplier_auth.login'))
        except BuildError:
            return "Login no disponible temporalmente.", 503

    @app.route('/auth/register', methods=['GET', 'POST'], endpoint='auth.register')
    def fallback_auth_register():
        """Mensaje claro cuando el registro estándar no está disponible."""
        flash('El registro de usuarios no está disponible en este entorno.', 'warning')
        try:
            return redirect(url_for('supplier_auth.registro'))
        except BuildError:
            return "Registro de usuarios no disponible temporalmente.", 503

_refresh_login_view()

# Enhanced blueprints opcionales
try:
    from equipos_new import equipos_new_bp
    # from inventario_new import inventario_new_bp  # Module has issues
    app.register_blueprint(equipos_new_bp, url_prefix='/equipos-new')
    # app.register_blueprint(inventario_new_bp, url_prefix='/inventario-new')  # Disabled

    # Disabled - inventario_new has issues
    # @app.route('/inventario/depositos')
    # @login_required
    # def inventory_depositos_redirect():
    #     return redirect(url_for('inventario_new.warehouses'))

    # @app.route('/inventario/movimientos')
    # @login_required
    # def inventory_movimientos_redirect():
    #     return redirect(url_for('inventario_new.movimientos'))

    # @app.route('/inventario/reservas')
    # @login_required
    # def inventory_reservas_redirect():
    #     return redirect(url_for('inventario_new.reservas'))

    # @app.route('/inventario/alertas')
    # @login_required
    # def inventory_alertas_redirect():
    #     return redirect(url_for('inventario_new.alertas'))
    print("[OK] Enhanced blueprints registered successfully")
except Exception as exc:
    app.logger.warning("Enhanced blueprints not available: %s", exc)

# Supplier portal
try:
    from supplier_auth import supplier_auth_bp
    from supplier_portal import supplier_portal_bp
    from market import market_bp
    app.register_blueprint(supplier_auth_bp)
    app.register_blueprint(supplier_portal_bp)
    app.register_blueprint(market_bp)
    print("[OK] Supplier portal blueprints registered successfully")
except ImportError as e:
    print(f"[WARN] Supplier portal blueprints not available: {e}")

_refresh_login_view()

# Marketplace front
try:
    from marketplace.routes import bp as marketplace_bp
    app.register_blueprint(marketplace_bp, url_prefix="/")
    print("[OK] Marketplace blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Marketplace blueprint not available: {e}")

# Super Admin panel
try:
    from superadmin import superadmin_bp
    app.register_blueprint(superadmin_bp)
    print("[OK] Super Admin blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Super Admin blueprint not available: {e}")

# API Offline para modo sin conexión
try:
    from api_offline import api_offline_bp
    app.register_blueprint(api_offline_bp)
    print("[OK] API Offline blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] API Offline blueprint not available: {e}")

# Admin Equipos Proveedor (Leiten)
try:
    from admin_equipos_leiten import admin_equipos_bp
    app.register_blueprint(admin_equipos_bp)
    print("[OK] Admin Equipos Proveedor blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Admin Equipos Proveedor blueprint not available: {e}")

# Fichadas (ingreso/egreso con geolocalización)
try:
    from fichadas import fichadas_bp
    app.register_blueprint(fichadas_bp)
    print("[OK] Fichadas blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Fichadas blueprint not available: {e}")

# Ordenes de Compra
try:
    from blueprint_ordenes_compra import ordenes_compra_bp
    app.register_blueprint(ordenes_compra_bp)
    print("[OK] Ordenes de Compra blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Ordenes de Compra blueprint not available: {e}")

# Proveedores OC
try:
    from blueprint_proveedores_oc import proveedores_oc_bp
    app.register_blueprint(proveedores_oc_bp)
    print("[OK] Proveedores OC blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Proveedores OC blueprint not available: {e}")

# Cotizaciones de Proveedores
try:
    from blueprint_cotizaciones import cotizaciones_bp
    app.register_blueprint(cotizaciones_bp)
    print("[OK] Cotizaciones blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Cotizaciones blueprint not available: {e}")

# Caja (Transferencias oficina -> obra)
try:
    from blueprint_caja import caja_bp
    app.register_blueprint(caja_bp)
    print("[OK] Caja blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Caja blueprint not available: {e}")

# Documentos de Obra (Legajo Digital)
try:
    from control_documentos import documentos_bp
    app.register_blueprint(documentos_bp)
    print("[OK] Documentos blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Documentos blueprint not available: {e}")

_refresh_login_view()

# --- Public legal pages fallbacks ---------------------------------------
if 'terminos' not in app.view_functions:
    app.add_url_rule('/terminos', endpoint='terminos',
                     view_func=lambda: render_template('legal/terminos.html'))

if 'privacidad' not in app.view_functions:
    app.add_url_rule('/privacidad', endpoint='privacidad',
                     view_func=lambda: render_template('legal/privacidad.html'))

# --- Manual de usuario ---
if 'manual' not in app.view_functions:
    app.add_url_rule('/manual', endpoint='manual',
                     view_func=lambda: render_template('ayuda/manual.html'))
    app.add_url_rule('/ayuda', endpoint='ayuda',
                     view_func=lambda: render_template('ayuda/manual.html'))

if 'reportes.dashboard' not in app.view_functions:
    @app.route('/reportes/dashboard', endpoint='reportes.dashboard')
    @login_required
    def fallback_reportes_dashboard():
        """Proporciona un dashboard básico cuando el módulo de reportes falta."""
        flash('El dashboard avanzado no está disponible en este entorno reducido.', 'warning')
        fallback_url = None
        for endpoint in ('obras.lista', 'supplier_portal.dashboard', 'index'):
            try:
                fallback_url = url_for(endpoint)
                break
            except BuildError:
                continue

        return render_template(
            'errors/dashboard_unavailable.html',
            fallback_url=fallback_url,
        ), 200

_refresh_login_view()

# === MEDIA SERVING ENDPOINT ===
@app.route("/media/<path:relpath>")
@login_required
def serve_media(relpath):
    """Serve authenticated media files from /media/ directory with org verification."""
    import re
    from services.memberships import get_current_org_id
    from models import Obra

    media_dir = Path(app.instance_path) / "media"

    # Verificar que el archivo pertenece a la organización del usuario
    # Estructura esperada: obras/{obra_id}/... o similar
    match = re.match(r'obras/(\d+)/', relpath)
    if match:
        obra_id = int(match.group(1))
        org_id = get_current_org_id()
        if org_id:
            obra = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first()
            if not obra:
                abort(403)

    return send_from_directory(media_dir, relpath)


@app.route("/secure-uploads/<path:relpath>")
@login_required
def serve_secure_upload(relpath):
    """Serve upload files with authentication and org verification.
    This replaces direct access to static/uploads/ which is publicly accessible.
    """
    import re
    from services.memberships import get_current_org_id
    from models import Obra

    uploads_dir = Path(app.static_folder) / "uploads"

    # Verificar que el archivo pertenece a la organización del usuario
    match = re.match(r'obras/(\d+)/', relpath)
    if match:
        obra_id = int(match.group(1))
        org_id = get_current_org_id()
        if org_id:
            obra = Obra.query.filter_by(id=obra_id, organizacion_id=org_id).first()
            if not obra:
                abort(403)

    return send_from_directory(uploads_dir, relpath)

# === SERVICE WORKER ENDPOINT ===
@app.route("/sw.js")
def service_worker():
    """Serve Service Worker from root directory - no cache para forzar updates"""
    from flask import make_response
    response = make_response(send_from_directory(".", "sw.js", mimetype="application/javascript"))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# === ENDPOINTS TEMPORALES DDL ELIMINADOS POR AUDITORÍA DE SEGURIDAD (2026-04-06) ===
# /admin/fix-etapa-nombre, /admin/fix-security-tables y /admin/diagnostico
# fueron removidos por exponer DDL y diagnósticos vía HTTP.
# Usar migraciones Alembic y CLI de Flask para estas operaciones.

# === HEALTH CHECK ENDPOINTS ===
@app.route("/health")
def health_check():
    """Health check básico para load balancers"""
    return {"status": "healthy", "app": "obyra"}, 200

@app.route("/health/detailed")
def health_check_detailed():
    """Health check detallado que verifica todas las dependencias"""
    from sqlalchemy import text

    checks = {
        "app": "healthy",
        "database": "unknown",
        "redis": "unknown"
    }
    status_code = 200

    # Verificar PostgreSQL
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)[:50]}"
        status_code = 503

    # Verificar Redis (si está configurado)
    try:
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            import redis
            r = redis.from_url(redis_url)
            r.ping()
            checks["redis"] = "healthy"
        else:
            checks["redis"] = "not_configured"
    except Exception as e:
        checks["redis"] = f"unhealthy: {str(e)[:50]}"
        # Redis no es crítico, no cambiamos status_code

    overall_status = "healthy" if status_code == 200 else "degraded"
    return {"status": overall_status, "checks": checks}, status_code

# Error handlers
@app.errorhandler(403)
def forbidden(error):
    app.logger.warning(f'403 Forbidden: {request.url} - User: {current_user.email if current_user.is_authenticated else "anonymous"}')
    return render_template('errors/403.html'), 403

@app.errorhandler(401)
def unauthorized_error(error):
    app.logger.warning(f'401 Unauthorized: {request.url} - User: {current_user.email if current_user.is_authenticated else "anonymous"}')
    if request.path.startswith('/obras/api/') or request.path.startswith('/api/'):
        from flask import jsonify
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    return _login_redirect()

@app.errorhandler(404)
def not_found(error):
    app.logger.warning(f'404 Not Found: {request.url}')
    try:
        dashboard_url = url_for('reportes.dashboard')
    except BuildError:
        try:
            dashboard_url = url_for('supplier_portal.dashboard')
        except BuildError:
            dashboard_url = url_for('index')
    return render_template('errors/404.html', dashboard_url=dashboard_url), 404

@app.errorhandler(500)
def internal_error(error):
    import traceback, sys
    # Forzar output a stderr para que Railway lo muestre en logs
    print(f'===== 500 ERROR: {request.url} =====', file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    print(f'===== END 500 ERROR =====', file=sys.stderr, flush=True)
    app.logger.error(f'500 Internal Server Error: {request.url}', exc_info=True)
    db.session.rollback()
    try:
        return render_template('errors/500.html'), 500
    except Exception:
        # Fallback si el template falla
        return 'Error interno del servidor', 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))  # Use port 5002 by default (5000 conflicts with macOS AirPlay)
    # DEBUG solo se activa si FLASK_DEBUG=1 (nunca en producción)
    debug_mode = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

