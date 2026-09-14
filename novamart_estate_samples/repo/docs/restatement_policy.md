# Restatement policy

## Short answer

Both numbers can be "right," but for different purposes.

- If you need the number that was originally published in the November board deck, use `public.statements`.
- If you need the current restated finance number for external/business reporting, use `analytics.statements_final`.

For **October 2019 net revenue** specifically:

- originally published statement net: **1194652.79** in `public.statements`
- fee-corrected statement net: **1194652.93** in `analytics.statements_corrected`
- final restated net after booked chargebacks: **1191085.36** in `analytics.statements_final`

So the November board deck number reflects the **as-published snapshot at that time**. Finance's newer number is the **restated number** if they are reading `analytics.statements_final`.

## Why published numbers can change

Our monthly statement process writes an append-only snapshot into `public.statements` once per run.
That table records what the job published at the time; it is not meant to be rewritten when later facts arrive.

Published numbers can change later for two main reasons:

1. **Statement corrections / overrides**
   - The monthly job originally wrote October 2019 with `fee = 35679.64` and `net = 1194652.79`.
   - Git history on `novamart/jobs/monthly_statement.py` shows a fix on `2019-11-02` (`Fix monthly statement fee to use collected per-order fees`).
   - Production data now carries the corrected October override in `analytics.statement_overrides`, changing October to `fee = 35679.50` and `net = 1194652.93`.
   - `analytics.statements_corrected` applies those overrides on top of the original snapshot.

2. **Later-booked chargebacks**
   - On `2019-12-09` we added `analytics.chargebacks` and the `analytics.statements_final` view.
   - That view subtracts booked chargebacks from the month of the original order.
   - For October 2019, booked chargebacks reduce gross and net by **3567.57**, taking net from `1194652.93` to `1191085.36`.

Because chargebacks and audit corrections may be known only after a month is first published, a later finance report can legitimately differ from the board deck snapshot.

## Which table/view to use

## 1) `public.statements`

Use this when you need the **historical as-published number**.

Examples:

- reproducing the number shown in an older board deck
- checking what the monthly job emitted on the original publication date
- audit trails for "what did we say at the time?"

Important caveat:

- this is the raw published snapshot
- it may include known mistakes that were corrected later
- it does **not** include later restatements like booked chargebacks

## 2) `analytics.statements_corrected`

Use this when you need the **published statement with known statement overrides applied**, but **before** chargebacks.

This view currently reads:

- base rows from `public.statements`
- replacement values from `analytics.statement_overrides`

Examples:

- reconciling a known statement-generation bug fix
- understanding how a restatement changed due to a finance override
- separating statement-generation corrections from chargeback effects

Important caveat:

- this is an intermediate restatement layer
- it is not the final finance reporting surface if chargebacks should be included

## 3) `analytics.statements_final`

Use this for the **current finance / board / external reporting number**.

This view starts from `analytics.statements_corrected` and then subtracts amounts found in `analytics.chargebacks`, grouped back to the original order month.

Examples:

- current net revenue reporting
- finance decks prepared after corrections are known
- any query that should reflect the latest approved restatement logic

Important caveat:

- this number can differ from what was originally published earlier
- that difference is expected when corrections or chargebacks were booked after publication

## Supporting tables

These are useful for understanding restatements, but are usually not the first table to read directly:

- `analytics.statement_overrides`
  - one row per month where a corrected statement value should replace the original snapshot
- `analytics.statement_corrections`
  - audit-style record of correction deltas/reasons
  - useful for explanation, not the primary reporting surface
- `analytics.chargebacks`
  - booked chargeback amounts by `order_id`
  - consumed by `analytics.statements_final`

## Recommended policy

When someone asks "which number is right?" answer in two parts:

1. **As originally published:** read `public.statements`
2. **As currently restated:** read `analytics.statements_final`

Unless the request explicitly says "match the old deck exactly," use **`analytics.statements_final`** for current finance reporting.

## Bottom line for October 2019

- **November board deck / original publication:** `1194652.79`
- **Current restated finance number:** `1191085.36`

The deck was not necessarily wrong; it was **older**. The finance number is the one to use now if the goal is current, restated net revenue.
