#!/usr/bin/env python3
"""Tests for batch validation and drift detection"""
import pytest
from datetime import datetime
from validation.batch_validator import BatchValidator
from validation.drift_detector import DriftDetector


class TestBatchValidator:
    """Test suite for BatchValidator class"""

    def setup_method(self):
        """Setup test fixtures"""
        self.validator = BatchValidator(batch_number=1, batch_size=100)

    def test_batch_validator_initialization(self):
        """Test BatchValidator initialization"""
        assert self.validator.batch_number == 1
        assert self.validator.batch_size == 100
        assert self.validator.validations == []

    def test_validate_vacancy_perfect_match(self):
        """Test validation with perfect match - no issues"""
        vacancy = {
            'id': 'job_123',
            'raw_title': 'Senior Graphic Designer',
            'raw_description': 'Looking for graphic designer with Figma experience'
        }
        classification = {
            'role_family': 'creatividad_diseno',
            'ai_level': 0,
            'confidence': 0.95,
            'ai_tools_detected': []
        }

        result = self.validator.validate_vacancy(vacancy, classification)

        assert result['vacancy_id'] == 'job_123'
        assert result['approved'] is True
        assert result['issues'] == []
        assert result['confidence_adjustment'] == 0
        assert result['adjusted_confidence'] == 0.95
        assert 'validated_at' in result

    def test_validate_vacancy_role_family_mismatch(self):
        """Test validation with role family mismatch"""
        vacancy = {
            'id': 'job_124',
            'raw_title': 'Marketing Manager',
            'raw_description': 'Looking for marketing manager'
        }
        classification = {
            'role_family': 'creatividad_diseno',
            'ai_level': 0,
            'confidence': 0.85,
            'ai_tools_detected': []
        }

        result = self.validator.validate_vacancy(vacancy, classification)

        assert result['approved'] is False
        assert len(result['issues']) == 1
        assert 'Role family mismatch' in result['issues'][0]
        assert result['confidence_adjustment'] == -0.15
        assert result['adjusted_confidence'] == 0.70

    def test_validate_vacancy_ai_level_inflation(self):
        """Test validation detecting AI level inflation"""
        vacancy = {
            'id': 'job_125',
            'raw_title': 'Art Director',
            'raw_description': 'Looking for art director. Must have design experience.'
        }
        classification = {
            'role_family': 'creatividad_diseno',
            'ai_level': 3,
            'confidence': 0.80,
            'ai_tools_detected': []
        }

        result = self.validator.validate_vacancy(vacancy, classification)

        assert result['approved'] is False
        assert any('AI level 3 but no explicit AI tools' in issue for issue in result['issues'])
        assert result['confidence_adjustment'] == -0.20
        assert result['adjusted_confidence'] == pytest.approx(0.60)

    def test_validate_vacancy_ai_tools_present(self):
        """Test validation with explicit AI tools mentioned"""
        vacancy = {
            'id': 'job_126',
            'raw_title': 'Creative Director',
            'raw_description': 'Experience with ChatGPT and Midjourney required. Using Claude for workflow automation.'
        }
        classification = {
            'role_family': 'creatividad_diseno',
            'ai_level': 2,
            'confidence': 0.92,
            'ai_tools_detected': ['ChatGPT', 'Midjourney', 'Claude']
        }

        result = self.validator.validate_vacancy(vacancy, classification)

        assert result['approved'] is True
        assert result['issues'] == []
        assert result['adjusted_confidence'] == 0.92

    def test_validate_vacancy_missing_ai_level(self):
        """Test validation when AI level is 0 but tools are mentioned"""
        vacancy = {
            'id': 'job_127',
            'raw_title': 'Designer',
            'raw_description': 'Using Firefly and Gemini for daily tasks'
        }
        classification = {
            'role_family': 'creatividad_diseno',
            'ai_level': 0,
            'confidence': 0.88,
            'ai_tools_detected': ['Firefly', 'Gemini']
        }

        result = self.validator.validate_vacancy(vacancy, classification)

        assert result['approved'] is False
        assert any('AI level 0 but explicit AI tools' in issue for issue in result['issues'])
        assert result['confidence_adjustment'] == -0.25
        assert result['adjusted_confidence'] == 0.63

    def test_batch_report_all_approved(self):
        """Test batch report when all validations pass"""
        validations = [
            {'approved': True, 'adjusted_confidence': 0.90},
            {'approved': True, 'adjusted_confidence': 0.92},
            {'approved': True, 'adjusted_confidence': 0.88},
        ]

        report = self.validator.batch_report(validations)

        assert report['batch_number'] == 1
        assert report['total_validated'] == 3
        assert report['approved'] == 3
        assert report['needs_review'] == 0
        assert report['approval_rate'] == 100.0
        assert report['gate_pass'] is True

    def test_batch_report_some_failures(self):
        """Test batch report with some failures"""
        validations = [
            {'approved': True, 'adjusted_confidence': 0.90},
            {'approved': True, 'adjusted_confidence': 0.92},
            {'approved': False, 'adjusted_confidence': 0.65},
            {'approved': False, 'adjusted_confidence': 0.70},
        ]

        report = self.validator.batch_report(validations)

        assert report['total_validated'] == 4
        assert report['approved'] == 2
        assert report['needs_review'] == 2
        assert report['approval_rate'] == 50.0
        assert report['gate_pass'] is False

    def test_batch_report_gate_at_threshold(self):
        """Test batch report at exactly 80% approval gate"""
        validations = [
            {'approved': True, 'adjusted_confidence': 0.90},
            {'approved': True, 'adjusted_confidence': 0.92},
            {'approved': True, 'adjusted_confidence': 0.88},
            {'approved': True, 'adjusted_confidence': 0.87},
            {'approved': False, 'adjusted_confidence': 0.65},
        ]

        report = self.validator.batch_report(validations)

        assert report['approved'] == 4
        assert report['total_validated'] == 5
        assert report['approval_rate'] == 80.0
        assert report['gate_pass'] is True


class TestDriftDetector:
    """Test suite for DriftDetector class"""

    def setup_method(self):
        """Setup test fixtures"""
        self.detector = DriftDetector()

    def test_drift_detector_initialization(self):
        """Test DriftDetector initialization"""
        assert self.detector.round_data == {}

    def test_detect_drift_first_round(self):
        """Test drift detection on first round (no baseline)"""
        validations = [
            {
                'classification': {'ai_level': 1, 'ai_tools_detected': ['Claude']},
                'adjusted_confidence': 0.85
            }
        ]

        result = self.detector.detect_drift(current_round=1, validations=validations)

        assert result['drift_detected'] is False
        assert 'First round' in result['reason']
        assert result['current_metrics']['avg_ai_level'] == 1.0
        assert result['current_metrics']['ai_tools_per_vacancy'] == 1.0
        assert result['current_metrics']['avg_confidence'] == 0.85

    def test_detect_drift_second_round(self):
        """Test drift detection in subsequent rounds"""
        validations = [
            {
                'classification': {'ai_level': 1, 'ai_tools_detected': ['Claude']},
                'adjusted_confidence': 0.85
            },
            {
                'classification': {'ai_level': 1, 'ai_tools_detected': ['ChatGPT']},
                'adjusted_confidence': 0.80
            }
        ]

        result = self.detector.detect_drift(current_round=2, validations=validations)

        assert 'current_metrics' in result
        assert result['current_metrics']['avg_ai_level'] == 1.0
        assert result['current_metrics']['ai_tools_per_vacancy'] == 1.0


class TestValidationIntegration:
    """Integration tests for validation workflow"""

    def test_full_validation_workflow(self):
        """Test complete validation workflow"""
        validator = BatchValidator(batch_number=1, batch_size=5)
        detector = DriftDetector()

        vacancies = [
            {
                'id': f'job_{i}',
                'raw_title': 'Graphic Designer' if i % 2 == 0 else 'Art Director',
                'raw_description': 'Looking for designer' + (' with ChatGPT skills' if i % 3 == 0 else '')
            }
            for i in range(5)
        ]

        classifications = [
            {
                'role_family': 'creatividad_diseno',
                'ai_level': 1 if i % 3 == 0 else 0,
                'confidence': 0.85 + (i * 0.02),
                'ai_tools_detected': ['ChatGPT'] if i % 3 == 0 else []
            }
            for i in range(5)
        ]

        validations = [
            validator.validate_vacancy(vac, clf)
            for vac, clf in zip(vacancies, classifications)
        ]

        report = validator.batch_report(validations)

        assert report['total_validated'] == 5
        assert isinstance(report['gate_pass'], bool)
        assert 0 <= report['approval_rate'] <= 100

        drift = detector.detect_drift(current_round=1, validations=validations)
        assert 'current_metrics' in drift
        assert 'drift_detected' in drift
