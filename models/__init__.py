"""
Models Package
==============
Este paquete contiene todos los modelos del sistema organizados por funcionalidad.

Estructura:
- core: Usuario, Organizacion, RBAC
- projects: Obra, Etapa, Tarea
- budgets: Presupuesto, ItemPresupuesto, WizardStage
- inventory: Inventario y gestión de stock
- equipment: Equipos y mantenimiento
- suppliers: Proveedores y productos
- marketplace: Marketplace y comercio
- templates: Plantillas y certificaciones
- utils: Utilidades (RegistroTiempo, ConsultaAgente)
"""

from extensions import db

# Core models - Usuario, Organizacion, RBAC
from models.core import (
    Organizacion,
    Usuario,
    OrgMembership,
    PerfilUsuario,
    OnboardingStatus,
    BillingProfile,
    RoleModule,
    UserModule,
    get_allowed_modules,
    upsert_user_module,
)

# Project models - Obras y tareas
from models.projects import (
    Obra,
    EtapaObra,
    TareaEtapa,
    TareaMiembro,
    TareaAvance,
    TareaAvanceFoto,
    TareaPlanSemanal,
    TareaAvanceSemanal,
    TareaAdjunto,
    TareaResponsables,
    AsignacionObra,
    ObraMiembro,
    resumen_tarea,
    calcular_avance_tarea,
    calcular_avance_etapa,
)

# Budget models - Presupuestos y pricing
from models.budgets import (
    ExchangeRate,
    CACIndex,
    PricingIndex,
    Presupuesto,
    ItemPresupuesto,
    GeocodeCache,
    WizardStageVariant,
    WizardStageCoefficient,
)

# Client models
from models.clients import Cliente

# Inventory models
from models.inventory import (
    # Sistema de Ubicaciones (nuevo)
    Location,
    StockUbicacion,
    MovimientoStock,
    # Legacy
    CategoriaInventario,
    ItemInventario,
    MovimientoInventario,
    UsoInventario,
    # New
    InventoryCategory,
    InventoryItem,
    Warehouse,
    Stock,
    StockMovement,
    StockReservation,
    # Global Catalog
    GlobalMaterialCatalog,
    GlobalMaterialUsage,
)

# Equipment models
from models.equipment import (
    Equipment,
    EquipmentAssignment,
    EquipmentUsage,
    MaintenanceTask,
    MaintenanceAttachment,
)

# Supplier models
from models.suppliers import (
    # Legacy
    Proveedor,
    CategoriaProveedor,
    SolicitudCotizacion,
    # New
    Supplier,
    SupplierUser,
    Category,
    Product,
    ProductVariant,
    ProductImage,
    ProductQNA,
)

# Marketplace models
from models.marketplace import (
    Order,
    OrderItem,
    OrderCommission,
    Cart,
    CartItem,
    SupplierPayout,
    Event,
)

# Template and certification models
from models.templates import (
    PlantillaProyecto,
    EtapaPlantilla,
    TareaPlantilla,
    ItemMaterialPlantilla,
    ConfiguracionInteligente,
    CertificacionAvance,
    WorkCertification,
    WorkCertificationItem,
    WorkPayment,
)

# Utility models
from models.utils import (
    RegistroTiempo,
    ConsultaAgente,
)


def seed_default_role_permissions():
    """Seed permisos por defecto para roles"""
    default_permissions = {
        'administrador': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'equipos': {'view': True, 'edit': True},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': True},
            'reportes': {'view': True, 'edit': True},
            'documentos': {'view': True, 'edit': True}
        },
        'tecnico': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': False},
            'reportes': {'view': True, 'edit': False},
            'documentos': {'view': True, 'edit': True}
        },
        'operario': {
            'obras': {'view': True, 'edit': False},
            'inventario': {'view': True, 'edit': False},
            'marketplaces': {'view': True, 'edit': False},
            'documentos': {'view': True, 'edit': False}
        },
        'jefe_obra': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'equipos': {'view': True, 'edit': False},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': True},
            'reportes': {'view': True, 'edit': False},
            'documentos': {'view': True, 'edit': True}
        },
        'compras': {
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': False},
            'reportes': {'view': True, 'edit': False}
        }
    }

    for role, modules in default_permissions.items():
        for module, perms in modules.items():
            existing = RoleModule.query.filter_by(role=role, module=module).first()
            if not existing:
                rm = RoleModule(
                    role=role,
                    module=module,
                    can_view=perms['view'],
                    can_edit=perms['edit']
                )
                db.session.add(rm)

    db.session.commit()


# Export all for convenient importing
__all__ = [
    # Core
    'Organizacion',
    'Usuario',
    'OrgMembership',
    'PerfilUsuario',
    'OnboardingStatus',
    'BillingProfile',
    'RoleModule',
    'UserModule',
    'get_allowed_modules',
    'upsert_user_module',
    # Projects
    'Obra',
    'EtapaObra',
    'TareaEtapa',
    'TareaMiembro',
    'TareaAvance',
    'TareaAvanceFoto',
    'TareaPlanSemanal',
    'TareaAvanceSemanal',
    'TareaAdjunto',
    'TareaResponsables',
    'AsignacionObra',
    'ObraMiembro',
    'resumen_tarea',
    # Budgets
    'ExchangeRate',
    'CACIndex',
    'PricingIndex',
    'Presupuesto',
    'ItemPresupuesto',
    'GeocodeCache',
    'WizardStageVariant',
    'WizardStageCoefficient',
    # Clients
    'Cliente',
    # Inventory
    'CategoriaInventario',
    'ItemInventario',
    'MovimientoInventario',
    'UsoInventario',
    'InventoryCategory',
    'InventoryItem',
    'Warehouse',
    'Stock',
    'StockMovement',
    'StockReservation',
    # Equipment
    'Equipment',
    'EquipmentAssignment',
    'EquipmentUsage',
    'MaintenanceTask',
    'MaintenanceAttachment',
    # Suppliers
    'Proveedor',
    'CategoriaProveedor',
    'SolicitudCotizacion',
    'Supplier',
    'SupplierUser',
    'Category',
    'Product',
    'ProductVariant',
    'ProductImage',
    'ProductQNA',
    # Marketplace
    'Order',
    'OrderItem',
    'OrderCommission',
    'Cart',
    'CartItem',
    'SupplierPayout',
    'Event',
    # Templates
    'PlantillaProyecto',
    'EtapaPlantilla',
    'TareaPlantilla',
    'ItemMaterialPlantilla',
    'ConfiguracionInteligente',
    'CertificacionAvance',
    'WorkCertification',
    'WorkCertificationItem',
    'WorkPayment',
    # Utils
    'RegistroTiempo',
    'ConsultaAgente',
    # Functions
    'seed_default_role_permissions',
]
