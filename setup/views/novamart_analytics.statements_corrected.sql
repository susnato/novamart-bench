SELECT s.month,
       COALESCE(o.gross, s.gross) AS gross,
       COALESCE(o.fee, s.fee) AS fee,
       COALESCE(o.net, s.net) AS net,
       COALESCE(o.orders_count, s.orders_count) AS orders_count,
       COALESCE(o.created_at, s.created_at) AS created_at
FROM `<warehouse-project>.novamart.statements` s
LEFT JOIN `<warehouse-project>.novamart_analytics.statement_overrides` o ON o.month = s.month
