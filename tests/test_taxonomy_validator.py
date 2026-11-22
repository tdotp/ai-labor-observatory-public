"""
Tests for TaxonomyValidator.

Covers:
  - Valid classifications pass with no errors
  - Invalid enum values are rejected with clear error messages
  - Missing required fields are rejected
  - ai_level type variants (int, float, string, bool) handled correctly
  - Confidence range enforcement
  - Batch validation stats
  - None responses in batch
  - No silent coercion of invalid values to correct ones
"""

import pytest
from validation.taxonomy_validator import (
    TaxonomyValidator,
    VALID_ROLE_FAMILIES,
    VALID_SENIORITY,
    VALID_AI_LEVELS,
)


@pytest.fixture
def validator():
    return TaxonomyValidator()


@pytest.fixture
def valid_classification():
    return {
        "vacancy_id": "TEST-001",
        "role_family": "creatividad_diseno",
        "seniority": "senior",
        "ai_level": 2,
        "confidence": 0.85,
        "ai_tools_detected": ["Figma AI"],
        "ai_keywords_detected": ["AI design"],
        "reasoning": "Visual design role with AI tools.",
        "model": "openai/gpt-3.5-turbo",
        "classified_at": "2026-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Valid classification passes
# ---------------------------------------------------------------------------

class TestValidClassifications:
    def test_valid_classification_passes(self, validator, valid_classification):
        result = validator.validate(valid_classification)
        assert result.is_valid, f"Expected valid, got errors: {result.errors}"
        assert not result.has_errors

    def test_valid_normalized_output_matches_input(self, validator, valid_classification):
        result = validator.validate(valid_classification)
        assert result.normalized is not None
        assert result.normalized["role_family"] == "creatividad_diseno"
        assert result.normalized["ai_level"] == 2
        assert result.normalized["confidence"] == 0.85

    def test_all_valid_role_families_pass(self, validator, valid_classification):
        for rf in VALID_ROLE_FAMILIES:
            clf = dict(valid_classification, role_family=rf)
            result = validator.validate(clf)
            assert result.is_valid, f"role_family={rf!r} should be valid, got: {result.errors}"

    def test_all_valid_seniority_values_pass(self, validator, valid_classification):
        for sn in VALID_SENIORITY:
            clf = dict(valid_classification, seniority=sn)
            result = validator.validate(clf)
            assert result.is_valid, f"seniority={sn!r} should be valid, got: {result.errors}"

    def test_all_valid_ai_levels_pass(self, validator, valid_classification):
        for level in VALID_AI_LEVELS:
            clf = dict(valid_classification, ai_level=level)
            result = validator.validate(clf)
            assert result.is_valid, f"ai_level={level} should be valid, got: {result.errors}"

    def test_empty_optional_fields_pass(self, validator, valid_classification):
        clf = dict(valid_classification, ai_tools_detected=[], ai_keywords_detected=[])
        result = validator.validate(clf)
        assert result.is_valid

    def test_missing_optional_fields_pass(self, validator):
        minimal = {
            "vacancy_id": "MINIMAL-001",
            "role_family": "marketing_growth",
            "seniority": "junior",
            "ai_level": 0,
            "confidence": 0.75,
        }
        result = validator.validate(minimal)
        assert result.is_valid, f"Minimal required-only classification should pass: {result.errors}"


# ---------------------------------------------------------------------------
# Invalid role_family
# ---------------------------------------------------------------------------

class TestInvalidRoleFamily:
    def test_unknown_role_family_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, role_family="engineering")
        result = validator.validate(clf)
        assert not result.is_valid
        assert any("role_family" in e for e in result.errors)

    def test_role_family_case_mismatch_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, role_family="Creatividad_Diseno")
        result = validator.validate(clf)
        assert not result.is_valid
        # Error message should hint at the correct value
        error_text = " ".join(result.errors)
        assert "creatividad_diseno" in error_text.lower()

    def test_english_role_family_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, role_family="creative_design")
        result = validator.validate(clf)
        assert not result.is_valid

    def test_empty_role_family_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, role_family="")
        result = validator.validate(clf)
        assert not result.is_valid

    def test_null_role_family_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, role_family=None)
        result = validator.validate(clf)
        assert not result.is_valid

    def test_invalid_role_family_no_normalized_output(self, validator, valid_classification):
        clf = dict(valid_classification, role_family="engineering")
        result = validator.validate(clf)
        assert result.normalized is None


# ---------------------------------------------------------------------------
# Invalid seniority
# ---------------------------------------------------------------------------

class TestInvalidSeniority:
    def test_unknown_seniority_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, seniority="executive")
        result = validator.validate(clf)
        assert not result.is_valid
        assert any("seniority" in e for e in result.errors)

    def test_seniority_case_mismatch_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, seniority="Senior")
        result = validator.validate(clf)
        assert not result.is_valid

    def test_integer_seniority_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, seniority=3)
        result = validator.validate(clf)
        assert not result.is_valid


# ---------------------------------------------------------------------------
# ai_level type handling
# ---------------------------------------------------------------------------

class TestAiLevelTypeHandling:
    def test_ai_level_as_string_integer_warns_not_errors(self, validator, valid_classification):
        clf = dict(valid_classification, ai_level="2")
        result = validator.validate(clf)
        # String "2" is accepted with a warning, not rejected
        assert result.is_valid, f"String '2' should produce warning, not error: {result.errors}"
        assert result.has_warnings

    def test_ai_level_as_float_integer_warns_not_errors(self, validator, valid_classification):
        clf = dict(valid_classification, ai_level=2.0)
        result = validator.validate(clf)
        assert result.is_valid or result.has_warnings  # coercible float is acceptable

    def test_ai_level_as_string_label_warns_not_errors(self, validator, valid_classification):
        clf = dict(valid_classification, ai_level="medium")
        result = validator.validate(clf)
        # "medium" → 2 is a valid coercion with a warning
        assert result.is_valid, f"String label 'medium' should coerce: {result.errors}"
        assert result.has_warnings
        assert result.normalized["ai_level"] == 2

    def test_ai_level_out_of_range_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, ai_level=4)
        result = validator.validate(clf)
        assert not result.is_valid

    def test_ai_level_negative_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, ai_level=-1)
        result = validator.validate(clf)
        assert not result.is_valid

    def test_ai_level_boolean_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, ai_level=True)
        result = validator.validate(clf)
        assert not result.is_valid

    def test_ai_level_none_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, ai_level=None)
        result = validator.validate(clf)
        assert not result.is_valid

    def test_ai_level_arbitrary_string_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, ai_level="very high")
        result = validator.validate(clf)
        assert not result.is_valid


# ---------------------------------------------------------------------------
# Confidence range
# ---------------------------------------------------------------------------

class TestConfidenceRange:
    def test_confidence_zero_passes(self, validator, valid_classification):
        clf = dict(valid_classification, confidence=0.0)
        result = validator.validate(clf)
        assert result.is_valid

    def test_confidence_one_passes(self, validator, valid_classification):
        clf = dict(valid_classification, confidence=1.0)
        result = validator.validate(clf)
        assert result.is_valid

    def test_confidence_above_one_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, confidence=1.1)
        result = validator.validate(clf)
        assert not result.is_valid

    def test_confidence_negative_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, confidence=-0.1)
        result = validator.validate(clf)
        assert not result.is_valid

    def test_confidence_string_rejected(self, validator, valid_classification):
        clf = dict(valid_classification, confidence="high")
        result = validator.validate(clf)
        assert not result.is_valid


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    def test_missing_role_family_rejected(self, validator, valid_classification):
        clf = {k: v for k, v in valid_classification.items() if k != "role_family"}
        result = validator.validate(clf)
        assert not result.is_valid
        assert any("role_family" in e for e in result.errors)

    def test_missing_seniority_rejected(self, validator, valid_classification):
        clf = {k: v for k, v in valid_classification.items() if k != "seniority"}
        result = validator.validate(clf)
        assert not result.is_valid

    def test_missing_ai_level_rejected(self, validator, valid_classification):
        clf = {k: v for k, v in valid_classification.items() if k != "ai_level"}
        result = validator.validate(clf)
        assert not result.is_valid

    def test_missing_confidence_rejected(self, validator, valid_classification):
        clf = {k: v for k, v in valid_classification.items() if k != "confidence"}
        result = validator.validate(clf)
        assert not result.is_valid

    def test_non_dict_input_rejected(self, validator):
        result = validator.validate("not a dict")
        assert not result.is_valid
        assert any("not a dict" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# No silent coercion policy
# ---------------------------------------------------------------------------

class TestNoSilentCoercion:
    """Invalid values must produce errors, not silently become valid values."""

    def test_invalid_role_family_not_converted(self, validator, valid_classification):
        clf = dict(valid_classification, role_family="design")
        result = validator.validate(clf)
        # Must fail — "design" is not "creatividad_diseno"
        assert not result.is_valid
        assert result.normalized is None

    def test_invalid_seniority_not_converted(self, validator, valid_classification):
        clf = dict(valid_classification, seniority="expert")
        result = validator.validate(clf)
        assert not result.is_valid
        assert result.normalized is None


# ---------------------------------------------------------------------------
# Batch validation
# ---------------------------------------------------------------------------

class TestBatchValidation:
    def test_batch_all_valid_returns_correct_stats(self, validator, valid_classification):
        batch = [dict(valid_classification, vacancy_id=f"ID-{i}") for i in range(5)]
        results, stats = validator.validate_batch(batch)
        assert stats["valid"] == 5
        assert stats["invalid"] == 0
        assert stats["none_responses"] == 0

    def test_batch_with_none_responses_counted(self, validator, valid_classification):
        batch = [valid_classification, None, valid_classification]
        results, stats = validator.validate_batch(batch)
        assert stats["none_responses"] == 1
        assert stats["valid"] == 2

    def test_batch_with_invalid_counted(self, validator, valid_classification):
        invalid = dict(valid_classification, role_family="BAD_VALUE")
        batch = [valid_classification, invalid]
        results, stats = validator.validate_batch(batch)
        assert stats["valid"] == 1
        assert stats["invalid"] == 1

    def test_batch_returns_aligned_results(self, validator, valid_classification):
        batch = [valid_classification, None]
        results, _ = validator.validate_batch(batch)
        assert len(results) == 2
        assert results[0].is_valid
        assert not results[1].is_valid

    def test_empty_batch_returns_empty_results(self, validator):
        results, stats = validator.validate_batch([])
        assert results == []
        assert stats["valid"] == 0
