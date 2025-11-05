#!/bin/bash
# Script para reconstruir y reiniciar Docker con los cambios

echo "🔄 Reconstruyendo imagen Docker con los cambios..."

# Detener el servidor local si está corriendo
echo "🛑 Deteniendo servidor local..."
pkill -9 -f "python.*app" 2>/dev/null || true

# Reconstruir la imagen de Docker
echo "🔨 Reconstruyendo imagen..."
docker-compose -f docker-compose.dev.yml build --no-cache app

# Reiniciar los servicios
echo "🚀 Iniciando servicios..."
docker-compose -f docker-compose.dev.yml up -d

# Esperar a que la app esté lista
echo "⏳ Esperando a que la app esté lista..."
sleep 5

# Mostrar estado
echo ""
echo "📊 Estado de los contenedores:"
docker-compose -f docker-compose.dev.yml ps

echo ""
echo "✅ ¡Listo! La app debería estar corriendo en:"
echo "   http://localhost:5002"
echo ""
echo "📋 Para ver los logs:"
echo "   docker-compose -f docker-compose.dev.yml logs -f app"
