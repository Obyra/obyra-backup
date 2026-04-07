"""
Servicio de Cierre Formal de Obra.

Encapsula toda la lógica del proceso de cierre:
1. Validar pre-condiciones (obra en curso, sin cierres activos previos)
2. Generar checklist con el estado actual de la obra
3. Crear cierre en estado borrador
4. Confirmar cierre → cambia obra a 'finalizada'
5. Anular cierre → vuelve obra a 'en_curso'
6. Crear acta de entrega vinculada al cierre
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from extensions import db
from models import CierreObra, ActaEntrega, Obra


class CierreObraError(Exception):
    """Error de validación o lógica del cierre."""
    pass


class CierreObraService:
    """Servicio de gestión del cierre formal de obras."""

    @staticmethod
    def get_cierre_activo(obra_id: int) -> Optional[CierreObra]:
        """Devuelve el cierre activo (borrador o cerrado) de una obra, si existe."""
        return CierreObra.query.filter(
            CierreObra.obra_id == obra_id,
            CierreObra.estado.in_(['borrador', 'cerrado'])
        ).order_by(CierreObra.id.desc()).first()

    @staticmethod
    def generar_checklist(obra: Obra) -> dict:
        """
        Genera el checklist con el estado actual de la obra.
        Cuenta tareas, etapas, certificaciones, materiales, etc.
        """
        from sqlalchemy import func
        from models import (
            EtapaObra, TareaEtapa, TareaAvance,
            WorkCertification, WorkPayment, UsoInventario
        )

        checklist = {
            'tareas': {'total': 0, 'completadas': 0, 'pendientes': 0, 'porcentaje': 0},
            'etapas': {'total': 0, 'completadas': 0},
            'certificaciones': {'total': 0, 'monto_total': 0},
            'pagos': {'total': 0, 'monto_total': 0},
            'materiales': {'consumos': 0},
            'avance_general': 0,
            'puede_cerrar': True,
            'advertencias': [],
        }

        try:
            # Etapas
            etapas = EtapaObra.query.filter_by(obra_id=obra.id).all()
            checklist['etapas']['total'] = len(etapas)
            checklist['etapas']['completadas'] = sum(
                1 for e in etapas if (e.porcentaje_avance or 0) >= 100
            )

            # Tareas
            tareas_query = TareaEtapa.query.join(EtapaObra).filter(
                EtapaObra.obra_id == obra.id
            )
            tareas = tareas_query.all()
            checklist['tareas']['total'] = len(tareas)
            checklist['tareas']['completadas'] = sum(
                1 for t in tareas if (t.porcentaje_avance or 0) >= 100
            )
            checklist['tareas']['pendientes'] = (
                checklist['tareas']['total'] - checklist['tareas']['completadas']
            )
            if checklist['tareas']['total']:
                checklist['tareas']['porcentaje'] = round(
                    100 * checklist['tareas']['completadas'] / checklist['tareas']['total'],
                    1
                )

            # Avance general (campo en obra o calculado)
            checklist['avance_general'] = float(obra.progreso or 0)

            # Certificaciones
            try:
                certs = WorkCertification.query.filter_by(obra_id=obra.id).all()
                checklist['certificaciones']['total'] = len(certs)
                checklist['certificaciones']['monto_total'] = float(
                    sum(c.monto_total or 0 for c in certs)
                )
            except Exception:
                pass

            # Pagos
            try:
                pagos = WorkPayment.query.filter_by(obra_id=obra.id).all()
                checklist['pagos']['total'] = len(pagos)
                checklist['pagos']['monto_total'] = float(
                    sum(p.monto or 0 for p in pagos)
                )
            except Exception:
                pass

            # Materiales consumidos
            try:
                checklist['materiales']['consumos'] = (
                    UsoInventario.query.filter_by(obra_id=obra.id).count()
                )
            except Exception:
                pass

            # Advertencias (no son bloqueantes, solo informativas)
            if checklist['tareas']['pendientes'] > 0:
                checklist['advertencias'].append(
                    f"Hay {checklist['tareas']['pendientes']} tareas pendientes"
                )
            if checklist['avance_general'] < 100:
                checklist['advertencias'].append(
                    f"Avance general en {checklist['avance_general']}% (no llegó a 100%)"
                )
            if checklist['certificaciones']['total'] == 0:
                checklist['advertencias'].append(
                    "No hay certificaciones registradas"
                )

        except Exception as e:
            checklist['error'] = str(e)

        return checklist

    @classmethod
    def iniciar_cierre(cls, obra_id: int, organizacion_id: int,
                       usuario_id: int, observaciones: str = '') -> CierreObra:
        """
        Inicia un proceso de cierre en estado borrador.
        Valida que la obra exista, pertenezca a la org y no tenga cierre activo.
        """
        obra = Obra.query.filter_by(
            id=obra_id, organizacion_id=organizacion_id
        ).first()
        if not obra:
            raise CierreObraError("La obra no existe o no pertenece a tu organización.")

        if obra.estado in ('finalizada', 'cancelada'):
            raise CierreObraError(
                f"La obra ya está en estado '{obra.estado}'. No se puede iniciar un cierre."
            )

        cierre_existente = cls.get_cierre_activo(obra_id)
        if cierre_existente:
            raise CierreObraError(
                f"Ya existe un cierre {cierre_existente.estado_display.lower()} para esta obra."
            )

        # Generar checklist al momento del inicio
        checklist = cls.generar_checklist(obra)

        # Snapshot financiero
        presupuesto_inicial = obra.presupuesto_total or 0

        cierre = CierreObra(
            obra_id=obra_id,
            organizacion_id=organizacion_id,
            estado='borrador',
            iniciado_por_id=usuario_id,
            observaciones=observaciones or '',
            presupuesto_inicial=presupuesto_inicial,
            monto_certificado=Decimal(str(checklist['certificaciones']['monto_total'])),
            monto_cobrado=Decimal(str(checklist['pagos']['monto_total'])),
        )
        cierre.set_checklist(checklist)

        db.session.add(cierre)
        db.session.commit()
        return cierre

    @classmethod
    def confirmar_cierre(cls, cierre_id: int, organizacion_id: int,
                          usuario_id: int) -> CierreObra:
        """
        Confirma el cierre. Cambia el estado de la obra a 'finalizada'.
        """
        cierre = CierreObra.query.filter_by(
            id=cierre_id, organizacion_id=organizacion_id
        ).first()
        if not cierre:
            raise CierreObraError("Cierre no encontrado.")

        if cierre.estado != 'borrador':
            raise CierreObraError(
                f"El cierre ya está en estado '{cierre.estado_display}'. "
                "Solo se pueden confirmar cierres en borrador."
            )

        # Cambiar estado del cierre
        cierre.estado = 'cerrado'
        cierre.fecha_cierre_definitivo = datetime.utcnow()
        cierre.cerrado_por_id = usuario_id

        # Cambiar estado de la obra
        obra = cierre.obra
        obra.estado = 'finalizada'
        obra.fecha_fin_real = datetime.utcnow().date()

        db.session.commit()
        return cierre

    @classmethod
    def anular_cierre(cls, cierre_id: int, organizacion_id: int,
                       usuario_id: int, motivo: str) -> CierreObra:
        """
        Anula un cierre. Si la obra estaba 'finalizada', vuelve a 'en_curso'.
        """
        cierre = CierreObra.query.filter_by(
            id=cierre_id, organizacion_id=organizacion_id
        ).first()
        if not cierre:
            raise CierreObraError("Cierre no encontrado.")

        if cierre.estado == 'anulado':
            raise CierreObraError("El cierre ya está anulado.")

        if not motivo or not motivo.strip():
            raise CierreObraError("Debe indicar el motivo de anulación.")

        cierre.estado = 'anulado'
        cierre.fecha_anulacion = datetime.utcnow()
        cierre.anulado_por_id = usuario_id
        cierre.motivo_anulacion = motivo.strip()

        # Si la obra estaba finalizada por este cierre, devolverla a en_curso
        obra = cierre.obra
        if obra.estado == 'finalizada':
            obra.estado = 'en_curso'

        db.session.commit()
        return cierre

    @classmethod
    def crear_acta(cls, cierre_id: int, organizacion_id: int, usuario_id: int,
                    datos: dict) -> ActaEntrega:
        """
        Crea un acta de entrega vinculada a un cierre.

        datos: dict con campos del acta:
            tipo, fecha_acta, recibido_por_nombre, recibido_por_dni,
            recibido_por_cargo, descripcion, observaciones_cliente,
            observaciones_internas, items_entregados, plazo_garantia_meses
        """
        cierre = CierreObra.query.filter_by(
            id=cierre_id, organizacion_id=organizacion_id
        ).first()
        if not cierre:
            raise CierreObraError("Cierre no encontrado.")

        if cierre.estado == 'anulado':
            raise CierreObraError("No se puede crear acta de un cierre anulado.")

        nombre = (datos.get('recibido_por_nombre') or '').strip()
        if not nombre:
            raise CierreObraError("El nombre de quien recibe es obligatorio.")

        from datetime import date
        fecha_acta_str = datos.get('fecha_acta')
        if isinstance(fecha_acta_str, str) and fecha_acta_str:
            try:
                fecha_acta = datetime.strptime(fecha_acta_str, '%Y-%m-%d').date()
            except ValueError:
                fecha_acta = date.today()
        else:
            fecha_acta = date.today()

        plazo_str = datos.get('plazo_garantia_meses')
        try:
            plazo = int(plazo_str) if plazo_str else None
        except (ValueError, TypeError):
            plazo = None

        acta = ActaEntrega(
            cierre_id=cierre.id,
            obra_id=cierre.obra_id,
            organizacion_id=organizacion_id,
            tipo=datos.get('tipo', 'definitiva'),
            fecha_acta=fecha_acta,
            recibido_por_nombre=nombre,
            recibido_por_dni=(datos.get('recibido_por_dni') or '').strip() or None,
            recibido_por_cargo=(datos.get('recibido_por_cargo') or '').strip() or None,
            descripcion=(datos.get('descripcion') or '').strip() or None,
            observaciones_cliente=(datos.get('observaciones_cliente') or '').strip() or None,
            observaciones_internas=(datos.get('observaciones_internas') or '').strip() or None,
            items_entregados=(datos.get('items_entregados') or '').strip() or None,
            plazo_garantia_meses=plazo,
            fecha_inicio_garantia=fecha_acta if plazo else None,
            creado_por_id=usuario_id,
        )

        db.session.add(acta)
        db.session.commit()
        return acta

    @classmethod
    def listar_cierres(cls, organizacion_id: int, estado: Optional[str] = None) -> list:
        """Lista cierres de una organización, opcionalmente filtrado por estado."""
        q = CierreObra.query.filter_by(organizacion_id=organizacion_id)
        if estado:
            q = q.filter_by(estado=estado)
        return q.order_by(CierreObra.fecha_inicio_cierre.desc()).all()
