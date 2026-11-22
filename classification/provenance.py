"""
Provenance tracking — AI Labor Observatory.

Attaches a traceability record to every classification so each label can
be tied back to the specific run, model, prompt version, and taxonomy version
that produced it.

This module does NOT persist anything — the pipeline's loader writes the
provenance dict alongside the classification result. This is intentional:
the traceability record stays with the data, not in a separate audit log that
can drift out of sync.

Fields:
    run_id              Unique ID for this pipeline execution.
                        Shared across all classifications in the same run.
    prompt_version      Hash or tag of the prompt template used.
    taxonomy_version    Semantic version of the taxonomy JSON on disk.
    requested_model     The model name the caller asked for.
    served_model        The model that actually processed the request
                        (may differ from requested_model on aliased routes).
    classified_at       ISO-8601 timestamp in UTC.
    validation_status   "valid" | "invalid_taxonomy" | "invalid_json" | "api_error"
    tokens_used         Token count from the provider's usage response.
    error               Error description when validation_status != "valid".
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Bump this whenever the taxonomy JSON schema changes in a breaking way.
# Non-breaking additions (new tools_detected entries) do not need a version bump.
_TAXONOMY_SCHEMA_VERSION = "1.0.0"

# Default prompt path
_DEFAULT_PROMPT_PATH = (
    Path(__file__).parent.parent / "prompts" / "openrouter_classification_prompt.md"
)


def _prompt_version(prompt_path: Optional[Path] = None) -> str:
    """
    Return a short content-hash of the prompt file.

    This ties each classification to the exact prompt that produced it.
    If the prompt file is missing or unreadable, returns "unknown".
    """
    path = prompt_path or _DEFAULT_PROMPT_PATH
    try:
        content = path.read_bytes()
        return "sha256:" + hashlib.sha256(content).hexdigest()[:12]
    except (OSError, IOError) as e:
        logger.warning(f"Could not hash prompt file {path}: {e}")
        return "unknown"


def _taxonomy_version(taxonomy_path: Optional[Path] = None) -> str:
    """
    Return the taxonomy schema version + content hash.

    The schema version is bumped manually on breaking taxonomy changes.
    The content hash catches any file modification.
    """
    if taxonomy_path is None:
        taxonomy_path = (
            Path(__file__).parent.parent / "data" / "taxonomies" / "role_families.json"
        )
    try:
        content = taxonomy_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()[:12]
        return f"{_TAXONOMY_SCHEMA_VERSION}+sha256:{content_hash}"
    except (OSError, IOError) as e:
        logger.warning(f"Could not hash taxonomy file {taxonomy_path}: {e}")
        return f"{_TAXONOMY_SCHEMA_VERSION}+unknown"


class RunContext:
    """
    Shared context for a single pipeline execution.

    Create once per run; pass to ProvenanceTracker.build() for each
    classification so all results share the same run_id.
    """

    def __init__(
        self,
        run_id: Optional[str] = None,
        prompt_path: Optional[Path] = None,
        taxonomy_path: Optional[Path] = None,
    ):
        self.run_id = run_id or str(uuid.uuid4())
        self.prompt_version = _prompt_version(prompt_path)
        self.taxonomy_version = _taxonomy_version(taxonomy_path)
        logger.info(
            f"RunContext created: run_id={self.run_id} "
            f"prompt={self.prompt_version} taxonomy={self.taxonomy_version}"
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "run_id": self.run_id,
            "prompt_version": self.prompt_version,
            "taxonomy_version": self.taxonomy_version,
        }


class ProvenanceTracker:
    """
    Builds provenance records to attach to classification results.

    Usage:
        ctx = RunContext()
        tracker = ProvenanceTracker(ctx)
        provenance = tracker.build(
            vacancy_id="v123",
            requested_model="openai/gpt-3.5-turbo",
            served_model="openai/gpt-3.5-turbo-0125",
            tokens_used={"prompt_tokens": 400, "completion_tokens": 80},
            validation_status="valid",
        )
        # Merge into classification result:
        classification["provenance"] = provenance
    """

    def __init__(self, run_context: RunContext):
        self.ctx = run_context

    def build(
        self,
        vacancy_id: str,
        requested_model: str,
        served_model: Optional[str] = None,
        tokens_used: Optional[Dict[str, int]] = None,
        validation_status: str = "valid",
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build a provenance dict for one classification.

        Args:
            vacancy_id: The vacancy this classification belongs to.
            requested_model: The model alias the caller requested.
            served_model: The model that actually processed the call
                          (from provider's usage response). Falls back
                          to requested_model if None.
            tokens_used: Provider usage dict (prompt_tokens, completion_tokens, total_tokens).
            validation_status: "valid" | "invalid_taxonomy" | "invalid_json" | "api_error"
            error: Short error description when validation_status != "valid".

        Returns:
            Provenance dict suitable for embedding in a classification record.
        """
        if validation_status not in ("valid", "invalid_taxonomy", "invalid_json", "api_error"):
            raise ValueError(
                f"validation_status must be one of "
                "'valid', 'invalid_taxonomy', 'invalid_json', 'api_error'. "
                f"Got: '{validation_status}'"
            )

        provenance: Dict[str, Any] = {
            "run_id": self.ctx.run_id,
            "prompt_version": self.ctx.prompt_version,
            "taxonomy_version": self.ctx.taxonomy_version,
            "vacancy_id": vacancy_id,
            "requested_model": requested_model,
            "served_model": served_model or requested_model,
            "classified_at": datetime.now(timezone.utc).isoformat(),
            "validation_status": validation_status,
        }

        if tokens_used:
            provenance["tokens_used"] = {
                "prompt_tokens": tokens_used.get("prompt_tokens", 0),
                "completion_tokens": tokens_used.get("completion_tokens", 0),
                "total_tokens": tokens_used.get("total_tokens", 0),
            }
        else:
            provenance["tokens_used"] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        if error:
            provenance["error"] = error

        return provenance
