"""
OBYRA Marketplace - Seller Masking Service
Handles public seller masking as "OBYRA Partner"
"""

MASKED = {"display": "OBYRA Partner"}
SCRUB_KEYS = {
    "seller", "seller_name", "seller_company_id", "seller_id", 
    "seller_contact", "store", "vendor", "emails", "phones", "addresses"
}

def redact_public(obj):
    """
    Recursively redact seller information from public data
    Used in public endpoints: /api/market/search, /api/market/products/:id
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in SCRUB_KEYS:
                out[k] = MASKED if k == "seller" else None
            else:
                out[k] = redact_public(v)
        return out
    if isinstance(obj, list):
        return [redact_public(x) for x in obj]
    return obj

def apply_seller_masking(product_data):
    """
    Apply seller masking to product data for public display
    """
    if isinstance(product_data, dict):
        # Always mask seller information in public views
        product_data["seller"] = MASKED
        
        # Remove any seller identifying fields
        for key in SCRUB_KEYS:
            if key in product_data:
                product_data[key] = None
    
    return product_data

def get_masked_seller_name(is_masked=True):
    """
    Get display name for seller based on masking status
    """
    return MASKED["display"] if is_masked else None