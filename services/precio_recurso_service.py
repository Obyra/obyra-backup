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

    # Traer precios de la org + base global. Con la base OBYRA (~6.3k recursos)
    # el cap se sube; el orden pone primero las filas de la org. (Optimizacion
    # futura: pre-filtrar por token/prefijo antes del scan en Python.)
    todos = (ProviderPriceList.query
             .filter(_scope)
             .order_by(_org_first, ProviderPriceList.fecha_actualizacion.desc())
             .limit(8000)
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
