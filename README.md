# Obyra Backend

## Configuración local

1. Crea un archivo `.env` a partir del template incluido:
   ```bash
   cp .env.example .env
   ```
2. Genera una clave secreta y colócala en el `.env`:
   ```bash
   flask --app app secret gen
   ```
   Copia el valor impreso y asígnalo a `SECRET_KEY` en tu `.env`.
3. Define cualquier otra variable necesaria (por ejemplo `DATABASE_URL`) o deja que la app use SQLite por defecto en desarrollo.
4. Si cambias la `SECRET_KEY`, cerrá la sesión en los navegadores o borrá la cookie `remember_token` desde las herramientas de desarrollador para evitar mensajes de sesión expirada.

## Notas de despliegue

- En producción es obligatorio definir `SECRET_KEY` antes de arrancar la aplicación; si falta, el proceso abortará con un error descriptivo.
- En entornos de desarrollo, si `SECRET_KEY` no está definida se generará una clave temporal y se emitirá un *warning* en los logs. Esa clave solo dura mientras el proceso está activo, por lo que las sesiones se invalidarán en cada reinicio.
