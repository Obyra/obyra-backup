# Roles y Permisos del Sistema OBYRA

Este documento describe los roles disponibles en el sistema y sus permisos específicos.

## Roles Disponibles

### 1. **Admin / Administrador**
**Acceso completo al sistema**

#### Permisos:
- ✅ **Presupuestos**: Crear, ver, editar, eliminar (incluso presupuestos enviados)
- ✅ **Obras**: Ver, crear, editar, eliminar, gestionar etapas y tareas
- ✅ **Clientes**: Ver, crear, editar, eliminar
- ✅ **Inventario**: Ver, crear, editar, eliminar items
- ✅ **Usuarios**: Gestionar usuarios, roles y permisos
- ✅ **Reportes**: Acceso completo a todos los reportes
- ✅ **Configuración**: Acceso a configuración del sistema

#### Restricciones:
- ❌ No puede eliminar presupuestos que ya fueron confirmados como obra

---

### 2. **PM (Project Manager)**
**Gestión de proyectos sin permisos de eliminación**

#### Permisos:
- ✅ **Presupuestos**: Crear, ver, editar
- ✅ **Obras**: Ver, editar etapas y tareas
- ✅ **Clientes**: Ver, crear, editar
- ✅ **Inventario**: Ver items
- ✅ **Reportes**: Ver reportes de proyectos

#### Restricciones:
- ❌ **No puede eliminar** presupuestos
- ❌ **No puede eliminar** obras
- ❌ No puede gestionar usuarios
- ❌ No tiene acceso a configuración del sistema

---

### 3. **Operario**
**Acceso limitado para trabajadores de campo**

#### Permisos:
- ✅ **Dashboard Personal**: Ver sus tareas asignadas
- ✅ **Obras Asignadas**: Ver solo las obras donde está asignado
- ✅ **Tareas**: Completar tareas asignadas
- ✅ **Inventario**: Ver y reportar uso de materiales

#### Restricciones:
- ❌ No puede ver presupuestos
- ❌ No puede ver todas las obras (solo las asignadas)
- ❌ No puede crear/editar/eliminar presupuestos
- ❌ No puede crear/editar/eliminar obras
- ❌ No puede gestionar clientes
- ❌ No puede ver reportes globales
- ❌ No puede gestionar usuarios

---

### 4. **Técnico**
**Acceso técnico para gestión operativa**

#### Permisos:
- ✅ **Presupuestos**: Crear, ver, editar
- ✅ **Obras**: Ver, crear, editar, gestionar etapas y tareas
- ✅ **Clientes**: Ver, crear, editar
- ✅ **Inventario**: Ver, crear, editar
- ✅ **Reportes**: Ver reportes técnicos

#### Restricciones:
- ❌ No puede eliminar presupuestos ni obras (solo Admin)
- ❌ No puede gestionar usuarios
- ❌ No tiene acceso a configuración del sistema

---

## Tabla Resumen de Permisos

| Módulo | Admin | PM | Técnico | Operario |
|--------|-------|----|---------| ---------|
| **Presupuestos** |
| Ver | ✅ | ✅ | ✅ | ❌ |
| Crear | ✅ | ✅ | ✅ | ❌ |
| Editar | ✅ | ✅ | ✅ | ❌ |
| Eliminar | ✅ | ❌ | ❌ | ❌ |
| **Obras** |
| Ver todas | ✅ | ✅ | ✅ | ❌ |
| Ver asignadas | ✅ | ✅ | ✅ | ✅ |
| Crear | ✅ | ❌ | ✅ | ❌ |
| Editar | ✅ | ✅ | ✅ | ❌ |
| Eliminar | ✅ | ❌ | ❌ | ❌ |
| **Tareas** |
| Ver todas | ✅ | ✅ | ✅ | ❌ |
| Ver asignadas | ✅ | ✅ | ✅ | ✅ |
| Completar | ✅ | ✅ | ✅ | ✅ |
| Crear/Editar | ✅ | ✅ | ✅ | ❌ |
| **Clientes** |
| Ver | ✅ | ✅ | ✅ | ❌ |
| Crear/Editar | ✅ | ✅ | ✅ | ❌ |
| Eliminar | ✅ | ❌ | ❌ | ❌ |
| **Inventario** |
| Ver | ✅ | ✅ | ✅ | ✅ |
| Crear/Editar | ✅ | ❌ | ✅ | ❌ |
| Reportar uso | ✅ | ✅ | ✅ | ✅ |
| **Usuarios** |
| Gestionar | ✅ | ❌ | ❌ | ❌ |
| **Reportes** |
| Ver todos | ✅ | ✅ | ✅ | ❌ |
| **Configuración** |
| Acceso | ✅ | ❌ | ❌ | ❌ |

---

## Notas Importantes

### Presupuestos Confirmados como Obra
- **Ningún rol** puede eliminar un presupuesto que ya fue confirmado como obra
- Esto protege la integridad de los datos históricos del proyecto

### Dashboard del Operario
- El operario tiene su propio dashboard simplificado
- Solo ve:
  - Sus tareas pendientes
  - Obras donde está asignado
  - Inventario disponible
  - Sus reportes de trabajo

### Creación de Usuarios
- Solo **Admin** puede crear y asignar roles a usuarios
- Para asignar el rol correcto al crear un usuario:
  ```sql
  -- Ejemplo de asignación de rol
  UPDATE usuarios SET role = 'pm' WHERE email = 'gestor@empresa.com';
  UPDATE usuarios SET role = 'operario' WHERE email = 'trabajador@empresa.com';
  ```

---

## Implementación en Código

### Backend (Python)
Los roles se verifican usando:

```python
# Verificar rol del usuario
user_role = getattr(current_user, 'role', None) or getattr(current_user, 'rol', None)

# Roles que pueden editar
roles_edicion = ['admin', 'pm', 'administrador', 'tecnico']
if user_role not in roles_edicion:
    return jsonify({'error': 'No tienes permisos'}), 403

# Solo admin puede eliminar
roles_eliminacion = ['admin', 'administrador']
es_admin = user_role in roles_eliminacion or current_user.es_admin()
if not es_admin:
    return jsonify({'error': 'No tienes permisos para eliminar'}), 403
```

### Frontend (Jinja2)
En templates se verifica con:

```jinja2
{% if current_user.role == 'admin' or current_user.es_admin() %}
    <!-- Botón eliminar solo para admins -->
    <button onclick="eliminarPresupuesto(...)">Eliminar</button>
{% endif %}

{% if current_user.role in ['admin', 'pm', 'tecnico'] %}
    <!-- Botón editar para admin, PM y técnico -->
    <button onclick="editarPresupuesto(...)">Editar</button>
{% endif %}
```

---

**Última actualización**: 2025-01-12
