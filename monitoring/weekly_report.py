#!/usr/bin/env python3
"""Weekly report generation for pipeline monitoring and health checks."""

import logging
import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, timezone
from collections import Counter

from pipeline.config import Config
from pipeline.loader import SupabaseLoader
from pipeline.db_utils import fetch_all_paginated
from validation.drift_detector import DriftDetector

logger = logging.getLogger(__name__)


class WeeklyReportGenerator:
    """Generate comprehensive weekly health reports for the Observatory Pipeline."""

    def __init__(self, supabase_url: Optional[str] = None, supabase_key: Optional[str] = None):
        """
        Initialize the weekly report generator.

        Args:
            supabase_url: Supabase URL (defaults to config)
            supabase_key: Supabase API key (defaults to config)
        """
        self.loader = SupabaseLoader(supabase_url, supabase_key)
        self.drift_detector = DriftDetector()
        self.config = Config
        self.tz = timezone.utc

    def collect_weekly_metrics(self, days_back: int = 7) -> Dict[str, Any]:
        """
        Collect all metrics from the past week.

        Args:
            days_back: Number of days to look back (default 7 for weekly)

        Returns:
            Dictionary with aggregated weekly metrics
        """
        if not self.loader.client:
            logger.error("Supabase client not initialized")
            return self._empty_metrics()

        try:
            # Calculate date range
            end_date = datetime.now(self.tz)
            start_date = end_date - timedelta(days=days_back)
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()

            metrics = {
                'period': {
                    'start': start_iso,
                    'end': end_iso,
                    'days': days_back
                },
                'vacancies': {},
                'classification': {},
                'validation': {},
                'new_keywords': [],
                'new_tools': [],
                'drift_indicators': []
            }

            # 1. Fetch vacancies from past week (PAGINATED)
            vacancies = fetch_all_paginated(
                lambda: self.loader.client.table('vacantes').select('*')
                    .gte('created_at', start_iso).lte('created_at', end_iso)
            )
            metrics['vacancies'] = {
                'total_processed': len(vacancies),
                'by_source': self._count_by_field(vacancies, 'source'),
                'by_country': self._count_by_field(vacancies, 'country'),
            }

            # 2. Classification metrics
            classified = [v for v in vacancies if v.get('classification')]
            unclassified = [v for v in vacancies if not v.get('classification')]

            if classified:
                classification_data = [v['classification'] for v in classified if v.get('classification')]
                metrics['classification'] = {
                    'total_classified': len(classified),
                    'total_unclassified': len(unclassified),
                    'classification_rate': len(classified) / len(vacancies) * 100 if vacancies else 0,
                    'avg_confidence': sum(c.get('confidence', 0) for c in classification_data) / len(classification_data),
                    'confidence_distribution': self._get_confidence_distribution(classification_data),
                    'role_families': self._count_by_field(classification_data, 'role_family'),
                    'ai_level_distribution': self._get_ai_level_distribution(classification_data),
                }

                # Extract new tools detected
                all_tools = []
                for c in classification_data:
                    tools = c.get('ai_tools_detected', [])
                    if isinstance(tools, list):
                        all_tools.extend(tools)
                    elif isinstance(tools, str):
                        try:
                            tools_list = json.loads(tools)
                            all_tools.extend(tools_list if isinstance(tools_list, list) else [])
                        except (json.JSONDecodeError, TypeError):
                            pass

                metrics['new_tools'] = list(set(all_tools))  # Unique tools

            # 3. Validation metrics (from classification_audit if available) - PAGINATED
            try:
                validations = fetch_all_paginated(
                    lambda: self.loader.client.table('classification_audit').select('*')
                        .gte('validated_at', start_iso).lte('validated_at', end_iso)
                )
                if validations:
                    approved = sum(1 for v in validations if v.get('approved'))
                    metrics['validation'] = {
                        'total_validated': len(validations),
                        'approved': approved,
                        'needs_review': len(validations) - approved,
                        'approval_rate': approved / len(validations) * 100 if validations else 0,
                        'avg_adjusted_confidence': sum(v.get('adjusted_confidence', 0) for v in validations) / len(validations),
                    }
            except Exception as e:
                logger.warning(f"Could not fetch validation metrics: {e}")

            # 4. Detect drift indicators
            if classified:
                drift_result = self.drift_detector.detect_drift(1, classified)
                metrics['drift_indicators'] = drift_result.get('indicators', [])

            logger.info(f"Weekly metrics collected for {days_back} days")
            return metrics

        except Exception as e:
            logger.error(f"Error collecting weekly metrics: {e}")
            return self._empty_metrics()

    def generate_report(self, include_recommendations: bool = True) -> Dict[str, Any]:
        """
        Generate the complete weekly report.

        Args:
            include_recommendations: Include action recommendations (default True)

        Returns:
            Dictionary containing the full weekly report
        """
        metrics = self.collect_weekly_metrics()

        report = {
            'report_type': 'WEEKLY_HEALTH_REPORT',
            'generated_at': datetime.now(self.tz).isoformat(),
            'period': metrics['period'],
            'summary': self._generate_summary(metrics),
            'detailed_metrics': metrics,
            'quality_gates': self._evaluate_quality_gates(metrics),
        }

        if include_recommendations:
            report['recommendations'] = self._generate_recommendations(metrics)

        logger.info("Weekly report generated successfully")
        return report

    def _generate_summary(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Generate executive summary from metrics."""
        vac_metrics = metrics['vacancies']
        class_metrics = metrics['classification']
        val_metrics = metrics['validation']

        summary = {
            'total_vacancies_processed': vac_metrics.get('total_processed', 0),
            'classification_rate': class_metrics.get('classification_rate', 0),
            'average_confidence': class_metrics.get('avg_confidence', 0),
            'approval_rate': val_metrics.get('approval_rate', 0),
            'new_ai_tools_detected': len(metrics.get('new_tools', [])),
            'drift_indicators_found': len(metrics.get('drift_indicators', [])),
            'health_status': self._determine_health_status(metrics),
        }

        return summary

    def _determine_health_status(self, metrics: Dict[str, Any]) -> str:
        """Determine overall pipeline health status."""
        issues = 0

        if metrics['classification'].get('classification_rate', 0) < 80:
            issues += 1
        if metrics['classification'].get('avg_confidence', 0) < 0.75:
            issues += 1
        if metrics['validation'].get('approval_rate', 0) < 80:
            issues += 1
        if len(metrics.get('drift_indicators', [])) > 2:
            issues += 1

        if issues == 0:
            return "HEALTHY"
        elif issues == 1:
            return "WARNING"
        elif issues <= 2:
            return "ALERT"
        else:
            return "CRITICAL"

    def _evaluate_quality_gates(self, metrics: Dict[str, Any]) -> Dict[str, bool]:
        """Evaluate pipeline quality gates."""
        gates = {
            'classification_rate_gate': metrics['classification'].get('classification_rate', 0) >= 80,
            'confidence_threshold_gate': metrics['classification'].get('avg_confidence', 0) >= 0.75,
            'approval_rate_gate': metrics['validation'].get('approval_rate', 0) >= 80,
            'drift_detection_gate': len(metrics.get('drift_indicators', [])) <= 2,
        }

        gates['all_gates_passed'] = all(gates.values())
        return gates

    def _generate_recommendations(self, metrics: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations based on metrics."""
        recommendations = []

        if metrics['classification'].get('classification_rate', 0) < 80:
            recommendations.append(
                "Classification rate below 80%. Review unclassified vacancies and improve classification pipeline."
            )

        if metrics['classification'].get('avg_confidence', 0) < 0.75:
            recommendations.append(
                "Average confidence below 0.75. Consider retraining model or adjusting confidence thresholds."
            )

        if metrics['validation'].get('approval_rate', 0) < 80:
            recommendations.append(
                "Approval rate below 80%. Review validation rules and investigate rejected classifications."
            )

        if len(metrics.get('drift_indicators', [])) > 2:
            recommendations.append(
                f"Detected {len(metrics['drift_indicators'])} drift indicators. Manual review recommended."
            )

        if metrics.get('new_tools'):
            recommendations.append(
                f"New AI tools detected: {', '.join(metrics['new_tools'])}. Update tool database."
            )

        if not recommendations:
            recommendations.append("Pipeline operating normally. Continue monitoring.")

        return recommendations

    def format_report_as_markdown(self, report: Dict[str, Any]) -> str:
        """
        Format the report as readable markdown.

        Args:
            report: The generated report dictionary

        Returns:
            Markdown-formatted report string
        """
        md = []
        md.append("# Weekly Observatory Pipeline Health Report\n")

        # Header info
        md.append(f"**Report Generated:** {report['generated_at']}\n")
        md.append(f"**Period:** {report['period']['start']} to {report['period']['end']}\n")

        # Summary
        summary = report['summary']
        md.append("## Executive Summary\n")
        md.append(f"- **Health Status:** {summary['health_status']}\n")
        md.append(f"- **Vacancies Processed:** {summary['total_vacancies_processed']}\n")
        md.append(f"- **Classification Rate:** {summary['classification_rate']:.2f}%\n")
        md.append(f"- **Average Confidence:** {summary['average_confidence']:.4f}\n")
        md.append(f"- **Approval Rate:** {summary['approval_rate']:.2f}%\n")
        md.append(f"- **New AI Tools Detected:** {summary['new_ai_tools_detected']}\n")
        md.append(f"- **Drift Indicators:** {summary['drift_indicators_found']}\n\n")

        # Quality Gates
        gates = report['quality_gates']
        md.append("## Quality Gates\n")
        for gate, passed in gates.items():
            if gate != 'all_gates_passed':
                status = "✓ PASS" if passed else "✗ FAIL"
                md.append(f"- {gate}: {status}\n")

        md.append(f"\n**Overall:** {'✓ All gates passed' if gates['all_gates_passed'] else '✗ Some gates failed'}\n\n")

        # Detailed metrics
        metrics = report['detailed_metrics']
        md.append("## Detailed Metrics\n")
        md.append("### Vacancies\n")
        vac = metrics['vacancies']
        md.append(f"- Total Processed: {vac.get('total_processed', 0)}\n")
        if vac.get('by_source'):
            md.append("- By Source:\n")
            for source, count in vac['by_source'].items():
                md.append(f"  - {source}: {count}\n")

        md.append("\n### Classification\n")
        cls = metrics['classification']
        md.append(f"- Classified: {cls.get('total_classified', 0)}\n")
        md.append(f"- Unclassified: {cls.get('total_unclassified', 0)}\n")
        md.append(f"- Average Confidence: {cls.get('avg_confidence', 0):.4f}\n")

        # Recommendations
        md.append("\n## Recommendations\n")
        for i, rec in enumerate(report.get('recommendations', []), 1):
            md.append(f"{i}. {rec}\n")

        return "".join(md)

    def send_email(self, report: Dict[str, Any], recipients: List[str]) -> bool:
        """
        Send the report via email.

        Args:
            report: The generated report dictionary
            recipients: List of email addresses

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            # This is a stub - actual implementation would require email config
            md_report = self.format_report_as_markdown(report)

            logger.info(f"Email report prepared for {len(recipients)} recipients")
            logger.debug(f"Email body:\n{md_report}")

            # TODO: Implement actual email sending with SMTP
            return True

        except Exception as e:
            logger.error(f"Error sending email report: {e}")
            return False

    @staticmethod
    def _count_by_field(data: List[Dict], field: str) -> Dict[str, int]:
        """Count occurrences of values in a field."""
        counter = Counter()
        for item in data:
            value = item.get(field)
            if value:
                counter[value] += 1
        return dict(counter)

    @staticmethod
    def _get_confidence_distribution(classifications: List[Dict]) -> Dict[str, int]:
        """Get distribution of confidence scores."""
        bins = {
            '0.0-0.2': 0,
            '0.2-0.4': 0,
            '0.4-0.6': 0,
            '0.6-0.8': 0,
            '0.8-1.0': 0,
        }

        for c in classifications:
            confidence = c.get('confidence', 0)
            if confidence <= 0.2:
                bins['0.0-0.2'] += 1
            elif confidence <= 0.4:
                bins['0.2-0.4'] += 1
            elif confidence <= 0.6:
                bins['0.4-0.6'] += 1
            elif confidence <= 0.8:
                bins['0.6-0.8'] += 1
            else:
                bins['0.8-1.0'] += 1

        return bins

    @staticmethod
    def _get_ai_level_distribution(classifications: List[Dict]) -> Dict[str, int]:
        """Get distribution of AI levels."""
        distribution = Counter()
        for c in classifications:
            level = c.get('ai_level', 0)
            distribution[f'Level {level}'] += 1
        return dict(distribution)

    @staticmethod
    def _empty_metrics() -> Dict[str, Any]:
        """Return empty metrics structure."""
        return {
            'period': {
                'start': datetime.now(timezone.utc).isoformat(),
                'end': datetime.now(timezone.utc).isoformat(),
                'days': 7
            },
            'vacancies': {'total_processed': 0},
            'classification': {'total_classified': 0, 'total_unclassified': 0},
            'validation': {'total_validated': 0},
            'new_keywords': [],
            'new_tools': [],
            'drift_indicators': []
        }
