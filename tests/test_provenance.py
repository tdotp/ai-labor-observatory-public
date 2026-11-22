"""
Tests for the provenance / traceability module.

Covers:
  - RunContext generates a unique run_id
  - RunContext hashes prompt and taxonomy files
  - ProvenanceTracker attaches all required traceability fields
  - validation_status enum is enforced
  - Two different runs have different run_ids
  - Token accounting in provenance dict
  - Error field propagation

No external calls, no VPS, no production systems.
"""

import pytest
import uuid
from pathlib import Path

from classification.provenance import RunContext, ProvenanceTracker


# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------

class TestRunContext:
    def test_run_id_is_set(self):
        ctx = RunContext()
        assert ctx.run_id is not None
        assert len(ctx.run_id) > 0

    def test_run_id_is_valid_uuid(self):
        ctx = RunContext()
        # Should not raise
        parsed = uuid.UUID(ctx.run_id)
        assert str(parsed) == ctx.run_id

    def test_two_contexts_have_different_run_ids(self):
        ctx1 = RunContext()
        ctx2 = RunContext()
        assert ctx1.run_id != ctx2.run_id

    def test_explicit_run_id_is_used(self):
        ctx = RunContext(run_id="my-custom-run-id")
        assert ctx.run_id == "my-custom-run-id"

    def test_prompt_version_is_set(self):
        ctx = RunContext()
        assert ctx.prompt_version is not None
        assert len(ctx.prompt_version) > 0

    def test_prompt_version_is_hash_or_unknown(self):
        ctx = RunContext()
        # Should start with "sha256:" or be "unknown"
        assert ctx.prompt_version.startswith("sha256:") or ctx.prompt_version == "unknown", (
            f"Unexpected prompt_version format: {ctx.prompt_version}"
        )

    def test_taxonomy_version_is_set(self):
        ctx = RunContext()
        assert ctx.taxonomy_version is not None
        assert len(ctx.taxonomy_version) > 0

    def test_taxonomy_version_contains_schema_version(self):
        ctx = RunContext()
        # Taxonomy version should contain "1.0.0" (schema version prefix)
        assert "1.0.0" in ctx.taxonomy_version

    def test_missing_prompt_file_returns_unknown(self):
        ctx = RunContext(prompt_path=Path("/nonexistent/prompt.md"))
        assert ctx.prompt_version == "unknown"

    def test_to_dict_has_required_keys(self):
        ctx = RunContext()
        d = ctx.to_dict()
        assert "run_id" in d
        assert "prompt_version" in d
        assert "taxonomy_version" in d

    def test_same_prompt_produces_same_hash(self):
        ctx1 = RunContext()
        ctx2 = RunContext()
        # Both use the same default prompt file — should produce the same hash
        assert ctx1.prompt_version == ctx2.prompt_version


# ---------------------------------------------------------------------------
# ProvenanceTracker
# ---------------------------------------------------------------------------

class TestProvenanceTracker:
    @pytest.fixture
    def ctx(self):
        return RunContext()

    @pytest.fixture
    def tracker(self, ctx):
        return ProvenanceTracker(ctx)

    def test_provenance_has_run_id(self, tracker, ctx):
        prov = tracker.build(
            vacancy_id="V-001",
            requested_model="openai/gpt-3.5-turbo",
        )
        assert prov["run_id"] == ctx.run_id

    def test_provenance_has_prompt_version(self, tracker, ctx):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo")
        assert prov["prompt_version"] == ctx.prompt_version

    def test_provenance_has_taxonomy_version(self, tracker, ctx):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo")
        assert prov["taxonomy_version"] == ctx.taxonomy_version

    def test_provenance_has_vacancy_id(self, tracker):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo")
        assert prov["vacancy_id"] == "V-001"

    def test_provenance_has_requested_model(self, tracker):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo")
        assert prov["requested_model"] == "openai/gpt-3.5-turbo"

    def test_provenance_served_model_defaults_to_requested(self, tracker):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo")
        assert prov["served_model"] == "openai/gpt-3.5-turbo"

    def test_provenance_served_model_can_differ_from_requested(self, tracker):
        prov = tracker.build(
            "V-001",
            "openai/gpt-3.5-turbo",
            served_model="openai/gpt-3.5-turbo-0125",
        )
        assert prov["requested_model"] == "openai/gpt-3.5-turbo"
        assert prov["served_model"] == "openai/gpt-3.5-turbo-0125"

    def test_provenance_has_classified_at_timestamp(self, tracker):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo")
        assert "classified_at" in prov
        assert prov["classified_at"].endswith("+00:00") or prov["classified_at"].endswith("Z")

    def test_provenance_has_validation_status_valid(self, tracker):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo", validation_status="valid")
        assert prov["validation_status"] == "valid"

    def test_provenance_all_valid_statuses_accepted(self, tracker):
        for status in ("valid", "invalid_taxonomy", "invalid_json", "api_error"):
            prov = tracker.build("V-001", "openai/gpt-3.5-turbo", validation_status=status)
            assert prov["validation_status"] == status

    def test_provenance_invalid_status_raises(self, tracker):
        with pytest.raises(ValueError, match="validation_status"):
            tracker.build("V-001", "openai/gpt-3.5-turbo", validation_status="bad_status")

    def test_provenance_has_tokens_used_dict(self, tracker):
        prov = tracker.build(
            "V-001",
            "openai/gpt-3.5-turbo",
            tokens_used={"prompt_tokens": 400, "completion_tokens": 80, "total_tokens": 480},
        )
        assert "tokens_used" in prov
        assert prov["tokens_used"]["prompt_tokens"] == 400
        assert prov["tokens_used"]["completion_tokens"] == 80
        assert prov["tokens_used"]["total_tokens"] == 480

    def test_provenance_tokens_zero_when_not_provided(self, tracker):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo")
        assert prov["tokens_used"]["total_tokens"] == 0

    def test_provenance_error_field_on_failure(self, tracker):
        prov = tracker.build(
            "V-001",
            "openai/gpt-3.5-turbo",
            validation_status="api_error",
            error="Connection timeout after 60s",
        )
        assert "error" in prov
        assert "timeout" in prov["error"]

    def test_provenance_no_error_field_on_success(self, tracker):
        prov = tracker.build("V-001", "openai/gpt-3.5-turbo", validation_status="valid")
        assert "error" not in prov

    def test_all_classifications_in_same_run_share_run_id(self, tracker, ctx):
        ids = ["V-001", "V-002", "V-003"]
        provs = [tracker.build(vid, "openai/gpt-3.5-turbo") for vid in ids]
        run_ids = {p["run_id"] for p in provs}
        assert len(run_ids) == 1, "All classifications in a run must share the same run_id"
        assert run_ids.pop() == ctx.run_id

    def test_different_runs_have_different_run_ids(self):
        ctx1 = RunContext()
        ctx2 = RunContext()
        t1 = ProvenanceTracker(ctx1)
        t2 = ProvenanceTracker(ctx2)
        prov1 = t1.build("V-001", "openai/gpt-3.5-turbo")
        prov2 = t2.build("V-001", "openai/gpt-3.5-turbo")
        assert prov1["run_id"] != prov2["run_id"]
