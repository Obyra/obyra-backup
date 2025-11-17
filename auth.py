from flask import Blueprint, render_template, request, flash, redirect, url_for, session, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from extensions import db, limiter
from app import _login_redirect
from models import Usuario, Organizacion, PerfilUsuario, OnboardingStatus, SupplierUser, OrgMembership
from sqlalchemy import func
from datetime import datetime
from typing import Dict, Optional, Tuple, Union, Any
import os
import re
import uuid
import secrets
import string
from werkzeug.routing import BuildError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from services.email_service import send_email
from services.memberships import (
    initialize_membership_session,
    get_current_org_id,
    get_current_membership,
    require_membership,
    set_current_membership,
    activate_pending_memberships,
    ensure_active_membership_for_user,
)
from utils.security_logger import (
    log_login_attempt,
    log_logout,
    log_password_change,
    log_data_modification,
    log_permission_change,
)

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
ResettableAccount = Union[Usuario, SupplierUser]

def _normalize_portal(portal: Optional[str]) -> str:
    if not portal:
        return 'user'
    portal_value = portal.lower()
    if portal_value in {'supplier', 'proveedor', 'supplier_portal'}:
        return 'supplier'
    return 'user'

def _portal_login_endpoint(portal: str) -> str:
    return 'supplier_auth.login' if portal == 'supplier' else 'auth.login'

def _portal_label_for_account(account: ResettableAccount) -> str:
    return 'supplier' if isinstance(account, SupplierUser) else 'user'

def _extract_portal_from_payload(payload: Optional[Any]) -> str:
    if isinstance(payload, dict):
        return _normalize_portal(payload.get('portal'))
    return 'user'

def _forgot_url_for_portal(portal: str) -> str:
    return url_for('auth.forgot_password', portal=portal) if portal == 'supplier' else url_for('auth.forgot_password')

def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}

# Solo configurar Google OAuth si las variables están disponibles Y NO VACÍAS
google_client_id = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '').strip()
google_client_secret = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '').strip()

if google_client_id and google_client_secret:
    google = oauth.register(
        name='google',
        client_id=google_client_id,
        client_secret=google_client_secret,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )
else:
    if _env_flag('ENABLE_GOOGLE_OAUTH_HELP', False):
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
        return False, {'message': 'Por favor, completa todos los campos.', 'category': 'danger'}

    usuario = Usuario.query.filter(func.lower(Usuario.email) == normalized_email.lower()).first()

    if not usuario or not usuario.activo:
        log_login_attempt(normalized_email, False, 'Usuario no existe o inactivo')
        return False, {'message': 'Email o contraseña incorrectos, o cuenta inactiva.', 'category': 'danger'}

    if usuario.auth_provider == 'google':
        log_login_attempt(normalized_email, False, 'Cuenta vinculada con Google')
        return False, {'message': 'Esta cuenta está vinculada con Google. Usa "Iniciar sesión con Google".', 'category': 'warning'}

    if usuario.auth_provider != 'manual' or not usuario.password_hash:
        log_login_attempt(normalized_email, False, 'Credenciales incorrectas')
        return False, {'message': 'Credenciales incorrectas.', 'category': 'danger'}

    if not usuario.check_password(password):
        log_login_attempt(normalized_email, False, 'Contrasena incorrecta')
        return False, {'message': 'Credenciales incorrectas.', 'category': 'danger'}

    login_user(usuario, remember=remember)
    log_login_attempt(normalized_email, True)
    current_app.logger.info(f'Login exitoso: {normalized_email} desde {request.remote_addr}')
    return True, usuario

def _resolve_dashboard_url() -> str:
    """Obtiene la URL más adecuada para enviar al usuario autenticado."""
    for endpoint in ('reportes.dashboard', 'obras.lista', 'supplier_portal.dashboard', 'index'):
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

def _generate_reset_token(account: ResettableAccount, portal: str) -> str:
    serializer = _get_reset_serializer()
    payload = {
        'account_id': account.id,
        'email': account.email,
        'account_type': _portal_label_for_account(account),
        'portal': _normalize_portal(portal),
    }
    # legacy para compatibilidad
    payload['user_id'] = payload['account_id']
    return serializer.dumps(payload, salt=PASSWORD_RESET_SALT)

def _load_reset_token(token: str, max_age: int = 3600) -> Tuple[ResettableAccount, str]:
    serializer = _get_reset_serializer()
    try:
        data = serializer.loads(token, salt=PASSWORD_RESET_SALT, max_age=max_age)
    except SignatureExpired as exc:
        payload = getattr(exc, 'payload', None)
        new_exc = SignatureExpired('El enlace para restablecer la contraseña ha expirado.')
        setattr(new_exc, 'payload', payload)
        raise new_exc from exc
    except BadSignature as exc:
        payload = getattr(exc, 'payload', None)
        new_exc = BadSignature('El enlace de restablecimiento no es válido.')
        setattr(new_exc, 'payload', payload)
        raise new_exc from exc

    account_id = data.get('account_id') or data.get('user_id')
    email = data.get('email')
    account_type = data.get('account_type', 'user')
    portal = _normalize_portal(data.get('portal'))

    if not account_id or not email:
        raise BadSignature('Token de restablecimiento incompleto.')

    account: Optional[ResettableAccount]
    if account_type == 'supplier':
        account = SupplierUser.query.get(account_id)
    else:
        account = Usuario.query.get(account_id)

    if not account or account.email.lower() != email.lower():
        raise BadSignature('El token no coincide con ninguna cuenta válida.')

    return account, portal

def generate_temporary_password(length: int = 12) -> str:
    """Genera una contraseña aleatoria segura para nuevos integrantes."""
    length = max(length, 8)
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def send_new_member_invitation(
    usuario: Usuario,
    membership: Optional[OrgMembership],
    temp_password: Optional[str] = None,
) -> Optional[str]:
    """Envía (o registra) el correo de bienvenida con enlace de activación."""
    try:
        token = _generate_reset_token(usuario, 'user')
        reset_url = url_for('auth.reset_password', token=token, _external=True)
    except Exception:
        current_app.logger.exception('No se pudo generar el enlace de activación para %s', usuario.email)
        reset_url = None

    html_content = render_template(
        'emails/nuevo_integrante.html',
        usuario=usuario,
        membership=membership,
        temp_password=temp_password,
        reset_url=reset_url,
    )

    email_sent = False
    try:
        email_sent = send_email(usuario.email, 'Tu acceso a OBYRA IA', html_content)
    except Exception:
        current_app.logger.exception('Fallo al enviar el email de bienvenida a %s', usuario.email)
        email_sent = False

    if not email_sent:
        if temp_password:
            current_app.logger.info(
                'Credenciales temporales generadas para %s | contraseña: %s | enlace: %s',
                usuario.email, temp_password, reset_url or 'N/D',
            )
        else:
            current_app.logger.info('Invitación registrada para %s | enlace: %s', usuario.email, reset_url or 'N/D')
    else:
        current_app.logger.info('Email de bienvenida enviado a %s', usuario.email)

    return reset_url

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    next_page = request.args.get('next') or request.form.get('next')
    form_data = {'email': request.form.get('email', ''), 'remember': bool(request.form.get('remember'))}

    if request.method == 'POST':
        success, payload = authenticate_manual_user(
            form_data['email'],
            request.form.get('password', ''),
            remember=form_data['remember'],
        )

        if success:
            usuario = payload
            membership_redirect = initialize_membership_session(usuario)
            if membership_redirect:
                return redirect(membership_redirect)
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

    return render_template('auth/login.html', google_available=bool(google), form_data=form_data, next_value=next_page)

@auth_bp.route('/organizaciones/seleccionar', methods=['GET', 'POST'])
@login_required
def seleccionar_organizacion():
    memberships = (
        OrgMembership.query
        .filter(
            OrgMembership.user_id == current_user.id,
            db.or_(OrgMembership.archived.is_(False), OrgMembership.archived.is_(None)),
        )
        .order_by(OrgMembership.accepted_at.desc().nullslast(), OrgMembership.invited_at.desc())
        .all()
    )

    if not memberships:
        fallback = ensure_active_membership_for_user(current_user)
        if fallback:
            memberships = [fallback]
        else:
            flash('Tu cuenta no tiene organizaciones asociadas. Solicita una invitación.', 'danger')
            return redirect(url_for('auth.logout'))

    next_url = request.args.get('next') or request.form.get('next') or url_for('reportes.dashboard')

    if request.method == 'POST':
        membership_id = request.form.get('membership_id')
        try:
            membership_id_int = int(membership_id)
        except (TypeError, ValueError):
            flash('Selecciona una organización válida.', 'danger')
            return redirect(url_for('auth.seleccionar_organizacion', next=next_url))

        if not set_current_membership(membership_id_int):
            flash('No tienes acceso activo a esa organización.', 'danger')
            return redirect(url_for('auth.seleccionar_organizacion', next=next_url))

        flash('Organización seleccionada correctamente.', 'success')
        return redirect(next_url)

    return render_template('auth/seleccionar_organizacion.html', memberships=memberships, next_url=next_url)

@auth_bp.route('/forgot', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def forgot_password():
    portal = _normalize_portal(request.args.get('portal') or request.form.get('portal'))
    submit_url = url_for('auth.forgot_password', portal=portal) if portal != 'user' else url_for('auth.forgot_password')
    back_url = url_for(_portal_login_endpoint(portal))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()

        if not email:
            flash('Por favor, ingresa tu email para continuar.', 'warning')
            return render_template('auth/forgot.html', portal=portal, submit_url=submit_url, back_url=back_url)

        account: Optional[ResettableAccount] = None
        if portal == 'supplier':
            account = SupplierUser.query.filter(func.lower(SupplierUser.email) == email).first()
            if account and not account.activo:
                account = None
        else:
            account = Usuario.query.filter(func.lower(Usuario.email) == email).first()
            if account and (account.auth_provider not in (None, 'manual') or not account.activo):
                account = None

        if account:
            token = _generate_reset_token(account, portal)
            reset_kwargs = {'token': token, '_external': True}
            if portal != 'user':
                reset_kwargs['portal'] = portal
            reset_url = url_for('auth.reset_password', **reset_kwargs)
            _deliver_reset_link(account, reset_url, portal)

        flash('Si el email corresponde a una cuenta activa, te enviamos las instrucciones para restablecer la contraseña.', 'info')
        return redirect(submit_url)

    return render_template('auth/forgot.html', portal=portal, submit_url=submit_url, back_url=back_url)

@auth_bp.route('/reset/<token>', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def reset_password(token: str):
    requested_portal = _normalize_portal(request.args.get('portal') or request.form.get('portal'))

    try:
        account, token_portal = _load_reset_token(token)
        portal = token_portal or requested_portal
    except SignatureExpired as exc:
        portal = _extract_portal_from_payload(getattr(exc, 'payload', None)) or requested_portal
        flash('El enlace ha expirado. Por favor, solicita uno nuevo.', 'warning')
        return redirect(_forgot_url_for_portal(portal))
    except BadSignature as exc:
        portal = _extract_portal_from_payload(getattr(exc, 'payload', None)) or requested_portal
        flash('El enlace no es válido. Solicita uno nuevo para continuar.', 'danger')
        return redirect(_forgot_url_for_portal(portal))

    def render_form() -> Any:
        submit_kwargs = {'token': token}
        if portal != 'user':
            submit_kwargs['portal'] = portal
        submit_url = url_for('auth.reset_password', **submit_kwargs)
        back_url = url_for(_portal_login_endpoint(portal))
        return render_template('auth/reset.html', token=token, portal=portal, submit_url=submit_url, back_url=back_url)

    if request.method == 'POST':
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm_password') or ''

        if not password or not confirm:
            flash('Debes ingresar y confirmar tu nueva contraseña.', 'warning')
            return render_form()
        if password != confirm:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_form()
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_form()

        account.set_password(password)
        if isinstance(account, Usuario):
            account.auth_provider = 'manual'
            activate_pending_memberships(account)
        db.session.commit()

        log_password_change(account.email, is_reset=True)
        current_app.logger.info(f'Contrasena restablecida para: {account.email}')

        flash('Tu contraseña fue actualizada. Ahora puedes iniciar sesión.', 'success')
        return redirect(url_for(_portal_login_endpoint(portal)))

    return render_form()

@auth_bp.route('/logout')
@login_required
def logout():
    user_email = current_user.email
    logout_user()
    log_logout(user_email)
    current_app.logger.info(f'Logout: {user_email}')
    session.pop('current_membership_id', None)
    session.pop('current_org_id', None)
    session.pop('membership_selection_confirmed', None)
    flash('Sesión cerrada exitosamente.', 'info')
    return redirect(url_for('index'))

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per minute", methods=["POST"])
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
            role_front = 'admin'
            nuevo_usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email.lower(),
                telefono=telefono,
                rol=rol_usuario,
                role=role_front,
                auth_provider='manual',
                activo=True,
                organizacion_id=nueva_organizacion.id,
                primary_org_id=nueva_organizacion.id,
            )
            nuevo_usuario.set_password(password)

            db.session.add(nuevo_usuario)
            db.session.flush()

            nuevo_usuario.ensure_membership(
                nueva_organizacion.id,
                role=role_front,
                status='active',
            )

            perfil_usuario = PerfilUsuario(
                usuario_id=nuevo_usuario.id,
                cuit=cuit_normalizado,
                direccion=direccion
            )
            db.session.add(perfil_usuario)

            onboarding_status = OnboardingStatus(usuario=nuevo_usuario)
            db.session.add(onboarding_status)

            db.session.commit()

            login_user(nuevo_usuario)
            log_login_attempt(email.lower(), True)
            current_app.logger.info(f'Nuevo usuario registrado: {email.lower()} - Organizacion: {nueva_organizacion.id}')
            flash(f'¡Bienvenido/a {nombre}! Tu cuenta ha sido creada exitosamente.', 'success')
            destino = _post_login_destination(nuevo_usuario)
            return redirect(destino)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error al crear cuenta para {email.lower()}: {str(e)}', exc_info=True)
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
        return _login_redirect()
    redirect_uri = url_for('auth.google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@auth_bp.route('/login/google/callback')
def google_callback():
    """Callback de Google OAuth"""
    if not google:
        flash('Google OAuth no está configurado.', 'danger')
        return _login_redirect()
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            flash('Error al obtener información de Google.', 'danger')
            return _login_redirect()
        
        email = user_info.get('email')
        nombre = user_info.get('given_name', '')
        apellido = user_info.get('family_name', '')
        google_id = user_info.get('sub')
        profile_picture = user_info.get('picture', '')
        if not email:
            flash('No se pudo obtener el email de Google.', 'danger')
            return _login_redirect()
        
        usuario = Usuario.query.filter_by(email=email.lower()).first()
        if usuario:
            if usuario.auth_provider == 'manual':
                usuario.auth_provider = 'google'
                usuario.google_id = google_id
                if nombre: usuario.nombre = nombre
                if apellido: usuario.apellido = apellido
                if profile_picture: usuario.profile_picture = profile_picture
            elif usuario.auth_provider == 'google':
                usuario.google_id = google_id
                if nombre: usuario.nombre = nombre
                if apellido: usuario.apellido = apellido
                if profile_picture: usuario.profile_picture = profile_picture
            
            if usuario.activo:
                db.session.commit()
                login_user(usuario)
                log_login_attempt(email, True)
                current_app.logger.info(f'Login exitoso con Google: {email}')
                flash(f'¡Bienvenido/a de vuelta, {usuario.nombre}!', 'success')
                destino = _post_login_destination(usuario)
                return redirect(destino)
            else:
                log_login_attempt(email, False, 'Cuenta inactiva')
                flash('Tu cuenta está inactiva. Contacta al administrador.', 'warning')
                return _login_redirect()
        else:
            usuario_existente = Usuario.query.filter_by(email=email.lower()).first()
            if usuario_existente:
                flash('⚠️ Este correo ya está registrado. Debés ser invitado por un administrador de tu organización para acceder.', 'warning')
                return _login_redirect()
            
            try:
                token_invitacion = session.get('token_invitacion')
                organizacion_id = session.get('organizacion_invitacion')
                role_front = 'operario'

                if token_invitacion and organizacion_id:
                    organizacion = Organizacion.query.get(organizacion_id)
                    if organizacion and organizacion.token_invitacion == token_invitacion:
                        nuevo_usuario = Usuario(
                            nombre=nombre or 'Usuario',
                            apellido=apellido or 'Google',
                            email=email.lower(),
                            auth_provider='google',
                            google_id=google_id,
                            profile_picture=profile_picture,
                            rol='operario',
                            role=role_front,
                            activo=True,
                            password_hash=None,
                            organizacion_id=organizacion_id,
                            primary_org_id=organizacion_id,
                        )
                        session.pop('token_invitacion', None)
                        session.pop('organizacion_invitacion', None)
                        mensaje = f'¡Bienvenido/a a {organizacion.nombre}, {nombre}!'
                    else:
                        flash('Token de invitación inválido.', 'danger')
                        return _login_redirect()
                else:
                    # Super admin debe configurarse manualmente en la base de datos por seguridad
                    # No se asigna automáticamente durante el registro
                    rol_usuario = 'administrador'
                    role_front = 'admin'
                    is_super = False  # Super admin flag must be set manually in database
                    nueva_organizacion = Organizacion(
                        nombre=f"Organización de {nombre} {apellido}",
                        fecha_creacion=datetime.utcnow()
                    )
                    db.session.add(nueva_organizacion)
                    db.session.flush()
                    nuevo_usuario = Usuario(
                        nombre=nombre or 'Usuario',
                        apellido=apellido or 'Google',
                        email=email.lower(),
                        auth_provider='google',
                        google_id=google_id,
                        profile_picture=profile_picture,
                        rol=rol_usuario,
                        role=role_front,
                        is_super_admin=is_super,
                        activo=True,
                        password_hash=None,
                        organizacion_id=nueva_organizacion.id,
                        primary_org_id=nueva_organizacion.id,
                    )
                    mensaje = f'¡Bienvenido/a a OBYRA IA, {nombre}! Tu organización ha sido creada.'

                db.session.add(nuevo_usuario)
                db.session.flush()

                target_org_id = nuevo_usuario.organizacion_id or nuevo_usuario.primary_org_id
                if target_org_id:
                    nuevo_usuario.ensure_membership(
                        target_org_id,
                        role=nuevo_usuario.role or role_front,
                        status='active',
                    )

                db.session.add(OnboardingStatus(usuario=nuevo_usuario))
                db.session.commit()

                login_user(nuevo_usuario)
                flash(mensaje, 'success')
                destino = _post_login_destination(nuevo_usuario)
                return redirect(destino)
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f'Error al crear cuenta con Google para {email}: {str(e)}', exc_info=True)
                flash('Error al crear la cuenta con Google. Intenta de nuevo.', 'danger')
                return _login_redirect()
    except Exception as e:
        current_app.logger.error(f'Error en autenticación OAuth con Google: {str(e)}', exc_info=True)
        flash('Error en la autenticación con Google. Intenta de nuevo.', 'danger')
        return _login_redirect()

# ================================
# RUTAS ADMINISTRATIVAS
# ================================
@auth_bp.route('/admin/register', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per minute", methods=["POST"])
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
        
        if not all([nombre, apellido, email, rol, password]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            from roles_construccion import obtener_roles_por_categoria
            return render_template('auth/admin_register.html', roles_por_categoria=obtener_roles_por_categoria())
        
        from roles_construccion import ROLES_CONSTRUCCION
        if rol not in ROLES_CONSTRUCCION.keys():
            flash('Rol no válido.', 'danger')
            from roles_construccion import obtener_roles_por_categoria
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
                role='admin' if rol in ('administrador', 'admin') else 'operario',
                auth_provider='manual',
                activo=True,
                organizacion_id=current_user.organizacion_id,
                primary_org_id=current_user.primary_org_id or current_user.organizacion_id,
            )
            nuevo_usuario.set_password(password)

            db.session.add(nuevo_usuario)
            db.session.flush()

            target_org = get_current_membership()
            if target_org:
                nuevo_usuario.ensure_membership(
                    target_org.org_id,
                    role='admin' if rol in ('administrador', 'admin') else 'operario',
                    status='active',
                )

            db.session.commit()
            flash(f'Usuario {nombre} {apellido} registrado exitosamente.', 'success')
            return redirect(url_for('auth.usuarios_admin'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error al registrar usuario admin: {str(e)}', exc_info=True)
            flash('Error al registrar el usuario. Intenta nuevamente.', 'danger')
    
    from roles_construccion import obtener_roles_por_categoria
    return render_template('auth/admin_register.html', roles_por_categoria=obtener_roles_por_categoria())

@auth_bp.route('/usuarios')
@login_required
def usuarios_admin():
    """Panel de administración de usuarios - solo para administradores"""
    membership = get_current_membership()
    if not membership or membership.role != 'admin':
        flash('No tienes permisos para acceder a la gestión de usuarios.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    rol_filtro = request.args.get('rol', '')
    auth_provider_filtro = request.args.get('auth_provider', '')
    buscar = request.args.get('buscar', '')

    query = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == membership.org_id,
            db.or_(OrgMembership.archived.is_(False), OrgMembership.archived.is_(None)),
        )
        .join(Usuario, OrgMembership.usuario)
    )

    if rol_filtro:
        query = query.filter(OrgMembership.role == rol_filtro)
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

    miembros = query.order_by(Usuario.apellido, Usuario.nombre).all()

    total_usuarios = len(miembros)
    usuarios_activos = sum(1 for miembro in miembros if miembro.status == 'active' and miembro.usuario.activo)
    admins_count = sum(1 for miembro in miembros if miembro.role == 'admin')
    usuarios_google = sum(1 for miembro in miembros if miembro.usuario.auth_provider == 'google')

    return render_template(
        'auth/usuarios_admin.html',
        miembros=miembros,
        total_usuarios=total_usuarios,
        usuarios_activos=usuarios_activos,
        admins_count=admins_count,
        usuarios_google=usuarios_google,
        rol_filtro=rol_filtro,
        auth_provider_filtro=auth_provider_filtro,
        buscar=buscar,
    )

@auth_bp.route('/usuarios/integrantes', methods=['POST'])
@login_required
@require_membership('admin')
@limiter.limit("20 per minute")
def crear_integrante_desde_panel():
    """Invita o crea un integrante dentro de la organización activa."""
    payload = request.get_json(silent=True) or request.form

    nombre = (payload.get('nombre') or '').strip()
    apellido = (payload.get('apellido') or '').strip()
    cuit_raw = (payload.get('cuit') or '').strip()
    direccion = (payload.get('direccion') or '').strip()
    telefono = (payload.get('telefono') or '').strip()
    email = (payload.get('email') or '').strip().lower()
    rol_solicitado = (payload.get('rol') or 'operario').strip().lower()

    if not all([nombre, apellido, cuit_raw, telefono, email]):
        return jsonify({'success': False, 'message': 'Por favor, completa todos los campos obligatorios.'}), 400

    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return jsonify({'success': False, 'message': 'El email ingresado no es válido.'}), 400

    cuit_normalizado = normalizar_cuit(cuit_raw)
    if not validar_cuit(cuit_normalizado):
        return jsonify({'success': False, 'message': 'El CUIT/CUIL ingresado no es válido.'}), 400

    rol_map = {
        'administrador': ('administrador', 'admin'),
        'admin': ('administrador', 'admin'),
        'operario': ('operario', 'operario'),
    }
    if rol_solicitado not in rol_map:
        return jsonify({'success': False, 'message': 'El rol seleccionado no es válido.'}), 400

    rol_interno, role_front = rol_map[rol_solicitado]
    telefono_sanitizado = re.sub(r'[^0-9+\s-]', '', telefono)
    if not telefono_sanitizado.strip():
        return jsonify({'success': False, 'message': 'El teléfono ingresado no es válido.'}), 400

    membership = get_current_membership()
    if not membership:
        return jsonify({'success': False, 'message': 'No se pudo determinar la organización activa.'}), 400

    organizacion = membership.organizacion
    org_id = organizacion.id if organizacion else current_user.organizacion_id
    if not org_id:
        return jsonify({'success': False, 'message': 'La organización actual no es válida.'}), 400

    email_existente = Usuario.query.filter(func.lower(Usuario.email) == email).first()
    temp_password: Optional[str] = None

    try:
        if email_existente:
            usuario_objetivo = email_existente
            membership_existente = OrgMembership.query.filter_by(org_id=org_id, user_id=usuario_objetivo.id).first()
            if membership_existente and not membership_existente.archived:
                estado = membership_existente.status
                return jsonify({'success': False, 'message': f'Este usuario ya pertenece a la organización con estado "{estado}".'}), 409

            if membership_existente and membership_existente.archived:
                membership_existente.archived = False
                membership_existente.status = 'pending'
                membership_existente.invited_by = current_user.id
                membership_existente.invited_at = datetime.utcnow()
                membership_nuevo = membership_existente
            else:
                membership_nuevo = OrgMembership(
                    org_id=org_id,
                    user_id=usuario_objetivo.id,
                    role=role_front,
                    status='pending',
                    invited_by=current_user.id,
                )
                db.session.add(membership_nuevo)

            perfil = usuario_objetivo.perfil
            if perfil and perfil.cuit and perfil.cuit != cuit_normalizado:
                return jsonify({'success': False, 'message': 'El CUIT/CUIL ya está asociado a otro usuario.'}), 409

            if not perfil:
                perfil = PerfilUsuario(usuario_id=usuario_objetivo.id)
                db.session.add(perfil)

            perfil.cuit = perfil.cuit or cuit_normalizado
            if direccion:
                perfil.direccion = direccion

            usuario_objetivo.nombre = usuario_objetivo.nombre or nombre
            usuario_objetivo.apellido = usuario_objetivo.apellido or apellido
            usuario_objetivo.telefono = telefono_sanitizado
            usuario_objetivo.rol = rol_interno
            usuario_objetivo.role = role_front
            usuario_objetivo.activo = True
            if not usuario_objetivo.organizacion_id:
                usuario_objetivo.organizacion_id = org_id
            if not getattr(usuario_objetivo, 'primary_org_id', None):
                usuario_objetivo.primary_org_id = org_id

            if not usuario_objetivo.password_hash:
                temp_password = generate_temporary_password()
                usuario_objetivo.set_password(temp_password)

            usuario_objetivo.ensure_onboarding_status()
        else:
            if PerfilUsuario.query.filter_by(cuit=cuit_normalizado).first():
                return jsonify({'success': False, 'message': 'El CUIT/CUIL ya está asociado a otro usuario.'}), 409

            temp_password = generate_temporary_password()
            usuario_objetivo = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email,
                telefono=telefono_sanitizado,
                rol=rol_interno,
                role=role_front,
                auth_provider='manual',
                activo=True,
                organizacion_id=org_id,
                primary_org_id=org_id,
            )
            usuario_objetivo.set_password(temp_password)
            db.session.add(usuario_objetivo)
            db.session.flush()

            perfil = PerfilUsuario(
                usuario_id=usuario_objetivo.id,
                cuit=cuit_normalizado,
                direccion=direccion or 'Sin especificar',
            )
            db.session.add(perfil)

            membership_nuevo = OrgMembership(
                org_id=org_id,
                user_id=usuario_objetivo.id,
                role=role_front,
                status='pending',
                invited_by=current_user.id,
            )
            db.session.add(membership_nuevo)

            usuario_objetivo.ensure_onboarding_status()

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error al crear/invitar integrante {email}: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'message': 'No se pudo crear el integrante. Intenta nuevamente.'}), 500

    send_new_member_invitation(usuario_objetivo, membership_nuevo, temp_password)
    flash('Invitación enviada correctamente.', 'success')

    return jsonify({'success': True, 'redirect_url': url_for('auth.usuarios_admin')})

@auth_bp.route('/usuarios/cambiar_rol', methods=['POST'])
@login_required
@require_membership('admin')
@limiter.limit("30 per minute")
def cambiar_rol():
    """Cambiar el rol de un usuario dentro de la organización actual."""
    usuario_id = request.form.get('usuario_id')
    nuevo_rol = request.form.get('nuevo_rol')

    if not usuario_id or not nuevo_rol:
        return jsonify({'success': False, 'message': 'Datos incompletos'})

    try:
        usuario_id_int = int(usuario_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Identificador inválido'})

    if usuario_id_int == current_user.id:
        return jsonify({'success': False, 'message': 'No puedes cambiar tu propio rol'})

    rol_map = {'administrador': 'admin', 'admin': 'admin', 'operario': 'operario'}
    if nuevo_rol not in rol_map:
        return jsonify({'success': False, 'message': 'Rol no válido'})

    membership = get_current_membership()
    objetivo = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == membership.org_id,
            OrgMembership.user_id == usuario_id_int,
            db.or_(OrgMembership.archived.is_(False), OrgMembership.archived.is_(None)),
        )
        .first()
    )
    if not objetivo:
        return jsonify({'success': False, 'message': 'El usuario no pertenece a esta organización.'}), 404

    try:
        old_role = objetivo.role
        objetivo.role = rol_map[nuevo_rol]
        objetivo.usuario.rol = nuevo_rol
        objetivo.usuario.role = rol_map[nuevo_rol]
        db.session.commit()

        log_permission_change(objetivo.usuario.email, old_role, rol_map[nuevo_rol], current_user.email)
        current_app.logger.info(f'Cambio de rol: {objetivo.usuario.email} {old_role} -> {rol_map[nuevo_rol]} por {current_user.email}')

        return jsonify({'success': True, 'message': 'Rol actualizado correctamente.'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error al cambiar rol de usuario {usuario_id}: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'message': 'Error al cambiar el rol'})

@auth_bp.route('/usuarios/toggle_usuario', methods=['POST'])
@login_required
@require_membership('admin')
@limiter.limit("30 per minute")
def toggle_usuario():
    """Activar o desactivar un integrante dentro de la organización actual."""
    usuario_id = request.form.get('usuario_id')
    nuevo_estado = request.form.get('nuevo_estado')

    if not usuario_id or nuevo_estado is None:
        return jsonify({'success': False, 'message': 'Datos incompletos'})

    try:
        usuario_id_int = int(usuario_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Identificador inválido'})

    if usuario_id_int == current_user.id:
        return jsonify({'success': False, 'message': 'No puedes desactivar tu propia cuenta'})

    membership = get_current_membership()
    objetivo = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == membership.org_id,
            OrgMembership.user_id == usuario_id_int,
            db.or_(OrgMembership.archived.is_(False), OrgMembership.archived.is_(None)),
        )
        .first()
    )
    if not objetivo:
        return jsonify({'success': False, 'message': 'El usuario no pertenece a esta organización.'}), 404

    activar = str(nuevo_estado).lower() == 'true'

    try:
        objetivo.status = 'active' if activar else 'inactive'
        objetivo.usuario.activo = activar
        db.session.commit()

        estado_texto = 'activado' if activar else 'desactivado'
        log_data_modification('Usuario', usuario_id_int, estado_texto.capitalize(), current_user.email)
        current_app.logger.info(f'Usuario {estado_texto}: {objetivo.usuario.email} por {current_user.email}')

        return jsonify({
            'success': True,
            'message': f'Usuario {estado_texto} exitosamente',
            'status': objetivo.status,
            'usuario_activo': activar,
            'usuario_id': usuario_id_int,
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error al toggle estado de usuario {usuario_id}: {str(e)}', exc_info=True)
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
        return _login_redirect()
    organizacion = Organizacion.query.filter_by(token_invitacion=token).first()
    if not organizacion:
        flash('Token de invitación inválido o expirado.', 'danger')
        return _login_redirect()
    session['token_invitacion'] = token
    session['organizacion_invitacion'] = organizacion.id
    flash(f'Te han invitado a unirte a "{organizacion.nombre}". Inicia sesión para continuar.', 'info')
    return _login_redirect()

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
        
        usuario_existente = Usuario.query.filter_by(email=email.lower()).first()
        if usuario_existente:
            flash('Este email ya está registrado en el sistema.', 'danger')
            return render_template('auth/invitar.html')
        
        try:
            nuevo_usuario = Usuario(
                nombre='Usuario',
                apellido='Invitado',
                email=email.lower(),
                auth_provider='manual',
                rol=rol,
                activo=False,
                organizacion_id=current_user.organizacion_id,
                password_hash=None
            )
            db.session.add(nuevo_usuario)
            db.session.commit()
            link_invitacion = url_for('auth.unirse_organizacion', token=current_user.organizacion.token_invitacion, _external=True)
            flash(f'Invitación enviada a {email}. Comparte este link: {link_invitacion}', 'success')
            return redirect(url_for('auth.usuarios_admin'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error al invitar usuario {email}: {str(e)}', exc_info=True)
            flash('Error al enviar la invitación. Intenta de nuevo.', 'danger')
    
    return render_template('auth/invitar.html')

@auth_bp.route('/aceptar_invitacion', methods=['GET', 'POST'])
def aceptar_invitacion():
    """Aceptar invitación y completar registro"""
    token = session.get('token_invitacion')
    organizacion_id = session.get('organizacion_invitacion')
    if not token or not organizacion_id:
        flash('Sesión de invitación inválida.', 'danger')
        return _login_redirect()
    
    organizacion = Organizacion.query.get(organizacion_id)
    if not organizacion:
        flash('Organización no encontrada.', 'danger')
        return _login_redirect()
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        email = request.form.get('email')
        password = request.form.get('password')
        if not all([nombre, apellido, email, password]):
            flash('Por favor, completa todos los campos.', 'danger')
            return render_template('auth/aceptar_invitacion.html', organizacion=organizacion)
        
        usuario = Usuario.query.filter_by(email=email.lower(), organizacion_id=organizacion_id).first()
        if usuario and not usuario.activo:
            usuario.nombre = nombre
            usuario.apellido = apellido
            usuario.set_password(password)
            usuario.activo = True
            db.session.commit()
            session.pop('token_invitacion', None)
            session.pop('organizacion_invitacion', None)
            login_user(usuario)
            flash(f'¡Bienvenido/a a {organizacion.nombre}!', 'success')
            return redirect(url_for('reportes.dashboard'))
        else:
            flash('Error al procesar la invitación.', 'danger')
    
    return render_template('auth/aceptar_invitacion.html', organizacion=organizacion)

def _deliver_reset_link(account: ResettableAccount, reset_url: str, portal: str) -> None:
    """Envía o registra el enlace de reseteo usando el canal configurado."""
    delivery_mode = current_app.config.get('PASSWORD_RESET_DELIVERY', 'email')
    portal = _normalize_portal(portal)
    email = getattr(account, 'email', 'cuenta')

    if current_app.debug or current_app.config.get('ENV') == 'development':
        print(f"🔐 Enlace de restablecimiento ({portal}) para {email}: {reset_url}")
        return

    if delivery_mode == 'email':
        current_app.logger.info('Enlace de restablecimiento generado para %s (%s): %s', email, portal, reset_url)
    else:
        current_app.logger.info('Password reset link for %s via %s pending integration: %s', email, delivery_mode, reset_url)


@auth_bp.route('/crear-operario-rapido', methods=['POST'])
@login_required
def crear_operario_rapido():
    """
    Endpoint para crear rápidamente un operario/responsable desde el wizard de tareas.
    Solo crea el usuario con rol 'operario' en la organización actual.
    """
    try:
        from models.core import Usuario, OrgMembership
        from extensions import db
        import secrets

        nombre_completo = request.form.get('nombre_completo', '').strip()
        email = request.form.get('email', '').strip()
        telefono = request.form.get('telefono', '').strip()

        if not nombre_completo:
            return jsonify({'ok': False, 'error': 'El nombre completo es requerido'}), 400

        org_id = current_user.organizacion_id
        if not org_id:
            return jsonify({'ok': False, 'error': 'No tienes una organización activa'}), 400

        # Generar email temporal si no se proporcionó
        if not email:
            # Usar timestamp y random para email único
            import time
            timestamp = int(time.time())
            random_str = secrets.token_hex(4)
            email = f"operario_{timestamp}_{random_str}@temp.obyra.local"

        # Verificar si el email ya existe
        existing_user = Usuario.query.filter_by(email=email).first()
        if existing_user:
            # Si el usuario ya existe y está en la misma organización, retornar error
            membership = OrgMembership.query.filter_by(
                user_id=existing_user.id,
                org_id=org_id
            ).first()
            if membership:
                return jsonify({
                    'ok': False,
                    'error': f'Ya existe un usuario con el email {email} en esta organización'
                }), 400

        # Separar nombre completo en nombre y apellido
        partes_nombre = nombre_completo.strip().split(maxsplit=1)
        nombre = partes_nombre[0] if partes_nombre else 'Operario'
        apellido = partes_nombre[1] if len(partes_nombre) > 1 else ''

        # Crear nuevo usuario
        password_temporal = secrets.token_urlsafe(12)
        nuevo_usuario = Usuario(
            email=email,
            nombre=nombre,
            apellido=apellido,
            telefono=telefono or None,
            rol='operario',
            role='operario',
            organizacion_id=org_id,
            primary_org_id=org_id
        )
        nuevo_usuario.set_password(password_temporal)
        db.session.add(nuevo_usuario)
        db.session.flush()

        # Asignar a la organización usando OrgMembership
        membership = OrgMembership(
            user_id=nuevo_usuario.id,
            org_id=org_id,
            role='operario',
            status='active'
        )
        db.session.add(membership)
        db.session.commit()

        current_app.logger.info(f"Operario creado rápidamente: {nombre_completo} (ID: {nuevo_usuario.id}) por usuario {current_user.email}")

        return jsonify({
            'ok': True,
            'usuario_id': nuevo_usuario.id,
            'nombre_completo': nuevo_usuario.nombre_completo,
            'email': nuevo_usuario.email
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creando operario rápido: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500

