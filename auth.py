from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db
from models import Usuario

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Por favor, completa todos los campos.', 'danger')
            return render_template('auth/login.html')
        
        usuario = Usuario.query.filter_by(email=email).first()
        
        if usuario and usuario.activo and check_password_hash(usuario.password_hash, password):
            login_user(usuario, remember=request.form.get('remember'))
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('reportes.dashboard'))
        else:
            flash('Email o contraseña incorrectos, o cuenta inactiva.', 'danger')
    
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada exitosamente.', 'info')
    return redirect(url_for('index'))

@auth_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    # Solo administradores pueden registrar nuevos usuarios
    if current_user.rol != 'administrador':
        flash('No tienes permisos para registrar usuarios.', 'danger')
        return redirect(url_for('reportes.dashboard'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        apellido = request.form.get('apellido')
        email = request.form.get('email')
        telefono = request.form.get('telefono')
        rol = request.form.get('rol')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validaciones
        if not all([nombre, apellido, email, rol, password]):
            flash('Por favor, completa todos los campos obligatorios.', 'danger')
            return render_template('auth/register.html')
        
        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('auth/register.html')
        
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('auth/register.html')
        
        if rol not in ['administrador', 'tecnico', 'operario']:
            flash('Rol no válido.', 'danger')
            return render_template('auth/register.html')
        
        # Verificar que el email no exista
        if Usuario.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese email.', 'danger')
            return render_template('auth/register.html')
        
        # Crear usuario
        nuevo_usuario = Usuario(
            nombre=nombre,
            apellido=apellido,
            email=email,
            telefono=telefono,
            rol=rol,
            activo=True
        )
        nuevo_usuario.password_hash = generate_password_hash(password)
        
        try:
            db.session.add(nuevo_usuario)
            db.session.commit()
            flash(f'Usuario {nombre} {apellido} registrado exitosamente.', 'success')
            return redirect(url_for('equipos.lista'))
        except Exception as e:
            db.session.rollback()
            flash('Error al registrar el usuario. Intenta nuevamente.', 'danger')
    
    return render_template('auth/register.html')

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
