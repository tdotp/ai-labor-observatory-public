"""Monitoring module for Observatory Pipeline.

This module provides weekly health reporting and real-time alerting capabilities
for the Observatory Pipeline, including:

- Weekly report generation with metrics and recommendations
- Alert management for threshold breaches
- Drift detection and pattern analysis
- Email integration for report distribution
"""

from monitoring.weekly_report import WeeklyReportGenerator
from monitoring.alert_system import AlertManager

__all__ = [
    'WeeklyReportGenerator',
    'AlertManager',
]

__version__ = '0.1.0'
