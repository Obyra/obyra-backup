"""
Marketplace Service - Gestión de marketplace y comercio
========================================================
Este servicio encapsula toda la lógica de negocio relacionada con el marketplace,
incluyendo gestión de carrito, órdenes, pagos, comisiones y payout a proveedores.

Funcionalidades principales:
- Gestión de carrito de compras (add, update, remove, clear)
- Creación y procesamiento de órdenes
- Tracking de pagos y reembolsos
- Cálculo de comisiones por venta
- Gestión de payouts a proveedores
- Búsqueda y navegación de productos
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from decimal import Decimal
import os

from sqlalchemy import and_, or_, func, desc
from sqlalchemy.exc import SQLAlchemyError

from services.base import BaseService, ValidationException, NotFoundException, ServiceException
from models import (
    Cart, CartItem, Order, OrderItem, OrderCommission,
    Product, ProductVariant, Category, Supplier, SupplierPayout,
    Organizacion, Usuario
)
from extensions import db


class MarketplaceService(BaseService[Order]):
    """
    Servicio para gestión del marketplace.

    Proporciona métodos para:
    - Gestión de carrito de compras
    - Creación y seguimiento de órdenes
    - Procesamiento de pagos
    - Cálculo de comisiones
    - Gestión de pagos a proveedores
    - Búsqueda y navegación de productos
    """

    model_class = Order

    # ============================================================
    # CART MANAGEMENT
    # ============================================================

    def get_or_create_cart(
        self,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> Cart:
        """
        Obtiene o crea un carrito para un usuario o sesión anónima.

        Args:
            user_id: ID del usuario logueado (opcional)
            session_id: ID de sesión para usuarios anónimos (opcional)

        Returns:
            Carrito existente o nuevo

        Raises:
            ValidationException: Si no se proporciona ni user_id ni session_id
        """
        if not user_id and not session_id:
            raise ValidationException(
                "Se requiere user_id o session_id para identificar el carrito"
            )

        # Buscar carrito existente
        query = Cart.query

        if user_id:
            cart = query.filter_by(user_id=user_id).first()
        else:
            cart = query.filter_by(session_id=session_id).first()

        if cart:
            # Actualizar timestamp
            cart.updated_at = datetime.utcnow()
            db.session.commit()
            self._log_debug(f"Carrito existente recuperado: {cart.id}")
            return cart

        # Crear nuevo carrito
        try:
            cart = Cart(
                user_id=user_id,
                session_id=session_id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.session.add(cart)
            db.session.commit()

            self._log_info(
                f"Nuevo carrito creado: {cart.id} "
                f"(user: {user_id}, session: {session_id})"
            )
            return cart

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al crear carrito: {str(e)}")
            raise ServiceException(f"Error al crear carrito: {str(e)}")

    def add_to_cart(
        self,
        cart_id: int,
        product_variant_id: int,
        cantidad: Decimal
    ) -> CartItem:
        """
        Agrega un producto al carrito o actualiza la cantidad si ya existe.

        Args:
            cart_id: ID del carrito
            product_variant_id: ID de la variante del producto
            cantidad: Cantidad a agregar

        Returns:
            CartItem creado o actualizado

        Raises:
            NotFoundException: Si el carrito o variante no existen
            ValidationException: Si la cantidad es inválida o no hay stock
        """
        # Validar cantidad
        if cantidad <= 0:
            raise ValidationException("La cantidad debe ser mayor a 0")

        # Verificar que el carrito existe
        cart = Cart.query.get(cart_id)
        if not cart:
            raise NotFoundException('Cart', cart_id)

        # Verificar que la variante existe y está disponible
        variant = ProductVariant.query.get(product_variant_id)
        if not variant:
            raise NotFoundException('ProductVariant', product_variant_id)

        if not variant.is_available:
            raise ValidationException(
                f"El producto '{variant.display_name}' no está disponible"
            )

        # Verificar stock disponible
        if not self.check_product_availability(product_variant_id, cantidad):
            raise ValidationException(
                f"Stock insuficiente para '{variant.display_name}'. "
                f"Stock disponible: {variant.stock} {variant.unidad}"
            )

        try:
            # Buscar si ya existe en el carrito
            existing_item = CartItem.query.filter_by(
                cart_id=cart_id,
                product_variant_id=product_variant_id
            ).first()

            if existing_item:
                # Actualizar cantidad
                nueva_cantidad = existing_item.qty + cantidad

                # Verificar stock para la nueva cantidad
                if nueva_cantidad > variant.stock:
                    raise ValidationException(
                        f"Stock insuficiente. Cantidad en carrito: {existing_item.qty}, "
                        f"intentando agregar: {cantidad}, stock disponible: {variant.stock}"
                    )

                existing_item.qty = nueva_cantidad
                existing_item.precio_snapshot = variant.precio
                cart.updated_at = datetime.utcnow()

                db.session.commit()

                self._log_info(
                    f"Cantidad actualizada en carrito {cart_id}: "
                    f"variant {product_variant_id}, nueva cantidad: {nueva_cantidad}"
                )
                return existing_item

            else:
                # Crear nuevo item
                cart_item = CartItem(
                    cart_id=cart_id,
                    product_variant_id=product_variant_id,
                    supplier_id=variant.product.supplier_id,
                    qty=cantidad,
                    precio_snapshot=variant.precio,
                    added_at=datetime.utcnow()
                )
                db.session.add(cart_item)
                cart.updated_at = datetime.utcnow()

                db.session.commit()

                self._log_info(
                    f"Producto agregado al carrito {cart_id}: "
                    f"variant {product_variant_id}, cantidad: {cantidad}"
                )
                return cart_item

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al agregar al carrito: {str(e)}")
            raise ServiceException(f"Error al agregar al carrito: {str(e)}")

    def update_cart_item(
        self,
        cart_item_id: int,
        cantidad: Decimal
    ) -> CartItem:
        """
        Actualiza la cantidad de un item del carrito.

        Args:
            cart_item_id: ID del item del carrito
            cantidad: Nueva cantidad

        Returns:
            CartItem actualizado

        Raises:
            NotFoundException: Si el item no existe
            ValidationException: Si la cantidad es inválida
        """
        if cantidad <= 0:
            raise ValidationException("La cantidad debe ser mayor a 0")

        cart_item = CartItem.query.get(cart_item_id)
        if not cart_item:
            raise NotFoundException('CartItem', cart_item_id)

        # Verificar disponibilidad
        if not self.check_product_availability(cart_item.product_variant_id, cantidad):
            variant = cart_item.variant
            raise ValidationException(
                f"Stock insuficiente para '{variant.display_name}'. "
                f"Stock disponible: {variant.stock} {variant.unidad}"
            )

        try:
            cart_item.qty = cantidad
            cart_item.precio_snapshot = cart_item.variant.precio  # Actualizar precio
            cart_item.cart.updated_at = datetime.utcnow()

            db.session.commit()

            self._log_info(f"CartItem {cart_item_id} actualizado: nueva cantidad {cantidad}")
            return cart_item

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al actualizar item del carrito: {str(e)}")
            raise ServiceException(f"Error al actualizar item del carrito: {str(e)}")

    def remove_from_cart(self, cart_item_id: int) -> bool:
        """
        Elimina un item del carrito.

        Args:
            cart_item_id: ID del item del carrito

        Returns:
            True si se eliminó correctamente

        Raises:
            NotFoundException: Si el item no existe
        """
        cart_item = CartItem.query.get(cart_item_id)
        if not cart_item:
            raise NotFoundException('CartItem', cart_item_id)

        try:
            cart = cart_item.cart
            db.session.delete(cart_item)
            cart.updated_at = datetime.utcnow()

            db.session.commit()

            self._log_info(f"Item {cart_item_id} eliminado del carrito")
            return True

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al eliminar item del carrito: {str(e)}")
            raise ServiceException(f"Error al eliminar item del carrito: {str(e)}")

    def clear_cart(self, cart_id: int) -> bool:
        """
        Vacía completamente un carrito.

        Args:
            cart_id: ID del carrito

        Returns:
            True si se vació correctamente

        Raises:
            NotFoundException: Si el carrito no existe
        """
        cart = Cart.query.get(cart_id)
        if not cart:
            raise NotFoundException('Cart', cart_id)

        try:
            CartItem.query.filter_by(cart_id=cart_id).delete()
            cart.updated_at = datetime.utcnow()

            db.session.commit()

            self._log_info(f"Carrito {cart_id} vaciado")
            return True

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al vaciar carrito: {str(e)}")
            raise ServiceException(f"Error al vaciar carrito: {str(e)}")

    def get_cart_total(self, cart_id: int) -> Decimal:
        """
        Calcula el total del carrito.

        Args:
            cart_id: ID del carrito

        Returns:
            Total del carrito

        Raises:
            NotFoundException: Si el carrito no existe
        """
        cart = Cart.query.get(cart_id)
        if not cart:
            raise NotFoundException('Cart', cart_id)

        total = sum(item.subtotal for item in cart.items)
        return Decimal(str(total))

    # ============================================================
    # ORDER MANAGEMENT
    # ============================================================

    def create_order_from_cart(
        self,
        cart_id: int,
        user_id: int,
        shipping_data: Dict[str, Any]
    ) -> Order:
        """
        Crea una orden a partir del contenido del carrito.

        Args:
            cart_id: ID del carrito
            user_id: ID del usuario que realiza la compra
            shipping_data: Datos de envío (dirección, contacto, etc.)

        Returns:
            Orden creada

        Raises:
            NotFoundException: Si el carrito o usuario no existen
            ValidationException: Si el carrito está vacío o hay problemas de stock
        """
        # Verificar que el carrito existe y no está vacío
        cart = Cart.query.get(cart_id)
        if not cart:
            raise NotFoundException('Cart', cart_id)

        if not cart.items:
            raise ValidationException("El carrito está vacío")

        # Verificar que el usuario existe
        user = Usuario.query.get(user_id)
        if not user:
            raise NotFoundException('Usuario', user_id)

        # Obtener la organización del usuario
        company_id = user.organizacion_id or user.primary_org_id
        if not company_id:
            raise ValidationException(
                "El usuario debe estar asociado a una organización para realizar compras"
            )

        try:
            # Agrupar items por proveedor (una orden por proveedor)
            items_by_supplier = {}
            for item in cart.items:
                supplier_id = item.supplier_id
                if supplier_id not in items_by_supplier:
                    items_by_supplier[supplier_id] = []
                items_by_supplier[supplier_id].append(item)

            created_orders = []

            # Crear una orden por cada proveedor
            for supplier_id, items in items_by_supplier.items():
                # Verificar que el proveedor existe
                supplier = Supplier.query.get(supplier_id)
                if not supplier:
                    raise NotFoundException('Supplier', supplier_id)

                # Calcular total de esta orden
                order_total = sum(item.subtotal for item in items)

                # Crear orden
                order = Order(
                    company_id=company_id,
                    supplier_id=supplier_id,
                    total=Decimal(str(order_total)),
                    moneda='ARS',  # TODO: Hacer configurable
                    estado='pendiente',
                    payment_method=None,
                    payment_status='init',
                    created_at=datetime.utcnow()
                )
                db.session.add(order)
                db.session.flush()  # Para obtener el ID

                # Crear items de la orden
                for cart_item in items:
                    variant = cart_item.variant

                    # Verificar stock nuevamente
                    if not self.check_product_availability(
                        cart_item.product_variant_id,
                        cart_item.qty
                    ):
                        raise ValidationException(
                            f"Stock insuficiente para '{variant.display_name}'. "
                            f"Por favor revise su carrito."
                        )

                    order_item = OrderItem(
                        order_id=order.id,
                        product_variant_id=cart_item.product_variant_id,
                        qty=cart_item.qty,
                        precio_unit=cart_item.precio_snapshot,
                        subtotal=cart_item.subtotal
                    )
                    db.session.add(order_item)

                    # Decrementar stock (reserva temporal)
                    variant.stock -= cart_item.qty

                # Calcular y crear comisión
                commission_data = self.calculate_commission(order.id)
                order_commission = OrderCommission(
                    order_id=order.id,
                    base=commission_data['base'],
                    rate=commission_data['rate'],
                    monto=commission_data['monto'],
                    iva=commission_data['iva'],
                    total=commission_data['total'],
                    status='pendiente',
                    created_at=datetime.utcnow()
                )
                db.session.add(order_commission)

                created_orders.append(order)

                self._log_info(
                    f"Orden creada: {order.id} para supplier {supplier_id}, "
                    f"total: {order_total}"
                )

            # Vaciar el carrito
            CartItem.query.filter_by(cart_id=cart_id).delete()

            db.session.commit()

            self._log_info(
                f"{len(created_orders)} órdenes creadas desde carrito {cart_id}"
            )

            # Si hay una sola orden, retornarla. Si hay múltiples, retornar la primera
            # (en producción, podrías querer retornar todas)
            return created_orders[0] if created_orders else None

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al crear orden desde carrito: {str(e)}")
            raise ServiceException(f"Error al crear orden: {str(e)}")

    def update_order_status(
        self,
        order_id: int,
        new_status: str,
        user_id: int
    ) -> Order:
        """
        Actualiza el estado de una orden.

        Args:
            order_id: ID de la orden
            new_status: Nuevo estado (pendiente, pagado, entregado, cancelado)
            user_id: ID del usuario que realiza el cambio

        Returns:
            Orden actualizada

        Raises:
            NotFoundException: Si la orden no existe
            ValidationException: Si el estado es inválido
        """
        valid_statuses = ['pendiente', 'pagado', 'entregado', 'cancelado']
        if new_status not in valid_statuses:
            raise ValidationException(
                f"Estado inválido: {new_status}. "
                f"Debe ser uno de: {', '.join(valid_statuses)}"
            )

        order = Order.query.get(order_id)
        if not order:
            raise NotFoundException('Order', order_id)

        old_status = order.estado

        try:
            order.estado = new_status
            db.session.commit()

            self._log_info(
                f"Estado de orden {order_id} actualizado: "
                f"{old_status} -> {new_status} (por usuario {user_id})"
            )

            return order

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al actualizar estado de orden: {str(e)}")
            raise ServiceException(f"Error al actualizar estado de orden: {str(e)}")

    def cancel_order(
        self,
        order_id: int,
        user_id: int,
        reason: Optional[str] = None
    ) -> Order:
        """
        Cancela una orden y restaura el stock de los productos.

        Args:
            order_id: ID de la orden
            user_id: ID del usuario que cancela
            reason: Razón de la cancelación (opcional)

        Returns:
            Orden cancelada

        Raises:
            NotFoundException: Si la orden no existe
            ValidationException: Si la orden no puede ser cancelada
        """
        order = Order.query.get(order_id)
        if not order:
            raise NotFoundException('Order', order_id)

        # Validar que se puede cancelar
        if order.estado == 'cancelado':
            raise ValidationException("La orden ya está cancelada")

        if order.estado == 'entregado':
            raise ValidationException(
                "No se puede cancelar una orden ya entregada. "
                "Debe procesarse como devolución."
            )

        try:
            # Restaurar stock de los productos
            for item in order.items:
                variant = item.variant
                variant.stock += item.qty
                self._log_debug(
                    f"Stock restaurado para variant {variant.id}: +{item.qty}"
                )

            # Actualizar estado de la orden
            order.estado = 'cancelado'

            # Actualizar comisión si existe
            if order.commission:
                order.commission.status = 'anulado'

            db.session.commit()

            self._log_info(
                f"Orden {order_id} cancelada por usuario {user_id}. "
                f"Razón: {reason or 'No especificada'}"
            )

            return order

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al cancelar orden: {str(e)}")
            raise ServiceException(f"Error al cancelar orden: {str(e)}")

    def get_orders_by_user(
        self,
        user_id: int,
        status: Optional[str] = None
    ) -> List[Order]:
        """
        Obtiene las órdenes de un usuario/organización.

        Args:
            user_id: ID del usuario
            status: Filtrar por estado (opcional)

        Returns:
            Lista de órdenes

        Raises:
            NotFoundException: Si el usuario no existe
        """
        user = Usuario.query.get(user_id)
        if not user:
            raise NotFoundException('Usuario', user_id)

        company_id = user.organizacion_id or user.primary_org_id
        if not company_id:
            return []

        query = Order.query.filter_by(company_id=company_id)

        if status:
            query = query.filter_by(estado=status)

        return query.order_by(desc(Order.created_at)).all()

    def get_orders_by_supplier(
        self,
        supplier_id: int,
        status: Optional[str] = None
    ) -> List[Order]:
        """
        Obtiene las órdenes de un proveedor.

        Args:
            supplier_id: ID del proveedor
            status: Filtrar por estado (opcional)

        Returns:
            Lista de órdenes

        Raises:
            NotFoundException: Si el proveedor no existe
        """
        supplier = Supplier.query.get(supplier_id)
        if not supplier:
            raise NotFoundException('Supplier', supplier_id)

        query = Order.query.filter_by(supplier_id=supplier_id)

        if status:
            query = query.filter_by(estado=status)

        return query.order_by(desc(Order.created_at)).all()

    # ============================================================
    # PAYMENT TRACKING
    # ============================================================

    def record_payment(
        self,
        order_id: int,
        payment_data: Dict[str, Any]
    ) -> Order:
        """
        Registra información de pago para una orden.

        Args:
            order_id: ID de la orden
            payment_data: Datos del pago (method, ref, status, etc.)

        Returns:
            Orden actualizada

        Raises:
            NotFoundException: Si la orden no existe
        """
        order = Order.query.get(order_id)
        if not order:
            raise NotFoundException('Order', order_id)

        try:
            if 'method' in payment_data:
                order.payment_method = payment_data['method']

            if 'ref' in payment_data:
                order.payment_ref = payment_data['ref']

            if 'status' in payment_data:
                order.payment_status = payment_data['status']

            db.session.commit()

            self._log_info(
                f"Pago registrado para orden {order_id}: "
                f"método={payment_data.get('method')}, "
                f"ref={payment_data.get('ref')}"
            )

            return order

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al registrar pago: {str(e)}")
            raise ServiceException(f"Error al registrar pago: {str(e)}")

    def confirm_payment(
        self,
        order_id: int,
        payment_id: str
    ) -> Order:
        """
        Confirma el pago de una orden.

        Args:
            order_id: ID de la orden
            payment_id: ID del pago confirmado

        Returns:
            Orden actualizada

        Raises:
            NotFoundException: Si la orden no existe
        """
        order = Order.query.get(order_id)
        if not order:
            raise NotFoundException('Order', order_id)

        try:
            order.payment_status = 'approved'
            order.payment_ref = payment_id
            order.estado = 'pagado'

            # Actualizar comisión
            if order.commission:
                order.commission.status = 'pendiente'

            db.session.commit()

            self._log_info(f"Pago confirmado para orden {order_id}: {payment_id}")

            return order

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al confirmar pago: {str(e)}")
            raise ServiceException(f"Error al confirmar pago: {str(e)}")

    def refund_payment(
        self,
        order_id: int,
        amount: Decimal,
        reason: str
    ) -> Order:
        """
        Procesa un reembolso para una orden.

        Args:
            order_id: ID de la orden
            amount: Monto a reembolsar
            reason: Razón del reembolso

        Returns:
            Orden actualizada

        Raises:
            NotFoundException: Si la orden no existe
            ValidationException: Si el monto es inválido
        """
        order = Order.query.get(order_id)
        if not order:
            raise NotFoundException('Order', order_id)

        if amount <= 0 or amount > order.total:
            raise ValidationException(
                f"El monto a reembolsar debe estar entre 0 y {order.total}"
            )

        try:
            order.payment_status = 'refunded'
            order.estado = 'cancelado'

            # Actualizar comisión
            if order.commission:
                order.commission.status = 'anulado'

            # Restaurar stock
            for item in order.items:
                variant = item.variant
                variant.stock += item.qty

            db.session.commit()

            self._log_info(
                f"Reembolso procesado para orden {order_id}: "
                f"monto={amount}, razón={reason}"
            )

            return order

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al procesar reembolso: {str(e)}")
            raise ServiceException(f"Error al procesar reembolso: {str(e)}")

    # ============================================================
    # COMMISSION CALCULATIONS
    # ============================================================

    def calculate_commission(self, order_id: int) -> Dict[str, Decimal]:
        """
        Calcula la comisión para una orden.

        Args:
            order_id: ID de la orden (puede ser temporal)

        Returns:
            Dict con: base, rate, monto, iva, total
        """
        # Obtener orden si existe
        order = Order.query.get(order_id)
        if order:
            base = order.total
        else:
            # Si no existe la orden, debe ser un cálculo previo
            raise NotFoundException('Order', order_id)

        # Obtener tasa de comisión de variable de entorno o usar default
        rate = Decimal(os.environ.get('PLATFORM_COMMISSION_RATE', '0.02'))

        # Calcular comisión
        monto = base * rate
        monto = monto.quantize(Decimal('0.01'))

        # Calcular IVA (21% sobre la comisión)
        iva_rate = Decimal('0.21')
        iva = monto * iva_rate
        iva = iva.quantize(Decimal('0.01'))

        total = monto + iva

        return {
            'base': base,
            'rate': rate,
            'monto': monto,
            'iva': iva,
            'total': total
        }

    def record_commission(
        self,
        order_id: int,
        commission_data: Dict[str, Any]
    ) -> OrderCommission:
        """
        Registra manualmente una comisión para una orden.

        Args:
            order_id: ID de la orden
            commission_data: Datos de la comisión

        Returns:
            Comisión creada o actualizada

        Raises:
            NotFoundException: Si la orden no existe
        """
        order = Order.query.get(order_id)
        if not order:
            raise NotFoundException('Order', order_id)

        try:
            # Verificar si ya existe comisión
            commission = order.commission

            if commission:
                # Actualizar existente
                commission.base = commission_data.get('base', commission.base)
                commission.rate = commission_data.get('rate', commission.rate)
                commission.monto = commission_data.get('monto', commission.monto)
                commission.iva = commission_data.get('iva', commission.iva)
                commission.total = commission_data.get('total', commission.total)
                commission.status = commission_data.get('status', commission.status)
            else:
                # Crear nueva
                commission = OrderCommission(
                    order_id=order_id,
                    base=commission_data['base'],
                    rate=commission_data.get('rate', Decimal('0.02')),
                    monto=commission_data['monto'],
                    iva=commission_data.get('iva', Decimal('0')),
                    total=commission_data['total'],
                    status=commission_data.get('status', 'pendiente'),
                    created_at=datetime.utcnow()
                )
                db.session.add(commission)

            db.session.commit()

            self._log_info(
                f"Comisión registrada para orden {order_id}: "
                f"monto={commission.monto}, total={commission.total}"
            )

            return commission

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al registrar comisión: {str(e)}")
            raise ServiceException(f"Error al registrar comisión: {str(e)}")

    def get_commission_summary(
        self,
        supplier_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Obtiene resumen de comisiones para un proveedor en un período.

        Args:
            supplier_id: ID del proveedor
            start_date: Fecha de inicio
            end_date: Fecha de fin

        Returns:
            Dict con resumen de comisiones

        Raises:
            NotFoundException: Si el proveedor no existe
        """
        supplier = Supplier.query.get(supplier_id)
        if not supplier:
            raise NotFoundException('Supplier', supplier_id)

        # Obtener órdenes del período
        orders = Order.query.filter(
            and_(
                Order.supplier_id == supplier_id,
                Order.created_at >= start_date,
                Order.created_at <= end_date,
                Order.payment_status == 'approved'
            )
        ).all()

        # Calcular totales
        total_sales = sum(order.total for order in orders)
        total_commissions = sum(
            order.commission.total
            for order in orders
            if order.commission
        )

        commissions_by_status = {}
        for order in orders:
            if order.commission:
                status = order.commission.status
                if status not in commissions_by_status:
                    commissions_by_status[status] = Decimal('0')
                commissions_by_status[status] += order.commission.total

        return {
            'supplier_id': supplier_id,
            'period_start': start_date,
            'period_end': end_date,
            'total_orders': len(orders),
            'total_sales': total_sales,
            'total_commissions': total_commissions,
            'commissions_by_status': commissions_by_status,
            'net_amount': total_sales - total_commissions
        }

    # ============================================================
    # SUPPLIER PAYOUTS
    # ============================================================

    def calculate_payout(
        self,
        supplier_id: int,
        period_start: datetime,
        period_end: datetime
    ) -> Decimal:
        """
        Calcula el monto a pagar a un proveedor en un período.

        Args:
            supplier_id: ID del proveedor
            period_start: Fecha de inicio del período
            period_end: Fecha de fin del período

        Returns:
            Monto a pagar (ventas - comisiones)

        Raises:
            NotFoundException: Si el proveedor no existe
        """
        summary = self.get_commission_summary(supplier_id, period_start, period_end)
        return summary['net_amount']

    def create_payout(
        self,
        supplier_id: int,
        amount: Decimal,
        period_start: datetime,
        period_end: datetime
    ) -> SupplierPayout:
        """
        Crea un registro de payout para un proveedor.

        Args:
            supplier_id: ID del proveedor
            amount: Monto del payout
            period_start: Inicio del período
            period_end: Fin del período

        Returns:
            Payout creado

        Raises:
            NotFoundException: Si el proveedor no existe
            ValidationException: Si el monto es inválido
        """
        supplier = Supplier.query.get(supplier_id)
        if not supplier:
            raise NotFoundException('Supplier', supplier_id)

        if amount <= 0:
            raise ValidationException("El monto del payout debe ser mayor a 0")

        try:
            # Obtener saldo actual del proveedor
            ultimo_payout = SupplierPayout.query.filter_by(
                supplier_id=supplier_id
            ).order_by(desc(SupplierPayout.created_at)).first()

            saldo_anterior = ultimo_payout.saldo_resultante if ultimo_payout else Decimal('0')
            saldo_nuevo = saldo_anterior + amount

            nota = (
                f"Pago por ventas del período "
                f"{period_start.strftime('%d/%m/%Y')} - {period_end.strftime('%d/%m/%Y')}"
            )

            payout = SupplierPayout(
                supplier_id=supplier_id,
                order_id=None,
                tipo='ingreso',
                monto=amount,
                moneda='ARS',
                saldo_resultante=saldo_nuevo,
                nota=nota,
                created_at=datetime.utcnow()
            )
            db.session.add(payout)
            db.session.commit()

            self._log_info(
                f"Payout creado para supplier {supplier_id}: "
                f"monto={amount}, saldo={saldo_nuevo}"
            )

            return payout

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al crear payout: {str(e)}")
            raise ServiceException(f"Error al crear payout: {str(e)}")

    def process_payout(self, payout_id: int) -> SupplierPayout:
        """
        Procesa un payout pendiente (marca como pagado).

        Args:
            payout_id: ID del payout

        Returns:
            Payout procesado

        Raises:
            NotFoundException: Si el payout no existe
        """
        payout = SupplierPayout.query.get(payout_id)
        if not payout:
            raise NotFoundException('SupplierPayout', payout_id)

        try:
            # En este modelo no hay campo de estado, pero podríamos agregar nota
            payout.nota = (payout.nota or '') + f" [Procesado: {datetime.utcnow()}]"

            db.session.commit()

            self._log_info(f"Payout {payout_id} procesado")

            return payout

        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al procesar payout: {str(e)}")
            raise ServiceException(f"Error al procesar payout: {str(e)}")

    def get_pending_payouts(
        self,
        supplier_id: Optional[int] = None
    ) -> List[SupplierPayout]:
        """
        Obtiene payouts pendientes.

        Args:
            supplier_id: Filtrar por proveedor (opcional)

        Returns:
            Lista de payouts pendientes
        """
        query = SupplierPayout.query.filter_by(tipo='ingreso')

        if supplier_id:
            query = query.filter_by(supplier_id=supplier_id)

        # Filtrar los que no tienen marca de procesado en la nota
        payouts = query.order_by(desc(SupplierPayout.created_at)).all()
        pending = [p for p in payouts if 'Procesado:' not in (p.nota or '')]

        return pending

    # ============================================================
    # PRODUCT BROWSING
    # ============================================================

    def search_products(
        self,
        query: Optional[str] = None,
        category_id: Optional[int] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        limit: int = 50
    ) -> List[Product]:
        """
        Busca productos con filtros opcionales.

        Args:
            query: Texto de búsqueda (nombre, descripción)
            category_id: Filtrar por categoría
            min_price: Precio mínimo
            max_price: Precio máximo
            limit: Máximo de resultados

        Returns:
            Lista de productos que coinciden
        """
        search_query = Product.query.filter_by(estado='publicado')

        # Filtro de texto
        if query:
            search_pattern = f"%{query}%"
            search_query = search_query.filter(
                or_(
                    Product.nombre.ilike(search_pattern),
                    Product.descripcion.ilike(search_pattern)
                )
            )

        # Filtro de categoría
        if category_id:
            search_query = search_query.filter_by(category_id=category_id)

        # Filtros de precio (basados en las variantes)
        if min_price is not None or max_price is not None:
            search_query = search_query.join(ProductVariant)

            if min_price is not None:
                search_query = search_query.filter(ProductVariant.precio >= min_price)

            if max_price is not None:
                search_query = search_query.filter(ProductVariant.precio <= max_price)

        # Ordenar por más visitados
        search_query = search_query.order_by(desc(Product.visitas))

        return search_query.limit(limit).all()

    def get_product_with_variants(self, product_id: int) -> Product:
        """
        Obtiene un producto con todas sus variantes e imágenes.

        Args:
            product_id: ID del producto

        Returns:
            Producto con variantes cargadas

        Raises:
            NotFoundException: Si el producto no existe
        """
        product = Product.query.get(product_id)
        if not product:
            raise NotFoundException('Product', product_id)

        # Incrementar contador de visitas
        product.increment_visits()

        # Las relaciones se cargan automáticamente vía lazy loading
        return product

    def check_product_availability(
        self,
        product_variant_id: int,
        cantidad: Decimal
    ) -> bool:
        """
        Verifica si hay stock disponible para una variante.

        Args:
            product_variant_id: ID de la variante
            cantidad: Cantidad requerida

        Returns:
            True si hay stock suficiente
        """
        variant = ProductVariant.query.get(product_variant_id)
        if not variant:
            return False

        if not variant.is_available:
            return False

        return variant.stock >= cantidad
