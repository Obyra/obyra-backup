from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from werkzeug.security import generate_password_hash
from app import db
from models import Supplier, SupplierUser
from datetime import datetime
import re

supplier_auth_bp = Blueprint('supplier_auth', __name__, url_prefix='/proveedor')

def supplier_login_required(f):
    """Decorator para verificar que el usuario proveedor esté logueado"""
    def decorated_function(*args, **kwargs):
        if 'supplier_user_id' not in session:
            flash('Debes iniciar sesión como proveedor para acceder a esta página.', 'warning')
            return redirect(url_for('supplier_auth.login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def get_current_supplier_user():
    """Obtiene el usuario proveedor actual de la sesión"""
    if 'supplier_user_id' not in session:
        return None
    return SupplierUser.query.get(session['supplier_user_id'])

def get_current_supplier():
    """Obtiene el proveedor actual de la sesión"""
    if 'supplier_id' not in session:
        return None
    return Supplier.query.get(session['supplier_id'])

@supplier_auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    """Registro de nuevo proveedor"""
    if request.method == 'POST':
        # Datos del proveedor
        razon_social = request.form.get('razon_social', '').strip()
        cuit = request.form.get('cuit', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        direccion = request.form.get('direccion', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        ubicacion = request.form.get('ubicacion', '').strip()
        
        # Datos del usuario
        nombre_usuario = request.form.get('nombre_usuario', '').strip()
        email_usuario = request.form.get('email_usuario', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        
        # Validaciones
        errors = []
        
        if not razon_social:
            errors.append('La razón social es obligatoria.')
        
        if not cuit or not validar_cuit(cuit):
            errors.append('El CUIT debe tener un formato válido (XX-XXXXXXXX-X).')
        
        if not email or not validar_email(email):
            errors.append('El email de la empresa debe ser válido.')
        
        if not nombre_usuario:
            errors.append('El nombre del usuario es obligatorio.')
        
        if not email_usuario or not validar_email(email_usuario):
            errors.append('El email del usuario debe ser válido.')
        
        if not password or len(password) < 6:
            errors.append('La contraseña debe tener al menos 6 caracteres.')
        
        if password != password_confirm:
            errors.append('Las contraseñas no coinciden.')
        
        # Verificar duplicados
        if Supplier.query.filter_by(cuit=cuit).first():
            errors.append('Ya existe un proveedor registrado con ese CUIT.')
        
        if Supplier.query.filter_by(email=email).first():
            errors.append('Ya existe un proveedor registrado con ese email.')
        
        if SupplierUser.query.filter_by(email=email_usuario).first():
            errors.append('Ya existe un usuario registrado con ese email.')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('supplier_auth/registro.html')
        
        try:
            # Crear proveedor
            supplier = Supplier(
                razon_social=razon_social,
                cuit=cuit,
                email=email,
                phone=phone,
                direccion=direccion,
                descripcion=descripcion,
                ubicacion=ubicacion
            )
            db.session.add(supplier)
            db.session.flush()  # Para obtener el ID
            
            # Crear usuario owner
            supplier_user = SupplierUser(
                supplier_id=supplier.id,
                nombre=nombre_usuario,
                email=email_usuario,
                rol='owner'
            )
            supplier_user.set_password(password)
            db.session.add(supplier_user)
            
            db.session.commit()
            
            flash('Registro exitoso. Tu cuenta está pendiente de verificación.', 'success')
            return redirect(url_for('supplier_auth.login'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error al crear la cuenta. Por favor, intenta nuevamente.', 'danger')
            return render_template('supplier_auth/registro.html')
    
    return render_template('supplier_auth/registro.html')

@supplier_auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login de proveedor"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Email y contraseña son obligatorios.', 'danger')
            return render_template('supplier_auth/login.html')
        
        # Buscar usuario
        supplier_user = SupplierUser.query.filter_by(email=email, activo=True).first()
        
        if not supplier_user or not supplier_user.check_password(password):
            flash('Email o contraseña incorrectos.', 'danger')
            return render_template('supplier_auth/login.html')
        
        # Verificar que el proveedor esté activo
        if supplier_user.supplier.estado == 'suspendido':
            flash('Tu cuenta de proveedor está suspendida. Contacta al administrador.', 'warning')
            return render_template('supplier_auth/login.html')
        
        # Crear sesión
        session['supplier_user_id'] = supplier_user.id
        session['supplier_id'] = supplier_user.supplier_id
        
        # Actualizar último login
        supplier_user.last_login = datetime.utcnow()
        db.session.commit()
        
        flash(f'Bienvenido, {supplier_user.nombre}!', 'success')
        
        # Redirigir a donde venía o al dashboard
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('supplier_portal.dashboard'))
    
    return render_template('supplier_auth/login.html')

@supplier_auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logout de proveedor"""
    session.pop('supplier_user_id', None)
    session.pop('supplier_id', None)
    flash('Has cerrado sesión exitosamente.', 'info')
    return redirect(url_for('supplier_auth.login'))

def validar_cuit(cuit):
    """Valida formato básico de CUIT argentino"""
    # Remover guiones y espacios
    cuit = re.sub(r'[^0-9]', '', cuit)
    
    # Debe tener 11 dígitos
    if len(cuit) != 11:
        return False
    
    # Validación básica del dígito verificador
    try:
        base = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
        suma = sum(int(cuit[i]) * base[i] for i in range(10))
        resto = suma % 11
        
        if resto < 2:
            verificador = resto
        else:
            verificador = 11 - resto
        
        return int(cuit[10]) == verificador
    except:
        return False

def validar_email(email):
    """Validación básica de email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None