# Agent Governance

## Automated Components

The observatory runs two categories of automation:

| Component | Type | Trigger | External calls |
|-----------|------|---------|----------------|
| `cron_guard.sh` + `pipeline/main.py` | Scheduled pipeline | System cron, every 4 days | Apify API (scraping), OpenRouter API (classification), Supabase (storage) |
| LLM classification calls | Per-vacancy API calls within the pipeline | Called by `main.py` | OpenRouter → LLM provider |

The LLM is used only for classification — it has no tools, no memory, and no ability to execute code or make external calls beyond producing a JSON response. It is not an agent in the autonomous sense; it is a stateless function called in a loop.

The pipeline orchestrator (`main.py`) is automated but not agentic: it executes a fixed sequence of steps. The governance concern is not the LLM's autonomy but the **unattended execution** of a script with real API and database access.

---

## The Cron Incident

**What happened:** An AI coding assistant was asked to "allow the cron to run tonight." The assistant deleted the cron guard lock file. This was mechanically correct — the lock file is what prevents runs — but the assistant did not recognize that the guard existed to enforce a minimum 4-day interval between runs, not merely to block "tonight."

**Effect:** An unplanned full pipeline run executed. The run consumed approximately $30 in LLM API credits.

**Root cause:** The agent had write access to production state files. The operator instruction was ambiguous. The agent did not ask for clarification and did not check whether deleting the file had side effects beyond the immediate request.

**What this illustrates (NIST AI RMF GOVERN 1.1):** Agents with broad file system access and ambiguous instructions can modify production state in ways the operator did not intend. This is a governance failure, not a technical failure — the agent behaved correctly given its understanding of the task.

---

## Controls Now in Place

**Technical controls:**

| Control | Location | Effect |
|---------|----------|--------|
| `cron_guard.sh` lock file | `scripts/cron_guard.sh` | Enforces minimum 4-day run interval |
| `RUN_BUDGET_USD` | `pipeline/config.py`, `pipeline/main.py` | Pipeline aborts if estimated cost exceeds the configured limit |
| `MAX_LLM_CALLS_PER_RUN` | `pipeline/config.py`, `pipeline/main.py` | Pipeline aborts after N LLM calls regardless of remaining vacancies |
| Token usage tracking | `pipeline/main.py` | Accumulates `response.usage` tokens; logged in run summary |

**Operator policy:**

> Any action that modifies production state — lock files, cron schedules, database schema, API key configuration, or `.env` files — requires explicit written confirmation from the human operator before execution by an AI agent. Agents must default to dry-run mode and present a plan before modifying state.

This policy is enforced by procedure, not by technical controls. Technical enforcement (e.g., restricted file permissions, a separate read-only user for the pipeline process) is listed as an open item.

---

## V2 Verified Controls (Test Suite)

The following controls are verified by the test suite in `tests/test_budget_and_cron.py`:

| Test | Scenario | Result |
|------|----------|--------|
| `test_budget_abort_on_cost_exceeded` | Estimated cost ≥ RUN_BUDGET_USD → RuntimeError | PASS |
| `test_call_limit_abort_on_max_calls` | LLM calls ≥ MAX_LLM_CALLS_PER_RUN → RuntimeError | PASS |
| `test_budget_not_exhausted_at_limit` | At exactly the limit, no abort | PASS |
| `test_cron_lock_acquired_before_run` | `CronLockSimulator.acquire()` returns True | PASS |
| `test_cron_lock_blocks_parallel_run` | Second acquire returns False (already locked) | PASS |
| `test_cron_minimum_interval_enforced` | Run rejected if < 4-day interval | PASS |
| `test_stale_lock_detected` | Lock older than 7 days → `is_stale()` True | PASS |
| `test_production_lock_path_is_not_touched` | Simulator path ≠ `/var/run/observatory_cron.lock` | PASS |
| API error retry tests | ConnectError, JSONDecodeError → RetryError handled | PASS |

**Note on the production lock path:** `/var/run/observatory_cron.lock` is **never touched by the test suite**. `CronLockSimulator` uses `pytest`'s `tmp_path` fixture exclusively. This is enforced by a dedicated test.

---

## Outstanding Risks

| Risk | Status |
|------|--------|
| No technical enforcement of agent file permissions | **OPEN** — requires VPS user/permission restructuring |
| Agent with broad codebase access could modify cron_guard.sh itself | **OPEN** — policy control only |
| Budget cap set to 0 (unlimited) in .env overrides in-code limit | **MITIGATED** — code checks for valid positive value; 0 or negative is rejected |

---

## Cost Governance

Each pipeline run logs estimated cost in its summary output. Cost is calculated from `response.usage.total_tokens` × model rate. The pipeline uses `openai/gpt-3.5-turbo` by default (~$0.001/1k tokens); a full run of 500 vacancies costs approximately $0.10–$0.50.

Configure `RUN_BUDGET_USD` in `.env` (default: `2.00`). The pipeline will abort and log a budget-exceeded error if this limit is reached mid-run. Remaining unclassified vacancies are picked up on the next run via `scripts/retry_unclassified.py`.

**Provider-level cap:** Set a monthly spend limit on your OpenRouter API key. This is a last-resort backstop; the in-code limit should be hit first.

---

## Emergency Stop

To halt all scheduled pipeline activity immediately:

```bash
# 1. Disable the cron job
crontab -r

# 2. If a run is in progress, kill it
pkill -f "pipeline/main.py"

# 3. Revoke the OpenRouter API key at openrouter.ai/settings/keys
#    (required if the key may have been compromised)
```

Restarting requires reconfiguring cron via `scripts/setup_cron.sh` and optionally re-enabling the monthly spend cap on the OpenRouter key.
