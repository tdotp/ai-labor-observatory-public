"""Classification module for vacancy analysis."""

from .openrouter_classifier import OpenRouterClassifier
from .skills_extractor import SkillsExtractor

__all__ = ["OpenRouterClassifier", "SkillsExtractor"]
