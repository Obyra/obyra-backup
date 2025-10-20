# OBYRA · Informe de arquitectura actual y backlog de racionalización

> Última revisión: 2025-10-17

## 1. Resumen ejecutivo
- La aplicación principal (`app.py`) carga 17 blueprints "core" y 7 opcionales; varios dependen de banderas de entorno o de módulos que no siempre están presentes en la instalación.
- Persisten componentes legacy (`app_old.py`, `main.py`, `marketplace_new.py`, `marketplace.py`) fuera del flujo oficial, además de modelos duplicados y servicios sin referencias activas.
- La capa de datos está repartida entre `models.py` (núcleo), `models_marketplace.py` (marketplace) y definiciones inline dentro de blueprints; existen archivos de modelos desacoplados (`models_inventario.py`, `models_equipos.py`).
- Se recomienda consolidar el marketplace "nuevo", retirar módulos obsoletos y definir ownership para servicios críticos (membresías, CAC, Mercado Pago).

## 2. Inventario de blueprints

### 2.1. Blueprints activos registrados siempre
| Blueprint (`endpoint`) | Módulo | Prefijo | Dependencias clave | Observaciones |
| --- | --- | --- | --- | --- |
| `auth` | `auth.py` | `/auth` | `services.email_service`, `services.memberships` | Inicializa OAuth si el módulo `auth.oauth` está disponible, de lo contrario `app.py` define rutas fallback. |
| `obras_bp` | `obras.py` | `/obras` | `services.geocoding_service`, `services.memberships`, `services.obras_filters`, `services.certifications`, `services.wizard_budgeting` | Monolito con vistas, formularios y lógica de negocio mezclados. |
| `presupuestos_bp` | `presupuestos.py` | `/presupuestos` | `services.exchange`, `services.cac.cac_service`, `services.geocoding_service`, `services.memberships` | Define modelos inline (`class Presupuesto`) y procesos de cálculo. |
| `equipos_bp` | `equipos.py` | `/equipos` | `services.memberships` | UI legacy para equipos. |
| `inventario_bp` | `inventario.py` | `/inventario` | `services.memberships` | Inventario histórico, convive con la versión "new". |
| `marketplaces_bp` | `marketplaces.py` | `/marketplaces` | `models_marketplace` | Catálogo público legacy. |
| `reportes_bp` | `reportes.py` | `/reportes` | `services.alerts`, `services.memberships`, `services.obras_filters` | Renderiza dashboards HTML. |
| `asistente_bp` | `asistente_ia.py` | `/asistente` | `asistente_ia` y OpenAI opcional | Router simple hacia el asistente IA. |
| `cotizacion_bp` | `cotizacion_inteligente.py` | `/cotizacion` | Servicios de CAC y exchange | Calculadora de cotizaciones con IA. |
| `documentos_bp` | `control_documentos.py` | `/documentos` | `services.memberships` | Gestión de documentos. |
| `seguridad_bp` | `seguridad_cumplimiento.py` | `/seguridad` | Formularios propios | Cumplimiento y seguridad. |
| `agent_bp` | `agent_local.py` | *(sin prefijo)* | Scripts agentes | API auxiliar. |
| `planes_bp` | `planes.py` | *(sin prefijo)* | Modelos en `models.py` | Gestión de planes. |
| `events_bp` | `events_service.py` | *(sin prefijo)* | `current_app` logging | API de eventos para marketplace. |
| `account_bp` | `account.py` | *(sin prefijo)* | `flask_login`, `services.memberships` | Perfil de usuario. |
| `onboarding_bp` | `onboarding.py` | `/onboarding` | `services.memberships` | Flujo de onboarding. |

### 2.2. Blueprints condicionales / feature flagged
| Blueprint | Módulo | Prefijo | Condición | Estado |
| --- | --- | --- | --- | --- |
| `reports_service_bp` | `reports_service.py` | *(sin prefijo)* | `ENABLE_REPORTS=1` y disponibilidad de `matplotlib` | API JSON para reportes y descargas. |
| `equipos_new_bp` | `equipos_new.py` | `/equipos-new` | Import exitoso | Proporciona nueva UI de equipos; `app.py` añade redirects desde rutas legacy. |
| `inventario_new_bp` | `inventario_new.py` | `/inventario-new` | Import exitoso | Nueva UI de inventario. |
| `supplier_auth_bp` | `supplier_auth.py` | *(sin prefijo)* | Import exitoso | Portal de proveedores (login). |
| `supplier_portal_bp` | `supplier_portal.py` | *(sin prefijo)* | Import exitoso | Dashboard de proveedores. |
| `market_bp` | `market.py` | `/market` | Import exitoso | Catálogo público para proveedores. |
| `marketplace_bp` | `marketplace/routes.py` | `/` | Import exitoso | API REST del marketplace "nuevo"; comparte modelos con `marketplace_payments`. |
| `payments_bp` | `marketplace_payments.py` | *(sin prefijo)* | Registro manual (no se hace en `app.py`) | Expuesto en scripts de marketplace; manejar via `app.register_blueprint` según entorno. |

### 2.3. Blueprints legacy / no registrados
| Blueprint / módulo | Situación | Riesgos |
| --- | --- | --- |
| `marketplace_new.py` | No se importa en `app.py`; contiene UI + pagos Mercado Pago duplicados | Divergencia de lógica de órdenes y pagos; riesgo de drift con `marketplace/routes.py`. |
| `marketplace.py` | UI legacy del marketplace | Plantillas obsoletas, rutas no protegidas. |
| `app_old.py`, `main.py`, `main_app.py` | Aplicaciones monolíticas históricas con `db.create_all()` | Pueden crear esquemas inconsistentes si se ejecutan. |
| `marketplace_new_bp` | Blueprint definido pero sin registro | Código muerto. |

### 2.4. Mapa de rutas y dependencias (Mermaid)
```mermaid
%%{init: {'theme': 'neutral', 'flowchart': {'curve': 'basis'}} }%%
graph TD
    app[app.py] --> auth[auth]
    app --> obras[obras]
    app --> presupuestos[presupuestos]
    app --> equipos[equipos]
    app --> inventario[inventario]
    app --> reportes[reportes]
    app --> asistente[asistente_ia]
    app --> cotizacion[cotizacion_inteligente]
    app --> documentos[control_documentos]
    app --> seguridad[seguridad_cumplimiento]
    app --> eventos[events_service]
    app --> account[account]
    app --> onboarding[onboarding]
    app --> planes[planes]
    app --> agent[agent_local]
    app --> marketplaces_bp[marketplaces]
    app -.-> reports_service[reports_service]
    app -.-> inventario_new[inventario_new]
    app -.-> equipos_new[equipos_new]
    app -.-> supplier_auth[supplier_auth]
    app -.-> supplier_portal[supplier_portal]
    app -.-> market[market]
    app -.-> marketplace_api[marketplace/routes]
    marketplace_api --> marketplace_models[models_marketplace]
    market -.-> marketplace_models
    reports_service --> matplotlib((matplotlib))
    presupuestos --> services_exchange[services.exchange]
    presupuestos --> services_cac[services.cac]
    obras --> services_cert[services.certifications]
    obras --> services_wizard[services.wizard_budgeting]
    marketplace_api --> mp_payments[marketplace_payments]
    mp_payments --> mercadopago((Mercado Pago))
    classDef active fill:#0f766e,stroke:#0f766e,color:#ffffff,font-weight:bold;
    classDef optional fill:#f97316,stroke:#c2410c,color:#000000;
    classDef legacy fill:#dc2626,stroke:#991b1b,color:#ffffff;
    class auth,obras,presupuestos,equipos,inventario,reportes,asistente,cotizacion,documentos,seguridad,eventos,account,onboarding,planes,agent,marketplaces_bp active;
    class reports_service,inventario_new,equipos_new,supplier_auth,supplier_portal,market,marketplace_api,mp_payments optional;
    class mercadopago,services_exchange,services_cac,services_cert,services_wizard,matplotlib,marketplace_models optional;
    legacy_marketplace_new[marketplace_new.py]
    legacy_app_old[app_old.py]
    legacy_main[main.py / main_app.py]
    app -.x legacy_marketplace_new
    app -.x legacy_app_old
    app -.x legacy_main
    class legacy_marketplace_new,legacy_app_old,legacy_main legacy;
```

## 3. Servicios y utilitarios
| Servicio / módulo | Uso actual | Dependencias | Estado |
| --- | --- | --- | --- |
| `services/memberships.py` | Inicializa contexto de membresía en `app.py`, usado por múltiples blueprints | `flask.g`, modelos `Usuario`, `Organizacion` | **Crítico** (mantener, revisar tests). |
| `services/email_service.py` | Envío de correos desde `auth`, `services.po_service` | SMTP configurado vía env vars | **Activo**. |
| `services/alerts.py` | `reportes_bp` para alertas y logging | `models.py` | **Activo**, requiere refactor para separar lógica/ORM. |
| `services/geocoding_service.py` | `obras`, `presupuestos`, `geocoding.py` | `MAPS_PROVIDER`, requests | **Activo**, considerar caching central. |
| `services/exchange` (`base.py`, providers) | `presupuestos`, `calculadora_ia`, runtime migrations | API BNA | **Activo**, monitorear proveedor BNA. |
| `services/cac` | Usado en `presupuestos`, `cotizacion_inteligente`, runtime admin CLI | `services.exchange`, modelos `CACIndice` | **Activo**, falta documentación. |
| `services/wizard_budgeting.py` | Seed y cálculos del nuevo wizard (`obras`, `docs`) | `models.py` | **Feature flag** (`WIZARD_BUDGET_*`). |
| `services/po_service.py` | `marketplace_payments` (generación de órdenes de compra) | `models_marketplace`, `services.email_service` | **Opcional**, ligado a marketplace. |
| `services/pricing/*` | No hay import directo en código actual | `services.cac` | **Revisar**: posible deuda técnica. |
| `services/certifications.py` | Consumido por `obras` | `models.py` | **Activo**. |

## 4. Modelos
| Archivo | Contenido principal | Uso | Estado |
| --- | --- | --- | --- |
| `models.py` | Usuarios, organizaciones, presupuestos, tareas, marketplace básico | Referenciado por la mayoría de blueprints | **Core**; requiere modularización. |
| `models_marketplace.py` | Catálogo extendido, órdenes, pagos, sellers | Usado por `marketplace/routes.py`, `marketplace_payments.py`, `services/po_service.py` | **Activo**. |
| `models_inventario.py` | Inventario alternativo | No referenciado en `app.py`; revisar scripts | **Legacy**, candidato a eliminar si no hay consumidores. |
| `models_equipos.py` | Modelos de equipos alternativos | Sin referencias actuales | **Legacy**. |
| Definiciones inline (`obras.py`, `presupuestos.py`, `marketplace.py`) | Modelos declarados dentro de blueprints | Mezclan vista y ORM | **Refactor urgente**. |

## 5. Dependencias y puntos de acoplamiento
- `app.py` controla registro condicional de blueprints mediante `try/except`; falla silenciosa puede ocultar errores reales de importación.
- Feature flags (`ENABLE_REPORTS`, `WIZARD_BUDGET_*`, `SHOW_IA_CALCULATOR_BUTTON`) cambian rutas y servicios disponibles; documentar en `docs/ENV.md`.
- Mercado Pago: `marketplace_payments.py` depende de configuraciones `MP_ACCESS_TOKEN` y `MP_WEBHOOK_PUBLIC_URL`; se recomienda centralizar registro del blueprint en `app.py` bajo feature flag.
- Servicios CAC y Exchange: se ejecutan tanto en runtime migrations como en rutas; requieren control de acceso a proveedores externos.

## 6. Backlog priorizado para racionalización
| Prioridad | Ámbito | Acción recomendada | Impacto | Notas |
| --- | --- | --- | --- | --- |
| Alta | Marketplace | Decidir versión canónica (`marketplace/routes.py` + `marketplace_payments.py` vs `marketplace_new.py`) y eliminar duplicados (`marketplace.py`, plantillas legacy). | Reduce divergencias de pagos y UI. | Requiere alineación con equipo negocio. |
| Alta | Bootstrap | Retirar `app_old.py`, `main.py`, `main_app.py` del deploy; mover cualquier script útil a CLI documentada. | Evita ejecuciones con `db.create_all()` y configuraciones inseguras. | Puede mantenerse en branch de archivo histórico. |
| Media | Modelos | Extraer modelos inline de `presupuestos.py`, `obras.py` y consolidarlos en paquetes `models/`. | Mejora mantenibilidad y reutilización. | Ideal combinar con migraciones Alembic. |
| Media | Servicios | Auditar `services/pricing` y `services/po_service` para confirmar uso; documentar ownership. | Evita dependencias muertas. | Crear pruebas unitarias mínimas. |
| Baja | Documentación | Generar diagrama actualizable (plantilla Mermaid en repo) y pipeline que lo publique. | Visibilidad continua. | Puede integrarse a MkDocs/Sphinx futuro. |
| Baja | Feature flags | Definir estrategia de retiro para `WIZARD_BUDGET_SHADOW_MODE` y `ENABLE_REPORTS_SERVICE` (observabilidad, métricas). | Reduce complejidad. | Depende del roadmap del producto. |

## 7. Próximos pasos sugeridos
1. Validar el backlog con stakeholders (producto, marketplace) y crear issues individuales.
2. Incorporar pruebas de smoke (GET básico) para cada blueprint activo en la suite CI.
3. Mantener este inventario vivo: actualizar la tabla cuando se agreguen o remuevan módulos.
4. Documentar en `docs/ENV.md` los requisitos de feature flags por entorno y la configuración del marketplace una vez consolidado.

