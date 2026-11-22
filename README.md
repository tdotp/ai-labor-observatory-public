# AI Labor Observatory

An automated pipeline that monitors how AI-related skills appear in job postings for creative, marketing, and communications roles across Latin America. Built as an applied AI research project exploring LLM-based data classification, pipeline governance, and responsible AI deployment.

> **Research status:** Exploratory. Labels are LLM-generated and have not been validated against a human-annotated ground truth. See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) and [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) before drawing conclusions from the data.

---

## What problem does this study?

Traditional labor market research takes months to produce. This observatory tracks in near-real-time whether job postings in LatAm creative and marketing roles are signaling demand for AI skills — and at what level.

**Research questions:**
- Are AI tools appearing as requirements in creative/marketing/comms job postings in LatAm?
- Which role families (creative design, content, social media, marketing, PR, strategy) show the highest AI signal?
- Is the signal growing over time?

**What it cannot answer:**
- Whether AI is actually *used* in those jobs (postings are aspirational)
- Net job creation or destruction attributable to AI
- Causation between AI skill demand and AI adoption at the company level

See [docs/METHODOLOGY.md](docs/METHODOLOGY.md) for full scope and limitations.

---

## Data sources

> **Public demo:** this repository ships with a **synthetic dataset only** (`data/synthetic/`). The scraping connectors for LinkedIn and Indeed are **not included** in this public release. See [docs/DATA_GOVERNANCE.md](docs/DATA_GOVERNANCE.md).

The full research pipeline collected vacancies from two sources:

| Source | Method (reference only) | Coverage |
|---|---|---|
| LinkedIn Jobs | Apify actor (`curious_coder/linkedin-jobs-scraper`) | 10 LatAm countries, last 30 days |
| Indeed | Apify actor (`borderline/indeed-scraper`) | 5 LatAm countries (CO, MX, BR, AR, CL), last 7 days |

The extraction layer (`pipeline/extractor.py`) and the database connector (`pipeline/loader.py`) are present as **architecture stubs** — they document the interface but raise `NotImplementedError` when called. This is intentional:

- Scraping LinkedIn and Indeed via third-party tools may violate those platforms' Terms of Service.
- Scraped vacancy content is third-party data whose redistribution is not authorised by the platforms.
- The public demo is designed to run entirely on synthetic data without any external connections.

If you want to run the full pipeline against live data, you need your own Apify account, your own legal assessment, and your own implementation of the scraping layer.

---

## How the pipeline works

```
cron (every 4 days)
    └─► pipeline/main.py
            ├─ Phase 1: Extract — Apify triggers LinkedIn + Indeed runs
            ├─ Phase 2: Clean — normalize, deduplicate, filter out-of-domain
            ├─ Phase 3: Load — insert into Supabase (Postgres)
            ├─ Phase 4: Classify — OpenRouter LLM labels each vacancy
            ├─ Phase 5: Skills — extract skill mentions per vacancy
            └─ Phase 6: Monitor — alert_system checks thresholds
```

Deduplication uses a `UNIQUE` constraint on `(raw_title, company_name, country, source)`. Each vacancy is classified independently; no cross-vacancy context is used.

---

## Role of AI models

The LLM performs two tasks per vacancy:

1. **Classification** — assigns `role_family`, `seniority`, and `ai_level` from a fixed taxonomy
2. **Skills extraction** — identifies named AI tools and skills mentioned in the posting

**Model:** `openai/gpt-3.5-turbo` via OpenRouter (configurable; see `.env.example`)  
**Temperature:** `0` (deterministic — classification is a lookup, not creative writing)  
**Validation:** Pydantic schema enforces enum constraints; results outside the taxonomy are retried or marked `needs_review`  
**Confidence:** LLM self-reports a confidence score. Applied as a threshold filter. **Not calibrated against ground truth.**

The LLM-reported confidence metric reflects the model's internal probability estimates, not an empirically validated accuracy rate. Labels should be treated as "LLM-generated annotations" pending human validation. See [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md).

---

## Taxonomy

**Role families:** `creative_design` · `content_copywriting` · `social_media` · `marketing_growth` · `pr_communications` · `strategy_accounts` · `other`

**Seniority:** `junior` · `mid` · `senior` · `director`

**AI level:** `none` · `low` · `medium` · `high`

Taxonomy definitions: [`data/taxonomies/role_families.json`](data/taxonomies/role_families.json)

---

## Running a demo (local, no credentials required)

```bash
# 1. Clone the repo
git clone <repo-url>
cd ai-labor-observatory

# 2. Install dependencies
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Run classification on synthetic data (no API calls)
python - <<'EOF'
import json
from classification.openrouter_classifier import OpenRouterClassifier

# Load synthetic vacancies
with open("data/synthetic/vacancies_synthetic.json") as f:
    vacancies = json.load(f)

print(f"Loaded {len(vacancies)} synthetic vacancies")
for v in vacancies[:3]:
    print(f"  [{v['classification']['ai_level']:6s}] {v['raw_title']} @ {v['company_name']} ({v['country']})")
EOF
```

To run the full pipeline against a live Supabase instance:
1. Copy `.env.example` to `.env` and fill in your credentials
2. Run `python pipeline/main.py --test --classify-only`

---

## Architecture

```
ai-labor-observatory/
├── classification/          # LLM classification (OpenRouter)
│   ├── openrouter_classifier.py   # vacancy → role_family/seniority/ai_level
│   └── skills_extractor.py        # vacancy → named AI skills
├── pipeline/                # Orchestration
│   ├── main.py              # Pipeline entry point
│   ├── config.py            # Configuration + budget controls
│   ├── extractor.py         # Apify integration
│   ├── cleaner.py           # Normalization, deduplication filter
│   └── loader.py            # Supabase read/write
├── monitoring/              # Alerting and drift detection
│   ├── alert_system.py      # Threshold checks (now wired to pipeline)
│   └── weekly_report.py     # Summary generation
├── validation/              # Data quality
│   ├── batch_validator.py   # Batch-level checks
│   ├── taxonomy_validator.py  # Strict taxonomy enum validation (V2)
│   └── drift_detector.py    # Distribution change detection
├── evaluation/              # Classifier evaluation (V2)
│   └── classifier_eval.py   # Gold set metrics: macro-F1, per-class P/R/F1
├── analysis/                # Insight generation
├── data/
│   ├── taxonomies/          # Classification schema (role families, skills)
│   ├── synthetic/           # Fictional vacancies for local demos
│   └── gold_set/            # 45 synthetic labeled vacancies for evaluation (V2)
├── prompts/                 # LLM prompt templates (versioned)
├── migrations/              # Database schema migrations
├── scripts/                 # Operational scripts (cron guard, retry, validator)
└── tests/                   # Unit tests with mocks
```

---

## Governance & AI safety

| Document | Topic |
|---|---|
| [docs/AI_GOVERNANCE_CASE_STUDY.md](docs/AI_GOVERNANCE_CASE_STUDY.md) | Risks, controls, automation incident, lessons learned |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | Data sources, collection, classification, biases |
| [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) | Validation approach, known gaps, accuracy limitations |
| [docs/AGENT_GOVERNANCE.md](docs/AGENT_GOVERNANCE.md) | Automation controls, incident post-mortem, cost governance |
| [docs/RISK_REGISTER.md](docs/RISK_REGISTER.md) | Full risk register with current residual status |
| [docs/DATA_GOVERNANCE.md](docs/DATA_GOVERNANCE.md) | Data provenance, privacy, licensing |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | Honest statement of all known limitations |
| [docs/SECURITY.md](docs/SECURITY.md) | Secret management, responsible disclosure |

This project uses [NIST AI RMF 1.0](https://www.nist.gov/system/files/documents/2023/01/26/AI%20RMF%201.0.pdf) and the [NIST Generative AI Profile](https://airc.nist.gov/Docs/1) as reference vocabulary for risk identification and governance documentation. No compliance certification is claimed or implied.

---

## Running tests

```bash
pip install pytest pytest-asyncio httpx tenacity
pytest tests/ -v
```

Tests use mocks — no API credentials required. The suite currently has **295 tests, 0 failures**.

To run classifier evaluation against the gold set (no live API required):

```bash
python - <<'EOF'
from evaluation.classifier_eval import ClassifierEvaluator, mock_rule_based_predictions

predictions = mock_rule_based_predictions()
report = ClassifierEvaluator.evaluate(predictions=predictions)
import json; print(json.dumps(report.to_dict(), indent=2))
EOF
```

Expected output includes rule-based baseline metrics (role_family macro-F1 ≈ 0.308, seniority ≈ 0.758, ai_level ≈ 0.314). See [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) for interpretation.

---

## License

[MIT](LICENSE)

## Contributing

This is a research project. Issues and discussions welcome. See [docs/SECURITY.md](docs/SECURITY.md) for responsible disclosure of security concerns.
