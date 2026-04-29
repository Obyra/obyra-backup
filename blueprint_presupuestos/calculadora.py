"""
Calculator API routes: calcular_etapas_ia, api_buscar_precios, api_precios_categoria,
api_listar_categorias, api_estadisticas_precios, api_calculadora_etapas,
api_calculadora_calcular_etapa, api_calculadora_calcular_completo,
api_calculadora_items_etapa, api_precios_mercadolibre, api_actualizar_precios_ml,
api_buscar_precio_ml, api_precios_referencia
"""
from flask import request, jsonify, current_app
from flask_login import login_required, current_user

from services.memberships import get_current_org_id

from blueprint_presupuestos import presupuestos_bp


@presupuestos_bp.route('/ia/etapas-sugeridas', methods=['GET'])
@login_required
def etapas_sugeridas_naturaleza():
    """
    Devuelve qué etapas debe preseleccionar/excluir el wizard según
    la naturaleza del proyecto (obra_nueva | remodelacion | ampliacion).

    Query params:
        - naturaleza: string (default 'obra_nueva')

    Response:
        {ok, naturaleza, sugeridas: [slugs], excluidas: [slugs]}
    """
    try:
        from calculadora_ia import obtener_etapas_para_naturaleza

        naturaleza = request.args.get('naturaleza', 'obra_nueva')
        info = obtener_etapas_para_naturaleza(naturaleza)
        info['ok'] = True
        return jsonify(info), 200
    except Exception as e:
        current_app.logger.error(f"Error en etapas_sugeridas_naturaleza: {e}")
        return jsonify({'ok': False, 'error': 'Error al obtener etapas sugeridas'}), 500


@presupuestos_bp.route('/ia/calcular/etapas', methods=['POST'])
@login_required
def calcular_etapas_ia():
    """
    Endpoint para cálculo de etapas seleccionadas con reglas determinísticas.
    Soporta redondeo de compras y precios duales USD/ARS.
    """
    try:
        from calculadora_ia import calcular_etapas_seleccionadas
        from services.exchange.base import ensure_rate
        from services.exchange.providers.bna import fetch_official_rate
        from services.budget_rounding_service import process_budget_with_rounding_and_dual_currency
        from decimal import Decimal
        from datetime import date

        data = request.get_json() or {}

        # Validar datos requeridos
        superficie_m2 = data.get('superficie_m2')
        if not superficie_m2 or float(superficie_m2) <= 0:
            return jsonify({
                'ok': False,
                'error': 'Superficie en m² es requerida y debe ser mayor a 0'
            }), 400

        etapa_ids = data.get('etapa_ids', [])
        if not etapa_ids:
            return jsonify({
                'ok': False,
                'error': 'Debes seleccionar al menos una etapa para calcular'
            }), 400

        # Parámetros opcionales
        tipo_calculo = data.get('tipo_calculo', 'Estándar')
        parametros_contexto = data.get('parametros_contexto', {})
        presupuesto_id = data.get('presupuesto_id')
        currency = (data.get('currency') or data.get('moneda', 'ARS')).upper()
        aplicar_desperdicio = data.get('aplicar_desperdicio', True)  # Por defecto True
        aplicar_redondeo = data.get('aplicar_redondeo', True)  # Redondeo de compras
        mostrar_sobrante = data.get('mostrar_sobrante', True)  # Mostrar sobrantes
        naturaleza_proyecto = data.get('naturaleza_proyecto') or (parametros_contexto or {}).get('naturaleza_proyecto')

        # Siempre obtener tipo de cambio para precios duales
        fx_snapshot = None
        fx_rate = None
        try:
            fx_snapshot = ensure_rate(
                provider='bna_html',
                base_currency='ARS',
                quote_currency='USD',
                fetcher=fetch_official_rate,
                as_of=date.today(),
                fallback_rate=Decimal('1000.00')  # Fallback conservador
            )
            fx_rate = float(fx_snapshot.value)
            current_app.logger.info(f"Tipo de cambio BNA obtenido: {fx_rate} ARS/USD")
        except Exception as e:
            current_app.logger.warning(f"No se pudo obtener tipo de cambio: {str(e)}")
            # Continuar sin tipo de cambio

        # Obtener org_id del usuario actual para consultar inventario
        org_id = get_current_org_id()

        # Verificar si hay niveles de edificio configurados
        niveles = data.get('niveles')

        if niveles and len(niveles) > 0 and any(float(n.get('area_m2', 0)) > 0 for n in niveles):
            # Modo edificio por niveles
            from calculadora_ia import calcular_etapas_por_niveles
            resultado = calcular_etapas_por_niveles(
                etapas_payload=etapa_ids,
                niveles=niveles,
                tipo_calculo=tipo_calculo,
                contexto=parametros_contexto,
                presupuesto_id=presupuesto_id,
                currency='ARS',
                fx_snapshot=None,
                aplicar_desperdicio=aplicar_desperdicio,
                org_id=org_id,
            )
        else:
            # Modo global m² (sin cambios)
            resultado = calcular_etapas_seleccionadas(
                etapas_payload=etapa_ids,
                superficie_m2=float(superficie_m2),
                tipo_calculo=tipo_calculo,
                contexto=parametros_contexto,
                presupuesto_id=presupuesto_id,
                currency='ARS',
                fx_snapshot=None,
                aplicar_desperdicio=aplicar_desperdicio,
                org_id=org_id,
                naturaleza_proyecto=naturaleza_proyecto,
            )

        if resultado.get('ok') and resultado.get('etapas'):
            # Aplicar redondeo de compras y precios duales
            resultado_procesado = process_budget_with_rounding_and_dual_currency(
                etapas=resultado['etapas'],
                fx_rate=fx_rate,
                base_currency='ARS',
                apply_rounding=aplicar_redondeo,
                include_surplus=mostrar_sobrante
            )

            # Actualizar resultado con datos procesados
            resultado['etapas'] = resultado_procesado['etapas']
            resultado['total_parcial_ars'] = resultado_procesado.get('total_parcial_ars', resultado.get('total_parcial', 0))
            resultado['total_parcial'] = resultado['total_parcial_ars']  # Mantener compatibilidad
            resultado['redondeo_aplicado'] = aplicar_redondeo

            if fx_rate:
                resultado['total_parcial_usd'] = resultado_procesado.get('total_parcial_usd')
                resultado['tipo_cambio'] = {
                    'valor': fx_rate,
                    'proveedor': fx_snapshot.provider if fx_snapshot else 'fallback',
                    'base_currency': 'ARS',
                    'quote_currency': 'USD',
                    'fetched_at': fx_snapshot.fetched_at.isoformat() if fx_snapshot else None,
                    'as_of': fx_snapshot.as_of_date.isoformat() if fx_snapshot else None
                }

            if mostrar_sobrante and aplicar_redondeo:
                resultado['total_sobrante_estimado'] = resultado_procesado.get('total_sobrante_estimado', 0)

        return jsonify(resultado), 200

    except ValueError as e:
        current_app.logger.error(f"Error de validación en calcular_etapas_ia: {str(e)}")
        return jsonify({
            'ok': False,
            'error': 'Error de validación en el cálculo'
        }), 400
    except Exception as e:
        current_app.logger.error(f"Error en calcular_etapas_ia: {str(e)}", exc_info=True)
        return jsonify({
            'ok': False,
            'error': 'Error al calcular etapas'
        }), 500


# =============================================================================
# API DE PRECIOS - Datos importados desde Excel
# =============================================================================

@presupuestos_bp.route('/api/precios/buscar')
@login_required
def api_buscar_precios():
    """
    Busca articulos y precios en la base de datos de Excel importada.

    Query params:
        q: Termino de busqueda
        tipo: Tipo de construccion (Economica, Estandar, Premium)
        limite: Maximo de resultados (default 20)
    """
    try:
        from services.calculadora_precios import buscar_articulos

        termino = request.args.get('q', '').strip()
        tipo_construccion = request.args.get('tipo', 'Estandar')
        limite = min(int(request.args.get('limite', 20)), 100)

        if not termino or len(termino) < 2:
            return jsonify({'ok': True, 'articulos': [], 'mensaje': 'Ingrese al menos 2 caracteres'})

        articulos = buscar_articulos(
            termino=termino,
            tipo_construccion=tipo_construccion,
            solo_con_precio=True,
            limite=limite
        )

        return jsonify({
            'ok': True,
            'articulos': articulos,
            'total': len(articulos),
            'tipo_construccion': tipo_construccion
        })

    except Exception as e:
        current_app.logger.error(f"Error buscando precios: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/precios/categoria/<path:categoria>')
@login_required
def api_precios_categoria(categoria):
    """
    Obtiene todos los precios de una categoria especifica.
    """
    try:
        from services.calculadora_precios import obtener_precios_categoria

        tipo_construccion = request.args.get('tipo', 'Estandar')

        articulos = obtener_precios_categoria(
            categoria=categoria,
            tipo_construccion=tipo_construccion,
            solo_con_precio=True
        )

        return jsonify({
            'ok': True,
            'categoria': categoria,
            'articulos': articulos,
            'total': len(articulos),
            'tipo_construccion': tipo_construccion
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo precios de categoria: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/precios/categorias')
@login_required
def api_listar_categorias():
    """
    Lista todas las categorias disponibles.
    """
    try:
        from services.calculadora_precios import obtener_categorias_disponibles

        tipo_construccion = request.args.get('tipo', 'Estandar')
        categorias = obtener_categorias_disponibles(tipo_construccion)

        return jsonify({
            'ok': True,
            'categorias': categorias,
            'total': len(categorias),
            'tipo_construccion': tipo_construccion
        })

    except Exception as e:
        current_app.logger.error(f"Error listando categorias: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/precios/estadisticas')
@login_required
def api_estadisticas_precios():
    """
    Obtiene estadisticas de los datos de precios importados.
    """
    try:
        from services.calculadora_precios import obtener_estadisticas

        stats = obtener_estadisticas()

        return jsonify({
            'ok': True,
            'estadisticas': stats
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo estadisticas: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


# ============================================================================
# CALCULADORA IA MEJORADA - Endpoints
# ============================================================================

@presupuestos_bp.route('/api/calculadora/etapas')
@login_required
def api_calculadora_etapas():
    """
    Obtiene la lista de etapas disponibles con cantidad de items.
    """
    try:
        from services.calculadora_ia_mejorada import obtener_resumen_etapas

        etapas = obtener_resumen_etapas()

        return jsonify({
            'ok': True,
            'etapas': etapas,
            'total_etapas': len(etapas)
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo etapas: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/calculadora/calcular-etapa', methods=['POST'])
@login_required
def api_calculadora_calcular_etapa():
    """
    Calcula el presupuesto para una etapa específica.

    Body JSON:
        - etapa_slug: slug de la etapa
        - metros_cuadrados: superficie en m²
        - tipo_construccion: 'Económica', 'Estándar' o 'Premium'
        - tipo_cambio_usd: (opcional) tipo de cambio USD/ARS
    """
    try:
        from services.calculadora_ia_mejorada import calcular_etapa_mejorada

        data = request.get_json() or {}

        etapa_slug = data.get('etapa_slug')
        metros_cuadrados = float(data.get('metros_cuadrados', 0))
        tipo_construccion = data.get('tipo_construccion', 'Estándar')
        tipo_cambio_usd = float(data.get('tipo_cambio_usd', 1200))

        if not etapa_slug:
            return jsonify({'ok': False, 'error': 'etapa_slug es requerido'}), 400

        if metros_cuadrados <= 0:
            return jsonify({'ok': False, 'error': 'metros_cuadrados debe ser mayor a 0'}), 400

        org_id = get_current_org_id() or 2

        resultado = calcular_etapa_mejorada(
            etapa_slug=etapa_slug,
            metros_cuadrados=metros_cuadrados,
            tipo_construccion=tipo_construccion,
            org_id=org_id,
            tipo_cambio_usd=tipo_cambio_usd,
            incluir_items_detalle=True
        )

        return jsonify({
            'ok': True,
            'calculo': resultado
        })

    except Exception as e:
        current_app.logger.error(f"Error calculando etapa: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/calculadora/calcular-completo', methods=['POST'])
@login_required
def api_calculadora_calcular_completo():
    """
    Calcula el presupuesto completo para múltiples etapas.

    Body JSON:
        - metros_cuadrados: superficie en m²
        - tipo_construccion: 'Económica', 'Estándar' o 'Premium'
        - etapas: (opcional) lista de slugs de etapas, null = todas
        - tipo_cambio_usd: (opcional) tipo de cambio USD/ARS
    """
    try:
        from services.calculadora_ia_mejorada import calcular_presupuesto_completo

        data = request.get_json() or {}

        metros_cuadrados = float(data.get('metros_cuadrados', 0))
        tipo_construccion = data.get('tipo_construccion', 'Estándar')
        etapas = data.get('etapas')  # None = todas
        tipo_cambio_usd = float(data.get('tipo_cambio_usd', 1200))

        if metros_cuadrados <= 0:
            return jsonify({'ok': False, 'error': 'metros_cuadrados debe ser mayor a 0'}), 400

        org_id = get_current_org_id() or 2

        resultado = calcular_presupuesto_completo(
            metros_cuadrados=metros_cuadrados,
            tipo_construccion=tipo_construccion,
            etapas_seleccionadas=etapas,
            org_id=org_id,
            tipo_cambio_usd=tipo_cambio_usd
        )

        return jsonify({
            'ok': True,
            'presupuesto': resultado
        })

    except Exception as e:
        current_app.logger.error(f"Error calculando presupuesto completo: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/calculadora/items-etapa/<etapa_slug>')
@login_required
def api_calculadora_items_etapa(etapa_slug):
    """
    Obtiene los items de inventario para una etapa específica.

    Query params:
        - tipo: 'Económica', 'Estándar' o 'Premium' (default: Estándar)
        - limite: máximo de items a retornar (default: 50)
    """
    try:
        from services.calculadora_ia_mejorada import obtener_items_etapa_desde_bd, contar_items_etapa

        tipo_construccion = request.args.get('tipo', 'Estándar')
        limite = int(request.args.get('limite', 50))

        org_id = get_current_org_id() or 2

        items = obtener_items_etapa_desde_bd(
            etapa_slug=etapa_slug,
            tipo_construccion=tipo_construccion,
            org_id=org_id,
            limite=limite
        )

        conteo = contar_items_etapa(etapa_slug, tipo_construccion, org_id)

        return jsonify({
            'ok': True,
            'etapa_slug': etapa_slug,
            'tipo_construccion': tipo_construccion,
            'items': items,
            'total_disponibles': conteo['total'],
            'con_precio': conteo['con_precio']
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo items de etapa: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


# ============================================================================
# MERCADOLIBRE - Precios de referencia
# ============================================================================

@presupuestos_bp.route('/api/calculadora/precios-mercadolibre')
@login_required
def api_precios_mercadolibre():
    """
    Obtiene precios de materiales desde MercadoLibre (cache 24hs).
    Query params:
        - material: codigo de material (ej: MAT-CEMENTO). Si no se pasa, retorna todos.
        - forzar: si '1', ignora cache
    """
    try:
        from services.mercadolibre_precios import (
            obtener_precio_material_ml,
            obtener_precios_ml_como_referencia,
            MATERIALES_ML
        )

        material = request.args.get('material')
        forzar = request.args.get('forzar') == '1'

        if material:
            resultado = obtener_precio_material_ml(material, forzar=forzar)
            if resultado:
                return jsonify({'ok': True, 'precio': resultado})
            return jsonify({'ok': False, 'error': f'Sin resultados para {material}'}), 404

        # Retornar todos los precios en cache
        precios = obtener_precios_ml_como_referencia()
        materiales_disponibles = list(MATERIALES_ML.keys())
        return jsonify({
            'ok': True,
            'precios': precios,
            'materiales_disponibles': materiales_disponibles,
            'total_en_cache': len(precios),
        })

    except Exception as e:
        current_app.logger.error(f"Error obteniendo precios ML: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/calculadora/actualizar-precios-ml', methods=['POST'])
@login_required
def api_actualizar_precios_ml():
    """
    Actualiza todos los precios de materiales desde MercadoLibre.
    Solo admin puede forzar actualizacion.
    """
    try:
        rol = getattr(current_user, 'rol', '') or ''
        role = getattr(current_user, 'role', '') or ''
        if rol not in ('administrador', 'admin') and role not in ('admin',):
            return jsonify({'error': 'Solo admin puede actualizar precios'}), 403

        from services.mercadolibre_precios import actualizar_todos_los_precios
        resultado = actualizar_todos_los_precios(forzar=True)
        return jsonify({'ok': True, 'resultado': resultado})

    except Exception as e:
        current_app.logger.error(f"Error actualizando precios ML: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/calculadora/buscar-precio-ml')
@login_required
def api_buscar_precio_ml():
    """
    Busca un producto en MercadoLibre y retorna precios.
    Query params:
        - q: termino de busqueda (ej: 'cemento portland 50kg')
        - limit: cantidad de resultados (default 10)
    """
    try:
        from services.mercadolibre_precios import buscar_precio_mercadolibre

        query = request.args.get('q', '').strip()
        limit = int(request.args.get('limit', 10))

        if not query:
            return jsonify({'ok': False, 'error': 'Parametro q requerido'}), 400

        resultado = buscar_precio_mercadolibre(query, limit=limit)
        if resultado:
            return jsonify({'ok': True, 'resultado': resultado})
        return jsonify({'ok': False, 'error': 'Sin resultados'}), 404

    except Exception as e:
        current_app.logger.error(f"Error buscando precio ML: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500


@presupuestos_bp.route('/api/calculadora/precios-referencia')
@login_required
def api_precios_referencia():
    """
    Retorna los precios de referencia de constructoras reales
    cargados desde el Excel de presupuestos.
    """
    try:
        from services.calculadora_ia_mejorada import _cargar_precios_constructora
        ref = _cargar_precios_constructora()
        return jsonify({
            'ok': True,
            'etapas_con_referencia': list(ref.keys()),
            'datos': ref,
        })
    except Exception as e:
        current_app.logger.error(f"Error obteniendo precios referencia: {e}")
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500
