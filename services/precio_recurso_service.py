"""Servicio de estimacion de precios (Fase 5.A).

Jerarquia DUAL segun el tipo de recurso:

  Si tipo == 'mano_obra':
     1. ManoObraCostoReferencia (org-scoped, vigente, categoria matcheada)
     2. ManoObraCostoReferencia global (organizacion_id IS NULL, vigente)
     3. CategoriaJornal (precio_jornal liso, fallback)
     4. EscalaSalarialUOCRA (jornal liso, fallback)
     5. Sin precio

  Si tipo in ('material', 'equipo'):
     0. provider_price_list por item_inventario_id (mas fuerte)
     1. provider_price_list vigente por descripcion_normalizada + unidad
     2. provider_price_list vencido < 180d (estado 'estimado'/'vencido')
     3. HistorialPrecioProveedor ultimos 6 meses
     4. ItemReferenciaConstructora
     5. Sin precio

Conversion de moneda: si la fuente trae moneda != ARS y el presupuesto
tiene exchange_rate_value cargado, se convierte. Si no, queda en
'requiere_tc' con precio_unitario=0.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from extensions import db


# Cortes de antigüedad (en dias)
DIAS_ACTUALIZADO = 30
DIAS_ESTIMADO = 180


def _calcular_estado(fecha_precio):
    """Devuelve 'actualizado' / 'estimado' / 'vencido' / 'sin_precio'."""
    if not fecha_precio:
        return 'sin_precio'
    if isinstance(fecha_precio, datetime):
        fecha_precio = fecha_precio.date()
    dias = (date.today() - fecha_precio).days
    if dias < 0:  # fecha futura, raro
        return 'actualizado'
    if dias <= DIAS_ACTUALIZADO:
        return 'actualizado'
    if dias <= DIAS_ESTIMADO:
        return 'estimado'
    return 'vencido'


def _convertir_moneda(precio, moneda_origen, presupuesto):
    """Convierte precio a ARS si moneda_origen != ARS y hay TC en el presupuesto.

    Returns: (precio_ars, info_audit_dict|None, requiere_tc_flag)
    """
    if (moneda_origen or 'ARS').upper() == 'ARS':
        return Decimal(str(precio)), None, False

    tc = getattr(presupuesto, 'exchange_rate_value', None)
    if not tc or Decimal(str(tc)) <= 0:
        # No podemos convertir, queda como 'requiere_tc'
        return Decimal('0'), {
            'precio_original': Decimal(str(precio)),
            'precio_moneda_original': moneda_origen,
            'precio_tipo_cambio_usado': None,
            'precio_tipo_cambio_fecha': None,
        }, True

    tc_dec = Decimal(str(tc))
    precio_ars = (Decimal(str(precio)) * tc_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    fecha_tc = getattr(presupuesto, 'exchange_rate_as_of', None) or \
               (getattr(presupuesto, 'exchange_rate_fetched_at', None).date()
                if getattr(presupuesto, 'exchange_rate_fetched_at', None) else None)
    return precio_ars, {
        'precio_original': Decimal(str(precio)),
        'precio_moneda_original': moneda_origen,
        'precio_tipo_cambio_usado': tc_dec,
        'precio_tipo_cambio_fecha': fecha_tc,
    }, False


# =====================================================================
# JERARQUIA: MANO DE OBRA
# =====================================================================

def _buscar_mo_costo_referencia(organizacion_id, descripcion, unidad, categoria_zona='CABA'):
    """Busca costo empresa de MO usando heuristica de categoria.

    Devuelve dict con info del precio o None.
    """
    from models.mano_obra_costo_referencia import (
        ManoObraCostoReferencia, categoria_canonica_para,
    )

    cat = categoria_canonica_para(descripcion)
    if not cat:
        return None

    # Buscar org-scoped vigente, fallback a global, ordenar por periodo desc
    hoy = date.today()
    q_base = ManoObraCostoReferencia.query.filter(
        ManoObraCostoReferencia.activo.is_(True),
        ManoObraCostoReferencia.categoria == cat,
        ManoObraCostoReferencia.zona == categoria_zona,
        ManoObraCostoReferencia.fecha_vigencia_desde <= hoy,
        db.or_(
            ManoObraCostoReferencia.fecha_vigencia_hasta.is_(None),
            ManoObraCostoReferencia.fecha_vigencia_hasta >= hoy,
        ),
    )

    # Prioridad 1: org-scoped
    fila = q_base.filter(
        ManoObraCostoReferencia.organizacion_id == organizacion_id
    ).order_by(ManoObraCostoReferencia.periodo.desc()).first()

    # Prioridad 2: global
    if not fila:
        fila = q_base.filter(
            ManoObraCostoReferencia.organizacion_id.is_(None)
        ).order_by(ManoObraCostoReferencia.periodo.desc()).first()

    if not fila:
        return None

    # Decidir si usar costo por hora o por jornal segun unidad
    unidad_lower = (unidad or '').strip().lower()
    if unidad_lower in ('hora', 'h', 'hr', 'hs', 'hrs', 'horas'):
        precio = fila.costo_empresa_hora
    else:  # default: jornal (8h)
        precio = fila.costo_empresa_jornal_8h

    if not precio or precio <= 0:
        return None

    return {
        'precio': float(precio),
        'fuente': 'mano_obra_costo_referencia',
        'estado': _calcular_estado(fila.fecha_vigencia_desde),
        'proveedor_id': None,
        'proveedor_nombre': None,
        'fecha': fila.fecha_vigencia_desde,
        'moneda': 'ARS',
        'notas': f"Costo empresa Gedif - {fila.categoria} ({fila.zona}, {fila.periodo})",
        'referencia_id': fila.id,
        'categoria_matcheada': cat,
    }


# categoria_canonica_para() devuelve 'oficial_especializado' pero categorias_jornal
# usa el codigo 'oficial_esp'. Alias para reconciliar (Fase 2.1).
_ALIAS_CODIGO_JORNAL = {'oficial_especializado': 'oficial_esp'}


def _buscar_costo_mo_v2(organizacion_id, descripcion, unidad, zona='CABA', fecha=None):
    """Costo empresa de MO (Fase 2.1): resuelve contra categorias_jornal +
    EstructuraRecargosMO via services.costo_mano_obra. Es la fuente PRINCIPAL de
    MO (reemplaza el uso de ManoObraCostoReferencia, que quedo vacia)."""
    from models.mano_obra_costo_referencia import categoria_canonica_para
    from services import costo_mano_obra

    cat = categoria_canonica_para(descripcion)
    if not cat:
        return None
    codigo = _ALIAS_CODIGO_JORNAL.get(cat, cat)

    basico, catrow = costo_mano_obra.resolver_basico_hora(codigo, organizacion_id, fecha)
    if catrow is None or basico <= 0:
        return None
    est = costo_mano_obra.resolver_estructura(organizacion_id, zona=zona, fecha=fecha)
    d = costo_mano_obra.desglose_costo_hora(basico, est)
    costo_hora = d['costo_hora']

    unidad_lower = (unidad or '').strip().lower()
    if unidad_lower in ('hora', 'h', 'hr', 'hs', 'hrs', 'horas'):
        precio = costo_hora
        unidad_txt = 'hora'
    else:  # default: jornal (8h)
        hpd = est.horas_por_dia if est else 8
        precio = costo_hora * Decimal(str(hpd))
        unidad_txt = 'jornal'
    if precio <= 0:
        return None

    est_nota = f" · recargos {est.nombre}" if est else " · sin recargos (basico liso)"
    return {
        'precio': float(precio),
        'fuente': 'costo_mano_obra',
        'estado': 'actualizado',
        'proveedor_id': None,
        'proveedor_nombre': None,
        'fecha': catrow.vigencia_desde,
        'moneda': 'ARS',
        'notas': f'Costo empresa MO {codigo} ({zona}, {unidad_txt}){est_nota}',
        'referencia_id': catrow.id,
        'categoria_matcheada': codigo,
    }


def _buscar_categoria_jornal(organizacion_id, descripcion, unidad):
    """Fallback: usa CategoriaJornal con precio_jornal liso."""
    from models.budgets import CategoriaJornal
    from models.mano_obra_costo_referencia import categoria_canonica_para

    cat = categoria_canonica_para(descripcion)
    if not cat:
        return None

    # Buscar org-scoped activo, fallback global
    fila = CategoriaJornal.query.filter(
        CategoriaJornal.activo.is_(True),
        CategoriaJornal.codigo == cat,
        CategoriaJornal.organizacion_id == organizacion_id,
    ).order_by(CategoriaJornal.id.desc()).first()
    if not fila:
        fila = CategoriaJornal.query.filter(
            CategoriaJornal.activo.is_(True),
            CategoriaJornal.codigo == cat,
            CategoriaJornal.organizacion_id.is_(None),
        ).order_by(CategoriaJornal.id.desc()).first()

    if not fila or not fila.precio_jornal:
        return None

    unidad_lower = (unidad or '').strip().lower()
    precio = float(fila.precio_jornal)
    if unidad_lower in ('hora', 'h', 'hr', 'hs', 'hrs', 'horas'):
        precio = precio / 8.0

    return {
        'precio': precio,
        'fuente': 'categoria_jornal',
        'estado': _calcular_estado(fila.vigencia_desde or fila.created_at),
        'proveedor_id': None,
        'proveedor_nombre': None,
        'fecha': fila.vigencia_desde or (fila.created_at.date() if fila.created_at else None),
        'moneda': fila.moneda or 'ARS',
        'notas': f'Categoria jornal {cat} (jornal liso, sin cargas)',
        'referencia_id': fila.id,
    }


# =====================================================================
# JERARQUIA: MATERIALES / EQUIPOS
# =====================================================================

_STOPWORDS_MATCHING = {
    'de', 'del', 'la', 'el', 'los', 'las', 'y', 'o', 'u', 'a', 'al', 'en',
    'para', 'por', 'con', 'sin', 'un', 'una', 'unos', 'unas', 'es', 'son',
    'que', 'se', 'no', 'lo', 'le', 'su', 'sus', 'mi', 'tu', 'mas', 'mas',
    'tipo', 'segun', 'sobre', 'desde', 'hacia',
}


def _tokens_significativos(texto: str) -> set:
    """Extrae tokens útiles para matching fuzzy: lowercase, sin acentos,
    sin stopwords. Mantiene tokens largos Y splittea números pegados a
    letras: '8mm' -> {'8', 'mm', '8mm'}, 'h21' -> {'h', '21', 'h21'}.
    Esto permite que 'Hierro 8mm' matchee con 'Hierro del 8 mm'.
    """
    if not texto:
        return set()
    import unicodedata
    s = str(texto).lower()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r'[^\w\s]', ' ', s)
    out = set()
    for t in s.split():
        if t in _STOPWORDS_MATCHING:
            continue
        if len(t) >= 3 or any(ch.isdigit() for ch in t):
            out.add(t)
        # Split números/letras: '8mm' -> '8', 'mm'. 'h21' -> 'h', '21'.
        partes = re.findall(r'\d+|[a-z]+', t)
        for p in partes:
            if p in _STOPWORDS_MATCHING:
                continue
            if len(p) >= 2 or p.isdigit():
                out.add(p)
    return out


_UNIDADES_SINONIMOS = {
    'm2': {'m2', 'm²', 'mts2', 'mt2', 'metros cuadrados', 'metro cuadrado'},
    'm3': {'m3', 'm³', 'mts3', 'mt3', 'metros cubicos', 'metro cubico'},
    'ml': {'ml', 'm', 'mts', 'mtrs', 'metro lineal', 'metros lineales'},
    'kg': {'kg', 'kilo', 'kilos', 'kgr'},
    'un': {'un', 'u', 'ud', 'und', 'unidad', 'unidades', 'gl', 'global', 'gbl', 'glb'},
    'hora': {'hora', 'hr', 'hs', 'h'},
    'jornal': {'jornal', 'jrnl', 'dia', 'día', 'd'},
    'l': {'l', 'lt', 'litro', 'litros'},
    'tn': {'tn', 'tonelada', 'toneladas'},
    'bolsa': {'bolsa', 'bolsas'},
}


def _unidades_compatibles(u1: str, u2: str) -> bool:
    """True si u1 y u2 son la misma unidad o sinónimos."""
    if not u1 or not u2:
        return False
    a = u1.strip().lower()
    b = u2.strip().lower()
    if a == b:
        return True
    for grupo in _UNIDADES_SINONIMOS.values():
        if a in grupo and b in grupo:
            return True
    return False


def _buscar_provider_price_list(organizacion_id, descripcion_norm, unidad, item_inventario_id=None):
    """Busca en provider_price_list. Devuelve (mejor, alternativas).

    Estrategia (prioridad descendente):
      0. Match por item_inventario_id (más fuerte).
      1. Match exacto por (descripcion_normalizada, unidad).
      2. Match exacto por descripcion_normalizada con UNIDAD COMPATIBLE
         (sinónimos: m2/m²/mts2; un/u/ud/gl; hora/hr/hs).
      3. Match FUZZY por tokens significativos (Jaccard >=0.5) con unidad
         compatible. Ranking por overlap de tokens.

    El paso 3 es el que sube fuerte la cobertura: items del JMG con
    descripciones largas matchean precios de la lista propia aunque la
    redacción exacta sea distinta.
    """
    from models.provider_price_list import ProviderPriceList

    # Fase 1 IA: buscar en los precios de la ORG y en la BASE GLOBAL (org NULL).
    # Los precios propios de la org PISAN la base global -> se ordena poniendo
    # primero las filas de la org (_org_first) y en fuzzy se les da un bonus.
    _scope = db.or_(ProviderPriceList.organizacion_id == organizacion_id,
                    ProviderPriceList.organizacion_id.is_(None))
    # org propio (0) antes que global (1). CASE, no boolean.desc(): para las
    # filas globales `org == X` da NULL y en Postgres NULL ordena primero en
    # DESC, lo que dejaba ganar a la global sobre el precio propio de la org.
    _org_first = db.case((ProviderPriceList.organizacion_id == organizacion_id, 0), else_=1)

    # Prioridad 0: matching por item_inventario_id (mas fuerte)
    if item_inventario_id:
        candidatos = (ProviderPriceList.query
                      .filter(_scope,
                              ProviderPriceList.item_inventario_id == item_inventario_id)
                      .order_by(_org_first, ProviderPriceList.fecha_actualizacion.desc())
                      .all())
        if candidatos:
            return candidatos[0], candidatos[1:6]

    # Prioridad 1: descripcion_normalizada exacto + unidad exacta
    candidatos = (ProviderPriceList.query
                  .filter(_scope,
                          ProviderPriceList.unidad == unidad,
                          ProviderPriceList.descripcion_normalizada == descripcion_norm)
                  .order_by(_org_first, ProviderPriceList.fecha_actualizacion.desc())
                  .all())
    if candidatos:
        return candidatos[0], candidatos[1:6]

    # Prioridad 2: descripcion exacta con unidad compatible (sinónimos)
    candidatos_desc_exacta = (ProviderPriceList.query
                              .filter(_scope,
                                      ProviderPriceList.descripcion_normalizada == descripcion_norm)
                              .order_by(_org_first, ProviderPriceList.fecha_actualizacion.desc())
                              .all())
    matches_compatibles = [c for c in candidatos_desc_exacta if _unidades_compatibles(c.unidad, unidad)]
    if matches_compatibles:
        return matches_compatibles[0], matches_compatibles[1:6]

    # Prioridad 3: FUZZY por tokens. Solo si hay tokens significativos
    # en la descripción del item.
    tokens_item = _tokens_significativos(descripcion_norm)
    if not tokens_item:
        return None, []

    # Pre-filtro SQL (perf): traer solo candidatos que comparten al menos un
    # token significativo con la query. Sin esto se cargaban/tokenizaban ~8000
    # filas en Python POR CADA recurso -> minutos en un pliego de 192 items.
    # Es seguro: un candidato sin ningun token en comun tiene interseccion 0 y
    # nunca pasaria el umbral, asi que no se pierde ningun match posible.
    toks_filtro = [t for t in tokens_item if len(t) >= 4]
    if not toks_filtro:
        toks_filtro = [t for t in tokens_item if len(t) >= 3]
    q = ProviderPriceList.query.filter(_scope)
    if toks_filtro:
        like = [ProviderPriceList.descripcion_normalizada.ilike('%' + t + '%')
                for t in sorted(toks_filtro, key=len, reverse=True)[:8]]
        q = q.filter(db.or_(*like))
    todos = (q.order_by(_org_first, ProviderPriceList.fecha_actualizacion.desc())
             .limit(2000)
             .all())

    scored = []
    for c in todos:
        tokens_c = _tokens_significativos(c.descripcion_normalizada or c.descripcion or '')
        if not tokens_c:
            continue
        inter = tokens_item & tokens_c
        if not inter:
            continue
        union = tokens_item | tokens_c
        jaccard = len(inter) / len(union)
        # Cobertura de la QUERY: cuanto del concepto buscado esta en el candidato.
        # Fixea "cemento" (1 token) vs "Bolsa de Cemento Loma Negra 50 kg" (Jaccard
        # 0.17 pero cov_item 1.0). Fase 2.1: sube fuerte la cobertura de recursos.
        cov_item = len(inter) / len(tokens_item)
        cov_cand = len(inter) / len(tokens_c)  # especificidad (desempata hacia el menos verboso)
        # Aceptar si la query esta mayormente cubierta O el Jaccard clasico es alto.
        if cov_item < 0.65 and jaccard < 0.4:
            continue
        unidad_bonus = 0.2 if _unidades_compatibles(c.unidad, unidad) else 0.0
        org_bonus = 0.5 if c.organizacion_id == organizacion_id else 0.0
        score = 0.55 * cov_item + 0.30 * jaccard + 0.15 * cov_cand + unidad_bonus + org_bonus
        scored.append((score, c))

    if not scored:
        return None, []

    scored.sort(key=lambda x: x[0], reverse=True)
    mejor = scored[0][1]
    alternativas = [s[1] for s in scored[1:6]]
    return mejor, alternativas


def _buscar_historial_proveedor(organizacion_id, descripcion_norm, unidad):
    """Busca en HistorialPrecioProveedor ultimos 6 meses."""
    from models.proveedores_oc import HistorialPrecioProveedor, ProveedorOC
    from models.provider_price_list import normalizar_descripcion_precio

    # Filtrar por proveedores de la organizacion + ultimos 6m
    seis_meses = date.today() - timedelta(days=180)
    candidatos = (
        db.session.query(HistorialPrecioProveedor, ProveedorOC)
        .join(ProveedorOC, HistorialPrecioProveedor.proveedor_id == ProveedorOC.id)
        .filter(ProveedorOC.organizacion_id == organizacion_id)
        .filter(HistorialPrecioProveedor.fecha >= seis_meses)
        .order_by(HistorialPrecioProveedor.fecha.desc())
        .limit(50)
        .all()
    )
    # Match por descripcion normalizada (in-memory porque la columna no esta normalizada en BD)
    for h, p in candidatos:
        if normalizar_descripcion_precio(h.descripcion_item) == descripcion_norm:
            return {
                'precio': float(h.precio_unitario or 0),
                'fuente': 'historial_proveedor',
                'estado': _calcular_estado(h.fecha),
                'proveedor_id': p.id,
                'proveedor_nombre': p.razon_social,
                'fecha': h.fecha,
                'moneda': h.moneda or 'ARS',
                'notas': f'Historial OC del proveedor {p.razon_social}',
                'referencia_id': h.id,
            }
    return None


def _buscar_referencia_constructora(organizacion_id, descripcion_norm, unidad):
    """Busca en ItemReferenciaConstructora (precios de mercado)."""
    from models.budgets import ItemReferenciaConstructora
    from models.provider_price_list import normalizar_descripcion_precio

    candidatos = ItemReferenciaConstructora.query.filter(
        ItemReferenciaConstructora.organizacion_id == organizacion_id,
        ItemReferenciaConstructora.activo.is_(True),
    ).limit(200).all()
    for ref in candidatos:
        if normalizar_descripcion_precio(ref.descripcion) == descripcion_norm and ref.unidad == unidad:
            return {
                'precio': float(ref.precio_unitario or 0),
                'fuente': 'referencia_constructora',
                'estado': 'estimado',  # referencia de mercado, no proveedor propio
                'proveedor_id': None,
                'proveedor_nombre': None,
                'fecha': ref.fecha_carga.date() if ref.fecha_carga else None,
                'moneda': 'ARS',
                'notas': f'Referencia constructora: {ref.constructora}',
                'referencia_id': ref.id,
            }
    return None


# =====================================================================
# API PUBLICA
# =====================================================================

def buscar_mejor_precio(
    *,
    organizacion_id: int,
    descripcion: str,
    unidad: str,
    tipo_recurso: str = 'material',
    item_inventario_id: Optional[int] = None,
    presupuesto=None,
    zona: str = 'CABA',
) -> Dict[str, Any]:
    """Busca el mejor precio segun jerarquia dual.

    Args:
      tipo_recurso: 'material' | 'mano_obra' | 'equipo'
      organizacion_id: scope multi-tenant.
      descripcion, unidad: para matching.
      item_inventario_id: opcional, prioridad 0 en materiales.
      presupuesto: opcional, para conversion de moneda con su TC.
      zona: zona laboral para mano de obra (default CABA).

    Returns:
      {
        'precio': float (en ARS si se pudo convertir),
        'fuente': str,
        'estado': str,
        'proveedor_id': int|None,
        'proveedor_nombre': str|None,
        'fecha': date|None,
        'moneda_original': str,
        'requiere_tc': bool,
        'auditoria_moneda': dict|None,
        'alternativas': list,
        'notas': str,
      }
    """
    from models.provider_price_list import normalizar_descripcion_precio

    desc_norm = normalizar_descripcion_precio(descripcion)
    tipo = (tipo_recurso or '').lower()

    info = None
    alternativas_raw = []

    # ----- MANO DE OBRA -----
    if tipo == 'mano_obra':
        # Fase 2.1: fuente principal = costo empresa via categorias_jornal + recargos.
        info = _buscar_costo_mo_v2(organizacion_id, descripcion, unidad, zona)
        if not info:
            info = _buscar_mo_costo_referencia(organizacion_id, descripcion, unidad, zona)
        if not info:
            info = _buscar_categoria_jornal(organizacion_id, descripcion, unidad)

    # ----- MATERIAL / EQUIPO / OTRO -----
    else:
        mejor, alternativas = _buscar_provider_price_list(
            organizacion_id, desc_norm, unidad, item_inventario_id
        )
        if mejor:
            info = {
                'precio': float(mejor.precio_unitario),
                'fuente': 'provider_price_list',
                'fuente_lista': mejor.fuente,  # 'estimado' | proveedor | etc (Fase 2.5)
                'estado': _calcular_estado(mejor.fecha_actualizacion),
                'proveedor_id': mejor.proveedor_id,
                'proveedor_nombre': mejor.proveedor.razon_social if mejor.proveedor else None,
                'fecha': mejor.fecha_actualizacion,
                'moneda': mejor.moneda or 'ARS',
                'notas': f'Lista de precios{" - " + mejor.proveedor.razon_social if mejor.proveedor else ""}',
                'referencia_id': mejor.id,
            }
            if not mejor.esta_vigente():
                # Vencido por vigencia_hasta -> estado mas pesimista
                info['estado'] = 'vencido'
            alternativas_raw = [{
                'precio': float(a.precio_unitario),
                'proveedor_nombre': a.proveedor.razon_social if a.proveedor else None,
                'fuente': 'provider_price_list',
                'estado': _calcular_estado(a.fecha_actualizacion),
                'fecha': a.fecha_actualizacion.isoformat() if a.fecha_actualizacion else None,
            } for a in (alternativas or [])][:5]

        if not info:
            info = _buscar_historial_proveedor(organizacion_id, desc_norm, unidad)
        if not info:
            info = _buscar_referencia_constructora(organizacion_id, desc_norm, unidad)

    # Sin matching
    if not info:
        return {
            'precio': 0.0,
            'fuente': 'sin_precio',
            'estado': 'sin_precio',
            'proveedor_id': None,
            'proveedor_nombre': None,
            'fecha': None,
            'moneda_original': 'ARS',
            'requiere_tc': False,
            'auditoria_moneda': None,
            'alternativas': [],
            'notas': '',
        }

    # Conversion de moneda si corresponde
    moneda = info.get('moneda', 'ARS')
    precio_ars, audit_moneda, requiere_tc = _convertir_moneda(
        info['precio'], moneda, presupuesto,
    )
    if requiere_tc:
        return {
            'precio': 0.0,
            'fuente': info['fuente'],
            'estado': 'requiere_tc',
            'proveedor_id': info.get('proveedor_id'),
            'proveedor_nombre': info.get('proveedor_nombre'),
            'fecha': info.get('fecha'),
            'moneda_original': moneda,
            'requiere_tc': True,
            'auditoria_moneda': audit_moneda,
            'alternativas': alternativas_raw,
            'notas': info.get('notas') + ' (requiere tipo de cambio)',
        }

    return {
        'precio': float(precio_ars),
        'fuente': info['fuente'],
        'fuente_lista': info.get('fuente_lista'),
        'estado': info['estado'],
        'proveedor_id': info.get('proveedor_id'),
        'proveedor_nombre': info.get('proveedor_nombre'),
        'fecha': info.get('fecha'),
        'moneda_original': moneda,
        'requiere_tc': False,
        'auditoria_moneda': audit_moneda,
        'alternativas': alternativas_raw,
        'notas': info.get('notas', ''),
    }


def estimar_precios_presupuesto(presupuesto, *, user_id=None):
    """Itera composiciones del presupuesto y aplica precios estimados.

    NO commitea. El caller (endpoint) maneja transaction + audit log.

    Reglas:
      - Salta composiciones con precio_estado='manual' (override del usuario).
      - Salta items solo_interno=True (no afectan al cliente — Fase 5.A acotada).
      - Bloquea si presupuesto.precios_snapshot_at esta seteado (snapshot Fase 5.C).

    Returns:
      dict con contadores por estado + costo total + precio sugerido al cliente.
    """
    from models.budgets import ItemPresupuesto, ItemPresupuestoComposicion

    if presupuesto.precios_snapshot_at:
        raise ValueError(
            'El presupuesto tiene precios congelados (snapshot al confirmar como obra). '
            'No se puede re-estimar.'
        )
    if presupuesto.estado not in ('borrador', 'enviado'):
        raise ValueError(f'Presupuesto en estado {presupuesto.estado}: no editable.')

    contadores = {
        'composiciones_evaluadas': 0,
        'actualizados': 0,
        'estimados': 0,
        'vencidos': 0,
        'sin_precio': 0,
        'requiere_tc': 0,
        'manual': 0,                  # composiciones individuales con precio_estado='manual'
        'mo_aplicadas': 0,
        'manuales_respetados': 0,     # items completos con precio_locked=True (Lock Manual MVP)
    }

    org_id = presupuesto.organizacion_id

    items = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
        solo_interno=False,
    ).all()

    for item in items:
        # Lock Manual MVP: si el item tiene precio_locked, la IA no toca
        # ninguna de sus composiciones — el usuario lo ajusto a mano y no
        # debe sobrescribirse en re-estimaciones.
        if getattr(item, 'precio_locked', False):
            contadores['manuales_respetados'] += 1
            continue

        for comp in (item.composiciones.all() if hasattr(item.composiciones, 'all') else item.composiciones):
            contadores['composiciones_evaluadas'] += 1
            # Skip si es manual
            if (comp.precio_estado or '').lower() == 'manual':
                contadores['manual'] += 1
                continue

            info = buscar_mejor_precio(
                organizacion_id=org_id,
                descripcion=comp.descripcion or '',
                unidad=comp.unidad or '',
                tipo_recurso=comp.tipo,
                item_inventario_id=comp.item_inventario_id,
                presupuesto=presupuesto,
            )

            comp.precio_unitario = Decimal(str(info['precio']))
            comp.total = (Decimal(str(comp.cantidad or 0)) * comp.precio_unitario).quantize(Decimal('0.01'))
            comp.precio_fuente = info['fuente']
            comp.precio_estado = info['estado']
            comp.precio_proveedor_id = info.get('proveedor_id')
            comp.precio_actualizado_at = datetime.utcnow()

            audit = info.get('auditoria_moneda') or {}
            comp.precio_original = audit.get('precio_original')
            comp.precio_moneda_original = audit.get('precio_moneda_original')
            comp.precio_tipo_cambio_usado = audit.get('precio_tipo_cambio_usado')
            comp.precio_tipo_cambio_fecha = audit.get('precio_tipo_cambio_fecha')

            estado = info['estado']
            if estado == 'actualizado':
                contadores['actualizados'] += 1
            elif estado == 'estimado':
                contadores['estimados'] += 1
            elif estado == 'vencido':
                contadores['vencidos'] += 1
            elif estado == 'requiere_tc':
                contadores['requiere_tc'] += 1
            else:
                contadores['sin_precio'] += 1

            if (comp.tipo or '').lower() == 'mano_obra' and info['precio'] > 0:
                contadores['mo_aplicadas'] += 1

    # Margen comercial unico para el presupuesto (override > org > 25%).
    margen = (
        presupuesto.margen_comercial_override
        or presupuesto.organizacion.margen_comercial_default
        or Decimal('25.00')
    )
    margen_dec = Decimal(str(margen))
    factor_margen = Decimal('1') + margen_dec / Decimal('100')

    # 2026-05-07 FIX: ademas de actualizar precio en composiciones, volcar
    # el precio al ItemPresupuesto (precio_unitario / total) para que el
    # presupuesto comercial muestre los valores. Antes /estimar-precios
    # solo tocaba composiciones y el presupuesto seguia viendose en $0.
    # Reglas:
    #   - precio_locked=True -> no tocar (Lock Manual respetado).
    #   - solo_interno=True  -> no entra al loop original (filtro arriba).
    #   - cantidad <= 0      -> no se puede dividir; saltamos.
    #   - sin composiciones  -> usar item.cantidad * costo unitario sugerido
    #     desde la lista de precios propios sobre la descripcion del item.
    contadores['items_volcados'] = 0
    contadores['items_sin_composicion'] = 0
    contadores['items_locked'] = 0
    contadores['items_costo_cero'] = 0
    contadores['items_cantidad_cero'] = 0
    contadores['items_volcados_directos'] = 0  # sin composicion, precio buscado por descripcion
    total_costo = Decimal('0')
    items_total = len(items)

    for item in items:
        # items ya filtra solo_interno=False. Falta saltar locked aqui.
        item_locked = bool(getattr(item, 'precio_locked', False))
        comps = list(
            item.composiciones.all() if hasattr(item.composiciones, 'all') else item.composiciones
        )
        costo_item = Decimal('0')
        for comp in comps:
            costo_item += Decimal(str(comp.total or 0))
        total_costo += costo_item

        if item_locked:
            contadores['items_locked'] += 1
            continue

        cantidad = Decimal(str(item.cantidad or 0))
        if cantidad <= 0:
            contadores['items_cantidad_cero'] += 1
            continue

        precio_unit_item = None
        precio_total_item = None
        es_directo = False

        if comps and costo_item > 0:
            # Camino normal: APU armada + composiciones con precio.
            precio_total_item = (costo_item * factor_margen).quantize(Decimal('0.01'))
            precio_unit_item = (precio_total_item / cantidad).quantize(Decimal('0.01'))
        else:
            # Fallback 2026-05-07: items sin composicion (globales/servicios o
            # items que generar-preliminar no descompuso) intentan precio
            # directo desde la lista propia / proveedores por descripcion.
            # Esto evita que el comercial quede en $0 cuando hay items sin APU.
            try:
                info = buscar_mejor_precio(
                    organizacion_id=org_id,
                    descripcion=item.descripcion or '',
                    unidad=item.unidad or '',
                    tipo_recurso=item.tipo,
                    item_inventario_id=getattr(item, 'item_inventario_id', None),
                    presupuesto=presupuesto,
                )
            except Exception:
                info = None

            precio_directo = Decimal(str((info or {}).get('precio') or 0))
            if precio_directo > 0:
                # Aplicamos el mismo margen comercial que en composiciones para
                # llegar al precio sugerido al cliente.
                precio_unit_item = (precio_directo * factor_margen).quantize(Decimal('0.01'))
                precio_total_item = (precio_unit_item * cantidad).quantize(Decimal('0.01'))
                es_directo = True
                # Sumar al total_costo para que el total general reflije esto tambien.
                total_costo += (precio_directo * cantidad).quantize(Decimal('0.01'))
            else:
                if not comps:
                    contadores['items_sin_composicion'] += 1
                else:
                    contadores['items_costo_cero'] += 1
                continue

        item.precio_unitario = precio_unit_item
        item.total = precio_total_item
        # Mirror en columnas ARS si la moneda del presupuesto es ARS
        # (presupuestos JMG/demo son todos ARS). Para currency!=ARS dejamos
        # los espejos como estan y dejamos que la conversion la haga el caller.
        currency_item = (item.currency or 'ARS').upper()
        if currency_item == 'ARS':
            item.price_unit_ars = precio_unit_item
            item.total_ars = precio_total_item
        item.origen = item.origen or 'ia'
        contadores['items_volcados'] += 1
        if es_directo:
            contadores['items_volcados_directos'] += 1

    # Logging visible en Railway logs para diagnostico de "presupuesto sigue en $0".
    # WARNING level para que sea facil de filtrar en Railway logs.
    try:
        from flask import current_app
        current_app.logger.warning(
            '[estimar_precios] presupuesto=%s items_total=%d volcados=%d '
            'sin_comp=%d locked=%d costo_cero=%d cant_cero=%d total_costo=%s factor=%s',
            presupuesto.id, items_total, contadores['items_volcados'],
            contadores['items_sin_composicion'], contadores['items_locked'],
            contadores['items_costo_cero'], contadores['items_cantidad_cero'],
            total_costo, factor_margen,
        )
    except Exception:
        pass

    # Forzar flush para detectar errores de persistencia inmediatamente.
    # Si algun UPDATE falla por constraint/tipo, sale aca y no en el commit
    # final del endpoint (donde el rollback nos perderia el log de items_volcados).
    try:
        db.session.flush()
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.exception(
                '[estimar_precios] flush fallo presupuesto=%s err=%s',
                presupuesto.id, type(e).__name__,
            )
        except Exception:
            pass
        raise

    precio_sugerido = (total_costo * factor_margen).quantize(Decimal('0.01'))

    total_eval = contadores['composiciones_evaluadas']
    cobertura_pct = 0.0
    if total_eval > 0:
        cobertura_pct = round(
            100.0 * (contadores['actualizados'] + contadores['estimados']) / total_eval, 1
        )

    return {
        **contadores,
        'total_costo': float(total_costo),
        'margen_aplicado': float(margen_dec),
        'precio_sugerido_cliente': float(precio_sugerido),
        'cobertura_pct': cobertura_pct,
    }


# ============================================================================
# FASE 1 - Precios crowdsourced de clientes (aprendizaje de OBYRA)
# ============================================================================

ZONA_DEFAULT = 'Buenos Aires'


def obtener_precio_promedio(material, zona=ZONA_DEFAULT, ultimos_dias=30,
                            fuente='confirmado_cliente'):
    """Promedio de precio aprendido para un material, por fuente (FASE 1 / FASE 2).

    Devuelve (precio_promedio: Decimal|None, cantidad_confirmaciones: int,
    fecha_mas_reciente: datetime|None). Filtra por material (ya normalizado) exacto,
    zona, `fuente` y los ultimos `ultimos_dias` dias. None si no hay datos.
    """
    from sqlalchemy import func
    from models.budgets import PresupuestoPrecioConfirmado

    mat = (material or '').strip()
    if not mat:
        return (None, 0, None)
    desde = datetime.utcnow() - timedelta(days=ultimos_dias)
    prom, n, fecha = db.session.query(
        func.avg(PresupuestoPrecioConfirmado.precio_unitario),
        func.count(PresupuestoPrecioConfirmado.id),
        func.max(PresupuestoPrecioConfirmado.fecha),
    ).filter(
        PresupuestoPrecioConfirmado.material == mat,
        PresupuestoPrecioConfirmado.zona == zona,
        PresupuestoPrecioConfirmado.fecha >= desde,
        PresupuestoPrecioConfirmado.fuente == fuente,
    ).one()
    if not n or prom is None:
        return (None, 0, None)
    return (Decimal(str(prom)), int(n), fecha)


def _proveedores_de(material, zona, ultimos_dias):
    """Proveedores distintos que publicaron precio para un material (para el badge)."""
    from models.budgets import PresupuestoPrecioConfirmado

    desde = datetime.utcnow() - timedelta(days=ultimos_dias)
    rows = db.session.query(PresupuestoPrecioConfirmado.proveedor).filter(
        PresupuestoPrecioConfirmado.material == material,
        PresupuestoPrecioConfirmado.zona == zona,
        PresupuestoPrecioConfirmado.fecha >= desde,
        PresupuestoPrecioConfirmado.fuente == 'scraping',
        PresupuestoPrecioConfirmado.proveedor.isnot(None),
    ).distinct().all()
    return [r[0] for r in rows if r[0]]


def obtener_precio_cascada(material, zona=ZONA_DEFAULT, ultimos_dias=30):
    """Cascada de precios aprendidos: confirmado_cliente > scraping (FASE 1 + 2).

    NO mezcla los tiers: una confirmacion real de un cliente vale mas que N listas
    de proveedor, asi que si hay confirmaciones se usan esas y el scraping ni se
    consulta. Dentro de cada tier promedia los ultimos `ultimos_dias` dias.

    Devuelve (precio: Decimal|None, n: int, fecha: datetime|None,
              fuente: 'confirmado'|'scraping'|None, proveedores: list[str])
    """
    prom, n, fecha = obtener_precio_promedio(material, zona, ultimos_dias, 'confirmado_cliente')
    if prom is not None:
        return (prom, n, fecha, 'confirmado', [])
    prom, n, fecha = obtener_precio_promedio(material, zona, ultimos_dias, 'scraping')
    if prom is not None:
        return (prom, n, fecha, 'scraping', _proveedores_de(material, zona, ultimos_dias))
    return (None, 0, None, None, [])


def existe_precio_aprendido(zona=ZONA_DEFAULT, ultimos_dias=30):
    """True si hay AL MENOS un precio aprendido vigente (cliente O scraping) para la
    zona. Perf: permite saltear el lookup por item cuando no hay nada -> evita N+1 en
    pliegos grandes."""
    from sqlalchemy import exists
    from models.budgets import PresupuestoPrecioConfirmado

    desde = datetime.utcnow() - timedelta(days=ultimos_dias)
    return bool(db.session.query(exists().where(
        (PresupuestoPrecioConfirmado.zona == zona) &
        (PresupuestoPrecioConfirmado.fecha >= desde) &
        (PresupuestoPrecioConfirmado.fuente.in_(('confirmado_cliente', 'scraping')))
    )).scalar())


def registrar_precios_confirmados(presupuesto, items):
    """Registra los precios que el cliente CONFIRMO en un presupuesto (FASE 1).

    Toma los items del cache del pipeline que el usuario marco como confirmados
    (flag `confirmado_por_usuario`, seteado al aceptar/editar un precio en la
    pantalla de validacion) y guarda uno por (presupuesto, material).

    Idempotente: borra las confirmaciones previas de este presupuesto y reinserta,
    para que re-guardar el cache no infle el conteo de 'confirmaciones' (cada
    presupuesto cuenta como 1 cliente por material). No guarda si precio<=0 o
    cantidad<=0. `material` = descripcion del item normalizada (== clave de lookup).

    Devuelve la cantidad de materiales registrados.
    """
    from decimal import InvalidOperation
    from models.budgets import PresupuestoPrecioConfirmado
    from services.pipeline_presupuesto_ia import _norm_material

    if not presupuesto or not isinstance(items, list):
        return 0
    zona = (getattr(presupuesto, 'zona', None) or ZONA_DEFAULT)
    org_id = getattr(presupuesto, 'organizacion_id', None)

    # Uno por material dentro del presupuesto (el ultimo gana). Solo items que el
    # usuario confirmo/edito -> senal real de mercado (no el estimado del pipeline).
    por_material = {}
    for it in (items or []):
        if not isinstance(it, dict) or not it.get('confirmado_por_usuario'):
            continue
        if (it.get('estado') or 'item') != 'item':
            continue
        try:
            precio = Decimal(str(it.get('precio_unitario') or it.get('costo_unitario') or 0))
            cant = Decimal(str(it.get('cantidad') or 0))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if precio <= 0 or cant <= 0:
            continue
        mat = _norm_material(it.get('descripcion'))
        if not mat:
            continue
        por_material[mat[:255]] = {
            'precio': precio, 'cant': cant, 'unidad': (it.get('unidad') or '')[:50],
        }

    PresupuestoPrecioConfirmado.query.filter_by(
        presupuesto_id=presupuesto.id, fuente='confirmado_cliente').delete()
    for mat, d in por_material.items():
        db.session.add(PresupuestoPrecioConfirmado(
            presupuesto_id=presupuesto.id, material=mat,
            precio_unitario=d['precio'], unidad=d['unidad'], cantidad=d['cant'],
            organizacion_id=org_id, zona=zona, fuente='confirmado_cliente'))
    db.session.commit()
    return len(por_material)


# ============================================================================
# FASE 2 - Scraping de listas de proveedores (N8N -> POST /precio-scraping)
# ============================================================================

# Unidades aceptadas (canonicas) y sus alias. Todo lo que no mapee se rechaza:
# una unidad mal detectada es la causa raiz del bug "precio de bolsa como $/kg".
_UNIDAD_ALIAS = {
    'u': 'u', 'un': 'u', 'uni': 'u', 'unid': 'u', 'unidad': 'u', 'unidades': 'u',
    'pza': 'u', 'pieza': 'u', 'piezas': 'u', 'c/u': 'u', 'cu': 'u',
    'kg': 'kg', 'kgs': 'kg', 'kilo': 'kg', 'kilos': 'kg', 'kilogramo': 'kg',
    'g': 'g', 'gr': 'g', 'grs': 'g', 'gramo': 'g', 'gramos': 'g',
    'tn': 'tn', 'ton': 'tn', 'tonelada': 'tn', 'toneladas': 'tn',
    'm': 'ml', 'ml': 'ml', 'mt': 'ml', 'mts': 'ml', 'metro': 'ml', 'metros': 'ml',
    'm2': 'm2', 'mt2': 'm2', 'm²': 'm2', 'metro2': 'm2',
    'm3': 'm3', 'mt3': 'm3', 'm³': 'm3', 'metro3': 'm3',
    'l': 'l', 'lt': 'l', 'lts': 'l', 'litro': 'l', 'litros': 'l',
    'bolsa': 'bolsa', 'bolsas': 'bolsa', 'bls': 'bolsa',
    'caja': 'caja', 'cajas': 'caja', 'rollo': 'rollo', 'rollos': 'rollo',
    'balde': 'balde', 'baldes': 'balde', 'tambor': 'tambor', 'bidon': 'bidon',
    'pallet': 'pallet', 'barra': 'barra', 'barras': 'barra', 'chapa': 'chapa',
    'jgo': 'jgo', 'juego': 'jgo', 'par': 'par',
    'paquete': 'paquete', 'paq': 'paquete', 'pack': 'paquete',
}

# Token de "tamano de envase" en la descripcion (ej "50 KG", "X 20LTS", "1000 GR").
_RE_ENVASE = re.compile(r'(?:^|[\sx×])(\d+(?:[.,]\d+)?)\s*(kgs?|grs?|lts?|l)\b')
_ENVASE_BASE = {'kg': 'kg', 'kgs': 'kg', 'g': 'g', 'gr': 'g', 'grs': 'g',
                'l': 'l', 'lt': 'l', 'lts': 'l'}


def _unidad_canonica(unidad):
    """Mapea la unidad recibida a la canonica de OBYRA. None si no se reconoce."""
    u = (unidad or '').strip().lower().replace('.', '')
    return _UNIDAD_ALIAS.get(u)


def _es_envase_sospechoso(descripcion_norm, unidad_canon):
    """True si la descripcion declara un envase (ej '50 KG') y la unidad dice ser esa
    MISMA unidad base. Entonces el precio es por ENVASE, no por unidad base: cargarlo
    como $/kg lo infla N veces. Es exactamente el bug del adhesivo a $146.834/kg
    (bolsa cargada como kilo) que reventaba porcelanato a $917.712/m2.
    """
    if unidad_canon not in ('kg', 'g', 'l'):
        return False
    for cant_txt, tok in _RE_ENVASE.findall(descripcion_norm or ''):
        base = _ENVASE_BASE.get(tok)
        if base != unidad_canon:
            continue
        try:
            if float(cant_txt.replace(',', '.')) > 1:
                return True
        except ValueError:
            continue
    return False


def registrar_precios_scraping(items, zona_default=ZONA_DEFAULT):
    """Registra precios scrapeados de listas de proveedores (FASE 2).

    Escribe en DOS lugares, a proposito:
      1. presupuesto_precio_confirmado (fuente='scraping'): alimenta la cascada a
         nivel ITEM. Upsert por (proveedor, material, unidad, zona) -> una fila
         vigente por producto y proveedor, no crece sin limite con cada corrida.
      2. provider_price_list (global, organizacion_id NULL, fuente='scraping'): es
         la tabla que buscar_mejor_precio ya usa con fuzzy matching para pricear los
         RECURSOS de cada APU. Aca esta el valor real del scraping, porque las listas
         de proveedor son de materiales, no de items de pliego.

    Guards (no negociables, protegen la base de precios):
      - Unidad debe mapear a una canonica conocida; si no, se ignora el item.
      - Si la descripcion declara envase ('50 KG') y la unidad dice 'kg', el precio
        es por bolsa -> NO se manda a provider_price_list (envenenaria los APU).
      - NUNCA pisa una fila de provider_price_list curada (fuente != 'scraping'):
        los seeds corregidos a mano tienen prioridad sobre el scraping.

    Devuelve un dict con el detalle de lo procesado.
    """
    from decimal import InvalidOperation
    from models.budgets import PresupuestoPrecioConfirmado
    from models.provider_price_list import ProviderPriceList, normalizar_descripcion_precio
    from services.pipeline_presupuesto_ia import _norm_material

    res = {'recibidos': 0, 'guardados': 0, 'lista_proveedor': 0, 'ignorados': 0,
           'envase_sospechoso': 0, 'curados_preservados': 0, 'errores': []}
    hoy = date.today()
    ahora = datetime.utcnow()

    for raw in (items or []):
        res['recibidos'] += 1
        if not isinstance(raw, dict):
            res['ignorados'] += 1
            continue
        desc = (raw.get('material') or raw.get('descripcion') or '').strip()
        prov = (raw.get('proveedor') or '').strip()[:120] or None
        zona = (raw.get('zona') or zona_default).strip()[:100]
        unidad = _unidad_canonica(raw.get('unidad'))
        try:
            precio = Decimal(str(raw.get('precio_unitario') or raw.get('precio') or 0))
        except (InvalidOperation, TypeError, ValueError):
            precio = Decimal('0')

        if not desc or precio <= 0 or unidad is None:
            res['ignorados'] += 1
            if len(res['errores']) < 20:
                res['errores'].append({
                    'material': desc[:80],
                    'motivo': ('descripcion vacia' if not desc else
                               'precio <= 0' if precio <= 0 else
                               f"unidad no reconocida: {raw.get('unidad')!r}")})
            continue

        mat = _norm_material(desc)[:255]
        if not mat:
            res['ignorados'] += 1
            continue

        # 1. Cascada a nivel item: upsert por proveedor+material+unidad+zona.
        row = PresupuestoPrecioConfirmado.query.filter_by(
            fuente='scraping', proveedor=prov, material=mat,
            unidad=unidad, zona=zona).first()
        if row is None:
            row = PresupuestoPrecioConfirmado(
                presupuesto_id=None, organizacion_id=None, material=mat,
                unidad=unidad, cantidad=Decimal('1'), zona=zona,
                fuente='scraping', proveedor=prov)
            db.session.add(row)
        row.precio_unitario = precio
        row.fecha = ahora
        res['guardados'] += 1

        # 2. Base de precios que usan los APU. Con guards.
        if _es_envase_sospechoso(mat, unidad):
            res['envase_sospechoso'] += 1
            continue
        dn = normalizar_descripcion_precio(desc)
        ppl = ProviderPriceList.query.filter(
            ProviderPriceList.organizacion_id.is_(None),
            ProviderPriceList.proveedor_id.is_(None),
            ProviderPriceList.descripcion_normalizada == dn,
            ProviderPriceList.unidad == unidad,
        ).first()
        if ppl is not None and (ppl.fuente or '') != 'scraping':
            res['curados_preservados'] += 1   # seed/lista real corregida a mano: no tocar
            continue
        if ppl is None:
            ppl = ProviderPriceList(
                organizacion_id=None, proveedor_id=None, descripcion=desc[:300],
                descripcion_normalizada=dn, unidad=unidad)
            db.session.add(ppl)
        ppl.precio_unitario = precio
        ppl.moneda = 'ARS'
        ppl.fuente = 'scraping'
        ppl.fecha_actualizacion = hoy
        ppl.notas = f'Scraping {prov or "?"} {hoy.isoformat()}'
        res['lista_proveedor'] += 1

    db.session.commit()
    return res
