SELECT o.id AS order_id,
       CASE WHEN o.status = 2 THEN 'order_cancelled'
            WHEN o.status = 3 THEN 'order_refunded'
       END AS kind,
       o.price AS amount,
       o.updated_at AS `at`
FROM `<warehouse-project>.novamart.orders` o
WHERE o.status IN (2, 3)
UNION ALL
SELECT p.order_id,
       'gateway_refund' AS kind,
       CASE WHEN p.gross < 0 THEN ABS(p.gross) ELSE ABS(p.net) END AS amount,
       p.created_at AS `at`
FROM `<warehouse-project>.novamart.payments` p
WHERE p.gross < 0 OR p.net < 0
