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
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

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

        # Query base - excluir presupuestos eliminados
        query = Presupuesto.query.filter_by(organizacion_id=org_id).filter(
            Presupuesto.estado != 'eliminado'
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
            cliente_nombre = request.form.get('cliente_nombre', '').strip()
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
    """Generar PDF del presupuesto"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Crear PDF en memoria
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # Título
        p.setFont("Helvetica-Bold", 16)
        p.drawString(100, height - 50, f"Presupuesto {presupuesto.numero}")

        # Información básica
        p.setFont("Helvetica", 12)
        y = height - 100
        p.drawString(100, y, f"Fecha: {presupuesto.fecha.strftime('%d/%m/%Y')}")
        y -= 20
        if presupuesto.cliente_nombre:
            p.drawString(100, y, f"Cliente: {presupuesto.cliente_nombre}")
            y -= 20
        if presupuesto.obra:
            p.drawString(100, y, f"Obra: {presupuesto.obra.nombre}")
            y -= 20

        p.drawString(100, y, f"Estado: {presupuesto.estado}")
        y -= 40

        # Items
        items = ItemPresupuesto.query.filter_by(presupuesto_id=id).order_by(
            ItemPresupuesto.tipo,
            ItemPresupuesto.orden
        ).all()

        p.setFont("Helvetica-Bold", 14)
        p.drawString(100, y, "Items:")
        y -= 25

        p.setFont("Helvetica", 10)
        for item in items:
            if y < 100:
                p.showPage()
                y = height - 50

            texto = f"{item.descripcion} - {item.cantidad} {item.unidad} x ${item.precio_unitario} = ${item.subtotal}"
            p.drawString(120, y, texto)
            y -= 20

        # Total
        y -= 20
        p.setFont("Helvetica-Bold", 12)
        p.drawString(100, y, f"Subtotal: ${presupuesto.total_sin_iva}")
        y -= 20
        p.drawString(100, y, f"IVA ({presupuesto.iva_porcentaje}%): ${presupuesto.total_iva}")
        y -= 20
        p.drawString(100, y, f"TOTAL: ${presupuesto.total_con_iva}")

        p.save()
        buffer.seek(0)

        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'presupuesto_{presupuesto.numero}.pdf'
        )

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.generar_pdf: {e}")
        flash('Error al generar el PDF', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


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
def editar_item(id):
    """Editar item de presupuesto"""
    if current_user.role not in ['admin', 'pm']:
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

        db.session.commit()

        # Calcular totales actualizados
        items = ItemPresupuesto.query.filter_by(presupuesto_id=presupuesto.id).all()
        subtotal_materiales = sum(i.total for i in items if i.tipo == 'material')
        subtotal_mano_obra = sum(i.total for i in items if i.tipo == 'mano_obra')
        subtotal_equipos = sum(i.total for i in items if i.tipo == 'equipo')
        total_sin_iva = sum(i.total for i in items)
        iva_monto = total_sin_iva * (presupuesto.iva_porcentaje / Decimal('100'))
        total_con_iva = total_sin_iva + iva_monto

        return jsonify({
            'exito': True,
            'nuevo_total': float(item.total),
            'price_unit_ars': float(item.price_unit_ars) if item.price_unit_ars else None,
            'total_ars': float(item.total_ars) if item.total_ars else None,
            'currency': item.currency,
            'subtotal_materiales': float(subtotal_materiales),
            'subtotal_mano_obra': float(subtotal_mano_obra),
            'subtotal_equipos': float(subtotal_equipos),
            'total_sin_iva': float(total_sin_iva),
            'iva_monto': float(iva_monto),
            'total_con_iva': float(total_con_iva)
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
