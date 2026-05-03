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
    EtapaDependencia,
    AsignacionObra,
    ObraMiembro,
    Fichada,
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
    ItemPresupuestoComposicion,
    MaterialCotizable,
    ProveedorAsignadoMaterial,
    SolicitudCotizacionMaterial,
    SolicitudCotizacionMaterialItem,
    NivelPresupuesto,
    ItemReferenciaConstructora,
    GeocodeCache,
    WizardStageVariant,
    WizardStageCoefficient,
    EscalaSalarialUOCRA,
    CuadrillaTipo,
    MiembroCuadrilla,
    EtapaInternaVinculo,
    CategoriaJornal,
    VariacionCacPendiente,
)

# Client models
from models.clients import Cliente

# Subcontratistas
from models.subcontratista import Subcontratista, DocumentoSubcontratista

# Suscripciones (Mercado Pago Preapproval)
from models.subscription import Subscription

# Proveedores OC models
from models.proveedores_oc import (
    ProveedorOC, HistorialPrecioProveedor, ProveedorEvaluacion,
    CotizacionProveedor, CotizacionProveedorItem,
    Zona, ContactoProveedor,
)

# Solicitud de cotizacion via WhatsApp (desde Presupuesto)
from models.presupuestos_wa import ItemPresupuestoProveedor, SolicitudCotizacionWA

# Inventory models
from models.inventory import (
    # Sistema de Ubicaciones (nuevo)
    Location,
    StockUbicacion,
    MovimientoStock,
    # Legacy
    CategoriaInventario,
    ItemInventario,
    item_categorias_adicionales,
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
    # Ordenes de Compra
    OrdenCompra,
    OrdenCompraItem,
    RecepcionOC,
    RecepcionOCItem,
    # Remitos
    Remito,
    RemitoItem,
)

# Equipment models
from models.equipment import (
    Equipment,
    EquipmentAssignment,
    EquipmentUsage,
    MaintenanceTask,
    MaintenanceAttachment,
    EquipmentMovement,
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
    LiquidacionMO,
    LiquidacionMOItem,
    MovimientoCaja,
)

# Utility models
from models.utils import (
    RegistroTiempo,
    ConsultaAgente,
)

# Audit log
from models.audit import AuditLog, registrar_audit

# Documentos legales y consentimientos
from models.legal import LegalDocument, UserConsent, documentos_pendientes_para_usuario, TIPOS_DOCUMENTO

# Aprendizaje IA: log de correcciones, candidatas, stats
from models.ia_learning import (
    IACorrectionLog, IARuleCandidate, IARuleUsageStat,
    TIPOS_CORRECCION, ESTADOS_CANDIDATA,
)

# Cierre formal de obra y acta de entrega
from models.cierre_obra import CierreObra, ActaEntrega


def seed_default_role_permissions():
    """Seed permisos por defecto para roles"""
    default_permissions = {
        'administrador': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'equipos': {'view': True, 'edit': True},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': True},
            'reportes': {'view': True, 'edit': True}
        },
        'tecnico': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': False},
            'reportes': {'view': True, 'edit': False}
        },
        'operario': {
            'obras': {'view': True, 'edit': False},
            'inventario': {'view': True, 'edit': False},
            'marketplaces': {'view': True, 'edit': False}
        },
        'jefe_obra': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'equipos': {'view': True, 'edit': False},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': True},
            'reportes': {'view': True, 'edit': False}
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
    'EtapaDependencia',
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
    'ItemPresupuestoComposicion',
    'MaterialCotizable',
    'ProveedorAsignadoMaterial',
    'SolicitudCotizacionMaterial',
    'SolicitudCotizacionMaterialItem',
    'NivelPresupuesto',
    'ItemReferenciaConstructora',
    'GeocodeCache',
    'WizardStageVariant',
    'WizardStageCoefficient',
    'EscalaSalarialUOCRA',
    'CategoriaJornal',
    'VariacionCacPendiente',
    'CuadrillaTipo',
    'MiembroCuadrilla',
    'EtapaInternaVinculo',
    # Clients
    'Cliente',
    # Proveedores OC
    'ProveedorOC',
    'HistorialPrecioProveedor',
    'ProveedorEvaluacion',
    'CotizacionProveedor',
    'CotizacionProveedorItem',
    'Zona',
    'ContactoProveedor',
    # Solicitud cotizacion WhatsApp
    'ItemPresupuestoProveedor',
    'SolicitudCotizacionWA',
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
    'EquipmentMovement',
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
    # Cierre de obra
    'CierreObra',
    'ActaEntrega',
    # Functions
    'seed_default_role_permissions',
]
