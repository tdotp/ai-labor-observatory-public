"""
Scraping connectors — NOT INCLUDED IN PUBLIC DEMO.

This module contained the Apify-based extractors for LinkedIn Jobs and Indeed.
Those connectors are excluded from the public release for two reasons:

  1. Legal/ToS: automating searches on LinkedIn and Indeed without authorisation
     violates their Terms of Service. Distributing ready-to-run scraping code
     creates a risk of facilitating ToS violations.

  2. Data: vacancies scraped from those platforms are third-party content
     whose redistribution is not authorised by the platforms.

The public demo uses ONLY the synthetic dataset in data/synthetic/.
See docs/DATA_GOVERNANCE.md for the full data-lineage statement.

Architecture note (for reference):
  ApifyExtractor.run_extraction(source, keywords, countries)
    └─ calls Apify actor (LinkedIn / Indeed) via Apify API
    └─ polls for completion
    └─ returns List[Dict] of raw vacancies
    └─ normalises country via COUNTRY_MAPPING below

If you want to run the full pipeline against live data, you must:
  - Obtain your own Apify account and tokens
  - Ensure you have a legal basis to collect that data under applicable law
  - Implement your own extraction layer conforming to this module's interface
"""

# Country/city → canonical country name used throughout the pipeline.
# Retained here as reference data (not scraped content).
COUNTRY_MAPPING = {
    # Colombia
    'colombia': 'Colombia', 'bogota': 'Colombia', 'bogotá': 'Colombia',
    'medellin': 'Colombia', 'medellín': 'Colombia', 'cali': 'Colombia',
    'barranquilla': 'Colombia', 'cartagena': 'Colombia',
    # México
    'mexico': 'Mexico', 'méxico': 'Mexico', 'mx': 'Mexico',
    'mexico city': 'Mexico', 'ciudad de méxico': 'Mexico', 'cdmx': 'Mexico',
    'guadalajara': 'Mexico', 'monterrey': 'Mexico',
    # Argentina
    'argentina': 'Argentina', 'buenos aires': 'Argentina',
    'cordoba': 'Argentina', 'córdoba': 'Argentina', 'rosario': 'Argentina',
    # Chile
    'chile': 'Chile', 'santiago': 'Chile', 'valparaiso': 'Chile',
    # Peru
    'peru': 'Peru', 'perú': 'Peru', 'lima': 'Peru',
    # Brasil
    'brasil': 'Brazil', 'brazil': 'Brazil', 'são paulo': 'Brazil',
    'sao paulo': 'Brazil', 'rio de janeiro': 'Brazil',
    # Ecuador
    'ecuador': 'Ecuador', 'quito': 'Ecuador', 'guayaquil': 'Ecuador',
    # Colombia / Rest LatAm
    'uruguay': 'Uruguay', 'montevideo': 'Uruguay',
    'paraguay': 'Paraguay', 'asuncion': 'Paraguay', 'asunción': 'Paraguay',
    'bolivia': 'Bolivia', 'la paz': 'Bolivia',
    'venezuela': 'Venezuela', 'caracas': 'Venezuela',
    'panama': 'Panama', 'panamá': 'Panama',
    'costa rica': 'Costa Rica', 'san jose': 'Costa Rica',
    'guatemala': 'Guatemala',
}


class ApifyExtractor:
    """Placeholder — scraping connector not included in public demo.

    Raises NotImplementedError on any call. See module docstring for context.
    """

    def __init__(self, api_token: str):
        raise NotImplementedError(
            "ApifyExtractor is not included in the public demo. "
            "See pipeline/extractor.py for the architecture reference and "
            "docs/DATA_GOVERNANCE.md for the data governance statement."
        )

    def run_extraction(self, *args, **kwargs):
        raise NotImplementedError("See module docstring.")
