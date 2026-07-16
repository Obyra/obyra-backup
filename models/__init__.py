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
    CustomRole,
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

# Perfil tecnico del proyecto (Fase 2: asistente de obra)
from models.project_technical_profile import (
    ProjectTechnicalProfile,
    validar_y_normalizar as validar_perfil_tecnico,
    TIPOS_OBRA, TIPOS_ESTRUCTURA, TIPOS_FUNDACION,
    CRITERIOS_DISTRIBUCION, CANTIDADES_EXCEL_SON_TOTALES,
)

# Cierre formal de obra y acta de entrega
from models.cierre_obra import CierreObra, ActaEntrega

# Fase 5.A: catalogo de precios de proveedores + costo empresa de mano de obra
from models.provider_price_list import ProviderPriceList, normalizar_descripcion_precio

# Biblioteca de formulas tecnicas + coeficientes (Fase 1 Plan 90%)
from models.formulas import (
    FormulaTecnica,
    Coeficiente,
    ImportBatchFormulas,
)

# Caja A: Facturas administrativas por obra (MVP)
from models.obra_factura import (
    ObraFactura,
    ObraFacturaAudit,
    TIPOS_COMPROBANTE,
    ESTADOS_FACTURA,
    adjunto_es_obligatorio,
)
from models.mano_obra_costo_referencia import (
    ManoObraCostoReferencia, CATEGORIAS_BASE, categoria_canonica_para,
)

# Fase 2.0 IA presupuestos: costo empresa de MO normalizado (recargos parametrizados)
from models.mano_obra import (
    EstructuraRecargosMO, RecargoMOLinea, IndiceActualizacion,
    GRUPOS_RECARGO, TIPOS_CALCULO,
)

# Fase 2.5 IA presupuestos: aprendizaje de correcciones por organizacion
from models.mapeo_aprendido import (
    MapeoItemAprendido, normalizar_texto_item, TRATAMIENTOS_MAPEO,
)

# Fase 6.A: archivos de licitacion (multiples Excel por presupuesto)
from models.presupuesto_archivo import PresupuestoArchivo

# Etapa 1 base inteligente de precios: observaciones append-only
from models.precio_observado import PrecioObservado

# Etapa 2 base IA: batches de import unificado
from models.import_batch import ImportBatch

# Modulo presupuestos flexible (Etapa 1): etapas editables del presupuesto
from models.presupuesto_etapa import PresupuestoEtapa


# Módulos del sistema y permisos por defecto de los 4 roles canónicos.
# Reemplaza los nombres viejos ('administrador'/'jefe_obra'/'compras') que
# no matcheaban Usuario.role. Ahora los permisos coinciden con el fallback
# hardcodeado de Usuario.puede_acceder_modulo / puede_editar_modulo.
_TODOS_LOS_MODULOS = [
    'obras', 'presupuestos', 'equipos', 'inventario',
    'marketplaces', 'reportes', 'asistente', 'cotizacion', 'seguridad',
]

# {rol: {'view': [modulos...], 'edit': [modulos...]}}
DEFAULT_ROLE_PERMISSIONS = {
    'admin':    {'view': list(_TODOS_LOS_MODULOS), 'edit': list(_TODOS_LOS_MODULOS)},
    'pm':       {'view': list(_TODOS_LOS_MODULOS), 'edit': list(_TODOS_LOS_MODULOS)},
    'tecnico':  {
        'view': ['obras', 'presupuestos', 'inventario', 'marketplaces',
                 'reportes', 'asistente', 'cotizacion', 'seguridad'],
        'edit': ['obras', 'presupuestos', 'inventario', 'marketplaces',
                 'reportes', 'asistente', 'cotizacion', 'seguridad'],
    },
    'operario': {
        'view': ['obras', 'inventario', 'marketplaces', 'asistente'],
        'edit': [],
    },
}

# Descripción de los 4 roles base (para custom_roles).
DEFAULT_ROLE_LABELS = {
    'admin': 'Administrador',
    'pm': 'Project Manager',
    'tecnico': 'Técnico',
    'operario': 'Operario',
}


def seed_custom_roles_for_org(org_id):
    """Crea los 4 roles base en custom_roles para una organización (idempotente)."""
    for nombre, descripcion in DEFAULT_ROLE_LABELS.items():
        existing = CustomRole.query.filter_by(org_id=org_id, nombre=nombre).first()
        if not existing:
            db.session.add(CustomRole(
                org_id=org_id, nombre=nombre, descripcion=descripcion, activo=True,
            ))


def seed_default_role_permissions(org_id=None):
    """Seed de permisos por rol POR ORGANIZACIÓN (idempotente).

    Si `org_id` es None, seedea todas las organizaciones. Crea tanto los
    custom_roles base como sus filas en role_modules (org-scoped).
    """
    from models.core import Organizacion

    org_ids = [org_id] if org_id is not None else [o.id for o in Organizacion.query.all()]

    for oid in org_ids:
        seed_custom_roles_for_org(oid)
        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
            edit_set = set(perms['edit'])
            for module in perms['view']:
                existing = RoleModule.query.filter_by(
                    org_id=oid, role=role, module=module
                ).first()
                if not existing:
                    db.session.add(RoleModule(
                        org_id=oid, role=role, module=module,
                        can_view=True, can_edit=(module in edit_set),
                    ))

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
    'CustomRole',
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
    # Costo MO normalizado (Fase 2.0)
    'EstructuraRecargosMO',
    'RecargoMOLinea',
    'IndiceActualizacion',
    # Aprendizaje por org (Fase 2.5)
    'MapeoItemAprendido',
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
    'seed_custom_roles_for_org',
]
