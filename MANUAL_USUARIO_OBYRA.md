# Manual de Usuario - OBYRA IA

## Plataforma de Gestión Inteligente para Construcción

---

## Tabla de Contenidos

1. [Introducción](#1-introducción)
2. [Primeros Pasos](#2-primeros-pasos)
3. [Módulo de Presupuestos](#3-módulo-de-presupuestos)
4. [Módulo de Obras](#4-módulo-de-obras)
5. [Módulo de Inventario](#5-módulo-de-inventario)
6. [Módulo de Requerimientos](#6-módulo-de-requerimientos)
7. [Módulo de Equipos](#7-módulo-de-equipos)
8. [Módulo de Clientes](#8-módulo-de-clientes)
9. [Módulo de Reportes](#9-módulo-de-reportes)
10. [Módulo de Seguridad](#10-módulo-de-seguridad)
11. [Marketplace](#11-marketplace)
12. [Configuración de Cuenta](#12-configuración-de-cuenta)
13. [Roles y Permisos](#13-roles-y-permisos)
14. [Preguntas Frecuentes](#14-preguntas-frecuentes)

---

## 1. Introducción

### ¿Qué es OBYRA IA?

OBYRA IA es una plataforma integral para gestionar proyectos de construcción. Permite:

- Crear presupuestos con asistencia de Inteligencia Artificial
- Gestionar obras con seguimiento en tiempo real
- Controlar inventario de materiales
- Coordinar equipos de trabajo
- Generar reportes y análisis

### Acceso a la Plataforma

- **URL de la aplicación:** https://app.obyra.com.ar
- **Sitio web:** https://www.obyra.com.ar

---

## 2. Primeros Pasos

### 2.1 Registro

1. Ingresa a https://app.obyra.com.ar
2. Haz clic en **"Crear cuenta"**
3. Completa tus datos:
   - Nombre y apellido
   - Email
   - Contraseña
4. También puedes registrarte con **Google**

### 2.2 Iniciar Sesión

1. Ingresa tu email y contraseña
2. Haz clic en **"Ingresar"**
3. Si olvidaste tu contraseña, usa **"¿Olvidaste tu contraseña?"**

### 2.3 Navegación Principal

El menú lateral izquierdo contiene todos los módulos:

| Icono | Módulo | Función |
|-------|--------|---------|
| 📊 | Dashboard | Vista general y KPIs |
| 📋 | Presupuestos | Crear y gestionar cotizaciones |
| 🏗️ | Obras | Gestionar proyectos |
| 📦 | Inventario | Control de materiales |
| 👥 | Equipos | Gestión de personal |
| 🛒 | Marketplace | Comprar materiales |
| ⚙️ | Configuración | Tu cuenta y organización |

---

## 3. Módulo de Presupuestos

### 3.1 ¿Para qué sirve?

Crear cotizaciones profesionales para tus clientes, con cálculo automático de materiales y mano de obra.

### 3.2 Crear Presupuesto con IA (Recomendado)

1. Ve a **Presupuestos** → **Crear con IA**
2. Describe la obra:
   - Tipo de construcción (casa, departamento, local, etc.)
   - Superficie en m²
   - Ubicación
   - Características especiales
3. La IA calculará automáticamente:
   - Etapas de la obra
   - Materiales necesarios
   - Mano de obra estimada
   - Costos aproximados
4. Revisa y ajusta los valores si es necesario
5. Guarda el presupuesto

### 3.3 Crear Presupuesto Manual

1. Ve a **Presupuestos** → **Crear Manual**
2. Completa los datos:
   - Cliente
   - Descripción de la obra
   - Ubicación
3. Agrega items uno por uno:
   - Descripción
   - Cantidad
   - Unidad (m², ml, unidad, etc.)
   - Precio unitario
4. El sistema calcula subtotales automáticamente
5. Agrega IVA y descuentos si aplica
6. Guarda el presupuesto

### 3.4 Estados del Presupuesto

| Estado | Significado |
|--------|-------------|
| **Borrador** | En edición, no enviado |
| **Enviado** | Enviado al cliente, esperando respuesta |
| **Aprobado** | Cliente aceptó, listo para convertir en obra |
| **Rechazado** | Cliente no aceptó |
| **Vencido** | Pasó la fecha de vigencia |

### 3.5 Convertir Presupuesto en Obra

Cuando el cliente aprueba:

1. Abre el presupuesto aprobado
2. Haz clic en **"Confirmar como Obra"**
3. El sistema crea automáticamente:
   - La obra con todos los datos
   - Las etapas planificadas
   - Las tareas iniciales

### 3.6 Generar PDF

1. Abre el presupuesto
2. Haz clic en **"Descargar PDF"**
3. El PDF incluye:
   - Logo de tu empresa
   - Datos del cliente
   - Detalle de items
   - Totales y condiciones

### 3.7 Enviar por Email

1. Abre el presupuesto
2. Haz clic en **"Enviar por Email"**
3. El cliente recibe el presupuesto en su correo

---

## 4. Módulo de Obras

### 4.1 ¿Para qué sirve?

Gestionar el ciclo completo de un proyecto de construcción: planificación, ejecución y seguimiento.

### 4.2 Crear una Obra

1. Ve a **Obras** → **Crear Obra**
2. Completa los datos básicos:
   - Nombre de la obra
   - Cliente
   - Dirección (el sistema geolocaliza automáticamente)
   - Fecha de inicio
   - Presupuesto total
3. Guarda la obra

### 4.3 Estados de la Obra

| Estado | Significado |
|--------|-------------|
| **Planificación** | En preparación, no iniciada |
| **En curso** | Trabajo activo |
| **Pausada** | Detenida temporalmente |
| **Finalizada** | Completada |
| **Cancelada** | No se realizará |

### 4.4 Gestionar Etapas

Las etapas organizan el trabajo en fases:

**Etapas típicas:**
- Cimentación
- Estructura
- Cubierta
- Cerramientos
- Instalaciones eléctricas
- Instalaciones sanitarias
- Terminaciones

**Para agregar etapas:**
1. Abre la obra
2. Ve a la sección **Etapas**
3. Haz clic en **"Agregar Etapa"**
4. Selecciona el tipo o crea una personalizada
5. Define fechas estimadas

### 4.5 Gestionar Tareas

Cada etapa tiene tareas específicas:

1. Dentro de una etapa, haz clic en **"Nueva Tarea"**
2. Completa:
   - Nombre de la tarea
   - Descripción
   - Cantidad y unidad
   - Responsable (quién la ejecutará)
   - Fecha límite
3. Guarda la tarea

### 4.6 Registrar Avances

Los operarios registran su trabajo diario:

1. Abre la tarea
2. Haz clic en **"Registrar Avance"**
3. Indica:
   - Porcentaje completado
   - Horas trabajadas
   - Observaciones
   - Fotos del trabajo (opcional)
4. Guarda el avance

El sistema calcula automáticamente el progreso de la etapa y de la obra.

### 4.7 Ver Progreso

En el detalle de la obra puedes ver:
- Barra de progreso general
- Progreso por etapa
- Tareas pendientes vs completadas
- Costos ejecutados vs presupuestados

### 4.8 Mapa de Obras

En la lista de obras hay un mapa interactivo:
- Muestra todas tus obras geolocalizadas
- Haz clic en un marcador para ver detalles
- Consulta información del clima en cada ubicación

### 4.9 Mis Tareas (para Operarios)

Si eres operario, en **"Mis Tareas"** ves solo las tareas asignadas a ti:
- Lista de tareas pendientes
- Puedes registrar avances directamente
- Marcar tareas como completadas

---

## 5. Módulo de Inventario

### 5.1 ¿Para qué sirve?

Controlar el stock de materiales, herramientas y equipos.

### 5.2 Ver Inventario

1. Ve a **Inventario**
2. Verás la lista de todos los items con:
   - Nombre y código
   - Categoría
   - Cantidad disponible
   - Ubicación (almacén)
   - Precio

### 5.3 Agregar Item

1. Haz clic en **"Nuevo Item"**
2. Completa:
   - Nombre
   - Descripción
   - Categoría (cemento, hierro, eléctricos, etc.)
   - Cantidad inicial
   - Unidad (kg, unidad, m², etc.)
   - Precio unitario
   - Stock mínimo (para alertas)
   - Ubicación/almacén
3. Guarda

### 5.4 Categorías

Organiza tu inventario en categorías:

**Categorías comunes:**
- Materiales de construcción
- Herrería
- Electricidad
- Plomería
- Pintura
- Herramientas
- Equipos de seguridad

Para crear categorías: **Inventario** → **Categorías** → **Nueva Categoría**

### 5.5 Movimientos de Stock

**Tipos de movimientos:**

| Tipo | Cuándo usar |
|------|-------------|
| **Entrada** | Cuando compras o recibes material |
| **Salida** | Cuando usas material en obra |
| **Traslado** | Mover entre almacenes |
| **Ajuste** | Corregir diferencias de inventario |

**Registrar movimiento:**
1. Abre el item
2. Haz clic en **"Registrar Movimiento"**
3. Selecciona tipo, cantidad y motivo
4. Si es para obra, selecciona la obra

### 5.6 Uso en Obra

Para asignar materiales a una obra:
1. Ve a **Inventario** → **Uso en Obra**
2. Selecciona la obra
3. Selecciona el item y cantidad
4. Confirma

El stock se descuenta automáticamente.

### 5.7 Alertas de Stock

El sistema te avisa cuando:
- Un item baja del stock mínimo
- Hay materiales por vencer
- Una obra necesita reposición

Ve a **Inventario** → **Alertas** para ver todas las alertas activas.

---

## 6. Módulo de Requerimientos

### 6.1 ¿Para qué sirve?

Solicitar compra de materiales cuando faltan en la obra.

### 6.2 Crear Requerimiento

1. Ve a **Requerimientos** → **Nuevo**
2. Completa:
   - Obra que necesita el material
   - Items requeridos (qué y cuánto)
   - Prioridad (normal, urgente, crítica)
   - Fecha en que se necesita
   - Motivo/justificación
3. Envía el requerimiento

### 6.3 Estados del Requerimiento

| Estado | Significado |
|--------|-------------|
| **Pendiente** | Esperando revisión |
| **Aprobado** | Autorizado, proceder a compra |
| **Rechazado** | No autorizado |
| **En proceso** | Compra en curso |
| **Completado** | Material recibido |

### 6.4 Flujo de Aprobación

1. **Operario/Técnico** crea el requerimiento
2. **Administrador** lo revisa
3. Si aprueba → se gestiona la compra
4. Cuando llega el material → se marca como completado
5. Se actualiza el inventario automáticamente

---

## 7. Módulo de Equipos

### 7.1 ¿Para qué sirve?

Gestionar maquinaria, herramientas y el equipo de trabajo.

### 7.2 Equipos/Maquinaria

**Agregar equipo:**
1. Ve a **Equipos** → **Nuevo**
2. Completa:
   - Nombre/modelo
   - Tipo (excavadora, hormigonera, etc.)
   - Estado (disponible, en uso, mantenimiento)
   - Ubicación actual

**Asignar a obra:**
1. Abre el equipo
2. Haz clic en **"Asignar a Obra"**
3. Selecciona la obra y fechas

### 7.3 Usuarios del Sistema

**Ver usuarios:** **Equipos** → **Usuarios**

**Crear usuario:**
1. Haz clic en **"Nuevo Usuario"**
2. Completa datos:
   - Nombre y apellido
   - Email
   - Rol (admin, pm, técnico, operario)
   - Contraseña temporal
3. El usuario recibe email de invitación

**Cambiar rol:**
1. Abre el usuario
2. Cambia el rol en el selector
3. Guarda

---

## 8. Módulo de Clientes

### 8.1 ¿Para qué sirve?

Mantener una base de datos de tus clientes.

### 8.2 Agregar Cliente

1. Ve a **Clientes** → **Nuevo**
2. Completa:
   - Nombre o razón social
   - CUIT/DNI
   - Teléfono
   - Email
   - Dirección
3. Guarda

### 8.3 Usar Clientes

Los clientes se usan en:
- Presupuestos (asociar cliente)
- Obras (dueño de la obra)
- Facturación

---

## 9. Módulo de Reportes

### 9.1 Dashboard Principal

Vista general con indicadores clave:
- Obras activas
- Presupuestos pendientes
- Alertas del sistema
- Gráficos de progreso

### 9.2 Reporte de Obras

Análisis de todas las obras:
- Estado de cada obra
- Progreso vs planificado
- Retrasos detectados
- Costos ejecutados

### 9.3 Reporte de Costos

Análisis económico:
- Presupuesto vs ejecutado
- Desglose por etapa
- Desglose por tipo (material, mano de obra)
- Rentabilidad

### 9.4 Reporte de Inventario

Estado del inventario:
- Items con bajo stock
- Movimientos recientes
- Valor total del inventario
- Uso por obra

---

## 10. Módulo de Seguridad

### 10.1 ¿Para qué sirve?

Gestionar la seguridad e higiene en las obras.

### 10.2 Protocolos

Crear protocolos de seguridad:
1. Ve a **Seguridad** → **Protocolos**
2. Crea un nuevo protocolo
3. Define los pasos/verificaciones
4. Asigna a obras

### 10.3 Checklists

Verificaciones diarias de seguridad:
1. Ve a **Seguridad** → **Checklists**
2. Selecciona el checklist a ejecutar
3. Completa cada punto
4. Guarda el resultado

### 10.4 Incidentes

Reportar accidentes o incidentes:
1. Ve a **Seguridad** → **Incidentes**
2. Crea nuevo reporte
3. Indica:
   - Tipo de incidente
   - Severidad
   - Descripción
   - Personas involucradas
   - Fotos/evidencia
4. Envía

### 10.5 Certificaciones

Registrar certificaciones del personal:
- Cursos de seguridad
- Habilitaciones
- Fechas de vencimiento
- El sistema alerta cuando una certificación está por vencer

### 10.6 Indicadores

KPIs de seguridad:
- Días sin accidentes
- Tasa de frecuencia
- Cumplimiento de protocolos
- Incidentes por período

---

## 11. Marketplace

### 11.1 ¿Para qué sirve?

Comprar materiales directamente a proveedores.

### 11.2 Buscar Productos

1. Ve a **Marketplace**
2. Usa el buscador o navega por categorías
3. Filtra por:
   - Precio
   - Ubicación del proveedor
   - Calificación

### 11.3 Ver Producto

En el detalle del producto ves:
- Fotos
- Descripción
- Variantes (tamaños, colores)
- Precio
- Stock disponible
- Datos del proveedor

### 11.4 Hacer Preguntas

Si tienes dudas:
1. En el producto, ve a **"Preguntas"**
2. Escribe tu consulta
3. El proveedor responderá

### 11.5 Comprar

1. Haz clic en **"Agregar al Carrito"**
2. Selecciona cantidad y variante
3. Ve al **Carrito**
4. Revisa los items
5. Haz clic en **"Finalizar Compra"**
6. Completa datos de envío
7. Confirma

### 11.6 Mis Órdenes

En **Marketplace** → **Mis Órdenes** ves:
- Historial de compras
- Estado de cada orden
- Seguimiento de envío

---

## 12. Configuración de Cuenta

### 12.1 Perfil Personal

En **Configuración** → **Perfil**:
- Editar nombre y apellido
- Cambiar foto de perfil
- Actualizar teléfono
- Cambiar contraseña

### 12.2 Datos de Facturación

En **Configuración** → **Facturación**:
- CUIT/DNI
- Razón social
- Dirección fiscal
- Condición de IVA

### 12.3 Organización

En **Configuración** → **Organización**:
- Nombre de la empresa
- Logo
- Datos de contacto
- Configuraciones generales

### 12.4 Plan y Suscripción

En **Planes**:
- Ver plan actual
- Cambiar de plan
- Ver historial de pagos

**Planes disponibles:**

| Plan | Características |
|------|-----------------|
| **Prueba** | 14 días gratis, funciones limitadas |
| **Standard** | Todas las funciones básicas |
| **Premium** | Funciones avanzadas + soporte prioritario |

---

## 13. Roles y Permisos

### 13.1 Tipos de Roles

| Rol | Descripción |
|-----|-------------|
| **Administrador** | Acceso completo a todo el sistema |
| **Project Manager** | Gestiona obras, presupuestos y equipos |
| **Técnico** | Crea presupuestos, ve obras, usa inventario |
| **Operario** | Ve sus tareas, registra avances |

### 13.2 Qué puede hacer cada rol

**Administrador:**
- Todo

**Project Manager:**
- Crear y editar obras
- Crear y editar presupuestos
- Gestionar inventario
- Asignar tareas
- Ver reportes
- Aprobar requerimientos

**Técnico:**
- Crear presupuestos
- Ver obras asignadas
- Crear requerimientos
- Usar inventario
- Ver reportes básicos

**Operario:**
- Ver mis tareas asignadas
- Registrar avances
- Usar materiales de inventario
- Reportar incidentes

---

## 14. Preguntas Frecuentes

### ¿Cómo recupero mi contraseña?
En la pantalla de login, haz clic en "¿Olvidaste tu contraseña?" e ingresa tu email. Recibirás un enlace para crear una nueva contraseña.

### ¿Puedo usar OBYRA en el celular?
Sí, OBYRA es una aplicación web responsiva que funciona en cualquier dispositivo. También puedes instalarla como app desde el navegador.

### ¿Cómo invito a mi equipo?
Ve a **Equipos** → **Usuarios** → **Nuevo Usuario** y completa los datos. El usuario recibirá un email de invitación.

### ¿Puedo exportar mis datos?
Sí, puedes generar PDFs de presupuestos y reportes. Los datos también están disponibles para exportación desde los módulos.

### ¿Cómo contacto a soporte?
- Email: soporte@obyra.com.ar
- WhatsApp: +54 9 11 7368-5175
- Desde la app: botón "Reserva tu Demo" en la página principal

### ¿Mis datos están seguros?
Sí, OBYRA usa encriptación SSL, autenticación segura y cumple con estándares de seguridad de la industria.

### ¿Puedo tener varias organizaciones?
Sí, un usuario puede pertenecer a múltiples organizaciones con diferentes roles en cada una.

### ¿Cómo funciona la IA para presupuestos?
La IA analiza el tipo de obra y superficie para calcular automáticamente las etapas, materiales y costos estimados basándose en datos del mercado argentino.

---

## Soporte

**¿Necesitas ayuda?**

- **Email:** soporte@obyra.com.ar
- **WhatsApp:** +54 9 11 7368-5175
- **Web:** www.obyra.com.ar

---

*Manual de Usuario OBYRA IA - Versión 1.0*
*Última actualización: Enero 2026*
