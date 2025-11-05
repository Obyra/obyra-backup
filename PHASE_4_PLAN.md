# Plan Fase 4: Runtime Migrations → Alembic

## 🎯 Objetivo

Convertir las 11 funciones de migración runtime en `migrations_runtime.py` a migraciones Alembic apropiadas, eliminando la lógica de migración del código de startup de la aplicación.

---

## 📊 Estado Actual

### Problemas con Runtime Migrations

1. **Performance**: Se ejecutan en cada startup de la app (aunque usen sentinels)
2. **Mantenibilidad**: Difícil trackear qué cambios se aplicaron y cuándo
3. **Rollback**: No hay forma de hacer rollback automático
4. **Versionado**: No están versionadas con Alembic
5. **Testing**: Difícil testear migraciones de forma aislada
6. **Documentación**: Sentinels en `instance/migrations/` son archivos `.done` sin SQL visible

### Archivos Afectados

```
migrations_runtime.py          (1,051 líneas - 11 funciones)
app.py                         (llama a migrations_runtime)
instance/migrations/*.done     (11 archivos sentinel)
```

---

## 🔄 Estrategia de Migración

### Fase 4.1: Crear Migraciones Alembic

Para cada función runtime, crear una migración Alembic equivalente que:

1. **Mantenga la lógica defensiva**:
   - `checkfirst=True` para CREATE TABLE
   - Verificación de columnas existentes antes de ALTER
   - Soporte PostgreSQL y SQLite

2. **Preserve el comportamiento**:
   - Mismas columnas, tipos, defaults
   - Mismo backfill de datos
   - Mismos índices y constraints

3. **Sea idempotente**:
   - Puede ejecutarse múltiples veces sin error
   - Usa `batch_alter_table` para SQLite

### Fase 4.2: Actualizar App Startup

1. Remover llamadas a `migrations_runtime.py` en `app.py`
2. Mantener `migrations_runtime.py` como referencia (renombrar a `_old`)
3. Documentar el cambio

### Fase 4.3: Documentación

1. Crear `MIGRATIONS_GUIDE.md` con:
   - Cómo crear nuevas migraciones
   - Cómo ejecutar migraciones
   - Cómo hacer rollback
   - Mejores prácticas

---

## 📋 Lista de Migraciones a Convertir

### 1. Avance Audit Columns (SQLite only)
**Función**: `ensure_avance_audit_columns()`
**Sentinel**: `20250910_add_avance_audit_cols.done`
**Tabla**: `tarea_avances`
**Cambios**:
- ADD COLUMN `cantidad_ingresada NUMERIC`
- ADD COLUMN `unidad_ingresada VARCHAR(10)`

**Nueva migración Alembic**: `20250910_add_avance_audit_cols.py`

---

### 2. Presupuesto State Columns
**Función**: `ensure_presupuesto_state_columns()`
**Sentinel**: `20250316_presupuesto_states.done`
**Tabla**: `presupuestos`
**Cambios**:
- ADD COLUMN `estado VARCHAR(20) DEFAULT 'borrador'`
- ADD COLUMN `perdido_motivo TEXT`
- ADD COLUMN `perdido_fecha TIMESTAMP`
- ADD COLUMN `deleted_at TIMESTAMP`
- UPDATE estado basado en `confirmado_como_obra`

**Nueva migración Alembic**: `20250316_presupuesto_states.py`

---

### 3. Item Presupuesto Stage Columns
**Función**: `ensure_item_presupuesto_stage_columns()`
**Sentinel**: `20250317_item_stage_cols.done`
**Tabla**: `items_presupuesto`
**Cambios**:
- ADD COLUMN `etapa_id INTEGER`
- ADD COLUMN `origen VARCHAR(20) DEFAULT 'manual'`
- UPDATE origen defaults

**Nueva migración Alembic**: `20250317_item_stage_cols.py`

---

### 4. Presupuesto Validity Columns
**Función**: `ensure_presupuesto_validity_columns()`
**Sentinel**: `20250319_presupuesto_validity_v2.done`
**Tabla**: `presupuestos`
**Cambios**:
- ADD COLUMN `vigencia_dias INTEGER DEFAULT 30`
- ADD COLUMN `fecha_vigencia DATE`
- ADD COLUMN `vigencia_bloqueada BOOLEAN DEFAULT FALSE`
- Backfill: calcular fecha_vigencia = fecha + vigencia_dias

**Nueva migración Alembic**: `20250319_presupuesto_validity_v2.py`

---

### 5. Inventory Package Columns
**Función**: `ensure_inventory_package_columns()`
**Sentinel**: `20250912_inventory_package_options.done`
**Tabla**: `inventory_item`
**Cambios**:
- ADD COLUMN `package_options TEXT`

**Nueva migración Alembic**: `20250912_inventory_package_options.py`

---

### 6. Inventory Location Columns
**Función**: `ensure_inventory_location_columns()`
**Sentinel**: `20250915_inventory_location_type.done`
**Tabla**: `warehouse`
**Cambios**:
- ADD COLUMN `tipo VARCHAR(20) DEFAULT 'deposito'`
- UPDATE tipo defaults

**Nueva migración Alembic**: `20250915_inventory_location_type.py`

---

### 7. Exchange Currency Tables & Columns
**Función**: `ensure_exchange_currency_columns()`
**Sentinel**: `20250321_exchange_currency_fx_cac.done`
**Tablas**:
- CREATE `exchange_rates` (con índices)
- CREATE `cac_indices` (con índices)
- CREATE `pricing_indices` (con índices)
- ALTER `presupuestos` (8+ columnas FX)
- ALTER `items_presupuesto` (5+ columnas FX)
- ALTER `materiales`, `mano_obra`, `equipos` (4 columnas FX cada uno)
- Seed inicial de CAC

**Nueva migración Alembic**: `20250321_exchange_currency_fx_cac.py`

---

### 8. Geocode Columns
**Función**: `ensure_geocode_columns()`
**Sentinel**: `20250320_geocode_columns.done`
**Tablas**:
- CREATE `geocode_cache` (via model)
- ALTER `obras` (6 columnas geo)
- ALTER `presupuestos` (8 columnas geo)

**Nueva migración Alembic**: `20250320_geocode_columns.py`

---

### 9. Org Memberships Table
**Función**: `ensure_org_memberships_table()`
**Sentinel**: `20250321_org_memberships_v2.done`
**Tablas**:
- ALTER `usuarios` ADD COLUMN `primary_org_id INTEGER`
- CREATE `org_memberships` con 8 columnas + índices
- Backfill desde `usuarios` (mapeo roles, estados)

**Nueva migración Alembic**: `20250321_org_memberships_v2.py`

---

### 10. Work Certification Tables
**Función**: `ensure_work_certification_tables()`
**Sentinel**: `20250901_work_certifications.done`
**Tablas**:
- CREATE `work_certifications` (17 columnas + índices)
- CREATE `work_certification_items` (9 columnas + índices)
- CREATE `work_payments` (16 columnas + índices)

**Nueva migración Alembic**: `20250901_work_certifications.py`

---

### 11. Wizard Budget Tables
**Función**: `ensure_wizard_budget_tables()`
**Sentinel**: `20250330_wizard_budget_tables.done`
**Tablas**:
- CREATE `wizard_stage_variants` (8 columnas JSONB)
- CREATE `wizard_stage_coefficients` (14 columnas JSONB)
- Seed default coefficients via service

**Nueva migración Alembic**: `20250330_wizard_budget_tables.py`

---

## 🛠️ Implementación

### Pasos

1. **Crear migraciones Alembic** (11 archivos):
   ```bash
   # Para cada migración runtime, crear equivalente Alembic
   alembic revision -m "add_avance_audit_cols"
   # ... etc
   ```

2. **Código de ejemplo** (con lógica defensiva):
   ```python
   def upgrade():
       # PostgreSQL vs SQLite detection
       bind = op.get_bind()
       is_pg = bind.engine.url.get_backend_name() == 'postgresql'

       # Check if column exists before adding
       inspector = sa.inspect(bind)
       columns = {col['name'] for col in inspector.get_columns('presupuestos')}

       if 'estado' not in columns:
           if is_pg:
               op.add_column('presupuestos',
                   sa.Column('estado', sa.String(20), server_default='borrador'))
           else:
               with op.batch_alter_table('presupuestos') as batch_op:
                   batch_op.add_column(
                       sa.Column('estado', sa.Text(), server_default='borrador'))
   ```

3. **Testing**:
   ```bash
   # Bajar base limpia
   alembic downgrade base

   # Aplicar todas las migraciones
   alembic upgrade head

   # Verificar que todo funciona
   docker-compose exec app flask shell
   ```

4. **Limpieza**:
   ```bash
   # Renombrar archivo runtime
   mv migrations_runtime.py _migrations_runtime_old.py

   # Eliminar sentinels (opcional, o mantener como histórico)
   rm -rf instance/migrations/*.done
   ```

---

## ✅ Beneficios Esperados

1. **Versionado**: Todas las migraciones en `migrations/versions/`
2. **Rollback**: `alembic downgrade` funcionará
3. **Performance**: No se ejecutan en cada startup
4. **Auditabilidad**: Git history de cambios de schema
5. **Testing**: Testear migraciones de forma aislada
6. **Documentación**: SQL generado visible en archivos .py
7. **CI/CD**: Integrar con pipelines de deployment

---

## 📝 Checklist de Completación

- [ ] Crear 11 migraciones Alembic
- [ ] Testear upgrade de base limpia
- [ ] Testear upgrade de base existente (con sentinels)
- [ ] Testear downgrade de cada migración
- [ ] Actualizar `app.py` (remover imports runtime)
- [ ] Renombrar `migrations_runtime.py` → `_old`
- [ ] Crear `MIGRATIONS_GUIDE.md`
- [ ] Actualizar `.gitignore` (ignorar `instance/migrations/`)
- [ ] Documentar en README cómo correr migraciones
- [ ] Crear `PHASE_4_SUMMARY.md`

---

## ⚠️ Consideraciones

### Compatibilidad con Sentinels Existentes

Si un entorno ya tiene los archivos `.done`, las nuevas migraciones Alembic deben:
- Detectar si ya se aplicó (checking columnas/tablas)
- Ser idempotentes (no fallar si ya existe)
- No duplicar trabajo

### SQLite vs PostgreSQL

Mantener soporte dual con:
- `batch_alter_table` para SQLite
- Type detection para columnas (VARCHAR vs TEXT, BOOLEAN vs INTEGER)
- Defaults apropiados (`NOW()` vs `CURRENT_TIMESTAMP`)

### Orden de Migraciones

Respetar el orden cronológico de los sentinels:
1. 20250316 → Presupuesto states
2. 20250317 → Item stage cols
3. 20250318/19 → Validity
4. 20250320 → Geocode
5. 20250321 → Exchange + Org memberships
6. 20250330 → Wizard
7. 20250901 → Certifications
8. 20250910 → Avance audit
9. 20250912 → Package options
10. 20250915 → Location type

---

## 📅 Timeline Estimado

- **Crear migraciones**: 2-3 horas (11 archivos)
- **Testing**: 1 hora
- **Actualizar app.py**: 30 minutos
- **Documentación**: 1 hora
- **Total**: ~4-5 horas

---

**Fecha**: 2 de Noviembre, 2025
**Fase**: 4 de 4 (Runtime Migrations → Alembic)
**Estado**: 📋 PLANIFICACIÓN
