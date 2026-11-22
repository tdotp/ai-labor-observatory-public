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

Validated with Pydantic:

```python
class ClassificationResult(BaseModel):
    role_family: RoleFamilyEnum        # creative_design | content_copywriting | social_media |
                                       # marketing_growth | pr_communications | strategy_accounts | other
    seniority: SeniorityEnum           # junior | mid | senior | director | unknown
    ai_level: AILevelEnum              # none | low | medium | high
    ai_tools_detected: List[str]
    confidence: float                  # 0.0 – 1.0, LLM self-reported
```

Taxonomy values are derived from `data/taxonomies/role_families.json`. Any response that does not match the schema is retried once; if the retry also fails, the vacancy is stored with `ai_level = needs_review` and excluded from aggregate queries.

---

## What IS Validated

| Check | Mechanism |
|-------|-----------|
| `role_family` is in the taxonomy | Pydantic enum |
| `seniority` is in the taxonomy | Pydantic enum |
| `ai_level` is in the taxonomy | Pydantic enum |
| `confidence` is in [0, 1] | Pydantic field validator |
| Response is valid JSON | json.loads + json.JSONDecodeError retry |
| Confidence threshold applied | Vacancies with `confidence < 0.7` stored as `needs_review` |
| Response model logged | `response["model"]` saved to `classification_model` column |

---

## What Is NOT Validated

| Gap | Why it matters |
|-----|---------------|
| **No human gold set.** The 5,610 labeled vacancies have not been compared against human annotations. | Classification accuracy, recall, and precision are unknown. |
| **No inter-annotator agreement (κ).** No human–human agreement baseline exists. | The taxonomy itself may be ambiguous in ways not yet detected. |
| **LLM confidence is not calibrated.** A reported confidence of 0.85 does not mean the label is correct 85% of the time. | Filtering on confidence removes uncertain labels, but the remaining labels may still be wrong. |
| **No cross-model consistency test.** Labels have not been compared across model versions or providers. | A model update could shift the label distribution silently. |
| **No adversarial test.** The prompt has not been tested with deliberately misleading vacancy descriptions. | Borderline cases are handled by the enum constraint, but creative prompt injections are untested. |

---

## Known Limitations

- Labels should be treated as **LLM-generated annotations, not ground truth.** They are suitable for exploratory analysis and trend detection, not for research claims requiring validated accuracy.
- The confidence score should be treated as an **ordinal signal** (higher = more certain), not as a probability.
- The model version may change without notice via OpenRouter's routing layer. `response["model"]` logging mitigates but does not fully prevent silent version drift.

---

## How to Improve

1. **Build a human gold set.** Annotate ~200 stratified vacancies (across countries, role families, and seniority levels) with two independent human raters. Compute Cohen's κ for human–human agreement, then human–LLM agreement. Publish κ alongside any reported statistics.
2. **Calibrate confidence.** Use the gold set to plot precision vs. confidence threshold and choose a threshold with empirical support.
3. **Version the prompt.** Store a SHA-256 hash of the prompt alongside each classification so that prompt changes are traceable.
4. **Test cross-model consistency.** Run a sample of 100 vacancies through multiple models and compare label distributions.
