import os
import logging
from pathlib import Path
from flask import Flask, render_template, redirect, url_for, flash, send_from_directory
from flask_login import login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
from werkzeug.routing import BuildError
from extensions import db, login_manager

# create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# configure logging
logging.basicConfig(level=logging.DEBUG)

# configure the database with fallback to SQLite
database_url = os.environ.get("DATABASE_URL")

base_dir = Path(__file__).resolve().parent
default_sqlite_path = base_dir / "tmp" / "dev.db"

# 🔥 FALLBACK: Si no hay DATABASE_URL o falla conexión, usar SQLite local
if not database_url:
    default_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{default_sqlite_path.as_posix()}"
    print("⚠️  DATABASE_URL no disponible, usando SQLite fallback")
else:
    # Verificar si DATABASE_URL contiene host de Neon y aplicar SSL
    if "neon.tech" in database_url and "sslmode=" not in database_url:
        if "?" in database_url:
            database_url += "&sslmode=require"
        else:
            database_url += "?sslmode=require"
        print("🔒 SSL requerido agregado para Neon")

    if database_url.startswith("sqlite:///"):
        # Normalizar rutas relativas a la carpeta del proyecto
        sqlite_path = database_url.replace("sqlite:///", "", 1)
        sqlite_path_obj = Path(sqlite_path)
        if not sqlite_path_obj.is_absolute():
            sqlite_path_obj = (base_dir / sqlite_path_obj).resolve()
            database_url = f"sqlite:///{sqlite_path_obj.as_posix()}"
        sqlite_path_obj.parent.mkdir(parents=True, exist_ok=True)

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
login_manager.login_view = None
login_manager.login_message = 'Por favor inicia sesión para acceder a esta página.'
login_manager.login_message_category = 'info'


def _resolve_login_url() -> str:
    for endpoint in ('auth.login', 'supplier_auth.login'):
        try:
            return url_for(endpoint)
        except BuildError:
            continue
    return '/proveedor/login'


def _login_redirect():
    return redirect(_resolve_login_url())


def _refresh_login_view() -> None:
    for endpoint in ('auth.login', 'supplier_auth.login'):
        if endpoint in app.view_functions:
            login_manager.login_view = endpoint
            return
    login_manager.login_view = None


@app.context_processor
def inject_login_url():
    return {"login_url": _resolve_login_url()}


@login_manager.user_loader
def load_user(user_id):
    # Import here to avoid circular imports
    from models import Usuario
    return Usuario.query.get(int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    """Custom unauthorized handler that returns JSON for API routes"""
    from flask import request, jsonify
    # Check if this is an API request
    if request.path.startswith('/obras/api/') or request.path.startswith('/api/'):
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    # For regular web requests, redirect to login
    return _login_redirect()


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
        'auth.login', 'auth.register', 'auth.logout',
        'supplier_auth.login', 'static', 'index'
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
        return redirect(url_for('reportes.dashboard'))
    return _login_redirect()


@app.route('/dashboard')
def dashboard():
    if current_user.is_authenticated:
        # Si es operario, NO ve dashboard → lo mandamos a Mis Tareas
        if getattr(current_user, "role", None) == "operario":
            return redirect(url_for("obras.mis_tareas"))
        return redirect(url_for('reportes.dashboard'))
    return _login_redirect()


@app.route('/login')
def login_redirect():
    """Ruta de compatibilidad que redirige al login activo."""

    return _login_redirect()


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

# Register blueprints after database initialization to avoid circular imports
try:
    from auth import auth_bp
    from obras import obras_bp
    from presupuestos import presupuestos_bp
    from equipos import equipos_bp
    from inventario import inventario_bp
    from marketplaces import marketplaces_bp
    from reportes import reportes_bp
    from asistente_ia import asistente_bp
    from cotizacion_inteligente import cotizacion_bp
    from control_documentos import documentos_bp
    from seguridad_cumplimiento import seguridad_bp
    from agent_local import agent_bp
    from planes import planes_bp
    from events_service import events_bp
    from reports_service import reports_bp
    
    # Initialize OAuth with app before registering auth blueprint
    from auth import oauth
    oauth.init_app(app)
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(obras_bp, url_prefix='/obras')
    app.register_blueprint(presupuestos_bp, url_prefix='/presupuestos')
    app.register_blueprint(equipos_bp, url_prefix='/equipos')
    app.register_blueprint(inventario_bp, url_prefix='/inventario')
    app.register_blueprint(marketplaces_bp, url_prefix='/marketplaces')
    app.register_blueprint(reportes_bp, url_prefix='/reportes')
    app.register_blueprint(asistente_bp, url_prefix='/asistente')
    app.register_blueprint(cotizacion_bp, url_prefix='/cotizacion')
    app.register_blueprint(documentos_bp, url_prefix='/documentos')
    app.register_blueprint(seguridad_bp, url_prefix='/seguridad')
    app.register_blueprint(agent_bp)
    app.register_blueprint(planes_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(reports_bp)
    
    print("✅ Core blueprints registered successfully")
except ImportError as e:
    print(f"⚠️ Some core blueprints not available: {e}")

_refresh_login_view()

# Try to register optional blueprints
try:
    from equipos_new import equipos_new_bp
    from inventario_new import inventario_new_bp
    app.register_blueprint(equipos_new_bp, url_prefix='/equipos-new')
    app.register_blueprint(inventario_new_bp, url_prefix='/inventario-new')
    print("✅ Enhanced blueprints registered successfully")
except ImportError as e:
    print(f"⚠️ Enhanced blueprints not available: {e}")

# Try to register supplier portal blueprints
try:
    from supplier_auth import supplier_auth_bp
    from supplier_portal import supplier_portal_bp
    from market import market_bp
    app.register_blueprint(supplier_auth_bp)
    app.register_blueprint(supplier_portal_bp)
    app.register_blueprint(market_bp)
    print("✅ Supplier portal blueprints registered successfully")
except ImportError as e:
    print(f"⚠️ Supplier portal blueprints not available: {e}")

_refresh_login_view()

# Try to register marketplace blueprints
try:
    from marketplace.routes import bp as marketplace_bp
    app.register_blueprint(marketplace_bp, url_prefix="/")
    print("✅ Marketplace blueprint registered successfully")
except ImportError as e:
    print(f"⚠️ Marketplace blueprint not available: {e}")

_refresh_login_view()


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
    from flask import request, jsonify
    # Check if this is an API request
    if request.path.startswith('/obras/api/') or request.path.startswith('/api/'):
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    # For regular web requests, redirect to login
    return _login_redirect()

@app.errorhandler(404)
def not_found(error):
    return render_template('errors/404.html'), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
