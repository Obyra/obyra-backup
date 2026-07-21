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
from flask import request, jsonify, current_app, render_template
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


@presupuestos_bp.route('/pipeline-ia/analizar', methods=['POST'])
@login_required
def pipeline_ia_analizar():
    """Pipeline IA completo (Fase 2.4): clasifica -> descompone -> pricea -> scorea.

    Body JSON:
      - items: [{descripcion, unidad, cantidad}]  (requerido)
      - nivel: 'economico' | 'estandar' | 'premium'  (default 'estandar')
      - zona: str (default 'CABA')
      - forzar_keyword: bool (opcional, salta el LLM)

    Devuelve {ok, items:[...con color verde/amarillo/rojo...], resumen:{...}}.
    """
    if not _puede_gestionar():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from services.pipeline_presupuesto_ia import procesar_items

    org_id = get_current_org_id()
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    if not isinstance(items, list) or not items:
        return jsonify({'ok': False, 'error': 'items requerido (lista no vacia)'}), 400
    nivel = (data.get('nivel') or 'estandar').strip().lower()
    zona = (data.get('zona') or 'CABA').strip()
    forzar_keyword = bool(data.get('forzar_keyword'))
    # Modelo de encofrado del pliego (bundle | separado). Se decide a nivel pliego
    # sobre TODOS los items (en la ruta revision_ia) y viaja en cada lote.
    modelo_encofrado = (data.get('modelo_encofrado') or 'bundle').strip().lower()

    # Opcional: convertir con el TC de un presupuesto (para materiales en USD)
    presupuesto = None
    pres_id = data.get('presupuesto_id')
    if pres_id:
        from models.budgets import Presupuesto
        presupuesto = Presupuesto.query.filter_by(id=pres_id).first()

    try:
        r = procesar_items(items, organizacion_id=org_id, nivel=nivel, zona=zona,
                           presupuesto=presupuesto, forzar_keyword=forzar_keyword,
                           modelo_encofrado=modelo_encofrado)
        return jsonify({'ok': True, **r})
    except Exception as e:
        current_app.logger.exception('Error en pipeline IA de presupuesto')
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/pipeline-ia/corregir', methods=['POST'])
@login_required
def pipeline_ia_corregir():
    """Guarda una correccion del usuario -> aprendizaje por org (Fase 2.5).

    Body JSON:
      - descripcion: str (el texto del item del cliente) [requerido]
      - regla_id: str | null   (el tipo de trabajo elegido; null si es manual)
      - nivel: 'economico'|'estandar'|'premium'  (default estandar)
      - tratamiento: 'apu' | 'manual'  (default: manual si no hay regla_id)
    """
    if not _puede_gestionar():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from services.aprendizaje_ia import guardar_correccion

    org_id = get_current_org_id()
    data = request.get_json(silent=True) or {}
    descripcion = (data.get('descripcion') or '').strip()
    if not descripcion:
        return jsonify({'ok': False, 'error': 'descripcion requerida'}), 400
    regla_id = data.get('regla_id') or None
    nivel = (data.get('nivel') or 'estandar').strip().lower()
    tratamiento = (data.get('tratamiento') or ('apu' if regla_id else 'manual')).strip().lower()

    try:
        m = guardar_correccion(org_id, descripcion, regla_id=regla_id, nivel=nivel,
                               tratamiento=tratamiento, user_id=getattr(current_user, 'id', None))
        return jsonify({'ok': True, 'mapeo': m.to_dict()})
    except Exception as e:
        current_app.logger.exception('Error guardando correccion IA')
        return jsonify({'ok': False, 'error': str(e)}), 500


@presupuestos_bp.route('/pipeline-ia/corregir-bulk', methods=['POST'])
@login_required
def pipeline_ia_corregir_bulk():
    """Guarda una correccion para VARIOS items en un paso (Fase 2.6).

    Uso principal: agrupar los rojos no-APU (honorarios/servicios) y cargarlos
    todos como monto global (tratamiento='manual') con un solo click.

    Body JSON:
      - descripciones: [str, ...]  (requerido)
      - regla_id: str | null       (default null -> manual)
      - tratamiento: 'apu' | 'manual'  (default 'manual')
      - nivel: str (default 'estandar')
    """
    if not _puede_gestionar():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from services.aprendizaje_ia import guardar_correccion

    org_id = get_current_org_id()
    data = request.get_json(silent=True) or {}
    descripciones = data.get('descripciones') or []
    if not isinstance(descripciones, list) or not descripciones:
        return jsonify({'ok': False, 'error': 'descripciones requerido (lista no vacia)'}), 400
    regla_id = data.get('regla_id') or None
    nivel = (data.get('nivel') or 'estandar').strip().lower()
    tratamiento = (data.get('tratamiento') or ('apu' if regla_id else 'manual')).strip().lower()

    guardadas, errores = 0, []
    for desc in descripciones:
        d = (desc or '').strip()
        if not d:
            continue
        try:
            guardar_correccion(org_id, d, regla_id=regla_id, nivel=nivel,
                               tratamiento=tratamiento,
                               user_id=getattr(current_user, 'id', None))
            guardadas += 1
        except Exception as e:
            errores.append({'descripcion': d[:80], 'error': str(e)})

    if errores and not guardadas:
        current_app.logger.error('corregir-bulk fallo entero: %s', errores[:3])
        return jsonify({'ok': False, 'error': 'No se pudo guardar ninguna', 'errores': errores}), 500
    return jsonify({'ok': True, 'guardadas': guardadas, 'errores': errores})


@presupuestos_bp.route('/<int:id>/calcular-ia')
@login_required
def calcular_ia(id):
    """PASO 1 del flujo simplificado: pantalla limpia post-import. Muestra el
    presupuesto + cantidad de items + UN boton 'Calcular presupuesto con IA'.
    Si ya hay un calculo guardado, ofrece ver la revision o recalcular."""
    if not _puede_gestionar():
        from flask import flash, redirect, url_for
        flash('No tenes permisos para esta seccion.', 'danger')
        return redirect(url_for('presupuestos.lista'))

    from models.budgets import Presupuesto, ItemPresupuesto

    pres = Presupuesto.query.get_or_404(id)
    _verificar_acceso_presupuesto(pres)
    n_items = ItemPresupuesto.query.filter_by(presupuesto_id=id).count()
    muestra = (ItemPresupuesto.query.filter_by(presupuesto_id=id)
               .order_by(ItemPresupuesto.id).limit(6).all())
    ya_calculado = bool(pres.pipeline_ia_cache and (pres.pipeline_ia_cache or {}).get('items'))
    return render_template('presupuestos/calcular_ia.html',
                           presupuesto=pres, n_items=n_items, muestra=muestra,
                           ya_calculado=ya_calculado, fecha_calculo=pres.pipeline_ia_fecha)


@presupuestos_bp.route('/<int:id>/revision-ia')
@login_required
def revision_ia(id):
    """Pantalla de revision. Lee el resultado GUARDADO del pipeline (calculado 1
    vez, no re-analiza en cada carga). Si no hay cache -o ?recalcular=1-, el front
    lo analiza EN LOTES contra /pipeline-ia/analizar (con progreso) y lo guarda."""
    if not _puede_gestionar():
        from flask import flash, redirect, url_for
        flash('No tenes permisos para esta seccion.', 'danger')
        return redirect(url_for('presupuestos.lista'))

    from models.budgets import Presupuesto, ItemPresupuesto

    pres = Presupuesto.query.get_or_404(id)
    _verificar_acceso_presupuesto(pres)

    filas = ItemPresupuesto.query.filter_by(presupuesto_id=id).order_by(ItemPresupuesto.id).all()
    items = [{'descripcion': f.descripcion, 'unidad': f.unidad,
              'cantidad': float(f.cantidad or 0), 'etapa_nombre': f.etapa_nombre}
             for f in filas]

    recalcular = request.args.get('recalcular') in ('1', 'true', 'yes')
    cache = pres.pipeline_ia_cache if not recalcular else None
    if not (isinstance(cache, dict) and cache.get('items')):
        cache = None
    nivel = (request.args.get('nivel')
             or (cache or {}).get('nivel') or 'estandar').strip().lower()

    # Modelo de encofrado del pliego (autodetectado sobre TODOS los items).
    from services.pipeline_presupuesto_ia import _pliego_tiene_encofrado
    modelo_encofrado = 'separado' if _pliego_tiene_encofrado(items) else 'bundle'

    # Margen comercial vigente (override > org default > 25%). El front lo usa para
    # mostrar precio de venta = costo x (1+margen/100), recalculando sin pegar a la IA.
    from services.margen_comercial import resolver_margen
    margen = float(resolver_margen(pres))

    return render_template('presupuestos/revision_ia.html',
                           presupuesto=pres, items=items, nivel=nivel,
                           cache=cache, fecha_calculo=pres.pipeline_ia_fecha,
                           modelo_encofrado=modelo_encofrado, margen=margen)


@presupuestos_bp.route('/<int:id>/pipeline-ia/guardar-cache', methods=['POST'])
@login_required
def pipeline_ia_guardar_cache(id):
    """Persiste el resultado del pipeline (items ya analizados por el front) en el
    presupuesto, para que la revision no re-analice en cada carga (Fase 2.6)."""
    if not _puede_gestionar():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    from models.budgets import Presupuesto

    pres = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(pres):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    data = request.get_json(silent=True) or {}
    items = data.get('items')
    if not isinstance(items, list) or not items:
        return jsonify({'ok': False, 'error': 'items requerido'}), 400
    nivel = (data.get('nivel') or 'estandar').strip().lower()

    pres.pipeline_ia_cache = {'items': items, 'nivel': nivel}
    pres.pipeline_ia_fecha = datetime.utcnow()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error guardando cache pipeline IA')
        return jsonify({'ok': False, 'error': f'{type(e).__name__}'}), 500
    return jsonify({'ok': True, 'fecha': pres.pipeline_ia_fecha.isoformat()})


@presupuestos_bp.route('/<int:id>/margen', methods=['POST'])
@login_required
def guardar_margen(id):
    """Persiste el margen comercial del presupuesto (override). Vacio/null -> NULL,
    hereda el default de la organizacion. Es presentacion: NO recalcula la IA."""
    from decimal import Decimal
    if not _puede_gestionar():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    from models.budgets import Presupuesto

    pres = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(pres):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    data = request.get_json(silent=True) or {}
    raw = data.get('margen')
    if raw in (None, '', 'null'):
        pres.margen_comercial_override = None
    else:
        try:
            m = Decimal(str(raw))
        except Exception:
            return jsonify({'ok': False, 'error': 'margen invalido'}), 400
        if m < 0 or m > 1000:
            return jsonify({'ok': False, 'error': 'margen fuera de rango'}), 400
        pres.margen_comercial_override = m
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error guardando margen')
        return jsonify({'ok': False, 'error': type(e).__name__}), 500
    from services.margen_comercial import resolver_margen
    return jsonify({'ok': True, 'margen': float(resolver_margen(pres))})


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
# UX revisión por lotes 2026-05-06 — Acciones masivas sobre items pendientes.
# ============================================================================

@presupuestos_bp.route('/<int:id>/aplicar-analisis-ia/bulk', methods=['POST'])
@login_required
def aplicar_analisis_ia_bulk(id: int):
    """Aplica acción (confirmar / omitir / clasificar) a varios items en un solo request.

    Body JSON:
      items: [item_id_1, item_id_2, ...]
      accion: 'confirmar' | 'omitir'                     (default 'confirmar')
      tipo_tratamiento: 'global'|'servicio'|'desglosar'|'excluir'  (opcional)
      rubro: string                                       (opcional)

    Para 'confirmar': si los items ya tienen sugerencia IA, los marca como
    resueltos (sugerencia_confirmada). Si además se pasa tipo_tratamiento o
    rubro, los aplica.

    No modifica descripción/unidad/cantidad — solo metadata de clasificación.
    Ideal para el botón "Confirmar grupo" del modal de pendientes.
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
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403
    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(ok=False,
                       error=f'Presupuesto en estado {presupuesto.estado}: no editable.'), 400

    payload = request.get_json(silent=True) or {}
    item_ids = payload.get('items') or []
    if not isinstance(item_ids, list) or not item_ids:
        return jsonify(ok=False, error='Pasá una lista de item_ids'), 400

    accion = (payload.get('accion') or 'confirmar').strip().lower()
    if accion not in ('confirmar', 'omitir'):
        return jsonify(ok=False, error=f'accion invalida: {accion}'), 400

    tt = (payload.get('tipo_tratamiento') or '').strip().lower()
    rubro = (payload.get('rubro') or '').strip()[:120]
    if tt and tt not in TIPOS_TRATAMIENTO:
        return jsonify(ok=False, error=f'tipo_tratamiento invalido: {tt}'), 400

    # Opcional: sugerencias_por_item permite que el caller pase las sugerencias
    # IA del paso anterior (por ej. de un POST a /analizar-ia justo antes), para
    # que el endpoint bulk las persista en `analisis_ia.sugerencias` ANTES de
    # marcar como sugerencia_confirmada. Sin esto, "confirmar" sin sugerencia
    # previa no aporta info al generador de composicion.
    # Estructura: { "<item_id>": {regla_id, rubro_sugerido, etapa_sugerida,
    #                              tipo_tratamiento, confianza, ...} }
    sugerencias_por_item = payload.get('sugerencias_por_item') or {}
    if not isinstance(sugerencias_por_item, dict):
        sugerencias_por_item = {}

    items = (ItemPresupuesto.query
             .filter(ItemPresupuesto.presupuesto_id == presupuesto.id,
                     ItemPresupuesto.id.in_(item_ids))
             .all())

    aplicados = 0
    saltados = 0
    for it in items:
        try:
            blob = dict(it.analisis_ia) if isinstance(it.analisis_ia, dict) else {}
            if accion == 'omitir':
                blob['estado_revision'] = 'omitido'
                blob['resuelto_por_usuario'] = True
                blob['resuelto_at'] = datetime.utcnow().isoformat()
                it.analisis_ia = blob
                it.revisado_ia = True
                aplicados += 1
                continue

            # accion == 'confirmar'
            # Guardar sugerencia provista por el caller, si hay
            sug_provista = sugerencias_por_item.get(str(it.id)) or sugerencias_por_item.get(it.id)
            if isinstance(sug_provista, dict):
                # Mergear con la existente (si hay) para preservar campos previos
                sug_existente = blob.get('sugerencias') or {}
                if isinstance(sug_existente, dict):
                    sug_existente.update(sug_provista)
                    blob['sugerencias'] = sug_existente
                else:
                    blob['sugerencias'] = sug_provista
                # Si la sugerencia trae tipo_tratamiento, propagar al top-level
                tt_sug = (sug_provista.get('tipo_tratamiento') or '').strip().lower()
                if tt_sug and not tt:
                    blob['tipo_tratamiento'] = tt_sug
                # Si trae rubro, sincronizar etapa_nombre del item
                rubro_sug = (sug_provista.get('rubro_sugerido') or
                             sug_provista.get('etapa_sugerida') or '')
                if rubro_sug and not rubro and not it.etapa_nombre:
                    it.etapa_nombre = str(rubro_sug)[:100]

            if tt:
                blob['tipo_tratamiento'] = tt
                blob['tipo_tratamiento_origen'] = 'bulk_confirmar'
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

            blob['estado_revision'] = 'sugerencia_confirmada' if not (tt or rubro) else 'clasificado_manual'
            blob['resuelto_por_usuario'] = True
            blob['resuelto_at'] = datetime.utcnow().isoformat()
            it.analisis_ia = blob
            it.revisado_ia = True
            aplicados += 1
        except Exception:
            current_app.logger.exception(f'Error en bulk para item {it.id}')
            saltados += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error commiteando aplicar_analisis_ia_bulk')
        return jsonify(ok=False, error=f'Error al guardar: {type(e).__name__}'), 500

    return jsonify(
        ok=True,
        aplicados=aplicados,
        saltados=saltados,
        accion=accion,
        tipo_tratamiento=tt or None,
        rubro=rubro or None,
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
