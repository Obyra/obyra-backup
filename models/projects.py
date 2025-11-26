"""Modelos de Proyectos y Obras"""
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from extensions import db
from sqlalchemy import func


class Obra(db.Model):
    __tablename__ = 'obras'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    direccion = db.Column(db.String(300))
    direccion_normalizada = db.Column(db.String(300))
    latitud = db.Column(db.Numeric(10, 8))  # Para geolocalización en mapa
    longitud = db.Column(db.Numeric(11, 8))  # Para geolocalización en mapa
    geocode_place_id = db.Column(db.String(120))
    geocode_provider = db.Column(db.String(50))
    geocode_status = db.Column(db.String(20), default='pending')
    geocode_raw = db.Column(db.Text)
    geocode_actualizado = db.Column(db.DateTime)
    cliente = db.Column(db.String(200), nullable=False)
    telefono_cliente = db.Column(db.String(20))
    email_cliente = db.Column(db.String(120))
    fecha_inicio = db.Column(db.Date)
    fecha_fin_estimada = db.Column(db.Date)
    fecha_fin_real = db.Column(db.Date)
    estado = db.Column(db.String(20), default='planificacion')  # planificacion, en_curso, pausada, finalizada, cancelada
    presupuesto_total = db.Column(db.Numeric(15, 2), default=0)
    costo_real = db.Column(db.Numeric(15, 2), default=0)
    progreso = db.Column(db.Integer, default=0)  # Porcentaje de avance
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)  # Nuevo: relación con tabla clientes

    # Datos de cliente adicionales (según especificaciones) - LEGACY, mantener por compatibilidad
    cliente_nombre = db.Column(db.String(120))
    cliente_email = db.Column(db.String(120))
    cliente_telefono = db.Column(db.String(50))

    # Ubicación detallada
    ciudad = db.Column(db.String(100))
    provincia = db.Column(db.String(100))
    pais = db.Column(db.String(100))
    codigo_postal = db.Column(db.String(20))
    referencia = db.Column(db.String(200))   # piso, entrecalles, etc.

    # Notas adicionales
    notas = db.Column(db.Text)

    # Relaciones
    organizacion = db.relationship('Organizacion', back_populates='obras')
    cliente_rel = db.relationship('Cliente', back_populates='obras')  # Nuevo: relación con Cliente
    etapas = db.relationship('EtapaObra', back_populates='obra', cascade='all, delete-orphan', lazy='dynamic')
    asignaciones = db.relationship('AsignacionObra', back_populates='obra', cascade='all, delete-orphan', lazy='dynamic')
    presupuestos = db.relationship('Presupuesto', back_populates='obra', lazy='dynamic')
    uso_inventario = db.relationship('UsoInventario', back_populates='obra', lazy='dynamic')
    certificaciones = db.relationship('CertificacionAvance', back_populates='obra', cascade='all, delete-orphan', lazy='dynamic')
    work_certifications = db.relationship('WorkCertification', back_populates='obra', cascade='all, delete-orphan', lazy='dynamic')
    work_payments = db.relationship('WorkPayment', back_populates='obra', cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<Obra {self.nombre}>'

    @property
    def dias_transcurridos(self):
        if self.fecha_inicio:
            return (date.today() - self.fecha_inicio).days
        return 0

    @property
    def dias_restantes(self):
        if self.fecha_fin_estimada:
            return (self.fecha_fin_estimada - date.today()).days
        return None

    def calcular_progreso_automatico(self):
        """
        Calcula el progreso automático basado en mediciones por etapa.
        Fórmula: (metros realizados / metros totales) * 100 por cada etapa
        """
        from decimal import Decimal, ROUND_HALF_UP

        total_etapas = self.etapas.count()
        if total_etapas == 0:
            return 0

        progreso_etapas = Decimal('0')
        total_planificado_obra = Decimal('0')
        total_ejecutado_obra = Decimal('0')

        for etapa in self.etapas:
            # Prioridad 1: Usar mediciones de la etapa si están definidas
            if etapa.cantidad_total_planificada and float(etapa.cantidad_total_planificada) > 0:
                # Calcular avance por medición para esta etapa
                etapa.calcular_avance_por_medicion()

                total_planificado_obra += Decimal(str(etapa.cantidad_total_planificada))
                total_ejecutado_obra += Decimal(str(etapa.cantidad_total_ejecutada or 0))

                # Contribución ponderada de esta etapa al progreso total
                porcentaje_etapa = Decimal(str(etapa.porcentaje_avance_medicion)) / Decimal(str(total_etapas))
                progreso_etapas += porcentaje_etapa

            # Prioridad 2: Fallback a tareas completadas
            else:
                total_tareas = etapa.tareas.count()
                if total_tareas > 0:
                    tareas_completadas = etapa.tareas.filter_by(estado='completada').count()
                    porcentaje_etapa = (Decimal(str(tareas_completadas)) / Decimal(str(total_tareas))) * (Decimal('100') / Decimal(str(total_etapas)))
                    progreso_etapas += porcentaje_etapa
                elif etapa.estado == 'finalizada':
                    progreso_etapas += (Decimal('100') / Decimal(str(total_etapas)))

        # Agregar progreso de certificaciones - convertir a Decimal
        progreso_certificaciones = Decimal('0')
        for cert in self.certificaciones.filter_by(activa=True):
            if cert.porcentaje_avance:
                progreso_certificaciones += Decimal(str(cert.porcentaje_avance))

        # El progreso total no puede exceder 100%
        progreso_total = min(Decimal('100'), progreso_etapas + progreso_certificaciones)

        # Actualizar el progreso en la base de datos - convertir a int
        self.progreso = int(progreso_total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        return self.progreso

    @property
    def porcentaje_presupuesto_ejecutado(self):
        """Calcula el porcentaje del presupuesto ejecutado"""
        from decimal import Decimal
        if self.presupuesto_total and self.presupuesto_total > 0:
            presupuesto = Decimal(str(self.presupuesto_total)) if not isinstance(self.presupuesto_total, Decimal) else self.presupuesto_total
            costo = Decimal(str(self.costo_real)) if not isinstance(self.costo_real, Decimal) else self.costo_real
            return float((costo / presupuesto) * Decimal('100'))
        return 0

    def puede_ser_pausada_por(self, usuario):
        """Verifica si un usuario puede pausar esta obra"""
        return (usuario.rol == 'administrador' or
                usuario.puede_pausar_obras or
                usuario.organizacion_id == self.organizacion_id)


class EtapaObra(db.Model):
    __tablename__ = 'etapas_obra'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    orden = db.Column(db.Integer, nullable=False)
    fecha_inicio_estimada = db.Column(db.Date)
    fecha_fin_estimada = db.Column(db.Date)
    fecha_inicio_real = db.Column(db.Date)
    fecha_fin_real = db.Column(db.Date)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, en_curso, finalizada
    progreso = db.Column(db.Integer, default=0)

    # Campos de medición por etapa
    unidad_medida = db.Column(db.String(10), default='m2')  # m2, m3, ml, u, hrs
    cantidad_total_planificada = db.Column(db.Numeric(15, 3), default=0)  # Total a ejecutar
    cantidad_total_ejecutada = db.Column(db.Numeric(15, 3), default=0)  # Total ejecutado
    porcentaje_avance_medicion = db.Column(db.Integer, default=0)  # Avance por medición (0-100)

    # Relaciones
    obra = db.relationship('Obra', back_populates='etapas')
    tareas = db.relationship('TareaEtapa', back_populates='etapa', cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<EtapaObra {self.nombre}>'

    def calcular_avance_por_medicion(self):
        """Calcula avance como: (cantidad_ejecutada / cantidad_planificada) * 100"""
        if self.cantidad_total_planificada and float(self.cantidad_total_planificada) > 0:
            avance = (float(self.cantidad_total_ejecutada or 0) / float(self.cantidad_total_planificada)) * 100
            self.porcentaje_avance_medicion = min(100, int(avance))
            self.progreso = self.porcentaje_avance_medicion  # Sincronizar con progreso general
        else:
            self.porcentaje_avance_medicion = 0
        return self.porcentaje_avance_medicion

    def registrar_avance_medicion(self, cantidad_ejecutada):
        """Registra avance en metros/unidades y recalcula porcentaje"""
        self.cantidad_total_ejecutada = (self.cantidad_total_ejecutada or 0) + cantidad_ejecutada
        return self.calcular_avance_por_medicion()


class TareaEtapa(db.Model):
    __tablename__ = 'tareas_etapa'

    id = db.Column(db.Integer, primary_key=True)
    etapa_id = db.Column(db.Integer, db.ForeignKey('etapas_obra.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    fecha_inicio_estimada = db.Column(db.Date)
    fecha_fin_estimada = db.Column(db.Date)
    fecha_inicio_real = db.Column(db.DateTime)  # Cambiado a DateTime para timestamp
    fecha_fin_real = db.Column(db.DateTime)    # Cambiado a DateTime para timestamp
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, en_curso, completada, cancelada
    horas_estimadas = db.Column(db.Numeric(8, 2))
    horas_reales = db.Column(db.Numeric(8, 2), default=0)
    porcentaje_avance = db.Column(db.Numeric(5, 2), default=0)  # Para control granular del avance
    responsable_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    fecha_inicio_plan = db.Column(db.Date)  # Fecha planificada de inicio
    fecha_fin_plan = db.Column(db.Date)     # Fecha planificada de fin
    unidad = db.Column(db.String(10), default='un')       # 'm2','ml','u','m3','hrs'
    cantidad_planificada = db.Column(db.Numeric)
    objetivo = db.Column(db.Numeric, nullable=True)  # Physical target (e.g. 500 m2)
    rendimiento = db.Column(db.Numeric(8, 2), nullable=True)  # Optional: quantity per hour (e.g. 20 m2/h)

    # EVM fields (nuevas columnas para planificación y seguimiento)
    fecha_inicio = db.Column(db.Date)              # Fecha de inicio planificada
    fecha_fin = db.Column(db.Date)                 # Fecha de fin planificada
    presupuesto_mo = db.Column(db.Numeric)         # Presupuesto de mano de obra para EV/PV

    # Vínculo con presupuesto para certificaciones
    item_presupuesto_id = db.Column(db.Integer, db.ForeignKey('items_presupuesto.id'), nullable=True)

    # Relaciones
    etapa = db.relationship('EtapaObra', back_populates='tareas')
    miembros = db.relationship('TareaMiembro', back_populates='tarea', cascade='all, delete-orphan')
    avances = db.relationship('TareaAvance', back_populates='tarea', cascade='all, delete-orphan')
    adjuntos = db.relationship('TareaAdjunto', back_populates='tarea', cascade='all, delete-orphan')
    responsable = db.relationship('Usuario')
    registros_tiempo = db.relationship('RegistroTiempo', back_populates='tarea', lazy='dynamic')
    asignaciones = db.relationship('TareaResponsables', back_populates='tarea', lazy='dynamic', cascade='all, delete-orphan')
    item_presupuesto = db.relationship('ItemPresupuesto', foreign_keys=[item_presupuesto_id])

    # EVM relationships
    plan_semanal = db.relationship('TareaPlanSemanal', back_populates='tarea', cascade='all, delete-orphan')
    avance_semanal = db.relationship('TareaAvanceSemanal', back_populates='tarea', cascade='all, delete-orphan')

    @property
    def metrics(self):
        """Calcula métricas de la tarea"""
        return resumen_tarea(self)

    @property
    def pct_completado(self):
        """Calculate completion percentage based on actual vs planned quantities"""
        # Get total planned quantity from planning tables
        from sqlalchemy import func
        qty_plan_total = (db.session.query(func.sum(TareaPlanSemanal.qty_plan))
                         .filter(TareaPlanSemanal.tarea_id == self.id)
                         .scalar()) or 0

        if qty_plan_total <= 0:
            # Fallback to objetivo or cantidad_planificada if no EVM planning
            qty_plan_total = float(self.objetivo or self.cantidad_planificada or 0)
            if qty_plan_total <= 0:
                return 0

        # Get total actual quantity from approved advances
        qty_real_total = (db.session.query(func.sum(TareaAvance.cantidad_ingresada))
                         .filter(
                             TareaAvance.tarea_id == self.id,
                             TareaAvance.status == 'aprobado'
                         )
                         .scalar()) or 0

        # Calculate percentage with safe division
        return min(100.0, (float(qty_real_total) / float(qty_plan_total)) * 100.0)

    @property
    def cantidad_objetivo(self):
        """Alias for objetivo field to maintain backward compatibility"""
        return self.objetivo

    def __repr__(self):
        return f'<TareaEtapa {self.nombre}>'


class TareaMiembro(db.Model):
    """Usuarios asignados a una tarea que pueden reportar avances"""
    __tablename__ = "tarea_miembros"

    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey("tareas_etapa.id"), index=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), index=True, nullable=False)
    cuota_objetivo = db.Column(db.Numeric)

    # Relaciones
    tarea = db.relationship('TareaEtapa', back_populates='miembros')
    usuario = db.relationship('Usuario')

    # Constraint de unicidad
    __table_args__ = (db.UniqueConstraint('tarea_id', 'user_id', name='unique_tarea_miembro'),)

    def __repr__(self):
        return f'<TareaMiembro tarea_id={self.tarea_id} user_id={self.user_id}>'


class TareaAvance(db.Model):
    """Registro de avances en las tareas"""
    __tablename__ = "tarea_avances"

    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey("tareas_etapa.id"), index=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    fecha = db.Column(db.Date, default=date.today)
    cantidad = db.Column(db.Numeric, nullable=False)
    unidad = db.Column(db.String(10))
    horas = db.Column(db.Numeric(8, 2), nullable=True)  # Time worked (optional)
    notas = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Audit fields for unit conversion tracking
    cantidad_ingresada = db.Column(db.Numeric, nullable=True)  # Original quantity entered
    unidad_ingresada = db.Column(db.String(10), nullable=True)  # Original unit entered
    horas_trabajadas = db.Column(db.Numeric(8, 2), nullable=True)  # Hours worked on this progress

    # Campos de aprobación
    status = db.Column(db.String(12), default="pendiente")  # pendiente/aprobado/rechazado
    confirmed_by = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    confirmed_at = db.Column(db.DateTime)
    reject_reason = db.Column(db.Text)

    # Certificación
    certificado = db.Column(db.Boolean, default=False)  # Si ya fue incluido en una certificación
    certificacion_id = db.Column(db.Integer, db.ForeignKey('work_certifications.id'), nullable=True)

    # Relaciones
    tarea = db.relationship('TareaEtapa', back_populates='avances')
    usuario = db.relationship('Usuario', foreign_keys=[user_id])
    confirmado_por = db.relationship('Usuario', foreign_keys=[confirmed_by])
    adjuntos = db.relationship('TareaAdjunto', back_populates='avance', cascade='all, delete-orphan')
    fotos = db.relationship('TareaAvanceFoto', back_populates='avance', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<TareaAvance tarea_id={self.tarea_id} cantidad={self.cantidad}>'


class TareaAvanceFoto(db.Model):
    """Fotos de evidencia de avances de tareas"""
    __tablename__ = "tarea_avance_fotos"

    id = db.Column(db.Integer, primary_key=True)
    avance_id = db.Column(db.Integer, db.ForeignKey("tarea_avances.id", ondelete='CASCADE'), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)  # Relative path like "avances/123/uuid.jpg"
    mime_type = db.Column(db.String(64))
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    avance = db.relationship('TareaAvance', back_populates='fotos')

    def __repr__(self):
        return f'<TareaAvanceFoto avance_id={self.avance_id} path={self.file_path}>'


class TareaPlanSemanal(db.Model):
    """Weekly planning distribution for EVM (S-curve)"""
    __tablename__ = "tarea_plan_semanal"

    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey("tareas_etapa.id", ondelete='CASCADE'), nullable=False)
    semana = db.Column(db.Date, nullable=False)  # Monday of ISO week
    qty_plan = db.Column(db.Numeric, default=0)  # Planned quantity for this week
    pv_mo = db.Column(db.Numeric, default=0)     # Planned Value for labor this week

    # Relationships
    tarea = db.relationship('TareaEtapa', back_populates='plan_semanal')

    # Unique constraint
    __table_args__ = (db.UniqueConstraint('tarea_id', 'semana', name='unique_tarea_semana_plan'),)

    def __repr__(self):
        return f'<TareaPlanSemanal tarea_id={self.tarea_id} semana={self.semana} qty_plan={self.qty_plan}>'


class TareaAvanceSemanal(db.Model):
    """Weekly progress aggregation for EVM calculations"""
    __tablename__ = "tarea_avance_semanal"

    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey("tareas_etapa.id", ondelete='CASCADE'), nullable=False)
    semana = db.Column(db.Date, nullable=False)  # Monday of ISO week
    qty_real = db.Column(db.Numeric, default=0)  # Actual quantity completed this week
    ac_mo = db.Column(db.Numeric, default=0)     # Actual Cost for labor this week
    ev_mo = db.Column(db.Numeric, default=0)     # Earned Value this week (calculated)

    # Relationships
    tarea = db.relationship('TareaEtapa', back_populates='avance_semanal')

    # Unique constraint
    __table_args__ = (db.UniqueConstraint('tarea_id', 'semana', name='unique_tarea_semana_avance'),)

    def __repr__(self):
        return f'<TareaAvanceSemanal tarea_id={self.tarea_id} semana={self.semana} qty_real={self.qty_real}>'


class TareaAdjunto(db.Model):
    """Archivos adjuntos de tareas y avances"""
    __tablename__ = "tarea_adjuntos"

    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey("tareas_etapa.id"), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    path = db.Column(db.String(500), nullable=False)
    avance_id = db.Column(db.Integer, db.ForeignKey("tarea_avances.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    tarea = db.relationship('TareaEtapa', back_populates='adjuntos')
    usuario = db.relationship('Usuario')
    avance = db.relationship('TareaAvance', back_populates='adjuntos')

    def __repr__(self):
        return f'<TareaAdjunto tarea_id={self.tarea_id} path={self.path}>'


class TareaResponsables(db.Model):
    """Modelo para asignaciones múltiples de usuarios a tareas"""
    __tablename__ = 'tarea_responsables'

    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey('tareas_etapa.id'), index=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), index=True, nullable=False)
    cuota_planificada = db.Column(db.Numeric)  # opcional para futuras funcionalidades

    # Relaciones
    tarea = db.relationship('TareaEtapa', back_populates='asignaciones')
    usuario = db.relationship('Usuario')

    # Constraint de unicidad
    __table_args__ = (db.UniqueConstraint('tarea_id', 'user_id', name='unique_tarea_user'),)

    def __repr__(self):
        return f'<TareaResponsables tarea_id={self.tarea_id} user_id={self.user_id}>'


class AsignacionObra(db.Model):
    __tablename__ = 'asignaciones_obra'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    etapa_id = db.Column(db.Integer, db.ForeignKey('etapas_obra.id'), nullable=True)  # Asignación por etapa específica
    rol_en_obra = db.Column(db.String(50), nullable=False)  # jefe_obra, supervisor, operario
    fecha_asignacion = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)

    # Relaciones
    obra = db.relationship('Obra', back_populates='asignaciones')
    usuario = db.relationship('Usuario', back_populates='obras_asignadas')
    etapa = db.relationship('EtapaObra', backref='asignaciones')

    def __repr__(self):
        return f'<AsignacionObra {self.usuario.nombre} en {self.obra.nombre}>'


class ObraMiembro(db.Model):
    """Miembros específicos por obra para permisos granulares"""
    __tablename__ = 'obra_miembros'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id', ondelete='CASCADE'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    rol_en_obra = db.Column(db.String(30))
    etapa_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # Relaciones
    obra = db.relationship('Obra')
    usuario = db.relationship('Usuario', lazy='joined')

    # Constraint de unicidad
    __table_args__ = (db.UniqueConstraint('obra_id', 'usuario_id', name='uq_obra_usuario'),)

    def __repr__(self):
        return f'<ObraMiembro Obra:{self.obra_id} Usuario:{self.usuario_id}>'


def resumen_tarea(t):
    """Helper para calcular métricas de una tarea (solo suma aprobados)"""
    plan = float(t.cantidad_planificada or 0)
    ejec = float(
        db.session.query(db.func.coalesce(db.func.sum(TareaAvance.cantidad), 0))
        .filter(TareaAvance.tarea_id == t.id, TareaAvance.status == "aprobado")
        .scalar() or 0
    )
    pct = (ejec/plan*100.0) if plan>0 else 0.0
    restante = max(plan - ejec, 0.0)
    atrasada = bool(t.fecha_fin_plan and date.today() > t.fecha_fin_plan and restante > 0)
    return {"plan": plan, "ejec": ejec, "pct": pct, "restante": restante, "atrasada": atrasada}


def calcular_avance_tarea(tarea_id):
    """
    Calcula el % de avance y monto certificable de una tarea basado en cantidad completada.

    Returns:
        dict: {
            'porcentaje': float,
            'cantidad_completada': Decimal,
            'cantidad_total': Decimal,
            'costo_acordado': Decimal,
            'monto_certificable': Decimal,
            'unidad': str
        }
    """
    from decimal import Decimal

    tarea = TareaEtapa.query.get(tarea_id)
    if not tarea:
        return None

    # Sumar todas las cantidades reportadas en avances aprobados y NO certificados
    cantidad_completada = db.session.query(
        func.coalesce(func.sum(TareaAvance.cantidad), 0)
    ).filter(
        TareaAvance.tarea_id == tarea_id,
        TareaAvance.status == 'aprobado',
        TareaAvance.certificado == False
    ).scalar() or Decimal('0')

    cantidad_total = tarea.cantidad_planificada or Decimal('0')

    # Calcular porcentaje
    if cantidad_total > 0:
        porcentaje = (float(cantidad_completada) / float(cantidad_total)) * 100
        porcentaje = min(porcentaje, 100)  # Cap at 100%
    else:
        porcentaje = 0

    # Obtener costo acordado de mano de obra
    costo_acordado = Decimal('0')

    # Opción 1: Si tiene item_presupuesto vinculado
    if tarea.item_presupuesto_id and tarea.item_presupuesto:
        costo_acordado = tarea.item_presupuesto.subtotal_ars or Decimal('0')
    # Opción 2: Si tiene presupuesto_mo directo
    elif tarea.presupuesto_mo:
        costo_acordado = tarea.presupuesto_mo

    # Calcular monto certificable
    monto_certificable = (Decimal(str(porcentaje)) / Decimal('100')) * costo_acordado

    return {
        'porcentaje': round(porcentaje, 2),
        'cantidad_completada': cantidad_completada,
        'cantidad_total': cantidad_total,
        'costo_acordado': costo_acordado,
        'monto_certificable': monto_certificable,
        'unidad': tarea.unidad or 'un'
    }


def calcular_avance_etapa(etapa_id):
    """
    Calcula el % de avance de una etapa ponderado por costo de mano de obra de las tareas.

    Returns:
        dict: {
            'porcentaje': float,
            'costo_total': Decimal,
            'costo_completado': Decimal,
            'tareas_total': int,
            'tareas_completadas': int
        }
    """
    from decimal import Decimal

    etapa = EtapaObra.query.get(etapa_id)
    if not etapa:
        return None

    tareas = etapa.tareas.all()

    costo_total = Decimal('0')
    costo_completado = Decimal('0')
    tareas_completadas = 0

    for tarea in tareas:
        # Obtener costo acordado de mano de obra
        costo_tarea = Decimal('0')
        if tarea.item_presupuesto_id and tarea.item_presupuesto:
            costo_tarea = tarea.item_presupuesto.subtotal_ars or Decimal('0')
        elif tarea.presupuesto_mo:
            costo_tarea = tarea.presupuesto_mo

        costo_total += costo_tarea

        # Calcular avance de la tarea
        avance = calcular_avance_tarea(tarea.id)
        if avance:
            costo_completado += avance['monto_certificable']
            if avance['porcentaje'] >= 100:
                tareas_completadas += 1

    # Calcular porcentaje de la etapa
    if costo_total > 0:
        porcentaje_etapa = (float(costo_completado) / float(costo_total)) * 100
    else:
        porcentaje_etapa = 0

    return {
        'porcentaje': round(porcentaje_etapa, 2),
        'costo_total': costo_total,
        'costo_completado': costo_completado,
        'tareas_total': len(tareas),
        'tareas_completadas': tareas_completadas
    }
