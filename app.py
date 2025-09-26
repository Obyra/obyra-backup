import os
import sys
import logging
import importlib.util
from importlib import import_module
from types import ModuleType
from flask import Flask, render_template, redirect, url_for, flash, send_from_directory
from flask_login import login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
from extensions import db, login_manager

# Provide a lightweight stub for authlib when it's not installed
def _ensure_authlib_stub():
    try:
        authlib_spec = importlib.util.find_spec("authlib.integrations.flask_client")
    except ModuleNotFoundError:
        authlib_spec = None

    if authlib_spec is not None:
        return

    # Build minimal package structure expected by the application
    authlib_pkg = sys.modules.setdefault("authlib", ModuleType("authlib"))
    integrations_pkg = sys.modules.setdefault(
        "authlib.integrations", ModuleType("authlib.integrations")
    )

    class OAuthStub:
        """Fallback OAuth stub used when authlib is unavailable."""

        def __init__(self, *args, **kwargs):
            pass

        def init_app(self, app):
            """Mirror the real API but perform no action."""

        def register(self, *args, **kwargs):
            raise RuntimeError(
                "authlib is required for OAuth support. Install authlib to enable this feature."
            )

    flask_client_module = ModuleType("authlib.integrations.flask_client")
    flask_client_module.OAuth = OAuthStub
    sys.modules["authlib.integrations.flask_client"] = flask_client_module
    setattr(integrations_pkg, "flask_client", flask_client_module)
    setattr(authlib_pkg, "integrations", integrations_pkg)
    print("⚠️  authlib not installed; OAuth functionality disabled.")


_ensure_authlib_stub()

# create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# configure logging
logging.basicConfig(level=logging.DEBUG)

# configure the database with fallback to SQLite
database_url = os.environ.get("DATABASE_URL")

# 🔥 FALLBACK: Si no hay DATABASE_URL o falla conexión, usar SQLite local
if not database_url:
    database_url = "sqlite:///tmp/dev.db"
    print("⚠️  DATABASE_URL no disponible, usando SQLite fallback")
else:
    # Verificar si DATABASE_URL contiene host de Neon y aplicar SSL
    if "neon.tech" in database_url and "sslmode=" not in database_url:
        if "?" in database_url:
            database_url += "&sslmode=require"
        else:
            database_url += "?sslmode=require"
        print("🔒 SSL requerido agregado para Neon")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,           # Reconexión cada 5 min
    "pool_pre_ping": True,         # Test conexión antes de usar
    "connect_args": {
        "connect_timeout": 10,      # Timeout corto para conexión
        "keepalives_idle": 600,     # Keep alive idle time
        "keepalives_interval": 30,  # Keep alive interval
        "keepalives_count": 3,      # Keep alive retry count
    } if database_url.startswith('postgresql') else {},
    "pool_timeout": 30,            # Timeout para obtener conexión del pool
    "max_overflow": 0,             # No overflow connections
    "pool_size": 5,                # Tamaño del pool
}

# initialize extensions
db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Por favor inicia sesión para acceder a esta página.'
login_manager.login_message_category = 'info'


def _first_available_endpoint(*endpoints):
    """Return the first endpoint that is currently registered on the app."""

    for endpoint in endpoints:
        if endpoint in app.view_functions:
            return endpoint
    return None


@login_manager.user_loader
def load_user(user_id):
    # Import here to avoid circular imports
    from models import Usuario
    return Usuario.query.get(int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    """Custom unauthorized handler that returns JSON for API routes"""
    from flask import request, jsonify, redirect, url_for
    # Check if this is an API request
    if request.path.startswith('/obras/api/') or request.path.startswith('/api/'):
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    # For regular web requests, redirect to login
    login_endpoint = _first_available_endpoint('auth.login', 'supplier_auth.login')
    if login_endpoint:
        return redirect(url_for(login_endpoint))
    return redirect('/')


# Register blueprints - moved after database initialization to avoid circular imports

# Funciones globales para templates
@app.context_processor
def utility_processor():
    from tareas_predefinidas import TAREAS_POR_ETAPA
    return dict(obtener_tareas_para_etapa=lambda nombre_etapa: TAREAS_POR_ETAPA.get(nombre_etapa, []))




@app.before_request
def verificar_periodo_prueba():
    """Middleware para verificar si el usuario necesita seleccionar un plan"""
    from flask import request
    
    # Rutas que no requieren verificación de plan
    rutas_excluidas = [
        'planes.mostrar_planes', 'planes.plan_standard', 'planes.plan_premium',
        'auth.login', 'auth.register', 'auth.logout', 'static', 'index'
    ]
    
    if (current_user.is_authenticated and 
        request.endpoint and
        request.endpoint not in rutas_excluidas and 
        not request.endpoint.startswith('static')):
        
        # ✨ EXCEPCIÓN ESPECIAL: Administradores tienen acceso completo sin restricciones
        emails_admin_completo = ['brenda@gmail.com', 'admin@obyra.com', 'obyra.servicios@gmail.com']
        if current_user.email in emails_admin_completo:
            return  # Acceso completo sin restricciones de plan
        
        # Verificar si el usuario está en periodo de prueba y ya expiró
        if (current_user.plan_activo == 'prueba' and 
            not current_user.esta_en_periodo_prueba()):
            
            flash(f'Tu período de prueba de 30 días ha expirado. Selecciona un plan para continuar.', 'warning')
            return redirect(url_for('planes.mostrar_planes'))

@app.route('/')
def index():
    """Redirigir automáticamente al dashboard después del login"""
    if current_user.is_authenticated:
        # Si es operario, NO ve dashboard → lo mandamos a Mis Tareas
        if getattr(current_user, "role", None) == "operario":
            return redirect(url_for("obras.mis_tareas"))

        dashboard_endpoint = _first_available_endpoint('reportes.dashboard', 'obras.lista')
        if dashboard_endpoint:
            return redirect(url_for(dashboard_endpoint))

    login_endpoint = _first_available_endpoint('auth.login', 'supplier_auth.login')
    if login_endpoint:
        return redirect(url_for(login_endpoint))
    return redirect('/')


@app.route('/dashboard')
def dashboard():
    if current_user.is_authenticated:
        # Si es operario, NO ve dashboard → lo mandamos a Mis Tareas
        if getattr(current_user, "role", None) == "operario":
            return redirect(url_for("obras.mis_tareas"))

        dashboard_endpoint = _first_available_endpoint('reportes.dashboard', 'obras.lista')
        if dashboard_endpoint:
            return redirect(url_for(dashboard_endpoint))

    login_endpoint = _first_available_endpoint('auth.login', 'supplier_auth.login')
    if login_endpoint:
        return redirect(url_for(login_endpoint))
    return redirect('/')


# Filtros personalizados
@app.template_filter('fecha')
def fecha_filter(fecha):
    if fecha:
        return fecha.strftime('%d/%m/%Y')
    return ''


@app.template_filter('moneda')
def moneda_filter(valor):
    if valor is None:
        return '$0'
    return f'${valor:,.2f}'


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
        # Fallback si hay algún error
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


# Create tables and initial data
with app.app_context():
    # Import models after app context is available to avoid circular imports
    from models import Usuario, Organizacion
    
    # Run startup migrations before creating tables
    from migrations_runtime import ensure_avance_audit_columns
    ensure_avance_audit_columns()

    # 🔥 Intento crear tablas con fallback automático a SQLite
    try:
        print(f"📊 Intentando conectar a: {app.config['SQLALCHEMY_DATABASE_URI'][:50]}...")
        db.create_all()
        print("✅ Base de datos conectada exitosamente")
    except Exception as e:
        print(f"❌ Error conectando a base de datos principal: {str(e)}")
        if "neon.tech" in app.config['SQLALCHEMY_DATABASE_URI']:
            print("🔄 Fallback automático a SQLite...")
            # Cambiar a SQLite y reiniciar SQLAlchemy
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tmp/dev.db"
            # Simplificar engine options para SQLite
            app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
                "pool_recycle": 300,
                "pool_pre_ping": True,
            }
            
            # Reiniciar la conexión con la nueva configuración
            db.init_app(app)
            try:
                db.create_all()
                print("✅ SQLite fallback conectado exitosamente")
            except Exception as sqlite_error:
                print(f"❌ Error crítico con SQLite fallback: {str(sqlite_error)}")
                raise sqlite_error
        else:
            raise e
    
    # Initialize RBAC permissions
    try:
        from models import seed_default_role_permissions
        seed_default_role_permissions()
        print("🔐 RBAC permissions seeded successfully")
    except Exception as e:
        print(f"⚠️ RBAC seeding skipped: {e}")
    
    # Initialize marketplace tables (isolated mk_ tables)
    try:
        from marketplace.models import MkProduct, MkProductVariant, MkCart, MkCartItem, MkOrder, MkOrderItem, MkPayment, MkPurchaseOrder, MkCommission
        
        # Create marketplace tables only
        MkProduct.__table__.create(db.engine, checkfirst=True)
        MkProductVariant.__table__.create(db.engine, checkfirst=True)
        MkCart.__table__.create(db.engine, checkfirst=True)
        MkCartItem.__table__.create(db.engine, checkfirst=True)
        MkOrder.__table__.create(db.engine, checkfirst=True)
        MkOrderItem.__table__.create(db.engine, checkfirst=True)
        MkPayment.__table__.create(db.engine, checkfirst=True)
        MkPurchaseOrder.__table__.create(db.engine, checkfirst=True)
        MkCommission.__table__.create(db.engine, checkfirst=True)
        
        # Seed basic marketplace data
        if not MkCommission.query.first():
            commission_rates = [
                MkCommission(category_id=1, exposure='standard', take_rate_pct=10.0),
                MkCommission(category_id=1, exposure='premium', take_rate_pct=12.0),
            ]
            for commission in commission_rates:
                db.session.add(commission)
            
            # Demo products
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
        
        print("🏪 Marketplace tables created and seeded successfully")
    except Exception as e:
        print(f"⚠️ Marketplace initialization skipped: {e}")
    
    print("📊 Database tables created successfully")

def _safe_register_blueprint(module_name, blueprint_attr, *, url_prefix=None, group="core", init_oauth=False):
    """Attempt to import and register a blueprint without aborting app startup."""

    try:
        module = import_module(module_name)
    except ImportError as exc:
        print(f"⚠️ {group.capitalize()} blueprint '{module_name}' not available: {exc}")
        return False

    try:
        blueprint = getattr(module, blueprint_attr)
    except AttributeError as exc:
        print(
            f"⚠️ {group.capitalize()} blueprint '{module_name}' is missing attribute '{blueprint_attr}': {exc}"
        )
        return False

    if init_oauth and hasattr(module, "oauth"):
        try:
            module.oauth.init_app(app)
        except Exception as exc:  # pragma: no cover - defensive guard
            print(f"⚠️ Failed to initialize OAuth for '{module_name}': {exc}")
            # Continue registering blueprint even if OAuth init fails so login view exists

    app.register_blueprint(blueprint, url_prefix=url_prefix)
    return True


# Register blueprints after database initialization to avoid circular imports
core_blueprints = [
    ("auth", "auth_bp", "/auth", {"init_oauth": True}),
    ("obras", "obras_bp", "/obras", {}),
    ("presupuestos", "presupuestos_bp", "/presupuestos", {}),
    ("equipos", "equipos_bp", "/equipos", {}),
    ("inventario", "inventario_bp", "/inventario", {}),
    ("marketplaces", "marketplaces_bp", "/marketplaces", {}),
    ("reportes", "reportes_bp", "/reportes", {}),
    ("asistente_ia", "asistente_bp", "/asistente", {}),
    ("cotizacion_inteligente", "cotizacion_bp", "/cotizacion", {}),
    ("control_documentos", "documentos_bp", "/documentos", {}),
    ("seguridad_cumplimiento", "seguridad_bp", "/seguridad", {}),
    ("agent_local", "agent_bp", None, {}),
    ("planes", "planes_bp", None, {}),
    ("events_service", "events_bp", None, {}),
    ("reports_service", "reports_bp", None, {}),
]

registered_core = [
    name
    for name, attr, prefix, options in core_blueprints
    if _safe_register_blueprint(
        name,
        attr,
        url_prefix=prefix,
        group="core",
        **options,
    )
]

if registered_core:
    print("✅ Core blueprints registered successfully")

# Try to register optional blueprints
enhanced_blueprints = [
    ("equipos_new", "equipos_new_bp", "/equipos-new"),
    ("inventario_new", "inventario_new_bp", "/inventario-new"),
]

if [
    name
    for name, attr, prefix in enhanced_blueprints
    if _safe_register_blueprint(name, attr, url_prefix=prefix, group="enhanced")
]:
    print("✅ Enhanced blueprints registered successfully")

# Try to register supplier portal blueprints
supplier_blueprints = [
    ("supplier_auth", "supplier_auth_bp", None),
    ("supplier_portal", "supplier_portal_bp", None),
    ("market", "market_bp", None),
]

if [
    name
    for name, attr, prefix in supplier_blueprints
    if _safe_register_blueprint(name, attr, url_prefix=prefix, group="supplier portal")
]:
    print("✅ Supplier portal blueprints registered successfully")

# Try to register marketplace blueprints
if _safe_register_blueprint(
    "marketplace.routes",
    "bp",
    url_prefix="/",
    group="marketplace",
):
    print("✅ Marketplace blueprint registered successfully")


resolved_login_view = _first_available_endpoint('auth.login', 'supplier_auth.login')
if resolved_login_view:
    login_manager.login_view = resolved_login_view


# === MEDIA SERVING ENDPOINT ===

@app.route("/media/<path:relpath>")
@login_required
def serve_media(relpath):
    """Serve authenticated media files from /media/ directory"""
    from pathlib import Path
    media_dir = Path(app.instance_path) / "media"
    return send_from_directory(media_dir, relpath)


# Error handlers to prevent unwanted redirects
@app.errorhandler(403)
def forbidden(error):
    return render_template('errors/403.html'), 403

@app.errorhandler(401)
def unauthorized(error):
    from flask import request, jsonify, redirect, url_for
    # Check if this is an API request  
    if request.path.startswith('/obras/api/') or request.path.startswith('/api/'):
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    # For regular web requests, redirect to login
    login_endpoint = _first_available_endpoint('auth.login', 'supplier_auth.login')
    if login_endpoint:
        return redirect(url_for(login_endpoint))
    return redirect('/')

@app.errorhandler(404)
def not_found(error):
    return render_template('errors/404.html'), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
