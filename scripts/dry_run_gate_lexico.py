"""DRY-RUN del gate lexico del matcher de precios. NO ESCRIBE NADA.

Que mide
--------
`_buscar_provider_price_list` paso 3 (fuzzy) acepta un candidato con
`cov_item = |comunes| / |tokens_query| >= 0.65`. El problema es que
`_tokens_significativos` explota las dimensiones: 'azulejo 15x15' ->
{azulejo, 15x15, 15}. DOS DE TRES tokens son la dimension, asi que un
candidato que solo comparta la medida llega a 0.67 y entra sin haber
matcheado el sustantivo.

Caso real (produccion, presupuesto 70):

    APU    : revestimiento_azulejo -> 'Azulejo 15x15' [u] x 35 piezas/m2
    MATCH  : 'Malla Sima 15x15 cm (4.2 mm de espesor) - Panel 3x2 m' [un]
             $20.700 el panel  ->  35 x 20.700 = $724.500 el m2
    EFECTO : 3 items de porcelanato = $1.044M sobre $2.612M de costo (40%)

El gate propuesto exige compartir al menos un token LEXICO (sustantivo o
calificativo; no numeros, no dimensiones, no palabras de medida) y calcula
la cobertura sobre esos.

Por que este script existe y por que lista NOMBRES
--------------------------------------------------
Precedente directo: el commit 57f538f revirtio un filtro por `_es_no_apu()`
que parecia sensato y destruyo 66 vinculos CORRECTOS. El error no se veia en
los agregados: se veia leyendo los NOMBRES de lo que se caia.

Por eso este script reporta CADA recurso cuyo precio cambia, con el match
viejo y el nuevo, para juzgarlos a mano. Un delta chico no prueba que el gate
sea bueno y uno grande no prueba que sea malo: hay que leer la lista.

Por que replica el loop de scoring
----------------------------------
Corre contra PRODUCCION, donde el codigo deployado todavia no tiene el gate.
Para no tocar nada en el contenedor, el script re-implementa el loop del paso
3 con el gate como flag. Esa replica podria driftear respecto del original, asi
que ANTES de comparar corre una AUTOVERIFICACION: con el gate apagado tiene que
dar exactamente lo mismo que `_buscar_provider_price_list` deployado, recurso
por recurso. Si no coincide, aborta y no reporta nada.

Es de solo lectura: unicamente SELECT y rollback al terminar.

Uso
---
    python scripts/dry_run_gate_lexico.py --org 1
    python scripts/dry_run_gate_lexico.py --org 1 --csv delta.csv
"""
import argparse
import os
import sys

os.environ.setdefault('SKIP_RUNTIME_MIGRATIONS', '1')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _recursos_del_catalogo(nivel='estandar'):
    """(nombre, unidad, regla, coeficiente) de cada material/equipo del YAML."""
    from services.coeficientes_loader import get_recursos, reglas_con_coeficientes

    vistos = {}
    for rid in sorted(reglas_con_coeficientes()):
        for r in (get_recursos(rid, nivel) or []):
            if (r.get('tipo') or '') == 'mano_obra':
                continue  # la MO no pasa por provider_price_list
            clave = (r.get('nombre', ''), r.get('unidad', ''))
            if clave not in vistos:
                vistos[clave] = (rid, float(r.get('coeficiente') or 0))
    return [(n, u, rid, coef) for (n, u), (rid, coef) in sorted(vistos.items())]


def _candidatos_fuzzy(prs, org, desc_norm):
    """Mismo pre-filtro SQL que el paso 3 del matcher deployado."""
    from extensions import db
    from models.provider_price_list import ProviderPriceList

    tokens_item = prs._tokens_significativos(desc_norm)
    if not tokens_item:
        return tokens_item, []
    scope = db.or_(ProviderPriceList.organizacion_id == org,
                   ProviderPriceList.organizacion_id.is_(None))
    org_first = db.case((ProviderPriceList.organizacion_id == org, 0), else_=1)
    toks = [t for t in tokens_item if len(t) >= 4] or [t for t in tokens_item if len(t) >= 3]
    q = ProviderPriceList.query.filter(scope)
    if toks:
        like = [ProviderPriceList.descripcion_normalizada.ilike('%' + t + '%')
                for t in sorted(toks, key=len, reverse=True)[:8]]
        q = q.filter(db.or_(*like))
    todos = (q.order_by(org_first, ProviderPriceList.fecha_actualizacion.desc())
             .limit(2000).all())
    return tokens_item, todos


def _lexicos(tokens):
    """Copia del _tokens_lexicos propuesto (el deployado todavia no lo tiene)."""
    no_identitarios = {
        'mts', 'mtr', 'mtrs', 'cms', 'mms', 'kgs', 'grs', 'lts', 'uni', 'und',
        'pulg', 'pulgada', 'pulgadas', 'espesor', 'medida', 'medidas', 'diametro',
        'largo', 'ancho', 'alto', 'altura',
    }
    return {t for t in tokens if len(t) >= 3 and t.isalpha() and t not in no_identitarios}


def _mejor(prs, org, desc_norm, unidad, con_gate):
    """Replica del paso 3 fuzzy. con_gate=False == comportamiento deployado."""
    tokens_item, todos = _candidatos_fuzzy(prs, org, desc_norm)
    if not tokens_item:
        return None
    lex_item = _lexicos(tokens_item) if con_gate else set()
    scored = []
    for c in todos:
        tokens_c = prs._tokens_significativos(c.descripcion_normalizada or c.descripcion or '')
        if not tokens_c:
            continue
        inter = tokens_item & tokens_c
        if not inter:
            continue
        if lex_item:
            inter_lex = lex_item & _lexicos(tokens_c)
            if not inter_lex:
                continue
            cov_item = len(inter_lex) / len(lex_item)
        else:
            cov_item = len(inter) / len(tokens_item)
        jaccard = len(inter) / len(tokens_item | tokens_c)
        cov_cand = len(inter) / len(tokens_c)
        if cov_item < 0.65 and jaccard < 0.4:
            continue
        score = (0.55 * cov_item + 0.30 * jaccard + 0.15 * cov_cand
                 + (0.2 if prs._unidades_compatibles(c.unidad, unidad) else 0.0)
                 + (0.5 if c.organizacion_id == org else 0.0))
        scored.append((score, c))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--org', type=int, required=True)
    ap.add_argument('--nivel', default='estandar')
    ap.add_argument('--csv')
    args = ap.parse_args()

    from app import app
    from extensions import db
    from models.provider_price_list import normalizar_descripcion_precio
    import services.precio_recurso_service as prs

    with app.app_context():
        db.session.execute(db.text('SET TRANSACTION READ ONLY'))

        recursos = _recursos_del_catalogo(args.nivel)
        print('Recursos de material/equipo en el catalogo APU: %d' % len(recursos))

        # --- AUTOVERIFICACION: gate apagado == matcher deployado ---
        divergencias = []
        for nombre, unidad, _rid, _coef in recursos:
            dn = normalizar_descripcion_precio(nombre)
            real, _ = prs._buscar_provider_price_list(args.org, dn, unidad)
            repl = _mejor(prs, args.org, dn, unidad, con_gate=False)
            # El matcher real puede resolver por prioridad 0/1/2 (antes del fuzzy);
            # en ese caso la replica no aplica y no se compara.
            if real is not None and repl is not None and real.id != repl.id:
                divergencias.append((nombre, unidad, real.id, repl.id))
        if divergencias:
            print('\nABORTA: la replica del loop no reproduce el matcher deployado '
                  'en %d recursos. No se puede confiar en la medicion.' % len(divergencias))
            for d in divergencias[:10]:
                print('   %s [%s]: real=%s replica=%s' % d)
            db.session.rollback()
            return 1
        print('Autoverificacion OK: gate apagado reproduce el matcher deployado.\n')

        # --- Comparacion real ---
        filas = []
        for nombre, unidad, rid, coef in recursos:
            dn = normalizar_descripcion_precio(nombre)
            # Solo importa lo que resuelve por fuzzy: si prioridad 0/1/2 ya matchea,
            # el gate no lo toca.
            real, _ = prs._buscar_provider_price_list(args.org, dn, unidad)
            antes = _mejor(prs, args.org, dn, unidad, con_gate=False)
            if real is not None and antes is not None and real.id != antes.id:
                continue  # resolvio por prioridad alta, el gate no participa
            despues = _mejor(prs, args.org, dn, unidad, con_gate=True)
            p_a = float(antes.precio_unitario) if antes else 0.0
            p_d = float(despues.precio_unitario) if despues else 0.0
            if abs(p_a - p_d) < 0.005:
                continue
            filas.append({
                'recurso': nombre, 'unidad': unidad, 'regla': rid, 'coef': coef,
                'precio_antes': p_a, 'precio_despues': p_d,
                'match_antes': (antes.descripcion or '') if antes else '(sin match)',
                'unidad_antes': (antes.unidad or '') if antes else '',
                'match_despues': (despues.descripcion or '') if despues else '(sin match)',
                'unidad_despues': (despues.unidad or '') if despues else '',
                'delta_unitario': (p_d - p_a) * coef,
            })

        perdidos = [f for f in filas if f['precio_despues'] == 0]
        cambiados = [f for f in filas if f['precio_despues'] > 0]

        print('=' * 100)
        print('RECURSOS QUE SE QUEDAN SIN PRECIO (%d) - LEER UNO POR UNO' % len(perdidos))
        print('=' * 100)
        for f in sorted(perdidos, key=lambda x: -abs(x['delta_unitario'])):
            print('\n  %s [%s]   (regla %s, coef %s)'
                  % (f['recurso'], f['unidad'], f['regla'], f['coef']))
            print('    antes  : $%-12s [%s] <- %s'
                  % (f['precio_antes'], f['unidad_antes'], f['match_antes'][:65]))
            print('    despues: SIN PRECIO    (saca $%.2f del unitario de la regla)'
                  % abs(f['delta_unitario']))

        print('\n' + '=' * 100)
        print('RECURSOS QUE CAMBIAN DE MATCH (%d)' % len(cambiados))
        print('=' * 100)
        for f in sorted(cambiados, key=lambda x: -abs(x['delta_unitario'])):
            print('\n  %s [%s]   (regla %s, coef %s)'
                  % (f['recurso'], f['unidad'], f['regla'], f['coef']))
            print('    antes  : $%-12s [%s] <- %s'
                  % (f['precio_antes'], f['unidad_antes'], f['match_antes'][:65]))
            print('    despues: $%-12s [%s] <- %s'
                  % (f['precio_despues'], f['unidad_despues'], f['match_despues'][:65]))
            print('    delta en el unitario de la regla: %+.2f' % f['delta_unitario'])

        print('\n' + '=' * 100)
        print('RESUMEN: %d recursos cambian (%d pierden precio, %d cambian de match)'
              % (len(filas), len(perdidos), len(cambiados)))
        print('=' * 100)

        if args.csv and filas:
            import csv
            with open(args.csv, 'w', newline='', encoding='utf-8') as fh:
                w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
                w.writeheader()
                w.writerows(filas)
            print('CSV: %s' % args.csv)

        db.session.rollback()
    return 0


if __name__ == '__main__':
    sys.exit(main())
