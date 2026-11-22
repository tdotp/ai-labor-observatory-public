import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class OpenRouterClassifier:
    """Classify vacancies using OpenRouter API."""

    BASE_URL = "https://openrouter.ai/api/v1"
    # Cheap models for cost-effective batch classification
    AVAILABLE_MODELS = [
        "openai/gpt-3.5-turbo",          # ~$0.001/1k tokens (cheapest)
        "deepseek/deepseek-chat",        # ~$0.001/1k tokens
        "mistralai/mistral-small-latest", # ~$0.001/1k tokens
        "anthropic/claude-haiku",        # ~$0.002/1k tokens (Haiku 4.5)
    ]

    # Title + first ~800 chars of description is enough to determine the
    # role family. The remaining tail of the description is mostly benefits,
    # company blurb and "how to apply" — not signal for classification.
    # Trimming here cuts input tokens by ~60-70% on long descriptions.
    CLASSIFICATION_DESC_MAX_CHARS = 800

    def __init__(self, api_key: str):
        """Initialize OpenRouter classifier.

        Args:
            api_key: OpenRouter API key
        """
        self.api_key = api_key
        # AsyncClient is REQUIRED for real concurrent classification — using
        # the sync Client inside an `async def` blocks the event loop and
        # turns asyncio.gather into a sequential queue.
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
        # Budget tracking — reset per batch run by the caller
        self._last_usage: dict = {}
        self._last_served_model: str = ""
        self.total_tokens_used: int = 0
        self.total_calls: int = 0

    def _load_classification_prompt(self) -> str:
        """Load classification prompt from file."""
        import os
        prompt_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "prompts",
            "openrouter_classification_prompt.md"
        )
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError))
    )
    async def classify(
        self,
        vacancy: Dict[str, Any],
        model: str = "openai/gpt-3.5-turbo"
    ) -> Dict[str, Any]:
        """Classify a single vacancy.

        Args:
            vacancy: Vacancy data dict with keys: vacancy_id, raw_title, raw_description, raw_requirements, company_name, country
            model: OpenRouter model to use

        Returns:
            Classification result with keys: role_family, seniority, ai_level, ai_tools_detected, ai_keywords_detected, confidence, model, classified_at
        """
        if model not in self.AVAILABLE_MODELS:
            raise ValueError(f"Invalid model: {model}. Available: {self.AVAILABLE_MODELS}")

        prompt = self._load_classification_prompt()

        # Build user message with vacancy data
        user_message = f"""{prompt}

## Input Vacancy Data

```json
{json.dumps(vacancy, indent=2)}
```

Please analyze this vacancy and provide the classification in JSON format."""

        try:
            response = await self._call_openrouter(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": user_message,
                    }
                ],
            )

            # Extract JSON from response
            content = response["choices"][0]["message"]["content"]

            # Parse JSON response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                raise json.JSONDecodeError("No JSON found in response", content, 0)

            classification = json.loads(content[json_start:json_end])

            # Record the model actually served (not just the alias we requested)
            classification["model"] = self._last_served_model or model
            classification["classified_at"] = datetime.now(timezone.utc).isoformat()
            # Accumulate token usage for budget enforcement
            self.total_tokens_used += self._last_usage.get("total_tokens", 0)
            self.total_calls += 1

            logger.info(f"Classified vacancy {vacancy.get('vacancy_id')} with model {model}")

            return classification

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response for vacancy {vacancy.get('vacancy_id')}: {e}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"API error classifying vacancy {vacancy.get('vacancy_id')}: {e}")
            raise

    @classmethod
    def _compact_for_classification(
        cls, vacancy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build a compact vacancy view for the classification prompt.

        Includes only the fields the classifier prompt actually consumes
        (title, company, country, truncated description). Saves tokens
        without removing signal — see CLASSIFICATION_DESC_MAX_CHARS.
        """
        desc = vacancy.get('raw_description') or ''
        if len(desc) > cls.CLASSIFICATION_DESC_MAX_CHARS:
            desc = desc[: cls.CLASSIFICATION_DESC_MAX_CHARS]
        return {
            'vacancy_id': vacancy.get('vacancy_id') or vacancy.get('id'),
            'raw_title': vacancy.get('raw_title'),
            'company_name': vacancy.get('company_name'),
            'country': vacancy.get('country'),
            'raw_description': desc,
        }

    async def classify_batch(
        self,
        vacancies: List[Dict[str, Any]],
        batch_name: str,
        model: str = "openai/gpt-3.5-turbo",
        concurrency: int = 8,
    ) -> List[Optional[Dict[str, Any]]]:
        """Classify a batch of vacancies in parallel with bounded concurrency.

        Uses asyncio.gather + Semaphore so up to `concurrency` requests are
        in flight at once. Each vacancy is compacted (truncated description)
        before being sent to the LLM.

        The returned list is aligned with the input list — failed items are
        `None` rather than missing, so callers can `zip(vacancies, results)`
        without going out of sync.

        Args:
            vacancies: List of vacancy dicts
            batch_name: Name for logging purposes
            model: OpenRouter model to use
            concurrency: Max parallel in-flight LLM calls

        Returns:
            List of classification results (or None for failures), aligned
            with `vacancies`.
        """
        total = len(vacancies)
        logger.info(
            f"Starting batch classification '{batch_name}' with {total} "
            f"vacancies using {model} (concurrency={concurrency})"
        )

        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _classify_one(v: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            async with semaphore:
                compact = self._compact_for_classification(v)
                try:
                    return await self.classify(compact, model)
                except Exception as e:
                    logger.error(
                        f"Failed to classify vacancy "
                        f"{v.get('id') or v.get('vacancy_id')} in batch "
                        f"'{batch_name}': {e}"
                    )
                    return None

        results = await asyncio.gather(*(_classify_one(v) for v in vacancies))
        successful = sum(1 for r in results if r is not None)
        logger.info(
            f"Batch classification '{batch_name}' complete: "
            f"{successful}/{total} successful"
        )
        return results

    async def _call_openrouter(
        self,
        model: str,
        messages: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Call OpenRouter API.

        Args:
            model: Model name
            messages: Messages list

        Returns:
            API response
        """
        result = await self.client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": 0,  # deterministic: classification is a lookup, not creative writing
                "max_tokens": 2000,
            },
        )
        result.raise_for_status()
        data = result.json()
        # Track token usage for budget enforcement (caller reads this)
        self._last_usage = data.get("usage", {})
        # Save the model actually served by OpenRouter (may differ from requested alias)
        self._last_served_model = data.get("model", model)
        return data

    async def aclose(self):
        """Close HTTP client asynchronously."""
        await self.client.aclose()

    def close(self):
        """Backwards-compatible no-op for callers that used the sync API."""
        # AsyncClient must be closed via aclose(); legacy callers that called
        # .close() get a no-op rather than an error.
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.aclose()
