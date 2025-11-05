# Guía de Migraciones con Alembic

## 📋 Introducción

Este proyecto usa **Alembic** (vía Flask-Migrate) para gestionar las migraciones de base de datos. Todas las migraciones están en `migrations/versions/` y se ejecutan de forma ordenada y versionada.

---

## 🎯 Antes de Empezar

### Requisitos
- PostgreSQL 16+ o SQLite (desarrollo)
- Alembic configurado (ya incluido en el proyecto)
- Docker (recomendado para desarrollo)

### Ubicación de Archivos
```
obyra-backup/
├── migrations/
│   ├── alembic.ini          # Configuración de Alembic
│   ├── env.py               # Entorno de Alembic
│   └── versions/            # Archivos de migración
│       ├── 20251028_baseline.py
│       ├── 20251028_fixes.py
│       ├── 20250316_presupuesto_states.py
│       └── ... (11 más)
├── models/                   # Modelos SQLAlchemy
└── app.py                    # Aplicación Flask
```

---

## 🚀 Comandos Básicos

### Ver Estado Actual

```bash
# Desde el host (con Docker)
docker-compose exec app alembic current

# Desde el contenedor
alembic current
```

**Salida esperada**:
```
20250915_inventory_location_type (head)
```

### Ver Historial de Migraciones

```bash
# Ver todas las migraciones
alembic history

# Ver con más detalle
alembic history --verbose

# Ver en formato de árbol
alembic history --indicate-current
```

### Aplicar Migraciones Pendientes

```bash
# Aplicar todas las pendientes
docker-compose exec app alembic upgrade head

# Aplicar solo la siguiente
docker-compose exec app alembic upgrade +1

# Aplicar hasta una migración específica
docker-compose exec app alembic upgrade 20250320_geocode_columns
```

### Revertir Migraciones

```bash
# Revertir la última migración
docker-compose exec app alembic downgrade -1

# Revertir hasta una migración específica
docker-compose exec app alembic downgrade 20250316_presupuesto_states

# Revertir TODAS (⚠️ PELIGROSO)
docker-compose exec app alembic downgrade base
```

### Ver SQL sin Ejecutar

```bash
# Ver el SQL que se ejecutará
docker-compose exec app alembic upgrade head --sql

# Ver SQL de una migración específica
docker-compose exec app alembic upgrade 20250320_geocode_columns --sql > migration.sql
```

---

## 📝 Crear Nueva Migración

### 1. Automática (desde modelos)

```bash
# Generar migración comparando modelos con DB
docker-compose exec app alembic revision --autogenerate -m "add_new_column_to_users"
```

**Nota**: Siempre revisa el archivo generado. Autogenerate no detecta:
- Cambios de tipo de datos
- Renombrado de columnas
- Renombrado de tablas
- Cambios de constraints complejos

### 2. Manual (vacía)

```bash
# Crear migración vacía para escribir a mano
docker-compose exec app alembic revision -m "custom_data_migration"
```

### 3. Formato de Migración

Todas las migraciones deben seguir este formato:

```python
"""descripción corta de la migración"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
import sqlalchemy as sa

# Metadata de la migración
revision = "YYYYMMDD_nombre_descriptivo"  # ID único
down_revision = "20250915_inventory_location_type"  # ID de la migración anterior
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Aplica los cambios al schema."""
    conn = op.get_bind()

    # Detectar tipo de DB
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'

    # PostgreSQL: setear schema
    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    # Verificar si la tabla existe (DEFENSIVO)
    if is_pg:
        table_exists = conn.execute(
            text("SELECT to_regclass('app.mi_tabla')")
        ).scalar()
    else:
        # SQLite: usar inspector
        from sqlalchemy import inspect
        inspector = inspect(conn)
        table_exists = 'mi_tabla' in inspector.get_table_names()

    if not table_exists:
        print("[SKIP] Table mi_tabla doesn't exist yet")
        return

    # Verificar si la columna existe
    from sqlalchemy import inspect
    inspector = inspect(conn)
    columns = {col['name'] for col in inspector.get_columns('mi_tabla')}

    if 'nueva_columna' not in columns:
        # Agregar columna
        if is_pg:
            conn.execute(text(
                "ALTER TABLE mi_tabla ADD COLUMN nueva_columna VARCHAR(50) DEFAULT 'valor'"
            ))
        else:
            # SQLite requiere batch mode para algunas operaciones
            with op.batch_alter_table('mi_tabla') as batch_op:
                batch_op.add_column(
                    sa.Column('nueva_columna', sa.String(50), server_default='valor')
                )


def downgrade() -> None:
    """Revierte los cambios (opcional, puede ser pass)."""
    # Implementación mínima o pass para evitar pérdida de datos
    pass
```

---

## ⚙️ Mejores Prácticas

### 1. Siempre Usa Lógica Defensiva

✅ **BIEN**:
```python
# Verificar antes de crear
if not table_exists:
    return

# Verificar antes de agregar columna
if 'columna' not in columns:
    add_column(...)
```

❌ **MAL**:
```python
# Asumir que la tabla existe
conn.execute(text("ALTER TABLE ..."))  # Puede fallar
```

### 2. Soporta Múltiples Bases de Datos

✅ **BIEN**:
```python
if is_pg:
    col_type = "VARCHAR(20)"
    bool_type = "BOOLEAN"
else:
    col_type = "TEXT"
    bool_type = "INTEGER"
```

❌ **MAL**:
```python
# Solo para PostgreSQL
col_type = "VARCHAR(20)"  # Fallará en SQLite
```

### 3. Usa `text()` para SQL Raw

✅ **BIEN**:
```python
conn.execute(text("UPDATE tabla SET columna = %s"), (valor,))
```

❌ **MAL**:
```python
conn.execute(f"UPDATE tabla SET columna = {valor}")  # SQL Injection!
```

### 4. Nombres de Migración Descriptivos

✅ **BIEN**:
```
20251102_add_user_preferences_table.py
20251102_add_email_verified_column.py
```

❌ **MAL**:
```
migration1.py
fix.py
update_db.py
```

### 5. Una Migración = Una Responsabilidad

✅ **BIEN**:
```
20251102_add_email_column.py        # Solo agregar columna
20251103_populate_email_defaults.py  # Solo backfill datos
```

❌ **MAL**:
```
20251102_refactor_users.py  # Hace 10 cosas diferentes
```

### 6. Testing de Migraciones

Antes de hacer commit:

```bash
# 1. Hacer backup
docker-compose exec postgres pg_dump -U obyra_owner obyra_dev > backup.sql

# 2. Probar migración
docker-compose exec app alembic upgrade head

# 3. Verificar que la app arranca
docker-compose restart app
curl http://localhost:5002/health

# 4. Probar downgrade
docker-compose exec app alembic downgrade -1

# 5. Probar upgrade de nuevo
docker-compose exec app alembic upgrade head
```

---

## 🔧 Troubleshooting

### Error: "Target database is not up to date"

**Causa**: Hay migraciones pendientes

**Solución**:
```bash
docker-compose exec app alembic upgrade head
```

### Error: "Can't locate revision identified by 'xxxxx'"

**Causa**: Falta una migración en la cadena

**Solución**:
```bash
# Ver las migraciones disponibles
alembic history

# Verificar que todas las migraciones estén en migrations/versions/
ls -la migrations/versions/
```

### Error: "column already exists"

**Causa**: La migración no es idempotente

**Solución**: Agregar check defensivo:
```python
columns = {col['name'] for col in inspector.get_columns('tabla')}
if 'columna' not in columns:
    # Agregar columna
```

### Error: "relation does not exist"

**Causa**: La tabla no existe aún (orden incorrecto)

**Solución**: Agregar check:
```python
table_exists = conn.execute(
    text("SELECT to_regclass('app.tabla')")
).scalar()
if not table_exists:
    return
```

### Migración Falla a Mitad de Camino

**Síntomas**: La DB queda en estado inconsistente

**Solución**:
```bash
# 1. Ver estado actual
alembic current

# 2. Marcar como ejecutada manualmente (⚠️ si ya se aplicó parcialmente)
alembic stamp head

# 3. O revertir
alembic downgrade -1

# 4. Restaurar backup si es necesario
docker-compose exec postgres psql -U obyra_owner obyra_dev < backup.sql
```

---

## 📊 Estructura de la Base de Datos

### Schema PostgreSQL

El proyecto usa un schema custom llamado `app`:

```sql
CREATE SCHEMA IF NOT EXISTS app;
SET search_path TO app, public;
```

**Todas las migraciones deben**:
1. Setear el search_path al inicio
2. Referenciar tablas como `app.tabla` o confiar en el search_path

### Tablas Principales

| Tabla | Migración que la creó | Descripción |
|-------|----------------------|-------------|
| usuarios | baseline | Usuarios del sistema |
| organizaciones | baseline | Organizaciones/empresas |
| org_memberships | 20250321_org_memberships_v2 | Membresías multi-org |
| obras | baseline | Proyectos/obras |
| presupuestos | baseline | Presupuestos |
| exchange_rates | 20250321_exchange_currency_fx_cac | Tipos de cambio |
| work_certifications | 20250901_work_certifications | Certificaciones de obra |
| inventory_item | baseline | Items de inventario |
| warehouse | baseline | Depósitos/almacenes |

---

## 🔄 Workflow Completo

### Desarrollo Local

```bash
# 1. Crear rama
git checkout -b feature/nueva-funcionalidad

# 2. Modificar modelos en models/
vim models/core.py

# 3. Generar migración
docker-compose exec app alembic revision --autogenerate -m "add_campo_a_usuarios"

# 4. Revisar migración generada
vim migrations/versions/20251102_add_campo_a_usuarios.py

# 5. Probar migración
docker-compose exec app alembic upgrade head

# 6. Verificar que funciona
docker-compose exec app flask shell
>>> from models import Usuario
>>> Usuario.query.first().campo_nuevo

# 7. Commit
git add migrations/versions/20251102_add_campo_a_usuarios.py models/core.py
git commit -m "feat: add campo_nuevo to Usuario model"

# 8. Push
git push origin feature/nueva-funcionalidad
```

### Producción

```bash
# En el servidor de producción

# 1. Pull latest code
git pull origin main

# 2. Backup DB
pg_dump -U obyra_owner obyra_production > backup_$(date +%Y%m%d).sql

# 3. Aplicar migraciones
docker-compose exec app alembic upgrade head

# 4. Restart app
docker-compose restart app

# 5. Verificar logs
docker-compose logs -f app

# 6. Verificar health
curl https://app.obyra.com/health
```

---

## 📚 Recursos

### Documentación Oficial
- [Alembic Docs](https://alembic.sqlalchemy.org/en/latest/)
- [Flask-Migrate Docs](https://flask-migrate.readthedocs.io/)
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)

### Comandos Útiles

```bash
# Ver ayuda de Alembic
alembic --help

# Ver ayuda de un comando específico
alembic upgrade --help

# Ver configuración actual
cat migrations/alembic.ini

# Ver entorno de Alembic
cat migrations/env.py
```

### Archivos de Referencia

- `migrations/versions/20251028_fixes.py` - Ejemplo de migración completa con lógica defensiva
- `_migrations_runtime_old.py` - Migraciones legacy (solo referencia, no usar)
- `PHASE_4_PLAN.md` - Plan de conversión de runtime a Alembic

---

## ⚠️ Advertencias Importantes

### ❌ NO HAGAS ESTO:

1. **No edites migraciones ya aplicadas en producción**
   - Crea una nueva migración en su lugar

2. **No elimines migraciones de `versions/`**
   - Rompe la cadena de versiones

3. **No uses `alembic downgrade` en producción sin backup**
   - Puede causar pérdida de datos

4. **No hagas migraciones con datos de usuario sin backup**
   - Siempre prueba en desarrollo primero

5. **No asumas que autogenerate es perfecto**
   - Siempre revisa el código generado

### ✅ SÍ HAZ ESTO:

1. **Siempre haz backup antes de migraciones en producción**
2. **Prueba migraciones en desarrollo/staging primero**
3. **Usa lógica defensiva (checkfirst, if exists)**
4. **Documenta migraciones complejas con comentarios**
5. **Mantén migraciones pequeñas y enfocadas**

---

## 🎓 Ejemplos Comunes

### Agregar Columna Simple

```python
def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'

    if is_pg:
        conn.execute(text("SET search_path TO app, public"))
        conn.execute(text(
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telefono VARCHAR(20)"
        ))
    else:
        with op.batch_alter_table('usuarios') as batch_op:
            batch_op.add_column(sa.Column('telefono', sa.String(20)))
```

### Agregar Índice

```python
def upgrade() -> None:
    op.create_index(
        'ix_usuarios_email',
        'usuarios',
        ['email'],
        unique=True,
        if_not_exists=True
    )
```

### Backfill de Datos

```python
def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'

    if is_pg:
        conn.execute(text("SET search_path TO app, public"))

    # Backfill: copiar email a username para usuarios sin username
    conn.execute(text("""
        UPDATE usuarios
        SET username = email
        WHERE username IS NULL OR username = ''
    """))
```

### Crear Tabla Nueva

```python
def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.engine.url.get_backend_name() == 'postgresql'

    if is_pg:
        conn.execute(text("SET search_path TO app, public"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES usuarios(id),
                theme VARCHAR(20) DEFAULT 'light',
                language VARCHAR(5) DEFAULT 'es',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
    else:
        op.create_table(
            'user_preferences',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('theme', sa.String(20), server_default='light'),
            sa.Column('language', sa.String(5), server_default='es'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now())
        )
```

---

## 📅 Historial de Cambios

| Fecha | Cambio | Autor |
|-------|--------|-------|
| 2025-11-02 | Conversión de runtime migrations a Alembic (Fase 4) | Phase 4 Refactoring |
| 2025-10-28 | Baseline inicial + fixes de role_modules | Phase 2 Refactoring |

---

**Última actualización**: 2 de Noviembre, 2025
**Fase**: 4 de 4 (Runtime Migrations → Alembic)
**Estado**: ✅ COMPLETADO
