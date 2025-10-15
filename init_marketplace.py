"""
OBYRA Market - Database Initialization
Creates tables and seeds initial data for the marketplace
"""

from datetime import datetime
import os

from sqlalchemy import inspect

from app import app, db
from models_marketplace import *

def init_marketplace_db():
    """Initialize marketplace database tables and seed data"""
    
    try:
        with app.app_context():
            uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
            if os.getenv("AUTO_CREATE_DB", "0") == "1" and uri.startswith("sqlite:"):
                print("🏗️  Creating marketplace database tables (SQLite dev mode)...")
                db.create_all()
            else:
                inspector = inspect(db.engine)
                required_tables = [
                    MarketCategory.__tablename__,
                    MarketBrand.__tablename__,
                    MarketCommission.__tablename__,
                    MarketCompany.__tablename__,
                    MarketUser.__tablename__,
                ]
                missing_tables = [
                    table for table in required_tables if not inspector.has_table(table)
                ]
                if missing_tables:
                    print(
                        "⚠️  Marketplace tables missing: "
                        f"{', '.join(missing_tables)}. Run migrations before seeding."
                    )
                    return
            
            # Seed basic data
            seed_categories()
            seed_brands()
            seed_commissions()
            seed_demo_companies()
            
            db.session.commit()
            print("✅ Marketplace database initialized successfully")
    except Exception as e:
        print(f"⚠️  Marketplace initialization error: {e}")
        # Don't break the app startup

def seed_categories():
    """Seed initial categories"""
    categories_data = [
        {'name': 'Materiales de Construcción', 'slug': 'materiales'},
        {'name': 'Herramientas', 'slug': 'herramientas'},
        {'name': 'Maquinaria', 'slug': 'maquinaria'},
        {'name': 'Seguridad', 'slug': 'seguridad'},
        {'name': 'Electricidad', 'slug': 'electricidad'},
        {'name': 'Plomería', 'slug': 'plomeria'},
        {'name': 'Pintura', 'slug': 'pintura'},
        {'name': 'Cemento y Hormigón', 'slug': 'cemento-hormigon'},
        {'name': 'Hierro y Acero', 'slug': 'hierro-acero'},
        {'name': 'Maderas', 'slug': 'maderas'}
    ]
    
    for cat_data in categories_data:
        existing = MarketCategory.query.filter_by(slug=cat_data['slug']).first()
        if not existing:
            category = MarketCategory(
                name=cat_data['name'],
                slug=cat_data['slug'],
                is_active=True
            )
            db.session.add(category)
    
    print("📂 Categories seeded")

def seed_brands():
    """Seed initial brands"""
    brands_data = [
        'Caterpillar', 'Bosch', 'Makita', 'DeWalt', 'Stanley',
        'Bahco', 'Milwaukee', 'Black & Decker', 'Hilti', 'Karcher',
        'Loma Negra', 'Petroquímica Comodoro Rivadavia', 'Aluar',
        'Acindar', 'Siderar', 'Ferrum', 'FV', 'Schneider Electric',
        'Philips', 'General Electric'
    ]
    
    for brand_name in brands_data:
        existing = MarketBrand.query.filter_by(name=brand_name).first()
        if not existing:
            brand = MarketBrand(name=brand_name, is_active=True)
            db.session.add(brand)
    
    print("🏷️  Brands seeded")

def seed_commissions():
    """Seed commission configuration"""
    # Get categories
    materiales = MarketCategory.query.filter_by(slug='materiales').first()
    herramientas = MarketCategory.query.filter_by(slug='herramientas').first()
    maquinaria = MarketCategory.query.filter_by(slug='maquinaria').first()
    
    if not all([materiales, herramientas, maquinaria]):
        print("⚠️  Categories not found for commission seeding")
        return
    
    commissions_data = [
        {'category_id': materiales.id, 'exposure': 'clasica', 'take_rate_pct': 8.0},
        {'category_id': materiales.id, 'exposure': 'premium', 'take_rate_pct': 12.0},
        {'category_id': herramientas.id, 'exposure': 'clasica', 'take_rate_pct': 10.0},
        {'category_id': herramientas.id, 'exposure': 'premium', 'take_rate_pct': 14.0},
        {'category_id': maquinaria.id, 'exposure': 'clasica', 'take_rate_pct': 6.0},
        {'category_id': maquinaria.id, 'exposure': 'premium', 'take_rate_pct': 10.0},
    ]
    
    for comm_data in commissions_data:
        existing = MarketCommission.query.filter_by(
            category_id=comm_data['category_id'],
            exposure=comm_data['exposure']
        ).first()
        
        if not existing:
            commission = MarketCommission(**comm_data)
            db.session.add(commission)
    
    print("💰 Commission rates seeded")

def seed_demo_companies():
    """Seed demo companies and users"""
    
    # Demo buyer company
    buyer_company = MarketCompany.query.filter_by(cuit='20123456789').first()
    if not buyer_company:
        buyer_company = MarketCompany(
            name='Constructora Demo SA',
            cuit='20123456789',
            type='buyer',
            iva_condition='RI',
            billing_email='compras@constructorademo.com',
            is_active=True,
            kyc_status='approved'
        )
        db.session.add(buyer_company)
        db.session.flush()
        
        # Demo buyer user
        buyer_user = MarketUser(
            company_id=buyer_company.id,
            name='Juan Comprador',
            email='juan@constructorademo.com',
            role='buyer_admin',
            password_hash='demo_hash',
            is_active=True
        )
        db.session.add(buyer_user)
    
    # Demo seller companies
    seller_companies_data = [
        {
            'name': 'Proveedora ABC SRL',
            'cuit': '30987654321',
            'email': 'ventas@proveedoraabc.com'
        },
        {
            'name': 'Materiales del Sur SA',
            'cuit': '30555666777',
            'email': 'pedidos@materialesdelsur.com'
        },
        {
            'name': 'Herramientas Pro SRL',
            'cuit': '30111222333',
            'email': 'info@herramientaspro.com'
        }
    ]
    
    for seller_data in seller_companies_data:
        existing_seller = MarketCompany.query.filter_by(cuit=seller_data['cuit']).first()
        if not existing_seller:
            seller_company = MarketCompany(
                name=seller_data['name'],
                cuit=seller_data['cuit'],
                type='seller',
                iva_condition='RI',
                billing_email=seller_data['email'],
                is_active=True,
                kyc_status='approved'
            )
            db.session.add(seller_company)
            db.session.flush()
            
            # Demo seller user
            seller_user = MarketUser(
                company_id=seller_company.id,
                name=f'Vendedor {seller_company.name}',
                email=seller_data['email'],
                role='seller_admin',
                password_hash='demo_hash',
                is_active=True
            )
            db.session.add(seller_user)
    
    print("🏢 Demo companies and users seeded")

def seed_demo_products():
    """Seed demo products (optional)"""
    
    # Get demo seller
    seller = MarketCompany.query.filter_by(type='seller').first()
    if not seller:
        print("⚠️  No seller company found for product seeding")
        return
    
    # Get categories and brands
    materiales_cat = MarketCategory.query.filter_by(slug='materiales').first()
    herramientas_cat = MarketCategory.query.filter_by(slug='herramientas').first()
    bosch_brand = MarketBrand.query.filter_by(name='Bosch').first()
    
    if not all([materiales_cat, herramientas_cat, bosch_brand]):
        print("⚠️  Required categories/brands not found for product seeding")
        return
    
    # Demo products
    products_data = [
        {
            'name': 'Taladro Percutor Bosch GSB 550',
            'brand_id': bosch_brand.id,
            'category_id': herramientas_cat.id,
            'description_html': '<p>Taladro percutor profesional de 550W con mandril de 13mm</p>',
            'warranty_months': 12,
            'variants': [
                {
                    'sku': 'BOSCH-GSB550-001',
                    'price': 45999.0,
                    'weight_kg': 1.8,
                    'length_cm': 25,
                    'width_cm': 8,
                    'height_cm': 20
                }
            ]
        },
        {
            'name': 'Cemento Portland 50kg',
            'category_id': materiales_cat.id,
            'description_html': '<p>Cemento Portland tipo CPN-40 bolsa de 50kg</p>',
            'variants': [
                {
                    'sku': 'CEM-PORT-50KG',
                    'price': 8999.0,
                    'weight_kg': 50,
                    'length_cm': 60,
                    'width_cm': 40,
                    'height_cm': 15
                }
            ]
        }
    ]
    
    for prod_data in products_data:
        existing = MarketProduct.query.filter_by(name=prod_data['name']).first()
        if not existing:
            variants_data = prod_data.pop('variants')
            
            product = MarketProduct(
                seller_company_id=seller.id,
                is_masked_seller=True,
                **prod_data
            )
            db.session.add(product)
            db.session.flush()
            
            # Add variants
            for variant_data in variants_data:
                variant = MarketProductVariant(
                    product_id=product.id,
                    currency='ARS',
                    tax_class='IVA_21',
                    is_active=True,
                    **variant_data
                )
                db.session.add(variant)
                db.session.flush()
                
                # Add publication
                publication = MarketPublication(
                    product_id=product.id,
                    exposure='clasica',
                    status='active',
                    start_at=datetime.utcnow()
                )
                db.session.add(publication)
    
    print("📦 Demo products seeded")

if __name__ == '__main__':
    init_marketplace_db()
    # Uncomment to seed demo products
    # seed_demo_products()
    # db.session.commit()