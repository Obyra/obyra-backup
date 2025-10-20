# OBYRA IA — Entorno mínimo viable

## 1) Prerrequisitos
- **Python 3.11+**
- **PostgreSQL 16** (en desarrollo sugerimos Docker)
- **WeasyPrint en Windows**: instalar **MSYS2/MINGW64** y agregarlo al `PATH` (requerido para dependencias nativas)

---

## 2) Variables de entorno (dev / staging / prod)

| Variable                      | Dev (ejemplo)                                                | Staging/Prod (formato)                        | Notas                                                                                 |
|------------------------------|--------------------------------------------------------------|-----------------------------------------------|---------------------------------------------------------------------------------------|
| `FLASK_APP`                  | `app.py`                                                     | `app.py`                                      | Módulo principal                                                                      |
| `FLASK_ENV`                  | `development`                                                | `production`                                  | En prod, sin debugger                                                                 |
| `FLASK_RUN_PORT`             | `8080`                                                       | *a definir*                                   | Puerto HTTP                                                                           |
| `SECRET_KEY` / `SESSION_SECRET` | *(generar)*                                                | *(generar)*                                   | `python -c "import secrets; print(secrets.token_hex(32))"`                             |
| `DATABASE_URL`               | `postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev` | `postgresql+psycopg://USER:PASS@HOST:PORT/DB` | **Obligatorio** Postgres. Si es Neon y falta, se fuerza `sslmode=require`.            |
| `OPENAI_API_KEY`             | *(opcional)*                                                 | `sk-…`                                        | Calculadora IA                                                                        |
| `GOOGLE_OAUTH_CLIENT_ID`     | *(opcional)*                                                 | `…apps.googleusercontent.com`                 | Login con Google                                                                      |
| `GOOGLE_OAUTH_CLIENT_SECRET` | *(opcional)*                                                 | `…`                                           |                                                                                       |
| `MP_ACCESS_TOKEN`            | *(opcional)*                                                 | `APP_USR-…`                                   | Token de Mercado Pago (nombre que espera la app)                                      |
| `MP_WEBHOOK_PUBLIC_URL`      | *(opcional)*                                                 | `https://…/api/payments/mp/webhook`           | URL pública del webhook de MP                                                         |
| `SHOW_IA_CALCULATOR_BUTTON`  | `0`/`1`                                                      | `0`/`1`                                       | Flag de UI                                                                            |
| `ENABLE_REPORTS`             | `0`/`1`                                                      | `0`/`1`                                       | Habilita módulo de reportes (Matplotlib/WeasyPrint)                                   |
| `MAPS_PROVIDER`              | `nominatim`                                                  | `nominatim`/otro                              | Geocoding                                                                             |
| `MAPS_API_KEY`               | *(si aplica)*                                                | *(si aplica)*                                 | Clave del proveedor de mapas                                                          |

> **Nunca** commitees `SECRET_KEY`, API keys ni passwords. Usá `.env` en local o variables del entorno en el servidor/CI.

---

## 3) `.env` de ejemplo (solo desarrollo)

```ini
FLASK_APP=app.py
FLASK_ENV=development
FLASK_RUN_PORT=8080

# Generar con: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=REEMPLAZAR_CON_TOKEN_HEX_DE_64_CARACTERES

DATABASE_URL=postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev

# Opcionales
# OPENAI_API_KEY=sk-...
# GOOGLE_OAUTH_CLIENT_ID=...
# GOOGLE_OAUTH_CLIENT_SECRET=...
# MP_ACCESS_TOKEN=APP_USR-...
# MP_WEBHOOK_PUBLIC_URL=https://tu-dominio.com/api/payments/mp/webhook
4) PostgreSQL 16 en Docker (Desarrollo)

Levantar el contenedor:

docker run -d --name obyra-pg \
  -e POSTGRES_USER=obyra \
  -e POSTGRES_PASSWORD=obyra \
  -e POSTGRES_DB=obyra_dev \
  -p 5433:5432 \
  -v obyra-pgdata:/var/lib/postgresql/data \
  postgres:16
Verificar que está corriendo:

docker ps --filter "name=obyra-pg"


URL de conexión (dev):

postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev


### Qué hacer ahora (en la UI de GitHub)
1) En el editor de conflictos, pegá ese contenido → **Mark as resolved**.  
2) **Commit merge** (o “Commit changes”).  
3) Si el PR ofrece “Update branch” o “Re-run checks”, hacelo.  
4) Cuando todo esté en verde, podés **Merge** (o esperar la aprobación del bot si así lo definimos).

---

## ¿Vamos a tener que hacer esto siempre?
No debería. Están apareciendo conflictos porque:
- Hay **edición concurrente** de los mismos archivos entre tu rama y la del bot/otros commits.
- Se mezclan cambios de **formato/estilo** con contenido en los mismos diffs.
- Falta una **guía única** (esta) para nombres de variables (antes había `MERCADOPAGO_ACCESS_TOKEN` y la app usa `MP_ACCESS_TOKEN`).

### Cómo reducir conflictos a futuro
- **Pull/rebase antes de editar**:  
  `git fetch origin && git rebase origin/pr20-local`
- **PRs pequeños y atómicos**: separar “código” vs “docs”.  
- **Congelar convenciones**: usar siempre `MP_ACCESS_TOKEN` y `MP_WEBHOOK_PUBLIC_URL`.  
- **Evitar tocar los mismos archivos** que el bot cuando no es necesario.  
- **Habilitar auto-merge** y pedir al bot que edite *solo* los archivos listados en su tarea.  
- (Opcional) Activar `git rerere` localmente para que Git recuerde resoluciones repetidas:


git config --global rerere.enabled true


Si te aparece **otro** archivo en conflicto, pásamelo y te doy el contenido final listo para pegar.