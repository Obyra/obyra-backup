# Configuración de Desarrollo Local

## ¿Necesito un virtualenv?

### TL;DR
- **Para desarrollo en Docker**: NO necesitas virtualenv
- **Para IDE features y testing local**: SÍ es recomendable

---

## Opción 1: Solo Docker (Setup Actual)

**Ventajas**:
- ✅ Entorno idéntico a producción
- ✅ Sin conflictos de dependencias
- ✅ Fácil onboarding de nuevos devs
- ✅ Todo ya configurado y funcionando

**Desventajas**:
- ❌ IDE autocomplete limitado
- ❌ Debugging más lento
- ❌ Sin linting/type checking local

**Uso actual**:
```bash
# La app ya corre en Docker
docker-compose -f docker-compose.dev.yml up

# Acceso a shell dentro del contenedor si necesitas
docker exec -it obyra-app-dev bash
```

---

## Opción 2: Virtualenv Local + Docker (Recomendado)

**Lo mejor de ambos mundos**:
- ✅ App corre en Docker (producción-ready)
- ✅ IDE features completos localmente
- ✅ Tests rápidos en local
- ✅ Type checking y linting

### Setup Paso a Paso

#### 1. Crear virtualenv

```bash
# Desde el directorio del proyecto
cd /Users/jmargalef/Sistemas/Obyra/obyra-backup

# Crear virtualenv con Python 3.11 (misma versión que Docker)
python3.11 -m venv venv

# Si no tienes Python 3.11:
# brew install python@3.11  # macOS
# apt install python3.11    # Ubuntu
```

#### 2. Activar virtualenv

```bash
# macOS/Linux
source venv/bin/activate

# Deberías ver (venv) en tu prompt
```

#### 3. Instalar dependencias

```bash
# Actualizar pip
pip install --upgrade pip

# Instalar todas las dependencias del proyecto
pip install -r requirements.txt

# Verificar instalación
pip list
```

#### 4. Variables de entorno (opcional para tests locales)

```bash
# Copiar .env.example si existe, o crear .env
cat > .env << 'EOF'
# Desarrollo local (apunta a Docker containers)
DATABASE_URL=postgresql://obyra_owner:obyra_pass@localhost:5434/obyra_dev
REDIS_URL=redis://localhost:6382/0
FLASK_ENV=development
SECRET_KEY=dev-secret-key-change-in-production
EOF
```

#### 5. Configurar tu IDE

**VS Code (`.vscode/settings.json`)**:
```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/venv/bin/python",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": false,
    "python.linting.flake8Enabled": true,
    "python.formatting.provider": "black",
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": [
        "tests"
    ],
    "python.analysis.typeCheckingMode": "basic"
}
```

**PyCharm**:
1. File → Settings → Project → Python Interpreter
2. Add Interpreter → Existing Environment
3. Seleccionar `venv/bin/python`

---

## Uso Diario

### Desarrollo en Docker (no cambia)
```bash
# Levantar servicios
docker-compose -f docker-compose.dev.yml up

# La app corre en http://localhost:5002
```

### Testing Local (con virtualenv)
```bash
# Activar virtualenv
source venv/bin/activate

# Correr tests
pytest

# Con coverage
pytest --cov=services --cov=models

# Test específico
pytest tests/test_user_service.py -v
```

### Linting y Type Checking
```bash
# Activar virtualenv
source venv/bin/activate

# Instalar herramientas de desarrollo (opcional)
pip install flake8 mypy black isort

# Linting
flake8 services/ models/

# Type checking
mypy services/ --ignore-missing-imports

# Auto-formatting
black services/ models/
isort services/ models/
```

### Scripts y Migraciones Locales
```bash
# Activar virtualenv
source venv/bin/activate

# Crear migración Alembic
alembic revision -m "descripcion"

# Ver SQL que se ejecutará
alembic upgrade head --sql

# Ejecutar scripts custom
python scripts/seed_data.py
```

---

## Comparación

| Característica | Solo Docker | Docker + Virtualenv |
|----------------|-------------|---------------------|
| **App runtime** | ✅ En Docker | ✅ En Docker |
| **IDE autocomplete** | ⚠️ Limitado | ✅ Completo |
| **Type checking** | ❌ No | ✅ Sí (mypy) |
| **Linting** | ❌ No | ✅ Sí (flake8) |
| **Tests rápidos** | ⚠️ En Docker | ✅ Locales |
| **Debugging** | ⚠️ Más lento | ✅ Más rápido |
| **Alembic local** | ❌ Solo en container | ✅ Local y container |
| **Aislamiento** | ✅ Perfecto | ✅ Perfecto |

---

## Recomendación Final

**Crea el virtualenv local** con estos comandos:

```bash
# 1. Crear virtualenv
python3.11 -m venv venv

# 2. Activar
source venv/bin/activate

# 3. Instalar deps
pip install --upgrade pip
pip install -r requirements.txt

# 4. Verificar
python -c "from services import UserService; print('✅ Services importados correctamente')"
```

**Luego sigue usando Docker para correr la app**:
```bash
docker-compose -f docker-compose.dev.yml up
```

**Beneficios inmediatos**:
- Tu IDE verá todas las clases y métodos
- Autocomplete funcionará perfectamente
- Podrás hacer jump-to-definition
- Type hints se validarán en tiempo real

---

## Troubleshooting

### "python3.11: command not found"
```bash
# macOS
brew install python@3.11

# Ubuntu/Debian
sudo apt update
sudo apt install python3.11 python3.11-venv
```

### "pip install falla con psycopg"
```bash
# macOS
brew install postgresql

# Ubuntu/Debian
sudo apt install libpq-dev python3-dev
```

### "No module named 'extensions'"
Esto es normal. El módulo `extensions` está en el proyecto y se importa cuando corres la app. Para tests locales, asegúrate de que el virtualenv esté activado y estés en el directorio raíz del proyecto.

---

## Siguiente Paso Sugerido

Una vez tengas el virtualenv:

1. **Crea tests para los servicios** (Phase 3.5 opcional):
   ```bash
   mkdir -p tests/services
   touch tests/services/test_user_service.py
   ```

2. **O continúa con Phase 4**: Migrar runtime migrations a Alembic

---

**Fecha**: 2 de Noviembre, 2025
**Estado**: Documentación de setup local
**Requisito**: Python 3.11+, pip, virtualenv
