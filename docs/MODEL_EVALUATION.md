# Model Evaluation

## Model Used

**Default model:** `openai/gpt-3.5-turbo` via OpenRouter.

The OpenRouter API routes requests to the named model; the pipeline stores `response["model"]` (the model actually served) alongside each classification for provenance. The model alias may resolve to different model versions over time.

> **Note:** Earlier documentation for this project incorrectly stated "Claude Haiku" as the model in use. The code default has always been `openai/gpt-3.5-turbo`. This discrepancy has been corrected.

---

## Prompt Design

The classification prompt is stored in `prompts/openrouter_classification_prompt.md`. It instructs the model to:

1. Read the vacancy title, company name, country, and truncated description (≤800 characters).
2. Assign one `role_family`, one `seniority`, one `ai_level`, list detected AI tools, and report a confidence score.
3. Return the result as a JSON object matching a defined schema.

System instructions and user-supplied vacancy data are separated in the message structure to reduce prompt injection risk (vacancy content is passed in the `user` role with explicit delimiters).

**Temperature:** 0. This maximizes output determinism for a given input and model version. Earlier versions used temperature 0.7, which introduced unnecessary label variance.

---

## Output Schema

Returned as JSON and validated by `TaxonomyValidator` (`validation/taxonomy_validator.py`):

```json
{
  "vacancy_id": "string",
  "role_family": "creatividad_diseno | contenido_social | marketing_growth | pr_comunicaciones | estrategia_cuentas | OTHER",
  "seniority": "junior | specialist | senior | lead | manager | director",
  "ai_level": "integer 0–3",
  "ai_tools_detected": ["list of strings"],
  "ai_keywords_detected": ["list of strings"],
  "confidence": "float 0.0–1.0",
  "reasoning": "string"
}
```

Taxonomy values are derived from `data/taxonomies/role_families.json`. Any response that does not match the schema is counted as invalid and **not silently coerced to a valid value**. See `validation/taxonomy_validator.py` for the rejection rules.

---

## Gold Set Evaluation

> **Important:** This gold set uses rule-based reference labels, not human-annotated ground truth. The labels are documented in `data/gold_set/vacancies_gold.json` and were assigned by the system authors according to written labeling rules. They are **not equivalent to expert-validated annotations** and do not establish an empirical accuracy claim for real-world job postings.

The gold set contains **45 synthetic vacancies** covering:

| Case Type | Count |
|---|---|
| explicit_ai_tools | 5 |
| ai_as_primary_requirement | 6 |
| ai_as_desirable | 6 |
| automation_no_ai | 3 |
| ambiguous_ai_reference | 5 |
| no_ai | 13 |
| insufficient_info | 3 |
| taxonomy_edge_case | 2 |

Ambiguous cases (marked `is_ambiguous=true`) are excluded from default evaluation metrics — they represent cases where even the reference labeler is uncertain.

**Gold set summary (non-ambiguous subset, n=36):**

| Field | Perfect predictor (sanity check) | Rule-based baseline | Random baseline |
|---|---|---|---|
| role_family macro-F1 | 1.000 | 0.308 | 0.132 |
| seniority macro-F1 | 1.000 | 0.758 | 0.213 |
| ai_level macro-F1 | 1.000 | 0.314 | 0.157 |
| role_family accuracy | 1.000 | 0.361 | 0.139 |
| ai_level accuracy | 1.000 | 0.444 | 0.194 |

The rule-based baseline uses simple keyword heuristics defined in `evaluation/classifier_eval.py`. It is a non-LLM baseline that shows what a naive approach achieves — not a comparison against the actual LLM classifier.

**To evaluate the actual LLM classifier against this gold set:**
```python
from evaluation.classifier_eval import ClassifierEvaluator
# 1. Collect LLM predictions for each gold vacancy (requires real API key)
# 2. Pass predictions list to:
report = ClassifierEvaluator.evaluate(predictions=my_preds, is_live_llm=True)
print(report.to_dict())
```
LLM-based results are not shown here because they require a live API call, vary by prompt version and model version, and cannot be reproduced deterministically without pinning both.

---

## Validation Controls

| Check | Mechanism | File |
|-------|-----------|------|
| `role_family` in taxonomy (exact match, case-sensitive) | TaxonomyValidator enum check | `validation/taxonomy_validator.py` |
| `seniority` in taxonomy (exact match) | TaxonomyValidator enum check | same |
| `ai_level` integer 0–3 | TaxonomyValidator type + range check | same |
| `confidence` in [0.0, 1.0] | TaxonomyValidator field validator | same |
| Response is valid JSON | json.loads + JSONDecodeError retry | `classification/openrouter_classifier.py` |
| Invalid values explicitly rejected | No silent coercion; errors logged | `validation/taxonomy_validator.py` |
| Response model logged | `response["model"]` saved via provenance | `classification/provenance.py` |
| Prompt version hashed | SHA-256 of prompt file content | `classification/provenance.py` |
| Taxonomy version pinned | Schema version + content hash | `classification/provenance.py` |

---

## Traceability

Each classification result includes a `provenance` block generated by `classification/provenance.py`:

```json
{
  "run_id": "uuid4 — shared across all calls in one pipeline run",
  "prompt_version": "sha256:abc123def456 — hash of prompt file",
  "taxonomy_version": "1.0.0+sha256:xyz789 — schema version + file hash",
  "vacancy_id": "V-001",
  "requested_model": "openai/gpt-3.5-turbo",
  "served_model": "openai/gpt-3.5-turbo-0125",
  "classified_at": "2026-01-01T12:00:00+00:00",
  "validation_status": "valid | invalid_taxonomy | invalid_json | api_error",
  "tokens_used": {"prompt_tokens": 400, "completion_tokens": 80, "total_tokens": 480}
}
```

---

## What Is NOT Validated

| Gap | Why it matters |
|-----|---------------|
| **No human-validated gold set.** | The 45 vacancies in `data/gold_set/` use rule-based reference labels, not human expert annotations. Classification accuracy against real-world labels is unknown. |
| **No inter-annotator agreement (κ).** | The taxonomy itself may be ambiguous in ways not yet detected. |
| **LLM confidence is not calibrated.** | A reported confidence of 0.85 does not mean the label is correct 85% of the time. |
| **No cross-model consistency test.** | Labels have not been compared across model versions or providers. |
| **Gold set is synthetic.** | The 45 gold vacancies were written by the system authors to cover test cases. They may not represent the statistical distribution of real LatAm job postings. |

---

## How to Improve

1. **Human annotation.** Have 2–3 independent human raters label ~200 stratified vacancies. Compute Cohen's κ for human–human agreement, then human–LLM agreement. Publish κ alongside any reported statistics.
2. **Calibrate confidence.** Use the annotated gold set to plot precision vs. confidence threshold and choose a threshold with empirical support.
3. **Cross-model consistency.** Run a sample of 100 vacancies through multiple models and compare label distributions.
4. **Real-distribution gold set.** Extend the gold set with real (anonymized) vacancies sampled from the production pipeline's output, not synthetic ones.
