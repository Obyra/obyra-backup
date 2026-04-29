"""
Importador simple de Excel de licitacion.

Crea un Presupuesto + ItemPresupuesto a partir de un Excel con columnas
basicas (descripcion, unidad, cantidad, precio_unit opcional).

Flujo:
  GET  /presupuestos/importar-licitacion         -> formulario
  POST /presupuestos/importar-licitacion         -> procesa archivo y crea presupuesto
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import (render_template, request, flash, redirect, url_for,
                   current_app, abort)
from flask_login import login_required, current_user

from blueprint_presupuestos import presupuestos_bp
from extensions import db
from models import Presupuesto, ItemPresupuesto, Cliente
from services.memberships import get_current_org_id


def _parse_decimal(val, default=0):
    if val is None or val == '':
        return Decimal(str(default))
    try:
        # Aceptar formato con coma decimal (AR)
        s = str(val).replace('.', '').replace(',', '.')
        # Si ya viene con punto decimal (EN), mejor intentar directo primero
        try:
            return Decimal(str(val))
        except (InvalidOperation, ValueError):
            return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(str(default))


def _detectar_columnas(headers):
    """Busca indices de columnas en el header (case insensitive, soporta acentos y abreviaturas).

    Retorna dict con idx_desc, idx_unidad, idx_cantidad, idx_precio (None si no encuentra).
    """
    idx = {'desc': None, 'unidad': None, 'cantidad': None, 'precio': None}

    def _norm(t):
        if t is None:
            return ''
        # Quitar acentos
        import unicodedata
        s = unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode().lower().strip()
        return s

    for i, h in enumerate(headers):
        if h is None:
            continue
        h_norm = _norm(h)

        # Descripcion: matches exactos o con keywords, evita match con "descripcion" si ya tiene
        if idx['desc'] is None:
            if h_norm in ('descripcion', 'descripcion item', 'detalle', 'item', 'articulo', 'concepto') \
               or 'descripcion' in h_norm or h_norm.startswith('descrip') \
               or h_norm == 'detalle' or 'concepto' in h_norm:
                idx['desc'] = i
                continue

        # Unidad: "Un", "Unid", "Unidad", "UM", "Medida"
        if idx['unidad'] is None:
            if h_norm in ('un', 'und', 'unid', 'unidad', 'um', 'medida', 'u/m', 'unid.', 'un.'):
                idx['unidad'] = i
                continue

        # Cantidad: "Cant", "Cantidad", "Cdad", "Q"
        if idx['cantidad'] is None:
            if h_norm in ('cant', 'cantidad', 'cdad', 'q', 'cant.') or h_norm.startswith('cant'):
                idx['cantidad'] = i
                continue

        # Precio unitario: "Precio Unit", "P. Unit", "$/un", "Precio/un", etc.
        # Importante: priorizar "$/un" o "precio/un" (precio unitario) sobre "$/total"
        if idx['precio'] is None:
            if h_norm in ('precio unitario', 'precio unit', 'p. unit', 'p.unit', 'pu',
                         'precio/un', 'precio unit.', 'pu.', 'precio') \
               or h_norm.startswith('$/un') or h_norm.startswith('$ un') \
               or h_norm == '$/un' or '/un' in h_norm and 'total' not in h_norm:
                idx['precio'] = i
                continue
    return idx


def _buscar_fila_header(rows, max_search=50):
    """Busca la primera fila que contenga keywords de header tipico.

    Retorna (idx, score). Score mas alto = mejor match.
    """
    import unicodedata

    def _norm(t):
        if t is None:
            return ''
        return unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode().lower()

    keywords = ['descripcion', 'detalle', 'cantidad', 'cant', 'unidad', 'precio', 'rubro', 'concepto', 'item']
    best_idx = None
    best_score = 0

    for i, row in enumerate(rows[:max_search]):
        score = 0
        for cell in row:
            if cell is None:
                continue
            cell_norm = _norm(cell).strip()
            for kw in keywords:
                if cell_norm == kw or kw in cell_norm:
                    score += 1
                    break
        if score > best_score:
            best_score = score
            best_idx = i

    if best_score >= 2:  # al menos 2 keywords coinciden
        return best_idx, best_score
    return None, 0


def _es_numero_validos(val):
    """True si val parsea a Decimal > 0."""
    try:
        d = _parse_decimal(val)
        return d > 0
    except Exception:
        return False


def _parsear_xlsx(file_stream):
    """Lee el xlsx (todas las hojas) y retorna lista de items con etapa detectada.

    Detecta rubros/secciones (filas sin cantidad pero con descripcion) y los asigna
    como 'etapa_nombre' a los items que vienen abajo.
    """
    import openpyxl
    import re
    wb = openpyxl.load_workbook(file_stream, data_only=True)

    items_total = []

    for sname in wb.sheetnames:
        ws = wb[sname]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        header_idx, score = _buscar_fila_header(rows)
        if header_idx is None:
            continue

        headers = list(rows[header_idx])
        idx = _detectar_columnas(headers)

        if idx['desc'] is None or idx['cantidad'] is None:
            continue

        # Saltar sub-header tipico ("$/un", "$/total")
        start_data = header_idx + 1
        if start_data < len(rows):
            sub = rows[start_data]
            sub_txt = ' '.join(str(c).lower() for c in sub if c is not None)
            cells_no_empty = len([c for c in sub if c is not None and str(c).strip() != ''])
            if ('$/' in sub_txt or '$' in sub_txt) and cells_no_empty <= 8:
                start_data += 1

        # Detectar columna de "rubro" o numero (ej: "1", "1.01", "2.05")
        # En el header puede llamarse "Rubro", "Codigo", "Cod", "Item No", etc.
        idx_rubro = None
        for i, h in enumerate(headers):
            if h is None:
                continue
            h_low = str(h).lower().strip()
            if h_low in ('rubro', 'codigo', 'cod', 'cod.', 'item', 'no', 'nro', 'n°', '#'):
                idx_rubro = i
                break

        # Patron para detectar codigos jerarquicos: "1", "1.01", "2.5.3"
        patron_codigo = re.compile(r'^\d+(\.\d+)*$')

        etapa_actual = None  # nombre de la seccion/rubro actual

        for row_i, row in enumerate(rows[start_data:], start=start_data + 1):
            if not row or all(c is None or str(c).strip() == '' for c in row):
                continue

            desc_raw = row[idx['desc']] if idx['desc'] < len(row) else None
            if not desc_raw or str(desc_raw).strip() == '':
                continue
            desc = str(desc_raw).strip()

            cant_raw = row[idx['cantidad']] if idx['cantidad'] is not None and idx['cantidad'] < len(row) else None
            tiene_cantidad = cant_raw is not None and str(cant_raw).strip() != '' and _es_numero_validos(cant_raw)

            # Detectar si es una fila de RUBRO/seccion (sin cantidad o con codigo de nivel 1)
            codigo = None
            if idx_rubro is not None and idx_rubro < len(row) and row[idx_rubro] is not None:
                codigo = str(row[idx_rubro]).strip()

            # Es rubro si: no tiene cantidad valida AND tiene una descripcion en mayusculas o codigo de 1 nivel
            # Palabras que NO son rubros sino totales/subtotales
            desc_lower = desc.lower()
            es_total = any(kw in desc_lower for kw in [
                'total', 'subtotal', 'resumen', 'gran total', 'suma',
                'iva', 'descuento', 'bonificacion', 'bonificación',
            ])

            es_rubro = False
            if not tiene_cantidad and not es_total:
                # Caso 1: codigo de un solo nivel (ej: "1", "2", "3")
                if codigo and patron_codigo.match(codigo) and '.' not in codigo:
                    es_rubro = True
                # Caso 2: descripcion sin codigo pero parece header (mayusculas o sin numeros)
                elif desc.upper() == desc and len(desc) > 3 and len(desc) < 80:
                    es_rubro = True

            if es_rubro:
                etapa_actual = desc[:100]
                continue

            # Si es un total/subtotal, saltar
            if es_total and not tiene_cantidad:
                continue

            # Si no tiene cantidad valida y no es rubro, saltar (puede ser subtotal, total, etc.)
            if not tiene_cantidad:
                continue

            try:
                cantidad_d = _parse_decimal(cant_raw)
            except Exception:
                continue
            if cantidad_d <= 0:
                continue

            unidad = row[idx['unidad']] if idx['unidad'] is not None and idx['unidad'] < len(row) else None
            precio = row[idx['precio']] if idx['precio'] is not None and idx['precio'] < len(row) else 0

            try:
                precio_d = _parse_decimal(precio)
            except Exception:
                precio_d = Decimal('0')

            items_total.append({
                'descripcion': desc[:300],
                'unidad': str(unidad).strip()[:20] if unidad else 'un',
                'cantidad': cantidad_d,
                'precio_unitario': precio_d,
                'total': cantidad_d * precio_d,
                'etapa_nombre': etapa_actual,
                'codigo': codigo,
            })

    return items_total if items_total else None


def _guardar_archivo_temp(file_storage):
    """Guarda el archivo subido en /tmp con un UUID y retorna el token."""
    import uuid
    import os
    token = str(uuid.uuid4())
    tmp_dir = '/tmp/obyra_excel_import'
    os.makedirs(tmp_dir, exist_ok=True)
    path = os.path.join(tmp_dir, f"{token}.xlsx")
    file_storage.stream.seek(0)
    file_storage.save(path)
    return token, path


def _path_archivo_temp(token):
    import os
    path = os.path.join('/tmp/obyra_excel_import', f"{token}.xlsx")
    return path if os.path.exists(path) else None


def _persistir_pliego(presu, temp_path, nombre_original=None):
    """Copia el Excel del pliego desde /tmp a static/uploads/pliegos/ para que
    quede como documento contractual del presupuesto (y luego de la obra).

    Guarda la ruta relativa (partiendo de 'static/') en presu.archivo_pliego_path
    y un nombre amigable en presu.archivo_pliego_nombre. No falla si no puede
    copiar — solo loggea y sigue.
    """
    import os
    import shutil
    try:
        base_dir = os.path.join('static', 'uploads', 'pliegos')
        os.makedirs(base_dir, exist_ok=True)
        dest_rel = os.path.join('uploads', 'pliegos', f'pres_{presu.id}.xlsx')
        dest_abs = os.path.join('static', dest_rel)
        shutil.copyfile(temp_path, dest_abs)
        presu.archivo_pliego_path = dest_rel.replace('\\', '/')
        presu.archivo_pliego_nombre = (
            nombre_original or f'Pliego_{presu.numero}.xlsx'
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning(f'No se pudo persistir pliego: {e}')


def _leer_preview(path, max_rows=30):
    """Retorna las primeras N filas + columnas detectadas."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    sheets = []
    for sname in wb.sheetnames:
        ws = wb[sname]
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True, max_row=max_rows)):
            rows.append([('' if c is None else str(c)[:80]) for c in row])
        max_cols = max((len(r) for r in rows), default=0)
        # Padding para que todas las filas tengan misma cantidad de columnas
        for r in rows:
            while len(r) < max_cols:
                r.append('')
        sheets.append({'nombre': sname, 'rows': rows, 'num_cols': max_cols})
    return sheets


def _crear_presupuesto_desde_items(org_id, cliente_id, numero, vigencia_dias, nombre_obra, items, modo_licitacion=True, ubicacion=None, ubicacion_lat=None, ubicacion_lng=None, ubicacion_normalizada=None, naturaleza_proyecto=None):
    """Helper compartido para crear el presupuesto + items.

    Si modo_licitacion=True (default), los precios del Excel se ignoran y
    los items se crean con precio_unitario=0 para que los carguen los proveedores.

    `naturaleza_proyecto` (obra_nueva | remodelacion | ampliacion) se persiste
    en `datos_proyecto` para que el modulo Ejecutivo (APU) filtre/sugiera las
    etapas internas que aplican al tipo de obra.
    """
    import json
    from calculadora_ia import normalizar_naturaleza_proyecto
    datos_proyecto = {
        'nombre_obra': nombre_obra,
        'modo_creacion': 'excel_licitacion',
        'modo_licitacion': modo_licitacion,
        'naturaleza_proyecto': normalizar_naturaleza_proyecto(naturaleza_proyecto),
    }
    if ubicacion:
        datos_proyecto['ubicacion'] = ubicacion
    presu = Presupuesto(
        numero=numero,
        organizacion_id=org_id,
        cliente_id=cliente_id,
        fecha=date.today(),
        vigencia_dias=vigencia_dias,
        estado='borrador',
        datos_proyecto=json.dumps(datos_proyecto),
        ubicacion_texto=(ubicacion or None),
        ubicacion_normalizada=(ubicacion_normalizada or None),
        geo_latitud=ubicacion_lat,
        geo_longitud=ubicacion_lng,
        currency='ARS',
    )
    db.session.add(presu)
    db.session.flush()

    from services.etapa_matcher import matchear_etapa_para_item

    subtotal = Decimal('0')
    for it in items:
        # Intentar matchear con etapa estandar del sistema
        etapa_excel = it.get('etapa_nombre')
        etapa_estandar = matchear_etapa_para_item(it['descripcion'], etapa_excel)
        # Usar la estandar si hay match, sino la del Excel
        etapa_final = etapa_estandar or etapa_excel

        precio = Decimal('0') if modo_licitacion else it['precio_unitario']
        total_item = it['cantidad'] * precio

        ip = ItemPresupuesto(
            presupuesto_id=presu.id,
            tipo='material',
            descripcion=it['descripcion'],
            unidad=it['unidad'],
            cantidad=it['cantidad'],
            precio_unitario=precio,
            total=total_item,
            origen='importado',
            currency='ARS',
            etapa_nombre=etapa_final,
        )
        db.session.add(ip)
        subtotal += total_item

    presu.subtotal_materiales = subtotal
    presu.total_sin_iva = subtotal
    iva_pct = Decimal('21')
    presu.iva_porcentaje = iva_pct
    presu.total_con_iva = subtotal + (subtotal * iva_pct / Decimal('100'))
    db.session.commit()
    return presu


@presupuestos_bp.route('/importar-licitacion', methods=['GET', 'POST'])
@login_required
def importar_licitacion():
    """Formulario + procesamiento de importacion de Excel de licitacion."""
    if not current_user.puede_gestionar():
        flash('No tienes permisos para crear presupuestos', 'danger')
        return redirect(url_for('presupuestos.lista'))

    org_id = get_current_org_id()
    if not org_id:
        flash('Seleccioná una organización.', 'warning')
        return redirect(url_for('auth.seleccionar_organizacion'))

    clientes = Cliente.query.filter_by(
        organizacion_id=org_id, activo=True
    ).order_by(Cliente.nombre).all()

    if request.method == 'GET':
        # Numero sugerido
        fecha_hoy = date.today().strftime('%Y%m%d')
        ultimo = (Presupuesto.query
                  .filter_by(organizacion_id=org_id)
                  .filter(Presupuesto.numero.like(f'PRES-{fecha_hoy}-%'))
                  .order_by(Presupuesto.id.desc()).first())
        if ultimo and ultimo.numero:
            try:
                n = int(ultimo.numero.split('-')[-1]) + 1
                numero_sug = f"PRES-{fecha_hoy}-{n:03d}"
            except (ValueError, IndexError):
                numero_sug = f"PRES-{fecha_hoy}-001"
        else:
            numero_sug = f"PRES-{fecha_hoy}-001"

        import os as _os
        return render_template('presupuestos/importar_licitacion.html',
                               clientes=clientes,
                               numero_sugerido=numero_sug,
                               google_maps_key=_os.environ.get('GOOGLE_MAPS_API_KEY', ''))

    # POST
    archivo = request.files.get('archivo_excel')
    nombre_obra = (request.form.get('nombre_obra') or '').strip()
    cliente_id = request.form.get('cliente_id', type=int)
    numero = (request.form.get('numero') or '').strip()
    vigencia_dias = request.form.get('vigencia_dias', 30, type=int)
    modo_licitacion = request.form.get('modo_licitacion') == '1'
    ubicacion = (request.form.get('ubicacion') or '').strip() or None
    ubicacion_lat = request.form.get('ubicacion_lat', type=float)
    ubicacion_lng = request.form.get('ubicacion_lng', type=float)
    ubicacion_normalizada = (request.form.get('ubicacion_normalizada') or '').strip() or None
    naturaleza_proyecto = (request.form.get('naturaleza_proyecto') or 'obra_nueva').strip()

    if not archivo or not archivo.filename:
        flash('Subí un archivo Excel', 'danger')
        return redirect(url_for('presupuestos.importar_licitacion'))

    if not archivo.filename.lower().endswith(('.xlsx', '.xls')):
        flash('El archivo debe ser .xlsx o .xls', 'danger')
        return redirect(url_for('presupuestos.importar_licitacion'))

    if not nombre_obra:
        flash('Ingresá un nombre de obra', 'danger')
        return redirect(url_for('presupuestos.importar_licitacion'))

    # Detectar duplicado: presupuesto reciente con mismo nombre_obra
    forzar = request.form.get('forzar_duplicado') == '1'
    if not forzar:
        from datetime import timedelta
        umbral = datetime.utcnow() - timedelta(hours=24)
        # Buscar presupuestos del mismo dia con descripcion similar,
        # excluyendo los eliminados/perdidos (no deben bloquear nueva creacion).
        estados_excluidos = ('eliminado', 'perdido')
        if hasattr(Presupuesto, 'created_at'):
            recientes = Presupuesto.query.filter(
                Presupuesto.organizacion_id == org_id,
                Presupuesto.created_at >= umbral,
                ~Presupuesto.estado.in_(estados_excluidos),
            ).all()
        else:
            recientes = Presupuesto.query.filter(
                Presupuesto.organizacion_id == org_id,
                Presupuesto.fecha == date.today(),
                ~Presupuesto.estado.in_(estados_excluidos),
            ).all()
        for p in recientes:
            try:
                import json
                dp = json.loads(p.datos_proyecto) if p.datos_proyecto else {}
                if (dp.get('nombre_obra') or '').strip().lower() == nombre_obra.lower():
                    flash(
                        f'Ya existe un presupuesto reciente para "{nombre_obra}" ({p.numero}). '
                        f'Si querés crear uno nuevo igual, tildá "Crear de todas formas" y reintentá.',
                        'warning'
                    )
                    return redirect(url_for('presupuestos.importar_licitacion'))
            except Exception:
                continue

    # Numero: usar sugerido si no se provee
    if not numero:
        fecha_hoy = date.today().strftime('%Y%m%d')
        ultimo = (Presupuesto.query
                  .filter_by(organizacion_id=org_id)
                  .filter(Presupuesto.numero.like(f'PRES-{fecha_hoy}-%'))
                  .order_by(Presupuesto.id.desc()).first())
        if ultimo and ultimo.numero:
            try:
                n = int(ultimo.numero.split('-')[-1]) + 1
                numero = f"PRES-{fecha_hoy}-{n:03d}"
            except (ValueError, IndexError):
                numero = f"PRES-{fecha_hoy}-001"
        else:
            numero = f"PRES-{fecha_hoy}-001"

    # Validar cliente
    if cliente_id:
        c = Cliente.query.filter_by(id=cliente_id, organizacion_id=org_id).first()
        if not c:
            flash('Cliente inválido', 'danger')
            return redirect(url_for('presupuestos.importar_licitacion'))

    # Guardar archivo en /tmp para procesamiento (auto o manual)
    try:
        token, path = _guardar_archivo_temp(archivo)
    except Exception as e:
        flash(f'Error al guardar archivo: {str(e)[:200]}', 'danger')
        return redirect(url_for('presupuestos.importar_licitacion'))

    # Si el usuario tildó "revisar antes de importar", saltar al mapeo manual
    revisar_antes = request.form.get('revisar_antes') == '1'

    if not revisar_antes:
        # Intentar auto-detect
        try:
            with open(path, 'rb') as f:
                items = _parsear_xlsx(f)
        except Exception as e:
            current_app.logger.exception("Error parseando Excel de licitacion")
            items = None

        if items:
            # Auto-detect funcionó: crear presupuesto directamente
            try:
                presu = _crear_presupuesto_desde_items(
                    org_id, cliente_id, numero, vigencia_dias, nombre_obra, items,
                    modo_licitacion=modo_licitacion, ubicacion=ubicacion,
                    ubicacion_lat=ubicacion_lat, ubicacion_lng=ubicacion_lng,
                    ubicacion_normalizada=ubicacion_normalizada,
                    naturaleza_proyecto=naturaleza_proyecto,
                )
                _persistir_pliego(presu, path, nombre_original=archivo.filename)
                import os
                try: os.remove(path)
                except Exception: pass
                if modo_licitacion:
                    msg = f'Presupuesto {numero} creado con {len(items)} ítems en $0 (modo licitación). Armá el Ejecutivo para desglosar en materiales y pedir cotización.'
                else:
                    msg = f'Presupuesto {numero} creado con {len(items)} ítems con precios del Excel.'
                flash(msg, 'success')
                return redirect(url_for('presupuestos.ejecutivo_vista', id=presu.id))
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception("Error creando presupuesto desde Excel")
                flash(f'Error al crear presupuesto: {str(e)[:200]}', 'danger')
                return redirect(url_for('presupuestos.importar_licitacion'))

    # Auto-detect falló o usuario quiere revisar: pasar a mapeo manual
    # Guardar parametros del form en query string
    return redirect(url_for(
        'presupuestos.importar_licitacion_mapear',
        token=token,
        nombre_obra=nombre_obra,
        cliente_id=cliente_id or '',
        numero=numero,
        vigencia_dias=vigencia_dias,
        modo_licitacion='1' if modo_licitacion else '0',
        ubicacion=ubicacion or '',
        ubicacion_lat=ubicacion_lat or '',
        ubicacion_lng=ubicacion_lng or '',
        ubicacion_normalizada=ubicacion_normalizada or '',
        naturaleza_proyecto=naturaleza_proyecto or 'obra_nueva',
    ))


@presupuestos_bp.route('/importar-licitacion/mapear/<token>', methods=['GET', 'POST'])
@login_required
def importar_licitacion_mapear(token):
    """Vista de mapeo manual de columnas del Excel."""
    if not current_user.puede_gestionar():
        abort(403)
    org_id = get_current_org_id()
    if not org_id:
        return redirect(url_for('auth.seleccionar_organizacion'))

    path = _path_archivo_temp(token)
    if not path:
        flash('Sesión expirada. Volvé a subir el archivo.', 'warning')
        return redirect(url_for('presupuestos.importar_licitacion'))

    nombre_obra = request.values.get('nombre_obra', '').strip()
    cliente_id_raw = request.values.get('cliente_id', '')
    cliente_id = int(cliente_id_raw) if cliente_id_raw and cliente_id_raw.isdigit() else None
    numero = request.values.get('numero', '').strip()
    vigencia_dias = int(request.values.get('vigencia_dias', 30) or 30)
    modo_licitacion = request.values.get('modo_licitacion', '1') == '1'
    ubicacion = (request.values.get('ubicacion') or '').strip() or None
    try:
        ubicacion_lat = float(request.values.get('ubicacion_lat') or '') or None
    except (ValueError, TypeError):
        ubicacion_lat = None
    try:
        ubicacion_lng = float(request.values.get('ubicacion_lng') or '') or None
    except (ValueError, TypeError):
        ubicacion_lng = None
    ubicacion_normalizada = (request.values.get('ubicacion_normalizada') or '').strip() or None
    naturaleza_proyecto = (request.values.get('naturaleza_proyecto') or 'obra_nueva').strip()

    if request.method == 'POST':
        # Procesar mapeo manual
        try:
            sheet_idx = int(request.form.get('sheet_idx', 0))
            header_row = int(request.form.get('header_row', 1)) - 1  # 1-based en UI
            col_desc = int(request.form.get('col_desc', -1))
            col_unidad_raw = request.form.get('col_unidad', '')
            col_cantidad = int(request.form.get('col_cantidad', -1))
            col_precio_raw = request.form.get('col_precio', '')

            col_unidad = int(col_unidad_raw) if col_unidad_raw not in ('', '-1') else None
            col_precio = int(col_precio_raw) if col_precio_raw not in ('', '-1') else None

            if col_desc < 0 or col_cantidad < 0:
                flash('Tenés que mapear al menos las columnas Descripción y Cantidad.', 'danger')
                return redirect(request.url)

            # Leer hoja seleccionada e importar
            import openpyxl
            wb = openpyxl.load_workbook(path, data_only=True)
            sheet = wb.worksheets[sheet_idx]
            rows = list(sheet.iter_rows(values_only=True))

            items = []
            for row in rows[header_row + 1:]:
                if not row or all(c is None or str(c).strip() == '' for c in row):
                    continue
                desc = row[col_desc] if col_desc < len(row) else None
                if not desc or str(desc).strip() == '':
                    continue
                cant_raw = row[col_cantidad] if col_cantidad < len(row) else 0
                if cant_raw is None or str(cant_raw).strip() == '':
                    continue
                try:
                    cant = _parse_decimal(cant_raw)
                except Exception:
                    continue
                if cant <= 0:
                    continue

                unidad = row[col_unidad] if col_unidad is not None and col_unidad < len(row) else None
                precio = row[col_precio] if col_precio is not None and col_precio < len(row) else 0
                try:
                    precio_d = _parse_decimal(precio)
                except Exception:
                    precio_d = Decimal('0')

                items.append({
                    'descripcion': str(desc).strip()[:300],
                    'unidad': str(unidad).strip()[:20] if unidad else 'un',
                    'cantidad': cant,
                    'precio_unitario': precio_d,
                    'total': cant * precio_d,
                })

            if not items:
                flash('No se detectaron items válidos con ese mapeo. Revisá la fila de encabezado y las columnas.', 'warning')
                return redirect(request.url)

            presu = _crear_presupuesto_desde_items(
                org_id, cliente_id, numero, vigencia_dias, nombre_obra, items,
                modo_licitacion=modo_licitacion, ubicacion=ubicacion,
                ubicacion_lat=ubicacion_lat, ubicacion_lng=ubicacion_lng,
                ubicacion_normalizada=ubicacion_normalizada,
                naturaleza_proyecto=naturaleza_proyecto,
            )
            _persistir_pliego(presu, path)
            import os
            try: os.remove(path)
            except Exception: pass
            suf = ' en $0 (modo licitación)' if modo_licitacion else ''
            flash(f'Presupuesto {numero} creado con {len(items)} ítems desde mapeo manual{suf}.', 'success')
            return redirect(url_for('presupuestos.ejecutivo_vista', id=presu.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error en mapeo manual")
            flash(f'Error: {str(e)[:200]}', 'danger')
            return redirect(request.url)

    # GET: mostrar preview + selectores
    try:
        sheets = _leer_preview(path, max_rows=40)
    except Exception as e:
        flash(f'Error leyendo Excel: {str(e)[:200]}', 'danger')
        return redirect(url_for('presupuestos.importar_licitacion'))

    return render_template('presupuestos/importar_licitacion_mapear.html',
                           token=token,
                           sheets=sheets,
                           nombre_obra=nombre_obra,
                           cliente_id=cliente_id,
                           numero=numero,
                           vigencia_dias=vigencia_dias)
