"""
OBYRA Marketplace - Commission Calculation Service
"""

from marketplace.models import MkCommission

def compute(category_id: int, exposure: str, price: float, qty: int) -> float:
    """
    Calculate commission amount for an order item
    
    Args:
        category_id: Product category ID
        exposure: Exposure level ('standard' or 'premium')
        price: Unit price
        qty: Quantity
        
    Returns:
        Commission amount in same currency
    """
    # Try to find specific commission rate
    commission_rule = MkCommission.query.filter_by(
        category_id=category_id,
        exposure=exposure
    ).first()
    
    if commission_rule:
        base_rate = float(commission_rule.take_rate_pct) / 100
    else:
        # Default rates if no specific rule found
        base_rate = 0.10  # 10% default
        if exposure == "premium":
            base_rate += 0.02  # +2% for premium exposure
    
    total_amount = price * qty
    commission = total_amount * base_rate
    
    return round(commission, 2)

def get_commission_rate(category_id: int, exposure: str) -> float:
    """
    Get commission rate percentage for a category/exposure combination
    """
    commission_rule = MkCommission.query.filter_by(
        category_id=category_id,
        exposure=exposure
    ).first()
    
    if commission_rule:
        return float(commission_rule.take_rate_pct)
    
    # Default rates
    base_rate = 10.0  # 10%
    if exposure == "premium":
        base_rate += 2.0  # +2% for premium
    
    return base_rate