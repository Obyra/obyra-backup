# -*- coding: utf-8 -*-
"""Clasificador LLM de items de presupuesto (Fase 2.3 IA presupuestos).

Mapea cada linea del Excel del cliente a una `regla_id` de la base tecnica
(REGLAS_TECNICAS / coeficientes_constructivos.yml). El LLM SOLO clasifica y
mapea: elige de la lista de reglas validas o devuelve null. NUNCA inventa
precios, coeficientes ni reglas nuevas (output constrained via tool schema).

Degradacion elegante: si no hay ANTHROPIC_API_KEY o el paquete anthropic no
esta, cae a un clasificador por keywords (base_tecnica) y marca fuente='keyword'.
"""
import os
import re
import unicodedata

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
    lineas = [f"- {c['id']} | {c['rubro']} | {c['tarea']} | unidad {c['unidad']}" for c in catalogo]
    reglas_txt = "\n".join(lineas)
    return (
        "Sos un asistente experto en computo y presupuesto de obra en Argentina. "
        "Recibis items de un pliego (Excel del cliente) y los mapeas a una regla "
        "tecnica de una lista CERRADA. Reglas:\n"
        "1. Elegi el `regla_id` EXACTO de la lista para cada item.\n"
        "2. Si ningun regla_id describe bien el item, devolve regla_id=null.\n"
        "3. NO inventes ids, precios ni coeficientes. Solo clasificas.\n"
        "4. `confianza`: 0.85-1.0 match claro; 0.5-0.85 probable; <0.5 dudoso.\n"
        "5. Usa la unidad del item como pista (m2/m3/ml/u).\n\n"
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
        system=system,
        tools=[_TOOL],
        tool_choice={'type': 'tool', 'name': 'clasificar_items'},
        messages=[{'role': 'user', 'content': user}],
    )
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
        except Exception:
            base = None  # cae a keyword si la API falla
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
