# Guía de Servicios - OBYRA

## 📚 Índice

1. [Introducción](#introducción)
2. [Arquitectura](#arquitectura)
3. [Servicios Disponibles](#servicios-disponibles)
4. [Uso Básico](#uso-básico)
5. [Manejo de Errores](#manejo-de-errores)
6. [Mejores Prácticas](#mejores-prácticas)

---

## 🎯 Introducción

La capa de servicios de OBYRA encapsula toda la lógica de negocio del sistema, proporcionando una interfaz limpia y consistente para operaciones complejas. Los servicios separan la lógica de negocio de los modelos de datos y los controladores.

### Beneficios

- ✅ **Reutilización**: Lógica compartida entre diferentes partes del sistema
- ✅ **Testabilidad**: Fácil de testear sin dependencias de Flask
- ✅ **Mantenibilidad**: Código organizado y fácil de localizar
- ✅ **Consistencia**: Patrones uniformes en toda la aplicación
- ✅ **Transacciones**: Manejo automático de transacciones de base de datos

---

## 🏗️ Arquitectura

### Jerarquía de Clases

```
BaseService[T]
├── ReadOnlyService[T]
├── UserService
├── ProjectService
├── BudgetService
├── InventoryService
└── MarketplaceService
```

### BaseService

Todos los servicios heredan de `BaseService` que proporciona:

- **CRUD Operations**: `create()`, `update()`, `delete()`, `get_by_id()`
- **Queries**: `get_all()`, `exists()`, `count()`
- **Transactions**: `commit()`, `rollback()`, `flush()`
- **Logging**: `_log_info()`, `_log_error()`, `_log_warning()`, `_log_debug()`

### Excepciones

```python
ServiceException          # Base exception
├── ValidationException   # Errores de validación
├── NotFoundException     # Recurso no encontrado
└── PermissionDeniedException  # Sin permisos
```

---

## 🔧 Servicios Disponibles

### 1. UserService

**Responsabilidades:**
- Autenticación y registro
- Gestión de membresías organizacionales
- Permisos y roles (RBAC)
- Perfiles y facturación
- Onboarding

**Métodos principales:**
```python
# Autenticación
authenticate(email, password) -> Usuario
register(email, nombre, apellido, password, org_id) -> Usuario
register_oauth_user(...) -> Usuario

# Passwords
set_password(user_id, password)
check_password(user_id, password) -> bool
reset_password(user_id, new_password)

# Membresías
ensure_membership(user_id, org_id, role, status)
get_active_memberships(user_id) -> List[OrgMembership]
archive_membership(user_id, org_id)

# Permisos
has_role(user_id, role, org_id) -> bool
can_access_module(user_id, module) -> bool
can_edit_module(user_id, module) -> bool
is_admin(user_id) -> bool

# Perfiles
ensure_onboarding(user_id) -> OnboardingStatus
ensure_billing_profile(user_id) -> BillingProfile
complete_profile(user_id, cuit, direccion)
```

**Ejemplo de uso:**
```python
from services import UserService

user_service = UserService()

# Registrar usuario
user = user_service.register(
    email='juan@example.com',
    nombre='Juan',
    apellido='Pérez',
    password='secure123',
    organizacion_id=1
)

# Autenticar
authenticated_user = user_service.authenticate('juan@example.com', 'secure123')

# Verificar permisos
can_view_projects = user_service.can_access_module(user.id, 'obras')
can_edit_budgets = user_service.can_edit_module(user.id, 'presupuestos')
```

---

### 2. ProjectService

**Responsabilidades:**
- Gestión de proyectos/obras
- Etapas y tareas
- Seguimiento de progreso
- Cálculos EVM (Earned Value Management)
- Asignaciones de usuarios

**Métodos principales:**
```python
# Proyectos
create_project(data) -> Obra
update_project(project_id, data) -> Obra
calculate_progress(project_id, auto_update=False) -> dict
can_pause(project_id, user_id) -> bool
pause_project(project_id, user_id)
resume_project(project_id, user_id)

# Tareas
create_task(etapa_id, data) -> TareaEtapa
update_task(task_id, data) -> TareaEtapa
assign_task(task_id, user_id, cuota_objetivo=None)
get_task_summary(task_id) -> dict

# Progreso
record_progress(task_id, data) -> TareaAvance
approve_progress(avance_id, user_id)
reject_progress(avance_id, user_id, reason)

# EVM
calculate_evm_metrics(task_id, as_of_date=None) -> dict
get_project_metrics(project_id) -> dict

# Asignaciones
assign_user_to_project(project_id, user_id, role, etapa_id=None)
get_project_members(project_id, active_only=True)
```

**Ejemplo de uso:**
```python
from services import ProjectService
from datetime import date

project_service = ProjectService()

# Crear proyecto
project = project_service.create_project({
    'nombre': 'Edificio Residencial',
    'organizacion_id': 1,
    'fecha_inicio': date.today(),
    'presupuesto_total': 50000000,
    'superficie': 1200.5
})

# Calcular progreso automático
progress = project_service.calculate_progress(project.id, auto_update=True)
print(f"Progreso: {progress['percentage']}%")

# Crear tarea
task = project_service.create_task(etapa_id=5, data={
    'nombre': 'Excavación de cimientos',
    'descripcion': 'Excavación hasta 2m de profundidad',
    'cantidad_objetivo': 50,
    'unidad': 'm3'
})

# Registrar avance
avance = project_service.record_progress(task.id, {
    'cantidad': 15,
    'descripcion': 'Avance día 1',
    'usuario_id': 1
})

# Aprobar avance
project_service.approve_progress(avance.id, user_id=2)
```

---

### 3. BudgetService

**Responsabilidades:**
- Gestión de presupuestos
- Cálculo de totales
- Gestión de ítems
- Tipos de cambio
- Validez de presupuestos
- Wizard de presupuesto

**Métodos principales:**
```python
# Presupuestos
create_budget(data) -> Presupuesto
calculate_totals(budget_id) -> dict
ensure_validity(budget_id, fecha_base=None) -> date
extend_validity(budget_id, days) -> date

# Ítems
add_item(budget_id, item_data) -> ItemPresupuesto
update_item(item_id, data) -> ItemPresupuesto
remove_item(item_id) -> bool

# Tipos de cambio
register_exchange_rate(budget_id, rate_data)
get_current_rate(from_currency='ARS', to_currency='USD') -> Decimal

# Wizard
calculate_wizard_budget(tasks, variants=None) -> dict
get_stage_variants(stage_slug=None) -> dict
get_stage_coefficients(stage_slug, variant_key=None) -> dict
```

**Ejemplo de uso:**
```python
from services import BudgetService
from decimal import Decimal

budget_service = BudgetService()

# Crear presupuesto
budget = budget_service.create_budget({
    'organizacion_id': 1,
    'numero': 'PRES-2025-001',
    'nombre': 'Presupuesto Edificio Central',
    'currency': 'ARS',
    'vigencia_dias': 45
})

# Agregar ítems
budget_service.add_item(budget.id, {
    'tipo': 'material',
    'descripcion': 'Cemento Portland x 50kg',
    'unidad': 'bolsa',
    'cantidad': 100,
    'precio_unitario': Decimal('5500.00')
})

budget_service.add_item(budget.id, {
    'tipo': 'mano_obra',
    'descripcion': 'Albañil oficial',
    'unidad': 'jornal',
    'cantidad': 20,
    'precio_unitario': Decimal('8500.00')
})

# Calcular totales
totals = budget_service.calculate_totals(budget.id)
print(f"Subtotal: ${totals['subtotal_sin_iva']}")
print(f"Total con IVA: ${totals['total_con_iva']}")

# Extender vigencia
new_date = budget_service.extend_validity(budget.id, days=15)
print(f"Nueva fecha de vencimiento: {new_date}")
```

---

### 4. InventoryService

**Responsabilidades:**
- Gestión de ítems de inventario
- Movimientos de stock (ingreso, egreso, transferencia, ajuste)
- Gestión de depósitos/almacenes
- Reservas de stock para proyectos
- Alertas de stock bajo
- Valorización de inventario

**Métodos principales:**
```python
# Ítems
create_item(data) -> InventoryItem
update_item(item_id, data) -> InventoryItem
get_item_stock(item_id, warehouse_id=None) -> Decimal
get_available_stock(item_id, warehouse_id=None) -> Decimal
needs_restock(item_id) -> bool

# Movimientos
record_ingreso(item_id, warehouse_id, cantidad, precio, proveedor, user_id)
record_egreso(item_id, warehouse_id, cantidad, obra_id, user_id, notas=None)
record_transferencia(item_id, from_warehouse, to_warehouse, cantidad, user_id)
record_ajuste(item_id, warehouse_id, cantidad, reason, user_id)

# Reservas
reserve_stock(item_id, cantidad, obra_id, user_id, warehouse_id=None)
release_reservation(reservation_id)
confirm_reservation(reservation_id)

# Uso en proyectos
record_usage(item_id, obra_id, cantidad, user_id)
get_usage_by_project(obra_id) -> list
get_usage_by_item(item_id) -> list

# Reportes
get_low_stock_items(company_id=None, warehouse_id=None) -> list
get_stock_value(company_id=None, warehouse_id=None) -> Decimal
get_movement_history(item_id, start_date=None, end_date=None) -> list
```

**Ejemplo de uso:**
```python
from services import InventoryService
from decimal import Decimal

inventory_service = InventoryService()

# Crear ítem
item = inventory_service.create_item({
    'sku': 'MAT-CEM-001',
    'nombre': 'Cemento Portland',
    'categoria_id': 1,
    'unidad': 'bolsa',
    'company_id': 1,
    'min_stock': Decimal('50')
})

# Registrar ingreso
inventory_service.record_ingreso(
    item_id=item.id,
    warehouse_id=1,
    cantidad=Decimal('100'),
    precio=Decimal('850.50'),
    proveedor='Distribuidora ABC',
    user_id=1
)

# Reservar para proyecto
reservation = inventory_service.reserve_stock(
    item_id=item.id,
    cantidad=Decimal('20'),
    obra_id=5,
    user_id=1,
    warehouse_id=1
)

# Registrar uso
inventory_service.record_usage(
    item_id=item.id,
    obra_id=5,
    cantidad=Decimal('15'),
    user_id=1
)

# Verificar stock bajo
low_stock = inventory_service.get_low_stock_items(company_id=1)
for item in low_stock:
    print(f"{item['nombre']}: {item['stock_actual']} (mín: {item['min_stock']})")
```

---

### 5. MarketplaceService

**Responsabilidades:**
- Gestión de carritos de compra
- Creación y procesamiento de órdenes
- Seguimiento de pagos
- Cálculo de comisiones
- Pagos a proveedores
- Búsqueda de productos

**Métodos principales:**
```python
# Carritos
get_or_create_cart(user_id=None, session_id=None) -> Cart
add_to_cart(cart_id, product_variant_id, cantidad)
update_cart_item(cart_item_id, cantidad)
remove_from_cart(cart_item_id)
clear_cart(cart_id)
get_cart_total(cart_id) -> Decimal

# Órdenes
create_order_from_cart(cart_id, user_id, shipping_data) -> Order
update_order_status(order_id, new_status, user_id)
cancel_order(order_id, user_id, reason)
get_orders_by_user(user_id, status=None) -> list
get_orders_by_supplier(supplier_id, status=None) -> list

# Pagos
record_payment(order_id, payment_data)
confirm_payment(order_id, payment_id)
refund_payment(order_id, amount, reason)

# Comisiones
calculate_commission(order_id) -> Decimal
record_commission(order_id, commission_data)
get_commission_summary(supplier_id, start_date, end_date) -> dict

# Pagos a proveedores
calculate_payout(supplier_id, period_start, period_end) -> Decimal
create_payout(supplier_id, amount, period_start, period_end)
process_payout(payout_id)
get_pending_payouts(supplier_id=None) -> list

# Productos
search_products(query, category_id=None, min_price=None, max_price=None)
get_product_with_variants(product_id)
check_product_availability(product_variant_id, cantidad) -> bool
```

**Ejemplo de uso:**
```python
from services import MarketplaceService
from decimal import Decimal

marketplace_service = MarketplaceService()

# Obtener o crear carrito
cart = marketplace_service.get_or_create_cart(user_id=123)

# Agregar productos
marketplace_service.add_to_cart(
    cart_id=cart.id,
    product_variant_id=456,
    cantidad=Decimal('2')
)

marketplace_service.add_to_cart(
    cart_id=cart.id,
    product_variant_id=789,
    cantidad=Decimal('5')
)

# Ver total
total = marketplace_service.get_cart_total(cart.id)
print(f"Total del carrito: ${total}")

# Crear orden
order = marketplace_service.create_order_from_cart(
    cart_id=cart.id,
    user_id=123,
    shipping_data={
        'address': 'Av. Ejemplo 123',
        'city': 'Buenos Aires',
        'phone': '+54 11 1234-5678',
        'notes': 'Entregar en horario laboral'
    }
)

# Registrar pago
marketplace_service.record_payment(order.id, {
    'method': 'online',
    'payment_ref': 'MP-123456789',
    'status': 'approved',
    'amount': order.total
})

# Confirmar pago
marketplace_service.confirm_payment(order.id, payment_id='MP-123456789')
```

---

## ⚠️ Manejo de Errores

Todos los servicios lanzan excepciones específicas que deben ser capturadas:

```python
from services import UserService, ValidationException, NotFoundException

user_service = UserService()

try:
    user = user_service.authenticate('user@example.com', 'wrong_password')
except ValidationException as e:
    print(f"Error de validación: {e.message}")
    print(f"Detalles: {e.details}")
except NotFoundException as e:
    print(f"No encontrado: {e.message}")
except ServiceException as e:
    print(f"Error de servicio: {e.message}")
```

### Jerarquía de Excepciones

```python
ServiceException
├── ValidationException      # Datos inválidos
├── NotFoundException        # Recurso no encontrado
└── PermissionDeniedException # Sin permisos
```

---

## 🎯 Mejores Prácticas

### 1. Usar Servicios en Lugar de Modelos Directamente

❌ **Mal:**
```python
user = Usuario.query.filter_by(email=email).first()
if user and user.check_password(password):
    # lógica de autenticación
```

✅ **Bien:**
```python
user_service = UserService()
user = user_service.authenticate(email, password)
```

### 2. Manejar Excepciones Apropiadamente

❌ **Mal:**
```python
user = user_service.get_by_id(123)  # Puede retornar None
user.nombre = 'Nuevo Nombre'  # Error si es None
```

✅ **Bien:**
```python
try:
    user = user_service.get_by_id_or_fail(123)
    user = user_service.update(123, nombre='Nuevo Nombre')
except NotFoundException:
    flash('Usuario no encontrado', 'error')
```

### 3. Usar Transacciones para Operaciones Múltiples

```python
from extensions import db

user_service = UserService()
project_service = ProjectService()

try:
    user = user_service.create(email='user@example.com', ...)
    project = project_service.create_project({
        'nombre': 'Proyecto',
        'organizacion_id': user.organizacion_id
    })
    project_service.assign_user_to_project(project.id, user.id, 'admin')
    db.session.commit()
except Exception as e:
    db.session.rollback()
    raise
```

### 4. Usar Type Hints

```python
from typing import Optional, List
from models import Usuario

def get_users_by_role(role: str, limit: int = 10) -> List[Usuario]:
    user_service = UserService()
    users = user_service.get_all(rol=role)
    return users[:limit]
```

### 5. Log Operations

Los servicios ya incluyen logging automático, pero puedes agregar más:

```python
user_service = UserService()
user_service._log_info(f"Procesando actualización para usuario {user_id}")
```

---

## 📝 Testing

### Unit Tests

```python
import pytest
from services import UserService, ValidationException

def test_authenticate_with_valid_credentials():
    service = UserService()
    user = service.authenticate('test@example.com', 'password')
    assert user is not None
    assert user.email == 'test@example.com'

def test_authenticate_with_invalid_password():
    service = UserService()
    with pytest.raises(ValidationException) as exc:
        service.authenticate('test@example.com', 'wrong_password')
    assert 'contraseña incorrecta' in str(exc.value).lower()
```

---

## 🔄 Migración desde Modelos

Si tienes código existente que usa métodos de modelos, aquí está cómo migrarlo:

### Antes (en models)
```python
class Obra(db.Model):
    def calcular_progreso_automatico(self):
        # lógica compleja aquí
        pass
```

### Después (en services)
```python
class ProjectService(BaseService[Obra]):
    def calculate_progress(self, project_id, auto_update=False):
        obra = self.get_by_id_or_fail(project_id)
        # lógica refactorizada aquí
        pass
```

### En tu código
```python
# Antes
obra = Obra.query.get(1)
obra.calcular_progreso_automatico()

# Después
project_service = ProjectService()
progress = project_service.calculate_progress(1, auto_update=True)
```

---

## 🚀 Conclusión

La capa de servicios proporciona:

- ✅ **Código más limpio y organizado**
- ✅ **Mejor testabilidad**
- ✅ **Reutilización de lógica**
- ✅ **Manejo consistente de errores**
- ✅ **Logging centralizado**
- ✅ **Transacciones manejadas automáticamente**

Para más información sobre cada servicio, consulta los docstrings en los archivos fuente.
