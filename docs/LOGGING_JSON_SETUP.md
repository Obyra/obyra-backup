# Activar Logging JSON estructurado

## ¿Qué es?

Por default OBYRA loguea en formato texto plano:
```
[2026-04-08 10:23:45] INFO in obras: Usuario creó obra ID 123
```

Con `LOG_FORMAT=json` los logs salen en formato JSON estructurado:
```json
{
  "timestamp": "2026-04-08T10:23:45.123456+00:00",
  "level": "INFO",
  "logger": "obras",
  "message": "Usuario creó obra ID 123",
  "module": "core",
  "function": "crear_obra",
  "line": 542,
  "request": {
    "method": "POST",
    "path": "/obras/crear",
    "remote_addr": "190.x.x.x"
  },
  "user": {
    "id": 5,
    "email": "admin@empresa.com",
    "organizacion_id": 3
  }
}
```

## ¿Para qué sirve?

Los logs en JSON son fáciles de ingestar en sistemas de monitoreo:

- **Loki + Grafana** (gratis, self-hosted)
- **ELK Stack** (Elasticsearch + Logstash + Kibana)
- **AWS CloudWatch Logs**
- **Datadog**
- **Splunk**

Estos sistemas te permiten:
- Buscar errores por usuario/organización/endpoint
- Hacer dashboards de errores en tiempo real
- Alertas automáticas (ej: "más de 5 errores 500 en los últimos 5 min")
- Correlacionar errores con cambios de código

## Cómo activarlo en Railway (2 minutos)

1. Ir a Railway → tu servicio (`obyra-backup`)
2. Click en **Variables**
3. Click **+ New Variable**
4. **Name:** `LOG_FORMAT`
5. **Value:** `json`
6. Railway hace redeploy automáticamente

Listo. Los logs van a empezar a salir en JSON.

## Cómo desactivarlo

Mismo procedimiento, pero borrá la variable o cámbiala a `text`.

## Cómo verificar

Después del redeploy, en Railway → tu servicio → tab **"Logs"**:

**Antes (texto):**
```
[INFO] Worker 1 booted
[2026-04-08 10:23:45] INFO in obras: Usuario creó obra
```

**Después (JSON):**
```
{"timestamp":"2026-04-08T10:23:45+00:00","level":"INFO","logger":"app","message":"Usuario creó obra",...}
```

## ¿Es seguro activarlo?

**Sí, completamente.**

- El default es `text` (formato actual). Si no seteás la variable, nada cambia.
- Los logs siguen yendo al mismo lugar (stdout, archivo, etc).
- Solo cambia el **formato** del mensaje, no el contenido.
- Si querés volver, borrás la variable y listo.

## Recomendación

**Activarlo desde el día 1 de producción.** No necesitás un sistema de monitoreo todavía — los logs JSON son legibles igual. Pero el día que quieras conectar Loki/Datadog, no vas a tener que tocar nada del código.

## Ejemplo de búsqueda con jq (si descargás logs)

```bash
# Errores del último día
cat railway-logs.txt | jq 'select(.level == "ERROR")'

# Errores de un usuario específico
cat railway-logs.txt | jq 'select(.user.id == 5)'

# Requests lentos a un endpoint
cat railway-logs.txt | jq 'select(.request.path == "/api/calcular")'
```
