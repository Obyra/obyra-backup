#!/bin/bash

# Setup Local Development Environment
# ====================================
# Este script configura un virtualenv local para desarrollo
# mientras mantienes Docker para correr la aplicación

set -e  # Exit on error

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     OBYRA - Local Development Environment Setup          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
echo "📋 Verificando Python..."
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD=python3.11
    echo -e "${GREEN}✅ Python 3.11 encontrado${NC}"
elif command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    PYTHON_CMD=python3
    echo -e "${YELLOW}⚠️  Usando Python $PYTHON_VERSION (se recomienda 3.11)${NC}"
else
    echo -e "${RED}❌ Python 3 no encontrado${NC}"
    echo "Por favor instala Python 3.11:"
    echo "  macOS: brew install python@3.11"
    echo "  Ubuntu: sudo apt install python3.11"
    exit 1
fi

# Check if virtualenv already exists
if [ -d "venv" ]; then
    echo -e "${YELLOW}⚠️  El directorio 'venv' ya existe${NC}"
    read -p "¿Quieres recrearlo? (s/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        echo "🗑️  Eliminando virtualenv anterior..."
        rm -rf venv
    else
        echo "✅ Usando virtualenv existente"
        source venv/bin/activate
        echo "📦 Actualizando dependencias..."
        pip install --upgrade pip -q
        pip install -r requirements.txt -q
        echo -e "${GREEN}✅ Setup completado${NC}"
        exit 0
    fi
fi

# Create virtualenv
echo "🔨 Creando virtualenv..."
$PYTHON_CMD -m venv venv

# Activate virtualenv
echo "⚡ Activando virtualenv..."
source venv/bin/activate

# Upgrade pip
echo "📦 Actualizando pip..."
pip install --upgrade pip -q

# Install dependencies
echo "📚 Instalando dependencias (esto puede tardar un minuto)..."
pip install -r requirements.txt -q

# Verify installation
echo ""
echo "🔍 Verificando instalación..."

# Test imports
python << EOF
try:
    from services import UserService, ProjectService, BudgetService
    from models import Usuario, Obra, Presupuesto
    print("✅ Services y Models importados correctamente")
except Exception as e:
    print(f"❌ Error al importar: {e}")
    exit(1)
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║              ✅ SETUP COMPLETADO EXITOSAMENTE             ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo ""
    echo "📝 Próximos pasos:"
    echo ""
    echo "1️⃣  Activar el virtualenv:"
    echo -e "   ${GREEN}source venv/bin/activate${NC}"
    echo ""
    echo "2️⃣  Configurar tu IDE:"
    echo "   - VS Code: Cmd+Shift+P → 'Python: Select Interpreter' → './venv/bin/python'"
    echo "   - PyCharm: Settings → Project → Python Interpreter → Add → Existing → './venv/bin/python'"
    echo ""
    echo "3️⃣  Correr tests localmente:"
    echo -e "   ${GREEN}pytest${NC}"
    echo ""
    echo "4️⃣  La app sigue corriendo en Docker:"
    echo -e "   ${GREEN}docker-compose -f docker-compose.dev.yml up${NC}"
    echo ""
    echo "📚 Más info: LOCAL_DEV_SETUP.md"
    echo ""
else
    echo ""
    echo -e "${RED}❌ Hubo un error durante la instalación${NC}"
    echo "Por favor revisa los mensajes de error arriba"
    exit 1
fi
