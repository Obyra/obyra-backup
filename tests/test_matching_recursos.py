# -*- coding: utf-8 -*-
"""Tests del matching de recursos mejorado (Fase 2.1).

Cubre:
  - Resolver de MO v2: buscar_mejor_precio(tipo='mano_obra') resuelve el costo
    empresa via categorias_jornal + EstructuraRecargosMO (no la base de materiales).
  - Alias de codigo oficial_especializado -> oficial_esp.
  - Matching por cobertura: una query corta ('cemento') matchea un SKU verboso
    ('Bolsa de Cemento Loma Negra 50 kg'), que con Jaccard puro quedaba afuera.
  - Techo documentado: 'cemento portland' NO matchea 'cemento loma negra'
    (marca != termino generico) -> necesita capa semantica (2.3).
"""
from datetime import date
from decimal import Decimal

import pytest

from services.precio_recurso_service import buscar_mejor_precio, _buscar_provider_price_list


def _limpiar(db):
    from models.provider_price_list import ProviderPriceList
    from models.budgets import CategoriaJornal
    from models.mano_obra import EstructuraRecargosMO, RecargoMOLinea
    ProviderPriceList.query.delete()
    RecargoMOLinea.query.delete()
    EstructuraRecargosMO.query.delete()
    CategoriaJornal.query.filter(CategoriaJornal.codigo.in_(['oficial_esp', 'ayudante'])).delete(synchronize_session=False)
    db.session.commit()


def _ppl(db, descripcion, unidad, precio, org=None):
    from models.provider_price_list import ProviderPriceList, normalizar_descripcion_precio
    db.session.add(ProviderPriceList(
        organizacion_id=org, descripcion=descripcion,
        descripcion_normalizada=normalizar_descripcion_precio(descripcion),
        unidad=unidad, precio_unitario=Decimal(str(precio)),
        fecha_actualizacion=date.today(), moneda='ARS',
    ))


@pytest.mark.integration
def test_matching_por_cobertura_query_corta_vs_sku_verboso(app):
    from extensions import db
    with app.app_context():
        _limpiar(db)
        _ppl(db, 'Bolsa de Cemento Loma Negra (50 kg)', 'kg', 11850)
        db.session.commit()

        # 'cemento' (1 token) debe matchear el SKU verboso (cobertura de query = 1.0)
        mejor, _alts = _buscar_provider_price_list(999, 'cemento', 'bolsa')
        assert mejor is not None
        assert 'cemento' in (mejor.descripcion_normalizada or '')

        _limpiar(db)


@pytest.mark.integration
def test_techo_matching_marca_distinta_no_matchea(app):
    """Documenta el limite: query con calificador que el SKU no tiene ('portland'
    vs 'loma negra') no matchea. Necesita sinonimos/LLM (2.3)."""
    from extensions import db
    with app.app_context():
        _limpiar(db)
        _ppl(db, 'Bolsa de Cemento Loma Negra (50 kg)', 'kg', 11850)
        db.session.commit()

        mejor, _alts = _buscar_provider_price_list(999, 'cemento portland', 'bolsa')
        assert mejor is None  # 'portland' no esta en el SKU -> cobertura < umbral

        _limpiar(db)


@pytest.mark.integration
def test_resolver_mo_v2_usa_costo_empresa(app):
    """buscar_mejor_precio(tipo='mano_obra', 'oficial especializado') resuelve el
    costo empresa via categorias_jornal + recargos, con alias de codigo."""
    from extensions import db
    from models.budgets import CategoriaJornal
    from models.mano_obra import EstructuraRecargosMO, RecargoMOLinea
    with app.app_context():
        _limpiar(db)
        # Basico global (codigo oficial_esp) + estructura con presentismo 20%
        db.session.add(CategoriaJornal(
            organizacion_id=None, nombre='Oficial Especializado', codigo='oficial_esp',
            valor_hora_convenio=Decimal('1000'), precio_jornal=Decimal('8000'),
            fuente='uocra', vigencia_desde=date(2026, 1, 1), activo=True,
        ))
        est = EstructuraRecargosMO(organizacion_id=None, nombre='G', zona='CABA',
                                   vigencia_desde=date(2026, 1, 1), activo=True)
        est.lineas.append(RecargoMOLinea(orden=1, concepto='Presentismo',
                                         grupo='adicional_remunerativo',
                                         tipo_calculo='pct_hora_convenio', valor=Decimal('20')))
        db.session.add(est)
        db.session.commit()

        # 'oficial especializado' -> categoria_canonica 'oficial_especializado'
        # -> alias 'oficial_esp' -> costo hora = 1000 * 1.20 = 1200
        r = buscar_mejor_precio(organizacion_id=999, descripcion='oficial especializado',
                                unidad='hora', tipo_recurso='mano_obra')
        assert r['fuente'] == 'costo_mano_obra'
        assert r['precio'] == pytest.approx(1200.0, abs=0.5)

        # por jornal (8h) = 1200 * 8 = 9600
        r2 = buscar_mejor_precio(organizacion_id=999, descripcion='oficial especializado',
                                 unidad='jornal', tipo_recurso='mano_obra')
        assert r2['precio'] == pytest.approx(9600.0, abs=1.0)

        _limpiar(db)
