# Migraciones y Seeds – OBYRA

Las instrucciones siguientes están probadas con Windows PowerShell contra el contenedor `obyra-pg-stg` expuesto en `localhost:5435`. Todos los pasos son idempotentes: si ya corriste una sección, volverla a ejecutar no rompe el estado.

> ⚠️ Recordá que las contraseñas reales **no** se versionan. Usá placeholders al editar `sql/roles.sql` y seteá las variables de entorno localmente.

## Variables de entorno base (PowerShell)
```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:FLASK_APP = "app.py"
$env:FLASK_ENV = "development"
$env:FLASK_RUN_PORT = "8080"
$env:DATABASE_URL = "postgresql+psycopg://obyra_app:<PASS_APP>@localhost:5435/obyra_dev"
$env:ALEMBIC_DATABASE_URL = "postgresql+psycopg://obyra_migrator:<PASS_MIGRATOR>@localhost:5435/obyra_dev"
```
Si las contraseñas contienen `%`, PowerShell enviará `%%` al proceso y Alembic las aceptará gracias al escape configurado en `migrations/env.py`.

---

## 1. Esquema y permisos (idempotente)
1. Editá `sql/roles.sql` para reemplazar los placeholders de contraseña según el entorno.
2. Ejecutá el script dentro de la base objetivo (`obyra_dev`, `obyra_stg`, etc.):
   ```powershell
   Get-Content sql\roles.sql | docker exec -i obyra-pg-stg psql \
       -U postgres \
       -d obyra_dev \
       -v ON_ERROR_STOP=1 \
       -f -
   ```
   El script crea el esquema `app`, provisiona los roles (`app_owner`, `app_rw`, `app_ro`, `obyra_migrator`), fija el `search_path`, concede privilegios por defecto y normaliza la tabla `app.seed_version`.

Si necesitás crear la base antes del script:
```powershell
$existsRaw = docker exec -i obyra-pg-stg psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='obyra_dev'"
if ([string]::IsNullOrWhiteSpace($existsRaw)) {
    Write-Host "La base no existe; se crea obyra_dev..."
    docker exec -i obyra-pg-stg psql -U postgres -d postgres -c "CREATE DATABASE obyra_dev OWNER obyra"
} else {
    Write-Host "La base ya existe; ajusto el owner..."
    docker exec -i obyra-pg-stg psql -U postgres -d postgres -c "ALTER DATABASE obyra_dev OWNER TO obyra"
}
```

---

## 2. Verificar acceso con el rol de la app
Usando el usuario que la aplicación emplea (`obyra_app`, heredando de `app_rw`):
```powershell
# Validar esquema y permisos básicos
docker exec -i obyra-pg-stg psql \ 
    -U obyra_app \ 
    -d obyra_dev \ 
    -c "SELECT current_user, current_schema();"

# Probar lectura/escritura sobre role_modules
docker exec -i obyra-pg-stg psql \ 
    -U obyra_app \ 
    -d obyra_dev \ 
    -c "INSERT INTO app.role_modules(role, module, can_view, can_edit) VALUES ('_smoke','_ok', TRUE, FALSE) RETURNING id;"

# Limpiar el registro de prueba si corresponde
docker exec -i obyra-pg-stg psql \ 
    -U obyra_app \ 
    -d obyra_dev \ 
    -c "DELETE FROM app.role_modules WHERE role = '_smoke' AND module = '_ok';"
```
Deberías ver `current_schema = app`, el `INSERT` devolviendo un `id > 0` y la secuencia avanzando sin errores de permisos.

---

## 3. Migraciones
1. Confirmá el estado antes de aplicar cambios:
   ```powershell
   alembic history --verbose
   alembic current
   ```
2. Aplicá la cabeza actual (incluye `20251028_baseline` y `20251028_fixes`):
   ```powershell
   alembic upgrade head
   ```
3. Si necesitás generar una nueva migración desde los modelos:
   ```powershell
   flask db migrate -m "YYYYMMDD_hhmm_descripcion"
   alembic upgrade head
   ```
   Flask-Migrate abre el contexto de Flask automáticamente; evitá envolver el comando en otra llamada a `app.app_context()` para no ver `Popped wrong app context`.

---

## 4. Comprobar versión Alembic
Después de `alembic upgrade head`, verificá que la base quedó en la revisión correcta:
```powershell
alembic current

docker exec -i obyra-pg-stg psql \
    -U postgres \
    -d obyra_dev \
    -c "SELECT * FROM app.alembic_version;"

docker exec -i obyra-pg-stg psql \
    -U postgres \
    -d obyra_dev \
    -c "\d+ app.role_modules"

docker exec -i obyra-pg-stg psql \
    -U postgres \
    -d obyra_dev \
    -c "SELECT column_default, is_nullable FROM information_schema.columns WHERE table_schema='app' AND table_name='presupuestos' AND column_name='vigencia_bloqueada';"
```
La salida debe mostrar `20251028_fixes` como revisión activa, `id` con `DEFAULT nextval('app.role_modules_id_seq'::regclass)` y la columna `vigencia_bloqueada` con `DEFAULT false` y `is_nullable = NO`.

---

## 5. Correr la app
Con las variables del bloque inicial ya seteadas:
```powershell
# Instalar dependencias si es la primera vez
pip install -r requirements.txt

# Ejecutar seeds si corresponde
flask seed:inventario --global

# Levantar la aplicación
flask run --host=0.0.0.0 --port=$env:FLASK_RUN_PORT
```
Los blueprints opcionales (`presupuestos`, `inventario_new`, `agent_local`) están envueltos en `try/except`, por lo que cualquier warning durante importación se registra pero no impide que `flask run` o `flask db upgrade` se ejecuten.

---

## Notas de referencia rápida
- Consultar configuración de Alembic: `alembic.ini` y `migrations/env.py`.
- Secuencia `app.role_modules_id_seq` queda normalizada en la migración `20251028_fixes`.
- Seeds se registran en `app.seed_version`; usá la tabla para controlar idempotencia.
- El contenedor estándar de Postgres en staging local es `obyra-pg-stg` (puerto `5435`).
