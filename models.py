from datetime import datetime, date
from flask_login import UserMixin
from app import db
import uuid


class Organizacion(db.Model):
    __tablename__ = 'organizaciones'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    token_invitacion = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    activa = db.Column(db.Boolean, default=True)
    
    # Relaciones
    usuarios = db.relationship('Usuario', back_populates='organizacion', lazy='dynamic')
    obras = db.relationship('Obra', back_populates='organizacion', lazy='dynamic')
    inventario = db.relationship('ItemInventario', back_populates='organizacion', lazy='dynamic')
    
    def __repr__(self):
        return f'<Organizacion {self.nombre}>'
    
    def regenerar_token(self):
        """Regenerar token de invitación"""
        self.token_invitacion = str(uuid.uuid4())
        db.session.commit()
    
    @property
    def total_usuarios(self):
        return self.usuarios.count()
    
    @property
    def administradores(self):
        return self.usuarios.filter_by(rol='administrador')
    
    @property
    def link_invitacion(self):
        from flask import url_for
        return url_for('auth.unirse_organizacion', token=self.token_invitacion, _external=True)


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    telefono = db.Column(db.String(20))
    password_hash = db.Column(db.String(256), nullable=True)  # Nullable para usuarios de Google
    rol = db.Column(db.String(20), nullable=False, default='operario')  # administrador, tecnico, operario
    activo = db.Column(db.Boolean, default=True)
    auth_provider = db.Column(db.String(20), nullable=False, default='manual')  # manual, google
    google_id = db.Column(db.String(100), nullable=True)  # ID de Google para usuarios OAuth
    profile_picture = db.Column(db.String(500), nullable=True)  # URL de imagen de perfil de Google
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    
    # Relaciones
    organizacion = db.relationship('Organizacion', back_populates='usuarios')
    obras_asignadas = db.relationship('AsignacionObra', back_populates='usuario', lazy='dynamic')
    registros_tiempo = db.relationship('RegistroTiempo', back_populates='usuario', lazy='dynamic')
    
    def __repr__(self):
        return f'<Usuario {self.nombre} {self.apellido}>'
    
    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"
    
    def puede_acceder_modulo(self, modulo):
        permisos = {
            'administrador': ['obras', 'presupuestos', 'equipos', 'inventario', 'reportes', 'asistente', 'cotizacion', 'documentos', 'seguridad'],
            'tecnico': ['obras', 'presupuestos', 'inventario', 'reportes', 'asistente', 'cotizacion', 'documentos', 'seguridad'],
            'operario': ['obras', 'inventario', 'asistente', 'documentos']
        }
        return modulo in permisos.get(self.rol, [])


class Obra(db.Model):
    __tablename__ = 'obras'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    direccion = db.Column(db.String(300))
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
    
    # Relaciones
    organizacion = db.relationship('Organizacion', back_populates='obras')
    etapas = db.relationship('EtapaObra', back_populates='obra', cascade='all, delete-orphan', lazy='dynamic')
    asignaciones = db.relationship('AsignacionObra', back_populates='obra', cascade='all, delete-orphan', lazy='dynamic')
    presupuestos = db.relationship('Presupuesto', back_populates='obra', lazy='dynamic')
    uso_inventario = db.relationship('UsoInventario', back_populates='obra', lazy='dynamic')
    
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
    
    # Relaciones
    obra = db.relationship('Obra', back_populates='etapas')
    tareas = db.relationship('TareaEtapa', back_populates='etapa', cascade='all, delete-orphan', lazy='dynamic')
    
    def __repr__(self):
        return f'<EtapaObra {self.nombre}>'


class TareaEtapa(db.Model):
    __tablename__ = 'tareas_etapa'
    
    id = db.Column(db.Integer, primary_key=True)
    etapa_id = db.Column(db.Integer, db.ForeignKey('etapas_obra.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    fecha_inicio_estimada = db.Column(db.Date)
    fecha_fin_estimada = db.Column(db.Date)
    fecha_inicio_real = db.Column(db.Date)
    fecha_fin_real = db.Column(db.Date)
    estado = db.Column(db.String(20), default='pendiente')
    horas_estimadas = db.Column(db.Numeric(8, 2))
    horas_reales = db.Column(db.Numeric(8, 2), default=0)
    responsable_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    
    # Relaciones
    etapa = db.relationship('EtapaObra', back_populates='tareas')
    responsable = db.relationship('Usuario')
    registros_tiempo = db.relationship('RegistroTiempo', back_populates='tarea', lazy='dynamic')
    
    def __repr__(self):
        return f'<TareaEtapa {self.nombre}>'


class AsignacionObra(db.Model):
    __tablename__ = 'asignaciones_obra'
    
    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    rol_en_obra = db.Column(db.String(50), nullable=False)  # jefe_obra, supervisor, operario
    fecha_asignacion = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)
    
    # Relaciones
    obra = db.relationship('Obra', back_populates='asignaciones')
    usuario = db.relationship('Usuario', back_populates='obras_asignadas')
    
    def __repr__(self):
        return f'<AsignacionObra {self.usuario.nombre} en {self.obra.nombre}>'


class Presupuesto(db.Model):
    __tablename__ = 'presupuestos'
    
    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    numero = db.Column(db.String(50), unique=True, nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    estado = db.Column(db.String(20), default='borrador')  # borrador, enviado, aprobado, rechazado
    subtotal_materiales = db.Column(db.Numeric(15, 2), default=0)
    subtotal_mano_obra = db.Column(db.Numeric(15, 2), default=0)
    subtotal_equipos = db.Column(db.Numeric(15, 2), default=0)
    total_sin_iva = db.Column(db.Numeric(15, 2), default=0)
    iva_porcentaje = db.Column(db.Numeric(5, 2), default=21)
    total_con_iva = db.Column(db.Numeric(15, 2), default=0)
    observaciones = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    obra = db.relationship('Obra', back_populates='presupuestos')
    items = db.relationship('ItemPresupuesto', back_populates='presupuesto', cascade='all, delete-orphan', lazy='dynamic')
    
    def __repr__(self):
        return f'<Presupuesto {self.numero}>'
    
    def calcular_totales(self):
        self.subtotal_materiales = sum(item.total for item in self.items if item.tipo == 'material')
        self.subtotal_mano_obra = sum(item.total for item in self.items if item.tipo == 'mano_obra')
        self.subtotal_equipos = sum(item.total for item in self.items if item.tipo == 'equipo')
        self.total_sin_iva = self.subtotal_materiales + self.subtotal_mano_obra + self.subtotal_equipos
        self.total_con_iva = self.total_sin_iva * (1 + self.iva_porcentaje / 100)


class ItemPresupuesto(db.Model):
    __tablename__ = 'items_presupuesto'
    
    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # material, mano_obra, equipo
    descripcion = db.Column(db.String(300), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(15, 2), nullable=False)
    
    # Relaciones
    presupuesto = db.relationship('Presupuesto', back_populates='items')
    
    def __repr__(self):
        return f'<ItemPresupuesto {self.descripcion}>'


class CategoriaInventario(db.Model):
    __tablename__ = 'categorias_inventario'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    tipo = db.Column(db.String(20), nullable=False)  # material, herramienta, maquinaria
    
    # Relaciones
    items = db.relationship('ItemInventario', back_populates='categoria', lazy='dynamic')
    
    def __repr__(self):
        return f'<CategoriaInventario {self.nombre}>'


class ItemInventario(db.Model):
    __tablename__ = 'items_inventario'
    
    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias_inventario.id'), nullable=False)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    unidad = db.Column(db.String(20), nullable=False)
    stock_actual = db.Column(db.Numeric(10, 3), default=0)
    stock_minimo = db.Column(db.Numeric(10, 3), default=0)
    precio_promedio = db.Column(db.Numeric(10, 2), default=0)
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    
    # Relaciones
    categoria = db.relationship('CategoriaInventario', back_populates='items')
    organizacion = db.relationship('Organizacion', back_populates='inventario')
    movimientos = db.relationship('MovimientoInventario', back_populates='item', lazy='dynamic')
    usos = db.relationship('UsoInventario', back_populates='item', lazy='dynamic')
    
    def __repr__(self):
        return f'<ItemInventario {self.codigo} - {self.nombre}>'
    
    @property
    def necesita_reposicion(self):
        return self.stock_actual <= self.stock_minimo


class MovimientoInventario(db.Model):
    __tablename__ = 'movimientos_inventario'
    
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # entrada, salida, ajuste
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    precio_unitario = db.Column(db.Numeric(10, 2))
    motivo = db.Column(db.String(200))
    observaciones = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    item = db.relationship('ItemInventario', back_populates='movimientos')
    usuario = db.relationship('Usuario')
    
    def __repr__(self):
        return f'<MovimientoInventario {self.tipo} - {self.item.nombre}>'


class UsoInventario(db.Model):
    __tablename__ = 'uso_inventario'
    
    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=False)
    cantidad_usada = db.Column(db.Numeric(10, 3), nullable=False)
    fecha_uso = db.Column(db.Date, default=date.today)
    observaciones = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    # Relaciones
    obra = db.relationship('Obra', back_populates='uso_inventario')
    item = db.relationship('ItemInventario', back_populates='usos')
    usuario = db.relationship('Usuario')
    
    def __repr__(self):
        return f'<UsoInventario {self.obra.nombre} - {self.item.nombre}>'


class RegistroTiempo(db.Model):
    __tablename__ = 'registros_tiempo'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    tarea_id = db.Column(db.Integer, db.ForeignKey('tareas_etapa.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    horas_trabajadas = db.Column(db.Numeric(8, 2), nullable=False)
    descripcion = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    usuario = db.relationship('Usuario', back_populates='registros_tiempo')
    tarea = db.relationship('TareaEtapa', back_populates='registros_tiempo')
    
    def __repr__(self):
        return f'<RegistroTiempo {self.usuario.nombre} - {self.tarea.nombre}>'


# Nuevos modelos para configuración inteligente de proyectos
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
