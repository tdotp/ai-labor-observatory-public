#!/usr/bin/env python3
"""Batch validation workflow for quality gates"""
import json
import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class BatchValidator:
    def __init__(self, batch_number: int, batch_size: int):
        self.batch_number = batch_number
        self.batch_size = batch_size
        self.validations = []

    def validate_vacancy(self, vacancy: Dict, classification: Dict) -> Dict:
        """Validate single classification against vacancy"""

        issues = []
        confidence_adjustments = []

        # Rule 1: Title match with role_family
        title_lower = vacancy['raw_title'].lower()
        role_family = classification.get('role_family', '')

        if role_family == 'creatividad_diseno':
            role_keywords = ['art director', 'creative director', 'graphic', 'designer']
            if not any(k in title_lower for k in role_keywords):
                issues.append(f"Role family mismatch: {role_family} not in title '{vacancy['raw_title']}'")
                confidence_adjustments.append(-0.15)

        # Rule 2: AI level validation
        ai_level = classification.get('ai_level', 0)
        has_explicit_ai = any(tool in vacancy['raw_description'].lower()
                             for tool in ['chatgpt', 'claude', 'gemini', 'midjourney', 'firefly'])

        if ai_level >= 2 and not has_explicit_ai:
            issues.append(f"AI level {ai_level} but no explicit AI tools found")
            confidence_adjustments.append(-0.20)

        elif ai_level == 0 and has_explicit_ai:
            issues.append(f"AI level 0 but explicit AI tools found")
            confidence_adjustments.append(-0.25)

        # Rule 3: Confidence score validation
        confidence = classification.get('confidence', 0)
        if confidence > 0.9 and issues:
            issues.append(f"Confidence {confidence} too high given issues")
            confidence_adjustments.append(-0.10)

        adjusted_confidence = max(0.1, confidence + sum(confidence_adjustments))

        return {
            'vacancy_id': vacancy.get('id'),
            'classification': classification,
            'issues': issues,
            'approved': len(issues) == 0,
            'confidence_adjustment': sum(confidence_adjustments),
            'adjusted_confidence': adjusted_confidence,
            'validated_at': datetime.now().isoformat()
        }

    def batch_report(self, validations: List[Dict]) -> Dict:
        """Generate batch validation report"""

        approved = sum(1 for v in validations if v['approved'])
        needs_review = len(validations) - approved

        avg_confidence = sum(v['adjusted_confidence'] for v in validations) / len(validations)

        return {
            'batch_number': self.batch_number,
            'total_validated': len(validations),
            'approved': approved,
            'needs_review': needs_review,
            'approval_rate': approved / len(validations) * 100,
            'avg_confidence': avg_confidence,
            'gate_pass': approved / len(validations) >= 0.80,  # 80% approval gate
            'report_generated_at': datetime.now().isoformat()
        }
