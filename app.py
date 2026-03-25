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

# PostgreSQL-optimized connection pooling
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_size": 10,           # Conexiones en el pool
    "max_overflow": 20,        # Conexiones adicionales si el pool está lleno
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
extensions.limiter = setup_rate_limiter(app)

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

        # Verificar si el plan es de prueba y ya expiró
        if plan_a_verificar == 'prueba' and entidad_con_plan:
            # Verificar expiración: usar fecha_creacion de la org para calcular 30 días
            periodo_vencido = False
            if hasattr(entidad_con_plan, 'fecha_creacion') and entidad_con_plan.fecha_creacion:
                from datetime import timedelta
                fecha_limite = entidad_con_plan.fecha_creacion + timedelta(days=30)
                periodo_vencido = datetime.utcnow() > fecha_limite

            if periodo_vencido:
                if current_user.role == 'admin':
                    if not request.endpoint or not request.endpoint.startswith('planes.'):
                        flash('Tu período de prueba de 30 días ha expirado. Selecciona un plan para continuar.', 'warning')
                    return redirect(url_for('planes.mostrar_planes'))
                else:
                    flash('El período de prueba de tu organización ha expirado. Contacta al administrador.', 'warning')
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

    return dict(
        obtener_tareas_para_etapa=obtener_tareas_para_etapa,
        has_endpoint=has_endpoint,
        tiene_rol=tiene_rol_helper,
        formatPrecio=formatPrecio,
        mostrar_calculadora_ia_header=app.config.get("SHOW_IA_CALCULATOR_BUTTON", False),
        current_membership=membership,
        current_organization=current_org,
        current_org_id=get_current_org_id,
    )

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

    # ============================================================================
    # PHASE 4 REFACTORING (Nov 2025):
    # Runtime migrations have been converted to Alembic migrations.
    # All schema changes are now in migrations/versions/*.py
    #
    # To apply pending migrations:
    #   docker-compose exec app alembic upgrade head
    #
    # Legacy file: migrations_runtime.py → _migrations_runtime_old.py
    # ============================================================================

    # En Railway/producción: crear todas las tablas si no existen
    # Esto es necesario porque las migraciones de Alembic usan schema "app"
    # que no existe en Railway (usa "public" por defecto)
    _is_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None or \
                  os.getenv("RAILWAY_PROJECT_ID") is not None
    if _is_railway:
        try:
            db.create_all()
            print("[OK] Railway: All database tables created/verified")
        except Exception as e:
            print(f"[WARN] Railway db.create_all() error: {e}")

    # Migración automática: agregar columnas de planes a organizaciones
    try:
        from sqlalchemy import text
        plan_columns_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='plan_tipo') THEN
                ALTER TABLE organizaciones ADD COLUMN plan_tipo VARCHAR(50) DEFAULT 'prueba';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='max_usuarios') THEN
                ALTER TABLE organizaciones ADD COLUMN max_usuarios INTEGER DEFAULT 5;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='fecha_inicio_plan') THEN
                ALTER TABLE organizaciones ADD COLUMN fecha_inicio_plan TIMESTAMP;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='fecha_fin_plan') THEN
                ALTER TABLE organizaciones ADD COLUMN fecha_fin_plan TIMESTAMP;
            END IF;
        END $$;
        """
        db.session.execute(text(plan_columns_sql))
        db.session.commit()
        print("[OK] Plan columns migration applied")
    except Exception as e:
        print(f"[WARN] Plan columns migration skipped: {e}")

    # Migración automática: columnas faltantes en Railway
    try:
        missing_cols_sql = """
        DO $$
        BEGIN
            -- logo_url en organizaciones
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='logo_url') THEN
                ALTER TABLE organizaciones ADD COLUMN logo_url VARCHAR(500);
            END IF;
            -- logo_url en proveedores
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='proveedores' AND column_name='logo_url') THEN
                ALTER TABLE proveedores ADD COLUMN logo_url VARCHAR(500);
            END IF;
            -- confirmado_como_obra en presupuestos
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='presupuestos' AND column_name='confirmado_como_obra') THEN
                ALTER TABLE presupuestos ADD COLUMN confirmado_como_obra BOOLEAN DEFAULT false;
            END IF;
        END $$;
        """
        db.session.execute(text(missing_cols_sql))
        db.session.commit()
        print("[OK] Missing columns migration applied (logo_url, confirmado_como_obra)")
    except Exception as e:
        print(f"[WARN] Missing columns migration skipped: {e}")

    # Migración: tabla niveles_presupuesto y columna nivel_nombre
    try:
        niveles_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='niveles_presupuesto') THEN
                CREATE TABLE niveles_presupuesto (
                    id SERIAL PRIMARY KEY,
                    presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id),
                    tipo_nivel VARCHAR(30) NOT NULL,
                    nombre VARCHAR(100) NOT NULL,
                    orden INTEGER NOT NULL DEFAULT 0,
                    repeticiones INTEGER NOT NULL DEFAULT 1,
                    area_m2 NUMERIC(10,2) NOT NULL,
                    sistema_constructivo VARCHAR(30) NOT NULL DEFAULT 'hormigon',
                    atributos JSONB DEFAULT '{}'::jsonb
                );
                CREATE INDEX ix_niveles_pres_id ON niveles_presupuesto(presupuesto_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='items_presupuesto' AND column_name='nivel_nombre') THEN
                ALTER TABLE items_presupuesto ADD COLUMN nivel_nombre VARCHAR(100);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='niveles_presupuesto' AND column_name='hormigon_m3') THEN
                ALTER TABLE niveles_presupuesto ADD COLUMN hormigon_m3 NUMERIC(10,2) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='niveles_presupuesto' AND column_name='albanileria_m2') THEN
                ALTER TABLE niveles_presupuesto ADD COLUMN albanileria_m2 NUMERIC(10,2) DEFAULT 0;
            END IF;
        END $$;
        """
        db.session.execute(text(niveles_sql))
        db.session.commit()
        print("[OK] Niveles presupuesto migration applied")
    except Exception as e:
        print(f"[WARN] Niveles presupuesto migration skipped: {e}")

    # Fichadas table + radio_fichada_metros column
    try:
        fichadas_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_schema='public' AND table_name='fichadas') THEN
                CREATE TABLE fichadas (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    tipo VARCHAR(10) NOT NULL,
                    fecha_hora TIMESTAMP NOT NULL DEFAULT NOW(),
                    latitud NUMERIC(10,8),
                    longitud NUMERIC(11,8),
                    precision_gps NUMERIC(8,2),
                    distancia_obra NUMERIC(8,2),
                    dentro_rango BOOLEAN DEFAULT FALSE,
                    ip_address VARCHAR(45),
                    user_agent VARCHAR(300),
                    nota TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX idx_fichadas_usuario ON fichadas(usuario_id);
                CREATE INDEX idx_fichadas_obra ON fichadas(obra_id);
                CREATE INDEX idx_fichadas_fecha ON fichadas(fecha_hora);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='obras' AND column_name='radio_fichada_metros') THEN
                ALTER TABLE obras ADD COLUMN radio_fichada_metros INTEGER DEFAULT 200;
            END IF;
        END $$;
        """
        db.session.execute(text(fichadas_sql))
        db.session.commit()
        print("[OK] Fichadas migration applied")
    except Exception as e:
        print(f"[WARN] Fichadas migration skipped: {e}")

    # Migración: campos de precio de compra en requerimiento_compra_items
    try:
        compra_items_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='precio_unitario_compra') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN precio_unitario_compra NUMERIC(15,2);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='cantidad_comprada') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN cantidad_comprada NUMERIC(10,3);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='proveedor_compra') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN proveedor_compra VARCHAR(200);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='factura_compra') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN factura_compra VARCHAR(100);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='fecha_compra') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN fecha_compra DATE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='fecha_pedido') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN fecha_pedido DATE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='fecha_entrega_aprox') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN fecha_entrega_aprox DATE;
            END IF;
        END $$;
        """
        db.session.execute(text(compra_items_sql))
        db.session.commit()
        print("[OK] Requerimiento compra items price fields migration applied")
    except Exception as e:
        print(f"[WARN] Requerimiento compra items migration skipped: {e}")

    # Ordenes de Compra + Recepciones + CAJA tables
    try:
        oc_sql = """
        DO $$
        BEGIN
            -- Ordenes de compra
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='ordenes_compra') THEN
                CREATE TABLE ordenes_compra (
                    id SERIAL PRIMARY KEY,
                    numero VARCHAR(20) UNIQUE NOT NULL,
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    requerimiento_id INTEGER REFERENCES requerimientos_compra(id),
                    proveedor VARCHAR(200) NOT NULL,
                    proveedor_cuit VARCHAR(20),
                    proveedor_contacto VARCHAR(200),
                    estado VARCHAR(20) DEFAULT 'borrador',
                    moneda VARCHAR(3) DEFAULT 'ARS',
                    subtotal NUMERIC(15,2) DEFAULT 0,
                    iva NUMERIC(15,2) DEFAULT 0,
                    total NUMERIC(15,2) DEFAULT 0,
                    fecha_emision DATE,
                    fecha_entrega_estimada DATE,
                    fecha_entrega_real DATE,
                    condicion_pago VARCHAR(100),
                    notas TEXT,
                    created_by_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_oc_org ON ordenes_compra(organizacion_id);
                CREATE INDEX ix_oc_obra ON ordenes_compra(obra_id);
                CREATE INDEX ix_oc_estado ON ordenes_compra(estado);
            END IF;

            -- Items de OC
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='orden_compra_items') THEN
                CREATE TABLE orden_compra_items (
                    id SERIAL PRIMARY KEY,
                    orden_compra_id INTEGER NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
                    item_inventario_id INTEGER REFERENCES items_inventario(id),
                    descripcion VARCHAR(300) NOT NULL,
                    cantidad NUMERIC(10,3) NOT NULL,
                    unidad VARCHAR(30) DEFAULT 'unidad',
                    precio_unitario NUMERIC(15,2) DEFAULT 0,
                    subtotal NUMERIC(15,2) DEFAULT 0,
                    cantidad_recibida NUMERIC(10,3) DEFAULT 0
                );
                CREATE INDEX ix_oci_oc ON orden_compra_items(orden_compra_id);
            END IF;

            -- Recepciones de OC
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='recepciones_oc') THEN
                CREATE TABLE recepciones_oc (
                    id SERIAL PRIMARY KEY,
                    orden_compra_id INTEGER NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
                    fecha_recepcion DATE NOT NULL,
                    recibido_por_id INTEGER NOT NULL REFERENCES usuarios(id),
                    remito_numero VARCHAR(100),
                    notas TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_rec_oc ON recepciones_oc(orden_compra_id);
            END IF;

            -- Items de recepcion
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='recepcion_oc_items') THEN
                CREATE TABLE recepcion_oc_items (
                    id SERIAL PRIMARY KEY,
                    recepcion_id INTEGER NOT NULL REFERENCES recepciones_oc(id) ON DELETE CASCADE,
                    oc_item_id INTEGER NOT NULL REFERENCES orden_compra_items(id),
                    cantidad_recibida NUMERIC(10,3) NOT NULL
                );
                CREATE INDEX ix_reci_rec ON recepcion_oc_items(recepcion_id);
            END IF;

            -- Movimientos de Caja
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='movimientos_caja') THEN
                CREATE TABLE movimientos_caja (
                    id SERIAL PRIMARY KEY,
                    numero VARCHAR(20) UNIQUE NOT NULL,
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    tipo VARCHAR(20) NOT NULL,
                    monto NUMERIC(15,2) NOT NULL,
                    moneda VARCHAR(3) DEFAULT 'ARS',
                    concepto VARCHAR(300),
                    referencia VARCHAR(100),
                    orden_compra_id INTEGER REFERENCES ordenes_compra(id),
                    fecha_movimiento DATE NOT NULL,
                    estado VARCHAR(20) DEFAULT 'pendiente',
                    comprobante_url VARCHAR(500),
                    created_by_id INTEGER REFERENCES usuarios(id),
                    confirmado_por_id INTEGER REFERENCES usuarios(id),
                    fecha_confirmacion TIMESTAMP,
                    notas TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_mc_org ON movimientos_caja(organizacion_id);
                CREATE INDEX ix_mc_obra ON movimientos_caja(obra_id);
                CREATE INDEX ix_mc_estado ON movimientos_caja(estado);
            END IF;

            -- Tipos de documento (para Legajo Digital)
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='tipos_documento') THEN
                CREATE TABLE tipos_documento (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    categoria VARCHAR(50) NOT NULL,
                    requiere_aprobacion BOOLEAN DEFAULT FALSE,
                    retencion_anos INTEGER DEFAULT 10,
                    activo BOOLEAN DEFAULT TRUE
                );
                INSERT INTO tipos_documento (nombre, categoria) VALUES
                    ('Contrato', 'contractual'),
                    ('Planos', 'tecnico'),
                    ('Renders', 'tecnico'),
                    ('Pliego de Especificaciones', 'tecnico'),
                    ('Memoria de Calculo', 'tecnico'),
                    ('Presupuesto', 'administrativo'),
                    ('Otros', 'general');
            END IF;

            -- Documentos de obra
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='documentos_obra') THEN
                CREATE TABLE documentos_obra (
                    id SERIAL PRIMARY KEY,
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    tipo_documento_id INTEGER NOT NULL REFERENCES tipos_documento(id),
                    organizacion_id INTEGER REFERENCES organizaciones(id),
                    nombre VARCHAR(200) NOT NULL,
                    descripcion TEXT,
                    archivo_path VARCHAR(500) NOT NULL,
                    version VARCHAR(10) DEFAULT '1.0',
                    estado VARCHAR(20) DEFAULT 'activo',
                    fecha_creacion TIMESTAMP DEFAULT NOW(),
                    fecha_modificacion TIMESTAMP DEFAULT NOW(),
                    creado_por_id INTEGER NOT NULL REFERENCES usuarios(id),
                    tags VARCHAR(500)
                );
                CREATE INDEX ix_do_obra ON documentos_obra(obra_id);
                CREATE INDEX ix_do_tipo ON documentos_obra(tipo_documento_id);
            END IF;
        END $$;
        """
        db.session.execute(text(oc_sql))
        db.session.commit()
        print("[OK] OC + Caja + Documentos tables migration applied")
    except Exception as e:
        print(f"[WARN] OC + Caja + Documentos migration skipped: {e}")

    # Proveedores OC + Historial precios
    try:
        prov_sql = """
        DO $$ BEGIN
            -- Proveedores OC
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='proveedores_oc') THEN
                CREATE TABLE proveedores_oc (
                    id SERIAL PRIMARY KEY,
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    razon_social VARCHAR(200) NOT NULL,
                    nombre_fantasia VARCHAR(200),
                    cuit VARCHAR(20),
                    tipo VARCHAR(50) DEFAULT 'materiales',
                    email VARCHAR(200),
                    telefono VARCHAR(50),
                    direccion VARCHAR(300),
                    ciudad VARCHAR(100),
                    provincia VARCHAR(100),
                    contacto_nombre VARCHAR(200),
                    contacto_telefono VARCHAR(50),
                    condicion_pago VARCHAR(100),
                    notas TEXT,
                    activo BOOLEAN DEFAULT TRUE,
                    created_by_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_prov_oc_org ON proveedores_oc(organizacion_id);
                CREATE INDEX ix_prov_oc_activo ON proveedores_oc(activo);
            END IF;

            -- Historial de precios proveedor
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='historial_precios_proveedor') THEN
                CREATE TABLE historial_precios_proveedor (
                    id SERIAL PRIMARY KEY,
                    proveedor_id INTEGER NOT NULL REFERENCES proveedores_oc(id),
                    item_inventario_id INTEGER REFERENCES items_inventario(id),
                    descripcion_item VARCHAR(300) NOT NULL,
                    precio_unitario NUMERIC(15,2) NOT NULL,
                    moneda VARCHAR(3) DEFAULT 'ARS',
                    orden_compra_id INTEGER REFERENCES ordenes_compra(id),
                    fecha DATE NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_hpp_prov ON historial_precios_proveedor(proveedor_id);
                CREATE INDEX ix_hpp_item ON historial_precios_proveedor(item_inventario_id);
            END IF;

            -- Agregar FK proveedor_oc_id a ordenes_compra si no existe
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='ordenes_compra' AND column_name='proveedor_oc_id') THEN
                ALTER TABLE ordenes_compra ADD COLUMN proveedor_oc_id INTEGER REFERENCES proveedores_oc(id);
            END IF;
        END $$;
        """
        db.session.execute(text(prov_sql))
        db.session.commit()
        print("[OK] Proveedores OC tables migration applied")
    except Exception as e:
        print(f"[WARN] Proveedores OC migration skipped: {e}")

    # Cotizaciones de proveedor tables
    try:
        cot_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='cotizaciones_proveedor') THEN
                CREATE TABLE cotizaciones_proveedor (
                    id SERIAL PRIMARY KEY,
                    requerimiento_id INTEGER NOT NULL REFERENCES requerimientos_compra(id),
                    proveedor_oc_id INTEGER NOT NULL REFERENCES proveedores_oc(id),
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    estado VARCHAR(20) DEFAULT 'borrador',
                    moneda VARCHAR(3) DEFAULT 'ARS',
                    condicion_pago VARCHAR(100),
                    plazo_entrega VARCHAR(100),
                    validez VARCHAR(100),
                    notas TEXT,
                    subtotal NUMERIC(15,2) DEFAULT 0,
                    total NUMERIC(15,2) DEFAULT 0,
                    fecha_solicitud TIMESTAMP DEFAULT NOW(),
                    fecha_recepcion TIMESTAMP,
                    created_by_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_cot_prov_req ON cotizaciones_proveedor(requerimiento_id);
                CREATE INDEX ix_cot_prov_org ON cotizaciones_proveedor(organizacion_id);
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='cotizacion_proveedor_items') THEN
                CREATE TABLE cotizacion_proveedor_items (
                    id SERIAL PRIMARY KEY,
                    cotizacion_id INTEGER NOT NULL REFERENCES cotizaciones_proveedor(id) ON DELETE CASCADE,
                    requerimiento_item_id INTEGER REFERENCES requerimiento_compra_items(id),
                    precio_unitario NUMERIC(15,2) DEFAULT 0,
                    subtotal NUMERIC(15,2) DEFAULT 0,
                    descripcion VARCHAR(300) NOT NULL,
                    cantidad NUMERIC(10,3) NOT NULL,
                    unidad VARCHAR(30) DEFAULT 'unidad',
                    item_inventario_id INTEGER REFERENCES items_inventario(id),
                    notas TEXT
                );
                CREATE INDEX ix_cot_item_cot ON cotizacion_proveedor_items(cotizacion_id);
                CREATE INDEX ix_cot_item_req ON cotizacion_proveedor_items(requerimiento_item_id);
            END IF;
        END $$;
        """
        db.session.execute(text(cot_sql))
        db.session.commit()
        print("[OK] Cotizaciones proveedor tables migration applied")
    except Exception as e:
        print(f"[WARN] Cotizaciones proveedor migration skipped: {e}")

    # Modalidad compra/alquiler en cotizacion_proveedor_items
    try:
        db.session.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name='cotizacion_proveedor_items' AND column_name='modalidad') THEN
                ALTER TABLE cotizacion_proveedor_items ADD COLUMN modalidad VARCHAR(20) DEFAULT 'compra';
                ALTER TABLE cotizacion_proveedor_items ADD COLUMN dias_alquiler INTEGER;
            END IF;
        END $$;
        """))
        db.session.commit()
        print("[OK] Cotizaciones modalidad compra/alquiler migration applied")
    except Exception as e:
        print(f"[WARN] Cotizaciones modalidad migration skipped: {e}")

    # Remitos + Stock Obra tables
    try:
        remitos_sql = """
        DO $$
        BEGIN
            -- Remitos
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='remitos') THEN
                CREATE TABLE remitos (
                    id SERIAL PRIMARY KEY,
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    requerimiento_id INTEGER REFERENCES requerimientos_compra(id),
                    numero_remito VARCHAR(50) NOT NULL,
                    proveedor VARCHAR(200) NOT NULL,
                    fecha DATE,
                    estado VARCHAR(30) DEFAULT 'recibido',
                    notas TEXT,
                    archivo_url VARCHAR(500),
                    recibido_por_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_remito_obra ON remitos(obra_id);
                CREATE INDEX ix_remito_req ON remitos(requerimiento_id);
            END IF;

            -- Items de remito
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='remito_items') THEN
                CREATE TABLE remito_items (
                    id SERIAL PRIMARY KEY,
                    remito_id INTEGER NOT NULL REFERENCES remitos(id) ON DELETE CASCADE,
                    descripcion VARCHAR(300) NOT NULL,
                    cantidad NUMERIC(10,3) NOT NULL,
                    unidad VARCHAR(20) DEFAULT 'u',
                    observacion VARCHAR(300)
                );
                CREATE INDEX ix_remito_item_remito ON remito_items(remito_id);
            END IF;

            -- Stock en obra
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='stock_obra') THEN
                CREATE TABLE stock_obra (
                    id SERIAL PRIMARY KEY,
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    item_inventario_id INTEGER NOT NULL REFERENCES items_inventario(id),
                    cantidad_disponible NUMERIC(12,3) DEFAULT 0,
                    cantidad_consumida NUMERIC(12,3) DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_stock_obra_item UNIQUE (obra_id, item_inventario_id)
                );
                CREATE INDEX ix_stock_obra_obra ON stock_obra(obra_id);
            END IF;

            -- Movimientos de stock en obra
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='movimientos_stock_obra') THEN
                CREATE TABLE movimientos_stock_obra (
                    id SERIAL PRIMARY KEY,
                    stock_obra_id INTEGER NOT NULL REFERENCES stock_obra(id) ON DELETE CASCADE,
                    tipo VARCHAR(20) NOT NULL,
                    cantidad NUMERIC(12,3) NOT NULL,
                    precio_unitario NUMERIC(15,2),
                    motivo VARCHAR(300),
                    usuario_id INTEGER REFERENCES usuarios(id),
                    reserva_id INTEGER,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_mso_stock ON movimientos_stock_obra(stock_obra_id);
            END IF;
        END $$;
        """
        db.session.execute(text(remitos_sql))
        db.session.commit()
        print("[OK] Remitos + Stock Obra tables migration applied")
    except Exception as e:
        print(f"[WARN] Remitos + Stock Obra migration skipped: {e}")

    # Remito <-> OC vinculación
    try:
        remito_oc_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='requerimiento_id') THEN
                ALTER TABLE remitos ADD COLUMN requerimiento_id INTEGER REFERENCES requerimientos_compra(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='proveedor_oc_id') THEN
                ALTER TABLE remitos ADD COLUMN proveedor_oc_id INTEGER REFERENCES proveedores_oc(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='recibido_por_id') THEN
                ALTER TABLE remitos ADD COLUMN recibido_por_id INTEGER REFERENCES usuarios(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='archivo_url') THEN
                ALTER TABLE remitos ADD COLUMN archivo_url VARCHAR(500);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='created_by_id') THEN
                ALTER TABLE remitos ADD COLUMN created_by_id INTEGER REFERENCES usuarios(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='updated_at') THEN
                ALTER TABLE remitos ADD COLUMN updated_at TIMESTAMP;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='orden_compra_id') THEN
                ALTER TABLE remitos ADD COLUMN orden_compra_id INTEGER REFERENCES ordenes_compra(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remito_items' AND column_name='oc_item_id') THEN
                ALTER TABLE remito_items ADD COLUMN oc_item_id INTEGER REFERENCES orden_compra_items(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remito_items' AND column_name='item_inventario_id') THEN
                ALTER TABLE remito_items ADD COLUMN item_inventario_id INTEGER REFERENCES items_inventario(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remito_items' AND column_name='precio_unitario') THEN
                ALTER TABLE remito_items ADD COLUMN precio_unitario NUMERIC(15,2);
            END IF;
        END $$;
        """
        db.session.execute(text(remito_oc_sql))
        db.session.commit()
        print("[OK] Remito-OC vinculacion migration applied")
    except Exception as e:
        print(f"[WARN] Remito-OC migration skipped: {e}")

    # Etapa dependencies and chaining
    try:
        dep_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='etapas_obra' AND column_name='nivel_encadenamiento') THEN
                ALTER TABLE etapas_obra ADD COLUMN nivel_encadenamiento INTEGER;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='etapas_obra' AND column_name='fechas_manuales') THEN
                ALTER TABLE etapas_obra ADD COLUMN fechas_manuales BOOLEAN DEFAULT false;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='etapas_obra' AND column_name='es_opcional') THEN
                ALTER TABLE etapas_obra ADD COLUMN es_opcional BOOLEAN DEFAULT false;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='etapa_dependencias') THEN
                CREATE TABLE etapa_dependencias (
                    id SERIAL PRIMARY KEY,
                    etapa_id INTEGER NOT NULL REFERENCES etapas_obra(id) ON DELETE CASCADE,
                    depende_de_id INTEGER NOT NULL REFERENCES etapas_obra(id) ON DELETE CASCADE,
                    tipo VARCHAR(10) DEFAULT 'FS',
                    lag_dias INTEGER DEFAULT 0,
                    UNIQUE(etapa_id, depende_de_id)
                );
                CREATE INDEX idx_etapa_dep_etapa ON etapa_dependencias(etapa_id);
                CREATE INDEX idx_etapa_dep_depende ON etapa_dependencias(depende_de_id);
            END IF;
        END $$;
        """
        db.session.execute(text(dep_sql))
        db.session.commit()
        print("[OK] Etapa dependencies migration applied")
    except Exception as e:
        print(f"[WARN] Etapa dependencies migration skipped: {e}")

    # max_obras en organizaciones
    try:
        db.session.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='max_obras') THEN
                ALTER TABLE organizaciones ADD COLUMN max_obras INTEGER DEFAULT 1;
            END IF;
        END $$;
        """))
        db.session.commit()
        print("[OK] max_obras migration applied")
    except Exception as e:
        print(f"[WARN] max_obras migration skipped: {e}")

    # Equipment: nuevos campos + tabla equipment_movement
    try:
        equip_sql = """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_hora') THEN
                ALTER TABLE equipment ADD COLUMN costo_hora NUMERIC(12,2) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='nro_serie') THEN
                ALTER TABLE equipment ADD COLUMN nro_serie VARCHAR(100);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='codigo') THEN
                ALTER TABLE equipment ADD COLUMN codigo VARCHAR(50);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_adquisicion') THEN
                ALTER TABLE equipment ADD COLUMN costo_adquisicion NUMERIC(15,2) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='vida_util_anios') THEN
                ALTER TABLE equipment ADD COLUMN vida_util_anios INTEGER;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='ubicacion_tipo') THEN
                ALTER TABLE equipment ADD COLUMN ubicacion_tipo VARCHAR(20) DEFAULT 'deposito';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='ubicacion_obra_id') THEN
                ALTER TABLE equipment ADD COLUMN ubicacion_obra_id INTEGER REFERENCES obras(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='moneda') THEN
                ALTER TABLE equipment ADD COLUMN moneda VARCHAR(3) DEFAULT 'ARS';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_hora_usd') THEN
                ALTER TABLE equipment ADD COLUMN costo_hora_usd NUMERIC(12,2);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_adquisicion_usd') THEN
                ALTER TABLE equipment ADD COLUMN costo_adquisicion_usd NUMERIC(15,2);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='equipment_movement') THEN
                CREATE TABLE equipment_movement (
                    id SERIAL PRIMARY KEY,
                    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
                    company_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    tipo VARCHAR(20) NOT NULL,
                    origen_tipo VARCHAR(20) NOT NULL,
                    origen_obra_id INTEGER REFERENCES obras(id),
                    destino_tipo VARCHAR(20) NOT NULL,
                    destino_obra_id INTEGER REFERENCES obras(id),
                    fecha_movimiento TIMESTAMP NOT NULL DEFAULT NOW(),
                    fecha_llegada TIMESTAMP,
                    estado VARCHAR(20) DEFAULT 'en_transito',
                    despachado_por INTEGER NOT NULL REFERENCES usuarios(id),
                    recibido_por INTEGER REFERENCES usuarios(id),
                    notas TEXT,
                    costo_transporte NUMERIC(12,2) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX idx_eqmov_equipment ON equipment_movement(equipment_id);
                CREATE INDEX idx_eqmov_company ON equipment_movement(company_id);
                CREATE INDEX idx_eqmov_destino ON equipment_movement(destino_obra_id);
            END IF;
        END $$;
        """
        db.session.execute(text(equip_sql))
        db.session.commit()
        print("[OK] Equipment movement migration applied")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Equipment movement migration skipped: {e}")

    # RBAC tables and seeding
    try:
        from models import RoleModule, UserModule, seed_default_role_permissions

        # Create RBAC tables if they don't exist
        RoleModule.__table__.create(db.engine, checkfirst=True)
        UserModule.__table__.create(db.engine, checkfirst=True)

        # Seed default permissions
        seed_default_role_permissions()
        print("[OK] RBAC permissions seeded successfully")
    except Exception as e:
        print(f"[WARN] RBAC seeding skipped: {e}")

    # Marketplace tables mínimas
    try:
        from marketplace.models import (
            MkProduct, MkProductVariant, MkCart, MkCartItem,
            MkOrder, MkOrderItem, MkPayment, MkPurchaseOrder, MkCommission
        )
        MkProduct.__table__.create(db.engine, checkfirst=True)
        MkProductVariant.__table__.create(db.engine, checkfirst=True)
        MkCart.__table__.create(db.engine, checkfirst=True)
        MkCartItem.__table__.create(db.engine, checkfirst=True)
        MkOrder.__table__.create(db.engine, checkfirst=True)
        MkOrderItem.__table__.create(db.engine, checkfirst=True)
        MkPayment.__table__.create(db.engine, checkfirst=True)
        MkPurchaseOrder.__table__.create(db.engine, checkfirst=True)
        MkCommission.__table__.create(db.engine, checkfirst=True)

        if not MkCommission.query.first():
            commission_rates = [
                MkCommission(category_id=1, exposure='standard', take_rate_pct=10.0),
                MkCommission(category_id=1, exposure='premium', take_rate_pct=12.0),
            ]
            for commission in commission_rates:
                db.session.add(commission)
            demo_product = MkProduct(
                seller_company_id=1,
                name="Cemento Portland 50kg",
                category_id=1,
                description_html="<p>Cemento Portland de alta calidad</p>",
                is_masked_seller=True
            )
            db.session.add(demo_product)
            db.session.flush()
            demo_variant = MkProductVariant(
                product_id=demo_product.id,
                sku="CEM-PORT-50KG",
                price=8999.0,
                currency="ARS",
                stock_qty=100
            )
            db.session.add(demo_variant)
            db.session.commit()
        print("[OK] Marketplace tables created and seeded successfully")
    except Exception as e:
        print(f"[WARN] Marketplace initialization skipped: {e}")

    # Índices de performance para reportes de inventario
    try:
        idx_sql = """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_uso_inventario_item_fecha') THEN
                CREATE INDEX ix_uso_inventario_item_fecha ON uso_inventario(item_id, fecha_uso);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_movimientos_inv_item_fecha') THEN
                CREATE INDEX ix_movimientos_inv_item_fecha ON movimientos_inventario(item_id, fecha);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_items_inventario_org_activo') THEN
                CREATE INDEX ix_items_inventario_org_activo ON items_inventario(organizacion_id, activo);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_fichadas_obra_fecha') THEN
                CREATE INDEX ix_fichadas_obra_fecha ON fichadas(obra_id, fecha_hora);
            END IF;
        END $$;
        """
        db.session.execute(text(idx_sql))
        db.session.commit()
        print("[OK] Performance indexes created")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Performance indexes skipped: {e}")

    print("[OK] Database tables created successfully")

    # Asegurar admin por defecto
    try:
        admin_email = 'admin@obyra.com'
        admin = Usuario.query.filter_by(email=admin_email).first()

        if not admin:
            admin_org = Organizacion(nombre='OBYRA - Administración Central')
            db.session.add(admin_org)
            db.session.flush()

            # Obtener contraseña desde variable de entorno (más seguro que hardcodear)
            admin_password = os.getenv('ADMIN_DEFAULT_PASSWORD', 'admin123')

            admin = Usuario(
                nombre='Administrador',
                apellido='OBYRA',
                email=admin_email,
                rol='administrador',
                role='administrador',
                is_super_admin=True,
                auth_provider='manual',
                activo=True,
                organizacion_id=admin_org.id,
                primary_org_id=admin_org.id,
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f'[ADMIN] Usuario administrador creado: {admin_email} (password desde variable de entorno)')
        else:
            updated = False
            hashed_markers = ('pbkdf2:', 'scrypt:', 'argon2:', 'bcrypt')
            stored_hash = admin.password_hash or ''
            if not stored_hash or not stored_hash.startswith(hashed_markers):
                original_secret = stored_hash or 'admin123'
                admin.set_password(original_secret)
                updated = True
            if admin.auth_provider != 'manual':
                admin.auth_provider = 'manual'
                updated = True
            if not admin.is_super_admin:
                admin.is_super_admin = True
                updated = True
            if not admin.organizacion:
                admin_org = Organizacion(nombre='OBYRA - Administración Central')
                db.session.add(admin_org)
                db.session.flush()
                admin.organizacion_id = admin_org.id
                if not admin.primary_org_id:
                    admin.primary_org_id = admin_org.id
                updated = True
            if updated:
                db.session.commit()
                print('[ADMIN] Credenciales del administrador principal verificadas y aseguradas.')
    except Exception as ensure_admin_exc:
        db.session.rollback()
        print(f"[WARN] No se pudo garantizar el usuario admin@obyra.com: {ensure_admin_exc}")

    # Migración: solo admin@obyra.com debe ser super admin
    try:
        # Quitar super_admin de todos los que NO sean admin@obyra.com
        non_admin_supers = Usuario.query.filter(
            Usuario.is_super_admin.is_(True),
            Usuario.email != 'admin@obyra.com'
        ).all()
        for u in non_admin_supers:
            u.is_super_admin = False
        # Asegurar que admin@obyra.com SÍ sea super admin
        admin_user = Usuario.query.filter_by(email='admin@obyra.com').first()
        if admin_user and not admin_user.is_super_admin:
            admin_user.is_super_admin = True
        if non_admin_supers or (admin_user and not admin_user.is_super_admin):
            db.session.commit()
            if non_admin_supers:
                print(f'[ADMIN] Removido is_super_admin de {len(non_admin_supers)} usuarios: {[u.email for u in non_admin_supers]}')
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error ajustando super admins: {e}")

    # Migración: crear índices en organizacion_id para queries multi-tenant
    try:
        index_sql = """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_items_inventario_org_id') THEN
                CREATE INDEX ix_items_inventario_org_id ON items_inventario(organizacion_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_presupuestos_org_id') THEN
                CREATE INDEX ix_presupuestos_org_id ON presupuestos(organizacion_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_obras_org_id') THEN
                CREATE INDEX ix_obras_org_id ON obras(organizacion_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_clientes_org_id') THEN
                CREATE INDEX ix_clientes_org_id ON clientes(organizacion_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_proveedores_org_id') THEN
                CREATE INDEX ix_proveedores_org_id ON proveedores(organizacion_id);
            END IF;
        END $$;
        """
        db.session.execute(text(index_sql))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error creando índices org_id: {e}")

    # Migración: cambiar unique constraint de codigo global a per-org
    try:
        uq_sql = """
        DO $$ BEGIN
            -- Eliminar unique global si existe
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'items_inventario_codigo_key') THEN
                ALTER TABLE items_inventario DROP CONSTRAINT items_inventario_codigo_key;
            END IF;
            -- Crear unique per-org si no existe
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_item_inventario_org_codigo') THEN
                ALTER TABLE items_inventario ADD CONSTRAINT uq_item_inventario_org_codigo
                    UNIQUE (organizacion_id, codigo);
            END IF;
        END $$;
        """
        db.session.execute(text(uq_sql))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error migrando unique constraint items: {e}")

    # Migración: agregar CASCADE DELETE a FKs huérfanas (tarea_miembros, tarea_responsables)
    try:
        cascade_sql = """
        DO $$ BEGIN
            -- tarea_miembros.tarea_id CASCADE
            IF EXISTS (SELECT 1 FROM information_schema.table_constraints
                       WHERE constraint_name = 'tarea_miembros_tarea_id_fkey' AND table_name = 'tarea_miembros') THEN
                ALTER TABLE tarea_miembros DROP CONSTRAINT tarea_miembros_tarea_id_fkey;
                ALTER TABLE tarea_miembros ADD CONSTRAINT tarea_miembros_tarea_id_fkey
                    FOREIGN KEY (tarea_id) REFERENCES tareas_etapa(id) ON DELETE CASCADE;
            END IF;
            -- tarea_miembros.user_id CASCADE
            IF EXISTS (SELECT 1 FROM information_schema.table_constraints
                       WHERE constraint_name = 'tarea_miembros_user_id_fkey' AND table_name = 'tarea_miembros') THEN
                ALTER TABLE tarea_miembros DROP CONSTRAINT tarea_miembros_user_id_fkey;
                ALTER TABLE tarea_miembros ADD CONSTRAINT tarea_miembros_user_id_fkey
                    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE;
            END IF;
            -- tarea_responsables.tarea_id CASCADE
            IF EXISTS (SELECT 1 FROM information_schema.table_constraints
                       WHERE constraint_name = 'tarea_responsables_tarea_id_fkey' AND table_name = 'tarea_responsables') THEN
                ALTER TABLE tarea_responsables DROP CONSTRAINT tarea_responsables_tarea_id_fkey;
                ALTER TABLE tarea_responsables ADD CONSTRAINT tarea_responsables_tarea_id_fkey
                    FOREIGN KEY (tarea_id) REFERENCES tareas_etapa(id) ON DELETE CASCADE;
            END IF;
            -- tarea_responsables.user_id CASCADE
            IF EXISTS (SELECT 1 FROM information_schema.table_constraints
                       WHERE constraint_name = 'tarea_responsables_user_id_fkey' AND table_name = 'tarea_responsables') THEN
                ALTER TABLE tarea_responsables DROP CONSTRAINT tarea_responsables_user_id_fkey;
                ALTER TABLE tarea_responsables ADD CONSTRAINT tarea_responsables_user_id_fkey
                    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE;
            END IF;
        END $$;
        """
        db.session.execute(text(cascade_sql))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error agregando CASCADE deletes: {e}")

    # Migración: eliminar items duplicados y reclasificar encofrados
    try:
        from models import ItemInventario, InventoryCategory
        from sqlalchemy import or_
        import re as _re

        def _normalizar_nombre(nombre):
            n = nombre.lower().strip()
            n = n.replace('ht20', 'h20')
            n = n.replace('(u)', '').strip()
            n = _re.sub(r'\(.*?\)', '', n).strip()
            n = n.replace('mt', '').replace(' m', '').replace(',', '').replace('.', '')
            n = _re.sub(r'\s+', ' ', n).strip()
            return n

        print('[INVENTARIO] Iniciando limpieza de duplicados semánticos...')

        # Paso 1: Identificar IDs a eliminar (sin tocar DB aún)
        orgs_con_items = db.session.query(ItemInventario.organizacion_id).distinct().all()
        ids_a_eliminar = []

        for (org_id_val,) in orgs_con_items:
            all_items = ItemInventario.query.filter(
                ItemInventario.organizacion_id == org_id_val
            ).order_by(ItemInventario.id.asc()).all()

            grupos = {}
            for item in all_items:
                key = _normalizar_nombre(item.nombre)
                if key not in grupos:
                    grupos[key] = []
                grupos[key].append(item)

            for key, items_grupo in grupos.items():
                if len(items_grupo) <= 1:
                    continue
                items_inv = [i for i in items_grupo if i.codigo.startswith('INV-')]
                mantener = items_inv[0] if items_inv else items_grupo[0]
                for item in items_grupo:
                    if item.id == mantener.id:
                        continue
                    if not item.stock_actual or float(item.stock_actual) == 0:
                        ids_a_eliminar.append((item.id, item.codigo, item.nombre, mantener.codigo))

        # Paso 2: Eliminar duplicados uno por uno con SAVEPOINT
        total_eliminados = 0
        for iid, codigo, nombre, mantener_cod in ids_a_eliminar:
            try:
                # Usar conexión raw para SAVEPOINT correcto
                cleanup_sql = """
                DO $$ BEGIN
                    -- Limpiar FKs directas
                    DELETE FROM movimientos_inventario WHERE item_id = {iid};
                    DELETE FROM uso_inventario WHERE item_id = {iid};
                    BEGIN DELETE FROM stock_ubicacion WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN DELETE FROM stock_obra WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN DELETE FROM reservas_stock WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN DELETE FROM movimientos_stock WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN DELETE FROM movimientos_stock_obra WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN DELETE FROM global_material_usage WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN DELETE FROM item_categorias_adicionales WHERE item_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    -- Desvincular FKs nullable
                    BEGIN UPDATE items_cotizacion SET item_inventario_id = NULL WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN UPDATE items_presupuesto SET item_inventario_id = NULL WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN UPDATE requerimiento_compra_items SET item_inventario_id = NULL WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN UPDATE orden_compra_items SET item_inventario_id = NULL WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    BEGIN UPDATE remito_items SET item_inventario_id = NULL WHERE item_inventario_id = {iid}; EXCEPTION WHEN undefined_table THEN NULL; END;
                    -- Eliminar el item
                    DELETE FROM items_inventario WHERE id = {iid};
                END $$;
                """.replace('{iid}', str(int(iid)))
                db.session.execute(text(cleanup_sql))
                db.session.commit()
                total_eliminados += 1
                print(f'  [DEL] {codigo} "{nombre}" (duplicado de {mantener_cod})')
            except Exception as del_err:
                db.session.rollback()
                print(f'  [SKIP] {codigo}: {del_err}')

        # Paso 3: Reclasificar encofrados
        total_reclasificados = 0
        for (org_id_val,) in orgs_con_items:
            cat_encofrados = InventoryCategory.query.filter(
                InventoryCategory.company_id == org_id_val,
                InventoryCategory.nombre == 'Encofrados'
            ).first()
            if cat_encofrados:
                keywords = ['viga h20', 'viga ht20', 'puntal', 'cabezal', 'tripode',
                           'trípode', 'fork', 'gato regulable', 'mensula', 'ménsula',
                           'tensor', 'panel encofrado', 'tablero encofrado', 'placa encofrado']
                filtros = [ItemInventario.nombre.ilike(f'%{kw}%') for kw in keywords]
                items_encofrado = ItemInventario.query.filter(
                    ItemInventario.organizacion_id == org_id_val,
                    or_(*filtros),
                    ItemInventario.categoria_id != cat_encofrados.id
                ).all()
                for item in items_encofrado:
                    item.categoria_id = cat_encofrados.id
                    total_reclasificados += 1

        if total_reclasificados:
            db.session.commit()

        print(f'[INVENTARIO] Limpieza: {total_eliminados} duplicados eliminados, {total_reclasificados} reclasificados a Encofrados')
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error en limpieza de inventario: {e}")

    # Runtime migrations removed in Phase 4 - now using Alembic migrations
    # See: MIGRATIONS_GUIDE.md

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
    ('presupuestos', 'presupuestos_bp', '/presupuestos'),
    ('blueprint_clientes', 'clientes_bp', None),  # usa el prefijo definido en el blueprint
    ('blueprint_requerimientos', 'requerimientos_bp', None),  # Requerimientos de compra desde obras
    ('blueprint_notificaciones', 'notificaciones_bp', None),  # Sistema de notificaciones
    ('agent_local', 'agent_bp', None),
]:
    try:
        blueprint = _import_blueprint(module_name, attr_name)
        app.register_blueprint(blueprint, url_prefix=prefix)

        # Excluir endpoint de eliminar presupuesto del CSRF
        if module_name == 'presupuestos':
            # El nombre de la vista en el blueprint es solo 'eliminar'
            view_func = blueprint.view_functions.get('eliminar')
            if view_func:
                csrf.exempt(view_func)
                app.logger.info(f"CSRF exempt aplicado a presupuestos.eliminar")
            else:
                app.logger.warning(f"No se encontró la vista 'eliminar' en presupuestos. Vistas disponibles: {list(blueprint.view_functions.keys())}")
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
    """Serve authenticated media files from /media/ directory"""
    media_dir = Path(app.instance_path) / "media"
    return send_from_directory(media_dir, relpath)

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

# === ADMIN FIX ENDPOINT (TEMPORAL) ===
@app.route("/admin/fix-etapa-nombre")
@login_required
def fix_etapa_nombre():
    """Endpoint temporal para agregar columna etapa_nombre en Railway"""
    from sqlalchemy import text

    # Solo super admins
    if not current_user.is_super_admin:
        return {"error": "Unauthorized"}, 403

    try:
        # Verificar si la columna existe
        result = db.session.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'items_presupuesto'
            AND column_name = 'etapa_nombre'
        """))

        if result.fetchone():
            return {
                "status": "already_exists",
                "message": "La columna 'etapa_nombre' ya existe"
            }, 200

        # Agregar la columna
        db.session.execute(text("""
            ALTER TABLE items_presupuesto
            ADD COLUMN etapa_nombre VARCHAR(100)
        """))
        db.session.commit()

        # Verificar que se agregó
        result = db.session.execute(text("""
            SELECT column_name, data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'items_presupuesto'
            AND column_name = 'etapa_nombre'
        """))

        row = result.fetchone()
        if row:
            return {
                "status": "success",
                "message": "Columna 'etapa_nombre' agregada exitosamente",
                "details": {
                    "column_name": row[0],
                    "data_type": row[1],
                    "max_length": row[2]
                }
            }, 200
        else:
            return {
                "status": "error",
                "message": "No se pudo verificar la columna después de agregarla"
            }, 500

    except Exception as e:
        db.session.rollback()
        return {
            "status": "error",
            "message": str(e)
        }, 500

@app.route("/admin/fix-security-tables")
@login_required
def fix_security_tables():
    """Endpoint temporal para crear tablas de seguridad en Railway"""
    from sqlalchemy import text

    # Solo super admins
    if not current_user.is_super_admin:
        return {"error": "Unauthorized"}, 403

    try:
        results = []
        errors = []

        # 1. protocolos_seguridad
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS protocolos_seguridad (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(200) NOT NULL,
                    descripcion TEXT,
                    categoria VARCHAR(50) NOT NULL,
                    obligatorio BOOLEAN DEFAULT true,
                    frecuencia_revision INTEGER DEFAULT 30,
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    activo BOOLEAN DEFAULT true,
                    normativa_referencia VARCHAR(200)
                )
            """))
            results.append("protocolos_seguridad")
        except Exception as e:
            errors.append(f"protocolos_seguridad: {str(e)}")

        # 2. checklists_seguridad
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS checklists_seguridad (
                    id SERIAL PRIMARY KEY,
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    protocolo_id INTEGER NOT NULL REFERENCES protocolos_seguridad(id),
                    fecha_inspeccion DATE NOT NULL,
                    inspector_id INTEGER NOT NULL REFERENCES usuarios(id),
                    estado VARCHAR(20) DEFAULT 'pendiente',
                    puntuacion INTEGER,
                    observaciones TEXT,
                    acciones_correctivas TEXT,
                    fecha_completado TIMESTAMP
                )
            """))
            results.append("checklists_seguridad")
        except Exception as e:
            errors.append(f"checklists_seguridad: {str(e)}")

        # 3. items_checklist
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS items_checklist (
                    id SERIAL PRIMARY KEY,
                    checklist_id INTEGER NOT NULL REFERENCES checklists_seguridad(id),
                    descripcion VARCHAR(300) NOT NULL,
                    conforme BOOLEAN,
                    observacion TEXT,
                    criticidad VARCHAR(20) DEFAULT 'media'
                )
            """))
            results.append("items_checklist")
        except Exception as e:
            errors.append(f"items_checklist: {str(e)}")

        # 4. incidentes_seguridad
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS incidentes_seguridad (
                    id SERIAL PRIMARY KEY,
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    fecha_incidente TIMESTAMP NOT NULL,
                    tipo_incidente VARCHAR(50) NOT NULL,
                    gravedad VARCHAR(20) NOT NULL,
                    descripcion TEXT NOT NULL,
                    ubicacion_exacta VARCHAR(200),
                    persona_afectada VARCHAR(100),
                    testigos TEXT,
                    primeros_auxilios BOOLEAN DEFAULT false,
                    atencion_medica BOOLEAN DEFAULT false,
                    dias_perdidos INTEGER DEFAULT 0,
                    causa_raiz TEXT,
                    acciones_inmediatas TEXT,
                    acciones_preventivas TEXT,
                    responsable_id INTEGER NOT NULL REFERENCES usuarios(id),
                    estado VARCHAR(20) DEFAULT 'abierto',
                    fecha_cierre TIMESTAMP
                )
            """))
            results.append("incidentes_seguridad")
        except Exception as e:
            errors.append(f"incidentes_seguridad: {str(e)}")

        # 5. certificaciones_personal
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS certificaciones_personal (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                    tipo_certificacion VARCHAR(100) NOT NULL,
                    entidad_emisora VARCHAR(200) NOT NULL,
                    numero_certificado VARCHAR(50),
                    fecha_emision DATE NOT NULL,
                    fecha_vencimiento DATE,
                    archivo_certificado VARCHAR(500),
                    activo BOOLEAN DEFAULT true
                )
            """))
            results.append("certificaciones_personal")
        except Exception as e:
            errors.append(f"certificaciones_personal: {str(e)}")

        # 6. auditorias_seguridad
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS auditorias_seguridad (
                    id SERIAL PRIMARY KEY,
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    fecha_auditoria DATE NOT NULL,
                    auditor_externo VARCHAR(200),
                    tipo_auditoria VARCHAR(50) NOT NULL,
                    puntuacion_general INTEGER,
                    hallazgos_criticos INTEGER DEFAULT 0,
                    hallazgos_mayores INTEGER DEFAULT 0,
                    hallazgos_menores INTEGER DEFAULT 0,
                    informe_path VARCHAR(500),
                    plan_accion_path VARCHAR(500),
                    fecha_seguimiento DATE,
                    estado VARCHAR(20) DEFAULT 'programada'
                )
            """))
            results.append("auditorias_seguridad")
        except Exception as e:
            errors.append(f"auditorias_seguridad: {str(e)}")

        # Crear índices
        try:
            db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_checklists_obra ON checklists_seguridad(obra_id)"))
            db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_checklists_estado ON checklists_seguridad(estado)"))
            db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_incidentes_obra ON incidentes_seguridad(obra_id)"))
            db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_incidentes_fecha ON incidentes_seguridad(fecha_incidente)"))
            db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_incidentes_estado ON incidentes_seguridad(estado)"))
            results.append("indices_creados")
        except Exception as e:
            errors.append(f"indices: {str(e)}")

        db.session.commit()

        return {
            "status": "success",
            "message": f"Tablas de seguridad creadas: {len(results)} exitosas, {len(errors)} errores",
            "tables_created": results,
            "errors": errors if errors else None
        }, 200

    except Exception as e:
        db.session.rollback()
        return {
            "status": "error",
            "message": f"Error crítico: {str(e)}"
        }, 500

@app.route("/admin/diagnostico")
@login_required
def diagnostico():
    """Endpoint de diagnóstico para ver errores en Railway"""
    from sqlalchemy import text
    import traceback

    # Solo super admins
    if not current_user.is_super_admin:
        return {"error": "Unauthorized"}, 403

    diagnostics = {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "role": current_user.role,
            "is_super_admin": current_user.is_super_admin
        },
        "database": {},
        "tables": {},
        "blueprints": {},
        "errors": []
    }

    # Verificar conexión a DB
    try:
        db.session.execute(text("SELECT 1"))
        diagnostics["database"]["status"] = "connected"
    except Exception as e:
        diagnostics["database"]["status"] = "error"
        diagnostics["database"]["error"] = str(e)
        diagnostics["errors"].append(f"DB: {str(e)}")

    # Verificar tablas de seguridad
    security_tables = [
        'protocolos_seguridad',
        'checklists_seguridad',
        'items_checklist',
        'incidentes_seguridad',
        'certificaciones_personal',
        'auditorias_seguridad'
    ]

    for table in security_tables:
        try:
            result = db.session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            diagnostics["tables"][table] = {"exists": True, "count": count}
        except Exception as e:
            diagnostics["tables"][table] = {"exists": False, "error": str(e)[:100]}
            diagnostics["errors"].append(f"{table}: {str(e)[:100]}")

    # Verificar blueprints registrados
    diagnostics["blueprints"]["registered"] = [
        rule.rule for rule in app.url_map.iter_rules()
        if 'seguridad' in rule.rule or 'api/offline' in rule.rule
    ]

    # Test seguridad dashboard
    try:
        with app.test_request_context():
            from seguridad_cumplimiento import calcular_estadisticas_seguridad
            stats = calcular_estadisticas_seguridad()
            diagnostics["seguridad_module"] = {"status": "ok", "stats": stats}
    except Exception as e:
        diagnostics["seguridad_module"] = {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        diagnostics["errors"].append(f"Seguridad module: {str(e)}")

    # Test API offline
    try:
        from api_offline import get_current_org_id
        org_id = get_current_org_id()
        diagnostics["api_offline"] = {"status": "ok", "org_id": org_id}
    except Exception as e:
        diagnostics["api_offline"] = {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        diagnostics["errors"].append(f"API offline: {str(e)}")

    return diagnostics, 200

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

