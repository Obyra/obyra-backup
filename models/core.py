"""
Modelos Core: Usuario, Organizacion, RBAC
Este módulo contiene los modelos fundamentales del sistema relacionados con
autenticación, gestión de usuarios y control de acceso basado en roles.
"""

from datetime import datetime, timedelta
from flask import session
from flask_login import UserMixin
from extensions import db
from sqlalchemy import func
from sqlalchemy.orm import backref
from werkzeug.security import generate_password_hash, check_password_hash
import uuid


class Organizacion(db.Model):
    __tablename__ = 'organizaciones'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.String(500), nullable=True)  # Descripción o tagline de la empresa
    cuit = db.Column(db.String(20), nullable=True)  # CUIT de la organización
    direccion = db.Column(db.String(255), nullable=True)  # Dirección fiscal
    telefono = db.Column(db.String(50), nullable=True)  # Teléfono de contacto
    email = db.Column(db.String(120), nullable=True)  # Email de contacto
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
    rol = db.Column(db.String(50), nullable=False, default='ayudante')  # Expandido para roles específicos de construcción
    role = db.Column(db.String(20), nullable=False, default='operario')  # Nuevo sistema de roles: admin, pm, operario
    puede_pausar_obras = db.Column(db.Boolean, default=False)  # Permiso especial para pausar obras
    is_super_admin = db.Column(db.Boolean, default=False, nullable=False)  # Super administrador con acceso total al sistema
    activo = db.Column(db.Boolean, default=True)
    auth_provider = db.Column(db.String(20), nullable=False, default='manual')  # manual, google
    google_id = db.Column(db.String(100), nullable=True)  # ID de Google para usuarios OAuth
    profile_picture = db.Column(db.String(500), nullable=True)  # URL de imagen de perfil de Google
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    organizacion_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=False)
    primary_org_id = db.Column(db.Integer, db.ForeignKey('organizaciones.id'), nullable=True)
    plan_activo = db.Column(db.String(50), default='prueba')  # prueba, standard, premium
    fecha_expiracion_plan = db.Column(db.DateTime)  # Para controlar la expiración del plan

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
        """Devuelve las membresías activas no archivadas del usuario."""
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
        """Determina si el usuario tiene el rol solicitado en la organización activa."""
        if not rol:
            return False

        objetivo = rol.strip().lower()
        org_id = session.get('current_org_id')
        membership = None

        if org_id:
            # Preferir membresía ya cargada en la sesión para evitar consultas extras
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

        # Compatibilidad hacia atrás: usar el rol global almacenado en el usuario
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
        """Obtiene la organización actual desde la sesión, falling back a la primaria."""
        try:
            from flask import session, g
        except RuntimeError:  # pragma: no cover - fuera de contexto de aplicación
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
    # Gestión de contraseñas
    # -----------------------------------------------------
    def set_password(self, password: str) -> None:
        """Genera y almacena el hash seguro de la contraseña suministrada."""
        if not password:
            raise ValueError('La contraseña no puede estar vacía.')
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Compara una contraseña en texto plano con el hash almacenado."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def esta_en_periodo_prueba(self):
        """Verifica si el usuario aún está en periodo de prueba"""
        if self.plan_activo != 'prueba':
            return False

        if not self.fecha_creacion:
            return True

        fecha_limite = self.fecha_creacion + timedelta(days=30)
        return datetime.utcnow() <= fecha_limite

    def dias_restantes_prueba(self):
        """Calcula los días restantes del periodo de prueba"""
        if self.plan_activo != 'prueba' or not self.fecha_creacion:
            return 0

        fecha_limite = self.fecha_creacion + timedelta(days=30)
        dias_restantes = (fecha_limite - datetime.utcnow()).days
        return max(0, dias_restantes)

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"

    def puede_acceder_modulo(self, modulo):
        """Verifica si el usuario puede acceder a un módulo usando RBAC"""
        # Primero verificar si hay override específico de usuario
        user_override = UserModule.query.filter_by(user_id=self.id, module=modulo).first()
        if user_override:
            return user_override.can_view

        # Si no hay override, usar permisos del rol
        role_perm = RoleModule.query.filter_by(role=self.rol, module=modulo).first()
        if role_perm:
            return role_perm.can_view

        # Fallback al sistema antiguo si no hay configuración RBAC
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
        """Verifica si el usuario puede editar en un módulo usando RBAC"""
        # Primero verificar si hay override específico de usuario
        user_override = UserModule.query.filter_by(user_id=self.id, module=modulo).first()
        if user_override:
            return user_override.can_edit

        # Si no hay override, usar permisos del rol
        role_perm = RoleModule.query.filter_by(role=self.rol, module=modulo).first()
        if role_perm:
            return role_perm.can_edit

        # Fallback: admins y tecnicos pueden editar la mayoría
        if self.rol in ['administrador', 'tecnico', 'jefe_obra']:
            return True

        return False

    def es_admin_completo(self):
        """Verifica si el usuario es administrador con acceso completo sin restricciones de plan"""
        # Usar el flag is_super_admin en lugar de emails hardcodeados
        if self.is_super_admin:
            return True

        # Mantener compatibilidad temporal con emails legacy
        # TODO: Remover después de migrar todos los usuarios
        emails_admin_completo = ['brenda@gmail.com', 'admin@obyra.com', 'obyra.servicios@gmail.com']
        return self.email in emails_admin_completo

    def es_admin(self):
        """Compatibilidad para plantillas antiguas que consultan current_user.es_admin()."""
        try:
            if self.tiene_rol('admin'):
                return True
        except Exception:
            # En caso de que la sesión aún no esté inicializada seguimos con los fallbacks legacy
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

        # Usuarios con planes activos (standard/premium) también tienen acceso
        if self.plan_activo in ['standard', 'premium']:
            return True

        # Usuarios en periodo de prueba válido
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
        """Garantiza que exista un perfil de facturación asociado al usuario."""
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


class RoleModule(db.Model):
    """Permisos por defecto para cada rol en cada módulo"""
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
    """Overrides de permisos por usuario específico"""
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
    """Obtiene los módulos permitidos para un usuario"""
    role_map = {rm.module: {"view": rm.can_view, "edit": rm.can_edit}
                for rm in RoleModule.query.filter_by(role=user.rol)}

    # Overrides de usuario
    for um in UserModule.query.filter_by(user_id=user.id):
        role_map[um.module] = {"view": um.can_view, "edit": um.can_edit}

    return role_map


def upsert_user_module(user_id, module, view, edit):
    """Inserta o actualiza permisos de módulo para un usuario"""
    um = UserModule.query.filter_by(user_id=user_id, module=module).first()
    if not um:
        um = UserModule(user_id=user_id, module=module)
        db.session.add(um)
    um.can_view = view
    um.can_edit = edit
    db.session.commit()
