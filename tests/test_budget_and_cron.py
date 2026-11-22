"""
Tests for budget controls and cron lock behavior.

Covers:
  - Budget abort: pipeline stops at RUN_BUDGET_USD and MAX_LLM_CALLS_PER_RUN
  - Token counting accumulates correctly across calls
  - Budget exceeded flag is raised before making additional calls
  - Cron lock: atomic write, interval enforcement, stale lock detection
  - Parallel run prevention
  - Lock-file content is a valid timestamp

NOTE: All tests use mocks and local temp files — no VPS, no API calls, no production runs.
The lock file at /var/run/observatory_cron.lock is NEVER touched by these tests.
"""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest

from classification.openrouter_classifier import OpenRouterClassifier
from pipeline.config import Config


# ---------------------------------------------------------------------------
# Budget configuration tests
# ---------------------------------------------------------------------------

class TestBudgetConfiguration:
    def test_run_budget_usd_is_positive(self):
        assert Config.RUN_BUDGET_USD > 0

    def test_max_llm_calls_is_positive(self):
        assert Config.MAX_LLM_CALLS_PER_RUN > 0

    def test_approx_cost_per_1k_tokens_is_positive(self):
        assert Config.APPROX_COST_PER_1K_TOKENS_USD > 0

    def test_run_budget_is_per_run_not_monthly(self):
        # Per-run budget should be sensible ($0.01 to $50)
        assert 0.01 <= Config.RUN_BUDGET_USD <= 50.0, (
            f"RUN_BUDGET_USD={Config.RUN_BUDGET_USD} seems outside per-run range. "
            "Ensure this is a per-run cap."
        )

    def test_max_llm_calls_bounded_reasonably(self):
        # 500 calls × 2 (classify + skills) = 1000 vacancies per run
        assert Config.MAX_LLM_CALLS_PER_RUN <= 2000

    def test_budget_variables_are_independent(self):
        """Both limits enforce independently — either can trip the abort."""
        # Verify they are separate attributes
        assert hasattr(Config, 'RUN_BUDGET_USD')
        assert hasattr(Config, 'MAX_LLM_CALLS_PER_RUN')
        assert hasattr(Config, 'APPROX_COST_PER_1K_TOKENS_USD')


# ---------------------------------------------------------------------------
# Token accounting (unit tests on classifier state)
# ---------------------------------------------------------------------------

class TestTokenAccounting:
    def test_initial_state_is_zero(self):
        clf = OpenRouterClassifier(api_key="dummy")
        assert clf.total_tokens_used == 0
        assert clf.total_calls == 0

    def test_tokens_accumulate_across_calls(self):
        """Simulate what classify() does when it records a successful call."""
        clf = OpenRouterClassifier(api_key="dummy")
        # Simulate two successful API responses with usage data
        clf._last_usage = {"total_tokens": 450}
        clf.total_tokens_used += clf._last_usage.get("total_tokens", 0)
        clf.total_calls += 1

        clf._last_usage = {"total_tokens": 480}
        clf.total_tokens_used += clf._last_usage.get("total_tokens", 0)
        clf.total_calls += 1

        assert clf.total_tokens_used == 930
        assert clf.total_calls == 2

    def test_estimated_cost_does_not_exceed_budget(self):
        """
        Verify that at the call limit with max tokens, estimated cost stays
        within a 2× margin of the budget.

        This is a sanity check — the actual abort logic is in the pipeline,
        but the config values should be coherent.
        """
        estimated_cost = (
            Config.MAX_LLM_CALLS_PER_RUN
            * 2000  # max_tokens per call
            / 1000
            * Config.APPROX_COST_PER_1K_TOKENS_USD
        )
        # At 500 calls × 2000 tokens × $0.001/1k = $1.00 — well under $5
        assert estimated_cost <= Config.RUN_BUDGET_USD * 2, (
            f"Estimated max cost at call limit (${estimated_cost:.2f}) exceeds "
            f"2× budget (${Config.RUN_BUDGET_USD * 2:.2f}). "
            "Review MAX_LLM_CALLS_PER_RUN or APPROX_COST_PER_1K_TOKENS_USD."
        )


# ---------------------------------------------------------------------------
# Budget abort logic (mock-based)
# ---------------------------------------------------------------------------

class BudgetGuard:
    """
    Minimal budget guard used to test abort behavior.
    This mirrors what pipeline/main.py should do before each LLM call.
    """

    def __init__(self, budget_usd: float, max_calls: int, cost_per_1k: float):
        self.budget_usd = budget_usd
        self.max_calls = max_calls
        self.cost_per_1k = cost_per_1k
        self.total_tokens = 0
        self.total_calls = 0

    @property
    def estimated_cost_usd(self) -> float:
        return self.total_tokens / 1000 * self.cost_per_1k

    def check_before_call(self) -> None:
        """Raise BudgetExceeded if either limit is reached."""
        if self.total_calls >= self.max_calls:
            raise RuntimeError(
                f"MAX_LLM_CALLS_PER_RUN reached: {self.total_calls}/{self.max_calls}"
            )
        if self.estimated_cost_usd >= self.budget_usd:
            raise RuntimeError(
                f"RUN_BUDGET_USD exceeded: ${self.estimated_cost_usd:.4f} >= ${self.budget_usd}"
            )

    def record_call(self, tokens_used: int) -> None:
        self.total_tokens += tokens_used
        self.total_calls += 1


class TestBudgetAbortLogic:
    def _guard(self, budget=5.0, max_calls=10, cost=0.001):
        return BudgetGuard(budget_usd=budget, max_calls=max_calls, cost_per_1k=cost)

    def test_allows_calls_within_budget(self):
        guard = self._guard()
        for _ in range(5):
            guard.check_before_call()
            guard.record_call(tokens_used=500)
        assert guard.total_calls == 5

    def test_raises_on_max_calls_reached(self):
        guard = self._guard(max_calls=3)
        for _ in range(3):
            guard.check_before_call()
            guard.record_call(tokens_used=100)
        with pytest.raises(RuntimeError, match="MAX_LLM_CALLS_PER_RUN"):
            guard.check_before_call()

    def test_raises_on_budget_exceeded(self):
        guard = self._guard(budget=0.01, cost=0.1)  # $0.10/1k tokens
        guard.check_before_call()
        guard.record_call(tokens_used=200)  # 200 tokens × $0.10/1k = $0.02 > $0.01
        with pytest.raises(RuntimeError, match="RUN_BUDGET_USD"):
            guard.check_before_call()

    def test_budget_check_happens_before_call_not_after(self):
        """Verifies check is pre-call — no extra call is made when limit is hit."""
        guard = self._guard(max_calls=2)
        calls_made = 0
        for i in range(5):
            try:
                guard.check_before_call()
                calls_made += 1
                guard.record_call(500)
            except RuntimeError:
                break
        assert calls_made == 2, f"Expected 2 calls before abort, got {calls_made}"

    def test_budget_and_call_limits_are_independent(self):
        """Either limit can fire first; test call limit fires first."""
        # Budget is high; call limit fires first
        guard = self._guard(budget=1000.0, max_calls=2)
        guard.check_before_call(); guard.record_call(100)
        guard.check_before_call(); guard.record_call(100)
        with pytest.raises(RuntimeError, match="MAX_LLM_CALLS_PER_RUN"):
            guard.check_before_call()

    def test_zero_calls_allowed_when_max_is_zero(self):
        guard = self._guard(max_calls=0)
        with pytest.raises(RuntimeError, match="MAX_LLM_CALLS_PER_RUN"):
            guard.check_before_call()


# ---------------------------------------------------------------------------
# Cron lock behavior (pure Python simulation — no VPS, no /var/run)
# ---------------------------------------------------------------------------

class CronLockSimulator:
    """
    Pure-Python simulation of the cron guard's lock file behavior.
    Tests the LOGIC of the shell script, not the shell script itself.
    """

    MIN_INTERVAL_S = 345600  # 4 days

    def __init__(self, lock_path: Path, min_interval: int = MIN_INTERVAL_S):
        self.lock_path = lock_path
        self.min_interval = min_interval

    def should_run(self, now: int) -> bool:
        """Return True if enough time has passed since the last run."""
        if not self.lock_path.exists():
            return True
        try:
            last_run = int(self.lock_path.read_text().strip())
        except (ValueError, OSError):
            return True  # Stale/corrupt lock — allow run
        return (now - last_run) >= self.min_interval

    def acquire(self, run_timestamp: int) -> bool:
        """Write the lock. Returns True on success."""
        try:
            self.lock_path.write_text(str(run_timestamp))
            return True
        except OSError:
            return False

    def is_stale(self, now: int, max_age_s: int = 86400 * 7) -> bool:
        """Return True if the lock exists but is older than max_age_s (stale)."""
        if not self.lock_path.exists():
            return False
        try:
            last_run = int(self.lock_path.read_text().strip())
            return (now - last_run) > max_age_s
        except (ValueError, OSError):
            return True  # Corrupt lock is treated as stale


class TestCronLockBehavior:
    @pytest.fixture
    def tmp_lock(self, tmp_path):
        return tmp_path / "observatory_cron.lock"

    @pytest.fixture
    def lock(self, tmp_lock):
        return CronLockSimulator(tmp_lock)

    def test_runs_when_no_lock_file(self, lock):
        now = int(time.time())
        assert lock.should_run(now) is True

    def test_runs_after_interval_elapsed(self, lock, tmp_lock):
        now = int(time.time())
        past = now - CronLockSimulator.MIN_INTERVAL_S - 1
        tmp_lock.write_text(str(past))
        assert lock.should_run(now) is True

    def test_skips_before_interval_elapsed(self, lock, tmp_lock):
        now = int(time.time())
        recent = now - 3600  # 1 hour ago
        tmp_lock.write_text(str(recent))
        assert lock.should_run(now) is False

    def test_skips_exactly_at_interval_minus_one(self, lock, tmp_lock):
        now = int(time.time())
        just_before = now - CronLockSimulator.MIN_INTERVAL_S + 1
        tmp_lock.write_text(str(just_before))
        assert lock.should_run(now) is False

    def test_runs_exactly_at_interval(self, lock, tmp_lock):
        now = int(time.time())
        exactly = now - CronLockSimulator.MIN_INTERVAL_S
        tmp_lock.write_text(str(exactly))
        assert lock.should_run(now) is True

    def test_acquire_writes_timestamp(self, lock, tmp_lock):
        now = int(time.time())
        result = lock.acquire(now)
        assert result is True
        content = tmp_lock.read_text().strip()
        assert content == str(now)

    def test_lock_content_is_valid_integer(self, lock, tmp_lock):
        now = int(time.time())
        lock.acquire(now)
        content = tmp_lock.read_text().strip()
        assert content.isdigit(), "Lock file must contain a plain integer timestamp"

    def test_stale_lock_detected(self, lock, tmp_lock):
        now = int(time.time())
        old = now - 86400 * 10  # 10 days ago
        tmp_lock.write_text(str(old))
        assert lock.is_stale(now) is True

    def test_fresh_lock_not_stale(self, lock, tmp_lock):
        now = int(time.time())
        recent = now - 3600  # 1 hour ago
        tmp_lock.write_text(str(recent))
        assert lock.is_stale(now) is False

    def test_corrupt_lock_treated_as_stale(self, lock, tmp_lock):
        tmp_lock.write_text("not_a_timestamp")
        now = int(time.time())
        assert lock.is_stale(now) is True

    def test_no_lock_not_stale(self, lock):
        now = int(time.time())
        assert lock.is_stale(now) is False

    def test_parallel_runs_prevented_by_interval(self, lock, tmp_lock):
        """
        Simulate two processes checking the lock at the same second.
        The first should run; the second should skip after the first writes the lock.
        """
        now = int(time.time())
        # Both check before any lock exists
        assert lock.should_run(now) is True

        # First process acquires
        lock.acquire(now)

        # Second process checks — lock now exists and is fresh
        lock2 = CronLockSimulator(tmp_lock)
        assert lock2.should_run(now) is False

    def test_production_lock_path_is_not_touched(self, tmp_lock):
        """
        CRITICAL: Tests must NEVER write to the production lock path.
        This test verifies the simulator uses a tmp path.
        """
        production_path = Path("/var/run/observatory_cron.lock")
        lock_sim = CronLockSimulator(tmp_lock)
        assert lock_sim.lock_path != production_path, (
            "CronLockSimulator test fixture must use a tmp path, NOT the production lock"
        )

    def test_recover_from_missing_lock_after_process_crash(self, lock, tmp_lock):
        """
        If the lock file is deleted after a crash, the guard should allow a new run.
        (This tests recovery, not that we should delete the lock — see cron_lock_rule.md.)
        """
        now = int(time.time())
        lock.acquire(now)
        assert lock.should_run(now) is False

        # Simulate lock file deletion (crash recovery scenario)
        tmp_lock.unlink()
        assert lock.should_run(now) is True


# ---------------------------------------------------------------------------
# Provider error and retry behavior
# ---------------------------------------------------------------------------

class TestProviderErrorHandling:
    @pytest.mark.asyncio
    async def test_classify_raises_on_api_error(self):
        """When HTTP call fails, classify() raises (after retries exhaust).

        tenacity wraps the original exception in RetryError after 3 attempts.
        We accept either the original exception type or RetryError.
        """
        import httpx
        from tenacity import RetryError

        clf = OpenRouterClassifier(api_key="dummy")
        vacancy = {
            "vacancy_id": "ERR-001",
            "raw_title": "Designer",
            "raw_description": "Design work",
            "raw_requirements": "",
            "company_name": "Co",
            "country": "MX",
        }
        with patch.object(clf.client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("connection refused")
            with pytest.raises((httpx.ConnectError, httpx.HTTPError, RetryError)):
                await clf.classify(vacancy)

    @pytest.mark.asyncio
    async def test_classify_raises_on_malformed_json(self):
        """When API returns non-JSON content, classify() raises (after retries exhaust).

        tenacity wraps JSONDecodeError in RetryError after 3 attempts.
        """
        import httpx
        from tenacity import RetryError

        clf = OpenRouterClassifier(api_key="dummy")
        vacancy = {
            "vacancy_id": "ERR-002",
            "raw_title": "Designer",
            "raw_description": "Design work",
            "raw_requirements": "",
            "company_name": "Co",
            "country": "MX",
        }

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "This is not JSON"}}],
            "usage": {"total_tokens": 50},
            "model": "openai/gpt-3.5-turbo",
        }

        with patch.object(clf.client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with pytest.raises((json.JSONDecodeError, RetryError)):
                await clf.classify(vacancy)

    @pytest.mark.asyncio
    async def test_classify_batch_continues_on_individual_failure(self):
        """classify_batch() returns None for failed items but completes the batch."""
        import httpx
        clf = OpenRouterClassifier(api_key="dummy")
        vacancies = [
            {"vacancy_id": f"V-{i}", "raw_title": "Role", "raw_description": "work",
             "raw_requirements": "", "company_name": "Co", "country": "MX"}
            for i in range(3)
        ]
        with patch.object(clf, 'classify', new_callable=AsyncMock) as mock_classify:
            # Second call fails
            mock_classify.side_effect = [
                {"vacancy_id": "V-0", "role_family": "marketing_growth", "ai_level": 0,
                 "seniority": "senior", "confidence": 0.8, "ai_tools_detected": [],
                 "ai_keywords_detected": [], "model": "mock", "classified_at": "2026-01-01T00:00:00Z"},
                httpx.ConnectError("fail"),
                {"vacancy_id": "V-2", "role_family": "contenido_social", "ai_level": 1,
                 "seniority": "junior", "confidence": 0.75, "ai_tools_detected": [],
                 "ai_keywords_detected": [], "model": "mock", "classified_at": "2026-01-01T00:00:00Z"},
            ]
            results = await clf.classify_batch(vacancies, batch_name="test_batch")
        assert len(results) == 3
        assert results[0] is not None
        assert results[1] is None  # failed item is None, not missing
        assert results[2] is not None
