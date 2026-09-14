-- novamart schema. Apply once: psql $NOVAMART_DSN -f schema.sql

-- scratch space for analysts and batch jobs; app tables stay clean
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS users (
    id               BIGINT PRIMARY KEY,
    email            TEXT NOT NULL,
    name             TEXT NOT NULL DEFAULT '',
    region           TEXT NOT NULL DEFAULT '',
    signup_channel   TEXT NOT NULL DEFAULT '',
    device           TEXT NOT NULL DEFAULT '',
    age_band         TEXT NOT NULL DEFAULT '',
    marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          BIGINT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    vendor      TEXT NOT NULL DEFAULT '',
    list_price  NUMERIC(12,2) NOT NULL,
    cost_price  NUMERIC(12,2) NOT NULL DEFAULT 0,
    stock       INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS cart_items (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    product_id  BIGINT NOT NULL,
    session     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    product_id  BIGINT NOT NULL,
    price       NUMERIC(12,2) NOT NULL,
    payment_ref TEXT NOT NULL,
    status      INT NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_ref ON orders(payment_ref);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);

CREATE TABLE IF NOT EXISTS payments (
    id          BIGSERIAL PRIMARY KEY,
    order_id    BIGINT NOT NULL REFERENCES orders(id),
    gross       NUMERIC(12,2) NOT NULL,
    fee         NUMERIC(12,2) NOT NULL,
    net         NUMERIC(12,2) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS report_rows (
    report_date DATE NOT NULL,
    product_id  BIGINT NOT NULL,
    units       INT NOT NULL,
    revenue     NUMERIC(14,2) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_date ON report_rows(report_date);

CREATE TABLE IF NOT EXISTS statements (
    month        TEXT NOT NULL,
    gross        NUMERIC(14,2) NOT NULL,
    fee          NUMERIC(14,2) NOT NULL,
    net          NUMERIC(14,2) NOT NULL,
    orders_count INT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL
);
