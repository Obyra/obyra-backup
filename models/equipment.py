"""Modelos de Equipos y Mantenimiento"""

from datetime import datetime
from decimal import Decimal
from extensions import db
from sqlalchemy.orm import backref


class Equipment(db.Model):
    __tablename__ = 'equipment'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(100), nullable=False)  # hormigonera, guinche, martillo, etc.
    marca = db.Column(db.String(100))
    modelo = db.Column(db.String(100))
    nro_serie = db.Column(db.String(100))
    costo_hora = db.Column(db.Numeric(12, 2), default=0)
    estado = db.Column(db.Enum('activo', 'baja', 'mantenimiento', name='equipment_estado'), default='activo')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    company = db.relationship('Organizacion', backref='equipments')
    assignments = db.relationship('EquipmentAssignment', back_populates='equipment', cascade='all, delete-orphan')
    usages = db.relationship('EquipmentUsage', back_populates='equipment', cascade='all, delete-orphan')
    maintenance_tasks = db.relationship('MaintenanceTask', back_populates='equipment', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Equipment {self.nombre}>'

    @property
    def current_assignment(self):
        """Obtiene la asignación activa actual"""
        return EquipmentAssignment.query.filter_by(
            equipment_id=self.id,
            estado='asignado'
        ).first()

    @property
    def is_available(self):
        """Verifica si el equipo está disponible para asignación"""
        return self.estado == 'activo' and not self.current_assignment


class EquipmentAssignment(db.Model):
    __tablename__ = 'equipment_assignment'

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    fecha_desde = db.Column(db.Date, nullable=False)
    fecha_hasta = db.Column(db.Date)
    estado = db.Column(db.Enum('asignado', 'liberado', name='assignment_estado'), default='asignado')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    equipment = db.relationship('Equipment', back_populates='assignments')
    project = db.relationship('Obra', backref='equipment_assignments')

    def __repr__(self):
        return f'<EquipmentAssignment {self.equipment.nombre} → {self.project.nombre}>'


class EquipmentUsage(db.Model):
    __tablename__ = 'equipment_usage'

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    horas = db.Column(db.Numeric(6, 2), nullable=False)
    avance_m2 = db.Column(db.Numeric(12, 2))
    avance_m3 = db.Column(db.Numeric(12, 2))
    notas = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    estado = db.Column(db.Enum('pendiente', 'aprobado', 'rechazado', name='usage_estado'), default='pendiente')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    approved_at = db.Column(db.DateTime)

    # Relaciones
    equipment = db.relationship('Equipment', back_populates='usages')
    project = db.relationship('Obra', backref='equipment_usages')
    user = db.relationship('Usuario', foreign_keys=[user_id], backref='equipment_usages')
    approver = db.relationship('Usuario', foreign_keys=[approved_by])

    def __repr__(self):
        return f'<EquipmentUsage {self.equipment.nombre} - {self.fecha}>'


class MaintenanceTask(db.Model):
    __tablename__ = 'maintenance_task'

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    tipo = db.Column(db.Enum('programado', 'correctivo', name='maintenance_tipo'), nullable=False)
    fecha_prog = db.Column(db.Date, nullable=False)
    fecha_real = db.Column(db.Date)
    costo = db.Column(db.Numeric(12, 2))
    notas = db.Column(db.Text)
    status = db.Column(db.Enum('abierta', 'en_proceso', 'cerrada', name='maintenance_status'), default='abierta')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    # Relaciones
    equipment = db.relationship('Equipment', back_populates='maintenance_tasks')
    creator = db.relationship('Usuario', backref='created_maintenance_tasks')
    attachments = db.relationship('MaintenanceAttachment', back_populates='maintenance_task', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<MaintenanceTask {self.equipment.nombre} - {self.tipo}>'


class MaintenanceAttachment(db.Model):
    __tablename__ = 'maintenance_attachment'

    id = db.Column(db.Integer, primary_key=True)
    maintenance_task_id = db.Column(db.Integer, db.ForeignKey('maintenance_task.id'), nullable=False)
    file_url = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    maintenance_task = db.relationship('MaintenanceTask', back_populates='attachments')
    uploader = db.relationship('Usuario', backref='maintenance_attachments')

    def __repr__(self):
        return f'<MaintenanceAttachment {self.filename}>'


# =============================================================================
# PRECIOS DE EQUIPOS - Integración con proveedores (Leiten, etc.)
# =============================================================================

class CategoriaEquipoProveedor(db.Model):
    """Categorías de equipos de proveedores externos (Leiten, etc.)"""
    __tablename__ = 'categoria_equipo_proveedor'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    proveedor = db.Column(db.String(100), default='leiten')  # leiten, otro_proveedor
    categoria_padre_id = db.Column(db.Integer, db.ForeignKey('categoria_equipo_proveedor.id'))
    orden = db.Column(db.Integer, default=0)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    categoria_padre = db.relationship('CategoriaEquipoProveedor', remote_side=[id], backref='subcategorias')
    equipos = db.relationship('EquipoProveedor', back_populates='categoria', lazy='dynamic')

    def __repr__(self):
        return f'<CategoriaEquipoProveedor {self.nombre}>'

    @staticmethod
    def get_or_create(nombre, proveedor='leiten'):
        """Obtiene o crea una categoría por nombre"""
        from slugify import slugify
        slug = slugify(nombre)
        cat = CategoriaEquipoProveedor.query.filter_by(slug=slug, proveedor=proveedor).first()
        if not cat:
            cat = CategoriaEquipoProveedor(nombre=nombre, slug=slug, proveedor=proveedor)
            db.session.add(cat)
        return cat


class EquipoProveedor(db.Model):
    """Equipos de proveedores externos con precios de alquiler y venta"""
    __tablename__ = 'equipo_proveedor'

    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria_equipo_proveedor.id'), nullable=False)
    proveedor = db.Column(db.String(100), default='leiten')

    # Identificación
    codigo = db.Column(db.String(50))  # Código interno del proveedor
    nombre = db.Column(db.String(300), nullable=False)
    marca = db.Column(db.String(100))
    modelo = db.Column(db.String(100))

    # Especificaciones técnicas
    potencia = db.Column(db.String(50))  # Ej: "5.5 hp", "3 kW"
    capacidad = db.Column(db.String(100))  # Ej: "150 litros", "500 kg"
    peso = db.Column(db.String(50))  # Ej: "70 kg"
    motor = db.Column(db.String(100))  # Ej: "Honda GX160 Nafta"
    especificaciones = db.Column(db.JSON)  # Otras specs en JSON

    # Precios de ALQUILER (en USD por 28 días)
    precio_alquiler_usd = db.Column(db.Numeric(12, 2))
    periodo_alquiler_dias = db.Column(db.Integer, default=28)

    # Precios de VENTA
    precio_venta_usd = db.Column(db.Numeric(12, 2))
    precio_venta_ars = db.Column(db.Numeric(14, 2))

    # IVA
    iva_porcentaje = db.Column(db.Numeric(5, 2), default=10.5)

    # Disponibilidad
    disponible_alquiler = db.Column(db.Boolean, default=True)
    disponible_venta = db.Column(db.Boolean, default=True)

    # Metadata
    url_producto = db.Column(db.String(500))  # URL en sitio del proveedor
    imagen_url = db.Column(db.String(500))
    notas = db.Column(db.Text)

    # Etapas de construcción donde aplica
    etapa_construccion = db.Column(db.String(100))  # excavacion, estructura, etc.

    # Control
    activo = db.Column(db.Boolean, default=True)
    fecha_actualizacion_precio = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    categoria = db.relationship('CategoriaEquipoProveedor', back_populates='equipos')

    def __repr__(self):
        return f'<EquipoProveedor {self.nombre}>'

    @property
    def precio_alquiler_diario_usd(self):
        """Calcula precio de alquiler por día"""
        if self.precio_alquiler_usd and self.periodo_alquiler_dias:
            return float(self.precio_alquiler_usd) / self.periodo_alquiler_dias
        return None

    @property
    def precio_alquiler_con_iva_usd(self):
        """Precio de alquiler con IVA incluido"""
        if self.precio_alquiler_usd:
            iva = float(self.iva_porcentaje or 10.5) / 100
            return float(self.precio_alquiler_usd) * (1 + iva)
        return None

    @property
    def precio_venta_con_iva_ars(self):
        """Precio de venta con IVA incluido en ARS"""
        if self.precio_venta_ars:
            iva = float(self.iva_porcentaje or 10.5) / 100
            return float(self.precio_venta_ars) * (1 + iva)
        return None

    def to_dict(self):
        """Convierte a diccionario para API"""
        return {
            'id': self.id,
            'codigo': self.codigo,
            'nombre': self.nombre,
            'marca': self.marca,
            'modelo': self.modelo,
            'categoria': self.categoria.nombre if self.categoria else None,
            'proveedor': self.proveedor,
            'potencia': self.potencia,
            'capacidad': self.capacidad,
            'peso': self.peso,
            'motor': self.motor,
            'precio_alquiler_usd': float(self.precio_alquiler_usd) if self.precio_alquiler_usd else None,
            'precio_alquiler_diario_usd': self.precio_alquiler_diario_usd,
            'periodo_alquiler_dias': self.periodo_alquiler_dias,
            'precio_venta_usd': float(self.precio_venta_usd) if self.precio_venta_usd else None,
            'precio_venta_ars': float(self.precio_venta_ars) if self.precio_venta_ars else None,
            'iva_porcentaje': float(self.iva_porcentaje) if self.iva_porcentaje else 10.5,
            'disponible_alquiler': self.disponible_alquiler,
            'disponible_venta': self.disponible_venta,
            'etapa_construccion': self.etapa_construccion,
            'url_producto': self.url_producto,
            'imagen_url': self.imagen_url
        }

    @staticmethod
    def buscar(query, categoria_id=None, proveedor='leiten', solo_alquiler=False, solo_venta=False):
        """Búsqueda de equipos"""
        q = EquipoProveedor.query.filter_by(activo=True, proveedor=proveedor)

        if categoria_id:
            q = q.filter_by(categoria_id=categoria_id)

        if solo_alquiler:
            q = q.filter(EquipoProveedor.disponible_alquiler == True)
            q = q.filter(EquipoProveedor.precio_alquiler_usd.isnot(None))

        if solo_venta:
            q = q.filter(EquipoProveedor.disponible_venta == True)
            q = q.filter(db.or_(
                EquipoProveedor.precio_venta_usd.isnot(None),
                EquipoProveedor.precio_venta_ars.isnot(None)
            ))

        if query:
            search = f"%{query}%"
            q = q.filter(db.or_(
                EquipoProveedor.nombre.ilike(search),
                EquipoProveedor.marca.ilike(search),
                EquipoProveedor.modelo.ilike(search),
                EquipoProveedor.codigo.ilike(search)
            ))

        return q.order_by(EquipoProveedor.nombre).all()


class HistorialPrecioEquipo(db.Model):
    """Historial de cambios de precios para tracking"""
    __tablename__ = 'historial_precio_equipo'

    id = db.Column(db.Integer, primary_key=True)
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipo_proveedor.id'), nullable=False)
    tipo_precio = db.Column(db.String(20), nullable=False)  # alquiler_usd, venta_usd, venta_ars
    precio_anterior = db.Column(db.Numeric(14, 2))
    precio_nuevo = db.Column(db.Numeric(14, 2))
    fecha_cambio = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))

    # Relaciones
    equipo = db.relationship('EquipoProveedor', backref='historial_precios')
    usuario = db.relationship('Usuario', backref='cambios_precio_equipo')

    def __repr__(self):
        return f'<HistorialPrecioEquipo {self.equipo_id} {self.tipo_precio}>'
