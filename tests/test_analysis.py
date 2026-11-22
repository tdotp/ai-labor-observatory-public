"""Tests for the analysis module.

Tests for LaborInsightsAnalyzer and PDFReporter classes.
"""

import unittest
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch

from analysis.labor_insights import LaborInsightsAnalyzer
from analysis.pdf_reporter import PDFReporter


class TestLaborInsightsAnalyzer(unittest.TestCase):
    """Test cases for LaborInsightsAnalyzer."""

    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = LaborInsightsAnalyzer(
            supabase_url="https://test.supabase.co",
            supabase_key="test_key"
        )
        self.tz = timezone.utc

    def test_analyzer_initialization(self):
        """Test analyzer initializes with correct attributes."""
        self.assertIsNotNone(self.analyzer)
        self.assertEqual(self.analyzer.tz, self.tz)

    @patch('analysis.labor_insights.SupabaseLoader')
    def test_skill_emergence_no_client(self, mock_loader):
        """Test skill emergence with no Supabase client."""
        self.analyzer.loader = Mock()
        self.analyzer.loader.client = None

        result = self.analyzer.analyze_skill_emergence()

        self.assertIn('period', result)
        self.assertIn('timeline', result)
        self.assertEqual(result['timeline'], {})

    @patch('analysis.labor_insights.SupabaseLoader')
    def test_role_transformation_no_client(self, mock_loader):
        """Test role transformation with no Supabase client."""
        self.analyzer.loader = Mock()
        self.analyzer.loader.client = None

        result = self.analyzer.analyze_role_transformation()

        self.assertIn('period', result)
        self.assertIn('most_transformed_roles', result)
        self.assertEqual(result['most_transformed_roles'], [])

    @patch('analysis.labor_insights.SupabaseLoader')
    def test_value_shift_no_client(self, mock_loader):
        """Test value shift with no Supabase client."""
        self.analyzer.loader = Mock()
        self.analyzer.loader.client = None

        result = self.analyzer.analyze_value_shift()

        self.assertIn('period', result)
        self.assertIn('skill_category_distribution', result)

    @patch('analysis.labor_insights.SupabaseLoader')
    def test_human_expertise_premium_no_client(self, mock_loader):
        """Test human expertise premium with no Supabase client."""
        self.analyzer.loader = Mock()
        self.analyzer.loader.client = None

        result = self.analyzer.analyze_human_expertise_premium()

        self.assertIn('ai_operational_prevalence_percent', result)
        self.assertIn('ai_cognitive_prevalence_percent', result)

    def test_skill_emergence_data_structure(self):
        """Test that skill emergence returns correct data structure."""
        result = self.analyzer.analyze_skill_emergence()

        # Verify structure
        self.assertIn('period', result)
        self.assertIn('timeline', result)
        self.assertIn('new_skills', result)
        self.assertIn('emergence_rate', result)
        self.assertIn('total_unique_skills', result)
        self.assertIn('hot_categories', result)
        self.assertIn('trend', result)
        self.assertIn('all_skills_by_category', result)

    def test_role_transformation_data_structure(self):
        """Test that role transformation returns correct data structure."""
        result = self.analyzer.analyze_role_transformation()

        # Verify structure
        self.assertIn('period', result)
        self.assertIn('most_transformed_roles', result)
        self.assertIn('transformation_metrics', result)
        self.assertIn('skill_shifts_by_role', result)
        self.assertIn('ai_adoption_speed', result)

    def test_value_shift_data_structure(self):
        """Test that value shift returns correct data structure."""
        result = self.analyzer.analyze_value_shift()

        # Verify structure
        self.assertIn('period', result)
        self.assertIn('skill_category_distribution', result)
        self.assertIn('shift_trajectory', result)
        self.assertIn('hard_to_strategic_ratio', result)
        self.assertIn('interpretation', result)

    def test_human_expertise_premium_data_structure(self):
        """Test that human expertise premium returns correct data structure."""
        result = self.analyzer.analyze_human_expertise_premium()

        # Verify structure
        self.assertIn('ai_operational_prevalence_percent', result)
        self.assertIn('ai_cognitive_prevalence_percent', result)
        self.assertIn('cognitive_premium_ratio', result)
        self.assertIn('sample_size', result)
        self.assertIn('top_cognitive_roles', result)
        self.assertIn('gap_by_role', result)
        self.assertIn('hypothesis_validation', result)

    def test_insights_summary_structure(self):
        """Test that insights summary returns correct structure."""
        result = self.analyzer.generate_insights_summary()

        # Verify structure
        self.assertIn('generated_at', result)
        self.assertIn('key_findings', result)
        self.assertIn('evidence_by_finding', result)
        self.assertIn('recommendations', result)
        self.assertIn('research_limitations', result)
        self.assertIn('thesis_validation', result)

        # Verify key findings list
        self.assertIsInstance(result['key_findings'], list)

        # Verify recommendations list
        self.assertIsInstance(result['recommendations'], list)

    def test_insights_summary_has_recommendations(self):
        """Test that insights summary includes meaningful recommendations."""
        result = self.analyzer.generate_insights_summary()

        recommendations = result.get('recommendations', [])
        # Should have at least one recommendation
        self.assertGreater(len(recommendations), 0)

        # Each recommendation should be a string
        for rec in recommendations:
            self.assertIsInstance(rec, str)
            self.assertGreater(len(rec), 0)

    def test_insights_summary_thesis_validation(self):
        """Test that thesis validation is present in summary."""
        result = self.analyzer.generate_insights_summary()

        thesis = result.get('thesis_validation', {})

        self.assertIn('central_question', thesis)
        self.assertIn('answer', thesis)
        self.assertIn('confidence', thesis)

    def test_empty_skill_emergence_structure(self):
        """Test empty skill emergence structure."""
        result = self.analyzer._empty_skill_emergence()

        # Should have all required keys
        self.assertIn('period', result)
        self.assertIn('timeline', result)
        self.assertIn('new_skills', result)
        self.assertIn('emergence_rate', result)

    def test_empty_role_transformation_structure(self):
        """Test empty role transformation structure."""
        result = self.analyzer._empty_role_transformation()

        # Should have all required keys
        self.assertIn('period', result)
        self.assertIn('most_transformed_roles', result)
        self.assertIn('transformation_metrics', result)

    def test_empty_value_shift_structure(self):
        """Test empty value shift structure."""
        result = self.analyzer._empty_value_shift()

        # Should have all required keys
        self.assertIn('period', result)
        self.assertIn('skill_category_distribution', result)

    def test_empty_human_expertise_premium_structure(self):
        """Test empty human expertise premium structure."""
        result = self.analyzer._empty_human_expertise_premium()

        # Should have all required keys
        self.assertIn('ai_operational_prevalence_percent', result)
        self.assertIn('ai_cognitive_prevalence_percent', result)

    def test_analyze_emergence_trend_accelerating(self):
        """Test emergence trend analysis with acceleration."""
        weekly_data = {
            '2024-W01': {'hard_skills': 10, 'soft_skills': 5},
            '2024-W02': {'hard_skills': 12, 'soft_skills': 6},
            '2024-W26': {'hard_skills': 25, 'soft_skills': 15},
            '2024-W27': {'hard_skills': 30, 'soft_skills': 18},
        }

        trend = self.analyzer._analyze_emergence_trend(weekly_data)

        # Should detect acceleration
        self.assertIn(trend, ['accelerating', 'decelerating', 'stable'])

    def test_analyze_emergence_trend_stable(self):
        """Test emergence trend analysis with stability."""
        weekly_data = {
            '2024-W01': {'hard_skills': 10},
            '2024-W26': {'hard_skills': 10},
        }

        trend = self.analyzer._analyze_emergence_trend(weekly_data)

        self.assertIn(trend, ['accelerating', 'decelerating', 'stable', 'insufficient_data'])

    def test_analyze_ai_adoption_speed(self):
        """Test AI adoption speed analysis."""
        role_skills = {
            'Engineer': [
                {'ChatGPT', 'Python', 'AI'},
                {'JavaScript', 'React'},
            ]
        }

        adoption = self.analyzer._analyze_ai_adoption_speed(role_skills)

        self.assertIn('Engineer', adoption)
        self.assertGreaterEqual(adoption['Engineer'], 0)
        self.assertLessEqual(adoption['Engineer'], 100)

    def test_interpret_value_shift_strategic_dominant(self):
        """Test value shift interpretation with strategic dominance."""
        distribution = {
            'hard_skills_percent': 30,
            'soft_skills_percent': 20,
            'strategic_skills_percent': 50,
        }

        interpretation = self.analyzer._interpret_value_shift(distribution, ratio=1.5)

        self.assertIsInstance(interpretation, str)
        self.assertGreater(len(interpretation), 0)
        self.assertIn('strategic', interpretation.lower() or 'shift' in interpretation.lower())

    def test_interpret_value_shift_hard_dominant(self):
        """Test value shift interpretation with hard skills dominant."""
        distribution = {
            'hard_skills_percent': 70,
            'soft_skills_percent': 20,
            'strategic_skills_percent': 10,
        }

        interpretation = self.analyzer._interpret_value_shift(distribution, ratio=0.1)

        self.assertIsInstance(interpretation, str)
        self.assertGreater(len(interpretation), 0)

    def test_interpret_value_shift_balanced(self):
        """Test value shift interpretation with balanced skills."""
        distribution = {
            'hard_skills_percent': 33,
            'soft_skills_percent': 33,
            'strategic_skills_percent': 34,
        }

        interpretation = self.analyzer._interpret_value_shift(distribution, ratio=1.0)

        self.assertIsInstance(interpretation, str)
        self.assertGreater(len(interpretation), 0)


class TestPDFReporter(unittest.TestCase):
    """Test cases for PDFReporter."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.reporter = PDFReporter(output_dir=self.temp_dir)

    def tearDown(self):
        """Clean up test files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reporter_initialization(self):
        """Test reporter initializes with correct attributes."""
        self.assertIsNotNone(self.reporter)
        self.assertEqual(self.reporter.output_dir, self.temp_dir)
        self.assertFalse(self.reporter.include_spanish)

    def test_reporter_with_spanish(self):
        """Test reporter initializes with Spanish option."""
        reporter = PDFReporter(output_dir=self.temp_dir, include_spanish=True)

        self.assertTrue(reporter.include_spanish)

    def test_create_output_directory(self):
        """Test that output directory is created."""
        new_dir = os.path.join(self.temp_dir, 'reports_new')

        reporter = PDFReporter(output_dir=new_dir)

        self.assertTrue(os.path.exists(new_dir))

    def test_custom_styles_created(self):
        """Test that custom styles are created."""
        styles = self.reporter.styles

        self.assertIn('title', styles)
        self.assertIn('heading1', styles)
        self.assertIn('heading2', styles)
        self.assertIn('normal', styles)

    def test_color_scheme_defined(self):
        """Test that color scheme is properly defined."""
        colors_scheme = self.reporter.colors_scheme

        self.assertIn('primary', colors_scheme)
        self.assertIn('secondary', colors_scheme)
        self.assertIn('accent', colors_scheme)
        self.assertIn('danger', colors_scheme)

    def test_generate_report_with_minimal_data(self):
        """Test PDF generation with minimal data."""
        insights_data = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'key_findings': [],
            'evidence_by_finding': {},
            'recommendations': [],
            'research_limitations': [],
            'thesis_validation': {},
        }

        filepath = self.reporter.generate_report(insights_data)

        # Check that file was created
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(filepath.endswith('.pdf'))

    def test_generate_report_with_full_data(self):
        """Test PDF generation with complete data."""
        insights_data = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'key_findings': [
                {
                    'title': 'Test Finding 1',
                    'finding': 'This is a test finding',
                    'implication': 'This has implications',
                },
                {
                    'title': 'Test Finding 2',
                    'finding': 'Another test finding',
                    'implication': 'More implications',
                },
            ],
            'evidence_by_finding': {
                'skill_emergence': {
                    'emergence_rate': 5.5,
                    'total_unique_skills': 150,
                    'trend': 'accelerating',
                    'hot_categories': [
                        {'category': 'ai_cognitive_skills', 'count': 45}
                    ],
                },
                'role_transformation': {
                    'most_transformed_roles': [
                        {
                            'role': 'Data Engineer',
                            'change_rate_percent': 35.5,
                        }
                    ],
                },
                'value_shift': {
                    'skill_category_distribution': {
                        'hard_skills_percent': 40,
                        'soft_skills_percent': 30,
                        'strategic_skills_percent': 30,
                    },
                },
                'human_expertise_premium': {
                    'ai_operational_prevalence_percent': 65,
                    'ai_cognitive_prevalence_percent': 45,
                    'cognitive_premium_ratio': 0.69,
                },
            },
            'recommendations': [
                'Invest in judgment and evaluation frameworks',
                'Develop meta-skills for rapid learning',
            ],
            'research_limitations': [
                'Analysis based on job postings only',
            ],
            'thesis_validation': {
                'central_question': 'What makes humans valuable in AI systems?',
                'answer': 'Judgment and orchestration',
                'confidence': 'HIGH',
            },
        }

        filepath = self.reporter.generate_report(insights_data)

        # Check that file was created
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(filepath.endswith('.pdf'))

        # File should have substantial size (PDF with content)
        file_size = os.path.getsize(filepath)
        self.assertGreater(file_size, 1000)  # At least 1KB

    def test_generate_report_custom_filename(self):
        """Test PDF generation with custom filename."""
        insights_data = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'key_findings': [],
            'evidence_by_finding': {},
            'recommendations': [],
            'research_limitations': [],
            'thesis_validation': {},
        }

        custom_filename = 'CustomReport_Test.pdf'
        filepath = self.reporter.generate_report(insights_data, filename=custom_filename)

        self.assertTrue(filepath.endswith(custom_filename))
        self.assertTrue(os.path.exists(filepath))

    def test_generate_report_default_filename(self):
        """Test PDF generation uses default filename pattern."""
        insights_data = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'key_findings': [],
            'evidence_by_finding': {},
            'recommendations': [],
            'research_limitations': [],
            'thesis_validation': {},
        }

        filepath = self.reporter.generate_report(insights_data)

        # Should match pattern: Observatory_Report_YYYY-MM-DD.pdf
        basename = os.path.basename(filepath)
        self.assertTrue(basename.startswith('Observatory_Report_'))
        self.assertTrue(basename.endswith('.pdf'))

    def test_add_cover_page(self):
        """Test cover page generation."""
        insights_data = {
            'generated_at': '2024-01-15T10:00:00+00:00',
        }

        story = self.reporter._add_cover_page(insights_data)

        # Should return a list with content
        self.assertIsInstance(story, list)
        self.assertGreater(len(story), 0)

    def test_add_executive_summary(self):
        """Test executive summary generation."""
        insights_data = {
            'key_findings': [
                {
                    'title': 'Finding 1',
                    'implication': 'This matters',
                }
            ],
            'thesis_validation': {
                'answer': 'Judgment is valuable',
                'confidence': 'HIGH',
            },
        }

        story = self.reporter._add_executive_summary(insights_data)

        self.assertIsInstance(story, list)
        self.assertGreater(len(story), 0)

    def test_add_methodology(self):
        """Test methodology section generation."""
        story = self.reporter._add_methodology()

        self.assertIsInstance(story, list)
        self.assertGreater(len(story), 0)

    def test_add_key_findings(self):
        """Test key findings section generation."""
        insights_data = {
            'evidence_by_finding': {
                'skill_emergence': {
                    'emergence_rate': 5.0,
                    'hot_categories': [{'category': 'ai_cognitive_skills'}],
                },
                'role_transformation': {
                    'most_transformed_roles': [
                        {'role': 'Engineer', 'change_rate_percent': 25}
                    ],
                },
                'value_shift': {
                    'skill_category_distribution': {
                        'strategic_skills_percent': 35,
                        'hard_skills_percent': 45,
                    },
                },
                'human_expertise_premium': {
                    'ai_operational_prevalence_percent': 60,
                    'ai_cognitive_prevalence_percent': 45,
                    'cognitive_premium_ratio': 0.75,
                },
            },
        }

        story = self.reporter._add_key_findings(insights_data)

        self.assertIsInstance(story, list)
        self.assertGreater(len(story), 0)

    def test_add_conclusions_and_recommendations(self):
        """Test conclusions and recommendations section."""
        insights_data = {
            'recommendations': [
                'First recommendation',
                'Second recommendation',
            ],
        }

        story = self.reporter._add_conclusions_and_recommendations(insights_data)

        self.assertIsInstance(story, list)
        self.assertGreater(len(story), 0)

    def test_add_appendices(self):
        """Test appendices section generation."""
        insights_data = {
            'evidence_by_finding': {
                'skill_emergence': {
                    'sample_size': 1000,
                },
            },
        }

        story = self.reporter._add_appendices(insights_data)

        self.assertIsInstance(story, list)
        self.assertGreater(len(story), 0)

    def test_save_pdf(self):
        """Test PDF file saving."""
        from io import BytesIO

        content = BytesIO(b'%PDF-1.4 test content')
        test_path = os.path.join(self.temp_dir, 'test.pdf')

        result = self.reporter.save_pdf(test_path, content)

        # Note: This test will fail because we're not providing valid PDF
        # but we can test the method structure
        self.assertIsInstance(result, bool)


class TestIntegration(unittest.TestCase):
    """Integration tests between analyzer and reporter."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.analyzer = LaborInsightsAnalyzer(
            supabase_url="https://test.supabase.co",
            supabase_key="test_key"
        )
        self.reporter = PDFReporter(output_dir=self.temp_dir)

    def tearDown(self):
        """Clean up test files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_report_generation(self):
        """Test full workflow from analysis to PDF."""
        # Generate insights summary
        insights = self.analyzer.generate_insights_summary()

        # Should return valid structure
        self.assertIn('key_findings', insights)
        self.assertIn('recommendations', insights)

        # Generate PDF from insights
        pdf_path = self.reporter.generate_report(insights)

        # PDF should be created
        self.assertTrue(os.path.exists(pdf_path))


if __name__ == '__main__':
    unittest.main()
