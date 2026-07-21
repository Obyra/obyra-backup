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

VIGENCIA = date(2026, 8, 1)   # Escala salarial UOCRA firmada (UOCRA/CAC), Zona A
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
def _lineas(comida_dia, epp_mes, uocra_dia):
    """Lineas de la estructura de recargos. Los % son estables; solo varian los
    montos fijos (comida/EPP/UOCRA) segun la vigencia. Bono es acuerdo fijo."""
    D = Decimal
    return [
        ('Presentismo',        'adicional_remunerativo',    'pct_hora_convenio', D('20'),        True,
         'Sobre hora convenio'),
        ('hh50 (6hh/50hsem)',  'adicional_remunerativo',    'pct_hora_convenio', D('2.27'),      False,
         'Horas al 50%. INACTIVO: la planilla calcula el costo empresa sobre bruto sin hh50. Activar si se incluye OT en la base.'),
        # F.931 depurado a la parte PATRONAL (2026-07-21). Se QUITAN los aportes del
        # TRABAJADOR (jubilacion 14,69 + OS 3,91 = 18,60% s/bruto): se descuentan del
        # bruto del empleado, NO son costo del empleador. Desglose auditable linea x
        # linea. Las 4 lineas de seg. social suman 19,48% (el patronal ya validado);
        # OS patronal 6,58; ART 14 (NO se baja); seguro de vida 0,08. Total 40,14%.
        ('Jubilacion (contrib. patronal SIPA)', 'carga_social', 'pct_bruto', D('12.35'), True,
         'Contribucion patronal jubilatoria (SIPA, Ley 24.241). Alicuota patronal.'),
        ('INSSJP (PAMI, contrib. patronal)',    'carga_social', 'pct_bruto', D('1.57'),  True,
         'Contribucion patronal (Ley 19.032).'),
        ('Asignaciones Familiares',             'carga_social', 'pct_bruto', D('4.67'),  True,
         'Contribucion patronal (Ley 24.714).'),
        ('Fondo Nacional de Empleo',            'carga_social', 'pct_bruto', D('0.89'),  True,
         'Contribucion patronal (Ley 24.013).'),
        ('Obra Social (contrib. patronal)',     'carga_social', 'pct_bruto', D('6.58'),  True,
         'Contribucion patronal a obra social (sin el aporte del trabajador de 3,91%).'),
        ('ART / LRT (construccion)',            'carga_social', 'pct_bruto', D('14'),    True,
         'Riesgos del trabajo. Construccion = alicuota mas alta del sistema. NO bajar.'),
        ('Seguro de vida obligatorio',          'carga_social', 'pct_bruto', D('0.08'),  True,
         'Decreto 1567/74.'),
        ('Fondo de desempleo', 'carga_social',              'pct_bruto',         D('12'),         True, None),
        ('SAC',                'carga_social',              'pct_bruto',         D('8.33'),       True,
         '1/12 de la remuneracion'),
        ('Vacaciones',         'carga_social',              'pct_bruto',         D('4.17'),       True,
         'Proporcionales'),
        ('UOCRA',              'carga_social',              'monto_dia',         D(str(uocra_dia)), True,
         'Aporte gremial (monto por dia)'),
        ('IERIC',              'carga_social',              'monto_mes',         D('15.90'),      True,
         '2% (monto mensual)'),
        ('Comida',             'adicional_no_remunerativo', 'monto_dia',         D(str(comida_dia)), True,
         'Vianda por dia'),
        ('EPP',                'adicional_no_remunerativo', 'monto_mes',         D(str(epp_mes)),   True,
         'Elementos de proteccion personal (monto mensual)'),
        ('Bono anual',         'adicional_no_remunerativo', 'monto_mes',         D('5000'),       True,
         '$30.000/anio amortizado en 6 meses = $5.000/mes (acuerdo fijo, no se ajusta por inflacion)'),
    ]


# Versiones de la estructura de recargos (los % son estables; los montos fijos se
# ajustan por inflacion acumulada abril->agosto = 6,7%; el bono queda fijo).
# (vigencia_desde, vigencia_hasta, nombre, lineas)
ESTRUCTURAS = [
    (date(2026, 4, 1), date(2026, 7, 31), 'Recargos MO Zona A CABA - abril 2026',
     _lineas(comida_dia='911.11', epp_mes='130.91', uocra_dia='278.30')),
    (date(2026, 8, 1), None,             'Recargos MO Zona A CABA - agosto 2026 (montos +6,7%)',
     _lineas(comida_dia='972.15', epp_mes='139.68', uocra_dia='296.95')),
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

    # Estructura de recargos global, VERSIONADA por vigencia. Los % son estables;
    # los montos fijos se ajustan por inflacion. Cada version es idempotente por
    # (org NULL, zona, vigencia_desde); la de agosto es la vigente hoy.
    est_vigente = None
    for vig_desde, vig_hasta, nombre, lineas in ESTRUCTURAS:
        est = EstructuraRecargosMO.query.filter(
            EstructuraRecargosMO.organizacion_id.is_(None),
            EstructuraRecargosMO.zona == ZONA,
            EstructuraRecargosMO.vigencia_desde == vig_desde,
        ).first()
        if est is None:
            est = EstructuraRecargosMO(
                organizacion_id=None, nombre=nombre, zona=ZONA,
                vigencia_desde=vig_desde, horas_mensuales=176, horas_por_dia=8,
                fuente='planilla_brenda', activo=True,
            )
            db.session.add(est)
            db.session.flush()
        else:
            est.lineas.clear()  # reemplazo limpio (cascade delete-orphan)
            db.session.flush()
        est.nombre = nombre
        est.vigencia_hasta = vig_hasta
        est.activo = True
        for i, (concepto, grupo, tc, valor, activo, notas) in enumerate(lineas, start=1):
            est.lineas.append(RecargoMOLinea(
                orden=i, concepto=concepto, grupo=grupo, tipo_calculo=tc,
                valor=valor, activo=activo, notas=notas,
            ))
        if vig_hasta is None:
            est_vigente = est

    db.session.commit()
    n_activas = len([l for l in ESTRUCTURAS[-1][3] if l[4]])
    return cats_touched, historicos, est_vigente.id, n_activas


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
