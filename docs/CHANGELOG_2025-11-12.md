# Changelog - 12 de Noviembre 2025

## Resumen de Cambios

### 1. ✅ Información del Cliente en Obras
**Problema**: Al confirmar un presupuesto como obra, no se mostraba la información de contacto del cliente.

**Solución**:
- Actualizado template `obras/detalle.html` para usar `cliente_rel` como fallback
- Modificado `blueprint_presupuestos.py` para copiar `nombre_completo` del cliente en lugar de solo `nombre`
- Actualizado template `presupuestos/lista.html` para mostrar nombre completo del cliente

**Archivos modificados**:
- `templates/obras/detalle.html` (líneas 65-82)
- `blueprint_presupuestos.py` (línea 606)
- `templates/presupuestos/lista.html` (línea 92)

---

### 2. ✅ Pre-cargar Etapas del Presupuesto en Wizard
**Problema**: Al confirmar presupuesto como obra, el wizard no mostraba las etapas del presupuesto pre-seleccionadas.

**Solución**:
- Modificado endpoint `/obras/api/wizard-tareas/etapas` para retornar `etapas_preseleccionadas`
- Actualizado `wizard.js` para pre-seleccionar etapas del presupuesto
- Las etapas vienen marcadas pero el usuario puede desmarcalas o agregar más

**Archivos modificados**:
- `obras.py` (líneas 2522-2542)
- `static/js/wizard.js` (líneas 319-325)

---

### 3. ✅ Fix Error CSRF al Eliminar Obra
**Problema**: Error "Bad Request - The CSRF token is missing" al intentar eliminar una obra.

**Solución**:
- Agregado token CSRF al formulario dinámico de eliminación
- Token se obtiene desde `{{ csrf_token() }}` en variable JavaScript
- Garantiza que el token esté disponible para todos los formularios dinámicos

**Archivos modificados**:
- `templates/obras/lista.html` (líneas 716-732)

---

### 4. ✅ Sistema de Roles y Permisos Mejorado
**Problema**:
- Solo se podían eliminar presupuestos en estado "borrador" o "perdido"
- No existía diferenciación clara entre rol Admin y PM
- Faltaba documentación de roles

**Solución implementada**:

#### Permisos de Eliminación de Presupuestos
- **Admins** ahora pueden eliminar presupuestos en **cualquier estado**
- Única restricción: No se pueden eliminar presupuestos confirmados como obra
- Removida validación restrictiva de estados

#### Roles Definidos

| Rol | Presupuestos | Obras | Eliminar |
|-----|-------------|-------|----------|
| **Admin** | ✅ Crear, Ver, Editar, Eliminar | ✅ Todo | ✅ Sí |
| **PM** | ✅ Crear, Ver, Editar | ✅ Ver, Editar tareas | ❌ No |
| **Técnico** | ✅ Crear, Ver, Editar | ✅ Crear, Ver, Editar | ❌ No |
| **Operario** | ❌ Sin acceso | ✅ Solo asignadas | ❌ No |

**Archivos modificados**:
- `blueprint_presupuestos.py` (múltiples líneas)
- `templates/presupuestos/lista.html` (línea 238)

**Archivos creados**:
- `docs/ROLES.md` - Documentación completa del sistema de roles

---

### 5. ✅ Configuración Sistema de Facturación
**Preparación**: Sistema listo para cuando se tenga empresa constituida legalmente.

**Creado**:
- `config/billing_config.py` - Configuración centralizada de facturación
- `docs/FACTURACION.md` - Guía completa de configuración AFIP
- Actualizado `.env.example` con todas las variables de facturación

**Features incluidas**:
- Integración con AFIP para facturación electrónica
- Soporte para Mercado Pago
- Facturación automática mensual
- Datos bancarios para transferencias

---

## Commits Realizados

### Commit 1: `b901407`
```
feat(obras): mostrar info de cliente y pre-cargar etapas de presupuesto en wizard

- Agregar fallback a cliente_rel en template de detalle de obra
- Convertir datos de contacto en links clickeables
- Modificar API wizard para retornar etapas_preseleccionadas
- Pre-seleccionar etapas del presupuesto en wizard paso 1
```

### Commit 2: `fce9105`
```
fix(obras): agregar token CSRF al eliminar obra

- Agregar csrf_token al formulario dinámico de eliminación
- Soluciona error 400 "Bad Request - The CSRF token is missing"
```

### Commit 3: `08837da`
```
fix(obras): usar csrf_token() directo en variable JavaScript

- Cambiar de meta tag a variable JavaScript directa
- Simplifica obtención del token para formularios dinámicos
```

### Commit 4: `0ff0dd6`
```
fix(presupuestos): usar nombre_completo del cliente en lugar de solo nombre

- Actualizar template lista para mostrar nombre_completo
- Al confirmar presupuesto como obra, copiar nombre_completo
- Soluciona problema de cliente que aparece como "Cliente por confirmar"
```

### Commit 5: `52d9c01`
```
feat(presupuestos): mejorar sistema de roles y permisos

- Admins pueden eliminar presupuestos en cualquier estado
- Agregar rol PM con permisos crear/editar sin eliminar
- Crear docs/ROLES.md con tabla completa de permisos
```

---

## Pendientes para Mañana

### Issues Identificados
1. ✅ **Verificar eliminación de presupuestos** - Rebuild de Docker realizado, pendiente de prueba

### Posibles Mejoras Futuras
- [ ] Implementar dashboard específico para rol Operario
- [ ] Agregar filtros por rol en vistas de presupuestos/obras
- [ ] Implementar auditoría de cambios por rol
- [ ] Agregar notificaciones push para operarios

---

## Documentación Actualizada

### Nuevos Documentos
- `docs/ROLES.md` - Sistema completo de roles y permisos
- `docs/FACTURACION.md` - Guía de configuración de facturación AFIP

### Configuración
- `.env.example` - Actualizado con variables de facturación y seguridad
- `config/billing_config.py` - Configuración centralizada de facturación

---

## Comandos para Asignar Roles

```sql
-- Asignar rol PM
UPDATE usuarios SET role = 'pm' WHERE email = 'gestor@empresa.com';

-- Asignar rol Operario
UPDATE usuarios SET role = 'operario' WHERE email = 'trabajador@empresa.com';

-- Asignar rol Admin
UPDATE usuarios SET role = 'admin' WHERE email = 'admin@empresa.com';
```

---

## Notas Técnicas

### Docker
- Rebuild completo realizado: `docker-compose down && docker-compose up -d --build`
- Todos los contenedores funcionando correctamente
- Código Python actualizado y compilado

### Caché
- Limpieza de caché de Python compilado (`.pyc`)
- Recomendado: CTRL+F5 en navegador para limpiar caché del cliente

---

**Última actualización**: 12 de Noviembre 2025, 19:00 UTC
**Estado del sistema**: ✅ Operativo y actualizado
