"""
Tests for the cost/time optimizations added to the pipeline:

- DataCleaner.is_out_of_domain    (blacklist)
- DataCleaner.semantic_key        (cross-run dedup key normalization)
- DataCleaner.clean_batch         (integration: blacklist + semantic dedup in-batch)
- SkillsExtractor.clean_boilerplate (boilerplate stripping)
- OpenRouterClassifier._compact_for_classification (description truncation)
- OpenRouterClassifier.classify_batch concurrency (Semaphore bound)
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from classification.openrouter_classifier import OpenRouterClassifier
from classification.skills_extractor import SkillsExtractor
from pipeline.cleaner import DataCleaner


# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------

class TestIsOutOfDomain:
    """Whole-word matching keeps in-domain roles safe while catching obvious
    out-of-domain ones."""

    @pytest.mark.parametrize("title", [
        "Senior UX Designer",
        "Creative Director",
        "Growth Marketing Manager",
        "Brand Designer",
        "PR Manager",
        "Content Strategist",
        # 'design' appears inside 'designer' — must NOT be caught by any
        # 'design'-prefixed blacklist entry.
        "Product Designer",
        "Motion Designer",
    ])
    def test_in_domain_not_flagged(self, title):
        assert DataCleaner.is_out_of_domain(title) is False

    @pytest.mark.parametrize("title", [
        "Senior Software Engineer",
        "Backend Developer",
        "Full Stack Developer",
        "Data Scientist",
        "Mobile Developer",
        "Registered Nurse",
        "Enfermera Profesional",
        "Contador Público",
        "Driver - Last Mile",
    ])
    def test_out_of_domain_flagged(self, title):
        assert DataCleaner.is_out_of_domain(title) is True

    def test_empty_title_is_not_out_of_domain(self):
        assert DataCleaner.is_out_of_domain("") is False
        assert DataCleaner.is_out_of_domain(None) is False


# ---------------------------------------------------------------------------
# Semantic key
# ---------------------------------------------------------------------------

class TestSemanticKey:
    """Two vacancies that describe the same real-world job must collapse to
    the same key regardless of cosmetic differences."""

    def test_collapses_case_and_whitespace(self):
        a = {
            'company_name': 'FullStack',
            'raw_title': 'Agentic Product Designer - Remote - Colombia',
            'country': 'Colombia',
        }
        b = {
            'company_name': '  fullstack  ',
            'raw_title': 'AGENTIC PRODUCT DESIGNER - REMOTE - COLOMBIA',
            'country': 'colombia ',
        }
        assert DataCleaner.semantic_key(a) == DataCleaner.semantic_key(b)

    def test_different_country_different_key(self):
        a = {'company_name': 'X', 'raw_title': 'T', 'country': 'Colombia'}
        b = {'company_name': 'X', 'raw_title': 'T', 'country': 'Peru'}
        assert DataCleaner.semantic_key(a) != DataCleaner.semantic_key(b)

    def test_missing_fields_become_empty_strings(self):
        # No KeyError; key is well-formed for partial data so it can still be
        # set-hashed.
        key = DataCleaner.semantic_key({})
        assert key == ('', '', '')


# ---------------------------------------------------------------------------
# clean_batch integration
# ---------------------------------------------------------------------------

class TestCleanBatchIntegration:
    """End-to-end: blacklist drops obvious noise, semantic dedup collapses
    in-batch reposts, valid items survive."""

    def _run(self, vacancies):
        """Write input, run clean_batch, read output."""
        cleaner = DataCleaner()
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / 'in.jsonl'
            out = Path(tmp) / 'out.jsonl'
            with open(inp, 'w', encoding='utf-8') as f:
                for v in vacancies:
                    f.write(json.dumps(v) + '\n')
            stats = cleaner.clean_batch(str(inp), str(out))
            survivors = [
                json.loads(line)
                for line in open(out, encoding='utf-8')
                if line.strip()
            ]
        return survivors, stats

    def test_blacklist_drops_engineer(self):
        vacs = [
            {
                'vacancy_hash': 'h1',
                'raw_title': 'Senior UX Designer',
                'raw_description': 'desc',
                'job_url': 'http://x/1',
                'company_name': 'C',
                'country': 'CO',
            },
            {
                'vacancy_hash': 'h2',
                'raw_title': 'Senior Software Engineer',
                'raw_description': 'desc',
                'job_url': 'http://x/2',
                'company_name': 'C',
                'country': 'CO',
            },
        ]
        survivors, stats = self._run(vacs)
        assert stats['blacklisted_removed'] == 1
        assert len(survivors) == 1
        # clean_vacancy lowercases titles, so check lowercased value
        assert 'designer' in survivors[0]['raw_title']

    def test_semantic_dedup_in_batch(self):
        # Two rows with different URLs/hashes but the same (company, title,
        # country) — the in-batch semantic dedup must collapse to one.
        common = {
            'raw_title': 'Brand Designer',
            'raw_description': 'desc',
            'company_name': 'Acme',
            'country': 'Colombia',
        }
        vacs = [
            {**common, 'vacancy_hash': 'h1', 'job_url': 'http://x/a'},
            {**common, 'vacancy_hash': 'h2', 'job_url': 'http://x/b'},
        ]
        survivors, stats = self._run(vacs)
        assert stats['semantic_duplicates_removed'] == 1
        assert len(survivors) == 1


# ---------------------------------------------------------------------------
# Boilerplate cleanup
# ---------------------------------------------------------------------------

class TestCleanBoilerplate:

    def test_strips_urls_and_emails(self):
        text = "Apply at https://acme.com/jobs or email careers@acme.com"
        out = SkillsExtractor.clean_boilerplate(text)
        assert 'http' not in out
        assert '@' not in out

    def test_strips_eeo_statement(self):
        text = (
            "Lead user research and prototyping in Figma. "
            "We are an equal opportunity employer and do not discriminate. "
            "Required: 5+ years."
        )
        out = SkillsExtractor.clean_boilerplate(text)
        assert 'equal opportunity' not in out.lower()
        # Skill content must be preserved
        assert 'figma' in out.lower()
        assert '5+ years' in out.lower()

    def test_preserves_skill_content(self):
        text = (
            "Required skills: Python, SQL, Figma, GA4. "
            "Nice to have: Looker, dbt."
        )
        out = SkillsExtractor.clean_boilerplate(text)
        for skill in ('python', 'sql', 'figma', 'ga4', 'looker', 'dbt'):
            assert skill in out.lower()

    def test_empty_returns_empty(self):
        assert SkillsExtractor.clean_boilerplate('') == ''
        assert SkillsExtractor.clean_boilerplate(None) == ''

    def test_caps_at_max_chars(self):
        long_text = 'word ' * 5000  # ~25k chars
        out = SkillsExtractor.clean_boilerplate(long_text)
        assert len(out) <= SkillsExtractor.DESCRIPTION_MAX_CHARS


# ---------------------------------------------------------------------------
# Classification compaction
# ---------------------------------------------------------------------------

class TestCompactForClassification:

    def test_truncates_long_description(self):
        vac = {
            'id': 1,
            'raw_title': 'UX Designer',
            'company_name': 'C',
            'country': 'CO',
            'raw_description': 'X' * 5000,
        }
        compact = OpenRouterClassifier._compact_for_classification(vac)
        assert (
            len(compact['raw_description'])
            == OpenRouterClassifier.CLASSIFICATION_DESC_MAX_CHARS
        )

    def test_short_description_unchanged(self):
        vac = {
            'id': 1,
            'raw_title': 'UX Designer',
            'company_name': 'C',
            'country': 'CO',
            'raw_description': 'short',
        }
        compact = OpenRouterClassifier._compact_for_classification(vac)
        assert compact['raw_description'] == 'short'

    def test_drops_unneeded_fields(self):
        vac = {
            'id': 1,
            'raw_title': 'UX Designer',
            'company_name': 'C',
            'country': 'CO',
            'raw_description': 'd',
            'raw_requirements': 'should be dropped',  # not consumed by classifier
            'job_url': 'http://x',  # not consumed
        }
        compact = OpenRouterClassifier._compact_for_classification(vac)
        # Title/company/country/description are kept; the others are pruned.
        assert 'raw_requirements' not in compact
        assert 'job_url' not in compact


# ---------------------------------------------------------------------------
# Parallel classify_batch: Semaphore bound
# ---------------------------------------------------------------------------

class TestClassifyBatchConcurrency:
    """Verify the Semaphore actually bounds in-flight requests rather than
    silently degrading to serial or unbounded."""

    @pytest.mark.asyncio
    async def test_concurrency_bounded(self, monkeypatch):
        clf = OpenRouterClassifier(api_key='dummy')
        # Patch _load_classification_prompt so we don't touch the filesystem.
        monkeypatch.setattr(
            clf, '_load_classification_prompt', lambda: 'prompt'
        )

        # Track simultaneous in-flight calls.
        in_flight = 0
        peak = 0
        lock = asyncio.Lock()

        async def fake_call(model, messages):
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.05)
                return {
                    'choices': [{
                        'message': {'content': '{"role_family":"OTHER"}'}
                    }]
                }
            finally:
                async with lock:
                    in_flight -= 1

        monkeypatch.setattr(clf, '_call_openrouter', fake_call)

        vacs = [{'id': i, 'raw_title': 't', 'raw_description': 'd'}
                for i in range(20)]
        results = await clf.classify_batch(
            vacs, 'test', model='openai/gpt-3.5-turbo', concurrency=4
        )
        await clf.aclose()

        # Same length as input, no None (every call succeeded in this mock).
        assert len(results) == len(vacs)
        # Peak must respect the cap, AND must actually go above 1 (else we'd
        # be running serially and the test would pass trivially).
        assert peak <= 4
        assert peak > 1
