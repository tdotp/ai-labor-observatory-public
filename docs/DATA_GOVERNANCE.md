# Data Governance

## Data Sources

| Source | Access method | Geographic scope |
|--------|--------------|-----------------|
| LinkedIn Jobs | Third-party Apify actor | 10 LatAm countries |
| Indeed | Third-party Apify actor | 5 LatAm countries (CO, MX, BR, AR, CL) |

---

## Collection Method

Data is collected via Apify actors that scrape public-facing job listing pages. The pipeline does not use any official LinkedIn or Indeed API. Each scraping actor is a third-party service that handles the HTTP requests and page parsing; the observatory receives structured JSON output.

**Important:** The legal status of this collection method has not been formally assessed against LinkedIn's and Indeed's terms of service. See [LIMITATIONS.md](LIMITATIONS.md) and [RISK_REGISTER.md](RISK_REGISTER.md) (R-07).

---

## What Data Is Collected

For each job posting:

| Field | Description |
|-------|-------------|
| `raw_title` | Job title as posted |
| `raw_description` | Job description text (truncated to 800 chars before LLM) |
| `job_url` | URL of the original posting |
| `company_name` | Company name as listed |
| `country` | Country of the posting |
| `source` | `linkedin_jobs` or `indeed` |
| `posted_date` | Date the posting was published (when available) |

The collection target is **organizational data** (what roles companies are hiring for), not personal data about individuals.

---

## What May Be Inadvertently Collected

Job descriptions sometimes include:

- Recruiter email addresses or phone numbers
- Recruiter LinkedIn profile URLs
- Internal HR contact names

These are incidentally present in the `raw_description` field. **No PII redaction is currently implemented.** This data is:
1. Stored in the Supabase database (operator's instance)
2. Sent to the LLM via OpenRouter for classification
3. Sent to LLM provider(s) downstream of OpenRouter

This is an open risk (R-06 in [RISK_REGISTER.md](RISK_REGISTER.md)). Planned remediation: regex-based redaction of email patterns, phone numbers, and LinkedIn profile URLs in `pipeline/cleaner.py` before the data leaves the cleaning stage.

---

## Storage

Production data is stored in a Supabase PostgreSQL instance (EU-Ireland region). The database schema includes:

- `vacantes`: one row per unique job posting
- `job_skills`: extracted skill mentions linked to vacancies

Row-level security (RLS) is configured to prevent unauthorized reads and writes. `UPDATE` operations require a service-role key; the anon key is insufficient.

**This repository does not contain any scraped or real vacancy data.** The `data/` directory contains only taxonomy reference files. The `data/synthetic/` directory contains synthetic example data for running pipeline tests locally.

---

## Data Published in This Repository

**What is included:**
- `data/taxonomies/` — role family, skill, and search query taxonomies (created by the author, freely publishable)
- `data/synthetic/` — 50 fictional vacancy records for local testing (no real company names, no real job postings)
- `data/gold_set/vacancies_gold.json` — 45 synthetic labeled vacancies for classifier evaluation, with rule-based reference labels (created by the author; no real vacancy data)
- `prompts/` — LLM classification and skill extraction prompts (created by the author)
- Aggregate statistics cited in the README are sourced from the author's private Supabase instance

**What is NOT included:**
- Raw scraped vacancy data
- Any data from the Supabase database
- Recruiter contact details
- Personal data of any kind

---

## Retention Policy

A formal data retention policy has not been defined. In practice:
- Vacancies remain in the database indefinitely
- Log files on the VPS are rotated (30-day retention documented in operational notes)
- No automated deletion or anonymization is in place

Defining and implementing a retention policy is an open item.

---

## Licensing

- Code: see [LICENSE](../LICENSE) in the repository root
- Taxonomy files (`data/taxonomies/`): created by the author; same license as code
- Synthetic data (`data/synthetic/`): created by the author; same license as code
- Scraped vacancy data: **not licensed for redistribution** — not included in this repository; rights belong to the original platform and posting employers

---

## Legal Basis for Collection

The legal basis for collecting job posting data via web scraping has not been formally assessed. Relevant frameworks that may apply depending on the researcher's jurisdiction and the data subject's location include:

- Colombia: Ley 1581 de 2012 (Habeas Data)
- Brazil: Lei Geral de Proteção de Dados (LGPD)
- Mexico: Ley Federal de Protección de Datos Personales en Posesión de Particulares
- EU (data stored in Ireland): GDPR

No compliance determination is made here. Researchers replicating this methodology should conduct their own legal review.
