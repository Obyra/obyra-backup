# -*- coding: utf-8 -*-
"""Pantalla de confirmacion de vinculos entre el pliego y el inventario.

    GET   /presupuestos/<id>/vincular-inventario           -> pantalla
    POST  /presupuestos/<id>/vincular-inventario/guardar   -> persiste lo confirmado
    GET   /presupuestos/<id>/vincular-inventario/buscar    -> buscador manual

El import NO escribe vinculos: las propuestas se calculan al vuelo acá y solo se
guarda lo que el usuario confirma. Ver services/vinculacion_inventario.py.
"""
from __future__ import annotations

from flask import (render_template, request, jsonify, redirect, url_for,
                   flash, current_app)
from flask_login import login_required, current_user
from sqlalchemy import or_

from services.memberships import get_current_org_id
from services.vinculacion_inventario import preparar_pantalla, guardar_vinculos
from blueprint_presupuestos import presupuestos_bp


def _es_super_admin():
    return bool(getattr(current_user, 'is_super_admin', False))


def _verificar_acceso_presupuesto(presupuesto):
    """Mismo criterio que el resto del modulo (analisis_ia, generador_preliminar)."""
    if not current_user.is_authenticated:
        return False
    if _es_super_admin():
        return True
    return presupuesto.organizacion_id == get_current_org_id()


def _puede_gestionar():
    """Confirmar un vinculo habilita reservar stock real contra el deposito:
    es una accion de gestion, no de lectura."""
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm', 'project_manager')


@presupuestos_bp.route('/<int:id>/vincular-inventario')
@login_required
def vincular_inventario(id):
    from models.budgets import Presupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        flash('No tenés acceso a este presupuesto.', 'danger')
        return redirect(url_for('presupuestos.lista'))

    org_id = get_current_org_id() or presupuesto.organizacion_id
    datos = preparar_pantalla(presupuesto, org_id)

    return render_template('presupuestos/vincular_inventario.html',
                           presupuesto=presupuesto,
                           puede_gestionar=_puede_gestionar(),
                           **datos)


@presupuestos_bp.route('/<int:id>/vincular-inventario/guardar', methods=['POST'])
@login_required
def vincular_inventario_guardar(id):
    from models.budgets import Presupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403
    if not _puede_gestionar():
        return jsonify({'ok': False, 'error': 'Sin permisos para modificar'}), 403

    data = request.get_json(silent=True) or {}
    seleccion = data.get('seleccion')
    if not isinstance(seleccion, list):
        return jsonify({'ok': False, 'error': 'Formato invalido'}), 400

    org_id = get_current_org_id() or presupuesto.organizacion_id
    try:
        res = guardar_vinculos(presupuesto, org_id, current_user.id, seleccion)
    except (KeyError, TypeError, ValueError):
        # Body malformado (falta item_id, cantidad no numerica, etc.)
        return jsonify({'ok': False, 'error': 'Datos invalidos'}), 400
    except Exception:
        from extensions import db
        db.session.rollback()
        current_app.logger.exception(
            f"Error guardando vinculos de inventario (pres={id})")
        return jsonify({'ok': False, 'error': 'No se pudo guardar'}), 500

    current_app.logger.info(
        f"Vinculacion inventario pres={id}: {res['vinculados']} vinculos "
        f"en {res['renglones']} renglones (user={current_user.id})")
    return jsonify({'ok': True, **res})


@presupuestos_bp.route('/<int:id>/vincular-inventario/buscar')
@login_required
def vincular_inventario_buscar(id):
    """Buscador del balde 'sin vincular'. Devuelve solo lo que la pantalla
    muestra: nombre, unidad y stock. Siempre filtrado por la org del usuario."""
    from models.budgets import Presupuesto
    from models.inventory import ItemInventario

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    term = (request.args.get('q') or '').strip()
    if len(term) < 2:
        return jsonify({'ok': True, 'items': []})

    org_id = get_current_org_id() or presupuesto.organizacion_id
    like = f'%{term}%'
    filas = (ItemInventario.query
             .with_entities(ItemInventario.id, ItemInventario.nombre,
                            ItemInventario.unidad, ItemInventario.codigo,
                            ItemInventario.stock_actual)
             .filter(ItemInventario.organizacion_id == org_id,
                     ItemInventario.activo.is_(True),
                     or_(ItemInventario.nombre.ilike(like),
                         ItemInventario.codigo.ilike(like)))
             .order_by(ItemInventario.nombre)
             .limit(20)
             .all())

    return jsonify({'ok': True, 'items': [
        {'id': f.id, 'nombre': f.nombre, 'unidad': f.unidad or '',
         'codigo': f.codigo or '', 'stock': float(f.stock_actual or 0)}
        for f in filas]})
