# CLAUDE.md — OBYRA IA

Guía para asistentes de IA (y humanos) que trabajan en este repo. SaaS de gestión de
obra y presupuestos para el mercado argentino. **Flask + PostgreSQL + SQLAlchemy**,
deployado en **Railway** (`app.obyra.com.ar`).

> Multi-tenant estricto: casi todo se filtra por `organizacion_id`. Ver "Patrones".

---

## 1. Stack y arranque

- **Framework:** Flask (app a nivel módulo, **NO** hay `create_app()` factory).
- **DB:** PostgreSQL obligatoria (`DATABASE_URL`), driver `psycopg` v3. SQLAlchemy + Flask-Migrate.
- **Auth:** Flask-Login (sesión por cookie), no JWT. OAuth Google opcional.
- **Async:** Celery + Redis **definido pero SIN worker en prod** (Railway corre solo
  gunicorn). Los PDFs y emails son **sincrónicos** hoy. `tasks/` existe pero está sin cablear.
- **PDF:** WeasyPrint (sincrónico, con semáforo de concurrencia anti-DoS → `services/pdf_concurrency.py`).
- **IA:** Anthropic (Claude Haiku) vía `services/clasificador_llm.py`.

### Punto de entrada
- **Prod:** `gunicorn --workers 4 --threads 2 --timeout 120 app:app` (ver `Dockerfile` CMD).
- **`app.py`** crea `app`, configura DB/sesión/CORS/headers/rate-limit, corre
  `runtime_migrations`, y registra todos los blueprints.

### Migraciones — IMPORTANTE
- **`runtime_migrations.py` es el aplicador REAL en prod.** Corre en cada boot de
  gunicorn (salvo `SKIP_RUNTIME_MIGRATIONS=1`) y aplica CREATE TABLE / ALTER / seeds
  idempotentes con bloques `DO $$`. **Alembic tiene múltiples heads** y no se usa como
  aplicador confiable. Para agregar una tabla/columna: modelo en `models/` **+** bloque
  en `runtime_migrations.py` (patrón: `IF NOT EXISTS ... THEN CREATE ... END IF`).

---

## 2. Estructura del codebase

```
app.py                     # entrypoint: config + registro de blueprints + runtime_migrations
auth.py                    # login/register/forgot/reset/logout, OAuth Google, tokens de reset
runtime_migrations.py      # migraciones idempotentes que corren al bootear (el aplicador real)
celery_app.py              # instancia Celery (broker Redis) — sin worker en prod
extensions.py              # db, csrf, limiter, mail (instancias compartidas)

models/          (30 .py)  # SQLAlchemy. core.py=Usuario/Organizacion/auth; budgets.py=Presupuesto/APU
services/        (68 .py)  # lógica de negocio (ver §4)
blueprint_presupuestos/(14)# el módulo más grande: presupuestos, APU/ejecutivo, pipeline IA, PDF
obras/           (12 .py)  # obras, etapas, tareas, certificaciones, remitos
tasks/            (4 .py)  # tareas Celery (emails/ia/pdfs) — definidas, no usadas en prod
middleware/       (3 .py)  # security_headers (CSP...), request_timing
config/           (5 .py)  # rate_limiter_config, logging_config, structured_logging
utils/            (7 .py)  # helpers (webhook_validator, etc.)
templates/                 # Jinja2 (auth/, presupuestos/, obras/, ...)
static/                    # JS/CSS/assets
migrations/                # Alembic (multiple heads — no confiar como aplicador)
tests/                     # pytest (conftest.py levanta app de test)
scripts/, seeds/           # seeds y utilidades one-off (OJO: clean_*_database.py borran datos)
docs/                      # documentación (incluye SCRAPING_PRECIOS_N8N.md)
Dockerfile, docker-compose*.yml  # prod usa Dockerfile; compose es para local/self-host
.github/workflows/         # ci.yml (pytest+ruff), dependency-audit.yml
```

Muchos blueprints viven en la raíz como `blueprint_*.py` (cotizaciones, ordenes_compra,
clientes, notificaciones, marketplace_payments, etc.).

---

## 3. Modelos clave (`models/`)

- **`core.py`** — `Usuario` (tabla `usuarios`), `Organizacion` (`organizaciones`),
  `OrgMembership`, `Notificacion`, `UserDailyLLMSpend` (cap de gasto IA). Password con
  `werkzeug.security` (scrypt/pbkdf2 salteado).
- **`budgets.py`** — `Presupuesto`, `ItemPresupuesto`, `ItemPresupuestoComposicion`
  (APU/ejecutivo), `PresupuestoPrecioConfirmado` (precios crowdsourced FASE 1/2),
  `NivelPresupuesto`, `MaterialCotizable`, `CuadrillaTipo`. El `Presupuesto` cachea el
  resultado del pipeline IA en `pipeline_ia_cache` (JSON).
- **`clients.py`** `Cliente` · **`projects.py`/`obras`** obras · **`inventory.py`**
  equipos/stock · **`suppliers.py`/`proveedores_oc.py`/`provider_price_list.py`**
  proveedores y catálogo de precios · **`subscription.py`** planes/billing.
- `models/__init__.py` re-exporta los modelos (agregá ahí los nuevos).

---

## 4. Servicios clave (`services/`)

**Pipeline de presupuesto IA (feature insignia):**
- `pipeline_presupuesto_ia.py` — `procesar_items()`: clasifica → descompone (APU) →
  pricea → scorea (verde/amarillo/rojo). Corre en lotes desde el front.
- `clasificador_llm.py` — clasifica ítems con Claude Haiku (fallback keyword sin API key).
- `coeficientes_loader.py` + `coeficientes_constructivos.yml` — las APU (recetas de
  materiales + mano de obra por tipo de trabajo).
- `precio_recurso_service.py` — `buscar_mejor_precio()` (fuzzy match contra
  `provider_price_list`), `obtener_precio_cascada()` (confirmado→scraping→APU→estimado),
  `registrar_precios_scraping()`.
- `margen_comercial.py` — margen como capa de presentación (costo → venta).
- `llm_budget.py` — cap de gasto de IA por usuario/día.

**Infra/seguridad:** `pdf_concurrency.py` (semáforo anti-DoS de PDF),
`captcha_service.py` (Turnstile), `storage_service.py`, `email` (Flask-Mail).

---

## 5. Cómo se conecta todo (flujo del pipeline IA)

```
Excel del pliego  →  import_pliego_service  →  ItemPresupuesto (crudos)
     │
     ▼  (front llama /presupuestos/pipeline-ia/analizar en lotes de 25)
procesar_items()  →  clasificar (LLM/keyword)  →  get_recursos (APU del YAML)
     →  _precios_recursos (buscar_mejor_precio)  →  cascada de precio  →  color
     │
     ▼  guardar-cache (persiste en Presupuesto.pipeline_ia_cache)
templates/presupuestos/revision_ia.html  (pantalla "Validación de presupuesto")
     │
     ▼  margen_comercial (costo → venta)
blueprint_presupuestos/pdf_email.py  →  PDF al cliente (WeasyPrint)
```

Registro de blueprints: `app.py` los importa en tandas con `_import_blueprint()` (tolerante
a fallos) y `register_blueprint(prefix=...)`. El grupo de presupuestos cuelga de `/presupuestos`.

---

## 6. Comandos

```bash
# --- Local (docker-compose: postgres + redis + app + celery + nginx) ---
docker compose up --build

# --- Local sin docker (requiere Postgres corriendo + .env con DATABASE_URL) ---
python app.py                      # usa app.run; FLASK_DEBUG=1 para debug

# --- Tests (CI usa Postgres+Redis reales; ver .github/workflows/ci.yml) ---
python -m pytest tests/ -v --tb=short
python -m pytest tests/test_auth.py -x     # un archivo

# --- Lint ---
ruff check .

# --- Migraciones ---
# En prod se aplican SOLAS al bootear (runtime_migrations.py). No requiere comando.
# Alembic existe pero tiene múltiples heads: usar con cuidado.
alembic upgrade head

# --- Validación offline útil (no hay DB local en la máquina de trabajo) ---
python -m py_compile <archivo.py>          # sintaxis Python
node --check <archivo.js>                   # JS extraído de templates
python -c "from jinja2 import Environment; Environment().parse(open('t.html').read())"
```

**Deploy:** push a `main` → Railway rebuildea el `Dockerfile` y redeploya (corre
`runtime_migrations` en el boot). Servicios en Railway: `obyra-backup` (web), `Postgres`, `Redis`.

---

## 7. Patrones y convenciones (leer antes de tocar)

- **Multi-tenant:** toda query de datos de negocio filtra por `organizacion_id`
  (`get_current_org_id()` de `services/memberships`). Endpoints que reciben un `<id>`:
  `get_or_404(id)` **seguido de** verificación de tenant (ej.
  `_verificar_acceso_presupuesto`, `_item_pertenece_a_org`). Nunca confiar en un
  `org_id` que venga del body. **Nunca** agregar una query global sin filtro de org.
- **Secretos:** SOLO en env vars de Railway, nunca hardcodeados ni en git. Ver
  `CREDENTIAL_ROTATION_CHECKLIST.md`. `SECRET_KEY` es obligatoria en prod.
- **Rate limiting:** global 200/min + 1000/h; login/reset con límites propios
  (`config/rate_limiter_config.py`, decorador `@limiter.limit`).
- **Headers/CSP:** `middleware/security_headers.py`. La CSP todavía tiene
  `unsafe-inline`/`unsafe-eval` (deuda pendiente: migrar a nonces).
- **PDFs:** siempre vía `services/pdf_concurrency.render_pdf_into()` (o `pdf_render_lock`
  fuera de vistas) para respetar el semáforo. No llamar `HTML(...).write_pdf()` directo.
- **Scripts destructivos:** `clean_*_database.py` tienen guardia anti-prod
  (`_check_not_production`, fail-closed). No las corras contra Railway.
- **Idioma:** UI, commits y comentarios en español (rioplatense).

---

## 8. Estado del proyecto (features grandes)

- **Pipeline IA de presupuestos** (Fase 2.x): import pliego → clasificación/APU/pricing → validación → PDF.
- **Precios crowdsourced** (FASE 1: confirmados por clientes; FASE 2: scraping N8N →
  `POST /presupuestos/precio-scraping`, ver `docs/SCRAPING_PRECIOS_N8N.md`).
- **Presupuesto Ejecutivo (APU)** + cotización a proveedores (`blueprint_presupuestos/ejecutivo.py`).
- **Remediación de seguridad** en curso (ver `CREDENTIAL_ROTATION_CHECKLIST.md`).
