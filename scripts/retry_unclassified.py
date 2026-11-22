#!/usr/bin/env python3
"""
One-off retry of vacancies left without a classification by previous runs.

Background: ~6.9% of the 28-may run (188 rows) finished with
`classification IS NULL` due to transient OpenRouter errors. This script
fetches just that subset and re-runs the classifier on it in parallel.
It does NOT re-scrape or re-extract — only the (cheap) classification pass.

Usage:
    python scripts/retry_unclassified.py                    # default concurrency 8
    python scripts/retry_unclassified.py --concurrency 4    # gentler on the API
    python scripts/retry_unclassified.py --limit 10         # try a small batch first
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from classification.openrouter_classifier import OpenRouterClassifier
from pipeline.db_utils import fetch_all_paginated
from pipeline.loader import SupabaseLoader

load_dotenv()

logger = logging.getLogger(__name__)


def _connect() -> SupabaseLoader:
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_ANON_KEY')
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and a service/anon key are required.")
    if not os.getenv('SUPABASE_SERVICE_ROLE_KEY'):
        logger.warning(
            "SUPABASE_SERVICE_ROLE_KEY not set — UPDATEs may silently fail "
            "under RLS."
        )
    loader = SupabaseLoader(url, key)
    if not loader.client:
        raise RuntimeError("Supabase client failed to initialize.")
    return loader


def _fetch_unclassified(loader: SupabaseLoader, limit: int | None) -> list[dict]:
    """All rows with `classification IS NULL`, paginated."""
    rows = fetch_all_paginated(
        lambda: loader.client.table('vacantes')
        .select('id, raw_title, raw_description, company_name, country')
        .is_('classification', 'null')
    )
    if limit is not None and limit > 0:
        rows = rows[:limit]
    return rows


async def _run(concurrency: int, limit: int | None, model: str) -> int:
    loader = _connect()

    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY required")

    pending = _fetch_unclassified(loader, limit)
    logger.info(f"Fetched {len(pending)} unclassified vacancies")
    if not pending:
        return 0

    async with OpenRouterClassifier(api_key) as classifier:
        # classify_batch already parallelizes via Semaphore + truncates the
        # description for the classification pass — exactly what we want here.
        results = await classifier.classify_batch(
            pending,
            batch_name='retry_unclassified',
            model=model,
            concurrency=concurrency,
        )

    updated = 0
    failed = 0
    for vac, classification in zip(pending, results):
        if classification is None:
            failed += 1
            continue
        ok = loader.update_classification(vac['id'], classification)
        if ok:
            updated += 1
        else:
            failed += 1

    logger.info(
        f"Retry done: {updated} updated, {failed} still failing "
        f"out of {len(pending)}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--concurrency', type=int, default=8)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument(
        '--model',
        default=os.getenv('CLASSIFICATION_MODEL', 'openai/gpt-3.5-turbo'),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s'
    )

    return asyncio.run(_run(args.concurrency, args.limit, args.model))


if __name__ == '__main__':
    sys.exit(main())
