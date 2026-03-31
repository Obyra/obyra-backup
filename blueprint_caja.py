"""
Blueprint para CAJA - Transferencias oficina <-> obra

Gestiona transferencias de dinero desde la oficina central a las obras
para compras rápidas y solucionar demoras en compras formales.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import func

caja_bp = Blueprint('caja', __name__, url_prefix='/caja')


def _tiene_permiso_caja():
    """Admin puede todo, PM puede ver/registrar gastos en sus obras."""
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm')


def _es_admin():
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role == 'admin'


def saldo_caja_obra(obra_id):
    """Calcula saldo disponible en caja de una obra."""
    from models.templates import MovimientoCaja

    ingresos = db.session.query(
        func.coalesce(func.sum(MovimientoCaja.monto), 0)
    ).filter(
        MovimientoCaja.obra_id == obra_id,
        MovimientoCaja.estado == 'confirmado',
        MovimientoCaja.tipo == 'transferencia_a_obra'
    ).scalar()

    egresos = db.session.query(
        func.coalesce(func.sum(MovimientoCaja.monto), 0)
    ).filter(
        MovimientoCaja.obra_id == obra_id,
        MovimientoCaja.estado == 'confirmado',
        MovimientoCaja.tipo.in_(['devolucion_obra', 'pago_proveedor', 'gasto_obra'])
    ).scalar()

    return float(ingresos) - float(egresos)


# ============================================================
# DASHBOARD DE CAJA
# ============================================================

@caja_bp.route('/')
@login_required
def dashboard():
    from models.templates import MovimientoCaja
    from models.projects import Obra

    if not _tiene_permiso_caja():
        flash('No tiene permisos para acceder a Caja.', 'danger')
        return redirect(url_for('main.dashboard'))

    org_id = current_user.organizacion_id

    obras = Obra.query.filter_by(organizacion_id=org_id).filter(Obra.deleted_at.is_(None)).order_by(Obra.nombre).all()

    # Calcular saldo por obra
    resumen_obras = []
    for obra in obras:
        saldo = saldo_caja_obra(obra.id)
        # Totales por tipo
        transferido = db.session.query(
            func.coalesce(func.sum(MovimientoCaja.monto), 0)
        ).filter(
            MovimientoCaja.obra_id == obra.id,
            MovimientoCaja.estado == 'confirmado',
            MovimientoCaja.tipo == 'transferencia_a_obra'
        ).scalar()

        gastado = db.session.query(
            func.coalesce(func.sum(MovimientoCaja.monto), 0)
        ).filter(
            MovimientoCaja.obra_id == obra.id,
            MovimientoCaja.estado == 'confirmado',
            MovimientoCaja.tipo.in_(['devolucion_obra', 'pago_proveedor', 'gasto_obra'])
        ).scalar()

        if float(transferido) > 0 or float(gastado) > 0:
            resumen_obras.append({
                'obra': obra,
                'transferido': float(transferido),
                'gastado': float(gastado),
                'saldo': saldo,
            })

    # Últimos movimientos
    movimientos = MovimientoCaja.query.filter_by(
        organizacion_id=org_id
    ).order_by(MovimientoCaja.created_at.desc()).limit(20).all()

    # Pendientes de confirmación
    pendientes = MovimientoCaja.query.filter_by(
        organizacion_id=org_id, estado='pendiente'
    ).count()

    return render_template('caja/dashboard.html',
                         resumen_obras=resumen_obras,
                         movimientos=movimientos,
                         pendientes=pendientes,
                         obras=obras)


# ============================================================
# MOVIMIENTOS DE UNA OBRA
# ============================================================

@caja_bp.route('/obra/<int:id>')
@login_required
def obra(id):
    from models.templates import MovimientoCaja
    from models.projects import Obra

    if not _tiene_permiso_caja():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('main.dashboard'))

    obra = Obra.query.get_or_404(id)
    if obra.organizacion_id != current_user.organizacion_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('caja.dashboard'))

    movimientos = MovimientoCaja.query.filter_by(
        obra_id=id
    ).order_by(MovimientoCaja.fecha_movimiento.desc(), MovimientoCaja.created_at.desc()).all()

    saldo = saldo_caja_obra(id)

    return render_template('caja/obra.html',
                         obra=obra, movimientos=movimientos, saldo=saldo)


# ============================================================
# TRANSFERIR DINERO A OBRA
# ============================================================

@caja_bp.route('/transferir', methods=['POST'])
@login_required
def transferir():
    from models.templates import MovimientoCaja

    if not _es_admin():
        flash('Solo administradores pueden realizar transferencias.', 'danger')
        return redirect(url_for('caja.dashboard'))

    org_id = current_user.organizacion_id

    try:
        obra_id = request.form.get('obra_id', type=int)
        monto_str = request.form.get('monto', '0')
        concepto = request.form.get('concepto', '').strip()
        referencia = request.form.get('referencia', '').strip()
        fecha_str = request.form.get('fecha_movimiento', '')
        notas = request.form.get('notas', '').strip()

        if not obra_id or not concepto:
            flash('Obra y concepto son obligatorios.', 'danger')
            return redirect(url_for('caja.dashboard'))

        try:
            monto = Decimal(str(monto_str).replace(',', '.'))
        except Exception:
            monto = Decimal('0')

        if monto <= 0:
            flash('El monto debe ser mayor a 0.', 'danger')
            return redirect(url_for('caja.dashboard'))

        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else date.today()
        except ValueError:
            fecha = date.today()

        mov = MovimientoCaja(
            numero=MovimientoCaja.generar_numero(org_id),
            organizacion_id=org_id,
            obra_id=obra_id,
            tipo='transferencia_a_obra',
            monto=monto,
            concepto=concepto,
            referencia=referencia,
            fecha_movimiento=fecha,
            estado='confirmado',  # Transferencias del admin se confirman directamente
            notas=notas,
            created_by_id=current_user.id,
            confirmado_por_id=current_user.id,
            fecha_confirmacion=datetime.utcnow(),
        )
        db.session.add(mov)
        db.session.commit()

        flash(f'Transferencia {mov.numero} registrada por ${monto:,.2f}', 'success')
        return redirect(url_for('caja.obra', id=obra_id))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en transferencia: {e}")
        flash(f'Error al registrar transferencia: {str(e)}', 'danger')
        return redirect(url_for('caja.dashboard'))


# ============================================================
# REGISTRAR GASTO DESDE CAJA DE OBRA
# ============================================================

@caja_bp.route('/gasto', methods=['POST'])
@login_required
def gasto():
    from models.templates import MovimientoCaja

    if not _tiene_permiso_caja():
        flash('No tiene permisos.', 'danger')
        return redirect(url_for('caja.dashboard'))

    org_id = current_user.organizacion_id

    try:
        obra_id = request.form.get('obra_id', type=int)
        tipo = request.form.get('tipo', 'gasto_obra')
        monto_str = request.form.get('monto', '0')
        concepto = request.form.get('concepto', '').strip()
        referencia = request.form.get('referencia', '').strip()
        fecha_str = request.form.get('fecha_movimiento', '')
        notas = request.form.get('notas', '').strip()

        if tipo not in ('gasto_obra', 'pago_proveedor', 'devolucion_obra'):
            tipo = 'gasto_obra'

        if not obra_id or not concepto:
            flash('Obra y concepto son obligatorios.', 'danger')
            return redirect(url_for('caja.obra', id=obra_id) if obra_id else url_for('caja.dashboard'))

        try:
            monto = Decimal(str(monto_str).replace(',', '.'))
        except Exception:
            monto = Decimal('0')

        if monto <= 0:
            flash('El monto debe ser mayor a 0.', 'danger')
            return redirect(url_for('caja.obra', id=obra_id))

        # Verificar saldo suficiente
        saldo = saldo_caja_obra(obra_id)
        if float(monto) > saldo:
            flash(f'Saldo insuficiente. Disponible: ${saldo:,.2f}', 'danger')
            return redirect(url_for('caja.obra', id=obra_id))

        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else date.today()
        except ValueError:
            fecha = date.today()

        mov = MovimientoCaja(
            numero=MovimientoCaja.generar_numero(org_id),
            organizacion_id=org_id,
            obra_id=obra_id,
            tipo=tipo,
            monto=monto,
            concepto=concepto,
            referencia=referencia,
            fecha_movimiento=fecha,
            estado='confirmado',
            notas=notas,
            created_by_id=current_user.id,
            confirmado_por_id=current_user.id,
            fecha_confirmacion=datetime.utcnow(),
        )
        db.session.add(mov)
        db.session.commit()

        flash(f'Gasto {mov.numero} registrado por ${monto:,.2f}', 'success')
        return redirect(url_for('caja.obra', id=obra_id))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en gasto: {e}")
        flash(f'Error al registrar gasto: {str(e)}', 'danger')
        return redirect(url_for('caja.dashboard'))


# ============================================================
# ANULAR MOVIMIENTO
# ============================================================

@caja_bp.route('/<int:id>/anular', methods=['POST'])
@login_required
def anular(id):
    from models.templates import MovimientoCaja

    if not _es_admin():
        flash('Solo administradores pueden anular movimientos.', 'danger')
        return redirect(url_for('caja.dashboard'))

    mov = MovimientoCaja.query.get_or_404(id)
    if mov.organizacion_id != current_user.organizacion_id:
        flash('No tiene acceso.', 'danger')
        return redirect(url_for('caja.dashboard'))

    if mov.estado == 'anulado':
        flash('Este movimiento ya esta anulado.', 'warning')
        return redirect(url_for('caja.obra', id=mov.obra_id))

    mov.estado = 'anulado'
    db.session.commit()
    flash(f'Movimiento {mov.numero} anulado.', 'info')
    return redirect(url_for('caja.obra', id=mov.obra_id))


# ============================================================
# API: Saldo de obra (para usar desde obra detalle)
# ============================================================

@caja_bp.route('/api/saldo/<int:obra_id>')
@login_required
def api_saldo(obra_id):
    if not _tiene_permiso_caja():
        return jsonify(ok=False, error='Sin permisos'), 403

    saldo = saldo_caja_obra(obra_id)
    return jsonify(ok=True, saldo=saldo)
