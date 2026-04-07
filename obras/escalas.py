"""Obras -- Salary scales + crews routes."""
from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app)
from flask_login import login_required, current_user
from datetime import date
from decimal import Decimal
from extensions import db

from obras import obras_bp, _get_roles_usuario


@obras_bp.route('/escala-salarial')
@login_required
def escala_salarial():
    """Pagina de gestion de escala salarial UOCRA y cuadrillas."""
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador', 'pm', 'project_manager'}):
        flash('Sin permisos para esta seccion', 'warning')
        return redirect(url_for('obras.listar'))

    org_id = current_user.organizacion_id
    if not org_id:
        flash('No tenes una organizacion asignada', 'warning')
        return redirect(url_for('obras.listar'))

    try:
        db.create_all()
    except Exception:
        pass

    try:
        from services.cuadrillas_service import seed_escala_salarial, seed_cuadrillas_default
        seed_escala_salarial(org_id)
        seed_cuadrillas_default(org_id)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error seeding escala/cuadrillas: %s", e)

    return render_template('obras/escala_salarial.html')


@obras_bp.route('/escala-salarial/api')
@login_required
def escala_salarial_api():
    """API: obtener escala salarial vigente."""
    try:
        from services.cuadrillas_service import obtener_escala_vigente
        org_id = current_user.organizacion_id
        if not org_id:
            return jsonify(ok=True, items=[])
        escalas = obtener_escala_vigente(org_id)
        return jsonify(ok=True, items=[{
            'id': e.id,
            'categoria': e.categoria,
            'descripcion': e.descripcion,
            'jornal': float(e.jornal),
            'tarifa_hora': float(e.tarifa_hora or 0),
            'vigencia_desde': e.vigencia_desde.isoformat() if e.vigencia_desde else None,
        } for e in escalas])
    except Exception as e:
        current_app.logger.exception("Error en escala_salarial_api")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/escala-salarial/api', methods=['POST'])
@login_required
def escala_salarial_actualizar():
    """API: actualizar escala salarial."""
    from services.cuadrillas_service import actualizar_escala
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True)
    if not data or 'items' not in data:
        return jsonify(ok=False, error='Datos invalidos'), 400

    try:
        vigencia = data.get('vigencia_desde')
        vigencia_date = date.fromisoformat(vigencia) if vigencia else None
        actualizar_escala(current_user.organizacion_id, data['items'], vigencia_date)
        return jsonify(ok=True, mensaje='Escala salarial actualizada')
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/cuadrillas/api')
@login_required
def cuadrillas_api():
    """API: obtener cuadrillas tipo de la organizacion."""
    from models.budgets import CuadrillaTipo
    org_id = current_user.organizacion_id
    tipo_obra = request.args.get('tipo_obra')
    etapa_tipo = request.args.get('etapa_tipo')

    query = CuadrillaTipo.query.filter_by(organizacion_id=org_id, activo=True)
    if tipo_obra:
        query = query.filter_by(tipo_obra=tipo_obra)
    if etapa_tipo:
        query = query.filter_by(etapa_tipo=etapa_tipo)

    cuadrillas = query.order_by(CuadrillaTipo.etapa_tipo, CuadrillaTipo.tipo_obra).all()

    return jsonify(ok=True, items=[{
        'id': c.id,
        'nombre': c.nombre,
        'etapa_tipo': c.etapa_tipo,
        'tipo_obra': c.tipo_obra,
        'rendimiento_diario': float(c.rendimiento_diario or 0),
        'unidad_rendimiento': c.unidad_rendimiento,
        'costo_diario': float(c.costo_diario),
        'cantidad_personas': c.cantidad_personas,
        'miembros': [{
            'id': m.id,
            'rol': m.rol,
            'cantidad': float(m.cantidad),
            'jornal': float(m.jornal_override or (m.escala.jornal if m.escala else 0)),
            'categoria': m.escala.categoria if m.escala else None,
            'descripcion_categoria': m.escala.descripcion if m.escala else None,
        } for m in c.miembros]
    } for c in cuadrillas])


@obras_bp.route('/cuadrillas/api', methods=['POST'])
@login_required
def cuadrillas_guardar():
    """API: crear o actualizar una cuadrilla tipo."""
    from models.budgets import CuadrillaTipo, MiembroCuadrilla, EscalaSalarialUOCRA
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'administrador', 'pm', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos invalidos'), 400

    org_id = current_user.organizacion_id

    try:
        cuadrilla_id = data.get('id')
        if cuadrilla_id:
            cuadrilla = CuadrillaTipo.query.get(cuadrilla_id)
            if not cuadrilla or cuadrilla.organizacion_id != org_id:
                return jsonify(ok=False, error='Cuadrilla no encontrada'), 404
        else:
            cuadrilla = CuadrillaTipo(organizacion_id=org_id)
            db.session.add(cuadrilla)

        cuadrilla.nombre = data.get('nombre', cuadrilla.nombre)
        cuadrilla.etapa_tipo = data.get('etapa_tipo', cuadrilla.etapa_tipo)
        cuadrilla.tipo_obra = data.get('tipo_obra', cuadrilla.tipo_obra)
        cuadrilla.rendimiento_diario = Decimal(str(data.get('rendimiento_diario', cuadrilla.rendimiento_diario or 0)))
        cuadrilla.unidad_rendimiento = data.get('unidad_rendimiento', cuadrilla.unidad_rendimiento)

        if 'miembros' in data:
            MiembroCuadrilla.query.filter_by(cuadrilla_id=cuadrilla.id).delete() if cuadrilla.id else None
            db.session.flush()

            for m_data in data['miembros']:
                escala = None
                if m_data.get('categoria'):
                    escala = EscalaSalarialUOCRA.query.filter_by(
                        organizacion_id=org_id,
                        categoria=m_data['categoria'],
                        activo=True,
                    ).first()

                miembro = MiembroCuadrilla(
                    cuadrilla_id=cuadrilla.id,
                    escala_id=escala.id if escala else None,
                    rol=m_data['rol'],
                    cantidad=Decimal(str(m_data.get('cantidad', 1))),
                    jornal_override=Decimal(str(m_data['jornal_override'])) if m_data.get('jornal_override') else None,
                )
                db.session.add(miembro)

        db.session.commit()
        return jsonify(ok=True, id=cuadrilla.id, mensaje='Cuadrilla guardada')
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500
