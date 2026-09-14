CREATE TABLE analytics.blank_brand_products (
    product_id bigint,
    title text,
    category text,
    brand text,
    vendor text,
    units bigint,
    revenue numeric(14,2),
    first_order_at timestamp with time zone,
    last_order_at timestamp with time zone,
    suspected_cause text,
    captured_at timestamp with time zone
);

CREATE TABLE analytics.category_name_history (
    code text NOT NULL,
    display_group text NOT NULL,
    valid_from date NOT NULL
);

CREATE TABLE analytics.category_names (
    code text NOT NULL,
    display_group text NOT NULL,
    valid_from date NOT NULL
);

CREATE TABLE analytics.chargebacks (
    order_id bigint NOT NULL,
    amount numeric(12,2) NOT NULL,
    reported_at timestamp with time zone NOT NULL
);

CREATE TABLE public.users (
    id bigint NOT NULL,
    email text NOT NULL,
    name text DEFAULT ''::text NOT NULL,
    region text DEFAULT ''::text NOT NULL,
    signup_channel text DEFAULT ''::text NOT NULL,
    device text DEFAULT ''::text NOT NULL,
    age_band text DEFAULT ''::text NOT NULL,
    marketing_opt_in boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE VIEW analytics.contactable_users AS
 SELECT id AS user_id,
    email,
    created_at
   FROM public.users u
  WHERE (marketing_opt_in AND (email ~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$'::text) AND (lower(split_part(email, '@'::text, 2)) <> ALL (ARRAY['example.com'::text, 'example.net'::text, 'example.org'::text])) AND (lower(split_part(email, '@'::text, 2)) !~~ '%.example'::text));

CREATE TABLE analytics.daily_funnel (
    day date,
    sessions integer,
    users_active integer,
    created_at timestamp with time zone
);

CREATE TABLE analytics.digest_log (
    sent_at timestamp with time zone,
    recipients integer,
    top_product bigint
);

CREATE TABLE analytics.kpi_daily (
    day date,
    active_customers integer,
    created_at timestamp with time zone
);

CREATE TABLE analytics.model_registry (
    version text,
    trained_at timestamp with time zone,
    coef_json text,
    train_rows integer
);

CREATE TABLE analytics.model_scores (
    base_pid bigint,
    rec_pid bigint,
    score numeric(10,4),
    updated_at timestamp with time zone
);

CREATE TABLE analytics.order_risk (
    order_id bigint,
    score numeric(6,4),
    core numeric(6,4),
    new_account boolean,
    high_velocity boolean,
    scored_at timestamp with time zone
);

CREATE TABLE analytics.price_history (
    product_id bigint NOT NULL,
    list_price numeric(12,2) NOT NULL,
    valid_from timestamp with time zone NOT NULL
);

CREATE TABLE analytics.price_suggestions (
    product_id bigint,
    current_price numeric(12,2),
    suggested_price numeric(12,2),
    demand_units integer,
    created_at timestamp with time zone
);

CREATE TABLE analytics.product_affinity (
    base_pid bigint,
    rec_pid bigint,
    score numeric(10,4),
    pairs_seen integer,
    updated_at timestamp with time zone
);

CREATE TABLE analytics.product_affinity_v2 (
    base_pid bigint,
    rec_pid bigint,
    score numeric(10,4),
    pairs_seen integer,
    model_version text,
    updated_at timestamp with time zone
);

CREATE TABLE analytics.rec_decision_log (
    ts timestamp with time zone,
    user_id bigint,
    base_pid bigint,
    items text,
    intended_version text,
    effective_version text,
    rec_source text,
    fallback_reason text,
    arm text
);

CREATE TABLE public.orders (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    product_id bigint NOT NULL,
    price numeric(12,2) NOT NULL,
    payment_ref text NOT NULL,
    status integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

CREATE TABLE public.payments (
    id bigint NOT NULL,
    order_id bigint NOT NULL,
    gross numeric(12,2) NOT NULL,
    fee numeric(12,2) NOT NULL,
    net numeric(12,2) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    payment_ref text
);

CREATE VIEW analytics.refunds_unified AS
 SELECT o.id AS order_id,
        CASE
            WHEN (o.status = 2) THEN 'order_cancelled'::text
            WHEN (o.status = 3) THEN 'order_refunded'::text
            ELSE NULL::text
        END AS kind,
    o.price AS amount,
    o.updated_at AS at
   FROM public.orders o
  WHERE (o.status = ANY (ARRAY[2, 3]))
UNION ALL
 SELECT p.order_id,
    'gateway_refund'::text AS kind,
        CASE
            WHEN (p.gross < (0)::numeric) THEN abs(p.gross)
            ELSE abs(p.net)
        END AS amount,
    p.created_at AS at
   FROM public.payments p
  WHERE ((p.gross < (0)::numeric) OR (p.net < (0)::numeric));

CREATE TABLE analytics.reorder_hints (
    product_id bigint,
    velocity numeric(10,4),
    hint_units integer,
    created_at timestamp with time zone
);

CREATE TABLE analytics.statement_corrections (
    month text NOT NULL,
    delta numeric(12,2) NOT NULL,
    reason text NOT NULL
);

CREATE TABLE analytics.statement_overrides (
    month text NOT NULL,
    gross numeric(12,2) NOT NULL,
    fee numeric(12,2) NOT NULL,
    net numeric(12,2) NOT NULL,
    orders_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    note text NOT NULL
);

CREATE TABLE public.statements (
    month text NOT NULL,
    gross numeric(14,2) NOT NULL,
    fee numeric(14,2) NOT NULL,
    net numeric(14,2) NOT NULL,
    orders_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE VIEW analytics.statements_corrected AS
 SELECT s.month,
    COALESCE(o.gross, s.gross) AS gross,
    COALESCE(o.fee, s.fee) AS fee,
    COALESCE(o.net, s.net) AS net,
    COALESCE(o.orders_count, s.orders_count) AS orders_count,
    COALESCE(o.created_at, s.created_at) AS created_at
   FROM (public.statements s
     LEFT JOIN analytics.statement_overrides o ON ((o.month = s.month)));

CREATE VIEW analytics.statements_final AS
 WITH chargebacks_by_month AS (
         SELECT to_char(date_trunc('month'::text, (o.created_at AT TIME ZONE 'America/New_York'::text)), 'YYYY-MM'::text) AS month,
            sum(c.amount) AS chargeback_amount
           FROM (analytics.chargebacks c
             JOIN public.orders o ON ((o.id = c.order_id)))
          GROUP BY (to_char(date_trunc('month'::text, (o.created_at AT TIME ZONE 'America/New_York'::text)), 'YYYY-MM'::text))
        )
 SELECT sc.month,
    round((sc.gross - COALESCE(cb.chargeback_amount, (0)::numeric)), 2) AS gross,
    sc.fee,
    round((sc.net - COALESCE(cb.chargeback_amount, (0)::numeric)), 2) AS net,
    sc.orders_count,
    sc.created_at
   FROM (analytics.statements_corrected sc
     LEFT JOIN chargebacks_by_month cb ON ((cb.month = sc.month)));

CREATE TABLE analytics.test_users (
    user_id bigint NOT NULL
);

CREATE TABLE analytics.trending_daily (
    day date,
    rank integer,
    product_id bigint,
    score numeric(12,4),
    units integer,
    created_at timestamp with time zone
);

CREATE TABLE public.account_map (
    uid bigint NOT NULL,
    account_id uuid NOT NULL,
    linked_at timestamp with time zone NOT NULL
);

CREATE TABLE public.accounts (
    account_id uuid NOT NULL,
    email text NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.cart_items (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    product_id bigint NOT NULL,
    session text NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.order_lines (
    order_id bigint NOT NULL,
    product_id bigint NOT NULL,
    price numeric NOT NULL,
    session text NOT NULL,
    payment_ref text NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.products (
    id bigint NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    category text DEFAULT ''::text NOT NULL,
    brand text DEFAULT ''::text NOT NULL,
    vendor text DEFAULT ''::text NOT NULL,
    list_price numeric(12,2) NOT NULL,
    cost_price numeric(12,2) DEFAULT 0 NOT NULL,
    stock integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.report_rows (
    report_date date NOT NULL,
    product_id bigint NOT NULL,
    units integer NOT NULL,
    revenue numeric(14,2) NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.report_rows_intraday (
    report_date date NOT NULL,
    product_id bigint NOT NULL,
    units integer NOT NULL,
    revenue numeric(14,2) NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.top_products (
    rank integer,
    product_id bigint,
    units integer,
    report_date date,
    created_at timestamp with time zone
);