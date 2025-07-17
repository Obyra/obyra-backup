from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from authlib.integrations.flask_client import OAuth
from app import db, app
from models import Usuario
import os
import re

auth_bp = Blueprint('auth', __name__)

# Configuración OAuth con Google
oauth = OAuth(app)
google = None

# Solo configurar Google OAuth si las variables están disponibles
if os.environ.get('GOOGLE_OAUTH_CLIENT_ID') and os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET'):
    google = oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_OAUTH_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )
else:
    print("""
🔗 Para habilitar Google OAuth en OBYRA IA:
1. Ve a https://console.cloud.google.com/apis/credentials
2. Crea un OAuth 2.0 Client ID
3. Agrega estas URLs autorizadas:
   - https://tu-dominio.replit.app/login/google/callback
4. Configura las variables de entorno:
   - GOOGLE_OAUTH_CLIENT_ID
   - GOOGLE_OAUTH_CLIENT_SECRET

Para más información: https://docs.replit.com/additional-resources/google-auth-in-flask
    """)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Por favor, completa todos los campos.', 'danger')
            return render_template('auth/login.html', google_available=bool(google))
        
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and usuario.activo:
            # Verificar si es usuario manual con contraseña
            if usuario.auth_provider == 'manual' and usuario.password_hash and check_password_hash(usuario.password_hash, password):
                login_user(usuario, remember=request.form.get('remember'))
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                return redirect(url_for('asistente.dashboard'))
            elif usuario.auth_provider == 'google':
                flash('Esta cuenta está vinculada con Google. Use "Iniciar sesión con Google".', 'warning')
            else:
                flash('Credenciales incorrectas.', 'danger')
        else:
            flash('Email o contraseña incorrectos, o cuenta inactiva.', 'danger')
    
    return render_template('auth/login.html', google_available=bool(google))

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada exitosamente.', 'info')
    return redirect(url_for('index'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Permitir registro público, pero usuarios existentes van al dashboard
    if current_user.is_authenticated:
        return redirect(url_for('asistente.dashboard'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        email = request.form.get('email')
        telefono = request.form.get('telefono')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validaciones
        if not all([nombre, apellido, email, password]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))
        
        # Validar formato de email
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            flash('Por favor, ingresa un email válido.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))
        
        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))
        
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))
        
        # Verificar que el email no exista
        if Usuario.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese email.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))
        
        try:
            # Crear nuevo usuario
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email.lower(),
                telefono=telefono,
                password_hash=generate_password_hash(password),
                rol='operario',  # Por defecto
                auth_provider='manual',
                activo=True
            )
            
            db.session.add(nuevo_usuario)
            db.session.commit()
            
            # Auto-login después del registro
            login_user(nuevo_usuario)
            flash(f'¡Bienvenido/a {nombre}! Tu cuenta ha sido creada exitosamente.', 'success')
            return redirect(url_for('asistente.dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error al crear la cuenta. Por favor, intenta de nuevo.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))
    
    return render_template('auth/register.html', google_available=bool(google))


# ================================
# RUTAS DE GOOGLE OAUTH
# ================================

@auth_bp.route('/login/google')
def google_login():
    """Iniciar login con Google"""
    if current_user.is_authenticated:
        return redirect(url_for('asistente.dashboard'))
    
    if not google:
        flash('Google OAuth no está configurado. Contacta al administrador.', 'warning')
        return redirect(url_for('auth.login'))
    
    # URL de callback para Google
    redirect_uri = url_for('auth.google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)


@auth_bp.route('/login/google/callback')
def google_callback():
    """Callback de Google OAuth"""
    if not google:
        flash('Google OAuth no está configurado.', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if not user_info:
            flash('Error al obtener información de Google.', 'danger')
            return redirect(url_for('auth.login'))
        
        email = user_info.get('email')
        nombre = user_info.get('given_name', '')
        apellido = user_info.get('family_name', '')
        google_id = user_info.get('sub')
        profile_picture = user_info.get('picture', '')
        
        if not email:
            flash('No se pudo obtener el email de Google.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Buscar usuario existente por email
        usuario = Usuario.query.filter_by(email=email.lower()).first()
        
        if usuario:
            # Usuario existente - actualizar con datos de Google si es necesario
            if usuario.auth_provider == 'manual':
                # Convertir cuenta manual a Google
                usuario.auth_provider = 'google'
                usuario.google_id = google_id
                # Actualizar información del perfil con datos de Google
                if nombre:
                    usuario.nombre = nombre
                if apellido:
                    usuario.apellido = apellido
                if profile_picture:
                    usuario.profile_picture = profile_picture
            elif usuario.auth_provider == 'google':
                # Actualizar datos de Google siempre para mantener información actualizada
                usuario.google_id = google_id
                if nombre:
                    usuario.nombre = nombre
                if apellido:
                    usuario.apellido = apellido
                if profile_picture:
                    usuario.profile_picture = profile_picture
            
            if usuario.activo:
                # Guardar cambios en la base de datos
                db.session.commit()
                login_user(usuario)
                flash(f'¡Bienvenido/a de vuelta, {usuario.nombre}!', 'success')
                return redirect(url_for('asistente.dashboard'))
            else:
                flash('Tu cuenta está inactiva. Contacta al administrador.', 'warning')
                return redirect(url_for('auth.login'))
        else:
            # Crear nuevo usuario con Google
            try:
                nuevo_usuario = Usuario(
                    nombre=nombre or 'Usuario',
                    apellido=apellido or 'Google',
                    email=email.lower(),
                    auth_provider='google',
                    google_id=google_id,
                    profile_picture=profile_picture,  # Guardar foto de perfil automáticamente
                    rol='operario',  # Por defecto
                    activo=True,
                    password_hash=None  # No necesita contraseña
                )
                
                db.session.add(nuevo_usuario)
                db.session.commit()
                
                login_user(nuevo_usuario)
                flash(f'¡Bienvenido/a a OBYRA IA, {nombre}! Tu cuenta ha sido creada con Google.', 'success')
                return redirect(url_for('asistente.dashboard'))
                
            except Exception as e:
                db.session.rollback()
                flash('Error al crear la cuenta con Google. Intenta de nuevo.', 'danger')
                return redirect(url_for('auth.login'))
                
    except Exception as e:
        flash('Error en la autenticación con Google. Intenta de nuevo.', 'danger')
        return redirect(url_for('auth.login'))


# ================================
# RUTAS ADMINISTRATIVAS
# ================================

@auth_bp.route('/admin/register', methods=['GET', 'POST'])
@login_required
def admin_register():
    """Registro administrativo - solo para administradores"""
    if current_user.rol != 'administrador':
        flash('No tienes permisos para registrar usuarios administrativamente.', 'danger')
        return redirect(url_for('asistente.dashboard'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        email = request.form.get('email')
        telefono = request.form.get('telefono')
        rol = request.form.get('rol')
        password = request.form.get('password')
        
        # Validaciones
        if not all([nombre, apellido, email, rol, password]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            return render_template('auth/admin_register.html')
        
        if rol not in ['administrador', 'tecnico', 'operario']:
            flash('Rol no válido.', 'danger')
            return render_template('auth/admin_register.html')
        
        if Usuario.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese email.', 'danger')
            return render_template('auth/admin_register.html')
        
        try:
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email.lower(),
                telefono=telefono,
                password_hash=generate_password_hash(password),
                rol=rol,
                auth_provider='manual',
                activo=True
            )
            
            db.session.add(nuevo_usuario)
            db.session.commit()
            flash(f'Usuario {nombre} {apellido} registrado exitosamente.', 'success')
            return redirect(url_for('equipos.lista'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error al registrar el usuario. Intenta nuevamente.', 'danger')
    
    return render_template('auth/admin_register.html')

@auth_bp.route('/usuarios')
@login_required
def lista_usuarios():
    if current_user.rol != 'administrador':
        flash('No tienes permisos para ver la lista de usuarios.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    usuarios = Usuario.query.order_by(Usuario.apellido, Usuario.nombre).all()
    return render_template('equipos/lista.html', usuarios=usuarios)

@auth_bp.route('/usuario/<int:id>/toggle')
@login_required
def toggle_usuario(id):
    if current_user.rol != 'administrador':
        flash('No tienes permisos para activar/desactivar usuarios.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    usuario = Usuario.query.get_or_404(id)
    if usuario.id == current_user.id:
        flash('No puedes desactivar tu propia cuenta.', 'danger')
        return redirect(url_for('auth.lista_usuarios'))
    
    usuario.activo = not usuario.activo
    try:
        db.session.commit()
        estado = "activado" if usuario.activo else "desactivado"
        flash(f'Usuario {usuario.nombre_completo} {estado} exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al cambiar el estado del usuario.', 'danger')
    
    return redirect(url_for('auth.lista_usuarios'))
