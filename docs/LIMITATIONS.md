# Limitations

This document lists the known limitations of the AI Labor Observatory. It is intended to prevent misinterpretation of results and to give researchers a realistic picture of what the data can and cannot support.

---

## Coverage

**Geographic scope:** Latin America only. The observatory covers 10 countries via LinkedIn and 5 via Indeed. It does not cover North America, Europe, Asia, or Africa.

**Role scope:** Creative, marketing, communications, and design roles only. The search strategy uses 8 keyword groups built around specific role titles. Roles that exist in the target domain but are described with titles not in the keyword list will be missed entirely. Coverage of "director creativo"-type Spanish-language titles is limited to one keyword group and may under-capture the full range of Spanish-language role naming conventions.

**Seniority scope:** The classification captures junior through director level. C-suite and VP-level roles that use non-standard titles may be misclassified or excluded by domain filtering.

---

## Source Bias

**LinkedIn** skews toward formally employed, white-collar professionals with active LinkedIn profiles and toward companies that actively recruit on the platform. It systematically under-represents informal employment, small and micro-enterprises, and roles in sectors that do not use LinkedIn for recruitment.

**Indeed** skews toward active job-seekers and toward companies that pay for Indeed listings. Coverage varies significantly by country.

**Both sources exclude the informal economy**, which represents a substantial share of employment in many LatAm markets.

**Both sources over-represent roles at companies that actively post online.** Small agencies and freelance-heavy sectors may be systematically under-counted.

---

## Classification Reliability

LLM classification is the core output of the observatory. These limitations apply to every label in the dataset:

- **No human gold set exists.** The 5,610 labels collected to date have not been validated against human annotations. Classification accuracy, precision, and recall are unknown.
- **Temperature 0 does not guarantee correctness.** It guarantees that the same input produces the same output for a given model version. The output may still be wrong.
- **LLM-reported confidence is not calibrated.** A reported confidence of 0.85 does not mean the label is correct 85% of the time. Use confidence as an ordinal signal, not a probability.
- **Model version drift.** OpenRouter may route requests to different model versions over time. Labels generated before and after a silent model update are not guaranteed to be consistent.
- **Borderline roles.** Roles that span multiple families (e.g., a content strategist with strong UX responsibilities) will be assigned to a single family. The choice is not always obvious even to human raters.

---

## Temporal

Each scraping run collects postings from the last 30 days (LinkedIn) or 7 days (Indeed). The cron schedule runs every 4 days. This means:

- There is a lag between a posting going live and being collected.
- Postings that expire within 4 days may be missed entirely.
- The dataset reflects a rolling snapshot, not a complete census.

Month-over-month trend analysis is only valid if collection completeness was consistent across the comparison periods. Infrastructure outages, Apify actor failures, or LinkedIn/Indeed anti-scraping measures can create gaps that are not explicitly flagged in the data.

---

## Causation and Inference

**Postings ≠ hires.** A job posting does not confirm that the role was filled, that a hire occurred, or that the described skills were actually used.

**Postings ≠ AI adoption.** Frequency of job postings mentioning AI tools does not equal the rate of organizational AI adoption, the number of workers affected, or the economic impact of AI on employment.

**Correlation ≠ causation.** Even if a correlation between AI-mentioning postings and other variables is observed, the observatory data cannot establish a causal relationship.

**Trend ≠ employment change.** An increase in postings for a role family does not necessarily mean net job creation; it may reflect turnover, role redefinition, or posting strategy changes.

---

## Language

Search queries are in English and Spanish. Portuguese coverage is limited: Brazil appears only in the Indeed source, and the keyword groups are not translated to Portuguese. This may systematically under-count Brazilian postings relative to Brazil's actual share of LatAm job activity.

---

## Data Published

No raw scraped data is published in this repository. Results cited in the README are drawn from the author's private Supabase instance. They are illustrative of the system's output, not a statistically representative sample of LatAm job postings. External researchers cannot independently verify or replicate the cited statistics without running the pipeline with their own API credentials and conducting their own collection.

---

## Infrastructure

The pipeline runs on a single virtual private server with no high-availability configuration. VPS outages, Apify downtime, or OpenRouter API outages will interrupt collection and classification without failover. Data collected during an outage window is not recoverable retroactively.
