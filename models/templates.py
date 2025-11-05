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
