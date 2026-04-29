"""Seed del Directorio Global de Proveedores OBYRA.

Carga los 303 proveedores curados por OBYRA con `scope='global'` y
`organizacion_id IS NULL`, ademas de las 13 zonas geograficas que usan.

Idempotente:
  - Si ya hay >= 50 proveedores globales, SE SALTEA (asume que ya esta cargado).
  - Si no, hace upsert por external_key (crea nuevos, actualiza existentes).
  - Las zonas se buscan/crean por slug.

Llamado desde runtime_migrations.py al arrancar la app (gunicorn).
"""
from datetime import date


def seed_proveedores_globales(db):
    """Aplica el seed. Recibe `db` (SQLAlchemy) ya inicializado con app context."""
    try:
        from seeds.proveedores_globales_data import ZONAS, PROVEEDORES
    except ImportError as e:
        print(f"[WARN] No se pudo importar data del directorio global: {e}")
        return

    from models.proveedores_oc import ProveedorOC, Zona
    from sqlalchemy import func

    # Guarda de idempotencia: si ya hay >=50 globales, no re-cargamos.
    # Esto evita correr 303 selects en cada deploy una vez que ya esta cargado.
    try:
        existentes = db.session.query(func.count(ProveedorOC.id)).filter(
            ProveedorOC.scope == 'global'
        ).scalar() or 0
    except Exception as e:
        print(f"[WARN] Seed proveedores globales: no se pudo contar (tabla aun no migrada?): {e}")
        return

    if existentes >= 50:
        # Ya esta cargado, salir rapido.
        return

    print(f"[SEED] Cargando Directorio OBYRA (existentes: {existentes}, target: {len(PROVEEDORES)})...")

    # 1) Asegurar zonas
    zonas_cache = {z.slug: z for z in Zona.query.all()}
    zonas_creadas = 0
    for z in ZONAS:
        slug = z['slug']
        if slug not in zonas_cache:
            nueva = Zona(
                nombre=z['nombre'][:120],
                slug=slug[:140],
                provincia=(z.get('provincia') or '')[:100] or None,
                activa=True,
            )
            db.session.add(nueva)
            db.session.flush()
            zonas_cache[slug] = nueva
            zonas_creadas += 1
    if zonas_creadas:
        db.session.commit()
        print(f"[SEED] Zonas creadas: {zonas_creadas}")

    # 2) Upsert proveedores
    creados = 0
    actualizados = 0
    errores = 0

    for i, p in enumerate(PROVEEDORES, start=1):
        try:
            external_key = p['external_key']
            zona_slug = p.get('zona_slug')
            zona_id = zonas_cache[zona_slug].id if zona_slug and zona_slug in zonas_cache else None

            campos = dict(
                razon_social=p.get('razon_social'),
                categoria=p.get('categoria'),
                subcategoria=p.get('subcategoria'),
                tier=p.get('tier'),
                provincia=p.get('provincia'),
                zona_id=zona_id,
                ubicacion_detalle=p.get('ubicacion_detalle'),
                cobertura=p.get('cobertura'),
                web=p.get('web'),
                telefono=p.get('telefono'),
                email=p.get('email'),
                direccion=p.get('direccion'),
                tipo_alianza=p.get('tipo_alianza'),
                notas=p.get('notas'),
            )

            existente = ProveedorOC.query.filter_by(scope='global', external_key=external_key).first()
            if existente:
                for k, v in campos.items():
                    setattr(existente, k, v)
                actualizados += 1
            else:
                nuevo = ProveedorOC(
                    scope='global',
                    organizacion_id=None,
                    external_key=external_key,
                    activo=True,
                    tipo='materiales',
                    **campos,
                )
                db.session.add(nuevo)
                creados += 1

            # commit cada 50 para no acumular sesion gigante
            if i % 50 == 0:
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            errores += 1
            print(f"[SEED] Error en proveedor {p.get('razon_social')!r}: {e}")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[SEED] Error commit final: {e}")

    print(f"[SEED] Directorio OBYRA: {creados} creados, {actualizados} actualizados, {errores} errores")
