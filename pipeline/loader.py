"""
Supabase loader — DEMO MODE: no-op stubs only.

The full SupabaseLoader writes classified vacancies to a Supabase (PostgreSQL)
instance. It is excluded from the runnable public demo because:

  - Running it requires a live Supabase project with credentials
  - The public demo operates exclusively on synthetic data in memory
  - No real data should leave the local machine during a demo run

Architecture note (for reference):
  SupabaseLoader.load_vacancies(vacancies)   → INSERT into `vacancies` table
  SupabaseLoader.update_classification(...)  → UPDATE classification columns
  SupabaseLoader.fetch_unclassified(...)     → SELECT for classify phase

The database schema is in migrations/. The service-role key is required for
UPDATE operations due to Supabase RLS policies (see docs/DATA_GOVERNANCE.md).

To run the full pipeline against a real database:
  1. Create a Supabase project
  2. Apply migrations/ in order
  3. Set SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY in .env
  4. Implement or restore the full loader (not shipped here)
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class SupabaseLoader:
    """Placeholder loader — raises NotImplementedError on all DB calls.

    Instantiating succeeds so that the import chain (pipeline/__init__, main.py)
    works at module load time. Calls to any method raise NotImplementedError.
    """

    def __init__(self, url: str = "", key: str = ""):
        self.client = None
        logger.warning(
            "SupabaseLoader is a stub in the public demo — "
            "no database connection will be made."
        )

    def load_vacancies(self, vacancies: List[Dict]) -> Dict:
        raise NotImplementedError(
            "SupabaseLoader is not included in the public demo. "
            "See pipeline/loader.py for the architecture reference."
        )

    def update_classification(self, vacancy_id: str, classification: Dict) -> bool:
        raise NotImplementedError("See module docstring.")

    def fetch_unclassified(self, *args, **kwargs) -> List[Dict]:
        raise NotImplementedError("See module docstring.")

    def fetch_unextracted_skills(self, *args, **kwargs) -> List[Dict]:
        raise NotImplementedError("See module docstring.")
