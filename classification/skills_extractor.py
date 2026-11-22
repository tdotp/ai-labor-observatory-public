import json
import logging
import re
from typing import List, Dict, Any, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SkillsExtractor:
    """Extract skills from vacancies using OpenRouter API."""

    BASE_URL = "https://openrouter.ai/api/v1"
    AVAILABLE_MODELS = [
        "openai/gpt-3.5-turbo",
        "deepseek/deepseek-chat",
        "mistralai/mistral-small-latest",
        "anthropic/claude-haiku",
    ]

    SKILL_CATEGORIES = {
        "hard_skills",
        "soft_skills",
        "strategic_skills",
        "ai_operational_skills",
        "ai_cognitive_skills"
    }

    # If a description is still longer than this after boilerplate cleanup,
    # truncate from the tail. Skills clues are concentrated in the first ~5k
    # chars (responsibilities + requirements); benefits/legalese live below.
    DESCRIPTION_MAX_CHARS = 5000

    # Conservative regex patterns that strip predictable, high-volume noise
    # from job descriptions BEFORE sending to the LLM. Each pattern targets
    # boilerplate that is virtually never a source of skill information
    # (URLs, emails, EEO statements, GDPR/legal closers). The goal is to
    # reduce input tokens by ~15-25% without removing any skill signal.
    _BOILERPLATE_PATTERNS = [
        # URLs — never carry skill info; safe to strip entirely
        re.compile(r'https?://\S+', re.IGNORECASE),
        # Emails
        re.compile(r'\S+@\S+\.\S+'),
        # Equal-employment-opportunity statements (English) — match the
        # standard "regardless of ..." closing rather than the whole intro
        # to avoid swallowing role copy.
        re.compile(
            r'\b(?:we\s+are\s+(?:an\s+)?equal\s+(?:opportunity|employment)\s+'
            r'(?:employer|workplace)[^.]*\.)',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r'\b(?:regardless\s+of\s+race,?\s+color,?\s+religion[^.]*\.)',
            re.IGNORECASE | re.DOTALL,
        ),
        # GDPR / "your data will be kept" disclaimers
        re.compile(
            r'\bby\s+submitting\s+your\s+application[^.]*\.',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r'\b(?:your\s+(?:personal\s+)?(?:data|information)\s+will\s+be[^.]*\.)',
            re.IGNORECASE | re.DOTALL,
        ),
        # Generic diversity/inclusion closers
        re.compile(
            r'\bwe\s+(?:are\s+)?(?:committed|believe)\s+(?:to\s+)?'
            r'(?:diversity|creating\s+an\s+inclusive)[^.]*\.',
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    def __init__(self, api_key: str):
        """Initialize skills extractor.

        Args:
            api_key: OpenRouter API key
        """
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0
        )

    @classmethod
    def clean_boilerplate(cls, text: Optional[str]) -> str:
        """
        Strip predictable boilerplate (URLs, emails, EEO/GDPR/diversity
        closers) and collapse whitespace.

        Used to shrink the description sent to the LLM WITHOUT touching
        responsibilities or requirements — the patterns are intentionally
        narrow to avoid removing skill signal. If the result is still longer
        than `DESCRIPTION_MAX_CHARS`, truncate from the tail (the head is
        where role copy lives in job posts).
        """
        if not text:
            return ''
        cleaned = text
        for pat in cls._BOILERPLATE_PATTERNS:
            cleaned = pat.sub(' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if len(cleaned) > cls.DESCRIPTION_MAX_CHARS:
            cleaned = cleaned[: cls.DESCRIPTION_MAX_CHARS]
        return cleaned

    def _load_extraction_prompt(self) -> str:
        """Load skills extraction prompt from file."""
        import os
        prompt_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "prompts",
            "openrouter_skills_extraction_prompt.md"
        )
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError))
    )
    async def extract_skills(
        self,
        vacancy: Dict[str, Any],
        model: str = "deepseek/deepseek-chat"
    ) -> List[Dict[str, Any]]:
        """Extract skills from a vacancy.

        Args:
            vacancy: Vacancy data dict with keys: vacancy_id, raw_description, raw_requirements
            model: OpenRouter model to use

        Returns:
            List of skill dicts with keys: skill_name, category, context_excerpt, confidence
        """
        if model not in self.AVAILABLE_MODELS:
            raise ValueError(f"Invalid model: {model}. Available: {self.AVAILABLE_MODELS}")

        prompt = self._load_extraction_prompt()

        # Strip boilerplate from description/requirements BEFORE sending to
        # the LLM — saves input tokens without removing skill signal.
        vacancy_for_llm = {
            **vacancy,
            'raw_description': self.clean_boilerplate(
                vacancy.get('raw_description')
            ),
            'raw_requirements': self.clean_boilerplate(
                vacancy.get('raw_requirements')
            ),
        }

        # Build user message with vacancy data
        user_message = f"""{prompt}

## Input Vacancy Data

```json
{json.dumps(vacancy_for_llm, indent=2)}
```

Please extract and categorize all skills from this vacancy and provide the response in JSON format."""

        try:
            response = await self._call_openrouter(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            )

            # Extract JSON from response
            content = response["choices"][0]["message"]["content"]

            # Parse JSON response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                raise json.JSONDecodeError("No JSON found in response", content, 0)

            result = json.loads(content[json_start:json_end])

            # Validate and extract skills array
            if "skills" not in result:
                logger.warning(f"No 'skills' key in response for vacancy {vacancy.get('vacancy_id')}")
                return []

            skills = result["skills"]

            # Validate each skill
            validated_skills = []
            for skill in skills:
                if self._validate_skill(skill):
                    validated_skills.append(skill)
                else:
                    logger.warning(f"Skipping invalid skill format in vacancy {vacancy.get('vacancy_id')}: {skill}")

            logger.info(f"Extracted {len(validated_skills)} skills from vacancy {vacancy.get('vacancy_id')}")

            return validated_skills

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response for vacancy {vacancy.get('vacancy_id')}: {e}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"API error extracting skills from vacancy {vacancy.get('vacancy_id')}: {e}")
            raise

    def _validate_skill(self, skill: Dict[str, Any]) -> bool:
        """Validate skill structure.

        Args:
            skill: Skill dict to validate

        Returns:
            True if valid, False otherwise
        """
        required_keys = {"skill_name", "category", "context_excerpt", "confidence"}

        # Check required keys
        if not all(key in skill for key in required_keys):
            return False

        # Validate category
        if skill.get("category") not in self.SKILL_CATEGORIES:
            return False

        # Validate confidence is between 0 and 1
        confidence = skill.get("confidence")
        if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
            return False

        # Validate skill_name is string
        if not isinstance(skill.get("skill_name"), str) or not skill.get("skill_name").strip():
            return False

        # Validate context_excerpt is string
        if not isinstance(skill.get("context_excerpt"), str) or not skill.get("context_excerpt").strip():
            return False

        return True

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
        response = await self.client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 3000
            }
        )
        response.raise_for_status()
        return response.json()

    async def aclose(self):
        """Close HTTP client asynchronously."""
        await self.client.aclose()

    def close(self):
        """Close HTTP client synchronously (no-op for AsyncClient)."""
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.aclose()
