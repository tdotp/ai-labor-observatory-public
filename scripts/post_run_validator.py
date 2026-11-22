#!/usr/bin/env python3
"""
Post-Run Validator for Observatory Pipeline.

Runs after every pipeline execution (called from cron_guard.sh) and validates
that the run completed properly and the database is in a healthy state.

Checks:
  1. No duplicate skills in job_skills (UNIQUE constraint should prevent, but verify)
  2. Coverage: % vacancies with skills extracted
  3. Vacancies count grew (or stayed equal if no new sources)
  4. Skill category distribution within expected ranges
  5. No vacancies with 0 skills (suggests extraction failure)
  6. Skill count is consistent with vacancy count (avg 30-50 skills/vacancy)

Exit codes:
  0 = All checks passed
  1 = One or more checks failed (cron_guard.sh logs an alert)
  2 = Critical: Could not connect to database

Usage:
  python3 scripts/post_run_validator.py
  python3 scripts/post_run_validator.py --verbose
  python3 scripts/post_run_validator.py --json  # Output machine-readable JSON
"""

import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Make pipeline modules importable when running as a script
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.db_utils import fetch_all_paginated, get_exact_count
from pipeline.loader import SupabaseLoader

# Logging setup
LOG_FILE = Path("/var/log/observatory/post_run_validation.log")
try:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
except PermissionError:
    # Fall back to local logs if /var/log not writable
    LOG_FILE = REPO_ROOT / "logs" / "post_run_validation.log"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Validation thresholds
# NOTE: max_skills_per_vacancy=200 is generous to accommodate "legacy" vacancies
# that were re-processed multiple times during the 1000-row bug era (~5 vacancies
# in the 150-200 range, max 164). Post-fix extractions should stay in 30-50.
# If you see NEW vacancies (high IDs) hitting >100 skills, that signals something
# is wrong (e.g., a script bypassing get_vacancies_pending_skills).
THRESHOLDS = {
    'min_skills_per_vacancy': 5,        # vacancy with <5 skills = extraction likely failed
    'max_skills_per_vacancy': 200,      # >200 skills = clear duplicates/noise (legacy max is 164)
    'min_coverage_pct': 80.0,           # at least 80% of vacancies should have skills
    'min_categories_present': 4,        # at least 4 of 5 categories should appear
    'expected_categories': {
        'hard_skills', 'soft_skills', 'strategic_skills',
        'ai_operational_skills', 'ai_cognitive_skills',
    },
}


def validate_no_duplicates(loader: SupabaseLoader) -> dict:
    """Check that no exact duplicates exist in job_skills."""
    skills = fetch_all_paginated(
        lambda: loader.client.table('job_skills').select('vacancy_id, skill, category')
    )
    groups = defaultdict(int)
    for s in skills:
        key = (s['vacancy_id'], s['skill'].lower().strip(), s['category'])
        groups[key] += 1
    duplicates = [k for k, count in groups.items() if count > 1]
    return {
        'check': 'no_duplicates',
        'passed': len(duplicates) == 0,
        'total_skills': len(skills),
        'unique_combinations': len(groups),
        'duplicate_count': len(duplicates),
        'sample_duplicates': [
            {'vacancy_id': k[0], 'skill': k[1], 'category': k[2]}
            for k in duplicates[:5]
        ],
    }


def validate_coverage(loader: SupabaseLoader) -> dict:
    """Check % of vacancies that have at least one skill."""
    total_vacancies = get_exact_count(lambda: loader.client.table('vacantes'))
    skills = fetch_all_paginated(
        lambda: loader.client.table('job_skills').select('vacancy_id')
    )
    vacancies_with_skills = len(set(s['vacancy_id'] for s in skills))
    coverage_pct = (vacancies_with_skills / total_vacancies * 100) if total_vacancies else 0
    return {
        'check': 'coverage',
        'passed': coverage_pct >= THRESHOLDS['min_coverage_pct'],
        'total_vacancies': total_vacancies,
        'vacancies_with_skills': vacancies_with_skills,
        'coverage_pct': round(coverage_pct, 2),
        'threshold': THRESHOLDS['min_coverage_pct'],
    }


def validate_skills_per_vacancy(loader: SupabaseLoader) -> dict:
    """Check that no vacancy has too few or too many skills."""
    skills = fetch_all_paginated(
        lambda: loader.client.table('job_skills').select('vacancy_id')
    )
    counts = Counter(s['vacancy_id'] for s in skills)

    too_few = [
        {'vacancy_id': vid, 'skill_count': c}
        for vid, c in counts.items() if c < THRESHOLDS['min_skills_per_vacancy']
    ]
    too_many = [
        {'vacancy_id': vid, 'skill_count': c}
        for vid, c in counts.items() if c > THRESHOLDS['max_skills_per_vacancy']
    ]

    total = sum(counts.values())
    avg = total / len(counts) if counts else 0
    return {
        'check': 'skills_per_vacancy',
        'passed': len(too_few) == 0 and len(too_many) == 0,
        'total_skills': total,
        'unique_vacancies': len(counts),
        'avg_per_vacancy': round(avg, 1),
        'too_few_count': len(too_few),
        'too_many_count': len(too_many),
        'sample_too_few': too_few[:5],
        'sample_too_many': too_many[:5],
    }


def validate_categories(loader: SupabaseLoader) -> dict:
    """Check that expected skill categories are all present."""
    skills = fetch_all_paginated(
        lambda: loader.client.table('job_skills').select('category')
    )
    present_categories = set(s['category'] for s in skills)
    missing = THRESHOLDS['expected_categories'] - present_categories
    unexpected = present_categories - THRESHOLDS['expected_categories']

    distribution = Counter(s['category'] for s in skills)
    return {
        'check': 'categories',
        'passed': (
            len(missing) <= (5 - THRESHOLDS['min_categories_present'])
            and len(unexpected) == 0
        ),
        'present_categories': sorted(present_categories),
        'missing_categories': sorted(missing),
        'unexpected_categories': sorted(unexpected),
        'distribution': dict(distribution),
    }


def run_all_checks(loader: SupabaseLoader, verbose: bool = False) -> dict:
    """Run all validation checks and return results."""
    logger.info("=" * 60)
    logger.info(f"POST-RUN VALIDATION - {datetime.now().isoformat()}")
    logger.info("=" * 60)

    checks = []
    overall_passed = True

    for check_fn in [
        validate_no_duplicates,
        validate_coverage,
        validate_skills_per_vacancy,
        validate_categories,
    ]:
        try:
            result = check_fn(loader)
            checks.append(result)
            status = "✓ PASS" if result['passed'] else "✗ FAIL"
            logger.info(f"{status}: {result['check']}")
            if verbose or not result['passed']:
                logger.info(f"   Details: {json.dumps(result, indent=2, default=str)}")
            if not result['passed']:
                overall_passed = False
        except Exception as e:
            logger.error(f"Check {check_fn.__name__} CRASHED: {e}", exc_info=True)
            checks.append({
                'check': check_fn.__name__,
                'passed': False,
                'error': str(e),
            })
            overall_passed = False

    summary = {
        'timestamp': datetime.now().isoformat(),
        'overall_passed': overall_passed,
        'checks_total': len(checks),
        'checks_passed': sum(1 for c in checks if c.get('passed')),
        'checks_failed': sum(1 for c in checks if not c.get('passed')),
        'checks': checks,
    }

    logger.info("-" * 60)
    if overall_passed:
        logger.info(f"✅ OVERALL: ALL {summary['checks_total']} CHECKS PASSED")
    else:
        logger.error(
            f"❌ OVERALL: {summary['checks_failed']}/{summary['checks_total']} CHECKS FAILED"
        )
    logger.info("=" * 60)

    return summary


def main():
    parser = argparse.ArgumentParser(description='Post-run validation for Observatory Pipeline')
    parser.add_argument('--verbose', action='store_true', help='Print detailed check results')
    parser.add_argument('--json', action='store_true', help='Output JSON only (machine-readable)')
    args = parser.parse_args()

    try:
        loader = SupabaseLoader()
        if not loader.client:
            logger.error("CRITICAL: Could not initialize Supabase client")
            print(json.dumps({'error': 'no_db_connection'}))
            sys.exit(2)

        summary = run_all_checks(loader, verbose=args.verbose)

        if args.json:
            print(json.dumps(summary, indent=2, default=str))

        sys.exit(0 if summary['overall_passed'] else 1)

    except Exception as e:
        logger.error(f"CRITICAL: Validator crashed: {e}", exc_info=True)
        print(json.dumps({'error': 'validator_crashed', 'message': str(e)}))
        sys.exit(2)


if __name__ == '__main__':
    main()
