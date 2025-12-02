"""
Budget Calculator - Cálculos Centralizados de Presupuestos
==========================================================

Este módulo centraliza TODA la lógica de cálculos de presupuestos:
- Subtotales por categoría (materiales, mano de obra, equipos)
- Total sin IVA
- Monto de IVA
- Total con IVA
- Conversión de monedas
- Cálculo de items individuales

Beneficios:
- Una sola fuente de verdad para todos los cálculos
- Constantes configurables (IVA, redondeo)
- Fácil de testear
- Elimina duplicación de código

Uso:
    from services.calculation import BudgetCalculator, BudgetConstants

    # Calcular monto de IVA
    monto_iva = BudgetCalculator.calcular_monto_iva(subtotal)

    # Calcular total con IVA
    total = BudgetCalculator.calcular_total_con_iva(subtotal)

    # Con tasa personalizada
    total = BudgetCalculator.calcular_total_con_iva(subtotal, iva_rate=Decimal('10.5'))
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from models import ItemPresupuesto


class BudgetConstants:
    """
    Constantes centralizadas para cálculos de presupuestos.

    Cambiar estos valores actualiza los cálculos en toda la aplicación.
    """

    # IVA por defecto en Argentina (21%)
    DEFAULT_IVA_RATE = Decimal('21')

    # Precisión de redondeo para moneda (2 decimales)
    CURRENCY_PRECISION = Decimal('0.01')

    # Precisión para cantidades (3 decimales)
    QUANTITY_PRECISION = Decimal('0.001')

    # Divisor para porcentajes
    PERCENTAGE_DIVISOR = Decimal('100')

    # Factor de desperdicio por defecto (10%)
    DEFAULT_WASTE_FACTOR = Decimal('1.10')

    # Tipos válidos de items
    VALID_ITEM_TYPES = ('material', 'mano_obra', 'equipo')


class BudgetCalculator:
    """
    Calculadora centralizada para presupuestos.

    Todos los métodos son estáticos para facilitar su uso sin instanciación.
    """

    @staticmethod
    def _to_decimal(value: Union[Decimal, float, int, str, None]) -> Decimal:
        """
        Convierte un valor a Decimal de forma segura.

        Args:
            value: Valor a convertir

        Returns:
            Decimal equivalente o Decimal('0') si no es convertible
        """
        if isinstance(value, Decimal):
            return value
        if value is None:
            return Decimal('0')
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal('0')

    @staticmethod
    def _round_currency(value: Decimal) -> Decimal:
        """
        Redondea un valor a precisión de moneda (2 decimales).

        Args:
            value: Valor a redondear

        Returns:
            Valor redondeado
        """
        return value.quantize(BudgetConstants.CURRENCY_PRECISION, rounding=ROUND_HALF_UP)

    @staticmethod
    def calcular_total_item(
        cantidad: Union[Decimal, float, int, str],
        precio_unitario: Union[Decimal, float, int, str]
    ) -> Decimal:
        """
        Calcula el total de un item individual.

        Args:
            cantidad: Cantidad del item
            precio_unitario: Precio por unidad

        Returns:
            Total calculado (cantidad × precio), redondeado a 2 decimales
        """
        cantidad_dec = BudgetCalculator._to_decimal(cantidad)
        precio_dec = BudgetCalculator._to_decimal(precio_unitario)

        total = cantidad_dec * precio_dec
        return BudgetCalculator._round_currency(total)

    @staticmethod
    def calcular_subtotales(
        items: List['ItemPresupuesto']
    ) -> Dict[str, Decimal]:
        """
        Calcula subtotales por categoría de items.

        Args:
            items: Lista de ItemPresupuesto

        Returns:
            Dict con subtotales:
            {
                'materiales': Decimal,
                'mano_obra': Decimal,
                'equipos': Decimal
            }
        """
        cero = Decimal('0')

        def _get_item_total(item) -> Decimal:
            """Obtiene el total del item, priorizando total_currency."""
            valor = getattr(item, 'total_currency', None)
            if valor is not None:
                return BudgetCalculator._to_decimal(valor)
            return BudgetCalculator._to_decimal(getattr(item, 'total', None))

        subtotal_materiales = sum(
            (_get_item_total(item) for item in items if item.tipo == 'material'),
            cero
        )
        subtotal_mano_obra = sum(
            (_get_item_total(item) for item in items if item.tipo == 'mano_obra'),
            cero
        )
        subtotal_equipos = sum(
            (_get_item_total(item) for item in items if item.tipo == 'equipo'),
            cero
        )

        return {
            'materiales': BudgetCalculator._round_currency(subtotal_materiales),
            'mano_obra': BudgetCalculator._round_currency(subtotal_mano_obra),
            'equipos': BudgetCalculator._round_currency(subtotal_equipos),
        }

    @staticmethod
    def calcular_total_sin_iva(
        subtotales: Optional[Dict[str, Decimal]] = None,
        *,
        materiales: Optional[Decimal] = None,
        mano_obra: Optional[Decimal] = None,
        equipos: Optional[Decimal] = None
    ) -> Decimal:
        """
        Calcula el total sin IVA sumando todos los subtotales.

        Puede recibir los subtotales como dict o como argumentos individuales.

        Args:
            subtotales: Dict con subtotales (de calcular_subtotales)
            materiales: Subtotal de materiales (alternativo)
            mano_obra: Subtotal de mano de obra (alternativo)
            equipos: Subtotal de equipos (alternativo)

        Returns:
            Total sin IVA
        """
        if subtotales is not None:
            mat = subtotales.get('materiales', Decimal('0'))
            mo = subtotales.get('mano_obra', Decimal('0'))
            eq = subtotales.get('equipos', Decimal('0'))
        else:
            mat = BudgetCalculator._to_decimal(materiales)
            mo = BudgetCalculator._to_decimal(mano_obra)
            eq = BudgetCalculator._to_decimal(equipos)

        total = mat + mo + eq
        return BudgetCalculator._round_currency(total)

    @staticmethod
    def calcular_monto_iva(
        total_sin_iva: Union[Decimal, float, int, str],
        iva_rate: Optional[Decimal] = None
    ) -> Decimal:
        """
        Calcula el monto de IVA.

        Args:
            total_sin_iva: Base imponible
            iva_rate: Tasa de IVA en porcentaje (default: 21%)

        Returns:
            Monto de IVA
        """
        base = BudgetCalculator._to_decimal(total_sin_iva)

        if iva_rate is None:
            iva_rate = BudgetConstants.DEFAULT_IVA_RATE
        else:
            iva_rate = BudgetCalculator._to_decimal(iva_rate)

        monto_iva = base * iva_rate / BudgetConstants.PERCENTAGE_DIVISOR
        return BudgetCalculator._round_currency(monto_iva)

    @staticmethod
    def calcular_total_con_iva(
        total_sin_iva: Union[Decimal, float, int, str],
        iva_rate: Optional[Decimal] = None
    ) -> Decimal:
        """
        Calcula el total con IVA incluido.

        Args:
            total_sin_iva: Base imponible
            iva_rate: Tasa de IVA en porcentaje (default: 21%)

        Returns:
            Total con IVA
        """
        base = BudgetCalculator._to_decimal(total_sin_iva)
        monto_iva = BudgetCalculator.calcular_monto_iva(base, iva_rate)

        return BudgetCalculator._round_currency(base + monto_iva)

    @staticmethod
    def calcular_factor_iva(iva_rate: Optional[Decimal] = None) -> Decimal:
        """
        Calcula el factor multiplicador de IVA (1 + tasa/100).

        Útil para: total_con_iva = total_sin_iva × factor_iva

        Args:
            iva_rate: Tasa de IVA en porcentaje (default: 21%)

        Returns:
            Factor multiplicador (ej: 1.21 para 21%)
        """
        if iva_rate is None:
            iva_rate = BudgetConstants.DEFAULT_IVA_RATE
        else:
            iva_rate = BudgetCalculator._to_decimal(iva_rate)

        return Decimal('1') + (iva_rate / BudgetConstants.PERCENTAGE_DIVISOR)

    @staticmethod
    def convertir_moneda(
        monto: Union[Decimal, float, int, str],
        tasa: Union[Decimal, float, int, str],
        inverso: bool = False
    ) -> Decimal:
        """
        Convierte un monto entre monedas usando una tasa de cambio.

        Args:
            monto: Monto a convertir
            tasa: Tasa de cambio (ej: ARS por USD)
            inverso: Si True, divide en vez de multiplicar

        Returns:
            Monto convertido

        Ejemplo:
            # USD → ARS (1 USD = 1200 ARS)
            ars = BudgetCalculator.convertir_moneda(100, 1200)  # 120000 ARS

            # ARS → USD
            usd = BudgetCalculator.convertir_moneda(120000, 1200, inverso=True)  # 100 USD
        """
        monto_dec = BudgetCalculator._to_decimal(monto)
        tasa_dec = BudgetCalculator._to_decimal(tasa)

        if tasa_dec == Decimal('0'):
            return Decimal('0')

        if inverso:
            resultado = monto_dec / tasa_dec
        else:
            resultado = monto_dec * tasa_dec

        return BudgetCalculator._round_currency(resultado)

    @staticmethod
    def calcular_totales_presupuesto(
        items: List['ItemPresupuesto'],
        iva_rate: Optional[Decimal] = None
    ) -> Dict[str, Decimal]:
        """
        Calcula todos los totales de un presupuesto de una sola vez.

        Método de conveniencia que combina:
        - calcular_subtotales
        - calcular_total_sin_iva
        - calcular_monto_iva
        - calcular_total_con_iva

        Args:
            items: Lista de ItemPresupuesto
            iva_rate: Tasa de IVA (default: 21%)

        Returns:
            Dict con todos los totales:
            {
                'subtotal_materiales': Decimal,
                'subtotal_mano_obra': Decimal,
                'subtotal_equipos': Decimal,
                'total_sin_iva': Decimal,
                'monto_iva': Decimal,
                'total_con_iva': Decimal,
                'iva_rate': Decimal
            }
        """
        if iva_rate is None:
            iva_rate = BudgetConstants.DEFAULT_IVA_RATE
        else:
            iva_rate = BudgetCalculator._to_decimal(iva_rate)

        # Calcular subtotales
        subtotales = BudgetCalculator.calcular_subtotales(items)

        # Calcular totales
        total_sin_iva = BudgetCalculator.calcular_total_sin_iva(subtotales)
        monto_iva = BudgetCalculator.calcular_monto_iva(total_sin_iva, iva_rate)
        total_con_iva = BudgetCalculator.calcular_total_con_iva(total_sin_iva, iva_rate)

        return {
            'subtotal_materiales': subtotales['materiales'],
            'subtotal_mano_obra': subtotales['mano_obra'],
            'subtotal_equipos': subtotales['equipos'],
            'total_sin_iva': total_sin_iva,
            'monto_iva': monto_iva,
            'total_con_iva': total_con_iva,
            'iva_rate': iva_rate,
        }

    @staticmethod
    def aplicar_desperdicio(
        cantidad: Union[Decimal, float, int, str],
        factor: Optional[Decimal] = None
    ) -> Decimal:
        """
        Aplica factor de desperdicio a una cantidad.

        Args:
            cantidad: Cantidad base
            factor: Factor de desperdicio (default: 1.10 = 10%)

        Returns:
            Cantidad ajustada con desperdicio
        """
        cantidad_dec = BudgetCalculator._to_decimal(cantidad)

        if factor is None:
            factor = BudgetConstants.DEFAULT_WASTE_FACTOR
        else:
            factor = BudgetCalculator._to_decimal(factor)

        resultado = cantidad_dec * factor
        return resultado.quantize(BudgetConstants.QUANTITY_PRECISION, rounding=ROUND_HALF_UP)

    @staticmethod
    def validar_tipo_item(tipo: str) -> bool:
        """
        Valida que el tipo de item sea válido.

        Args:
            tipo: Tipo a validar

        Returns:
            True si es válido, False si no
        """
        return tipo in BudgetConstants.VALID_ITEM_TYPES

    @staticmethod
    def validar_tasa_cambio(tasa: Union[Decimal, float, int, str, None]) -> bool:
        """
        Valida que una tasa de cambio sea válida (positiva y no cero).

        Args:
            tasa: Tasa de cambio a validar

        Returns:
            True si es válida, False si no
        """
        if tasa is None:
            return False
        tasa_dec = BudgetCalculator._to_decimal(tasa)
        return tasa_dec > Decimal('0')

    @staticmethod
    def calcular_item_con_conversion(
        cantidad: Union[Decimal, float, int, str],
        precio_unitario: Union[Decimal, float, int, str],
        currency: str,
        tasa_usd: Optional[Union[Decimal, float, int, str]] = None
    ) -> Dict[str, Decimal]:
        """
        Calcula totales de un item con conversión de moneda opcional.

        Args:
            cantidad: Cantidad del item
            precio_unitario: Precio por unidad
            currency: Moneda del precio ('ARS' o 'USD')
            tasa_usd: Tasa de cambio USD→ARS (opcional)

        Returns:
            Dict con:
            {
                'total': Decimal (en moneda original),
                'precio_unitario': Decimal,
                'price_unit_ars': Decimal (en ARS),
                'total_ars': Decimal (en ARS),
                'currency': str
            }
        """
        cantidad_dec = BudgetCalculator._to_decimal(cantidad)
        precio_dec = BudgetCalculator._to_decimal(precio_unitario)

        total = BudgetCalculator._round_currency(cantidad_dec * precio_dec)

        # Por defecto, ARS = original
        price_unit_ars = precio_dec
        total_ars = total

        # Convertir si es USD y hay tasa válida
        if currency == 'USD' and BudgetCalculator.validar_tasa_cambio(tasa_usd):
            tasa = BudgetCalculator._to_decimal(tasa_usd)
            price_unit_ars = BudgetCalculator.convertir_moneda(precio_dec, tasa)
            total_ars = BudgetCalculator.convertir_moneda(total, tasa)

        return {
            'total': total,
            'precio_unitario': BudgetCalculator._round_currency(precio_dec),
            'price_unit_ars': price_unit_ars,
            'total_ars': total_ars,
            'currency': currency.upper() if currency else 'ARS'
        }
