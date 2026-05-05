# Storage

Carpeta de almacenamiento privado para archivos subidos por usuarios.

**NO se sirve directamente** desde la web. Está fuera de `/static/` por
diseño: las descargas pasan por endpoints protegidos que validan acceso
multi-tenant + crean `audit_log`.

Estructura:

```
storage/
└── uploads/
    └── presupuestos/
        └── <presupuesto_id>/
            └── <sha256_short>.xlsx     # Archivos de pliego (Fase 6.A)
```

Acceso a estos archivos:
- Endpoint `GET /presupuestos/<pid>/archivos/<aid>/descargar`
- El path real (`storage/...`) NO se expone al browser.
- En producción, el web server (gunicorn + Railway) NO debería servir
  esta carpeta como static. Validar al deployar.
