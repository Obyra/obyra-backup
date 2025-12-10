"""
Blueprint de Clientes - Gestión de clientes
"""
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app)
from flask_login import login_required, current_user
from datetime import datetime
from extensions import db, csrf
from models import Cliente
from services.memberships import get_current_org_id
from sqlalchemy import or_

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes')


@clientes_bp.route('/')
@login_required
def lista():
    """Lista de clientes"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        # Búsqueda
        buscar = request.args.get('buscar', '').strip()
        activo = request.args.get('activo', '')

        # Query base
        query = Cliente.query.filter_by(organizacion_id=org_id)

        # Filtro de búsqueda
        if buscar:
            query = query.filter(
                or_(
                    Cliente.nombre.ilike(f'%{buscar}%'),
                    Cliente.apellido.ilike(f'%{buscar}%'),
                    Cliente.email.ilike(f'%{buscar}%'),
                    Cliente.numero_documento.ilike(f'%{buscar}%'),
                    Cliente.empresa.ilike(f'%{buscar}%')
                )
            )

        # Filtro de activo/inactivo
        if activo == 'true':
            query = query.filter_by(activo=True)
        elif activo == 'false':
            query = query.filter_by(activo=False)

        # Ordenar
        query = query.order_by(Cliente.apellido, Cliente.nombre)

        # Paginación
        page = request.args.get('page', 1, type=int)
        per_page = 20
        clientes = query.paginate(page=page, per_page=per_page, error_out=False)

        return render_template('clientes/lista.html',
                             clientes=clientes.items,
                             pagination=clientes,
                             buscar=buscar,
                             activo=activo)

    except Exception as e:
        current_app.logger.error(f"Error en clientes.lista: {e}", exc_info=True)
        flash('Error al cargar la lista de clientes', 'danger')
        return redirect(url_for('index'))


@clientes_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    """Crear nuevo cliente"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        if request.method == 'POST':
            # Importar validadores
            from utils.validators import validate_email, validate_string_length, validate_phone, sanitize_string

            # Obtener datos del formulario
            empresa = request.form.get('empresa', '').strip()
            tipo_documento = request.form.get('tipo_documento', 'CUIT').strip()
            numero_documento = request.form.get('numero_documento', '').strip()
            email = request.form.get('email', '').strip()
            telefono = request.form.get('telefono', '').strip()
            telefono_alternativo = request.form.get('telefono_alternativo', '').strip()
            direccion = request.form.get('direccion', '').strip()
            ciudad = request.form.get('ciudad', '').strip()
            provincia = request.form.get('provincia', '').strip()
            codigo_postal = request.form.get('codigo_postal', '').strip()
            notas = request.form.get('notas', '').strip()

            # Procesar contactos/empleados
            contactos_nombres = request.form.getlist('contacto_nombre[]')
            contactos_apellidos = request.form.getlist('contacto_apellido[]')
            contactos_emails = request.form.getlist('contacto_email[]')
            contactos_telefonos = request.form.getlist('contacto_telefono[]')
            contactos_roles = request.form.getlist('contacto_rol[]')

            contactos = []
            for i in range(len(contactos_nombres)):
                # Solo agregar si al menos hay nombre o apellido
                if contactos_nombres[i].strip() or contactos_apellidos[i].strip():
                    contacto = {
                        'nombre': contactos_nombres[i].strip() if i < len(contactos_nombres) else '',
                        'apellido': contactos_apellidos[i].strip() if i < len(contactos_apellidos) else '',
                        'email': contactos_emails[i].strip() if i < len(contactos_emails) else '',
                        'telefono': contactos_telefonos[i].strip() if i < len(contactos_telefonos) else '',
                        'rol': contactos_roles[i].strip() if i < len(contactos_roles) else ''
                    }
                    contactos.append(contacto)

            # Para mantener compatibilidad, usar primer contacto como datos principales si existen
            nombre = contactos[0]['nombre'] if contactos and contactos[0]['nombre'] else empresa
            apellido = contactos[0]['apellido'] if contactos and contactos[0]['apellido'] else ''

            # Validaciones mejoradas
            valid, error = validate_string_length(empresa, "Razón Social / Nombre de la Empresa", min_length=2, max_length=150)
            if not valid:
                flash(error, 'danger')
                return redirect(url_for('clientes.crear'))

            valid, error = validate_string_length(numero_documento, "Número de documento", min_length=5, max_length=20)
            if not valid:
                flash(error, 'danger')
                return redirect(url_for('clientes.crear'))

            # Validar email de la empresa si está presente
            if email:
                valid, error = validate_email(email)
                if not valid:
                    flash(error, 'danger')
                    return redirect(url_for('clientes.crear'))

            # Validar teléfonos si están presentes
            if telefono:
                valid, error = validate_phone(telefono)
                if not valid:
                    flash(f"Teléfono: {error}", 'danger')
                    return redirect(url_for('clientes.crear'))

            if telefono_alternativo:
                valid, error = validate_phone(telefono_alternativo)
                if not valid:
                    flash(f"Teléfono alternativo: {error}", 'danger')
                    return redirect(url_for('clientes.crear'))

            # Sanitizar strings para prevenir problemas
            nombre = sanitize_string(nombre, 100)
            apellido = sanitize_string(apellido, 100)
            direccion = sanitize_string(direccion, 255)
            ciudad = sanitize_string(ciudad, 100)
            provincia = sanitize_string(provincia, 100)

            # Verificar si ya existe un cliente con ese documento
            existing = Cliente.query.filter_by(
                organizacion_id=org_id,
                numero_documento=numero_documento
            ).first()

            if existing:
                flash(f'Ya existe un cliente con el documento {numero_documento}', 'warning')
                return redirect(url_for('clientes.crear'))

            # Crear cliente
            cliente = Cliente(
                organizacion_id=org_id,
                nombre=nombre,
                apellido=apellido,
                tipo_documento=tipo_documento,
                numero_documento=numero_documento,
                email=email or None,
                telefono=telefono or None,
                telefono_alternativo=telefono_alternativo or None,
                direccion=direccion or None,
                ciudad=ciudad or None,
                provincia=provincia or None,
                codigo_postal=codigo_postal or None,
                empresa=empresa,
                contactos=contactos if contactos else None,
                notas=notas or None
            )

            db.session.add(cliente)
            db.session.commit()

            flash(f'Cliente {cliente.nombre_completo} creado exitosamente', 'success')

            # Redirigir con parámetro success para comunicación con ventana padre
            return render_template('clientes/crear.html',
                                 cliente_creado=cliente,
                                 success=True)

        return render_template('clientes/crear.html')

    except Exception as e:
        current_app.logger.error(f"Error en clientes.crear: {e}", exc_info=True)
        db.session.rollback()
        flash('Error al crear el cliente', 'danger')
        return redirect(url_for('clientes.lista'))


@clientes_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar(id):
    """Editar cliente existente"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        cliente = Cliente.query.get_or_404(id)

        # Verificar que el cliente pertenece a la organización
        if cliente.organizacion_id != org_id:
            flash('No tienes permisos para editar este cliente', 'danger')
            return redirect(url_for('clientes.lista'))

        if request.method == 'POST':
            # Actualizar datos
            cliente.nombre = request.form.get('nombre', '').strip()
            cliente.apellido = request.form.get('apellido', '').strip()
            cliente.tipo_documento = request.form.get('tipo_documento', 'DNI').strip()
            cliente.numero_documento = request.form.get('numero_documento', '').strip()
            cliente.email = request.form.get('email', '').strip()
            cliente.telefono = request.form.get('telefono', '').strip() or None
            cliente.telefono_alternativo = request.form.get('telefono_alternativo', '').strip() or None
            cliente.direccion = request.form.get('direccion', '').strip() or None
            cliente.ciudad = request.form.get('ciudad', '').strip() or None
            cliente.provincia = request.form.get('provincia', '').strip() or None
            cliente.codigo_postal = request.form.get('codigo_postal', '').strip() or None
            cliente.empresa = request.form.get('empresa', '').strip() or None
            cliente.notas = request.form.get('notas', '').strip() or None
            cliente.activo = request.form.get('activo') == 'on'

            # Validaciones
            if not cliente.nombre or not cliente.apellido:
                flash('El nombre y apellido son requeridos', 'danger')
                return render_template('clientes/editar.html', cliente=cliente)

            if not cliente.email:
                flash('El email es requerido', 'danger')
                return render_template('clientes/editar.html', cliente=cliente)

            if not cliente.numero_documento:
                flash('El número de documento es requerido', 'danger')
                return render_template('clientes/editar.html', cliente=cliente)

            cliente.fecha_modificacion = datetime.utcnow()
            db.session.commit()

            flash(f'Cliente {cliente.nombre_completo} actualizado exitosamente', 'success')
            return redirect(url_for('clientes.lista'))

        return render_template('clientes/editar.html', cliente=cliente)

    except Exception as e:
        current_app.logger.error(f"Error en clientes.editar: {e}", exc_info=True)
        db.session.rollback()
        flash('Error al editar el cliente', 'danger')
        return redirect(url_for('clientes.lista'))


@clientes_bp.route('/<int:id>/eliminar', methods=['POST'])
@csrf.exempt
@login_required
def eliminar(id):
    """Eliminar (desactivar) cliente"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        cliente = Cliente.query.get_or_404(id)

        # Verificar permisos
        if cliente.organizacion_id != org_id:
            return jsonify({'error': 'No autorizado'}), 403

        # Verificar si tiene presupuestos u obras asociadas
        tiene_presupuestos = cliente.presupuestos.count() > 0
        tiene_obras = cliente.obras.count() > 0

        if tiene_presupuestos or tiene_obras:
            # No eliminar, solo desactivar
            cliente.activo = False
            db.session.commit()
            razon = []
            if tiene_presupuestos:
                razon.append('presupuestos')
            if tiene_obras:
                razon.append('obras')
            return jsonify({'mensaje': f'Cliente {cliente.nombre_completo} desactivado (tiene {" y ".join(razon)} asociados)'})
        else:
            # Eliminar completamente
            nombre = cliente.nombre_completo
            db.session.delete(cliente)
            db.session.commit()
            return jsonify({'mensaje': f'Cliente {nombre} eliminado correctamente'})

    except Exception as e:
        current_app.logger.error(f"Error en clientes.eliminar: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': f'Error al eliminar el cliente: {str(e)}'}), 500


@clientes_bp.route('/<int:id>/cambiar-estado', methods=['POST'])
@csrf.exempt
@login_required
def cambiar_estado(id):
    """Cambiar estado activo/inactivo del cliente"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        cliente = Cliente.query.get_or_404(id)

        # Verificar permisos
        if cliente.organizacion_id != org_id:
            return jsonify({'error': 'No autorizado'}), 403

        # Obtener el nuevo estado del body JSON o form
        data = request.get_json() if request.is_json else {}
        nuevo_estado = data.get('activo')

        if nuevo_estado is None:
            # Toggle si no se especifica
            cliente.activo = not cliente.activo
        else:
            cliente.activo = bool(nuevo_estado)

        cliente.fecha_modificacion = datetime.utcnow()
        db.session.commit()

        estado_texto = 'activado' if cliente.activo else 'desactivado'
        return jsonify({
            'ok': True,
            'mensaje': f'Cliente {cliente.nombre_completo} {estado_texto}',
            'activo': cliente.activo
        })

    except Exception as e:
        current_app.logger.error(f"Error en clientes.cambiar_estado: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': f'Error al cambiar estado: {str(e)}'}), 500


@clientes_bp.route('/api/listar')
@login_required
def api_listar():
    """API para listar todos los clientes activos (para dropdown en presupuestos)"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        # Listar todos los clientes activos
        clientes = Cliente.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).order_by(Cliente.empresa, Cliente.apellido, Cliente.nombre).all()

        return jsonify([{
            'id': c.id,
            'nombre_completo': c.nombre_completo,
            'email': c.email,
            'telefono': c.telefono,
            'documento': c.documento_formateado,
            'empresa': c.empresa
        } for c in clientes])

    except Exception as e:
        current_app.logger.error(f"Error en clientes.api_listar: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@clientes_bp.route('/api/buscar')
@login_required
def api_buscar():
    """API para buscar clientes (para selector en presupuestos)"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        termino = request.args.get('q', '').strip()

        if len(termino) < 2:
            return jsonify([])

        # Buscar clientes activos
        clientes = Cliente.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).filter(
            or_(
                Cliente.nombre.ilike(f'%{termino}%'),
                Cliente.apellido.ilike(f'%{termino}%'),
                Cliente.email.ilike(f'%{termino}%'),
                Cliente.numero_documento.ilike(f'%{termino}%'),
                Cliente.empresa.ilike(f'%{termino}%')
            )
        ).limit(10).all()

        return jsonify([{
            'id': c.id,
            'nombre_completo': c.nombre_completo,
            'email': c.email,
            'telefono': c.telefono,
            'documento': c.documento_formateado,
            'empresa': c.empresa
        } for c in clientes])

    except Exception as e:
        current_app.logger.error(f"Error en clientes.api_buscar: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
