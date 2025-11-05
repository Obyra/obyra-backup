"""
Modelos Utilitarios: Registro de Tiempo y Asistente IA
"""
from datetime import datetime
from extensions import db
import json


class RegistroTiempo(db.Model):
    """Modelo para registrar horas trabajadas en tareas"""
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


class ConsultaAgente(db.Model):
    """Modelo para registrar consultas realizadas al agente IA"""
    __tablename__ = 'consultas_agente'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    consulta_texto = db.Column(db.Text, nullable=False)
    respuesta_texto = db.Column(db.Text)
    tipo_consulta = db.Column(db.String(50))  # obra, presupuesto, inventario, usuario, general
    estado = db.Column(db.String(20), nullable=False)  # exito, error
    tiempo_respuesta_ms = db.Column(db.Integer)
    error_detalle = db.Column(db.Text)
    metadata_consulta = db.Column(db.Text)  # JSON con datos adicionales
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    fecha_consulta = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion')
    usuario = db.relationship('Usuario')

    def __repr__(self):
        return f'<ConsultaAgente {self.usuario.nombre} - {self.tipo_consulta}>'

    @property
    def metadata_dict(self):
        """Convierte el metadata JSON a diccionario"""
        if self.metadata_consulta:
            try:
                return json.loads(self.metadata_consulta)
            except:
                return {}
        return {}

    def set_metadata(self, data_dict):
        """Convierte diccionario a JSON para guardar metadata"""
        self.metadata_consulta = json.dumps(data_dict) if data_dict else None
