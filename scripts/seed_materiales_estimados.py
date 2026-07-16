"""Seed de materiales ESTIMADOS para las APUs de Fase 2.2 (pliego JMG).

Carga en la base global de precios (organizacion_id NULL) los materiales que las
reglas nuevas de coeficientes_constructivos.yml referencian pero que NO estan en
la base real (catalogo de plomeria). Precios orientativos de mercado argentino
~agosto 2026. Todos con fuente='estimado' -> se corrigen cuando haya listas reales.

La descripcion coincide con el `nombre` del recurso en el YAML para que el
matching exacto (prioridad 1) los encuentre al pricear una composicion.

Uso:  python scripts/seed_materiales_estimados.py
Idempotente por (org NULL, descripcion_normalizada, unidad).
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FUENTE = 'estimado'

# (descripcion == nombre YAML, unidad, precio_unitario ARS orientativo ago-2026)
MATERIALES = [
    ('Ladrillo hueco 8x18x33',                       'u',     450),
    ('Ladrillo hueco 4x18x33',                       'u',     380),
    ('Ladrillo comun 5.5x12.5x25',                   'u',     180),
    ('Mortero asentamiento 1:1/4:4',                 'm3',  95000),
    ('Mortero CPV 1:3 (cemento + arena)',            'm3', 110000),
    ('Mortero cemento 1:3',                          'm3', 110000),
    ('Mortero fino a la cal (cal + arena fina)',     'm3',  88000),
    ('Placa de yeso 12.5mm',                         'm2',   9500),
    ('Perfil montante 70mm',                         'ml',   3200),
    ('Perfil solera 70mm',                           'ml',   3000),
    ('Perfil montante 35mm',                         'ml',   2600),
    ('Perfil montante/solera cielorraso',            'ml',   2900),
    ('Tornillos T2 punta aguja',                     'u',      25),
    ('Masilla para juntas',                          'kg',   1900),
    ('Cinta de papel para juntas',                   'ml',    120),
    ('Vela y regulador para cielorraso',             'u',    1400),
    ('Hidrofugo en pasta (Sika 1 o equivalente)',    'kg',   3800),
    ('Cemento portland (bolsa 50 kg)',               'bolsa',11800),
    ('Arena',                                        'm3',  36500),
    ('Poliestireno expandido / perlita',             'm3',  52000),
    ('Piedra partida / canto rodado',                'm3',  42000),
    ('Adhesivo cementicio (cemento cola)',           'kg',    850),
    ('Pastina para juntas',                          'kg',   1600),
    ('Hormigon H21 elaborado',                       'm3', 174000),
    ('Hierro construccion 8mm',                      'kg',  10495),
    ('Madera para encofrado',                        'm2',   8500),
    ('Membrana asfaltica 4mm con aluminio',          'm2',  14000),
    ('Imprimacion asfaltica (pintura asfaltica)',    'l',    6500),
    ('Yeso de proyeccion',                           'kg',    680),
    ('Zocalo ceramico/porcelanato',                  'ml',   3900),
    # --- Fase 2.2b: encofrados + 11 rubros ---
    ('Madera de pino para encofrado',                'm2',   7500),
    ('Clavos de punta',                              'kg',   2200),
    ('Fenolico 18mm para encofrado',                 'm2',  28000),
    ('Puntal metalico (amortizacion)',               'u',    4500),
    ('Clavos/tornillos',                             'kg',   2500),
    ('Alambre de atar N16',                          'kg',   2800),
    ('Tosca / tierra de aporte',                     'm3',  18000),
    ('Chapa acanalada galvanizada',                  'm2',  16500),
    ('Clavaderas / tirantillos de madera',           'ml',   2400),
    ('Aislacion base bajo chapa (film/membrana)',    'm2',   3200),
    ('Tornillos autoperforantes',                    'u',      90),
    ('Placa aislante termica (EPS/lana)',            'm2',   8900),
    ('Cano corrugado electrico',                     'ml',    650),
    ('Cable unipolar 2.5mm2',                        'ml',    980),
    ('Caja rectangular PVC',                         'u',     780),
    ('Cano agua PPR/termofusion 1/2',                'ml',   2900),
    ('Accesorios agua (codos, tes, llaves)',         'u',    1500),
    ('Cano PVC cloacal 110mm',                       'ml',   6800),
    ('Accesorios cloacales (codos 45, registros, sifones)', 'u', 3500),
    ('Pintura latex exterior',                       'l',    7800),
    ('Fijador al agua',                              'l',    4200),
    ('Esmalte sintetico',                            'l',    9500),
    ('Imprimante/fondo para madera',                 'l',    8200),
    ('Azulejo 15x15',                                'u',     320),
]

# Materiales con moneda/fuente propia. (desc, unidad, precio, moneda, fuente)
# El sistema convierte USD->ARS con el TC del presupuesto (doble moneda).
MATERIALES_ESPECIALES = [
    ('Sistema encofrado modular Flex (alquiler mensual)', 'mes', 6.81, 'USD',
     'lista proveedor Flex ago-2026'),
]


def _upsert(db, desc, unidad, precio, moneda, fuente, nota):
    from models.provider_price_list import ProviderPriceList, normalizar_descripcion_precio
    dn = normalizar_descripcion_precio(desc)
    row = ProviderPriceList.query.filter(
        ProviderPriceList.organizacion_id.is_(None),
        ProviderPriceList.proveedor_id.is_(None),
        ProviderPriceList.descripcion_normalizada == dn,
        ProviderPriceList.unidad == unidad,
    ).first()
    creado = False
    if row is None:
        row = ProviderPriceList(
            organizacion_id=None, proveedor_id=None,
            descripcion=desc, descripcion_normalizada=dn, unidad=unidad, notas=nota,
        )
        db.session.add(row)
        creado = True
    row.precio_unitario = Decimal(str(precio))
    row.moneda = moneda
    row.fuente = fuente
    row.fecha_actualizacion = date(2026, 8, 1)
    return creado


def seed(db):
    ins = upd = 0
    nota_est = 'Precio orientativo estimado (mercado AR ~ago 2026). Reemplazar con lista real.'
    for desc, unidad, precio in MATERIALES:
        creado = _upsert(db, desc, unidad, precio, 'ARS', FUENTE, nota_est)
        ins += creado
        upd += (not creado)
    for desc, unidad, precio, moneda, fuente in MATERIALES_ESPECIALES:
        creado = _upsert(db, desc, unidad, precio, moneda,
                         fuente, f'Precio {moneda} de lista de proveedor. Se convierte con el TC del presupuesto.')
        ins += creado
        upd += (not creado)
    db.session.commit()
    return ins, upd


def main():
    import app as _app
    from extensions import db
    with _app.app.app_context():
        ins, upd = seed(db)
        total = len(MATERIALES) + len(MATERIALES_ESPECIALES)
        print(f"[OK] materiales estimados: {ins} insertados, {upd} actualizados ({total} total)")


if __name__ == '__main__':
    main()
