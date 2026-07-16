# -*- coding: utf-8 -*-
"""Aprendizaje por organizacion (Fase 2.5 IA presupuestos).

Cada vez que el usuario resuelve un item en la pantalla de revision (elige el
tipo de trabajo correcto, o lo marca como precio manual), se guarda un mapeo
`texto del cliente -> resolucion` POR ORGANIZACION. La proxima vez que aparezca
ese mismo texto (mismo tenant), el pipeline lo resuelve directo (verde) sin
llamar al LLM.
"""
import unicodedata
from datetime import datetime

from extensions import db


TRATAMIENTOS_MAPEO = ('apu', 'manual')  # apu = usa una regla; manual = lump-sum


def normalizar_texto_item(s: str) -> str:
    """Normaliza el texto del item para el lookup: minusculas, sin acentos,
    espacios colapsados. Estable para matchear el mismo item entre pliegos."""
    if not s:
        return ''
    s = unicodedata.normalize('NFD', str(s).lower())
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return ' '.join(s.split())


class MapeoItemAprendido(db.Model):
    __tablename__ = 'mapeo_item_aprendido'
    __table_args__ = (
        db.UniqueConstraint('organizacion_id', 'texto_normalizado', name='uq_mapeo_org_texto'),
        db.Index('ix_mapeo_org', 'organizacion_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                nullable=False, index=True)
    texto_normalizado = db.Column(db.String(300), nullable=False)
    texto_original = db.Column(db.String(400), nullable=True)

    regla_id = db.Column(db.String(80), nullable=True)          # None si tratamiento manual
    nivel = db.Column(db.String(20), nullable=False, default='estandar')
    tratamiento = db.Column(db.String(20), nullable=False, default='apu')  # 'apu' | 'manual'

    veces_usado = db.Column(db.Integer, nullable=False, default=0)
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'organizacion_id': self.organizacion_id,
            'texto_original': self.texto_original,
            'regla_id': self.regla_id,
            'nivel': self.nivel,
            'tratamiento': self.tratamiento,
            'veces_usado': self.veces_usado,
        }

    def __repr__(self):
        return f'<MapeoItemAprendido org={self.organizacion_id} "{self.texto_normalizado[:24]}" -> {self.regla_id or self.tratamiento}>'
