"""
OBYRA IA - Configuración principal de Google OAuth
Archivo de configuración para autenticación con Google usando Authlib
"""

import os
from flask import Flask, request, redirect, url_for, session, flash
from flask_login import login_user, current_user
from authlib.integrations.flask_client import OAuth
from app import app, db
from models import Usuario
from datetime import datetime

# Configuración OAuth
oauth = OAuth(app)

# Configurar Google OAuth si las credenciales están disponibles
google = None
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
    print("✅ Google OAuth configurado correctamente")
else:
    print("""
🔧 Google OAuth no configurado. Para habilitarlo:

1. Ve a Google Cloud Console: https://console.cloud.google.com/apis/credentials
2. Crea un nuevo proyecto o selecciona uno existente
3. Habilita la API de Google+ o Google Identity
4. Crea credenciales OAuth 2.0 Client ID:
   - Tipo de aplicación: Aplicación web
   - URIs de redireccionamiento autorizados:
     • https://tu-dominio.replit.app/auth/google
     • https://tu-dominio.replit.app/login/google/callback

5. Configura las variables de entorno en Replit:
   - GOOGLE_OAUTH_CLIENT_ID=tu_client_id
   - GOOGLE_OAUTH_CLIENT_SECRET=tu_client_secret

6. Reinicia la aplicación

Documentación completa: https://docs.replit.com/additional-resources/google-auth-in-flask
    """)

@app.route('/login/google')
def google_login():
    """Iniciar proceso de login con Google"""
    if current_user.is_authenticated:
        return redirect(url_for('asistente.dashboard'))
    
    if not google:
        flash('Google OAuth no está configurado. Contacta al administrador del sistema.', 'warning')
        return redirect(url_for('auth.login'))
    
    # URL de callback para el proceso OAuth
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google')
def google_callback():
    """Procesar callback de Google OAuth y autenticar usuario"""
    if not google:
        flash('Google OAuth no está configurado.', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Obtener token de acceso de Google
        token = google.authorize_access_token()
        
        # Extraer información del usuario
        user_info = token.get('userinfo')
        
        if not user_info:
            flash('No se pudo obtener información del usuario de Google.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Extraer datos necesarios
        google_id = user_info.get('sub')
        email = user_info.get('email')
        nombre = user_info.get('given_name', '')
        apellido = user_info.get('family_name', '')
        profile_picture = user_info.get('picture', '')
        
        if not email or not google_id:
            flash('Email o ID de Google no disponible.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Buscar usuario existente por email o google_id
        usuario = Usuario.query.filter(
            (Usuario.email == email) | (Usuario.google_id == google_id)
        ).first()
        
        if usuario:
            # Usuario existente - actualizar información de Google si es necesario
            if not usuario.google_id:
                usuario.google_id = google_id
                usuario.auth_provider = 'google'
            
            if not usuario.profile_picture and profile_picture:
                usuario.profile_picture = profile_picture
                
            # Actualizar nombre si no existe
            if not usuario.nombre and nombre:
                usuario.nombre = nombre
            if not usuario.apellido and apellido:
                usuario.apellido = apellido
                
        else:
            # Crear nuevo usuario
            usuario = Usuario(
                email=email,
                nombre=nombre or 'Usuario',
                apellido=apellido or 'Google',
                google_id=google_id,
                auth_provider='google',
                profile_picture=profile_picture,
                rol='operario',  # Rol por defecto para usuarios de Google
                activo=True,
                created_at=datetime.utcnow(),
                fecha_creacion=datetime.utcnow()
            )
            db.session.add(usuario)
        
        # Guardar cambios en la base de datos
        db.session.commit()
        
        # Verificar que el usuario esté activo
        if not usuario.activo:
            flash('Tu cuenta está desactivada. Contacta al administrador.', 'warning')
            return redirect(url_for('auth.login'))
        
        # Realizar login del usuario
        login_user(usuario, remember=True)
        
        # Mensaje de bienvenida personalizado
        if usuario.created_at and (datetime.utcnow() - usuario.created_at).seconds < 60:
            flash(f'¡Bienvenido/a a OBYRA IA, {usuario.nombre}! Tu cuenta ha sido creada exitosamente.', 'success')
        else:
            flash(f'¡Bienvenido/a de vuelta, {usuario.nombre}!', 'success')
        
        # Redirigir al dashboard
        return redirect(url_for('asistente.dashboard'))
        
    except Exception as e:
        # Log del error para debugging
        print(f"Error en Google OAuth: {str(e)}")
        db.session.rollback()
        flash('Error durante el proceso de autenticación con Google. Intenta de nuevo.', 'danger')
        return redirect(url_for('auth.login'))

def init_google_oauth():
    """Función para inicializar Google OAuth si es necesario"""
    return google is not None

# Función auxiliar para verificar estado de Google OAuth
def is_google_oauth_configured():
    """Verifica si Google OAuth está configurado correctamente"""
    return bool(
        os.environ.get('GOOGLE_OAUTH_CLIENT_ID') and 
        os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET') and 
        google
    )

if __name__ == '__main__':
    with app.app_context():
        # Verificar configuración al iniciar
        if is_google_oauth_configured():
            print("🚀 OBYRA IA iniciado con Google OAuth habilitado")
        else:
            print("🚀 OBYRA IA iniciado - Google OAuth pendiente de configuración")