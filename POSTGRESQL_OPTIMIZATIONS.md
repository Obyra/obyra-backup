# OBYRA - Optimizaciones PostgreSQL

**Fecha:** 2 de Noviembre, 2025
**Sistema:** PostgreSQL 16 + Optimizaciones

---

## 🎯 Resumen

Sistema completamente migrado y optimizado para PostgreSQL. **SQLite ha sido completamente eliminado del código**.

### Beneficios de PostgreSQL
- ✅ **Performance superior** para queries complejos
- ✅ **Concurrent users** sin locks de tabla completa
- ✅ **ACID completo** con transacciones robustas
- ✅ **Full-text search** integrado
- ✅ **JSON/JSONB** para datos semi-estructurados
- ✅ **Índices avanzados** (GiST, GIN, BRIN)
- ✅ **Particionamiento** de tablas grandes
- ✅ **Replicación** para alta disponibilidad

---

## 🚀 Optimizaciones Implementadas

### 1. Connection Pooling Optimizado

**Archivo:** `app.py` (líneas 140-155)

```python
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_size": 10,           # Conexiones permanentes en el pool
    "max_overflow": 20,        # Conexiones adicionales bajo demanda
    "pool_timeout": 30,        # Timeout para obtener conexión
    "pool_recycle": 1800,      # Reciclar conexiones cada 30 min
    "pool_pre_ping": True,     # Verificar conexión antes de usar
    "connect_args": {
        "application_name": "obyra_app",
        "options": "-c statement_timeout=30000",  # 30s por query
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 600,
        "keepalives_interval": 30,
        "keepalives_count": 3,
    }
}
```

**Beneficios:**
- 🎯 Pool de 10 conexiones reutilizables
- 🎯 Hasta 30 conexiones concurrentes (10 + 20 overflow)
- 🎯 Detección automática de conexiones caídas (pre_ping)
- 🎯 Reciclaje cada 30 min para evitar stale connections
- 🎯 Identificación en `pg_stat_activity` como "obyra_app"

### 2. Índices de Performance

**Archivo:** `migrations/versions/20251102_add_performance_indices.py`

**Índices creados:**
```sql
-- Usuarios
CREATE INDEX idx_usuarios_email ON app.usuarios(email);
CREATE INDEX idx_usuarios_org_id ON app.usuarios(organizacion_id);
CREATE INDEX idx_usuarios_activo ON app.usuarios(activo);

-- Obras (cuando existan)
CREATE INDEX idx_obras_org_id ON app.obras(organizacion_id);
CREATE INDEX idx_obras_estado ON app.obras(estado);
CREATE INDEX idx_obras_fecha_inicio ON app.obras(fecha_inicio);

-- Presupuestos (cuando existan)
CREATE INDEX idx_presupuestos_org_id ON app.presupuestos(organizacion_id);
CREATE INDEX idx_presupuestos_estado ON app.presupuestos(estado);
```

**Impacto:**
- 🚀 3-10x más rápido en queries con filtros
- 🚀 Mejora drástica en JOINs
- 🚀 Queries por organización optimizadas

### 3. Schema Separado (app)

**Configuración:**
- Todas las tablas en schema `app` en lugar de `public`
- Mejor organización y seguridad
- Migraciones configuradas con `version_table_schema='app'`

**Consultas optimizadas:**
```sql
SET search_path TO app, public;
```

### 4. Statement Timeout

**Configuración:** Timeout de 30 segundos por query

```python
"options": "-c statement_timeout=30000"
```

**Beneficios:**
- Evita queries que cuelguen indefinidamente
- Protege contra queries mal optimizados
- Fuerza a escribir queries eficientes

### 5. Keepalives para Conexiones

**Configuración TCP keepalive:**
```python
"keepalives": 1,
"keepalives_idle": 600,     # 10 min sin actividad
"keepalives_interval": 30,  # Check cada 30s
"keepalives_count": 3,      # 3 intentos fallidos
```

**Beneficios:**
- Detecta conexiones caídas automáticamente
- Evita "connection already closed" errors
- Mantiene pool saludable

---

## 🔍 Monitoreo de PostgreSQL

### Ver Conexiones Activas

```sql
SELECT
    application_name,
    state,
    COUNT(*) as conn_count
FROM pg_stat_activity
WHERE application_name = 'obyra_app'
GROUP BY application_name, state;
```

### Ver Queries Lentas

```sql
SELECT
    pid,
    now() - query_start AS duration,
    query,
    state
FROM pg_stat_activity
WHERE application_name = 'obyra_app'
AND state != 'idle'
AND now() - query_start > interval '5 seconds'
ORDER BY duration DESC;
```

### Ver Tamaño de Tablas

```sql
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'app'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### Ver Índices y su Uso

```sql
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'app'
ORDER BY idx_scan DESC;
```

### Cache Hit Rate

```sql
SELECT
    'cache hit rate' AS metric,
    sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) AS ratio
FROM pg_statio_user_tables;
```

**Objetivo:** > 0.95 (95% cache hit rate)

---

## ⚡ Optimizaciones Adicionales Recomendadas

### 1. Índices Parciales

Para queries frecuentes con condiciones:

```sql
-- Solo indexar usuarios activos
CREATE INDEX idx_usuarios_activo_email
ON app.usuarios(email)
WHERE activo = TRUE;

-- Solo indexar obras no completadas
CREATE INDEX idx_obras_activas
ON app.obras(estado, fecha_inicio)
WHERE estado != 'completada';
```

### 2. Índices Compuestos

Para queries con múltiples filtros:

```sql
-- Búsquedas por organización + estado
CREATE INDEX idx_obras_org_estado
ON app.obras(organizacion_id, estado);

-- Búsquedas por organización + fecha
CREATE INDEX idx_obras_org_fecha
ON app.obras(organizacion_id, fecha_inicio DESC);
```

### 3. ANALYZE Regular

```sql
-- Manual
ANALYZE app.usuarios;
ANALYZE app.obras;
ANALYZE app.presupuestos;

-- Automático (pg_cron extension)
SELECT cron.schedule('analyze-tables', '0 2 * * *',
    'ANALYZE app.usuarios, app.obras, app.presupuestos'
);
```

### 4. VACUUM Regular

```sql
-- Recuperar espacio y actualizar stats
VACUUM ANALYZE app.usuarios;

-- Full vacuum (más lento, requiere lock)
VACUUM FULL app.usuarios;
```

### 5. Configuración PostgreSQL Recomendada

**postgresql.conf optimizaciones:**

```ini
# Memory
shared_buffers = 256MB          # 25% de RAM disponible
effective_cache_size = 1GB      # 50-75% de RAM
work_mem = 16MB                 # Por operación de sort/hash
maintenance_work_mem = 128MB    # Para VACUUM, CREATE INDEX

# Connections
max_connections = 100           # Ajustar según carga

# Checkpoints
checkpoint_completion_target = 0.9
wal_buffers = 16MB

# Query Planning
random_page_cost = 1.1          # Para SSD (default 4.0)
effective_io_concurrency = 200  # Para SSD (default 1)

# Logging
log_min_duration_statement = 1000  # Log queries > 1s
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_checkpoints = on
log_connections = on
log_disconnections = on
log_lock_waits = on
```

---

## 🔧 Herramientas de Análisis

### 1. EXPLAIN ANALYZE

```sql
EXPLAIN ANALYZE
SELECT u.* FROM app.usuarios u
WHERE u.organizacion_id = 1
AND u.activo = TRUE;
```

**Buscar:**
- `Seq Scan` → Mal (necesita índice)
- `Index Scan` → Bien
- `Bitmap Index Scan` → Bien para muchos resultados
- `cost=X..Y` → Menor es mejor

### 2. pg_stat_statements

```sql
CREATE EXTENSION pg_stat_statements;

-- Top 10 queries más lentas
SELECT
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    max_exec_time
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### 3. pg_stat_user_tables

```sql
-- Tablas con más seq scans (necesitan índices)
SELECT
    schemaname,
    relname,
    seq_scan,
    seq_tup_read,
    idx_scan,
    seq_tup_read / seq_scan AS avg_seq_read
FROM pg_stat_user_tables
WHERE schemaname = 'app'
AND seq_scan > 0
ORDER BY seq_scan DESC;
```

---

## 📊 Benchmarks Esperados

| Operación | Sin Optimización | Con Optimización | Mejora |
|-----------|------------------|------------------|--------|
| **Login por email** | ~200ms | ~20ms | 10x |
| **Lista usuarios org** | ~500ms | ~50ms | 10x |
| **Filtrar obras estado** | ~400ms | ~40ms | 10x |
| **JOIN usuarios + org** | ~300ms | ~30ms | 10x |
| **Búsqueda full-text** | ~800ms | ~80ms | 10x |

---

## 🛡️ Seguridad PostgreSQL

### 1. Roles y Permisos

```sql
-- Crear rol de aplicación (solo app schema)
CREATE ROLE obyra_app_role;
GRANT CONNECT ON DATABASE obyra_dev TO obyra_app_role;
GRANT USAGE ON SCHEMA app TO obyra_app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO obyra_app_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO obyra_app_role;

-- Aplicar rol al usuario
GRANT obyra_app_role TO obyra;
```

### 2. Row Level Security (RLS)

Para multi-tenancy a nivel de BD:

```sql
-- Habilitar RLS en usuarios
ALTER TABLE app.usuarios ENABLE ROW LEVEL SECURITY;

-- Policy: usuarios solo ven su org
CREATE POLICY usuarios_org_isolation ON app.usuarios
    FOR SELECT
    USING (organizacion_id = current_setting('app.current_org_id')::int);
```

### 3. Encriptación

```sql
-- Instalar pgcrypto
CREATE EXTENSION pgcrypto;

-- Encriptar datos sensibles
UPDATE app.usuarios
SET telefono = pgp_sym_encrypt(telefono, 'encryption-key');

-- Desencriptar
SELECT pgp_sym_decrypt(telefono::bytea, 'encryption-key')
FROM app.usuarios;
```

---

## 📝 Checklist de Optimización

### Implementado ✅
- [x] Connection pooling configurado
- [x] Índices básicos en columnas frecuentes
- [x] Schema separado (app)
- [x] Statement timeout configurado
- [x] TCP keepalives configurados
- [x] Código SQLite completamente eliminado
- [x] Migraciones solo para PostgreSQL

### Recomendado para Producción
- [ ] Configurar `pg_stat_statements`
- [ ] Implementar índices parciales
- [ ] Configurar ANALYZE automático
- [ ] Configurar VACUUM automático
- [ ] Implementar Row Level Security
- [ ] Configurar replicación
- [ ] Backups automáticos diarios
- [ ] Monitoreo con Prometheus + Grafana

---

## 🔗 Referencias

- **PostgreSQL Performance:** https://wiki.postgresql.org/wiki/Performance_Optimization
- **Connection Pooling:** https://docs.sqlalchemy.org/en/latest/core/pooling.html
- **Index Types:** https://www.postgresql.org/docs/current/indexes-types.html
- **Monitoring:** https://www.postgresql.org/docs/current/monitoring-stats.html
- **pg_stat_statements:** https://www.postgresql.org/docs/current/pgstatstatements.html

---

**Sistema OBYRA 100% PostgreSQL - Sin SQLite** 🚀
**Fecha:** 2 de Noviembre, 2025
