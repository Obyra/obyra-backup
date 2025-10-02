import os
import logging
import importlib
import click
from flask import Flask, render_template, redirect, url_for, flash, send_from_directory, request
from flask.cli import AppGroup
from flask_login import login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.routing import BuildError
from extensions import db, login_manager

# create the app
app = Flask(__name__)
app.secret_key = (
    os.environ.get("SESSION_SECRET")
    or os.environ.get("SECRET_KEY")
    or "dev-secret-key-change-me"
)
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
login_manager.login_view = 'index'
login_manager.login_message = 'Por favor inicia sesión para acceder a esta página.'
login_manager.login_message_category = 'info'

db_cli = AppGroup('db')


@db_cli.command('upgrade')
def db_upgrade():
    """Apply pending lightweight database migrations."""
    with app.app_context():
        from migrations_runtime import ensure_avance_audit_columns, ensure_presupuesto_state_columns

        ensure_avance_audit_columns()
        ensure_presupuesto_state_columns()

    click.echo('✅ Database upgraded successfully.')


app.cli.add_command(db_cli)


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
    # For regular web requests, redirect to the main landing page preserving "next"
    return redirect(url_for('index', next=request.url))


# Register blueprints - moved after database initialization to avoid circular imports

# Funciones globales para templates
@app.context_processor
def utility_processor():
    from tareas_predefinidas import TAREAS_POR_ETAPA
    def obtener_tareas_para_etapa(nombre_etapa):
        return TAREAS_POR_ETAPA.get(nombre_etapa, [])

    def has_endpoint(endpoint_name: str) -> bool:
        return endpoint_name in app.view_functions

    return dict(
        obtener_tareas_para_etapa=obtener_tareas_para_etapa,
        has_endpoint=has_endpoint,
    )




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

@app.route('/', methods=['GET', 'POST'])
def index():
    """Landing principal con acceso a inicio de sesión y portal de proveedores."""
    if current_user.is_authenticated:
        # Si es operario, NO ve dashboard → lo mandamos a Mis Tareas
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
    return redirect(url_for('auth.login'))


@app.route('/dashboard')
def dashboard():
    if current_user.is_authenticated:
        # Si es operario, NO ve dashboard → lo mandamos a Mis Tareas
        if getattr(current_user, "role", None) == "operario":
            return redirect(url_for("obras.mis_tareas"))
        return redirect(url_for('reportes.dashboard'))
    return redirect(url_for('auth.login'))


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
        'perdido': 'bg-dark',
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
    from migrations_runtime import ensure_avance_audit_columns, ensure_presupuesto_state_columns
    ensure_avance_audit_columns()
    ensure_presupuesto_state_columns()

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

    # Ensure default admin credentials exist and are hashed correctly
    try:
        admin_email = 'admin@obyra.com'
        admin = Usuario.query.filter_by(email=admin_email).first()

        if not admin:
            admin_org = Organizacion(nombre='OBYRA - Administración Central')
            db.session.add(admin_org)
            db.session.flush()

            admin = Usuario(
                nombre='Administrador',
                apellido='OBYRA',
                email=admin_email,
                rol='administrador',
                role='administrador',
                auth_provider='manual',
                activo=True,
                organizacion_id=admin_org.id
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('👤 Usuario administrador creado: admin@obyra.com / admin123')
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

            if not admin.organizacion:
                admin_org = Organizacion(nombre='OBYRA - Administración Central')
                db.session.add(admin_org)
                db.session.flush()
                admin.organizacion_id = admin_org.id
                updated = True

            if updated:
                db.session.commit()
                print('🔐 Credenciales del administrador principal verificadas y aseguradas.')
    except Exception as ensure_admin_exc:
        db.session.rollback()
        print(f"⚠️ No se pudo garantizar el usuario admin@obyra.com: {ensure_admin_exc}")

def _import_blueprint(module_name, attr_name):
    """Importa un blueprint de manera segura sin interrumpir el resto."""
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


# Register blueprints after database initialization to avoid circular imports
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
    ('reports_service', 'reports_bp', None),
    ('account', 'account_bp', None),
    ('onboarding', 'onboarding_bp', '/onboarding'),
]:
    try:
        blueprint = _import_blueprint(module_name, attr_name)
        app.register_blueprint(blueprint, url_prefix=prefix)
    except Exception as exc:
        core_failures.append(f"{module_name} ({exc})")

if core_failures:
    print("⚠️ Some core blueprints not available: " + "; ".join(core_failures))
else:
    print("✅ Core blueprints registered successfully")

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

# Try to register marketplace blueprints
try:
    from marketplace.routes import bp as marketplace_bp
    app.register_blueprint(marketplace_bp, url_prefix="/")
    print("✅ Marketplace blueprint registered successfully")
except ImportError as e:
    print(f"⚠️ Marketplace blueprint not available: {e}")


# --- Public legal pages fallbacks ---------------------------------------
# Algunas implementaciones históricas definen estas rutas en módulos
# separados (p.ej. main.py), pero cuando esos blueprints no están
# disponibles la plantilla base sigue apuntando a los endpoints
# ``terminos`` y ``privacidad``. Para evitar nuevos BuildError cuando
# el proyecto se ejecuta en entornos mínimos (Replit, Visual Studio,
# etc.), agregamos reglas lightweight sólo si aún no existen.
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
    return redirect(url_for('auth.login'))

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
