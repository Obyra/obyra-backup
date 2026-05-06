"""Análisis IA sobre presupuestos importados desde Excel de licitación.

Endpoints:
  POST /presupuestos/<id>/analizar-ia                     -> devuelve sugerencias (no toca BD)
  POST /presupuestos/<id>/aplicar-analisis-ia             -> aplica seleccionadas (modo experto)
  POST /presupuestos/<id>/items/<iid>/clasificar          -> clasificacion manual de un pendiente
  GET  /presupuestos/api/rubros-tecnicos                  -> lista rubros/etapas/unidades para dropdowns

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
    perfil_dict = (contexto or {}).get('perfil_tecnico') if contexto else None
    items_reconocidos = 0
    try:
        from services.estado_operativo_service import (
            calcular_resumen, metadatos_todos_estados,
        )
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
        # Contar items reconocidos = todos menos no_reconocidos
        items_reconocidos = (resumen['total'] - (resumen['kpis'].get('no_reconocido') or 0))
    except Exception:
        current_app.logger.exception('No se pudo calcular estados operativos')

    # Fase 3.5: avance del Presupuesto Preliminar hacia el 90%.
    # Calcula los componentes posibles HOY. Los componentes de Fases 4/5
    # (composicion, precios, MO/equipos, margen) quedan en 0 hasta que se
    # activen. Esta es la metrica que ve el usuario en la vista simple.
    try:
        from services.avance_presupuesto_service import calcular_avance
        avance = calcular_avance(
            total_items=len(items),
            items_reconocidos=items_reconocidos,
            perfil_tecnico=perfil_dict,
            estados_kpis=(resultado.get('estados_operativos') or {}).get('kpis'),
            presupuesto=presupuesto,
        )
        resultado['avance_preliminar'] = avance
    except Exception:
        current_app.logger.exception('No se pudo calcular avance preliminar')

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


# ============================================================
# Resolver items pendientes (clasificacion manual basica)
# ============================================================

UNIDADES_DISPONIBLES = (
    'm', 'm2', 'm3', 'kg', 'tn', 'l', 'h', 'dia', 'mes', 'jornal',
    'unidad', 'gl', 'bolsa', 'caja', 'par',
)

# Tipos de tratamiento operativo de un item del pliego (Fase 4 UX).
# Permiten que el usuario decida que hacer con items globales/generales que
# no tienen sentido desglosar en composicion ejecutiva.
TIPOS_TRATAMIENTO = ('desglosar', 'global', 'servicio', 'excluir')


@presupuestos_bp.route('/api/rubros-tecnicos', methods=['GET'])
@login_required
def api_rubros_tecnicos():
    """Lista de rubros/etapas/unidades para popular dropdowns en la vista
    'Resolver items pendientes'. Se construye desde la base tecnica."""
    try:
        from services.base_tecnica_computos import REGLAS_TECNICAS
        rubros = sorted({(r.get('rubro') or '').strip() for r in REGLAS_TECNICAS if r.get('rubro')})
        etapas = sorted({(r.get('etapa') or '').strip() for r in REGLAS_TECNICAS if r.get('etapa')})
    except Exception:
        rubros, etapas = [], []
    return jsonify(
        ok=True,
        rubros=[r for r in rubros if r],
        etapas=[e for e in etapas if e],
        unidades=list(UNIDADES_DISPONIBLES),
    )


@presupuestos_bp.route('/<int:id>/items/<int:item_id>/clasificar', methods=['POST'])
@login_required
def clasificar_item_pendiente(id, item_id):
    """Clasificacion manual de un item pendiente.

    Body JSON:
      {
        "accion": "confirmar" | "guardar" | "omitir",
        "descripcion": "..." (opcional),
        "unidad": "m3" (opcional),
        "etapa_nombre": "Estructura" (opcional),
        "rubro": "Estructura" (opcional, se mergea al blob analisis_ia)
      }

    Para "confirmar": aplica los cambios + marca revisado_ia=True.
    Para "guardar":  idem (alias).
    Para "omitir":   no modifica el item; solo registra audit/learning para
                     trackear que el usuario eligio postergar la decision.
    """
    from datetime import datetime
    from models.budgets import Presupuesto, ItemPresupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403
    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(ok=False, error=f'Presupuesto en estado {presupuesto.estado}: no editable.'), 400

    item = ItemPresupuesto.query.filter_by(
        id=item_id, presupuesto_id=presupuesto.id,
    ).first()
    if not item:
        return jsonify(ok=False, error='Item no encontrado'), 404

    payload = request.get_json(silent=True) or {}
    accion = (payload.get('accion') or 'guardar').strip().lower()
    if accion not in ('confirmar', 'guardar', 'omitir'):
        return jsonify(ok=False, error='accion invalida'), 400

    # Tipo de tratamiento operativo (opcional): permite que el usuario marque
    # un item como global/gasto general/servicio/excluir, evitando que el
    # generador de composicion ejecutiva intente desglosarlo.
    tipo_tratamiento = (payload.get('tipo_tratamiento') or '').strip().lower()
    if tipo_tratamiento and tipo_tratamiento not in TIPOS_TRATAMIENTO:
        return jsonify(ok=False, error=f'tipo_tratamiento invalido: {tipo_tratamiento}'), 400

    # Snapshot de la sugerencia que tenia el item (para registrar correccion)
    analisis_blob = item.analisis_ia or {}
    sugerencia_original = (
        analisis_blob.get('sugerencias') if 'sugerencias' in analisis_blob else analisis_blob
    ) or {}

    cambios = {}
    if accion != 'omitir':
        # Aplicar cambios solo si vienen explicitos
        if payload.get('descripcion'):
            if not item.descripcion_original:
                item.descripcion_original = item.descripcion
            nueva_desc = str(payload['descripcion']).strip()[:300]
            if nueva_desc and nueva_desc != item.descripcion:
                item.descripcion = nueva_desc
                cambios['descripcion'] = nueva_desc
        if payload.get('unidad'):
            if not item.unidad_original:
                item.unidad_original = item.unidad
            nueva_un = str(payload['unidad']).strip()[:20]
            if nueva_un and nueva_un != item.unidad:
                item.unidad = nueva_un
                cambios['unidad'] = nueva_un
        if payload.get('etapa_nombre'):
            nueva_et = str(payload['etapa_nombre']).strip()[:100]
            if nueva_et and nueva_et != item.etapa_nombre:
                item.etapa_nombre = nueva_et
                cambios['etapa_nombre'] = nueva_et

        # Mergear el rubro elegido + marca de resolucion al blob para
        # trazabilidad y para que el servicio de estados operativos
        # pueda detectar "resuelto por usuario" aunque la confianza
        # original fuese baja o nula.
        rubro_in = (payload.get('rubro') or '').strip()
        analisis_blob = dict(analisis_blob)  # mutable copy
        if 'sugerencias' in analisis_blob:
            sug_actualizada = dict(sugerencia_original)
        else:
            sug_actualizada = analisis_blob

        if rubro_in:
            cambios['rubro'] = rubro_in
            sug_actualizada['rubro_sugerido'] = rubro_in[:120]

        # Marca canonica que el servicio de estados operativos
        # usa para devolver "listo" aunque la confianza_label sea sin/baja.
        # 'sugerencia_confirmada' = el usuario confirmo lo sugerido tal cual.
        # 'clasificado_manual'    = el usuario edito al menos un campo.
        if accion == 'confirmar' and not cambios:
            estado_revision = 'sugerencia_confirmada'
        else:
            estado_revision = 'clasificado_manual'

        if 'sugerencias' in analisis_blob:
            analisis_blob['sugerencias'] = sug_actualizada
            analisis_blob['estado_revision'] = estado_revision
            analisis_blob['resuelto_por_usuario'] = True
            analisis_blob['resuelto_at'] = datetime.utcnow().isoformat()
            if tipo_tratamiento:
                analisis_blob['tipo_tratamiento'] = tipo_tratamiento
        else:
            sug_actualizada['estado_revision'] = estado_revision
            sug_actualizada['resuelto_por_usuario'] = True
            sug_actualizada['resuelto_at'] = datetime.utcnow().isoformat()
            if tipo_tratamiento:
                sug_actualizada['tipo_tratamiento'] = tipo_tratamiento
            analisis_blob = sug_actualizada
        item.analisis_ia = analisis_blob

        if tipo_tratamiento:
            cambios['tipo_tratamiento'] = tipo_tratamiento

        item.revisado_ia = True
        item.fecha_analisis_ia = datetime.utcnow()

    # Aprendizaje IA Fase B (fail-safe)
    aprendizaje_ok = False
    try:
        from services.ia_learning_service import registrar_aplicacion_ia
        # entry simulado para que el servicio detecte tipos de correccion
        entry = {
            'aplicar': True,
            'descripcion': item.descripcion,
            'unidad': item.unidad,
            'etapa_nombre': item.etapa_nombre,
            'rubro': payload.get('rubro'),
            'analisis': item.analisis_ia or {},
        }
        res = registrar_aplicacion_ia(
            item=item,
            entry=entry,
            presupuesto=presupuesto,
            user_id=current_user.id if current_user.is_authenticated else None,
            organizacion_id=presupuesto.organizacion_id,
        )
        aprendizaje_ok = bool(res and not res.get('error'))
    except Exception:
        current_app.logger.exception('Aprendizaje IA fallo en clasificar_item_pendiente')

    # Audit
    try:
        from models.audit import registrar_audit
        registrar_audit(
            accion='revision_tecnica_ia',
            entidad='item_presupuesto',
            entidad_id=item.id,
            detalle=(
                f'accion={accion} '
                f'cambios={list(cambios.keys()) if cambios else "ninguno"} '
                f'aprendizaje={"ok" if aprendizaje_ok else "skip"}'
            ),
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error commiteando clasificar_item_pendiente')
        return jsonify(ok=False, error=f'Error al guardar: {type(e).__name__}'), 500

    # Recuperar marca de resolucion aplicada (para feedback en el frontend)
    blob_final = item.analisis_ia or {}
    sug_final = blob_final.get('sugerencias') if 'sugerencias' in blob_final else blob_final
    estado_revision_aplicado = None
    tipo_tratamiento_aplicado = None
    if accion != 'omitir':
        if isinstance(blob_final, dict):
            estado_revision_aplicado = blob_final.get('estado_revision') or (
                sug_final.get('estado_revision') if isinstance(sug_final, dict) else None
            )
            tipo_tratamiento_aplicado = blob_final.get('tipo_tratamiento') or (
                sug_final.get('tipo_tratamiento') if isinstance(sug_final, dict) else None
            )

    return jsonify(
        ok=True,
        item_id=item.id,
        accion=accion,
        cambios=list(cambios.keys()),
        revisado_ia=item.revisado_ia,
        descripcion=item.descripcion,
        unidad=item.unidad,
        etapa_nombre=item.etapa_nombre,
        estado_revision=estado_revision_aplicado,
        tipo_tratamiento=tipo_tratamiento_aplicado,
    )


# ============================================================================
# MVP autoclasificación 2026-05-06 — Aplicar clasificación a similares.
# ============================================================================

def _normalizar_tokens(s: str):
    """Normaliza descripción y devuelve set de tokens (palabras > 2 letras)."""
    if not s:
        return set()
    import unicodedata, re
    s = str(s).strip().lower()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r'[^\w\s]', ' ', s)
    return set(t for t in s.split() if len(t) > 2)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return (inter / union) if union > 0 else 0.0


@presupuestos_bp.route(
    '/<int:id>/items/<int:item_id>/aplicar-similares',
    methods=['POST']
)
@login_required
def aplicar_clasificacion_a_similares(id: int, item_id: int):
    """Aplica la clasificación de un ítem a otros similares del mismo presupuesto.

    Body JSON:
      tipo_tratamiento: 'global' | 'servicio' | 'desglosar' | 'excluir'   (opcional)
      rubro:            string                                            (opcional)
      threshold:        0.5 default — similitud Jaccard mínima por tokens

    Busca items en el mismo presupuesto cuya descripción tenga similitud
    Jaccard >= threshold con la del item base, y les aplica el mismo
    tipo_tratamiento (y rubro si viene). Items con composiciones manuales
    no se tocan.

    Devuelve resumen con cuántos items se actualizaron.
    """
    from models.budgets import Presupuesto, ItemPresupuesto

    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organizacion activa'), 400
    presupuesto = Presupuesto.query.filter_by(
        id=id, organizacion_id=org_id
    ).first()
    if not presupuesto:
        return jsonify(ok=False, error='Presupuesto no encontrado'), 404
    if not getattr(current_user, 'puede_gestionar', lambda: False)():
        return jsonify(ok=False, error='Sin permisos'), 403
    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(ok=False,
                       error=f'Presupuesto en estado {presupuesto.estado}: no editable.'), 400

    base = ItemPresupuesto.query.filter_by(
        id=item_id, presupuesto_id=presupuesto.id
    ).first()
    if not base:
        return jsonify(ok=False, error='Item base no encontrado'), 404

    payload = request.get_json(silent=True) or {}
    tt = (payload.get('tipo_tratamiento') or '').strip().lower()
    rubro = (payload.get('rubro') or '').strip()[:120]
    threshold = float(payload.get('threshold') or 0.5)
    if tt and tt not in TIPOS_TRATAMIENTO:
        return jsonify(ok=False, error=f'tipo_tratamiento invalido: {tt}'), 400
    if not tt and not rubro:
        return jsonify(ok=False, error='Pasá tipo_tratamiento o rubro'), 400

    base_tokens = _normalizar_tokens(base.descripcion or '')
    if len(base_tokens) < 1:
        return jsonify(ok=False,
                       error='El item base tiene descripcion vacía o muy corta'), 400

    candidatos = ItemPresupuesto.query.filter(
        ItemPresupuesto.presupuesto_id == presupuesto.id,
        ItemPresupuesto.id != base.id,
    ).all()

    aplicados = 0
    items_aplicados = []
    for it in candidatos:
        # No tocar items con composiciones manuales (lock implícito)
        try:
            comps_manuales = sum(
                1 for c in (it.composiciones.all()
                            if hasattr(it.composiciones, 'all')
                            else it.composiciones)
                if (c.origen or 'manual').lower() != 'calculadora_ia'
            )
            if comps_manuales > 0:
                continue
        except Exception:
            pass

        tokens = _normalizar_tokens(it.descripcion or '')
        if _jaccard(base_tokens, tokens) < threshold:
            continue

        blob = dict(it.analisis_ia) if isinstance(it.analisis_ia, dict) else {}
        if tt:
            blob['tipo_tratamiento'] = tt
            blob['tipo_tratamiento_origen'] = 'aplicar_a_similares'
            sug = blob.get('sugerencias') or {}
            if isinstance(sug, dict):
                sug['tipo_tratamiento'] = tt
                blob['sugerencias'] = sug
        if rubro:
            sug = blob.get('sugerencias') or {}
            if isinstance(sug, dict):
                sug['rubro_sugerido'] = rubro
                blob['sugerencias'] = sug
            it.etapa_nombre = rubro[:100]
        blob['estado_revision'] = 'clasificado_manual'
        blob['resuelto_por_usuario'] = True
        blob['resuelto_at'] = datetime.utcnow().isoformat()
        it.analisis_ia = blob
        it.revisado_ia = True
        aplicados += 1
        items_aplicados.append({
            'id': it.id,
            'descripcion': (it.descripcion or '')[:80],
        })

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error en aplicar_a_similares')
        return jsonify(ok=False, error=f'Error: {type(e).__name__}'), 500

    return jsonify(
        ok=True,
        item_base_id=base.id,
        aplicados=aplicados,
        items=items_aplicados[:30],   # cap para response
        threshold=threshold,
        tipo_tratamiento=tt or None,
        rubro=rubro or None,
    )
