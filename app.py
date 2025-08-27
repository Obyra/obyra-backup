import os
import logging
from flask import Flask, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()

# create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "obyra-ia-secret-key-2024")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# configure logging
logging.basicConfig(level=logging.DEBUG)

# configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# initialize extensions
db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Por favor inicia sesión para acceder a esta página.'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    from models import Usuario
    return Usuario.query.get(int(user_id))


# Register blueprints
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
from agent_local import agent_bp  # 👈 nuestro mini agente local
from planes import planes_bp

# Importar nuevos blueprints mejorados
from equipos_new import equipos_new_bp
from inventario_new import inventario_new_bp

# Importar blueprints del Portal de Proveedores
from supplier_auth import supplier_auth_bp
from supplier_portal import supplier_portal_bp
from market import market_bp

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
app.register_blueprint(agent_bp)  # Agente IA local sin prefijo
app.register_blueprint(planes_bp)  # Sistema de planes

# Registrar nuevos blueprints mejorados
app.register_blueprint(equipos_new_bp, url_prefix='/equipos-new')
app.register_blueprint(inventario_new_bp, url_prefix='/inventario-new')

# Registrar blueprints del Portal de Proveedores
app.register_blueprint(supplier_auth_bp)  # Ya tiene prefix '/proveedor'
app.register_blueprint(supplier_portal_bp)  # Ya tiene prefix '/proveedor'
app.register_blueprint(market_bp)  # Ya tiene prefix '/market'

# Registrar nuevos blueprints del marketplace mejorado
from marketplace import marketplace_bp
from cart import cart_bp
from orders import orders_bp

app.register_blueprint(marketplace_bp)  # Ya tiene prefix /market
app.register_blueprint(cart_bp)  # Ya tiene prefix /cart
app.register_blueprint(orders_bp)  # Ya tiene prefix /orders

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
        return redirect(url_for('reportes.dashboard'))
    return redirect(url_for('auth.login'))


@app.route('/dashboard')
def dashboard():
    if current_user.is_authenticated:
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
    from models import Usuario, Organizacion

    # Create all tables
    db.create_all()
    print("📊 Database tables created successfully")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
