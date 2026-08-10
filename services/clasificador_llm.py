# -*- coding: utf-8 -*-
"""Clasificador LLM de items de presupuesto (Fase 2.3 IA presupuestos).

Mapea cada linea del Excel del cliente a una `regla_id` de la base tecnica
(REGLAS_TECNICAS / coeficientes_constructivos.yml). El LLM SOLO clasifica y
mapea: elige de la lista de reglas validas o devuelve null. NUNCA inventa
precios, coeficientes ni reglas nuevas (output constrained via tool schema).

Degradacion elegante: si no hay ANTHROPIC_API_KEY o el paquete anthropic no
esta, cae a un clasificador por keywords (base_tecnica) y marca fuente='keyword'.
"""
import logging
import os
import re
import unicodedata

logger = logging.getLogger(__name__)

MODELO = 'claude-haiku-4-5-20251001'
_BATCH = 40  # items por request


# ---------------------------------------------------------------------------
# Catalogo de reglas validas (el universo cerrado que el LLM puede elegir)
# ---------------------------------------------------------------------------

def catalogo_reglas(solo_con_coeficientes: bool = False):
    """Lista de reglas candidatas: {id, rubro, tarea, unidad}."""
    from services.base_tecnica_computos import REGLAS_TECNICAS
    try:
        from services.coeficientes_loader import tiene_coeficientes
    except Exception:
        tiene_coeficientes = lambda _rid: False

    out = []
    for r in REGLAS_TECNICAS:
        rid = r.get('id')
        if not rid:
            continue
        if solo_con_coeficientes and not tiene_coeficientes(rid):
            continue
        out.append({
            'id': rid,
            'rubro': r.get('rubro', ''),
            'tarea': r.get('tarea', ''),
            'unidad': r.get('unidad_esperada', ''),
            # Se mandan al LLM: las unidades alternativas evitan descartar un match
            # bueno por como escribio la unidad el cliente (m2 vs m² vs metro cuadrado),
            # y las excluyentes son senal NEGATIVA (el fallback keyword ya las usaba,
            # el LLM no las veia). Ademas engordan el system prompt lo suficiente para
            # superar el minimo cacheable de Haiku 4.5 -> ver _llamar_api.
            'unidades_validas': list(r.get('unidades_validas') or []),
            'excluyentes': list(r.get('palabras_excluyentes') or []),
            'tiene_coef': bool(tiene_coeficientes(rid)),
        })
    return out


# ---------------------------------------------------------------------------
# Disponibilidad del LLM
# ---------------------------------------------------------------------------

def _api_key():
    return os.environ.get('ANTHROPIC_API_KEY') or ''


def llm_disponible() -> bool:
    if not _api_key():
        return False
    try:
        import anthropic  # noqa
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Clasificacion por LLM
# ---------------------------------------------------------------------------

_TOOL = {
    'name': 'clasificar_items',
    'description': 'Asigna a cada item de obra la regla tecnica que mejor lo describe.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'clasificaciones': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'indice': {'type': 'integer', 'description': 'indice del item (0-based)'},
                        'regla_id': {'type': ['string', 'null'],
                                     'description': 'id EXACTO de la lista de reglas, o null si ninguna aplica'},
                        'confianza': {'type': 'number', 'description': '0.0 a 1.0'},
                    },
                    'required': ['indice', 'regla_id', 'confianza'],
                },
            },
        },
        'required': ['clasificaciones'],
    },
}


def _system_prompt(catalogo):
    """Prompt del clasificador. ESTABLE entre lotes y entre presupuestos: es el
    prefijo que se cachea (ver _llamar_api). No meter fechas, ids de presupuesto
    ni nada variable aca adentro o el cache no pega nunca."""
    lineas = []
    for c in catalogo:
        linea = f"- {c['id']} | {c['rubro']} | {c['tarea']} | unidad {c['unidad']}"
        uv = c.get('unidades_validas') or []
        if uv:
            linea += f" (acepta: {'/'.join(uv)})"
        exc = c.get('excluyentes') or []
        if exc:
            linea += f" | NO aplica si dice: {', '.join(exc)}"
        lineas.append(linea)
    reglas_txt = "\n".join(lineas)
    return (
        "Sos un asistente experto en computo y presupuesto de obra en Argentina. "
        "Recibis items de un pliego (Excel del cliente) y los mapeas a una regla "
        "tecnica de una lista CERRADA. Reglas:\n"
        "1. Elegi el `regla_id` EXACTO de la lista para cada item.\n"
        "2. Si ningun regla_id describe bien el item, devolve regla_id=null.\n"
        "3. NO inventes ids, precios ni coeficientes. Solo clasificas.\n"
        "4. `confianza`: 0.85-1.0 match claro; 0.5-0.85 probable; <0.5 dudoso.\n"
        "5. Usa la unidad del item como pista (m2/m3/ml/u). El campo `acepta` "
        "lista las formas equivalentes de escribir esa unidad: si la unidad del "
        "item esta ahi, la unidad coincide.\n"
        "6. `NO aplica si dice` son terminos que DESCARTAN esa regla: si la "
        "descripcion del item los contiene, no la elijas aunque el resto suene "
        "parecido.\n\n"
        f"REGLAS VALIDAS (id | rubro | tarea | unidad):\n{reglas_txt}"
    )


def _user_prompt(items):
    lineas = []
    for i, it in enumerate(items):
        desc = (it.get('descripcion') or '').strip()
        un = (it.get('unidad') or '').strip()
        lineas.append(f"{i}: {desc} ({un})")
    return "Clasifica estos items:\n" + "\n".join(lineas)


def _llamar_api(system, user):
    """Aislada para poder mockear en tests. Devuelve la lista de clasificaciones."""
    import anthropic
    client = anthropic.Anthropic(api_key=_api_key())
    resp = client.messages.create(
        model=MODELO,
        max_tokens=4096,
        # Sin esto la API usa temperature=1.0 y dos corridas del MISMO pliego dan
        # numeros distintos. Medido en el presupuesto 70: 8 filas identicas "Losas",
        # 7 fueron a losa_hormigon y la mas grande (282 m3, mas que las otras 7
        # juntas) salio regla_id=null -> $0. Un renglon, una tirada de dados, el 9%
        # del presupuesto. Clasificar no es una tarea creativa: queremos que el
        # mismo item de siempre la misma regla.
        temperature=0,
        # Prompt caching: el system prompt (catalogo de reglas) es IDENTICO en cada
        # lote y entre presupuestos. Marcarlo con cache_control cachea el prefijo
        # (tools + system) por 5 min: el 1er lote lo crea a precio full y los
        # siguientes lo leen al 10%.
        # OJO: Haiku 4.5 tiene el minimo cacheable MAS ALTO de todos los modelos,
        # 4096 tokens. Con el catalogo pelado (id|rubro|tarea|unidad) el prefijo
        # medía 3.644 y NO cacheaba: la API no da error, simplemente devuelve
        # cache_creation_input_tokens=0 y se paga todo full. Sumando unidades_validas
        # y palabras_excluyentes al catalogo el prefijo quedo en ~5.2K y si cachea.
        # Si algun dia se recorta el catalogo, medir de nuevo con count_tokens:
        # bajar de 4096 apaga el cache en silencio.
        system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
        tools=[_TOOL],
        tool_choice={'type': 'tool', 'name': 'clasificar_items'},
        messages=[{'role': 'user', 'content': user}],
    )
    # Acumula el uso REAL de tokens en el request actual (para el cap de gasto por
    # usuario/dia; el endpoint lo lee y lo registra). Fuera de un request (scripts,
    # tests) no hace nada. Ver services/llm_budget.py.
    usage = getattr(resp, 'usage', None)
    _crea = (getattr(usage, 'cache_creation_input_tokens', 0) or 0) if usage else 0
    _lee = (getattr(usage, 'cache_read_input_tokens', 0) or 0) if usage else 0

    # Log de cache por llamada. Si `cache_creacion` y `cache_lectura` vienen los dos
    # en 0 el prefijo quedo por debajo del minimo cacheable y se esta pagando todo
    # full sin aviso de la API.
    logger.info('clasificador LLM: lote=%s items | tokens sin_cachear=%s '
                'cache_creacion=%s cache_lectura=%s salida=%s',
                user.count('\n') + 1 if user else 0,
                (getattr(usage, 'input_tokens', 0) or 0) if usage else 0,
                _crea, _lee,
                (getattr(usage, 'output_tokens', 0) or 0) if usage else 0)

    try:
        from flask import g, has_request_context
        if has_request_context() and usage is not None:
            # Con prompt caching, input_tokens NO incluye lo cacheado (va en
            # cache_creation/cache_read). Los sumamos para que el cap diario no
            # subcuente (conservador: los cache_read cuestan solo 10%, pero
            # contarlos a full mantiene el cap del lado seguro).
            _inp = (getattr(usage, 'input_tokens', 0) or 0) + _crea + _lee
            g._llm_input_tokens = getattr(g, '_llm_input_tokens', 0) + _inp
            g._llm_output_tokens = getattr(g, '_llm_output_tokens', 0) + (getattr(usage, 'output_tokens', 0) or 0)
            # Contadores aparte, SOLO para observabilidad del cache (no tocan el cap).
            g._llm_cache_creacion = getattr(g, '_llm_cache_creacion', 0) + _crea
            g._llm_cache_lectura = getattr(g, '_llm_cache_lectura', 0) + _lee
    except Exception:
        pass
    for block in resp.content:
        if getattr(block, 'type', None) == 'tool_use' and block.name == 'clasificar_items':
            return block.input.get('clasificaciones', [])
    return []


def _clasificar_llm(items, catalogo):
    ids_validos = {c['id'] for c in catalogo}
    resultado = [None] * len(items)
    for base in range(0, len(items), _BATCH):
        lote = items[base:base + _BATCH]
        crudas = _llamar_api(_system_prompt(catalogo), _user_prompt(lote))
        for c in crudas:
            idx = c.get('indice')
            if not isinstance(idx, int) or not (0 <= idx < len(lote)):
                continue
            rid = c.get('regla_id')
            if rid not in ids_validos:  # constrained: descarta ids inventados
                rid = None
            try:
                conf = float(c.get('confianza') or 0)
            except (TypeError, ValueError):
                conf = 0.0
            resultado[base + idx] = {'regla_id': rid, 'confianza': max(0.0, min(1.0, conf))}
    return resultado


# ---------------------------------------------------------------------------
# Fallback por keywords (sin LLM)
# ---------------------------------------------------------------------------

def _norm(s):
    s = unicodedata.normalize('NFD', (s or '').lower())
    return ''.join(ch for ch in s if not unicodedata.combining(ch))


def candidatos_para(descripcion, unidad=None, n=3):
    """Top-N reglas candidatas por keyword (para la pantalla de revision).
    Devuelve datos HUMANOS (trabajo/rubro), sin ids tecnicos en primer plano."""
    from services.base_tecnica_computos import REGLAS_TECNICAS
    try:
        from services.coeficientes_loader import tiene_coeficientes
    except Exception:
        tiene_coeficientes = lambda _r: False
    t = _norm(descripcion)
    scored = []
    for r in REGLAS_TECNICAS:
        if any(_norm(x) in t for x in r.get('palabras_excluyentes', [])):
            continue
        score = 0
        for kw in r.get('palabras_clave_fuertes', []):
            if _norm(kw) in t:
                score += 3
        for kw in r.get('palabras_clave_medias', []):
            if _norm(kw) in t:
                score += 2
        for kw in r.get('palabras_clave_debiles', []):
            if _norm(kw) in t:
                score += 1
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [{
        'regla_id': r['id'],
        'trabajo': r.get('tarea') or r.get('id'),
        'rubro': r.get('rubro', ''),
        'unidad': r.get('unidad_esperada', ''),
        'tiene_precio': bool(tiene_coeficientes(r['id'])),
        'score_raw': sc,   # score keyword crudo (para la regla de auto-aplicacion)
    } for sc, r in scored[:n]]


def rescatar_candidato(descripcion, unidad):
    """Rescate de rojos 'obvios': si hay un candidato keyword CLARO cuya unidad
    coincide con la del item y con ventaja neta sobre el #2, lo devolvemos para
    auto-aplicarlo (en vez de mandar el item a rojo sin razon). (regla_id, conf) o
    (None, 0.0). Conservador: exige unidad compatible + al menos un match fuerte +
    ventaja >=2 sobre el segundo + que la regla tenga coeficientes (se pueda pricear)."""
    from services.base_tecnica_computos import REGLAS_TECNICAS
    try:
        from services.coeficientes_loader import tiene_coeficientes
    except Exception:
        return None, 0.0
    t = _norm(descripcion)
    if not t:
        return None, 0.0
    u = _norm(unidad)
    scored = []
    for r in REGLAS_TECNICAS:
        if any(_norm(x) in t for x in r.get('palabras_excluyentes', [])):
            continue
        score = 0
        for kw in r.get('palabras_clave_fuertes', []):
            if _norm(kw) in t:
                score += 3
        for kw in r.get('palabras_clave_medias', []):
            if _norm(kw) in t:
                score += 2
        for kw in r.get('palabras_clave_debiles', []):
            if _norm(kw) in t:
                score += 1
        if score > 0:
            unit_ok = bool(u) and u in [_norm(x) for x in r.get('unidades_validas', [])]
            scored.append((score, unit_ok, r))
    if not scored:
        return None, 0.0
    scored.sort(key=lambda x: (-x[0], not x[1]))  # score desc; en empate, la de unidad ok
    s1, u1, r1 = scored[0]
    s2 = scored[1][0] if len(scored) > 1 else 0
    if u1 and s1 >= 3 and (s1 - s2) >= 2 and tiene_coeficientes(r1['id']):
        return r1['id'], min(0.8, 0.55 + 0.05 * s1)
    return None, 0.0


def _clasificar_keyword_item(desc, unidad):
    """Scoring simple contra REGLAS_TECNICAS: fuerte=3, media=2, debil=1;
    excluyentes descartan la regla. Devuelve (regla_id|None, confianza)."""
    from services.base_tecnica_computos import REGLAS_TECNICAS
    t = _norm(desc)
    mejor, mejor_score = None, 0
    for r in REGLAS_TECNICAS:
        if any(_norm(x) in t for x in r.get('palabras_excluyentes', [])):
            continue
        score = 0
        for kw in r.get('palabras_clave_fuertes', []):
            if _norm(kw) in t:
                score += 3
        for kw in r.get('palabras_clave_medias', []):
            if _norm(kw) in t:
                score += 2
        for kw in r.get('palabras_clave_debiles', []):
            if _norm(kw) in t:
                score += 1
        if unidad and _norm(unidad) in [_norm(u) for u in r.get('unidades_validas', [])]:
            score += 1
        if score > mejor_score:
            mejor_score, mejor = score, r.get('id')
    if mejor_score <= 0:
        return None, 0.0
    conf = min(0.6, 0.2 + 0.1 * mejor_score)  # keyword nunca da alta confianza
    return mejor, conf


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def clasificar_items(items, forzar_keyword: bool = False):
    """Clasifica una lista de items {descripcion, unidad, ...}.

    Devuelve lista alineada: {descripcion, unidad, regla_id, confianza, fuente,
    tiene_coeficientes}. fuente = 'llm' | 'keyword'.
    """
    catalogo = catalogo_reglas()
    coef_por_id = {c['id']: c['tiene_coef'] for c in catalogo}

    usar_llm = (not forzar_keyword) and llm_disponible()
    base = None
    if usar_llm:
        try:
            base = _clasificar_llm(items, catalogo)
            fuente = 'llm'
        except Exception as e:
            base = None  # cae a keyword si la API falla
            # Señal de degradacion: el LLM estaba disponible (hay key) pero fallo
            # (sin credito, rate limit, error de red...). El pipeline la propaga
            # para que la pantalla avise que se uso el metodo basico (keyword).
            logger.warning('Clasificador LLM fallo, cae a keyword: %s: %s',
                           type(e).__name__, str(e)[:200])
            try:
                from flask import g, has_request_context
                if has_request_context():
                    g.ia_llm_fallo = True
            except Exception:
                pass
    if base is None:
        fuente = 'keyword'
        base = []
        for it in items:
            rid, conf = _clasificar_keyword_item(it.get('descripcion'), it.get('unidad'))
            base.append({'regla_id': rid, 'confianza': conf})

    salida = []
    for it, cl in zip(items, base or [None] * len(items)):
        cl = cl or {'regla_id': None, 'confianza': 0.0}
        rid = cl.get('regla_id')
        salida.append({
            'descripcion': it.get('descripcion'),
            'unidad': it.get('unidad'),
            'regla_id': rid,
            'confianza': cl.get('confianza', 0.0),
            'fuente': fuente,
            'tiene_coeficientes': bool(coef_por_id.get(rid, False)) if rid else False,
        })
    return salida
