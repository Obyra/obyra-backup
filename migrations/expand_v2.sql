-- Expand phase for OBYRA v2 platform modules.
-- Run in additive-only mode. All foreign keys are deferrable to avoid blocking legacy traffic.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS suppliers (
    id UUID PRIMARY KEY,
    organization_id UUID,
    name TEXT NOT NULL,
    tax_id TEXT,
    country_code TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supplier_users (
    id UUID PRIMARY KEY,
    supplier_id UUID REFERENCES suppliers(id) DEFERRABLE INITIALLY DEFERRED,
    user_id UUID,
    role TEXT NOT NULL,
    invited_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY,
    supplier_id UUID REFERENCES suppliers(id) DEFERRABLE INITIALLY DEFERRED,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    unit_of_measure TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product_prices (
    id UUID PRIMARY KEY,
    product_id UUID REFERENCES products(id) DEFERRABLE INITIALLY DEFERRED,
    currency TEXT NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id UUID PRIMARY KEY,
    organization_id UUID,
    supplier_id UUID,
    status TEXT NOT NULL,
    total_amount NUMERIC(14,2),
    currency TEXT,
    requested_at TIMESTAMPTZ,
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id UUID PRIMARY KEY,
    purchase_order_id UUID REFERENCES purchase_orders(id) DEFERRABLE INITIALLY DEFERRED,
    product_id UUID,
    quantity NUMERIC(12,2) NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL,
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY,
    organization_id UUID,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payment_methods (
    id UUID PRIMARY KEY,
    organization_id UUID,
    provider TEXT NOT NULL,
    token TEXT NOT NULL,
    last4 TEXT,
    brand TEXT,
    exp_month INT,
    exp_year INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analytics_events (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    event_name TEXT NOT NULL,
    payload JSONB,
    occurred_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    user_id UUID,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id UUID,
    payload JSONB,
    occurred_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feature_flags (
    id UUID PRIMARY KEY,
    tenant_id UUID,
    flag TEXT NOT NULL,
    enabled BOOLEAN NOT NULL,
    enabled_at TIMESTAMPTZ,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_feature_flags_tenant_flag ON feature_flags (tenant_id, flag);
CREATE INDEX IF NOT EXISTS idx_analytics_events_tenant ON analytics_events (tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON audit_log (tenant_id, occurred_at DESC);

