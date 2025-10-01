"""Seed script to exercise the v2 supplier + PO flow end-to-end.

Usage:
    python tools/seeds/seed_demo_supplier_flow.py --db postgresql://... --tenant TENANT_UUID

The script is additive-only; it will not modify legacy tables and skips existing
records. Designed for staging/canary environments.
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

SUPPLIER_ID = uuid.uuid4()
PRODUCT_ID = uuid.uuid4()
PRICE_ID = uuid.uuid4()
PO_ID = uuid.uuid4()
PO_ITEM_ID = uuid.uuid4()
SUBSCRIPTION_ID = uuid.uuid4()
PAYMENT_METHOD_ID = uuid.uuid4()


def upsert(engine, statement: str, **params):
    with engine.begin() as conn:
        conn.execute(text(statement), params)


def seed_supplier(engine, tenant_id: str):
    upsert(
        engine,
        """
        INSERT INTO suppliers (id, organization_id, name, tax_id, country_code, created_at)
        VALUES (:id, :org_id, :name, :tax_id, :country, :created_at)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(SUPPLIER_ID),
        org_id=tenant_id,
        name="Proveedor Demo Shadow",
        tax_id="30-99999999-9",
        country="AR",
        created_at=datetime.now(timezone.utc),
    )

    upsert(
        engine,
        """
        INSERT INTO supplier_users (id, supplier_id, user_id, role, invited_at)
        VALUES (:id, :supplier_id, :user_id, :role, :invited_at)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(uuid.uuid4()),
        supplier_id=str(SUPPLIER_ID),
        user_id=str(uuid.uuid4()),
        role="admin",
        invited_at=datetime.now(timezone.utc),
    )


def seed_catalog(engine):
    upsert(
        engine,
        """
        INSERT INTO products (id, supplier_id, sku, name, description, unit_of_measure, metadata)
        VALUES (:id, :supplier_id, :sku, :name, :description, :uom, :metadata::jsonb)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(PRODUCT_ID),
        supplier_id=str(SUPPLIER_ID),
        sku="CEM-OBYRA-25KG",
        name="Cemento OBYRA 25KG",
        description="Bolsa de cemento de alta resistencia.",
        uom="bag",
        metadata='{"category": "materiales"}',
    )

    upsert(
        engine,
        """
        INSERT INTO product_prices (id, product_id, currency, unit_price, valid_from)
        VALUES (:id, :product_id, :currency, :price, :valid_from)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(PRICE_ID),
        product_id=str(PRODUCT_ID),
        currency="ARS",
        price=9500,
        valid_from=datetime.now(timezone.utc),
    )


def seed_billing(engine, tenant_id: str):
    upsert(
        engine,
        """
        INSERT INTO payment_methods (id, organization_id, provider, token, brand, last4, exp_month, exp_year, created_at)
        VALUES (:id, :org_id, :provider, :token, :brand, :last4, :exp_month, :exp_year, :created_at)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(PAYMENT_METHOD_ID),
        org_id=tenant_id,
        provider="mock_psp",
        token="tok_test_visa",
        brand="visa",
        last4="4242",
        exp_month=12,
        exp_year=2030,
        created_at=datetime.now(timezone.utc),
    )

    upsert(
        engine,
        """
        INSERT INTO subscriptions (id, organization_id, plan, status, current_period_start, current_period_end, created_at)
        VALUES (:id, :org_id, :plan, :status, :start, :end, :created)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(SUBSCRIPTION_ID),
        org_id=tenant_id,
        plan="scale",
        status="active",
        start=datetime.now(timezone.utc),
        end=datetime.now(timezone.utc),
        created=datetime.now(timezone.utc),
    )


def seed_po(engine, tenant_id: str):
    upsert(
        engine,
        """
        INSERT INTO purchase_orders (id, organization_id, supplier_id, status, total_amount, currency, requested_at)
        VALUES (:id, :org_id, :supplier_id, :status, :total, :currency, :requested)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(PO_ID),
        org_id=tenant_id,
        supplier_id=str(SUPPLIER_ID),
        status="draft",
        total=19000,
        currency="ARS",
        requested=datetime.now(timezone.utc),
    )

    upsert(
        engine,
        """
        INSERT INTO purchase_order_items (id, purchase_order_id, product_id, quantity, unit_price, metadata)
        VALUES (:id, :po_id, :product_id, :qty, :unit_price, :metadata::jsonb)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(PO_ITEM_ID),
        po_id=str(PO_ID),
        product_id=str(PRODUCT_ID),
        qty=2,
        unit_price=9500,
        metadata='{"notes": "Entrega en 48h"}',
    )


def seed_audit(engine, tenant_id: str):
    upsert(
        engine,
        """
        INSERT INTO audit_log (id, tenant_id, user_id, action, entity, entity_id, payload, occurred_at)
        VALUES (:id, :tenant_id, :user_id, :action, :entity, :entity_id, :payload::jsonb, :occurred)
        ON CONFLICT (id) DO NOTHING
        """,
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=str(uuid.uuid4()),
        action="seed_demo_supplier_flow",
        entity="purchase_order",
        entity_id=str(PO_ID),
        payload='{"status": "draft"}',
        occurred=datetime.now(timezone.utc),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed demo supplier + PO data")
    parser.add_argument("--db", required=True, help="SQLAlchemy database URL")
    parser.add_argument("--tenant", required=True, help="Tenant UUID")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    engine = create_engine(args.db)

    seed_supplier(engine, args.tenant)
    seed_catalog(engine)
    seed_billing(engine, args.tenant)
    seed_po(engine, args.tenant)
    seed_audit(engine, args.tenant)

    print("✅ Demo supplier flow seeded successfully")


if __name__ == "__main__":
    main()
