"""
Modelos de Plantillas, Certificaciones y Configuraciones

Este módulo contiene los modelos para gestionar plantillas de proyectos,
etapas, tareas, configuraciones inteligentes y certificaciones de trabajo.
"""

from datetime import datetime, date
from decimal import Decimal
from extensions import db
import json


class PlantillaProyecto(db.Model):
    __tablename__ = 'plantillas_proyecto'

    id = db.Column(db.Integer, primary_key=True)
    tipo_obra = db.Column(db.String(100), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    duracion_base_dias = db.Column(db.Integer, default=30)
    metros_cuadrados_min = db.Column(db.Numeric(10, 2), default=0)
    metros_cuadrados_max = db.Column(db.Numeric(10, 2), default=999999)
    costo_base_m2 = db.Column(db.Numeric(10, 2), nullable=False)
    factor_complejidad = db.Column(db.Numeric(3, 2), default=1.0)
    activa = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    etapas_plantilla = db.relationship('EtapaPlantilla', back_populates='plantilla', cascade='all, delete-orphan')
    items_materiales = db.relationship('ItemMaterialPlantilla', back_populates='plantilla', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<PlantillaProyecto {self.tipo_obra}>'


class EtapaPlantilla(db.Model):
    __tablename__ = 'etapas_plantilla'

    id = db.Column(db.Integer, primary_key=True)
    plantilla_id = db.Column(db.Integer, db.ForeignKey('plantillas_proyecto.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    orden = db.Column(db.Integer, nullable=False)
    duracion_dias = db.Column(db.Integer, nullable=False)
    porcentaje_presupuesto = db.Column(db.Numeric(5, 2), default=0)
    es_critica = db.Column(db.Boolean, default=False)

    # Relaciones
    plantilla = db.relationship('PlantillaProyecto', back_populates='etapas_plantilla')
    tareas_plantilla = db.relationship('TareaPlantilla', back_populates='etapa_plantilla', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<EtapaPlantilla {self.nombre}>'


class TareaPlantilla(db.Model):
    __tablename__ = 'tareas_plantilla'

    id = db.Column(db.Integer, primary_key=True)
    etapa_plantilla_id = db.Column(db.Integer, db.ForeignKey('etapas_plantilla.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    orden = db.Column(db.Integer, nullable=False)
    duracion_horas = db.Column(db.Numeric(8, 2), nullable=False)
    requiere_especialista = db.Column(db.Boolean, default=False)
    tipo_especialista = db.Column(db.String(100))
    es_critica = db.Column(db.Boolean, default=False)

    # Relaciones
    etapa_plantilla = db.relationship('EtapaPlantilla', back_populates='tareas_plantilla')

    def __repr__(self):
        return f'<TareaPlantilla {self.nombre}>'


class ItemMaterialPlantilla(db.Model):
    __tablename__ = 'items_material_plantilla'

    id = db.Column(db.Integer, primary_key=True)
    plantilla_id = db.Column(db.Integer, db.ForeignKey('plantillas_proyecto.id'), nullable=False)
    categoria = db.Column(db.String(100), nullable=False)  # estructura, albañilería, instalaciones, etc.
    material = db.Column(db.String(200), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    cantidad_por_m2 = db.Column(db.Numeric(10, 4), nullable=False)
    precio_unitario_base = db.Column(db.Numeric(10, 2), nullable=False)
    es_critico = db.Column(db.Boolean, default=False)
    proveedor_sugerido = db.Column(db.String(200))
    notas = db.Column(db.Text)

    # Relaciones
    plantilla = db.relationship('PlantillaProyecto', back_populates='items_materiales')

    def __repr__(self):
        return f'<ItemMaterialPlantilla {self.material}>'


class ConfiguracionInteligente(db.Model):
    __tablename__ = 'configuraciones_inteligentes'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    plantilla_id = db.Column(db.Integer, db.ForeignKey('plantillas_proyecto.id'), nullable=False)
    factor_complejidad_aplicado = db.Column(db.Numeric(3, 2), nullable=False)
    ajustes_ubicacion = db.Column(db.JSON)  # JSON con ajustes específicos por ubicación
    recomendaciones_ia = db.Column(db.JSON)  # JSON con recomendaciones generadas
    fecha_configuracion = db.Column(db.DateTime, default=datetime.utcnow)
    configurado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Relaciones
    obra = db.relationship('Obra')
    plantilla = db.relationship('PlantillaProyecto')
    configurado_por = db.relationship('Usuario')

    def __repr__(self):
        return f'<ConfiguracionInteligente Obra-{self.obra_id}>'


class CertificacionAvance(db.Model):
    __tablename__ = 'certificaciones_avance'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    porcentaje_avance = db.Column(db.Numeric(5, 2), nullable=False)  # Porcentaje de avance certificado
    costo_certificado = db.Column(db.Numeric(15, 2), default=0)  # Costo asociado a este avance
    notas = db.Column(db.Text)  # Notas opcionales
    activa = db.Column(db.Boolean, default=True)  # Para poder desactivar certificaciones si es necesario
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    obra = db.relationship('Obra', back_populates='certificaciones')
    usuario = db.relationship('Usuario')  # Usuario que creó la certificación

    def __repr__(self):
        return f'<CertificacionAvance {self.porcentaje_avance}% - Obra {self.obra.nombre}>'

    @classmethod
    def validar_certificacion(cls, obra_id, nuevo_porcentaje):
        """Valida que la nueva certificación no exceda el 100% del progreso total"""
        from models import Obra
        obra = Obra.query.get(obra_id)
        if not obra:
            return False, "Obra no encontrada"

        # Calcular progreso actual de certificaciones activas
        progreso_certificaciones = sum(cert.porcentaje_avance for cert in obra.certificaciones.filter_by(activa=True))

        # Calcular progreso de tareas/etapas
        progreso_tareas = obra.calcular_progreso_automatico() - progreso_certificaciones

        # Verificar que el nuevo total no exceda 100%
        nuevo_total = progreso_tareas + progreso_certificaciones + nuevo_porcentaje

        if nuevo_total > 100:
            return False, f"El total de avance sería {nuevo_total}%, excede el 100% permitido"

        return True, "Certificación válida"


class WorkCertification(db.Model):
    __tablename__ = 'work_certifications'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False, index=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)
    periodo_desde = db.Column(db.Date)
    periodo_hasta = db.Column(db.Date)
    porcentaje_avance = db.Column(db.Numeric(7, 3), default=0)
    monto_certificado_ars = db.Column(db.Numeric(15, 2), default=0)
    monto_certificado_usd = db.Column(db.Numeric(15, 2), default=0)
    moneda_base = db.Column(db.String(3), default='ARS')
    tc_usd = db.Column(db.Numeric(12, 4))
    indice_cac = db.Column(db.Numeric(12, 4))
    estado = db.Column(db.String(20), default='borrador')
    notas = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    approved_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = db.Column(db.DateTime)

    obra = db.relationship('Obra', back_populates='work_certifications')
    organizacion = db.relationship('Organizacion')
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])
    approved_by = db.relationship('Usuario', foreign_keys=[approved_by_id])
    items = db.relationship('WorkCertificationItem', back_populates='certificacion', cascade='all, delete-orphan', lazy='dynamic')
    payments = db.relationship('WorkPayment', back_populates='certificacion', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_work_certifications_obra_estado', 'obra_id', 'estado'),
    )

    def marcar_aprobada(self, usuario):
        self.estado = 'aprobada'
        self.approved_by = usuario
        self.approved_at = datetime.utcnow()

    @property
    def porcentaje_pagado(self):
        total_pagado = Decimal('0')
        for payment in self.payments.filter_by(estado='confirmado'):
            total_pagado += payment.monto_equivalente_ars
        base = Decimal(str(self.monto_certificado_ars or 0))
        if base <= 0:
            return Decimal('0')
        return (total_pagado / base).quantize(Decimal('0.01'))


class WorkCertificationItem(db.Model):
    __tablename__ = 'work_certification_items'

    id = db.Column(db.Integer, primary_key=True)
    certificacion_id = db.Column(db.Integer, db.ForeignKey('work_certifications.id'), nullable=False, index=True)
    etapa_id = db.Column(db.Integer, db.ForeignKey('etapas_obra.id'))
    tarea_id = db.Column(db.Integer, db.ForeignKey('tareas_etapa.id'))
    porcentaje_aplicado = db.Column(db.Numeric(7, 3), default=0)
    monto_ars = db.Column(db.Numeric(15, 2), default=0)
    monto_usd = db.Column(db.Numeric(15, 2), default=0)
    fuente_avance = db.Column(db.String(20), default='manual')
    resumen_avance = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    certificacion = db.relationship('WorkCertification', back_populates='items')
    etapa = db.relationship('EtapaObra')
    tarea = db.relationship('TareaEtapa')

    def resumen_dict(self):
        if not self.resumen_avance:
            return {}
        try:
            return json.loads(self.resumen_avance)
        except Exception:
            return {}


class WorkPayment(db.Model):
    __tablename__ = 'work_payments'

    id = db.Column(db.Integer, primary_key=True)
    certificacion_id = db.Column(db.Integer, db.ForeignKey('work_certifications.id'))
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False, index=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)
    operario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    metodo_pago = db.Column(db.String(30), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    monto = db.Column(db.Numeric(15, 2), nullable=False)
    tc_usd_pago = db.Column(db.Numeric(12, 4))
    fecha_pago = db.Column(db.Date, default=date.today)
    comprobante_url = db.Column(db.String(500))
    notas = db.Column(db.Text)
    estado = db.Column(db.String(20), default='pendiente')
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    certificacion = db.relationship('WorkCertification', back_populates='payments')
    obra = db.relationship('Obra', back_populates='work_payments')
    organizacion = db.relationship('Organizacion')
    operario = db.relationship('Usuario', foreign_keys=[operario_id])
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])

    __table_args__ = (
        db.Index('ix_work_payments_certificacion', 'certificacion_id'),
        db.Index('ix_work_payments_estado', 'estado'),
    )

    @property
    def monto_equivalente_ars(self):
        monto = Decimal(str(self.monto or 0))
        if self.moneda == 'ARS' or not self.tc_usd_pago:
            return monto
        return monto * Decimal(str(self.tc_usd_pago))

    @property
    def monto_equivalente_usd(self):
        monto = Decimal(str(self.monto or 0))
        if self.moneda == 'USD' or not self.tc_usd_pago or Decimal(str(self.tc_usd_pago)) == 0:
            return monto
        return monto / Decimal(str(self.tc_usd_pago))


# ============================================================
# LIQUIDACIÓN MANO DE OBRA
# ============================================================

class LiquidacionMO(db.Model):
    """Liquidación de mano de obra para un período."""
    __tablename__ = 'liquidaciones_mo'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    periodo_desde = db.Column(db.Date, nullable=False)
    periodo_hasta = db.Column(db.Date, nullable=False)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente / parcial / pagado
    notas = db.Column(db.Text)
    monto_total = db.Column(db.Numeric(15, 2), default=0)
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    obra = db.relationship('Obra', backref=db.backref('liquidaciones_mo', lazy='dynamic'))
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])
    items = db.relationship('LiquidacionMOItem', back_populates='liquidacion',
                            cascade='all, delete-orphan', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_liq_mo_obra', 'obra_id'),
        db.Index('ix_liq_mo_estado', 'estado'),
    )

    @property
    def items_pendientes(self):
        return self.items.filter_by(estado='pendiente').count()

    @property
    def items_pagados(self):
        return self.items.filter_by(estado='pagado').count()

    def recalcular_estado(self):
        """Actualiza estado basado en items."""
        total = self.items.count()
        pagados = self.items_pagados
        if total == 0:
            self.estado = 'pendiente'
        elif pagados == total:
            self.estado = 'pagado'
        elif pagados > 0:
            self.estado = 'parcial'
        else:
            self.estado = 'pendiente'

    def recalcular_total(self):
        """Recalcula monto_total sumando items."""
        total = sum(Decimal(str(item.monto or 0)) for item in self.items.all())
        self.monto_total = total


class LiquidacionMOItem(db.Model):
    """Item de liquidación: un operario dentro de una liquidación."""
    __tablename__ = 'liquidaciones_mo_items'

    id = db.Column(db.Integer, primary_key=True)
    liquidacion_id = db.Column(db.Integer, db.ForeignKey('liquidaciones_mo.id'), nullable=False)
    operario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Horas calculadas (informativas, no editables directamente)
    horas_avance = db.Column(db.Numeric(8, 2), default=0)      # Horas de avances registrados
    horas_fichadas = db.Column(db.Numeric(8, 2), default=0)    # Horas de fichadas (ingreso/egreso)

    # Datos de liquidación (editables por el admin)
    horas_liquidadas = db.Column(db.Numeric(8, 2), default=0)  # Horas que se pagan
    tarifa_hora = db.Column(db.Numeric(12, 2), default=0)      # $/hora
    monto = db.Column(db.Numeric(15, 2), default=0)            # Monto final a pagar

    # Trazabilidad de modalidad: medida | hora | fichada (se cachea al liquidar)
    modalidad_pago = db.Column(db.String(20))
    cantidad_liquidada = db.Column(db.Numeric(12, 3), default=0)  # Cantidad pagada (para 'medida')
    unidad_liquidada = db.Column(db.String(10))                   # 'm2', 'h', etc.

    # Pago
    estado = db.Column(db.String(20), default='pendiente')  # pendiente / pagado
    metodo_pago = db.Column(db.String(30))                   # transferencia / efectivo
    fecha_pago = db.Column(db.Date)
    comprobante_url = db.Column(db.String(500))
    pagado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    pagado_at = db.Column(db.DateTime)

    notas = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    liquidacion = db.relationship('LiquidacionMO', back_populates='items')
    operario = db.relationship('Usuario', foreign_keys=[operario_id])
    pagado_por = db.relationship('Usuario', foreign_keys=[pagado_por_id])

    __table_args__ = (
        db.Index('ix_liq_mo_item_liq', 'liquidacion_id'),
        db.Index('ix_liq_mo_item_op', 'operario_id'),
        db.Index('ix_liq_mo_item_estado', 'estado'),
    )


# ============================================================
# CAJA - Transferencias oficina <-> obra
# ============================================================

class MovimientoCaja(db.Model):
    """Movimiento de caja: transferencias de dinero entre oficina y obras."""
    __tablename__ = 'movimientos_caja'
    __table_args__ = (
        db.UniqueConstraint('organizacion_id', 'numero', name='uq_mv_caja_org_numero'),
    )

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), nullable=False)  # MV-2026-0001
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)

    # Tipo: transferencia_a_obra, devolucion_obra, pago_proveedor, gasto_obra
    tipo = db.Column(db.String(20), nullable=False)

    monto = db.Column(db.Numeric(15, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    concepto = db.Column(db.String(300))
    referencia = db.Column(db.String(100))  # Nro transferencia/recibo

    orden_compra_id = db.Column(db.Integer, db.ForeignKey('ordenes_compra.id'), nullable=True)

    fecha_movimiento = db.Column(db.Date, nullable=False)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, confirmado, anulado
    comprobante_url = db.Column(db.String(500))

    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    confirmado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    fecha_confirmacion = db.Column(db.DateTime)
    notas = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion')
    obra = db.relationship('Obra', backref='movimientos_caja')
    orden_compra = db.relationship('OrdenCompra')
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])
    confirmado_por = db.relationship('Usuario', foreign_keys=[confirmado_por_id])

    @classmethod
    def generar_numero(cls, organizacion_id=None):
        """Genera numero unico GLOBAL para evitar colision con unique constraint."""
        year = datetime.utcnow().year
        prefix = f'MV-{year}-'
        todos = cls.query.filter(cls.numero.like(f'{prefix}%')).all()
        max_num = 0
        for r in todos:
            try:
                num = int(r.numero.replace(prefix, ''))
                if num > max_num:
                    max_num = num
            except (ValueError, AttributeError):
                continue
        return f'{prefix}{str(max_num + 1).zfill(4)}'

    @property
    def tipo_display(self):
        tipos = {
            'transferencia_a_obra': 'Transferencia a Obra',
            'devolucion_obra': 'Devolucion de Obra',
            'pago_proveedor': 'Pago a Proveedor',
            'gasto_obra': 'Gasto de Obra',
        }
        return tipos.get(self.tipo, self.tipo)

    @property
    def tipo_color(self):
        colores = {
            'transferencia_a_obra': 'success',
            'devolucion_obra': 'warning',
            'pago_proveedor': 'primary',
            'gasto_obra': 'danger',
        }
        return colores.get(self.tipo, 'secondary')

    @property
    def tipo_icono(self):
        iconos = {
            'transferencia_a_obra': 'fa-arrow-right',
            'devolucion_obra': 'fa-arrow-left',
            'pago_proveedor': 'fa-store',
            'gasto_obra': 'fa-receipt',
        }
        return iconos.get(self.tipo, 'fa-exchange-alt')

    @property
    def es_ingreso_obra(self):
        return self.tipo == 'transferencia_a_obra'

    @property
    def es_egreso_obra(self):
        return self.tipo in ('devolucion_obra', 'pago_proveedor', 'gasto_obra')

    @property
    def estado_display(self):
        estados = {
            'pendiente': 'Pendiente',
            'confirmado': 'Confirmado',
            'anulado': 'Anulado',
        }
        return estados.get(self.estado, self.estado)

    @property
    def estado_color(self):
        colores = {
            'pendiente': 'warning',
            'confirmado': 'success',
            'anulado': 'secondary',
        }
        return colores.get(self.estado, 'secondary')
