# OBYRA · Informe de arquitectura actual y backlog de racionalización

> Última revisión: 2025-10-17

## 1. Resumen ejecutivo
- La aplicación principal (`app.py`) carga **17 blueprints core** y **7 opcionales**; varios dependen de banderas de entorno o de módulos que no siempre están presentes.
- Persisten componentes **legacy** (`app_old.py`, `main.py`, `main_app.py`, `marketplace_new.py`, `marketplace.py`) fuera del flujo oficial, además de modelos duplicados y servicios sin referencias activas.
- La capa de datos está repartida entre `models.py` (núcleo), `models_marketplace.py` (marketplace) y definiciones inline dentro de blueprints; existen archivos de modelos desacoplados (`models_inventario.py`, `models_equipos.py`).
- Recomendación: **consolidar** el marketplace “nuevo”, **retirar** módulos obsoletos y **definir ownership** para servicios críticos (membresías, CAC, Mercado Pago).

---

## 2. Inventario de blueprints

### 2.1. Blueprints activos registrados siempre
| Blueprint (endpoint) | Módulo | Prefijo | Dependencias clave | Observaciones |
|---|---|---|---|---|
| `auth` | `auth.py` | `/auth` | `services.email_service`, `services.memberships` | Inicializa OAuth si `auth.oauth` está disponible; si falta, `app.py` define rutas fallback. |
| `obras_bp` | `obras.py` | `/obras` | `services.geocoding_service`, `services.memberships`, `services.obras_filters`, `services.certifications`, `services.wizard_budgeting` | Monolito con vistas + lógica. |
| `presupuestos_bp` | `presupuestos.py` | `/presupuestos` | `services.exchange`, `services.cac.cac_service`, `services.geocoding_service`, `services.memberships` | Define modelos inline (p.ej. `Presupuesto`). |
| `equipos_bp` | `equipos.py` | `/equipos` | `services.memberships` | UI legacy de equipos. |
| `inventario_bp` | `inventario.py` | `/inventario` | `services.memberships` | Inventario histórico, convive con “new”. |
| `marketplaces_bp` | `marketplaces.py` | `/marketplaces` | `models_marketplace` | Catálogo público legacy. |
| `reportes_bp` | `reportes.py` | `/reportes` | `services.alerts`, `services.memberships`, `services.obras_filters` | Dashboards HTML. |
| `asistente_bp` | `asistente_ia.py` | `/asistente` | OpenAI (opcional) | Router simple. |
| `cotizacion_bp` | `cotizacion_inteligente.py` | `/cotizacion` | CAC y Exchange | Calculadora con IA. |
| `documentos_bp` | `control_documentos.py` | `/documentos` | `services.memberships` | Gestión documental. |
| `seguridad_bp` | `seguridad_cumplimiento.py` | `/seguridad` | Formularios propios | Cumplimiento y seguridad. |
| `agent_bp` | `agent_local.py` | *(sin prefijo)* | Scripts agentes | API auxiliar. |
| `planes_bp` | `planes.py` | *(sin prefijo)* | Modelos en `models.py` | Gestión de planes. |
| `events_bp` | `events_service.py` | *(sin prefijo)* | `current_app` logging | API de eventos para marketplace. |
| `account_bp` | `account.py` | *(sin prefijo)* | `flask_login`, `services.memberships` | Perfil de usuario. |
| `onboarding_bp` | `onboarding.py` | `/onboarding` | `services.memberships` | Flujo de onboarding. |

### 2.2. Blueprints condicionales / feature flagged
| Blueprint | Módulo | Prefijo | Condición | Estado |
|---|---|---|---|---|
| `reports_service_bp` | `reports_service.py` | *(sin prefijo)* | `ENABLE_REPORTS=1` y `matplotlib` disponible | API de reportes/descargas. |
| `equipos_new_bp` | `equipos_new.py` | `/equipos-new` | Import exitoso | Nueva UI de equipos; hay redirects desde legacy. |
| `inventario_new_bp` | `inventario_new.py` | `/inventario-new` | Import exitoso | Nueva UI de inventario. |
| `supplier_auth_bp` | `supplier_auth.py` | *(sin prefijo)* | Import exitoso | Login de proveedores. |
| `supplier_portal_bp` | `supplier_portal.py` | *(sin prefijo)* | Import exitoso | Dashboard de proveedores. |
| `market_bp` | `market.py` | `/market` | Import exitoso | Catálogo público para proveedores. |
| `marketplace_bp` | `marketplace/routes.py` | `/` | Import exitoso | API REST del marketplace “nuevo”; comparte modelos con pagos. |
| `payments_bp` | `marketplace_payments.py` | *(sin prefijo)* | **Registro manual** (no en `app.py`) | Úsese `app.register_blueprint` bajo flag/entorno. |

### 2.3. Blueprints legacy / no registrados
| Blueprint / módulo | Situación | Riesgos |
|---|---|---|
| `marketplace_new.py` | No se importa en `app.py`; contiene UI + pagos MP duplicados | Divergencia de lógica y drift con `marketplace/routes.py`. |
| `marketplace.py` | UI legacy del marketplace | Plantillas obsoletas, rutas no protegidas. |
| `app_old.py`, `main.py`, `main_app.py` | Apps históricas con `db.create_all()` | Pueden crear esquemas inconsistentes si se ejecutan. |
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
3. Servicios y utilitarios
Servicio / módulo	Uso actual	Dependencias	Estado
services/memberships.py	Inicializa contexto de membresía (hooks en g) desde app.py	flask.g, modelos Usuario, Organizacion	Crítico (mantener, revisar tests)
services/email_service.py	Envíos desde auth y services.po_service	SMTP (SMTP_*)	Activo
services/alerts.py	Alertas en reportes_bp	models.py	Activo, refactor deseable
services/geocoding_service.py	Geocodificación en obras, presupuestos	requests, MAPS_*	Activo (caché central recomendado)
services/exchange/*	FX para presupuestos, runtime migrations	Proveedor BNA	Activo
services/cac/*	Índice CAC (cotizacion_inteligente, CLI)	exchange	Activo
services/wizard_budgeting.py	Nuevo presupuestador	models.py	Flag WIZARD_BUDGET_*
services/po_service.py	Órdenes marketplace	models_marketplace	Opcional (ligado a marketplace)
services/pricing/*	Sin import directo actual	services.cac	Revisar (posible deuda)
services/certifications.py	Certificaciones en obras	models.py	Activo
4. Modelos
Archivo	Contenido principal	Uso	Estado
models.py	Usuarios, organizaciones, presupuestos, tareas, marketplace básico	Referenciado por la mayoría de blueprints	Core (modularizar)
models_marketplace.py	Productos, órdenes, pagos, sellers	marketplace/routes.py, marketplace_payments.py, services/po_service.py	Activo
models_inventario.py	Inventario alternativo	No importado en app.py	Legacy
models_equipos.py	Equipos alternativos	Sin referencias actuales	Legacy
Definiciones inline	Dentro de presupuestos.py, obras.py, marketplace.py	Mezclan vista/ORM	Refactor urgente
5. Dependencias y puntos de acoplamiento

app.py controla registro condicional de blueprints mediante try/except; la falla silenciosa puede ocultar errores reales de importación.

Feature flags (ENABLE_REPORTS, WIZARD_BUDGET_*, SHOW_IA_CALCULATOR_BUTTON) cambian rutas/servicios; documentar en docs/ENV.md.

Mercado Pago: marketplace_payments.py depende de MP_ACCESS_TOKEN y MP_WEBHOOK_PUBLIC_URL; se recomienda centralizar su registro en app.py bajo flag.

CAC/Exchange: usados en runtime y rutas; requieren control de errores ante proveedores externos.

6. Backlog priorizado para racionalización
Prioridad	Ámbito	Acción recomendada	Impacto	Notas
Alta	Marketplace	Elegir versión canónica (marketplace/routes.py + pagos) y eliminar duplicados (marketplace_new.py, marketplace.py).	Menos divergencias de pagos/UI.	Alinear con negocio.
Alta	Bootstrap	Retirar app_old.py, main.py, main_app.py del deploy; mover scripts útiles a CLI documentada.	Evita esquemas inconsistentes.	Guardar en rama histórica.
Media	Modelos	Extraer modelos inline de blueprints a models/ dedicados.	Mantenibilidad.	Ideal con migraciones Alembic.
Media	Servicios	Auditar services/pricing y services/po_service (uso/ownership).	Limpieza de dependencias muertas.	Agregar tests mínimos.
Baja	Documentación	Mantener diagrama Mermaid y publicarlo en docs/.	Visibilidad continua.	Automatizable en CI.
Baja	Feature flags	Plan de retiro para WIZARD_BUDGET_SHADOW_MODE y ENABLE_REPORTS.	Reduce complejidad.	Depende del roadmap.
7. Próximos pasos sugeridos

Validar el backlog con stakeholders (producto/marketplace) y crear issues individuales.

Incorporar smoke tests (mínimo GET) para cada blueprint activo en la suite CI.

Mantener este inventario vivo: actualizar la tabla cuando se agreguen o remuevan módulos.

Completar docs/ENV.md con estados de flags por entorno y la configuración final del marketplace una vez consolidado.

### Qué hacés ahora
1) En el editor de conflictos de GitHub, **reemplazá todo** el archivo por el bloque de arriba.  
2) Click en **Mark as resolved** → **Commit merge** para ese archivo.  
3) Decime el **siguiente archivo con conflicto** y te doy el contenido final listo para pegar.
