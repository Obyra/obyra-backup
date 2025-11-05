"""
Inventory Service - Gestión de inventario y stock
==================================================
Servicio para gestión completa de inventario, incluyendo:
- Gestión de items (crear, actualizar, rastreo de stock)
- Movimientos de stock (ingreso, egreso, transferencia, ajuste)
- Gestión de depósitos/almacenes
- Reservas de stock
- Seguimiento de uso por proyecto
- Alertas de stock bajo
- Soporte multi-depósito
"""

from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import func, and_, or_
from sqlalchemy.exc import SQLAlchemyError

from services.base import BaseService, ValidationException, NotFoundException, ServiceException
from extensions import db
from models import (
    InventoryItem, Stock, StockMovement, Warehouse, StockReservation,
    UsoInventario, InventoryCategory, Obra, Usuario
)


class InventoryService(BaseService[InventoryItem]):
    """
    Servicio para gestión de inventario y stock.

    Proporciona funcionalidad completa para:
    - Gestión de items de inventario
    - Movimientos de stock (ingreso, egreso, transferencia, ajuste)
    - Gestión de depósitos/almacenes
    - Reservas de stock para proyectos
    - Seguimiento de uso por proyecto
    - Alertas de stock bajo
    - Cálculo de valor de inventario
    - Reportes y consultas
    """

    model_class = InventoryItem

    # ===== ITEM MANAGEMENT =====

    def create_item(self, data: Dict[str, Any]) -> InventoryItem:
        """
        Crea un nuevo item de inventario.

        Args:
            data: Diccionario con los datos del item. Campos requeridos:
                - sku: Código único del item
                - nombre: Nombre del item
                - categoria_id: ID de la categoría
                - unidad: Unidad de medida (kg, m, u, m2, m3, etc.)
                - company_id: ID de la organización
                Campos opcionales: descripcion, min_stock, package_options, activo

        Returns:
            InventoryItem: Instancia del item creado

        Raises:
            ValidationException: Si faltan campos requeridos o datos inválidos
        """
        # Validar campos requeridos
        required_fields = ['sku', 'nombre', 'categoria_id', 'unidad', 'company_id']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise ValidationException(
                f"Campos requeridos faltantes: {', '.join(missing_fields)}",
                details={'missing_fields': missing_fields}
            )

        # Validar SKU único
        existing_sku = InventoryItem.query.filter_by(sku=data['sku']).first()
        if existing_sku:
            raise ValidationException(
                f"El SKU '{data['sku']}' ya existe",
                details={'field': 'sku', 'value': data['sku']}
            )

        # Validar categoría existe
        categoria = InventoryCategory.query.get(data['categoria_id'])
        if not categoria:
            raise NotFoundException('InventoryCategory', data['categoria_id'])

        # Validar min_stock
        if 'min_stock' in data and data['min_stock'] is not None:
            try:
                data['min_stock'] = Decimal(str(data['min_stock']))
                if data['min_stock'] < 0:
                    raise ValidationException("El stock mínimo no puede ser negativo")
            except (ValueError, TypeError):
                raise ValidationException("Stock mínimo inválido")

        # Establecer valores por defecto
        data.setdefault('activo', True)
        data.setdefault('min_stock', Decimal('0'))

        try:
            item = self.create(**data)
            self._log_info(f"Item de inventario creado: {item.sku} - {item.nombre} (ID: {item.id})")
            return item
        except Exception as e:
            self._log_error(f"Error al crear item de inventario: {str(e)}")
            raise

    def update_item(self, item_id: int, data: Dict[str, Any]) -> InventoryItem:
        """
        Actualiza un item de inventario existente.

        Args:
            item_id: ID del item a actualizar
            data: Diccionario con los campos a actualizar

        Returns:
            InventoryItem: Instancia del item actualizado

        Raises:
            NotFoundException: Si el item no existe
            ValidationException: Si los datos son inválidos
        """
        item = self.get_by_id_or_fail(item_id)

        # Si se actualiza SKU, validar que sea único
        if 'sku' in data and data['sku'] != item.sku:
            existing_sku = InventoryItem.query.filter_by(sku=data['sku']).first()
            if existing_sku:
                raise ValidationException(
                    f"El SKU '{data['sku']}' ya existe",
                    details={'field': 'sku', 'value': data['sku']}
                )

        # Validar categoría si se actualiza
        if 'categoria_id' in data:
            categoria = InventoryCategory.query.get(data['categoria_id'])
            if not categoria:
                raise NotFoundException('InventoryCategory', data['categoria_id'])

        # Validar min_stock si se actualiza
        if 'min_stock' in data and data['min_stock'] is not None:
            try:
                data['min_stock'] = Decimal(str(data['min_stock']))
                if data['min_stock'] < 0:
                    raise ValidationException("El stock mínimo no puede ser negativo")
            except (ValueError, TypeError):
                raise ValidationException("Stock mínimo inválido")

        try:
            updated_item = self.update(item_id, **data)
            self._log_info(f"Item de inventario actualizado: {updated_item.sku} (ID: {item_id})")
            return updated_item
        except Exception as e:
            self._log_error(f"Error al actualizar item de inventario: {str(e)}")
            raise

    def get_item_stock(self, item_id: int, warehouse_id: Optional[int] = None) -> Decimal:
        """
        Obtiene el stock actual de un item.

        Args:
            item_id: ID del item
            warehouse_id: ID del depósito (opcional). Si no se especifica, retorna stock total

        Returns:
            Decimal: Cantidad en stock

        Raises:
            NotFoundException: Si el item o depósito no existe
        """
        item = self.get_by_id_or_fail(item_id)

        if warehouse_id:
            stock = Stock.query.filter_by(item_id=item_id, warehouse_id=warehouse_id).first()
            return stock.cantidad if stock else Decimal('0')
        else:
            # Stock total en todos los depósitos
            return item.total_stock

    def get_available_stock(self, item_id: int, warehouse_id: Optional[int] = None) -> Decimal:
        """
        Obtiene el stock disponible de un item (descontando reservas).

        Args:
            item_id: ID del item
            warehouse_id: ID del depósito (opcional)

        Returns:
            Decimal: Cantidad disponible

        Raises:
            NotFoundException: Si el item no existe
        """
        item = self.get_by_id_or_fail(item_id)

        if warehouse_id:
            # Stock en el depósito específico
            stock = Stock.query.filter_by(item_id=item_id, warehouse_id=warehouse_id).first()
            stock_qty = stock.cantidad if stock else Decimal('0')

            # Reservas activas (sin filtrar por depósito, ya que las reservas son globales)
            reserved = db.session.query(func.sum(StockReservation.qty))\
                .filter_by(item_id=item_id, estado='activa')\
                .scalar() or Decimal('0')

            # Aproximación: restar proporcionalmente
            if item.total_stock > 0:
                proportion = stock_qty / item.total_stock
                reserved_in_warehouse = reserved * proportion
            else:
                reserved_in_warehouse = Decimal('0')

            return max(stock_qty - reserved_in_warehouse, Decimal('0'))
        else:
            # Stock disponible total
            return item.available_stock

    def needs_restock(self, item_id: int) -> bool:
        """
        Verifica si un item necesita reposición de stock.

        Args:
            item_id: ID del item

        Returns:
            bool: True si el stock está bajo el mínimo

        Raises:
            NotFoundException: Si el item no existe
        """
        item = self.get_by_id_or_fail(item_id)
        return item.is_low_stock

    # ===== STOCK MOVEMENTS =====

    def record_ingreso(
        self,
        item_id: int,
        warehouse_id: int,
        cantidad: Decimal,
        precio: Optional[Decimal] = None,
        proveedor: Optional[str] = None,
        notas: Optional[str] = None,
        user_id: int = None
    ) -> StockMovement:
        """
        Registra un ingreso de mercadería al stock.

        Args:
            item_id: ID del item
            warehouse_id: ID del depósito destino
            cantidad: Cantidad ingresada (debe ser positiva)
            precio: Precio unitario (opcional)
            proveedor: Nombre del proveedor (opcional)
            notas: Notas adicionales (opcional)
            user_id: ID del usuario que registra el movimiento

        Returns:
            StockMovement: Movimiento registrado

        Raises:
            ValidationException: Si la cantidad es inválida
            NotFoundException: Si el item o depósito no existe
        """
        # Validaciones
        item = self.get_by_id_or_fail(item_id)
        warehouse = Warehouse.query.get(warehouse_id)
        if not warehouse:
            raise NotFoundException('Warehouse', warehouse_id)

        try:
            cantidad = Decimal(str(cantidad))
            if cantidad <= 0:
                raise ValidationException("La cantidad debe ser positiva")
        except (ValueError, TypeError):
            raise ValidationException("Cantidad inválida")

        if precio is not None:
            try:
                precio = Decimal(str(precio))
                if precio < 0:
                    raise ValidationException("El precio no puede ser negativo")
            except (ValueError, TypeError):
                raise ValidationException("Precio inválido")

        # Construir motivo
        motivo_parts = ["Ingreso de mercadería"]
        if proveedor:
            motivo_parts.append(f"Proveedor: {proveedor}")
        if precio:
            motivo_parts.append(f"Precio: ${precio}")
        if notas:
            motivo_parts.append(f"Notas: {notas}")
        motivo = " | ".join(motivo_parts)

        try:
            # Crear movimiento
            movimiento = StockMovement(
                item_id=item_id,
                tipo='ingreso',
                qty=cantidad,
                destino_warehouse_id=warehouse_id,
                motivo=motivo,
                user_id=user_id,
                fecha=datetime.utcnow()
            )
            db.session.add(movimiento)

            # Actualizar stock
            self._update_stock(item_id, warehouse_id, cantidad)

            db.session.commit()
            self._log_info(f"Ingreso registrado: {cantidad} {item.unidad} de {item.nombre} en {warehouse.nombre}")
            return movimiento

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al registrar ingreso: {str(e)}")
            raise ServiceException(f"Error al registrar ingreso: {str(e)}")

    def record_egreso(
        self,
        item_id: int,
        warehouse_id: int,
        cantidad: Decimal,
        obra_id: Optional[int] = None,
        notas: Optional[str] = None,
        user_id: int = None
    ) -> StockMovement:
        """
        Registra un egreso de mercadería del stock.

        Args:
            item_id: ID del item
            warehouse_id: ID del depósito origen
            cantidad: Cantidad egresada (debe ser positiva)
            obra_id: ID de la obra destino (opcional)
            notas: Notas adicionales (opcional)
            user_id: ID del usuario que registra el movimiento

        Returns:
            StockMovement: Movimiento registrado

        Raises:
            ValidationException: Si la cantidad es inválida o supera el stock disponible
            NotFoundException: Si el item, depósito u obra no existe
        """
        # Validaciones
        item = self.get_by_id_or_fail(item_id)
        warehouse = Warehouse.query.get(warehouse_id)
        if not warehouse:
            raise NotFoundException('Warehouse', warehouse_id)

        if obra_id:
            obra = Obra.query.get(obra_id)
            if not obra:
                raise NotFoundException('Obra', obra_id)

        try:
            cantidad = Decimal(str(cantidad))
            if cantidad <= 0:
                raise ValidationException("La cantidad debe ser positiva")
        except (ValueError, TypeError):
            raise ValidationException("Cantidad inválida")

        # Verificar stock disponible
        stock_disponible = self.get_available_stock(item_id, warehouse_id)
        if cantidad > stock_disponible:
            raise ValidationException(
                f"Stock insuficiente. Disponible: {stock_disponible} {item.unidad}, solicitado: {cantidad} {item.unidad}",
                details={'disponible': float(stock_disponible), 'solicitado': float(cantidad)}
            )

        # Construir motivo
        motivo_parts = ["Egreso de mercadería"]
        if obra_id:
            motivo_parts.append(f"Obra: {obra.nombre}")
        if notas:
            motivo_parts.append(f"Notas: {notas}")
        motivo = " | ".join(motivo_parts)

        try:
            # Crear movimiento
            movimiento = StockMovement(
                item_id=item_id,
                tipo='egreso',
                qty=cantidad,
                origen_warehouse_id=warehouse_id,
                project_id=obra_id,
                motivo=motivo,
                user_id=user_id,
                fecha=datetime.utcnow()
            )
            db.session.add(movimiento)

            # Actualizar stock
            self._update_stock(item_id, warehouse_id, -cantidad)

            db.session.commit()
            self._log_info(f"Egreso registrado: {cantidad} {item.unidad} de {item.nombre} desde {warehouse.nombre}")
            return movimiento

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al registrar egreso: {str(e)}")
            raise ServiceException(f"Error al registrar egreso: {str(e)}")

    def record_transferencia(
        self,
        item_id: int,
        from_warehouse: int,
        to_warehouse: int,
        cantidad: Decimal,
        notas: Optional[str] = None,
        user_id: int = None
    ) -> StockMovement:
        """
        Registra una transferencia de mercadería entre depósitos.

        Args:
            item_id: ID del item
            from_warehouse: ID del depósito origen
            to_warehouse: ID del depósito destino
            cantidad: Cantidad transferida (debe ser positiva)
            notas: Notas adicionales (opcional)
            user_id: ID del usuario que registra el movimiento

        Returns:
            StockMovement: Movimiento registrado

        Raises:
            ValidationException: Si la cantidad es inválida, los depósitos son iguales,
                               o no hay stock suficiente
            NotFoundException: Si el item o depósitos no existen
        """
        # Validaciones
        item = self.get_by_id_or_fail(item_id)

        origen = Warehouse.query.get(from_warehouse)
        if not origen:
            raise NotFoundException('Warehouse (origen)', from_warehouse)

        destino = Warehouse.query.get(to_warehouse)
        if not destino:
            raise NotFoundException('Warehouse (destino)', to_warehouse)

        if from_warehouse == to_warehouse:
            raise ValidationException("Los depósitos de origen y destino no pueden ser iguales")

        try:
            cantidad = Decimal(str(cantidad))
            if cantidad <= 0:
                raise ValidationException("La cantidad debe ser positiva")
        except (ValueError, TypeError):
            raise ValidationException("Cantidad inválida")

        # Verificar stock disponible en origen
        stock_origen = self.get_available_stock(item_id, from_warehouse)
        if cantidad > stock_origen:
            raise ValidationException(
                f"Stock insuficiente en {origen.nombre}. Disponible: {stock_origen} {item.unidad}",
                details={'disponible': float(stock_origen), 'solicitado': float(cantidad)}
            )

        # Construir motivo
        motivo = f"Transferencia de {origen.nombre} a {destino.nombre}"
        if notas:
            motivo += f" | Notas: {notas}"

        try:
            # Crear movimiento
            movimiento = StockMovement(
                item_id=item_id,
                tipo='transferencia',
                qty=cantidad,
                origen_warehouse_id=from_warehouse,
                destino_warehouse_id=to_warehouse,
                motivo=motivo,
                user_id=user_id,
                fecha=datetime.utcnow()
            )
            db.session.add(movimiento)

            # Actualizar stocks
            self._update_stock(item_id, from_warehouse, -cantidad)
            self._update_stock(item_id, to_warehouse, cantidad)

            db.session.commit()
            self._log_info(f"Transferencia registrada: {cantidad} {item.unidad} de {item.nombre} de {origen.nombre} a {destino.nombre}")
            return movimiento

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al registrar transferencia: {str(e)}")
            raise ServiceException(f"Error al registrar transferencia: {str(e)}")

    def record_ajuste(
        self,
        item_id: int,
        warehouse_id: int,
        cantidad: Decimal,
        reason: str,
        user_id: int = None
    ) -> StockMovement:
        """
        Registra un ajuste de stock (positivo o negativo).

        Args:
            item_id: ID del item
            warehouse_id: ID del depósito
            cantidad: Cantidad del ajuste (puede ser positiva o negativa)
            reason: Razón del ajuste (requerido)
            user_id: ID del usuario que registra el movimiento

        Returns:
            StockMovement: Movimiento registrado

        Raises:
            ValidationException: Si la cantidad o razón son inválidas,
                               o el ajuste negativo supera el stock
            NotFoundException: Si el item o depósito no existe
        """
        # Validaciones
        item = self.get_by_id_or_fail(item_id)
        warehouse = Warehouse.query.get(warehouse_id)
        if not warehouse:
            raise NotFoundException('Warehouse', warehouse_id)

        if not reason or not reason.strip():
            raise ValidationException("La razón del ajuste es requerida")

        try:
            cantidad = Decimal(str(cantidad))
            if cantidad == 0:
                raise ValidationException("La cantidad de ajuste no puede ser cero")
        except (ValueError, TypeError):
            raise ValidationException("Cantidad inválida")

        # Si es ajuste negativo, verificar stock
        if cantidad < 0:
            stock_actual = self.get_item_stock(item_id, warehouse_id)
            if abs(cantidad) > stock_actual:
                raise ValidationException(
                    f"Ajuste negativo excede el stock actual. Stock: {stock_actual} {item.unidad}",
                    details={'stock_actual': float(stock_actual), 'ajuste': float(cantidad)}
                )

        motivo = f"Ajuste de inventario: {reason}"

        try:
            # Crear movimiento
            movimiento = StockMovement(
                item_id=item_id,
                tipo='ajuste',
                qty=abs(cantidad),  # Guardamos valor absoluto
                destino_warehouse_id=warehouse_id,  # Siempre en destino para ajustes
                motivo=motivo,
                user_id=user_id,
                fecha=datetime.utcnow()
            )
            db.session.add(movimiento)

            # Actualizar stock
            self._update_stock(item_id, warehouse_id, cantidad)

            db.session.commit()
            tipo_ajuste = "positivo" if cantidad > 0 else "negativo"
            self._log_info(f"Ajuste {tipo_ajuste} registrado: {cantidad} {item.unidad} de {item.nombre} en {warehouse.nombre}")
            return movimiento

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al registrar ajuste: {str(e)}")
            raise ServiceException(f"Error al registrar ajuste: {str(e)}")

    # ===== RESERVATIONS =====

    def reserve_stock(
        self,
        item_id: int,
        cantidad: Decimal,
        obra_id: int,
        user_id: int,
        warehouse_id: Optional[int] = None
    ) -> StockReservation:
        """
        Crea una reserva de stock para un proyecto.

        Args:
            item_id: ID del item
            cantidad: Cantidad a reservar (debe ser positiva)
            obra_id: ID de la obra
            user_id: ID del usuario que crea la reserva
            warehouse_id: ID del depósito (opcional, para validación)

        Returns:
            StockReservation: Reserva creada

        Raises:
            ValidationException: Si la cantidad es inválida o no hay stock disponible
            NotFoundException: Si el item u obra no existe
        """
        # Validaciones
        item = self.get_by_id_or_fail(item_id)
        obra = Obra.query.get(obra_id)
        if not obra:
            raise NotFoundException('Obra', obra_id)

        try:
            cantidad = Decimal(str(cantidad))
            if cantidad <= 0:
                raise ValidationException("La cantidad debe ser positiva")
        except (ValueError, TypeError):
            raise ValidationException("Cantidad inválida")

        # Verificar stock disponible
        stock_disponible = self.get_available_stock(item_id, warehouse_id)
        if cantidad > stock_disponible:
            raise ValidationException(
                f"Stock insuficiente para reserva. Disponible: {stock_disponible} {item.unidad}",
                details={'disponible': float(stock_disponible), 'solicitado': float(cantidad)}
            )

        try:
            reserva = StockReservation(
                item_id=item_id,
                project_id=obra_id,
                qty=cantidad,
                estado='activa',
                created_by=user_id,
                created_at=datetime.utcnow()
            )
            db.session.add(reserva)
            db.session.commit()

            self._log_info(f"Reserva creada: {cantidad} {item.unidad} de {item.nombre} para {obra.nombre}")
            return reserva

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al crear reserva: {str(e)}")
            raise ServiceException(f"Error al crear reserva: {str(e)}")

    def release_reservation(self, reservation_id: int) -> StockReservation:
        """
        Libera una reserva de stock.

        Args:
            reservation_id: ID de la reserva

        Returns:
            StockReservation: Reserva liberada

        Raises:
            NotFoundException: Si la reserva no existe
            ValidationException: Si la reserva no está activa
        """
        reserva = StockReservation.query.get(reservation_id)
        if not reserva:
            raise NotFoundException('StockReservation', reservation_id)

        if reserva.estado != 'activa':
            raise ValidationException(
                f"La reserva no está activa (estado: {reserva.estado})",
                details={'estado_actual': reserva.estado}
            )

        try:
            reserva.estado = 'liberada'
            reserva.updated_at = datetime.utcnow()
            db.session.commit()

            self._log_info(f"Reserva liberada: ID {reservation_id}")
            return reserva

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al liberar reserva: {str(e)}")
            raise ServiceException(f"Error al liberar reserva: {str(e)}")

    def confirm_reservation(self, reservation_id: int) -> StockReservation:
        """
        Confirma una reserva de stock (marca como consumida).

        Args:
            reservation_id: ID de la reserva

        Returns:
            StockReservation: Reserva confirmada

        Raises:
            NotFoundException: Si la reserva no existe
            ValidationException: Si la reserva no está activa
        """
        reserva = StockReservation.query.get(reservation_id)
        if not reserva:
            raise NotFoundException('StockReservation', reservation_id)

        if reserva.estado != 'activa':
            raise ValidationException(
                f"La reserva no está activa (estado: {reserva.estado})",
                details={'estado_actual': reserva.estado}
            )

        try:
            reserva.estado = 'consumida'
            reserva.updated_at = datetime.utcnow()
            db.session.commit()

            self._log_info(f"Reserva confirmada: ID {reservation_id}")
            return reserva

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al confirmar reserva: {str(e)}")
            raise ServiceException(f"Error al confirmar reserva: {str(e)}")

    # ===== USAGE TRACKING =====

    def record_usage(
        self,
        item_id: int,
        obra_id: int,
        cantidad: Decimal,
        user_id: int,
        observaciones: Optional[str] = None
    ) -> UsoInventario:
        """
        Registra el uso de inventario en un proyecto.

        Args:
            item_id: ID del item
            obra_id: ID de la obra
            cantidad: Cantidad usada (debe ser positiva)
            user_id: ID del usuario que registra el uso
            observaciones: Observaciones adicionales (opcional)

        Returns:
            UsoInventario: Registro de uso creado

        Raises:
            ValidationException: Si la cantidad es inválida
            NotFoundException: Si el item u obra no existe
        """
        # Validaciones
        item = self.get_by_id_or_fail(item_id)
        obra = Obra.query.get(obra_id)
        if not obra:
            raise NotFoundException('Obra', obra_id)

        try:
            cantidad = Decimal(str(cantidad))
            if cantidad <= 0:
                raise ValidationException("La cantidad debe ser positiva")
        except (ValueError, TypeError):
            raise ValidationException("Cantidad inválida")

        try:
            uso = UsoInventario(
                item_id=item_id,
                obra_id=obra_id,
                cantidad_usada=cantidad,
                fecha_uso=date.today(),
                observaciones=observaciones,
                usuario_id=user_id
            )
            db.session.add(uso)
            db.session.commit()

            self._log_info(f"Uso registrado: {cantidad} {item.unidad} de {item.nombre} en {obra.nombre}")
            return uso

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al registrar uso: {str(e)}")
            raise ServiceException(f"Error al registrar uso: {str(e)}")

    def get_usage_by_project(self, obra_id: int) -> List[Dict[str, Any]]:
        """
        Obtiene el resumen de uso de inventario por proyecto.

        Args:
            obra_id: ID de la obra

        Returns:
            List[Dict]: Lista con el resumen de uso por item

        Raises:
            NotFoundException: Si la obra no existe
        """
        obra = Obra.query.get(obra_id)
        if not obra:
            raise NotFoundException('Obra', obra_id)

        # Consulta agrupada por item
        resultados = db.session.query(
            UsoInventario.item_id,
            func.sum(UsoInventario.cantidad_usada).label('total_usado'),
            func.count(UsoInventario.id).label('num_registros'),
            func.max(UsoInventario.fecha_uso).label('ultima_fecha')
        ).filter_by(obra_id=obra_id)\
         .group_by(UsoInventario.item_id)\
         .all()

        # Formatear resultados
        resumen = []
        for row in resultados:
            item = InventoryItem.query.get(row.item_id) or ItemInventario.query.get(row.item_id)
            if item:
                resumen.append({
                    'item_id': row.item_id,
                    'item_nombre': item.nombre,
                    'item_codigo': getattr(item, 'sku', None) or getattr(item, 'codigo', None),
                    'unidad': item.unidad,
                    'total_usado': float(row.total_usado),
                    'num_registros': row.num_registros,
                    'ultima_fecha': row.ultima_fecha.isoformat() if row.ultima_fecha else None
                })

        return resumen

    def get_usage_by_item(
        self,
        item_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene el historial de uso de un item.

        Args:
            item_id: ID del item
            start_date: Fecha de inicio (opcional)
            end_date: Fecha de fin (opcional)

        Returns:
            List[Dict]: Lista con el historial de uso

        Raises:
            NotFoundException: Si el item no existe
        """
        item = self.get_by_id_or_fail(item_id)

        query = UsoInventario.query.filter_by(item_id=item_id)

        if start_date:
            query = query.filter(UsoInventario.fecha_uso >= start_date)
        if end_date:
            query = query.filter(UsoInventario.fecha_uso <= end_date)

        usos = query.order_by(UsoInventario.fecha_uso.desc()).all()

        historial = []
        for uso in usos:
            historial.append({
                'id': uso.id,
                'obra_id': uso.obra_id,
                'obra_nombre': uso.obra.nombre,
                'cantidad_usada': float(uso.cantidad_usada),
                'unidad': item.unidad,
                'fecha_uso': uso.fecha_uso.isoformat(),
                'observaciones': uso.observaciones,
                'usuario_id': uso.usuario_id,
                'usuario_nombre': uso.usuario.nombre if uso.usuario else None
            })

        return historial

    # ===== WAREHOUSE MANAGEMENT =====

    def create_warehouse(self, data: Dict[str, Any]) -> Warehouse:
        """
        Crea un nuevo depósito/almacén.

        Args:
            data: Diccionario con los datos del depósito. Campos requeridos:
                - nombre: Nombre del depósito
                - company_id: ID de la organización
                Campos opcionales: direccion, tipo, activo

        Returns:
            Warehouse: Instancia del depósito creado

        Raises:
            ValidationException: Si faltan campos requeridos
        """
        # Validar campos requeridos
        required_fields = ['nombre', 'company_id']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise ValidationException(
                f"Campos requeridos faltantes: {', '.join(missing_fields)}",
                details={'missing_fields': missing_fields}
            )

        # Establecer valores por defecto
        data.setdefault('tipo', 'deposito')
        data.setdefault('activo', True)

        # Validar tipo
        if data['tipo'] not in ['deposito', 'obra']:
            raise ValidationException(
                "El tipo debe ser 'deposito' u 'obra'",
                details={'tipo_proporcionado': data['tipo']}
            )

        try:
            warehouse = Warehouse(**data)
            db.session.add(warehouse)
            db.session.commit()

            self._log_info(f"Depósito creado: {warehouse.nombre} (ID: {warehouse.id})")
            return warehouse

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al crear depósito: {str(e)}")
            raise ServiceException(f"Error al crear depósito: {str(e)}")

    def get_warehouse_stock(self, warehouse_id: int) -> List[Dict[str, Any]]:
        """
        Obtiene el inventario completo de un depósito.

        Args:
            warehouse_id: ID del depósito

        Returns:
            List[Dict]: Lista con el stock de cada item en el depósito

        Raises:
            NotFoundException: Si el depósito no existe
        """
        warehouse = Warehouse.query.get(warehouse_id)
        if not warehouse:
            raise NotFoundException('Warehouse', warehouse_id)

        stocks = Stock.query.filter_by(warehouse_id=warehouse_id)\
                            .filter(Stock.cantidad > 0)\
                            .all()

        inventario = []
        for stock in stocks:
            item = stock.item
            # Calcular reservas activas del item
            reserved = db.session.query(func.sum(StockReservation.qty))\
                .filter_by(item_id=item.id, estado='activa')\
                .scalar() or Decimal('0')

            inventario.append({
                'item_id': item.id,
                'sku': item.sku,
                'nombre': item.nombre,
                'categoria': item.categoria.nombre,
                'unidad': item.unidad,
                'stock_actual': float(stock.cantidad),
                'stock_reservado': float(reserved),
                'stock_disponible': float(stock.cantidad - reserved),
                'min_stock': float(item.min_stock),
                'necesita_reposicion': stock.cantidad <= item.min_stock,
                'ultima_actualizacion': stock.updated_at.isoformat() if stock.updated_at else None
            })

        return inventario

    def transfer_between_warehouses(
        self,
        item_id: int,
        from_id: int,
        to_id: int,
        cantidad: Decimal,
        user_id: int = None
    ) -> StockMovement:
        """
        Alias conveniente para transferir entre depósitos.

        Args:
            item_id: ID del item
            from_id: ID del depósito origen
            to_id: ID del depósito destino
            cantidad: Cantidad a transferir
            user_id: ID del usuario

        Returns:
            StockMovement: Movimiento registrado
        """
        return self.record_transferencia(item_id, from_id, to_id, cantidad, user_id=user_id)

    # ===== ALERTS AND REPORTS =====

    def get_low_stock_items(
        self,
        warehouse_id: Optional[int] = None,
        company_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene los items con stock bajo el mínimo.

        Args:
            warehouse_id: ID del depósito (opcional, para filtrar por depósito)
            company_id: ID de la organización (opcional)

        Returns:
            List[Dict]: Lista de items con stock bajo
        """
        query = db.session.query(
            InventoryItem.id,
            InventoryItem.sku,
            InventoryItem.nombre,
            InventoryItem.unidad,
            InventoryItem.min_stock,
            func.sum(Stock.cantidad).label('stock_total')
        ).join(Stock, Stock.item_id == InventoryItem.id)\
         .group_by(
             InventoryItem.id,
             InventoryItem.sku,
             InventoryItem.nombre,
             InventoryItem.unidad,
             InventoryItem.min_stock
         )\
         .having(func.sum(Stock.cantidad) <= InventoryItem.min_stock)

        if warehouse_id:
            query = query.filter(Stock.warehouse_id == warehouse_id)

        if company_id:
            query = query.filter(InventoryItem.company_id == company_id)

        resultados = query.all()

        items_bajos = []
        for row in resultados:
            items_bajos.append({
                'item_id': row.id,
                'sku': row.sku,
                'nombre': row.nombre,
                'unidad': row.unidad,
                'stock_actual': float(row.stock_total),
                'stock_minimo': float(row.min_stock),
                'diferencia': float(row.min_stock - row.stock_total),
                'porcentaje': float((row.stock_total / row.min_stock * 100) if row.min_stock > 0 else 0)
            })

        return items_bajos

    def get_stock_value(
        self,
        warehouse_id: Optional[int] = None,
        company_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Calcula el valor total del inventario basado en movimientos recientes.

        Args:
            warehouse_id: ID del depósito (opcional)
            company_id: ID de la organización (opcional)

        Returns:
            Dict: Información del valor del inventario
        """
        # Esta es una estimación basada en los últimos ingresos
        # En un sistema real, se debería mantener un precio promedio ponderado

        query = db.session.query(
            InventoryItem.id,
            InventoryItem.sku,
            InventoryItem.nombre,
            InventoryItem.unidad,
            Stock.warehouse_id,
            Stock.cantidad
        ).join(Stock, Stock.item_id == InventoryItem.id)\
         .filter(Stock.cantidad > 0)

        if warehouse_id:
            query = query.filter(Stock.warehouse_id == warehouse_id)

        if company_id:
            query = query.filter(InventoryItem.company_id == company_id)

        stocks = query.all()

        total_items = 0
        total_quantity = Decimal('0')
        estimated_value = Decimal('0')
        items_detail = []

        for stock in stocks:
            # Obtener el último precio de ingreso
            ultimo_ingreso = StockMovement.query\
                .filter_by(item_id=stock.id, tipo='ingreso')\
                .order_by(StockMovement.fecha.desc())\
                .first()

            # Extraer precio del motivo si existe (formato: "... | Precio: $XXX")
            precio_unitario = Decimal('0')
            if ultimo_ingreso and ultimo_ingreso.motivo:
                try:
                    if "Precio: $" in ultimo_ingreso.motivo:
                        precio_str = ultimo_ingreso.motivo.split("Precio: $")[1].split("|")[0].strip()
                        precio_unitario = Decimal(precio_str)
                except (IndexError, ValueError):
                    pass

            valor_item = stock.cantidad * precio_unitario

            total_items += 1
            total_quantity += stock.cantidad
            estimated_value += valor_item

            if precio_unitario > 0:
                items_detail.append({
                    'item_id': stock.id,
                    'sku': stock.sku,
                    'nombre': stock.nombre,
                    'cantidad': float(stock.cantidad),
                    'unidad': stock.unidad,
                    'precio_unitario': float(precio_unitario),
                    'valor_total': float(valor_item),
                    'warehouse_id': stock.warehouse_id
                })

        return {
            'total_items': total_items,
            'total_quantity': float(total_quantity),
            'estimated_value': float(estimated_value),
            'items_with_value': len(items_detail),
            'items_detail': sorted(items_detail, key=lambda x: x['valor_total'], reverse=True)[:20]  # Top 20
        }

    def get_movement_history(
        self,
        item_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        tipo: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Obtiene el historial de movimientos de un item.

        Args:
            item_id: ID del item
            start_date: Fecha de inicio (opcional)
            end_date: Fecha de fin (opcional)
            tipo: Tipo de movimiento para filtrar (opcional): ingreso, egreso, transferencia, ajuste
            limit: Número máximo de registros (default: 100)

        Returns:
            List[Dict]: Lista con el historial de movimientos

        Raises:
            NotFoundException: Si el item no existe
        """
        item = self.get_by_id_or_fail(item_id)

        query = StockMovement.query.filter_by(item_id=item_id)

        if start_date:
            query = query.filter(StockMovement.fecha >= start_date)
        if end_date:
            query = query.filter(StockMovement.fecha <= end_date)
        if tipo:
            if tipo not in ['ingreso', 'egreso', 'transferencia', 'ajuste']:
                raise ValidationException(f"Tipo de movimiento inválido: {tipo}")
            query = query.filter(StockMovement.tipo == tipo)

        movimientos = query.order_by(StockMovement.fecha.desc()).limit(limit).all()

        historial = []
        for mov in movimientos:
            historial.append({
                'id': mov.id,
                'tipo': mov.tipo,
                'cantidad': float(mov.qty),
                'unidad': item.unidad,
                'fecha': mov.fecha.isoformat(),
                'motivo': mov.motivo,
                'origen_warehouse_id': mov.origen_warehouse_id,
                'origen_warehouse': mov.origen_warehouse.nombre if mov.origen_warehouse else None,
                'destino_warehouse_id': mov.destino_warehouse_id,
                'destino_warehouse': mov.destino_warehouse.nombre if mov.destino_warehouse else None,
                'project_id': mov.project_id,
                'project_nombre': mov.project.nombre if mov.project else None,
                'user_id': mov.user_id,
                'user_nombre': mov.user.nombre if mov.user else None
            })

        return historial

    # ===== HELPER METHODS =====

    def _update_stock(self, item_id: int, warehouse_id: int, delta: Decimal):
        """
        Actualiza el stock de un item en un depósito.

        Args:
            item_id: ID del item
            warehouse_id: ID del depósito
            delta: Cambio en la cantidad (positivo o negativo)
        """
        stock = Stock.query.filter_by(item_id=item_id, warehouse_id=warehouse_id).first()

        if stock:
            stock.cantidad += delta
            stock.updated_at = datetime.utcnow()

            # Evitar cantidades negativas por errores de redondeo
            if stock.cantidad < 0:
                stock.cantidad = Decimal('0')
        else:
            # Crear nuevo registro de stock si no existe
            if delta > 0:
                stock = Stock(
                    item_id=item_id,
                    warehouse_id=warehouse_id,
                    cantidad=delta,
                    updated_at=datetime.utcnow()
                )
                db.session.add(stock)
            else:
                raise ServiceException(
                    f"No se puede crear stock con cantidad negativa en depósito {warehouse_id}"
                )

    def get_item_summary(self, item_id: int) -> Dict[str, Any]:
        """
        Obtiene un resumen completo de un item de inventario.

        Args:
            item_id: ID del item

        Returns:
            Dict: Resumen con stock, reservas, movimientos recientes, etc.

        Raises:
            NotFoundException: Si el item no existe
        """
        item = self.get_by_id_or_fail(item_id)

        # Stock por depósito
        stocks_por_deposito = []
        for stock in item.stocks:
            if stock.cantidad > 0:
                stocks_por_deposito.append({
                    'warehouse_id': stock.warehouse_id,
                    'warehouse_nombre': stock.warehouse.nombre,
                    'warehouse_tipo': stock.warehouse.tipo,
                    'cantidad': float(stock.cantidad),
                    'ultima_actualizacion': stock.updated_at.isoformat() if stock.updated_at else None
                })

        # Reservas activas
        reservas_activas = []
        for reserva in item.reservations:
            if reserva.estado == 'activa':
                reservas_activas.append({
                    'id': reserva.id,
                    'project_id': reserva.project_id,
                    'project_nombre': reserva.project.nombre,
                    'cantidad': float(reserva.qty),
                    'created_at': reserva.created_at.isoformat()
                })

        # Últimos movimientos
        ultimos_movimientos = self.get_movement_history(item_id, limit=10)

        return {
            'item': {
                'id': item.id,
                'sku': item.sku,
                'nombre': item.nombre,
                'categoria': item.categoria.nombre,
                'unidad': item.unidad,
                'min_stock': float(item.min_stock),
                'activo': item.activo
            },
            'stock': {
                'total': float(item.total_stock),
                'reservado': float(item.reserved_stock),
                'disponible': float(item.available_stock),
                'necesita_reposicion': item.is_low_stock,
                'por_deposito': stocks_por_deposito
            },
            'reservas_activas': reservas_activas,
            'ultimos_movimientos': ultimos_movimientos
        }
