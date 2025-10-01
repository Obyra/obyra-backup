# QA & Smoke Test Checklist

## Antes de activar cualquier flag
- [ ] Aplicar migraciones `migrations/expand_v2.sql` en entorno objetivo.
- [ ] Verificar que los servicios legacy (login, obras, inventario) siguen operativos.
- [ ] Confirmar que `FF_*` están en `false` en `.env` o base de datos.

## FF_ANALYTICS / FF_AUDIT_LOG
- [ ] Activar flag sólo en staging/canario.
- [ ] Generar eventos (crear obra, mover inventario) y validar inserción en `analytics_events` y `audit_log`.
- [ ] Confirmar que respuesta HTTP no cambia (comparar status/latencia con flag OFF).
- [ ] Revisar dashboards (PostHog/SQL) para confirmar recepción de eventos.

## FF_SUPPLIERS
- [ ] Ejecutar script `seed_demo_supplier_flow.py` en staging.
- [ ] Consumir endpoints `/api/v2/suppliers` (crear, listar, actualizar) con OpenAPI.
- [ ] Validar que UI legacy sigue sin cambios.

## FF_BILLING
- [ ] Configurar sandbox PSP y variables (`PSP_PUBLIC_KEY`, `PSP_SECRET_KEY`).
- [ ] Registrar método de pago tokenizado (`POST /api/v2/billing/payment-method`).
- [ ] Crear suscripción (`POST /api/v2/billing/subscribe`).
- [ ] Simular ciclo de facturación y revisar tablas `subscriptions`, `payment_methods`.

## FF_PO
- [ ] Crear PO (`POST /api/v2/po`).
- [ ] Confirmar desde proveedor (`PATCH /api/v2/po/:id/confirm`).
- [ ] Registrar entrega parcial (`POST /api/v2/po/:id/deliveries`).
- [ ] Validar que wizard/obras v1 siguen operativos.

## Rollback Smoke
- [ ] Apagar flag y repetir operaciones legacy para asegurar estabilidad.
- [ ] Monitorear logs/alertas durante 1h posterior.

