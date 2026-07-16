"""Seed global de costo MO (Fase 2.0 IA presupuestos). Idempotente.

Carga como BASE GLOBAL (organizacion_id NULL, visible a todas las orgs):
  1. valor_hora_convenio en las 5 categorias UOCRA Zona A / CABA (abril 2026).
     - oficial_especializado: $5.470/hh  -> CONFIRMADO por Brenda (planilla).
     - resto: PROPUESTO (escala UOCRA relativa) -> a validar contra la planilla.
  2. Una EstructuraRecargosMO global (CABA, abril 2026) con las lineas de recargo
     de la planilla real de Brenda. Reproduce costo/hh oficial esp = $12.205,79
     (con bono) / $12.177,38 (sin bono) — a $0.41 del target por redondeo.

Uso:
    python scripts/seed_mano_obra.py
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VIGENCIA = date(2026, 4, 1)
ZONA = 'CABA'

# (codigo, nombre, valor_hora_convenio, confirmado)
CATEGORIAS = [
    ('oficial_esp',   'Oficial Especializado', Decimal('5470.00'), True),
    ('oficial',       'Oficial',               Decimal('4679.20'), False),
    ('medio_oficial', 'Medio Oficial',         Decimal('4324.30'), False),
    ('ayudante',      'Ayudante',              Decimal('3980.40'), False),
    ('sereno',        'Sereno',                Decimal('3782.00'), False),
]

# Lineas de la estructura de recargos (planilla Brenda, abril 2026 CABA).
# (concepto, grupo, tipo_calculo, valor, activo, notas)
LINEAS = [
    ('Presentismo',        'adicional_remunerativo',    'pct_hora_convenio', Decimal('20'),      True,
     'Sobre hora convenio'),
    ('hh50 (6hh/50hsem)',  'adicional_remunerativo',    'pct_hora_convenio', Decimal('2.27'),    False,
     'Horas al 50%. INACTIVO: la planilla calcula el costo empresa sobre bruto sin hh50. Activar si se incluye OT en la base.'),
    ('F.931',              'carga_social',              'pct_bruto',         Decimal('58.74'),   True,
     'Contrib. seg. social 19,48 + aportes 14,69 + contrib. OS 6,58 + aportes OS 3,91 + LRT 14 + seguro vida 0,08'),
    ('Fondo de desempleo', 'carga_social',              'pct_bruto',         Decimal('12'),      True, None),
    ('SAC',                'carga_social',              'pct_bruto',         Decimal('8.33'),    True,
     '1/12 de la remuneracion'),
    ('Vacaciones',         'carga_social',              'pct_bruto',         Decimal('4.17'),    True,
     'Proporcionales'),
    ('UOCRA',              'carga_social',              'monto_dia',         Decimal('278.30'),  True,
     'Aporte gremial (monto por dia)'),
    ('IERIC',              'carga_social',              'monto_mes',         Decimal('15.90'),   True,
     '2% (monto mensual)'),
    ('Comida',             'adicional_no_remunerativo', 'monto_dia',         Decimal('911.11'),  True,
     'Vianda por dia'),
    ('EPP',                'adicional_no_remunerativo', 'monto_mes',         Decimal('130.91'),  True,
     'Elementos de proteccion personal (monto mensual)'),
    ('Bono anual',         'adicional_no_remunerativo', 'monto_mes',         Decimal('5000'),    True,
     '$30.000/anio amortizado en 6 meses = $5.000/mes'),
]


def seed(db):
    from models.budgets import CategoriaJornal
    from models.mano_obra import EstructuraRecargosMO, RecargoMOLinea

    cats_touched = 0
    for codigo, nombre, hora, confirmado in CATEGORIAS:
        cat = CategoriaJornal.query.filter(
            CategoriaJornal.organizacion_id.is_(None),
            CategoriaJornal.codigo == codigo,
        ).first()
        nota_prop = None if confirmado else 'valor_hora_convenio PROPUESTO (escala UOCRA) - a validar'
        if cat is None:
            cat = CategoriaJornal(
                organizacion_id=None, nombre=nombre, codigo=codigo, moneda='ARS',
                fuente='uocra', vigencia_desde=VIGENCIA, activo=True, notas=nota_prop,
            )
            db.session.add(cat)
        cat.valor_hora_convenio = hora
        cat.precio_jornal = (hora * Decimal('8')).quantize(Decimal('0.01'))  # sync legacy
        if cat.vigencia_desde is None:
            cat.vigencia_desde = VIGENCIA
        cats_touched += 1

    # Estructura de recargos global (idempotente por org NULL + zona + vigencia)
    est = EstructuraRecargosMO.query.filter(
        EstructuraRecargosMO.organizacion_id.is_(None),
        EstructuraRecargosMO.zona == ZONA,
        EstructuraRecargosMO.vigencia_desde == VIGENCIA,
    ).first()
    if est is None:
        est = EstructuraRecargosMO(
            organizacion_id=None, nombre='UOCRA Zona A CABA - abril 2026',
            zona=ZONA, vigencia_desde=VIGENCIA, horas_mensuales=176, horas_por_dia=8,
            fuente='planilla_brenda', activo=True,
        )
        db.session.add(est)
        db.session.flush()
    else:
        # Reemplazo limpio de las lineas (cascade delete-orphan)
        est.lineas.clear()
        db.session.flush()

    for i, (concepto, grupo, tc, valor, activo, notas) in enumerate(LINEAS, start=1):
        est.lineas.append(RecargoMOLinea(
            orden=i, concepto=concepto, grupo=grupo, tipo_calculo=tc,
            valor=valor, activo=activo, notas=notas,
        ))

    db.session.commit()
    return cats_touched, est.id, len([l for l in LINEAS if l[4]])


def main():
    import app as _app
    from extensions import db
    with _app.app.app_context():
        cats, est_id, lineas_activas = seed(db)
        print(f"[OK] categorias con hora convenio: {cats}")
        print(f"[OK] estructura recargos global id={est_id} ({lineas_activas} lineas activas)")

        # Verificacion: costo/hh oficial especializado
        from services.costo_mano_obra import desglose_categoria
        d = desglose_categoria('oficial_esp', organizacion_id=None, zona=ZONA, fecha=VIGENCIA)
        print(f"[VERIF] oficial_esp: basico={d['basico_hora']} bruto={d['bruto_hora']} "
              f"costo/hora={d['costo_hora']} costo/jornal={d['costo_jornal']}")
        print(f"        target planilla: $12.206,20 (con bono) / $12.177,79 (sin bono)")


if __name__ == '__main__':
    main()
