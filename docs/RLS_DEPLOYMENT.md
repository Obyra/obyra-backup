# Row Level Security (RLS) — Guía de despliegue

## ¿Qué es?

RLS es una capa de seguridad **a nivel de PostgreSQL** que filtra automáticamente las filas según el usuario actual. Es una **segunda línea de defensa** contra fugas multi-tenant: aunque un bug en el código olvide agregar `WHERE organizacion_id = X`, PostgreSQL devuelve cero filas en lugar de filas de otras organizaciones.

## Estado actual

- ✅ Migración Alembic creada: `migrations/versions/20260408_enable_row_level_security.py`
- ✅ Middleware Python creado: `middleware/rls_middleware.py`
- ❌ **NO está activado** todavía (deploy controlado)

## Por qué NO está activado todavía

Activar RLS sin antes verificar el middleware en producción puede **bloquear toda la app**. Si el middleware falla en setear `app.current_org_id`, todas las queries devolverían cero filas.

## Plan de activación segura (3 fases)

### Fase A — Despliegue del middleware (zero risk)

1. Pushear el middleware sin activar la migración
2. Integrarlo en `app.py`:
   ```python
   from middleware.rls_middleware import setup_rls_middleware
   setup_rls_middleware(app, db)
   ```
3. El middleware ejecuta `SET app.current_org_id = X` en cada checkout de conexión, pero como NO hay policies RLS aún, no afecta nada
4. Verificar en producción que la app sigue funcionando normal por 1-2 días

### Fase B — Aplicar la migración RLS

```bash
# En Railway o local con DATABASE_URL apuntando a prod:
alembic upgrade 202604080001
```

Esto crea las policies pero **NO bloquea nada** porque el middleware ya está seteando el contexto.

### Fase C — Verificación

1. Ingresar como usuario normal y verificar que ves SOLO tus datos (debería ser igual que antes)
2. Ingresar como super admin y verificar que ves todo
3. Si algo falla, rollback inmediato:
   ```bash
   alembic downgrade 202602260002
   ```

## Cómo testear localmente antes de prod

```bash
# 1. Conectar a la BD local
psql obyra_dev

# 2. Setear contexto manual
SET app.current_org_id = '5';
SET app.is_super_admin = 'false';

# 3. Verificar que solo ves obras de la org 5
SELECT id, nombre, organizacion_id FROM obras LIMIT 10;

# 4. Resetear contexto
RESET app.current_org_id;
RESET app.is_super_admin;

# 5. Verificar que ahora ves todas (porque current_org_id IS NULL = bypass)
SELECT id, nombre, organizacion_id FROM obras LIMIT 10;
```

## Comportamiento de las policies

Cada policy RLS sigue esta lógica:

```sql
CREATE POLICY tenant_isolation ON tabla
    USING (
        app_is_super_admin()                   -- Super admin: ve todo
        OR organizacion_id = app_current_org_id()  -- Usuario normal: solo su org
        OR app_current_org_id() IS NULL        -- Sin contexto (CLI/migrations): ve todo
    );
```

**El último OR es crítico**: permite que migrations, scripts CLI, y debugging funcionen normalmente. En producción, el middleware siempre setea el contexto, por lo que `app_current_org_id()` nunca es NULL desde una request HTTP.

## Limitaciones conocidas

1. **Tablas indirectas no protegidas**: `tareas_etapa`, `avances_tarea`, etc. NO tienen `organizacion_id`. La protección de estas tablas sigue dependiendo del código de aplicación.

2. **Performance**: Agrega un overhead de ~5% en las queries. Aceptable para el beneficio de seguridad.

3. **Conexiones del pool reusadas**: El middleware usa `checkout` event, que ejecuta cada vez que se saca una conexión del pool. Para conexiones reutilizadas dentro del mismo request, no se vuelve a ejecutar (lo cual está bien — el contexto ya está seteado).

## Tablas protegidas (30 totales)

**Con organizacion_id (22):**
audit_log, clientes, consultas_agente, cotizaciones_proveedor, cuadrillas_tipo, escala_salarial_uocra, global_material_usage, items_inventario, items_referencia_constructora, liquidaciones_mo, locations, movimientos_caja, notificaciones, obras, ordenes_compra, presupuestos, proveedores, proveedores_oc, remitos, requerimientos_compra, work_certifications, work_payments

**Con company_id (7):**
equipment, equipment_movement, events, inventory_category, inventory_item, order, warehouse

## Rollback de emergencia

Si después de activar RLS hay cualquier problema:

```bash
alembic downgrade 202602260002
```

Esto deshabilita RLS en todas las tablas inmediatamente. La app vuelve a funcionar como antes (sin la segunda capa de defensa, pero sigue protegida por el código de aplicación).
