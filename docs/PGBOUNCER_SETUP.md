# PgBouncer — Connection Pooler para Producción

## ¿Por qué PgBouncer?

PostgreSQL es lento abriendo conexiones (~10-50ms cada una). En una app web con muchos requests, esto:

1. **Limita throughput**: cada worker debe esperar la conexión
2. **Saturas max_connections**: PostgreSQL típicamente tiene 100 conexiones max. Si tenés 10 instancias × 4 workers × 2 threads = 80 conexiones potenciales, ya estás cerca del límite
3. **Cuesta caro**: Railway/AWS RDS facturan por instancia, y necesitás máquinas más grandes solo para soportar conexiones

**PgBouncer** es un proxy ligero que mantiene un pool de conexiones reutilizables. Tu app abre 1000 "conexiones" pero PgBouncer las multiplexa sobre solo 20 conexiones reales a PostgreSQL.

## ¿Cuándo lo necesitás?

- ✅ Más de 1 instancia de la app corriendo
- ✅ Más de 50 usuarios concurrentes
- ✅ Latencia P95 > 200ms
- ❌ Hoy con 1 instancia y pocos usuarios → no urgente

## Estado actual de OBYRA

```python
# config en app.py
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_size": 10,
    "max_overflow": 20,
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}
```

Esto da hasta **30 conexiones por proceso de Gunicorn**. Con 4 workers, son **120 conexiones potenciales**. Ya estamos al límite del default de PostgreSQL.

## Setup en Railway

Railway tiene un plugin oficial de PgBouncer. Para activarlo:

1. Ir al proyecto en Railway
2. Click en **+ New** → **Database** → **PgBouncer**
3. Conectarlo al servicio Postgres existente
4. Railway te dará una nueva `DATABASE_URL` que apunta a PgBouncer
5. En las variables del servicio app, cambiar `DATABASE_URL` a la nueva
6. Reduce el `pool_size` de la app a 5 (porque PgBouncer ya hace el pooling):
   ```env
   SQLALCHEMY_POOL_SIZE=5
   SQLALCHEMY_MAX_OVERFLOW=10
   ```

## Setup self-hosted con Docker

```yaml
# docker-compose.prod.yml — agregar este servicio
services:
  pgbouncer:
    image: edoburu/pgbouncer:latest
    container_name: obyra-pgbouncer
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://obyra:${POSTGRES_PASSWORD}@postgres:5432/obyra_prod
      POOL_MODE: transaction
      MAX_CLIENT_CONN: 1000
      DEFAULT_POOL_SIZE: 25
      ADMIN_USERS: postgres,obyra
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - obyra-network

  app:
    environment:
      # Cambiar para usar PgBouncer en vez de postgres directo
      DATABASE_URL: postgresql://obyra:${POSTGRES_PASSWORD}@pgbouncer:5432/obyra_prod
```

## Modos de pooling

- **session**: una conexión backend por sesión cliente (poco beneficio)
- **transaction**: una conexión backend por transacción (RECOMENDADO)
- **statement**: una conexión backend por statement (rompe transacciones)

**Usar `transaction` mode.**

## Limitaciones de transaction mode

Algunas features de PostgreSQL NO funcionan con `transaction` mode:
- Prepared statements (SQLAlchemy los maneja diferente)
- `LISTEN/NOTIFY` (raro)
- `SET` statements persistentes ⚠️ **¡IMPORTANTE PARA RLS!**

### ⚠️ RLS + PgBouncer

Como RLS usa `SET app.current_org_id = '...'`, y PgBouncer transaction mode resetea variables entre transacciones, hay que ser cuidadoso.

**Solución:** usar `SET LOCAL` en vez de `SET`:

```sql
-- En vez de:
SET app.current_org_id = '5';

-- Usar:
SET LOCAL app.current_org_id = '5';
```

`SET LOCAL` aplica solo a la transacción actual, lo cual funciona con PgBouncer transaction mode.

El middleware `rls_middleware.py` ya está preparado para ambos modos — solo hay que ajustarlo si usás PgBouncer (cambiar `SET` por `SET LOCAL`).

## Recomendación

**No instalar PgBouncer todavía**. Esperar a tener:
1. >50 usuarios concurrentes confirmados, O
2. Latencia P95 > 200ms en queries simples, O
3. Errores `too many connections` en logs

Cuando llegue alguno de esos triggers, instalar PgBouncer + ajustar `pool_size` de la app.
