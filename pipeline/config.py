"""Configuration module for the Observatory Pipeline."""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()


class Config:
    """Central configuration for the Observatory Pipeline."""

    # ==================== API KEYS ====================
    APIFY_TOKEN: str = os.getenv('APIFY_TOKEN', '')
    OPENROUTER_API_KEY: str = os.getenv('OPENROUTER_API_KEY', '')
    CLAUDE_API_KEY: str = os.getenv('CLAUDE_API_KEY', '')
    SUPABASE_URL: str = os.getenv('SUPABASE_URL', '')
    SUPABASE_ANON_KEY: str = os.getenv('SUPABASE_ANON_KEY', '')
    # Service-role key bypasses RLS. REQUIRED for UPDATE operations
    # (e.g. update_classification). The ANON key silently no-ops UPDATEs
    # under default RLS. See handoff regla #3.
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

    # ==================== APIFY ACTORS ====================
    APIFY_ACTORS: Dict[str, str] = {
        # LinkedIn: curious_coder/linkedin-jobs-scraper
        'linkedin_jobs': os.getenv('APIFY_ACTOR_LINKEDIN_JOBS', 'hKByXkMQaC5Qt9UMN'),
        # Indeed: borderline/indeed-scraper
        'indeed': os.getenv('APIFY_ACTOR_INDEED', 'MXLpngmVpE8WTESQr'),
    }

    # ==================== APIFY ACTOR INPUTS (search parameters) ====================
    # These inputs are passed to each Apify actor when the pipeline triggers a run.
    # Edit here to change which keywords/countries/limits the cron scrapes.
    #
    # Schema docs:
    #   LinkedIn: https://apify.com/curious_coder/linkedin-jobs-scraper/input-schema
    #   Indeed:   https://apify.com/borderline/indeed-scraper/input-schema

    # ====================================================================
    # Keywords del estudio — 8 grupos × ~40 títulos cubriendo 5 role families
    # (creatividad/diseno, contenido/social, marketing/growth, pr_comunicaciones,
    # estrategia_cuentas). Incluye grupo en español para LatAm hispano.
    # Si quieres ajustar la cobertura del estudio, edita esta lista.
    # ====================================================================
    _LINKEDIN_KEYWORDS = [
        # G1 — Creative/Design CORE
        '"creative director" OR "graphic designer" OR "ui designer" OR "ux designer" OR "art director" OR "visual designer"',
        # G2 — Design Specialists
        '"brand designer" OR "motion designer" OR "product designer" OR "design director" OR "web designer" OR "illustrator"',
        # G3 — Content & Copywriting (copywriter era la mayor brecha)
        '"copywriter" OR "content strategist" OR "content creator" OR "content marketing manager" OR "content producer" OR "video editor"',
        # G4 — Social Media & Community
        '"social media manager" OR "community manager" OR "influencer marketing manager" OR "social media strategist"',
        # G5 — Marketing & Growth
        '"growth marketer" OR "marketing manager" OR "performance marketer" OR "digital marketer" OR "brand manager" OR "marketing specialist"',
        # G6 — PR & Communications
        '"pr manager" OR "communications manager" OR "public relations specialist" OR "director of communications" OR "corporate communications"',
        # G7 — Strategy & Accounts (familia más débil hoy; refuerzo)
        '"brand strategist" OR "account manager" OR "account director" OR "account executive" OR "strategic planner" OR "creative strategist"',
        # G8 — Español (captura LatAm hispano que no matchea en inglés)
        '"director creativo" OR "director de arte" OR "diseñador gráfico" OR "gerente de marketing" OR "community manager"',
    ]

    # Indeed query — paridad con LinkedIn (todos los keywords concatenados con OR)
    _INDEED_QUERY = (
        '"creative director" OR "graphic designer" OR "ui designer" OR "ux designer" OR "art director" OR "visual designer" OR '
        '"brand designer" OR "motion designer" OR "product designer" OR "design director" OR "web designer" OR "illustrator" OR '
        '"copywriter" OR "content strategist" OR "content creator" OR "content marketing manager" OR "video editor" OR '
        '"social media manager" OR "community manager" OR "influencer marketing manager" OR '
        '"growth marketer" OR "marketing manager" OR "performance marketer" OR "digital marketer" OR "brand manager" OR "marketing specialist" OR '
        '"pr manager" OR "communications manager" OR "public relations specialist" OR "director of communications" OR '
        '"brand strategist" OR "account manager" OR "account director" OR "account executive" OR "strategic planner" OR '
        '"director creativo" OR "diseñador gráfico" OR "gerente de marketing"'
    )

    # LatAm para LinkedIn — multi-país gratis (LinkedIn cobra por run, no por URL)
    LATAM_COUNTRIES_LINKEDIN: List[str] = [
        "Colombia", "Mexico", "Argentina", "Chile", "Peru",
        "Brazil", "Uruguay", "Panama", "Costa Rica", "Ecuador",
    ]

    # LatAm para Indeed — actor acepta solo 1 país por run; cada entrada = $0.50/run.
    # Top 5 mercados LatAm. Costo total Indeed: $0.50 × len = $2.50/run.
    LATAM_COUNTRIES_INDEED: Dict[str, str] = {
        'Colombia': 'co',
        'Mexico':   'mx',
        'Brazil':   'br',
        'Argentina':'ar',
        'Chile':    'cl',
    }

    @classmethod
    def _build_linkedin_urls(cls) -> List[str]:
        """Construye URLs de LinkedIn: 1 URL por país × por keyword group.

        Con 10 países y 8 keyword groups → 80 URLs por run.
        Apify cobra por RUN (flat $0.10), no por URL, así que multi-país es gratis.
        """
        from urllib.parse import quote
        urls = []
        for country in cls.LATAM_COUNTRIES_LINKEDIN:
            for kw in cls._LINKEDIN_KEYWORDS:
                urls.append(
                    f"https://www.linkedin.com/jobs/search/?keywords={quote(kw)}"
                    f"&location={quote(country)}&f_TPR=r2592000"
                )
        return urls
        # NOTE: f_TPR=r2592000 = jobs posted in last 30 days

    @classmethod
    def get_apify_inputs(cls) -> Dict[str, Any]:
        """Devuelve input(s) por source.

        - LinkedIn: 1 dict (1 run con N URLs multi-país)
        - Indeed: LISTA de dicts (1 run por país, el extractor itera la lista)
        """
        return {
            'linkedin_jobs': {
                'urls': cls._build_linkedin_urls(),  # 10 países × 8 keywords = 80 URLs
                'count': 1000,           # ~12 vacancies por URL × 80 URLs ≈ 960 max
                'scrapeCompany': False,  # save credits
            },
            'indeed': [   # LIST: extractor triggers un Apify run por país
                {
                    'country': country_code,
                    'query': cls._INDEED_QUERY,
                    'maxRows': 100,
                    'sort': 'date',
                    'fromDays': '7',       # last 7 days (cubre 4-day cron + buffer)
                    'enableUniqueJobs': True,
                }
                for country_code in cls.LATAM_COUNTRIES_INDEED.values()
            ],
        }

    # ==================== PATHS ====================
    BASE_PATH: Path = Path(os.path.dirname(os.path.dirname(__file__)))
    DATA_PATH: Path = BASE_PATH / 'data'
    LOG_PATH: Path = BASE_PATH / 'logs'

    # Create directories if they don't exist
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    LOG_PATH.mkdir(parents=True, exist_ok=True)

    # ==================== OPENROUTER MODELS ====================
    OPENROUTER_MODELS: List[str] = [
        "openrouter/auto",
    ]
    DEFAULT_MODEL: str = "openrouter/auto"
    # For classification, use cheapest available models via OpenRouter
    CLASSIFICATION_MODEL: str = os.getenv('CLASSIFICATION_MODEL', 'openai/gpt-3.5-turbo')

    # ==================== THRESHOLDS & BATCH SIZES ====================
    CONFIDENCE_THRESHOLD: float = float(os.getenv('CONFIDENCE_THRESHOLD', '0.7'))
    BATCH_SIZE_FIRST: int = int(os.getenv('BATCH_SIZE_FIRST', '100'))
    BATCH_SIZE_SECOND: int = int(os.getenv('BATCH_SIZE_SECOND', '50'))
    BATCH_SIZE_THIRD: int = int(os.getenv('BATCH_SIZE_THIRD', '25'))

    # ==================== BUDGET CONTROLS ====================
    # Hard limit on LLM API spend per pipeline run (USD).
    # Pipeline aborts cleanly when this is exceeded.
    # Set to 0 to disable. Configure at the provider level too.
    RUN_BUDGET_USD: float = float(os.getenv('RUN_BUDGET_USD', '5.0'))
    # Hard limit on total LLM calls (classification + skills) per run.
    # Prevents runaway loops from consuming budget.
    MAX_LLM_CALLS_PER_RUN: int = int(os.getenv('MAX_LLM_CALLS_PER_RUN', '500'))
    # Approximate cost per 1k tokens (adjust to your model/plan)
    APPROX_COST_PER_1K_TOKENS_USD: float = float(os.getenv('APPROX_COST_PER_1K_TOKENS_USD', '0.001'))

    # ==================== LOGGING ====================
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    LOG_FILE: Path = LOG_PATH / 'pipeline.log'

    # ==================== FEATURES ====================
    TEST_MODE_SAMPLE_SIZE: int = 10
    MAX_RETRIES: int = 3
    REQUEST_TIMEOUT: int = 30

    @classmethod
    def validate(cls) -> bool:
        """
        Validate that all required configuration is present.

        Returns:
            bool: True if all required config is valid, False otherwise

        Raises:
            ValueError: If critical configuration is missing
        """
        required_keys = {
            'APIFY_TOKEN': cls.APIFY_TOKEN,
            'OPENROUTER_API_KEY': cls.OPENROUTER_API_KEY,
            'SUPABASE_URL': cls.SUPABASE_URL,
            'SUPABASE_ANON_KEY': cls.SUPABASE_ANON_KEY,
        }

        # SERVICE_ROLE is required for UPDATE-heavy ops (classification updates)
        # but treated as a warning, not a hard error, to keep tests/local runs
        # without it usable.
        if not cls.SUPABASE_SERVICE_ROLE_KEY:
            logger.warning(
                "SUPABASE_SERVICE_ROLE_KEY not set; UPDATE operations may "
                "silently fail under RLS. Set it in production."
            )

        # CLAUDE_API_KEY is optional (can use OpenRouter instead)

        missing_keys = [key for key, value in required_keys.items() if not value]

        if missing_keys:
            error_msg = f"Missing required config: {', '.join(missing_keys)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Validate paths
        if not cls.BASE_PATH.exists():
            raise ValueError(f"BASE_PATH does not exist: {cls.BASE_PATH}")

        # Validate thresholds
        if not (0 <= cls.CONFIDENCE_THRESHOLD <= 1):
            raise ValueError(
                f"CONFIDENCE_THRESHOLD must be between 0 and 1, got {cls.CONFIDENCE_THRESHOLD}"
            )

        # Validate batch sizes
        if cls.BATCH_SIZE_FIRST <= 0 or cls.BATCH_SIZE_SECOND <= 0 or cls.BATCH_SIZE_THIRD <= 0:
            raise ValueError("All batch sizes must be positive integers")

        logger.info("Configuration validated successfully")
        return True

    @classmethod
    def get_summary(cls) -> str:
        """
        Get a summary of the current configuration.

        Returns:
            str: Configuration summary
        """
        summary = f"""
        ===== CONFIGURATION SUMMARY =====
        Base Path: {cls.BASE_PATH}
        Data Path: {cls.DATA_PATH}
        Log Path: {cls.LOG_PATH}
        Log Level: {cls.LOG_LEVEL}

        OpenRouter Model: {cls.DEFAULT_MODEL}
        Confidence Threshold: {cls.CONFIDENCE_THRESHOLD}

        Batch Sizes:
          - First: {cls.BATCH_SIZE_FIRST}
          - Second: {cls.BATCH_SIZE_SECOND}
          - Third: {cls.BATCH_SIZE_THIRD}

        Apify Actors Configured: {len(cls.APIFY_ACTORS)}
        OpenRouter Models Available: {len(cls.OPENROUTER_MODELS)}

        Test Mode Sample Size: {cls.TEST_MODE_SAMPLE_SIZE}
        ================================
        """
        return summary
