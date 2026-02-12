# Pasos para ver los cambios de edición de usuarios

## 1. Reiniciar el servidor Flask

Si tienes el servidor corriendo, **detenlo** (presiona `Ctrl+C` en la terminal) y luego **inícialo nuevamente**:

```bash
# Detener: Ctrl+C en la terminal donde corre Flask

# Iniciar nuevamente:
python app.py
# O si usas otro comando:
flask run
```

## 2. Limpiar caché del navegador

Después de reiniciar el servidor, en tu navegador:

### Opción A: Forzar recarga (más rápido)
- **Windows/Linux**: `Ctrl + Shift + R`
- **Mac**: `Cmd + Shift + R`

### Opción B: Abrir en modo incógnito
- Abre una ventana de incógnito/privada y accede a la aplicación

### Opción C: Limpiar caché manualmente
1. Abre las herramientas de desarrollador (`F12`)
2. Haz clic derecho en el botón de recargar
3. Selecciona "Vaciar caché y recargar de forma forzada"

## 3. Verifica los cambios

Deberías ver:
- Una nueva columna **"ACCIONES"** en la tabla
- Un botón **"Editar"** en cada fila de usuario
- Al hacer clic en "Editar", se abre un modal para modificar los datos

---

Si después de estos pasos sigues sin ver los cambios, avísame.
