"""Ops runbook: recompute a day's discounted revenue after a job failure.

Usage: python scripts/rerun_kpis.py  (run from repo root)
"""
from novamart.jobs.discounts import apply_discounts


def main():
    # ops one-off: pull yesterday's rows and reapply the promo cap
    rows = []  # filled by hand from the failed day's report export
    print(apply_discounts(rows))


if __name__ == "__main__":
    main()
