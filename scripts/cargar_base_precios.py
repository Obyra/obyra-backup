"""Carga la base de precios OBYRA (catalogo ~6.345 recursos) a ProviderPriceList.

Fase 1 — IA de presupuestos. Idempotente: correr 2 veces actualiza precios,
no duplica (clave: org + desc_normalizada + unidad + zona).

Uso:
    python scripts/cargar_base_precios.py --org-id 8 \
        --xlsx "C:/Users/ECSA/Desktop/BREN/PRECIOS OBYRA/OBYRA_base_precios_recursos_v1.xlsx"

La base se carga POR ORGANIZACION (ProviderPriceList es multi-tenant y
precio_recurso_service la consulta filtrando por organizacion_id, sin fallback
global). Para que otra org la use, correr con su --org-id.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DEFAULT_XLSX = r"C:\Users\ECSA\Desktop\BREN\PRECIOS OBYRA\OBYRA_base_precios_recursos_v1.xlsx"


def main():
    ap = argparse.ArgumentParser(description="Cargar base de precios OBYRA a ProviderPriceList")
    ap.add_argument("--org-id", type=int, required=True,
                    help="ID de organizacion para el ImportBatch (trazabilidad). Con --global "
                         "los precios se cargan como base global; sin --global, para esa org.")
    ap.add_argument("--xlsx", default=_DEFAULT_XLSX, help="Ruta al OBYRA_base_precios_recursos_v1.xlsx")
    ap.add_argument("--user-id", type=int, default=None, help="ID del usuario que carga (opcional)")
    ap.add_argument("--global", dest="global_base", action=argparse.BooleanOptionalAction,
                    default=True, help="Cargar como BASE GLOBAL (org NULL). Default: True.")
    args = ap.parse_args()

    import app as _app
    from extensions import db
    with _app.app.app_context():
        from services.importer_lista_propia import importar_catalogo_base
        res = importar_catalogo_base(
            db=db, xlsx_path=args.xlsx, organizacion_id=args.org_id, user_id=args.user_id,
            global_base=args.global_base,
        )
        print("Resultado:", res)
        if not res.get("ok"):
            sys.exit(1)


if __name__ == "__main__":
    main()
