from flask import Blueprint, render_template, request, flash, redirect, url_for, session, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from extensions import db
from models import Usuario, Organizacion, PerfilUsuario, OnboardingStatus
from sqlalchemy import func
from datetime import datetime
from typing import Dict, Optional, Tuple, Union
import os
import re
import uuid
from werkzeug.routing import BuildError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


def normalizar_cuit(valor: Optional[str]) -> str:
    """Elimina caracteres no numéricos y limita a 11 dígitos."""
    if not valor:
        return ''
    return re.sub(r'[^0-9]', '', valor)[:11]


def validar_cuit(valor: Optional[str]) -> bool:
    """Valida CUIL/CUIT usando el algoritmo estándar de verificación."""
    cuit = normalizar_cuit(valor)
    if len(cuit) != 11:
        return False

    try:
        base = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
        total = sum(int(cuit[i]) * base[i] for i in range(10))
        resto = total % 11
        verificador = 11 - resto
        if verificador == 11:
            verificador = 0
        elif verificador == 10:
            verificador = 9
        return int(cuit[-1]) == verificador
    except ValueError:
        return False

auth_bp = Blueprint('auth', __name__)

# Configuración OAuth con Google
oauth = OAuth()
google = None

PASSWORD_RESET_SALT = 'obyra-password-reset'

# Lista blanca de emails para administradores automáticos
ADMIN_EMAILS = [
    'brenda@gmail.com',
    'cliente@empresa.com',
    'admin@obyra.com',
    'admin@obyra.ia'
]

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


AuthResult = Tuple[bool, Union[Usuario, Dict[str, str]]]


def authenticate_manual_user(email: Optional[str], password: Optional[str], *, remember: bool = False) -> AuthResult:
    """Autentica a un usuario interno y devuelve (success, payload)."""
    normalized_email = (email or '').strip()
    password = password or ''

    if not normalized_email or not password:
        return False, {
            'message': 'Por favor, completa todos los campos.',
            'category': 'danger',
        }

    usuario = Usuario.query.filter(func.lower(Usuario.email) == normalized_email.lower()).first()

    if not usuario or not usuario.activo:
        return False, {
            'message': 'Email o contraseña incorrectos, o cuenta inactiva.',
            'category': 'danger',
        }

    if usuario.auth_provider == 'google':
        return False, {
            'message': 'Esta cuenta está vinculada con Google. Usa "Iniciar sesión con Google".',
            'category': 'warning',
        }

    if usuario.auth_provider != 'manual' or not usuario.password_hash:
        return False, {
            'message': 'Credenciales incorrectas.',
            'category': 'danger',
        }

    if not usuario.check_password(password):
        return False, {
            'message': 'Credenciales incorrectas.',
            'category': 'danger',
        }

    login_user(usuario, remember=remember)
    return True, usuario


def _resolve_dashboard_url() -> str:
    """Obtiene la URL más adecuada para enviar al usuario autenticado."""
    for endpoint in (
        'reportes.dashboard',
        'obras.lista',
        'supplier_portal.dashboard',
        'index',
    ):
        try:
            return url_for(endpoint)
        except BuildError:
            continue
    return '/'


def _determine_onboarding_redirect(usuario: Usuario) -> Optional[str]:
    """Devuelve la ruta del siguiente paso de onboarding o None si está completo."""
    status = usuario.ensure_onboarding_status()
    db.session.commit()

    if not status.profile_completed:
        return url_for('onboarding.profile')

    if not status.billing_completed:
        return url_for('onboarding.billing')

    return None


def _post_login_destination(usuario: Usuario, next_page: Optional[str] = None) -> str:
    """Determina la redirección apropiada tras el login o registro."""
    if next_page:
        return next_page

    onboarding_url = _determine_onboarding_redirect(usuario)
    if onboarding_url:
        return onboarding_url

    if getattr(usuario, 'role', None) == 'operario':
        try:
            return url_for('obras.mis_tareas')
        except BuildError:
            pass

    return _resolve_dashboard_url()


def _get_reset_serializer() -> URLSafeTimedSerializer:
    secret_key = current_app.config.get('SECRET_KEY')
    if not secret_key:
        raise RuntimeError('SECRET_KEY no está configurado, no se puede generar tokens seguros.')
    return URLSafeTimedSerializer(secret_key)


def _generate_reset_token(usuario: Usuario) -> str:
    serializer = _get_reset_serializer()
    payload = {
        'user_id': usuario.id,
        'email': usuario.email,
    }
    return serializer.dumps(payload, salt=PASSWORD_RESET_SALT)


def _load_reset_token(token: str, max_age: int = 3600) -> Usuario:
    serializer = _get_reset_serializer()
    try:
        data = serializer.loads(token, salt=PASSWORD_RESET_SALT, max_age=max_age)
    except SignatureExpired as exc:
        raise SignatureExpired('El enlace para restablecer la contraseña ha expirado.') from exc
    except BadSignature as exc:
        raise BadSignature('El enlace de restablecimiento no es válido.') from exc

    user_id = data.get('user_id')
    email = data.get('email')
    if not user_id or not email:
        raise BadSignature('Token de restablecimiento incompleto.')

    usuario = Usuario.query.get(user_id)
    if not usuario or usuario.email.lower() != email.lower():
        raise BadSignature('El token no coincide con ningún usuario válido.')
    return usuario

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    next_page = request.args.get('next') or request.form.get('next')
    form_data = {
        'email': request.form.get('email', ''),
        'remember': bool(request.form.get('remember')),
    }

    if request.method == 'POST':
        success, payload = authenticate_manual_user(
            form_data['email'],
            request.form.get('password', ''),
            remember=form_data['remember'],
        )

        if success:
            usuario = payload
            destino = _post_login_destination(usuario, next_page)
            return redirect(destino)

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
        'auth/login.html',
        google_available=bool(google),
        form_data=form_data,
        next_value=next_page,
    )


@auth_bp.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()

        if not email:
            flash('Por favor, ingresa tu email para continuar.', 'warning')
            return render_template('auth/forgot.html')

        usuario = Usuario.query.filter(func.lower(Usuario.email) == email).first()

        if usuario and usuario.auth_provider == 'manual' and usuario.activo:
            token = _generate_reset_token(usuario)
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            _deliver_reset_link(usuario, reset_url)

        flash('Si el email corresponde a una cuenta activa, te enviamos las instrucciones para restablecer la contraseña.', 'info')
        return redirect(url_for('auth.forgot_password'))

    return render_template('auth/forgot.html')


@auth_bp.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token: str):
    try:
        usuario = _load_reset_token(token)
    except SignatureExpired:
        flash('El enlace ha expirado. Por favor, solicita uno nuevo.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    except BadSignature:
        flash('El enlace no es válido. Solicita uno nuevo para continuar.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm_password') or ''

        if not password or not confirm:
            flash('Debes ingresar y confirmar tu nueva contraseña.', 'warning')
            return render_template('auth/reset.html', token=token)

        if password != confirm:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('auth/reset.html', token=token)

        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('auth/reset.html', token=token)

        usuario.set_password(password)
        usuario.auth_provider = 'manual'
        db.session.commit()

        flash('Tu contraseña fue actualizada. Ahora puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset.html', token=token)

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
        return redirect(url_for('reportes.dashboard'))
    
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        apellido = (request.form.get('apellido') or '').strip()
        email = (request.form.get('email') or '').strip()
        telefono = (request.form.get('telefono') or '').strip()
        cuit_input = (request.form.get('cuit') or '').strip()
        direccion = (request.form.get('direccion') or '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # Validaciones
        if not all([nombre, apellido, email, password, cuit_input, direccion]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))

        # Validar formato de email
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            flash('Por favor, ingresa un email válido.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))

        cuit_normalizado = normalizar_cuit(cuit_input)
        if not validar_cuit(cuit_normalizado):
            flash('El CUIL/CUIT ingresado no es válido.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))

        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))

        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))
        
        # Verificar que el email no exista
        if Usuario.query.filter(func.lower(Usuario.email) == email.lower()).first():
            flash('Ya existe un usuario con ese email.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))

        if PerfilUsuario.query.filter_by(cuit=cuit_normalizado).first():
            flash('Ya existe un usuario registrado con ese CUIL/CUIT.', 'danger')
            return render_template('auth/register.html', google_available=bool(google))

        try:
            nueva_organizacion = Organizacion(
                nombre=f"Organización de {nombre} {apellido}",
                fecha_creacion=datetime.utcnow()
            )
            db.session.add(nueva_organizacion)
            db.session.flush()

            rol_usuario = 'administrador'
            # Crear nuevo usuario
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email.lower(),
                telefono=telefono,
                rol=rol_usuario,
                role=rol_usuario,
                auth_provider='manual',
                activo=True,
                organizacion_id=nueva_organizacion.id
            )

            nuevo_usuario.set_password(password)

            db.session.add(nuevo_usuario)
            db.session.flush()

            perfil_usuario = PerfilUsuario(
                usuario_id=nuevo_usuario.id,
                cuit=cuit_normalizado,
                direccion=direccion
            )
            db.session.add(perfil_usuario)

            onboarding_status = OnboardingStatus(usuario=nuevo_usuario)
            db.session.add(onboarding_status)

            db.session.commit()

            # Auto-login después del registro
            login_user(nuevo_usuario)
            flash(f'¡Bienvenido/a {nombre}! Tu cuenta ha sido creada exitosamente.', 'success')
            destino = _post_login_destination(nuevo_usuario)
            return redirect(destino)
            
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
        return redirect(url_for('reportes.dashboard'))
    
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
                destino = _post_login_destination(usuario)
                return redirect(destino)
            else:
                flash('Tu cuenta está inactiva. Contacta al administrador.', 'warning')
                return redirect(url_for('auth.login'))
        else:
            # Verificar si el email ya existe en otra organización
            usuario_existente = Usuario.query.filter_by(email=email.lower()).first()
            if usuario_existente:
                flash('⚠️ Este correo ya está registrado. Debés ser invitado por un administrador de tu organización para acceder.', 'warning')
                return redirect(url_for('auth.login'))
            
            # Crear nuevo usuario con Google
            try:
                # Verificar si hay una invitación pendiente en la sesión
                token_invitacion = session.get('token_invitacion')
                organizacion_id = session.get('organizacion_invitacion')
                
                if token_invitacion and organizacion_id:
                    # Usuario viene por invitación - se une a organización existente
                    organizacion = Organizacion.query.get(organizacion_id)
                    if organizacion and organizacion.token_invitacion == token_invitacion:
                        nuevo_usuario = Usuario(
                            nombre=nombre or 'Usuario',
                            apellido=apellido or 'Google',
                            email=email.lower(),
                            auth_provider='google',
                            google_id=google_id,
                            profile_picture=profile_picture,
                            rol='operario',  # Invitados son operarios por defecto
                            activo=True,
                            password_hash=None,
                            organizacion_id=organizacion_id
                        )
                        
                        # Limpiar sesión
                        session.pop('token_invitacion', None)
                        session.pop('organizacion_invitacion', None)
                        
                        mensaje = f'¡Bienvenido/a a {organizacion.nombre}, {nombre}!'
                    else:
                        flash('Token de invitación inválido.', 'danger')
                        return redirect(url_for('auth.login'))
                else:
                    # Usuario nuevo - crear organización propia
                    rol_usuario = 'administrador' if email.lower() in ADMIN_EMAILS else 'administrador'
                    
                    nueva_organizacion = Organizacion(
                        nombre=f"Organización de {nombre} {apellido}",
                        fecha_creacion=datetime.utcnow()
                    )
                    db.session.add(nueva_organizacion)
                    db.session.flush()  # Para obtener el ID
                    
                    nuevo_usuario = Usuario(
                        nombre=nombre or 'Usuario',
                        apellido=apellido or 'Google',
                        email=email.lower(),
                        auth_provider='google',
                        google_id=google_id,
                        profile_picture=profile_picture,
                        rol=rol_usuario,
                        activo=True,
                        password_hash=None,
                        organizacion_id=nueva_organizacion.id
                    )
                    
                    mensaje = f'¡Bienvenido/a a OBYRA IA, {nombre}! Tu organización ha sido creada.'
                
                db.session.add(nuevo_usuario)
                db.session.add(OnboardingStatus(usuario=nuevo_usuario))
                db.session.commit()

                login_user(nuevo_usuario)
                flash(mensaje, 'success')
                destino = _post_login_destination(nuevo_usuario)
                return redirect(destino)
                
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
        return redirect(url_for('reportes.dashboard'))
    
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
            from roles_construccion import obtener_roles_por_categoria
            return render_template('auth/admin_register.html', roles_por_categoria=obtener_roles_por_categoria())
        
        # Importar roles válidos
        from roles_construccion import ROLES_CONSTRUCCION
        if rol not in ROLES_CONSTRUCCION.keys():
            flash('Rol no válido.', 'danger')
            return render_template('auth/admin_register.html', roles_por_categoria=obtener_roles_por_categoria())
        
        if Usuario.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese email.', 'danger')
            from roles_construccion import obtener_roles_por_categoria
            return render_template('auth/admin_register.html', roles_por_categoria=obtener_roles_por_categoria())
        
        try:
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email.lower(),
                telefono=telefono,
                rol=rol,
                auth_provider='manual',
                activo=True,
                organizacion_id=current_user.organizacion_id
            )

            nuevo_usuario.set_password(password)
            
            db.session.add(nuevo_usuario)
            db.session.commit()
            flash(f'Usuario {nombre} {apellido} registrado exitosamente.', 'success')
            return redirect(url_for('auth.usuarios_admin'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error al registrar el usuario. Intenta nuevamente.', 'danger')
    
    from roles_construccion import obtener_roles_por_categoria
    return render_template('auth/admin_register.html', roles_por_categoria=obtener_roles_por_categoria())

@auth_bp.route('/usuarios')
@login_required
def usuarios_admin():
    """Panel de administración de usuarios - solo para administradores"""
    if current_user.rol != 'administrador':
        flash('No tienes permisos para acceder a la gestión de usuarios.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    # Filtros
    rol_filtro = request.args.get('rol', '')
    auth_provider_filtro = request.args.get('auth_provider', '')
    buscar = request.args.get('buscar', '')
    
    # Query base - solo usuarios de la misma organización
    query = Usuario.query.filter_by(organizacion_id=current_user.organizacion_id)
    
    # Aplicar filtros
    if rol_filtro:
        query = query.filter(Usuario.rol == rol_filtro)
    
    if auth_provider_filtro:
        query = query.filter(Usuario.auth_provider == auth_provider_filtro)
    
    if buscar:
        query = query.filter(
            db.or_(
                Usuario.nombre.contains(buscar),
                Usuario.apellido.contains(buscar),
                Usuario.email.contains(buscar)
            )
        )
    
    usuarios = query.order_by(Usuario.apellido, Usuario.nombre).all()
    
    # Estadísticas - solo de la organización
    total_usuarios = Usuario.query.filter_by(organizacion_id=current_user.organizacion_id).count()
    usuarios_activos = Usuario.query.filter_by(organizacion_id=current_user.organizacion_id, activo=True).count()
    admins_count = Usuario.query.filter_by(organizacion_id=current_user.organizacion_id, rol='administrador').count()
    usuarios_google = Usuario.query.filter_by(organizacion_id=current_user.organizacion_id, auth_provider='google').count()
    
    return render_template('auth/usuarios_admin.html', 
                         usuarios=usuarios,
                         total_usuarios=total_usuarios,
                         usuarios_activos=usuarios_activos,
                         admins_count=admins_count,
                         usuarios_google=usuarios_google,
                         rol_filtro=rol_filtro,
                         auth_provider_filtro=auth_provider_filtro,
                         buscar=buscar)

@auth_bp.route('/usuarios/cambiar_rol', methods=['POST'])
@login_required
def cambiar_rol():
    """Cambiar el rol de un usuario"""
    if current_user.rol != 'administrador':
        return jsonify({'success': False, 'message': 'No tienes permisos para cambiar roles'})
    
    usuario_id = request.form.get('usuario_id')
    nuevo_rol = request.form.get('nuevo_rol')
    
    if not usuario_id or not nuevo_rol:
        return jsonify({'success': False, 'message': 'Datos incompletos'})
    
    # Importar roles válidos
    from roles_construccion import ROLES_CONSTRUCCION
    if nuevo_rol not in ROLES_CONSTRUCCION.keys():
        return jsonify({'success': False, 'message': 'Rol no válido'})
    
    # No permitir cambiar el rol del usuario actual
    if int(usuario_id) == current_user.id:
        return jsonify({'success': False, 'message': 'No puedes cambiar tu propio rol'})
    
    try:
        usuario = Usuario.query.get_or_404(usuario_id)
        usuario.rol = nuevo_rol
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'Rol cambiado a {nuevo_rol} exitosamente'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Error al cambiar el rol'})

@auth_bp.route('/usuarios/toggle_usuario', methods=['POST'])
@login_required
def toggle_usuario():
    """Activar/desactivar un usuario"""
    if current_user.rol != 'administrador':
        return jsonify({'success': False, 'message': 'No tienes permisos para gestionar usuarios'})
    
    usuario_id = request.form.get('usuario_id')
    nuevo_estado = request.form.get('nuevo_estado')
    
    if not usuario_id or nuevo_estado is None:
        return jsonify({'success': False, 'message': 'Datos incompletos'})
    
    # No permitir desactivar el usuario actual
    if int(usuario_id) == current_user.id:
        return jsonify({'success': False, 'message': 'No puedes desactivar tu propia cuenta'})
    
    try:
        usuario = Usuario.query.get_or_404(usuario_id)
        usuario.activo = nuevo_estado.lower() == 'true'
        db.session.commit()
        
        estado_texto = 'activado' if usuario.activo else 'desactivado'
        return jsonify({'success': True, 'message': f'Usuario {estado_texto} exitosamente'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Error al cambiar el estado del usuario'})

# ================================
# SISTEMA DE INVITACIONES
# ================================

@auth_bp.route('/unirse')
def unirse_organizacion():
    """Procesar invitación a organización"""
    token = request.args.get('token')
    
    if not token:
        flash('Token de invitación inválido.', 'danger')
        return redirect(url_for('auth.login'))
    
    # Buscar organización por token
    organizacion = Organizacion.query.filter_by(token_invitacion=token).first()
    if not organizacion:
        flash('Token de invitación inválido o expirado.', 'danger')
        return redirect(url_for('auth.login'))
    
    # Guardar token en sesión para usar después del login
    session['token_invitacion'] = token
    session['organizacion_invitacion'] = organizacion.id
    
    flash(f'Te han invitado a unirte a "{organizacion.nombre}". Inicia sesión para continuar.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/invitar', methods=['GET', 'POST'])
@login_required
def invitar_usuario():
    """Invitar usuarios a la organización"""
    if current_user.rol != 'administrador':
        flash('No tienes permisos para invitar usuarios.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        rol = request.form.get('rol', 'operario')
        
        if not email:
            flash('Por favor, ingresa un email válido.', 'danger')
            return render_template('auth/invitar.html')
        
        # Verificar si el email ya existe
        usuario_existente = Usuario.query.filter_by(email=email.lower()).first()
        if usuario_existente:
            flash('Este email ya está registrado en el sistema.', 'danger')
            return render_template('auth/invitar.html')
        
        # Crear usuario pendiente (inactivo hasta que acepte la invitación)
        try:
            nuevo_usuario = Usuario(
                nombre='Usuario',
                apellido='Invitado',
                email=email.lower(),
                auth_provider='manual',
                rol=rol,
                activo=False,  # Inactivo hasta que acepte
                organizacion_id=current_user.organizacion_id,
                password_hash=None  # Se establecerá cuando acepte la invitación
            )
            
            db.session.add(nuevo_usuario)
            db.session.commit()
            
            # Generar link de invitación
            link_invitacion = url_for('auth.unirse_organizacion', token=current_user.organizacion.token_invitacion, _external=True)
            
            flash(f'Invitación enviada a {email}. Comparte este link: {link_invitacion}', 'success')
            return redirect(url_for('auth.usuarios_admin'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error al enviar la invitación. Intenta de nuevo.', 'danger')
    
    return render_template('auth/invitar.html')

@auth_bp.route('/aceptar_invitacion', methods=['GET', 'POST'])
def aceptar_invitacion():
    """Aceptar invitación y completar registro"""
    token = session.get('token_invitacion')
    organizacion_id = session.get('organizacion_invitacion')
    
    if not token or not organizacion_id:
        flash('Sesión de invitación inválida.', 'danger')
        return redirect(url_for('auth.login'))
    
    organizacion = Organizacion.query.get(organizacion_id)
    if not organizacion:
        flash('Organización no encontrada.', 'danger')
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not all([nombre, apellido, email, password]):
            flash('Por favor, completa todos los campos.', 'danger')
            return render_template('auth/aceptar_invitacion.html', organizacion=organizacion)
        
        # Verificar si el usuario ya existe y está pendiente
        usuario = Usuario.query.filter_by(email=email.lower(), organizacion_id=organizacion_id).first()
        
        if usuario and not usuario.activo:
            # Activar usuario existente
            usuario.nombre = nombre
            usuario.apellido = apellido
            usuario.set_password(password)
            usuario.activo = True
            
            db.session.commit()
            
            # Limpiar sesión
            session.pop('token_invitacion', None)
            session.pop('organizacion_invitacion', None)
            
            login_user(usuario)
            flash(f'¡Bienvenido/a a {organizacion.nombre}!', 'success')
            return redirect(url_for('reportes.dashboard'))
        else:
            flash('Error al procesar la invitación.', 'danger')
    
    return render_template('auth/aceptar_invitacion.html', organizacion=organizacion)
def _deliver_reset_link(usuario: Usuario, reset_url: str) -> None:
    """Envía o registra el enlace de reseteo usando el canal configurado."""
    delivery_mode = current_app.config.get('PASSWORD_RESET_DELIVERY', 'email')

    if current_app.debug or current_app.config.get('ENV') == 'development':
        print(f"🔐 Enlace de restablecimiento para {usuario.email}: {reset_url}")
        return

    if delivery_mode == 'email':
        current_app.logger.info('Enlace de restablecimiento generado para %s: %s', usuario.email, reset_url)
    else:
        current_app.logger.info(
            'Password reset link for %s via %s pending integration: %s',
            usuario.email,
            delivery_mode,
            reset_url,
        )
