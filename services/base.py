"""
Base Service Class
==================
Clase base para todos los servicios del sistema.
Proporciona funcionalidad común y patrones reutilizables.
"""

from typing import TypeVar, Generic, Type, Optional, List, Any
from flask import current_app
from extensions import db
from sqlalchemy.exc import SQLAlchemyError


T = TypeVar('T')


class ServiceException(Exception):
    """Excepción base para errores de servicios"""
    def __init__(self, message: str, code: str = 'SERVICE_ERROR', details: Optional[dict] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class ValidationException(ServiceException):
    """Excepción para errores de validación"""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, code='VALIDATION_ERROR', details=details)


class NotFoundException(ServiceException):
    """Excepción cuando no se encuentra un recurso"""
    def __init__(self, resource: str, identifier: Any):
        message = f"{resource} con id {identifier} no encontrado"
        super().__init__(message, code='NOT_FOUND', details={'resource': resource, 'id': identifier})


class PermissionDeniedException(ServiceException):
    """Excepción cuando el usuario no tiene permisos"""
    def __init__(self, action: str, resource: str):
        message = f"Permiso denegado para {action} en {resource}"
        super().__init__(message, code='PERMISSION_DENIED', details={'action': action, 'resource': resource})


class BaseService(Generic[T]):
    """
    Servicio base con operaciones CRUD comunes.

    Los servicios específicos deben heredar de esta clase y definir:
    - model_class: La clase del modelo SQLAlchemy
    """

    model_class: Type[T] = None

    def __init__(self):
        if self.model_class is None:
            raise NotImplementedError("model_class debe estar definido en la subclase")

    # ===== CRUD Operations =====

    def get_by_id(self, id: int) -> Optional[T]:
        """Obtiene un registro por ID"""
        return self.model_class.query.get(id)

    def get_by_id_or_fail(self, id: int) -> T:
        """Obtiene un registro por ID o lanza excepción"""
        instance = self.get_by_id(id)
        if not instance:
            raise NotFoundException(self.model_class.__name__, id)
        return instance

    def get_all(self, **filters) -> List[T]:
        """Obtiene todos los registros con filtros opcionales"""
        query = self.model_class.query
        if filters:
            query = query.filter_by(**filters)
        return query.all()

    def create(self, **data) -> T:
        """Crea un nuevo registro"""
        try:
            instance = self.model_class(**data)
            db.session.add(instance)
            db.session.commit()
            self._log_info(f"Created {self.model_class.__name__} with id {instance.id}")
            return instance
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error creating {self.model_class.__name__}: {str(e)}")
            raise ServiceException(f"Error al crear {self.model_class.__name__}: {str(e)}")

    def update(self, id: int, **data) -> T:
        """Actualiza un registro existente"""
        instance = self.get_by_id_or_fail(id)
        try:
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            db.session.commit()
            self._log_info(f"Updated {self.model_class.__name__} with id {id}")
            return instance
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error updating {self.model_class.__name__}: {str(e)}")
            raise ServiceException(f"Error al actualizar {self.model_class.__name__}: {str(e)}")

    def delete(self, id: int) -> bool:
        """Elimina un registro"""
        instance = self.get_by_id_or_fail(id)
        try:
            db.session.delete(instance)
            db.session.commit()
            self._log_info(f"Deleted {self.model_class.__name__} with id {id}")
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error deleting {self.model_class.__name__}: {str(e)}")
            raise ServiceException(f"Error al eliminar {self.model_class.__name__}: {str(e)}")

    def exists(self, id: int) -> bool:
        """Verifica si existe un registro"""
        return self.model_class.query.filter_by(id=id).first() is not None

    def count(self, **filters) -> int:
        """Cuenta registros con filtros opcionales"""
        query = self.model_class.query
        if filters:
            query = query.filter_by(**filters)
        return query.count()

    # ===== Transaction Management =====

    def commit(self):
        """Commit explícito de la sesión"""
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            raise ServiceException(f"Error al guardar cambios: {str(e)}")

    def rollback(self):
        """Rollback explícito de la sesión"""
        db.session.rollback()

    def flush(self):
        """Flush de la sesión sin commit"""
        try:
            db.session.flush()
        except SQLAlchemyError as e:
            db.session.rollback()
            raise ServiceException(f"Error al ejecutar flush: {str(e)}")

    # ===== Logging Helpers =====

    def _log_info(self, message: str):
        """Log de información"""
        if current_app:
            current_app.logger.info(f"[{self.__class__.__name__}] {message}")

    def _log_error(self, message: str):
        """Log de error"""
        if current_app:
            current_app.logger.error(f"[{self.__class__.__name__}] {message}")

    def _log_warning(self, message: str):
        """Log de advertencia"""
        if current_app:
            current_app.logger.warning(f"[{self.__class__.__name__}] {message}")

    def _log_debug(self, message: str):
        """Log de debug"""
        if current_app:
            current_app.logger.debug(f"[{self.__class__.__name__}] {message}")


class ReadOnlyService(BaseService[T]):
    """
    Servicio base de solo lectura.
    Elimina los métodos de escritura.
    """

    def create(self, **data):
        raise PermissionDeniedException('create', self.model_class.__name__)

    def update(self, id: int, **data):
        raise PermissionDeniedException('update', self.model_class.__name__)

    def delete(self, id: int):
        raise PermissionDeniedException('delete', self.model_class.__name__)
