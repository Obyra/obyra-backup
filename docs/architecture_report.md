# OBYRA · Mapeo funcional y backlog de racionalización

## 1. Resumen ejecutivo
- La aplicación principal (`app.py`) registra 18 blueprints núcleo más un conjunto de módulos opcionales ligados al portal de proveedores y al marketplace.
- Existen implementaciones duplicadas/legacy (`app_old.py`, `marketplace_new.py`, `marketplace.py`) que conviven con la versión actual sin estar registradas o siendo referenciadas sólo por scripts auxiliares.
- Los modelos siguen centralizados en `models.py`, mientras que archivos como `models_inventario.py` o `models_equipos.py` permanecen desconectados del flujo actual.
- El ecosistema de servicios (carpeta `services/`) cubre casos de uso de membresías, reportes, pricing y CAC, pero varios módulos no se integran con los blueprints activos.

## 2. Blueprints registrados desde `app.py`
| Blueprint (`endpoint`) | Módulo | Prefijo | Estado | Observaciones |
| --- | --- | --- | --- | --- |
| `auth` | `auth.py` | `/auth` | Activo | Depende de `auth.oauth.init_app`; se provee fallback si falla la importación. |
| `obras_bp` | `obras.py` | `/obras` | Activo | Módulo monolítico con vistas y lógica mezclada. |
| `presupuestos_bp` | `presupuestos.py` | `/presupuestos` | Activo | Blueprint extenso; depende de modelos en `models.py`. |
| `equipos_bp` | `equipos.py` | `/equipos` | Activo | Interfaz clásica para gestión de equipos. |
| `inventario_bp` | `inventario.py` | `/inventario` | Activo | Complementado por la variante "new" (ver opcionales). |
| `marketplaces_bp` | `marketplaces.py` | `/marketplaces` | Activo | Catálogo público legacy. |
| `reportes_bp` | `reportes.py` | `/reportes` | Activo | Dashboard de reportes HTML. |
| `asistente_bp` | `asistente_ia.py` | `/asistente` | Activo | Enrutador mínimo al asistente IA. |
| `cotizacion_bp` | `cotizacion_inteligente.py` | `/cotizacion` | Activo | Cotizaciones inteligentes. |
| `documentos_bp` | `control_documentos.py` | `/documentos` | Activo | Gestión documental. |
| `seguridad_bp` | `seguridad_cumplimiento.py` | `/seguridad` | Activo | Contiene formularios de cumplimiento. |
| `agent_bp` | `agent_local.py` | *(sin prefijo)* | Activo | Endpoint auxiliar para agentes locales. |
| `planes_bp` | `planes.py` | *(sin prefijo)* | Activo | Suscripciones/planes. |
| `events_bp` | `events_service.py` | *(sin prefijo)* | Activo | API para eventos del marketplace; usa `current_app`. |
| `account_bp` | `account.py` | *(sin prefijo)* | Activo | Gestión de cuenta/usuario final. |
| `onboarding_bp` | `onboarding.py` | `/onboarding` | Activo | Flujo de onboarding. |
| `reports_service_bp` | `reports_service.py` | *(sin prefijo)* | Opcional | Sólo se registra si `ENABLE_REPORTS=1` y `matplotlib` está disponible. |
| `equipos_new_bp` | `equipos_new.py` | `/equipos-new` | Opcional | Redirecciones desde `/inventario/*` apuntan aquí cuando se carga. |
| `inventario_new_bp` | `inventario_new.py` | `/inventario-new` | Opcional | Nueva UI de inventario; se registran redirects desde rutas legacy. |
| `supplier_auth_bp` | `supplier_auth.py` | *(sin prefijo)* | Opcional | Portal de proveedores; depende de módulos `supplier_portal` y `market`. |
| `supplier_portal_bp` | `supplier_portal.py` | *(sin prefijo)* | Opcional | Portal de proveedores. |
| `market_bp` | `market.py` | `/market` | Opcional | Portal público orientado a proveedores. |
| `marketplace_bp` | `marketplace/routes.py` | `/` | Opcional | API REST/JSON del marketplace "nuevo"; convive con plantillas legacy. |

### Blueprints legacy/no registrados
| Blueprint | Módulo | Estado | Riesgo |
| --- | --- | --- | --- |
| `marketplace_new_bp` | `marketplace_new.py` | No registrado | Implementa marketplace completo (UI + pagos) pero no se importa desde `app.py`. Plantillas bajo `templates/marketplace_new/`. |
| `marketplace_bp` (legacy UI) | `marketplace.py` | No registrado | Versión legacy del marketplace público. |
| Vistas antiguas | `app_old.py`, `main.py`, `main_app.py` | No registrados | Aún poseen `db.create_all()` y rutas duplicadas; generan deuda técnica. |

## 3. Servicios y utilitarios
- **`services/memberships.py`**: inicialización de sesión de membresía, hooks `g`. Usado directamente en `app.py`.
- **`services/alerts.py`, `services/email_service.py`, `services/geocoding_service.py`**: funciones auxiliares llamadas desde blueprints.
- **`services/wizard_budgeting.py`**: lógica del nuevo presupuestador (en pruebas, activado por `WIZARD_BUDGET_*`).
- **`services/po_service.py`**: depende de `models_marketplace`; da soporte a órdenes del marketplace.
- **Paquetes `services/cac` y `services/pricing`**: lógica aislada sin integración evidente en `app.py`; requieren evaluación para confirmar uso real.

## 4. Modelos y capas de datos
- **`models.py`**: define la mayoría de entidades (usuarios, organizaciones, presupuestos, marketplace básico). Presenta constraints duplicados y relaciones densas.
- **`models_marketplace.py`**: esquema extendido del marketplace (products, orders, payments). Referenciado por `marketplace_payments.py`, `marketplace_new.py`, `services/po_service.py` e `init_marketplace.py`.
- **`models_inventario.py`, `models_equipos.py`**: no aparecen importados desde `app.py` ni blueprints activos; candidatos a limpieza si se confirma desuso.
- **`obras.py`, `presupuestos.py`, `inventario.py`**: mezclan modelos inline con vistas (ej. `class Presupuesto(db.Model)` declarada en `presupuestos.py`). Conviene moverlos a módulos dedicados.

## 5. Rutas y dependencias destacadas
- **Autenticación**: `auth_bp` (si disponible) gestiona OAuth; `supplier_auth` provee login alternativo. `login_manager` resuelve rutas dinámicamente.
- **Reportes**: `reportes_bp` renderiza dashboards; `reports_service_bp` expone endpoints JSON/descargas condicionados por flag.
- **Marketplace**: coexistencia de `marketplace/routes.py` (API) y `marketplace_new.py` (UI + SDK Mercado Pago) sin registro oficial. `marketplace_payments.py` provee callbacks para pagos.
- **Inventario**: versiones "legacy" (`inventario_bp`) y "new" (`inventario_new_bp`) convivientes con redirects.
- **Asistente IA**: rutas simples que delegan a `asistente_ia`/`asistente_ia_backup`.

## 6. Backlog recomendado (deuda técnica)
1. **Depurar marketplace duplicado**
   - Confirmar qué blueprint debe permanecer (`marketplace/routes.py` vs `marketplace_new.py`) y eliminar el resto.
   - Consolidar uso de `models_marketplace` y retirar `marketplace.py` legacy.
2. **Retirar aplicaciones legacy**
   - `app_old.py`, `main.py`, `main_app.py`, `marketplace_new.py` (si se desactiva) y scripts `*_new.py` sin references.
3. **Modularizar modelos**
   - Migrar definiciones inline (p.ej. en `presupuestos.py`) a paquetes `models/` especializados.
   - Eliminar `models_inventario.py` y `models_equipos.py` si se confirma falta de uso.
4. **Refactor de servicios**
   - Revisar `services/cac`, `services/pricing`, `events_service` para validar endpoints activos.
   - Documentar dependencias externas (Mercado Pago, Google OAuth) en un README técnico.
5. **Diagramar rutas**
   - Generar un diagrama (Mermaid/Draw.io) a partir de la tabla anterior para comunicar la arquitectura.
   - Incorporar la definición al pipeline de documentación (`docs/`).

## 7. Próximos pasos sugeridos
- Establecer un proceso de baja controlada de módulos legacy (issue tracker con impacto y métricas).
- Configurar pruebas de smoke automáticas por blueprint (mínimo `GET /<prefix>`).
- Mantener inventario actualizado en cada release (este documento sirve como base viva).
