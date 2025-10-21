import os
from collections import defaultdict, OrderedDict
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urlparse

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    current_app,
)
from flask_login import current_user, login_required

from app import db, _login_redirect

from models import (
    InventoryCategory,
    InventoryItem,
    ItemInventario,
    Organizacion,
    Obra,
    Stock,
    StockMovement,
    StockReservation,
    Warehouse,
)
from sqlalchemy import func
from sqlalchemy.orm import aliased

from services.memberships import get_current_org_id
from seed_inventory_categories import seed_inventory_categories_for_company
from inventory_category_service import (
    ensure_categories_for_company,
    ensure_categories_for_company_id,
    get_active_categories,
    serialize_category,
    render_category_catalog,
    user_can_manage_inventory_categories,
)
