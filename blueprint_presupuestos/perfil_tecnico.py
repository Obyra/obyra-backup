"""Endpoints del Perfil Tecnico del Proyecto (Fase 2).

  GET  /presupuestos/<id>/perfil-tecnico    -> JSON con perfil + niveles
  POST /presupuestos/<id>/perfil-tecnico    -> crear/actualizar perfil

Multi-tenant: solo puede operar el usuario de la organizacion duena del
presupuesto, o un super admin.
"""
from __future__ import annotations

from flask import request, jsonify, current_app
from flask_login import login_required, current_user

from extensions import db
from services.memberships import get_current_org_id
from blueprint_presupuestos import presupuestos_bp


def _es_super_admin():
    return bool(getattr(current_user, 'is_super_admin', False))


def _verificar_acceso_presupuesto(presupuesto):
    if not current_user.is_authenticated:
        return False
    if _es_super_admin():
        return True
    org_id = get_current_org_id()
    return presupuesto.organizacion_id == org_id


def _puede_gestionar():
    rol = getattr(current_user, 'rol', '') or ''
    role = getattr(current_user, 'role', '') or ''
    return rol in ('administrador', 'admin') or role in ('admin', 'pm', 'project_manager')


@presupuestos_bp.route('/<int:id>/perfil-tecnico', methods=['GET'])
@login_required
def perfil_tecnico_get(id):
    """Devuelve el perfil tecnico + niveles del presupuesto.

    Si no hay perfil cargado, devuelve ok=True con profile=None para que el
    frontend muestre "Sin perfil tecnico cargado" + boton de completar.
    """
    from models.budgets import Presupuesto
    from models.project_technical_profile import ProjectTechnicalProfile

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403

    profile = ProjectTechnicalProfile.query.filter_by(presupuesto_id=presupuesto.id).first()
    if not profile:
        return jsonify(ok=True, profile=None, niveles=[])

    return jsonify(ok=True, profile=profile.to_dict(include_niveles=True))


@presupuestos_bp.route('/<int:id>/perfil-tecnico', methods=['POST'])
@login_required
def perfil_tecnico_post(id):
    """Crea o actualiza el perfil tecnico del presupuesto.

    Body JSON con cualquier subset de campos (ver validar_y_normalizar).
    Retorna {ok, profile, niveles_generados, fue_creacion}.
    """
    from models.budgets import Presupuesto
    from services.perfil_tecnico_service import upsert_perfil_tecnico

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403

    # Bloquear edicion de perfil tecnico si el presupuesto esta aprobado.
    # En estado borrador / enviado se puede editar libremente.
    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(
            ok=False,
            error=f'No se puede modificar el perfil tecnico de un presupuesto en estado {presupuesto.estado}',
        ), 400

    payload = request.get_json(silent=True) or request.form.to_dict()
    autogenerar = bool(payload.get('autogenerar_niveles', True))

    try:
        result = upsert_perfil_tecnico(
            presupuesto=presupuesto,
            payload=payload,
            user_id=current_user.id if current_user.is_authenticated else None,
            autogenerar_niveles=autogenerar,
        )
    except ValueError as ve:
        db.session.rollback()
        return jsonify(ok=False, error=str(ve)), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error guardando perfil tecnico')
        return jsonify(ok=False, error='Error interno guardando el perfil'), 500

    # Audit
    try:
        from models.audit import registrar_audit
        registrar_audit(
            accion='crear_perfil_tecnico' if result['fue_creacion'] else 'editar_perfil_tecnico',
            entidad='presupuesto',
            entidad_id=presupuesto.id,
            detalle=(
                f'tipo_obra={result["profile"].tipo_obra} '
                f'pisos={result["profile"].cantidad_pisos} '
                f'subsuelos={result["profile"].cantidad_subsuelos} '
                f'criterio={result["profile"].criterio_distribucion} '
                f'niveles_generados={result["niveles_generados"]}'
            ),
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error commiteando perfil tecnico')
        return jsonify(ok=False, error=f'Error al guardar: {type(e).__name__}'), 500

    return jsonify(
        ok=True,
        profile=result['profile'].to_dict(include_niveles=True),
        niveles_generados=result['niveles_generados'],
        fue_creacion=result['fue_creacion'],
    )


# ============================================================
# CRUD por nivel del presupuesto (edicion manual de pisos)
# ============================================================

TIPOS_NIVEL_VALIDOS = ('subsuelo', 'pb', 'piso_tipo', 'piso_especial', 'terraza')


def _normalizar_payload_nivel(p, presupuesto):
    """Valida + normaliza un payload de nivel. Devuelve dict con keys solo
    de campos editables. Lanza ValueError si hay datos invalidos."""
    out = {}
    if 'nombre' in p:
        nombre = (str(p.get('nombre') or '').strip())[:100]
        if not nombre:
            raise ValueError('nombre es obligatorio')
        out['nombre'] = nombre
    if 'tipo_nivel' in p:
        tn = (str(p.get('tipo_nivel') or '').strip().lower())
        if tn and tn not in TIPOS_NIVEL_VALIDOS:
            raise ValueError(f'tipo_nivel invalido: {tn}')
        if tn:
            out['tipo_nivel'] = tn
    if 'area_m2' in p:
        try:
            v = float(str(p['area_m2']).replace(',', '.'))
            if v < 0 or v > 999999:
                raise ValueError()
            out['area_m2'] = v
        except (TypeError, ValueError):
            raise ValueError('area_m2 invalida')
    if 'repeticiones' in p:
        try:
            v = int(p['repeticiones'])
            if v < 1 or v > 200:
                raise ValueError()
            out['repeticiones'] = v
        except (TypeError, ValueError):
            raise ValueError('repeticiones invalida')
    if 'orden' in p:
        try:
            v = int(p['orden'])
            if v < 0 or v > 9999:
                raise ValueError()
            out['orden'] = v
        except (TypeError, ValueError):
            raise ValueError('orden invalido')
    if 'altura_m' in p:
        v_alt = p['altura_m']
        if v_alt in (None, ''):
            out['_altura_m'] = None
        else:
            try:
                fv = float(str(v_alt).replace(',', '.'))
                if fv < 0 or fv > 50:
                    raise ValueError()
                out['_altura_m'] = fv
            except (TypeError, ValueError):
                raise ValueError('altura_m invalida')
    if 'observaciones' in p:
        obs = (str(p.get('observaciones') or '').strip())[:300]
        out['observaciones'] = obs or None
    if 'excluido_del_calculo' in p:
        v = p['excluido_del_calculo']
        out['excluido_del_calculo'] = str(v).strip().lower() in ('1', 'true', 'on', 'yes', 'si', 'sí')
    return out


def _aplicar_payload_a_nivel(nivel, datos):
    """Asigna campos normalizados al modelo NivelPresupuesto."""
    for k in ('nombre', 'tipo_nivel', 'area_m2', 'repeticiones', 'orden',
              'observaciones', 'excluido_del_calculo'):
        if k in datos:
            setattr(nivel, k, datos[k])
    if '_altura_m' in datos:
        atrs = dict(nivel.atributos or {})
        if datos['_altura_m'] is None:
            atrs.pop('altura_libre', None)
        else:
            atrs['altura_libre'] = datos['_altura_m']
        nivel.atributos = atrs


def _bloquear_si_aprobado(presupuesto):
    if presupuesto.estado not in ('borrador', 'enviado'):
        return jsonify(ok=False, error=f'Presupuesto en estado {presupuesto.estado}: no editable.'), 400
    return None


@presupuestos_bp.route('/<int:id>/niveles', methods=['POST'])
@login_required
def nivel_crear(id):
    """Crea un nivel manual para el presupuesto."""
    from models.budgets import Presupuesto, NivelPresupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403
    bloqueo = _bloquear_si_aprobado(presupuesto)
    if bloqueo:
        return bloqueo

    payload = request.get_json(silent=True) or {}
    try:
        datos = _normalizar_payload_nivel(payload, presupuesto)
    except ValueError as ve:
        return jsonify(ok=False, error=str(ve)), 400

    # orden por defecto: ultimo + 10 (espacio para insertar entre)
    if 'orden' not in datos:
        ult = NivelPresupuesto.query.filter_by(presupuesto_id=presupuesto.id) \
            .order_by(NivelPresupuesto.orden.desc()).first()
        datos['orden'] = (ult.orden + 10) if ult else 1

    nivel = NivelPresupuesto(
        presupuesto_id=presupuesto.id,
        tipo_nivel=datos.get('tipo_nivel') or 'piso_tipo',
        nombre=datos.get('nombre') or 'Nivel sin nombre',
        orden=datos['orden'],
        repeticiones=datos.get('repeticiones', 1),
        area_m2=datos.get('area_m2', 0),
        sistema_constructivo='hormigon',
        hormigon_m3=0,
        albanileria_m2=0,
        atributos={},
        excluido_del_calculo=datos.get('excluido_del_calculo', False),
        observaciones=datos.get('observaciones'),
    )
    if '_altura_m' in datos:
        atrs = {}
        if datos['_altura_m'] is not None:
            atrs['altura_libre'] = datos['_altura_m']
        nivel.atributos = atrs
    db.session.add(nivel)

    try:
        from models.audit import registrar_audit
        registrar_audit(
            accion='crear_nivel',
            entidad='presupuesto',
            entidad_id=presupuesto.id,
            detalle=f'Nivel manual: {nivel.nombre} ({nivel.area_m2} m2)',
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, nivel=nivel.to_dict())


@presupuestos_bp.route('/<int:id>/niveles/<int:nivel_id>', methods=['PATCH', 'PUT'])
@login_required
def nivel_actualizar(id, nivel_id):
    """Edita campos de un nivel existente."""
    from models.budgets import Presupuesto, NivelPresupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403
    bloqueo = _bloquear_si_aprobado(presupuesto)
    if bloqueo:
        return bloqueo

    nivel = NivelPresupuesto.query.filter_by(
        id=nivel_id, presupuesto_id=presupuesto.id,
    ).first()
    if not nivel:
        return jsonify(ok=False, error='Nivel no encontrado'), 404

    payload = request.get_json(silent=True) or {}
    try:
        datos = _normalizar_payload_nivel(payload, presupuesto)
    except ValueError as ve:
        return jsonify(ok=False, error=str(ve)), 400

    _aplicar_payload_a_nivel(nivel, datos)

    try:
        from models.audit import registrar_audit
        registrar_audit(
            accion='editar_nivel',
            entidad='presupuesto',
            entidad_id=presupuesto.id,
            detalle=f'Nivel #{nivel.id} ({nivel.nombre}): {list(datos.keys())}',
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, nivel=nivel.to_dict())


@presupuestos_bp.route('/<int:id>/niveles/<int:nivel_id>/duplicar', methods=['POST'])
@login_required
def nivel_duplicar(id, nivel_id):
    """Duplica un nivel existente con sufijo (copia) en el nombre."""
    from models.budgets import Presupuesto, NivelPresupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403
    bloqueo = _bloquear_si_aprobado(presupuesto)
    if bloqueo:
        return bloqueo

    base = NivelPresupuesto.query.filter_by(
        id=nivel_id, presupuesto_id=presupuesto.id,
    ).first()
    if not base:
        return jsonify(ok=False, error='Nivel no encontrado'), 404

    ult = NivelPresupuesto.query.filter_by(presupuesto_id=presupuesto.id) \
        .order_by(NivelPresupuesto.orden.desc()).first()
    nuevo_orden = (ult.orden + 10) if ult else 10

    nuevo = NivelPresupuesto(
        presupuesto_id=presupuesto.id,
        tipo_nivel=base.tipo_nivel,
        nombre=f'{base.nombre} (copia)'[:100],
        orden=nuevo_orden,
        repeticiones=base.repeticiones,
        area_m2=base.area_m2,
        sistema_constructivo=base.sistema_constructivo,
        hormigon_m3=base.hormigon_m3,
        albanileria_m2=base.albanileria_m2,
        atributos=dict(base.atributos or {}),
        excluido_del_calculo=base.excluido_del_calculo,
        observaciones=base.observaciones,
    )
    db.session.add(nuevo)

    try:
        from models.audit import registrar_audit
        registrar_audit(
            accion='duplicar_nivel',
            entidad='presupuesto',
            entidad_id=presupuesto.id,
            detalle=f'Nivel #{base.id} -> {nuevo.nombre}',
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, nivel=nuevo.to_dict())


@presupuestos_bp.route('/<int:id>/niveles/<int:nivel_id>', methods=['DELETE'])
@login_required
def nivel_eliminar(id, nivel_id):
    """Elimina un nivel si no tiene items vinculados."""
    from models.budgets import Presupuesto, NivelPresupuesto, ItemPresupuesto

    presupuesto = Presupuesto.query.get_or_404(id)
    if not _verificar_acceso_presupuesto(presupuesto):
        return jsonify(ok=False, error='No autorizado'), 403
    if not _puede_gestionar():
        return jsonify(ok=False, error='Sin permisos'), 403
    bloqueo = _bloquear_si_aprobado(presupuesto)
    if bloqueo:
        return bloqueo

    nivel = NivelPresupuesto.query.filter_by(
        id=nivel_id, presupuesto_id=presupuesto.id,
    ).first()
    if not nivel:
        return jsonify(ok=False, error='Nivel no encontrado'), 404

    # Safety: chequear si algun ItemPresupuesto.nivel_nombre matchea exacto.
    # Es una validacion conservadora — el campo es texto libre y puede haber
    # divergencias por mayusculas/acentos. Si hay items vinculados, bloqueamos.
    items_vinculados = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
        nivel_nombre=nivel.nombre,
    ).count()
    if items_vinculados > 0:
        return jsonify(
            ok=False,
            error=f'No se puede eliminar: {items_vinculados} ítem(s) del presupuesto están vinculados a este nivel.',
            items_vinculados=items_vinculados,
        ), 400

    nombre_log = nivel.nombre
    db.session.delete(nivel)

    try:
        from models.audit import registrar_audit
        registrar_audit(
            accion='eliminar_nivel',
            entidad='presupuesto',
            entidad_id=presupuesto.id,
            detalle=f'Nivel eliminado: {nombre_log}',
        )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True)
