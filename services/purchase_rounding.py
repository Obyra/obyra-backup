"""
Motor de Redondeo de Compras para Presupuestos

Convierte cantidades teóricas (netas) a cantidades comprables reales,
respetando las presentaciones estándar definidas en el inventario.

Reglas de redondeo:
1. Nunca puede faltar: cantidad final >= neto requerido
2. Minimizar sobrante (excedente)
3. Si hay empate en sobrante: minimizar cantidad de packs
4. Si persiste empate y hay precios: minimizar costo total
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
import math


@dataclass
class PackSize:
    """Representa una presentación/pack disponible"""
    size: float  # Cantidad en unidad base (ej: 20 para balde de 20L)
    price: Optional[float] = None  # Precio por pack (opcional)
    name: Optional[str] = None  # Nombre descriptivo (ej: "Balde 20L")


@dataclass
class RoundingResult:
    """Resultado del redondeo para un artículo"""
    articulo_id: Optional[int] = None
    descripcion: str = ""
    unidad_base: str = "unidad"

    # Cantidad neta requerida
    neto_qty: float = 0.0

    # Packs seleccionados: {tamaño: cantidad}
    packs_seleccionados: Dict[float, int] = field(default_factory=dict)

    # Total a comprar
    total_compra_qty: float = 0.0

    # Sobrante
    sobrante_qty: float = 0.0

    # Costo total (si hay precios)
    costo_total: Optional[float] = None

    # Detalle legible de packs
    detalle_packs: str = ""

    def to_dict(self) -> dict:
        return {
            'articulo_id': self.articulo_id,
            'descripcion': self.descripcion,
            'unidad_base': self.unidad_base,
            'neto_qty': self.neto_qty,
            'packs_seleccionados': [
                {'pack': size, 'qty': qty}
                for size, qty in self.packs_seleccionados.items()
            ],
            'total_compra_qty': self.total_compra_qty,
            'sobrante_qty': self.sobrante_qty,
            'costo_total': self.costo_total,
            'detalle_packs': self.detalle_packs
        }


def round_to_purchase(
    required_qty: float,
    pack_sizes: List[float],
    prices: Optional[Dict[float, float]] = None,
    max_packs_per_size: int = 100
) -> Tuple[Dict[float, int], float, float, Optional[float]]:
    """
    Calcula la combinación óptima de packs para cubrir la cantidad requerida.

    Args:
        required_qty: Cantidad neta requerida en unidad base
        pack_sizes: Lista de tamaños de pack disponibles (ej: [20, 10, 5])
        prices: Dict opcional de precios por tamaño {size: price}
        max_packs_per_size: Límite máximo de packs por tamaño (evita explosión combinatoria)

    Returns:
        Tuple de (packs_dict, total_qty, surplus, total_cost)
        - packs_dict: {tamaño: cantidad}
        - total_qty: cantidad total comprada
        - surplus: sobrante
        - total_cost: costo total (None si no hay precios)

    Ejemplo:
        >>> round_to_purchase(66, [20, 10, 5])
        ({20: 3, 10: 1}, 70.0, 4.0, None)
    """
    if required_qty <= 0:
        return {}, 0.0, 0.0, None

    if not pack_sizes:
        # Sin presentaciones definidas, devolver cantidad exacta
        return {1: math.ceil(required_qty)}, math.ceil(required_qty), math.ceil(required_qty) - required_qty, None

    # Ordenar packs de mayor a menor para greedy
    pack_sizes = sorted(pack_sizes, reverse=True)

    best_solution = None
    best_surplus = float('inf')
    best_pack_count = float('inf')
    best_cost = float('inf')

    # Estrategia: Usar programación dinámica limitada / búsqueda acotada
    # Para cada pack size, calcular cuántos packs máximos podríamos necesitar
    max_counts = {}
    for size in pack_sizes:
        max_counts[size] = min(
            math.ceil(required_qty / size) + 1,  # +1 para permitir sobrante mínimo
            max_packs_per_size
        )

    # Generar combinaciones de forma eficiente usando enfoque greedy + ajustes
    def generate_combinations():
        """Genera combinaciones candidatas de forma eficiente"""
        combinations = []

        # 1. Solución greedy pura (de mayor a menor)
        remaining = required_qty
        greedy = {}
        for size in pack_sizes:
            if remaining > 0:
                count = math.ceil(remaining / size)
                # Limitar para no excederse demasiado
                count = min(count, max_counts[size])
                if count > 0:
                    greedy[size] = count
                    remaining -= count * size
        if sum(size * count for size, count in greedy.items()) >= required_qty:
            combinations.append(greedy.copy())

        # 2. Variaciones del greedy: probar con -1 del pack más grande y compensar
        for main_size in pack_sizes:
            if main_size not in greedy or greedy[main_size] <= 0:
                continue

            variant = greedy.copy()
            variant[main_size] = greedy[main_size] - 1

            # Recalcular cantidad restante
            total = sum(s * c for s, c in variant.items())
            if total < required_qty:
                # Necesitamos compensar con packs más pequeños
                deficit = required_qty - total
                for small_size in pack_sizes:
                    if small_size >= main_size:
                        continue
                    needed = math.ceil(deficit / small_size)
                    needed = min(needed, max_counts[small_size])
                    if needed > 0:
                        variant[small_size] = variant.get(small_size, 0) + needed
                        deficit -= needed * small_size
                    if deficit <= 0:
                        break

            total = sum(s * c for s, c in variant.items())
            if total >= required_qty:
                combinations.append(variant)

        # 3. Solución usando solo el pack más pequeño (como fallback)
        smallest = min(pack_sizes)
        single_pack = {smallest: math.ceil(required_qty / smallest)}
        combinations.append(single_pack)

        # 4. Soluciones usando solo cada tamaño de pack
        for size in pack_sizes:
            single = {size: math.ceil(required_qty / size)}
            combinations.append(single)

        # 5. Búsqueda limitada de combinaciones de 2 packs
        for i, size1 in enumerate(pack_sizes):
            for size2 in pack_sizes[i+1:]:
                # Probar varias combinaciones
                for count1 in range(max_counts[size1] + 1):
                    remaining_after_1 = required_qty - (count1 * size1)
                    if remaining_after_1 <= 0:
                        if count1 > 0:
                            combinations.append({size1: count1})
                        break
                    count2 = math.ceil(remaining_after_1 / size2)
                    if count2 <= max_counts[size2]:
                        combo = {}
                        if count1 > 0:
                            combo[size1] = count1
                        if count2 > 0:
                            combo[size2] = count2
                        if combo:
                            combinations.append(combo)

        return combinations

    # Evaluar todas las combinaciones candidatas
    for combo in generate_combinations():
        total = sum(size * count for size, count in combo.items())

        # Verificar que cubre el requerimiento
        if total < required_qty:
            continue

        surplus = total - required_qty
        pack_count = sum(combo.values())

        # Calcular costo si hay precios
        cost = None
        if prices:
            cost = sum(prices.get(size, 0) * count for size, count in combo.items())

        # Comparar con mejor solución actual
        is_better = False

        if surplus < best_surplus:
            is_better = True
        elif surplus == best_surplus:
            if pack_count < best_pack_count:
                is_better = True
            elif pack_count == best_pack_count and cost is not None and best_cost is not None:
                if cost < best_cost:
                    is_better = True

        if is_better:
            best_solution = combo
            best_surplus = surplus
            best_pack_count = pack_count
            best_cost = cost if cost is not None else float('inf')

    # Si no encontramos solución, usar el pack más pequeño
    if best_solution is None:
        smallest = min(pack_sizes) if pack_sizes else 1
        count = math.ceil(required_qty / smallest)
        best_solution = {smallest: count}
        best_surplus = (count * smallest) - required_qty
        best_cost = prices.get(smallest, 0) * count if prices else None

    total_qty = sum(size * count for size, count in best_solution.items())
    final_cost = None
    if prices and best_cost != float('inf'):
        final_cost = best_cost

    return best_solution, total_qty, best_surplus, final_cost


def convert_area_to_units(
    area_m2: float,
    coverage_per_unit: float
) -> int:
    """
    Convierte metros cuadrados a unidades necesarias.

    Args:
        area_m2: Área en metros cuadrados a cubrir
        coverage_per_unit: Cobertura por unidad (ej: 0.0225 m² por cerámico 15x15)

    Returns:
        Número de unidades necesarias (redondeado hacia arriba)
    """
    if coverage_per_unit <= 0:
        return 0
    return math.ceil(area_m2 / coverage_per_unit)


def round_item_for_purchase(
    articulo_id: Optional[int],
    descripcion: str,
    required_qty: float,
    unidad_base: str,
    presentaciones: List[Dict],
    area_m2: Optional[float] = None,
    coverage_per_unit: Optional[float] = None
) -> RoundingResult:
    """
    Redondea un artículo para compra.

    Args:
        articulo_id: ID del artículo en inventario
        descripcion: Descripción del artículo
        required_qty: Cantidad requerida en unidad base
        unidad_base: Unidad base (L, kg, m², unidad, etc)
        presentaciones: Lista de presentaciones [{size: float, price: float, name: str}]
        area_m2: Área en m² (si aplica conversión)
        coverage_per_unit: Cobertura por unidad (si aplica conversión)

    Returns:
        RoundingResult con el detalle del redondeo
    """
    result = RoundingResult(
        articulo_id=articulo_id,
        descripcion=descripcion,
        unidad_base=unidad_base,
        neto_qty=required_qty
    )

    # Si hay conversión de área a unidades
    if area_m2 is not None and coverage_per_unit is not None and coverage_per_unit > 0:
        required_qty = convert_area_to_units(area_m2, coverage_per_unit)
        result.neto_qty = required_qty

    # Extraer tamaños y precios de presentaciones
    pack_sizes = []
    prices = {}
    pack_names = {}

    for pres in presentaciones:
        size = pres.get('size', pres.get('tamanio', 1))
        pack_sizes.append(size)
        if 'price' in pres or 'precio' in pres:
            prices[size] = pres.get('price', pres.get('precio', 0))
        if 'name' in pres or 'nombre' in pres:
            pack_names[size] = pres.get('name', pres.get('nombre', f'{size} {unidad_base}'))

    # Si no hay presentaciones, asumir unidad individual
    if not pack_sizes:
        pack_sizes = [1]

    # Calcular redondeo
    packs, total, surplus, cost = round_to_purchase(
        required_qty,
        pack_sizes,
        prices if prices else None
    )

    result.packs_seleccionados = packs
    result.total_compra_qty = total
    result.sobrante_qty = surplus
    result.costo_total = cost

    # Generar detalle legible
    detalle_parts = []
    for size in sorted(packs.keys(), reverse=True):
        qty = packs[size]
        name = pack_names.get(size, f'{size} {unidad_base}')
        detalle_parts.append(f'{qty}x{name}')

    result.detalle_packs = ' + '.join(detalle_parts) if detalle_parts else str(int(total))

    return result


def round_etapa_items(
    etapa_nombre: str,
    medida_ejecutar: float,
    unidad_medida: str,
    items: List[Dict]
) -> Dict:
    """
    Redondea todos los items de una etapa.

    Args:
        etapa_nombre: Nombre de la etapa
        medida_ejecutar: Cantidad a ejecutar (m², ml, m³, etc)
        unidad_medida: Unidad de la medida
        items: Lista de items con sus cantidades y presentaciones

    Returns:
        Dict con el resultado por etapa
    """
    resultado = {
        'etapa': etapa_nombre,
        'medida_ejecutar': medida_ejecutar,
        'unidad_medida': unidad_medida,
        'items': []
    }

    for item in items:
        rounded = round_item_for_purchase(
            articulo_id=item.get('articulo_id'),
            descripcion=item.get('descripcion', ''),
            required_qty=item.get('cantidad', 0),
            unidad_base=item.get('unidad', 'unidad'),
            presentaciones=item.get('presentaciones', []),
            area_m2=item.get('area_m2'),
            coverage_per_unit=item.get('cobertura_por_unidad')
        )
        resultado['items'].append(rounded.to_dict())

    return resultado


# Función de utilidad para obtener presentaciones de un item de inventario
def get_presentaciones_from_inventory(item_inventario) -> List[Dict]:
    """
    Obtiene las presentaciones de un item de inventario.

    Args:
        item_inventario: Objeto ItemInventario del modelo

    Returns:
        Lista de presentaciones en formato estándar
    """
    presentaciones = []

    # Verificar si el item tiene presentaciones definidas
    if hasattr(item_inventario, 'presentaciones') and item_inventario.presentaciones:
        # Si es JSON string, parsearlo
        if isinstance(item_inventario.presentaciones, str):
            import json
            try:
                presentaciones = json.loads(item_inventario.presentaciones)
            except:
                presentaciones = []
        elif isinstance(item_inventario.presentaciones, list):
            presentaciones = item_inventario.presentaciones

    # Si no hay presentaciones, usar valores por defecto según unidad
    if not presentaciones:
        unidad = getattr(item_inventario, 'unidad', 'unidad')

        # Valores por defecto según tipo de unidad
        defaults = {
            'lts': [{'size': 20, 'name': 'Balde 20L'}, {'size': 10, 'name': 'Balde 10L'}, {'size': 5, 'name': 'Balde 5L'}, {'size': 1, 'name': 'Litro'}],
            'kg': [{'size': 50, 'name': 'Bolsa 50kg'}, {'size': 25, 'name': 'Bolsa 25kg'}, {'size': 10, 'name': 'Bolsa 10kg'}, {'size': 1, 'name': 'Kg'}],
            'ml': [{'size': 1, 'name': 'Metro'}],
            'm2': [{'size': 1, 'name': 'm²'}],
            'm3': [{'size': 1, 'name': 'm³'}],
            'bolsa': [{'size': 1, 'name': 'Bolsa'}],
            'unidad': [{'size': 1, 'name': 'Unidad'}],
        }

        presentaciones = defaults.get(unidad, [{'size': 1, 'name': 'Unidad'}])

    return presentaciones
