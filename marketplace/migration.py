"""
OBYRA Marketplace - Database Migration
Creates ONLY marketplace tables with mk_ prefix
Following strict instructions - NO modification of existing tables
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db

app = create_app()
from marketplace.models import *

def create_marketplace_tables():
    """Create marketplace tables only"""
    with app.app_context():
        print("🏗️  Creating MARKETPLACE tables (mk_ prefix only)...")
        
        # Create only marketplace tables
        MkProduct.__table__.create(db.engine, checkfirst=True)
        MkProductVariant.__table__.create(db.engine, checkfirst=True)
        MkCart.__table__.create(db.engine, checkfirst=True)
        MkCartItem.__table__.create(db.engine, checkfirst=True)
        MkOrder.__table__.create(db.engine, checkfirst=True)
        MkOrderItem.__table__.create(db.engine, checkfirst=True)
        MkPayment.__table__.create(db.engine, checkfirst=True)
        MkPurchaseOrder.__table__.create(db.engine, checkfirst=True)
        MkCommission.__table__.create(db.engine, checkfirst=True)
        
        print("✅ Marketplace tables created successfully")

def seed_marketplace_data():
    """Seed initial marketplace data"""
    with app.app_context():
        print("🌱 Seeding marketplace data...")
        
        # Create demo commission rates
        commission_rates = [
            MkCommission(category_id=1, exposure='standard', take_rate_pct=10.0),
            MkCommission(category_id=1, exposure='premium', take_rate_pct=12.0),
            MkCommission(category_id=2, exposure='standard', take_rate_pct=8.0),
            MkCommission(category_id=2, exposure='premium', take_rate_pct=10.0),
        ]
        
        for commission in commission_rates:
            existing = MkCommission.query.filter_by(
                category_id=commission.category_id,
                exposure=commission.exposure
            ).first()
            if not existing:
                db.session.add(commission)
        
        # Create demo products
        demo_products = [
            MkProduct(
                seller_company_id=1,
                name="Cemento Portland 50kg",
                category_id=1,
                description_html="<p>Cemento Portland de alta calidad para construcción</p>",
                is_masked_seller=True
            ),
            MkProduct(
                seller_company_id=1,
                name="Taladro Percutor 750W",
                category_id=2,
                description_html="<p>Taladro percutor profesional con mandril de 13mm</p>",
                is_masked_seller=True
            )
        ]
        
        for product in demo_products:
            existing = MkProduct.query.filter_by(name=product.name).first()
            if not existing:
                db.session.add(product)
                db.session.flush()
                
                # Add variants
                if "Cemento" in product.name:
                    variant = MkProductVariant(
                        product_id=product.id,
                        sku="CEM-PORT-50KG",
                        price=8999.0,
                        currency="ARS",
                        stock_qty=100
                    )
                    db.session.add(variant)
                elif "Taladro" in product.name:
                    variant = MkProductVariant(
                        product_id=product.id,
                        sku="TAL-PERC-750W",
                        price=45999.0,
                        currency="ARS",
                        stock_qty=25
                    )
                    db.session.add(variant)
        
        db.session.commit()
        print("✅ Marketplace data seeded successfully")

if __name__ == '__main__':
    create_marketplace_tables()
    seed_marketplace_data()