# -*- coding: utf-8 -*-
"""DRY-RUN de la vinculacion item de presupuesto <-> inventario. NO ESCRIBE NADA.

Para que sirve
--------------
`services/inventory_matcher.py` decide, al importar un pliego, que items del
presupuesto se vinculan a un ItemInventario (y por lo tanto se pueden reservar
contra el deposito en la obra). Los umbrales (_MIN_COBERTURA, _GAP_MIN) se
eligieron contra un inventario sintetico. Este script los somete a datos REALES:
recorre un presupuesto ya importado y reporta que vincularia, que no, y --lo mas
importante-- que casos quedaron CERCA del umbral, para saber si hay que moverlo.

Es de solo lectura: unicamente SELECT, y hace rollback al terminar. Se puede
correr contra produccion sin riesgo.

Uso
---
    python scripts/dry_run_vinculacion_inventario.py --presupuesto-id 123
    python scripts/dry_run_vinculacion_inventario.py --presupuesto-id 123 --top 5
    python scripts/dry_run_vinculacion_inventario.py --presupuesto-id 123 --csv salida.csv

Como leer la salida
-------------------
  cobertura = que fraccion del NOMBRE DE INVENTARIO aparece en la descripcion del
              pliego. 1.0 = el nombre completo esta contenido en el renglon.
  El bloque CALIBRACION barre el umbral de cobertura y muestra cuantos items
  vincularias con cada valor. Si al bajar de 0.60 a 0.50 aparecen muchos items
  y son correctos, el umbral esta alto. Si aparecen disparates, esta bien.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Descripciones con acentos + consola Windows cp1252 = UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

SEP = "=" * 100
SUB = "-" * 100


def _corto(s, n):
    s = (s or '').strip().replace('\n', ' ')
    return s if len(s) <= n else s[:n - 1] + '…'


def main():
    ap = argparse.ArgumentParser(
        description="Dry-run de vinculacion con inventario (NO escribe en la DB)")
    ap.add_argument("--presupuesto-id", type=int, required=True,
                    help="ID del presupuesto ya importado a analizar")
    ap.add_argument("--top", type=int, default=3,
                    help="Candidatos a mostrar por item sin vincular (default 3)")
    ap.add_argument("--csv", default=None,
                    help="Ruta opcional para volcar el detalle completo en CSV")
    args = ap.parse_args()

    import app as _app
    from extensions import db

    with _app.app.app_context():
        try:
            _reportar(db, args)
        finally:
            # Paranoia: este script no escribe, pero si algo dejo la sesion
            # sucia no queremos que se persista por un autoflush.
            db.session.rollback()


def _reportar(db, args):
    from models.budgets import Presupuesto, ItemPresupuesto
    from services.inventory_matcher import (
        construir_indice_inventario, evaluar_candidatos, vincular_item_inventario,
        _MIN_COBERTURA, _GAP_MIN,
    )

    pres = Presupuesto.query.get(args.presupuesto_id)
    if not pres:
        print(f"ERROR: no existe el presupuesto {args.presupuesto_id}")
        sys.exit(1)

    org_id = pres.organizacion_id
    indice = construir_indice_inventario(org_id)

    items = (ItemPresupuesto.query
             .filter(ItemPresupuesto.presupuesto_id == pres.id,
                     ItemPresupuesto.tipo == 'material')
             .order_by(ItemPresupuesto.id)
             .all())

    print(SEP)
    print("DRY-RUN vinculacion inventario  --  NO SE ESCRIBE NADA EN LA DB")
    print(SEP)
    print(f"  presupuesto      : #{pres.id}  {pres.numero}   (origen: {pres.origen_creacion or 'n/d'})")
    print(f"  organizacion     : {org_id}")
    print(f"  items material   : {len(items)}")
    print(f"  inventario activo: {len(indice)} items")
    print(f"  umbrales         : cobertura >= {_MIN_COBERTURA}   gap > {_GAP_MIN}")

    if not indice:
        print("\n  !! El inventario de esta organizacion esta VACIO.")
        print("     Ningun item se puede vincular, y no es culpa del matcher.")
        return
    if not items:
        print("\n  !! El presupuesto no tiene items de tipo 'material'.")
        return

    ya_vinculados = sum(1 for it in items if it.item_inventario_id)
    if ya_vinculados:
        print(f"  ya vinculados    : {ya_vinculados} (el import los habia resuelto)")

    filas = []
    for it in items:
        inv_id, score, motivo = vincular_item_inventario(
            it.descripcion, it.unidad, indice)
        cands = evaluar_candidatos(it.descripcion, it.unidad, indice,
                                   incluir_rechazados=True)
        filas.append({'item': it, 'inv_id': inv_id, 'score': score,
                      'motivo': motivo, 'cands': cands})

    por_id = {c['id']: c['nombre'] for c in indice}
    vinc = [f for f in filas if f['inv_id']]
    novinc = [f for f in filas if not f['inv_id']]

    # ---------- VINCULARIA ----------
    print("\n" + SEP)
    print(f"VINCULARIA  ({len(vinc)} de {len(items)})")
    print(SUB)
    if not vinc:
        print("  (ninguno)")
    for f in sorted(vinc, key=lambda x: -x['score']):
        it = f['item']
        print(f"  {f['score']:>4}  {_corto(it.descripcion, 52):52} [{(it.unidad or '')[:5]:>5}]")
        print(f"        -> {_corto(por_id.get(f['inv_id'], '?'), 60)}")

    # ---------- NO VINCULARIA ----------
    print("\n" + SEP)
    print(f"NO VINCULARIA  ({len(novinc)} de {len(items)})")
    print(SUB)
    if not novinc:
        print("  (ninguno)")
    for f in novinc:
        it = f['item']
        print(f"  [{f['motivo']:>12}] {_corto(it.descripcion, 55):55} [{(it.unidad or '')[:5]:>5}]")
        for c in f['cands'][:args.top]:
            marca = c['rechazo'] or 'PASA'
            print(f"        cand cob={c['cobertura']:<5} {_corto(c['nombre'], 40):40} "
                  f"[{(c['unidad'] or '')[:5]:>5}] {marca}")
        if not f['cands']:
            print("        (sin candidatos con tokens en comun)")

    # ---------- RESUMEN ----------
    n = len(items)
    pct = lambda k: f"{100.0 * k / n:.1f}%"          # noqa: E731
    motivos = {}
    for f in novinc:
        motivos[f['motivo']] = motivos.get(f['motivo'], 0) + 1

    print("\n" + SEP)
    print("RESUMEN")
    print(SUB)
    print(f"  vincularia         : {len(vinc):>4}  ({pct(len(vinc))})")
    print(f"  sin vincular       : {len(novinc):>4}  ({pct(len(novinc))})")
    for m, k in sorted(motivos.items(), key=lambda x: -x[1]):
        print(f"      por {m:<18}: {k:>4}")

    # ---------- CALIBRACION ----------
    print("\n" + SEP)
    print("CALIBRACION")
    print(SUB)

    # (a) barrido del umbral de cobertura. Se respeta SIEMPRE el guard de unidad
    #     y el minimo de tokens: esos no son parametros de ajuste, son guards.
    print("\n  (a) Si movieras el umbral de cobertura (unidad y tokens siguen filtrando):\n")
    print("        umbral   vincularia   delta vs actual")
    for u in (0.40, 0.50, 0.55, 0.60, 0.70, 0.80, 0.90, 1.00):
        k = 0
        for f in filas:
            elegibles = [c for c in f['cands']
                         if c['rechazo'] in (None, 'cobertura_baja')
                         and c['cobertura'] >= u]
            if not elegibles:
                continue
            if len(elegibles) > 1:
                a, b = elegibles[0], elegibles[1]
                if (a['cobertura'] - b['cobertura']) <= _GAP_MIN and a['n_comunes'] == b['n_comunes']:
                    continue        # ambiguo, no vincularia
            k += 1
        marca = "   <-- actual" if abs(u - _MIN_COBERTURA) < 1e-9 else ""
        print(f"        {u:<8} {k:>10}   {k - len(vinc):+d}{marca}")

    # (b) los que entraron raspando: si el umbral sube, estos son los que se caen
    raspando = [f for f in vinc if f['score'] < _MIN_COBERTURA + 0.15]
    print(f"\n  (b) Entraron raspando (cobertura < {_MIN_COBERTURA + 0.15:.2f}) — "
          f"reviselos a mano, son los mas dudosos: {len(raspando)}\n")
    for f in sorted(raspando, key=lambda x: x['score'])[:15]:
        print(f"        cob={f['score']:<5} {_corto(f['item'].descripcion, 45):45}")
        print(f"                -> {_corto(por_id.get(f['inv_id'], '?'), 55)}")
    if not raspando:
        print("        (ninguno — todos los vinculos son de cobertura alta)")

    # (c) los que quedaron cerca por abajo: si el umbral baja, estos son los que entran
    cerca = []
    for f in novinc:
        for c in f['cands']:
            if c['rechazo'] == 'cobertura_baja' and c['cobertura'] >= _MIN_COBERTURA - 0.20:
                cerca.append((f['item'], c))
                break
    print(f"\n  (c) Quedaron cerca por abajo (cobertura entre "
          f"{_MIN_COBERTURA - 0.20:.2f} y {_MIN_COBERTURA:.2f}): {len(cerca)}\n")
    for it, c in sorted(cerca, key=lambda x: -x[1]['cobertura'])[:15]:
        print(f"        cob={c['cobertura']:<5} {_corto(it.descripcion, 45):45}")
        print(f"                -> {_corto(c['nombre'], 55)}   comunes={c['comunes']}")
    if not cerca:
        print("        (ninguno)")

    # (d) ambiguos: cuanto gap les falto
    amb = [f for f in novinc if f['motivo'] == 'ambiguo']
    print(f"\n  (d) Ambiguos (empate entre variantes): {len(amb)}\n")
    for f in amb[:10]:
        print(f"        {_corto(f['item'].descripcion, 55)}")
        for c in f['cands'][:2]:
            print(f"                cob={c['cobertura']:<5} {_corto(c['nombre'], 50)}")
    if not amb:
        print("        (ninguno)")

    # (e) rechazo por unidad: si es alto, el problema son las unidades del inventario,
    #     no el umbral de texto.
    solo_unidad = 0
    for f in novinc:
        tiene_texto_ok = any(c['rechazo'] == 'unidad' and c['cobertura'] >= _MIN_COBERTURA
                             for c in f['cands'])
        if tiene_texto_ok:
            solo_unidad += 1
    print(f"\n  (e) Items donde el TEXTO matcheaba pero la UNIDAD no: {solo_unidad}")
    if solo_unidad:
        print("      Si este numero es alto, revisa las unidades cargadas en el inventario")
        print("      (o hace falta factor_conversion: m2 de pared -> unidades de ladrillo).")
        for f in novinc:
            for c in f['cands']:
                if c['rechazo'] == 'unidad' and c['cobertura'] >= _MIN_COBERTURA:
                    print(f"        {_corto(f['item'].descripcion, 42):42} "
                          f"[{(f['item'].unidad or '')[:5]:>5}]  vs  "
                          f"{_corto(c['nombre'], 28):28} [{(c['unidad'] or '')[:5]:>5}]")
                    break

    # ---------- CSV ----------
    if args.csv:
        import csv
        with open(args.csv, 'w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['item_id', 'descripcion', 'unidad', 'vincula_a_id',
                        'vincula_a_nombre', 'score', 'motivo',
                        'mejor_candidato', 'mejor_cobertura', 'mejor_rechazo'])
            for f in filas:
                it = f['item']
                mc = f['cands'][0] if f['cands'] else None
                w.writerow([
                    it.id, it.descripcion, it.unidad,
                    f['inv_id'] or '', por_id.get(f['inv_id'], ''),
                    f['score'], f['motivo'],
                    mc['nombre'] if mc else '', mc['cobertura'] if mc else '',
                    (mc['rechazo'] or 'PASA') if mc else '',
                ])
        print(f"\n  CSV escrito en: {args.csv}")

    print("\n" + SEP)
    print("Fin del dry-run. No se modifico ningun registro.")
    print(SEP)


if __name__ == '__main__':
    main()
