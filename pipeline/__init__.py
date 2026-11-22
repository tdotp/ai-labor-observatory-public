"""Pipeline module — public demo edition.

Available in this release:
  - DataCleaner     (normalisation, deduplication, out-of-domain filter)
  - Config          (budget controls, taxonomy thresholds)

Not available in this release (see individual module docstrings):
  - ApifyExtractor  (scraping connectors excluded — see extractor.py)
  - SupabaseLoader  (database connector excluded — see loader.py)
"""

from pipeline.cleaner import DataCleaner

__all__ = ['DataCleaner']
