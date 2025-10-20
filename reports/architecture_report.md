# Obyra – Architecture Field Report

## Scope and methodology
- **Branch analysed:** current working tree (HEAD)
- **Techniques:** static inspection with `rg`, custom AST parsers, and `git log` history. Command excerpts are stored under `reports/evidence/`.
- **Limitations:** runtime code paths behind feature flags (`ENABLE_REPORTS_SERVICE`, marketplace feature toggles) were not executed; conclusions rely on import graphs and registration logic.
- **Assumptions:** a blueprint is considered **active** when it is registered in `app.py` under normal configuration; modules never imported or mapped by the bootstrap are treated as **legacy**.

## Decisiones de arquitectura

| Dominio | Activo | Legacy / Experimental | Evidencia | Plan de migración |
|---------|--------|-----------------------|-----------|-------------------|
| Inventario | `inventario_new` registrado como `/inventario-new` y destino de los redirects heredados | `inventario` sigue expuesto en `/inventario` para compatibilidad | Registro y redirecciones en el bootstrap【F:reports/evidence/app_blueprint_registration.txt†L23-L109】 | Consolidar navegación hacia `/inventario-new`, retirar plantillas legacy y apagar el blueprint antiguo tras monitorear métricas |
| Equipos | `equipos_new` disponible como `/equipos-new` | `equipos` mantiene la UI histórica en `/equipos` | Bloque opcional de blueprints nuevos frente al listado core del arranque【F:reports/evidence/app_blueprint_registration.txt†L23-L109】 | Migrar plantillas y enlaces a `/equipos-new`, revisar permisos y eliminar gradualmente la versión legacy |
| Marketplace | `marketplace.routes` es el único blueprint registrado en la app pública | `marketplace_new` y `marketplace.py` no se importan en el arranque; `marketplace_new` persiste como experimento | Registro explícito del blueprint activo y ausencia de import del alternativo, solo rutas internas en el módulo nuevo【F:reports/evidence/app_blueprint_registration.txt†L114-L133】【F:reports/evidence/marketplace_new_usage.txt†L1-L48】 | Mantener `marketplace.routes` endurecido y archivar el stack “_new” en carpeta legacy antes de eliminarlo |
| Asistente | `asistente_ia` continúa registrado para `/asistente` | `asistente_ia_backup` declara un blueprint homónimo sin registrarse | Lista de blueprints cargados vs. inventario bruto de definiciones duplicadas【F:reports/evidence/app_blueprint_registration.txt†L23-L42】【F:reports/evidence/blueprints_raw.txt†L3-L18】 | Confirmar que ningún entorno importa el backup, respaldar plantillas y remover duplicado |

## Blueprint catalogue

| Blueprint (module) | Type | URL prefix | Responsibility | Service deps | Evidence |
|--------------------|------|------------|----------------|--------------|----------|
| `auth_bp` (`auth.py`) | Core active | `/auth` | Authentication, password reset, Google OAuth | `services.email_service`, `services.memberships` | `app.py` registration block; service imports in `auth.py`【F:reports/evidence/app_blueprint_registration.txt†L1-L55】【F:reports/evidence/blueprint_service_imports.txt†L1-L1】 |
| `obras_bp` (`obras.py`) | Core active | `/obras` | Project/works catalogue CRUD | — | Registration list in `app.py`【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `presupuestos_bp` (`presupuestos.py`) | Core active | `/presupuestos` | Budget workflows, IA calculator, geo helpers | Exchange, CAC, geocoding, memberships services | `app.py` register; imports in `presupuestos.py`【F:reports/evidence/app_blueprint_registration.txt†L25-L55】【F:reports/evidence/blueprint_service_imports.txt†L5-L5】 |
| `equipos_bp` (`equipos.py`) | Core active | `/equipos` | Equipment catalogue legacy UI | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `inventario_bp` (`inventario.py`) | Core active | `/inventario` | Inventory management legacy UI | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `marketplaces_bp` (`marketplaces.py`) | Core active | `/marketplaces` | Marketplace admin dashboards (legacy) | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `reportes_bp` (`reportes.py`) | Core active | `/reportes` | Web reporting module | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `asistente_bp` (`asistente_ia.py`) | Core active | `/asistente` | IA assistant redirectors | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `cotizacion_bp` (`cotizacion_inteligente.py`) | Core active | `/cotizacion` | Intelligent quote helper | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `documentos_bp` (`control_documentos.py`) | Core active | `/documentos` | Document control workflows | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `seguridad_bp` (`seguridad_cumplimiento.py`) | Core active | `/seguridad` | Compliance and safety checks | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `agent_bp` (`agent_local.py`) | Core active | none | Local agent utilities | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `planes_bp` (`planes.py`) | Core active | none | Subscription plans | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `events_bp` (`events_service.py`) | Core active | none | Event tracking endpoints | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `account_bp` (`account.py`) | Core active | none | Account configuration | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `onboarding_bp` (`onboarding.py`) | Core active | `/onboarding` | New-user onboarding wizard | — | `app.py` register list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| `reports_service_bp` (`reports_service.py`) | Conditional | none | PDF/CSV generation service | Depends on `matplotlib` at runtime | Feature flag in `app.py`【F:reports/evidence/app_blueprint_registration.txt†L57-L76】 |
| `equipos_new_bp` (`equipos_new.py`) | Conditional | `/equipos-new` | Revamped equipment UI | — | Optional block in `app.py`【F:reports/evidence/app_blueprint_registration.txt†L78-L116】 |
| `inventario_new_bp` (`inventario_new.py`) | Conditional | `/inventario-new` | Revamped inventory UI | — | Optional block in `app.py`【F:reports/evidence/app_blueprint_registration.txt†L78-L116】 |
| `supplier_auth_bp` (`supplier_auth.py`) | Conditional | `/proveedor` | Supplier authentication | — | Supplier block in `app.py`【F:reports/evidence/app_blueprint_registration.txt†L118-L135】 |
| `supplier_portal_bp` (`supplier_portal.py`) | Conditional | `/proveedor` | Supplier portal UI | — | Supplier block in `app.py`【F:reports/evidence/app_blueprint_registration.txt†L118-L135】 |
| `market_bp` (`market.py`) | Conditional | `/market` | Supplier-facing marketplace | — | Supplier block in `app.py`【F:reports/evidence/app_blueprint_registration.txt†L118-L135】 |
| `marketplace_bp` (`marketplace/routes.py`) | Conditional | `/` | Public marketplace API | — | Marketplace block in `app.py`【F:reports/evidence/app_blueprint_registration.txt†L137-L150】 |
| `payments_bp` (`marketplace_payments.py`) | Legacy | none | Mercado Pago webhook & preference helpers (not wired) | Uses `mercadopago.SDK` | No registration in `app.py`, search output empty【F:reports/evidence/marketplace_payments_usage.txt†L1-L1】 |
| `marketplace_new_bp` (`marketplace_new.py`) | Legacy | none | Alternate marketplace UI (never imported) | — | No imports found outside file【F:reports/evidence/marketplace_new_usage.txt†L1-L21】 |
| `marketplace_bp` (`marketplace.py`) | Legacy | `/market` | Older marketplace implementation duplicated | — | Not registered in `app.py`; `git log` shows stale history【F:reports/evidence/app_blueprint_registration.txt†L118-L135】【F:reports/evidence/git_last_commit.txt†L3-L7】 |
| `asistente_bp` (`asistente_ia_backup.py`) | Legacy | `/asistente` | Outdated assistant blueprint | — | No references in bootstrap; duplicate name | Evidence from absence in registration list【F:reports/evidence/app_blueprint_registration.txt†L25-L55】 |
| Additional duplicates (`main.py`, `main_app.py`, `app_old.py`) | Legacy apps | — | Historical entry points | — | Search results show no current imports【F:reports/evidence/app_old_usage.txt†L1-L3】 |

## Services overview

`services/` hosts task-specific helpers. Active integrations are identified by import usage inside blueprints (see `reports/evidence/blueprint_service_imports.txt`).

| Module | Purpose | Blueprint consumers | Status |
|--------|---------|---------------------|--------|
| `services.email_service` | Password/reset mail delivery | `auth_bp` | Active |
| `services.memberships` | Org and membership management | `auth_bp`, `presupuestos_bp` | Active |
| `services.exchange.base` & providers | FX conversion | `presupuestos_bp` | Active |
| `services.cac.cac_service` | Construction cost index | `presupuestos_bp` | Active |
| `services.geocoding_service` | Address geocoding | `presupuestos_bp` | Active |
| `services.wizard_budgeting` | Budget wizard calculations | Imported by `presupuestos.py` (backlog of new calculator) | Active (IA calculator) |
| `services.alerts`, `services.certifications`, `services.po_service` | No direct blueprint imports detected | Likely background/legacy utilities – requires confirmation | Candidate review |

## Data model inventory

`models.py` aggregates most ORM definitions (see `reports/evidence/models_classes.txt`). Satellite schemas live in `models_inventario.py`, `models_equipos.py`, and `models_marketplace.py`.

- **Active models:** Entities referenced by active blueprints (`Presupuesto`, `Usuario`, `Organizacion`, `Equipo`, `InventarioItem`, `MarketplaceProduct`, etc.).
- **Legacy/duplicate models:** Marketplace tables defined both in `models_marketplace.py` and `marketplace/models.py`, plus legacy equipment/inventory variants. The `git log` evidence shows long periods without updates, suggesting stale modules.【F:reports/evidence/git_last_commit.txt†L8-L14】

## Candidatos a deprecación

### Remoción rápida (Low risk, S/M)

| Módulo | Evidencia | Paso siguiente |
|--------|-----------|----------------|
| `marketplace_new.py` | Solo declara rutas internas; no aparece en el bootstrap principal | Respaldar plantillas `marketplace_new/*` y archivar módulo antes de eliminación definitiva【F:reports/evidence/marketplace_new_usage.txt†L1-L48】 |
| `marketplace_payments.py` | Webhooks y vistas asociadas al stack “_new”, sin registro en `app.py` | Confirmar ausencia de webhooks configurados y eliminar blueprint junto con templates antiguos【F:reports/evidence/marketplace_payments_usage.txt†L1-L9】 |
| `asistente_ia_backup.py` | Blueprint duplicado (`asistente`) detectado en inventario crudo pero no en el registro de arranque | Mover plantillas a un respaldo y borrar módulo para evitar confusión entre equipos【F:reports/evidence/app_blueprint_registration.txt†L23-L42】【F:reports/evidence/blueprints_raw.txt†L3-L18】 |

### Refactor por fases (Med risk, M/L)

| Módulo | Evidencia | Paso siguiente |
|--------|-----------|----------------|
| `inventario.py` | Sigue registrado en `/inventario` y consume servicios críticos pese a redirigir al módulo nuevo | Retirar gradualmente vistas legacy tras mover enlaces y cubrir redirecciones con pruebas automatizadas【F:reports/evidence/app_blueprint_registration.txt†L23-L109】【F:reports/evidence/blueprint_service_imports.txt†L1-L16】 |
| `equipos.py` | Blueprint legacy aún registrado y con dependencias de memberships | Migrar flujos de roles/permisos a `equipos_new` y despublicar formularios heredados por etapas【F:reports/evidence/app_blueprint_registration.txt†L23-L109】【F:reports/evidence/blueprint_service_imports.txt†L1-L16】 |
| `marketplace.py` | Código antiguo de marketplace con historial extenso pero sin registro actual | Revisar scripts externos y consolidar lógica activa en `marketplace/routes.py` antes de retirar archivo【F:reports/evidence/app_blueprint_registration.txt†L114-L133】【F:reports/evidence/git_last_commit.txt†L1-L9】 |

### Mantener / estabilizar (High usage)

| Módulo | Evidencia | Paso siguiente |
|--------|-----------|----------------|
| `inventario_new.py` | Blueprint activo con redirects heredados; último commit reciente | Completar QA de regresión y publicar guía de adopción para equipos internos【F:reports/evidence/app_blueprint_registration.txt†L85-L109】【F:reports/evidence/git_last_commit.txt†L11-L22】 |
| `equipos_new.py` | Registrado junto al stack legacy para nuevas rutas de mantenimiento | Revisar permisos y almacenamiento de adjuntos antes de retirar la versión antigua【F:reports/evidence/app_blueprint_registration.txt†L85-L133】【F:reports/evidence/git_last_commit.txt†L1-L22】 |
| `marketplace/routes.py` | Único blueprint público cargado en `app.py` | Mantener monitoreo y endurecer contratos externos antes de futuras refactorizaciones【F:reports/evidence/app_blueprint_registration.txt†L114-L133】【F:reports/evidence/git_last_commit.txt†L1-L9】 |

## Route and dependency diagrams

- `reports/routes_diagram.svg`: simplified view linking the Flask app to representative blueprints, their key endpoints, and the service layer touchpoints.
- `reports/dependencies_graph.svg`: condensed module import graph emphasising marketplace duplication and helper modules used exclusively by legacy stacks.

## Backlog of modules to rationalise

Detailed JSON under `reports/backlog_modules.json`. Highlights:

1. **`inventario.py`** – mantener mientras se completan migraciones hacia `/inventario-new`, luego retirar blueprint legacy.
2. **`equipos.py`** – duplicado del stack nuevo; requiere plan de apagado por fases validando roles/permisos.
3. **`marketplace/routes.py`** – módulo activo de alto impacto; documentar contratos y endurecer monitoreo antes de cambios.
4. **`marketplace_new.py` y `marketplace_payments.py`** – candidatos a archivo rápido tras confirmar ausencia de webhooks.
5. **Servicios sin consumidores (`alerts`, `certifications`, `po_service`)** – verificar uso en jobs antes de eliminar dependencias.

Each backlog item includes rationale, impact, priority, effort, risk, and next steps.【F:reports/backlog_modules.json†L1-L106】

## Evidence bundle

All supporting commands (registration snippet, git history, usage searches) reside in `reports/evidence/` for auditability.

## Confidence & follow-up
- **Confidence:** Medium — based on static analysis of registrations and imports; runtime feature flags may hide additional consumers.
- **Follow-up:** Validate marketplace feature toggles in staging, confirm whether background workers load legacy services, and schedule clean-up iterations per backlog priorities.
