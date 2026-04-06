#!/bin/bash
# ============================================
# OBYRA - Setup SSL con Let's Encrypt
# ============================================
# Uso: ./scripts/setup_ssl.sh tu-dominio.com tu-email@ejemplo.com
#
# Prerrequisitos:
# 1. DNS del dominio apuntando al servidor
# 2. Puertos 80 y 443 abiertos
# 3. docker-compose.prod.yml ejecutándose

set -euo pipefail

DOMAIN="${1:?Uso: $0 <dominio> <email>}"
EMAIL="${2:?Uso: $0 <dominio> <email>}"

echo "=== Configurando SSL para ${DOMAIN} ==="

# 1. Actualizar nginx config con el dominio real
echo "[1/4] Configurando Nginx para ${DOMAIN}..."
sed -i "s/DOMINIO/${DOMAIN}/g" nginx/conf.d/obyra-ssl.conf
sed -i "s/server_name _;/server_name ${DOMAIN};/g" nginx/conf.d/obyra-ssl.conf

# 2. Primero obtener certificado con certbot standalone
echo "[2/4] Obteniendo certificado SSL de Let's Encrypt..."
docker compose -f docker-compose.prod.yml run --rm certbot \
    certonly --webroot \
    -w /var/www/certbot \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email \
    -d "${DOMAIN}"

# 3. Reiniciar nginx para cargar el certificado
echo "[3/4] Reiniciando Nginx..."
docker compose -f docker-compose.prod.yml restart nginx

# 4. Verificar
echo "[4/4] Verificando SSL..."
sleep 5
if curl -s -o /dev/null -w "%{http_code}" "https://${DOMAIN}/health" | grep -q "200"; then
    echo ""
    echo "=== SSL configurado exitosamente ==="
    echo "URL: https://${DOMAIN}"
    echo "Certificado se renueva automáticamente cada 12 horas."
else
    echo ""
    echo "=== ADVERTENCIA: No se pudo verificar HTTPS ==="
    echo "Revisa los logs: docker compose -f docker-compose.prod.yml logs nginx"
fi
