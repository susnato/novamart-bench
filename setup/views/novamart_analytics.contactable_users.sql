SELECT id AS user_id, email, created_at
FROM `<warehouse-project>.novamart.users`
WHERE marketing_opt_in
  AND REGEXP_CONTAINS(email, r'(?i)^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$')
  AND LOWER(SPLIT(email, '@')[SAFE_OFFSET(1)])
      NOT IN ('example.com', 'example.net', 'example.org')
  AND NOT (LOWER(SPLIT(email, '@')[SAFE_OFFSET(1)]) LIKE '%.example')
