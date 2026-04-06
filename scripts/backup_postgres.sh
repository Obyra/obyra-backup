#!/bin/bash
# ============================================
# OBYRA - Backup automático de PostgreSQL
# ============================================
# Uso: ./scripts/backup_postgres.sh
# Cron: 0 3 * * * /app/scripts/backup_postgres.sh >> /var/log/backup.log 2>&1
#
# Variables requeridas:
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST
#   BACKUP_DIR (default: /backups)
#   BACKUP_RETENTION_DAYS (default: 30)

set -euo pipefail

# Configuración
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="${POSTGRES_DB:-obyra_prod}"
DB_USER="${POSTGRES_USER:-obyra}"
DB_HOST="${POSTGRES_HOST:-postgres}"
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

echo "[$(date)] === Iniciando backup de PostgreSQL ==="

# Crear directorio si no existe
mkdir -p "${BACKUP_DIR}"

# Ejecutar pg_dump comprimido
echo "[$(date)] Dumping ${DB_NAME}..."
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    -h "${DB_HOST}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    --no-owner \
    --no-privileges \
    --format=custom \
    --compress=9 \
    -f "${BACKUP_FILE%.gz}"

# Comprimir si se usó formato custom (ya está comprimido)
mv "${BACKUP_FILE%.gz}" "${BACKUP_FILE%.sql.gz}.dump"
BACKUP_FILE="${BACKUP_FILE%.sql.gz}.dump"

# Verificar que el backup no está vacío
BACKUP_SIZE=$(stat -f%z "${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_FILE}" 2>/dev/null || echo 0)
if [ "${BACKUP_SIZE}" -lt 1000 ]; then
    echo "[$(date)] ERROR: Backup demasiado pequeño (${BACKUP_SIZE} bytes). Posible falla."
    exit 1
fi

echo "[$(date)] Backup creado: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))"

# Limpiar backups viejos
echo "[$(date)] Limpiando backups con más de ${RETENTION_DAYS} días..."
DELETED=$(find "${BACKUP_DIR}" -name "${DB_NAME}_*.dump" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
echo "[$(date)] ${DELETED} backups antiguos eliminados."

# Verificación de restauración (test rápido)
echo "[$(date)] Verificando integridad del backup..."
pg_restore --list "${BACKUP_FILE}" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "[$(date)] Backup verificado correctamente."
else
    echo "[$(date)] ADVERTENCIA: El backup podría estar corrupto."
    exit 1
fi

echo "[$(date)] === Backup completado exitosamente ==="
