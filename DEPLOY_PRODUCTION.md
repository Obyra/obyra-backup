# Guía de Despliegue a Producción — OBYRA

## Prerrequisitos

- Servidor con Docker y Docker Compose instalado
- Dominio DNS apuntando al servidor (ej: app.obyra.com)
- Puertos 80 y 443 abiertos

## 1. Configurar variables de entorno

Copiar `.env.example` a `.env` y configurar TODAS las variables:

```bash
cp .env.example .env
nano .env
```

**Variables OBLIGATORIAS:**
```env
# Seguridad
SECRET_KEY=<clave-secreta-larga-aleatoria>
ADMIN_DEFAULT_PASSWORD=<password-seguro-admin>

# Base de datos
POSTGRES_PASSWORD=<password-seguro-db>
POSTGRES_DB=obyra_prod
POSTGRES_USER=obyra

# Dominio
BASE_URL=https://tu-dominio.com

# Monitoring (crear cuenta gratis en sentry.io)
SENTRY_DSN=https://xxxxx@o123.ingest.sentry.io/456
```

**Generar SECRET_KEY:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## 2. Desplegar

```bash
# Build y arrancar todos los servicios
docker compose -f docker-compose.prod.yml up -d --build

# Verificar que todo está corriendo
docker compose -f docker-compose.prod.yml ps

# Ver logs
docker compose -f docker-compose.prod.yml logs -f app
```

## 3. Configurar SSL

```bash
chmod +x scripts/setup_ssl.sh
./scripts/setup_ssl.sh tu-dominio.com tu-email@ejemplo.com
```

## 4. Verificar

```bash
# Health check
curl https://tu-dominio.com/health

# Verificar backup
docker compose -f docker-compose.prod.yml logs backup

# Verificar SSL
curl -I https://tu-dominio.com
```

## Servicios incluidos

| Servicio | Puerto | Descripción |
|----------|--------|-------------|
| nginx | 80, 443 | Reverse proxy + SSL + rate limiting |
| app | 5000 (interno) | Flask/Gunicorn (4 workers) |
| postgres | 5432 (interno) | Base de datos |
| redis | 6379 (interno) | Cache + sesiones + rate limiter |
| celery-worker | — | Tareas en background |
| celery-beat | — | Tareas programadas |
| certbot | — | Renovación automática SSL |
| backup | — | Backup diario PostgreSQL (3:00 AM) |

## Backups

- **Automático:** Backup diario a las 3:00 AM, retención de 30 días
- **Manual:** `docker compose -f docker-compose.prod.yml exec backup /backup.sh`
- **Restaurar:** `docker compose -f docker-compose.prod.yml exec postgres pg_restore -U obyra -d obyra_prod /backups/archivo.dump`
- **Ver backups:** `docker compose -f docker-compose.prod.yml exec backup ls -la /backups/`

## Monitoring (Sentry)

1. Crear cuenta en [sentry.io](https://sentry.io) (gratis hasta 5K eventos/mes)
2. Crear proyecto Flask
3. Copiar el DSN a `SENTRY_DSN` en `.env`
4. Reiniciar: `docker compose -f docker-compose.prod.yml restart app celery-worker`

Sentry captura automáticamente:
- Errores 500
- Excepciones no manejadas
- Performance de requests
- Errores de base de datos

## CI/CD

El pipeline `.github/workflows/ci.yml` ejecuta automáticamente en cada push/PR:
- Verificación de sintaxis de todos los archivos Python
- Tests con pytest contra PostgreSQL real
- Linting con ruff

## Mantenimiento

```bash
# Actualizar la aplicación
git pull
docker compose -f docker-compose.prod.yml up -d --build app

# Ver logs de un servicio
docker compose -f docker-compose.prod.yml logs -f app

# Reiniciar un servicio
docker compose -f docker-compose.prod.yml restart app

# Escalar workers
docker compose -f docker-compose.prod.yml up -d --scale celery-worker=2
```
