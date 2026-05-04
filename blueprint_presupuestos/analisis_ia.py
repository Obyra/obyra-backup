"""Análisis IA sobre presupuestos importados desde Excel de licitación.

Endpoints:
  POST /presupuestos/<id>/analizar-ia          -> devuelve sugerencias (no toca BD)
  POST /presupuestos/<id>/aplicar-analisis-ia  -> aplica sugerencias seleccionadas

Reusa el servicio determinístico services/analisis_ia_presupuesto.py.
"""
from __future__ import annotations

from datetime import datetime
from flask import request, jsonify, current_app
from flask_login import login_required, current_user

from extensions import db
from services.memberships import get_current_org_id
from blueprint_presupuestos import presupuestos_bp


def _es_super_admin():
    return bool(getattr(current_user, 'is_super_admin', False))


def _verificar_acceso_presupuesto(presupuesto):
    """Devuelve True si el usuario actual puede ver/editar este presupuesto."""
    if not current_user.is_authenticated:
        return False
    if _es_super_admin():
        return True
    org_id = get_current_org_id()
    return presupuesto.organizacion_id == org_id


def _puede_gestionar():
    """admin | administrador | pm | project_manager pueden modificar."""
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm', 'project_manager')


@presupuestos_bp.route('/<int:id>/analizar-ia', methods=['POST'])
@login_required
def analizar_ia(id):
    """Analiza los ítems del presupuesto y devuelve sugerencias IA.

    NO modifica la base de datos. Solo retorna la propuesta.
    """
    from models.budgets import Presupuesto, ItemPresupuesto
    from services.analisis_ia_presupuesto import analizar_items_con_ia

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    # Solo items "del cliente" (excluye items internos del Ejecutivo APU)
    items = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
        solo_interno=False,
    ).order_by(ItemPresupuesto.id).all()

    if not items:
        return jsonify(ok=False, error='El presupuesto no tiene ítems para analizar.'), 400

    payload = [{
        'id': it.id,
        'descripcion': it.descripcion,
        'unidad': it.unidad,
        'cantidad': float(it.cantidad or 0),
        'etapa_nombre': it.etapa_nombre,
        'tipo': it.tipo,
    } for it in items]

    # Fase 2: pasar contexto tecnico (perfil + niveles) si el presupuesto
    # tiene perfil cargado. Si no, contexto=None y la IA se comporta como antes.
    contexto = None
    try:
        from services.perfil_tecnico_service import construir_contexto_ia
        contexto = construir_contexto_ia(presupuesto)
    except Exception:
        contexto = None

    try:
        resultado = analizar_items_con_ia(payload, contexto=contexto)
    except Exception as e:
        current_app.logger.exception('Error analizando con IA')
        return jsonify(ok=False, error=f'Error en analisis IA: {type(e).__name__}'), 500

    # Fase 3.5: enriquecer respuesta con estados operativos del Generador
    # Preliminar IA. La logica interna de confianza no se toca; solo se
    # mapea a estados de negocio para la UX. Si el servicio no existe o falla,
    # se omite y la respuesta sigue funcionando (compat).
    try:
        from services.estado_operativo_service import (
            calcular_resumen, metadatos_todos_estados,
        )
        perfil_dict = (contexto or {}).get('perfil_tecnico') if contexto else None
        resumen = calcular_resumen(
            items_resultado=resultado.get('items', []),
            perfil_tecnico=perfil_dict,
            items_db=items,
        )
        resultado['estados_operativos'] = {
            'catalogo': metadatos_todos_estados(),
            'kpis': resumen['kpis'],
            'porcentaje_listos': resumen['porcentaje_listos'],
            'estados_por_item': resumen['estados_por_item'],
        }
    except Exception:
        current_app.logger.exception('No se pudo calcular estados operativos')

    resultado['ok'] = True
    return jsonify(resultado)


@presupuestos_bp.route('/<int:id>/aplicar-analisis-ia', methods=['POST'])
@login_required
def aplicar_analisis_ia(id):
    """Aplica las sugerencias seleccionadas a los ítems del presupuesto.

    Body JSON:
      {
        "items": [
          {
            "item_id": 123,
            "aplicar": true,
            "descripcion": "...",   # opcional, lo nuevo
            "unidad": "m2",         # opcional
            "etapa_nombre": "...",  # opcional
            "analisis": { ... }     # opcional, blob completo a guardar
          },
          ...
        ]
      }

    Para cada item donde aplicar=true:
      - Si descripcion_original esta vacio, copia la descripcion actual ahi.
      - Si unidad_original esta vacio, copia la unidad actual.
      - Aplica los cambios al item (descripcion / unidad / etapa_nombre).
      - Guarda el blob analisis en analisis_ia.
      - Marca revisado_ia=True, fecha_analisis_ia=now.
    """
    from models.budgets import Presupuesto, ItemPresupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403
    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(ok=False, error=f'No se puede modificar presupuesto en estado {presupuesto.estado}'), 400

    data = request.get_json(silent=True) or {}
    items_payload = data.get('items') or []
    if not isinstance(items_payload, list) or not items_payload:
        return jsonify(ok=False, error='items es obligatorio'), 400

    # Cargar items en una sola query (evitar N+1)
    item_ids = [int(p.get('item_id')) for p in items_payload if p.get('item_id')]
    items_db = {it.id: it for it in ItemPresupuesto.query.filter(
        ItemPresupuesto.id.in_(item_ids),
        ItemPresupuesto.presupuesto_id == presupuesto.id,
    ).all()}

    aplicados = 0
    omitidos = 0
    errores = []
    aprendizaje_logs = 0
    aprendizaje_candidatas_nuevas = 0
    now = datetime.utcnow()

    # Servicio de aprendizaje IA (Fase B). Se importa una sola vez fuera del
    # loop. Si la importacion falla, el endpoint sigue funcionando pero sin
    # aprendizaje (defensa en profundidad).
    try:
        from services.ia_learning_service import registrar_aplicacion_ia
    except Exception:
        registrar_aplicacion_ia = None

    org_id = get_current_org_id()

    for entry in items_payload:
        if not entry.get('aplicar'):
            omitidos += 1
            continue
        try:
            item_id = int(entry.get('item_id'))
        except (TypeError, ValueError):
            errores.append({'entry': entry, 'error': 'item_id invalido'})
            continue
        item = items_db.get(item_id)
        if not item:
            errores.append({'item_id': item_id, 'error': 'no encontrado o no pertenece al presupuesto'})
            continue

        try:
            # 1. Preservar original (solo la primera vez)
            if not item.descripcion_original:
                item.descripcion_original = item.descripcion
            if not item.unidad_original:
                item.unidad_original = item.unidad

            # 2. Aplicar cambios solo si vienen explicitos
            if entry.get('descripcion'):
                item.descripcion = str(entry['descripcion']).strip()[:300]
            if entry.get('unidad'):
                item.unidad = str(entry['unidad']).strip()[:20]
            if entry.get('etapa_nombre'):
                item.etapa_nombre = str(entry['etapa_nombre']).strip()[:100] or None

            # 3. Guardar blob de analisis (incluye sugerencias completas)
            analisis = entry.get('analisis')
            if analisis is not None:
                item.analisis_ia = analisis

            # 4. Auditoria item-level
            item.revisado_ia = True
            item.fecha_analisis_ia = now

            aplicados += 1

            # 5. Aprendizaje IA continuo (fail-safe via savepoint)
            if registrar_aplicacion_ia is not None:
                res = registrar_aplicacion_ia(
                    item=item,
                    entry=entry,
                    presupuesto=presupuesto,
                    user_id=current_user.id if current_user.is_authenticated else None,
                    organizacion_id=org_id,
                )
                if res and not res.get('error'):
                    aprendizaje_logs += 1
                    if res.get('es_nueva_candidata'):
                        aprendizaje_candidatas_nuevas += 1
        except Exception as e:
            errores.append({'item_id': item_id, 'error': str(e)})

    if aplicados:
        # Audit: aplicacion de analisis IA
        try:
            from models.audit import registrar_audit
            registrar_audit(
                accion='aplicar_ia',
                entidad='presupuesto',
                entidad_id=presupuesto.id,
                detalle=f'Aplicacion de sugerencias IA: {aplicados} items modificados',
            )
        except Exception:
            pass

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Error commiteando aplicar_analisis_ia')
            return jsonify(ok=False, error=f'Error al guardar: {type(e).__name__}'), 500
    else:
        db.session.rollback()

    return jsonify(
        ok=True,
        aplicados=aplicados,
        omitidos=omitidos,
        errores=errores,
        aprendizaje={
            'logs_creados': aprendizaje_logs,
            'candidatas_nuevas': aprendizaje_candidatas_nuevas,
        },
    )
