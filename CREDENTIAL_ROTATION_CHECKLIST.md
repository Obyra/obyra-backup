# Checklist de rotación de credenciales

Última actualización: 2026-07-23

> **Regla:** este archivo NO contiene valores de credenciales. Todos los secretos
> viven **solo** en las env vars de Railway (servicio `obyra-backup`), nunca en git.
> Verificado: ningún secreto está hardcodeado en `.py` (todos se leen de `os.getenv`).

## Contexto

Una auditoría (jul 2026) encontró que el archivo `.env` estuvo **versionado en el
historial de git** (commit `571deed` y anteriores como `14eec7a "cambio en .env"`),
exponiendo algunas credenciales. Borrar el archivo **no** purga el historial, así que
todo lo que alguna vez estuvo ahí debe rotarse.

Comando para ver qué había (valores redactados):
```bash
git show 571deed^:.env | sed -E 's/(=.{4}).*/\1***/'
```

---

## Estado

| Credencial | En git history | En Railway | Estado | Acción |
|---|---|---|---|---|
| `MP_ACCESS_TOKEN` | **SÍ** (`APP_USR-…`) | SET | 🔴 **Rotar** | Regenerar en Mercado Pago |
| `SMTP_PASSWORD` | **SÍ** | SET | 🔴 **Rotar** | Regenerar en el proveedor de mail |
| `ANTHROPIC_API_KEY` | No (nunca commiteado) | SET | 🟡 Rotar por prudencia | Se vio en sesión; regenerar en Console |
| `MP_WEBHOOK_SECRET` | No (estaba vacío) | verificar | 🟢 / ⚪ | Confirmar que esté seteado (valida webhooks MP) |
| `TURNSTILE_SITE_KEY` | No (es pública) | **SET** ✅ | 🟢 | Ya cargada. Se activa en el próximo deploy |
| `TURNSTILE_SECRET_KEY` | No | **SET** ✅ | 🟢 | Ya cargada (por CLI, `--stdin`) |
| `SCRAPING_TOKEN` | No | SET | 🟢 | OK (FASE 2) |
| `CLOUDFLARE_API_TOKEN` | — | — | ⚪ N/A | No se usa en el código |

---

## Pendientes 🔴 (rotación manual, ~5-10 min c/u — puros clicks, sin código)

### 1. Mercado Pago — `MP_ACCESS_TOKEN`
**Riesgo:** acceso a cobros/reembolsos y webhooks de pagos.
1. https://www.mercadopago.com.ar/ → **Tus integraciones / Credenciales**.
2. Regenerá el **Access Token** de producción.
3. Railway → servicio `obyra-backup` → **Variables** → reemplazá `MP_ACCESS_TOKEN`.
4. (Si aplica) actualizá también `MP_ACCESS_TOKEN_TEST` para sandbox.
5. Probá un pago de prueba; si anda, invalidá/olvidá el token viejo.

### 2. SMTP — `SMTP_PASSWORD`
**Riesgo:** envío de mails (reset de contraseña, PDFs por correo, notificaciones).
1. Panel del proveedor de correo → regenerá la contraseña / app-password.
2. Railway → reemplazá `SMTP_PASSWORD`.
3. Probá un envío real (pedí un reset de contraseña de prueba).

### 3. Anthropic — `ANTHROPIC_API_KEY` (prudencial)
**Riesgo:** costo de API. Nunca estuvo en git, pero se vió en una sesión de trabajo.
1. https://console.anthropic.com/ → **API Keys** → creá una nueva, revocá la vieja.
2. Railway → reemplazá `ANTHROPIC_API_KEY`.
3. Verificá que el pipeline IA siga clasificando (recalculá un presupuesto).
4. **Además**: configurá un **límite de gasto mensual** en la Console (complementa
   el cap por usuario/día del código — ver `services/llm_budget.py`).

---

## Turnstile — ya configurado ✅ (falta activar + testear)

Las dos claves ya están cargadas en Railway (`TURNSTILE_SITE_KEY` pública,
`TURNSTILE_SECRET_KEY` secreta). Se cargaron con `--skip-deploys`, así que **se
activan en el próximo deploy**. Después:
1. Abrí `app.obyra.com.ar/register` y `.../forgot` → debe aparecer el widget.
2. Completá el captcha y enviá → debe dejar pasar.
3. Si el widget NO aparece: revisá que el deploy haya corrido con las env vars.
4. Si aparece pero da error: verificá que el dominio del sitio en Cloudflare
   Turnstile coincida con `app.obyra.com.ar`.

> Nota: `login` NO tiene captcha a propósito (ya está rate-limited 10/min; captcha
> en cada login es mala UX). Se puede sumar si se quiere.

---

## Verificaciones finales

- [ ] `MP_ACCESS_TOKEN` rotado y pagos OK.
- [ ] `SMTP_PASSWORD` rotado y mails OK (reset de contraseña de prueba).
- [ ] `ANTHROPIC_API_KEY` rotado y pipeline IA OK; límite de gasto en Console.
- [ ] `MP_WEBHOOK_SECRET` seteado en Railway (valida firma de webhooks).
- [ ] Turnstile visible y funcionando en `/register` y `/forgot`.
- [ ] Sin secretos nuevos en git: `git log -p -S "APP_USR-"` y `-S "sk-ant-"` vacíos hacia adelante.
- [ ] (Backlog, no urgente) **Purgar el historial de git** con `git filter-repo` si el
      repo estuvo accesible a terceros, para eliminar los secretos viejos del historial.

---

## Fixes de seguridad ya aplicados (contexto)

Deployados en `main` esta tanda (ver commits): guardia anti-wipe de prod en scripts,
cap de gasto LLM por usuario/día, semáforo anti-DoS en render de PDFs, reset tokens
single-use, y Turnstile. **Pendiente**: Fix 6 — CSP con nonces (sacar `unsafe-inline`
/`unsafe-eval`), ~2-3h, no urgente.
