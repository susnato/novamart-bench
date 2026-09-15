WITH chargebacks_by_month AS (
  SELECT FORMAT_DATETIME('%Y-%m',
           DATETIME_TRUNC(DATETIME(o.created_at, 'America/New_York'), MONTH)) AS month,
         SUM(c.amount) AS chargeback_amount
  FROM `<warehouse-project>.novamart_analytics.chargebacks` c
  JOIN `<warehouse-project>.novamart.orders` o ON o.id = c.order_id
  GROUP BY 1
)
SELECT sc.month,
       ROUND(sc.gross - COALESCE(cb.chargeback_amount, 0), 2) AS gross,
       sc.fee,
       ROUND(sc.net - COALESCE(cb.chargeback_amount, 0), 2) AS net,
       sc.orders_count,
       sc.created_at
FROM `<warehouse-project>.novamart_analytics.statements_corrected` sc
LEFT JOIN chargebacks_by_month cb ON cb.month = sc.month
