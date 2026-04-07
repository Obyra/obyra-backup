# Storage Service — Guía de migración

OBYRA hoy guarda archivos en `static/uploads/` (filesystem local). Esto bloquea el escalado horizontal: si tenés 2 instancias de la app, un archivo subido a la instancia A no está disponible en la B.

## Solución: `services/storage_service.py`

Una abstracción que soporta:
- **Filesystem local** (default, sin dependencias) — para desarrollo
- **S3** — para producción AWS
- **MinIO** — para producción self-hosted

## Uso

```python
from services.storage_service import storage

# Guardar (igual de simple que file.save())
@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['archivo']
    key = f'obras/{obra_id}/documentos/{file.filename}'
    storage.save(file, key=key, content_type=file.content_type)
    return {'ok': True, 'key': key}

# Leer
content = storage.read('obras/123/documentos/contrato.pdf')

# Generar URL temporal (presigned para S3)
url = storage.get_url('obras/123/documentos/contrato.pdf', expires_in=3600)

# Eliminar
storage.delete('obras/123/documentos/contrato.pdf')
```

## Configuración

### Modo local (default — sin cambios)
```env
STORAGE_BACKEND=local
STORAGE_LOCAL_PATH=./storage
```

### Modo S3 (AWS)
```env
STORAGE_BACKEND=s3
STORAGE_S3_BUCKET=obyra-uploads
STORAGE_S3_REGION=us-east-1
STORAGE_S3_ACCESS_KEY=AKIA...
STORAGE_S3_SECRET_KEY=...
```

### Modo MinIO (self-hosted)
```env
STORAGE_BACKEND=minio
STORAGE_S3_BUCKET=obyra-uploads
STORAGE_S3_REGION=us-east-1
STORAGE_S3_ENDPOINT=https://minio.miempresa.com
STORAGE_S3_ACCESS_KEY=minioadmin
STORAGE_S3_SECRET_KEY=minioadmin
```

Para Railway: usar Cloudflare R2 (compatible con S3, gratis hasta 10GB).

## Plan de migración

### Fase 1 — Adopción gradual (sin riesgo)
Para cada **nuevo** endpoint que sube archivos, usar `storage.save()` en lugar de `file.save()`.

### Fase 2 — Migración de endpoints existentes
Reemplazar uno por uno:

```python
# ANTES:
filepath = os.path.join(app.static_folder, 'uploads', 'obras', str(obra_id), filename)
os.makedirs(os.path.dirname(filepath), exist_ok=True)
file.save(filepath)
db_record.archivo_path = f'uploads/obras/{obra_id}/{filename}'

# DESPUÉS:
key = f'obras/{obra_id}/{filename}'
storage.save(file, key=key, content_type=file.content_type)
db_record.archivo_path = key  # Solo la key, sin /static/uploads/
```

### Fase 3 — Migrar archivos existentes a S3
Script único para mover archivos viejos:

```python
# scripts/migrate_uploads_to_s3.py
from pathlib import Path
from services.storage_service import storage

uploads_dir = Path('static/uploads')
for file_path in uploads_dir.rglob('*'):
    if file_path.is_file():
        key = str(file_path.relative_to(uploads_dir))
        with open(file_path, 'rb') as f:
            storage.save(f, key=key)
        print(f'Migrated: {key}')
```

### Fase 4 — Limpieza
Una vez verificado que todo funciona desde S3, eliminar `static/uploads/`.

## Por qué se hace así

1. **Sin lock-in**: el código no sabe si usa local o S3, solo llama `storage.save()`
2. **Tests fáciles**: en testing usás local, en prod usás S3
3. **Migración gradual**: podés ir endpoint por endpoint
4. **Seguridad**: las URLs son presigned (temporales) en S3, no exponés archivos
5. **Multi-tenant**: las keys siempre incluyen `obras/{obra_id}/...` así que el `secure-uploads` middleware sigue funcionando

## Costo estimado

| Provider | Gratis hasta | Costo después |
|----------|--------------|---------------|
| AWS S3 | 5GB primer año | $0.023/GB/mes + transferencia |
| Cloudflare R2 | 10GB | $0.015/GB/mes, sin egress fee |
| MinIO self-hosted | Ilimitado | Solo el costo del servidor |

Para OBYRA, **Cloudflare R2** es probablemente la mejor opción (sin transferencia paga).
