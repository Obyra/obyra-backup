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

    return render_template('obras/equipos_movimientos.html',
                           equipos=equipos, obras=obras, movimientos=movimientos,
                           en_transito=en_transito, cotizacion_usd=cotizacion_usd)


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
    costo_adquisicion = request.form.get('costo_adquisicion', 0, type=float)

    cotizacion = _get_cotizacion_usd()
    costo_hora_usd = None
    costo_adquisicion_usd = None

    if moneda == 'USD' and cotizacion:
        costo_hora_usd = costo_hora
        costo_hora = round(costo_hora * cotizacion, 2)
        costo_adquisicion_usd = costo_adquisicion
        costo_adquisicion = round(costo_adquisicion * cotizacion, 2)
    elif moneda == 'ARS' and cotizacion:
        costo_hora_usd = round(costo_hora / cotizacion, 2) if costo_hora else None
        costo_adquisicion_usd = round(costo_adquisicion / cotizacion, 2) if costo_adquisicion else None

    try:
        equipo = Equipment(
            company_id=org_id,
            nombre=nombre,
            codigo=request.form.get('codigo', '').strip() or None,
            tipo=tipo,
            marca=request.form.get('marca', '').strip() or None,
            modelo=request.form.get('modelo', '').strip() or None,
            nro_serie=request.form.get('nro_serie', '').strip() or None,
            costo_hora=costo_hora,
            costo_hora_usd=costo_hora_usd,
            costo_adquisicion=costo_adquisicion,
            costo_adquisicion_usd=costo_adquisicion_usd,
            moneda=moneda,
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
        costo_adquisicion = request.form.get('costo_adquisicion', type=float) or 0

        cotizacion = _get_cotizacion_usd()
        if moneda == 'USD' and cotizacion:
            equipo.costo_hora_usd = costo_hora
            equipo.costo_hora = round(costo_hora * cotizacion, 2)
            equipo.costo_adquisicion_usd = costo_adquisicion
            equipo.costo_adquisicion = round(costo_adquisicion * cotizacion, 2)
        elif moneda == 'ARS' and cotizacion:
            equipo.costo_hora = costo_hora
            equipo.costo_hora_usd = round(costo_hora / cotizacion, 2) if costo_hora else None
            equipo.costo_adquisicion = costo_adquisicion
            equipo.costo_adquisicion_usd = round(costo_adquisicion / cotizacion, 2) if costo_adquisicion else None
        else:
            equipo.costo_hora = costo_hora
            equipo.costo_adquisicion = costo_adquisicion
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
    """Aceptar recepcion de equipo en la obra"""
    from models.equipment import Equipment, EquipmentMovement
    org_id = current_user.organizacion_id
    mov = EquipmentMovement.query.filter_by(id=mov_id, company_id=org_id, estado='en_transito').first_or_404()

    try:
        mov.estado = 'recibido'
        mov.recibido_por = current_user.id
        mov.fecha_llegada = datetime.utcnow()

        equipo = mov.equipment
        equipo.ubicacion_tipo = mov.destino_tipo
        equipo.ubicacion_obra_id = mov.destino_obra_id

        db.session.commit()
        flash(f'Equipo "{equipo.nombre}" recibido correctamente', 'success')
        return jsonify(ok=True)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500
