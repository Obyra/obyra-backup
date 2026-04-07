# Migración: Índices faltantes en FKs

## ¿Qué hace?

La migración `20260408_add_missing_fk_indices.py` agrega ~45 índices a Foreign Keys que no los tenían. Esto mejora dramáticamente:

- **JOINs**: queries que conectan tablas se vuelven mucho más rápidas
- **DELETE**: eliminar un padre ya no tiene que escanear toda la tabla hija
- **Filtros**: queries `WHERE fk_id = X` usan el índice

## ¿Por qué es seguro?

1. **`CREATE INDEX IF NOT EXISTS`** — Si el índice ya existe, no falla ni duplica
2. **No toca código** — solo SQL DDL
3. **Verifica que la tabla y columna existan** antes de crear el índice
4. **Reversible** con `alembic downgrade`
5. **Idempotente** — podés correrla múltiples veces sin problema

## Cómo aplicarla

### Opción A — Railway (más simple)

Railway corre las migraciones automáticamente al hacer deploy si tenés `RUN_MIGRATIONS=true`. Verificalo:

1. Railway → tu servicio → Variables
2. Buscar `RUN_MIGRATIONS`
3. Si vale `true`, la migración corre sola en el próximo deploy
4. Si vale `false` o no existe, ejecutarla manualmente (ver abajo)

### Opción B — Manual desde tu máquina

```bash
# 1. Conectarte a la BD de Railway con su DATABASE_URL
export DATABASE_URL='postgresql://...railway...'
export ALEMBIC_DATABASE_URL=$DATABASE_URL

# 2. Ver el estado actual de migraciones
alembic current

# 3. Ver qué migraciones están pendientes
alembic history --indicate-current

# 4. Aplicar SOLO esta migración
alembic upgrade 202604080002

# Si todo OK, deberías ver muchos:
#   [OK] ix_presupuestos_obra_id
#   [OK] ix_tareas_etapa_etapa_id
#   ...
#   [INDICES] Completado: 45 creados, 0 skipped, 0 errores
```

### Opción C — Desde Railway CLI

```bash
railway run alembic upgrade 202604080002
```

## Cuánto tarda

Depende del tamaño de las tablas. Para una BD con:
- ~10K obras, ~100K tareas, ~500K avances: **~30-60 segundos total**
- BD pequeña (cientos de filas): **<5 segundos**

PostgreSQL crea los índices en una transacción que **bloquea writes brevemente** en cada tabla. Durante esos pocos segundos, los `INSERT/UPDATE/DELETE` esperan, pero los `SELECT` siguen funcionando normal.

## Si algo sale mal

Rollback en 1 comando:

```bash
alembic downgrade 202604080001
```

Esto elimina todos los índices creados. La app vuelve a funcionar como antes (sin el boost de performance).

## Cómo verificar que funcionó

Después de aplicar:

```sql
-- Conectarse a la BD y ejecutar:
SELECT indexname, tablename
FROM pg_indexes
WHERE indexname LIKE 'ix_%'
ORDER BY tablename, indexname;
```

Deberías ver los nuevos índices listados.

Para medir el impacto, antes y después correr una query típica con `EXPLAIN ANALYZE`:

```sql
EXPLAIN ANALYZE
SELECT * FROM tarea_avances
WHERE tarea_id = 12345;
```

Antes: probablemente `Seq Scan` (lento)
Después: `Index Scan using ix_tarea_avances_tarea_id` (rápido)

## Lista completa de índices que se crean

Ver el archivo `migrations/versions/20260408_add_missing_fk_indices.py`. Son ~45 índices en estas tablas:

- `presupuestos`, `items_presupuesto`, `niveles_presupuesto`
- `tareas_etapa`, `tarea_avances`, `tarea_adjuntos`, `tarea_miembros`, `tarea_responsables`
- `asignaciones_obra`, `obra_miembros`
- `fichadas`
- `movimientos_inventario`, `uso_inventario`
- `notificaciones`
- `equipment_assignment`, `equipment_usage`, `maintenance_task`
- `usuarios`
- `stock`, `stock_ubicacion`
- `org_memberships`
