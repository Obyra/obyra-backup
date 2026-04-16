"""
Models para gestión de Proveedores de Órdenes de Compra.
Separado del modelo legacy Proveedor (marketplace) en models/suppliers.py.
"""
from extensions import db
from datetime import datetime


class ProveedorOC(db.Model):
    """Proveedor vinculado a Órdenes de Compra."""
    __tablename__ = 'proveedores_oc'

    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False, index=True)

    # Datos principales
    razon_social = db.Column(db.String(200), nullable=False)
    nombre_fantasia = db.Column(db.String(200))
    cuit = db.Column(db.String(20))
    tipo = db.Column(db.String(50), default='materiales')  # materiales, servicios, equipos, otros

    # Contacto
    email = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    direccion = db.Column(db.String(300))
    ciudad = db.Column(db.String(100))
    provincia = db.Column(db.String(100))

    # Persona de contacto
    contacto_nombre = db.Column(db.String(200))
    contacto_telefono = db.Column(db.String(50))

    # Comercial
    condicion_pago = db.Column(db.String(100))  # "Contado", "30 días", etc
    notas = db.Column(db.Text)

    # Estado
    activo = db.Column(db.Boolean, default=True, nullable=False)

    # Auditoría
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    organizacion = db.relationship('Organizacion', backref='proveedores_oc')
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])
    historial_precios = db.relationship('HistorialPrecioProveedor', back_populates='proveedor',
                                        lazy='dynamic', order_by='HistorialPrecioProveedor.fecha.desc()')

    def __repr__(self):
        return f'<ProveedorOC {self.razon_social}>'

    @property
    def nombre_display(self):
        if self.nombre_fantasia:
            return f"{self.nombre_fantasia} ({self.razon_social})"
        return self.razon_social

    @property
    def tipo_display(self):
        tipos = {
            'materiales': 'Materiales',
            'servicios': 'Servicios',
            'equipos': 'Equipos',
            'otros': 'Otros'
        }
        return tipos.get(self.tipo, self.tipo or 'Otros')

    @property
    def tipo_color(self):
        colores = {
            'materiales': 'primary',
            'servicios': 'success',
            'equipos': 'warning',
            'otros': 'secondary'
        }
        return colores.get(self.tipo, 'secondary')

    @property
    def scorecard(self):
        """Retorna resumen de evaluaciones del proveedor."""
        evals = self.evaluaciones.all() if hasattr(self, 'evaluaciones') else []
        if not evals:
            return None
        n = len(evals)
        avg_entrega = round(sum(e.puntaje_entrega for e in evals) / n, 1)
        avg_precio = round(sum(e.puntaje_precio for e in evals) / n, 1)
        avg_calidad = round(sum(e.puntaje_calidad for e in evals) / n, 1)
        avg_servicio = round(sum(e.puntaje_servicio for e in evals) / n, 1)
        avg_general = round((avg_entrega + avg_precio + avg_calidad + avg_servicio) / 4, 1)
        return {
            'evaluaciones': n,
            'promedio': avg_general,
            'entrega': avg_entrega,
            'precio': avg_precio,
            'calidad': avg_calidad,
            'servicio': avg_servicio,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'razon_social': self.razon_social,
            'nombre_fantasia': self.nombre_fantasia,
            'nombre_display': self.nombre_display,
            'cuit': self.cuit,
            'tipo': self.tipo,
            'email': self.email,
            'telefono': self.telefono,
            'direccion': self.direccion,
            'ciudad': self.ciudad,
            'provincia': self.provincia,
            'contacto_nombre': self.contacto_nombre,
            'contacto_telefono': self.contacto_telefono,
            'condicion_pago': self.condicion_pago,
            'activo': self.activo,
        }


class ProveedorEvaluacion(db.Model):
    """Evaluacion/scorecard de un proveedor tras una OC."""
    __tablename__ = 'proveedor_evaluaciones'

    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id'), nullable=False)
    orden_compra_id = db.Column(db.Integer, db.ForeignKey('ordenes_compra.id'), nullable=True)
    evaluador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)

    puntaje_entrega = db.Column(db.Integer, default=3)     # 1-5
    puntaje_precio = db.Column(db.Integer, default=3)      # 1-5
    puntaje_calidad = db.Column(db.Integer, default=3)     # 1-5
    puntaje_servicio = db.Column(db.Integer, default=3)    # 1-5
    comentario = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    proveedor = db.relationship('ProveedorOC', backref=db.backref('evaluaciones', lazy='dynamic'))
    orden_compra = db.relationship('OrdenCompra')
    evaluador = db.relationship('Usuario', foreign_keys=[evaluador_id])

    @property
    def puntaje_promedio(self):
        return round((self.puntaje_entrega + self.puntaje_precio +
                       self.puntaje_calidad + self.puntaje_servicio) / 4, 1)


class HistorialPrecioProveedor(db.Model):
    """Registro histórico de precios por proveedor (append-only, se crea al completar OC)."""
    __tablename__ = 'historial_precios_proveedor'

    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id'), nullable=False)
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=True)
    descripcion_item = db.Column(db.String(300), nullable=False)
    precio_unitario = db.Column(db.Numeric(15, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    orden_compra_id = db.Column(db.Integer, db.ForeignKey('ordenes_compra.id'), nullable=True)
    fecha = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    proveedor = db.relationship('ProveedorOC', back_populates='historial_precios')
    item_inventario = db.relationship('ItemInventario')
    orden_compra = db.relationship('OrdenCompra')

    def to_dict(self):
        return {
            'id': self.id,
            'descripcion_item': self.descripcion_item,
            'precio_unitario': float(self.precio_unitario or 0),
            'moneda': self.moneda,
            'fecha': self.fecha.isoformat() if self.fecha else None,
            'orden_compra_numero': self.orden_compra.numero if self.orden_compra else None,
        }


# ============================================================
# COTIZACIONES DE PROVEEDORES
# ============================================================

class CotizacionProveedor(db.Model):
    """Cotización de un proveedor para un requerimiento de compra."""
    __tablename__ = 'cotizaciones_proveedor'

    id = db.Column(db.Integer, primary_key=True)
    requerimiento_id = db.Column(db.Integer, db.ForeignKey('requerimientos_compra.id'), nullable=False)
    proveedor_oc_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id'), nullable=False)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)

    # Estado: borrador, recibida, elegida, descartada
    estado = db.Column(db.String(20), default='borrador')

    # Condiciones comerciales
    moneda = db.Column(db.String(3), default='ARS')
    condicion_pago = db.Column(db.String(100))
    plazo_entrega = db.Column(db.String(100))  # "5 dias habiles", etc
    validez = db.Column(db.String(100))  # "15 dias", etc
    notas = db.Column(db.Text)

    # Totales (calculados desde items)
    subtotal = db.Column(db.Numeric(15, 2), default=0)
    total = db.Column(db.Numeric(15, 2), default=0)

    # Fechas
    fecha_solicitud = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_recepcion = db.Column(db.DateTime)  # Cuando se cargaron los precios

    # Auditoría
    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    requerimiento = db.relationship('RequerimientoCompra', backref='cotizaciones')
    proveedor = db.relationship('ProveedorOC', backref='cotizaciones')
    organizacion = db.relationship('Organizacion')
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])
    items = db.relationship('CotizacionProveedorItem', back_populates='cotizacion',
                            cascade='all, delete-orphan', lazy='dynamic')

    def __repr__(self):
        return f'<CotizacionProveedor {self.id} - RC:{self.requerimiento_id}>'

    @property
    def estado_display(self):
        estados = {
            'borrador': 'Borrador',
            'recibida': 'Recibida',
            'elegida': 'Elegida',
            'descartada': 'Descartada',
        }
        return estados.get(self.estado, self.estado)

    @property
    def estado_color(self):
        colores = {
            'borrador': 'secondary',
            'recibida': 'info',
            'elegida': 'success',
            'descartada': 'danger',
        }
        return colores.get(self.estado, 'secondary')

    def recalcular_totales(self):
        """Recalcula subtotal y total desde los items."""
        sub = sum(float(i.subtotal or 0) for i in self.items)
        self.subtotal = sub
        self.total = sub

    def to_dict(self):
        return {
            'id': self.id,
            'requerimiento_id': self.requerimiento_id,
            'proveedor_oc_id': self.proveedor_oc_id,
            'proveedor_nombre': self.proveedor.razon_social if self.proveedor else None,
            'estado': self.estado,
            'estado_display': self.estado_display,
            'moneda': self.moneda,
            'condicion_pago': self.condicion_pago,
            'plazo_entrega': self.plazo_entrega,
            'validez': self.validez,
            'subtotal': float(self.subtotal or 0),
            'total': float(self.total or 0),
            'fecha_solicitud': self.fecha_solicitud.isoformat() if self.fecha_solicitud else None,
            'fecha_recepcion': self.fecha_recepcion.isoformat() if self.fecha_recepcion else None,
        }


class CotizacionProveedorItem(db.Model):
    """Ítem de una cotización de proveedor."""
    __tablename__ = 'cotizacion_proveedor_items'

    id = db.Column(db.Integer, primary_key=True)
    cotizacion_id = db.Column(db.Integer, db.ForeignKey('cotizaciones_proveedor.id', ondelete='CASCADE'), nullable=False)
    requerimiento_item_id = db.Column(db.Integer, db.ForeignKey('requerimiento_compra_items.id'), nullable=True)

    # Precio cotizado
    precio_unitario = db.Column(db.Numeric(15, 2), default=0)
    subtotal = db.Column(db.Numeric(15, 2), default=0)  # cantidad * precio_unitario

    # Snapshot del item del RC
    descripcion = db.Column(db.String(300), nullable=False)
    cantidad = db.Column(db.Numeric(10, 3), nullable=False)
    unidad = db.Column(db.String(30), default='unidad')

    # Referencia a inventario
    item_inventario_id = db.Column(db.Integer, db.ForeignKey('items_inventario.id'), nullable=True)

    # Modalidad: compra o alquiler
    modalidad = db.Column(db.String(20), default='compra')  # 'compra' o 'alquiler'
    dias_alquiler = db.Column(db.Integer, nullable=True)  # días de alquiler (si aplica)

    # Observaciones del proveedor
    notas = db.Column(db.Text)

    # Relaciones
    cotizacion = db.relationship('CotizacionProveedor', back_populates='items')
    requerimiento_item = db.relationship('RequerimientoCompraItem')
    item_inventario = db.relationship('ItemInventario')

    def __repr__(self):
        return f'<CotizacionProveedorItem {self.descripcion}>'

    def recalcular_subtotal(self):
        precio = float(self.precio_unitario or 0)
        cant = float(self.cantidad or 0)
        if self.modalidad == 'alquiler' and self.dias_alquiler:
            self.subtotal = precio * cant * int(self.dias_alquiler)
        else:
            self.subtotal = precio * cant

    def to_dict(self):
        return {
            'id': self.id,
            'cotizacion_id': self.cotizacion_id,
            'requerimiento_item_id': self.requerimiento_item_id,
            'descripcion': self.descripcion,
            'cantidad': float(self.cantidad or 0),
            'unidad': self.unidad,
            'precio_unitario': float(self.precio_unitario or 0),
            'subtotal': float(self.subtotal or 0),
            'notas': self.notas,
        }
