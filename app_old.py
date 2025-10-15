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

with app.app_context():
    # Importar todos los modelos antes de crear las tablas
    import models

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('asistente.dashboard'))
    return render_template('index.html')

# Jinja2 custom filters
@app.template_filter('numero')
def numero_filter(valor, decimales=0):
    """Formatea número con separador de miles"""
    if valor is None:
        return "0"
    try:
        if decimales == 0:
            return f"{int(valor):,}".replace(',', '.')
        else:
            return f"{float(valor):,.{decimales}f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return str(valor)

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

@app.template_filter('estado_badge')
def estado_badge_filter(estado):
    """Retorna clase CSS para badge según estado"""
    clases = {
        'borrador': 'bg-secondary',
        'enviado': 'bg-warning',
        'aprobado': 'bg-success',
        'rechazado': 'bg-danger',
        'planificacion': 'bg-info',
        'en_curso': 'bg-primary',
        'pausada': 'bg-warning',
        'finalizada': 'bg-success',
        'cancelada': 'bg-danger'
    }
    return clases.get(estado, 'bg-secondary')

@app.context_processor
def inject_user():
    return dict(current_user=current_user)

with app.app_context():
    import models
    from models import Usuario, Organizacion, Obra, ItemInventario
    from werkzeug.security import generate_password_hash
    
    # Función para migrar datos existentes
    def migrar_organizaciones():
        try:
            # Solo migrar si hay usuarios sin organizacion_id
            usuarios_sin_org = []
            try:
                usuarios_sin_org = Usuario.query.filter(Usuario.organizacion_id == None).all()
            except:
                # Si falla, probablemente la columna no existe todavía
                pass
            
            for usuario in usuarios_sin_org:
                # Crear nueva organización para cada usuario existente
                nueva_org = Organizacion(
                    nombre=f"Organización de {usuario.nombre_completo}",
                    fecha_creacion=usuario.fecha_creacion or datetime.utcnow()
                )
                db.session.add(nueva_org)
                db.session.flush()  # Para obtener el ID
                
                # Asignar la organización al usuario
                usuario.organizacion_id = nueva_org.id
                if usuario.rol != 'administrador':
                    usuario.rol = 'administrador'  # Usuarios existentes se convierten en admins de su org
                
                print(f"🏢 Organización creada para {usuario.nombre_completo}")
            
            # Migrar obras existentes
            try:
                obras_sin_org = Obra.query.filter(Obra.organizacion_id == None).all()
                
                if obras_sin_org and usuarios_sin_org:
                    primera_org = Organizacion.query.first()
                    if primera_org:
                        for obra in obras_sin_org:
                            obra.organizacion_id = primera_org.id
                        print(f"📋 {len(obras_sin_org)} obras migradas")
            except Exception as e:
                print(f"⚠️ Error migrando obras: {e}")
            
            # Migrar inventario existente
            try:
                items_sin_org = ItemInventario.query.filter(ItemInventario.organizacion_id == None).all()
                
                if items_sin_org and usuarios_sin_org:
                    primera_org = Organizacion.query.first()
                    if primera_org:
                        for item in items_sin_org:
                            item.organizacion_id = primera_org.id
                        print(f"📦 {len(items_sin_org)} items de inventario migrados")
            except Exception as e:
                print(f"⚠️ Error migrando inventario: {e}")
            
            db.session.commit()
            if usuarios_sin_org:
                print("✅ Migración de organizaciones completada")
                
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error en migración: {e}")
    
    # Ejecutar migración
    migrar_organizaciones()
    
    # Crear usuario administrador por defecto si no existe
    admin = Usuario.query.filter_by(email='admin@obyra.com').first()
    if not admin:
        # Crear organización para admin
        admin_org = Organizacion(
            nombre='OBYRA - Administración Central'
        )
        db.session.add(admin_org)
        db.session.flush()
        
        admin = Usuario(
            nombre='Administrador',
            apellido='Sistema',
            email='admin@obyra.com',
            telefono='1234567890',
            rol='administrador',
            activo=True,
            organizacion_id=admin_org.id
        )
        admin.password_hash = generate_password_hash('admin123')
        db.session.add(admin)
        db.session.commit()
        print("👤 Usuario administrador creado: admin@obyra.com / admin123")

def maybe_create_sqlite_schema():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if os.getenv("AUTO_CREATE_DB", "0") == "1" and uri.startswith("sqlite:"):
        with app.app_context():
            db.create_all()
        print("📊 Tablas de base de datos creadas correctamente")


if __name__ == '__main__':
    maybe_create_sqlite_schema()
    app.run(host='0.0.0.0', port=5000, debug=True)
