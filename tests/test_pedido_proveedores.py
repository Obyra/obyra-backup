# -*- coding: utf-8 -*-
"""Tests de la capa "pedido a proveedores" (Recursos a cotizar).

REGLA DURA que blindan estos tests: editar el pedido NO toca el presupuesto.
Corregir 12.384 kg a 800 kg cambia lo que se le pide al proveedor; el costo del
ejecutivo y los totales del presupuesto quedan igual. Las cantidades y precios
del presupuesto se editan en Validacion, no aca.

Cubren tambien:
  - que sincronizar_materiales_cotizables() no pise las ediciones al recorrer
    de nuevo (corre en CADA GET de la pantalla);
  - que el alias por organizacion no se filtre al matcher de precios;
  - que un huerfano con trabajo encima ya no se borre en silencio.
"""
from decimal import Decimal

import pytest

from blueprint_presupuestos.ejecutivo import (
    _grupo_hash_material,
    cantidad_para_pedido,
    cargar_alias_org,
    hay_drift_cantidad,
    nombre_para_pedido,
    sincronizar_materiales_cotizables,
)
from extensions import db
from models import (
    ItemPresupuesto,
    ItemPresupuestoComposicion,
    MaterialCotizable,
    Presupuesto,
    RecursoAliasOrg,
)

DESC_GENERICA = 'Adhesivo cementicio para porcelanato'
ALIAS = 'Klaukol'


def _armar_presupuesto(org_id, cantidad=Decimal('12.384'), descripcion=DESC_GENERICA):
    """Presupuesto con 1 item y 1 composicion material. Devuelve (pres, item, comp)."""
    pres = Presupuesto(organizacion_id=org_id, numero=f'TEST-{org_id}-PED')
    db.session.add(pres)
    db.session.flush()

    item = ItemPresupuesto(
        presupuesto_id=pres.id,
        tipo='material',
        descripcion='Colocacion de porcelanato',
        unidad='m2',
        cantidad=Decimal('100'),
        precio_unitario=Decimal('5000'),
        total=Decimal('500000'),
    )
    db.session.add(item)
    db.session.flush()

    comp = ItemPresupuestoComposicion(
        item_presupuesto_id=item.id,
        tipo='material',
        descripcion=descripcion,
        unidad='kg',
        cantidad=cantidad,
        precio_unitario=Decimal('1200'),
        total=cantidad * Decimal('1200'),
    )
    db.session.add(comp)
    db.session.commit()
    return pres, item, comp


@pytest.mark.unit
def test_editar_cantidad_del_pedido_no_toca_el_presupuesto(app, test_org):
    """El test que blinda la regla dura: 12.384 -> 800 no mueve un peso."""
    with app.app_context():
        pres, item, comp = _armar_presupuesto(test_org.id)
        materiales = sincronizar_materiales_cotizables(pres)
        mat = materiales[0]

        costo_comp_antes = comp.total
        cantidad_comp_antes = comp.cantidad
        total_item_antes = item.total

        # El usuario corrige la cantidad del PEDIDO.
        mat.cantidad_pedido = Decimal('800')
        mat.cantidad_calculada_al_editar = mat.cantidad_total
        db.session.commit()

        # Lo que se le pide al proveedor cambio...
        assert cantidad_para_pedido(mat) == Decimal('800')

        # ...y NADA del presupuesto se movio.
        db.session.refresh(comp)
        db.session.refresh(item)
        assert comp.cantidad == cantidad_comp_antes == Decimal('12.384')
        assert comp.total == costo_comp_antes
        assert item.total == total_item_antes
        # cantidad_total sigue siendo la verdad del APU.
        assert mat.cantidad_total == Decimal('12.384')


@pytest.mark.unit
def test_sync_no_pisa_las_ediciones_del_pedido(app, test_org):
    """El sync corre en cada F5 y reescribe descripcion/unidad/cantidad_total.

    Las ediciones viven en otras columnas justamente para sobrevivir a eso.
    """
    with app.app_context():
        pres, item, comp = _armar_presupuesto(test_org.id)
        mat = sincronizar_materiales_cotizables(pres)[0]

        mat.cantidad_pedido = Decimal('800')
        mat.cantidad_calculada_al_editar = mat.cantidad_total
        mat.excluido_pedido = True
        db.session.commit()
        mat_id = mat.id

        # Segunda corrida del sync (equivale a recargar la pantalla).
        sincronizar_materiales_cotizables(pres)

        mat = db.session.get(MaterialCotizable, mat_id)
        assert mat is not None, 'el sync borro la fila'
        assert mat.cantidad_pedido == Decimal('800')
        assert mat.excluido_pedido is True
        # Y la zona que el sync SI reescribe sigue reflejando el APU.
        assert mat.cantidad_total == Decimal('12.384')
        assert mat.descripcion == DESC_GENERICA


@pytest.mark.unit
def test_cantidad_pedido_nula_cae_en_la_calculada(app, test_org):
    """NULL = 'usa cantidad_total'. Es lo que distingue no-editado de editado."""
    with app.app_context():
        pres, _item, _comp = _armar_presupuesto(test_org.id)
        mat = sincronizar_materiales_cotizables(pres)[0]

        assert mat.cantidad_pedido is None
        assert cantidad_para_pedido(mat) == mat.cantidad_total

        mat.cantidad_pedido = Decimal('800')
        db.session.commit()
        assert cantidad_para_pedido(mat) == Decimal('800')

        # Resetear vuelve a la calculada.
        mat.cantidad_pedido = None
        mat.cantidad_calculada_al_editar = None
        db.session.commit()
        assert cantidad_para_pedido(mat) == Decimal('12.384')


@pytest.mark.unit
def test_drift_se_detecta_cuando_el_apu_cambia_despues_de_editar(app, test_org):
    """Corregiste a 800 y despues arreglaste el APU de verdad: hay que preguntar."""
    with app.app_context():
        pres, _item, comp = _armar_presupuesto(test_org.id)
        mat = sincronizar_materiales_cotizables(pres)[0]

        mat.cantidad_pedido = Decimal('800')
        mat.cantidad_calculada_al_editar = mat.cantidad_total
        db.session.commit()
        assert hay_drift_cantidad(mat) is False

        # Ahora se corrige el APU en Validacion y el sync trae 900.
        comp.cantidad = Decimal('900')
        db.session.commit()
        sincronizar_materiales_cotizables(pres)
        db.session.refresh(mat)

        assert mat.cantidad_total == Decimal('900')
        assert mat.cantidad_pedido == Decimal('800'), 'la edicion no se resuelve sola'
        assert hay_drift_cantidad(mat) is True


@pytest.mark.unit
def test_alias_no_toca_la_descripcion_generica(app, test_org):
    """El matcher de precios busca por descripcion; el alias vive aparte.

    Si el alias se escribiera en mat.descripcion, "Klaukol" entraria al fuzzy
    match de buscar_mejor_precio. Ese es exactamente el escenario a evitar.
    """
    with app.app_context():
        pres, _item, comp = _armar_presupuesto(test_org.id)
        mat = sincronizar_materiales_cotizables(pres)[0]

        db.session.add(RecursoAliasOrg(
            organizacion_id=test_org.id,
            grupo_hash=mat.grupo_hash,
            alias=ALIAS,
            descripcion_generica=mat.descripcion,
        ))
        db.session.commit()

        alias_map = cargar_alias_org(test_org.id)
        assert nombre_para_pedido(mat, alias_map) == ALIAS

        # El nombre generico quedo intacto en las dos puntas.
        assert mat.descripcion == DESC_GENERICA
        db.session.refresh(comp)
        assert comp.descripcion == DESC_GENERICA

        # Y sobrevive al sync.
        sincronizar_materiales_cotizables(pres)
        db.session.refresh(mat)
        assert mat.descripcion == DESC_GENERICA
        assert nombre_para_pedido(mat, cargar_alias_org(test_org.id)) == ALIAS


@pytest.mark.unit
def test_alias_es_por_organizacion_no_por_presupuesto(app, test_org):
    """Clave (org, grupo_hash): no hay que re-tipear el alias en cada presupuesto."""
    with app.app_context():
        pres_a, _i, _c = _armar_presupuesto(test_org.id)
        mat_a = sincronizar_materiales_cotizables(pres_a)[0]

        db.session.add(RecursoAliasOrg(
            organizacion_id=test_org.id,
            grupo_hash=mat_a.grupo_hash,
            alias=ALIAS,
        ))
        db.session.commit()

        # Otro presupuesto de la misma org con el mismo recurso.
        pres_b = Presupuesto(organizacion_id=test_org.id, numero='TEST-PED-B')
        db.session.add(pres_b)
        db.session.flush()
        item_b = ItemPresupuesto(
            presupuesto_id=pres_b.id, tipo='material', descripcion='Otra tarea',
            unidad='m2', cantidad=Decimal('50'), precio_unitario=Decimal('1'),
            total=Decimal('50'),
        )
        db.session.add(item_b)
        db.session.flush()
        db.session.add(ItemPresupuestoComposicion(
            item_presupuesto_id=item_b.id, tipo='material', descripcion=DESC_GENERICA,
            unidad='kg', cantidad=Decimal('5'), precio_unitario=Decimal('1200'),
            total=Decimal('6000'),
        ))
        db.session.commit()

        mat_b = sincronizar_materiales_cotizables(pres_b)[0]
        # Mismo recurso => mismo hash => el alias se re-engancha solo.
        assert mat_b.grupo_hash == mat_a.grupo_hash
        assert nombre_para_pedido(mat_b, cargar_alias_org(test_org.id)) == ALIAS


@pytest.mark.unit
def test_alias_no_cruza_entre_organizaciones(app, test_org):
    """Multi-tenant: el alias de una org no puede aparecerle a otra."""
    with app.app_context():
        pres, _item, _comp = _armar_presupuesto(test_org.id)
        mat = sincronizar_materiales_cotizables(pres)[0]

        # Alias cargado por OTRA organizacion sobre el mismo recurso generico.
        db.session.add(RecursoAliasOrg(
            organizacion_id=test_org.id + 9999,
            grupo_hash=mat.grupo_hash,
            alias='Marca de otra empresa',
        ))
        db.session.commit()

        assert nombre_para_pedido(mat, cargar_alias_org(test_org.id)) == DESC_GENERICA


@pytest.mark.unit
def test_huerfano_con_trabajo_encima_no_se_borra(app, test_org):
    """Antes se borraba y se iban en silencio precio elegido y respuestas.

    El hash cambia solo (aca simulado editando la descripcion de la composicion,
    igual que pasa al vincular inventario: 'txt:...' -> 'inv:<id>').
    """
    with app.app_context():
        pres, _item, comp = _armar_presupuesto(test_org.id)
        mat = sincronizar_materiales_cotizables(pres)[0]
        mat_id, hash_viejo = mat.id, mat.grupo_hash

        # Trabajo del usuario encima de la fila.
        mat.precio_elegido = Decimal('1350')
        mat.estado = 'elegido'
        db.session.commit()

        # Cambia la descripcion de la composicion => hash nuevo.
        comp.descripcion = 'Adhesivo cementicio premium para porcelanato'
        db.session.commit()
        resultado = sincronizar_materiales_cotizables(pres)

        viejo = db.session.get(MaterialCotizable, mat_id)
        assert viejo is not None, 'se borro una fila con precio elegido'
        assert viejo.huerfano is True
        assert viejo.huerfano_at is not None
        assert viejo.precio_elegido == Decimal('1350')

        # Y aparecio la fila nueva con el hash nuevo.
        hashes = {m.grupo_hash for m in resultado}
        assert hash_viejo in hashes
        assert len(hashes) == 2


@pytest.mark.unit
def test_huerfano_sin_nada_que_perder_se_sigue_borrando(app, test_org):
    """La contracara: no acumular basura. Fila limpia => hard delete, como antes."""
    with app.app_context():
        pres, _item, comp = _armar_presupuesto(test_org.id)
        mat = sincronizar_materiales_cotizables(pres)[0]
        mat_id = mat.id

        comp.descripcion = 'Otro adhesivo totalmente distinto'
        db.session.commit()
        sincronizar_materiales_cotizables(pres)

        assert db.session.get(MaterialCotizable, mat_id) is None


@pytest.mark.unit
def test_huerfano_que_reaparece_se_desmarca(app, test_org):
    """Si el recurso vuelve al APU, deja de ser huerfano (con su trabajo intacto)."""
    with app.app_context():
        pres, _item, comp = _armar_presupuesto(test_org.id)
        mat = sincronizar_materiales_cotizables(pres)[0]
        mat.precio_elegido = Decimal('1350')
        db.session.commit()
        mat_id = mat.id

        comp.descripcion = 'Adhesivo cementicio premium'
        db.session.commit()
        sincronizar_materiales_cotizables(pres)
        assert db.session.get(MaterialCotizable, mat_id).huerfano is True

        # Se deshace el cambio.
        comp.descripcion = DESC_GENERICA
        db.session.commit()
        sincronizar_materiales_cotizables(pres)

        revivido = db.session.get(MaterialCotizable, mat_id)
        assert revivido.huerfano is False
        assert revivido.huerfano_at is None
        assert revivido.precio_elegido == Decimal('1350')


@pytest.mark.unit
def test_grupo_hash_estable_para_el_mismo_recurso(app):
    """El alias se apoya en el hash: si no fuera determinista, no serviria de clave."""
    with app.app_context():
        h1 = _grupo_hash_material(DESC_GENERICA, 'kg', None, tipo='material')
        h2 = _grupo_hash_material(f'  {DESC_GENERICA.upper()}  ', 'KG', None, tipo='material')
        assert h1 == h2

        # Distinto tipo no se mezcla (material vs equipo).
        assert h1 != _grupo_hash_material(DESC_GENERICA, 'kg', None, tipo='equipo')
