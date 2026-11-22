"""Analysis Engine for the Observatory Project.

This package provides tools for analyzing labor market trends and generating
professional reports on human expertise value in AI systems.

Modules:
- labor_insights: Core analysis engine with temporal and categorical analysis
- pdf_reporter: Professional PDF report generation from analysis results
"""

from analysis.labor_insights import LaborInsightsAnalyzer
from analysis.pdf_reporter import PDFReporter

__version__ = "1.0.0"
__all__ = ["LaborInsightsAnalyzer", "PDFReporter"]
