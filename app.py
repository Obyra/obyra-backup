import os
import logging
from flask import Flask, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix


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
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///obyra.db")
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
        return redirect(url_for('asistente.dashboard'))
    return render_template('index.html')

# Jinja2 custom filters
@app.template_filter('fecha')
def fecha_filter(fecha):
    """Formatea fecha para mostrar en templates"""
    if fecha:
        if hasattr(fecha, 'strftime'):
            return fecha.strftime('%d/%m/%Y')
        return str(fecha)
    return '-'

@app.template_filter('moneda')
def moneda_filter(cantidad):
    """Formatea cantidad como moneda argentina"""
    if cantidad is None:
        return "$0"
    return f"${cantidad:,.0f}".replace(",", ".")

@app.context_processor
def inject_user():
    return dict(current_user=current_user)

with app.app_context():
    import models
    db.create_all()
    
    # Crear usuario administrador por defecto
    from models import Usuario
    from werkzeug.security import generate_password_hash
    
    admin = Usuario.query.filter_by(email='admin@obyra.com').first()
    if not admin:
        admin = Usuario(
            nombre='Administrador',
            apellido='Sistema',
            email='admin@obyra.com',
            telefono='1234567890',
            rol='administrador',
            activo=True
        )
        admin.password_hash = generate_password_hash('admin123')
        db.session.add(admin)
        db.session.commit()
        logging.info("Usuario administrador creado: admin@obyra.com / admin123")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
