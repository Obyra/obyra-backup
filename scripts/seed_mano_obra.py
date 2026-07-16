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

VIGENCIA = date(2026, 8, 1)          # Escala salarial UOCRA firmada (UOCRA/CAC), Zona A
VIGENCIA_RECARGOS = date(2026, 4, 1)  # Estructura de recargos (planilla): independiente del basico
ZONA = 'CABA'
HORAS_MES = 176               # para derivar hora convenio de sueldos mensuales

# Escala UOCRA Zona A ($/hora) vigente 01/08/2026 — valores OFICIALES firmados.
# El sereno se paga MENSUAL: se deriva la hora convenio = sueldo_mes / HORAS_MES.
# (codigo, nombre, valor_hora_convenio, nota)
CATEGORIAS = [
    ('oficial_esp',   'Oficial Especializado', Decimal('7420.00'), None),
    ('oficial',       'Oficial',               Decimal('6348.00'), None),
    ('medio_oficial', 'Medio Oficial',         Decimal('5866.00'), None),
    ('ayudante',      'Ayudante',              Decimal('5399.00'), None),
    ('sereno',        'Sereno',                (Decimal('980858') / Decimal(HORAS_MES)).quantize(Decimal('0.01')),
     f'Sueldo mensual $980.858 / {HORAS_MES} hs (categoria mensual, no por jornal)'),
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
    historicos = 0
    for codigo, nombre, hora, nota in CATEGORIAS:
        # Fila vigente de la escala nueva (idempotente por org NULL + codigo + vigencia)
        cat = CategoriaJornal.query.filter(
            CategoriaJornal.organizacion_id.is_(None),
            CategoriaJornal.codigo == codigo,
            CategoriaJornal.vigencia_desde == VIGENCIA,
        ).first()
        if cat is None:
            cat = CategoriaJornal(
                organizacion_id=None, nombre=nombre, codigo=codigo, moneda='ARS',
                fuente='uocra', vigencia_desde=VIGENCIA, activo=True,
            )
            db.session.add(cat)
        cat.valor_hora_convenio = hora
        cat.precio_jornal = (hora * Decimal('8')).quantize(Decimal('0.01'))  # sync legacy
        cat.fuente = 'uocra'
        cat.activo = True
        cat.notas = nota or 'Escala UOCRA Zona A firmada (UOCRA/CAC) - vigencia 01/08/2026'
        cats_touched += 1

        # Filas anteriores de la misma categoria -> historico (inactivas)
        viejas = CategoriaJornal.query.filter(
            CategoriaJornal.organizacion_id.is_(None),
            CategoriaJornal.codigo == codigo,
            CategoriaJornal.activo.is_(True),
            CategoriaJornal.vigencia_desde < VIGENCIA,
        ).all()
        for v in viejas:
            v.activo = False
            marca = '[historico - reemplazado por escala 01/08/2026]'
            if marca not in (v.notas or ''):
                v.notas = ((v.notas or '').strip() + ' ' + marca).strip()
            historicos += 1

    # Estructura de recargos global: es INDEPENDIENTE de la escala salarial
    # (los % de F931/presentismo/etc. no cambian al actualizar el basico). Hay
    # UNA sola global por zona; se actualiza in-place, no se duplica por vigencia.
    est = EstructuraRecargosMO.query.filter(
        EstructuraRecargosMO.organizacion_id.is_(None),
        EstructuraRecargosMO.zona == ZONA,
        EstructuraRecargosMO.activo.is_(True),
    ).order_by(EstructuraRecargosMO.vigencia_desde.asc()).first()
    if est is None:
        est = EstructuraRecargosMO(
            organizacion_id=None, nombre='Recargos MO Zona A CABA (planilla abril 2026)',
            zona=ZONA, vigencia_desde=VIGENCIA_RECARGOS, horas_mensuales=176, horas_por_dia=8,
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
    return cats_touched, historicos, est.id, len([l for l in LINEAS if l[4]])


def main():
    import app as _app
    from extensions import db
    with _app.app.app_context():
        cats_touched, historicos, est_id, lineas_activas = seed(db)
        print(f"[OK] categorias escala 01/08/2026: {cats_touched}  |  filas de abril a historico: {historicos}")
        print(f"[OK] estructura recargos global id={est_id} ({lineas_activas} lineas activas)")

        # Verificacion: costo empresa/hh de cada categoria con los basicos nuevos
        from services.costo_mano_obra import desglose_categoria
        print("[VERIF] costo empresa por categoria (escala 01/08/2026, recargos CABA):")
        for codigo, nombre, _hora, _nota in CATEGORIAS:
            d = desglose_categoria(codigo, organizacion_id=None, zona=ZONA, fecha=VIGENCIA)
            print(f"        {nombre:<22} basico={d['basico_hora']:>9}  bruto={d['bruto_hora']:>9}  "
                  f"costo/hora={d['costo_hora']:>10}  costo/jornal={d['costo_jornal']:>11}")


if __name__ == '__main__':
    main()
