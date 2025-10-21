from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from flask import session
from flask_login import UserMixin
from app.extensions import db
from sqlalchemy import func, inspect
from sqlalchemy.orm import backref
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import json
import os


class Organizacion(db.Model):
    __tablename__ = 'organizaciones'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    token_invitacion = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    activa = db.Column(db.Boolean, default=True)
    
    # Relaciones
    usuarios = db.relationship(
        'Usuario',
        back_populates='organizacion',
        foreign_keys='Usuario.organizacion_id',
        primaryjoin='Organizacion.id == Usuario.organizacion_id',
        lazy='dynamic'
    )
    usuarios_primarios = db.relationship(
        'Usuario',
        back_populates='primary_organizacion',
        foreign_keys='Usuario.primary_org_id',
        primaryjoin='Organizacion.id == Usuario.primary_org_id',
        lazy='dynamic'
    )
    memberships = db.relationship(
        'OrgMembership',
        back_populates='organizacion',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    obras = db.relationship('Obra', back_populates='organizacion', lazy='dynamic')
    inventario = db.relationship('ItemInventario', back_populates='organizacion', lazy='dynamic')
    presupuestos = db.relationship('Presupuesto', lazy='dynamic')
    
    def __repr__(self):
        return f'<Organizacion {self.nombre}>'
    
    def regenerar_token(self):
        """Regenerar token de invitaciÃ³n"""
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
    rol = db.Column(db.String(50), nullable=False, default='ayudante')  # Expandido para roles especÃ­ficos de construcciÃ³n
    role = db.Column(db.String(20), nullable=False, default='operario')  # Nuevo sistema de roles: admin, pm, operario
    puede_pausar_obras = db.Column(db.Boolean, default=False)  # Permiso especial para pausar obras
    activo = db.Column(db.Boolean, default=True)
    auth_provider = db.Column(db.String(20), nullable=False, default='manual')  # manual, google
    google_id = db.Column(db.String(100), nullable=True)  # ID de Google para usuarios OAuth
    profile_picture = db.Column(db.String(500), nullable=True)  # URL de imagen de perfil de Google
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    primary_org_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True)
    plan_activo = db.Column(db.String(50), default='prueba')  # prueba, standard, premium
    fecha_expiracion_plan = db.Column(db.DateTime)  # Para controlar la expiraciÃ³n del plan
    
    # Relaciones
    organizacion = db.relationship(
        'Organizacion',
        back_populates='usuarios',
        foreign_keys=[organizacion_id]
    )
    primary_organizacion = db.relationship(
        'Organizacion',
        foreign_keys=[primary_org_id],
        back_populates='usuarios_primarios',
        lazy='joined'
    )
    memberships = db.relationship(
        'OrgMembership',
        foreign_keys='OrgMembership.user_id',
        back_populates='usuario',
        cascade='all, delete-orphan'
    )
    perfil = db.relationship(
        'PerfilUsuario',
        back_populates='usuario',
        uselist=False,
        cascade='all, delete-orphan'
    )
    onboarding_status = db.relationship(
        'OnboardingStatus',
        back_populates='usuario',
        uselist=False,
        cascade='all, delete-orphan'
    )
    billing_profile = db.relationship(
        'BillingProfile',
        back_populates='usuario',
        uselist=False,
        cascade='all, delete-orphan'
    )
    obras_asignadas = db.relationship('AsignacionObra', back_populates='usuario', lazy='dynamic')
    registros_tiempo = db.relationship('RegistroTiempo', back_populates='usuario', lazy='dynamic')

    def __repr__(self):
        return f'<Usuario {self.nombre} {self.apellido}>'

    def active_memberships(self):
        """Devuelve las membresÃ­as activas no archivadas del usuario."""
        return [
            membership
            for membership in self.memberships
            if not membership.archived and membership.status == 'active'
        ]

    def membership_for_org(self, org_id: int):
        for membership in self.memberships:
            if membership.org_id == org_id and not membership.archived:
                return membership
        return None

    def tiene_rol(self, rol: str) -> bool:
        """Determina si el usuario tiene el rol solicitado en la organizaciÃ³n activa."""
        if not rol:
            return False

        objetivo = rol.strip().lower()
        org_id = session.get('current_org_id')
        membership = None

        if org_id:
            # Preferir membresÃ­a ya cargada en la sesiÃ³n para evitar consultas extras
            for candidate in self.memberships:
                if candidate.org_id == org_id and not candidate.archived:
                    membership = candidate
                    break

            if membership is None:
                membership = (
                    OrgMembership.query
                    .filter(
                        OrgMembership.org_id == org_id,
                        OrgMembership.user_id == self.id,
                        db.or_(
                            OrgMembership.archived.is_(False),
                            OrgMembership.archived.is_(None),
                        ),
                    )
                    .first()
                )

            if membership:
                return membership.status == 'active' and (membership.role or '').lower() == objetivo

        # Compatibilidad hacia atrÃ¡s: usar el rol global almacenado en el usuario
        role_global = (getattr(self, 'role', None) or '').lower()
        if role_global:
            return role_global == objetivo

        rol_legacy = (getattr(self, 'rol', None) or '').lower()
        if rol_legacy in {'administrador', 'admin'} and objetivo == 'admin':
            return True

        return False

    def ensure_membership(self, org_id: int, *, role: str | None = None, status: str = 'active'):
        existing = self.membership_for_org(org_id)
        if existing:
            return existing

        resolved_role = role or (self.role if getattr(self, 'role', None) else 'operario')
        normalized_role = 'admin' if resolved_role in ('administrador', 'admin', 'administrador_general') else 'operario'

        membership = OrgMembership(
            org_id=org_id,
            usuario=self,
            role=normalized_role,
            status=status,
        )
        db.session.add(membership)

        if not self.primary_org_id:
            self.primary_org_id = org_id
        if not self.organizacion_id:
            self.organizacion_id = org_id
        return membership

    def get_current_org_id(self):
        """Obtiene la organizaciÃ³n actual desde la sesiÃ³n, falling back a la primaria."""
        try:
            from flask import session, g
        except RuntimeError:  # pragma: no cover - fuera de contexto de aplicaciÃ³n
            session = {}
            g = type('obj', (), {})()

        current_membership = getattr(g, 'current_membership', None)
        if current_membership and not current_membership.archived:
            return current_membership.org_id

        org_id = session.get('current_org_id')
        if org_id:
            return org_id

        if self.organizacion_id:
            return self.organizacion_id

        active = self.active_memberships()
        if active:
            return active[0].org_id

        return None

    # -----------------------------------------------------
    # GestiÃ³n de contraseÃ±as
    # -----------------------------------------------------
    def set_password(self, password: str) -> None:
        """Genera y almacena el hash seguro de la contraseÃ±a suministrada."""
        if not password:
            raise ValueError('La contraseÃ±a no puede estar vacÃ­a.')
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Compara una contraseÃ±a en texto plano con el hash almacenado."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def esta_en_periodo_prueba(self):
        """Verifica si el usuario aÃºn estÃ¡ en periodo de prueba"""
        if self.plan_activo != 'prueba':
            return False
        
        if not self.fecha_creacion:
            return True
        
        from datetime import datetime, timedelta
        fecha_limite = self.fecha_creacion + timedelta(days=30)
        return datetime.utcnow() <= fecha_limite
    
    def dias_restantes_prueba(self):
        """Calcula los dÃ­as restantes del periodo de prueba"""
        if self.plan_activo != 'prueba' or not self.fecha_creacion:
            return 0
        
        from datetime import datetime, timedelta
        fecha_limite = self.fecha_creacion + timedelta(days=30)
        dias_restantes = (fecha_limite - datetime.utcnow()).days
        return max(0, dias_restantes)
    
    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"
    
    def puede_acceder_modulo(self, modulo):
        """Verifica si el usuario puede acceder a un mÃ³dulo usando RBAC"""
        # Primero verificar si hay override especÃ­fico de usuario
        user_override = UserModule.query.filter_by(user_id=self.id, module=modulo).first()
        if user_override:
            return user_override.can_view
        
        # Si no hay override, usar permisos del rol
        role_perm = RoleModule.query.filter_by(role=self.rol, module=modulo).first()
        if role_perm:
            return role_perm.can_view
        
        # Fallback al sistema antiguo si no hay configuraciÃ³n RBAC
        roles_direccion = [
            'director_general', 'director_operaciones', 'director_proyectos', 
            'jefe_obra', 'jefe_produccion', 'coordinador_proyectos'
        ]
        
        roles_tecnicos = [
            'ingeniero_civil', 'ingeniero_construcciones', 'arquitecto',
            'ingeniero_seguridad', 'ingeniero_electrico', 'ingeniero_sanitario',
            'ingeniero_mecanico', 'topografo', 'bim_manager', 'computo_presupuesto'
        ]
        
        roles_supervision = [
            'encargado_obra', 'supervisor_obra', 'inspector_calidad',
            'inspector_seguridad', 'supervisor_especialidades'
        ]
        
        roles_administrativos = [
            'administrador_obra', 'comprador', 'logistica', 'recursos_humanos',
            'contador_finanzas'
        ]
        
        roles_operativos = [
            'capataz', 'maestro_mayor_obra', 'oficial_albanil', 'oficial_plomero',
            'oficial_electricista', 'oficial_herrero', 'oficial_pintor', 'oficial_yesero',
            'medio_oficial', 'ayudante', 'operador_maquinaria', 'chofer_camion'
        ]
        
        permisos = {}
        
        for rol in roles_direccion:
            permisos[rol] = ['obras', 'presupuestos', 'equipos', 'inventario', 'marketplaces', 'reportes', 'asistente', 'cotizacion', 'documentos', 'seguridad']
        
        for rol in roles_tecnicos:
            permisos[rol] = ['obras', 'presupuestos', 'inventario', 'marketplaces', 'reportes', 'asistente', 'cotizacion', 'documentos', 'seguridad']
            
        for rol in roles_supervision:
            permisos[rol] = ['obras', 'inventario', 'marketplaces', 'reportes', 'asistente', 'documentos', 'seguridad']
            
        for rol in roles_administrativos:
            permisos[rol] = ['obras', 'presupuestos', 'inventario', 'marketplaces', 'reportes', 'cotizacion', 'documentos']
            
        for rol in roles_operativos:
            permisos[rol] = ['obras', 'inventario', 'marketplaces', 'asistente', 'documentos']
        
        permisos.update({
            'administrador': ['obras', 'presupuestos', 'equipos', 'inventario', 'marketplaces', 'reportes', 'asistente', 'cotizacion', 'documentos', 'seguridad'],
            'tecnico': ['obras', 'presupuestos', 'inventario', 'marketplaces', 'reportes', 'asistente', 'cotizacion', 'documentos', 'seguridad'],
            'operario': ['obras', 'inventario', 'marketplaces', 'asistente', 'documentos']
        })

        return modulo in permisos.get(self.rol, [])

    def puede_editar_modulo(self, modulo):
        """Verifica si el usuario puede editar en un mÃ³dulo usando RBAC"""
        # Primero verificar si hay override especÃ­fico de usuario
        user_override = UserModule.query.filter_by(user_id=self.id, module=modulo).first()
        if user_override:
            return user_override.can_edit

        # Si no hay override, usar permisos del rol
        role_perm = RoleModule.query.filter_by(role=self.rol, module=modulo).first()
        if role_perm:
            return role_perm.can_edit

        # Fallback: admins y tecnicos pueden editar la mayorÃ­a
        if self.rol in ['administrador', 'tecnico', 'jefe_obra']:
            return True

        return False

    def es_admin_completo(self):
        """Verifica si el usuario es administrador con acceso completo sin restricciones de plan"""
        emails_admin_completo = ['brenda@gmail.com', 'admin@obyra.com', 'obyra.servicios@gmail.com']
        return self.email in emails_admin_completo

    def es_admin(self):
        """Compatibilidad para plantillas antiguas que consultan current_user.es_admin()."""
        try:
            if self.tiene_rol('admin'):
                return True
        except Exception:
            # En caso de que la sesiÃ³n aÃºn no estÃ© inicializada seguimos con los fallbacks legacy
            pass

        role_global = (getattr(self, 'role', None) or '').lower()
        if role_global in {'admin', 'administrador', 'administrador_general'}:
            return True

        rol_legacy = (getattr(self, 'rol', None) or '').lower()
        if rol_legacy in {'admin', 'administrador', 'administrador_general'}:
            return True

        return self.es_admin_completo()

    def tiene_acceso_sin_restricciones(self):
        """Verifica si el usuario tiene acceso completo al sistema"""
        # Administradores especiales tienen acceso completo
        if self.es_admin_completo():
            return True

        # Usuarios con planes activos (standard/premium) tambiÃ©n tienen acceso
        if self.plan_activo in ['standard', 'premium']:
            return True

        # Usuarios en periodo de prueba vÃ¡lido
        if self.plan_activo == 'prueba' and self.esta_en_periodo_prueba():
            return True

        return False

    def ensure_onboarding_status(self):
        """Garantiza que exista un registro de onboarding para el usuario."""
        status = self.onboarding_status
        if not status:
            status = OnboardingStatus(usuario=self)
            db.session.add(status)
            db.session.flush()
        return status

    def ensure_billing_profile(self):
        """Garantiza que exista un perfil de facturaciÃ³n asociado al usuario."""
        profile = self.billing_profile
        if not profile:
            profile = BillingProfile(usuario=self)
            db.session.add(profile)
            db.session.flush()
        return profile


class OrgMembership(db.Model):
    __tablename__ = 'org_memberships'

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='operario')
    status = db.Column(db.String(20), nullable=False, default='pending')
    archived = db.Column(db.Boolean, nullable=False, default=False)
    archived_at = db.Column(db.DateTime, nullable=True)
    invited_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    invited_at = db.Column(db.DateTime, server_default=func.now())
    accepted_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('org_id', 'user_id', name='uq_membership_org_user'),
        db.Index('ix_membership_user', 'user_id'),
        db.Index('ix_membership_org', 'org_id'),
    )

    organizacion = db.relationship(
        'Organizacion',
        back_populates='memberships',
        foreign_keys=[org_id]
    )
    usuario = db.relationship(
        'Usuario',
        foreign_keys=[user_id],
        back_populates='memberships'
    )
    invitador = db.relationship(
        'Usuario',
        foreign_keys=[invited_by],
        backref=backref('memberships_invitadas', lazy='dynamic'),
    )

    def marcar_activa(self):
        self.status = 'active'
        self.archived = False
        self.accepted_at = datetime.utcnow()

    def marcar_archivada(self):
        self.archived = True
        self.archived_at = datetime.utcnow()


class PerfilUsuario(db.Model):
    __tablename__ = 'perfiles_usuario'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    cuit = db.Column(db.String(20), nullable=False, unique=True)
    direccion = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = db.relationship('Usuario', back_populates='perfil')

    def __repr__(self):
        return f'<PerfilUsuario usuario_id={self.usuario_id} cuit={self.cuit}>'


class OnboardingStatus(db.Model):
    __tablename__ = 'onboarding_status'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    profile_completed = db.Column(db.Boolean, default=False)
    billing_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = db.relationship('Usuario', back_populates='onboarding_status')

    def mark_profile_completed(self):
        self.profile_completed = True
        self._update_completion_timestamp()

    def mark_billing_completed(self):
        self.billing_completed = True
        self._update_completion_timestamp()

    def _update_completion_timestamp(self):
        if self.profile_completed and self.billing_completed:
            self.completed_at = datetime.utcnow()


class BillingProfile(db.Model):
    __tablename__ = 'billing_profiles'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    razon_social = db.Column(db.String(255))
    tax_id = db.Column(db.String(20))
    billing_email = db.Column(db.String(120))
    billing_phone = db.Column(db.String(50))
    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city = db.Column(db.String(120))
    province = db.Column(db.String(120))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(100), default='Argentina')
    stripe_customer_id = db.Column(db.String(120))
    mercadopago_customer_id = db.Column(db.String(120))
    cardholder_name = db.Column(db.String(120))
    card_last4 = db.Column(db.String(4))
    card_brand = db.Column(db.String(50))
    card_exp_month = db.Column(db.String(2))
    card_exp_year = db.Column(db.String(4))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = db.relationship('Usuario', back_populates='billing_profile')


class Obra(db.Model):
    __tablename__ = 'obras'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    direccion = db.Column(db.String(300))
    direccion_normalizada = db.Column(db.String(300))
    latitud = db.Column(db.Numeric(10, 8))  # Para geolocalizaciÃ³n en mapa
    longitud = db.Column(db.Numeric(11, 8))  # Para geolocalizaciÃ³n en mapa
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
    
    # Datos de cliente adicionales (segÃºn especificaciones)
    cliente_nombre = db.Column(db.String(120))
    cliente_email = db.Column(db.String(120))
    cliente_telefono = db.Column(db.String(50))
    
    # UbicaciÃ³n detallada
    ciudad = db.Column(db.String(100))
    provincia = db.Column(db.String(100))
    pais = db.Column(db.String(100))
    codigo_postal = db.Column(db.String(20))
    referencia = db.Column(db.String(200))   # piso, entrecalles, etc.
    
    # Notas adicionales
    notas = db.Column(db.Text)
    
    # Relaciones
    organizacion = db.relationship('Organizacion', back_populates='obras')
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
        """Calcula el progreso automÃ¡tico basado en etapas, tareas y certificaciones"""
        from decimal import Decimal, ROUND_HALF_UP
        
        total_etapas = self.etapas.count()
        if total_etapas == 0:
            return 0
        
        progreso_etapas = Decimal('0')
        for etapa in self.etapas:
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
    
    # EVM fields (nuevas columnas para planificaciÃ³n y seguimiento)
    fecha_inicio = db.Column(db.Date)              # Fecha de inicio planificada
    fecha_fin = db.Column(db.Date)                 # Fecha de fin planificada  
    presupuesto_mo = db.Column(db.Numeric)         # Presupuesto de mano de obra para EV/PV
    
    # Relaciones
    etapa = db.relationship('EtapaObra', back_populates='tareas')
    miembros = db.relationship('TareaMiembro', back_populates='tarea', cascade='all, delete-orphan')
    avances = db.relationship('TareaAvance', back_populates='tarea', cascade='all, delete-orphan')
    adjuntos = db.relationship('TareaAdjunto', back_populates='tarea', cascade='all, delete-orphan')
    responsable = db.relationship('Usuario')
    registros_tiempo = db.relationship('RegistroTiempo', back_populates='tarea', lazy='dynamic')
    asignaciones = db.relationship('TareaResponsables', back_populates='tarea', lazy='dynamic', cascade='all, delete-orphan')
    
    # EVM relationships
    plan_semanal = db.relationship('TareaPlanSemanal', back_populates='tarea', cascade='all, delete-orphan')
    avance_semanal = db.relationship('TareaAvanceSemanal', back_populates='tarea', cascade='all, delete-orphan')
    
    @property 
    def metrics(self):
        """Calcula mÃ©tricas de la tarea"""
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
    __table_args__ = (db.UniqueConstraint('tarea_id', 'user_id', name='uq_tarea_miembros_tarea_user'),)
    
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

    # Campos de aprobaciÃ³n 
    status = db.Column(db.String(12), default="pendiente")  # pendiente/aprobado/rechazado
    confirmed_by = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    confirmed_at = db.Column(db.DateTime)
    reject_reason = db.Column(db.Text)
    
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
    """Modelo para asignaciones mÃºltiples de usuarios a tareas"""
    __tablename__ = 'tarea_responsables'
    
    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey('tareas_etapa.id'), index=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), index=True, nullable=False)
    cuota_planificada = db.Column(db.Numeric)  # opcional para futuras funcionalidades
    
    # Relaciones
    tarea = db.relationship('TareaEtapa', back_populates='asignaciones')
    usuario = db.relationship('Usuario')
    
    # Constraint de unicidad
    __table_args__ = (db.UniqueConstraint('tarea_id', 'user_id', name='uq_tarea_responsables_tarea_user'),)
    
    def __repr__(self):
        return f'<TareaResponsables tarea_id={self.tarea_id} user_id={self.user_id}>'


class AsignacionObra(db.Model):
    __tablename__ = 'asignaciones_obra'
    
    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    etapa_id = db.Column(db.Integer, db.ForeignKey('etapas_obra.id'), nullable=True)  # AsignaciÃ³n por etapa especÃ­fica
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
    """Miembros especÃ­ficos por obra para permisos granulares"""
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


class ExchangeRate(db.Model):
    __tablename__ = 'exchange_rates'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False)
    base_currency = db.Column(db.String(3), nullable=False, default='ARS')
    quote_currency = db.Column(db.String(3), nullable=False, default='USD')
    value = db.Column('rate', db.Numeric(18, 6), nullable=False)
    as_of_date = db.Column(db.Date, nullable=False, default=date.today)
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    source_url = db.Column(db.String(255))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('provider', 'base_currency', 'quote_currency', 'as_of_date', name='uq_exchange_rate_daily'),
    )

    presupuestos = db.relationship('Presupuesto', back_populates='exchange_rate', lazy='dynamic')

    def __repr__(self):
        return (
            f"<ExchangeRate {self.provider} {self.base_currency}/{self.quote_currency} "
            f"{self.value} ({self.as_of_date})>"
        )


class CACIndex(db.Model):
    __tablename__ = 'cac_indices'

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    value = db.Column(db.Numeric(12, 2), nullable=False)
    provider = db.Column(db.String(50), nullable=False)
    source_url = db.Column(db.String(255))
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('year', 'month', 'provider', name='uq_cac_index_period_provider'),
    )

    def __repr__(self):
        return f"<CACIndex {self.year}-{self.month:02d} {self.value} ({self.provider})>"


class PricingIndex(db.Model):
    __tablename__ = 'pricing_indices'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Numeric(18, 6), nullable=False)
    valid_from = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('name', 'valid_from', name='uq_pricing_indices_name_valid_from'),
    )

    def __repr__(self):
        return f"<PricingIndex {self.name} {self.value} ({self.valid_from})>"


class Presupuesto(db.Model):
    __tablename__ = 'presupuestos'

    id = db.Column(db.Integer, primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)  # Ahora puede ser NULL
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    numero = db.Column(db.String(50), unique=True, nullable=False)
    fecha = db.Column(db.Date, default=date.today)
    estado = db.Column(db.String(20), default='borrador')  # borrador, enviado, aprobado, rechazado, perdido, eliminado
    confirmado_como_obra = db.Column(db.Boolean, default=False)  # NUEVO: Si ya se convirtiÃ³ en obra
    datos_proyecto = db.Column(db.Text)  # NUEVO: Datos del proyecto en JSON
    ubicacion_texto = db.Column(db.String(300))
    ubicacion_normalizada = db.Column(db.String(300))
    geo_latitud = db.Column(db.Numeric(10, 8))
    geo_longitud = db.Column(db.Numeric(11, 8))
    geocode_place_id = db.Column(db.String(120))
    geocode_provider = db.Column(db.String(50))
    geocode_status = db.Column(db.String(20))
    geocode_raw = db.Column(db.Text)
    geocode_actualizado = db.Column(db.DateTime)
    subtotal_materiales = db.Column(db.Numeric(15, 2), default=0)
    subtotal_mano_obra = db.Column(db.Numeric(15, 2), default=0)
    subtotal_equipos = db.Column(db.Numeric(15, 2), default=0)
    total_sin_iva = db.Column(db.Numeric(15, 2), default=0)
    iva_porcentaje = db.Column(db.Numeric(5, 2), default=21)
    total_con_iva = db.Column(db.Numeric(15, 2), default=0)
    observaciones = db.Column(db.Text)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    perdido_motivo = db.Column(db.Text)
    perdido_fecha = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)
    vigencia_dias = db.Column(db.Integer, default=30)
    fecha_vigencia = db.Column(db.Date)
    vigencia_bloqueada = db.Column(db.Boolean, nullable=False, default=True)
    currency = db.Column(db.String(3), nullable=False, default='ARS')
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.id'))
    exchange_rate_value = db.Column(db.Numeric(18, 6))
    exchange_rate_provider = db.Column(db.String(50))
    exchange_rate_fetched_at = db.Column(db.DateTime)
    exchange_rate_as_of = db.Column(db.Date)
    tasa_usd_venta = db.Column(db.Numeric(10, 4))
    indice_cac_valor = db.Column(db.Numeric(12, 2))
    indice_cac_fecha = db.Column(db.Date)

    # Relaciones
    obra = db.relationship('Obra', back_populates='presupuestos')
    organizacion = db.relationship('Organizacion', overlaps="presupuestos")
    items = db.relationship('ItemPresupuesto', back_populates='presupuesto', cascade='all, delete-orphan', lazy='dynamic')
    exchange_rate = db.relationship('ExchangeRate', back_populates='presupuestos', lazy='joined')
    
    def __repr__(self):
        return f'<Presupuesto {self.numero}>'
    
    def calcular_totales(self):
        items = self.items.all() if hasattr(self.items, 'all') else list(self.items)
        cero = Decimal('0')

        def _as_decimal(value):
            if isinstance(value, Decimal):
                return value
            if value is None:
                return Decimal('0')
            try:
                return Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError):
                return Decimal('0')

        def _item_total(item):
            valor = getattr(item, 'total_currency', None)
            if valor is not None:
                return _as_decimal(valor)
            return _as_decimal(getattr(item, 'total', None))

        self.subtotal_materiales = sum((_item_total(item) for item in items if item.tipo == 'material'), cero)
        self.subtotal_mano_obra = sum((_item_total(item) for item in items if item.tipo == 'mano_obra'), cero)
        self.subtotal_equipos = sum((_item_total(item) for item in items if item.tipo == 'equipo'), cero)

        self.subtotal_materiales = self.subtotal_materiales.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.subtotal_mano_obra = self.subtotal_mano_obra.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.subtotal_equipos = self.subtotal_equipos.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        self.total_sin_iva = (self.subtotal_materiales + self.subtotal_mano_obra + self.subtotal_equipos).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        iva = Decimal(self.iva_porcentaje or 0)
        factor_iva = Decimal('1') + (iva / Decimal('100'))
        self.total_con_iva = (self.total_sin_iva * factor_iva).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        self.asegurar_vigencia()

    def asegurar_vigencia(self, fecha_base=None):
        dias = self.vigencia_dias if self.vigencia_dias and self.vigencia_dias > 0 else 30
        if dias < 1:
            dias = 1
        elif dias > 180:
            dias = 180
        if self.vigencia_dias != dias:
            self.vigencia_dias = dias
        if fecha_base is None:
            if self.fecha:
                fecha_base = self.fecha
            elif self.fecha_creacion:
                fecha_base = self.fecha_creacion.date()
            else:
                fecha_base = date.today()
        if not self.fecha_vigencia or fecha_base + timedelta(days=dias) != self.fecha_vigencia:
            self.fecha_vigencia = fecha_base + timedelta(days=dias)
        return self.fecha_vigencia

    @property
    def esta_vencido(self):
        if not self.fecha_vigencia:
            return False
        return self.fecha_vigencia < date.today()

    @property
    def dias_restantes_vigencia(self):
        if not self.fecha_vigencia:
            return None
        return (self.fecha_vigencia - date.today()).days

    @property
    def estado_vigencia(self):
        dias = self.dias_restantes_vigencia
        if dias is None:
            return None
        if dias < 0:
            return 'vencido'
        if dias <= 3:
            return 'critico'
        if dias <= 15:
            return 'alerta'
        return 'normal'

    @property
    def clase_vigencia_badge(self):
        estado = self.estado_vigencia
        mapping = {
            'critico': 'bg-danger text-white',
            'alerta': 'bg-warning text-dark',
            'normal': 'bg-success text-white',
            'vencido': 'bg-secondary text-white',
        }
        return mapping.get(estado, 'bg-secondary text-white')

    def registrar_tipo_cambio(self, snapshot):
        """Actualiza los metadatos de tipo de cambio segÃºn el snapshot recibido."""

        if snapshot is None:
            self.exchange_rate_id = None
            self.exchange_rate_value = None
            self.exchange_rate_provider = None
            self.exchange_rate_fetched_at = None
            return

        self.exchange_rate_id = snapshot.id
        self.exchange_rate_value = snapshot.value
        self.exchange_rate_provider = snapshot.provider
        self.exchange_rate_fetched_at = snapshot.fetched_at
        self.exchange_rate_as_of = snapshot.as_of_date
        if snapshot.quote_currency.upper() == 'USD' and snapshot.base_currency.upper() == 'ARS':
            self.tasa_usd_venta = snapshot.value



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
    etapa_id = db.Column(db.Integer, db.ForeignKey('etapas_obra.id'), nullable=True)
    origen = db.Column(db.String(20), default='manual')  # manual, ia, importado
    currency = db.Column(db.String(3), nullable=False, default='ARS')
    price_unit_currency = db.Column(db.Numeric(15, 2))
    total_currency = db.Column(db.Numeric(15, 2))
    price_unit_ars = db.Column(db.Numeric(15, 2))
    total_ars = db.Column(db.Numeric(15, 2))

    # Relaciones
    presupuesto = db.relationship('Presupuesto', back_populates='items')
    etapa = db.relationship('EtapaObra', lazy='joined')

    def __repr__(self):
        return f'<ItemPresupuesto {self.descripcion}>'


class GeocodeCache(db.Model):
    __tablename__ = 'geocode_cache'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False)
    query_text = db.Column(db.String(400), nullable=False)
    normalized_text = db.Column(db.String(400), nullable=False)
    display_name = db.Column(db.String(400))
    place_id = db.Column(db.String(120))
    latitud = db.Column(db.Numeric(10, 8))
    longitud = db.Column(db.Numeric(11, 8))
    raw_response = db.Column(db.Text)
    status = db.Column(db.String(20), default='ok')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('provider', 'normalized_text', name='uq_geocode_provider_norm'),
        db.Index('ix_geocode_norm', 'normalized_text'),
    )

    def to_payload(self) -> dict:
        def _to_float(value):
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        payload = {
            'provider': self.provider,
            'query': self.query_text,
            'normalized': self.normalized_text,
            'display_name': self.display_name,
            'place_id': self.place_id,
            'lat': _to_float(self.latitud),
            'lng': _to_float(self.longitud),
            'status': self.status or 'ok',
        }

        if self.raw_response:
            try:
                payload['raw'] = json.loads(self.raw_response)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload['raw'] = None
        else:
            payload['raw'] = None

        payload['created_at'] = self.created_at
        payload['updated_at'] = self.updated_at
        return payload


@db.event.listens_for(Presupuesto, 'before_insert')
def _presupuesto_before_insert(mapper, connection, target):
    if target.vigencia_bloqueada is None:
        target.vigencia_bloqueada = True
    target.asegurar_vigencia()


@db.event.listens_for(Presupuesto, 'before_update')
def _presupuesto_before_update(mapper, connection, target):
    state = inspect(target)
    if target.vigencia_bloqueada:
        cambios_vigencia = (
            state.attrs['vigencia_dias'].history.has_changes()
            or state.attrs['fecha_vigencia'].history.has_changes()
        )
        if cambios_vigencia:
            raise ValueError('La vigencia del presupuesto estÃ¡ bloqueada y no puede modificarse.')
    else:
        target.asegurar_vigencia()


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


class ConsultaAgente(db.Model):
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


# Nuevos modelos para configuraciÃ³n inteligente de proyectos
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
    categoria = db.Column(db.String(100), nullable=False)  # estructura, albaÃ±ilerÃ­a, instalaciones, etc.
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
    ajustes_ubicacion = db.Column(db.JSON)  # JSON con ajustes especÃ­ficos por ubicaciÃ³n
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
    usuario = db.relationship('Usuario')  # Usuario que creÃ³ la certificaciÃ³n
    
    def __repr__(self):
        return f'<CertificacionAvance {self.porcentaje_avance}% - Obra {self.obra.nombre}>'
    
    @classmethod
    def validar_certificacion(cls, obra_id, nuevo_porcentaje):
        """Valida que la nueva certificaciÃ³n no exceda el 100% del progreso total"""
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
            return False, f"El total de avance serÃ­a {nuevo_total}%, excede el 100% permitido"

        return True, "CertificaciÃ³n vÃ¡lida"


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
        from decimal import Decimal

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
        from decimal import Decimal

        monto = Decimal(str(self.monto or 0))
        if self.moneda == 'ARS' or not self.tc_usd_pago:
            return monto
        return monto * Decimal(str(self.tc_usd_pago))

    @property
    def monto_equivalente_usd(self):
        from decimal import Decimal

        monto = Decimal(str(self.monto or 0))
        if self.moneda == 'USD' or not self.tc_usd_pago or Decimal(str(self.tc_usd_pago)) == 0:
            return monto
        return monto / Decimal(str(self.tc_usd_pago))


class Proveedor(db.Model):
    __tablename__ = 'proveedores'
    
    id = db.Column(db.Integer, primary_key=True)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    categoria = db.Column(db.String(100), nullable=False)  # materiales, equipos, servicios, profesionales
    especialidad = db.Column(db.String(200))  # subcategorÃ­a especÃ­fica
    ubicacion = db.Column(db.String(300))
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(120))
    sitio_web = db.Column(db.String(200))
    precio_promedio = db.Column(db.Numeric(15, 2))  # Precio promedio por servicio/producto
    calificacion = db.Column(db.Numeric(3, 2), default=5.0)  # CalificaciÃ³n de 1 a 5
    trabajos_completados = db.Column(db.Integer, default=0)
    verificado = db.Column(db.Boolean, default=False)  # Verificado por la plataforma
    activo = db.Column(db.Boolean, default=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    organizacion = db.relationship('Organizacion')
    cotizaciones = db.relationship('SolicitudCotizacion', back_populates='proveedor', lazy='dynamic')
    
    def __repr__(self):
        return f'<Proveedor {self.nombre}>'
    
    @property
    def calificacion_estrellas(self):
        """Devuelve la calificaciÃ³n en formato de estrellas"""
        return round(float(self.calificacion), 1)


class CategoriaProveedor(db.Model):
    __tablename__ = 'categorias_proveedor'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    icono = db.Column(db.String(50))  # Clase de FontAwesome
    activa = db.Column(db.Boolean, default=True)
    
    def __repr__(self):
        return f'<CategoriaProveedor {self.nombre}>'


class SolicitudCotizacion(db.Model):
    __tablename__ = 'solicitudes_cotizacion'
    
    id = db.Column(db.Integer, primary_key=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores.id'), nullable=False)
    solicitante_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, cotizada, aceptada, rechazada
    fecha_solicitud = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_respuesta = db.Column(db.DateTime)
    precio_cotizado = db.Column(db.Numeric(15, 2))
    notas_proveedor = db.Column(db.Text)
    tiempo_entrega_dias = db.Column(db.Integer)
    
    # Relaciones
    proveedor = db.relationship('Proveedor', back_populates='cotizaciones')
    solicitante = db.relationship('Usuario')
    
    def __repr__(self):
        return f'<SolicitudCotizacion {self.id} - {self.estado}>'


# ===== MODELOS DE EQUIPOS =====

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
        """Obtiene la asignaciÃ³n activa actual"""
        return EquipmentAssignment.query.filter_by(
            equipment_id=self.id, 
            estado='asignado'
        ).first()
    
    @property
    def is_available(self):
        """Verifica si el equipo estÃ¡ disponible para asignaciÃ³n"""
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
        return f'<EquipmentAssignment {self.equipment.nombre} â†’ {self.project.nombre}>'


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


# ===== MODELOS DE INVENTARIO =====

class InventoryCategory(db.Model):
    __tablename__ = 'inventory_category'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_global = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    company = db.relationship('Organizacion', backref='inventory_categories')
    parent = db.relationship('InventoryCategory', remote_side=[id], backref='children')
    items = db.relationship('InventoryItem', back_populates='categoria')
    
    def __repr__(self):
        return f'<InventoryCategory {self.nombre}>'

    @property
    def full_path(self):
        """Obtiene la ruta completa de la categorÃ­a con separadores jerÃ¡rquicos."""

        parts = []
        current = self
        visited = set()

        while current is not None:
            # Evitar ciclos en casos de datos inconsistentes
            current_id = getattr(current, "id", None)
            if current_id is not None:
                if current_id in visited:
                    break
                visited.add(current_id)

            parts.append(current.nombre)
            current = current.parent

        return " \u2192 ".join(reversed(parts))

    @property
    def org_id(self):
        """Alias compatible con nomenclatura org_id"""
        return self.company_id


class InventoryItem(db.Model):
    __tablename__ = 'inventory_item'
    
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    sku = db.Column(db.String(100), nullable=False, unique=True)
    nombre = db.Column(db.String(200), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('inventory_category.id'), nullable=False)
    unidad = db.Column(db.String(20), nullable=False)  # kg, m, u, m2, m3, etc.
    package_options_raw = db.Column('package_options', db.Text)
    min_stock = db.Column(db.Numeric(12, 2), default=0)
    descripcion = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)
    
    # Relaciones
    company = db.relationship('Organizacion', backref='inventory_items')
    categoria = db.relationship('InventoryCategory', back_populates='items')
    stocks = db.relationship('Stock', back_populates='item', cascade='all, delete-orphan')
    movements = db.relationship('StockMovement', back_populates='item', cascade='all, delete-orphan')
    reservations = db.relationship('StockReservation', back_populates='item', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<InventoryItem {self.sku} - {self.nombre}>'
    
    @property
    def total_stock(self):
        """Stock total en todos los depÃ³sitos"""
        return sum(stock.cantidad for stock in self.stocks)

    @property
    def reserved_stock(self):
        """Stock reservado activo"""
        return sum(res.qty for res in self.reservations if res.estado == 'activa')
    
    @property
    def available_stock(self):
        """Stock disponible (total - reservado)"""
        return self.total_stock - self.reserved_stock
    
    @property
    def is_low_stock(self):
        """Verifica si el stock estÃ¡ bajo"""
        return self.total_stock <= self.min_stock

    @property
    def package_options(self):
        """Opciones de presentaciÃ³n configuradas para el item."""
        raw = self.package_options_raw
        if not raw:
            return []

        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []

        normalized = []
        if isinstance(data, list):
            for entry in data:
                option = self._normalize_package_option(entry)
                if option:
                    normalized.append(option)
        elif isinstance(data, dict):
            option = self._normalize_package_option(data)
            if option:
                normalized.append(option)

        return normalized

    @package_options.setter
    def package_options(self, value):
        options = []
        if isinstance(value, dict):
            maybe_option = self._normalize_package_option(value)
            if maybe_option:
                options.append(maybe_option)
        elif isinstance(value, list):
            for entry in value:
                maybe_option = self._normalize_package_option(entry)
                if maybe_option:
                    options.append(maybe_option)

        if options:
            self.package_options_raw = json.dumps(options)
        else:
            self.package_options_raw = None

    @staticmethod
    def _normalize_package_option(entry):
        if not isinstance(entry, dict):
            return None

        label = (entry.get('label') or entry.get('nombre') or entry.get('name') or '').strip()
        if not label:
            return None

        unit = (entry.get('unit') or entry.get('unidad') or entry.get('presentation_unit') or '').strip()
        multiplier = entry.get('multiplier') or entry.get('factor') or entry.get('cantidad')

        try:
            multiplier_val = float(multiplier)
        except (TypeError, ValueError):
            return None

        key = (entry.get('key') or entry.get('id') or label.lower())
        key = ''.join(ch for ch in key if ch.isalnum() or ch in ('_', '-')).strip('_-')
        if not key:
            key = label.lower().replace(' ', '_')

        return {
            'key': key,
            'label': label,
            'unit': unit or 'unidad',
            'multiplier': multiplier_val,
        }

    @property
    def package_summary(self):
        options = self.package_options
        if not options:
            return ''
        return ', '.join(option['label'] for option in options)


class Warehouse(db.Model):
    __tablename__ = 'warehouse'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.String(500))
    tipo = db.Column(db.String(20), nullable=False, default='deposito')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)

    # Relaciones
    company = db.relationship('Organizacion', backref='warehouses')
    stocks = db.relationship('Stock', back_populates='warehouse', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Warehouse {self.nombre}>'

    @property
    def tipo_normalizado(self) -> str:
        value = (self.tipo or 'deposito').lower()
        return 'obra' if value == 'obra' else 'deposito'

    @property
    def grupo_display(self) -> str:
        return 'Obras' if self.tipo_normalizado == 'obra' else 'DepÃ³sitos'


class Stock(db.Model):
    __tablename__ = 'stock'
    
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'), nullable=False)
    cantidad = db.Column(db.Numeric(14, 3), default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    item = db.relationship('InventoryItem', back_populates='stocks')
    warehouse = db.relationship('Warehouse', back_populates='stocks')
    
    __table_args__ = (
        db.UniqueConstraint('item_id', 'warehouse_id', name='uq_stock_item_warehouse'),
    )
    
    def __repr__(self):
        return f'<Stock {self.item.nombre} @ {self.warehouse.nombre}: {self.cantidad}>'


class StockMovement(db.Model):
    __tablename__ = 'stock_movement'
    
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    tipo = db.Column(db.Enum('ingreso', 'egreso', 'transferencia', 'ajuste', name='movement_tipo'), nullable=False)
    qty = db.Column(db.Numeric(14, 3), nullable=False)
    origen_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    destino_warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    project_id = db.Column(db.Integer, db.ForeignKey('obras.id'))
    motivo = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    item = db.relationship('InventoryItem', back_populates='movements')
    origen_warehouse = db.relationship('Warehouse', foreign_keys=[origen_warehouse_id])
    destino_warehouse = db.relationship('Warehouse', foreign_keys=[destino_warehouse_id])
    project = db.relationship('Obra', backref='inventory_movements')
    user = db.relationship('Usuario', backref='inventory_movements')
    
    def __repr__(self):
        return f'<StockMovement {self.tipo} - {self.item.nombre}>'
    
    @property
    def warehouse_display(self):
        """Muestra el depÃ³sito relevante segÃºn el tipo de movimiento"""
        if self.tipo == 'ingreso':
            return self.destino_warehouse.nombre if self.destino_warehouse else 'N/A'
        elif self.tipo == 'egreso':
            return self.origen_warehouse.nombre if self.origen_warehouse else 'N/A'
        elif self.tipo == 'transferencia':
            return f"{self.origen_warehouse.nombre} â†’ {self.destino_warehouse.nombre}"
        else:  # ajuste
            return self.destino_warehouse.nombre if self.destino_warehouse else 'N/A'


class StockReservation(db.Model):
    __tablename__ = 'stock_reservation'
    
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_item.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    qty = db.Column(db.Numeric(14, 3), nullable=False)
    estado = db.Column(db.Enum('activa', 'liberada', 'consumida', name='reservation_estado'), default='activa')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    item = db.relationship('InventoryItem', back_populates='reservations')
    project = db.relationship('Obra', backref='inventory_reservations')
    creator = db.relationship('Usuario', backref='inventory_reservations')
    
    def __repr__(self):
        return f'<StockReservation {self.item.nombre} - {self.project.nombre}>'


# ===== MODELOS DEL PORTAL DE PROVEEDORES =====

class Supplier(db.Model):
    __tablename__ = 'supplier'
    
    id = db.Column(db.Integer, primary_key=True)
    razon_social = db.Column(db.String(200), nullable=False)
    cuit = db.Column(db.String(15), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    direccion = db.Column(db.Text)
    descripcion = db.Column(db.Text)
    ubicacion = db.Column(db.String(100))  # Ciudad/Provincia
    estado = db.Column(db.Enum('activo', 'suspendido', name='supplier_estado'), default='activo')
    verificado = db.Column(db.Boolean, default=False)
    mp_collector_id = db.Column(db.String(50))  # Para Mercado Pago
    logo_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    users = db.relationship('SupplierUser', back_populates='supplier', cascade='all, delete-orphan')
    products = db.relationship('Product', back_populates='supplier', cascade='all, delete-orphan')
    orders = db.relationship('Order', back_populates='supplier')
    payouts = db.relationship('SupplierPayout', back_populates='supplier', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Supplier {self.razon_social}>'
    
    @property
    def active_products_count(self):
        return Product.query.filter_by(supplier_id=self.id, estado='publicado').count()
    
    @property
    def total_orders_value(self):
        total = db.session.query(func.sum(Order.total)).filter_by(
            supplier_id=self.id, 
            payment_status='approved'
        ).scalar()
        return total or 0


class SupplierUser(db.Model):
    __tablename__ = 'supplier_user'

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.Enum('owner', 'editor', name='supplier_user_rol'), default='editor')
    activo = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    supplier = db.relationship('Supplier', back_populates='users')
    
    def __repr__(self):
        return f'<SupplierUser {self.email}>'
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    @property
    def is_owner(self):
        return self.rol == 'owner'

    # Compatibilidad con plantillas que consultan current_user.es_admin()
    def es_admin(self):
        return False


class Category(db.Model):
    __tablename__ = 'category'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    parent = db.relationship('Category', remote_side=[id], backref='children')
    products = db.relationship('Product', back_populates='category')
    
    def __repr__(self):
        return f'<Category {self.nombre}>'
    
    @property
    def full_path(self):
        if self.parent:
            return f"{self.parent.full_path} > {self.nombre}"
        return self.nombre


class Product(db.Model):
    __tablename__ = 'product'
    
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False)  # SEO friendly URL
    descripcion = db.Column(db.Text)
    estado = db.Column(db.Enum('borrador', 'publicado', 'pausado', name='product_estado'), default='borrador')
    rating_prom = db.Column(db.Numeric(2, 1), default=0)
    published_at = db.Column(db.DateTime)  # Fecha de publicaciÃ³n
    visitas = db.Column(db.Integer, default=0)  # Contador de visitas
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    supplier = db.relationship('Supplier', back_populates='products')
    category = db.relationship('Category', back_populates='products')
    variants = db.relationship('ProductVariant', back_populates='product', cascade='all, delete-orphan')
    images = db.relationship('ProductImage', back_populates='product', cascade='all, delete-orphan')
    qnas = db.relationship('ProductQNA', back_populates='product', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Product {self.nombre}>'
    
    @property
    def can_publish(self):
        """Verifica si el producto puede ser publicado"""
        has_visible_variant = any(v.visible and v.precio > 0 and v.stock > 0 for v in self.variants)
        has_image = len(self.images) > 0
        return has_visible_variant and has_image
    
    @property
    def main_image(self):
        """Obtiene la imagen principal (primera en orden)"""
        return self.images[0] if self.images else None
    
    @property
    def min_price(self):
        """Precio mÃ­nimo de las variantes visibles"""
        visible_variants = [v for v in self.variants if v.visible and v.precio > 0]
        return min(v.precio for v in visible_variants) if visible_variants else 0
    
    @property
    def cover_url(self):
        """URL de la imagen principal"""
        main_image = self.main_image
        return main_image.url if main_image else '/static/img/product-placeholder.jpg'
    
    def increment_visits(self):
        """Incrementa el contador de visitas"""
        self.visitas = (self.visitas or 0) + 1
        db.session.commit()


class ProductVariant(db.Model):
    __tablename__ = 'product_variant'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    sku = db.Column(db.String(100), unique=True, nullable=False)
    atributos_json = db.Column(db.JSON)  # Ej: {"color": "rojo", "talla": "M"}
    unidad = db.Column(db.String(20), nullable=False)  # kg, m, u, etc.
    precio = db.Column(db.Numeric(12, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    stock = db.Column(db.Numeric(12, 2), default=0)
    visible = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    product = db.relationship('Product', back_populates='variants')
    order_items = db.relationship('OrderItem', back_populates='variant')
    
    def __repr__(self):
        return f'<ProductVariant {self.sku}>'
    
    @property
    def display_name(self):
        """Nombre para mostrar incluyendo atributos"""
        if self.atributos_json:
            attrs = ", ".join(f"{k}: {v}" for k, v in self.atributos_json.items())
            return f"{self.product.nombre} ({attrs})"
        return self.product.nombre
    
    @property
    def is_available(self):
        return self.visible and self.stock > 0 and self.product.estado == 'publicado'


class ProductImage(db.Model):
    __tablename__ = 'product_image'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    orden = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    product = db.relationship('Product', back_populates='images')
    
    def __repr__(self):
        return f'<ProductImage {self.filename}>'


class ProductQNA(db.Model):
    __tablename__ = 'product_qna'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))  # Puede ser NULL para anÃ³nimos
    pregunta = db.Column(db.Text, nullable=False)
    respuesta = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    answered_at = db.Column(db.DateTime)
    
    # Relaciones
    product = db.relationship('Product', back_populates='qnas')
    user = db.relationship('Usuario', backref='product_questions')
    
    def __repr__(self):
        return f'<ProductQNA {self.id}>'
    
    @property
    def is_answered(self):
        return self.respuesta is not None


class Order(db.Model):
    __tablename__ = 'order'
    
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    estado = db.Column(db.Enum('pendiente', 'pagado', 'entregado', 'cancelado', name='order_estado'), default='pendiente')
    payment_method = db.Column(db.Enum('online', 'offline', name='payment_method'))
    payment_status = db.Column(db.Enum('init', 'approved', 'rejected', 'refunded', name='payment_status'), default='init')
    payment_ref = db.Column(db.String(100))  # ID de pago de MP
    buyer_invoice_url = db.Column(db.String(500))  # Factura del proveedor al comprador
    supplier_invoice_number = db.Column(db.String(50))
    supplier_invoice_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    company = db.relationship('Organizacion', backref='supplier_orders')
    supplier = db.relationship('Supplier', back_populates='orders')
    items = db.relationship('OrderItem', back_populates='order', cascade='all, delete-orphan')
    commission = db.relationship('OrderCommission', back_populates='order', uselist=False, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Order {self.id}>'
    
    @property
    def commission_amount(self):
        """Calcula la comisiÃ³n (2% del total)"""
        rate = float(os.environ.get('PLATFORM_COMMISSION_RATE', '0.02'))
        return round(float(self.total) * rate, 2)
    
    @property
    def is_paid(self):
        return self.payment_status == 'approved'


class OrderItem(db.Model):
    __tablename__ = 'order_item'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=False)
    qty = db.Column(db.Numeric(12, 2), nullable=False)
    precio_unit = db.Column(db.Numeric(12, 2), nullable=False)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    
    # Relaciones
    order = db.relationship('Order', back_populates='items')
    variant = db.relationship('ProductVariant', back_populates='order_items')
    
    def __repr__(self):
        return f'<OrderItem {self.order_id}-{self.variant.sku}>'


class OrderCommission(db.Model):
    __tablename__ = 'order_commission'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    base = db.Column(db.Numeric(12, 2), nullable=False)  # Total del pedido
    rate = db.Column(db.Numeric(5, 4), default=0.02)  # 2%
    monto = db.Column(db.Numeric(12, 2), nullable=False)  # ComisiÃ³n sin IVA
    iva = db.Column(db.Numeric(12, 2), default=0)  # IVA sobre la comisiÃ³n
    total = db.Column(db.Numeric(12, 2), nullable=False)  # ComisiÃ³n + IVA
    status = db.Column(db.Enum('pendiente', 'facturado', 'cobrado', 'anulado', name='commission_status'), default='pendiente')
    invoice_number = db.Column(db.String(50))
    invoice_pdf_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    order = db.relationship('Order', back_populates='commission')
    
    def __repr__(self):
        return f'<OrderCommission {self.order_id}>'
    
    @staticmethod
    def compute_commission(base, rate=0.02, iva_included=False):
        """Calcula la comisiÃ³n con o sin IVA"""
        monto = round(float(base) * rate, 2)
        if iva_included:
            # Aplicar gross-up para IVA (21%)
            iva = round(monto * 0.21, 2)
            total = monto + iva
        else:
            iva = 0
            total = monto
        
        return {
            'monto': monto,
            'iva': iva,
            'total': total
        }


# ===== CARRITO DE COMPRAS =====

class Cart(db.Model):
    __tablename__ = 'cart'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))  # Usuario logueado (opcional)
    session_id = db.Column(db.String(64))  # Para usuarios anÃ³nimos
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    user = db.relationship('Usuario', backref='carts')
    items = db.relationship('CartItem', back_populates='cart', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Cart {self.id}>'
    
    @property
    def total_items(self):
        return sum(item.qty for item in self.items)
    
    @property
    def total_amount(self):
        return sum(item.subtotal for item in self.items)
    
    def clear(self):
        """VacÃ­a el carrito"""
        CartItem.query.filter_by(cart_id=self.id).delete()
        db.session.commit()


class CartItem(db.Model):
    __tablename__ = 'cart_item'
    
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('cart.id'), nullable=False)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    qty = db.Column(db.Numeric(12, 2), nullable=False)
    precio_snapshot = db.Column(db.Numeric(12, 2), nullable=False)  # Precio al momento de agregar
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    cart = db.relationship('Cart', back_populates='items')
    variant = db.relationship('ProductVariant', backref='cart_items')
    supplier = db.relationship('Supplier', backref='cart_items')
    
    def __repr__(self):
        return f'<CartItem {self.variant.sku} x{self.qty}>'
    
    @property
    def subtotal(self):
        return self.precio_snapshot * self.qty


class SupplierPayout(db.Model):
    __tablename__ = 'supplier_payout'
    
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))  # Puede ser NULL
    tipo = db.Column(db.Enum('ingreso', 'deuda', 'pago_comision', name='payout_tipo'), nullable=False)
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    moneda = db.Column(db.String(3), default='ARS')
    saldo_resultante = db.Column(db.Numeric(12, 2), nullable=False)
    nota = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    supplier = db.relationship('Supplier', back_populates='payouts')
    order = db.relationship('Order', backref='payouts')
    
    def __repr__(self):
        return f'<SupplierPayout {self.supplier_id}-{self.tipo}>'


# ===== SISTEMA DE EVENTOS Y ACTIVIDAD =====

class Event(db.Model):
    """
    Modelo para registrar eventos del sistema que alimentan el feed de actividad.
    Incluye alertas, cambios de estado, hitos, etc.
    """
    __tablename__ = 'events'
    
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)  # Nullable para eventos globales
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)  # Usuario que generÃ³ el evento
    
    # Tipo de evento
    type = db.Column(db.Enum(
        'alert', 'milestone', 'delay', 'cost_overrun', 'stock_low', 
        'status_change', 'budget_created', 'inventory_alert', 'custom',
        name='event_type'
    ), nullable=False)
    
    # Severidad del evento
    severity = db.Column(db.Enum(
        'baja', 'media', 'alta', 'critica',
        name='event_severity'
    ), nullable=True)
    
    # Contenido del evento
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    meta = db.Column(db.JSON)  # Metadata adicional del evento
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    
    # Relaciones
    company = db.relationship('Organizacion', backref='events')
    project = db.relationship('Obra', backref='events')
    user = db.relationship('Usuario', foreign_keys=[user_id], backref='generated_events')
    creator = db.relationship('Usuario', foreign_keys=[created_by], backref='created_events')
    
    # Ãndices
    __table_args__ = (
        db.Index('idx_events_company_created', 'company_id', 'created_at'),
        db.Index('idx_events_project', 'project_id'),
        db.Index('idx_events_type', 'type'),
    )
    
    @property
    def type_icon(self):
        """Retorna el icono FontAwesome correspondiente al tipo de evento"""
        icons = {
            'alert': 'fas fa-exclamation-triangle',
            'milestone': 'fas fa-flag-checkered',
            'delay': 'fas fa-clock',
            'cost_overrun': 'fas fa-dollar-sign',
            'stock_low': 'fas fa-boxes',
            'status_change': 'fas fa-exchange-alt',
            'budget_created': 'fas fa-calculator',
            'inventory_alert': 'fas fa-warehouse',
            'custom': 'fas fa-info-circle'
        }
        return icons.get(self.type, 'fas fa-bell')
    
    @property
    def severity_badge_class(self):
        """Retorna la clase CSS Bootstrap para el badge de severidad"""
        classes = {
            'critica': 'badge bg-danger',
            'alta': 'badge bg-warning',
            'media': 'badge bg-warning text-dark',
            'baja': 'badge bg-secondary'
        }
        return classes.get(self.severity, 'badge bg-secondary')
    
    @property
    def time_ago(self):
        """Retorna tiempo transcurrido en formato legible"""
        from datetime import datetime, timedelta
        
        now = datetime.utcnow()
        diff = now - self.created_at
        
        if diff.days > 7:
            return self.created_at.strftime('%d/%m/%Y')
        elif diff.days > 0:
            return f'hace {diff.days} dÃ­a{"s" if diff.days > 1 else ""}'
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f'hace {hours} hora{"s" if hours > 1 else ""}'
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f'hace {minutes} min'
        else:
            return 'hace un momento'

    def __repr__(self):
        return f'<Event {self.id}: {self.title}>'
    
    @property
    def severity_badge_class(self):
        """Retorna la clase CSS para el badge de severidad"""
        severity_classes = {
            'baja': 'badge bg-success',
            'media': 'badge bg-warning text-dark',
            'alta': 'badge bg-orange text-white',
            'critica': 'badge bg-danger'
        }
        return severity_classes.get(self.severity, 'badge bg-secondary')
    
    @property
    def type_icon(self):
        """Retorna el Ã­cono FontAwesome para el tipo de evento"""
        type_icons = {
            'alert': 'fas fa-exclamation-triangle',
            'milestone': 'fas fa-flag-checkered',
            'delay': 'fas fa-clock',
            'cost_overrun': 'fas fa-dollar-sign',
            'stock_low': 'fas fa-boxes',
            'status_change': 'fas fa-exchange-alt',
            'budget_created': 'fas fa-calculator',
            'inventory_alert': 'fas fa-warehouse',
            'custom': 'fas fa-info-circle'
        }
        return type_icons.get(self.type, 'fas fa-bell')
    
    @property
    def time_ago(self):
        """Retorna una representaciÃ³n amigable del tiempo transcurrido"""
        now = datetime.utcnow()
        diff = now - self.created_at
        
        if diff.days > 0:
            return f"hace {diff.days} dÃ­a{'s' if diff.days > 1 else ''}"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"hace {hours} hora{'s' if hours > 1 else ''}"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"hace {minutes} minuto{'s' if minutes > 1 else ''}"
        else:
            return "hace unos segundos"
    
    @classmethod
    def create_alert_event(cls, company_id, project_id, title, description, severity='media', user_id=None, meta=None):
        """Factory method para crear eventos de alerta"""
        event = cls(
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
            type='alert',
            severity=severity,
            title=title,
            description=description,
            meta=meta or {},
            created_by=user_id
        )
        db.session.add(event)
        return event
    
    @classmethod
    def create_status_change_event(cls, company_id, project_id, old_status, new_status, user_id=None):
        """Factory method para crear eventos de cambio de estado"""
        title = f"Cambio de estado de obra"
        description = f"Estado cambiÃ³ de '{old_status}' a '{new_status}'"
        meta = {
            'old_status': old_status,
            'new_status': new_status
        }
        
        event = cls(
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
            type='status_change',
            severity='media',
            title=title,
            description=description,
            meta=meta,
            created_by=user_id
        )
        db.session.add(event)
        return event
    
    @classmethod
    def create_budget_event(cls, company_id, project_id, budget_id, budget_total, user_id=None):
        """Factory method para crear eventos de presupuesto"""
        title = f"Nuevo presupuesto creado"
        description = f"Presupuesto por ${budget_total:,.2f} creado para la obra"
        meta = {
            'budget_id': budget_id,
            'budget_total': float(budget_total)
        }
        
        event = cls(
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
            type='budget_created',
            severity='baja',
            title=title,
            description=description,
            meta=meta,
            created_by=user_id
        )
        db.session.add(event)
        return event
    
    @classmethod
    def create_inventory_alert_event(cls, company_id, item_name, current_stock, min_stock, user_id=None):
        """Factory method para crear eventos de stock bajo"""
        title = f"Stock bajo: {item_name}"
        description = f"Stock actual: {current_stock}, mÃ­nimo: {min_stock}"
        severity = 'alta' if current_stock <= min_stock * 0.5 else 'media'
        meta = {
            'item_name': item_name,
            'current_stock': float(current_stock),
            'min_stock': float(min_stock)
        }
        
        event = cls(
            company_id=company_id,
            project_id=None,  # Eventos de inventario son globales
            user_id=user_id,
            type='inventory_alert',
            severity=severity,
            title=title,
            description=description,
            meta=meta,
            created_by=user_id
        )
        db.session.add(event)
        return event


# ===== MODELOS RBAC =====

class RoleModule(db.Model):
    """Permisos por defecto para cada rol en cada mÃ³dulo"""
    __tablename__ = 'role_modules'
    
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(50), nullable=False)
    module = db.Column(db.String(50), nullable=False)
    can_view = db.Column(db.Boolean, default=False)
    can_edit = db.Column(db.Boolean, default=False)
    
    __table_args__ = (db.UniqueConstraint('role', 'module', name='unique_role_module'),)
    
    def __repr__(self):
        return f'<RoleModule {self.role}:{self.module} view={self.can_view} edit={self.can_edit}>'


class UserModule(db.Model):
    """Overrides de permisos por usuario especÃ­fico"""
    __tablename__ = 'user_modules'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    module = db.Column(db.String(50), nullable=False)
    can_view = db.Column(db.Boolean, default=False)
    can_edit = db.Column(db.Boolean, default=False)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'module', name='unique_user_module'),)
    
    # Relaciones
    user = db.relationship('Usuario', backref='module_overrides')
    
    def __repr__(self):
        return f'<UserModule user={self.user_id}:{self.module} view={self.can_view} edit={self.can_edit}>'


# ===== FUNCIONES HELPER PARA RBAC =====

def get_allowed_modules(user):
    """Obtiene los mÃ³dulos permitidos para un usuario"""
    role_map = {rm.module: {"view": rm.can_view, "edit": rm.can_edit}
                for rm in RoleModule.query.filter_by(role=user.rol)}
    
    # Overrides de usuario
    for um in UserModule.query.filter_by(user_id=user.id):
        role_map[um.module] = {"view": um.can_view, "edit": um.can_edit}
    
    return role_map


def upsert_user_module(user_id, module, view, edit):
    """Inserta o actualiza permisos de mÃ³dulo para un usuario"""
    um = UserModule.query.filter_by(user_id=user_id, module=module).first()
    if not um:
        um = UserModule(user_id=user_id, module=module)
        db.session.add(um)
    um.can_view = view
    um.can_edit = edit
    db.session.commit()


# ===== FUNCIONES HELPER PARA TAREAS =====

def resumen_tarea(t):
    """Helper para calcular mÃ©tricas de una tarea (solo suma aprobados)"""
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


class WizardStageVariant(db.Model):
    __tablename__ = 'wizard_stage_variants'

    id = db.Column(db.Integer, primary_key=True)
    stage_slug = db.Column(db.String(80), nullable=False, index=True)
    variant_key = db.Column(db.String(80), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.String(255))
    is_default = db.Column(db.Boolean, default=False)
    metadata_raw = db.Column('metadata', db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    coefficients = db.relationship(
        'WizardStageCoefficient',
        back_populates='variant',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('stage_slug', 'variant_key', name='uq_wizard_stage_variant'),
    )

    @property
    def meta(self):
        try:
            return json.loads(self.metadata_raw or '{}')
        except (ValueError, TypeError):
            return {}

    @meta.setter
    def meta(self, value):
        self.metadata_raw = json.dumps(value or {})

    def __repr__(self):
        return f"<WizardStageVariant stage={self.stage_slug} variant={self.variant_key}>"


class WizardStageCoefficient(db.Model):
    __tablename__ = 'wizard_stage_coefficients'

    id = db.Column(db.Integer, primary_key=True)
    stage_slug = db.Column(db.String(80), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('wizard_stage_variants.id'), nullable=True)
    unit = db.Column(db.String(20), nullable=False, default='u')
    quantity_metric = db.Column(db.String(50), nullable=False, default='cantidad')
    materials_per_unit = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    labor_per_unit = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    equipment_per_unit = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default='ARS')
    source = db.Column(db.String(80))
    notes = db.Column(db.String(255))
    is_baseline = db.Column(db.Boolean, default=False)
    metadata_raw = db.Column('metadata', db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    variant = db.relationship('WizardStageVariant', back_populates='coefficients')

    __table_args__ = (
        db.UniqueConstraint('stage_slug', 'variant_id', name='uq_wizard_stage_coeff_variant'),
    )

    @property
    def meta(self):
        try:
            return json.loads(self.metadata_raw or '{}')
        except (ValueError, TypeError):
            return {}

    @meta.setter
    def meta(self, value):
        self.metadata_raw = json.dumps(value or {})

    def __repr__(self):
        return (
            f"<WizardStageCoefficient stage={self.stage_slug} variant={self.variant_id} "
            f"mat={self.materials_per_unit} labor={self.labor_per_unit}>"
        )


def seed_default_role_permissions():
    """Seed permisos por defecto para roles"""
    default_permissions = {
        'administrador': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'equipos': {'view': True, 'edit': True},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': True},
            'reportes': {'view': True, 'edit': True},
            'documentos': {'view': True, 'edit': True}
        },
        'tecnico': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': False},
            'reportes': {'view': True, 'edit': False},
            'documentos': {'view': True, 'edit': True}
        },
        'operario': {
            'obras': {'view': True, 'edit': False},
            'inventario': {'view': True, 'edit': False},
            'marketplaces': {'view': True, 'edit': False},
            'documentos': {'view': True, 'edit': False}
        },
        'jefe_obra': {
            'obras': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': True},
            'equipos': {'view': True, 'edit': False},
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': True},
            'reportes': {'view': True, 'edit': False},
            'documentos': {'view': True, 'edit': True}
        },
        'compras': {
            'inventario': {'view': True, 'edit': True},
            'marketplaces': {'view': True, 'edit': True},
            'presupuestos': {'view': True, 'edit': False},
            'reportes': {'view': True, 'edit': False}
        }
    }
    
    for role, modules in default_permissions.items():
        for module, perms in modules.items():
            existing = RoleModule.query.filter_by(role=role, module=module).first()
            if not existing:
                rm = RoleModule(
                    role=role,
                    module=module,
                    can_view=perms['view'],
                    can_edit=perms['edit']
                )
                db.session.add(rm)
    
    db.session.commit()
