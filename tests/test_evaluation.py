"""
Tests for the classifier evaluation module.

Covers:
  - Gold set structure and completeness
  - Perfect predictor → F1=1.0
  - Random predictor → F1<1.0 (non-trivial predictions)
  - Rule-based baseline produces valid metrics
  - Invalid predictions are counted, not silently coerced
  - Ambiguous cases are separated from main metrics
  - Evaluation report serializes to dict

NOTE: These tests run with mock predictions — no real LLM calls are made.
Metrics here measure agreement with RULE-BASED REFERENCE LABELS, not
against human-validated ground truth.
"""

import pytest
import json
from pathlib import Path
from evaluation.classifier_eval import (
    ClassifierEvaluator,
    EvaluationReport,
    FieldMetrics,
    _compute_field_metrics,
    VALID_ROLE_FAMILIES,
    VALID_SENIORITY,
    VALID_AI_LEVELS,
)

GOLD_PATH = Path(__file__).parent.parent / "data" / "gold_set" / "vacancies_gold.json"


# ---------------------------------------------------------------------------
# Gold set structure
# ---------------------------------------------------------------------------

class TestGoldSetStructure:
    """The gold set must meet structural requirements before any evaluation."""

    def test_gold_set_exists(self):
        assert GOLD_PATH.exists(), f"Gold set not found at {GOLD_PATH}"

    def test_gold_set_is_valid_json(self):
        with open(GOLD_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_gold_set_has_minimum_size(self):
        data = ClassifierEvaluator.load_gold_set()
        assert len(data) >= 40, f"Gold set has {len(data)} vacancies; need at least 40"

    def test_all_vacancies_have_required_fields(self):
        data = ClassifierEvaluator.load_gold_set()
        required = {"vacancy_id", "raw_title", "raw_description", "ground_truth", "case_metadata"}
        for v in data:
            missing = required - set(v.keys())
            assert not missing, f"Vacancy {v.get('vacancy_id')} missing fields: {missing}"

    def test_all_ground_truth_has_required_fields(self):
        data = ClassifierEvaluator.load_gold_set()
        for v in data:
            gt = v["ground_truth"]
            assert "role_family" in gt, f"Vacancy {v['vacancy_id']} missing ground_truth.role_family"
            assert "seniority" in gt, f"Vacancy {v['vacancy_id']} missing ground_truth.seniority"
            assert "ai_level" in gt, f"Vacancy {v['vacancy_id']} missing ground_truth.ai_level"

    def test_all_ground_truth_values_are_valid(self):
        data = ClassifierEvaluator.load_gold_set()
        for v in data:
            gt = v["ground_truth"]
            vid = v["vacancy_id"]
            assert gt["role_family"] in VALID_ROLE_FAMILIES, (
                f"Vacancy {vid}: invalid role_family '{gt['role_family']}'"
            )
            assert gt["seniority"] in VALID_SENIORITY, (
                f"Vacancy {vid}: invalid seniority '{gt['seniority']}'"
            )
            assert int(gt["ai_level"]) in VALID_AI_LEVELS, (
                f"Vacancy {vid}: invalid ai_level '{gt['ai_level']}'"
            )

    def test_case_types_cover_required_categories(self):
        data = ClassifierEvaluator.load_gold_set()
        case_types = {v["case_metadata"]["case_type"] for v in data}
        required_types = {
            "explicit_ai_tools",
            "ai_as_primary_requirement",
            "ai_as_desirable",
            "automation_no_ai",
            "ambiguous_ai_reference",
            "no_ai",
            "insufficient_info",
            "taxonomy_edge_case",
        }
        missing = required_types - case_types
        assert not missing, f"Gold set missing case types: {missing}"

    def test_all_role_families_represented(self):
        data = ClassifierEvaluator.load_gold_set()
        families = {v["ground_truth"]["role_family"] for v in data}
        required = {"creatividad_diseno", "contenido_social", "marketing_growth",
                    "pr_comunicaciones", "estrategia_cuentas", "OTHER"}
        missing = required - families
        assert not missing, f"Gold set missing role families: {missing}"

    def test_all_ai_levels_represented(self):
        data = ClassifierEvaluator.load_gold_set()
        levels = {int(v["ground_truth"]["ai_level"]) for v in data}
        assert levels == {0, 1, 2, 3}, f"Gold set missing AI levels: {set(range(4)) - levels}"

    def test_ambiguous_cases_marked(self):
        data = ClassifierEvaluator.load_gold_set()
        ambiguous = [v for v in data if v["case_metadata"].get("is_ambiguous")]
        assert len(ambiguous) >= 3, (
            f"Expected at least 3 ambiguous cases for realistic evaluation; found {len(ambiguous)}"
        )

    def test_vacancy_ids_are_unique(self):
        data = ClassifierEvaluator.load_gold_set()
        ids = [v["vacancy_id"] for v in data]
        assert len(ids) == len(set(ids)), "Duplicate vacancy_id in gold set"


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

class TestFieldMetrics:
    """Unit tests for the internal _compute_field_metrics function."""

    def test_perfect_predictions_yield_f1_one(self):
        labels = ["a", "b", "a", "c", "b"]
        metrics = _compute_field_metrics(labels, labels, "test", {"a", "b", "c"})
        assert metrics.macro_f1 == 1.0
        assert metrics.accuracy == 1.0

    def test_all_wrong_predictions_yield_zero_f1(self):
        gold = ["a", "a", "a"]
        pred = ["b", "b", "b"]
        metrics = _compute_field_metrics(gold, pred, "test", {"a", "b"})
        assert metrics.accuracy == 0.0
        assert metrics.per_class["a"]["recall"] == 0.0

    def test_invalid_predictions_are_counted_separately(self):
        gold = ["a", "b", "a"]
        pred = ["a", "INVALID_VALUE", "a"]
        metrics = _compute_field_metrics(gold, pred, "test", {"a", "b"})
        assert metrics.invalid_predictions == 1
        # Only 2 valid predictions evaluated
        assert metrics.support == 2

    def test_empty_predictions_return_zero_metrics(self):
        metrics = _compute_field_metrics([], [], "test", {"a", "b"})
        assert metrics.support == 0
        assert metrics.macro_f1 == 0.0

    def test_per_class_support_is_gold_frequency(self):
        gold = ["a", "a", "b"]
        pred = ["a", "a", "b"]
        metrics = _compute_field_metrics(gold, pred, "test", {"a", "b"})
        assert metrics.per_class["a"]["support"] == 2
        assert metrics.per_class["b"]["support"] == 1


# ---------------------------------------------------------------------------
# End-to-end evaluation
# ---------------------------------------------------------------------------

class TestClassifierEvaluator:
    """Integration tests for ClassifierEvaluator."""

    def test_perfect_predictor_yields_f1_one(self):
        preds = ClassifierEvaluator.mock_perfect_predictions()
        report = ClassifierEvaluator.evaluate(preds, exclude_ambiguous=True)
        assert report.role_family.macro_f1 == 1.0, (
            f"Perfect predictor should have macro F1=1.0, got {report.role_family.macro_f1}"
        )
        assert report.seniority.macro_f1 == 1.0
        assert report.ai_level.macro_f1 == 1.0

    def test_random_predictor_has_lower_f1(self):
        preds = ClassifierEvaluator.mock_random_predictions(seed=42)
        report = ClassifierEvaluator.evaluate(preds, exclude_ambiguous=True)
        assert report.role_family.macro_f1 < 1.0, (
            "Random predictor should have macro F1 < 1.0"
        )

    def test_rule_based_baseline_produces_valid_metrics(self):
        preds = ClassifierEvaluator.mock_rule_based_predictions()
        report = ClassifierEvaluator.evaluate(preds, exclude_ambiguous=True)
        assert report.evaluated > 0
        assert 0.0 <= report.role_family.macro_f1 <= 1.0
        assert 0.0 <= report.ai_level.macro_f1 <= 1.0
        assert 0.0 <= report.seniority.macro_f1 <= 1.0

    def test_ambiguous_cases_excluded_by_default(self):
        preds = ClassifierEvaluator.mock_perfect_predictions()
        report = ClassifierEvaluator.evaluate(preds, exclude_ambiguous=True)
        assert report.skipped_ambiguous > 0, "Expected some ambiguous cases to be skipped"
        assert report.evaluated < report.total_gold

    def test_ambiguous_cases_included_when_requested(self):
        preds = ClassifierEvaluator.mock_perfect_predictions()
        report_excl = ClassifierEvaluator.evaluate(preds, exclude_ambiguous=True)
        report_incl = ClassifierEvaluator.evaluate(preds, exclude_ambiguous=False)
        assert report_incl.evaluated > report_excl.evaluated

    def test_missing_predictions_are_skipped(self):
        preds = ClassifierEvaluator.mock_perfect_predictions()
        # Remove one prediction
        partial_preds = preds[:-1]
        report = ClassifierEvaluator.evaluate(partial_preds)
        # Should not crash — just fewer evaluated
        assert report.evaluated <= report.total_gold

    def test_report_serializes_to_dict(self):
        preds = ClassifierEvaluator.mock_perfect_predictions()
        report = ClassifierEvaluator.evaluate(preds)
        d = report.to_dict()
        assert "summary" in d
        assert "role_family" in d
        assert "seniority" in d
        assert "ai_level" in d
        assert d["summary"]["total_gold"] > 0

    def test_live_llm_flag_propagates_to_report(self):
        preds = ClassifierEvaluator.mock_perfect_predictions()
        report = ClassifierEvaluator.evaluate(preds, is_live_llm=True)
        assert report.is_live_llm is True
        d = report.to_dict()
        assert d["summary"]["is_live_llm"] is True

    def test_report_note_disclaims_ground_truth_validation(self):
        preds = ClassifierEvaluator.mock_perfect_predictions()
        report = ClassifierEvaluator.evaluate(preds)
        d = report.to_dict()
        note = d["summary"].get("note", "")
        assert "rule-based" in note.lower() or "reference label" in note.lower(), (
            "Report summary must disclaim that labels are rule-based, not human-validated"
        )

    def test_invalid_role_family_in_prediction_counted(self):
        preds = ClassifierEvaluator.mock_perfect_predictions()
        # Inject one invalid role_family
        preds[0]["role_family"] = "completely_invalid_family"
        report = ClassifierEvaluator.evaluate(preds, exclude_ambiguous=False)
        total_invalid = (
            (report.role_family.invalid_predictions if report.role_family else 0)
        )
        assert total_invalid >= 1, "Invalid role_family prediction should be counted"

    def test_rule_based_baseline_role_family_f1_better_than_random(self):
        rule_preds = ClassifierEvaluator.mock_rule_based_predictions()
        rand_preds = ClassifierEvaluator.mock_random_predictions(seed=42)
        rule_report = ClassifierEvaluator.evaluate(rule_preds, exclude_ambiguous=True)
        rand_report = ClassifierEvaluator.evaluate(rand_preds, exclude_ambiguous=True)
        assert rule_report.role_family.macro_f1 >= rand_report.role_family.macro_f1, (
            "Rule-based classifier should perform at least as well as random on role_family"
        )
