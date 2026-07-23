# FASE 2 — Scraping de precios de proveedores con N8N

Cada 48h N8N trae la lista de precios de un proveedor y la carga en OBYRA. El
pipeline de presupuestos usa esos precios en la cascada
**confirmado_cliente → scraping → APU → estimado**.

- **Endpoint:** `POST https://app.obyra.com.ar/presupuestos/precio-scraping`
- **Auth:** header `Authorization: Bearer <SCRAPING_TOKEN>` (la env var ya está
  seteada en Railway, servicio `obyra-backup`). Sin token → 401. Sin la env var en
  el server → 503.
- **Idempotente:** el endpoint hace *upsert* por `(proveedor, material, unidad,
  zona)`. Correr el workflow dos veces **no** duplica ni infla promedios.
- **La `fuente` se fuerza a `scraping`** del lado servidor: por esta vía no se
  pueden falsificar confirmaciones de cliente.

## Formato del body

Un ítem o un lote (recomendado; máximo **2000** ítems por request):

```json
{ "items": [
  { "material": "Cemento Loma Negra bolsa x 50 kg",
    "precio_unitario": 11800.50,
    "unidad": "bolsa",
    "proveedor": "Abelson",
    "zona": "Buenos Aires",
    "fuente": "scraping" }
]}
```

### Respuesta

```json
{ "ok": true, "recibidos": 500, "guardados": 498, "lista_proveedor": 490,
  "ignorados": 2, "envase_sospechoso": 8, "curados_preservados": 3,
  "errores": [ { "material": "producto raro", "motivo": "unidad no reconocida: 'cajita'" } ] }
```

| Campo | Significado |
|---|---|
| `guardados` | filas escritas en la tabla de cascada a nivel ítem |
| `lista_proveedor` | filas escritas en `provider_price_list` (la que usan los APU) |
| `ignorados` | descartados por el server (precio ≤ 0, unidad no reconocida, desc vacía) |
| `envase_sospechoso` | precio por **envase** cargado como unidad base (ej "x 30 kg" en `kg`). **No** entra a `provider_price_list`. Si viene alto → arreglar el parser. |
| `curados_preservados` | filas que ya existían corregidas a mano; el scraping **no** las pisó |

---

## Opción A (recomendada) — Execute Command corre el script ya probado

Si el N8N tiene acceso al repo y a Python con `openpyxl` (misma máquina/imagen que
el backend), reusá [`scripts/scraping_abelson.py`](../scripts/scraping_abelson.py):
ya hace parseo, normalización, batching de 500, retry 3× y aviso a Slack. **No hay
que reimplementar nada en N8N.**

### Nodos

1. **Schedule Trigger** — cada 48h, hora 02:00 (poco tráfico).
2. **Google Drive → Download** — baja el Excel a un archivo. Guardá la ruta (ej
   `/data/listaPrecios.xlsx`).
   - Si el archivo llega como binario en memoria, agregá un **Write Binary File**
     para bajarlo a disco y pasar la ruta al script.
3. **Execute Command**
   ```
   SCRAPING_TOKEN=<token> \
   SLACK_WEBHOOK_URL=<webhook> \
   PROVEEDOR=Abelson ZONA="Buenos Aires" \
   python scripts/scraping_abelson.py "/data/listaPrecios.xlsx"
   ```
   - Definí `SCRAPING_TOKEN` como credencial/variable de N8N, no hardcodeada.
   - El script sale con **exit 0** si todos los lotes entraron, **1** si alguno
     falló → N8N marca el nodo como error.
4. **IF (exit code / error)** → **Slack** en la rama de error. (El script ya avisa a
   Slack por su cuenta si `SLACK_WEBHOOK_URL` está seteada; el nodo IF es un
   segundo cinturón por si el proceso ni siquiera arrancó.)

### Otros proveedores con el mismo script

El script sirve para cualquier Excel con una solapa de columnas
`ART_CODIGO / ART_DESCRI / ART_PREVT1`. Para un proveedor con otra estructura,
cambian solo el nombre de la solapa y los nombres de columna: se parametriza
copiando el script y ajustando `SHEET` y el mapeo de columnas, o pasás
`PROVEEDOR=Leiten` si el formato coincide.

---

## Opción B — N8N puro (sin ejecutar el script)

Si el N8N es hosted y no puede correr nuestro Python, replicá la lógica con nodos
nativos. El **Code node** de abajo hace lo mismo que el script (normalizar,
detectar unidad conservadora, filtrar) y arma los lotes.

### Nodos

1. **Schedule Trigger** — cada 48h, 02:00.
2. **Google Drive → Download** — baja el Excel (binario).
3. **Spreadsheet File** (Read) — solapa `bd`, desde la fila 2. Devuelve objetos con
   `ART_CODIGO`, `ART_DESCRI`, `ART_PREVT1`.
4. **Code** (Run Once for All Items) — normaliza, filtra y arma lotes de 500:

   ```javascript
   const PROVEEDOR = 'Abelson', ZONA = 'Buenos Aires', BATCH = 500;
   const CONTENEDORES = [
     ['bolsa',['BOLSA']], ['balde',['BALDE']], ['tambor',['TAMBOR']],
     ['bidon',['BIDON','BIDÓN']], ['rollo',['ROLLO']], ['caja',['CAJA','CJA ']],
     ['juego',['JUEGO','JGO']],
   ];
   const reVale = /^\s*VALE\b|\bVALE POR PALLET\b/;

   function unidad(du){ for (const [u,toks] of CONTENEDORES) if (toks.some(t=>du.includes(t))) return u; return 'un'; }
   function norm(s){ return String(s).trim().replace(/²/g,'2').replace(/³/g,'3').replace(/\s+/g,' '); }

   const items = [];
   for (const row of $input.all()) {
     const j = row.json;
     const desc = j.ART_DESCRI, precioRaw = j.ART_PREVT1;
     if (desc == null || !String(desc).trim()) continue;
     const du = String(desc).toUpperCase();
     if (reVale.test(du)) continue;                       // VALE POR PALLET
     const precio = Number(String(precioRaw).replace(',','.'));
     if (!(precio > 0)) continue;                         // precio <= 0 o no numérico
     items.push({ material: norm(desc), precio_unitario: Math.round(precio*100)/100,
                  unidad: unidad(du), proveedor: PROVEEDOR, zona: ZONA, fuente: 'scraping' });
   }
   // partir en lotes de 500 -> un item de salida por lote
   const out = [];
   for (let i=0;i<items.length;i+=BATCH) out.push({ json: { lote: items.slice(i,i+BATCH) } });
   return out;
   ```

5. **HTTP Request** (corre una vez por cada lote de salida del Code):
   - Method `POST`, URL `https://app.obyra.com.ar/presupuestos/precio-scraping`
   - Header `Authorization: Bearer {{$env.SCRAPING_TOKEN}}` (o credencial de N8N)
   - Body (JSON): `{ "items": {{ $json.lote }} }`
   - **Settings → Retry On Fail:** 3 intentos, ~2s de espera. **Continue On Fail:**
     ON (un lote que falla no frena los demás).
6. **Code / Set** (agrega) — sumá `guardados`, `ignorados`, `envase_sospechoso` de
   cada respuesta para el mensaje final.
7. **Slack** — al terminar: `✅ Abelson: N guardados, M ignorados, K envase
   sospechoso`. En la rama de error (algún lote con `error`): `❌ ...`.

> **Regla de oro sobre unidades:** nunca infieras `kg`/`m3`/`ml`/`l` desde un token
> de envase de la descripción ("x 50 KG"). Ese número es el **contenido**, no la
> unidad de venta; cargarlo como `$/kg` infla el precio N veces (es el bug que puso
> el adhesivo a $146.834/kg y el porcelanato a $917.712/m²). Ante la duda, `un`:
> una unidad que el APU no matchea queda inerte; una unidad mal puesta envenena la
> base que cotiza a todos los clientes. El server tiene un guard, pero el parser es
> la primera línea.

---

## Verificación post-corrida (Brenda)

1. Recalculá un presupuesto que tenga ítems del rubro scrapeado (para Abelson:
   plomería/gas/incendio — caños, griferías, accesorios).
2. En la pantalla de validación, el badge bajo el precio debe decir
   **`Fuente: lista de proveedor (Abelson, hace Xh)`** (azul).
3. Si un ítem tiene confirmaciones de cliente además del scraping, gana el cliente:
   badge verde **`Fuente: precios reales (N clientes)`**.

Chequeo directo en la base (cuántas filas de scraping hay):

```sql
SELECT proveedor, count(*) FROM presupuesto_precio_confirmado
WHERE fuente='scraping' GROUP BY proveedor;

SELECT count(*) FROM provider_price_list
WHERE fuente='scraping' AND organizacion_id IS NULL;
```

## Notas de mantenimiento

- **El Excel de Abelson trae ~19.851 productos; ~11.800 con precio.** El resto (8.000
  en cero) se saltea solo.
- **Revisar el link/estructura 1× por mes:** si Abelson mueve el botón o cambia la
  solapa, la descarga o el parseo fallan y salta el aviso de Slack.
- **La carga completa tarda varios minutos** (el endpoint hace upsert por ítem sobre
  dos tablas). Corre bien desatendido; no la dispares en un contexto con timeout
  corto. *Mejora pendiente:* pasar el endpoint a `INSERT ... ON CONFLICT` en bloque.
- **Este catálogo es de plomería.** El valor grande de FASE 2 llega al sumar
  proveedores de albañilería (ladrillo/hormigón/hierro: Leiten, SINIS, Acíndar),
  cuyos materiales sí matchean los APU estructurales.
