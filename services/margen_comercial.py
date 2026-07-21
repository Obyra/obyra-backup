# -*- coding: utf-8 -*-
"""Margen comercial: capa de PRESENTACION (no toca el pipeline ni el cache).

Convencion: el margen es un MARKUP SOBRE EL COSTO, no un margen sobre venta.

    precio_venta = costo_directo * (1 + margen/100)

El pipeline (services/pipeline_presupuesto_ia.py) y el pipeline_ia_cache guardan
SIEMPRE costo directo puro. El margen se aplica reciEn al mostrar/imprimir, para que
cambiar el margen NO obligue a recalcular los items con IA.

Fuente unica: TODO lo que muestre precios de venta al usuario (PDF, revision) resuelve
el margen y aplica la formula acA. Precedencia:
    presupuesto.margen_comercial_override > organizacion.margen_comercial_default > 25%
"""
from decimal import Decimal, ROUND_HALF_UP

MARGEN_DEFAULT = Decimal('25')


def resolver_margen(presupuesto) -> Decimal:
    """Margen comercial (%) vigente para el presupuesto, resolviendo la precedencia:
    override del presupuesto > default de la organizacion > 25%."""
    if presupuesto is None:
        return MARGEN_DEFAULT
    m = presupuesto.margen_comercial_override
    if m is None:
        org = getattr(presupuesto, 'organizacion', None)
        m = getattr(org, 'margen_comercial_default', None) if org is not None else None
    if m is None:
        m = MARGEN_DEFAULT
    return Decimal(str(m))


def factor_margen(presupuesto) -> Decimal:
    """Factor multiplicativo: precio_venta = costo * factor. Markup SOBRE EL COSTO."""
    return Decimal('1') + resolver_margen(presupuesto) / Decimal('100')


def precio_venta(costo_directo, presupuesto) -> Decimal:
    """Precio de VENTA = costo_directo * (1 + margen/100). Markup sobre el costo
    (NO margen sobre venta). Redondea a centavos. Esta es la funcion unica por la que
    tiene que pasar todo lo que muestre precio de venta al usuario."""
    costo = Decimal(str(costo_directo or 0))
    return (costo * factor_margen(presupuesto)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
