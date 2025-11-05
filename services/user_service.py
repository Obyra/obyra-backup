"""
User Service - Gestión de usuarios, autenticación y permisos
=============================================================
Este servicio encapsula toda la lógica de negocio relacionada con usuarios,
incluyendo autenticación, registro, gestión de membresías y permisos.

Extrae lógica de models/core.py para seguir el patrón Service Layer.
"""

from datetime import datetime, timedelta
from typing import Optional, List
from flask import session, g
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError

from services.base import BaseService, ValidationException, NotFoundException, ServiceException
from models import (
    Usuario, Organizacion, OrgMembership, PerfilUsuario,
    OnboardingStatus, BillingProfile, RoleModule, UserModule
)
from extensions import db
from config.cache_config import cache_user_query, invalidate_pattern


class UserService(BaseService[Usuario]):
    """
    Servicio para gestión de usuarios, autenticación y permisos.

    Proporciona métodos para:
    - Autenticación y registro de usuarios
    - Gestión de contraseñas
    - Gestión de membresías a organizaciones
    - Verificación de permisos y roles
    - Onboarding y perfiles de facturación
    """

    model_class = Usuario

    # ============================================================
    # AUTHENTICATION METHODS
    # ============================================================

    def authenticate(self, email: str, password: str) -> Optional[Usuario]:
        """
        Autentica un usuario mediante email y contraseña.

        Args:
            email: Email del usuario
            password: Contraseña en texto plano

        Returns:
            Usuario autenticado o None si las credenciales son inválidas

        Raises:
            ValidationException: Si el email o password están vacíos
        """
        if not email or not password:
            raise ValidationException("Email y contraseña son requeridos")

        email = email.strip().lower()
        user = self.get_by_email(email)

        if not user:
            self._log_warning(f"Intento de login fallido: usuario no encontrado {email}")
            return None

        if not user.activo:
            self._log_warning(f"Intento de login de usuario inactivo: {email}")
            return None

        if user.auth_provider != 'manual':
            self._log_warning(f"Intento de login manual para usuario OAuth: {email}")
            raise ValidationException(
                f"Este usuario está registrado con {user.auth_provider}. "
                f"Por favor use el método de inicio de sesión correspondiente."
            )

        if not self.check_password(user.id, password):
            self._log_warning(f"Intento de login fallido: contraseña incorrecta para {email}")
            return None

        self._log_info(f"Usuario autenticado exitosamente: {email}")
        return user

    def register(
        self,
        email: str,
        nombre: str,
        apellido: str,
        password: str,
        organizacion_id: int,
        telefono: Optional[str] = None,
        rol: str = 'operario',
        role: str = 'operario',
        auth_provider: str = 'manual'
    ) -> Usuario:
        """
        Registra un nuevo usuario en el sistema.

        Args:
            email: Email del usuario (único)
            nombre: Nombre del usuario
            apellido: Apellido del usuario
            password: Contraseña en texto plano
            organizacion_id: ID de la organización a la que pertenece
            telefono: Teléfono opcional
            rol: Rol legacy del usuario
            role: Rol del nuevo sistema (admin, pm, operario)
            auth_provider: Proveedor de autenticación (manual, google)

        Returns:
            Usuario creado

        Raises:
            ValidationException: Si faltan datos requeridos o el email ya existe
            NotFoundException: Si la organización no existe
        """
        # Validaciones
        if not all([email, nombre, apellido, password, organizacion_id]):
            raise ValidationException(
                "Email, nombre, apellido, contraseña y organización son requeridos"
            )

        email = email.strip().lower()

        # Verificar que la organización existe
        organizacion = Organizacion.query.get(organizacion_id)
        if not organizacion:
            raise NotFoundException('Organizacion', organizacion_id)

        # Verificar que el email no existe
        if self.get_by_email(email):
            raise ValidationException(
                f"El email {email} ya está registrado",
                details={'field': 'email'}
            )

        try:
            # Crear usuario
            user = Usuario(
                email=email,
                nombre=nombre.strip(),
                apellido=apellido.strip(),
                telefono=telefono,
                rol=rol,
                role=role,
                organizacion_id=organizacion_id,
                primary_org_id=organizacion_id,
                auth_provider=auth_provider,
                activo=True,
                plan_activo='prueba',
                fecha_creacion=datetime.utcnow(),
                created_at=datetime.utcnow()
            )

            # Establecer contraseña
            if auth_provider == 'manual' and password:
                user.set_password(password)

            db.session.add(user)
            db.session.flush()  # Para obtener el ID

            # Crear membresía automática
            self.ensure_membership(user.id, organizacion_id, role=role, status='active')

            # Crear onboarding status
            self.ensure_onboarding(user.id)

            # Crear billing profile
            self.ensure_billing_profile(user.id)

            db.session.commit()

            # Invalidar cache de usuarios al crear uno nuevo
            invalidate_pattern('obyra:user:*')

            self._log_info(f"Usuario registrado exitosamente: {email} (ID: {user.id})")
            return user

        except IntegrityError as e:
            db.session.rollback()
            self._log_error(f"Error de integridad al registrar usuario {email}: {str(e)}")
            raise ValidationException(
                "Error al registrar usuario. El email podría estar duplicado.",
                details={'error': str(e)}
            )
        except Exception as e:
            db.session.rollback()
            self._log_error(f"Error al registrar usuario {email}: {str(e)}")
            raise ServiceException(f"Error al registrar usuario: {str(e)}")

    def register_oauth_user(
        self,
        email: str,
        nombre: str,
        apellido: str,
        organizacion_id: int,
        auth_provider: str,
        oauth_id: str,
        profile_picture: Optional[str] = None
    ) -> Usuario:
        """
        Registra un usuario que se autentica mediante OAuth (Google, etc.).

        Args:
            email: Email del usuario
            nombre: Nombre del usuario
            apellido: Apellido del usuario
            organizacion_id: ID de la organización
            auth_provider: Proveedor OAuth (google, etc.)
            oauth_id: ID del usuario en el proveedor OAuth
            profile_picture: URL de la foto de perfil

        Returns:
            Usuario creado
        """
        email = email.strip().lower()

        # Verificar si el usuario ya existe
        existing = self.get_by_email(email)
        if existing:
            # Actualizar info de OAuth si es necesario
            if existing.auth_provider != auth_provider:
                existing.auth_provider = auth_provider
            if auth_provider == 'google':
                existing.google_id = oauth_id
            if profile_picture:
                existing.profile_picture = profile_picture
            db.session.commit()
            return existing

        # Crear nuevo usuario OAuth (sin contraseña)
        return self.register(
            email=email,
            nombre=nombre,
            apellido=apellido,
            password='',  # No se usa para OAuth
            organizacion_id=organizacion_id,
            auth_provider=auth_provider,
            role='operario'
        )

    # ============================================================
    # PASSWORD MANAGEMENT
    # ============================================================

    def set_password(self, user_id: int, password: str) -> None:
        """
        Establece la contraseña de un usuario.

        Args:
            user_id: ID del usuario
            password: Nueva contraseña en texto plano

        Raises:
            ValidationException: Si la contraseña está vacía
            NotFoundException: Si el usuario no existe
        """
        if not password:
            raise ValidationException("La contraseña no puede estar vacía")

        user = self.get_by_id_or_fail(user_id)
        user.password_hash = generate_password_hash(password)

        db.session.commit()

        # Invalidar cache del usuario modificado
        invalidate_pattern('obyra:user:*')

        self._log_info(f"Contraseña actualizada para usuario {user_id}")

    def check_password(self, user_id: int, password: str) -> bool:
        """
        Verifica si una contraseña es correcta para un usuario.

        Args:
            user_id: ID del usuario
            password: Contraseña a verificar

        Returns:
            True si la contraseña es correcta, False en caso contrario
        """
        user = self.get_by_id(user_id)
        if not user or not user.password_hash:
            return False
        return check_password_hash(user.password_hash, password)

    def reset_password(self, user_id: int, new_password: str) -> None:
        """
        Resetea la contraseña de un usuario.
        Alias de set_password para mayor claridad semántica.

        Args:
            user_id: ID del usuario
            new_password: Nueva contraseña
        """
        self.set_password(user_id, new_password)
        self._log_info(f"Contraseña reseteada para usuario {user_id}")

    def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str
    ) -> None:
        """
        Cambia la contraseña de un usuario verificando primero la actual.

        Args:
            user_id: ID del usuario
            current_password: Contraseña actual
            new_password: Nueva contraseña

        Raises:
            ValidationException: Si la contraseña actual es incorrecta
        """
        if not self.check_password(user_id, current_password):
            raise ValidationException("La contraseña actual es incorrecta")

        self.set_password(user_id, new_password)
        self._log_info(f"Contraseña cambiada exitosamente para usuario {user_id}")

    # ============================================================
    # MEMBERSHIP MANAGEMENT
    # ============================================================

    def ensure_membership(
        self,
        user_id: int,
        org_id: int,
        role: Optional[str] = None,
        status: str = 'active'
    ) -> OrgMembership:
        """
        Garantiza que exista una membresía para el usuario en la organización.
        Si ya existe, la retorna. Si no existe, la crea.

        Args:
            user_id: ID del usuario
            org_id: ID de la organización
            role: Rol del usuario (admin, pm, operario). Si es None, usa el rol del usuario
            status: Estado de la membresía (active, pending, suspended)

        Returns:
            Membresía existente o creada

        Raises:
            NotFoundException: Si el usuario u organización no existen
        """
        user = self.get_by_id_or_fail(user_id)

        # Verificar que la organización existe
        org = Organizacion.query.get(org_id)
        if not org:
            raise NotFoundException('Organizacion', org_id)

        # Buscar membresía existente no archivada
        existing = OrgMembership.query.filter_by(
            user_id=user_id,
            org_id=org_id,
            archived=False
        ).first()

        if existing:
            return existing

        # Determinar el rol
        if role:
            resolved_role = role
        else:
            resolved_role = user.role if hasattr(user, 'role') and user.role else 'operario'

        # Normalizar rol legacy
        if resolved_role in ('administrador', 'admin', 'administrador_general'):
            resolved_role = 'admin'
        elif resolved_role not in ('admin', 'pm', 'operario'):
            resolved_role = 'operario'

        # Crear nueva membresía
        membership = OrgMembership(
            org_id=org_id,
            user_id=user_id,
            role=resolved_role,
            status=status,
            invited_at=datetime.utcnow()
        )
        db.session.add(membership)

        # Actualizar referencias del usuario si es necesario
        if not user.primary_org_id:
            user.primary_org_id = org_id
        if not user.organizacion_id:
            user.organizacion_id = org_id

        db.session.flush()

        self._log_info(
            f"Membresía creada: usuario {user_id} -> org {org_id} "
            f"(rol: {resolved_role}, status: {status})"
        )

        return membership

    def get_active_memberships(self, user_id: int) -> List[OrgMembership]:
        """
        Obtiene todas las membresías activas (no archivadas) de un usuario.

        Args:
            user_id: ID del usuario

        Returns:
            Lista de membresías activas
        """
        return OrgMembership.query.filter_by(
            user_id=user_id,
            status='active',
            archived=False
        ).all()

    def get_membership_for_org(
        self,
        user_id: int,
        org_id: int
    ) -> Optional[OrgMembership]:
        """
        Obtiene la membresía de un usuario para una organización específica.

        Args:
            user_id: ID del usuario
            org_id: ID de la organización

        Returns:
            Membresía o None si no existe
        """
        return OrgMembership.query.filter_by(
            user_id=user_id,
            org_id=org_id,
            archived=False
        ).first()

    def activate_membership(self, user_id: int, org_id: int) -> OrgMembership:
        """
        Activa una membresía existente.

        Args:
            user_id: ID del usuario
            org_id: ID de la organización

        Returns:
            Membresía activada

        Raises:
            NotFoundException: Si la membresía no existe
        """
        membership = self.get_membership_for_org(user_id, org_id)
        if not membership:
            raise NotFoundException('Membership', f"user:{user_id}, org:{org_id}")

        membership.status = 'active'
        membership.archived = False
        membership.accepted_at = datetime.utcnow()

        db.session.commit()
        self._log_info(f"Membresía activada: usuario {user_id} -> org {org_id}")

        return membership

    def archive_membership(self, user_id: int, org_id: int) -> None:
        """
        Archiva una membresía (soft delete).

        Args:
            user_id: ID del usuario
            org_id: ID de la organización

        Raises:
            NotFoundException: Si la membresía no existe
        """
        membership = self.get_membership_for_org(user_id, org_id)
        if not membership:
            raise NotFoundException('Membership', f"user:{user_id}, org:{org_id}")

        membership.archived = True
        membership.archived_at = datetime.utcnow()

        db.session.commit()
        self._log_info(f"Membresía archivada: usuario {user_id} -> org {org_id}")

    def suspend_membership(self, user_id: int, org_id: int) -> None:
        """
        Suspende una membresía (el usuario no puede acceder temporalmente).

        Args:
            user_id: ID del usuario
            org_id: ID de la organización
        """
        membership = self.get_membership_for_org(user_id, org_id)
        if not membership:
            raise NotFoundException('Membership', f"user:{user_id}, org:{org_id}")

        membership.status = 'suspended'
        db.session.commit()
        self._log_info(f"Membresía suspendida: usuario {user_id} -> org {org_id}")

    def update_membership_role(
        self,
        user_id: int,
        org_id: int,
        new_role: str
    ) -> OrgMembership:
        """
        Actualiza el rol de un usuario en una organización.

        Args:
            user_id: ID del usuario
            org_id: ID de la organización
            new_role: Nuevo rol (admin, pm, operario)

        Returns:
            Membresía actualizada
        """
        if new_role not in ('admin', 'pm', 'operario'):
            raise ValidationException(
                f"Rol inválido: {new_role}. Debe ser: admin, pm u operario"
            )

        membership = self.get_membership_for_org(user_id, org_id)
        if not membership:
            raise NotFoundException('Membership', f"user:{user_id}, org:{org_id}")

        old_role = membership.role
        membership.role = new_role

        db.session.commit()
        self._log_info(
            f"Rol actualizado: usuario {user_id} en org {org_id} "
            f"({old_role} -> {new_role})"
        )

        return membership

    # ============================================================
    # PERMISSIONS & ROLES
    # ============================================================

    def has_role(self, user_id: int, role: str, org_id: Optional[int] = None) -> bool:
        """
        Verifica si un usuario tiene un rol específico.

        Args:
            user_id: ID del usuario
            role: Rol a verificar (admin, pm, operario, etc.)
            org_id: ID de la organización (opcional, usa la actual de la sesión)

        Returns:
            True si el usuario tiene el rol
        """
        user = self.get_by_id(user_id)
        if not user:
            return False

        if not role:
            return False

        target_role = role.strip().lower()

        # Determinar la organización
        if not org_id:
            org_id = session.get('current_org_id')

        # Intentar obtener desde la membresía
        if org_id:
            membership = self.get_membership_for_org(user_id, org_id)
            if membership and membership.status == 'active':
                user_role = (membership.role or '').lower()
                return user_role == target_role

        # Fallback al rol global del usuario
        role_global = (getattr(user, 'role', None) or '').lower()
        if role_global:
            return role_global == target_role

        # Compatibilidad con rol legacy
        rol_legacy = (getattr(user, 'rol', None) or '').lower()
        if rol_legacy in {'administrador', 'admin'} and target_role == 'admin':
            return True

        return False

    def can_access_module(
        self,
        user_id: int,
        module: str
    ) -> bool:
        """
        Verifica si el usuario puede acceder (ver) un módulo.

        Args:
            user_id: ID del usuario
            module: Nombre del módulo

        Returns:
            True si el usuario puede acceder al módulo
        """
        user = self.get_by_id_or_fail(user_id)

        # Verificar override específico de usuario
        user_override = UserModule.query.filter_by(
            user_id=user_id,
            module=module
        ).first()

        if user_override:
            return user_override.can_view

        # Verificar permisos del rol
        role_perm = RoleModule.query.filter_by(
            role=user.rol,
            module=module
        ).first()

        if role_perm:
            return role_perm.can_view

        # Fallback a lógica legacy si no hay configuración RBAC
        return self._legacy_can_access_module(user, module)

    def can_edit_module(
        self,
        user_id: int,
        module: str
    ) -> bool:
        """
        Verifica si el usuario puede editar en un módulo.

        Args:
            user_id: ID del usuario
            module: Nombre del módulo

        Returns:
            True si el usuario puede editar en el módulo
        """
        user = self.get_by_id_or_fail(user_id)

        # Verificar override específico de usuario
        user_override = UserModule.query.filter_by(
            user_id=user_id,
            module=module
        ).first()

        if user_override:
            return user_override.can_edit

        # Verificar permisos del rol
        role_perm = RoleModule.query.filter_by(
            role=user.rol,
            module=module
        ).first()

        if role_perm:
            return role_perm.can_edit

        # Fallback: admins y tecnicos pueden editar la mayoría
        if user.rol in ['administrador', 'tecnico', 'jefe_obra']:
            return True

        return False

    def _legacy_can_access_module(self, user: Usuario, module: str) -> bool:
        """
        Lógica legacy para verificar acceso a módulos.
        Mantiene compatibilidad con el sistema antiguo.
        """
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
            permisos[rol] = [
                'obras', 'presupuestos', 'equipos', 'inventario',
                'marketplaces', 'reportes', 'asistente', 'cotizacion',
                'documentos', 'seguridad'
            ]

        for rol in roles_tecnicos:
            permisos[rol] = [
                'obras', 'presupuestos', 'inventario', 'marketplaces',
                'reportes', 'asistente', 'cotizacion', 'documentos', 'seguridad'
            ]

        for rol in roles_supervision:
            permisos[rol] = [
                'obras', 'inventario', 'marketplaces', 'reportes',
                'asistente', 'documentos', 'seguridad'
            ]

        for rol in roles_administrativos:
            permisos[rol] = [
                'obras', 'presupuestos', 'inventario', 'marketplaces',
                'reportes', 'cotizacion', 'documentos'
            ]

        for rol in roles_operativos:
            permisos[rol] = [
                'obras', 'inventario', 'marketplaces', 'asistente', 'documentos'
            ]

        permisos.update({
            'administrador': [
                'obras', 'presupuestos', 'equipos', 'inventario',
                'marketplaces', 'reportes', 'asistente', 'cotizacion',
                'documentos', 'seguridad'
            ],
            'tecnico': [
                'obras', 'presupuestos', 'inventario', 'marketplaces',
                'reportes', 'asistente', 'cotizacion', 'documentos', 'seguridad'
            ],
            'operario': [
                'obras', 'inventario', 'marketplaces', 'asistente', 'documentos'
            ]
        })

        return module in permisos.get(user.rol, [])

    def is_admin(self, user_id: int) -> bool:
        """
        Verifica si el usuario es administrador.

        Args:
            user_id: ID del usuario

        Returns:
            True si el usuario es admin
        """
        # Primero intentar por rol en membresía
        try:
            if self.has_role(user_id, 'admin'):
                return True
        except Exception:
            pass

        user = self.get_by_id(user_id)
        if not user:
            return False

        # Verificar rol global
        role_global = (getattr(user, 'role', None) or '').lower()
        if role_global in {'admin', 'administrador', 'administrador_general'}:
            return True

        # Verificar rol legacy
        rol_legacy = (getattr(user, 'rol', None) or '').lower()
        if rol_legacy in {'admin', 'administrador', 'administrador_general'}:
            return True

        # Verificar emails especiales con acceso completo
        return self.is_full_admin(user_id)

    def is_full_admin(self, user_id: int) -> bool:
        """
        Verifica si el usuario es administrador completo (sin restricciones de plan).

        Args:
            user_id: ID del usuario

        Returns:
            True si es admin completo
        """
        user = self.get_by_id(user_id)
        if not user:
            return False

        # Usar is_super_admin flag en lugar de emails hardcodeados
        if user.is_super_admin:
            return True

        # Mantener compatibilidad temporal con emails legacy
        # TODO: Remover después de migrar todos los usuarios
        emails_admin_completo = [
            'brenda@gmail.com',
            'admin@obyra.com',
            'obyra.servicios@gmail.com'
        ]
        return user.email in emails_admin_completo

    def set_module_permissions(
        self,
        user_id: int,
        module: str,
        can_view: bool,
        can_edit: bool
    ) -> UserModule:
        """
        Establece permisos específicos para un módulo en un usuario.
        Override de los permisos del rol.

        Args:
            user_id: ID del usuario
            module: Nombre del módulo
            can_view: Si puede ver el módulo
            can_edit: Si puede editar en el módulo

        Returns:
            UserModule creado o actualizado
        """
        user = self.get_by_id_or_fail(user_id)

        user_module = UserModule.query.filter_by(
            user_id=user_id,
            module=module
        ).first()

        if not user_module:
            user_module = UserModule(
                user_id=user_id,
                module=module
            )
            db.session.add(user_module)

        user_module.can_view = can_view
        user_module.can_edit = can_edit

        db.session.commit()
        self._log_info(
            f"Permisos de módulo actualizados: usuario {user_id}, "
            f"módulo {module} (view:{can_view}, edit:{can_edit})"
        )

        return user_module

    # ============================================================
    # ONBOARDING & PROFILE
    # ============================================================

    def ensure_onboarding(self, user_id: int) -> OnboardingStatus:
        """
        Garantiza que exista un registro de onboarding para el usuario.

        Args:
            user_id: ID del usuario

        Returns:
            OnboardingStatus existente o creado
        """
        user = self.get_by_id_or_fail(user_id)

        status = user.onboarding_status
        if not status:
            status = OnboardingStatus(usuario_id=user_id)
            db.session.add(status)
            db.session.flush()
            self._log_info(f"OnboardingStatus creado para usuario {user_id}")

        return status

    def ensure_billing_profile(self, user_id: int) -> BillingProfile:
        """
        Garantiza que exista un perfil de facturación para el usuario.

        Args:
            user_id: ID del usuario

        Returns:
            BillingProfile existente o creado
        """
        user = self.get_by_id_or_fail(user_id)

        profile = user.billing_profile
        if not profile:
            profile = BillingProfile(usuario_id=user_id)
            db.session.add(profile)
            db.session.flush()
            self._log_info(f"BillingProfile creado para usuario {user_id}")

        return profile

    def complete_profile(
        self,
        user_id: int,
        cuit: str,
        direccion: str
    ) -> PerfilUsuario:
        """
        Completa el perfil de usuario con CUIT y dirección.

        Args:
            user_id: ID del usuario
            cuit: CUIT del usuario
            direccion: Dirección del usuario

        Returns:
            PerfilUsuario creado

        Raises:
            ValidationException: Si el CUIT ya existe o faltan datos
        """
        if not cuit or not direccion:
            raise ValidationException("CUIT y dirección son requeridos")

        user = self.get_by_id_or_fail(user_id)

        # Verificar si ya existe perfil
        if user.perfil:
            raise ValidationException("El usuario ya tiene un perfil completo")

        # Verificar que el CUIT no exista
        existing = PerfilUsuario.query.filter_by(cuit=cuit).first()
        if existing:
            raise ValidationException(
                "El CUIT ya está registrado",
                details={'field': 'cuit'}
            )

        try:
            perfil = PerfilUsuario(
                usuario_id=user_id,
                cuit=cuit.strip(),
                direccion=direccion.strip()
            )
            db.session.add(perfil)

            # Marcar onboarding como completado
            onboarding = self.ensure_onboarding(user_id)
            onboarding.mark_profile_completed()

            db.session.commit()

            self._log_info(f"Perfil completado para usuario {user_id}")
            return perfil

        except IntegrityError as e:
            db.session.rollback()
            self._log_error(f"Error de integridad al completar perfil: {str(e)}")
            raise ValidationException(
                "Error al completar perfil. El CUIT podría estar duplicado.",
                details={'error': str(e)}
            )

    def update_billing_profile(
        self,
        user_id: int,
        **data
    ) -> BillingProfile:
        """
        Actualiza el perfil de facturación de un usuario.

        Args:
            user_id: ID del usuario
            **data: Datos a actualizar (razon_social, tax_id, address_line1, etc.)

        Returns:
            BillingProfile actualizado
        """
        profile = self.ensure_billing_profile(user_id)

        allowed_fields = [
            'razon_social', 'tax_id', 'billing_email', 'billing_phone',
            'address_line1', 'address_line2', 'city', 'province',
            'postal_code', 'country', 'cardholder_name', 'card_last4',
            'card_brand', 'card_exp_month', 'card_exp_year'
        ]

        for key, value in data.items():
            if key in allowed_fields and hasattr(profile, key):
                setattr(profile, key, value)

        profile.updated_at = datetime.utcnow()

        # Si se completa información de facturación, marcar onboarding
        if data.get('tax_id') or data.get('razon_social'):
            onboarding = self.ensure_onboarding(user_id)
            onboarding.mark_billing_completed()

        db.session.commit()
        self._log_info(f"BillingProfile actualizado para usuario {user_id}")

        return profile

    def mark_onboarding_complete(self, user_id: int) -> OnboardingStatus:
        """
        Marca el onboarding como completado manualmente.

        Args:
            user_id: ID del usuario

        Returns:
            OnboardingStatus actualizado
        """
        onboarding = self.ensure_onboarding(user_id)
        onboarding.profile_completed = True
        onboarding.billing_completed = True
        onboarding.completed_at = datetime.utcnow()

        db.session.commit()
        self._log_info(f"Onboarding marcado como completo para usuario {user_id}")

        return onboarding

    # ============================================================
    # PLAN & SUBSCRIPTION MANAGEMENT
    # ============================================================

    def is_in_trial(self, user_id: int) -> bool:
        """
        Verifica si el usuario está en periodo de prueba.

        Args:
            user_id: ID del usuario

        Returns:
            True si está en periodo de prueba válido
        """
        user = self.get_by_id_or_fail(user_id)

        if user.plan_activo != 'prueba':
            return False

        if not user.fecha_creacion:
            return True

        fecha_limite = user.fecha_creacion + timedelta(days=30)
        return datetime.utcnow() <= fecha_limite

    def get_trial_days_remaining(self, user_id: int) -> int:
        """
        Calcula los días restantes del periodo de prueba.

        Args:
            user_id: ID del usuario

        Returns:
            Días restantes (0 si no está en prueba)
        """
        user = self.get_by_id_or_fail(user_id)

        if user.plan_activo != 'prueba' or not user.fecha_creacion:
            return 0

        fecha_limite = user.fecha_creacion + timedelta(days=30)
        dias_restantes = (fecha_limite - datetime.utcnow()).days
        return max(0, dias_restantes)

    def has_unrestricted_access(self, user_id: int) -> bool:
        """
        Verifica si el usuario tiene acceso completo al sistema.

        Args:
            user_id: ID del usuario

        Returns:
            True si tiene acceso completo
        """
        user = self.get_by_id_or_fail(user_id)

        # Admins especiales
        if self.is_full_admin(user_id):
            return True

        # Planes activos
        if user.plan_activo in ['standard', 'premium']:
            return True

        # Periodo de prueba válido
        if user.plan_activo == 'prueba' and self.is_in_trial(user_id):
            return True

        return False

    def upgrade_plan(
        self,
        user_id: int,
        new_plan: str,
        expiration_date: Optional[datetime] = None
    ) -> Usuario:
        """
        Actualiza el plan de un usuario.

        Args:
            user_id: ID del usuario
            new_plan: Nuevo plan (prueba, standard, premium)
            expiration_date: Fecha de expiración del plan

        Returns:
            Usuario actualizado
        """
        if new_plan not in ['prueba', 'standard', 'premium']:
            raise ValidationException(
                f"Plan inválido: {new_plan}. "
                f"Debe ser: prueba, standard o premium"
            )

        user = self.get_by_id_or_fail(user_id)
        old_plan = user.plan_activo

        user.plan_activo = new_plan
        user.fecha_expiracion_plan = expiration_date

        db.session.commit()
        self._log_info(
            f"Plan actualizado para usuario {user_id}: {old_plan} -> {new_plan}"
        )

        return user

    # ============================================================
    # UTILITY METHODS
    # ============================================================

    @cache_user_query(ttl=600)  # Cache por 10 minutos
    def get_by_email(self, email: str) -> Optional[Usuario]:
        """
        Obtiene un usuario por su email.
        NOTA: Resultado cacheado por 10 minutos en Redis.

        Args:
            email: Email del usuario

        Returns:
            Usuario o None si no existe
        """
        if not email:
            return None

        email = email.strip().lower()
        return Usuario.query.filter(
            db.func.lower(Usuario.email) == email
        ).first()

    def get_current_org_id(self, user_id: int) -> Optional[int]:
        """
        Obtiene la organización actual del usuario.
        Intenta desde la sesión, luego la primaria, luego la primera activa.

        Args:
            user_id: ID del usuario

        Returns:
            ID de la organización o None
        """
        # Intentar desde g.current_membership
        try:
            current_membership = getattr(g, 'current_membership', None)
            if current_membership and not current_membership.archived:
                return current_membership.org_id
        except (RuntimeError, AttributeError):
            pass

        # Intentar desde la sesión
        try:
            org_id = session.get('current_org_id')
            if org_id:
                return org_id
        except (RuntimeError, AttributeError):
            pass

        user = self.get_by_id(user_id)
        if not user:
            return None

        # Organización del usuario
        if user.organizacion_id:
            return user.organizacion_id

        # Primera membresía activa
        active = self.get_active_memberships(user_id)
        if active:
            return active[0].org_id

        return None

    def activate_user(self, user_id: int) -> Usuario:
        """
        Activa un usuario.

        Args:
            user_id: ID del usuario

        Returns:
            Usuario activado
        """
        user = self.get_by_id_or_fail(user_id)
        user.activo = True
        db.session.commit()
        self._log_info(f"Usuario {user_id} activado")
        return user

    def deactivate_user(self, user_id: int) -> Usuario:
        """
        Desactiva un usuario (no puede iniciar sesión).

        Args:
            user_id: ID del usuario

        Returns:
            Usuario desactivado
        """
        user = self.get_by_id_or_fail(user_id)
        user.activo = False
        db.session.commit()
        self._log_info(f"Usuario {user_id} desactivado")
        return user

    def update_profile_picture(
        self,
        user_id: int,
        picture_url: str
    ) -> Usuario:
        """
        Actualiza la foto de perfil de un usuario.

        Args:
            user_id: ID del usuario
            picture_url: URL de la imagen

        Returns:
            Usuario actualizado
        """
        user = self.get_by_id_or_fail(user_id)
        user.profile_picture = picture_url
        db.session.commit()
        self._log_info(f"Foto de perfil actualizada para usuario {user_id}")
        return user

    def get_users_by_organization(self, org_id: int) -> List[Usuario]:
        """
        Obtiene todos los usuarios de una organización.

        Args:
            org_id: ID de la organización

        Returns:
            Lista de usuarios
        """
        memberships = OrgMembership.query.filter_by(
            org_id=org_id,
            archived=False
        ).all()

        return [m.usuario for m in memberships if m.usuario]

    def search_users(
        self,
        query: str,
        org_id: Optional[int] = None,
        role: Optional[str] = None,
        limit: int = 20
    ) -> List[Usuario]:
        """
        Busca usuarios por nombre, apellido o email.

        Args:
            query: Texto a buscar
            org_id: Filtrar por organización (opcional)
            role: Filtrar por rol (opcional)
            limit: Máximo de resultados

        Returns:
            Lista de usuarios
        """
        search_query = Usuario.query

        if query:
            search_pattern = f"%{query}%"
            search_query = search_query.filter(
                db.or_(
                    Usuario.nombre.ilike(search_pattern),
                    Usuario.apellido.ilike(search_pattern),
                    Usuario.email.ilike(search_pattern)
                )
            )

        if org_id:
            search_query = search_query.filter(
                Usuario.organizacion_id == org_id
            )

        if role:
            search_query = search_query.filter(Usuario.role == role)

        return search_query.limit(limit).all()
