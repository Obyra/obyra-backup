"""Obras -- Certifications + liquidations routes."""
from flask import (render_template, request, flash, redirect,
                   url_for, jsonify, current_app, abort)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
from extensions import db
from models import (
    Obra, EtapaObra, TareaEtapa, CertificacionAvance, WorkCertification,
    TareaAvance,
)
from services.memberships import get_current_org_id, get_current_membership
from services.permissions import validate_obra_ownership, get_org_id
from services.certifications import (
    approved_entries, build_pending_entries, certification_totals,
    create_certification, pending_percentage, register_payment,
    resolve_budget_context,
)
from services.project_shared_service import ProjectSharedService

from obras import (
    obras_bp, _get_roles_usuario, _parse_date, can_manage_obra,
    calcular_costo_materiales, recalc_tarea_pct, sincronizar_estado_obra,
)


@obras_bp.route('/<int:id>/certificar_avance', methods=['POST'])
@login_required
def certificar_avance(id):
    """Compat wrapper: crea certificacion usando el flujo 2.0."""
    obra = Obra.query.get_or_404(id)

    membership = get_current_membership()
    if not membership or membership.org_id != obra.organizacion_id or membership.role not in ('admin', 'project_manager'):
        flash('No tienes permisos para certificar avances.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    porcentaje_avance = request.form.get('porcentaje_avance') or request.form.get('porcentaje')
    if not porcentaje_avance:
        flash('El porcentaje de avance es obligatorio.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    periodo_desde = _parse_date(request.form.get('periodo_desde'))
    periodo_hasta = _parse_date(request.form.get('periodo_hasta'))
    notas = request.form.get('notas')

    try:
        porcentaje = Decimal(str(porcentaje_avance).replace(',', '.'))
        cert = create_certification(
            obra,
            current_user,
            porcentaje,
            periodo=(periodo_desde, periodo_hasta),
            notas=notas,
            aprobar=True,
        )
        db.session.commit()
        flash(
            f'Se registro la certificacion #{cert.id} por {porcentaje}% correctamente.',
            'success',
        )
    except Exception as exc:
        db.session.rollback()
        flash(f'Error al registrar certificacion: {exc}', 'danger')

    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/<int:id>/actualizar_progreso', methods=['POST'])
@login_required
def actualizar_progreso_automatico(id):
    roles = _get_roles_usuario(current_user)
    if not any(r in roles for r in ['administrador', 'tecnico', 'admin']):
        flash('No tienes permisos para actualizar el progreso.', 'danger')
        return redirect(url_for('obras.detalle', id=id))

    org_id = get_current_org_id() or getattr(current_user, 'organizacion_id', None)
    obra = Obra.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

    try:
        progreso_anterior = obra.progreso
        tareas_completadas = 0

        for etapa in obra.etapas:
            for tarea in etapa.tareas:
                recalc_tarea_pct(tarea.id)
                if tarea.estado == 'completada':
                    tareas_completadas += 1

        nuevo_progreso = obra.calcular_progreso_automatico()

        from sqlalchemy import func

        costo_materiales = calcular_costo_materiales(obra.id)

        from models import LiquidacionMO
        costo_mano_obra = db.session.query(
            db.func.coalesce(db.func.sum(LiquidacionMO.monto_total), 0)
        ).filter(LiquidacionMO.obra_id == obra.id).scalar() or Decimal('0')

        obra.costo_real = Decimal(str(costo_materiales)) + Decimal(str(costo_mano_obra))

        db.session.commit()

        flash(
            f'Progreso actualizado de {progreso_anterior}% a {nuevo_progreso}%. '
            f'{tareas_completadas} tareas completadas. '
            f'Costo real: ${float(obra.costo_real):,.2f}',
            'success'
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error actualizando progreso obra {id}")
        flash(f'Error al actualizar progreso: {str(e)}', 'danger')

    return redirect(url_for('obras.detalle', id=id))


@obras_bp.route('/<int:id>/certificaciones', methods=['GET', 'POST'])
@login_required
def historial_certificaciones(id):
    """Historial de certificaciones de una obra"""
    return ProjectSharedService.historial_certificaciones(
        id,
        'obras',
        create_certification,
        certification_totals,
        build_pending_entries,
        approved_entries,
        pending_percentage,
        resolve_budget_context,
        register_payment
    )


# ============================================================
# LIQUIDACION MANO DE OBRA (CERTIFICACION UNIFICADA)
# ============================================================

@obras_bp.route('/<int:obra_id>/certificacion-unificada/preview')
@login_required
def certificacion_unificada_preview(obra_id):
    """API: preview unificado etapas + operarios para un periodo."""
    validate_obra_ownership(obra_id)
    from services.liquidacion_mo import generar_preview_unificado
    desde = request.args.get('desde')
    hasta = request.args.get('hasta')
    if not desde or not hasta:
        return jsonify(ok=False, error='Debe indicar periodo desde/hasta'), 400
    try:
        desde_date = date.fromisoformat(desde)
        hasta_date = date.fromisoformat(hasta)
    except ValueError:
        return jsonify(ok=False, error='Formato de fecha invalido (YYYY-MM-DD)'), 400

    try:
        data = generar_preview_unificado(obra_id, desde_date, hasta_date)
        return jsonify(ok=True, **data)
    except Exception as e:
        current_app.logger.exception("Error en preview unificado")
        return jsonify(ok=True, etapas=[], operarios_sin_etapa=[],
                       tarifa_default=0, ya_certificado_ars=0,
                       presupuesto_total=0, total_certificable=0)


@obras_bp.route('/<int:obra_id>/liquidacion-mo/preview')
@login_required
def liquidacion_mo_preview(obra_id):
    """API: preview de liquidacion para un periodo (legacy)."""
    validate_obra_ownership(obra_id)
    from services.liquidacion_mo import generar_preview_liquidacion
    desde = request.args.get('desde')
    hasta = request.args.get('hasta')
    if not desde or not hasta:
        return jsonify(ok=False, error='Debe indicar periodo desde/hasta'), 400
    try:
        desde_date = date.fromisoformat(desde)
        hasta_date = date.fromisoformat(hasta)
    except ValueError:
        return jsonify(ok=False, error='Formato de fecha invalido (YYYY-MM-DD)'), 400

    items = generar_preview_liquidacion(obra_id, desde_date, hasta_date)
    return jsonify(ok=True, items=items)


@obras_bp.route('/<int:obra_id>/liquidacion-mo', methods=['POST'])
@login_required
def crear_liquidacion_mo(obra_id):
    """Crear una liquidacion de mano de obra."""
    validate_obra_ownership(obra_id)
    from services.liquidacion_mo import crear_liquidacion
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'administrador', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos para crear liquidaciones'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos invalidos'), 400

    try:
        desde = date.fromisoformat(data['periodo_desde'])
        hasta = date.fromisoformat(data['periodo_hasta'])
        items_data = data.get('items', [])
        if not items_data:
            return jsonify(ok=False, error='Debe incluir al menos un operario'), 400

        liq = crear_liquidacion(obra_id, desde, hasta, items_data, notas=data.get('notas'))
        return jsonify(ok=True, liquidacion_id=liq.id, monto_total=float(liq.monto_total))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error creando liquidacion MO")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:obra_id>/liquidacion-mo/auto-fichadas', methods=['POST'])
@login_required
def auto_liquidacion_desde_fichadas(obra_id):
    """Genera automaticamente una liquidacion MO a partir de las fichadas del periodo.

    Body JSON: { periodo_desde, periodo_hasta, notas? }
    No requiere preview ni edicion: lee fichadas, calcula con tarifa default
    de la obra y crea la liquidacion en un solo paso.
    """
    validate_obra_ownership(obra_id)
    from services.liquidacion_mo import generar_liquidacion_desde_fichadas
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'administrador', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos para crear liquidaciones'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos invalidos'), 400

    try:
        desde = date.fromisoformat(data['periodo_desde'])
        hasta = date.fromisoformat(data['periodo_hasta'])
    except (KeyError, ValueError):
        return jsonify(ok=False, error='Formato de fecha invalido (YYYY-MM-DD)'), 400

    if desde > hasta:
        return jsonify(ok=False, error='La fecha desde debe ser anterior a hasta'), 400

    try:
        liq, resumen = generar_liquidacion_desde_fichadas(
            obra_id, desde, hasta, notas=data.get('notas')
        )
        if liq is None:
            return jsonify(ok=False, error=resumen.get('error', 'Error desconocido')), 400

        return jsonify(
            ok=True,
            liquidacion_id=liq.id,
            monto_total=resumen['monto_total'],
            operarios_liquidados=resumen['operarios_liquidados'],
            operarios_sin_horas=resumen['operarios_sin_horas'],
            tarifa_hora=resumen['tarifa_hora'],
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error generando liquidacion auto desde fichadas")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:obra_id>/liquidacion-mo/confirmar-y-pagar', methods=['POST'])
@login_required
def confirmar_y_pagar_liquidacion(obra_id):
    """Crea liquidacion + marca como pagado + actualiza costo_real en un solo paso."""
    validate_obra_ownership(obra_id)
    from services.liquidacion_mo import crear_liquidacion, registrar_pago_item
    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'administrador', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error='Datos invalidos'), 400

    try:
        desde = date.fromisoformat(data['periodo_desde'])
        hasta = date.fromisoformat(data['periodo_hasta'])
        items_data = data.get('items', [])
        metodo_pago = data.get('metodo_pago', 'transferencia')
        if not items_data:
            return jsonify(ok=False, error='Debe incluir al menos un operario'), 400

        liq = crear_liquidacion(obra_id, desde, hasta, items_data, notas=data.get('notas'), commit=False)
        db.session.flush()

        for item in liq.items.all():
            item.estado = 'pagado'
            item.metodo_pago = metodo_pago
            item.fecha_pago = date.today()
            item.pagado_por_id = current_user.id
            item.pagado_at = datetime.utcnow()

        liq.estado = 'pagado'

        from services.liquidacion_mo import _decimal
        from models.templates import LiquidacionMOItem, LiquidacionMO as LiqMO
        obra = validate_obra_ownership(obra_id)

        costo_mo_pagado = _decimal(
            db.session.query(db.func.coalesce(db.func.sum(LiquidacionMOItem.monto), 0))
            .join(LiqMO)
            .filter(LiqMO.obra_id == obra_id, LiquidacionMOItem.estado == 'pagado')
            .scalar()
        ) + _decimal(liq.monto_total)

        costo_materiales = calcular_costo_materiales(obra_id)
        obra.costo_real = float(costo_materiales + costo_mo_pagado)

        db.session.commit()
        return jsonify(
            ok=True,
            liquidacion_id=liq.id,
            monto_total=float(liq.monto_total),
            costo_real_obra=obra.costo_real,
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error en confirmar y pagar liquidacion MO")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/liquidacion-mo/item/<int:item_id>/recibo-pdf')
@login_required
def recibo_liquidacion_pdf(item_id):
    """Genera PDF de recibo de pago de un item de liquidacion."""
    from models.templates import LiquidacionMOItem
    try:
        from weasyprint import HTML
    except ImportError:
        flash('La exportacion a PDF no esta disponible.', 'warning')
        return redirect(request.referrer or url_for('index'))

    item = LiquidacionMOItem.query.get_or_404(item_id)
    if item.liquidacion.obra.organizacion_id != get_current_org_id():
        abort(403)
    liq = item.liquidacion
    obra = liq.obra
    org_id = get_org_id()
    if not org_id or obra.organizacion_id != org_id:
        abort(404)
    org = obra.organizacion if hasattr(obra, 'organizacion') else None

    html_content = render_template('obras/recibo_liquidacion_pdf.html',
        item=item,
        liquidacion=liq,
        obra=obra,
        organizacion=org,
        fecha_generacion=datetime.now().strftime('%d/%m/%Y %H:%M'),
    )

    import io
    from flask import send_file
    pdf_buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)

    nombre_op = item.operario.nombre_completo if item.operario else 'operario'
    nombre_safe = nombre_op.replace(' ', '_')[:30]
    filename = f"recibo_{nombre_safe}_{liq.periodo_desde.strftime('%Y%m%d')}.pdf"

    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)


@obras_bp.route('/liquidacion-mo/<int:liq_id>/recibo-pdf')
@login_required
def recibo_liquidacion_completa_pdf(liq_id):
    """Genera PDF de recibo de toda una liquidacion (todos los operarios)."""
    from models.templates import LiquidacionMO as LiqMO
    try:
        from weasyprint import HTML
    except ImportError:
        flash('La exportacion a PDF no esta disponible.', 'warning')
        return redirect(request.referrer or url_for('index'))

    liq = LiqMO.query.get_or_404(liq_id)
    if liq.obra.organizacion_id != get_current_org_id():
        abort(403)
    obra = liq.obra
    org_id = get_org_id()
    if not org_id or obra.organizacion_id != org_id:
        abort(404)
    org = obra.organizacion if hasattr(obra, 'organizacion') else None
    items = liq.items.all()

    html_content = render_template('obras/recibo_liquidacion_pdf.html',
        item=None,
        items=items,
        liquidacion=liq,
        obra=obra,
        organizacion=org,
        fecha_generacion=datetime.now().strftime('%d/%m/%Y %H:%M'),
    )

    import io
    from flask import send_file
    pdf_buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)

    filename = f"liquidacion_{liq.periodo_desde.strftime('%Y%m%d')}_{liq.periodo_hasta.strftime('%Y%m%d')}.pdf"
    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)


@obras_bp.route('/liquidacion-mo/item/<int:item_id>/pagar', methods=['POST'])
@login_required
def pagar_liquidacion_mo_item(item_id):
    """Registrar pago de un item de liquidacion."""
    from services.liquidacion_mo import registrar_pago_item
    from models.templates import LiquidacionMOItem as LiqMOItem
    item_check = LiqMOItem.query.get_or_404(item_id)
    if item_check.liquidacion.obra.organizacion_id != get_current_org_id():
        abort(403)

    roles = _get_roles_usuario(current_user)
    if not (roles & {'admin', 'pm', 'administrador', 'project_manager'}):
        return jsonify(ok=False, error='Sin permisos'), 403

    from models.templates import LiquidacionMOItem
    liq_item = LiquidacionMOItem.query.get_or_404(item_id)
    org_id = get_org_id()
    if not org_id or liq_item.liquidacion.obra.organizacion_id != org_id:
        abort(404)

    data = request.get_json(silent=True) or {}
    try:
        metodo = data.get('metodo_pago', 'transferencia')
        fecha = date.fromisoformat(data['fecha_pago']) if data.get('fecha_pago') else date.today()
        comprobante = data.get('comprobante_url')
        notas = data.get('notas')

        item = registrar_pago_item(item_id, metodo, fecha, comprobante, notas)
        return jsonify(ok=True, estado=item.estado, liquidacion_estado=item.liquidacion.estado)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Error registrando pago liquidacion MO")
        return jsonify(ok=False, error=str(e)), 500


@obras_bp.route('/<int:obra_id>/liquidacion-mo/historial')
@login_required
def liquidacion_mo_historial(obra_id):
    """API: obtener historial de liquidaciones de una obra."""
    validate_obra_ownership(obra_id)
    try:
        from services.liquidacion_mo import obtener_liquidaciones_obra
        liquidaciones = obtener_liquidaciones_obra(obra_id)
        result = []
        for liq in liquidaciones:
            items = []
            for item in liq.items.all():
                items.append({
                    'id': item.id,
                    'operario_id': item.operario_id,
                    'operario_nombre': item.operario.nombre_completo if item.operario else 'N/A',
                    'horas_avance': float(item.horas_avance or 0),
                    'horas_fichadas': float(item.horas_fichadas or 0),
                    'horas_liquidadas': float(item.horas_liquidadas or 0),
                    'tarifa_hora': float(item.tarifa_hora or 0),
                    'monto': float(item.monto or 0),
                    'estado': item.estado,
                    'metodo_pago': item.metodo_pago,
                    'fecha_pago': item.fecha_pago.isoformat() if item.fecha_pago else None,
                    'comprobante_url': item.comprobante_url,
                })
            result.append({
                'id': liq.id,
                'periodo_desde': liq.periodo_desde.isoformat(),
                'periodo_hasta': liq.periodo_hasta.isoformat(),
                'estado': liq.estado,
                'monto_total': float(liq.monto_total or 0),
                'notas': liq.notas,
                'created_at': liq.created_at.isoformat() if liq.created_at else None,
                'created_by': liq.created_by.nombre_completo if liq.created_by else 'N/A',
                'items': items,
            })
        return jsonify(ok=True, liquidaciones=result)
    except Exception as e:
        if 'liquidaciones_mo' in str(e).lower() or 'relation' in str(e).lower():
            try:
                db.session.rollback()
                db.create_all()
                db.session.commit()
                current_app.logger.info("Tablas de liquidacion MO creadas automaticamente")
                return jsonify(ok=True, liquidaciones=[])
            except Exception:
                pass
        db.session.rollback()
        current_app.logger.exception("Error en historial liquidacion MO")
        return jsonify(ok=True, liquidaciones=[])


@obras_bp.route('/certificacion/<int:id>/desactivar', methods=['POST'])
@login_required
def desactivar_certificacion(id):
    roles = _get_roles_usuario(current_user)
    if 'administrador' not in roles and 'admin' not in roles:
        flash('Solo los administradores pueden desactivar certificaciones.', 'danger')
        return redirect(url_for('reportes.dashboard'))

    certificacion = CertificacionAvance.query.get_or_404(id)
    if certificacion.obra.organizacion_id != get_current_org_id():
        abort(403)
    obra = certificacion.obra
    org_id = get_org_id()
    if not org_id or obra.organizacion_id != org_id:
        abort(404)

    try:
        certificacion.activa = False
        obra.costo_real -= certificacion.costo_certificado
        obra.calcular_progreso_automatico()
        db.session.commit()
        flash('Certificacion desactivada exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al desactivar certificacion: {str(e)}', 'danger')

    return redirect(url_for('obras.historial_certificaciones', id=obra.id))


@obras_bp.route('/certificaciones/<int:cert_id>/pagos', methods=['POST'])
@login_required
def registrar_pago_certificacion(cert_id):
    certificacion = WorkCertification.query.get_or_404(cert_id)
    obra = certificacion.obra

    membership = get_current_membership()
    if not membership or membership.org_id != obra.organizacion_id or membership.role not in ('admin', 'project_manager'):
        error_msg = 'No tienes permisos para registrar pagos.'
        if request.is_json:
            return jsonify(ok=False, error=error_msg), 403
        flash(error_msg, 'danger')
        return redirect(url_for('obras.historial_certificaciones', id=obra.id))

    data = request.get_json(silent=True) or request.form
    monto_raw = data.get('monto')
    metodo = data.get('metodo') or data.get('metodo_pago')
    if not monto_raw or not metodo:
        msg = 'Debe indicar monto y metodo de pago.'
        if request.is_json:
            return jsonify(ok=False, error=msg), 400
        flash(msg, 'danger')
        return redirect(url_for('obras.historial_certificaciones', id=obra.id))

    moneda = (data.get('moneda') or 'ARS').upper()
    notas = data.get('notas')
    tc_usd = data.get('tc_usd') or data.get('tc_usd_pago')
    fecha_pago = _parse_date(data.get('fecha_pago'))
    operario_id = data.get('operario_id') or data.get('usuario_id')
    try:
        operario_id = int(operario_id) if operario_id else None
    except (TypeError, ValueError):
        operario_id = None

    try:
        monto = Decimal(str(monto_raw).replace(',', '.'))
        payment = register_payment(
            certificacion,
            obra,
            current_user,
            monto=monto,
            metodo=metodo,
            moneda=moneda,
            fecha=fecha_pago,
            tc_usd=Decimal(str(tc_usd).replace(',', '.')) if tc_usd else None,
            notas=notas,
            operario_id=operario_id,
            comprobante_url=data.get('comprobante_url'),
        )
        db.session.commit()
        payload = {'ok': True, 'pago_id': payment.id, 'certificacion_id': certificacion.id}
        if request.is_json:
            return jsonify(payload)
        flash('Pago registrado correctamente.', 'success')
    except Exception as exc:
        db.session.rollback()
        if request.is_json:
            return jsonify(ok=False, error=str(exc)), 400
        flash(f'Error al registrar el pago: {exc}', 'danger')

    return redirect(url_for('obras.historial_certificaciones', id=obra.id))
