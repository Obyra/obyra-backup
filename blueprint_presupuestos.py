"""
Blueprint de Presupuestos - Gestión de presupuestos y cotizaciones
"""
from flask import (Blueprint, render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort, send_file)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from extensions import db, csrf
from sqlalchemy import desc, or_
from models import Presupuesto, ItemPresupuesto, Obra, Organizacion, Cliente
from services.memberships import get_current_org_id, get_current_membership
from utils.pagination import Pagination
from utils import safe_int
import io
from weasyprint import HTML
from flask_mail import Message

presupuestos_bp = Blueprint('presupuestos', __name__)


@presupuestos_bp.route('/')
@login_required
def lista():
    """Lista de presupuestos"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        # Filtros
        estado = request.args.get('estado', '')
        vigencia = request.args.get('vigencia', '')
        obra_id = request.args.get('obra_id', type=int)

        # Query base - excluir presupuestos eliminados y presupuestos confirmados como obras
        query = Presupuesto.query.filter_by(organizacion_id=org_id).filter(
            Presupuesto.estado != 'eliminado',
            Presupuesto.confirmado_como_obra != True
        )

        # Aplicar filtros
        if estado:
            query = query.filter_by(estado=estado)

        if vigencia == 'vigentes':
            query = query.filter(
                Presupuesto.estado.in_(['borrador', 'enviado', 'aprobado']),
                Presupuesto.vigente == True
            )
        elif vigencia == 'vencidos':
            query = query.filter(Presupuesto.vigente == False)

        if obra_id:
            query = query.filter_by(obra_id=obra_id)

        # Ordenar por fecha de creación descendente
        query = query.order_by(desc(Presupuesto.fecha))

        # Paginación
        page = request.args.get('page', 1, type=int)
        per_page = 20

        presupuestos = query.paginate(page=page, per_page=per_page, error_out=False)

        # Recalcular totales de todos los presupuestos en la página actual
        for presupuesto in presupuestos.items:
            presupuesto.calcular_totales()
        db.session.commit()

        # Obras disponibles para filtro
        obras = Obra.query.filter_by(organizacion_id=org_id).order_by(Obra.nombre).all()

        return render_template('presupuestos/lista.html',
                             presupuestos=presupuestos.items,
                             pagination=presupuestos,
                             estado=estado,
                             vigencia=vigencia,
                             obra_id=obra_id,
                             obras=obras)
    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.lista: {e}")
        flash('Error al cargar la lista de presupuestos', 'danger')
        return redirect(url_for('index'))


@presupuestos_bp.route('/crear', methods=['GET', 'POST'])
@login_required
def crear():
    """Crear nuevo presupuesto"""
    if current_user.role not in ['admin', 'pm']:
        flash('No tienes permisos para crear presupuestos', 'danger')
        return redirect(url_for('presupuestos.lista'))

    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        if request.method == 'POST':
            # Obtener datos del formulario
            numero = request.form.get('numero', '').strip()
            obra_id = request.form.get('obra_id', type=int)
            cliente_id = request.form.get('cliente_id', type=int)  # ID del cliente seleccionado
            cliente_nombre = request.form.get('cliente_nombre', '').strip()  # Nombre (para retrocompatibilidad)
            vigencia_dias = request.form.get('vigencia_dias', 30, type=int)

            # Validaciones
            if not numero:
                flash('El número de presupuesto es requerido', 'danger')
                return redirect(url_for('presupuestos.crear'))

            # Verificar que el número no esté duplicado
            existing = Presupuesto.query.filter_by(
                organizacion_id=org_id,
                numero=numero
            ).first()

            if existing:
                flash(f'Ya existe un presupuesto con el número {numero}', 'danger')
                return redirect(url_for('presupuestos.crear'))

            # Si se seleccionó un cliente, obtener su nombre de la base de datos
            if cliente_id:
                from models.core import Cliente
                cliente = Cliente.query.filter_by(id=cliente_id, organizacion_id=org_id).first()
                if cliente:
                    cliente_nombre = cliente.nombre

            # Preparar datos del proyecto como JSON
            import json
            datos_proyecto = {
                'nombre_obra': request.form.get('nombre_obra', '').strip(),
                'tipo_obra': request.form.get('tipo_obra', '').strip(),
                'ubicacion': request.form.get('ubicacion', '').strip(),
                'tipo_construccion': request.form.get('tipo_construccion', '').strip(),
                'superficie_m2': request.form.get('superficie_m2', '').strip(),
                'cliente_nombre': cliente_nombre,
            }

            # Procesar datos de IA antes de crear el presupuesto
            ia_payload_str = request.form.get('ia_etapas_payload', '').strip()
            moneda_presupuesto = 'ARS'  # Default

            if ia_payload_str:
                try:
                    ia_payload = json.loads(ia_payload_str)
                    # Obtener la moneda del payload de IA
                    moneda_presupuesto = ia_payload.get('moneda', 'ARS')
                except Exception as e:
                    current_app.logger.error(f"Error parseando payload IA para obtener moneda: {str(e)}")

            # Crear presupuesto con la moneda correcta
            presupuesto = Presupuesto(
                organizacion_id=org_id,
                numero=numero,
                obra_id=obra_id if obra_id else None,
                cliente_id=cliente_id if cliente_id else None,  # Asignar el cliente seleccionado
                fecha=date.today(),
                vigencia_dias=vigencia_dias,
                datos_proyecto=json.dumps(datos_proyecto),
                ubicacion_texto=request.form.get('ubicacion', '').strip(),
                estado='borrador',
                currency=moneda_presupuesto,
                iva_porcentaje=Decimal('21.0'),
                vigencia_bloqueada=True
            )

            db.session.add(presupuesto)
            db.session.flush()  # Get presupuesto.id before commit

            # Procesar items calculados por IA si existen
            if ia_payload_str:
                try:
                    ia_payload = json.loads(ia_payload_str)
                    etapas_ia = ia_payload.get('etapas', [])
                    moneda_ia = ia_payload.get('moneda', 'ARS')

                    for etapa in etapas_ia:
                        items_etapa = etapa.get('items', [])
                        for item in items_etapa:
                            # Obtener precios en la moneda correcta
                            precio_unit = Decimal(str(item.get('precio_unit', 0)))
                            subtotal = Decimal(str(item.get('subtotal', 0)))

                            # Si hay precio en ARS, usarlo, sino usar el precio_unit
                            precio_unit_ars = Decimal(str(item.get('precio_unit_ars', item.get('precio_unit', 0))))
                            total_ars = Decimal(str(item.get('subtotal_ars', item.get('subtotal', 0))))

                            item_presupuesto = ItemPresupuesto(
                                presupuesto_id=presupuesto.id,
                                tipo=item.get('tipo', 'material'),
                                descripcion=item.get('descripcion', ''),
                                unidad=item.get('unidad', 'unidades'),
                                cantidad=Decimal(str(item.get('cantidad', 0))),
                                precio_unitario=precio_unit,
                                total=subtotal,
                                origen='ia',
                                currency=moneda_ia,
                                price_unit_ars=precio_unit_ars,
                                total_ars=total_ars
                            )
                            db.session.add(item_presupuesto)

                    current_app.logger.info(f"Guardados {sum(len(e.get('items', [])) for e in etapas_ia)} items de IA en {moneda_ia} para presupuesto {numero}")
                except Exception as e:
                    current_app.logger.error(f"Error procesando items de IA: {str(e)}")
                    import traceback
                    current_app.logger.error(traceback.format_exc())
                    # No fallar la creación del presupuesto por este error

            db.session.commit()

            flash(f'Presupuesto {numero} creado exitosamente', 'success')
            return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

        # GET - Mostrar formulario
        obras = Obra.query.filter_by(organizacion_id=org_id).order_by(Obra.nombre).all()

        # Generar número de presupuesto sugerido
        fecha_hoy = date.today().strftime('%Y%m%d')

        # Buscar el último presupuesto del día actual
        ultimo_hoy = Presupuesto.query.filter_by(organizacion_id=org_id).filter(
            Presupuesto.numero.like(f'PRES-{fecha_hoy}-%')
        ).order_by(desc(Presupuesto.id)).first()

        if ultimo_hoy and ultimo_hoy.numero:
            # Extraer el número correlativo del formato "PRES-20251105-001"
            try:
                partes = ultimo_hoy.numero.split('-')
                if len(partes) == 3:
                    num = int(partes[2]) + 1
                    numero_sugerido = f"PRES-{fecha_hoy}-{num:03d}"
                else:
                    numero_sugerido = f"PRES-{fecha_hoy}-001"
            except:
                numero_sugerido = f"PRES-{fecha_hoy}-001"
        else:
            numero_sugerido = f"PRES-{fecha_hoy}-001"

        # Obtener lista de clientes activos de la organización
        clientes = Cliente.query.filter_by(
            organizacion_id=org_id,
            activo=True
        ).order_by(Cliente.nombre, Cliente.apellido).all()

        return render_template('presupuestos/crear.html',
                             obras=obras,
                             numero_sugerido=numero_sugerido,
                             clientes=clientes)

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.crear: {e}")
        flash('Error al crear el presupuesto', 'danger')
        return redirect(url_for('presupuestos.lista'))


@presupuestos_bp.route('/<int:id>')
@login_required
def detalle(id):
    """Ver detalle de un presupuesto"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Recalcular totales del presupuesto para asegurar que estén actualizados
        presupuesto.calcular_totales()
        db.session.commit()

        # Obtener items agrupados por tipo y origen
        items = ItemPresupuesto.query.filter_by(presupuesto_id=id).order_by(
            ItemPresupuesto.tipo,
            ItemPresupuesto.id
        ).all()

        # Agrupar por tipo
        items_materiales = [i for i in items if i.tipo == 'material']
        items_mano_obra = [i for i in items if i.tipo == 'mano_obra']
        items_equipos = [i for i in items if i.tipo == 'equipo']

        # Separar items de IA
        ia_materiales = [i for i in items if i.tipo == 'material' and i.origen == 'ia']
        ia_mano_obra = [i for i in items if i.tipo == 'mano_obra' and i.origen == 'ia']
        ia_equipos = [i for i in items if i.tipo == 'equipo' and i.origen == 'ia']
        ia_herramientas = [i for i in items if i.tipo == 'herramienta' and i.origen == 'ia']

        # Calcular totales de IA
        totales_ia = {
            'materiales': sum(i.total for i in ia_materiales),
            'mano_obra': sum(i.total for i in ia_mano_obra),
            'equipos': sum(i.total for i in ia_equipos),
            'herramientas': sum(i.total for i in ia_herramientas),
        }
        totales_ia['general'] = sum(totales_ia.values())

        # Calcular subtotales por categoría
        subtotal_materiales = sum(i.total for i in items_materiales)
        subtotal_mano_obra = sum(i.total for i in items_mano_obra)
        subtotal_equipos = sum(i.total for i in items_equipos)

        # Calcular total general del presupuesto
        subtotal = sum(i.total for i in items)
        iva_monto = subtotal * (presupuesto.iva_porcentaje / Decimal('100'))
        total_con_iva = subtotal + iva_monto

        # Parsear datos_proyecto para obtener información del cliente y obra
        import json
        datos_proyecto = {}
        if presupuesto.datos_proyecto:
            try:
                datos_proyecto = json.loads(presupuesto.datos_proyecto)
            except:
                pass

        # Pasar subtotales como variables separadas al template
        return render_template('presupuestos/detalle.html',
                             presupuesto=presupuesto,
                             materiales=items_materiales,
                             mano_obra=items_mano_obra,
                             equipos=items_equipos,
                             items_materiales=items_materiales,
                             items_mano_obra=items_mano_obra,
                             items_equipos=items_equipos,
                             ia_materiales=ia_materiales,
                             ia_mano_obra=ia_mano_obra,
                             ia_equipos=ia_equipos,
                             ia_herramientas=ia_herramientas,
                             totales_ia=totales_ia,
                             subtotal_materiales=subtotal_materiales,
                             subtotal_mano_obra=subtotal_mano_obra,
                             subtotal_equipos=subtotal_equipos,
                             subtotal=subtotal,
                             iva_monto=iva_monto,
                             total_con_iva=total_con_iva,
                             datos_proyecto=datos_proyecto)

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.detalle: {e}")
        flash('Error al cargar el presupuesto', 'danger')
        return redirect(url_for('presupuestos.lista'))


@presupuestos_bp.route('/<int:id>/pdf')
@login_required
def generar_pdf(id):
    """Generar PDF del presupuesto con WeasyPrint"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        # Obtener presupuesto con eager loading para evitar queries dentro del template
        from sqlalchemy.orm import joinedload
        presupuesto = Presupuesto.query.options(
            joinedload(Presupuesto.cliente)
        ).filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Obtener organización
        organizacion = Organizacion.query.get(org_id)

        # Obtener items ordenados usando sintaxis SQLAlchemy 2.0
        from models.budgets import ItemPresupuesto
        from extensions import db
        items_ordenados = db.session.query(ItemPresupuesto).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id
        ).order_by(ItemPresupuesto.tipo, ItemPresupuesto.id).all()

        try:
            # Renderizar HTML
            html_string = render_template(
                'presupuestos/pdf_template.html',
                presupuesto=presupuesto,
                organizacion=organizacion,
                usuario=current_user,
                now=datetime.now(),
                items=items_ordenados
            )
        except Exception as render_error:
            current_app.logger.error(f"Error al renderizar template PDF: {render_error}", exc_info=True)
            raise Exception(f"Error al renderizar template: {str(render_error)}")

        try:
            # Generar PDF con WeasyPrint (ignorar warnings de fontconfig)
            pdf_buffer = io.BytesIO()
            HTML(string=html_string, base_url=request.url_root).write_pdf(
                pdf_buffer,
                presentational_hints=True
            )
            pdf_buffer.seek(0)
        except Exception as pdf_error:
            current_app.logger.error(f"Error al generar PDF con WeasyPrint: {pdf_error}", exc_info=True)
            raise Exception(f"Error al generar PDF: {str(pdf_error)}")

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'presupuesto_{presupuesto.numero}.pdf'
        )

    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback_str = traceback.format_exc()
        current_app.logger.error(f"Error en presupuestos.generar_pdf: {error_msg}\n{traceback_str}")
        flash(f'Error al generar el PDF: {error_msg}', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/<int:id>/enviar-email', methods=['GET', 'POST'])
@login_required
def enviar_email(id):
    """Enviar presupuesto por email"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        organizacion = Organizacion.query.get(org_id)

        if request.method == 'GET':
            # Mostrar formulario de envío
            email_destino = presupuesto.cliente.email if presupuesto.cliente else ''
            user_name = f"{current_user.nombre} {current_user.apellido}" if current_user.is_authenticated else "nuestro equipo"
            mensaje_default = f"""Estimado/a,

Adjunto encontrará el presupuesto Nº {presupuesto.numero} solicitado.

Este presupuesto tiene una vigencia hasta el {presupuesto.fecha_vigencia.strftime('%d/%m/%Y') if presupuesto.fecha_vigencia else 'consultar'}.

Para cualquier consulta, puede responder directamente este email y su mensaje llegará a {user_name}.

Saludos cordiales,
{organizacion.nombre}"""

            return render_template(
                'presupuestos/enviar_email.html',
                presupuesto=presupuesto,
                email_destino=email_destino,
                mensaje_default=mensaje_default
            )

        # POST: Enviar email
        email_destino = request.form.get('email', '').strip()
        asunto = request.form.get('asunto', f'Presupuesto {presupuesto.numero}').strip()
        mensaje = request.form.get('mensaje', '').strip()

        if not email_destino:
            flash('Debe ingresar un email de destino', 'danger')
            return redirect(url_for('presupuestos.enviar_email', id=id))

        # Verificar que el presupuesto tenga ítems
        if presupuesto.items.count() == 0:
            flash('No se puede enviar un presupuesto sin ítems. Por favor agregue ítems al presupuesto primero.', 'warning')
            return redirect(url_for('presupuestos.detalle', id=id))

        # Obtener items ordenados (igual que en generar_pdf)
        from models.budgets import ItemPresupuesto
        items_ordenados = db.session.query(ItemPresupuesto).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id
        ).order_by(ItemPresupuesto.tipo, ItemPresupuesto.id).all()

        # Generar PDF
        html_string = render_template(
            'presupuestos/pdf_template.html',
            presupuesto=presupuesto,
            organizacion=organizacion,
            usuario=current_user,
            now=datetime.now(),
            items=items_ordenados
        )

        pdf_buffer = io.BytesIO()
        HTML(string=html_string, base_url=request.url_root).write_pdf(
            pdf_buffer,
            presentational_hints=True
        )
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.read()

        # Enviar email usando Flask-Mail si está configurado, sino informar
        try:
            from extensions import mail

            # NOTA: Gmail no permite cambiar el remitente (FROM) cuando se envía a través de su SMTP.
            # Usamos Reply-To para que las respuestas vayan al usuario actual que envía el presupuesto.
            user_email = current_user.email if current_user.is_authenticated else None
            user_name = f"{current_user.nombre} {current_user.apellido}" if current_user.is_authenticated else "OBYRA"

            # El FROM será siempre obyra.servicios@gmail.com (configurado en MAIL_DEFAULT_SENDER)
            # Pero incluimos el nombre del usuario en el display name
            sender_email = f"{user_name} - OBYRA <{current_app.config.get('MAIL_DEFAULT_SENDER')}>"

            # Log para debugging
            current_app.logger.info(f"Intentando enviar email desde {sender_email} hacia {email_destino}")
            if user_email:
                current_app.logger.info(f"Reply-To: {user_email}")
            current_app.logger.info(f"SMTP Config: {current_app.config.get('MAIL_SERVER')}:{current_app.config.get('MAIL_PORT')}")

            msg = Message(
                asunto,
                recipients=[email_destino],
                body=mensaje,
                sender=sender_email
            )

            # Si el usuario tiene email, configurar Reply-To para que las respuestas vayan a él
            if user_email:
                msg.reply_to = f"{user_name} <{user_email}>"
            msg.attach(
                f'presupuesto_{presupuesto.numero}.pdf',
                'application/pdf',
                pdf_bytes
            )

            current_app.logger.info("Enviando email...")
            mail.send(msg)
            current_app.logger.info("Email enviado exitosamente!")

            # Actualizar estado si está en borrador
            if presupuesto.estado == 'borrador':
                presupuesto.estado = 'enviado'
                db.session.commit()

            flash(f'Presupuesto enviado exitosamente a {email_destino}', 'success')
            return redirect(url_for('presupuestos.detalle', id=id))

        except ImportError:
            flash('El sistema de envío de emails no está configurado. Por favor contacte al administrador.', 'warning')
            current_app.logger.warning("Flask-Mail no está configurado")
            return redirect(url_for('presupuestos.detalle', id=id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.enviar_email: {e}", exc_info=True)
        flash('Error al enviar el email', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/<int:id>/confirmar-obra', methods=['POST'])
@login_required
def confirmar_como_obra(id):
    """Confirmar presupuesto y convertirlo en obra"""
    try:
        org_id = get_current_org_id()
        presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

        # Solo administradores pueden confirmar presupuestos
        if not (current_user.role == 'admin' or current_user.es_admin()):
            return jsonify({'error': 'No tiene permisos para confirmar presupuestos'}), 403

        # Verificar que el presupuesto no esté ya confirmado
        if presupuesto.confirmado_como_obra:
            return jsonify({'error': 'Este presupuesto ya fue confirmado como obra'}), 400

        # Verificar que tenga ítems
        if presupuesto.items.count() == 0:
            return jsonify({'error': 'No se puede confirmar un presupuesto sin ítems'}), 400

        # Obtener datos del formulario
        data = request.get_json() or {}
        crear_tareas = data.get('crear_tareas', True)
        normalizar_slugs = data.get('normalizar_slugs', True)

        # Crear la obra desde el presupuesto
        obra = Obra()

        # Datos básicos de la obra
        # Extraer el nombre del JSON datos_proyecto si existe
        nombre_obra = f"Obra {presupuesto.numero}"
        if presupuesto.datos_proyecto:
            try:
                import json
                proyecto_data = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                nombre_obra = proyecto_data.get('nombre_obra') or proyecto_data.get('nombre') or nombre_obra
            except (json.JSONDecodeError, TypeError):
                pass

        obra.nombre = nombre_obra[:200]  # Limitar a 200 caracteres
        obra.organizacion_id = presupuesto.organizacion_id

        # Cliente
        if presupuesto.cliente:
            obra.cliente_id = presupuesto.cliente_id
            obra.cliente = presupuesto.cliente.nombre
            obra.telefono_cliente = presupuesto.cliente.telefono
            obra.email_cliente = presupuesto.cliente.email
        else:
            obra.cliente = "Sin cliente asignado"

        # Ubicación
        obra.direccion = presupuesto.ubicacion_texto
        obra.direccion_normalizada = presupuesto.ubicacion_normalizada
        obra.latitud = presupuesto.geo_latitud
        obra.longitud = presupuesto.geo_longitud
        obra.geocode_place_id = presupuesto.geocode_place_id
        obra.geocode_provider = presupuesto.geocode_provider
        obra.geocode_status = presupuesto.geocode_status
        obra.geocode_raw = presupuesto.geocode_raw
        obra.geocode_actualizado = presupuesto.geocode_actualizado

        # Presupuesto y fechas
        obra.presupuesto_total = presupuesto.total_con_iva
        obra.fecha_inicio = date.today()
        obra.fecha_fin_estimada = presupuesto.fecha_vigencia
        obra.estado = 'planificacion'
        obra.progreso = 0

        db.session.add(obra)
        db.session.flush()  # Para obtener el ID de la obra

        # Marcar el presupuesto como confirmado
        presupuesto.confirmado_como_obra = True
        presupuesto.obra_id = obra.id
        presupuesto.estado = 'aprobado'

        db.session.commit()

        current_app.logger.info(f"Presupuesto {presupuesto.numero} confirmado como obra {obra.id}")

        return jsonify({
            'success': True,
            'message': f'Presupuesto confirmado exitosamente. Obra creada: {obra.nombre}',
            'obra_id': obra.id,
            'obra_url': url_for('obras.detalle', id=obra.id),
            'redirect_url': url_for('obras.detalle', id=obra.id)
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en presupuestos.confirmar_como_obra: {e}", exc_info=True)
        return jsonify({'error': 'Error al confirmar el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/editar-obra', methods=['POST'])
@login_required
def editar_obra(id):
    """Editar información de la obra/proyecto del presupuesto"""
    try:
        org_id = get_current_org_id()
        presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

        # Solo técnicos y administradores pueden editar
        if not (current_user.role in ['admin', 'tecnico'] or current_user.es_admin()):
            return jsonify({'error': 'No tiene permisos para editar presupuestos'}), 403

        # No se puede editar si ya está confirmado como obra
        if presupuesto.confirmado_como_obra:
            return jsonify({'error': 'No se puede editar un presupuesto ya confirmado como obra'}), 400

        data = request.get_json() or {}

        # Obtener datos del proyecto actual
        import json
        if presupuesto.datos_proyecto:
            try:
                proyecto_data = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
            except (json.JSONDecodeError, TypeError):
                proyecto_data = {}
        else:
            proyecto_data = {}

        # Actualizar campos del proyecto
        if 'nombre' in data:
            proyecto_data['nombre_obra'] = data['nombre'].strip()

        if 'cliente' in data:
            proyecto_data['cliente_nombre'] = data['cliente'].strip()

        if 'descripcion' in data:
            proyecto_data['descripcion'] = data['descripcion'].strip()

        # Guardar el JSON actualizado
        presupuesto.datos_proyecto = json.dumps(proyecto_data, ensure_ascii=False)

        db.session.commit()

        current_app.logger.info(f"Información del presupuesto {presupuesto.numero} actualizada")

        return jsonify({
            'exito': True,
            'message': 'Información actualizada correctamente'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en presupuestos.editar_obra: {e}", exc_info=True)
        return jsonify({'error': 'Error al actualizar la información'}), 500


@presupuestos_bp.route('/<int:id>/items/agregar', methods=['POST'])
@login_required
def agregar_item(id):
    """Agregar item a presupuesto"""
    if current_user.role not in ['admin', 'pm']:
        return jsonify({'ok': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'ok': False, 'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        if presupuesto.estado != 'borrador':
            flash('Solo se pueden agregar items a presupuestos en borrador', 'warning')
            return redirect(url_for('presupuestos.detalle', id=id))

        # Obtener datos del formulario
        descripcion = request.form.get('descripcion', '').strip()
        tipo = request.form.get('tipo', 'material')
        cantidad = Decimal(request.form.get('cantidad', '0'))
        unidad = request.form.get('unidad', 'un')
        precio_unitario = Decimal(request.form.get('precio_unitario', '0'))
        currency = request.form.get('currency', presupuesto.currency or 'ARS')

        if not descripcion or cantidad <= 0 or precio_unitario <= 0:
            flash('Datos inválidos para el item', 'danger')
            return redirect(url_for('presupuestos.detalle', id=id))

        # Calcular total
        total = cantidad * precio_unitario

        # Si la moneda es USD, calcular equivalente en ARS (usando tasa si existe)
        price_unit_ars = precio_unitario
        total_ars = total

        if currency == 'USD' and presupuesto.tasa_usd_venta:
            price_unit_ars = precio_unitario * presupuesto.tasa_usd_venta
            total_ars = total * presupuesto.tasa_usd_venta

        # Crear item
        item = ItemPresupuesto(
            presupuesto_id=id,
            descripcion=descripcion,
            tipo=tipo,
            cantidad=cantidad,
            unidad=unidad,
            precio_unitario=precio_unitario,
            total=total,
            currency=currency,
            price_unit_ars=price_unit_ars,
            total_ars=total_ars,
            origen='manual'
        )

        db.session.add(item)

        # Actualizar totales del presupuesto
        presupuesto.calcular_totales()
        db.session.commit()

        flash('Item agregado exitosamente', 'success')
        return redirect(url_for('presupuestos.detalle', id=id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.agregar_item: {e}")
        db.session.rollback()
        flash('Error al agregar el item', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/item/<int:id>/editar', methods=['POST'])
@login_required
@csrf.exempt
def editar_item(id):
    """Editar item de presupuesto"""
    if current_user.rol not in ['administrador', 'tecnico']:
        return jsonify({'exito': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'exito': False, 'error': 'Sin organización activa'}), 400

        item = ItemPresupuesto.query.get_or_404(id)
        presupuesto = item.presupuesto

        if presupuesto.organizacion_id != org_id:
            return jsonify({'exito': False, 'error': 'No autorizado'}), 403

        if presupuesto.estado != 'borrador':
            return jsonify({'exito': False, 'error': 'Solo se pueden editar items de presupuestos en borrador'}), 400

        # Obtener datos del JSON
        data = request.get_json()

        # Actualizar campos básicos
        if 'descripcion' in data:
            item.descripcion = data['descripcion']
        if 'unidad' in data:
            item.unidad = data['unidad']
        if 'cantidad' in data:
            item.cantidad = Decimal(str(data['cantidad']))
        if 'precio_unitario' in data:
            item.precio_unitario = Decimal(str(data['precio_unitario']))
        if 'currency' in data:
            item.currency = data['currency']

        # Recalcular total
        item.total = item.cantidad * item.precio_unitario

        # Calcular equivalente en ARS según la moneda
        if item.currency == 'USD' and presupuesto.tasa_usd_venta:
            item.price_unit_ars = item.precio_unitario * presupuesto.tasa_usd_venta
            item.total_ars = item.total * presupuesto.tasa_usd_venta
        else:
            # Si es ARS, copiar los valores directamente
            item.price_unit_ars = item.precio_unitario
            item.total_ars = item.total

        # Actualizar totales del presupuesto
        presupuesto.calcular_totales()
        db.session.commit()

        # Devolver totales actualizados
        return jsonify({
            'exito': True,
            'nuevo_total': float(item.total),
            'price_unit_ars': float(item.price_unit_ars) if item.price_unit_ars else None,
            'total_ars': float(item.total_ars) if item.total_ars else None,
            'currency': item.currency,
            'subtotal_materiales': float(presupuesto.subtotal_materiales),
            'subtotal_mano_obra': float(presupuesto.subtotal_mano_obra),
            'subtotal_equipos': float(presupuesto.subtotal_equipos),
            'total_sin_iva': float(presupuesto.total_sin_iva),
            'iva_monto': float(presupuesto.total_con_iva - presupuesto.total_sin_iva),
            'total_con_iva': float(presupuesto.total_con_iva)
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.editar_item: {e}")
        db.session.rollback()
        return jsonify({'exito': False, 'error': 'Error al editar el item'}), 500


@presupuestos_bp.route('/items/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_item(id):
    """Eliminar item de presupuesto"""
    if current_user.role not in ['admin', 'pm']:
        return jsonify({'ok': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'ok': False, 'error': 'Sin organización activa'}), 400

        item = ItemPresupuesto.query.get_or_404(id)
        presupuesto = item.presupuesto

        if presupuesto.organizacion_id != org_id:
            abort(404)

        if presupuesto.estado != 'borrador':
            flash('Solo se pueden eliminar items de presupuestos en borrador', 'warning')
            return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

        db.session.delete(item)

        # Actualizar totales del presupuesto después de eliminar
        presupuesto.calcular_totales()
        db.session.commit()

        flash('Item eliminado exitosamente', 'success')
        return redirect(url_for('presupuestos.detalle', id=presupuesto.id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.eliminar_item: {e}")
        db.session.rollback()
        flash('Error al eliminar el item', 'danger')
        return redirect(url_for('index'))


@presupuestos_bp.route('/<int:id>/eliminar', methods=['POST'])
@csrf.exempt  # Exentar CSRF para este endpoint que usa AJAX
@login_required
def eliminar(id):
    """Eliminar (archivar) presupuesto"""
    try:
        # Log para debugging
        current_app.logger.info(f'Usuario {current_user.id} intentando eliminar presupuesto {id}')
        current_app.logger.info(f'Usuario rol: {getattr(current_user, "rol", None)}, role: {getattr(current_user, "role", None)}')

        # Verificar permisos usando ambos sistemas de roles
        es_admin = (getattr(current_user, 'rol', None) == 'administrador' or
                    getattr(current_user, 'role', None) == 'admin' or
                    getattr(current_user, 'is_super_admin', False))

        if not es_admin:
            current_app.logger.warning(f'Usuario {current_user.id} sin permisos de admin')
            return jsonify({'error': 'No tienes permisos para eliminar presupuestos'}), 403

        org_id = get_current_org_id()
        current_app.logger.info(f'Org ID obtenido: {org_id}')

        if not org_id:
            # Intentar obtener de usuario directamente
            org_id = getattr(current_user, 'organizacion_id', None)
            current_app.logger.info(f'Org ID de usuario: {org_id}')

        if not org_id:
            current_app.logger.warning('No se pudo obtener organización activa')
            return jsonify({'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.get(id)
        if not presupuesto:
            current_app.logger.warning(f'Presupuesto {id} no encontrado')
            return jsonify({'error': 'Presupuesto no encontrado'}), 404

        if presupuesto.organizacion_id != org_id:
            current_app.logger.warning(f'Usuario sin autorización para presupuesto {id}')
            return jsonify({'error': 'No autorizado'}), 403

        # Solo permitir eliminar presupuestos en borrador o perdidos
        if presupuesto.estado not in ['borrador', 'perdido']:
            current_app.logger.warning(f'Intento de eliminar presupuesto {id} en estado {presupuesto.estado}')
            return jsonify({'error': f'Solo se pueden eliminar presupuestos en borrador o perdidos. Estado actual: {presupuesto.estado}'}), 400

        # Marcar como eliminado en lugar de borrar
        presupuesto.estado = 'eliminado'
        db.session.commit()

        current_app.logger.info(f'Presupuesto {presupuesto.numero} eliminado correctamente')
        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} eliminado correctamente'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.eliminar: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': f'Error al eliminar el presupuesto: {str(e)}'}), 500


@presupuestos_bp.route('/<int:id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado(id):
    """Cambiar estado del presupuesto"""
    if current_user.role not in ['admin', 'pm']:
        flash('No tienes permisos para cambiar el estado', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))

    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        nuevo_estado = request.form.get('estado', '').strip()
        estados_validos = ['borrador', 'enviado', 'aprobado', 'confirmado', 'rechazado', 'perdido', 'vencido']

        if nuevo_estado not in estados_validos:
            flash('Estado inválido', 'danger')
            return redirect(url_for('presupuestos.detalle', id=id))

        presupuesto.estado = nuevo_estado
        db.session.commit()

        flash(f'Estado cambiado a {nuevo_estado}', 'success')
        return redirect(url_for('presupuestos.detalle', id=id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.cambiar_estado: {e}")
        db.session.rollback()
        flash('Error al cambiar el estado', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/<int:id>/revertir-borrador', methods=['POST'])
@login_required
def revertir_borrador(id):
    """Revertir presupuesto a estado borrador (solo administradores)"""
    try:
        # Solo administradores
        if current_user.role != 'admin':
            return jsonify({'error': 'Solo administradores pueden revertir presupuestos'}), 403

        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Verificar que el presupuesto esté en un estado que permita revertir
        if presupuesto.estado not in ['enviado', 'aprobado', 'rechazado', 'perdido']:
            return jsonify({'error': f'No se puede revertir un presupuesto en estado {presupuesto.estado}'}), 400

        # Revertir a borrador
        estado_anterior = presupuesto.estado
        presupuesto.estado = 'borrador'

        # Si estaba marcado como perdido, limpiar esos datos
        if estado_anterior == 'perdido':
            presupuesto.perdido_motivo = None
            presupuesto.perdido_fecha = None

        db.session.commit()

        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} revertido a borrador exitosamente',
            'estado_anterior': estado_anterior,
            'estado_nuevo': 'borrador'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.revertir_borrador: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': 'Error al revertir el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/restaurar', methods=['POST'])
@login_required
def restaurar(id):
    """Restaurar presupuesto perdido a borrador"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Solo se pueden restaurar presupuestos perdidos
        if presupuesto.estado != 'perdido':
            return jsonify({'error': 'Solo se pueden restaurar presupuestos marcados como perdidos'}), 400

        presupuesto.estado = 'borrador'
        presupuesto.perdido_motivo = None
        presupuesto.perdido_fecha = None
        db.session.commit()

        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} restaurado a borrador'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.restaurar: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': 'Error al restaurar el presupuesto'}), 500


@presupuestos_bp.route('/guardar', methods=['POST'])
@login_required
def guardar_presupuesto():
    """Guardar presupuesto desde calculadora IA"""
    if current_user.role not in ['admin', 'pm']:
        return jsonify({'ok': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'ok': False, 'error': 'Sin organización activa'}), 400

        data = request.get_json() or request.form.to_dict()

        # Crear presupuesto
        numero = data.get('numero', f"PRES-{date.today().strftime('%Y%m%d')}")

        presupuesto = Presupuesto(
            organizacion_id=org_id,
            numero=numero,
            obra_id=data.get('obra_id'),
            cliente_nombre=data.get('cliente_nombre', ''),
            fecha=date.today(),
            vigencia_dias=30,
            estado='borrador',
            currency='ARS',
            iva_porcentaje=Decimal('21.0')
        )

        db.session.add(presupuesto)
        db.session.flush()

        # Agregar items si vienen en el payload
        items_data = data.get('items', [])
        for item_data in items_data:
            item = ItemPresupuesto(
                presupuesto_id=presupuesto.id,
                descripcion=item_data.get('descripcion', ''),
                tipo=item_data.get('tipo', 'material'),
                cantidad=Decimal(str(item_data.get('cantidad', 0))),
                unidad=item_data.get('unidad', 'un'),
                precio_unitario=Decimal(str(item_data.get('precio_unitario', 0))),
                subtotal=Decimal(str(item_data.get('subtotal', 0))),
                orden=item_data.get('orden', 0)
            )
            db.session.add(item)

        db.session.commit()

        return jsonify({
            'ok': True,
            'presupuesto_id': presupuesto.id,
            'message': 'Presupuesto guardado exitosamente'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.guardar_presupuesto: {e}")
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/ia/calcular/etapas', methods=['POST'])
@login_required
def calcular_etapas_ia():
    """
    Endpoint para cálculo de etapas seleccionadas con reglas determinísticas
    """
    try:
        from calculadora_ia import calcular_etapas_seleccionadas
        from services.exchange.base import ensure_rate
        from services.exchange.providers.bna import fetch_official_rate
        from decimal import Decimal
        from datetime import date

        data = request.get_json() or {}

        # Validar datos requeridos
        superficie_m2 = data.get('superficie_m2')
        if not superficie_m2 or float(superficie_m2) <= 0:
            return jsonify({
                'ok': False,
                'error': 'Superficie en m² es requerida y debe ser mayor a 0'
            }), 400

        etapa_ids = data.get('etapa_ids', [])
        if not etapa_ids:
            return jsonify({
                'ok': False,
                'error': 'Debes seleccionar al menos una etapa para calcular'
            }), 400

        # Parámetros opcionales
        tipo_calculo = data.get('tipo_calculo', 'Estándar')
        parametros_contexto = data.get('parametros_contexto', {})
        presupuesto_id = data.get('presupuesto_id')
        currency = (data.get('currency') or data.get('moneda', 'ARS')).upper()

        # Obtener tipo de cambio si es necesario
        fx_snapshot = None
        if currency == 'USD':
            try:
                fx_snapshot = ensure_rate(
                    provider='bna_html',
                    base_currency='ARS',
                    quote_currency='USD',
                    fetcher=fetch_official_rate,
                    as_of=date.today(),
                    fallback_rate=Decimal('1000.00')  # Fallback conservador
                )
                current_app.logger.info(f"Tipo de cambio obtenido: {fx_snapshot.value} ARS/USD")
            except Exception as e:
                current_app.logger.error(f"Error obteniendo tipo de cambio: {str(e)}")
                return jsonify({
                    'ok': False,
                    'error': f'No se pudo obtener el tipo de cambio USD: {str(e)}'
                }), 500

        # Llamar a la función de cálculo
        resultado = calcular_etapas_seleccionadas(
            etapas_payload=etapa_ids,
            superficie_m2=float(superficie_m2),
            tipo_calculo=tipo_calculo,
            contexto=parametros_contexto,
            presupuesto_id=presupuesto_id,
            currency=currency,
            fx_snapshot=fx_snapshot
        )

        return jsonify(resultado), 200

    except ValueError as e:
        current_app.logger.error(f"Error de validación en calcular_etapas_ia: {str(e)}")
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 400
    except Exception as e:
        current_app.logger.error(f"Error en calcular_etapas_ia: {str(e)}", exc_info=True)
        return jsonify({
            'ok': False,
            'error': f'Error al calcular etapas: {str(e)}'
        }), 500
