"""
Dashboard service — datos por rol
=================================================================
Provee los datos de cada uno de los 4 dashboards (admin / pm / tecnico /
operario) para el blueprint `bp_dashboards`.

Decisiones de diseño (ver auditoria de costos/estado):
- `costo_real` se RECALCULA fresco con la formula "rica" via
  services.obra_costos_service.calcular_costo_real() — NO se lee la columna
  obra.costo_real (que es inconsistente entre obras porque su valor depende
  de que accion la escribio ultima).
- `avance` usa obra.progreso (columna persistida, se refresca en cada cambio
  de tarea/etapa).
- `estado_operativo` se DERIVA (no existe como estado guardado): la columna
  obra.estado solo tiene planificacion/en_curso/pausada/finalizada/cancelada.
- "Obras que gestiona un PM/Tecnico" se infiere de AsignacionObra activa
  (la tabla obras no tiene columna de responsable/pm).

Las alertas se reutilizan de services.alertas_dashboard (ya calculan por org
y en timezone AR) — no se reinventan aca.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from extensions import db
from models.projects import (
    Obra,
    AsignacionObra,
    EtapaObra,
    TareaEtapa,
    TareaMiembro,
)
from services.obra_costos_service import calcular_costo_real


# ============================================================================
# Primitivas de calculo (reutilizadas por los 4 dashboards)
# ============================================================================

def estado_operativo(obra, costo_real) -> str:
    """Deriva el estado operativo de negocio.

    Precedencia (la primera que aplica gana):
      FINALIZADA / CANCELADA -> por columna obra.estado
      PARADA                 -> obra.estado == 'pausada'
      CRITICA                -> costo_real > presupuesto (sobrecosto)
      ATRASADA               -> fecha_fin_estimada pasada y avance < 100
      EN_CURSO               -> resto
    """
    estado = (obra.estado or '').lower()
    if estado == 'finalizada':
        return 'FINALIZADA'
    if estado == 'cancelada':
        return 'CANCELADA'
    if estado == 'pausada':
        return 'PARADA'

    presupuesto = Decimal(str(obra.presupuesto_total or 0))
    if presupuesto > 0 and Decimal(str(costo_real)) > presupuesto:
        return 'CRITICA'

    avance = obra.progreso or 0
    if obra.fecha_fin_estimada and date.today() > obra.fecha_fin_estimada and avance < 100:
        return 'ATRASADA'

    return 'EN_CURSO'


def resumen_obra(obra) -> dict:
    """Resumen de una obra con costo real FRESCO (formula rica) + estado operativo."""
    costo = calcular_costo_real(
        obra.id,
        incluir_mo_pagada_solo=True,        # MO pagada
        incluir_maquinaria=True,            # + maquinaria aprobada
        incluir_caja_b_confirmados_legacy=True,  # + caja B confirmada
    )
    presupuesto = Decimal(str(obra.presupuesto_total or 0))
    consumo_pct = float(costo / presupuesto * 100) if presupuesto > 0 else 0.0
    margen = presupuesto - costo

    return {
        'id': obra.id,
        'nombre': obra.nombre,
        'cliente': obra.cliente,
        'fecha_fin_estimada': obra.fecha_fin_estimada,
        'presupuesto': float(presupuesto),
        'costo_real': float(costo),
        'margen': float(margen),
        'avance': obra.progreso or 0,
        'consumo_pct': round(consumo_pct, 1),
        'estado': obra.estado,
        'estado_operativo': estado_operativo(obra, costo),
    }


def resumen_financiero(resumenes) -> dict:
    """Totales financieros a partir de una lista de resumen_obra()."""
    tot_pres = sum(r['presupuesto'] for r in resumenes)
    tot_costo = sum(r['costo_real'] for r in resumenes)
    margen = tot_pres - tot_costo
    return {
        'presupuesto_total': tot_pres,
        'gastado_total': tot_costo,
        'margen': margen,
        'margen_pct': round(margen / tot_pres * 100, 1) if tot_pres > 0 else 0.0,
        'ejecucion_pct': round(tot_costo / tot_pres * 100, 1) if tot_pres > 0 else 0.0,
        'cantidad_obras': len(resumenes),
    }


# ============================================================================
# Selectores de obras por rol
# ============================================================================

def _obras_activas_org(org_id):
    """Todas las obras vivas de la organizacion (para admin)."""
    return (
        Obra.query_active()
        .filter(
            Obra.organizacion_id == org_id,
            Obra.estado.notin_(['cancelada']),
        )
        .order_by(Obra.fecha_fin_estimada)
        .all()
    )


# Roles de AsignacionObra que implican GESTIONAR la obra (no solo trabajar en
# una tarea). La tabla obras no tiene columna de PM/responsable, asi que la
# gestion se infiere del rol_en_obra de la asignacion.
ROLES_GESTION = {'pm', 'project_manager', 'jefe_obra', 'supervisor', 'encargado_obra'}


def obras_asignadas(user, roles=None):
    """Obras donde el usuario tiene una asignacion activa.

    Args:
        roles: si se pasa un set de rol_en_obra, filtra a esas asignaciones
               (p.ej. ROLES_GESTION para el dashboard de PM). Si es None,
               devuelve cualquier obra donde el usuario este asignado
               (p.ej. el dashboard de Tecnico: "obras en las que esta").
    """
    q = (
        Obra.query_active()
        .join(AsignacionObra, AsignacionObra.obra_id == Obra.id)
        .filter(
            AsignacionObra.usuario_id == user.id,
            AsignacionObra.activo.is_(True),
            Obra.organizacion_id == user.organizacion_id,
            Obra.estado.notin_(['cancelada']),
        )
    )
    if roles:
        q = q.filter(AsignacionObra.rol_en_obra.in_(list(roles)))
    return q.distinct().all()


# ============================================================================
# Bloques secundarios (entregas, equipo, stock, tareas, material)
# ============================================================================

def _entregas_proximas(obra_ids, limite=10):
    """OC pendientes de recepcion (vencidas o proximas) para un set de obras."""
    if not obra_ids:
        return []
    from models.inventory import OrdenCompra

    hoy = date.today()
    ocs = (
        OrdenCompra.query
        .filter(
            OrdenCompra.obra_id.in_(obra_ids),
            OrdenCompra.estado.in_(['emitida', 'recibida_parcial']),
            OrdenCompra.fecha_entrega_estimada.isnot(None),
        )
        .order_by(OrdenCompra.fecha_entrega_estimada)
        .limit(limite)
        .all()
    )
    out = []
    for oc in ocs:
        dias = (oc.fecha_entrega_estimada - hoy).days
        out.append({
            'numero': oc.numero,
            'proveedor': oc.proveedor,
            'obra': oc.obra.nombre if oc.obra else '—',
            'fecha': oc.fecha_entrega_estimada,
            'dias': dias,
            'vencida': dias < 0,
            'url': f'/ordenes-compra/{oc.id}/recepcion',
        })
    return out


def _equipo_de_obras(obra_ids):
    """Personal con asignacion activa en un set de obras (para PM)."""
    if not obra_ids:
        return []
    from models.core import Usuario

    filas = (
        db.session.query(AsignacionObra, Usuario, Obra)
        .join(Usuario, Usuario.id == AsignacionObra.usuario_id)
        .join(Obra, Obra.id == AsignacionObra.obra_id)
        .filter(
            AsignacionObra.obra_id.in_(obra_ids),
            AsignacionObra.activo.is_(True),
        )
        .all()
    )
    equipo = []
    for asig, usuario, obra in filas:
        nombre = getattr(usuario, 'nombre_completo', None) or usuario.nombre or usuario.email
        equipo.append({
            'usuario': nombre,
            'rol_en_obra': asig.rol_en_obra,
            'obra': obra.nombre,
        })
    return equipo


def _stock_disponible(obra_ids, limite=50):
    """Stock con cantidad disponible en las obras del usuario (para Tecnico)."""
    if not obra_ids:
        return []
    from models.inventory import StockObra

    filas = (
        StockObra.query
        .filter(
            StockObra.obra_id.in_(obra_ids),
            StockObra.cantidad_disponible > 0,
        )
        .order_by(StockObra.cantidad_disponible.desc())
        .limit(limite)
        .all()
    )
    out = []
    for s in filas:
        item = s.item
        out.append({
            'item': item.nombre if item else f'Item {s.item_inventario_id}',
            'unidad': item.unidad if item else '',
            'cantidad': float(s.cantidad_disponible or 0),
            'obra_id': s.obra_id,
        })
    return out


def _mis_tareas(user):
    """Tareas pendientes/en curso donde el usuario es responsable o miembro."""
    filtro_estado = TareaEtapa.estado.in_(['pendiente', 'en_curso'])

    q_resp = (
        db.session.query(TareaEtapa, Obra.id, Obra.nombre)
        .join(EtapaObra, EtapaObra.id == TareaEtapa.etapa_id)
        .join(Obra, Obra.id == EtapaObra.obra_id)
        .filter(
            TareaEtapa.responsable_id == user.id,
            Obra.organizacion_id == user.organizacion_id,
            filtro_estado,
        )
    )
    q_miem = (
        db.session.query(TareaEtapa, Obra.id, Obra.nombre)
        .join(TareaMiembro, TareaMiembro.tarea_id == TareaEtapa.id)
        .join(EtapaObra, EtapaObra.id == TareaEtapa.etapa_id)
        .join(Obra, Obra.id == EtapaObra.obra_id)
        .filter(
            TareaMiembro.user_id == user.id,
            Obra.organizacion_id == user.organizacion_id,
            filtro_estado,
        )
    )

    hoy = date.today()
    vistas = {}
    for tarea, obra_id, obra_nombre in list(q_resp.all()) + list(q_miem.all()):
        if tarea.id in vistas:
            continue
        vistas[tarea.id] = {
            'id': tarea.id,
            'nombre': tarea.nombre,
            'estado': tarea.estado,
            'fecha_fin_plan': tarea.fecha_fin_plan,
            'atrasada': bool(tarea.fecha_fin_plan and hoy > tarea.fecha_fin_plan),
            'obra_id': obra_id,
            'obra': obra_nombre,
        }
    tareas = list(vistas.values())
    # Atrasadas primero, luego por fecha de fin planificada
    tareas.sort(key=lambda t: (not t['atrasada'], t['fecha_fin_plan'] or date.max))
    return tareas


def _material_para_obras(obra_ids, limite=10):
    """Remitos recientes (material que llego) para las obras del operario."""
    if not obra_ids:
        return []
    from models.inventory import Remito

    remitos = (
        Remito.query
        .filter(Remito.obra_id.in_(obra_ids))
        .order_by(Remito.fecha.desc())
        .limit(limite)
        .all()
    )
    out = []
    for r in remitos:
        out.append({
            'numero': r.numero_remito,
            'proveedor': r.proveedor,
            'fecha': r.fecha,
            'estado': r.estado,
            'obra_id': r.obra_id,
        })
    return out


# ============================================================================
# Entradas publicas — una por dashboard
# ============================================================================

def data_admin(org_id) -> dict:
    """1) Alertas criticas (todas) 2) Obras activas 3) Entregas 4) Financiero."""
    from services.alertas_dashboard import obtener_alertas_para_dashboard

    obras = _obras_activas_org(org_id)
    resumenes = [resumen_obra(o) for o in obras]
    return {
        'alertas': obtener_alertas_para_dashboard(org_id, limite=12),
        'obras': resumenes,
        'entregas': _entregas_proximas([o.id for o in obras], limite=10),
        'financiero': resumen_financiero(resumenes),
    }


def data_pm(user) -> dict:
    """1) Alertas de SUS obras 2) Obras que gestiona 3) Entregas 4) Equipo."""
    obras = obras_asignadas(user, roles=ROLES_GESTION)
    resumenes = [resumen_obra(o) for o in obras]
    obra_ids = [o.id for o in obras]
    entregas = _entregas_proximas(obra_ids, limite=10)

    # Alertas acotadas a sus obras, derivadas del estado operativo + entregas.
    alertas = []
    for r in resumenes:
        if r['estado_operativo'] == 'CRITICA':
            alertas.append({
                'severidad': 'critica', 'color': 'danger', 'icono': 'fa-triangle-exclamation',
                'titulo': f"Sobrecosto: {r['nombre']}",
                'detalle': f"Gastado {r['consumo_pct']}% del presupuesto",
                'url': f"/obras/{r['id']}",
            })
        elif r['estado_operativo'] == 'ATRASADA':
            alertas.append({
                'severidad': 'alta', 'color': 'warning', 'icono': 'fa-clock',
                'titulo': f"Obra atrasada: {r['nombre']}",
                'detalle': f"Venció {r['fecha_fin_estimada']}, avance {r['avance']}%",
                'url': f"/obras/{r['id']}",
            })
    for e in entregas:
        if e['vencida']:
            alertas.append({
                'severidad': 'critica', 'color': 'danger', 'icono': 'fa-truck',
                'titulo': f"Entrega vencida: {e['numero']}",
                'detalle': f"{e['proveedor']} → {e['obra']}",
                'url': e['url'],
            })
    orden = {'critica': 0, 'alta': 1, 'media': 2, 'baja': 3}
    alertas.sort(key=lambda a: orden.get(a['severidad'], 3))

    return {
        'alertas': alertas,
        'obras': resumenes,
        'entregas': entregas,
        'equipo': _equipo_de_obras(obra_ids),
        'financiero': resumen_financiero(resumenes),
    }


def data_tecnico(user) -> dict:
    """1) Obras en las que esta 2) Stock/inventario disponible."""
    obras = obras_asignadas(user)  # cualquier rol: "obras en las que esta"
    resumenes = [resumen_obra(o) for o in obras]
    return {
        'obras': resumenes,
        'stock': _stock_disponible([o.id for o in obras]),
    }


def data_operario(user) -> dict:
    """1) Mis tareas (pendientes/en curso) 2) Material (remitos) de esas obras."""
    tareas = _mis_tareas(user)
    obra_ids = list({t['obra_id'] for t in tareas if t['obra_id']})
    return {
        'tareas': tareas,
        'material': _material_para_obras(obra_ids, limite=10),
    }
