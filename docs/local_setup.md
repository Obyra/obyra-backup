# Configuración local y ejecución de la app

Estas instrucciones permiten levantar la aplicación en Windows, macOS o Linux utilizando un entorno virtual de Python.

## 1. Requisitos previos

- Python 3.11 instalado.
- `git` para clonar/actualizar el repositorio.

Puedes verificar la versión de Python con:

```bash
python --version
```

o en Windows con:

```powershell
py --version
```

## 2. Crear y activar un entorno virtual

Se recomienda aislar las dependencias en un *virtualenv*:

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### macOS / Linux (bash/zsh)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Cuando el entorno esté activo deberías ver el prefijo `(.venv)` en la consola.

## 3. Instalar dependencias

Con el entorno virtual activo, instala las dependencias definidas en `pyproject.toml`:

```bash
pip install --upgrade pip
pip install -e .
```

Esto instalará Flask y el resto de paquetes necesarios. Si prefieres no usar modo editable, puedes ejecutar `pip install .`.

## 4. Variables de entorno recomendadas

La aplicación funciona por defecto con SQLite en `tmp/dev.db`. Si deseas utilizar otra base (por ejemplo PostgreSQL) define `DATABASE_URL` antes de iniciar.

Ejemplo en PowerShell:

```powershell
$env:DATABASE_URL = "postgresql://usuario:password@host:puerto/base"
```

En bash/zsh:

```bash
export DATABASE_URL="postgresql://usuario:password@host:puerto/base"
```

## 5. Ejecutar la aplicación

Con el entorno virtual activo y dependencias instaladas, tienes dos alternativas para iniciar el servidor de desarrollo:

### Opción A: Ejecutar el módulo principal directamente

```bash
python app.py
```

### Opción B: Usar el comando Flask

```bash
export FLASK_APP=app.py      # en Windows PowerShell: $env:FLASK_APP = "app.py"
python -m flask run
```

Usar `python -m flask` garantiza que el comando se resuelva dentro del entorno virtual incluso en Windows, evitando el error `flask : El término 'flask' no se reconoce...`.

La aplicación quedará disponible en `http://127.0.0.1:5000/`.

## 6. Detener el servidor

Presiona `Ctrl+C` en la terminal donde corre el servidor. Para salir del entorno virtual ejecuta `deactivate`.

## 7. Solución de problemas

- **`flask : El término 'flask' no se reconoce`**: indica que el comando se está ejecutando fuera del entorno virtual o que Flask no está instalado. Repite los pasos 2 y 3 y luego inicia con `python -m flask run`.
- **Errores de base de datos**: verifica que la ruta de `tmp/dev.db` sea accesible o define `DATABASE_URL` con la conexión correcta.

Con estos pasos deberías poder iniciar la aplicación en tu entorno local.
