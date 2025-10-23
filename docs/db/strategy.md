# Estrategia de Base de Datos

Esta guía describe la topología objetivo de PostgreSQL para OBYRA, las prácticas de conexión y pooling, la configuración de variables de entorno por ambiente y los pilares de observabilidad, seguridad y cumplimiento que aplican desde Fase 2.

## Topología objetivo

### Ambientes
- **Local**: contenedor Docker con PostgreSQL 16 expuesto en `localhost:5433`. Permite reinicios frecuentes y pruebas de migraciones.
- **Staging**: instancia administrada (Neon u oferta equivalente) con soporte para replicas de lectura y pooler integrado. Se habilitan pruebas automatizadas y verificación manual previa a producción.
- **Producción**: clúster PostgreSQL 16 con almacenamiento duradero, redundancia regional y réplicas de solo lectura. Acceso únicamente mediante pooler TLS.

### Esquema de la aplicación
- Todo el dominio de la app vive en el esquema `app`.
- Esquemas administrados por proveedores (`pg_catalog`, `information_schema`, extensiones) quedan fuera del control de Alembic.
- Convenciones de nombres en `app`: tablas `snake_case`, secuencias `tablename_id_seq`, índices `idx_<tabla>_<columna>`, constraints `ck`, `fk`, `pk`.

### Roles lógicos
- `obyra_app`: credenciales de la aplicación. Solo lectura/escritura dentro de `app`.
- `obyra_migrator`: propietario del esquema `app` y rol usado por Alembic. Se revocan permisos directos de login en producción; se usa usuario técnico o secret manager temporal.
- `obyra_readonly`: acceso `SELECT` sobre `app` para analítica / soporte.
- Roles se aprovisionan mediante los scripts en `infra/sql/` y se rotan cada 90 días.

### Pooler
- **Staging/Producción**: se conecta vía pooler administrado (Neon pooler u otro) utilizando `psycopg` v3 y SQLAlchemy 2.x. Configuración mínima:
  - `pool_size=10`, `max_overflow=10`, `pool_timeout=30` en workers web.
  - Activar `pool_pre_ping` para detectar conexiones caducadas.
  - Evitar consultas de larga duración (> 30s); delegar reportes a réplicas.
- **Local**: se recomienda `sqlalchemy.create_engine(..., pool_size=5, max_overflow=5, pool_pre_ping=True)`.

### Variables de entorno por ambiente
| Variable | Local | Staging | Producción |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev` | URL del pooler de escritura | URL del pooler de escritura |
| `ALEMBIC_DATABASE_URL` | Igual que `DATABASE_URL` pero con rol `obyra_migrator` | URL directa sin pooler con credencial migrator | URL directa (secret manager, solo en pipelines) |
| `READONLY_DATABASE_URL` | Opcional; replica local | Pooler de replica de solo lectura | Pooler de replica |
| `SQLALCHEMY_POOL_SIZE` | 5-10 | 10 | 10 |
| `SQLALCHEMY_MAX_OVERFLOW` | 5-10 | 10 | 10 |
| `SQLALCHEMY_POOL_TIMEOUT` | 30 | 30 | 30 |

## Observabilidad
- Habilitar la extensión `pg_stat_statements` (ver `infra/sql/03_observability.sql`).
- Configurar dashboards en el proveedor para latencia, throughput, conexiones, locks y WAL.
- Activar log de consultas lentas (`log_min_duration_statement = 500ms` en staging, `1000ms` en producción) y enviar a el stack de logs central.
- Realizar `VACUUM ANALYZE` automático (autovacuum habilitado) y monitorear bloat con vistas `pg_stat_all_tables`.

## Seguridad y red
- Acceso restringido a redes privadas o túneles mTLS. Bloquear conexiones desde IPs no autorizadas.
- Requerir TLS 1.2+ en todas las conexiones (pooler incluido).
- Rotar contraseñas de roles cada 90 días usando secret manager.
- Habilitar `pgcrypto` únicamente si se necesita cifrado de columnas.
- Registrar auditoría de logins fallidos y cambios DDL.

## Cumplimiento y gobernanza
- Mantener backups con retención diferenciada (ver `docs/db/backups-dr.md`).
- Ejecutar revisión trimestral de roles/permisos y documentarla en `docs/db/checklists/security.md`.
- Garantizar que las migraciones cumplan con la política de ventanas de mantenimiento y compatibilidad hacia adelante.
- Documentar excepciones o cambios urgentes en el runbook de incidencias.
