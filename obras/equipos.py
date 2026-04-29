"""Obras -- Equipment in projects routes."""
from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app)
from flask_login import login_required, current_user
from datetime import datetime
from extensions import db
from models import Obra

from obras import obras_bp


def _get_cotizacion_usd():
    """Obtener cotizacion USD/ARS mas reciente del Banco Nacion"""
    try:
        from models.budgets import ExchangeRate
        rate = ExchangeRate.query.filter(
            ExchangeRate.base_currency == 'USD',
            ExchangeRate.quote_currency == 'ARS'
        ).order_by(ExchangeRate.as_of_date.desc(), ExchangeRate.id.desc()).first()
        if rate and rate.sell_rate:
            return float(rate.sell_rate)
    except Exception:
        pass
    return None


@obras_bp.route('/equipos/movimientos', methods=['GET'])
@login_required
def equipos_movimientos():
    """Panel de ubicacion y movimientos de equipos"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id

    equipos = Equipment.query.filter_by(company_id=org_id).order_by(Equipment.nombre).all()
    obras = Obra.query.filter_by(organizacion_id=org_id, estado='en_curso').filter(Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

    movimientos = EquipmentMovement.query.filter_by(company_id=org_id)\
        .order_by(EquipmentMovement.fecha_movimiento.desc()).limit(50).all()

    en_transito = {}
    for mov in EquipmentMovement.query.filter_by(company_id=org_id, estado='en_transito').all():
        en_transito[mov.equipment_id] = mov

    cotizacion_usd = _get_cotizacion_usd()

    # Proveedores visibles para selector de alquiler (propios + globales OBYRA)
    from models.proveedores_oc import ProveedorOC
    from sqlalchemy import or_
    proveedores_alquiler = ProveedorOC.query.filter(
        ProveedorOC.activo.is_(True),
        or_(ProveedorOC.scope == 'global', ProveedorOC.organizacion_id == org_id),
    ).order_by(ProveedorOC.razon_social).all()

    return render_template('obras/equipos_movimientos.html',
                           equipos=equipos, obras=obras, movimientos=movimientos,
                           en_transito=en_transito, cotizacion_usd=cotizacion_usd,
                           proveedores_alquiler=proveedores_alquiler)


@obras_bp.route('/equipos/crear', methods=['POST'])
@login_required
def crear_equipo():
    """Crear nuevo equipo/maquinaria"""
    from models.equipment import Equipment
    org_id = current_user.organizacion_id

    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        return jsonify(ok=False, error='El nombre es obligatorio'), 400

    tipo = request.form.get('tipo', '').strip()
    if not tipo:
        return jsonify(ok=False, error='El tipo es obligatorio'), 400

    moneda = request.form.get('moneda', 'ARS')
    costo_hora = request.form.get('costo_hora', 0, type=float)
    costo_dia = request.form.get('costo_dia', 0, type=float)
    costo_adquisicion = request.form.get('costo_adquisicion', 0, type=float)

    # Modalidad: compra | alquiler_hora | alquiler_dia
    modalidad_costo = (request.form.get('modalidad_costo') or 'compra').strip()
    if modalidad_costo not in ('compra', 'alquiler_hora', 'alquiler_dia'):
        modalidad_costo = 'compra'

    # Datos de alquiler (si aplica)
    proveedor_alquiler_id = request.form.get('proveedor_alquiler_id', type=int)
    fecha_inicio_str = (request.form.get('fecha_inicio_alquiler') or '').strip()
    fecha_fin_str = (request.form.get('fecha_fin_alquiler') or '').strip()
    fecha_inicio_alquiler = None
    fecha_fin_alquiler = None
    if modalidad_costo != 'compra':
        from datetime import datetime as _dt
        try:
            if fecha_inicio_str:
                fecha_inicio_alquiler = _dt.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            if fecha_fin_str:
                fecha_fin_alquiler = _dt.strptime(fecha_fin_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify(ok=False, error='Fechas de alquiler invalidas (use YYYY-MM-DD)'), 400
        # Validar proveedor visible para el tenant (propio o global)
        if proveedor_alquiler_id:
            from models.proveedores_oc import ProveedorOC
            from sqlalchemy import or_
            prov_ok = ProveedorOC.query.filter(
                ProveedorOC.id == proveedor_alquiler_id,
                or_(ProveedorOC.scope == 'global', ProveedorOC.organizacion_id == org_id),
            ).first()
            if not prov_ok:
                proveedor_alquiler_id = None
    else:
        proveedor_alquiler_id = None

    cotizacion = _get_cotizacion_usd()
    costo_hora_usd = None
    costo_adquisicion_usd = None

    if moneda == 'USD' and cotizacion:
        costo_hora_usd = costo_hora
        costo_hora = round(costo_hora * cotizacion, 2)
        costo_adquisicion_usd = costo_adquisicion
        costo_adquisicion = round(costo_adquisicion * cotizacion, 2)
        # costo_dia tambien convertir si viene en USD
        if costo_dia:
            costo_dia = round(costo_dia * cotizacion, 2)
    elif moneda == 'ARS' and cotizacion:
        costo_hora_usd = round(costo_hora / cotizacion, 2) if costo_hora else None
        costo_adquisicion_usd = round(costo_adquisicion / cotizacion, 2) if costo_adquisicion else None

    # Si no se manda codigo, generar correlativo MAQ-NNN automaticamente.
    codigo_form = (request.form.get('codigo') or '').strip()
    if not codigo_form:
        try:
            codigo_form = _proximo_codigo_equipo(org_id)
        except Exception as e:
            current_app.logger.warning(f'No se pudo autogenerar codigo: {e}')
            codigo_form = None

    try:
        equipo = Equipment(
            company_id=org_id,
            nombre=nombre,
            codigo=codigo_form,
            tipo=tipo,
            marca=request.form.get('marca', '').strip() or None,
            modelo=request.form.get('modelo', '').strip() or None,
            nro_serie=request.form.get('nro_serie', '').strip() or None,
            costo_hora=costo_hora,
            costo_hora_usd=costo_hora_usd,
            costo_dia=costo_dia,
            costo_adquisicion=costo_adquisicion,
            costo_adquisicion_usd=costo_adquisicion_usd,
            moneda=moneda,
            modalidad_costo=modalidad_costo,
            proveedor_alquiler_id=proveedor_alquiler_id,
            fecha_inicio_alquiler=fecha_inicio_alquiler,
            fecha_fin_alquiler=fecha_fin_alquiler,
            estado='activo',
            ubicacion_tipo='deposito',
        )
        db.session.add(equipo)
        db.session.commit()
        flash(f'Equipo "{nombre}" creado exitosamente', 'success')
        return jsonify(ok=True, id=equipo.id)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/<int:equipo_id>/editar', methods=['POST'])
@login_required
def editar_equipo(equipo_id):
    """Editar equipo existente"""
    from models.equipment import Equipment
    org_id = current_user.organizacion_id
    equipo = Equipment.query.filter_by(id=equipo_id, company_id=org_id).first_or_404()

    try:
        equipo.nombre = request.form.get('nombre', equipo.nombre).strip()
        equipo.codigo = request.form.get('codigo', '').strip() or equipo.codigo
        equipo.tipo = request.form.get('tipo', equipo.tipo).strip()
        equipo.marca = request.form.get('marca', '').strip() or equipo.marca
        equipo.modelo = request.form.get('modelo', '').strip() or equipo.modelo
        equipo.nro_serie = request.form.get('nro_serie', '').strip() or equipo.nro_serie
        equipo.estado = request.form.get('estado', equipo.estado)

        moneda = request.form.get('moneda', equipo.moneda or 'ARS')
        costo_hora = request.form.get('costo_hora', type=float) or 0
        costo_dia = request.form.get('costo_dia', type=float) or 0
        costo_adquisicion = request.form.get('costo_adquisicion', type=float) or 0

        # Modalidad y datos de alquiler
        modalidad_costo = (request.form.get('modalidad_costo') or equipo.modalidad_costo or 'compra').strip()
        if modalidad_costo not in ('compra', 'alquiler_hora', 'alquiler_dia'):
            modalidad_costo = 'compra'
        equipo.modalidad_costo = modalidad_costo

        if modalidad_costo == 'compra':
            equipo.proveedor_alquiler_id = None
            equipo.fecha_inicio_alquiler = None
            equipo.fecha_fin_alquiler = None
        else:
            from datetime import datetime as _dt
            from sqlalchemy import or_
            from models.proveedores_oc import ProveedorOC

            prov_id = request.form.get('proveedor_alquiler_id', type=int)
            if prov_id:
                prov_ok = ProveedorOC.query.filter(
                    ProveedorOC.id == prov_id,
                    or_(ProveedorOC.scope == 'global', ProveedorOC.organizacion_id == org_id),
                ).first()
                equipo.proveedor_alquiler_id = prov_id if prov_ok else None
            else:
                equipo.proveedor_alquiler_id = None

            fi = (request.form.get('fecha_inicio_alquiler') or '').strip()
            ff = (request.form.get('fecha_fin_alquiler') or '').strip()
            try:
                equipo.fecha_inicio_alquiler = _dt.strptime(fi, '%Y-%m-%d').date() if fi else None
                equipo.fecha_fin_alquiler = _dt.strptime(ff, '%Y-%m-%d').date() if ff else None
            except ValueError:
                return jsonify(ok=False, error='Fechas de alquiler invalidas (use YYYY-MM-DD)'), 400

        cotizacion = _get_cotizacion_usd()
        if moneda == 'USD' and cotizacion:
            equipo.costo_hora_usd = costo_hora
            equipo.costo_hora = round(costo_hora * cotizacion, 2)
            equipo.costo_adquisicion_usd = costo_adquisicion
            equipo.costo_adquisicion = round(costo_adquisicion * cotizacion, 2)
            equipo.costo_dia = round(costo_dia * cotizacion, 2) if costo_dia else 0
        elif moneda == 'ARS' and cotizacion:
            equipo.costo_hora = costo_hora
            equipo.costo_hora_usd = round(costo_hora / cotizacion, 2) if costo_hora else None
            equipo.costo_adquisicion = costo_adquisicion
            equipo.costo_adquisicion_usd = round(costo_adquisicion / cotizacion, 2) if costo_adquisicion else None
            equipo.costo_dia = costo_dia
        else:
            equipo.costo_hora = costo_hora
            equipo.costo_adquisicion = costo_adquisicion
            equipo.costo_dia = costo_dia
        equipo.moneda = moneda

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" actualizado', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/<int:equipo_id>/eliminar', methods=['POST'])
@login_required
def eliminar_equipo(equipo_id):
    """Dar de baja un equipo"""
    from models.equipment import Equipment
    org_id = current_user.organizacion_id
    equipo = Equipment.query.filter_by(id=equipo_id, company_id=org_id).first_or_404()

    try:
        equipo.estado = 'baja'
        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" dado de baja', 'warning')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/<int:equipo_id>/despachar', methods=['POST'])
@login_required
def despachar_equipo(equipo_id):
    """Despacho: Deposito -> Obra"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id
    equipo = Equipment.query.filter_by(id=equipo_id, company_id=org_id).first_or_404()

    if equipo.ubicacion_tipo != 'deposito':
        return jsonify(ok=False, error='El equipo no esta en deposito'), 400

    destino_obra_id = request.form.get('destino_obra_id', type=int)
    if not destino_obra_id:
        return jsonify(ok=False, error='Debe indicar la obra destino'), 400

    obra_destino = Obra.query.filter_by(id=destino_obra_id, organizacion_id=org_id).first()
    if not obra_destino:
        return jsonify(ok=False, error='Obra destino no encontrada'), 404

    try:
        mov = EquipmentMovement(
            equipment_id=equipo.id,
            company_id=org_id,
            tipo='despacho',
            origen_tipo='deposito',
            origen_obra_id=None,
            destino_tipo='obra',
            destino_obra_id=destino_obra_id,
            despachado_por=current_user.id,
            notas=request.form.get('notas', ''),
            costo_transporte=request.form.get('costo_transporte', 0, type=float),
            estado='en_transito'
        )
        db.session.add(mov)

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" despachado a {obra_destino.nombre} (pendiente de recepcion)', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/<int:equipo_id>/trasladar', methods=['POST'])
@login_required
def trasladar_equipo(equipo_id):
    """Traslado: Obra -> Obra"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id
    equipo = Equipment.query.filter_by(id=equipo_id, company_id=org_id).first_or_404()

    destino_obra_id = request.form.get('destino_obra_id', type=int)
    if not destino_obra_id:
        return jsonify(ok=False, error='Debe indicar la obra destino'), 400

    obra_destino = Obra.query.filter_by(id=destino_obra_id, organizacion_id=org_id).first()
    if not obra_destino:
        return jsonify(ok=False, error='Obra destino no encontrada'), 404

    try:
        movs_previos = EquipmentMovement.query.filter_by(
            equipment_id=equipo.id, estado='en_transito'
        ).all()
        for mp in movs_previos:
            mp.estado = 'cancelado'

        origen_obra_id = equipo.ubicacion_obra_id
        origen_tipo = equipo.ubicacion_tipo

        mov = EquipmentMovement(
            equipment_id=equipo.id,
            company_id=org_id,
            tipo='traslado',
            origen_tipo=origen_tipo,
            origen_obra_id=origen_obra_id,
            destino_tipo='obra',
            destino_obra_id=destino_obra_id,
            despachado_por=current_user.id,
            notas=request.form.get('notas', ''),
            costo_transporte=request.form.get('costo_transporte', 0, type=float),
            estado='en_transito'
        )
        db.session.add(mov)

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" en transito a {obra_destino.nombre} (pendiente de recepcion)', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/<int:equipo_id>/devolver', methods=['POST'])
@login_required
def devolver_equipo(equipo_id):
    """Devolucion: Obra -> Deposito"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id
    equipo = Equipment.query.filter_by(id=equipo_id, company_id=org_id).first_or_404()

    if equipo.ubicacion_tipo != 'obra':
        return jsonify(ok=False, error='El equipo ya esta en deposito'), 400

    try:
        mov = EquipmentMovement(
            equipment_id=equipo.id,
            company_id=org_id,
            tipo='devolucion',
            origen_tipo='obra',
            origen_obra_id=equipo.ubicacion_obra_id,
            destino_tipo='deposito',
            destino_obra_id=None,
            despachado_por=current_user.id,
            notas=request.form.get('notas', ''),
            costo_transporte=request.form.get('costo_transporte', 0, type=float),
            estado='recibido'
        )
        db.session.add(mov)

        equipo.ubicacion_tipo = 'deposito'
        equipo.ubicacion_obra_id = None

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" devuelto al deposito', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/equipos/ubicaciones-json', methods=['GET'])
@login_required
def equipos_ubicaciones_json():
    """API: ubicacion actual de todos los equipos"""
    from models.equipment import Equipment
    org_id = current_user.organizacion_id
    equipos = Equipment.query.filter_by(company_id=org_id, estado='activo').all()

    result = []
    for eq in equipos:
        result.append({
            'id': eq.id,
            'nombre': eq.nombre,
            'codigo': eq.codigo,
            'tipo': eq.tipo,
            'ubicacion_tipo': eq.ubicacion_tipo,
            'ubicacion_obra_id': eq.ubicacion_obra_id,
            'ubicacion_obra_nombre': eq.ubicacion_obra.nombre if eq.ubicacion_obra else None,
            'costo_hora': float(eq.costo_hora) if eq.costo_hora else 0,
            'estado': eq.estado,
        })

    return jsonify(ok=True, equipos=result)


@obras_bp.route('/equipos/movimiento/<int:mov_id>/aceptar', methods=['POST'])
@login_required
def aceptar_movimiento(mov_id):
    """Aceptar recepcion de equipo en la obra.

    Ademas de marcar el movimiento como recibido y actualizar la ubicacion
    del equipo, crea/actualiza un EquipmentAssignment con la fecha de
    recepcion (= fecha_llegada del movimiento). Si ya hay un assignment
    activo del equipo en esa obra, lo reutiliza completando fecha_recepcion
    si todavia esta vacia. Si el equipo viene de OTRA obra, libera el
    assignment anterior.
    """
    from models.equipment import Equipment, EquipmentMovement, EquipmentAssignment
    from datetime import date as _date
    org_id = current_user.organizacion_id
    mov = EquipmentMovement.query.filter_by(id=mov_id, company_id=org_id, estado='en_transito').first_or_404()

    try:
        mov.estado = 'recibido'
        mov.recibido_por = current_user.id
        mov.fecha_llegada = datetime.utcnow()

        equipo = mov.equipment
        ubicacion_anterior_obra_id = equipo.ubicacion_obra_id
        equipo.ubicacion_tipo = mov.destino_tipo
        equipo.ubicacion_obra_id = mov.destino_obra_id

        # Auto-gestion de EquipmentAssignment cuando el destino es una obra
        if mov.destino_tipo == 'obra' and mov.destino_obra_id:
            fecha_llegada_dt = mov.fecha_llegada.date() if mov.fecha_llegada else _date.today()

            # 1. Liberar assignment activo en otra obra (origen) si lo habia
            if ubicacion_anterior_obra_id and ubicacion_anterior_obra_id != mov.destino_obra_id:
                anterior = EquipmentAssignment.query.filter_by(
                    equipment_id=equipo.id,
                    project_id=ubicacion_anterior_obra_id,
                    estado='asignado',
                ).first()
                if anterior:
                    anterior.estado = 'liberado'
                    anterior.fecha_devolucion_real = fecha_llegada_dt
                    if not anterior.fecha_hasta:
                        anterior.fecha_hasta = fecha_llegada_dt

            # 2. Buscar/crear assignment activo en la obra destino
            asg = EquipmentAssignment.query.filter_by(
                equipment_id=equipo.id,
                project_id=mov.destino_obra_id,
                estado='asignado',
            ).first()
            if asg:
                # Si ya existe, completar fecha_recepcion si estaba vacia.
                if not asg.fecha_recepcion:
                    asg.fecha_recepcion = fecha_llegada_dt
                if not asg.responsable_recepcion_id:
                    asg.responsable_recepcion_id = current_user.id
            else:
                asg = EquipmentAssignment(
                    equipment_id=equipo.id,
                    project_id=mov.destino_obra_id,
                    fecha_desde=fecha_llegada_dt,
                    fecha_recepcion=fecha_llegada_dt,
                    responsable_recepcion_id=current_user.id,
                    estado='asignado',
                    jornada_base_horas=8,
                )
                db.session.add(asg)

        # Si el destino es deposito y habia un assignment activo en obra origen, liberarlo
        elif mov.destino_tipo == 'deposito' and mov.origen_tipo == 'obra' and mov.origen_obra_id:
            asg = EquipmentAssignment.query.filter_by(
                equipment_id=equipo.id,
                project_id=mov.origen_obra_id,
                estado='asignado',
            ).first()
            if asg:
                asg.estado = 'liberado'
                fecha_devol = mov.fecha_llegada.date() if mov.fecha_llegada else _date.today()
                asg.fecha_devolucion_real = fecha_devol
                if not asg.fecha_hasta:
                    asg.fecha_hasta = fecha_devol

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" recibido correctamente', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/api/equipment/<int:equipment_id>/usos', methods=['GET'])
@login_required
def api_listar_usos_equipo(equipment_id):
    """Lista usos de un equipo en una obra dada (todos los estados).
    Query param: ?project_id=<id>
    """
    from models.equipment import EquipmentUsage, Equipment

    equipo = Equipment.query.filter_by(
        id=equipment_id,
        company_id=current_user.organizacion_id
    ).first()
    if not equipo:
        return jsonify(ok=False, error='Equipo no encontrado'), 404

    project_id = request.args.get('project_id', type=int)
    q = EquipmentUsage.query.filter_by(equipment_id=equipment_id)
    if project_id:
        q = q.filter_by(project_id=project_id)

    usos = q.order_by(EquipmentUsage.fecha.desc(), EquipmentUsage.id.desc()).all()
    unidad = 'días' if (getattr(equipo, 'modalidad_costo', '') == 'alquiler_dia') else 'h'

    return jsonify(ok=True, unidad=unidad, usos=[{
        'id': u.id,
        'fecha': u.fecha.strftime('%Y-%m-%d') if u.fecha else '',
        'fecha_display': u.fecha.strftime('%d/%m/%Y') if u.fecha else '',
        'horas': float(u.horas or 0),
        'notas': u.notas or '',
        'estado': u.estado,
        'usuario': (u.usuario.nombre_completo if u.usuario else '—') if hasattr(u, 'usuario') else '—',
    } for u in usos])


@obras_bp.route('/api/equipment/uso/<int:uso_id>', methods=['PATCH'])
@login_required
def api_editar_uso_equipo(uso_id):
    """Edita horas/notas de un uso. Solo admin/pm/tecnico pueden editar.
    Al editar, el cálculo del costo real se recalcula automáticamente en el
    próximo render (el query suma desde estado='aprobado')."""
    from models.equipment import EquipmentUsage, Equipment

    uso = EquipmentUsage.query.get(uso_id)
    if not uso:
        return jsonify(ok=False, error='Uso no encontrado'), 404

    equipo = Equipment.query.get(uso.equipment_id)
    if not equipo or equipo.company_id != current_user.organizacion_id:
        return jsonify(ok=False, error='Sin permisos'), 403

    # Solo admin/pm/tecnico pueden editar
    roles_usuario = {(getattr(current_user, 'rol', '') or '').lower(),
                      (getattr(current_user, 'role', '') or '').lower()}
    roles_edicion = {'admin', 'administrador', 'pm', 'project_manager', 'tecnico'}
    if not (roles_usuario & roles_edicion) and not getattr(current_user, 'is_super_admin', False):
        return jsonify(ok=False, error='Sin permisos para editar usos'), 403

    data = request.get_json(silent=True) or {}
    try:
        if 'horas' in data and data['horas'] is not None:
            nuevas_horas = float(str(data['horas']).replace(',', '.'))
            if nuevas_horas <= 0:
                return jsonify(ok=False, error='Las horas/días deben ser > 0'), 400
            uso.horas = nuevas_horas
        if 'notas' in data:
            uso.notas = data['notas'] or ''
        if 'fecha' in data and data['fecha']:
            try:
                uso.fecha = datetime.strptime(data['fecha'], '%Y-%m-%d').date()
            except ValueError:
                return jsonify(ok=False, error='Fecha inválida'), 400

        db.session.commit()
        return jsonify(ok=True, horas=float(uso.horas or 0))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error editando uso de equipo')
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/api/equipment/uso/<int:uso_id>', methods=['DELETE'])
@login_required
def api_eliminar_uso_equipo(uso_id):
    """Elimina un uso de equipo. Solo admin/pm/tecnico."""
    from models.equipment import EquipmentUsage, Equipment

    uso = EquipmentUsage.query.get(uso_id)
    if not uso:
        return jsonify(ok=False, error='Uso no encontrado'), 404

    equipo = Equipment.query.get(uso.equipment_id)
    if not equipo or equipo.company_id != current_user.organizacion_id:
        return jsonify(ok=False, error='Sin permisos'), 403

    roles_usuario = {(getattr(current_user, 'rol', '') or '').lower(),
                      (getattr(current_user, 'role', '') or '').lower()}
    roles_edicion = {'admin', 'administrador', 'pm', 'project_manager', 'tecnico'}
    if not (roles_usuario & roles_edicion) and not getattr(current_user, 'is_super_admin', False):
        return jsonify(ok=False, error='Sin permisos para eliminar usos'), 403

    try:
        db.session.delete(uso)
        db.session.commit()
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error eliminando uso de equipo')
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/api/equipment/<int:equipment_id>/uso', methods=['POST'])
@login_required
def api_registrar_uso_equipo(equipment_id):
    """Registra un uso de equipo en una obra desde la solapa de Maquinaria.

    Crea un EquipmentUsage con estado 'pendiente'. Solo impactará en el
    costo real de la obra cuando un admin/pm lo apruebe (estado='aprobado').

    Payload JSON:
      {
        "project_id": int,   # Obra donde se usó
        "fecha": "YYYY-MM-DD",
        "horas": float,      # Cantidad (si modalidad alquiler_dia, se interpreta como DÍAS)
        "notas": str (opcional)
      }
    """
    from models.equipment import Equipment, EquipmentUsage

    data = request.get_json(silent=True) or {}
    project_id = data.get('project_id')
    fecha_str = data.get('fecha')
    horas = data.get('horas')
    notas = data.get('notas') or ''

    if not project_id or not fecha_str or horas is None:
        return jsonify(ok=False, error='Faltan campos (project_id, fecha, horas)'), 400

    try:
        horas = float(horas)
        if horas <= 0:
            return jsonify(ok=False, error='La cantidad debe ser > 0'), 400
    except (TypeError, ValueError):
        return jsonify(ok=False, error='Cantidad inválida'), 400

    equipo = Equipment.query.filter_by(
        id=equipment_id,
        company_id=current_user.organizacion_id
    ).first()
    if not equipo:
        return jsonify(ok=False, error='Equipo no encontrado'), 404

    # Validar que la obra pertenezca a la misma organización
    obra = Obra.query.filter_by(id=int(project_id),
                                 organizacion_id=current_user.organizacion_id).first()
    if not obra:
        return jsonify(ok=False, error='Obra no encontrada'), 404

    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify(ok=False, error='Fecha inválida (formato esperado YYYY-MM-DD)'), 400

    # Si lo registra un admin/PM/técnico, el uso queda aprobado directamente
    # (ellos son la autoridad). Si es operario, queda pendiente para que un
    # admin lo revise y apruebe.
    roles_usuario = set()
    rol_attr = (getattr(current_user, 'rol', '') or '').lower()
    role_attr = (getattr(current_user, 'role', '') or '').lower()
    if rol_attr: roles_usuario.add(rol_attr)
    if role_attr: roles_usuario.add(role_attr)
    roles_auto_aprueban = {'admin', 'administrador', 'pm', 'project_manager', 'tecnico'}
    es_autoridad = bool(roles_usuario & roles_auto_aprueban) or getattr(current_user, 'is_super_admin', False)

    estado_inicial = 'aprobado' if es_autoridad else 'pendiente'

    try:
        uso = EquipmentUsage(
            equipment_id=equipment_id,
            project_id=int(project_id),
            fecha=fecha,
            horas=horas,
            notas=notas,
            user_id=current_user.id,
            estado=estado_inicial,
        )
        # Si ya queda aprobado, registrar auditoría de auto-aprobación
        if estado_inicial == 'aprobado':
            uso.approved_by = current_user.id
            uso.approved_at = datetime.utcnow()
        db.session.add(uso)
        db.session.commit()
        return jsonify(ok=True, uso_id=uso.id, estado=estado_inicial)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error registrando uso de equipo')
        return jsonify(ok=False, error=str(e)), 500



# ============================================================
# Fase 1 maquinaria: fechas planificadas + recepcion del Assignment
# ============================================================

@obras_bp.route('/<int:obra_id>/maquinaria/<int:asg_id>/fechas', methods=['POST'])
@login_required
def editar_fechas_assignment(obra_id, asg_id):
    """Editar fechas planificadas y datos de recepcion del EquipmentAssignment.

    Body JSON o form:
      - fecha_recepcion: YYYY-MM-DD (opcional)
      - fecha_inicio_uso_estimada: YYYY-MM-DD (opcional)
      - fecha_fin_uso_estimada: YYYY-MM-DD (opcional)
      - fecha_devolucion_estimada: YYYY-MM-DD (opcional)
      - jornada_base_horas: int (default 8)
      - responsable_recepcion_id: int (opcional)
      - observaciones: text (opcional)
    """
    from models.equipment import EquipmentAssignment
    from datetime import datetime as _dt

    org_id = current_user.organizacion_id

    asg = EquipmentAssignment.query.filter_by(id=asg_id, project_id=obra_id).first_or_404()
    # Validar que la obra pertenece a la organizacion
    if not asg.project or asg.project.organizacion_id != org_id:
        return jsonify(ok=False, error='No autorizado'), 403

    data = request.get_json(silent=True) or request.form

    def _parse_date(key):
        s = (data.get(key) or '').strip() if hasattr(data, 'get') else ''
        if not s:
            return None
        try:
            return _dt.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return False  # marca error

    try:
        fechas = {}
        for k in ('fecha_recepcion', 'fecha_inicio_uso_estimada',
                  'fecha_fin_uso_estimada', 'fecha_devolucion_estimada'):
            if k in data:
                v = _parse_date(k)
                if v is False:
                    return jsonify(ok=False, error=f'Fecha {k} invalida (use YYYY-MM-DD)'), 400
                fechas[k] = v

        for k, v in fechas.items():
            setattr(asg, k, v)

        if 'jornada_base_horas' in data:
            try:
                jb = int(data.get('jornada_base_horas') or 8)
                if jb < 1 or jb > 24:
                    return jsonify(ok=False, error='jornada_base_horas debe estar entre 1 y 24'), 400
                asg.jornada_base_horas = jb
            except (TypeError, ValueError):
                return jsonify(ok=False, error='jornada_base_horas invalida'), 400

        if 'responsable_recepcion_id' in data:
            try:
                rid = data.get('responsable_recepcion_id')
                asg.responsable_recepcion_id = int(rid) if rid else None
            except (TypeError, ValueError):
                pass

        if 'observaciones' in data:
            obs = (data.get('observaciones') or '').strip()
            asg.observaciones = obs or None

        db.session.commit()
        return jsonify(ok=True, assignment={
            'id': asg.id,
            'fecha_recepcion': asg.fecha_recepcion.isoformat() if asg.fecha_recepcion else None,
            'fecha_inicio_uso_estimada': asg.fecha_inicio_uso_estimada.isoformat() if asg.fecha_inicio_uso_estimada else None,
            'fecha_fin_uso_estimada': asg.fecha_fin_uso_estimada.isoformat() if asg.fecha_fin_uso_estimada else None,
            'fecha_devolucion_estimada': asg.fecha_devolucion_estimada.isoformat() if asg.fecha_devolucion_estimada else None,
            'jornada_base_horas': asg.jornada_base_horas,
            'responsable_recepcion_id': asg.responsable_recepcion_id,
            'observaciones': asg.observaciones,
            'estado_uso': asg.estado_uso,
            'horas_estimadas_jornada': asg.horas_estimadas_jornada,
            'dias_en_obra': asg.dias_en_obra,
            'dias_hasta_fin_uso': asg.dias_hasta_fin_uso,
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error editando fechas de assignment')
        return jsonify(ok=False, error=str(e)), 500


# ============================================================
# Codigo automatico de equipo (MAQ-NNN correlativo)
# ============================================================

def _proximo_codigo_equipo(org_id, prefijo='MAQ-'):
    """Devuelve el proximo codigo correlativo MAQ-NNN para la organizacion."""
    import re
    from models.equipment import Equipment
    existentes = Equipment.query.filter(
        Equipment.company_id == org_id,
        Equipment.codigo.like(f'{prefijo}%'),
    ).all()
    max_num = 0
    for eq in existentes:
        m = re.search(r'-(\d+)$', eq.codigo or '')
        if m:
            try:
                n = int(m.group(1))
                if n > max_num:
                    max_num = n
            except ValueError:
                continue
    siguiente = max_num + 1
    codigo = f'{prefijo}{siguiente:03d}'
    # Garantia anti-colisiones (por si hay codigos manuales con mismo formato)
    while Equipment.query.filter_by(company_id=org_id, codigo=codigo).first():
        siguiente += 1
        codigo = f'{prefijo}{siguiente:03d}'
    return codigo


@obras_bp.route('/api/equipos/proximo-codigo')
@login_required
def api_proximo_codigo_equipo():
    """Devuelve el proximo codigo correlativo de equipo para la org actual.

    Patron: MAQ-001, MAQ-002, ...
    """
    org_id = current_user.organizacion_id
    if not org_id:
        return jsonify(ok=False, error='Sin organizacion activa'), 400
    try:
        codigo = _proximo_codigo_equipo(org_id)
        return jsonify(ok=True, codigo=codigo)
    except Exception as e:
        current_app.logger.exception('Error generando codigo de equipo')
        return jsonify(ok=False, error=f'Error: {type(e).__name__}: {str(e)[:200]}'), 500
