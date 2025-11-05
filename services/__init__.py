"""
Services Package
================
Capa de servicios para lógica de negocio del sistema OBYRA.

Los servicios encapsulan la lógica de negocio y proporcionan una interfaz
limpia para operaciones complejas. Todos los servicios heredan de BaseService.

Estructura:
-----------
- base: Clase base y excepciones
- user_service: Gestión de usuarios y autenticación
- project_service: Gestión de proyectos y tareas
- budget_service: Gestión de presupuestos
- inventory_service: Gestión de inventario y stock
- marketplace_service: Gestión de marketplace y comercio

Uso:
----
    from services import UserService, ProjectService

    user_service = UserService()
    user = user_service.authenticate('user@example.com', 'password')

    project_service = ProjectService()
    progress = project_service.calculate_progress(project_id=1)
"""

# Base service and exceptions
from services.base import (
    BaseService,
    ReadOnlyService,
    ServiceException,
    ValidationException,
    NotFoundException,
    PermissionDeniedException,
)

# Domain services
from services.user_service import UserService
from services.project_service import ProjectService
from services.budget_service import BudgetService
from services.inventory_service import InventoryService
from services.marketplace_service import MarketplaceService


__all__ = [
    # Base classes
    'BaseService',
    'ReadOnlyService',
    # Exceptions
    'ServiceException',
    'ValidationException',
    'NotFoundException',
    'PermissionDeniedException',
    # Services
    'UserService',
    'ProjectService',
    'BudgetService',
    'InventoryService',
    'MarketplaceService',
]


# Service instances for convenient imports
# These can be imported directly: from services import user_service
user_service = UserService()
project_service = ProjectService()
budget_service = BudgetService()
inventory_service = InventoryService()
marketplace_service = MarketplaceService()
