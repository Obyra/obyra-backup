#!/bin/bash

# ============================================
# Script de Verificación de Puertos OBYRA
# ============================================
# Este script verifica qué puertos están libres/ocupados

echo "==========================================="
echo "  OBYRA - Verificación de Puertos"
echo "==========================================="
echo ""

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Función para verificar puerto
check_port() {
    local port=$1
    local service=$2

    if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
        process=$(lsof -nP -iTCP:$port -sTCP:LISTEN | tail -1 | awk '{print $1}')
        printf "${RED}❌ Puerto $port OCUPADO${NC} - $service (usado por: $process)\n"
        return 1
    else
        printf "${GREEN}✅ Puerto $port LIBRE${NC} - $service\n"
        return 0
    fi
}

echo "Verificando puertos de PRODUCCIÓN (docker-compose.yml):"
echo "-----------------------------------------------------------"
check_port 5003 "Flask App (Producción)"
check_port 5436 "PostgreSQL (Producción)"
check_port 6381 "Redis (Producción)"
check_port 8080 "Nginx HTTP"
check_port 8443 "Nginx HTTPS"

echo ""
echo "Verificando puertos de DESARROLLO (docker-compose.dev.yml):"
echo "-----------------------------------------------------------"
check_port 5002 "Flask App (Desarrollo)"
check_port 5434 "PostgreSQL (Desarrollo)"
check_port 6382 "Redis (Desarrollo)"
check_port 5051 "pgAdmin"
check_port 8082 "Redis Commander"

echo ""
echo "Verificando puertos OCUPADOS conocidos:"
echo "-----------------------------------------------------------"
check_port 5000 "Flask Local (NO USAR)"
check_port 5432 "PostgreSQL Existente (NO USAR)"
check_port 5435 "PostgreSQL Secundario (NO USAR)"
check_port 6379 "Redis Existente (NO USAR)"
check_port 6380 "Redis Secundario (NO USAR)"

echo ""
echo "==========================================="
echo "  Resumen"
echo "==========================================="

# Contar puertos libres necesarios para OBYRA
free_count=0
total_count=5

for port in 5003 5436 6381 8080 8443; do
    if ! lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
        ((free_count++))
    fi
done

if [ $free_count -eq $total_count ]; then
    printf "${GREEN}✅ Todos los puertos de PRODUCCIÓN están libres${NC}\n"
    echo "Puedes iniciar: docker-compose up -d"
else
    printf "${YELLOW}⚠️  $free_count/$total_count puertos de producción libres${NC}\n"
    echo "Revisa los puertos ocupados arriba y ajusta docker-compose.yml"
fi

echo ""

# Verificar puertos de desarrollo
free_dev_count=0
total_dev_count=5

for port in 5002 5434 6382 5051 8082; do
    if ! lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
        ((free_dev_count++))
    fi
done

if [ $free_dev_count -eq $total_dev_count ]; then
    printf "${GREEN}✅ Todos los puertos de DESARROLLO están libres${NC}\n"
    echo "Puedes iniciar: docker-compose -f docker-compose.dev.yml up -d"
else
    printf "${YELLOW}⚠️  $free_dev_count/$total_dev_count puertos de desarrollo libres${NC}\n"
    echo "Revisa los puertos ocupados arriba y ajusta docker-compose.dev.yml"
fi

echo ""
echo "==========================================="
echo "Ver mapeo completo: cat PORTS.md"
echo "==========================================="
