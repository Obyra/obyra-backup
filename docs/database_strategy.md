# Estrategia de base de datos PostgreSQL para OBYRA

## 1. Diagnóstico actual
- La aplicación principal se conecta exclusivamente vía `DATABASE_URL` con driver `psycopg` (v3).
- Persisten artefactos legacy (`app_old.py`, `init_marketplace.py`) que crean tablas con `db.create_all()` fuera del flujo de migraciones.
- Las migraciones Alembic existen pero requieren estandarización (historial parcial y runtime helpers).
- No hay documentación formal sobre roles de base de datos, backups ni monitoreo.

## 2. Topología objetivo
| Entorno | Instancia | Esquema | Propósito |
| --- | --- | --- | --- |
| Dev compartido | PostgreSQL 16 (Docker o RDS dev) | `public` | Iteración de equipo; permite recrear esquema sin preservar datos. |
| Staging | PostgreSQL 16 gestionado (RDS/Cloud SQL) | `app` (principal), `audit` (opcional) | Ensayo previo a producción; acceso restringido a equipo QA/devops. |
| Producción | PostgreSQL 16 gestionado con alta disponibilidad | `app` (principal), `audit`, `analytics` (lectura) | Tráfico real. Replica de sólo lectura para BI opcional. |

### Componentes adicionales
- **Replica de lectura**: opcional en PROD para reportes pesados.
- **Servicio de backups**: snapshots automáticos diarios + PITR 7 días.
- **Monitoreo**: integración con CloudWatch/Stackdriver (latencia, conexiones, locks).

## 3. Roles y políticas de acceso
| Rol | Permisos | Uso |
| --- | --- | --- |
| `obyra_app` | `CONNECT`, `USAGE` en esquema `app`, `SELECT/INSERT/UPDATE/DELETE` | Credenciales usadas por la aplicación.
| `obyra_migrate` | `obyra_app` + `CREATE/ALTER/DROP` en esquema `app` | Usado por pipeline de migraciones Alembic. Rotar credenciales cada 90 días.
| `obyra_readonly` | `CONNECT`, `USAGE`, `SELECT` | Consultas ad-hoc, reportes, herramientas BI.
| `obyra_admin` | Superusuario gestionado por DevOps | Sólo para mantenimiento (no usar en app). |

Políticas recomendadas:
- Usar autenticación mediante contraseñas generadas y almacenadas en gestor de secretos (AWS Secrets Manager, Google Secret Manager, Vault).
- Registrar IPs de origen por entorno (listas de control VPC / security groups).
- Rotación automática de contraseñas cada 90 días con notificación al equipo.

## 4. Gestión de migraciones y seeds
1. **Alembic como única fuente**
   - Mantener `flask db upgrade` como paso obligatorio en despliegue.
   - Prohibir `db.create_all()` en código productivo.
2. **Pipeline CI/CD**
   - Job que ejecute `alembic upgrade head` contra una base temporal antes de publicar.
   - Job que corra `alembic downgrade -1` para validar reversibilidad (cuando aplique).
3. **Seeds versionados**
   - Crear carpeta `migrations/seeds` con scripts idempotentes (por ejemplo, `001_bootstrap_roles.sql`).
   - Invocar seeds mediante comando `flask db seed` o script de provisioning separado.
4. **Runtime helpers**
   - Consolidar `migrations_runtime.py` para que verifique existencia de tablas con `to_regclass` y ejecute sólo alteraciones idempotentes.

## 5. Backups y recuperación
- **Backups automáticos**: snapshots diarios con retención mínima de 14 días en staging y 30 días en producción.
- **PITR**: habilitar point-in-time recovery (min 7 días) para producción.
- **Pruebas de restore**: calendarizar ejercicio trimestral de restauración en entorno aislado.
- **Exportaciones lógicas**: usar `pg_dump` mensual para conservar copia externa cifrada (almacenada en S3/GCS con SSE).

## 6. Seguridad y cumplimiento
- Forzar TLS (`require_ssl=1`) en todas las conexiones externas.
- Activar `pg_stat_statements` para auditar consultas lentas.
- Revisar permisos de tablas sensibles (`users`, `payments`) para garantizar mínimo privilegio.
- Configurar alertas sobre: conexiones >80% del pool, locks mayores a 30 s, crecimiento anómalo (>10% diario).
- Registrar en runbook incidentes DB con responsables y tiempos de respuesta.

## 7. Checklist de despliegue (por entorno)
- [ ] Credenciales almacenadas en gestor de secretos y cargadas en el runtime (Docker/Kubernetes/VM).
- [ ] Roles creados y grants aplicados (`obyra_app`, `obyra_migrate`, `obyra_readonly`).
- [ ] `alembic upgrade head` ejecutado en base vacía sin errores.
- [ ] Seeds aplicados y verificados (organizaciones iniciales, usuarios admin).
- [ ] Backups automáticos configurados y testeados.
- [ ] Monitoreo/alertas activos (CPU, conexiones, almacenamiento, locks).
- [ ] Documentación de credenciales de emergencia y plan de comunicación.

## 8. Próximos pasos
1. Abrir tickets para eliminar `db.create_all()` remanentes (`app_old.py`, `init_marketplace.py`).
2. Configurar workflow de migraciones en CI.
3. Elaborar runbook de incidentes (RTO/RPO) y agregarlo al repositorio (`docs/runbook_db.md`).
4. Establecer política de limpieza de datos sensibles en entornos no productivos (anonimización).
