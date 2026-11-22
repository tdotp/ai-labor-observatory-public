import logging
import json
from typing import List, Dict, Any, Set
import re

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class DataCleaner:
    """Clean and validate job vacancy data."""

    REQUIRED_FIELDS = [
        'raw_title',
        'raw_description',
        'job_url',
        'company_name',
        'country'
    ]

    # Whole-word keywords (matched with \b) that strongly indicate a role
    # OUTSIDE the observatory's domain (creative / marketing / PR / content /
    # social / design). Vacancies whose title contains any of these are
    # dropped BEFORE classification to save OpenRouter tokens — they would
    # otherwise be classified as OTHER and still incur cost.
    #
    # Conservative list: only roles that virtually never overlap with the
    # target domain. Add cautiously to avoid false positives.
    OUT_OF_DOMAIN_KEYWORDS = frozenset({
        # Engineering / tech roles (the biggest source of noise)
        'software engineer', 'software developer',
        'backend developer', 'back-end developer', 'backend engineer',
        'frontend developer', 'front-end developer', 'frontend engineer',
        'full stack developer', 'fullstack developer', 'full-stack developer',
        'devops engineer', 'sre engineer', 'site reliability engineer',
        'data engineer', 'data scientist', 'data analyst',
        'machine learning engineer', 'ml engineer', 'ai engineer',
        'qa engineer', 'qa analyst', 'quality assurance engineer',
        'mobile developer', 'ios developer', 'android developer',
        'security engineer', 'cybersecurity analyst',
        'cloud engineer', 'platform engineer', 'infrastructure engineer',
        # Healthcare
        'nurse', 'enfermer',
        'doctor', 'physician', 'medico', 'médico',
        # Finance / legal / admin
        'accountant', 'contador', 'contadora',
        'lawyer', 'abogad', 'paralegal',
        'auditor',
        # Education
        'teacher', 'profesor', 'docente',
        # Operations / blue-collar
        'driver', 'conductor', 'repartidor',
        'chef', 'cocinero',
        'mechanic', 'mecanic',
        'construction worker', 'albanil', 'albañil',
        'waiter', 'mesero',
        'cashier', 'cajero', 'cajera',
        'janitor', 'conserje',
        'security guard', 'vigilante',
        'warehouse worker', 'almacenista',
    })

    def __init__(self):
        """Initialize the data cleaner."""
        self.seen_hashes: Set[str] = set()
        self.seen_semantic_keys: Set[tuple] = set()
        self.dedup_stats = {
            'total_checked': 0,
            'duplicates_removed': 0,
            'semantic_duplicates_removed': 0,
            'blacklisted_removed': 0,
            'unique_kept': 0,
        }
        logger.info("DataCleaner initialized")

    def clean_text(self, text: str) -> str:
        """
        Clean and normalize text: strip, lowercase, normalize whitespace.

        Args:
            text: The text to clean

        Returns:
            Cleaned text
        """
        if not text:
            return ''

        # Strip leading/trailing whitespace
        text = text.strip()

        # Lowercase
        text = text.lower()

        # Normalize whitespace (multiple spaces to single)
        text = re.sub(r'\s+', ' ', text)

        # Remove HTML tags if present
        text = re.sub(r'<[^>]+>', '', text)

        # Remove extra punctuation
        text = re.sub(r'[^\w\s.,!?-]', '', text)

        return text

    @classmethod
    def normalize_for_key(cls, value: Any) -> str:
        """Normalize a string for use in a semantic key (lower, single-spaced, trimmed)."""
        if not value:
            return ''
        text = str(value).strip().lower()
        return re.sub(r'\s+', ' ', text)

    @classmethod
    def semantic_key(cls, vacancy: Dict[str, Any]) -> tuple:
        """
        Build the semantic dedup key for a vacancy: (company, title, country).

        Two vacancies with the same key are treated as the SAME real-world job
        opening even if their URLs differ (the case for LinkedIn promoted /
        paginated re-posts). Both the in-batch cleaner and the cross-run loader
        use this same function so the definition stays in one place.
        """
        return (
            cls.normalize_for_key(vacancy.get('company_name')),
            cls.normalize_for_key(vacancy.get('raw_title')),
            cls.normalize_for_key(vacancy.get('country')),
        )

    @classmethod
    def is_out_of_domain(cls, title: str) -> bool:
        """
        Return True if the title contains any OUT_OF_DOMAIN_KEYWORDS.

        Matching is "stem + tail": `\\b{kw}\\w*\\b`. The leading word
        boundary prevents catching e.g. 'design' inside 'designer'; the
        trailing `\\w*` lets a stem like `enfermer` match Spanish gender
        / plural inflections (`enfermera`, `enfermero`, `enfermeras`) and
        English plurals (`nurse` → `nurses`).
        """
        if not title:
            return False
        cleaned = cls.normalize_for_key(title)
        for kw in cls.OUT_OF_DOMAIN_KEYWORDS:
            # re.escape covers any future keywords with regex metachars.
            if re.search(r'\b' + re.escape(kw) + r'\w*\b', cleaned):
                return True
        return False

    def check_duplicate(self, vacancy_hash: str) -> bool:
        """
        Check if a vacancy hash has been seen before.

        Args:
            vacancy_hash: The MD5 hash of the vacancy

        Returns:
            True if duplicate (already seen), False if new
        """
        if vacancy_hash in self.seen_hashes:
            return True
        else:
            self.seen_hashes.add(vacancy_hash)
            return False

    def remove_duplicates(self, vacancies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicate vacancies based on vacancy_hash.

        Args:
            vacancies: List of vacancy dictionaries

        Returns:
            List without duplicates, tracking stats
        """
        self.dedup_stats['total_checked'] = len(vacancies)
        unique_vacancies = []

        for vacancy in vacancies:
            vacancy_hash = vacancy.get('vacancy_hash')
            if not vacancy_hash:
                logger.warning("Vacancy missing vacancy_hash, skipping")
                continue

            if self.check_duplicate(vacancy_hash):
                self.dedup_stats['duplicates_removed'] += 1
                logger.debug(f"Duplicate removed: {vacancy_hash}")
            else:
                unique_vacancies.append(vacancy)
                self.dedup_stats['unique_kept'] += 1

        logger.info(
            f"Deduplication stats: {self.dedup_stats['total_checked']} total, "
            f"{self.dedup_stats['duplicates_removed']} duplicates removed, "
            f"{self.dedup_stats['unique_kept']} unique kept"
        )

        return unique_vacancies

    def validate_vacancy(self, vacancy: Dict[str, Any]) -> bool:
        """
        Validate that a vacancy has all required fields.

        Args:
            vacancy: The vacancy dictionary to validate

        Returns:
            True if valid, False otherwise
        """
        missing_fields = []

        for field in self.REQUIRED_FIELDS:
            value = vacancy.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                missing_fields.append(field)

        if missing_fields:
            logger.warning(
                f"Vacancy invalid - missing fields: {', '.join(missing_fields)}"
            )
            return False

        return True

    def clean_vacancy(self, vacancy: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean text fields in a vacancy.

        Args:
            vacancy: The vacancy dictionary to clean

        Returns:
            Vacancy with cleaned text fields
        """
        cleaned = vacancy.copy()

        # Clean text fields
        text_fields = ['raw_title', 'raw_description', 'company_name']
        for field in text_fields:
            if field in cleaned:
                cleaned[field] = self.clean_text(cleaned[field])

        return cleaned

    def clean_batch(self, input_file: str, output_file: str) -> Dict[str, int]:
        """
        Full cleaning pipeline: load, deduplicate, validate, clean, save.

        Args:
            input_file: Path to input JSONL file
            output_file: Path to output JSONL file

        Returns:
            Dictionary with stats: processed, duplicates_removed, validated, errors
        """
        stats = {
            'processed': 0,
            'duplicates_removed': 0,
            'semantic_duplicates_removed': 0,
            'blacklisted_removed': 0,
            'validated': 0,
            'errors': 0,
            'written': 0,
        }

        try:
            # Load input
            vacancies = []
            with open(input_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            vacancy = json.loads(line)
                            vacancies.append(vacancy)
                            stats['processed'] += 1
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing JSON line: {e}")
                            stats['errors'] += 1

            logger.info(f"Loaded {len(vacancies)} vacancies from {input_file}")

            # Remove duplicates
            unique_vacancies = self.remove_duplicates(vacancies)
            stats['duplicates_removed'] = self.dedup_stats['duplicates_removed']

            # Validate, blacklist, semantic-dedup, clean
            valid_vacancies = []
            for vacancy in unique_vacancies:
                if not self.validate_vacancy(vacancy):
                    continue

                # Blacklist: drop out-of-domain titles before any LLM call
                if self.is_out_of_domain(vacancy.get('raw_title')):
                    self.dedup_stats['blacklisted_removed'] += 1
                    stats['blacklisted_removed'] += 1
                    logger.debug(
                        f"Blacklisted (out of domain): "
                        f"{vacancy.get('raw_title')!r:.80}"
                    )
                    continue

                # Semantic dedup within this batch
                key = self.semantic_key(vacancy)
                if key in self.seen_semantic_keys:
                    self.dedup_stats['semantic_duplicates_removed'] += 1
                    stats['semantic_duplicates_removed'] += 1
                    logger.debug(f"Semantic duplicate (in-batch): {key}")
                    continue
                self.seen_semantic_keys.add(key)

                cleaned_vacancy = self.clean_vacancy(vacancy)
                valid_vacancies.append(cleaned_vacancy)
                stats['validated'] += 1

            # Write output
            with open(output_file, 'w', encoding='utf-8') as f:
                for vacancy in valid_vacancies:
                    f.write(json.dumps(vacancy, ensure_ascii=False) + '\n')
                    stats['written'] += 1

            logger.info(
                f"Cleaning complete: {stats['processed']} processed, "
                f"{stats['duplicates_removed']} hash-duplicates removed, "
                f"{stats['semantic_duplicates_removed']} semantic-duplicates removed, "
                f"{stats['blacklisted_removed']} blacklisted, "
                f"{stats['validated']} validated, "
                f"{stats['written']} written to {output_file}"
            )

            return stats

        except Exception as e:
            logger.error(f"Error in clean_batch: {e}")
            stats['errors'] += 1
            return stats
