"""
Calculator API routes: etapas_sugeridas_naturaleza, calcular_etapas_ia.

(Los 12 endpoints /api/precios/* y /api/calculadora/* que vivian aca
-- busqueda de precios importados de Excel, calculadora alternativa
por m2, integracion MercadoLibre -- se borraron: sin caller en ningun
template ni JS del repo, confirmado por grep antes de sacarlos.)
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

