"""
Service centralizado de calculo de costo real de obra — Caja B.1 / Plan 90%
============================================================================

OBJETIVO de esta fase (B.1):
  - Crear UN unico lugar donde se calcule `obra.costo_real`.
  - NO conectar todavia con los 6 lugares que escriben costo_real
    (eso es B.2).
  - NO sumar Caja B al calculo todavia (eso es B.4).

La funcion `calcular_costo_real` replica EXACTAMENTE la formula actual
para no romper compatibilidad. La funcion `calcular_costo_real_proyectado`
devuelve el breakdown completo + el monto que SUMARIA si Caja B estuviera
activo (para script de auditoria pre-migracion).

Fase B.4 cambiara el comportamiento default a `usar_caja_b=True` cuando
hayamos auditado y confirmado que los numeros cierran.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional


def _calcular_costo_materiales(obra_id: int) -> Decimal:
    """Suma UsoInventario.cantidad_usada * precio_unitario_al_uso.

    Replica EXACTAMENTE la formula de obras.calcular_costo_materiales
    (que es la fuente de verdad usada por los 6 lugares que escriben
    obra.costo_real hoy). El precio usado es el congelado al momento
    de descontar el material — no el promedio actual del inventario.
    """
    from extensions import db
    from models.inventory import UsoInventario
    total = db.session.query(
        db.func.coalesce(
            db.func.sum(
                UsoInventario.cantidad_usada *
                db.func.coalesce(UsoInventario.precio_unitario_al_uso, 0)
            ), 0
        )
    ).filter(UsoInventario.obra_id == obra_id).scalar()
    return Decimal(str(total or 0))


def _calcular_costo_mano_obra_pagada(obra_id: int) -> Decimal:
    """Suma LiquidacionMOItem.monto donde estado='pagado' para la obra.

    Coincide con la formula usada en obras/materiales.py:849-857.
    """
    from extensions import db
    from models.templates import LiquidacionMO, LiquidacionMOItem
    total = db.session.query(
        db.func.coalesce(db.func.sum(LiquidacionMOItem.monto), 0)
    ).join(LiquidacionMO).filter(
        LiquidacionMO.obra_id == obra_id,
        LiquidacionMOItem.estado == 'pagado',
    ).scalar() or 0
    return Decimal(str(total))


def _calcular_costo_mano_obra_total(obra_id: int) -> Decimal:
    """Suma LiquidacionMO.monto_total de todas las liquidaciones de la obra.

    Replica la formula 'minima' usada por obras/tareas.py:461-463 y
    obras/certificaciones.py:96-99 (que NO filtran por estado='pagado').
    """
    from extensions import db
    from models.templates import LiquidacionMO
    total = db.session.query(
        db.func.coalesce(db.func.sum(LiquidacionMO.monto_total), 0)
    ).filter(LiquidacionMO.obra_id == obra_id).scalar() or 0
    return Decimal(str(total))


def _calcular_costo_maquinaria(obra_id: int) -> Decimal:
    """Replica EXACTAMENTE el calculo de obras/core.py:815-866.

    - Solo EquipmentUsage.estado='aprobado'.
    - Separa por modalidad: 'compra'/'alquiler_hora' usan costo_hora,
      'alquiler_dia' usa costo_dia.
    - Equipos en USD se convierten a ARS con el ultimo ExchangeRate.
    """
    from extensions import db
    from sqlalchemy import func
    try:
        from models.equipment import EquipmentUsage, Equipment
    except Exception:
        return Decimal('0')

    # Tipo de cambio USD->ARS (mas reciente).
    tipo_cambio_ars = Decimal('1')
    try:
        from models.budgets import ExchangeRate
        rate = ExchangeRate.query.filter(
            ExchangeRate.base_currency == 'USD',
            ExchangeRate.quote_currency == 'ARS',
        ).order_by(
            ExchangeRate.as_of_date.desc(), ExchangeRate.id.desc()
        ).first()
        if rate and rate.value:
            tipo_cambio_ars = Decimal(str(rate.value))
    except Exception:
        pass

    mod_hora = Equipment.modalidad_costo.in_(['compra', 'alquiler_hora'])
    mod_dia = Equipment.modalidad_costo == 'alquiler_dia'

    def _sum_usos(modalidad_filter, campo_costo, moneda):
        try:
            v = db.session.query(
                func.coalesce(func.sum(EquipmentUsage.horas * campo_costo), 0)
            ).join(Equipment).filter(
                EquipmentUsage.project_id == obra_id,
                EquipmentUsage.estado == 'aprobado',
                Equipment.moneda == moneda,
                modalidad_filter,
            ).scalar() or 0
            return Decimal(str(v))
        except Exception:
            return Decimal('0')

    h_ars = _sum_usos(mod_hora, Equipment.costo_hora, 'ARS')
    d_ars = _sum_usos(mod_dia, Equipment.costo_dia, 'ARS')
    h_usd = _sum_usos(mod_hora, Equipment.costo_hora, 'USD')
    d_usd = _sum_usos(mod_dia, Equipment.costo_dia, 'USD')

    return h_ars + d_ars + (h_usd + d_usd) * tipo_cambio_ars


def _calcular_horas_maquinaria(obra_id: int) -> Decimal:
    """Horas de uso aprobado (solo modalidad hora/compra).

    Necesario para que obras/core.py pueda seguir devolviendo `horas_maquinaria`
    en su JSON sin cambiar la respuesta.
    """
    from extensions import db
    from sqlalchemy import func
    try:
        from models.equipment import EquipmentUsage, Equipment
        mod_hora = Equipment.modalidad_costo.in_(['compra', 'alquiler_hora'])
        v = db.session.query(
            func.coalesce(func.sum(EquipmentUsage.horas), 0)
        ).join(Equipment).filter(
            EquipmentUsage.project_id == obra_id,
            EquipmentUsage.estado == 'aprobado',
            mod_hora,
        ).scalar() or 0
        return Decimal(str(v))
    except Exception:
        return Decimal('0')


def _calcular_caja_b_confirmados_legacy(obra_id: int) -> Decimal:
    """Replica fórmula vieja de obras/core.py:879-892 (PRE-B.1).

    Suma todos los MovimientoCaja con tipo IN ('gasto_obra','pago_proveedor')
    y estado='confirmado'. NO mira impacta_costo_real (esa columna es nueva
    de B.1 y todos los movimientos viejos tienen impacta_costo_real=FALSE).

    En B.2 mantenemos este comportamiento para no cambiar valores.
    En B.4 evaluaremos migrar este lugar al flag impacta_costo_real.
    """
    from extensions import db
    from sqlalchemy import func
    try:
        from models.templates import MovimientoCaja
        v = db.session.query(
            func.coalesce(func.sum(MovimientoCaja.monto), 0)
        ).filter(
            MovimientoCaja.obra_id == obra_id,
            MovimientoCaja.estado == 'confirmado',
            MovimientoCaja.tipo.in_(['gasto_obra', 'pago_proveedor']),
        ).scalar() or 0
        return Decimal(str(v))
    except Exception:
        return Decimal('0')


def _calcular_caja_b_egresos_impacta(obra_id: int) -> Decimal:
    """Suma MovimientoCaja.monto para egresos confirmados que impactan costo.

    Solo se incluyen movimientos:
      - direccion = 'egreso'
      - impacta_costo_real = TRUE
      - estado = 'confirmado'

    En B.1 esto se calcula pero NO se suma al costo_real por default.
    La funcion calcular_costo_real_proyectado lo muestra como referencia
    para que el script de auditoria pueda compararlo.
    """
    from extensions import db
    from models.templates import MovimientoCaja
    # OJO: las columnas direccion / impacta_costo_real son nuevas (B.1).
    # Si todavia no estan en BD (migration no corrida), devolvemos 0.
    try:
        total = db.session.query(
            db.func.coalesce(db.func.sum(MovimientoCaja.monto), 0)
        ).filter(
            MovimientoCaja.obra_id == obra_id,
            MovimientoCaja.direccion == 'egreso',
            MovimientoCaja.impacta_costo_real.is_(True),
            MovimientoCaja.estado == 'confirmado',
        ).scalar() or 0
        return Decimal(str(total))
    except Exception:
        # Si las columnas todavia no existen (deploy parcial), no romper.
        return Decimal('0')


def calcular_costo_real(
    obra_id: int,
    *,
    incluir_mo_pagada_solo: bool = True,
    incluir_maquinaria: bool = False,
    incluir_caja_b_confirmados_legacy: bool = False,
    incluir_caja_b_marcada: bool = False,
    mo_extra: Optional[Decimal] = None,
) -> Decimal:
    """Calcula costo real de obra con flags explicitos por componente.

    B.2 (2026-05-13): cada caller historico llama con los flags que
    replican SU formula original. Esto centraliza el calculo sin cambiar
    valores existentes.

    Args:
        obra_id: ID de la obra.
        incluir_mo_pagada_solo:
            True  -> suma SOLO LiquidacionMOItem.monto where estado='pagado'
                     (formula 'media' — usada por materiales.py, liquidacion_mo.py,
                      certificaciones.py:311, core.py).
            False -> suma LiquidacionMO.monto_total de TODAS las liquidaciones
                     (formula 'minima' — usada por tareas.py y certificaciones.py:101).
        incluir_maquinaria:
            True  -> suma EquipmentUsage aprobado (replica core.py:815-866).
                     Solo usado por obras/core.py.
        incluir_caja_b_confirmados_legacy:
            True  -> suma MovimientoCaja tipo IN (gasto_obra, pago_proveedor)
                     y estado='confirmado'. NO mira impacta_costo_real.
                     Replica fórmula PRE-B.1 de obras/core.py:879-892.
                     Solo usado por obras/core.py.
        incluir_caja_b_marcada:
            True  -> suma MovimientoCaja con impacta_costo_real=TRUE,
                     direccion='egreso', estado='confirmado'.
                     NUEVO de B.1. **DESACTIVADO en B.2.** Se activa en B.4.
        mo_extra:
            Decimal adicional sumado a MO. Caso especial usado solo por
            certificaciones.py:311 cuando se certifica una liquidación
            nueva (debe contar tambien los items aun no marcados como pagados
            de esa liquidación recien creada).

    Returns:
        Decimal con el costo real total, quantizado a 2 decimales.
    """
    if not obra_id:
        return Decimal('0')

    materiales = _calcular_costo_materiales(obra_id)
    if incluir_mo_pagada_solo:
        mo = _calcular_costo_mano_obra_pagada(obra_id)
    else:
        mo = _calcular_costo_mano_obra_total(obra_id)

    if mo_extra is not None:
        mo = mo + Decimal(str(mo_extra))

    maquinaria = (_calcular_costo_maquinaria(obra_id)
                  if incluir_maquinaria else Decimal('0'))
    caja_legacy = (_calcular_caja_b_confirmados_legacy(obra_id)
                   if incluir_caja_b_confirmados_legacy else Decimal('0'))
    caja_marcada = (_calcular_caja_b_egresos_impacta(obra_id)
                    if incluir_caja_b_marcada else Decimal('0'))

    total = materiales + mo + maquinaria + caja_legacy + caja_marcada
    return total.quantize(Decimal('0.01'))


def calcular_costo_real_proyectado(obra_id: int) -> dict:
    """Breakdown completo de todos los componentes.

    Devuelve cada componente por separado para diagnostico/auditoria.
    NO escribe nada. NO afecta calculo en uso.
    """
    materiales = _calcular_costo_materiales(obra_id)
    mo_pagada = _calcular_costo_mano_obra_pagada(obra_id)
    mo_total = _calcular_costo_mano_obra_total(obra_id)
    maquinaria = _calcular_costo_maquinaria(obra_id)
    caja_legacy = _calcular_caja_b_confirmados_legacy(obra_id)
    caja_marcada = _calcular_caja_b_egresos_impacta(obra_id)

    # Resultados con cada combinacion de flags (las 3 formulas activas en B.2):
    formula_minima = materiales + mo_total
    formula_media = materiales + mo_pagada
    formula_rica = materiales + mo_pagada + maquinaria + caja_legacy

    Q = Decimal('0.01')
    return {
        'obra_id': obra_id,
        'componentes': {
            'materiales': float(materiales.quantize(Q)),
            'mano_obra_pagada': float(mo_pagada.quantize(Q)),
            'mano_obra_total': float(mo_total.quantize(Q)),
            'maquinaria': float(maquinaria.quantize(Q)),
            'caja_b_confirmados_legacy': float(caja_legacy.quantize(Q)),
            'caja_b_marcada': float(caja_marcada.quantize(Q)),
        },
        'formulas': {
            'minima': float(formula_minima.quantize(Q)),  # tareas, cert:101
            'media': float(formula_media.quantize(Q)),     # mat, liq, cert:311
            'rica': float(formula_rica.quantize(Q)),       # core.py
        },
        # Compatibilidad con codigo viejo que usaba estas keys
        'costo_real_actual': formula_media.quantize(Q),
        'costo_real_proyectado': formula_media.quantize(Q),
    }


def recalcular_y_persistir(
    obra_id: int,
    *,
    incluir_mo_pagada_solo: bool = True,
    incluir_maquinaria: bool = False,
    incluir_caja_b_confirmados_legacy: bool = False,
    incluir_caja_b_marcada: bool = False,
    mo_extra: Optional[Decimal] = None,
) -> Decimal:
    """Calcula y escribe el costo real en `obra.costo_real`.

    Punto de entrada UNICO para B.2 en adelante. Los 6 lugares que
    historicamente escribian `obra.costo_real` pasan a llamar esta funcion
    con los flags que replican su formula original.

    No hace commit — el caller maneja transaccion.

    Returns:
        Decimal con el costo persistido.
    """
    from models.projects import Obra
    obra = Obra.query.get(obra_id)
    if not obra:
        return Decimal('0')
    nuevo = calcular_costo_real(
        obra_id,
        incluir_mo_pagada_solo=incluir_mo_pagada_solo,
        incluir_maquinaria=incluir_maquinaria,
        incluir_caja_b_confirmados_legacy=incluir_caja_b_confirmados_legacy,
        incluir_caja_b_marcada=incluir_caja_b_marcada,
        mo_extra=mo_extra,
    )
    # Mantener float para compatibilidad con escrituras anteriores que usaban
    # float() en lugar de Decimal — sqlalchemy convierte ambos OK.
    obra.costo_real = float(nuevo)
    return nuevo


# ============================================================================
# Helpers para el frontend / reportes (opcional, no rompe nada en B.1)
# ============================================================================

def desglose_costo_real(obra_id: int) -> dict:
    """Devuelve el desglose detallado para mostrar en UI/reportes.

    En B.1 se puede usar para diagnosticar; en B.4 sera la base de los
    reportes de rentabilidad.
    """
    materiales = _calcular_costo_materiales(obra_id)
    mo = _calcular_costo_mano_obra_pagada(obra_id)
    caja_b = _calcular_caja_b_egresos_impacta(obra_id)
    total = materiales + mo + caja_b

    return {
        'componentes': {
            'materiales': float(materiales),
            'mano_obra_pagada': float(mo),
            'caja_b_egresos': float(caja_b),
        },
        'total': float(total.quantize(Decimal('0.01'))),
        'porcentajes': {
            'materiales': float(materiales / total * 100) if total > 0 else 0,
            'mano_obra_pagada': float(mo / total * 100) if total > 0 else 0,
            'caja_b_egresos': float(caja_b / total * 100) if total > 0 else 0,
        },
    }
