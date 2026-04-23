"""Precios comerciales oficiales de OBYRA.

Fuente única de verdad para precios visibles y cobro. Si cambia el precio,
se cambia acá y se propaga a todo el sistema, landing (hardcodeado aparte)
y logica de Mercado Pago.

Reglas vigentes (2026):
- Hay UN solo plan comercial: OBYRA Profesional.
- El plan mensual se cobra en ARS. Al crear la suscripción, se multiplica
  MONTHLY_PLAN_PRICE_USD por la cotización BNA del día y ese valor en ARS
  queda fijo para toda la vida de esa suscripción (snapshot). Si el dolar
  fluctua, las renovaciones del usuario ya activo NO cambian — MP Preapproval
  no permite cambios de monto sin re-autorización.
- La licencia 5 años se cobra offline (transferencia / WhatsApp). NO pasa
  por Mercado Pago.
- NO hay renovación anual obligatoria después del año 5: si el cliente quiere
  extender, se renegocia puntualmente.
"""

from decimal import Decimal


# Suscripción mensual — OBYRA Profesional
MONTHLY_PLAN_PRICE_USD = Decimal('300.00')

# Licencia 5 años — OBYRA Profesional, pago único
FIVE_YEAR_LICENSE_PRICE_USD = Decimal('11900.00')

# Cálculos derivados (para textos comerciales de ahorro)
# 5 años mensual = 300 × 60 = 18.000 USD
# Ahorro vs licencia = 18.000 - 11.900 = 6.100 USD (34%)
_MONTHLY_TOTAL_5_YEARS_USD = MONTHLY_PLAN_PRICE_USD * Decimal('60')
SAVING_VS_MONTHLY_USD = _MONTHLY_TOTAL_5_YEARS_USD - FIVE_YEAR_LICENSE_PRICE_USD  # 6100
SAVING_VS_MONTHLY_PCT = int(
    (SAVING_VS_MONTHLY_USD / _MONTHLY_TOTAL_5_YEARS_USD * Decimal('100')).quantize(Decimal('1'))
)  # 34
