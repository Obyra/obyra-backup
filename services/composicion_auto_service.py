"""Generador de composicion ejecutiva automatica (Fase 4).

Toma cada item del presupuesto que tiene `analisis_ia.regla_id` y crea
una serie de `ItemPresupuestoComposicion` (materiales + MO + equipos)
usando los coeficientes del YAML.

Reglas operativas:
  - Idempotente: si el item ya tiene composiciones con origen='calculadora_ia',
    salta el item (no duplica).
  - Respeta composiciones manuales: si el item tiene composiciones con
    origen != 'calculadora_ia', tambien salta. La sugerencia es que el
    usuario las borre antes de regenerar.
  - Filtra cantidades < 0.001 (ruido por coeficientes muy chicos).
  - Marca todas las composiciones generadas como `es_estimado=True` y
    `precio_unitario=0` (el precio se llena en la etapa de catalogo).
  - Sincroniza MaterialCotizable al final.
  - NO modifica presupuestos aprobados ni con ejecutivo aprobado (esa
    validacion esta en el endpoint).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from extensions import db


CANTIDAD_MINIMA = Decimal('0.001')

# Tipos validos para ItemPresupuestoComposicion.tipo. El YAML puede tener
# otros (ej: 'servicio') pero los mapeamos aca para mantener compat con la
# logica existente de sincronizar_materiales_cotizables.
TIPOS_VALIDOS = ('material', 'mano_obra', 'equipo')


def _normalizar_tipo(tipo_yaml: str) -> str:
    """Mapea tipos del YAML a los tipos validos en BD.

    En Fase 4, 'servicio' se mapea a 'equipo' por simplicidad (decision
    confirmada por producto). Si en el futuro queremos distinguir, agregar
    'servicio' como tipo valido y ajustar sincronizar_materiales_cotizables.
    """
    t = (tipo_yaml or '').strip().lower()
    if t in TIPOS_VALIDOS:
        return t
    if t == 'servicio':
        return 'equipo'
    if t in ('mo', 'manoobra'):
        return 'mano_obra'
    # Default a material si viene algo raro
    return 'material'


def _decimal(v) -> Decimal:
    """Convierte a Decimal de forma segura (devuelve 0 si no se puede)."""
    if v is None:
        return Decimal('0')
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal('0')


def _composiciones_existentes(item) -> Dict[str, int]:
    """Cuenta composiciones del item agrupadas por origen.

    Returns: {'manual': N, 'calculadora_ia': M, ...}
    """
    out: Dict[str, int] = {}
    try:
        for c in (item.composiciones.all() if hasattr(item.composiciones, 'all') else item.composiciones):
            o = (c.origen or 'manual').lower()
            out[o] = out.get(o, 0) + 1
    except Exception:
        pass
    return out


def generar_para_item(item, *, regla_id: Optional[str]) -> Dict[str, Any]:
    """Genera composiciones para UN item. Idempotente.

    Returns dict con:
      'estado': 'creado' | 'sin_regla' | 'sin_coeficiente' |
                'ya_generado' | 'respetado_manual' | 'cantidad_invalida' |
                'global_no_desglosa' | 'servicio_no_desglosa' | 'excluido'
      'composiciones_creadas': int
      'recursos_filtrados_chicos': int  (cantidad < 0.001)
    """
    from models.budgets import ItemPresupuestoComposicion
    from services.coeficientes_loader import get_recursos, tiene_coeficientes

    # Respeto al tipo_tratamiento elegido por el usuario:
    # 'global'    -> el item entra al ejecutivo como linea global, no se desglosa.
    # 'servicio'  -> se cotizara como servicio, no se desglosa con coeficientes.
    # 'excluir'   -> queda fuera del preliminar.
    # 'desglosar' -> flujo normal con coeficientes YAML.
    blob = getattr(item, 'analisis_ia', None) or {}
    tt = ''
    if isinstance(blob, dict):
        tt = (blob.get('tipo_tratamiento') or '').lower()
        if not tt:
            sug_tt = blob.get('sugerencias') if 'sugerencias' in blob else None
            if isinstance(sug_tt, dict):
                tt = (sug_tt.get('tipo_tratamiento') or '').lower()
    if tt == 'excluir':
        return {'estado': 'excluido', 'composiciones_creadas': 0}
    if tt == 'global':
        return {'estado': 'global_no_desglosa', 'composiciones_creadas': 0}
    if tt == 'servicio':
        return {'estado': 'servicio_no_desglosa', 'composiciones_creadas': 0}

    if not regla_id:
        return {'estado': 'sin_regla', 'composiciones_creadas': 0}

    if not tiene_coeficientes(regla_id):
        return {'estado': 'sin_coeficiente', 'composiciones_creadas': 0}

    # Idempotencia + respeto a composiciones manuales
    existentes = _composiciones_existentes(item)
    if existentes.get('calculadora_ia', 0) > 0:
        return {'estado': 'ya_generado', 'composiciones_creadas': 0}
    # Si tiene composiciones de cualquier otro origen (manual / importado),
    # no las pisamos. El usuario debe borrarlas manualmente para regenerar.
    otras = sum(v for k, v in existentes.items() if k != 'calculadora_ia')
    if otras > 0:
        return {'estado': 'respetado_manual', 'composiciones_creadas': 0}

    cantidad_item = _decimal(item.cantidad)
    if cantidad_item <= 0:
        return {'estado': 'cantidad_invalida', 'composiciones_creadas': 0}

    recursos = get_recursos(regla_id)
    creadas = 0
    filtradas = 0

    for r in recursos:
        coef = _decimal(r.get('coeficiente'))
        if coef <= 0:
            continue
        cantidad_calc = (cantidad_item * coef).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
        if cantidad_calc < CANTIDAD_MINIMA:
            filtradas += 1
            continue

        notas_partes = ['Estimacion orientativa.', f'Coeficiente: {coef}.']
        if r.get('notas'):
            notas_partes.append(str(r['notas']))
        notas = ' '.join(notas_partes)[:1000]

        clave_yaml = f"{regla_id}.{r.get('clave', '')}"[:80]

        comp = ItemPresupuestoComposicion(
            item_presupuesto_id=item.id,
            tipo=_normalizar_tipo(r.get('tipo', 'material')),
            descripcion=str(r.get('nombre') or '')[:300],
            unidad=str(r.get('unidad') or '')[:20],
            cantidad=cantidad_calc,
            precio_unitario=Decimal('0'),
            total=Decimal('0'),
            notas=notas,
            origen='calculadora_ia',
            es_estimado=True,
            coeficiente_usado=clave_yaml,
        )
        db.session.add(comp)
        creadas += 1

    return {
        'estado': 'creado' if creadas else 'sin_recursos_validos',
        'composiciones_creadas': creadas,
        'recursos_filtrados_chicos': filtradas,
    }


def generar_preliminar(presupuesto, *, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Genera composiciones ejecutivas para todos los items del presupuesto.

    Retorna un dict con resumen + lista de items saltados (max 50).
    NO commitea. El caller (endpoint) hace el commit + audit log + sync.
    """
    from models.budgets import ItemPresupuesto
    from services.coeficientes_loader import metadatos as yaml_metadatos

    items = ItemPresupuesto.query.filter_by(
        presupuesto_id=presupuesto.id,
        solo_interno=False,
    ).order_by(ItemPresupuesto.id).all()

    contadores = {
        'items_procesados': 0,
        'items_creados': 0,
        'composiciones_creadas': 0,
        'items_ya_generado': 0,
        'items_respetado_manual': 0,
        'items_sin_regla': 0,
        'items_sin_coeficiente': 0,
        'items_cantidad_invalida': 0,
        'items_globales': 0,
        'items_servicio': 0,
        'items_excluidos': 0,
        'recursos_filtrados_chicos': 0,
    }
    saltados: List[Dict[str, Any]] = []
    advertencias: List[str] = []

    for it in items:
        contadores['items_procesados'] += 1
        # Extraer regla_id del blob analisis_ia (lo guardado al aplicar IA)
        regla_id = None
        analisis = getattr(it, 'analisis_ia', None) or {}
        if isinstance(analisis, dict):
            sug = analisis.get('sugerencias') if 'sugerencias' in analisis else analisis
            if isinstance(sug, dict):
                regla_id = sug.get('regla_id')

        res = generar_para_item(it, regla_id=regla_id)
        estado = res['estado']
        contadores['composiciones_creadas'] += res.get('composiciones_creadas', 0)
        contadores['recursos_filtrados_chicos'] += res.get('recursos_filtrados_chicos', 0)

        if estado == 'creado':
            contadores['items_creados'] += 1
        elif estado == 'sin_regla':
            contadores['items_sin_regla'] += 1
            if len(saltados) < 50:
                saltados.append({
                    'item_id': it.id,
                    'descripcion': (it.descripcion or '')[:120],
                    'razon': 'Sin regla técnica detectada por la Calculadora IA. Aplicar análisis IA primero.',
                })
        elif estado == 'sin_coeficiente':
            contadores['items_sin_coeficiente'] += 1
            if len(saltados) < 50:
                saltados.append({
                    'item_id': it.id,
                    'descripcion': (it.descripcion or '')[:120],
                    'razon': f'Sin coeficiente cargado para esta regla técnica ({regla_id}).',
                })
        elif estado == 'ya_generado':
            contadores['items_ya_generado'] += 1
        elif estado == 'respetado_manual':
            contadores['items_respetado_manual'] += 1
            if len(saltados) < 50:
                saltados.append({
                    'item_id': it.id,
                    'descripcion': (it.descripcion or '')[:120],
                    'razon': 'Respetado: el ítem ya tiene composiciones manuales.',
                })
        elif estado == 'cantidad_invalida':
            contadores['items_cantidad_invalida'] += 1
            if len(saltados) < 50:
                saltados.append({
                    'item_id': it.id,
                    'descripcion': (it.descripcion or '')[:120],
                    'razon': 'Cantidad del ítem es 0 o negativa.',
                })
        elif estado == 'global_no_desglosa':
            contadores['items_globales'] += 1
        elif estado == 'servicio_no_desglosa':
            contadores['items_servicio'] += 1
        elif estado == 'excluido':
            contadores['items_excluidos'] += 1

    # Advertencias contextuales
    if contadores['items_sin_regla'] > 0:
        advertencias.append(
            f'{contadores["items_sin_regla"]} ítems no tienen regla técnica detectada. '
            'Abrí "Analizar con IA" y aplicá el análisis antes de regenerar.'
        )
    if contadores['items_sin_coeficiente'] > 0:
        advertencias.append(
            f'{contadores["items_sin_coeficiente"]} ítems tienen regla técnica pero todavía no '
            'hay coeficiente cargado para esa regla en el YAML del producto.'
        )
    if contadores['items_respetado_manual'] > 0:
        advertencias.append(
            f'{contadores["items_respetado_manual"]} ítems se respetaron porque ya tenían '
            'composiciones manuales. Borralas antes si querés regenerar.'
        )

    return {
        'contadores': contadores,
        'saltados': saltados,
        'saltados_truncado': max(0,
            (contadores['items_sin_regla']
             + contadores['items_sin_coeficiente']
             + contadores['items_respetado_manual']
             + contadores['items_cantidad_invalida'])
            - len(saltados)
        ),
        'advertencias': advertencias,
        'yaml_version': yaml_metadatos().get('version'),
    }
