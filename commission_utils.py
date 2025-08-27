"""
Utilidades para el cálculo de comisiones del Portal de Proveedores
"""

from decimal import Decimal
import os


def compute_commission(base: Decimal, rate: Decimal = None, iva_rate: Decimal = Decimal('0.21'), iva_included=False):
    """
    Calcula la comisión del portal de proveedores
    
    Args:
        base: Monto base sobre el cual calcular la comisión
        rate: Tasa de comisión (default: 2% desde variable de entorno)
        iva_rate: Tasa de IVA (default: 21%)
        iva_included: Si la tarifa incluye IVA o no
    
    Returns:
        tuple: (monto_comision, iva, total)
    """
    if rate is None:
        rate = Decimal(os.environ.get('PLATFORM_COMMISSION_RATE', '0.02'))
    
    # Calcular comisión base
    monto = (base * rate).quantize(Decimal('0.01'))
    
    if iva_included:
        # Si la tarifa es "IVA incluido", desglosar
        total = monto
        iva = (total - total / (Decimal('1.0') + iva_rate)).quantize(Decimal('0.01'))
        monto = (total - iva).quantize(Decimal('0.01'))
    else:
        # IVA adicional sobre la comisión
        iva = (monto * iva_rate).quantize(Decimal('0.01'))
        total = (monto + iva).quantize(Decimal('0.01'))
    
    return monto, iva, total


def format_currency(amount: Decimal, currency='ARS', include_symbol=True):
    """
    Formatea un monto como moneda
    
    Args:
        amount: Monto a formatear
        currency: Código de moneda
        include_symbol: Si incluir el símbolo de moneda
    
    Returns:
        str: Monto formateado
    """
    if currency == 'ARS':
        symbol = '$' if include_symbol else ''
        return f"{symbol}{amount:,.2f}".replace(',', '.')
    else:
        symbol = f"{currency} " if include_symbol else ''
        return f"{symbol}{amount:,.2f}"


def calculate_net_amount(total: Decimal, commission_rate: Decimal = None):
    """
    Calcula el monto neto que recibe el proveedor después de descontar la comisión
    
    Args:
        total: Monto total de la venta
        commission_rate: Tasa de comisión (default: desde variable de entorno)
    
    Returns:
        tuple: (monto_neto, comision_total)
    """
    if commission_rate is None:
        commission_rate = Decimal(os.environ.get('PLATFORM_COMMISSION_RATE', '0.02'))
    
    monto_comision, iva_comision, total_comision = compute_commission(total, commission_rate)
    monto_neto = total - total_comision
    
    return monto_neto, total_comision


def get_commission_summary(order_total: Decimal, commission_rate: Decimal = None):
    """
    Obtiene un resumen completo de la comisión para una orden
    
    Args:
        order_total: Total de la orden
        commission_rate: Tasa de comisión
    
    Returns:
        dict: Resumen detallado de la comisión
    """
    if commission_rate is None:
        commission_rate = Decimal(os.environ.get('PLATFORM_COMMISSION_RATE', '0.02'))
    
    monto_comision, iva_comision, total_comision = compute_commission(order_total, commission_rate)
    monto_neto, _ = calculate_net_amount(order_total, commission_rate)
    
    return {
        'order_total': order_total,
        'commission_rate': commission_rate,
        'commission_base': monto_comision,
        'commission_iva': iva_comision,
        'commission_total': total_comision,
        'net_amount': monto_neto,
        'commission_percentage': float(commission_rate * 100),
        'formatted': {
            'order_total': format_currency(order_total),
            'commission_base': format_currency(monto_comision),
            'commission_iva': format_currency(iva_comision),
            'commission_total': format_currency(total_comision),
            'net_amount': format_currency(monto_neto)
        }
    }


# Constantes para estados de comisión
COMMISSION_STATUS = {
    'PENDING': 'pendiente',
    'INVOICED': 'facturado',
    'PAID': 'cobrado',
    'CANCELLED': 'anulado'
}

# Constantes para métodos de pago
PAYMENT_METHODS = {
    'ONLINE': 'online',      # Mercado Pago con split
    'OFFLINE': 'offline'     # Pago manual del proveedor
}

# Constantes para estados de pago
PAYMENT_STATUS = {
    'INIT': 'init',
    'APPROVED': 'approved',
    'REJECTED': 'rejected',
    'REFUNDED': 'refunded'
}