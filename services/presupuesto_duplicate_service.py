# -*- coding: utf-8 -*-
"""Duplicación profunda de presupuestos (feature de ventas).

Crea una copia EDITABLE (estado='borrador') de un presupuesto con toda su estructura
de cálculo:
    Presupuesto (cabecera)
      ├── NivelPresupuesto           (los ítems linkean por nivel_nombre string)
      ├── PresupuestoEtapa           (etapas editables; se remapea el id en los ítems)
      └── ItemPresupuesto            (remapea etapa_presupuesto_id)
            └── ItemPresupuestoComposicion  (APU; remapea item_presupuesto_id)

NO se copia (pertenece al ciclo del presupuesto original, no a una copia nueva):
  - Compras: MaterialCotizable, SolicitudCotizacion*, ProveedorAsignado.
  - PresupuestoPrecioConfirmado (crowdsourced): copiarlo inflaría los promedios.
  - Archivos subidos (PresupuestoArchivo) y el vínculo a la Obra.

Se usa introspección de columnas: se clonan TODAS las columnas de cada modelo (salvo
la PK) y luego se overridean las que deben cambiar. Así no se pierden campos cuando el
modelo evoluciona (a diferencia de listar campos a mano).
"""
import logging
from datetime import datetime

from sqlalchemy import inspect as sa_inspect

from extensions import db
from models.budgets import (
    Presupuesto, ItemPresupuesto, NivelPresupuesto, ItemPresupuestoComposicion,
)
from models.presupuesto_etapa import PresupuestoEtapa

logger = logging.getLogger(__name__)


def _clonar_columnas(obj, overrides=None):
    """Dict con TODAS las columnas de `obj` salvo la PK, más los `overrides`."""
    mapper = sa_inspect(type(obj))
    pk = {c.name for c in mapper.primary_key}
    data = {c.name: getattr(obj, c.name) for c in mapper.columns if c.name not in pk}
    if overrides:
        data.update(overrides)
    return data


def _tiene_columna(modelo, nombre):
    return nombre in {c.name for c in sa_inspect(modelo).columns}


def _numero_copia(org_id, numero_original):
    """Número único para la copia: '<orig> (copia)', luego '(copia 2)', '(copia 3)'..."""
    base = (numero_original or 'PRES').strip()
    candidato = f"{base} (copia)"
    n = 2
    while Presupuesto.query.filter_by(organizacion_id=org_id, numero=candidato).first():
        candidato = f"{base} (copia {n})"
        n += 1
    return candidato


def duplicar_presupuesto(presupuesto_id, organizacion_id, usuario_id=None):
    """Duplica un presupuesto completo. Devuelve el nuevo Presupuesto (commiteado).

    Raises ValueError si no existe o pertenece a otra organización.
    """
    original = Presupuesto.query.get(presupuesto_id)
    if not original:
        raise ValueError('Presupuesto no encontrado')
    if original.organizacion_id != organizacion_id:
        raise ValueError('El presupuesto pertenece a otra organización')

    try:
        # 1. Cabecera: copiar todo salvo PK; resetear estado/aprobación/vínculos.
        nuevo = Presupuesto(**_clonar_columnas(original, {
            'numero': _numero_copia(organizacion_id, original.numero),
            'estado': 'borrador',
            'obra_id': None,                 # copia fresca, no atada a la obra original
            'confirmado_como_obra': False,
            'ejecutivo_aprobado': False,
            'ejecutivo_aprobado_at': None,
            'precios_snapshot_at': None,     # no está congelada comercialmente
            'deleted_at': None,
            'fecha_creacion': datetime.utcnow(),
        }))
        db.session.add(nuevo)
        db.session.flush()   # -> nuevo.id

        # 2. Niveles (FK presupuesto_id). Los ítems linkean por nivel_nombre (string).
        for niv in original.niveles.all():   # relación lazy='dynamic'
            db.session.add(NivelPresupuesto(**_clonar_columnas(niv, {'presupuesto_id': nuevo.id})))

        # 3. Etapas editables. Mapa etapa_original.id -> etapa_nueva.id para los ítems.
        etapa_map = {}
        for et in PresupuestoEtapa.query.filter_by(presupuesto_id=original.id).all():
            clon = PresupuestoEtapa(**_clonar_columnas(et, {'presupuesto_id': nuevo.id}))
            db.session.add(clon)
            db.session.flush()
            etapa_map[et.id] = clon.id

        # 4. Ítems. Remapea etapa_presupuesto_id; suelta vínculos al ciclo original.
        item_map = {}
        item_overrides_base = {
            'presupuesto_id': nuevo.id,
            'etapa_id': None,            # etapa de OBRA (la obra no se copia)
            'archivo_origen_id': None,   # archivos del original no se copian
        }
        for it in original.items.all():   # relación lazy='dynamic'
            ov = dict(item_overrides_base)
            ov['etapa_presupuesto_id'] = etapa_map.get(getattr(it, 'etapa_presupuesto_id', None))
            if _tiene_columna(ItemPresupuesto, 'editado_por_user_id'):
                ov['editado_por_user_id'] = None
            clon = ItemPresupuesto(**_clonar_columnas(it, ov))
            db.session.add(clon)
            db.session.flush()
            item_map[it.id] = clon.id

        # 5. Composición (APU) de cada ítem. Remapea item_presupuesto_id; suelta la
        #    referencia a materiales_cotizables (parte de compras, no se copia).
        if item_map:
            comps = ItemPresupuestoComposicion.query.filter(
                ItemPresupuestoComposicion.item_presupuesto_id.in_(list(item_map.keys()))
            ).all()
            tiene_mat = _tiene_columna(ItemPresupuestoComposicion, 'material_cotizable_id')
            for comp in comps:
                ov = {'item_presupuesto_id': item_map[comp.item_presupuesto_id]}
                if tiene_mat:
                    ov['material_cotizable_id'] = None
                db.session.add(ItemPresupuestoComposicion(**_clonar_columnas(comp, ov)))

        db.session.commit()
        logger.info('Presupuesto %s duplicado -> %s (numero %r) por user %s',
                    original.id, nuevo.id, nuevo.numero, usuario_id)
        return nuevo
    except Exception:
        db.session.rollback()
        logger.exception('Error duplicando presupuesto %s', presupuesto_id)
        raise
