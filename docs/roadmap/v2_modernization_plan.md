# OBYRA Modernización Incremental – Plan Integral

## Principios Clave
- **No tocar lo que funciona**: todas las iteraciones siguen el patrón *expand → migrate → switch reads → contract*. No se eliminan rutas v1 ni se renombra código crítico hasta después de 30–60 días estables.
- **Cambios aditivos primero**: nuevas tablas, servicios y módulos se agregan en paralelo y se protegen con *feature flags* por módulo y tenant.
- **Versionado de APIs**: los nuevos servicios viven en `/api/v2/`, mientras `/api/v1/` continúa sin modificaciones.
- **Flags por entorno y tenant**: `FF_SUPPLIERS`, `FF_BILLING`, `FF_ANALYTICS`, `FF_PO` se almacenan en configuración y base de datos para activar gradualmente capacidades.
- **Rollback inmediato**: apagar un flag revierte cualquier funcionalidad nueva sin afectar la operación legacy.

## Sprint Breakdown

### Sprint A — Infraestructura mínima (Expand)
- Crear tablas nuevas (sin FKs intrusivas, usar UUIDs con restricciones diferibles):
  - `suppliers`, `supplier_users`, `products`, `product_prices`, `purchase_orders`, `purchase_order_items`, `subscriptions`, `payment_methods`, `analytics_events`, `audit_log`.
- Registrar *feature flags* en tabla `feature_flags` (tenant aware) y variables de entorno.
- Añadir cron jobs “no-op” (`cron_billing`, `cron_dunning`, `cron_payouts`) desactivados.
- Objetivo: despliegue sin cambios visibles en la UX.

### Sprint B — Observabilidad sombra
- Activar `FF_ANALYTICS` sólo en staging/canario.
- Middleware `emit_analytics` registra eventos en `analytics_events` (shadow write); no altera respuestas.
- `audit_log` almacena acciones clave (crear obra, tarea, movimientos inventario) en modo append-only.
- Configurar dashboards PostHog/SQL para seguimiento de métricas.

### Sprint C — Perfil de proveedores (solo lectura + carga interna)
- Implementar `/api/v2/suppliers` CRUD para founders.
- UI oculta detrás de `FF_SUPPLIERS`; sin exposición para clientes legacy.
- Carga de proveedores y catálogos (manual + CSV) en staging.

### Sprint D — Suscripción & pagos
- Endpoints `/api/v2/billing` para métodos de pago, suscripciones, invoices.
- Integración PSP tokenizada (SAQ-A); no bloquear flujo legacy.
- `FF_BILLING` sólo ON en staging hasta completar QA.

### Sprint E — Purchase Orders (PO)
- `/api/v2/po` para creación por empresa y confirmación proveedor.
- `FF_PO` controla visibilidad completa.
- Mantener wizard y flujo de obras v1 sin cambios.

### Sprint F — Encendido gradual
- Activar flags por tenant (canarios → cohortes).
- Monitorear 24–48h con métricas de error/latencia.
- Documentar métricas OK antes de expandir.

## Feature Flags
| Flag | Descripción | Default Prod | Activación |
|------|-------------|--------------|------------|
| `FF_ANALYTICS` | Middleware analytics sombra | `false` | Staging y tenant canario |
| `FF_AUDIT_LOG` | Registro audit log (si se desea separado) | `false` | Se activa junto a analytics |
| `FF_SUPPLIERS` | UI/API proveedores | `false` | Post Sprint C |
| `FF_BILLING` | Suscripciones/pagos | `false` | Post Sprint D |
| `FF_PO` | Módulo de órdenes de compra | `false` | Post Sprint E |

### Flags en `.env`
```
FF_ANALYTICS=false
FF_AUDIT_LOG=false
FF_SUPPLIERS=false
FF_BILLING=false
FF_PO=false
```

### Flags por tenant (tabla `feature_flags`)
| Campo | Tipo |
|-------|------|
| `id` | UUID PK |
| `tenant_id` | UUID |
| `flag` | TEXT |
| `enabled` | BOOLEAN |
| `enabled_at` | TIMESTAMPTZ |
| `metadata` | JSONB |

## Migraciones (Expand)
Ejemplo inicial (`migrations/expand_v2.sql`):
```sql
CREATE TABLE IF NOT EXISTS suppliers (
    id UUID PRIMARY KEY,
    organization_id UUID,
    name TEXT NOT NULL,
    tax_id TEXT,
    country_code TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supplier_users (
    id UUID PRIMARY KEY,
    supplier_id UUID REFERENCES suppliers(id) DEFERRABLE INITIALLY DEFERRED,
    user_id UUID,
    role TEXT NOT NULL,
    invited_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY,
    supplier_id UUID REFERENCES suppliers(id) DEFERRABLE INITIALLY DEFERRED,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    unit_of_measure TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product_prices (
    id UUID PRIMARY KEY,
    product_id UUID REFERENCES products(id) DEFERRABLE INITIALLY DEFERRED,
    currency TEXT NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id UUID PRIMARY KEY,
    organization_id UUID,
    supplier_id UUID,
    status TEXT NOT NULL,
    total_amount NUMERIC(14,2),
    currency TEXT,
    requested_at TIMESTAMPTZ,
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id UUID PRIMARY KEY,
    purchase_order_id UUID REFERENCES purchase_orders(id) DEFERRABLE INITIALLY DEFERRED,
    product_id UUID,
    quantity NUMERIC(12,2) NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL,
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY,
    organization_id UUID,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payment_methods (
    id UUID PRIMARY KEY,
    organization_id UUID,
    provider TEXT NOT NULL,
    token TEXT NOT NULL,
    last4 TEXT,
    brand TEXT,
    exp_month INT,
    exp_year INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analytics_events (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    event_name TEXT NOT NULL,
    payload JSONB,
    occurred_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id UUID,
    payload JSONB,
    occurred_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feature_flags (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    flag TEXT NOT NULL,
    enabled BOOLEAN NOT NULL,
    enabled_at TIMESTAMPTZ,
    metadata JSONB
);
```

## Migraciones (Migrate / Backfill)
- Scripts idempotentes en `tools/backfill/` (ver ejemplo `backfill_suppliers.py`) para copiar datos legacy a tablas v2 sin bloquear.
- Dual-write controlado por flag `FF_DUALWRITE` (opcional) dentro de servicios v1.

## Observabilidad y QA
- Alarmas suaves: `error_rate > 2%`, `p95_response_time > 1.5s`, `job_failures > 0`.
- *Smoke tests* antes de encender cada flag:
  1. Login y CRUD obras/tareas.
  2. Inventario: crear item, registrar movimiento.
  3. Reportes v1.
  4. Wizard IA.
  5. Middleware analytics en staging (verificar inserciones sombra).

## Rollout y Rollback
- **Rollout**: activar flag por tenant, monitorear 48h, documentar métricas y feedback antes de expandir.
- **Rollback**: apagar flag correspondiente, pausar crons relacionados, monitorear que tablas v2 queden sin writes.
- **Post estabilización**: limpieza (contract) sólo tras 30–60 días.

## Artefactos Incluidos
- OpenAPI v2 (`docs/api/v2_platform.yaml`).
- Scripts de seed (`tools/seeds/seed_demo_supplier_flow.py`).
- Snippets de middleware (`services/middleware/snippets.py`).
- Checklist QA (`docs/roadmap/qa_checklist.md`).

## Próximos Pasos
1. Ejecutar migración `expand_v2.sql` en staging.
2. Incorporar los middlewares con flags y verificar shadow writes.
3. Cargar proveedor demo usando script de seed.
4. Validar flujo completo con OpenAPI en Postman/Insomnia.
5. Documentar resultados y preparar Sprint B.

