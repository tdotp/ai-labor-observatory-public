"""
Taxonomy validator — AI Labor Observatory.

Validates classifier output against the declared taxonomy.
Provides strict rejection of invalid values, structured error reporting,
and handling of unparseable/incomplete responses.

This is distinct from BatchValidator (which checks semantic plausibility):
TaxonomyValidator checks structural/enum correctness.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Taxonomy constants (single source of truth for all validators)
# ---------------------------------------------------------------------------

VALID_ROLE_FAMILIES = {
    "creatividad_diseno",
    "contenido_social",
    "marketing_growth",
    "pr_comunicaciones",
    "estrategia_cuentas",
    "OTHER",
}

VALID_SENIORITY = {
    "junior",
    "specialist",
    "senior",
    "lead",
    "manager",
    "director",
}

VALID_AI_LEVELS = {0, 1, 2, 3}

REQUIRED_FIELDS = {
    "vacancy_id",
    "role_family",
    "seniority",
    "ai_level",
    "confidence",
}

OPTIONAL_FIELDS = {
    "ai_tools_detected",
    "ai_keywords_detected",
    "reasoning",
    "model",
    "classified_at",
}

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of validating a single classification response."""
    vacancy_id: str
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    normalized: Optional[Dict[str, Any]] = None

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------

class TaxonomyValidator:
    """
    Validates classifier output against the Observatory taxonomy.

    Rules:
    - role_family must be one of VALID_ROLE_FAMILIES (case-sensitive)
    - seniority must be one of VALID_SENIORITY (case-sensitive)
    - ai_level must be an integer in {0, 1, 2, 3}
    - confidence must be a float in [0.0, 1.0]
    - Required fields must be present and non-null

    Errors vs Warnings:
    - Errors: invalid/missing required fields → classification is REJECTED
    - Warnings: suspicious but not strictly invalid values → classification passes with note

    This validator does NOT silently coerce invalid values to valid ones —
    silent coercion would mask real model failures and corrupt the audit trail.
    """

    def validate(
        self,
        raw_classification: Dict[str, Any],
        vacancy_id: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate a single classification response dict.

        Args:
            raw_classification: The dict returned by the classifier.
            vacancy_id: Override the vacancy_id if not in raw_classification.

        Returns:
            ValidationResult with is_valid, errors, warnings, and
            a normalized copy (only on success).
        """
        vid = vacancy_id or (raw_classification.get("vacancy_id", "UNKNOWN") if isinstance(raw_classification, dict) else "UNKNOWN")
        errors: List[str] = []
        warnings: List[str] = []

        if not isinstance(raw_classification, dict):
            return ValidationResult(
                vacancy_id=vacancy_id or "UNKNOWN",
                is_valid=False,
                errors=["Classification response is not a dict — likely an unparseable response"],
            )

        # 1. Required fields presence
        for f_name in REQUIRED_FIELDS:
            if f_name not in raw_classification or raw_classification[f_name] is None:
                errors.append(f"Missing required field: '{f_name}'")

        if errors:
            return ValidationResult(
                vacancy_id=vid,
                is_valid=False,
                errors=errors,
                warnings=warnings,
            )

        # 2. role_family enum check
        rf = raw_classification.get("role_family")
        if rf not in VALID_ROLE_FAMILIES:
            # Attempt case-insensitive match to identify near-miss errors
            candidates = [v for v in VALID_ROLE_FAMILIES if v.lower() == str(rf).lower()]
            if candidates:
                errors.append(
                    f"role_family '{rf}' is not valid (case mismatch — did you mean '{candidates[0]}'?). "
                    f"Valid values: {sorted(VALID_ROLE_FAMILIES)}"
                )
            else:
                errors.append(
                    f"role_family '{rf}' is not a valid taxonomy value. "
                    f"Valid values: {sorted(VALID_ROLE_FAMILIES)}"
                )

        # 3. seniority enum check
        sn = raw_classification.get("seniority")
        if sn not in VALID_SENIORITY:
            candidates = [v for v in VALID_SENIORITY if v.lower() == str(sn).lower()]
            if candidates:
                errors.append(
                    f"seniority '{sn}' is not valid (case mismatch — did you mean '{candidates[0]}'?). "
                    f"Valid values: {sorted(VALID_SENIORITY)}"
                )
            else:
                errors.append(
                    f"seniority '{sn}' is not a valid taxonomy value. "
                    f"Valid values: {sorted(VALID_SENIORITY)}"
                )

        # 4. ai_level type and range check
        ai_raw = raw_classification.get("ai_level")
        ai_level_valid = False
        ai_level_int = None
        if isinstance(ai_raw, bool):
            errors.append(f"ai_level must be int 0-3, got boolean '{ai_raw}'")
        elif isinstance(ai_raw, (int, float)):
            ai_level_int = int(ai_raw)
            if ai_level_int not in VALID_AI_LEVELS:
                errors.append(
                    f"ai_level {ai_level_int} is out of range. Valid values: {sorted(VALID_AI_LEVELS)}"
                )
            elif ai_level_int != ai_raw:
                warnings.append(
                    f"ai_level {ai_raw} is a float; will be treated as int {ai_level_int}"
                )
                ai_level_valid = True
            else:
                ai_level_valid = True
        elif isinstance(ai_raw, str):
            # Accept string representations like "0", "1", "2", "3"
            try:
                ai_level_int = int(ai_raw)
                if ai_level_int in VALID_AI_LEVELS:
                    warnings.append(
                        f"ai_level '{ai_raw}' is a string, expected int. Will be coerced to {ai_level_int}."
                    )
                    ai_level_valid = True
                else:
                    errors.append(
                        f"ai_level '{ai_raw}' (as int: {ai_level_int}) is out of range {sorted(VALID_AI_LEVELS)}"
                    )
            except ValueError:
                # Check if it's the string enum form (none/low/medium/high)
                string_to_int = {"none": 0, "low": 1, "medium": 2, "high": 3}
                if ai_raw.lower() in string_to_int:
                    ai_level_int = string_to_int[ai_raw.lower()]
                    warnings.append(
                        f"ai_level '{ai_raw}' is a string label, expected int. "
                        f"Coerced to {ai_level_int}. Update prompt to return integers."
                    )
                    ai_level_valid = True
                else:
                    errors.append(
                        f"ai_level '{ai_raw}' cannot be parsed as an integer 0-3. "
                        f"Valid values: {sorted(VALID_AI_LEVELS)}"
                    )
        else:
            errors.append(
                f"ai_level has unexpected type {type(ai_raw).__name__}: '{ai_raw}'. "
                f"Expected integer 0-3."
            )

        # 5. confidence range check
        conf = raw_classification.get("confidence")
        if not isinstance(conf, (int, float)):
            errors.append(f"confidence must be a number, got {type(conf).__name__}: '{conf}'")
        elif not (0.0 <= float(conf) <= 1.0):
            errors.append(f"confidence {conf} is outside [0.0, 1.0]")

        # 6. ai_tools_detected type check (warning only)
        tools = raw_classification.get("ai_tools_detected")
        if tools is not None and not isinstance(tools, list):
            warnings.append(
                f"ai_tools_detected should be a list, got {type(tools).__name__}. "
                f"Will be treated as empty list."
            )

        # 7. ai_keywords_detected type check (warning only)
        keywords = raw_classification.get("ai_keywords_detected")
        if keywords is not None and not isinstance(keywords, list):
            warnings.append(
                f"ai_keywords_detected should be a list, got {type(keywords).__name__}. "
                f"Will be treated as empty list."
            )

        is_valid = len(errors) == 0

        normalized = None
        if is_valid:
            normalized = {
                "vacancy_id": str(vid),
                "role_family": rf,
                "seniority": sn,
                "ai_level": ai_level_int,
                "confidence": float(conf),
                "ai_tools_detected": tools if isinstance(tools, list) else [],
                "ai_keywords_detected": keywords if isinstance(keywords, list) else [],
                "reasoning": raw_classification.get("reasoning", ""),
                "model": raw_classification.get("model", ""),
                "classified_at": raw_classification.get("classified_at", ""),
            }

        result = ValidationResult(
            vacancy_id=vid,
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            normalized=normalized,
        )

        if errors:
            logger.warning(
                f"Taxonomy validation FAILED for vacancy {vid}: {errors}"
            )
        elif warnings:
            logger.info(
                f"Taxonomy validation passed with warnings for vacancy {vid}: {warnings}"
            )

        return result

    def validate_batch(
        self,
        classifications: List[Optional[Dict[str, Any]]],
        vacancy_ids: Optional[List[str]] = None,
    ) -> Tuple[List[ValidationResult], Dict[str, int]]:
        """
        Validate a batch of classification responses.

        Args:
            classifications: List of classification dicts (or None for failures).
            vacancy_ids: Optional list of vacancy IDs aligned with classifications.

        Returns:
            (results, stats) where stats = {valid, invalid, none_responses, with_warnings}
        """
        results = []
        stats = {"valid": 0, "invalid": 0, "none_responses": 0, "with_warnings": 0}

        for i, clf in enumerate(classifications):
            vid = (vacancy_ids[i] if vacancy_ids and i < len(vacancy_ids) else None)

            if clf is None:
                stats["none_responses"] += 1
                results.append(
                    ValidationResult(
                        vacancy_id=vid or f"idx_{i}",
                        is_valid=False,
                        errors=["No classification returned (None response — likely an API failure)"],
                    )
                )
                continue

            result = self.validate(clf, vacancy_id=vid)
            results.append(result)

            if result.is_valid:
                stats["valid"] += 1
                if result.has_warnings:
                    stats["with_warnings"] += 1
            else:
                stats["invalid"] += 1

        total = len(classifications)
        logger.info(
            f"Batch taxonomy validation: {stats['valid']}/{total} valid, "
            f"{stats['invalid']} invalid, {stats['none_responses']} None responses"
        )
        return results, stats
