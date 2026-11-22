"""
Database utilities for paginated Supabase queries.

CRITICAL: Supabase Python SDK has an invisible 1000-row default limit on .execute().
This module provides utilities to work around that by paginating queries.

ALWAYS use these utilities for any query that could return >1000 rows.
"""

import logging
from typing import List, Dict, Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 1000  # Supabase max rows per query


def fetch_all_paginated(
    query_builder: Callable,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch ALL rows from a Supabase query by paginating through .range().

    This bypasses the invisible 1000-row default limit that .execute() applies.

    Args:
        query_builder: Callable that returns a FRESH query builder each call.
                       Must support .range(start, end) chaining.
                       Example:
                           lambda: db.table('vacantes').select('*').eq('source', 'linkedin_jobs')
        page_size: Rows per page (max 1000 per Supabase limits).
        max_pages: Safety limit on number of pages. None = unlimited.

    Returns:
        Combined list of ALL rows from all pages.

    Raises:
        Exception: Propagates errors from the underlying query.

    Example:
        from pipeline.db_utils import fetch_all_paginated

        skills = fetch_all_paginated(
            lambda: client.table('job_skills').select('id, vacancy_id, skill')
        )
        # Returns ALL skills, not just first 1000.
    """
    all_rows: List[Dict[str, Any]] = []
    page = 0

    while True:
        start = page * page_size
        end = start + page_size - 1

        response = query_builder().range(start, end).execute()
        batch = response.data or []

        if not batch:
            break

        all_rows.extend(batch)

        # If we got fewer rows than page_size, this was the last page.
        if len(batch) < page_size:
            break

        page += 1

        if max_pages is not None and page >= max_pages:
            logger.warning(
                f"fetch_all_paginated: reached max_pages limit ({max_pages}) "
                f"after {len(all_rows)} rows. Possible missing data."
            )
            break

    logger.info(
        f"fetch_all_paginated: retrieved {len(all_rows)} rows across {page + 1} page(s)"
    )
    return all_rows


def get_exact_count(query_builder: Callable) -> int:
    """
    Get the EXACT row count for a Supabase query.

    Uses count='exact' which bypasses the data truncation issue.
    This is safer than len(response.data) when there are >1000 rows.

    Args:
        query_builder: Callable that returns a fresh query builder.
                       The builder should NOT already include .select() — this function adds it.
                       Example:
                           lambda: db.table('vacantes').eq('source', 'linkedin_jobs')

    Returns:
        Exact count of rows matching the query.

    Example:
        from pipeline.db_utils import get_exact_count

        total = get_exact_count(lambda: client.table('job_skills'))
        print(f"Real total: {total} skills")  # Returns 21296, not capped at 1000
    """
    response = query_builder().select('id', count='exact').limit(1).execute()
    return response.count or 0


def fetch_unique_values(
    query_builder: Callable,
    field: str,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> set:
    """
    Get the set of unique values for a given field across ALL rows.

    Useful for things like "how many unique vacancies have skills" without
    loading the full table into memory.

    Args:
        query_builder: Fresh query builder callable (must already .select(field))
        field: The field name to extract unique values from.
        page_size: Rows per page.

    Returns:
        Set of unique values.

    Example:
        unique_vacancy_ids = fetch_unique_values(
            lambda: client.table('job_skills').select('vacancy_id'),
            field='vacancy_id'
        )
    """
    rows = fetch_all_paginated(query_builder, page_size=page_size)
    return set(r[field] for r in rows if r.get(field) is not None)
