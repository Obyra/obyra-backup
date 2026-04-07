"""
Storage Service — Abstracción de almacenamiento de archivos
============================================================

Provee una API unificada para guardar/leer/eliminar archivos, soportando:
- Filesystem local (default, sin dependencias)
- S3 (boto3)
- MinIO (boto3 con endpoint custom)

Configuración via variables de entorno:
    STORAGE_BACKEND=local|s3|minio  (default: local)

    Para S3/MinIO:
    STORAGE_S3_BUCKET=obyra-uploads
    STORAGE_S3_REGION=us-east-1
    STORAGE_S3_ENDPOINT=https://s3.amazonaws.com  (omitir para AWS S3 default)
    STORAGE_S3_ACCESS_KEY=...
    STORAGE_S3_SECRET_KEY=...

    Para local:
    STORAGE_LOCAL_PATH=./storage  (default)

Uso:
    from services.storage_service import storage

    # Guardar archivo desde un FileStorage de Flask
    path = storage.save(file_obj, key='obras/123/contrato.pdf')

    # Leer
    content = storage.read('obras/123/contrato.pdf')

    # URL para servirlo (si es S3, devuelve presigned URL)
    url = storage.get_url('obras/123/contrato.pdf', expires_in=3600)

    # Eliminar
    storage.delete('obras/123/contrato.pdf')
"""

import os
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, BinaryIO, Union


logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Interfaz abstracta para backends de almacenamiento."""

    @abstractmethod
    def save(self, file_obj: BinaryIO, key: str, content_type: Optional[str] = None) -> str:
        """Guarda un archivo y devuelve la key (path interno)."""
        pass

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Lee el contenido completo de un archivo."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Elimina un archivo. Devuelve True si se eliminó."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Verifica si existe un archivo."""
        pass

    @abstractmethod
    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Devuelve URL para acceder al archivo (presigned para S3)."""
        pass


class LocalStorageBackend(StorageBackend):
    """Storage en filesystem local."""

    def __init__(self, base_path: str = './storage'):
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _full_path(self, key: str) -> Path:
        # Prevenir path traversal
        key = key.lstrip('/').replace('..', '')
        path = (self.base_path / key).resolve()
        if not str(path).startswith(str(self.base_path)):
            raise ValueError(f'Invalid key: {key}')
        return path

    def save(self, file_obj: BinaryIO, key: str, content_type: Optional[str] = None) -> str:
        path = self._full_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        if hasattr(file_obj, 'save'):
            # Es un Flask FileStorage
            file_obj.save(str(path))
        else:
            with open(path, 'wb') as f:
                if hasattr(file_obj, 'read'):
                    f.write(file_obj.read())
                else:
                    f.write(file_obj)

        return key

    def read(self, key: str) -> bytes:
        path = self._full_path(key)
        with open(path, 'rb') as f:
            return f.read()

    def delete(self, key: str) -> bool:
        path = self._full_path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        return self._full_path(key).exists()

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        # Para storage local, devolvemos la URL del endpoint /secure-uploads/
        return f'/secure-uploads/{key}'


class S3StorageBackend(StorageBackend):
    """Storage en S3 / MinIO usando boto3."""

    def __init__(self, bucket: str, region: str = 'us-east-1',
                 endpoint_url: Optional[str] = None,
                 access_key: Optional[str] = None,
                 secret_key: Optional[str] = None):
        try:
            import boto3
            from botocore.client import Config
        except ImportError:
            raise ImportError(
                'boto3 no está instalado. Instalar con: pip install boto3'
            )

        self.bucket = bucket
        self.region = region

        kwargs = {'region_name': region}
        if endpoint_url:
            kwargs['endpoint_url'] = endpoint_url
            kwargs['config'] = Config(signature_version='s3v4')
        if access_key:
            kwargs['aws_access_key_id'] = access_key
        if secret_key:
            kwargs['aws_secret_access_key'] = secret_key

        self.client = boto3.client('s3', **kwargs)

        # Verificar que el bucket existe (no fallar, solo loguear)
        try:
            self.client.head_bucket(Bucket=bucket)
        except Exception as e:
            logger.warning(f'[Storage] No se pudo verificar bucket {bucket}: {e}')

    def save(self, file_obj: BinaryIO, key: str, content_type: Optional[str] = None) -> str:
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type

        if hasattr(file_obj, 'stream'):
            # Es un Flask FileStorage
            self.client.upload_fileobj(file_obj.stream, self.bucket, key, ExtraArgs=extra_args)
        else:
            self.client.upload_fileobj(file_obj, self.bucket, key, ExtraArgs=extra_args)

        return key

    def read(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response['Body'].read()

    def delete(self, key: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.error(f'[Storage] Error eliminando {key}: {e}')
            return False

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': key},
            ExpiresIn=expires_in,
        )


def _create_backend() -> StorageBackend:
    """Factory que crea el backend según STORAGE_BACKEND env var."""
    backend_type = os.environ.get('STORAGE_BACKEND', 'local').lower()

    if backend_type in ('s3', 'minio'):
        return S3StorageBackend(
            bucket=os.environ['STORAGE_S3_BUCKET'],
            region=os.environ.get('STORAGE_S3_REGION', 'us-east-1'),
            endpoint_url=os.environ.get('STORAGE_S3_ENDPOINT'),
            access_key=os.environ.get('STORAGE_S3_ACCESS_KEY'),
            secret_key=os.environ.get('STORAGE_S3_SECRET_KEY'),
        )
    else:
        return LocalStorageBackend(
            base_path=os.environ.get('STORAGE_LOCAL_PATH', './storage')
        )


# Singleton: instancia global del storage
storage: StorageBackend = _create_backend()
