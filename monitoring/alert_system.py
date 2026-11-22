#!/usr/bin/env python3
"""Alert system for monitoring pipeline thresholds and health metrics."""

import logging
import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

from pipeline.config import Config
from pipeline.loader import SupabaseLoader
from validation.drift_detector import DriftDetector

logger = logging.getLogger(__name__)


class AlertManager:
    """Monitor and alert on pipeline performance thresholds."""

    # Default alert thresholds
    DEFAULT_THRESHOLDS = {
        'confidence_threshold': 0.75,
        'approval_rate_threshold': 0.80,
        'drift_indicator_limit': 2,
        'cron_failure_limit': 1,
    }

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        alert_log_path: Optional[Path] = None,
        thresholds: Optional[Dict[str, float]] = None
    ):
        """
        Initialize the alert manager.

        Args:
            supabase_url: Supabase URL
            supabase_key: Supabase API key
            alert_log_path: Path to store alert history
            thresholds: Custom threshold values
        """
        self.loader = SupabaseLoader(supabase_url, supabase_key)
        self.drift_detector = DriftDetector()
        self.config = Config
        self.tz = timezone.utc

        # Setup alert log
        self.alert_log_path = alert_log_path or Config.LOG_PATH / 'alerts.jsonl'
        self.alert_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Setup thresholds
        self.thresholds = {**self.DEFAULT_THRESHOLDS}
        if thresholds:
            self.thresholds.update(thresholds)

        # Alert history for pattern detection
        self.alert_history = self._load_alert_history()

    def check_all_thresholds(self) -> List[Dict[str, Any]]:
        """
        Run all threshold checks and return any triggered alerts.

        Returns:
            List of alert dictionaries
        """
        alerts = []

        # Check each threshold
        confidence_alerts = self.check_confidence_threshold()
        alerts.extend(confidence_alerts)

        approval_alerts = self.check_approval_rate()
        alerts.extend(approval_alerts)

        drift_alerts = self.check_drift_threshold()
        alerts.extend(drift_alerts)

        # Log any alerts
        for alert in alerts:
            self._log_alert(alert)
            logger.warning(f"ALERT: {alert['alert_type']} - {alert['message']}")

        return alerts

    def check_confidence_threshold(self) -> List[Dict[str, Any]]:
        """
        Check if classification confidence drops below threshold.

        Returns:
            List of confidence alerts (empty if threshold not breached)
        """
        if not self.loader.client:
            logger.error("Supabase client not initialized")
            return []

        try:
            # Fetch recent classifications
            response = self.loader.client.table('vacantes').select(
                'classification, classified_at'
            ).not_('classification', 'is', None).order(
                'classified_at', desc=True
            ).limit(50).execute()

            classifications = response.data or []

            if not classifications:
                return []

            # Calculate average confidence from recent classifications
            confidences = []
            for v in classifications:
                if v.get('classification'):
                    cls = v['classification']
                    if isinstance(cls, dict):
                        confidence = cls.get('confidence', 0)
                    else:
                        try:
                            cls_dict = json.loads(cls) if isinstance(cls, str) else cls
                            confidence = cls_dict.get('confidence', 0)
                        except (json.JSONDecodeError, TypeError):
                            confidence = 0

                    confidences.append(confidence)

            if not confidences:
                return []

            avg_confidence = sum(confidences) / len(confidences)
            threshold = self.thresholds['confidence_threshold']

            if avg_confidence < threshold:
                alert = {
                    'alert_type': 'CONFIDENCE_BELOW_THRESHOLD',
                    'severity': 'HIGH',
                    'message': f"Classification confidence {avg_confidence:.4f} below threshold {threshold}",
                    'current_value': avg_confidence,
                    'threshold': threshold,
                    'samples': len(confidences),
                    'triggered_at': datetime.now(self.tz).isoformat(),
                }
                return [alert]

            return []

        except Exception as e:
            logger.error(f"Error checking confidence threshold: {e}")
            return []

    def check_approval_rate(self) -> List[Dict[str, Any]]:
        """
        Check if batch approval rate drops below threshold.

        Returns:
            List of approval rate alerts
        """
        if not self.loader.client:
            logger.error("Supabase client not initialized")
            return []

        try:
            # Fetch recent validations
            response = self.loader.client.table('classification_audit').select(
                'approved, validated_at'
            ).order('validated_at', desc=True).limit(100).execute()

            validations = response.data or []

            if not validations:
                return []

            approved = sum(1 for v in validations if v.get('approved'))
            approval_rate = approved / len(validations)
            threshold = self.thresholds['approval_rate_threshold']

            if approval_rate < threshold:
                alert = {
                    'alert_type': 'APPROVAL_RATE_BELOW_THRESHOLD',
                    'severity': 'HIGH',
                    'message': f"Approval rate {approval_rate*100:.1f}% below threshold {threshold*100:.1f}%",
                    'current_value': approval_rate,
                    'threshold': threshold,
                    'approved': approved,
                    'total': len(validations),
                    'triggered_at': datetime.now(self.tz).isoformat(),
                }
                return [alert]

            return []

        except Exception as e:
            logger.error(f"Error checking approval rate: {e}")
            return []

    def check_drift_threshold(self) -> List[Dict[str, Any]]:
        """
        Check if drift indicators exceed threshold.

        Returns:
            List of drift detection alerts
        """
        if not self.loader.client:
            logger.error("Supabase client not initialized")
            return []

        try:
            # Fetch recent classifications
            response = self.loader.client.table('vacantes').select(
                'classification, classified_at'
            ).not_('classification', 'is', None).order(
                'classified_at', desc=True
            ).limit(100).execute()

            classifications = response.data or []

            if not classifications:
                return []

            # Detect drift
            drift_result = self.drift_detector.detect_drift(1, classifications)
            drift_indicators = drift_result.get('indicators', [])
            limit = self.thresholds['drift_indicator_limit']

            if len(drift_indicators) > limit:
                alert = {
                    'alert_type': 'DRIFT_INDICATORS_EXCEEDED',
                    'severity': 'MEDIUM',
                    'message': f"Detected {len(drift_indicators)} drift indicators (limit: {limit})",
                    'drift_count': len(drift_indicators),
                    'limit': limit,
                    'indicators': drift_indicators,
                    'triggered_at': datetime.now(self.tz).isoformat(),
                }
                return [alert]

            return []

        except Exception as e:
            logger.error(f"Error checking drift threshold: {e}")
            return []

    def check_cron_health(self, last_run_log: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Check if cron job failed (exit code != 0).

        Args:
            last_run_log: Path to cron job output log

        Returns:
            List of cron health alerts
        """
        if not last_run_log:
            logger.debug("No cron log path provided, skipping cron health check")
            return []

        try:
            log_path = Path(last_run_log)

            if not log_path.exists():
                logger.warning(f"Cron log not found: {log_path}")
                return []

            content = log_path.read_text().strip()

            # Simple check: if last line contains error/failure, mark as failed
            is_failed = any(keyword in content.lower() for keyword in [
                'error', 'failed', 'exception', 'traceback', 'exit code: 1'
            ])

            if is_failed:
                alert = {
                    'alert_type': 'CRON_JOB_FAILED',
                    'severity': 'CRITICAL',
                    'message': f"Cron job failed. Check log: {last_run_log}",
                    'log_path': str(log_path),
                    'triggered_at': datetime.now(self.tz).isoformat(),
                }
                return [alert]

            return []

        except Exception as e:
            logger.error(f"Error checking cron health: {e}")
            return []

    def get_alert_summary(self, hours_back: int = 24) -> Dict[str, Any]:
        """
        Get summary of alerts from the past N hours.

        Args:
            hours_back: Number of hours to look back

        Returns:
            Summary of alerts and trends
        """
        recent_alerts = self._get_recent_alerts(hours_back)

        summary = {
            'period_hours': hours_back,
            'total_alerts': len(recent_alerts),
            'critical': sum(1 for a in recent_alerts if a.get('severity') == 'CRITICAL'),
            'high': sum(1 for a in recent_alerts if a.get('severity') == 'HIGH'),
            'medium': sum(1 for a in recent_alerts if a.get('severity') == 'MEDIUM'),
            'alert_types': {},
        }

        for alert in recent_alerts:
            alert_type = alert.get('alert_type', 'UNKNOWN')
            summary['alert_types'][alert_type] = summary['alert_types'].get(alert_type, 0) + 1

        return summary

    def _log_alert(self, alert: Dict[str, Any]) -> bool:
        """
        Log alert to file.

        Args:
            alert: Alert dictionary

        Returns:
            True if logged successfully
        """
        try:
            with open(self.alert_log_path, 'a') as f:
                f.write(json.dumps(alert) + '\n')
            return True
        except Exception as e:
            logger.error(f"Error logging alert: {e}")
            return False

    def _load_alert_history(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """
        Load alert history from log file.

        Args:
            limit: Maximum number of alerts to load

        Returns:
            List of alert dictionaries
        """
        if not self.alert_log_path.exists():
            return []

        try:
            alerts = []
            with open(self.alert_log_path, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            alerts.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

            return alerts[-limit:]  # Return last N alerts

        except Exception as e:
            logger.error(f"Error loading alert history: {e}")
            return []

    def _get_recent_alerts(self, hours_back: int = 24) -> List[Dict[str, Any]]:
        """
        Get alerts from the past N hours.

        Args:
            hours_back: Number of hours to look back

        Returns:
            List of recent alerts
        """
        cutoff = datetime.now(self.tz).timestamp() - (hours_back * 3600)
        recent = []

        for alert in self.alert_history:
            try:
                alert_time = datetime.fromisoformat(
                    alert.get('triggered_at', '')
                ).timestamp()
                if alert_time > cutoff:
                    recent.append(alert)
            except (ValueError, TypeError):
                pass

        return recent
