# 📊 Análisis de Concurrencia - Sistema OBYRA

**Fecha**: 2 de Noviembre de 2025
**Versión**: 1.0
**Estado**: Análisis Completo

---

## 📋 Resumen Ejecutivo

El sistema OBYRA puede manejar **~200-300 usuarios concurrentes activos** bajo carga normal, con picos de hasta **~500-600 usuarios** durante períodos cortos. Los principales limitantes son:

1. **Gunicorn Workers**: 8 requests simultáneas (cuello de botella principal)
2. **PostgreSQL Pool**: 30 conexiones máximas
3. **Rate Limiting**: Varía por endpoint (3-100 req/min)

**Recomendación**: El sistema está bien configurado para equipos medianos (50-100 usuarios activos diarios), pero requerirá escalamiento horizontal para empresas grandes (>200 usuarios activos simultáneos).

---

## 🔍 Componentes Analizados

### 1. Nginx - Reverse Proxy

**Archivo**: `nginx/nginx.conf`

| Parámetro | Valor | Impacto en Concurrencia |
|-----------|-------|------------------------|
| `worker_processes` | auto | Se ajusta según CPU cores (típicamente 2-8) |
| `worker_connections` | 1024 | **1,024 conexiones por worker** |
| `keepalive` | 32 | Reutiliza 32 conexiones al backend |

**Capacidad Teórica de Nginx**:
```
Total = worker_processes × worker_connections
Ejemplo (4 cores): 4 × 1024 = 4,096 conexiones simultáneas
```

**Rate Limiting en Nginx**:
```nginx
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/s;
limit_req_zone $binary_remote_addr zone=general_limit:10m rate=50r/s;
```

- **Login**: 5 requests/minuto por IP (adicional al rate limit de Flask)
- **API**: 100 requests/segundo por IP
- **General**: 50 requests/segundo por IP

**Conclusión**: Nginx NO es un cuello de botella. Puede manejar miles de conexiones simultáneas.

---

### 2. Gunicorn - Application Server

**Archivo**: `Dockerfile:100`

```bash
gunicorn --bind 0.0.0.0:5000 \
  --workers 4 \
  --threads 2 \
  --timeout 120
```

| Parámetro | Valor | Significado |
|-----------|-------|-------------|
| `workers` | 4 | 4 procesos independientes de Python |
| `threads` | 2 | 2 threads por worker |
| `timeout` | 120s | Request timeout de 2 minutos |

**Capacidad de Gunicorn**:
```
Requests Concurrentes = workers × threads
                     = 4 × 2 = 8 requests simultáneas
```

**⚠️ CUELLO DE BOTELLA PRINCIPAL**

Con solo 8 requests concurrentes, este es el **limitante principal** del sistema.

**Fórmula de Workers Recomendados** (según documentación de Gunicorn):
```
workers = (2 × CPU_cores) + 1
```

Para un servidor con 4 cores:
```
workers = (2 × 4) + 1 = 9 workers
```

**Cálculo de Throughput** (requests por segundo):

Asumiendo request promedio de 200ms:
```
Throughput = (requests concurrentes) / (tiempo promedio request)
           = 8 / 0.2 seg
           = 40 requests/segundo
```

Para requests más lentos (500ms):
```
Throughput = 8 / 0.5 = 16 requests/segundo
```

**Usuarios Concurrentes Soportados**:

Un usuario activo genera ~2-5 requests por minuto (navegación normal).

```
Usuarios = Throughput × 60 / requests_por_usuario_min
        = 40 × 60 / 3
        = ~800 usuarios activos (con requests rápidos)

Realista (500ms promedio):
        = 16 × 60 / 3
        = ~320 usuarios activos
```

**Conclusión**: Con 4 workers × 2 threads, el sistema soporta **200-400 usuarios concurrentes activos** dependiendo de la latencia de las operaciones.

---

### 3. PostgreSQL - Base de Datos

**Archivo**: `app.py:140-155`

```python
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_size": 10,           # Conexiones en el pool
    "max_overflow": 20,        # Conexiones adicionales
    "pool_timeout": 30,        # Timeout para obtener conexión
    "pool_recycle": 1800,      # Reciclar cada 30 min
    "pool_pre_ping": True,     # Health check
}
```

| Parámetro | Valor | Significado |
|-----------|-------|-------------|
| `pool_size` | 10 | 10 conexiones permanentes en el pool |
| `max_overflow` | 20 | Hasta 20 conexiones adicionales bajo carga |
| **Total Máximo** | **30** | **30 conexiones concurrentes máximo** |

**Relación con Gunicorn**:

Cada worker de Gunicorn puede necesitar 1-2 conexiones a PostgreSQL.

```
Max Conexiones Necesarias = workers × threads × 1.5 (factor de seguridad)
                          = 4 × 2 × 1.5
                          = 12 conexiones

Disponibles: 30 conexiones
Utilizadas: ~12 conexiones bajo carga normal
Margen: 18 conexiones (150% de headroom) ✅ Bien configurado
```

**Timeout de Query**: 30 segundos (`statement_timeout=30000ms`)

**Conclusión**: PostgreSQL NO es un cuello de botella. El pool es suficiente para la configuración actual de Gunicorn.

---

### 4. Redis - Cache & Sessions

**Archivo**: `docker-compose.yml:39`

```bash
redis-server --appendonly yes \
  --maxmemory 512mb \
  --maxmemory-policy allkeys-lru
```

| Parámetro | Valor | Significado |
|-----------|-------|-------------|
| `maxmemory` | 512MB | Máximo de memoria RAM para cache |
| `maxmemory-policy` | allkeys-lru | Evict menos usados cuando se llena |

**Capacidad de Redis**:

512MB es suficiente para:
- **~50,000 sessions** (10KB cada una)
- **~500,000 entradas de cache** pequeñas (1KB cada una)
- **~100,000 rate limit counters**

**Throughput de Redis**: >100,000 ops/segundo (típico en un solo core)

**Conclusión**: Redis NO es un cuello de botella. Puede manejar fácilmente la carga del sistema.

---

### 5. Celery - Background Tasks

**Archivo**: `docker-compose.yml:142`

```bash
celery -A celery_app worker --loglevel=info --concurrency=4
```

| Parámetro | Valor | Significado |
|-----------|-------|-------------|
| `concurrency` | 4 | 4 tareas en paralelo |

**Capacidad de Celery**:
- 4 tareas pesadas ejecutándose simultáneamente
- Tareas en cola esperan a que se libere un worker

**Uso Típico**:
- Generación de reportes PDF
- Geocodificación de direcciones
- Envío de emails
- Procesamiento de imágenes

**Conclusión**: Celery maneja tareas asíncronas adecuadamente para el tamaño actual del sistema.

---

### 6. Rate Limiting - Flask Limiter

**Archivo**: `auth.py`, `obras.py`

#### Endpoints de Autenticación:

| Endpoint | Límite | Impacto |
|----------|--------|---------|
| POST /auth/login | 10/min | Max 10 intentos de login por minuto |
| POST /auth/register | 3/min | Max 3 registros por minuto |
| POST /auth/forgot | 5/min | Max 5 solicitudes de reset |
| POST /auth/reset/<token> | 5/min | Max 5 resets por minuto |

#### Endpoints Administrativos:

| Endpoint | Límite | Impacto |
|----------|--------|---------|
| POST /auth/usuarios/integrantes | 20/min | Max 20 creaciones de usuarios/min |
| POST /auth/usuarios/cambiar_rol | 30/min | Max 30 cambios de rol/min |

#### Endpoints Críticos de Obras:

| Endpoint | Límite | Impacto |
|----------|--------|---------|
| POST /obras/eliminar/<id> | 10/min | Max 10 eliminaciones/min |
| POST /obras/api/.../bulk_delete | 20/min | Max 20 operaciones bulk/min |
| POST /obras/reiniciar-sistema | **1/min** | Operación extremadamente destructiva |
| POST /obras/geocodificar-todas | **2/hora** | API externa costosa |

**Conclusión**: Rate limiting protege contra abuso pero limita operaciones masivas. Esto es **intencional por seguridad**.

---

## 📈 Capacidad Máxima Teórica

### Escenario 1: Carga Normal (Navegación Web)

**Asunciones**:
- Request promedio: 200ms
- Usuario genera 3 requests/minuto
- 80% de requests cacheable en Redis

**Capacidad**:
```
Throughput efectivo = 8 requests concurrentes / 0.2s = 40 req/s
Usuarios concurrentes = 40 × 60 / 3 = ~800 usuarios

Con cache hit (80%):
Usuarios = 800 / 0.2 (factor de cache) = ~400 usuarios activos
```

**Resultado**: **~400 usuarios concurrentes navegando activamente**

---

### Escenario 2: Carga Media (Operaciones de Base de Datos)

**Asunciones**:
- Request promedio: 500ms
- Usuario genera 5 requests/minuto
- 50% de requests requieren DB

**Capacidad**:
```
Throughput = 8 / 0.5s = 16 req/s
Usuarios = 16 × 60 / 5 = ~192 usuarios

Con DB overhead:
Usuarios = 192 × 0.8 = ~150 usuarios activos
```

**Resultado**: **~150-200 usuarios con operaciones intensivas**

---

### Escenario 3: Carga Alta (Reportes/Operaciones Pesadas)

**Asunciones**:
- Request promedio: 2 segundos (generación de PDFs, consultas complejas)
- Usuario genera 10 requests/minuto
- 100% de requests usan DB

**Capacidad**:
```
Throughput = 8 / 2s = 4 req/s
Usuarios = 4 × 60 / 10 = ~24 usuarios

Con Celery offloading:
Usuarios = 24 × 3 (tareas async) = ~72 usuarios
```

**Resultado**: **~50-100 usuarios con operaciones muy pesadas**

---

## 🚨 Cuellos de Botella Identificados

### 1. 🔴 CRÍTICO - Gunicorn Workers (4 × 2 = 8)

**Problema**: Solo 8 requests simultáneas es MUY BAJO para producción.

**Síntomas cuando se alcanza el límite**:
- Timeouts en el navegador
- Requests en cola esperando
- Usuarios experimentan lentitud extrema

**Solución**:
```bash
# Recomendado para servidor de 4 cores:
--workers 9 --threads 2  # 18 requests concurrentes

# Para servidor de 8 cores:
--workers 17 --threads 2  # 34 requests concurrentes
```

**Impacto de la mejora**:
```
Actual: 8 requests → ~200-400 usuarios
Con 18 requests → ~450-900 usuarios
Con 34 requests → ~850-1700 usuarios
```

---

### 2. 🟡 MEDIO - PostgreSQL Pool (30 conexiones)

**Problema**: Si aumentas workers a 9-17, podrías quedarte sin conexiones.

**Recomendación**:
```python
# Para 9 workers × 2 threads = 18 concurrentes:
"pool_size": 15,
"max_overflow": 30,  # Total: 45 conexiones

# Para 17 workers × 2 threads = 34 concurrentes:
"pool_size": 20,
"max_overflow": 40,  # Total: 60 conexiones
```

**Nota**: PostgreSQL puede manejar 100-200 conexiones sin problema en hardware moderno.

---

### 3. 🟡 MEDIO - Rate Limiting Agresivo

**Problema**: Algunos rate limits son muy estrictos para uso legítimo.

**Ejemplos problemáticos**:
- `POST /auth/register` - 3/min: Un admin registrando múltiples usuarios debe esperar
- `POST /obras/geocodificar-todas` - 2/hora: Solo 2 geocodificaciones masivas al día

**Recomendación**:
- Implementar **rate limiting por usuario autenticado** (más permisivo)
- Mantener **rate limiting por IP** (estricto) para no autenticados
- Usar diferentes límites para admin vs usuario regular

---

### 4. 🟢 BAJO - Redis Memory (512MB)

**Problema**: Puede llenarse con muchas sesiones activas.

**Capacidad actual**: ~50,000 sesiones simultáneas

**Recomendación**: Aumentar a 1GB si se esperan >30,000 usuarios concurrentes.

```yaml
# docker-compose.yml
command: redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru
```

---

## 📊 Tabla Resumen de Capacidad

| Componente | Configuración Actual | Capacidad Máxima | Cuello de Botella | Prioridad |
|------------|---------------------|------------------|-------------------|-----------|
| **Nginx** | 1024 conn/worker | ~4,096 conexiones | ❌ No | ✅ OK |
| **Gunicorn** | 4 workers × 2 threads | **8 requests** | ✅ **SÍ** | 🔴 ALTA |
| **PostgreSQL** | 10 + 20 pool | 30 conexiones | ⚠️ Si escalas Gunicorn | 🟡 MEDIA |
| **Redis** | 512MB | ~50k sesiones | ❌ No | 🟢 BAJA |
| **Celery** | 4 workers | 4 tareas async | ⚠️ Para tareas pesadas | 🟢 BAJA |

---

## 🎯 Recomendaciones de Escalamiento

### Corto Plazo (Esta Semana)

#### 1. Aumentar Workers de Gunicorn

**Prioridad**: 🔴 CRÍTICA

```dockerfile
# Dockerfile:100 - Cambiar de:
CMD ["gunicorn", "--workers", "4", "--threads", "2", ...]

# A (para 4 cores):
CMD ["gunicorn", "--workers", "9", "--threads", "2", ...]

# O (para 8 cores):
CMD ["gunicorn", "--workers", "17", "--threads", "2", ...]
```

**Impacto**:
- Usuarios concurrentes: 200-400 → 450-900 (125% aumento)
- Costo: Mínimo (solo más RAM/CPU)

#### 2. Ajustar Pool de PostgreSQL

**Prioridad**: 🟡 MEDIA

```python
# app.py:140 - Para 9 workers:
"pool_size": 15,
"max_overflow": 30,  # Total: 45

# Para 17 workers:
"pool_size": 20,
"max_overflow": 40,  # Total: 60
```

#### 3. Mejorar Rate Limiting

**Prioridad**: 🟡 MEDIA

Implementar rate limiting diferenciado:

```python
# Ejemplo de mejora:
@limiter.limit("3 per minute", methods=["POST"])  # IP anónima
@limiter.limit("30 per minute", methods=["POST"], key_func=lambda: f"user:{current_user.id}")  # Usuario autenticado
def register():
    ...
```

---

### Medio Plazo (Próximo Mes)

#### 4. Implementar Caching Agresivo

**Prioridad**: 🟡 MEDIA

```python
from flask_caching import Cache

cache = Cache(app, config={
    'CACHE_TYPE': 'redis',
    'CACHE_REDIS_URL': 'redis://localhost:6379/3',
    'CACHE_DEFAULT_TIMEOUT': 300
})

@cache.cached(timeout=60, key_prefix='dashboard_data')
def get_dashboard_data():
    # Operación costosa
    return data
```

**Impacto**: Reduce carga en DB hasta 80% para datos frecuentemente consultados.

#### 5. Optimizar Queries Lentas

**Prioridad**: 🟡 MEDIA

Identificar queries lentas:

```sql
-- En PostgreSQL
SELECT query, calls, mean_exec_time, max_exec_time
FROM pg_stat_statements
WHERE mean_exec_time > 100  -- >100ms
ORDER BY mean_exec_time DESC
LIMIT 20;
```

Agregar índices donde sea necesario.

---

### Largo Plazo (Próximos 3-6 Meses)

#### 6. Escalamiento Horizontal

**Prioridad**: 🟢 BAJA (solo si >500 usuarios concurrentes)

Cuando un solo servidor ya no sea suficiente:

```yaml
# docker-compose.yml
services:
  app1:
    # Primer servidor Flask
  app2:
    # Segundo servidor Flask
  app3:
    # Tercer servidor Flask

  nginx:
    # Load balancer entre app1, app2, app3
```

**Nginx configuration**:
```nginx
upstream flask_backend {
    least_conn;
    server app1:5000;
    server app2:5000;
    server app3:5000;
}
```

**Impacto**: Escala linealmente con número de servidores.

#### 7. CDN para Assets Estáticos

**Prioridad**: 🟢 BAJA

Usar CloudFlare, AWS CloudFront, o similar para servir:
- JavaScript, CSS
- Imágenes
- PDFs generados

**Impacto**: Reduce carga en servidor Flask hasta 40%.

---

## 🧪 Testing de Carga Recomendado

### Herramientas

1. **Locust** (Recomendado para Flask)
```python
# locustfile.py
from locust import HttpUser, task, between

class ObyraUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def view_dashboard(self):
        self.client.get("/reportes/dashboard")

    @task(1)
    def view_obras(self):
        self.client.get("/obras/lista")
```

Ejecutar:
```bash
locust -f locustfile.py --host=http://localhost:5002
```

2. **Apache Bench** (Para tests rápidos)
```bash
# Test simple de login
ab -n 1000 -c 10 -p login_data.txt -T application/x-www-form-urlencoded \
   http://localhost:5002/auth/login
```

3. **K6** (Para CI/CD)
```javascript
import http from 'k6/http';
import { check } from 'k6';

export let options = {
  stages: [
    { duration: '2m', target: 100 },  // Ramp up to 100 users
    { duration: '5m', target: 100 },  // Stay at 100 users
    { duration: '2m', target: 0 },    // Ramp down
  ],
};

export default function() {
  let res = http.get('http://localhost:5002/');
  check(res, { 'status was 200': (r) => r.status == 200 });
}
```

### Métricas a Monitorear

1. **Latencia**:
   - P50 (mediana): <200ms ✅
   - P95: <500ms ✅
   - P99: <1000ms ✅

2. **Throughput**:
   - Requests/segundo sin errores
   - Objetivo: >40 req/s con config actual

3. **Errores**:
   - HTTP 500: <0.1% ✅
   - HTTP 429 (rate limit): Depende del endpoint
   - Timeouts: <1% ✅

4. **Recursos**:
   - CPU: <80% promedio ✅
   - RAM: <80% de disponible ✅
   - DB connections: <70% del pool ✅

---

## 📝 Conclusiones Finales

### Capacidad Actual

| Escenario | Usuarios Concurrentes | Configuración Requerida |
|-----------|---------------------|------------------------|
| **Navegación ligera** | ~300-400 usuarios | ✅ Configuración actual |
| **Uso normal (mix)** | ~200-300 usuarios | ✅ Configuración actual |
| **Operaciones pesadas** | ~50-100 usuarios | ✅ Configuración actual |

### Para Escalar a Más Usuarios

| Objetivo | Acción Requerida | Dificultad | Costo |
|----------|-----------------|------------|-------|
| **500-800 usuarios** | Aumentar Gunicorn workers a 9-17 | 🟢 Fácil | 💰 Bajo |
| **1000-2000 usuarios** | + PostgreSQL pool + Redis 1GB | 🟡 Medio | 💰💰 Medio |
| **>2000 usuarios** | Escalamiento horizontal (múltiples servidores) | 🔴 Difícil | 💰💰💰 Alto |

### Próximos Pasos Inmediatos

1. ✅ **Monitorear métricas actuales** (CPU, RAM, response times)
2. ✅ **Implementar testing de carga** con Locust
3. ✅ **Aumentar Gunicorn workers** si CPU usage < 60%
4. ✅ **Configurar alertas** para cuando se alcance 80% de capacidad

---

**Última actualización**: 2025-11-02
**Autor**: Análisis de Claude Code
**Próxima revisión**: Cuando se alcance 70% de capacidad actual
