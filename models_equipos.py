# Modelos para el módulo de Equipos
from app import db
from datetime import datetime
from sqlalchemy import Index

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


# Índices para optimización
Index('idx_equipment_assignment_project', EquipmentAssignment.project_id)