# Plan de consolidación de sistemas duplicados

OBYRA tiene 3 generaciones de modelos coexistiendo. La consolidación es **alto riesgo** y requiere:
1. Cobertura de tests amplia
2. Migración de datos en producción
3. Window de mantenimiento

Este documento es el plan, NO ejecutar sin pruebas exhaustivas.

## 1. Sistema de Inventario

### Estado actual
| Sistema | Modelos | Usos |
|---------|---------|------|
| Legacy (activo) | `ItemInventario`, `CategoriaInventario`, `MovimientoInventario`, `UsoInventario` | **378 referencias en 35 archivos** |
| Nuevo (parcial) | `InventoryItem`, `InventoryCategory`, `Stock`, `StockMovement` | 27 referencias en 9 archivos |

### Decisión recomendada
**Mantener `ItemInventario` como canónico** y eliminar `InventoryItem`. El sistema legacy es el que tiene los datos y el código. Migrar todo al nuevo sería:
- Tocar 35 archivos
- Migrar miles de filas en producción
- Riesgo alto de introducir bugs

### Pasos para eliminar `InventoryItem`
1. Renombrar `inventario_new.py` → `_inventario_new_DEAD.py.bak` (ya está deshabilitado)
2. Identificar features que usan `InventoryItem` y reescribirlas con `ItemInventario`
3. Eliminar `InventoryItem`, `InventoryCategory`, `Stock`, `StockMovement`, `Warehouse` de `models/inventory.py`
4. Eliminar tablas de la BD con migración Alembic

## 2. Sistema de Proveedores

### Estado actual
| Sistema | Modelo | Usos |
|---------|--------|------|
| Legacy | `Proveedor` | 73 |
| Marketplace | `Supplier` | 46 |
| OC | `ProveedorOC` | 55 |

### Decisión recomendada
**Mantener los 3, son funcionalmente distintos:**
- `Proveedor`: catálogo viejo (probablemente eliminable)
- `Supplier`: para el marketplace B2B (vendedores externos)
- `ProveedorOC`: para órdenes de compra internas

`Proveedor` es el único candidato a eliminar. Verificar primero que no tenga datos críticos.

## 3. Campo `Usuario.rol` vs `Usuario.role`

### Estado actual
- `.role`: campo activo, mayoría del código lo usa
- `.rol`: marcado deprecated, sincronizado con `_sync_rol_from_role`
- Solo se usa en lugares legacy (templates principalmente)

### Decisión recomendada
1. Migrar templates uno por uno (cambiar `current_user.rol` → `current_user.role`)
2. Mantener `_sync_rol_from_role` durante la transición
3. Cuando 0 lugares usen `.rol`, eliminar la columna con migración Alembic

### Templates a actualizar (76 usos)
Ya identificados en la auditoría — requieren actualización manual cuidadosa.

## Prerrequisitos antes de empezar

1. **Tests de regresión** que cubran:
   - Crear/editar/eliminar items de inventario
   - Movimientos de stock
   - Asignación de roles
   - Login con cada tipo de rol

2. **Backup completo** de la BD antes de cada paso

3. **Window de mantenimiento** o feature flags para rollback

## Por qué no se hizo en Fase 3

La consolidación toca 35-40 archivos críticos con datos en producción. El riesgo de introducir bugs sutiles es muy alto sin una suite de tests robusta. Es mejor:
1. Primero ampliar cobertura de tests (Fase 4 o aparte)
2. Hacer la consolidación con un branch dedicado y QA exhaustiva
3. Deploy con feature flags y monitoreo intensivo

**Estimación de esfuerzo total: 2-3 semanas con tests previos.**
