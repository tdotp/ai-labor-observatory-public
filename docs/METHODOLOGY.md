# Methodology

## Research Question

How is demand for AI-related skills evolving in creative, marketing, and communications job postings across Latin America? The observatory tracks job titles, role families, seniority levels, and the degree to which postings require or mention AI skills, over time.

---

## Data Sources

| Source | Method | Coverage |
|--------|--------|----------|
| LinkedIn Jobs | Apify actor (`curious_coder/linkedin-jobs-scraper`) | 10 LatAm countries, last 30 days |
| Indeed | Apify actor (`borderline/indeed-scraper`) | 5 LatAm countries (CO, MX, BR, AR, CL), last 7 days |

**Countries (LinkedIn):** Colombia, Mexico, Argentina, Chile, Peru, Brazil, Uruguay, Panama, Costa Rica, Ecuador.

**Countries (Indeed):** Colombia, Mexico, Brazil, Argentina, Chile. Indeed's actor is priced per run per country, so coverage is limited to the top 5 markets.

---

## Search Strategy

Eight keyword groups covering the target role families are used for LinkedIn, with one Spanish-language group to capture postings that do not use English titles:

| Group | Examples |
|-------|---------|
| G1 — Creative/Design Core | creative director, graphic designer, ui designer, art director |
| G2 — Design Specialists | brand designer, motion designer, product designer, web designer |
| G3 — Content & Copywriting | copywriter, content strategist, content creator, video editor |
| G4 — Social Media | social media manager, community manager, influencer marketing |
| G5 — Marketing & Growth | growth marketer, marketing manager, performance marketer |
| G6 — PR & Communications | pr manager, communications manager, director of communications |
| G7 — Strategy & Accounts | brand strategist, account manager, account director |
| G8 — Spanish | director creativo, diseñador gráfico, gerente de marketing |

This produces up to 80 LinkedIn search URLs per run (10 countries × 8 groups). The LinkedIn actor is charged per run, not per URL, so multi-country coverage is cost-neutral.

---

## Collection Schedule

A cron job runs every 4 days. A guard script (`cron_guard.sh`) enforces a minimum 4-day interval via a lock file, preventing accidental double runs. Each LinkedIn run targets postings from the last 30 days (`f_TPR=r2592000`); each Indeed run targets the last 7 days with a 4-day buffer.

---

## Deduplication

A UNIQUE constraint on `(raw_title, company_name, country, source)` prevents duplicate rows. The constraint is enforced at the database level; the pipeline also checks for existing records before insertion (upsert semantics).

---

## Cleaning Pipeline

Before storage and classification, each record passes through `DataCleaner`:

1. **Required fields check:** records missing `raw_title`, `raw_description`, `job_url`, `company_name`, or `country` are discarded.
2. **Out-of-domain filtering:** titles matching a blocklist of roles clearly outside the target domain (software engineer, nurse, driver, etc.) are dropped to avoid wasting classification tokens.
3. **Title normalization:** lowercasing, whitespace normalization.
4. **Description truncation:** descriptions are truncated to 800 characters before being sent to the LLM. The first 800 characters contain the role description; the remainder is typically benefits and application instructions, which carry little signal for classification.

---

## LLM Classification

Each cleaned vacancy is classified by a large language model via the OpenRouter API. The classification extracts:

- **role_family**: one of `creative_design`, `content_copywriting`, `social_media`, `marketing_growth`, `pr_communications`, `strategy_accounts`, `other`
- **seniority**: `junior`, `mid`, `senior`, `director`, `unknown`
- **ai_level**: `none`, `low`, `medium`, `high`
- **ai_tools_detected**: list of AI tools mentioned
- **confidence**: LLM self-reported confidence (0–1)

**Model:** `openai/gpt-3.5-turbo` via OpenRouter (default). The actual model served may differ from the alias; the pipeline saves `response["model"]` for provenance.

**Prompt:** Structured with system instructions separate from vacancy data. The prompt and taxonomy version are logged per classification run.

**Temperature:** 0 (deterministic output).

**Validation:** Output is validated against a Pydantic schema with enums for `role_family`, `seniority`, and `ai_level`. Invalid responses are retried once; persistent failures are stored as `needs_review`.

---

## Known Collection Biases

- **Platform bias:** LinkedIn skews toward white-collar, formally employed roles and toward users who actively maintain a profile. Indeed skews toward active job-seekers. Both systematically under-represent the informal economy, which is significant in LatAm.
- **Keyword bias:** Roles that exist but are described with titles not in the keyword groups will be missed entirely (false negatives in coverage, not in classification).
- **Country bias:** LinkedIn coverage is broader (10 countries) than Indeed (5 countries). Brazil appears only in Indeed due to LinkedIn's Portuguese-language gap in keyword matching.
- **Temporal sampling:** The 4-day cron window means postings may be collected multiple times if they remain active across runs. Deduplication mitigates but does not fully eliminate this.
- **Scraping reliability:** Apify actor coverage depends on LinkedIn/Indeed's anti-scraping measures and actor updates. Runs may return fewer results without a clear error signal.

---

## Classification Uncertainty

LLM classification is not deterministic even at temperature 0 across model version updates. The confidence score is LLM self-reported and has not been calibrated against human annotations. No human gold set exists for this dataset; therefore, classification accuracy is unknown.

Vacancies with `confidence < CONFIDENCE_THRESHOLD` (default 0.7) are stored with `ai_level = needs_review` and excluded from aggregate statistics by default.

---

## Limits of Inference

- **Postings ≠ hires.** A job posting does not confirm that the role was filled or that the skill was actually used in the role.
- **Postings ≠ AI adoption.** Frequency of AI-mentioning postings does not equal organizational AI adoption or employment-level impact.
- **Trends require continuity.** Month-over-month comparisons are only meaningful where collection completeness is consistent. Infrastructure outages or actor failures create gaps that distort trends.
- **No causation claims.** Correlations between AI skill demand and other variables do not establish causal relationships.
