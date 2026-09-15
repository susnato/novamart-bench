WITH lines AS (
  SELECT
    insertId,
    timestamp AS ts,
    REGEXP_EXTRACT(textPayload, r'^\S+ \[([^\]]+)\] statement: ') AS actor_tag,
    REGEXP_REPLACE(REGEXP_EXTRACT(textPayload, r' statement: (.+)$'),
                   r' -- params:.*$', '') AS qtext
  FROM `<warehouse-project>.novamart_logs.db_queries`
  WHERE STRPOS(textPayload, ' statement: ') > 0
)
SELECT
  CONCAT('nvmq_', insertId) AS job_id,
  qtext AS query,
  UPPER(REGEXP_EXTRACT(qtext, r'^\s*([A-Za-z]+)')) AS statement_type,
  CONCAT(REPLACE(actor_tag, ':', '.'), '@novamart.sim') AS user_email,
  ts AS creation_time,
  ts AS start_time,
  ts AS end_time,
  CAST(NULL AS INT64) AS total_bytes_processed,
  CAST(NULL AS INT64) AS total_slot_ms,
  FALSE AS cache_hit,
  CAST(NULL AS STRUCT<project_id STRING, dataset_id STRING, table_id STRING>) AS destination_table,
  ARRAY(
    SELECT DISTINCT AS STRUCT
      '<warehouse-project>' AS project_id,
      CASE
        WHEN STRPOS(tbl, '.') > 0 AND SPLIT(tbl, '.')[OFFSET(0)] = 'analytics'
          THEN 'novamart_analytics'
        WHEN STRPOS(tbl, '.') > 0 THEN SPLIT(tbl, '.')[OFFSET(0)]
        ELSE 'novamart'
      END AS dataset_id,
      IF(STRPOS(tbl, '.') > 0, SPLIT(tbl, '.')[OFFSET(1)], tbl) AS table_id
    FROM UNNEST(REGEXP_EXTRACT_ALL(qtext,
         r'(?i)(?:FROM|JOIN|INTO|UPDATE)\s+([a-zA-Z_][a-zA-Z0-9_.]*)')) AS tbl
    WHERE LOWER(tbl) NOT IN ('select', 'unnest')
  ) AS referenced_tables,
  'QUERY' AS job_type,
  'DONE' AS state,
  CAST(NULL AS STRUCT<reason STRING, location STRING, message STRING>) AS error_result
FROM lines
WHERE qtext IS NOT NULL AND qtext != ''
