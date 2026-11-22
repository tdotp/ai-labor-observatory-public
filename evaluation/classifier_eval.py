"""
Classifier evaluation module — AI Labor Observatory.

Compares predicted classifications against a labeled gold set.
Returns precision, recall, F1-score per class and macro averages.

IMPORTANT: Metrics are computed against RULE-BASED REFERENCE LABELS, not
against human-validated ground truth. Labels marked is_ambiguous=true in
the gold set are excluded from metrics by default to avoid penalizing the
classifier for cases where even the reference labeler is uncertain.

Ambiguous cases are reported separately for transparency.

Usage (with mock predictions):
    from evaluation.classifier_eval import ClassifierEvaluator
    results = ClassifierEvaluator.evaluate(predictions=my_preds, gold_path="data/gold_set/vacancies_gold.json")

Usage (with real LLM predictions):
    # Pass is_live_llm=True to flag that results come from a real LLM call,
    # not a deterministic mock. Live results may vary between runs.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid taxonomy values (must match prompt spec)
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


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FieldMetrics:
    """Per-class and macro precision/recall/F1 for one taxonomy field."""
    field_name: str
    classes: List[str]
    per_class: Dict[str, Dict[str, float]] = field(default_factory=dict)
    macro_precision: float = 0.0
    macro_recall: float = 0.0
    macro_f1: float = 0.0
    accuracy: float = 0.0
    support: int = 0
    invalid_predictions: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationReport:
    """Complete evaluation report across all taxonomy fields."""
    total_gold: int = 0
    evaluated: int = 0
    skipped_ambiguous: int = 0
    invalid_predictions: int = 0
    is_live_llm: bool = False

    role_family: Optional[FieldMetrics] = None
    seniority: Optional[FieldMetrics] = None
    ai_level: Optional[FieldMetrics] = None

    # Disagreements for manual review
    disagreements: List[Dict[str, Any]] = field(default_factory=list)
    ambiguous_cases: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "summary": {
                "total_gold": self.total_gold,
                "evaluated": self.evaluated,
                "skipped_ambiguous": self.skipped_ambiguous,
                "invalid_predictions": self.invalid_predictions,
                "is_live_llm": self.is_live_llm,
                "note": (
                    "Metrics compare predictions against rule-based reference labels. "
                    "NOT validated against human-annotated ground truth."
                ),
            },
            "role_family": self.role_family.to_dict() if self.role_family else None,
            "seniority": self.seniority.to_dict() if self.seniority else None,
            "ai_level": self.ai_level.to_dict() if self.ai_level else None,
            "disagreements": self.disagreements,
            "ambiguous_cases_summary": [
                {"vacancy_id": c["vacancy_id"], "case_type": c.get("case_type"), "notes": c.get("notes")}
                for c in self.ambiguous_cases
            ],
        }
        return d


# ---------------------------------------------------------------------------
# Core metric computation
# ---------------------------------------------------------------------------

def _compute_field_metrics(
    gold_labels: List[Any],
    pred_labels: List[Any],
    field_name: str,
    valid_values: set,
) -> FieldMetrics:
    """
    Compute precision, recall, F1 per class and macro averages.

    Invalid predictions (values not in taxonomy) are counted separately
    and excluded from per-class metrics — they cannot be "correct."
    """
    classes = sorted(str(v) for v in valid_values)

    # Identify invalid predictions
    invalid_idxs = {i for i, p in enumerate(pred_labels) if p not in valid_values}
    invalid_count = len(invalid_idxs)

    # Filter to valid predictions only
    valid_pairs = [
        (g, p) for i, (g, p) in enumerate(zip(gold_labels, pred_labels))
        if i not in invalid_idxs
    ]
    support = len(valid_pairs)

    if support == 0:
        return FieldMetrics(
            field_name=field_name,
            classes=classes,
            macro_precision=0.0,
            macro_recall=0.0,
            macro_f1=0.0,
            accuracy=0.0,
            support=0,
            invalid_predictions=invalid_count,
        )

    # Normalize labels to strings for consistent dict key access
    # (ai_level labels are ints; classes list is always strings)
    valid_pairs_str = [(str(g), str(p)) for g, p in valid_pairs]

    # Counts per class
    tp: Dict[str, int] = defaultdict(int)
    fp: Dict[str, int] = defaultdict(int)
    fn: Dict[str, int] = defaultdict(int)

    for gold, pred in valid_pairs_str:
        if gold == pred:
            tp[gold] += 1
        else:
            fp[pred] += 1
            fn[gold] += 1

    # Per-class metrics
    per_class: Dict[str, Dict[str, float]] = {}
    for cls in classes:
        c_tp = tp[cls]
        c_fp = fp[cls]
        c_fn = fn[cls]
        c_support = c_tp + c_fn

        prec = c_tp / (c_tp + c_fp) if (c_tp + c_fp) > 0 else 0.0
        rec = c_tp / (c_tp + c_fn) if (c_tp + c_fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

        per_class[str(cls)] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": c_support,
        }

    # Macro averages (only over classes that appear in the gold set)
    present_classes = [cls for cls in classes if per_class[str(cls)]["support"] > 0]
    if present_classes:
        macro_p = sum(per_class[str(c)]["precision"] for c in present_classes) / len(present_classes)
        macro_r = sum(per_class[str(c)]["recall"] for c in present_classes) / len(present_classes)
        macro_f = sum(per_class[str(c)]["f1"] for c in present_classes) / len(present_classes)
    else:
        macro_p = macro_r = macro_f = 0.0

    # Accuracy (exact match, over valid predictions)
    correct = sum(1 for g, p in valid_pairs_str if g == p)
    accuracy = correct / support if support > 0 else 0.0

    return FieldMetrics(
        field_name=field_name,
        classes=classes,
        per_class=per_class,
        macro_precision=round(macro_p, 4),
        macro_recall=round(macro_r, 4),
        macro_f1=round(macro_f, 4),
        accuracy=round(accuracy, 4),
        support=support,
        invalid_predictions=invalid_count,
    )


# ---------------------------------------------------------------------------
# Public evaluator
# ---------------------------------------------------------------------------

class ClassifierEvaluator:
    """
    Compare classifier predictions against the gold set.

    IMPORTANT: This evaluator measures agreement between the classifier
    and rule-based reference labels. It does NOT measure accuracy against
    real-world job market labels or human expert annotations.
    """

    DEFAULT_GOLD_PATH = Path(__file__).parent.parent / "data" / "gold_set" / "vacancies_gold.json"

    @classmethod
    def load_gold_set(cls, gold_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        """Load gold set from JSON file."""
        path = Path(gold_path) if gold_path else cls.DEFAULT_GOLD_PATH
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def evaluate(
        cls,
        predictions: List[Dict[str, Any]],
        gold_path: Optional[Path] = None,
        exclude_ambiguous: bool = True,
        is_live_llm: bool = False,
    ) -> EvaluationReport:
        """
        Evaluate predictions against the gold set.

        Args:
            predictions: List of dicts, each with keys:
                vacancy_id, role_family, seniority, ai_level
            gold_path: Path to gold set JSON (defaults to data/gold_set/vacancies_gold.json)
            exclude_ambiguous: If True, skip cases marked is_ambiguous=True in the gold set.
                               These are cases where even the reference labeler is uncertain.
            is_live_llm: Set True when predictions come from a real LLM call (not a mock).
                         Live results may vary between runs; mock results are deterministic.

        Returns:
            EvaluationReport with per-field metrics.
        """
        gold_data = cls.load_gold_set(gold_path)
        gold_by_id = {v["vacancy_id"]: v for v in gold_data}
        pred_by_id = {p["vacancy_id"]: p for p in predictions}

        report = EvaluationReport(
            total_gold=len(gold_data),
            is_live_llm=is_live_llm,
        )

        gold_rf, pred_rf = [], []
        gold_sn, pred_sn = [], []
        gold_ai, pred_ai = [], []

        ambiguous_cases = []
        disagreements = []

        for vacancy_id, gold_item in gold_by_id.items():
            gt = gold_item["ground_truth"]
            meta = gold_item.get("case_metadata", {})
            is_ambiguous = meta.get("is_ambiguous", False)

            if is_ambiguous:
                ambiguous_cases.append({
                    "vacancy_id": vacancy_id,
                    "case_type": meta.get("case_type"),
                    "notes": meta.get("notes"),
                    "ground_truth": gt,
                })
                if exclude_ambiguous:
                    report.skipped_ambiguous += 1
                    continue

            pred = pred_by_id.get(vacancy_id)
            if pred is None:
                logger.warning(f"No prediction for gold vacancy {vacancy_id} — skipping")
                continue

            # Collect labels (convert ai_level to int)
            gold_rf.append(gt["role_family"])
            pred_rf.append(pred.get("role_family", "MISSING"))

            gold_sn.append(gt["seniority"])
            pred_sn.append(pred.get("seniority", "MISSING"))

            gold_ai.append(int(gt["ai_level"]))
            raw_pred_ai = pred.get("ai_level")
            try:
                pred_ai.append(int(raw_pred_ai))
            except (TypeError, ValueError):
                pred_ai.append(raw_pred_ai)  # will be counted as invalid

            # Track disagreements for review
            mismatch = {}
            if pred.get("role_family") != gt["role_family"]:
                mismatch["role_family"] = {"gold": gt["role_family"], "pred": pred.get("role_family")}
            if pred.get("seniority") != gt["seniority"]:
                mismatch["seniority"] = {"gold": gt["seniority"], "pred": pred.get("seniority")}
            try:
                pred_ai_v = int(raw_pred_ai)
            except (TypeError, ValueError):
                pred_ai_v = None
            if pred_ai_v != int(gt["ai_level"]):
                mismatch["ai_level"] = {"gold": gt["ai_level"], "pred": raw_pred_ai}
            if mismatch:
                disagreements.append({
                    "vacancy_id": vacancy_id,
                    "raw_title": gold_item.get("raw_title", ""),
                    "case_type": meta.get("case_type", ""),
                    "mismatches": mismatch,
                })

            report.evaluated += 1

        report.ambiguous_cases = ambiguous_cases
        report.disagreements = disagreements

        if report.evaluated == 0:
            logger.warning("No predictions matched the gold set — empty evaluation")
            return report

        # Compute per-field metrics
        report.role_family = _compute_field_metrics(
            gold_rf, pred_rf, "role_family", VALID_ROLE_FAMILIES
        )
        report.seniority = _compute_field_metrics(
            gold_sn, pred_sn, "seniority", VALID_SENIORITY
        )
        report.ai_level = _compute_field_metrics(
            gold_ai, pred_ai, "ai_level", VALID_AI_LEVELS
        )

        invalid = (
            report.role_family.invalid_predictions
            + report.seniority.invalid_predictions
            + report.ai_level.invalid_predictions
        )
        report.invalid_predictions = invalid

        logger.info(
            f"Evaluation complete: {report.evaluated} evaluated, "
            f"{report.skipped_ambiguous} skipped (ambiguous), "
            f"{invalid} invalid predictions"
        )
        return report

    @classmethod
    def mock_perfect_predictions(cls, gold_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        """
        Return predictions that exactly match the gold set.

        Used for testing the evaluator itself — a perfect predictor should
        yield F1=1.0 on all non-ambiguous cases.
        """
        gold_data = cls.load_gold_set(gold_path)
        return [
            {
                "vacancy_id": v["vacancy_id"],
                "role_family": v["ground_truth"]["role_family"],
                "seniority": v["ground_truth"]["seniority"],
                "ai_level": v["ground_truth"]["ai_level"],
                "confidence": 1.0,
                "model": "mock_perfect",
            }
            for v in gold_data
        ]

    @classmethod
    def mock_random_predictions(cls, gold_path: Optional[Path] = None, seed: int = 42) -> List[Dict[str, Any]]:
        """
        Return random but valid predictions from the gold set.

        Used for testing that the evaluator produces sub-1.0 scores on
        non-trivial predictions.
        """
        import random
        rng = random.Random(seed)
        gold_data = cls.load_gold_set(gold_path)
        rf_choices = list(VALID_ROLE_FAMILIES)
        sn_choices = list(VALID_SENIORITY)
        ai_choices = list(VALID_AI_LEVELS)
        return [
            {
                "vacancy_id": v["vacancy_id"],
                "role_family": rng.choice(rf_choices),
                "seniority": rng.choice(sn_choices),
                "ai_level": rng.choice(ai_choices),
                "confidence": round(rng.uniform(0.4, 0.8), 2),
                "model": "mock_random",
            }
            for v in gold_data
        ]

    @classmethod
    def mock_rule_based_predictions(cls, gold_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        """
        Produce rule-based predictions using simple keyword heuristics.

        This is a deterministic non-LLM baseline that demonstrates what a
        naive keyword classifier achieves. It is NOT the actual LLM classifier.
        Used to compare against LLM classifier results.
        """
        gold_data = cls.load_gold_set(gold_path)
        results = []
        for v in gold_data:
            title = (v.get("raw_title") or "").lower()
            desc = (v.get("raw_description") or "").lower()
            req = (v.get("raw_requirements") or "").lower()
            full_text = f"{title} {desc} {req}"

            # Role family heuristic
            rf = "OTHER"
            if any(w in full_text for w in ["design", "ux", "ui", "figma", "visual", "creative director", "motion", "art director"]):
                rf = "creatividad_diseno"
            elif any(w in full_text for w in ["social media", "community", "content creat", "copywriter", "video editor", "redactor"]):
                rf = "contenido_social"
            elif any(w in full_text for w in ["growth", "performance market", "seo", "sem", "paid", "marketing manager", "marketing digital"]):
                rf = "marketing_growth"
            elif any(w in full_text for w in ["pr ", "public relations", "communications", "press", "comunicacion"]):
                rf = "pr_comunicaciones"
            elif any(w in full_text for w in ["account manager", "account exec", "account director", "cuentas", "estrateg", "strategic planner", "brand strateg"]):
                rf = "estrategia_cuentas"

            # AI level heuristic
            ai_tools = ["chatgpt", "midjourney", "dall-e", "stable diffusion", "runway ml", "claude", "jasper",
                        "albert.ai", "persado", "pika labs", "elevenlabs", "adobe firefly", "figma ai",
                        "capcut ai", "gpt-4", "copilot", "bard", "llm", "generative ai", "ai-native"]
            ai_mentions = sum(1 for t in ai_tools if t in full_text)

            if ai_mentions >= 3 or any(w in full_text for w in ["mandatory", "required", "ai-native", "100% ai", "obligatorio"]):
                ai_level = 3
            elif ai_mentions >= 2 or any(w in full_text for w in ["ai-first", "ai is core", "primary"]):
                ai_level = 3
            elif ai_mentions == 1 or any(w in full_text for w in ["ai tool", "herramienta", "integrando", "integrating ai"]):
                ai_level = 2
            elif any(w in full_text for w in ["plus", "valued", "deseable", "curiosity", "exploring", "optional"]):
                ai_level = 1
            else:
                ai_level = 0

            # Seniority heuristic
            sn = "senior"
            if any(w in title for w in ["junior", "jnr", "entry", "coordinador", "coordinator"]):
                sn = "junior"
            elif any(w in title for w in ["director", "head of", "chief", "vp ", "responsable"]):
                sn = "director"
            elif any(w in title for w in ["lead", "lead "]):
                sn = "lead"
            elif any(w in title for w in ["manager", "gerente"]):
                sn = "manager"

            results.append({
                "vacancy_id": v["vacancy_id"],
                "role_family": rf,
                "seniority": sn,
                "ai_level": ai_level,
                "confidence": 0.6,
                "model": "mock_rule_based",
            })
        return results
