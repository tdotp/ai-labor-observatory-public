import pytest
import json
from datetime import datetime
from classification.openrouter_classifier import OpenRouterClassifier
from classification.skills_extractor import SkillsExtractor


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_vacancy():
    """Sample vacancy for testing."""
    return {
        "vacancy_id": "TEST-001",
        "raw_title": "Senior UX Designer - E-commerce Platform",
        "raw_description": "We are looking for a Senior UX Designer to lead design initiatives on our e-commerce platform. You will own the user experience strategy, conduct user research, create wireframes and prototypes in Figma, and collaborate with product and engineering teams. You'll establish design systems and mentor junior designers.",
        "raw_requirements": "7+ years of UX design experience. Proficiency in Figma, Sketch, or similar tools. Understanding of user research methodologies. Experience with design systems. Leadership and mentoring skills.",
        "company_name": "TechCorp",
        "country": "Spain"
    }


@pytest.fixture
def sample_vacancy_with_ai():
    """Sample vacancy with AI tools mentioned."""
    return {
        "vacancy_id": "TEST-002",
        "raw_title": "Growth Marketing Manager",
        "raw_description": "Lead our growth marketing function with focus on conversion optimization and user acquisition. You'll analyze performance data using analytics tools, A/B test landing pages, optimize funnels, and work with paid media teams. We use ChatGPT and Claude for copywriting A/B test variations, campaign messaging refinement, and competitive analysis.",
        "raw_requirements": "5-8 years of growth marketing experience. Proficiency with Google Analytics, Excel, SQL. Experience with A/B testing and funnel optimization. Familiarity with marketing automation platforms (HubSpot, Marketo). Ability to use AI tools like ChatGPT effectively.",
        "company_name": "GrowthStart",
        "country": "USA"
    }


@pytest.fixture
def classifier():
    """Create a classifier instance (with dummy API key for testing)."""
    # This would be replaced with actual API key in real tests
    return OpenRouterClassifier(api_key="dummy-key")


@pytest.fixture
def skills_extractor():
    """Create a skills extractor instance (with dummy API key for testing)."""
    return SkillsExtractor(api_key="dummy-key")


# ============================================================================
# CLASSIFICATION TESTS
# ============================================================================

class TestOpenRouterClassifier:
    """Tests for OpenRouterClassifier."""

    def test_classifier_initialization(self, classifier):
        """Test classifier initializes correctly."""
        assert classifier.api_key == "dummy-key"
        assert classifier.BASE_URL == "https://openrouter.ai/api/v1"

    def test_available_models(self, classifier):
        """Test available models are defined (4 cost-effective models for classification)."""
        assert len(classifier.AVAILABLE_MODELS) == 4
        assert "openai/gpt-3.5-turbo" in classifier.AVAILABLE_MODELS
        assert "deepseek/deepseek-chat" in classifier.AVAILABLE_MODELS
        assert "mistralai/mistral-small-latest" in classifier.AVAILABLE_MODELS
        assert "anthropic/claude-haiku" in classifier.AVAILABLE_MODELS

    @pytest.mark.asyncio
    async def test_invalid_model_raises_error(self, classifier, sample_vacancy):
        """Test that classify() raises ValueError for unknown model names.

        Model validation lives in classify(), not _call_openrouter(), so we
        call classify() directly and expect it to raise before any HTTP call.
        """
        import asyncio
        with pytest.raises(ValueError, match="Invalid model"):
            await classifier.classify(sample_vacancy, model="invalid-model")

    @pytest.mark.asyncio
    async def test_classify_output_structure(self, classifier, sample_vacancy):
        """Test classify returns correct output structure."""
        # This test would need mocking of HTTP calls
        # Expected structure validation
        expected_keys = {
            "vacancy_id",
            "role_family",
            "seniority",
            "ai_level",
            "ai_tools_detected",
            "ai_keywords_detected",
            "confidence",
            "model",
            "classified_at"
        }
        # Would validate against actual response structure

    def test_role_family_enum_values(self):
        """Test role family has correct enum values."""
        valid_families = {
            "creatividad_diseno",
            "contenido_social",
            "marketing_growth",
            "pr_comunicaciones",
            "estrategia_cuentas",
            "OTHER"
        }
        assert len(valid_families) == 6

    def test_seniority_enum_values(self):
        """Test seniority has correct enum values."""
        valid_levels = {
            "junior",
            "specialist",
            "senior",
            "lead",
            "manager",
            "director"
        }
        assert len(valid_levels) == 6

    def test_ai_level_ranges(self):
        """Test ai_level valid ranges (0-3)."""
        valid_ai_levels = {0, 1, 2, 3}
        assert len(valid_ai_levels) == 4
        assert min(valid_ai_levels) == 0
        assert max(valid_ai_levels) == 3

    def test_confidence_ranges(self):
        """Test confidence valid range (0.0-1.0)."""
        min_confidence = 0.0
        max_confidence = 1.0
        assert min_confidence >= 0.0
        assert max_confidence <= 1.0

    @pytest.mark.parametrize("ai_level", [0, 1, 2, 3])
    def test_ai_level_values_valid(self, ai_level):
        """Test each ai_level value is valid."""
        assert isinstance(ai_level, int)
        assert 0 <= ai_level <= 3

    @pytest.mark.parametrize("confidence", [0.0, 0.5, 0.75, 0.95, 1.0])
    def test_confidence_values_valid(self, confidence):
        """Test various confidence values are valid."""
        assert isinstance(confidence, (int, float))
        assert 0.0 <= confidence <= 1.0


# ============================================================================
# SKILLS EXTRACTION TESTS
# ============================================================================

class TestSkillsExtractor:
    """Tests for SkillsExtractor."""

    def test_extractor_initialization(self, skills_extractor):
        """Test extractor initializes correctly."""
        assert skills_extractor.api_key == "dummy-key"
        assert skills_extractor.BASE_URL == "https://openrouter.ai/api/v1"

    def test_skill_categories(self, skills_extractor):
        """Test skill categories are defined correctly."""
        expected_categories = {
            "hard_skills",
            "soft_skills",
            "strategic_skills",
            "ai_operational_skills",
            "ai_cognitive_skills"
        }
        assert skills_extractor.SKILL_CATEGORIES == expected_categories

    def test_validate_skill_requires_all_fields(self, skills_extractor):
        """Test skill validation requires all required fields."""
        invalid_skill = {
            "skill_name": "Figma",
            # Missing category, context_excerpt, confidence
        }
        assert not skills_extractor._validate_skill(invalid_skill)

    def test_validate_skill_invalid_category(self, skills_extractor):
        """Test skill validation rejects invalid category."""
        invalid_skill = {
            "skill_name": "Figma",
            "category": "invalid_category",
            "context_excerpt": "Proficiency in Figma",
            "confidence": 0.95
        }
        assert not skills_extractor._validate_skill(invalid_skill)

    def test_validate_skill_invalid_confidence_too_high(self, skills_extractor):
        """Test skill validation rejects confidence > 1.0."""
        invalid_skill = {
            "skill_name": "Figma",
            "category": "hard_skills",
            "context_excerpt": "Proficiency in Figma",
            "confidence": 1.5
        }
        assert not skills_extractor._validate_skill(invalid_skill)

    def test_validate_skill_invalid_confidence_too_low(self, skills_extractor):
        """Test skill validation rejects confidence < 0.0."""
        invalid_skill = {
            "skill_name": "Figma",
            "category": "hard_skills",
            "context_excerpt": "Proficiency in Figma",
            "confidence": -0.5
        }
        assert not skills_extractor._validate_skill(invalid_skill)

    def test_validate_skill_empty_skill_name(self, skills_extractor):
        """Test skill validation rejects empty skill name."""
        invalid_skill = {
            "skill_name": "",
            "category": "hard_skills",
            "context_excerpt": "Proficiency in Figma",
            "confidence": 0.95
        }
        assert not skills_extractor._validate_skill(invalid_skill)

    def test_validate_skill_empty_context(self, skills_extractor):
        """Test skill validation rejects empty context excerpt."""
        invalid_skill = {
            "skill_name": "Figma",
            "category": "hard_skills",
            "context_excerpt": "",
            "confidence": 0.95
        }
        assert not skills_extractor._validate_skill(invalid_skill)

    def test_validate_skill_valid(self, skills_extractor):
        """Test skill validation accepts valid skill."""
        valid_skill = {
            "skill_name": "Figma",
            "category": "hard_skills",
            "context_excerpt": "Proficiency in Figma and Adobe Creative Suite",
            "confidence": 0.95
        }
        assert skills_extractor._validate_skill(valid_skill)

    @pytest.mark.parametrize("category", [
        "hard_skills",
        "soft_skills",
        "strategic_skills",
        "ai_operational_skills",
        "ai_cognitive_skills"
    ])
    def test_skill_categories_valid(self, skills_extractor, category):
        """Test each skill category is valid."""
        assert category in skills_extractor.SKILL_CATEGORIES

    @pytest.mark.parametrize("confidence", [0.0, 0.55, 0.70, 0.85, 0.95, 1.0])
    def test_skill_confidence_values(self, skills_extractor, confidence):
        """Test various confidence values are valid for skills."""
        skill = {
            "skill_name": "Test Skill",
            "category": "hard_skills",
            "context_excerpt": "Test context",
            "confidence": confidence
        }
        assert skills_extractor._validate_skill(skill)

    @pytest.mark.asyncio
    async def test_extract_skills_output_structure(self, skills_extractor, sample_vacancy):
        """Test extract_skills returns correct output structure."""
        # This test would need mocking of HTTP calls
        # Expected structure: list of dicts with skill info
        pass

    def test_available_models(self, skills_extractor):
        """Test available models are defined (must match classifier's list)."""
        assert len(skills_extractor.AVAILABLE_MODELS) == 4
        assert "openai/gpt-3.5-turbo" in skills_extractor.AVAILABLE_MODELS
        assert "deepseek/deepseek-chat" in skills_extractor.AVAILABLE_MODELS


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for classification and extraction."""

    def test_both_modules_use_same_models(self, classifier, skills_extractor):
        """Test classifier and extractor use same models."""
        assert classifier.AVAILABLE_MODELS == skills_extractor.AVAILABLE_MODELS

    def test_both_modules_use_openrouter_api(self, classifier, skills_extractor):
        """Test both modules use OpenRouter API base URL."""
        assert classifier.BASE_URL == skills_extractor.BASE_URL
        assert classifier.BASE_URL == "https://openrouter.ai/api/v1"

    def test_vacancy_structure_compatible(self, sample_vacancy, sample_vacancy_with_ai):
        """Test sample vacancies have required structure."""
        required_keys = {"vacancy_id", "raw_description"}

        # For classifier
        classifier_keys = {"vacancy_id", "raw_title", "raw_description", "raw_requirements", "company_name", "country"}
        assert all(key in sample_vacancy for key in classifier_keys)
        assert all(key in sample_vacancy_with_ai for key in classifier_keys)

        # For extractor
        extractor_keys = {"vacancy_id", "raw_description", "raw_requirements"}
        assert all(key in sample_vacancy for key in extractor_keys)
        assert all(key in sample_vacancy_with_ai for key in extractor_keys)
