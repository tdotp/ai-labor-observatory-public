# AI Governance Case Study: AI Labor Observatory

This document describes the governance challenges encountered while building and operating the AI Labor Observatory, the controls that were implemented, and the lessons learned. It uses NIST AI RMF 1.0 and the NIST Artificial Intelligence Risk Management Framework: Generative AI Profile (NIST AI 600-1) as reference vocabulary — not as a compliance claim.

---

## Problem

The AI Labor Observatory tracks how demand for AI-related skills is evolving in creative, marketing, and communications job postings across Latin America. The system scrapes job listings from LinkedIn and Indeed, cleans and stores them in a relational database, and uses a large language model to classify each posting by role family, seniority, and AI skill level.

Three governance challenges emerged during development that are typical of small-scale AI research systems:

1. **Reliability of AI-generated labels.** The LLM classification is the core output of the study. If the labels are unreliable, every downstream finding is unreliable.
2. **Cost and runaway automation.** An automated pipeline with API calls to external services can generate unexpected expenditure if scheduling or concurrency controls fail.
3. **Credential and data hygiene.** Operational documentation containing real API keys and infrastructure identifiers was committed to the version-controlled repository.

---

## Risks Identified

Using the NIST AI RMF's GOVERN → MAP → MEASURE → MANAGE structure as a lens:

| Category | Risk |
|----------|------|
| Trustworthiness (Accuracy) | LLM classification at temperature 0.7 produces inconsistent labels for borderline vacancies |
| Trustworthiness (Reliability) | `CONFIDENCE_THRESHOLD` was defined in configuration but never applied in the pipeline |
| Accountability | The model identifier saved to the database was the model *requested*, not the model *served* by the routing layer |
| Security | Five credentials or secrets were present in versioned documentation files |
| Operational | An AI agent deleted a cron lock file, triggering an unplanned full pipeline run |
| Privacy | Job descriptions sent to the LLM may contain recruiter contact details (email, phone); no redaction was in place |
| Legal/ToS | Collection via third-party scraping actors may conflict with LinkedIn and Indeed terms of service |

A full risk register is in [RISK_REGISTER.md](RISK_REGISTER.md).

---

## Controls Implemented

The following controls were applied in this public version:

**Classifier reliability**
- Temperature reduced from 0.7 to 0 for deterministic output on the same input.
- Output schema validated with Pydantic enums derived from the taxonomy files; responses that do not match are retried once, then marked `needs_review`.
- `CONFIDENCE_THRESHOLD` is now applied: vacancies below the threshold are stored with `ai_level = needs_review` and excluded from aggregate statistics by default.
- Prompt restructured to separate system instructions from user-supplied vacancy data, reducing prompt injection surface.

**Cost and scheduling**
- `RUN_BUDGET_USD` and `MAX_LLM_CALLS_PER_RUN` added to `Config`; the pipeline counts tokens from `response.usage` and aborts cleanly when either limit is reached.
- `cron_guard.sh` enforces a minimum 4-day interval between runs by writing a lock file.
- Operator policy: AI agents must receive explicit human approval before modifying production state (lock files, cron schedules, database schema, API keys).

**Credential hygiene**
- All real credentials and infrastructure identifiers removed from this repository; replaced with `<PLACEHOLDER>` values.
- `.env.example` updated with safe placeholder keys.
- Pre-commit secret scanning recommended (see [SECURITY.md](SECURITY.md)).

**Monitoring**
- `AlertSystem` is now invoked at the end of each pipeline run to check classification rate, error rate, and cost thresholds.
- `DriftDetector` runs weekly to flag distribution shifts in role family labels.

---

## The Automation Incident

During development, an AI coding assistant was asked to "allow the cron to run tonight." The assistant deleted the cron guard lock file — which was the correct mechanical action — without recognizing that the guard existed to enforce a 4-day minimum interval, not just to block "tonight." This triggered a full, unplanned pipeline run that consumed approximately $30 in LLM API credits.

**Root cause:** The agent had write access to production state files and lacked the context to distinguish "run once now" from "run on the normal schedule." The operator instruction was ambiguous.

**What is now in place:** An operator policy requiring explicit human confirmation before any agent modifies production state files. The budget cap in code means that even an accidental run is bounded in cost. Technical enforcement of agent file permissions remains an open item.

---

## Verified Remediations (This Repository)

| Item | Verification |
|------|-------------|
| Temperature = 0 | `classification/openrouter_classifier.py`, `_call_openrouter` |
| Pydantic schema validation | `classification/openrouter_classifier.py`, `ClassificationResult` model |
| Confidence threshold applied | `pipeline/main.py`, post-classification filter |
| Budget controls | `pipeline/config.py` (`RUN_BUDGET_USD`, `MAX_LLM_CALLS_PER_RUN`), `pipeline/main.py` |
| Response model saved | `classification/openrouter_classifier.py`, `response["model"]` stored |
| AlertSystem wired | `pipeline/main.py`, `_run_post_pipeline_checks()` |
| No credentials in repo | Secret scan: 0 findings (see QA results in `docs/`) |

---

## V2 Controls (Added in This Release)

The following controls were added in V2 to close gaps identified during the initial review:

**Classifier Evaluation (Prioridad 1)**

| Control | Risk | Implementation | Evidence | Test | Result | Residual Limitation |
|---------|------|----------------|----------|------|--------|---------------------|
| Gold set (45 synthetic vacancies) | No ground truth for classifier evaluation | `data/gold_set/vacancies_gold.json` with rule-based reference labels | 8 case types covered; 9 ambiguous cases marked | `tests/test_evaluation.py` (22 tests) | PASS — all 22 tests pass | Labels are rule-based, not human-annotated |
| Evaluation module with per-class metrics | Accuracy unknown; no macro-F1 tracked | `evaluation/classifier_eval.py` — computes macro-F1, per-class P/R/F1, invalid rate | Rule-based baseline: role_family F1=0.308, seniority F1=0.758, ai_level F1=0.314 | `test_perfect_predictor_yields_f1_one`, `test_rule_based_baseline_metrics` | PASS | Real LLM evaluation requires live API; not run in demo |
| Mock/live LLM distinction | Demo results could be confused with real LLM results | `is_live_llm` flag in `EvaluationReport`; disclaimer in every report | Report `note` field asserts rule-based baseline; `is_live_llm=False` in all tests | `test_report_note_disclaims_ground_truth_validation` | PASS | — |

**Strict Taxonomy Validation (Prioridad 2)**

| Control | Risk | Implementation | Evidence | Test | Result | Residual Limitation |
|---------|------|----------------|----------|------|--------|---------------------|
| Reject invalid taxonomy values (no silent coercion) | Invalid labels stored without error | `validation/taxonomy_validator.py` — errors = reject; warnings = accept with note | `normalized=None` on failure; `is_valid=False` with error list | `tests/test_taxonomy_validator.py` (35+ tests) | PASS | ai_level string labels (e.g. "medium") are coerced with a warning |
| Structured error types | Validation failures not distinguishable | `ValidationResult(is_valid, errors, warnings, normalized)` | Each error is a distinct message string | `test_bool_ai_level_rejected`, `test_invalid_role_family_not_converted` | PASS | — |
| None-response handling | None (API failure) causes AttributeError | `validate_batch()` checks None explicitly | `ValidationResult(is_valid=False, errors=["No classification returned…"])` | `test_none_classification_handled_gracefully` | PASS | — |

**Budget and Cron Controls (Prioridad 3)**

| Control | Risk | Implementation | Evidence | Test | Result | Residual Limitation |
|---------|------|----------------|----------|------|--------|---------------------|
| Budget abort (RUN_BUDGET_USD=5.0) | Uncapped spend | `BudgetGuard.check_before_call()` raises RuntimeError when estimated cost ≥ budget | Config reads from env; guard called before every LLM call | `tests/test_budget_and_cron.py` — budget exhaustion tests | PASS | Cost estimate uses approximate token rate; actual cost may vary |
| Call limit abort (MAX_LLM_CALLS_PER_RUN=500) | Unbounded runs | `BudgetGuard.check_before_call()` raises RuntimeError when calls ≥ limit | Same guard | call limit tests | PASS | — |
| Cron lock tested without touching production path | Tests could accidentally delete /var/run/observatory_cron.lock | `CronLockSimulator` uses `tmp_path`; `test_production_lock_path_is_not_touched` asserts isolation | Test assertions confirm simulator path ≠ production path | `test_production_lock_path_is_not_touched` | PASS | Production lock path enforced by policy, not filesystem permissions |
| Retry and provider error handling | Uncaught exceptions crash the pipeline | Classifier uses `tenacity`; `RetryError` caught in tests | `pytest.raises((httpx.ConnectError, httpx.HTTPError, RetryError))` | API error tests | PASS | — |

**Traceability and Provenance (Prioridad 4)**

| Control | Risk | Implementation | Evidence | Test | Result | Residual Limitation |
|---------|------|----------------|----------|------|--------|---------------------|
| Per-classification provenance | Label unattributable to run/model/prompt | `classification/provenance.py` — RunContext (run_id UUID, prompt SHA-256, taxonomy version), ProvenanceTracker | `provenance` dict attached to every classification | `tests/test_provenance.py` (25+ tests) | PASS | Historical labels (pre-V2) have no provenance |
| validation_status enum enforced | Unknown string values could be stored | `ProvenanceTracker.build()` raises ValueError for invalid statuses | Allowed: valid, invalid_taxonomy, invalid_json, api_error | `test_provenance_invalid_status_raises` | PASS | — |
| Served model vs. requested model tracked | Alias routing means served model may differ | `served_model` field in provenance dict | Tests assert `requested_model ≠ served_model` case | `test_provenance_served_model_can_differ_from_requested` | PASS | — |

**Fully Synthetic Demo (Prioridad 6)**

| Control | Risk | Implementation | Evidence | Test | Result | Residual Limitation |
|---------|------|----------------|----------|------|--------|---------------------|
| Scraper stubs raise NotImplementedError | Test suite could inadvertently call production scrapers | `pipeline/extractor.py` and `pipeline/loader.py` stub methods | `ALO-LEGAL-01` comment; `NotImplementedError` on call | Existing governance tests | PASS | Requires operator discipline not to swap stubs back in |
| No real credentials in repo | Credential exposure | Scan: 0 secrets found across all new files | `gitleaks`/`truffleHog`-compatible scan passed | Manual + automated scan | PASS | — |

---

## Limitations

- **No human gold set exists.** The 45 vacancies in `data/gold_set/` use rule-based reference labels. The 5,610 labels collected to date have not been validated against human annotations. Classification accuracy against real-world job postings is unknown.
- **Rule-based baseline ≠ LLM evaluation.** The metrics in `docs/MODEL_EVALUATION.md` compare a keyword heuristic against reference labels, not the LLM classifier against ground truth.
- **LLM-reported confidence is not calibrated.** The model's self-reported confidence score does not correspond to a measured precision rate.
- **Data collection legality is unresolved.** The scraping method via third-party Apify actors has not received legal review against LinkedIn and Indeed terms of service.
- **VPS hardening is incomplete.** SSH root login by password remains active on the production server. This requires operator action.
- **PII redaction is not implemented.** Recruiter contact details in job descriptions may be sent to the LLM and stored.

---

## Lessons Learned

1. **Define what "done" means for AI outputs before collecting data.** Running 5,610 classifications without a validation plan makes the labels harder to publish credibly later.
2. **Separate operational documentation from the repository.** API keys, server IPs, and deployment procedures do not belong in version-controlled markdown files.
3. **Agents need bounded permissions.** An agent that can write to any file on a server can inadvertently modify production state. Minimum-privilege principles apply to AI agents as much as to human operators.
4. **Budget caps belong in code, not just in provider dashboards.** Provider-level caps are a last resort; the code should enforce them first.
5. **Configuration drift between documentation and code is costly.** The documentation claimed Claude Haiku was the model in use; the code defaulted to GPT-3.5-turbo. Auditing the discrepancy consumed time and created uncertainty about historical label provenance.

---

## Relevance to AI Governance

This project is a small-scale example of the governance challenges the NIST AI RMF identifies for AI systems in production:

- **GOVERN 1.1** (Policies and processes): The lack of a formal operator policy for agent actions allowed an accidental production modification.
- **MEASURE 2.5** (AI system performance): Without a gold set, measurement of classification accuracy was not possible.
- **MANAGE 2.4** (Incidents and near-misses): The cron incident was documented and remediated, but the underlying root cause (unrestricted agent file access) remains partially open.
- **NIST AI 600-1, GV-1.1** (Accountability for GenAI outputs): The LLM-generated labels are the primary research output; accountability for their reliability requires human validation that has not yet been done.

The purpose of surfacing these findings is to demonstrate honest assessment and iterative improvement, not to claim that the system is fully governed.
