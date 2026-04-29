"""Blueprint de Categorias de Jornal (mano de obra).

Catalogo hibrido:
  - Categorias globales (organizacion_id IS NULL): curadas por OBYRA superadmin,
    visibles a todos los tenants.
  - Categorias por tenant: cargadas por la propia constructora.

Cada constructora ve: globales + propias. Solo el superadmin edita las globales.
Cada tenant edita las propias.

Endpoints:
  GET  /jornales                        -> pagina HTML con la tabla
  GET  /jornales/api                    -> JSON con jornales visibles
  POST /jornales                        -> crear (form o JSON)
  POST /jornales/<id>                   -> editar (form o JSON)
  POST /jornales/<id>/eliminar          -> soft delete
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from datetime import date

from extensions import db
from services.memberships import get_current_org_id


jornales_bp = Blueprint('jornales', __name__, url_prefix='/jornales')


def _es_super_admin():
    return bool(getattr(current_user, 'is_super_admin', False))


def _tiene_permiso():
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm')


def _puede_editar(cat, org_id):
    if cat.is_global:
        return _es_super_admin()
    return cat.organizacion_id == org_id


def _query_visible(org_id):
    from models.budgets import CategoriaJornal
    from sqlalchemy import or_
    base = CategoriaJornal.query.filter_by(activo=True)
    if _es_super_admin():
        return base
    return base.filter(or_(
        CategoriaJornal.organizacion_id.is_(None),
        CategoriaJornal.organizacion_id == org_id,
    ))


@jornales_bp.route('/')
@login_required
def lista():
    if not _tiene_permiso():
        flash('No tiene permisos para ver categorias de jornal.', 'danger')
        return redirect(url_for('main.dashboard'))

    from models.budgets import CategoriaJornal, VariacionCacPendiente
    org_id = get_current_org_id()
    cats = _query_visible(org_id).order_by(
        CategoriaJornal.organizacion_id.asc().nullsfirst(),  # globales primero
        CategoriaJornal.nombre,
    ).all()

    # Variaciones CAC pendientes (solo para superadmin)
    pendientes = []
    if _es_super_admin():
        pendientes = VariacionCacPendiente.query.filter_by(estado='pendiente').order_by(
            VariacionCacPendiente.periodo.desc()
        ).limit(5).all()

    return render_template('jornales/lista.html',
                           jornales=cats,
                           es_super_admin=_es_super_admin(),
                           org_id=org_id,
                           variaciones_pendientes=pendientes)


@jornales_bp.route('/api')
@login_required
def api_lista():
    """JSON con jornales visibles - usado por el modal de MO en presupuestos."""
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    cats = _query_visible(org_id).order_by(
        CategoriaJornal.organizacion_id.asc().nullsfirst(),
        CategoriaJornal.nombre,
    ).all()
    return jsonify({'ok': True, 'jornales': [c.to_dict() for c in cats]})


@jornales_bp.route('/', methods=['POST'])
@login_required
def crear():
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    data = request.get_json(silent=True) or request.form

    nombre = (data.get('nombre') or '').strip()
    if not nombre:
        return jsonify({'ok': False, 'error': 'Nombre obligatorio'}), 400

    try:
        precio = float(data.get('precio_jornal') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Precio jornal invalido'}), 400

    es_global = bool(data.get('global')) and _es_super_admin()
    cat = CategoriaJornal(
        organizacion_id=None if es_global else org_id,
        nombre=nombre[:120],
        codigo=(data.get('codigo') or '').strip()[:40] or None,
        precio_jornal=precio,
        moneda=(data.get('moneda') or 'ARS').strip()[:3].upper(),
        fuente=(data.get('fuente') or 'manual').strip()[:40],
        notas=(data.get('notas') or '').strip() or None,
        vigencia_desde=date.today(),
        activo=True,
        created_by_id=current_user.id,
    )

    try:
        db.session.add(cat)
        db.session.commit()
        return jsonify({'ok': True, 'categoria': cat.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error creando categoria jornal')
        return jsonify({'ok': False, 'error': str(e)}), 500


@jornales_bp.route('/<int:id>', methods=['POST'])
@login_required
def editar(id):
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    cat = CategoriaJornal.query.get_or_404(id)
    if not _puede_editar(cat, org_id):
        return jsonify({'ok': False, 'error': 'Esta categoria es global y solo la edita OBYRA'}), 403

    data = request.get_json(silent=True) or request.form
    if 'nombre' in data:
        cat.nombre = (data.get('nombre') or '').strip()[:120] or cat.nombre
    if 'codigo' in data:
        cat.codigo = (data.get('codigo') or '').strip()[:40] or None
    if 'precio_jornal' in data:
        try:
            cat.precio_jornal = float(data.get('precio_jornal') or 0)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Precio jornal invalido'}), 400
    if 'moneda' in data:
        cat.moneda = (data.get('moneda') or 'ARS').strip()[:3].upper()
    if 'notas' in data:
        cat.notas = (data.get('notas') or '').strip() or None
    if 'fuente' in data:
        cat.fuente = (data.get('fuente') or 'manual').strip()[:40]

    cat.vigencia_desde = date.today()

    try:
        db.session.commit()
        return jsonify({'ok': True, 'categoria': cat.to_dict()})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error editando categoria jornal')
        return jsonify({'ok': False, 'error': str(e)}), 500


@jornales_bp.route('/aplicar-variacion', methods=['POST'])
@login_required
def aplicar_variacion():
    """Aplica una variacion porcentual a las categorias visibles.

    Body JSON:
      - porcentaje: float (ej 3.2 = +3.2%, -1.5 = -1.5%)
      - alcance: 'globales' | 'mias' | 'todas' (segun permisos)
      - confirmar: bool (false = preview, true = aplicar)
      - nota: string opcional (queda en `notas` de cada categoria como traza)

    Retorna:
      - preview: lista de {id, nombre, precio_actual, precio_nuevo, delta}
      - aplicados: cuantas filas se modificaron (solo si confirmar=true)
    """
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from models.budgets import CategoriaJornal
    from sqlalchemy import or_
    from decimal import Decimal, ROUND_HALF_UP

    org_id = get_current_org_id()
    data = request.get_json(silent=True) or {}

    try:
        porcentaje = float(data.get('porcentaje'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Porcentaje invalido'}), 400
    if porcentaje < -50 or porcentaje > 100:
        return jsonify({'ok': False, 'error': 'Porcentaje fuera de rango razonable (-50% a +100%)'}), 400

    alcance = (data.get('alcance') or 'mias').strip().lower()
    confirmar = bool(data.get('confirmar'))
    nota = (data.get('nota') or '').strip()

    # Construir query segun alcance
    q = CategoriaJornal.query.filter_by(activo=True)
    if alcance == 'globales':
        if not _es_super_admin():
            return jsonify({'ok': False, 'error': 'Solo superadmin puede actualizar las globales.'}), 403
        q = q.filter(CategoriaJornal.organizacion_id.is_(None))
    elif alcance == 'todas':
        if not _es_super_admin():
            # tenant no superadmin: 'todas' = visibles para mi (globales + mias)
            q = q.filter(or_(
                CategoriaJornal.organizacion_id.is_(None),
                CategoriaJornal.organizacion_id == org_id,
            ))
        # superadmin ve todas, sin filtro
    else:  # 'mias'
        q = q.filter(CategoriaJornal.organizacion_id == org_id)

    cats = q.order_by(CategoriaJornal.nombre).all()
    if not cats:
        return jsonify({'ok': False, 'error': 'No hay categorias para actualizar con ese alcance.'}), 400

    factor = Decimal(str(1 + (porcentaje / 100)))
    quant = Decimal('0.01')

    preview = []
    for c in cats:
        actual = Decimal(str(c.precio_jornal or 0))
        nuevo = (actual * factor).quantize(quant, rounding=ROUND_HALF_UP)
        preview.append({
            'id': c.id,
            'nombre': c.nombre,
            'is_global': c.is_global,
            'precio_actual': float(actual),
            'precio_nuevo': float(nuevo),
            'delta': float(nuevo - actual),
        })

    if not confirmar:
        return jsonify({'ok': True, 'preview': preview, 'aplicado': False})

    # Aplicar
    from datetime import date as _date
    aplicados = 0
    for c, item in zip(cats, preview):
        if alcance == 'globales' and not c.is_global:
            continue
        # Defensa: tenant no puede tocar globales
        if c.is_global and not _es_super_admin():
            continue
        if not c.is_global and c.organizacion_id != org_id and not _es_super_admin():
            continue
        c.precio_jornal = item['precio_nuevo']
        c.vigencia_desde = _date.today()
        if nota:
            existente = (c.notas or '').strip()
            traza = f'[{_date.today().isoformat()}] {nota} ({porcentaje:+.2f}%)'
            c.notas = (existente + '\n' + traza).strip() if existente else traza
        aplicados += 1

    try:
        db.session.commit()
        return jsonify({'ok': True, 'preview': preview, 'aplicado': True, 'aplicados': aplicados})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error aplicando variacion jornales')
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================
# CAC: variaciones pendientes (scraper Indicador Camarco)
# ============================================================

@jornales_bp.route('/cac/buscar', methods=['POST'])
@login_required
def cac_buscar_variacion():
    """Dispara el scraper, registra la variacion como pendiente si no existe."""
    if not _es_super_admin():
        return jsonify({'ok': False, 'error': 'Solo superadmin puede buscar variaciones CAC.'}), 403

    from services.cac_scraper import buscar_ultimo_indicador
    from models.budgets import VariacionCacPendiente

    info = buscar_ultimo_indicador()
    if not info:
        return jsonify({'ok': False, 'error': 'No se pudo obtener el ultimo Indicador Camarco. Revisa el sitio manualmente y carga la variacion con el boton "Aplicar variacion CAC".'}), 502

    # Upsert por periodo
    existente = VariacionCacPendiente.query.filter_by(periodo=info['periodo']).first()
    if existente:
        # actualizar valores si cambiaron, pero no pisar estado
        existente.porcentaje_mo = info.get('porcentaje_mo')
        existente.porcentaje_general = info.get('porcentaje_general')
        existente.indice_general = info.get('indice_general')
        existente.fuente_url = info.get('fuente_url')
        existente.fuente_titulo = info.get('fuente_titulo')
        nuevo = False
    else:
        existente = VariacionCacPendiente(
            periodo=info['periodo'],
            porcentaje_mo=info.get('porcentaje_mo'),
            porcentaje_general=info.get('porcentaje_general'),
            indice_general=info.get('indice_general'),
            fuente_url=info.get('fuente_url'),
            fuente_titulo=info.get('fuente_titulo'),
            estado='pendiente',
        )
        db.session.add(existente)
        nuevo = True

    try:
        db.session.commit()
        return jsonify({'ok': True, 'nuevo': nuevo, 'variacion': existente.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@jornales_bp.route('/cac/pendientes')
@login_required
def cac_listar_pendientes():
    """Devuelve las variaciones CAC en estado pendiente."""
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403
    from models.budgets import VariacionCacPendiente
    rows = VariacionCacPendiente.query.filter_by(estado='pendiente').order_by(
        VariacionCacPendiente.periodo.desc()
    ).all()
    return jsonify({'ok': True, 'pendientes': [r.to_dict() for r in rows]})


@jornales_bp.route('/cac/<int:variacion_id>/aplicar', methods=['POST'])
@login_required
def cac_aplicar_variacion(variacion_id):
    """Aplica el % de la variacion pendiente a las globales y la marca como aplicada."""
    if not _es_super_admin():
        return jsonify({'ok': False, 'error': 'Solo superadmin'}), 403

    from models.budgets import VariacionCacPendiente, CategoriaJornal
    from datetime import date as _date, datetime
    from decimal import Decimal, ROUND_HALF_UP

    var = VariacionCacPendiente.query.get_or_404(variacion_id)
    if var.estado != 'pendiente':
        return jsonify({'ok': False, 'error': f'Variacion ya esta {var.estado}'}), 400
    if var.porcentaje_mo is None:
        return jsonify({'ok': False, 'error': 'Sin % de MO para aplicar'}), 400

    pct = float(var.porcentaje_mo)
    factor = Decimal(str(1 + pct / 100))
    quant = Decimal('0.01')

    cats = CategoriaJornal.query.filter(
        CategoriaJornal.activo.is_(True),
        CategoriaJornal.organizacion_id.is_(None),
    ).all()
    aplicados = 0
    for c in cats:
        actual = Decimal(str(c.precio_jornal or 0))
        if actual <= 0:
            continue
        c.precio_jornal = (actual * factor).quantize(quant, rounding=ROUND_HALF_UP)
        c.vigencia_desde = var.periodo
        traza = f'[{var.periodo.strftime("%b %Y")}] CAC MO {pct:+.2f}%'
        c.notas = ((c.notas or '').strip() + '\n' + traza).strip()
        aplicados += 1

    var.estado = 'aplicada'
    var.aplicado_at = datetime.utcnow()
    var.aplicado_por_id = current_user.id

    try:
        db.session.commit()
        return jsonify({'ok': True, 'aplicados': aplicados, 'porcentaje': pct})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@jornales_bp.route('/cac/<int:variacion_id>/descartar', methods=['POST'])
@login_required
def cac_descartar_variacion(variacion_id):
    """Marca la variacion como descartada (no aplicar)."""
    if not _es_super_admin():
        return jsonify({'ok': False, 'error': 'Solo superadmin'}), 403
    from models.budgets import VariacionCacPendiente
    var = VariacionCacPendiente.query.get_or_404(variacion_id)
    if var.estado != 'pendiente':
        return jsonify({'ok': False, 'error': f'Ya esta {var.estado}'}), 400
    motivo = (request.get_json(silent=True) or {}).get('motivo') or ''
    var.estado = 'descartada'
    var.descartado_motivo = motivo[:500]
    try:
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@jornales_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar(id):
    if not _tiene_permiso():
        return jsonify({'ok': False, 'error': 'Sin permisos'}), 403

    from models.budgets import CategoriaJornal
    org_id = get_current_org_id()
    cat = CategoriaJornal.query.get_or_404(id)
    if not _puede_editar(cat, org_id):
        return jsonify({'ok': False, 'error': 'No autorizado'}), 403

    cat.activo = False
    try:
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
