"""
Models para gestión de Proveedores de Órdenes de Compra.
Separado del modelo legacy Proveedor (marketplace) en models/suppliers.py.

Soporta directorio global curado por OBYRA (`scope='global'`,
`organizacion_id IS NULL`) visible a todos los tenants en modo lectura,
y proveedores propios de cada tenant (`scope='tenant'`).
"""
from extensions import db
from datetime import datetime


class Zona(db.Model):
    """Zona geográfica normalizada para filtrar proveedores."""
    __tablename__ = 'zonas'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), nullable=False, unique=True)
    provincia = db.Column(db.String(100))
    activa = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Zona {self.nombre}>'

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'slug': self.slug,
            'provincia': self.provincia,
            'activa': self.activa,
        }


class ProveedorOC(db.Model):
    """Proveedor vinculado a Órdenes de Compra (propio del tenant o global)."""
    __tablename__ = 'proveedores_oc'

    id = db.Column(db.Integer, primary_key=True)
    # NULL => proveedor global (curado por OBYRA, visible a todos los tenants)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True, index=True)

    # Scope de visibilidad: 'tenant' (privado del tenant) | 'global' (catalogo OBYRA)
    scope = db.Column(db.String(20), nullable=False, default='tenant')
    # Llave determinística para idempotencia en imports del catalogo global.
    # UNIQUE solo cuando scope='global' (constraint a nivel BD via partial index).
    external_key = db.Column(db.String(160))

    # Datos principales
    razon_social = db.Column(db.String(200), nullable=False)
    nombre_fantasia = db.Column(db.String(200))
    cuit = db.Column(db.String(20))
    tipo = db.Column(db.String(50), default='materiales')  # materiales, servicios, equipos, otros

    # Categorización del directorio
    categoria = db.Column(db.String(120))            # Cemento, Hormigón, Pinturas, etc.
    subcategoria = db.Column(db.String(160))         # detalle de la categoría
    tier = db.Column(db.String(20))                  # 'TIER 1' | 'TIER 2' | 'TIER 3'
    tipo_alianza = db.Column(db.String(80))          # Distribuidor, Alianza estratégica, etc.

    # Contacto
    email = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    web = db.Column(db.String(300))
    direccion = db.Column(db.String(300))
    ciudad = db.Column(db.String(100))
    provincia = db.Column(db.String(100))
    zona_id = db.Column(db.Integer, db.ForeignKey('zonas.id', ondelete='SET NULL'))
    ubicacion_detalle = db.Column(db.String(255))    # texto libre (barrio/partido/ciudad)
    cobertura = db.Column(db.String(255))            # hasta dónde llega comercialmente

    # Persona de contacto (legacy: campos sueltos. Para multi-contacto usar ContactoProveedor)
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
    zona = db.relationship('Zona', foreign_keys=[zona_id])
    historial_precios = db.relationship('HistorialPrecioProveedor', back_populates='proveedor',
                                        lazy='dynamic', order_by='HistorialPrecioProveedor.fecha.desc()')
    contactos = db.relationship('ContactoProveedor', back_populates='proveedor',
                                cascade='all, delete-orphan', lazy='dynamic')

    @property
    def is_global(self):
        """True si el proveedor pertenece al catalogo global de OBYRA."""
        return self.scope == 'global'

    def puede_editar(self, current_user, current_org_id=None):
        """Reglas de edicion:
        - Globales: solo super_admin.
        - Tenant: cualquier usuario de la organizacion duenia con permiso.
        """
        if not current_user or not getattr(current_user, 'is_authenticated', False):
            return False
        if self.is_global:
            return bool(getattr(current_user, 'is_super_admin', False))
        # tenant: organizacion del proveedor debe coincidir con la activa
        org_id = current_org_id if current_org_id is not None else getattr(current_user, 'organizacion_id', None)
        return self.organizacion_id == org_id

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
        """Retorna resumen de evaluaciones del proveedor + tiempo respuesta WA."""
        evals = self.evaluaciones.all() if hasattr(self, 'evaluaciones') else []
        wa_stats = self.wa_response_stats

        if not evals and not wa_stats:
            return None

        if evals:
            n = len(evals)
            avg_entrega = round(sum(e.puntaje_entrega for e in evals) / n, 1)
            avg_precio = round(sum(e.puntaje_precio for e in evals) / n, 1)
            avg_calidad = round(sum(e.puntaje_calidad for e in evals) / n, 1)
            avg_servicio = round(sum(e.puntaje_servicio for e in evals) / n, 1)
            avg_general = round((avg_entrega + avg_precio + avg_calidad + avg_servicio) / 4, 1)
        else:
            n = 0
            avg_entrega = avg_precio = avg_calidad = avg_servicio = avg_general = 0

        result = {
            'evaluaciones': n,
            'promedio': avg_general,
            'entrega': avg_entrega,
            'precio': avg_precio,
            'calidad': avg_calidad,
            'servicio': avg_servicio,
        }
        if wa_stats:
            result.update(wa_stats)
        return result

    @property
    def wa_response_stats(self):
        """Estadisticas de respuesta a solicitudes de cotizacion via WhatsApp.

        Retorna dict con:
          - wa_enviadas: total de solicitudes enviadas
          - wa_respondidas: cuantas fueron respondidas
          - wa_tasa_respuesta: % respondidas / enviadas
          - wa_tiempo_respuesta_horas: promedio de horas entre envio y respuesta
        """
        try:
            from models.presupuestos_wa import SolicitudCotizacionWA
            solicitudes = SolicitudCotizacionWA.query.filter_by(
                proveedor_oc_id=self.id
            ).filter(SolicitudCotizacionWA.fecha_envio.isnot(None)).all()
        except Exception:
            return None

        if not solicitudes:
            return None

        total = len(solicitudes)
        respondidas = [s for s in solicitudes if s.fecha_respuesta]
        n_resp = len(respondidas)
        tasa = round((n_resp / total) * 100, 0) if total > 0 else 0

        tiempo_promedio_h = None
        if respondidas:
            horas_total = 0
            for s in respondidas:
                if s.fecha_envio and s.fecha_respuesta:
                    diff = (s.fecha_respuesta - s.fecha_envio).total_seconds() / 3600
                    if diff >= 0:
                        horas_total += diff
            if n_resp > 0:
                tiempo_promedio_h = round(horas_total / n_resp, 1)

        return {
            'wa_enviadas': total,
            'wa_respondidas': n_resp,
            'wa_tasa_respuesta': tasa,
            'wa_tiempo_respuesta_horas': tiempo_promedio_h,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'scope': self.scope,
            'is_global': self.is_global,
            'razon_social': self.razon_social,
            'nombre_fantasia': self.nombre_fantasia,
            'nombre_display': self.nombre_display,
            'cuit': self.cuit,
            'tipo': self.tipo,
            'categoria': self.categoria,
            'subcategoria': self.subcategoria,
            'tier': self.tier,
            'tipo_alianza': self.tipo_alianza,
            'email': self.email,
            'telefono': self.telefono,
            'web': self.web,
            'direccion': self.direccion,
            'ciudad': self.ciudad,
            'provincia': self.provincia,
            'zona_id': self.zona_id,
            'zona_nombre': self.zona.nombre if self.zona else None,
            'ubicacion_detalle': self.ubicacion_detalle,
            'cobertura': self.cobertura,
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


# ============================================================
# CONTACTOS DE PROVEEDOR (multi-contacto, scoped por tenant)
# ============================================================

class ContactoProveedor(db.Model):
    """Contacto comercial vinculado a un proveedor.

    Cada tenant agrega sus propios contactos sobre proveedores propios o
    globales. Los contactos creados por un tenant solo son visibles para ese
    tenant; los creados por el superadmin (sin organizacion_id) son visibles
    a todos los tenants.
    """
    __tablename__ = 'contactos_proveedor'

    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores_oc.id', ondelete='CASCADE'),
                             nullable=False, index=True)
    # NULL => contacto global cargado por el superadmin (visible a todos los tenants)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id', ondelete='CASCADE'),
                                nullable=True, index=True)

    nombre = db.Column(db.String(200), nullable=False)
    cargo = db.Column(db.String(120))
    email = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    whatsapp = db.Column(db.String(50))
    notas = db.Column(db.Text)

    principal = db.Column(db.Boolean, nullable=False, default=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    proveedor = db.relationship('ProveedorOC', back_populates='contactos')
    organizacion = db.relationship('Organizacion')
    created_by = db.relationship('Usuario', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<ContactoProveedor {self.nombre} (prov {self.proveedor_id})>'

    @property
    def is_global(self):
        return self.organizacion_id is None

    def to_dict(self):
        return {
            'id': self.id,
            'proveedor_id': self.proveedor_id,
            'organizacion_id': self.organizacion_id,
            'is_global': self.is_global,
            'nombre': self.nombre,
            'cargo': self.cargo,
            'email': self.email,
            'telefono': self.telefono,
            'whatsapp': self.whatsapp,
            'notas': self.notas,
            'principal': self.principal,
            'activo': self.activo,
        }
