import os
import logging
from flask import Flask, render_template, redirect, url_for
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
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///obyra.db"
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
from reportes import reportes_bp
from asistente_ia import asistente_bp
from cotizacion_inteligente import cotizacion_bp
from control_documentos import documentos_bp
from seguridad_cumplimiento import seguridad_bp
from agent_local import agent_bp  # 👈 nuestro mini agente local

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(obras_bp, url_prefix='/obras')
app.register_blueprint(presupuestos_bp, url_prefix='/presupuestos')
app.register_blueprint(equipos_bp, url_prefix='/equipos')
app.register_blueprint(inventario_bp, url_prefix='/inventario')
app.register_blueprint(reportes_bp, url_prefix='/reportes')
app.register_blueprint(asistente_bp, url_prefix='/asistente')
app.register_blueprint(cotizacion_bp, url_prefix='/cotizacion')
app.register_blueprint(documentos_bp, url_prefix='/documentos')
app.register_blueprint(seguridad_bp, url_prefix='/seguridad')



@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('reportes.dashboard'))
    return render_template('index.html')


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


# Create tables and initial data
with app.app_context():
    from models import Usuario, Organizacion

    # Create all tables
    db.create_all()
    print("📊 Database tables created successfully")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
