#!/usr/bin/env python3
"""
One-off cleanup of semantic-duplicate vacancies in the `vacantes` table.

Background: until the cross-run semantic dedup added in `loader.py`,
LinkedIn promoted/paginated re-posts entered the DB as separate rows
(same company + title + country, different URLs and `vacancy_hash`).
This script collapses each duplicate group down to the OLDEST row by
`created_at`, deleting the rest plus their `job_skills` children.

Defaults to dry-run. Pass `--execute` to apply changes.

A full backup of `vacantes` and `job_skills` is written to `backups/`
BEFORE any destructive operation, even in dry-run (so the artefact is
always available).

Usage:
    python scripts/cleanup_duplicates.py           # dry-run, prints groups
    python scripts/cleanup_duplicates.py --execute # apply deletions
    python scripts/cleanup_duplicates.py --top 20  # only show top 20 groups
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Allow running this script directly from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.cleaner import DataCleaner
from pipeline.db_utils import fetch_all_paginated
from pipeline.loader import SupabaseLoader

load_dotenv()

logger = logging.getLogger(__name__)


def _connect() -> SupabaseLoader:
    """Build a loader using the service-role key (required for DELETE)."""
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_ANON_KEY')
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and a service/anon key are required.")
    loader = SupabaseLoader(url, key)
    if not loader.client:
        raise RuntimeError("Supabase client failed to initialize.")
    return loader


def _backup(loader: SupabaseLoader, backups_dir: Path) -> None:
    """
    Dump full `vacantes` + `job_skills` tables to JSONL in `backups/`.
    Always runs (even in dry-run) so the artefact exists if needed later.
    """
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

    for table in ('vacantes', 'job_skills'):
        rows = fetch_all_paginated(lambda t=table: loader.client.table(t).select('*'))
        path = backups_dir / f'{table}_{ts}.jsonl'
        with open(path, 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, default=str, ensure_ascii=False) + '\n')
        logger.info(f"Backup written: {path} ({len(rows)} rows)")


def _find_duplicate_groups(loader: SupabaseLoader) -> dict:
    """
    Return a mapping `semantic_key -> [vacancy rows]` for every key that has
    more than one row. Each row carries the fields needed to pick a survivor
    and delete the rest.
    """
    rows = fetch_all_paginated(
        lambda: loader.client.table('vacantes').select(
            'id, company_name, raw_title, country, created_at, vacancy_hash'
        )
    )
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[DataCleaner.semantic_key(r)].append(r)
    return {k: g for k, g in groups.items() if len(g) > 1}


def _pick_survivor(group: list[dict]) -> dict:
    """
    Choose the row to keep from a duplicate group: the OLDEST by
    `created_at` (falls back to lowest id if `created_at` is missing/equal).
    """
    def sort_key(row):
        return (row.get('created_at') or '', row.get('id') or 0)
    return min(group, key=sort_key)


def _delete_rows(loader: SupabaseLoader, vacancy_ids: list[int]) -> None:
    """Delete vacancies and their `job_skills` children in batches."""
    if not vacancy_ids:
        return
    BATCH = 50  # keep URL length sane for IN()-style filters
    for i in range(0, len(vacancy_ids), BATCH):
        chunk = vacancy_ids[i : i + BATCH]
        # Delete dependent rows first
        loader.client.table('job_skills').delete().in_('vacancy_id', chunk).execute()
        loader.client.table('vacantes').delete().in_('id', chunk).execute()
        logger.info(f"Deleted batch of {len(chunk)} vacancies + their skills")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--execute', action='store_true',
        help='Apply deletions. Without this flag the script is dry-run only.'
    )
    parser.add_argument(
        '--top', type=int, default=10,
        help='Print the top-N largest duplicate groups (default: 10).'
    )
    parser.add_argument(
        '--no-backup', action='store_true',
        help='Skip the backup step (NOT recommended; for tests only).'
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s'
    )

    loader = _connect()

    backups_dir = Path(__file__).resolve().parent.parent / 'backups'
    if not args.no_backup:
        _backup(loader, backups_dir)

    groups = _find_duplicate_groups(loader)
    total_groups = len(groups)
    total_dups = sum(len(g) - 1 for g in groups.values())
    total_rows = sum(len(g) for g in groups.values())

    logger.info(
        f"Found {total_groups} duplicate groups covering {total_rows} rows; "
        f"{total_dups} rows would be removed."
    )

    # Top-N preview
    top = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[: args.top]
    for key, group in top:
        company, title, country = key
        survivor = _pick_survivor(group)
        logger.info(
            f"  group n={len(group)} | keep id={survivor['id']} created={survivor.get('created_at')} | "
            f"{title[:50]} @ {company[:30]} / {country}"
        )

    if not args.execute:
        logger.info("Dry-run only — pass --execute to apply deletions.")
        return 0

    # Apply
    to_delete: list[int] = []
    for group in groups.values():
        survivor = _pick_survivor(group)
        for row in group:
            if row['id'] != survivor['id']:
                to_delete.append(row['id'])

    logger.info(f"Executing deletion of {len(to_delete)} duplicate vacancies...")
    _delete_rows(loader, to_delete)
    logger.info("Cleanup complete.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
