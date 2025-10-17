from dotenv import load_dotenv
load_dotenv()

import os
import sys
import logging
import importlib
import click
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from sqlalchemy.engine.url import make_url

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
from flask.cli import AppGroup
from flask_login import login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.routing import BuildError

from services.memberships import (
    initialize_membership_session,
    load_membership_into_context,
    get_current_membership,
    get_current_org_id,
)

from extensions import db, login_manager
from flask_migrate import Migrate


# -------------------------- I/O y prints seguros ------------------------------

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


# ------------------------------ App & config ---------------------------------

app = Flask(__name__)
app.secret_key = (
    os.environ.get("SESSION_SECRET")
    or os.environ.get("SECRET_KEY")
    or "dev-secret-key-change-me"
)

def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# logging
logging.basicConfig(level=logging.DEBUG)


# ------------------------- DB (PostgreSQL/SQLite tests) ----------------------

def _is_test_environment() -> bool:
    return (
        _env_flag("TESTING")
        or os.environ.get("FLASK_ENV", "").strip().lower() == "test"
        or os.environ.get("PYTEST_CURRENT_TEST") is not None
    )

is_test_environment = _is_test_environment()
database_url = (os.environ.get("DATABASE_URL") or "").strip()

if not database_url:
    if is_test_environment:
        database_url = "sqlite:///:memory:"
        logging.getLogger(__name__).warning(
            "DATABASE_URL no definido. Usando SQLite en memoria para tests."
        )
    else:
        raise RuntimeError(
            "DATABASE_URL es obligatorio y debe apuntar a PostgreSQL (psycopg3)."
        )

url_obj = make_url(database_url)

if not is_test_environment and not url_obj.drivername.startswith("postgresql"):
    raise RuntimeError(
        f"DATABASE_URL debe usar PostgreSQL, se recibió '{url_obj.drivername}'."
    )

# Forzar SSL si es Neon
if (url_obj.host and "neon.tech" in url_obj.host) or ("neon.tech" in database_url):
    if "sslmode=" not in database_url:
        sep = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{sep}sslmode=require"
        logging.getLogger(__name__).info("Se agregó sslmode=require para Neon")
        url_obj = make_url(database_url)

engine_options = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}
if url_obj.drivername.startswith("postgresql"):
    engine_options.update({"pool_size": 20, "max_overflow": 20})

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options

# otras opciones de app
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

# init extensions
db.init_app(app)
login_manager.init_app(app)
migrate = Migrate(app, db)


# -------------------------- Alembic / runtime flags --------------------------

def _is_alembic_running() -> bool:
    """Return True when Alembic is orchestrating the process."""
    return os.getenv("ALEMBIC_RUNNING") == "1"


def _should_skip_create_all() -> bool:
    """Return True when automatic table creation must be skipped."""
    return _is_alembic_running() or os.getenv("FLASK_SKIP_CREATE_ALL") == "1"


# ---------------------- Login endpoint resolution helpers --------------------

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


# ------------------------------- CLI: DB upgrade -----------------------------

db_cli = AppGroup('db')

@db_cli.command('upgrade')
def db_upgrade():
    """Apply pending lightweight database migrations."""
    with app.app_context():
        from flask_migrate import upgrade as alembic_upgrade

        logger = app.logger
        logger.info("Running Alembic upgrade...")
        alembic_upgrade()
        logger.info("Alembic upgrade → OK")
        logger.info("Running post-upgrade runtime ensures...")

        from migrations_runtime import (
            ensure_avance_audit_columns,
            ensure_presupuesto_state_columns,
            ensure_item_presupuesto_stage_columns,
            ensure_presupuesto_validity_columns,
            ensure_exchange_currency_columns,
            ensure_geocode_columns,
            ensure_org_memberships_table,
            ensure_work_certification_tables,
        )

        ensure_avance_audit_columns()
        ensure_presupuesto_state_columns()
        ensure_item_presupuesto_stage_columns()
        ensure_presupuesto_validity_columns()
        ensure_exchange_currency_columns()
        ensure_geocode_columns()
        ensure_org_memberships_table()
        ensure_work_certification_tables()

    click.echo('[OK] Database upgraded successfully.')

app.cli.add_command(db_cli)


# ----------------------------- CLI: FX & CAC --------------------------------

fx_cli = AppGroup('fx')

@fx_cli.command('update')
@click.option('--provider', default='bna', help='Proveedor de tipo de cambio (ej. bna)')
def fx_update(provider: str):
    """Actualiza el tipo de cambio almacenado."""
    provider_key = (provider or 'bna').lower()

    with app.app_context():
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


# -------------------------- Helpers para CLI/blueprints ----------------------

def _import_blueprint(module_name, attr_name):
    """Importa un blueprint de manera segura sin interrumpir el resto."""
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)

def _resolve_cli_organization(identifier: str):
    """Resolve an organization by id, slug, token or name."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None

    from models import Organizacion  # Local import to avoid circular deps
    from sqlalchemy import func as sa_func

    if identifier.isdigit():
        return Organizacion.query.get(int(identifier))

    if hasattr(Organizacion, "slug"):
        org = Organizacion.query.filter_by(slug=identifier).first()
        if org:
            return org

    org = Organizacion.query.filter_by(token_invitacion=identifier).first()
    if org:
        return org

    lowered = identifier.lower()
    return (
        Organizacion.query
        .filter(sa_func.lower(Organizacion.nombre) == lowered)
        .first()
    )

def _format_seed_summary(stats: dict) -> str:
    created = stats.get("created", 0)
    existing = stats.get("existing", 0)
    reactivated = stats.get("reactivated", 0)
    return f"creadas={created}, existentes={existing}, reactivadas={reactivated}"


# ------------------------------ CLI: seed inventario -------------------------

@app.cli.command("seed:inventario")
@click.option("--global", "seed_global", is_flag=True, help="Inicializa el catálogo global compartido")
@click.option("--org", "org_identifiers", multiple=True, help="ID, slug, token o nombre de la organización a sembrar")
@click.option("--quiet", is_flag=True, help="Oculta el detalle por categoría")
def seed_inventario_cli(seed_global: bool, org_identifiers: Tuple[str, ...], quiet: bool) -> None:
    """Seed de categorías de inventario utilizando el CLI de Flask."""
    if not seed_global and not org_identifiers:
        raise click.ClickException(
            "Debes indicar al menos una organización con --org o usar --global."
        )

    from models import Organizacion
    from seed_inventory_categories import seed_inventory_categories_for_company

    verbose = not quiet
    identifiers = list(org_identifiers)
    fallback_identifier = identifiers[0] if (seed_global and identifiers) else None

    try:
        if seed_global:
            fallback_org = (
                _resolve_cli_organization(fallback_identifier)
                if fallback_identifier
                else Organizacion.query.order_by(Organizacion.id.asc()).first()
            )

            if not fallback_org:
                raise click.ClickException(
                    "No se encontró una organización para inicializar el catálogo global."
                )

            stats = seed_inventory_categories_for_company(
                fallback_org,
                verbose=verbose,
                mark_global=True,
            )
            db.session.commit()
            click.echo(
                f"🌐 Catálogo global listo ({fallback_org.nombre}): {_format_seed_summary(stats)}"
            )

        for identifier in identifiers:
            organizacion = _resolve_cli_organization(identifier)
            if not organizacion:
                raise click.ClickException(
                    f"No se encontró la organización '{identifier}'."
                )

            stats = seed_inventory_categories_for_company(
                organizacion,
                verbose=verbose,
            )
            db.session.commit()
            click.echo(
                f"🏗️  {organizacion.nombre}: {_format_seed_summary(stats)}"
            )
    except click.ClickException:
        db.session.rollback()
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        db.session.rollback()
        raise click.ClickException(str(exc)) from exc


# ---------------------------- Registro de blueprints -------------------------

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
    ('presupuestos', 'presupuestos_bp', '/presupuestos'),
    ('equipos', 'equipos_bp', '/equipos'),
    ('inventario', 'inventario_bp', '/inventario'),
    ('marketplaces', 'marketplaces_bp', '/marketplaces'),
    ('reportes', 'reportes_bp', '/reportes'),
    ('asistente_ia', 'asistente_bp', '/asistente'),
    ('cotizacion_inteligente', 'cotizacion_bp', '/cotizacion'),
    ('control_documentos', 'documentos_bp', '/documentos'),
    ('seguridad_cumplimiento', 'seguridad_bp', '/seguridad'),
    ('agent_local', 'agent_bp', None),
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

_refresh_login_view()

# Reports (opcional)
if app.config.get("ENABLE_REPORTS_SERVICE"):
    try:
        import matplotlib  # noqa: F401 - sanity check for optional dependency
        reports_service_bp = _import_blueprint('reports_service', 'reports_bp')
        app.register_blueprint(reports_service_bp)
        print("[OK] Reports service enabled")
    except Exception as exc:
        app.logger.warning("Reports service disabled: %s", exc)
        app.config["ENABLE_REPORTS_SERVICE"] = False
else:
    app.logger.info("Reports service disabled (set ENABLE_REPORTS=1 to enable)")

# Fallbacks de auth si falta el blueprint
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

# Enhanced blueprints
try:
    from equipos_new import equipos_new_bp
    from inventario_new import inventario_new_bp
    app.register_blueprint(equipos_new_bp, url_prefix='/equipos-new')
    app.register_blueprint(inventario_new_bp, url_prefix='/inventario-new')
    print("[OK] Enhanced blueprints registered successfully")
except ImportError as e:
    print(f"[WARN] Enhanced blueprints not available: {e}")

# Supplier portal / marketplace
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

try:
    from marketplace.routes import bp as marketplace_bp
    app.register_blueprint(marketplace_bp, url_prefix="/")
    print("[OK] Marketplace blueprint registered successfully")
except ImportError as e:
    print(f"[WARN] Marketplace blueprint not available: {e}")

_refresh_login_view()


# ---------------------- Páginas legales fallback -----------------------------

if 'terminos' not in app.view_functions:
    app.add_url_rule(
        '/terminos',
        endpoint='terminos',
        view_func=lambda: render_template('legal/terminos.html')
    )

if 'privacidad' not in app.view_functions:
    app.add_url_rule(
        '/privacidad',
        endpoint='privacidad',
        view_func=lambda: render_template('legal/privacidad.html')
    )


# --------------------------------- Rutas base --------------------------------

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


# ---------------------------- Filtros de template ----------------------------

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
    symbol = 'US$' if (currency or 'ARS').upper() == 'USD' else '$'
    return f"{symbol}{monto:,.2f}"

@app.template_filter('porcentaje')
def porcentaje_filter(valor):
    if valor is None:
        return '0%'
    return f'{valor:.1f}%'

@app.template_filter('numero')
def numero_filter(valor, decimales=0):
    if valor is None:
        return '0'
    return f'{valor:,.{decimales}f}'

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
    """Filtro para convertir códigos de rol a nombres legibles"""
    try:
        from roles_construccion import obtener_nombre_rol
        return obtener_nombre_rol(codigo_rol)
    except:
        return codigo_rol.replace('_', ' ').title()

@app.template_filter('from_json')
def from_json_filter(json_str):
    """Filtro para convertir string JSON a diccionario"""
    if not json_str:
        return {}
    try:
        import json
        return json.loads(json_str)
    except:
        return {}


# --------------------------- Membresía y planes ------------------------------

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
    rutas_excluidas = [
        'planes.mostrar_planes', 'planes.plan_standard', 'planes.plan_premium',
        'auth.login', 'auth.register', 'auth.logout', 'static', 'index'
    ]
    if (
        current_user.is_authenticated
        and request.endpoint
        and request.endpoint not in rutas_excluidas
        and not request.endpoint.startswith('static')
    ):
        emails_admin_completo = ['brenda@gmail.com', 'admin@obyra.com', 'obyra.servicios@gmail.com']
        if current_user.email in emails_admin_completo:
            return
        if (current_user.plan_activo == 'prueba' and not current_user.esta_en_periodo_prueba()):
            flash('Tu período de prueba de 30 días ha expirado. Selecciona un plan para continuar.', 'warning')
            return redirect(url_for('planes.mostrar_planes'))


# -------------------------- Fallback dashboard reportes ----------------------

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


# --------------------------- Media autenticada -------------------------------

@app.route("/media/<path:relpath>")
@login_required
def serve_media(relpath):
    """Serve authenticated media files from /media/ directory"""
    from pathlib import Path
    media_dir = Path(app.instance_path) / "media"
    return send_from_directory(media_dir, relpath)


# ------------------------------ Error handlers -------------------------------

@app.errorhandler(403)
def forbidden(error):
    return render_template('errors/403.html'), 403

@app.errorhandler(401)
def unauthorized(error):
    if request.path.startswith('/obras/api/') or request.path.startswith('/api/'):
        from flask import jsonify
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    return _login_redirect()

@app.errorhandler(404)
def not_found(error):
    try:
        dashboard_url = url_for('reportes.dashboard')
    except BuildError:
        try:
            dashboard_url = url_for('supplier_portal.dashboard')
        except BuildError:
            dashboard_url = url_for('index')
    return render_template('errors/404.html', dashboard_url=dashboard_url), 404


# --------------------------- Dev helper (SQLite) -----------------------------

def maybe_create_sqlite_schema():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if os.getenv("AUTO_CREATE_DB", "0") == "1" and uri.startswith("sqlite:"):
        with app.app_context():
            db.create_all()


# ---------------------------------- Main -------------------------------------

if __name__ == '__main__':
    maybe_create_sqlite_schema()
    app.run(host='0.0.0.0', port=5000, debug=True)
