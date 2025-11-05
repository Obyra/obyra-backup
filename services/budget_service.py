"""
Budget Service - Gestión de presupuestos y cotizaciones
========================================================

Este servicio gestiona toda la lógica de negocio relacionada con presupuestos:
- Creación y actualización de presupuestos
- Cálculo de totales por tipo (materiales, mano de obra, equipos)
- Gestión de vigencia y extensión de plazos
- Gestión de ítems del presupuesto
- Registro y consulta de tipos de cambio
- Cálculos para presupuestador wizard

Extrae lógica de negocio de los modelos Presupuesto e ItemPresupuesto,
siguiendo el patrón service layer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, List, Optional, Any, Tuple

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import (
    Presupuesto,
    ItemPresupuesto,
    ExchangeRate,
    WizardStageVariant,
    WizardStageCoefficient,
)
from services.base import BaseService, ValidationException, NotFoundException
from services.wizard_budgeting import (
    calculate_budget_breakdown,
    get_stage_variant_payload,
)


class BudgetService(BaseService[Presupuesto]):
    """
    Servicio para gestión de presupuestos y cotizaciones.

    Proporciona funcionalidad completa para:
    - CRUD de presupuestos
    - Cálculo de totales y subtotales
    - Gestión de vigencia
    - Ítems del presupuesto
    - Tipos de cambio
    - Presupuestador wizard
    """

    model_class = Presupuesto

    # ===== Budget Management =====

    def create_budget(self, data: Dict[str, Any]) -> Presupuesto:
        """
        Crea un nuevo presupuesto con validaciones.

        Args:
            data: Diccionario con los datos del presupuesto.
                  Campos requeridos: organizacion_id, numero
                  Campos opcionales: obra_id, estado, currency, vigencia_dias, etc.

        Returns:
            Presupuesto creado

        Raises:
            ValidationException: Si faltan campos requeridos o datos inválidos
        """
        # Validaciones
        if not data.get('organizacion_id'):
            raise ValidationException("organizacion_id es requerido")

        if not data.get('numero'):
            raise ValidationException("numero de presupuesto es requerido")

        # Verificar que el número no esté duplicado
        existing = Presupuesto.query.filter_by(numero=data['numero']).first()
        if existing:
            raise ValidationException(
                f"Ya existe un presupuesto con el número {data['numero']}",
                details={'numero': data['numero']}
            )

        # Valores por defecto
        data.setdefault('fecha', date.today())
        data.setdefault('estado', 'borrador')
        data.setdefault('currency', 'ARS')
        data.setdefault('iva_porcentaje', Decimal('21'))
        data.setdefault('vigencia_dias', 30)
        data.setdefault('vigencia_bloqueada', True)

        try:
            presupuesto = self.create(**data)
            self._log_info(f"Presupuesto creado: {presupuesto.numero}")
            return presupuesto
        except SQLAlchemyError as e:
            self._log_error(f"Error creando presupuesto: {str(e)}")
            raise

    def calculate_totals(self, budget_id: int) -> Dict[str, Decimal]:
        """
        Calcula los totales del presupuesto basándose en sus ítems.

        Extrae la lógica de Presupuesto.calcular_totales() del modelo.
        Calcula subtotales por tipo (materiales, mano de obra, equipos),
        total sin IVA y total con IVA.

        Args:
            budget_id: ID del presupuesto

        Returns:
            Dict con los totales calculados:
            {
                'subtotal_materiales': Decimal,
                'subtotal_mano_obra': Decimal,
                'subtotal_equipos': Decimal,
                'total_sin_iva': Decimal,
                'total_con_iva': Decimal
            }

        Raises:
            NotFoundException: Si el presupuesto no existe
        """
        presupuesto = self.get_by_id_or_fail(budget_id)

        items = presupuesto.items.all() if hasattr(presupuesto.items, 'all') else list(presupuesto.items)
        cero = Decimal('0')

        def _as_decimal(value):
            """Convierte un valor a Decimal de forma segura."""
            if isinstance(value, Decimal):
                return value
            if value is None:
                return Decimal('0')
            try:
                return Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError):
                return Decimal('0')

        def _item_total(item):
            """Obtiene el total de un ítem, priorizando total_currency."""
            valor = getattr(item, 'total_currency', None)
            if valor is not None:
                return _as_decimal(valor)
            return _as_decimal(getattr(item, 'total', None))

        # Calcular subtotales por tipo
        subtotal_materiales = sum(
            (_item_total(item) for item in items if item.tipo == 'material'),
            cero
        )
        subtotal_mano_obra = sum(
            (_item_total(item) for item in items if item.tipo == 'mano_obra'),
            cero
        )
        subtotal_equipos = sum(
            (_item_total(item) for item in items if item.tipo == 'equipo'),
            cero
        )

        # Redondear subtotales
        subtotal_materiales = subtotal_materiales.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        subtotal_mano_obra = subtotal_mano_obra.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        subtotal_equipos = subtotal_equipos.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Calcular total sin IVA
        total_sin_iva = (subtotal_materiales + subtotal_mano_obra + subtotal_equipos).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # Calcular total con IVA
        iva = Decimal(presupuesto.iva_porcentaje or 0)
        factor_iva = Decimal('1') + (iva / Decimal('100'))
        total_con_iva = (total_sin_iva * factor_iva).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Actualizar el presupuesto
        presupuesto.subtotal_materiales = subtotal_materiales
        presupuesto.subtotal_mano_obra = subtotal_mano_obra
        presupuesto.subtotal_equipos = subtotal_equipos
        presupuesto.total_sin_iva = total_sin_iva
        presupuesto.total_con_iva = total_con_iva

        # Asegurar vigencia
        self.ensure_validity(budget_id)

        # Guardar cambios
        self.commit()

        return {
            'subtotal_materiales': subtotal_materiales,
            'subtotal_mano_obra': subtotal_mano_obra,
            'subtotal_equipos': subtotal_equipos,
            'total_sin_iva': total_sin_iva,
            'total_con_iva': total_con_iva,
        }

    def ensure_validity(
        self,
        budget_id: int,
        fecha_base: Optional[date] = None
    ) -> date:
        """
        Asegura que el presupuesto tenga fecha de vigencia válida.

        Extrae la lógica de Presupuesto.asegurar_vigencia() del modelo.
        Calcula y actualiza la fecha de vigencia basándose en vigencia_dias.

        Args:
            budget_id: ID del presupuesto
            fecha_base: Fecha base para el cálculo (opcional, por defecto usa la fecha del presupuesto)

        Returns:
            Fecha de vigencia calculada

        Raises:
            NotFoundException: Si el presupuesto no existe
        """
        presupuesto = self.get_by_id_or_fail(budget_id)

        # Normalizar vigencia_dias (entre 1 y 180 días)
        dias = presupuesto.vigencia_dias if presupuesto.vigencia_dias and presupuesto.vigencia_dias > 0 else 30
        if dias < 1:
            dias = 1
        elif dias > 180:
            dias = 180

        if presupuesto.vigencia_dias != dias:
            presupuesto.vigencia_dias = dias

        # Determinar fecha base
        if fecha_base is None:
            if presupuesto.fecha:
                fecha_base = presupuesto.fecha
            elif presupuesto.fecha_creacion:
                fecha_base = presupuesto.fecha_creacion.date()
            else:
                fecha_base = date.today()

        # Calcular y actualizar fecha de vigencia
        nueva_vigencia = fecha_base + timedelta(days=dias)

        if not presupuesto.fecha_vigencia or presupuesto.fecha_vigencia != nueva_vigencia:
            presupuesto.fecha_vigencia = nueva_vigencia
            self._log_debug(
                f"Vigencia actualizada para presupuesto {presupuesto.numero}: "
                f"{nueva_vigencia} ({dias} días desde {fecha_base})"
            )

        return presupuesto.fecha_vigencia

    def extend_validity(self, budget_id: int, days: int) -> date:
        """
        Extiende la vigencia de un presupuesto.

        Args:
            budget_id: ID del presupuesto
            days: Días adicionales de vigencia (puede ser negativo para reducir)

        Returns:
            Nueva fecha de vigencia

        Raises:
            NotFoundException: Si el presupuesto no existe
            ValidationException: Si la vigencia está bloqueada o días inválido
        """
        presupuesto = self.get_by_id_or_fail(budget_id)

        if presupuesto.vigencia_bloqueada:
            raise ValidationException(
                "No se puede modificar la vigencia de un presupuesto bloqueado",
                details={'budget_id': budget_id}
            )

        if not isinstance(days, int):
            raise ValidationException("days debe ser un número entero")

        # Actualizar vigencia_dias
        nueva_vigencia_dias = (presupuesto.vigencia_dias or 30) + days

        # Validar límites
        if nueva_vigencia_dias < 1:
            nueva_vigencia_dias = 1
        elif nueva_vigencia_dias > 180:
            nueva_vigencia_dias = 180

        presupuesto.vigencia_dias = nueva_vigencia_dias

        # Recalcular fecha de vigencia
        nueva_fecha = self.ensure_validity(budget_id)

        self.commit()

        self._log_info(
            f"Vigencia extendida para presupuesto {presupuesto.numero}: "
            f"+{days} días -> {nueva_vigencia_dias} días totales, vence {nueva_fecha}"
        )

        return nueva_fecha

    # ===== Item Management =====

    def add_item(self, budget_id: int, item_data: Dict[str, Any]) -> ItemPresupuesto:
        """
        Agrega un ítem al presupuesto.

        Args:
            budget_id: ID del presupuesto
            item_data: Datos del ítem (tipo, descripcion, unidad, cantidad, precio_unitario, etc.)

        Returns:
            ItemPresupuesto creado

        Raises:
            NotFoundException: Si el presupuesto no existe
            ValidationException: Si faltan campos requeridos
        """
        presupuesto = self.get_by_id_or_fail(budget_id)

        # Validaciones
        required_fields = ['tipo', 'descripcion', 'unidad', 'cantidad', 'precio_unitario']
        missing = [f for f in required_fields if not item_data.get(f)]
        if missing:
            raise ValidationException(
                f"Faltan campos requeridos: {', '.join(missing)}",
                details={'missing_fields': missing}
            )

        # Validar tipo
        valid_tipos = ['material', 'mano_obra', 'equipo']
        if item_data['tipo'] not in valid_tipos:
            raise ValidationException(
                f"Tipo inválido: {item_data['tipo']}. Debe ser uno de: {', '.join(valid_tipos)}",
                details={'tipo': item_data['tipo'], 'valid_tipos': valid_tipos}
            )

        # Calcular total
        try:
            cantidad = Decimal(str(item_data['cantidad']))
            precio_unitario = Decimal(str(item_data['precio_unitario']))
            total = (cantidad * precio_unitario).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError) as e:
            raise ValidationException(f"Error calculando total del ítem: {str(e)}")

        # Valores por defecto
        item_data.setdefault('origen', 'manual')
        item_data.setdefault('currency', presupuesto.currency or 'ARS')
        item_data['total'] = total
        item_data['presupuesto_id'] = budget_id

        # Crear ítem
        item = ItemPresupuesto(**item_data)
        db.session.add(item)

        try:
            self.commit()

            # Recalcular totales del presupuesto
            self.calculate_totals(budget_id)

            self._log_info(
                f"Ítem agregado a presupuesto {presupuesto.numero}: "
                f"{item.tipo} - {item.descripcion}"
            )

            return item
        except SQLAlchemyError as e:
            self.rollback()
            self._log_error(f"Error agregando ítem: {str(e)}")
            raise

    def update_item(self, item_id: int, data: Dict[str, Any]) -> ItemPresupuesto:
        """
        Actualiza un ítem del presupuesto.

        Args:
            item_id: ID del ítem
            data: Datos a actualizar

        Returns:
            ItemPresupuesto actualizado

        Raises:
            NotFoundException: Si el ítem no existe
        """
        item = ItemPresupuesto.query.get(item_id)
        if not item:
            raise NotFoundException('ItemPresupuesto', item_id)

        budget_id = item.presupuesto_id

        # Actualizar campos
        for key, value in data.items():
            if key != 'id' and key != 'presupuesto_id' and hasattr(item, key):
                setattr(item, key, value)

        # Recalcular total si cambió cantidad o precio
        if 'cantidad' in data or 'precio_unitario' in data:
            try:
                cantidad = Decimal(str(item.cantidad))
                precio_unitario = Decimal(str(item.precio_unitario))
                item.total = (cantidad * precio_unitario).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except (InvalidOperation, ValueError, TypeError) as e:
                raise ValidationException(f"Error calculando total del ítem: {str(e)}")

        try:
            self.commit()

            # Recalcular totales del presupuesto
            self.calculate_totals(budget_id)

            self._log_info(f"Ítem actualizado: {item.descripcion}")

            return item
        except SQLAlchemyError as e:
            self.rollback()
            self._log_error(f"Error actualizando ítem: {str(e)}")
            raise

    def remove_item(self, item_id: int) -> bool:
        """
        Elimina un ítem del presupuesto.

        Args:
            item_id: ID del ítem a eliminar

        Returns:
            True si se eliminó correctamente

        Raises:
            NotFoundException: Si el ítem no existe
        """
        item = ItemPresupuesto.query.get(item_id)
        if not item:
            raise NotFoundException('ItemPresupuesto', item_id)

        budget_id = item.presupuesto_id
        descripcion = item.descripcion

        try:
            db.session.delete(item)
            self.commit()

            # Recalcular totales del presupuesto
            self.calculate_totals(budget_id)

            self._log_info(f"Ítem eliminado: {descripcion}")

            return True
        except SQLAlchemyError as e:
            self.rollback()
            self._log_error(f"Error eliminando ítem: {str(e)}")
            raise

    # ===== Exchange Rate Management =====

    def register_exchange_rate(
        self,
        budget_id: int,
        rate_data: Optional[ExchangeRate] = None
    ) -> None:
        """
        Registra el tipo de cambio en el presupuesto.

        Extrae la lógica de Presupuesto.registrar_tipo_cambio() del modelo.
        Actualiza los metadatos de tipo de cambio del presupuesto.

        Args:
            budget_id: ID del presupuesto
            rate_data: ExchangeRate snapshot o None para limpiar

        Raises:
            NotFoundException: Si el presupuesto no existe
        """
        presupuesto = self.get_by_id_or_fail(budget_id)

        if rate_data is None:
            # Limpiar datos de tipo de cambio
            presupuesto.exchange_rate_id = None
            presupuesto.exchange_rate_value = None
            presupuesto.exchange_rate_provider = None
            presupuesto.exchange_rate_fetched_at = None
            presupuesto.exchange_rate_as_of = None

            self._log_debug(f"Tipo de cambio limpiado para presupuesto {presupuesto.numero}")
        else:
            # Actualizar metadatos de tipo de cambio
            presupuesto.exchange_rate_id = rate_data.id
            presupuesto.exchange_rate_value = rate_data.value
            presupuesto.exchange_rate_provider = rate_data.provider
            presupuesto.exchange_rate_fetched_at = rate_data.fetched_at
            presupuesto.exchange_rate_as_of = rate_data.as_of_date

            # Si es ARS/USD, actualizar tasa_usd_venta
            if (rate_data.quote_currency.upper() == 'USD' and
                rate_data.base_currency.upper() == 'ARS'):
                presupuesto.tasa_usd_venta = rate_data.value

            self._log_info(
                f"Tipo de cambio registrado para presupuesto {presupuesto.numero}: "
                f"{rate_data.provider} {rate_data.base_currency}/{rate_data.quote_currency} "
                f"= {rate_data.value}"
            )

        self.commit()

    def get_current_rate(
        self,
        from_currency: str = 'ARS',
        to_currency: str = 'USD'
    ) -> Optional[Decimal]:
        """
        Obtiene el tipo de cambio más reciente para un par de monedas.

        Args:
            from_currency: Moneda base (default: ARS)
            to_currency: Moneda cotizada (default: USD)

        Returns:
            Valor del tipo de cambio o None si no existe
        """
        rate = (
            ExchangeRate.query
            .filter_by(
                base_currency=from_currency.upper(),
                quote_currency=to_currency.upper()
            )
            .order_by(ExchangeRate.as_of_date.desc(), ExchangeRate.fetched_at.desc())
            .first()
        )

        return rate.value if rate else None

    # ===== Wizard Budget Calculations =====

    def calculate_wizard_budget(
        self,
        tasks: List[Dict[str, Any]],
        variants: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Calcula el presupuesto del wizard basándose en tareas y variantes.

        Delega en el módulo wizard_budgeting para los cálculos complejos.

        Args:
            tasks: Lista de tareas con etapa_slug, cantidad, unidad, variant_key
            variants: Mapeo opcional de etapa_slug a variant_key

        Returns:
            Dict con stages, totals y metadata del presupuesto calculado
        """
        # Aplicar variantes si se especifican
        if variants:
            for task in tasks:
                etapa_slug = task.get('etapa_slug')
                if etapa_slug and etapa_slug in variants:
                    task.setdefault('variant_key', variants[etapa_slug])

        # Delegar al módulo wizard_budgeting
        result = calculate_budget_breakdown(tasks)

        self._log_debug(
            f"Presupuesto wizard calculado: {len(result.get('stages', []))} etapas, "
            f"total {result['totals']['total']} {result['totals']['currency']}"
        )

        return result

    def get_stage_variants(self, stage_slug: Optional[str] = None) -> Dict[str, Any]:
        """
        Obtiene las variantes disponibles para una o todas las etapas.

        Args:
            stage_slug: Slug de la etapa específica o None para todas

        Returns:
            Dict con variantes y coeficientes por etapa
        """
        payload = get_stage_variant_payload()

        if stage_slug:
            return {
                'variants': payload['variants'].get(stage_slug, []),
                'coefficients': payload['coefficients'].get(stage_slug, {}),
            }

        return payload

    def get_stage_coefficients(
        self,
        stage_slug: str,
        variant_key: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Obtiene los coeficientes de una etapa para una variante específica.

        Args:
            stage_slug: Slug de la etapa
            variant_key: Clave de la variante (opcional, usa baseline si es None)

        Returns:
            Dict con los coeficientes o None si no existe
        """
        query = WizardStageCoefficient.query.filter_by(stage_slug=stage_slug)

        if variant_key:
            # Buscar coeficiente para variante específica
            variant = WizardStageVariant.query.filter_by(
                stage_slug=stage_slug,
                variant_key=variant_key
            ).first()

            if variant:
                coeff = query.filter_by(variant_id=variant.id).first()
            else:
                coeff = None
        else:
            # Buscar baseline
            coeff = query.filter_by(is_baseline=True).first()

        if not coeff:
            return None

        return {
            'stage_slug': coeff.stage_slug,
            'variant_key': coeff.variant.variant_key if coeff.variant else 'baseline',
            'variant_name': coeff.variant.nombre if coeff.variant else 'Baseline',
            'unit': coeff.unit or 'u',
            'materials_per_unit': str(coeff.materials_per_unit or 0),
            'labor_per_unit': str(coeff.labor_per_unit or 0),
            'equipment_per_unit': str(coeff.equipment_per_unit or 0),
            'currency': (coeff.currency or 'ARS').upper(),
            'is_baseline': coeff.is_baseline,
            'source': coeff.source,
            'notes': coeff.notes,
        }
