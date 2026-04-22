"""Presupuesto Ejecutivo (APU).

Vista interna donde cada item del pliego se descompone en MO + materiales + equipos.
El cliente ve solo el presupuesto comercial; el ejecutivo es uso interno para
calcular costo estimado y margen por etapa antes de pasar a obra.

Rutas:
  GET  /presupuestos/<id>/ejecutivo           -> vista principal con items agrupados por etapa
"""
import hashlib
import json
import re
import unicodedata
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import render_template, redirect, url_for, flash, abort, request, jsonify
from flask_login import login_required, current_user

from blueprint_presupuestos import presupuestos_bp
from extensions import db
from models import (
    Presupuesto, ItemPresupuesto, ItemPresupuestoComposicion, MaterialCotizable,
    ProveedorAsignadoMaterial, SolicitudCotizacionMaterial, SolicitudCotizacionMaterialItem,
    EtapaInternaVinculo,
)
from models.proveedores_oc import ProveedorOC
from services.memberships import get_current_org_id
from etapas_predefinidas import ETAPAS_CONSTRUCCION, obtener_etapa_por_slug


def _normalizar_texto(s):
    """Pasa a lowercase, quita acentos, colapsa espacios. Útil para dedup."""
    if not s:
        return ''
    s = str(s).strip().lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'\s+', ' ', s)
    return s


def _grupo_hash_material(descripcion, unidad, item_inventario_id=None, tipo='material'):
    """Hash determinístico para identificar recursos iguales dentro del mismo tipo.

    Regla: si hay item_inventario_id, manda ese ID (más confiable que texto).
    Si no, normaliza descripción y unidad. Siempre se prefija con el tipo para
    no mezclar 'Excavadora' material con 'Excavadora' equipo.
    """
    if item_inventario_id:
        inner = f'inv:{item_inventario_id}'
    else:
        inner = f'txt:{_normalizar_texto(descripcion)}|{_normalizar_texto(unidad)}'
    key = f'{tipo}|{inner}'
    return hashlib.sha1(key.encode()).hexdigest()[:32]


def sincronizar_materiales_cotizables(presupuesto):
    """Consolida todas las composiciones COTIZABLES (material + equipo) del
    presupuesto en registros MaterialCotizable agrupando por hash.

    Qué hace:
      - Lee composiciones tipo='material' Y tipo='equipo' del presupuesto.
      - Agrupa por hash determinístico (desc + unidad + item_inventario_id).
      - Crea/actualiza MaterialCotizable por grupo (upsert).
      - Linkea cada composición a su MaterialCotizable via FK.
      - Borra MaterialCotizable huérfanos (si una composición desapareció).

    NO incluye mano_obra: esos son costos internos (sueldos/jornales) que
    vos conocés y no se cotizan a proveedores externos.

    Retorna lista ordenada de MaterialCotizable del presupuesto.
    """
    # 1. Traer composiciones cotizables (material + equipo) del presupuesto
    comps = db.session.query(ItemPresupuestoComposicion).join(
        ItemPresupuesto, ItemPresupuesto.id == ItemPresupuestoComposicion.item_presupuesto_id,
    ).filter(
        ItemPresupuesto.presupuesto_id == presupuesto.id,
        ItemPresupuestoComposicion.tipo.in_(['material', 'equipo']),
    ).all()

    # 2. Agrupar por hash (prefijando tipo para no mezclar material vs equipo)
    grupos = {}  # hash -> dict(tipo, composiciones, descripciones, unidades, cantidad_total, item_inv_id)
    for comp in comps:
        h = _grupo_hash_material(comp.descripcion, comp.unidad, comp.item_inventario_id, tipo=comp.tipo)
        if h not in grupos:
            grupos[h] = {
                'tipo': comp.tipo,
                'composiciones': [],
                'descripciones': [],
                'unidades': set(),
                'cantidad_total': Decimal('0'),
                'item_inventario_id': comp.item_inventario_id,
            }
        grupos[h]['composiciones'].append(comp)
        grupos[h]['descripciones'].append(comp.descripcion or '')
        grupos[h]['unidades'].add(comp.unidad or '')
        try:
            grupos[h]['cantidad_total'] += Decimal(str(comp.cantidad or 0))
        except (InvalidOperation, TypeError):
            pass

    # 3. Cargar MaterialCotizable existentes para este presupuesto
    existentes = {
        m.grupo_hash: m for m in MaterialCotizable.query.filter_by(
            presupuesto_id=presupuesto.id
        ).all()
    }

    # 4. Upsert: crear o actualizar por hash
    for h, info in grupos.items():
        # Descripción representativa = la más larga entre las composiciones agrupadas
        desc_rep = max(info['descripciones'], key=len) if info['descripciones'] else ''
        unidad_rep = next(iter(info['unidades']), 'un') if info['unidades'] else 'un'

        mat = existentes.get(h)
        if mat is None:
            mat = MaterialCotizable(
                presupuesto_id=presupuesto.id,
                grupo_hash=h,
                tipo=info['tipo'],
                descripcion=desc_rep[:300],
                unidad=unidad_rep[:20],
                cantidad_total=info['cantidad_total'],
                item_inventario_id=info['item_inventario_id'],
                estado='nuevo',
            )
            db.session.add(mat)
            db.session.flush()
        else:
            mat.tipo = info['tipo']
            mat.descripcion = desc_rep[:300]
            mat.unidad = unidad_rep[:20]
            mat.cantidad_total = info['cantidad_total']
            mat.item_inventario_id = info['item_inventario_id']

        # Linkear composiciones
        for comp in info['composiciones']:
            if comp.material_cotizable_id != mat.id:
                comp.material_cotizable_id = mat.id

    # 5. Borrar MaterialCotizable huérfanos (ya no tienen composiciones)
    for h, mat in existentes.items():
        if h not in grupos:
            db.session.delete(mat)

    db.session.commit()

    # 6. Devolver lista final ordenada
    return MaterialCotizable.query.filter_by(
        presupuesto_id=presupuesto.id
    ).order_by(MaterialCotizable.descripcion).all()


def _matchea_etapa_del_pliego(etapa_estandar_nombre, nombres_pliego_set):
    """True si esta etapa estándar ya está cubierta por una etapa del pliego."""
    if not etapa_estandar_nombre or not nombres_pliego_set:
        return False
    nombre_lower = etapa_estandar_nombre.strip().lower()
    for n in nombres_pliego_set:
        if not n:
            continue
        n_lower = n.strip().lower()
        if nombre_lower == n_lower:
            return True
        # Matching flexible: "Depresión de Napa / Bombeo" matchea con "Depresion de Napa"
        base_standard = nombre_lower.split('/')[0].strip()
        base_pliego = n_lower.split('/')[0].strip()
        if base_standard and base_standard == base_pliego:
            return True
    return False


def _cargar_datos_proyecto(presupuesto):
    """Devuelve el dict datos_proyecto del presupuesto (creando uno vacío si falta)."""
    if not presupuesto.datos_proyecto:
        return {}
    if isinstance(presupuesto.datos_proyecto, dict):
        return presupuesto.datos_proyecto
    try:
        return json.loads(presupuesto.datos_proyecto)
    except (json.JSONDecodeError, TypeError):
        return {}


def _guardar_datos_proyecto(presupuesto, datos):
    presupuesto.datos_proyecto = json.dumps(datos, ensure_ascii=False)


TIPOS_COMPOSICION = ('material', 'mano_obra', 'equipo', 'otro')


def _puede_editar_ejecutivo(presupuesto):
    """True si el ejecutivo permite agregar/editar/eliminar composiciones.

    Una vez aprobado queda congelado; para modificar hay que revertir primero.
    """
    if presupuesto.ejecutivo_aprobado:
        return False
    return presupuesto.estado in ESTADOS_EDITABLES_EJECUTIVO


ESTADOS_EDITABLES_EJECUTIVO = ('borrador', 'enviado', 'aprobado')


def _puede_ver_ejecutivo(presupuesto):
    """El ejecutivo es interno: solo admin/PM."""
    if not current_user.is_authenticated:
        return False
    rol = getattr(current_user, 'role', '') or ''
    return rol in ('admin', 'administrador', 'pm', 'project_manager')


@presupuestos_bp.route('/<int:id>/ejecutivo')
@login_required
def ejecutivo_vista(id):
    """Vista del presupuesto ejecutivo: items del pliego agrupados por etapa."""
    org_id = get_current_org_id()
    if not org_id:
        flash('Seleccioná una organización.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion'))

    presupuesto = Presupuesto.query.filter_by(
        id=id, organizacion_id=org_id,
    ).first_or_404()

    if not _puede_ver_ejecutivo(presupuesto):
        abort(403)

    if presupuesto.estado not in ESTADOS_EDITABLES_EJECUTIVO:
        flash(
            f'El presupuesto ejecutivo solo está disponible para presupuestos '
            f'en estado borrador, enviado o aprobado (actual: {presupuesto.estado}).',
            'warning',
        )
        return redirect(url_for('presupuestos.detalle', id=id))

    # Traer items ordenados por etapa_nombre para agrupar en el template.
    # Se traen TODOS (incluidos los solo_interno=True) pero se separan en dos
    # grupos: "etapas del pliego" y "etapas internas" (las agregadas por el PM
    # en el ejecutivo, que no se muestran al cliente).
    items = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
    ).order_by(
        ItemPresupuesto.etapa_nombre,
        ItemPresupuesto.id,
    ).all()

    # Agrupar por etapa, pre-cargando composiciones
    etapas = OrderedDict()           # etapas del pliego (solo_interno=False)
    etapas_internas = OrderedDict()  # etapas internas (solo_interno=True)

    for item in items:
        nombre_etapa = item.etapa_nombre or (item.etapa.nombre if item.etapa else 'Sin etapa')

        comp_list = item.composiciones.order_by(
            ItemPresupuestoComposicion.tipo,
            ItemPresupuestoComposicion.id,
        ).all()
        item.comp_list = comp_list
        costo_item = sum((Decimal(str(c.total or 0)) for c in comp_list), Decimal('0'))
        item.costo_estimado = costo_item

        target = etapas_internas if item.solo_interno else etapas
        if nombre_etapa not in target:
            target[nombre_etapa] = {
                'items': [],
                'total_vendido': Decimal('0'),
                'total_costo': Decimal('0'),
            }
        target[nombre_etapa]['items'].append(item)
        # Solo suma al vendido si NO es interno (los internos no se facturan al cliente)
        if not item.solo_interno:
            target[nombre_etapa]['total_vendido'] += Decimal(str(item.total or 0))
        target[nombre_etapa]['total_costo'] += costo_item

    # Gap 14+15: vínculos etapa interna -> rubro pliego. El costo de cada
    # etapa interna vinculada se acumula en el rubro pliego destino (A+i:
    # suma directa, precio vendido NO cambia).
    vinculos_rows = EtapaInternaVinculo.query.filter_by(
        presupuesto_id=presupuesto.id,
    ).all()
    vinculos_interna_a_pliego = {
        v.etapa_interna_nombre: v.etapa_pliego_nombre for v in vinculos_rows
    }

    # Inicializar contribución por pliego y marcar cada interna con su vínculo
    for d in etapas.values():
        d['costo_internas_vinculadas'] = Decimal('0')
        d['internas_vinculadas'] = []  # [(nombre, costo), ...]
    for nombre_int, d in etapas_internas.items():
        pliego_dest = vinculos_interna_a_pliego.get(nombre_int)
        d['vinculada_a'] = pliego_dest
        if pliego_dest and pliego_dest in etapas:
            etapas[pliego_dest]['costo_internas_vinculadas'] += d['total_costo']
            etapas[pliego_dest]['internas_vinculadas'].append(
                (nombre_int, d['total_costo'])
            )

    # Calcular margen y margen% por etapa pliego, usando costo consolidado
    # (propio + internas vinculadas). El vendido no cambia.
    for nombre_etapa, d in etapas.items():
        d['total_costo_consolidado'] = d['total_costo'] + d['costo_internas_vinculadas']
        d['margen'] = d['total_vendido'] - d['total_costo_consolidado']
        d['margen_pct'] = (d['margen'] / d['total_vendido'] * 100) if d['total_vendido'] > 0 else Decimal('0')

    # Las etapas internas solo tienen costo (no margen porque no se venden)
    for d in etapas_internas.values():
        d['margen'] = Decimal('0')
        d['margen_pct'] = Decimal('0')

    # Lista ordenada de nombres de etapas pliego (para el selector del vínculo)
    nombres_etapas_pliego = list(etapas.keys())

    total_vendido = sum((d['total_vendido'] for d in etapas.values()), Decimal('0'))
    # Costo total = costo de etapas del pliego + costo de etapas internas
    total_costo_pliego = sum((d['total_costo'] for d in etapas.values()), Decimal('0'))
    total_costo_interno = sum((d['total_costo'] for d in etapas_internas.values()), Decimal('0'))
    total_costo = total_costo_pliego + total_costo_interno
    margen = total_vendido - total_costo
    margen_pct = (margen / total_vendido * 100) if total_vendido > 0 else Decimal('0')

    # Materiales sin cotizar (precio=0 y tipo=material) para warning al aprobar
    materiales_sin_precio = db.session.query(ItemPresupuestoComposicion).join(
        ItemPresupuesto, ItemPresupuesto.id == ItemPresupuestoComposicion.item_presupuesto_id,
    ).filter(
        ItemPresupuesto.presupuesto_id == presupuesto.id,
        ItemPresupuestoComposicion.tipo == 'material',
        ItemPresupuestoComposicion.precio_unitario == 0,
    ).count()

    return render_template(
        'presupuestos/ejecutivo.html',
        presupuesto=presupuesto,
        etapas=etapas,
        etapas_internas=etapas_internas,
        total_vendido=total_vendido,
        total_costo=total_costo,
        total_costo_pliego=total_costo_pliego,
        total_costo_interno=total_costo_interno,
        margen=margen,
        margen_pct=margen_pct,
        materiales_sin_precio=materiales_sin_precio,
        nombres_etapas_pliego=nombres_etapas_pliego,
    )


def _parse_decimal(val, default='0'):
    try:
        return Decimal(str(val).replace(',', '.'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _item_pertenece_a_org(item, org_id):
    """Valida que el item pertenezca a un presupuesto de la org activa."""
    return bool(item and item.presupuesto and item.presupuesto.organizacion_id == org_id)


def _serializar_composicion(comp):
    return {
        'id': comp.id,
        'tipo': comp.tipo,
        'descripcion': comp.descripcion,
        'unidad': comp.unidad,
        'cantidad': float(comp.cantidad or 0),
        'precio_unitario': float(comp.precio_unitario or 0),
        'total': float(comp.total or 0),
        'item_inventario_id': comp.item_inventario_id,
        'modalidad_costo': comp.modalidad_costo,
        'notas': comp.notas,
    }


@presupuestos_bp.route('/items/<int:item_id>/composicion', methods=['POST'])
@login_required
def composicion_crear(item_id):
    """Crea una composición (material/mano_obra/equipo) dentro de un item del pliego."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    item = ItemPresupuesto.query.get_or_404(item_id)
    if not _item_pertenece_a_org(item, org_id):
        return jsonify(ok=False, error='Item no pertenece a tu organización'), 403

    if not _puede_editar_ejecutivo(item.presupuesto):
        motivo = 'ejecutivo aprobado — revertí la aprobación para editarlo' \
            if item.presupuesto.ejecutivo_aprobado \
            else f'estado {item.presupuesto.estado} no editable'
        return jsonify(ok=False, error=f'No se puede editar el ejecutivo: {motivo}'), 400

    data = request.get_json(silent=True) or request.form.to_dict()

    tipo = (data.get('tipo') or '').strip().lower()
    if tipo not in TIPOS_COMPOSICION:
        return jsonify(ok=False, error=f'Tipo inválido. Usá uno de: {", ".join(TIPOS_COMPOSICION)}'), 400

    descripcion = (data.get('descripcion') or '').strip()
    if not descripcion:
        return jsonify(ok=False, error='La descripción es obligatoria'), 400

    unidad = (data.get('unidad') or '').strip() or 'un'
    cantidad = _parse_decimal(data.get('cantidad'), '0')
    precio = _parse_decimal(data.get('precio_unitario'), '0')

    if cantidad < 0 or precio < 0:
        return jsonify(ok=False, error='Cantidad y precio no pueden ser negativos'), 400

    item_inventario_id = data.get('item_inventario_id')
    try:
        item_inventario_id = int(item_inventario_id) if item_inventario_id else None
    except (ValueError, TypeError):
        item_inventario_id = None

    # Modalidad de costo: solo aplica a equipos (compra | alquiler).
    modalidad = (data.get('modalidad_costo') or '').strip().lower() or None
    if tipo == 'equipo' and modalidad not in ('compra', 'alquiler', None):
        return jsonify(ok=False, error='Modalidad de equipo inválida (usá compra o alquiler)'), 400
    if tipo != 'equipo':
        modalidad = None

    comp = ItemPresupuestoComposicion(
        item_presupuesto_id=item.id,
        tipo=tipo,
        descripcion=descripcion[:300],
        unidad=unidad[:20],
        cantidad=cantidad,
        precio_unitario=precio,
        total=cantidad * precio,
        item_inventario_id=item_inventario_id,
        modalidad_costo=modalidad,
        notas=(data.get('notas') or None),
    )
    db.session.add(comp)
    db.session.commit()

    return jsonify(ok=True, composicion=_serializar_composicion(comp))


@presupuestos_bp.route('/composicion/<int:comp_id>', methods=['PUT', 'PATCH'])
@login_required
def composicion_actualizar(comp_id):
    """Edita una composición existente."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    comp = ItemPresupuestoComposicion.query.get_or_404(comp_id)
    if not _item_pertenece_a_org(comp.item_presupuesto, org_id):
        return jsonify(ok=False, error='Composición no pertenece a tu organización'), 403

    if not _puede_editar_ejecutivo(comp.item_presupuesto.presupuesto):
        motivo = 'ejecutivo aprobado — revertí la aprobación para editarlo' \
            if comp.item_presupuesto.presupuesto.ejecutivo_aprobado \
            else f'estado {comp.item_presupuesto.presupuesto.estado} no editable'
        return jsonify(ok=False, error=f'No se puede editar el ejecutivo: {motivo}'), 400

    data = request.get_json(silent=True) or request.form.to_dict()

    # Validar tipo solo si se envía (en edición puede no cambiar)
    if 'tipo' in data:
        nuevo_tipo = (data.get('tipo') or '').strip().lower()
        if nuevo_tipo not in TIPOS_COMPOSICION:
            return jsonify(ok=False, error='Tipo inválido'), 400
        comp.tipo = nuevo_tipo

    if 'descripcion' in data:
        desc = (data.get('descripcion') or '').strip()
        if not desc:
            return jsonify(ok=False, error='La descripción es obligatoria'), 400
        comp.descripcion = desc[:300]

    if 'unidad' in data:
        comp.unidad = ((data.get('unidad') or 'un').strip() or 'un')[:20]

    if 'cantidad' in data:
        cantidad = _parse_decimal(data.get('cantidad'), '0')
        if cantidad < 0:
            return jsonify(ok=False, error='Cantidad no puede ser negativa'), 400
        comp.cantidad = cantidad

    if 'precio_unitario' in data:
        precio = _parse_decimal(data.get('precio_unitario'), '0')
        if precio < 0:
            return jsonify(ok=False, error='Precio no puede ser negativo'), 400
        comp.precio_unitario = precio

    # Modalidad aplica solo a equipos; si el tipo final no es equipo, la blanqueamos.
    if comp.tipo == 'equipo':
        if 'modalidad_costo' in data:
            modalidad = (data.get('modalidad_costo') or '').strip().lower() or None
            if modalidad not in ('compra', 'alquiler', None):
                return jsonify(ok=False, error='Modalidad inválida'), 400
            comp.modalidad_costo = modalidad
    else:
        comp.modalidad_costo = None

    if 'notas' in data:
        comp.notas = (data.get('notas') or None)

    comp.recalcular_total()
    db.session.commit()

    return jsonify(ok=True, composicion=_serializar_composicion(comp))


@presupuestos_bp.route('/composicion/<int:comp_id>', methods=['DELETE'])
@login_required
def composicion_eliminar(comp_id):
    """Elimina una composición del ejecutivo."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    comp = ItemPresupuestoComposicion.query.get_or_404(comp_id)
    if not _item_pertenece_a_org(comp.item_presupuesto, org_id):
        return jsonify(ok=False, error='Composición no pertenece a tu organización'), 403

    if not _puede_editar_ejecutivo(comp.item_presupuesto.presupuesto):
        motivo = 'ejecutivo aprobado — revertí la aprobación para editarlo' \
            if comp.item_presupuesto.presupuesto.ejecutivo_aprobado \
            else f'estado {comp.item_presupuesto.presupuesto.estado} no editable'
        return jsonify(ok=False, error=f'No se puede editar el ejecutivo: {motivo}'), 400

    db.session.delete(comp)
    db.session.commit()

    return jsonify(ok=True)


@presupuestos_bp.route('/items/<int:item_id>/composiciones', methods=['GET'])
@login_required
def composiciones_listar(item_id):
    """Devuelve las composiciones de un item (para refrescar UI sin reload)."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    item = ItemPresupuesto.query.get_or_404(item_id)
    if not _item_pertenece_a_org(item, org_id):
        return jsonify(ok=False, error='Item no pertenece a tu organización'), 403

    comps = item.composiciones.order_by(ItemPresupuestoComposicion.tipo, ItemPresupuestoComposicion.id).all()
    costo_total = sum((float(c.total or 0) for c in comps), 0.0)
    return jsonify(
        ok=True,
        item_id=item.id,
        costo_estimado=costo_total,
        composiciones=[_serializar_composicion(c) for c in comps],
    )


def _crear_etapa_interna_para_slug(presupuesto, slug):
    """Crea la etapa interna con sus items sinteticos. Retorna (ok, etapa_nombre, error)."""
    from tareas_predefinidas import obtener_tareas_por_etapa

    cat = obtener_etapa_por_slug(slug)
    if not cat:
        return False, slug, f'Etapa "{slug}" no existe en el catálogo'

    etapa_nombre = cat['nombre']

    ya_existe_interna = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
        solo_interno=True,
        etapa_nombre=etapa_nombre,
    ).first()
    if ya_existe_interna:
        return False, etapa_nombre, f'La etapa interna "{etapa_nombre}" ya está agregada.'

    ya_en_pliego = ItemPresupuesto.query.filter(
        ItemPresupuesto.presupuesto_id == presupuesto.id,
        ItemPresupuesto.solo_interno == False,  # noqa: E712
        ItemPresupuesto.etapa_nombre == etapa_nombre,
    ).first()
    if ya_en_pliego:
        return False, etapa_nombre, f'La etapa "{etapa_nombre}" ya forma parte del pliego.'

    predefs = obtener_tareas_por_etapa(etapa_nombre) or []
    predefs_core = [t for t in predefs if not t.get('si_aplica')]

    if predefs_core:
        for tdef in predefs_core:
            item = ItemPresupuesto(
                presupuesto_id=presupuesto.id,
                tipo='material',
                descripcion=tdef['nombre'][:300],
                unidad='un' if tdef.get('aplica_cantidad') is False else 'h',
                cantidad=Decimal('1'),
                precio_unitario=Decimal('0'),
                total=Decimal('0'),
                etapa_nombre=etapa_nombre,
                origen='ejecutivo_interno',
                currency=presupuesto.currency or 'ARS',
                solo_interno=True,
            )
            db.session.add(item)
    else:
        item = ItemPresupuesto(
            presupuesto_id=presupuesto.id,
            tipo='material',
            descripcion=f'Ejecución {etapa_nombre}',
            unidad='un',
            cantidad=Decimal('1'),
            precio_unitario=Decimal('0'),
            total=Decimal('0'),
            etapa_nombre=etapa_nombre,
            origen='ejecutivo_interno',
            currency=presupuesto.currency or 'ARS',
            solo_interno=True,
        )
        db.session.add(item)
    return True, etapa_nombre, None


@presupuestos_bp.route('/<int:id>/ejecutivo/etapas-internas', methods=['POST'])
@login_required
def ejecutivo_agregar_etapa_interna(id):
    """Agrega una o varias etapas internas al ejecutivo.

    Crea N ítems sintéticos (`solo_interno=True`) en el presupuesto, uno por
    cada tarea predefinida de la etapa elegida. Estos items:
      - NO aparecen en el PDF del cliente.
      - NO suman al precio vendido.
      - SÍ pueden tener composiciones (materiales/MO/equipos) que sumen al costo.

    Body JSON (un slug):      {"slug": "mamposteria"}
    Body JSON (varios slugs): {"slugs": ["mamposteria", "pisos", "pintura"]}
    """
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
    if presupuesto.ejecutivo_aprobado:
        return jsonify(ok=False, error='Ejecutivo aprobado. Revertí la aprobación primero.'), 400
    if presupuesto.estado not in ESTADOS_EDITABLES_EJECUTIVO:
        return jsonify(ok=False, error=f'Estado {presupuesto.estado} no editable'), 400

    data = request.get_json(silent=True) or {}
    slugs = data.get('slugs')
    if slugs is None:
        slug_unico = (data.get('slug') or '').strip()
        slugs = [slug_unico] if slug_unico else []
    # Normalizar + deduplicar preservando orden
    slugs_limpios = []
    for s in slugs:
        s = (s or '').strip()
        if s and s not in slugs_limpios:
            slugs_limpios.append(s)
    if not slugs_limpios:
        return jsonify(ok=False, error='Hay que mandar al menos un slug'), 400

    exitosas = []
    errores = []
    for slug in slugs_limpios:
        ok, etapa_nombre, err = _crear_etapa_interna_para_slug(presupuesto, slug)
        if ok:
            exitosas.append(etapa_nombre)
        else:
            errores.append({'slug': slug, 'etapa_nombre': etapa_nombre, 'error': err})

    if exitosas:
        db.session.commit()
    else:
        db.session.rollback()

    # Si pedimos una sola y falló, devolvemos 400 (compat con flujo anterior).
    if len(slugs_limpios) == 1 and not exitosas:
        return jsonify(ok=False, error=errores[0]['error']), 400

    return jsonify(
        ok=bool(exitosas),
        agregadas=exitosas,
        errores=errores,
    )


@presupuestos_bp.route('/<int:id>/ejecutivo/etapas-internas', methods=['DELETE'])
@login_required
def ejecutivo_eliminar_etapa_interna(id):
    """Elimina una etapa interna completa (todos sus ítems internos y sus composiciones).

    Body JSON: {"etapa_nombre": "Mampostería"}
    """
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
    if presupuesto.ejecutivo_aprobado:
        return jsonify(ok=False, error='Ejecutivo aprobado. Revertí la aprobación primero.'), 400

    data = request.get_json(silent=True) or {}
    etapa_nombre = (data.get('etapa_nombre') or '').strip()
    if not etapa_nombre:
        return jsonify(ok=False, error='etapa_nombre requerido'), 400

    items = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
        solo_interno=True,
        etapa_nombre=etapa_nombre,
    ).all()

    if not items:
        return jsonify(ok=False, error=f'No hay etapa interna "{etapa_nombre}"'), 404

    # Las composiciones tienen cascade DELETE desde item_presupuesto
    for item in items:
        db.session.delete(item)
    # Y si había un vínculo, limpiarlo también
    EtapaInternaVinculo.query.filter_by(
        presupuesto_id=presupuesto.id,
        etapa_interna_nombre=etapa_nombre,
    ).delete()
    db.session.commit()

    return jsonify(ok=True, eliminados=len(items))


@presupuestos_bp.route('/<int:id>/ejecutivo/vincular-etapa', methods=['POST'])
@login_required
def ejecutivo_vincular_etapa(id):
    """Vincula (o desvincula) una etapa interna a un rubro del pliego.

    Body JSON:
      {"etapa_interna_nombre": "Mampostería", "etapa_pliego_nombre": "Estructura"}
      {"etapa_interna_nombre": "Mampostería", "etapa_pliego_nombre": null}  -> desvincula

    El costo total de la etapa interna se sumará al rubro pliego destino
    (A+i: solo costo, precio vendido no se toca).
    """
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
    if presupuesto.ejecutivo_aprobado:
        return jsonify(ok=False, error='Ejecutivo aprobado. Revertí la aprobación primero.'), 400

    data = request.get_json(silent=True) or {}
    etapa_interna_nombre = (data.get('etapa_interna_nombre') or '').strip()
    etapa_pliego_nombre = (data.get('etapa_pliego_nombre') or '').strip() or None

    if not etapa_interna_nombre:
        return jsonify(ok=False, error='etapa_interna_nombre requerido'), 400

    # Validar que la etapa interna exista
    existe_interna = db.session.query(ItemPresupuesto.id).filter(
        ItemPresupuesto.presupuesto_id == presupuesto.id,
        ItemPresupuesto.solo_interno == True,  # noqa: E712
        ItemPresupuesto.etapa_nombre == etapa_interna_nombre,
    ).first()
    if not existe_interna:
        return jsonify(ok=False, error=f'No existe etapa interna "{etapa_interna_nombre}"'), 404

    vinculo = EtapaInternaVinculo.query.filter_by(
        presupuesto_id=presupuesto.id,
        etapa_interna_nombre=etapa_interna_nombre,
    ).first()

    if etapa_pliego_nombre is None:
        # Desvincular
        if vinculo:
            db.session.delete(vinculo)
            db.session.commit()
        return jsonify(ok=True, vinculada_a=None)

    # Validar que la etapa pliego destino exista
    existe_pliego = db.session.query(ItemPresupuesto.id).filter(
        ItemPresupuesto.presupuesto_id == presupuesto.id,
        ItemPresupuesto.solo_interno == False,  # noqa: E712
        ItemPresupuesto.etapa_nombre == etapa_pliego_nombre,
    ).first()
    if not existe_pliego:
        return jsonify(ok=False, error=f'No existe etapa pliego "{etapa_pliego_nombre}"'), 404

    if vinculo:
        vinculo.etapa_pliego_nombre = etapa_pliego_nombre
    else:
        vinculo = EtapaInternaVinculo(
            presupuesto_id=presupuesto.id,
            etapa_interna_nombre=etapa_interna_nombre,
            etapa_pliego_nombre=etapa_pliego_nombre,
        )
        db.session.add(vinculo)
    db.session.commit()
    return jsonify(ok=True, vinculada_a=etapa_pliego_nombre)


@presupuestos_bp.route('/<int:id>/ejecutivo/etapas-estandar')
@login_required
def ejecutivo_etapas_estandar(id):
    """Catálogo de etapas estándar marcando cuáles están disponibles para
    agregar como etapa interna al ejecutivo.

    Para cada etapa:
      - en_pliego: ya es parte del pliego (items con solo_interno=False)
      - ya_interna: ya fue agregada como etapa interna (items con solo_interno=True)
      - disponible: se puede agregar
    """
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

    nombres_pliego = set(
        n for (n,) in db.session.query(ItemPresupuesto.etapa_nombre).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id,
            ItemPresupuesto.solo_interno == False,  # noqa: E712
            ItemPresupuesto.etapa_nombre.isnot(None),
        ).distinct().all()
    )
    nombres_internos = set(
        n for (n,) in db.session.query(ItemPresupuesto.etapa_nombre).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id,
            ItemPresupuesto.solo_interno == True,  # noqa: E712
            ItemPresupuesto.etapa_nombre.isnot(None),
        ).distinct().all()
    )

    catalogo = []
    for et in ETAPAS_CONSTRUCCION:
        en_pliego = _matchea_etapa_del_pliego(et['nombre'], nombres_pliego)
        ya_interna = et['nombre'] in nombres_internos
        catalogo.append({
            'slug': et['slug'],
            'nombre': et['nombre'],
            'descripcion': et['descripcion'],
            'nivel': et.get('nivel'),
            'en_pliego': en_pliego,
            'ya_interna': ya_interna,
            'disponible': not en_pliego and not ya_interna,
        })

    return jsonify(ok=True, etapas=catalogo)


@presupuestos_bp.route('/<int:id>/ejecutivo/aprobar', methods=['POST'])
@login_required
def ejecutivo_aprobar(id):
    """Aprueba el ejecutivo y lo congela: no se pueden editar composiciones
    ni agregar etapas internas hasta que se revierta la aprobación.
    """
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

    if presupuesto.ejecutivo_aprobado:
        return jsonify(ok=False, error='El ejecutivo ya estaba aprobado'), 400

    # Validar que haya al menos una composición cargada
    total_comps = db.session.query(ItemPresupuestoComposicion).join(ItemPresupuesto).filter(
        ItemPresupuesto.presupuesto_id == presupuesto.id,
    ).count()
    if total_comps == 0:
        return jsonify(
            ok=False,
            error='No hay recursos cargados en el ejecutivo. Agregá al menos una composición antes de aprobar.',
        ), 400

    presupuesto.ejecutivo_aprobado = True
    presupuesto.ejecutivo_aprobado_at = datetime.utcnow()
    db.session.commit()

    return jsonify(
        ok=True,
        aprobado_at=presupuesto.ejecutivo_aprobado_at.isoformat(),
    )


@presupuestos_bp.route('/<int:id>/ejecutivo/revertir', methods=['POST'])
@login_required
def ejecutivo_revertir(id):
    """Revierte la aprobación del ejecutivo para poder editarlo de nuevo."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        return jsonify(ok=False, error='Sin permisos'), 403

    presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

    if presupuesto.confirmado_como_obra:
        return jsonify(
            ok=False,
            error='El presupuesto ya fue confirmado como obra — no se puede revertir el ejecutivo.',
        ), 400

    if not presupuesto.ejecutivo_aprobado:
        return jsonify(ok=False, error='El ejecutivo no estaba aprobado'), 400

    presupuesto.ejecutivo_aprobado = False
    presupuesto.ejecutivo_aprobado_at = None
    db.session.commit()

    return jsonify(ok=True)


# ============================================================================
# FASE A - Consolidación de materiales a cotizar
# ============================================================================

@presupuestos_bp.route('/<int:id>/ejecutivo/materiales')
@login_required
def ejecutivo_materiales_vista(id):
    """Vista con los materiales consolidados del ejecutivo, listos para cotizar.

    Se llama también `/materiales` y sirve de entrada al circuito de cotización:
    el PM ve la lista de materiales únicos (agrupados) con su cantidad total y
    desde acá en siguientes fases va a poder asignar proveedores y pedir cotización.
    """
    org_id = get_current_org_id()
    if not org_id:
        flash('Seleccioná una organización.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion'))

    presupuesto = Presupuesto.query.filter_by(
        id=id, organizacion_id=org_id,
    ).first_or_404()

    rol = getattr(current_user, 'role', '') or ''
    if rol not in ('admin', 'administrador', 'pm', 'project_manager'):
        abort(403)

    # Sincronizar: crea/actualiza MaterialCotizable a partir de las composiciones
    materiales = sincronizar_materiales_cotizables(presupuesto)

    # Proveedores disponibles en la org (para los chips / modal)
    proveedores_disponibles = ProveedorOC.query.filter_by(
        organizacion_id=org_id,
    ).order_by(ProveedorOC.razon_social).all()

    # Hay al menos una asignación pendiente de enviar?
    hay_pendientes_enviar = db.session.query(ProveedorAsignadoMaterial).join(
        MaterialCotizable, MaterialCotizable.id == ProveedorAsignadoMaterial.material_cotizable_id,
    ).filter(
        MaterialCotizable.presupuesto_id == presupuesto.id,
        ProveedorAsignadoMaterial.solicitud_item_id.is_(None),
    ).count() > 0

    # Solicitudes ya generadas (para la sección "Solicitudes enviadas")
    solicitudes = SolicitudCotizacionMaterial.query.filter_by(
        presupuesto_id=presupuesto.id,
    ).order_by(SolicitudCotizacionMaterial.fecha_creacion.desc()).all()

    # Adjuntar info de "origen" + asignaciones
    for mat in materiales:
        origenes = []
        for comp in mat.composiciones:
            item = comp.item_presupuesto
            if item is None:
                continue
            origenes.append({
                'etapa': item.etapa_nombre or 'Sin etapa',
                'tarea': item.descripcion[:80] if item.descripcion else '',
                'cantidad': float(comp.cantidad or 0),
                'interno': bool(item.solo_interno),
            })
        mat.origenes = origenes
        # Asignaciones actuales (pendientes + enviadas, para mostrar chips completos)
        mat.asignaciones_list = list(mat.asignaciones)

    return render_template(
        'presupuestos/ejecutivo_materiales.html',
        presupuesto=presupuesto,
        materiales=materiales,
        proveedores_disponibles=proveedores_disponibles,
        hay_pendientes_enviar=hay_pendientes_enviar,
        solicitudes=solicitudes,
    )


@presupuestos_bp.route('/<int:id>/ejecutivo/materiales/json')
@login_required
def ejecutivo_materiales_json(id):
    """Misma info que la vista pero como JSON (para refrescar sin reload)."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    presupuesto = Presupuesto.query.filter_by(
        id=id, organizacion_id=org_id,
    ).first_or_404()

    materiales = sincronizar_materiales_cotizables(presupuesto)
    data = []
    for mat in materiales:
        data.append({
            'id': mat.id,
            'descripcion': mat.descripcion,
            'unidad': mat.unidad,
            'cantidad_total': float(mat.cantidad_total or 0),
            'estado': mat.estado,
            'grupo_hash': mat.grupo_hash,
            'item_inventario_id': mat.item_inventario_id,
            'proveedor_elegido_id': mat.proveedor_elegido_id,
            'precio_elegido': float(mat.precio_elegido or 0) if mat.precio_elegido else None,
            'num_composiciones': mat.composiciones.count(),
        })
    return jsonify(ok=True, materiales=data)


# ============================================================================
# FASE B - Asignar proveedores y generar solicitudes WhatsApp
# ============================================================================

def _verificar_permiso_ejecutivo():
    rol = getattr(current_user, 'role', '') or ''
    return rol in ('admin', 'administrador', 'pm', 'project_manager')


@presupuestos_bp.route('/ejecutivo/material/<int:material_id>/asignar-proveedor', methods=['POST'])
@login_required
def material_asignar_proveedor(material_id):
    """Asigna un proveedor a un material cotizable (antes de enviar solicitud).

    Body JSON: {"proveedor_id": 42}
    """
    if not _verificar_permiso_ejecutivo():
        return jsonify(ok=False, error='Sin permisos'), 403

    org_id = get_current_org_id()
    mat = MaterialCotizable.query.get_or_404(material_id)
    if mat.presupuesto.organizacion_id != org_id:
        return jsonify(ok=False, error='Material no pertenece a tu organización'), 403

    data = request.get_json(silent=True) or {}
    prov_id = data.get('proveedor_id')
    if not prov_id:
        return jsonify(ok=False, error='proveedor_id requerido'), 400

    prov = ProveedorOC.query.filter_by(id=prov_id, organizacion_id=org_id).first()
    if not prov:
        return jsonify(ok=False, error='Proveedor no encontrado'), 404

    existente = ProveedorAsignadoMaterial.query.filter_by(
        material_cotizable_id=mat.id, proveedor_id=prov.id,
    ).first()
    if existente:
        return jsonify(ok=False, error='Proveedor ya asignado a este material'), 400

    asignacion = ProveedorAsignadoMaterial(
        material_cotizable_id=mat.id,
        proveedor_id=prov.id,
    )
    db.session.add(asignacion)
    db.session.commit()

    return jsonify(ok=True, asignacion_id=asignacion.id, proveedor={
        'id': prov.id, 'razon_social': prov.razon_social,
    })


@presupuestos_bp.route('/ejecutivo/asignacion/<int:asignacion_id>', methods=['DELETE'])
@login_required
def material_desasignar_proveedor(asignacion_id):
    """Elimina la asignación proveedor-material (solo si aún no se generó solicitud)."""
    if not _verificar_permiso_ejecutivo():
        return jsonify(ok=False, error='Sin permisos'), 403

    org_id = get_current_org_id()
    asignacion = ProveedorAsignadoMaterial.query.get_or_404(asignacion_id)
    if asignacion.material_cotizable.presupuesto.organizacion_id != org_id:
        return jsonify(ok=False, error='No pertenece a tu organización'), 403

    if asignacion.solicitud_item_id:
        return jsonify(
            ok=False,
            error='Este proveedor ya fue incluido en una solicitud enviada. No se puede desasignar desde acá.',
        ), 400

    db.session.delete(asignacion)
    db.session.commit()
    return jsonify(ok=True)


def _generar_mensaje_whatsapp(presupuesto, org_nombre, items_info):
    """Arma el mensaje WhatsApp agrupado para un proveedor.

    items_info: lista de dicts {descripcion, cantidad, unidad}
    """
    lineas = [f'Hola! {org_nombre or "OBYRA"} - Presupuesto {presupuesto.numero}']
    if presupuesto.datos_proyecto:
        try:
            dp = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
            nombre_obra = dp.get('nombre_obra') or dp.get('nombre')
            if nombre_obra:
                lineas.append(f'Obra: {nombre_obra}')
        except (json.JSONDecodeError, TypeError):
            pass

    lineas.append('')
    lineas.append('Necesito cotización para los siguientes recursos:')
    lineas.append('')
    for i, it in enumerate(items_info, start=1):
        cant = it['cantidad']
        # Formatear cantidad: si es entero, sin decimales; si no, con máx 3
        if cant == int(cant):
            cant_str = str(int(cant))
        else:
            cant_str = f'{cant:.3f}'.rstrip('0').rstrip('.')
        lineas.append(f"{i}. {it['descripcion']} — {cant_str} {it['unidad']}")
    lineas.append('')
    lineas.append('Por favor respondeme con el precio unitario de cada uno.')
    lineas.append('Gracias!')

    return '\n'.join(lineas)


@presupuestos_bp.route('/<int:id>/ejecutivo/generar-solicitudes', methods=['POST'])
@login_required
def ejecutivo_generar_solicitudes(id):
    """Agrupa asignaciones pendientes por proveedor y crea una SolicitudCotizacionMaterial
    por cada uno con sus items. Genera mensaje WhatsApp + URL wa.me.

    Devuelve lista de solicitudes creadas con sus URLs para abrir.
    """
    if not _verificar_permiso_ejecutivo():
        return jsonify(ok=False, error='Sin permisos'), 403

    org_id = get_current_org_id()
    presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

    # Traer asignaciones pendientes (sin solicitud_item_id)
    asignaciones = db.session.query(ProveedorAsignadoMaterial).join(
        MaterialCotizable, MaterialCotizable.id == ProveedorAsignadoMaterial.material_cotizable_id,
    ).filter(
        MaterialCotizable.presupuesto_id == presupuesto.id,
        ProveedorAsignadoMaterial.solicitud_item_id.is_(None),
    ).all()

    if not asignaciones:
        return jsonify(
            ok=False,
            error='No hay asignaciones pendientes. Asigná proveedores a los recursos primero.',
        ), 400

    # Agrupar por proveedor_id
    por_proveedor = {}  # prov_id -> [asignaciones]
    for a in asignaciones:
        por_proveedor.setdefault(a.proveedor_id, []).append(a)

    from services.whatsapp_service import normalizar_telefono, generar_url_wa_me

    org_nombre = None
    try:
        from models import Organizacion
        org = Organizacion.query.get(org_id)
        if org:
            org_nombre = getattr(org, 'nombre_fantasia', None) or org.nombre
    except Exception:
        pass

    solicitudes_creadas = []
    for prov_id, asigns in por_proveedor.items():
        prov = ProveedorOC.query.get(prov_id)
        if not prov:
            continue

        # Calcular versión: cuántas solicitudes previas tenemos para este proveedor
        version = 1 + db.session.query(SolicitudCotizacionMaterial).filter_by(
            presupuesto_id=presupuesto.id, proveedor_id=prov.id,
        ).count()

        items_info = []
        for a in asigns:
            mat = a.material_cotizable
            items_info.append({
                'descripcion': mat.descripcion,
                'cantidad': float(mat.cantidad_total or 0),
                'unidad': mat.unidad,
            })

        mensaje = _generar_mensaje_whatsapp(presupuesto, org_nombre, items_info)
        telefono = normalizar_telefono(prov.telefono) if prov.telefono else None
        wa_url = generar_url_wa_me(telefono, mensaje) if telefono else None

        solicitud = SolicitudCotizacionMaterial(
            presupuesto_id=presupuesto.id,
            proveedor_id=prov.id,
            version=version,
            estado='pendiente',
            mensaje_texto=mensaje,
            wa_url=wa_url,
        )
        db.session.add(solicitud)
        db.session.flush()

        for a in asigns:
            mat = a.material_cotizable
            item_solicitud = SolicitudCotizacionMaterialItem(
                solicitud_id=solicitud.id,
                material_cotizable_id=mat.id,
                descripcion_snapshot=mat.descripcion,
                unidad_snapshot=mat.unidad,
                cantidad_snapshot=mat.cantidad_total,
            )
            db.session.add(item_solicitud)
            db.session.flush()

            # Linkear asignación a su item (para no re-procesar)
            a.solicitud_item_id = item_solicitud.id

            # Marcar material como 'cotizando'
            if mat.estado == 'nuevo':
                mat.estado = 'cotizando'

        solicitudes_creadas.append({
            'solicitud_id': solicitud.id,
            'proveedor_id': prov.id,
            'proveedor_razon_social': prov.razon_social,
            'telefono': telefono,
            'wa_url': wa_url,
            'num_items': len(asigns),
            'version': version,
            'sin_telefono': not telefono,
        })

    db.session.commit()
    return jsonify(ok=True, solicitudes=solicitudes_creadas)


@presupuestos_bp.route('/<int:id>/ejecutivo/solicitudes')
@login_required
def ejecutivo_solicitudes_listar(id):
    """Lista todas las solicitudes de cotización generadas para el presupuesto."""
    org_id = get_current_org_id()
    if not org_id:
        return jsonify(ok=False, error='Sin organización activa'), 400

    presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()
    sols = SolicitudCotizacionMaterial.query.filter_by(
        presupuesto_id=presupuesto.id,
    ).order_by(SolicitudCotizacionMaterial.fecha_creacion.desc()).all()

    data = []
    for s in sols:
        items = []
        for it in s.items.order_by(SolicitudCotizacionMaterialItem.id):
            items.append({
                'id': it.id,
                'descripcion': it.descripcion_snapshot,
                'cantidad': float(it.cantidad_snapshot or 0),
                'unidad': it.unidad_snapshot,
                'precio_respuesta': float(it.precio_respuesta) if it.precio_respuesta else None,
                'elegido': it.elegido,
            })
        data.append({
            'id': s.id,
            'proveedor_id': s.proveedor_id,
            'proveedor_razon_social': s.proveedor.razon_social if s.proveedor else '—',
            'version': s.version,
            'estado': s.estado,
            'fecha_creacion': s.fecha_creacion.isoformat() if s.fecha_creacion else None,
            'fecha_enviado': s.fecha_enviado.isoformat() if s.fecha_enviado else None,
            'wa_url': s.wa_url,
            'mensaje': s.mensaje_texto,
            'items': items,
        })
    return jsonify(ok=True, solicitudes=data)


@presupuestos_bp.route('/ejecutivo/solicitud/<int:solicitud_id>/marcar-enviada', methods=['POST'])
@login_required
def ejecutivo_solicitud_marcar_enviada(solicitud_id):
    """Marca la solicitud como enviada (cuando el PM tocó el link WA)."""
    if not _verificar_permiso_ejecutivo():
        return jsonify(ok=False, error='Sin permisos'), 403

    org_id = get_current_org_id()
    s = SolicitudCotizacionMaterial.query.get_or_404(solicitud_id)
    if s.presupuesto.organizacion_id != org_id:
        return jsonify(ok=False, error='No pertenece a tu organización'), 403

    if s.estado == 'pendiente':
        s.estado = 'enviado'
    if not s.fecha_enviado:
        s.fecha_enviado = datetime.utcnow()
    db.session.commit()
    return jsonify(ok=True, estado=s.estado)


# ============================================================================
# FASE C - Cargar respuestas + comparativa + elegir ganador
# ============================================================================

@presupuestos_bp.route('/ejecutivo/solicitud/<int:solicitud_id>/respuestas', methods=['POST'])
@login_required
def ejecutivo_solicitud_cargar_respuestas(solicitud_id):
    """Carga los precios que respondió un proveedor para cada item de la solicitud.

    Body JSON: {
      "items": [
        {"item_id": 12, "precio": 8500, "notas": "entrega 48hs"},
        {"item_id": 13, "precio": 1250, "notas": null}
      ]
    }
    """
    if not _verificar_permiso_ejecutivo():
        return jsonify(ok=False, error='Sin permisos'), 403

    org_id = get_current_org_id()
    solicitud = SolicitudCotizacionMaterial.query.get_or_404(solicitud_id)
    if solicitud.presupuesto.organizacion_id != org_id:
        return jsonify(ok=False, error='No pertenece a tu organización'), 403

    data = request.get_json(silent=True) or {}
    items_data = data.get('items') or []
    if not isinstance(items_data, list):
        return jsonify(ok=False, error='items debe ser una lista'), 400

    # Mapear items de la solicitud para validar que los ids enviados pertenecen a esta solicitud
    items_by_id = {it.id: it for it in solicitud.items}

    actualizados = 0
    materiales_afectados = set()
    for row in items_data:
        item_id = row.get('item_id')
        if item_id not in items_by_id:
            continue
        item = items_by_id[item_id]
        precio_raw = row.get('precio')
        notas = (row.get('notas') or '').strip() or None

        if precio_raw is None or precio_raw == '':
            # Sin precio = no cotizó ese ítem. Limpio cualquier respuesta previa.
            item.precio_respuesta = None
        else:
            precio = _parse_decimal(precio_raw, '0')
            if precio < 0:
                continue
            item.precio_respuesta = precio
        item.notas_respuesta = notas
        materiales_afectados.add(item.material_cotizable_id)
        actualizados += 1

    # Actualizar estado de la solicitud
    if any(it.precio_respuesta is not None for it in solicitud.items):
        solicitud.estado = 'respondido'
        if not solicitud.fecha_respondido:
            solicitud.fecha_respondido = datetime.utcnow()

    # Actualizar estado de los materiales afectados
    for mat_id in materiales_afectados:
        mat = MaterialCotizable.query.get(mat_id)
        if not mat:
            continue
        if mat.estado == 'elegido':
            continue  # ya se eligió ganador, no bajar de estado
        # Si hay al menos una respuesta con precio, estado='con_respuestas'
        respuestas_count = db.session.query(SolicitudCotizacionMaterialItem).filter(
            SolicitudCotizacionMaterialItem.material_cotizable_id == mat_id,
            SolicitudCotizacionMaterialItem.precio_respuesta.isnot(None),
        ).count()
        mat.estado = 'con_respuestas' if respuestas_count > 0 else 'cotizando'

    db.session.commit()
    return jsonify(ok=True, actualizados=actualizados)


@presupuestos_bp.route('/ejecutivo/material/<int:material_id>/comparativa')
@login_required
def ejecutivo_material_comparativa(material_id):
    """Devuelve la comparativa de precios de un material (todas las respuestas
    de proveedores a través de todas las solicitudes/versiones).
    """
    org_id = get_current_org_id()
    mat = MaterialCotizable.query.get_or_404(material_id)
    if mat.presupuesto.organizacion_id != org_id:
        return jsonify(ok=False, error='No pertenece a tu organización'), 403

    # Traer todos los items de solicitud para este material con su solicitud+proveedor
    items = db.session.query(SolicitudCotizacionMaterialItem).join(
        SolicitudCotizacionMaterial,
        SolicitudCotizacionMaterial.id == SolicitudCotizacionMaterialItem.solicitud_id,
    ).filter(
        SolicitudCotizacionMaterialItem.material_cotizable_id == mat.id,
    ).order_by(SolicitudCotizacionMaterial.fecha_creacion.desc()).all()

    respuestas = []
    for it in items:
        s = it.solicitud
        prov = s.proveedor
        precio = float(it.precio_respuesta) if it.precio_respuesta else None
        subtotal = precio * float(mat.cantidad_total or 0) if precio else None
        respuestas.append({
            'item_id': it.id,
            'solicitud_id': s.id,
            'version': s.version,
            'proveedor_id': prov.id if prov else None,
            'proveedor_razon_social': prov.razon_social if prov else '—',
            'proveedor_telefono': prov.telefono if prov else None,
            'precio': precio,
            'subtotal': subtotal,
            'notas': it.notas_respuesta,
            'elegido': it.elegido,
            'fecha_solicitud': s.fecha_creacion.isoformat() if s.fecha_creacion else None,
            'fecha_respuesta': s.fecha_respondido.isoformat() if s.fecha_respondido else None,
            'estado_solicitud': s.estado,
        })

    # Identificar el mejor precio (más bajo, solo entre los con precio cargado)
    precios_validos = [r for r in respuestas if r['precio'] is not None]
    mejor_precio = min((r['precio'] for r in precios_validos), default=None)

    return jsonify(
        ok=True,
        material={
            'id': mat.id,
            'descripcion': mat.descripcion,
            'unidad': mat.unidad,
            'cantidad_total': float(mat.cantidad_total or 0),
            'estado': mat.estado,
            'tipo': mat.tipo,
            'proveedor_elegido_id': mat.proveedor_elegido_id,
            'precio_elegido': float(mat.precio_elegido) if mat.precio_elegido else None,
        },
        respuestas=respuestas,
        mejor_precio=mejor_precio,
    )


@presupuestos_bp.route('/ejecutivo/material/<int:material_id>/elegir-ganador', methods=['POST'])
@login_required
def ejecutivo_material_elegir_ganador(material_id):
    """Marca un SolicitudCotizacionMaterialItem como ganador y propaga su
    precio a todas las composiciones que componen este MaterialCotizable.

    Body JSON: {"item_id": 42}
    """
    if not _verificar_permiso_ejecutivo():
        return jsonify(ok=False, error='Sin permisos'), 403

    org_id = get_current_org_id()
    mat = MaterialCotizable.query.get_or_404(material_id)
    if mat.presupuesto.organizacion_id != org_id:
        return jsonify(ok=False, error='No pertenece a tu organización'), 403

    if mat.presupuesto.ejecutivo_aprobado:
        return jsonify(
            ok=False,
            error='El ejecutivo está aprobado. Revertí la aprobación antes de elegir ganador.',
        ), 400

    data = request.get_json(silent=True) or {}
    item_id = data.get('item_id')
    if not item_id:
        return jsonify(ok=False, error='item_id requerido'), 400

    item = SolicitudCotizacionMaterialItem.query.get(item_id)
    if not item or item.material_cotizable_id != mat.id:
        return jsonify(ok=False, error='item no pertenece a este material'), 400

    if item.precio_respuesta is None:
        return jsonify(
            ok=False,
            error='Ese proveedor todavía no cargó precio para este recurso.',
        ), 400

    # 1. Marcar todos los items del material como NO elegidos
    db.session.query(SolicitudCotizacionMaterialItem).filter_by(
        material_cotizable_id=mat.id,
    ).update({'elegido': False})

    # 2. Marcar este item como ganador
    item.elegido = True
    mat.proveedor_elegido_id = item.solicitud.proveedor_id
    mat.precio_elegido = item.precio_respuesta
    mat.estado = 'elegido'

    # 3. Propagar precio a todas las composiciones del material.
    #    Esto actualiza el COSTO ESTIMADO del ejecutivo — NO afecta el precio
    #    vendido al cliente (ese es el total del ItemPresupuesto padre).
    comps_afectadas = 0
    for comp in mat.composiciones:
        comp.precio_unitario = item.precio_respuesta
        comp.recalcular_total()
        comps_afectadas += 1

    db.session.commit()

    return jsonify(
        ok=True,
        proveedor_razon_social=item.solicitud.proveedor.razon_social,
        precio_elegido=float(item.precio_respuesta),
        composiciones_actualizadas=comps_afectadas,
    )


@presupuestos_bp.route('/ejecutivo/material/<int:material_id>/desmarcar-ganador', methods=['POST'])
@login_required
def ejecutivo_material_desmarcar_ganador(material_id):
    """Deshace la elección de ganador para un material (devuelve a estado
    'con_respuestas' y limpia precio_elegido / composiciones vuelven a 0).
    """
    if not _verificar_permiso_ejecutivo():
        return jsonify(ok=False, error='Sin permisos'), 403

    org_id = get_current_org_id()
    mat = MaterialCotizable.query.get_or_404(material_id)
    if mat.presupuesto.organizacion_id != org_id:
        return jsonify(ok=False, error='No pertenece a tu organización'), 403

    if mat.presupuesto.ejecutivo_aprobado:
        return jsonify(
            ok=False,
            error='Ejecutivo aprobado. Revertí la aprobación primero.',
        ), 400

    db.session.query(SolicitudCotizacionMaterialItem).filter_by(
        material_cotizable_id=mat.id,
    ).update({'elegido': False})

    mat.proveedor_elegido_id = None
    mat.precio_elegido = None
    mat.estado = 'con_respuestas' if mat.respuestas.filter(
        SolicitudCotizacionMaterialItem.precio_respuesta.isnot(None)
    ).count() > 0 else 'cotizando'

    for comp in mat.composiciones:
        comp.precio_unitario = Decimal('0')
        comp.recalcular_total()

    db.session.commit()
    return jsonify(ok=True)
