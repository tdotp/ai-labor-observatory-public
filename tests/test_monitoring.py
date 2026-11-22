#!/usr/bin/env python3
"""Tests for monitoring module (weekly reports and alerts)."""

import pytest
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from monitoring.weekly_report import WeeklyReportGenerator
from monitoring.alert_system import AlertManager


class TestWeeklyReportGenerator:
    """Test suite for WeeklyReportGenerator class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.generator = WeeklyReportGenerator()

    def test_weekly_report_generator_initialization(self):
        """Test WeeklyReportGenerator initialization."""
        assert self.generator.loader is not None
        assert self.generator.drift_detector is not None
        assert self.generator.config is not None

    def test_empty_metrics_structure(self):
        """Test empty metrics structure."""
        metrics = self.generator._empty_metrics()

        assert 'period' in metrics
        assert 'vacancies' in metrics
        assert 'classification' in metrics
        assert 'validation' in metrics
        assert 'new_tools' in metrics
        assert 'drift_indicators' in metrics

    def test_count_by_field(self):
        """Test counting by field."""
        data = [
            {'source': 'linkedin', 'country': 'Colombia'},
            {'source': 'indeed', 'country': 'Colombia'},
            {'source': 'linkedin', 'country': 'Argentina'},
        ]

        result = self.generator._count_by_field(data, 'source')
        assert result['linkedin'] == 2
        assert result['indeed'] == 1

        result_country = self.generator._count_by_field(data, 'country')
        assert result_country['Colombia'] == 2
        assert result_country['Argentina'] == 1

    def test_confidence_distribution(self):
        """Test confidence distribution calculation."""
        classifications = [
            {'confidence': 0.95},
            {'confidence': 0.85},
            {'confidence': 0.55},
            {'confidence': 0.35},
            {'confidence': 0.15},
        ]

        result = self.generator._get_confidence_distribution(classifications)

        assert result['0.8-1.0'] == 2
        assert result['0.6-0.8'] == 0
        assert result['0.4-0.6'] == 1
        assert result['0.2-0.4'] == 1
        assert result['0.0-0.2'] == 1

    def test_ai_level_distribution(self):
        """Test AI level distribution calculation."""
        classifications = [
            {'ai_level': 0},
            {'ai_level': 0},
            {'ai_level': 1},
            {'ai_level': 2},
            {'ai_level': 3},
            {'ai_level': 2},
        ]

        result = self.generator._get_ai_level_distribution(classifications)

        assert result['Level 0'] == 2
        assert result['Level 1'] == 1
        assert result['Level 2'] == 2
        assert result['Level 3'] == 1

    def test_determine_health_status_healthy(self):
        """Test health status determination when healthy."""
        metrics = {
            'classification': {'classification_rate': 95, 'avg_confidence': 0.85},
            'validation': {'approval_rate': 90},
            'drift_indicators': [],
        }

        status = self.generator._determine_health_status(metrics)
        assert status == "HEALTHY"

    def test_determine_health_status_warning(self):
        """Test health status determination with one issue."""
        metrics = {
            'classification': {'classification_rate': 75, 'avg_confidence': 0.85},
            'validation': {'approval_rate': 90},
            'drift_indicators': [],
        }

        status = self.generator._determine_health_status(metrics)
        assert status == "WARNING"

    def test_determine_health_status_alert(self):
        """Test health status determination with exactly 2 issues → ALERT.

        The function maps: 0 issues→HEALTHY, 1→WARNING, ≤2→ALERT, >2→CRITICAL.
        Using classification_rate<80 and avg_confidence<0.75 (2 issues) with
        approval_rate≥80 so we land in the ALERT bucket, not CRITICAL.
        """
        metrics = {
            'classification': {'classification_rate': 70, 'avg_confidence': 0.70},
            'validation': {'approval_rate': 85},
            'drift_indicators': [],
        }

        status = self.generator._determine_health_status(metrics)
        assert status == "ALERT"

    def test_determine_health_status_critical(self):
        """Test health status determination in critical state."""
        metrics = {
            'classification': {'classification_rate': 60, 'avg_confidence': 0.65},
            'validation': {'approval_rate': 70},
            'drift_indicators': [1, 2, 3],
        }

        status = self.generator._determine_health_status(metrics)
        assert status == "CRITICAL"

    def test_evaluate_quality_gates_all_pass(self):
        """Test quality gate evaluation when all pass."""
        metrics = {
            'classification': {'classification_rate': 85, 'avg_confidence': 0.80},
            'validation': {'approval_rate': 85},
            'drift_indicators': [1],
        }

        gates = self.generator._evaluate_quality_gates(metrics)

        assert gates['classification_rate_gate'] is True
        assert gates['confidence_threshold_gate'] is True
        assert gates['approval_rate_gate'] is True
        assert gates['drift_detection_gate'] is True
        assert gates['all_gates_passed'] is True

    def test_evaluate_quality_gates_some_fail(self):
        """Test quality gate evaluation with failures."""
        metrics = {
            'classification': {'classification_rate': 75, 'avg_confidence': 0.70},
            'validation': {'approval_rate': 75},
            'drift_indicators': [1, 2, 3],
        }

        gates = self.generator._evaluate_quality_gates(metrics)

        assert gates['classification_rate_gate'] is False
        assert gates['confidence_threshold_gate'] is False
        assert gates['approval_rate_gate'] is False
        assert gates['drift_detection_gate'] is False
        assert gates['all_gates_passed'] is False

    def test_generate_recommendations_empty(self):
        """Test recommendation generation when all is good."""
        metrics = {
            'classification': {'classification_rate': 90, 'avg_confidence': 0.85},
            'validation': {'approval_rate': 90},
            'drift_indicators': [],
            'new_tools': [],
        }

        recommendations = self.generator._generate_recommendations(metrics)

        assert len(recommendations) == 1
        assert "operating normally" in recommendations[0].lower()

    def test_generate_recommendations_with_issues(self):
        """Test recommendation generation with issues."""
        metrics = {
            'classification': {'classification_rate': 70, 'avg_confidence': 0.70},
            'validation': {'approval_rate': 70},
            'drift_indicators': [1, 2, 3],
            'new_tools': ['ChatGPT', 'Claude'],
        }

        recommendations = self.generator._generate_recommendations(metrics)

        assert len(recommendations) >= 3
        assert any('Classification rate' in r for r in recommendations)
        assert any('confidence' in r.lower() for r in recommendations)
        assert any('ChatGPT' in r or 'Claude' in r for r in recommendations)

    def test_format_report_as_markdown(self):
        """Test markdown report formatting."""
        report = {
            'report_type': 'WEEKLY_HEALTH_REPORT',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'period': {
                'start': '2024-01-01T00:00:00+00:00',
                'end': '2024-01-08T00:00:00+00:00',
            },
            'summary': {
                'health_status': 'HEALTHY',
                'total_vacancies_processed': 100,
                'classification_rate': 95.0,
                'average_confidence': 0.85,
                'approval_rate': 90.0,
                'new_ai_tools_detected': 2,
                'drift_indicators_found': 0,
            },
            'quality_gates': {
                'classification_rate_gate': True,
                'confidence_threshold_gate': True,
                'approval_rate_gate': True,
                'drift_detection_gate': True,
                'all_gates_passed': True,
            },
            'detailed_metrics': {
                'vacancies': {'total_processed': 100},
                'classification': {'total_classified': 95},
                'validation': {},
            },
            'recommendations': ['Continue monitoring.'],
        }

        md = self.generator.format_report_as_markdown(report)

        assert '# Weekly Observatory Pipeline Health Report' in md
        assert 'HEALTHY' in md
        assert 'Vacancies Processed:** 100' in md  # markdown bold format: **Vacancies Processed:** 100
        assert '✓ All gates passed' in md
        assert 'Continue monitoring' in md


class TestAlertManager:
    """Test suite for AlertManager class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_log = Path('/tmp/test_alerts.jsonl')
        self.alert_manager = AlertManager(alert_log_path=self.temp_log)

    def teardown_method(self):
        """Cleanup test fixtures."""
        if self.temp_log.exists():
            self.temp_log.unlink()

    def test_alert_manager_initialization(self):
        """Test AlertManager initialization."""
        assert self.alert_manager.loader is not None
        assert self.alert_manager.drift_detector is not None
        assert self.alert_manager.config is not None
        assert self.alert_manager.alert_log_path == self.temp_log

    def test_default_thresholds(self):
        """Test default thresholds are set."""
        manager = AlertManager(alert_log_path=self.temp_log)

        assert manager.thresholds['confidence_threshold'] == 0.75
        assert manager.thresholds['approval_rate_threshold'] == 0.80
        assert manager.thresholds['drift_indicator_limit'] == 2
        assert manager.thresholds['cron_failure_limit'] == 1

    def test_custom_thresholds(self):
        """Test custom thresholds override defaults."""
        custom_thresholds = {
            'confidence_threshold': 0.80,
            'approval_rate_threshold': 0.90,
        }
        manager = AlertManager(
            alert_log_path=self.temp_log,
            thresholds=custom_thresholds
        )

        assert manager.thresholds['confidence_threshold'] == 0.80
        assert manager.thresholds['approval_rate_threshold'] == 0.90
        assert manager.thresholds['drift_indicator_limit'] == 2

    def test_log_alert(self):
        """Test alert logging."""
        alert = {
            'alert_type': 'TEST_ALERT',
            'severity': 'HIGH',
            'message': 'Test alert message',
            'triggered_at': datetime.now(timezone.utc).isoformat(),
        }

        success = self.alert_manager._log_alert(alert)
        assert success is True

        with open(self.temp_log, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 1
            logged_alert = json.loads(lines[0])
            assert logged_alert['alert_type'] == 'TEST_ALERT'

    def test_load_alert_history(self):
        """Test loading alert history from log file."""
        alerts = [
            {
                'alert_type': 'ALERT_1',
                'triggered_at': datetime.now(timezone.utc).isoformat(),
            },
            {
                'alert_type': 'ALERT_2',
                'triggered_at': datetime.now(timezone.utc).isoformat(),
            },
        ]

        for alert in alerts:
            self.alert_manager._log_alert(alert)

        loaded = self.alert_manager._load_alert_history()
        assert len(loaded) == 2
        assert loaded[0]['alert_type'] == 'ALERT_1'
        assert loaded[1]['alert_type'] == 'ALERT_2'

    def test_get_alert_summary(self):
        """Test alert summary generation."""
        alerts = [
            {'alert_type': 'CRITICAL_ALERT', 'severity': 'CRITICAL', 'triggered_at': datetime.now(timezone.utc).isoformat()},
            {'alert_type': 'HIGH_ALERT', 'severity': 'HIGH', 'triggered_at': datetime.now(timezone.utc).isoformat()},
            {'alert_type': 'HIGH_ALERT', 'severity': 'HIGH', 'triggered_at': datetime.now(timezone.utc).isoformat()},
            {'alert_type': 'MEDIUM_ALERT', 'severity': 'MEDIUM', 'triggered_at': datetime.now(timezone.utc).isoformat()},
        ]

        for alert in alerts:
            self.alert_manager._log_alert(alert)

        self.alert_manager.alert_history = self.alert_manager._load_alert_history()

        summary = self.alert_manager.get_alert_summary(hours_back=24)

        assert summary['total_alerts'] == 4
        assert summary['critical'] == 1
        assert summary['high'] == 2
        assert summary['medium'] == 1
        assert summary['alert_types']['CRITICAL_ALERT'] == 1
        assert summary['alert_types']['HIGH_ALERT'] == 2

    def test_check_confidence_threshold_alert(self):
        """Test confidence threshold check that triggers alert."""
        alerts = self.alert_manager.check_confidence_threshold()

        assert isinstance(alerts, list)

    def test_check_approval_rate_alert(self):
        """Test approval rate threshold check."""
        alerts = self.alert_manager.check_approval_rate()

        assert isinstance(alerts, list)

    def test_check_drift_threshold_alert(self):
        """Test drift threshold check."""
        alerts = self.alert_manager.check_drift_threshold()

        assert isinstance(alerts, list)

    def test_check_cron_health_no_log(self):
        """Test cron health check with no log file."""
        alerts = self.alert_manager.check_cron_health(None)

        assert alerts == []

    def test_check_cron_health_success(self):
        """Test cron health check with successful run."""
        temp_cron_log = Path('/tmp/test_cron_success.log')
        temp_cron_log.write_text("Cron job completed successfully\nProcessed 100 items\n")

        alerts = self.alert_manager.check_cron_health(str(temp_cron_log))

        assert alerts == []
        temp_cron_log.unlink()

    def test_check_cron_health_failure(self):
        """Test cron health check with failed run."""
        temp_cron_log = Path('/tmp/test_cron_failure.log')
        temp_cron_log.write_text("Cron job failed\nError: Database connection timeout\nExit code: 1\n")

        alerts = self.alert_manager.check_cron_health(str(temp_cron_log))

        assert len(alerts) == 1
        assert alerts[0]['alert_type'] == 'CRON_JOB_FAILED'
        assert alerts[0]['severity'] == 'CRITICAL'

        temp_cron_log.unlink()

    def test_check_all_thresholds(self):
        """Test checking all thresholds."""
        alerts = self.alert_manager.check_all_thresholds()

        assert isinstance(alerts, list)
