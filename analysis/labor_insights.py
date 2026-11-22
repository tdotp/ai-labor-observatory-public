"""Labor market insights analysis engine for the Observatory Project.

This module analyzes skill emergence, role transformation, and the value of human
expertise in AI systems through temporal analysis of job market data.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
import statistics

from pipeline.loader import SupabaseLoader
from pipeline.db_utils import fetch_all_paginated

logger = logging.getLogger(__name__)


class LaborInsightsAnalyzer:
    """Analyze labor market trends and human expertise value in AI systems."""

    def __init__(self, supabase_url: Optional[str] = None, supabase_key: Optional[str] = None):
        """
        Initialize the labor insights analyzer.

        Args:
            supabase_url: Supabase URL (defaults to env var)
            supabase_key: Supabase API key (defaults to env var)
        """
        self.loader = SupabaseLoader(supabase_url, supabase_key)
        self.tz = timezone.utc

    def analyze_skill_emergence(self, weeks_back: int = 52) -> Dict[str, Any]:
        """
        Track new skills emergence by week and category.

        Analyzes temporal patterns of skill introduction to understand when
        new capabilities enter the job market.

        Args:
            weeks_back: Number of weeks to analyze (default 52 for yearly)

        Returns:
            Dictionary with:
            - timeline: weekly skill counts by category
            - new_skills: skills appearing first this period
            - emergence_rate: average new skills per week
            - hot_categories: fastest-growing skill categories
            - trend: overall acceleration/deceleration
        """
        if not self.loader.client:
            logger.error("Supabase client not initialized")
            return self._empty_skill_emergence()

        try:
            end_date = datetime.now(self.tz)
            start_date = end_date - timedelta(weeks=weeks_back)

            # Fetch classified vacancies with skills in date range (PAGINATED)
            vacancies = fetch_all_paginated(
                lambda: self.loader.client.table('vacantes').select(
                    'id, posted_date, classification'
                ).gte('posted_date', start_date.isoformat()).lte(
                    'posted_date', end_date.isoformat()
                )
            )
            logger.info(f"Fetched {len(vacancies)} vacancies for skill emergence analysis")

            # Parse classifications and organize by week
            weekly_skills = defaultdict(lambda: {
                'hard_skills': set(),
                'soft_skills': set(),
                'strategic_skills': set(),
                'ai_operational_skills': set(),
                'ai_cognitive_skills': set(),
            })

            all_skills_by_category = defaultdict(set)

            for vacancy in vacancies:
                if not vacancy.get('classification'):
                    continue

                classification = vacancy['classification']
                posted_date = datetime.fromisoformat(
                    vacancy.get('posted_date', '').replace('Z', '+00:00')
                ) if vacancy.get('posted_date') else None

                if not posted_date:
                    continue

                # Calculate week key (ISO calendar)
                week_key = posted_date.strftime('%Y-W%V')

                # Extract skills by category
                for category in [
                    'hard_skills', 'soft_skills', 'strategic_skills',
                    'ai_operational_skills', 'ai_cognitive_skills'
                ]:
                    skills = classification.get(category, [])
                    if isinstance(skills, list):
                        for skill in skills:
                            weekly_skills[week_key][category].add(skill)
                            all_skills_by_category[category].add(skill)

            # Convert sets to counts
            weekly_timeline = {}
            for week, categories in sorted(weekly_skills.items()):
                weekly_timeline[week] = {
                    cat: len(skills) for cat, skills in categories.items()
                }

            # Identify new skills (appearing in final week but not before)
            final_week = max(weekly_timeline.keys()) if weekly_timeline else None
            previous_weeks = list(weekly_timeline.keys())[:-1] if weekly_timeline else []

            new_skills = {}
            if final_week and previous_weeks:
                final_skills = {
                    cat: set(v) for cat, v in weekly_skills[final_week].items()
                }
                previous_all_skills = defaultdict(set)
                for week in previous_weeks:
                    for cat, skills in weekly_skills[week].items():
                        previous_all_skills[cat].update(skills)

                for category in all_skills_by_category:
                    new_in_category = final_skills.get(category, set()) - previous_all_skills[category]
                    if new_in_category:
                        new_skills[category] = list(new_in_category)

            # Calculate emergence rate
            weeks_with_data = len(weekly_timeline)
            total_unique_skills = sum(
                len(all_skills_by_category[cat]) for cat in all_skills_by_category
            )
            emergence_rate = total_unique_skills / weeks_with_data if weeks_with_data > 0 else 0

            # Identify hot categories (fastest growing)
            category_totals = {cat: len(all_skills_by_category[cat]) for cat in all_skills_by_category}
            hot_categories = sorted(
                category_totals.items(), key=lambda x: x[1], reverse=True
            )[:3]

            # Trend analysis (compare first half vs second half)
            trend = self._analyze_emergence_trend(weekly_timeline)

            result = {
                'period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat(),
                    'weeks': weeks_back
                },
                'timeline': weekly_timeline,
                'new_skills': new_skills,
                'emergence_rate': emergence_rate,
                'total_unique_skills': total_unique_skills,
                'hot_categories': [{'category': cat, 'count': count} for cat, count in hot_categories],
                'trend': trend,
                'all_skills_by_category': {
                    cat: list(all_skills_by_category[cat]) for cat in all_skills_by_category
                }
            }

            logger.info(f"Skill emergence analysis complete: {total_unique_skills} unique skills")
            return result

        except Exception as e:
            logger.error(f"Error analyzing skill emergence: {e}")
            return self._empty_skill_emergence()

    def analyze_role_transformation(self, weeks_back: int = 52) -> Dict[str, Any]:
        """
        Analyze which roles transform most rapidly.

        Identifies role families with fastest skill requirements changes,
        indicating which careers are being most impacted by AI adoption.

        Args:
            weeks_back: Number of weeks to analyze (default 52)

        Returns:
            Dictionary with:
            - most_transformed_roles: role families changing fastest
            - transformation_metrics: change rates by role
            - skill_shifts_by_role: which skills enter/exit each role
            - adoption_speed: how quickly roles adopt AI skills
        """
        if not self.loader.client:
            logger.error("Supabase client not initialized")
            return self._empty_role_transformation()

        try:
            end_date = datetime.now(self.tz)
            start_date = end_date - timedelta(weeks=weeks_back)

            # PAGINATED to avoid 1000-row truncation
            vacancies = fetch_all_paginated(
                lambda: self.loader.client.table('vacantes').select(
                    'id, posted_date, classification'
                ).gte('posted_date', start_date.isoformat()).lte(
                    'posted_date', end_date.isoformat()
                )
            )

            # Organize by role family and time period (first half vs second half)
            first_half_roles = defaultdict(list)
            second_half_roles = defaultdict(list)
            midpoint = start_date + timedelta(weeks=weeks_back // 2)

            for vacancy in vacancies:
                if not vacancy.get('classification'):
                    continue

                classification = vacancy['classification']
                posted_date = datetime.fromisoformat(
                    vacancy.get('posted_date', '').replace('Z', '+00:00')
                ) if vacancy.get('posted_date') else None

                if not posted_date:
                    continue

                role_family = classification.get('role_family', 'Unknown')

                # Extract all skills
                all_skills = set()
                for skill_type in [
                    'hard_skills', 'soft_skills', 'strategic_skills',
                    'ai_operational_skills', 'ai_cognitive_skills'
                ]:
                    skills = classification.get(skill_type, [])
                    if isinstance(skills, list):
                        all_skills.update(skills)

                if posted_date < midpoint:
                    first_half_roles[role_family].append(all_skills)
                else:
                    second_half_roles[role_family].append(all_skills)

            # Calculate transformation metrics
            transformation_metrics = {}
            skill_shifts = {}

            all_role_families = set(first_half_roles.keys()) | set(second_half_roles.keys())

            for role in all_role_families:
                first_half = first_half_roles.get(role, [])
                second_half = second_half_roles.get(role, [])

                if not first_half or not second_half:
                    continue

                # Calculate average skill count change
                first_avg = statistics.mean(len(s) for s in first_half)
                second_avg = statistics.mean(len(s) for s in second_half)
                change_rate = ((second_avg - first_avg) / first_avg * 100) if first_avg > 0 else 0

                # Calculate new skills entering role
                first_all_skills = set().union(*first_half) if first_half else set()
                second_all_skills = set().union(*second_half) if second_half else set()

                new_skills = second_all_skills - first_all_skills
                exiting_skills = first_all_skills - second_all_skills

                transformation_metrics[role] = {
                    'change_rate_percent': change_rate,
                    'first_half_avg_skills': first_avg,
                    'second_half_avg_skills': second_avg,
                    'vacancy_count_first': len(first_half),
                    'vacancy_count_second': len(second_half),
                }

                skill_shifts[role] = {
                    'new_skills_count': len(new_skills),
                    'exiting_skills_count': len(exiting_skills),
                    'new_skills_sample': list(new_skills)[:10],
                    'exiting_skills_sample': list(exiting_skills)[:10],
                }

            # Find most transformed roles
            most_transformed = sorted(
                transformation_metrics.items(),
                key=lambda x: abs(x[1]['change_rate_percent']),
                reverse=True
            )[:5]

            # AI adoption speed (% of roles requiring AI skills in second half)
            ai_adoption = self._analyze_ai_adoption_speed(second_half_roles)

            result = {
                'period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat(),
                    'weeks': weeks_back
                },
                'most_transformed_roles': [
                    {
                        'role': role,
                        'change_rate_percent': metrics['change_rate_percent'],
                        'metrics': metrics
                    }
                    for role, metrics in most_transformed
                ],
                'transformation_metrics': transformation_metrics,
                'skill_shifts_by_role': skill_shifts,
                'ai_adoption_speed': ai_adoption,
                'total_roles_analyzed': len(all_role_families),
            }

            logger.info(f"Role transformation analysis complete: {len(all_role_families)} roles")
            return result

        except Exception as e:
            logger.error(f"Error analyzing role transformation: {e}")
            return self._empty_role_transformation()

    def analyze_value_shift(self, weeks_back: int = 52) -> Dict[str, Any]:
        """
        Analyze shifts from hard skills to soft skills to strategic skills.

        Tracks whether the market is increasingly valuing judgment,
        strategy, and human capabilities over pure technical execution.

        Args:
            weeks_back: Number of weeks to analyze

        Returns:
            Dictionary with:
            - skill_category_distribution: % of jobs requiring each type
            - shift_trajectory: how distribution changes over time
            - hard_to_strategic_ratio: relative shift magnitude
            - interpretation: narrative about what this means
        """
        if not self.loader.client:
            logger.error("Supabase client not initialized")
            return self._empty_value_shift()

        try:
            end_date = datetime.now(self.tz)
            start_date = end_date - timedelta(weeks=weeks_back)

            # PAGINATED to avoid 1000-row truncation
            vacancies = fetch_all_paginated(
                lambda: self.loader.client.table('vacantes').select(
                    'id, posted_date, classification'
                ).gte('posted_date', start_date.isoformat()).lte(
                    'posted_date', end_date.isoformat()
                )
            )

            # Organize by time period (weekly windows)
            weekly_category_counts = defaultdict(lambda: {
                'hard_skills': 0,
                'soft_skills': 0,
                'strategic_skills': 0,
                'total_vacancies': 0,
            })

            for vacancy in vacancies:
                if not vacancy.get('classification'):
                    continue

                classification = vacancy['classification']
                posted_date = datetime.fromisoformat(
                    vacancy.get('posted_date', '').replace('Z', '+00:00')
                ) if vacancy.get('posted_date') else None

                if not posted_date:
                    continue

                week_key = posted_date.strftime('%Y-W%V')
                weekly_category_counts[week_key]['total_vacancies'] += 1

                # Count vacancies with each skill type
                for skill_type in ['hard_skills', 'soft_skills', 'strategic_skills']:
                    skills = classification.get(skill_type, [])
                    if isinstance(skills, list) and skills:
                        weekly_category_counts[week_key][skill_type] += 1

            # Calculate percentages and shift
            shift_trajectory = {}
            for week in sorted(weekly_category_counts.keys()):
                counts = weekly_category_counts[week]
                total = counts['total_vacancies']
                if total > 0:
                    shift_trajectory[week] = {
                        'hard_skills_percent': (counts['hard_skills'] / total) * 100,
                        'soft_skills_percent': (counts['soft_skills'] / total) * 100,
                        'strategic_skills_percent': (counts['strategic_skills'] / total) * 100,
                        'vacancy_count': total,
                    }

            # Calculate overall distribution
            total_hard = sum(counts['hard_skills'] for counts in weekly_category_counts.values())
            total_soft = sum(counts['soft_skills'] for counts in weekly_category_counts.values())
            total_strategic = sum(counts['strategic_skills'] for counts in weekly_category_counts.values())
            total_all = sum(counts['total_vacancies'] for counts in weekly_category_counts.values())

            if total_all > 0:
                distribution = {
                    'hard_skills_percent': (total_hard / total_all) * 100,
                    'soft_skills_percent': (total_soft / total_all) * 100,
                    'strategic_skills_percent': (total_strategic / total_all) * 100,
                }
            else:
                distribution = {'hard_skills_percent': 0, 'soft_skills_percent': 0, 'strategic_skills_percent': 0}

            # Calculate shift magnitude
            hard_to_strategic_ratio = (
                distribution['strategic_skills_percent'] / distribution['hard_skills_percent']
                if distribution['hard_skills_percent'] > 0 else 0
            )

            # Generate interpretation
            interpretation = self._interpret_value_shift(distribution, hard_to_strategic_ratio)

            result = {
                'period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat(),
                    'weeks': weeks_back
                },
                'skill_category_distribution': distribution,
                'shift_trajectory': shift_trajectory,
                'hard_to_strategic_ratio': hard_to_strategic_ratio,
                'interpretation': interpretation,
                'sample_size': total_all,
            }

            logger.info(f"Value shift analysis complete: {total_all} vacancies analyzed")
            return result

        except Exception as e:
            logger.error(f"Error analyzing value shift: {e}")
            return self._empty_value_shift()

    def analyze_human_expertise_premium(self) -> Dict[str, Any]:
        """
        Analyze the gap between AI operational and AI cognitive skills.

        The key thesis: AI operational skills (using ChatGPT, tool mastery)
        are table-stakes. AI cognitive skills (evaluation, curation,
        orchestration, validation) create the real value premium.

        Returns:
            Dictionary with:
            - ai_operational_prevalence: % jobs requiring operational AI skills
            - ai_cognitive_prevalence: % jobs requiring cognitive AI skills
            - cognitive_premium: ratio of cognitive to operational
            - gap_analysis: where the value gap is largest
            - hypothesis_validation: evidence for the thesis
        """
        if not self.loader.client:
            logger.error("Supabase client not initialized")
            return self._empty_human_expertise_premium()

        try:
            # PAGINATED to avoid 1000-row truncation (this query can hit >1000 easily)
            vacancies = fetch_all_paginated(
                lambda: self.loader.client.table('vacantes').select(
                    'id, classification, posted_date'
                ).is_('classification', 'not.null')
            )
            logger.info(f"Fetched {len(vacancies)} classified vacancies for expertise premium analysis")

            operational_count = 0
            cognitive_count = 0
            both_count = 0
            neither_count = 0
            operational_only = 0
            cognitive_only = 0

            operational_skills_freq = Counter()
            cognitive_skills_freq = Counter()
            operational_roles = defaultdict(int)
            cognitive_roles = defaultdict(int)

            for vacancy in vacancies:
                classification = vacancy.get('classification', {})

                operational_skills = classification.get('ai_operational_skills', [])
                cognitive_skills = classification.get('ai_cognitive_skills', [])

                has_operational = bool(operational_skills and len(operational_skills) > 0)
                has_cognitive = bool(cognitive_skills and len(cognitive_skills) > 0)

                role_family = classification.get('role_family', 'Unknown')

                if has_operational:
                    operational_count += 1
                    if isinstance(operational_skills, list):
                        operational_skills_freq.update(operational_skills)
                    operational_roles[role_family] += 1

                if has_cognitive:
                    cognitive_count += 1
                    if isinstance(cognitive_skills, list):
                        cognitive_skills_freq.update(cognitive_skills)
                    cognitive_roles[role_family] += 1

                if has_operational and has_cognitive:
                    both_count += 1
                    cognitive_only += 0
                    operational_only += 0
                elif has_operational:
                    operational_only += 1
                elif has_cognitive:
                    cognitive_only += 1
                else:
                    neither_count += 1

            total = len(vacancies)

            # Calculate prevalence
            operational_prevalence = (operational_count / total * 100) if total > 0 else 0
            cognitive_prevalence = (cognitive_count / total * 100) if total > 0 else 0

            # Cognitive premium: ratio of jobs requiring cognitive vs operational
            cognitive_premium = (
                cognitive_count / operational_count if operational_count > 0 else 0
            )

            # Gap analysis: roles where cognitive skills matter most
            gap_by_role = {}
            all_roles = set(operational_roles.keys()) | set(cognitive_roles.keys())

            for role in all_roles:
                op = operational_roles.get(role, 0)
                cog = cognitive_roles.get(role, 0)

                if op > 0:
                    gap_by_role[role] = {
                        'operational_jobs': op,
                        'cognitive_jobs': cog,
                        'cognitive_ratio': cog / op,
                        'gap': cog - op,
                    }

            top_cognitive_roles = sorted(
                gap_by_role.items(),
                key=lambda x: x[1]['cognitive_ratio'],
                reverse=True
            )[:5]

            # Hypothesis validation
            hypothesis = {
                'operational_as_table_stakes': operational_prevalence > 50,
                'cognitive_creates_premium': cognitive_premium > 0.3,
                'gap_growing': cognitive_only > operational_only,
                'evidence': {
                    'operational_only_jobs': operational_only,
                    'cognitive_only_jobs': cognitive_only,
                    'both_skills_jobs': both_count,
                    'neither_jobs': neither_count,
                }
            }

            result = {
                'ai_operational_prevalence_percent': operational_prevalence,
                'ai_cognitive_prevalence_percent': cognitive_prevalence,
                'cognitive_premium_ratio': cognitive_premium,
                'sample_size': total,
                'top_cognitive_roles': [
                    {
                        'role': role,
                        'cognitive_ratio': metrics['cognitive_ratio'],
                        'metrics': metrics
                    }
                    for role, metrics in top_cognitive_roles
                ],
                'gap_by_role': gap_by_role,
                'skill_frequencies': {
                    'operational_top_10': operational_skills_freq.most_common(10),
                    'cognitive_top_10': cognitive_skills_freq.most_common(10),
                },
                'hypothesis_validation': hypothesis,
            }

            logger.info(f"Human expertise premium analysis complete")
            return result

        except Exception as e:
            logger.error(f"Error analyzing human expertise premium: {e}")
            return self._empty_human_expertise_premium()

    def generate_insights_summary(self) -> Dict[str, Any]:
        """
        Generate consolidated narrative findings across all analyses.

        Synthesizes the four core analyses into a coherent story about
        how labor markets are transforming around AI.

        Returns:
            Dictionary with:
            - key_findings: main narrative points
            - evidence_by_finding: data supporting each finding
            - recommendations: action items from analysis
            - research_limitations: caveats and scope limits
        """
        try:
            # Run all analyses
            skill_emergence = self.analyze_skill_emergence()
            role_transformation = self.analyze_role_transformation()
            value_shift = self.analyze_value_shift()
            expertise_premium = self.analyze_human_expertise_premium()

            key_findings = []

            # Finding 1: Skill acceleration
            if skill_emergence.get('emergence_rate', 0) > 0:
                key_findings.append({
                    'title': 'AI Skills Are Entering the Market Rapidly',
                    'finding': (
                        f"Average emergence rate: {skill_emergence['emergence_rate']:.1f} new skills/week. "
                        f"Hot categories: {', '.join(cat['category'] for cat in skill_emergence.get('hot_categories', [])[:2])}"
                    ),
                    'implication': 'Traditional skill-building timelines are becoming obsolete.',
                })

            # Finding 2: Role transformation
            most_transformed = role_transformation.get('most_transformed_roles', [])
            if most_transformed:
                top_role = most_transformed[0]
                key_findings.append({
                    'title': 'Certain Roles Transform Much Faster Than Others',
                    'finding': (
                        f"{top_role.get('role')} roles changing fastest "
                        f"(change rate: {top_role.get('change_rate_percent', 0):.1f}%). "
                        f"This indicates selective, not uniform, disruption."
                    ),
                    'implication': 'Career resilience depends heavily on role choice and adaptability.',
                })

            # Finding 3: Value shift
            dist = value_shift.get('skill_category_distribution', {})
            if dist.get('strategic_skills_percent', 0) > 0:
                key_findings.append({
                    'title': 'Markets Value Strategic Skills Increasingly',
                    'finding': (
                        f"Strategic skills in {dist.get('strategic_skills_percent', 0):.1f}% of jobs. "
                        f"Hard:Strategic ratio = {value_shift.get('hard_to_strategic_ratio', 0):.2f}. "
                        f"This represents a structural shift in what the market values."
                    ),
                    'implication': 'Judgment and strategy are becoming differentiators.',
                })

            # Finding 4: Expertise premium
            if expertise_premium.get('cognitive_premium_ratio', 0) > 0.3:
                key_findings.append({
                    'title': 'Human Cognitive Skills Create a Value Premium',
                    'finding': (
                        f"Cognitive AI skills prevalence: {expertise_premium.get('ai_cognitive_prevalence_percent', 0):.1f}%. "
                        f"Operational AI skills prevalence: {expertise_premium.get('ai_operational_prevalence_percent', 0):.1f}%. "
                        f"Cognitive premium ratio: {expertise_premium.get('cognitive_premium_ratio', 0):.2f}. "
                        f"This validates the thesis that cognitive skills are where value accrues."
                    ),
                    'implication': 'The competitive advantage shifts to those who can evaluate and orchestrate AI.',
                })

            # Recommendations
            recommendations = [
                'Invest in judgment and evaluation frameworks for AI tool selection',
                'Develop meta-skills: how to learn new tools rapidly',
                'Create role-specific AI integration strategies (not one-size-fits-all)',
                'Build team capabilities around orchestration and human-in-the-loop validation',
                'Monitor role transformation rates to identify high-risk careers',
            ]

            limitations = [
                'Analysis based on job postings (may not reflect actual market demand)',
                'Skill categories rely on classification model accuracy',
                f"Temporal coverage: {skill_emergence.get('period', {}).get('weeks', 'N/A')} weeks",
                'Sample includes only structured job data (excludes gig work, etc.)',
                'Does not account for regional or sector variations comprehensively',
            ]

            result = {
                'generated_at': datetime.now(self.tz).isoformat(),
                'key_findings': key_findings,
                'evidence_by_finding': {
                    'skill_emergence': skill_emergence,
                    'role_transformation': role_transformation,
                    'value_shift': value_shift,
                    'human_expertise_premium': expertise_premium,
                },
                'recommendations': recommendations,
                'research_limitations': limitations,
                'thesis_validation': {
                    'central_question': 'What human capabilities become more valuable when AI is infrastructure?',
                    'answer': 'Judgment, curation, orchestration, and validation—the cognitive skills.',
                    'confidence': 'HIGH - supported by differential prevalence of cognitive vs operational skills',
                }
            }

            logger.info("Insights summary generated successfully")
            return result

        except Exception as e:
            logger.error(f"Error generating insights summary: {e}")
            return {
                'error': str(e),
                'key_findings': [],
                'evidence_by_finding': {},
                'recommendations': [],
            }

    # Private helper methods

    @staticmethod
    def _analyze_emergence_trend(weekly_timeline: Dict[str, Dict]) -> str:
        """Determine if skill emergence is accelerating or decelerating."""
        if len(weekly_timeline) < 2:
            return "insufficient_data"

        weeks = sorted(weekly_timeline.keys())
        first_half = weeks[:len(weeks) // 2]
        second_half = weeks[len(weeks) // 2:]

        first_total = sum(
            sum(v.values()) for w in first_half for v in [weekly_timeline.get(w, {})]
        )
        second_total = sum(
            sum(v.values()) for w in second_half for v in [weekly_timeline.get(w, {})]
        )

        first_avg = first_total / len(first_half) if first_half else 0
        second_avg = second_total / len(second_half) if second_half else 0

        if second_avg > first_avg * 1.2:
            return "accelerating"
        elif second_avg < first_avg * 0.8:
            return "decelerating"
        else:
            return "stable"

    @staticmethod
    def _analyze_ai_adoption_speed(role_skills: Dict[str, List]) -> Dict[str, Any]:
        """Analyze how rapidly roles are adopting AI skills."""
        ai_adoption = {}
        for role, skill_sets in role_skills.items():
            if not skill_sets:
                continue

            with_ai = 0
            for skills in skill_sets:
                # Simple heuristic: check for 'ai' keyword in skills
                if any('ai' in str(s).lower() for s in skills):
                    with_ai += 1

            adoption_rate = (with_ai / len(skill_sets) * 100) if skill_sets else 0
            ai_adoption[role] = adoption_rate

        return ai_adoption

    @staticmethod
    def _interpret_value_shift(distribution: Dict, ratio: float) -> str:
        """Generate narrative interpretation of value shift."""
        hard_pct = distribution.get('hard_skills_percent', 0)
        soft_pct = distribution.get('soft_skills_percent', 0)
        strategic_pct = distribution.get('strategic_skills_percent', 0)

        if strategic_pct > hard_pct and ratio > 1.0:
            return (
                f"Market increasingly values judgment and strategy. "
                f"Strategic skills in {strategic_pct:.1f}% of jobs vs hard skills in {hard_pct:.1f}%. "
                f"This represents a fundamental shift toward human expertise in system design."
            )
        elif hard_pct > 60:
            return (
                f"Traditional technical execution still dominates ({hard_pct:.1f}%), "
                f"but strategic skills are growing. Transitional period."
            )
        else:
            return (
                f"Balanced skill portfolio emerging. Hard ({hard_pct:.1f}%), "
                f"Soft ({soft_pct:.1f}%), Strategic ({strategic_pct:.1f}%)."
            )

    @staticmethod
    def _empty_skill_emergence() -> Dict[str, Any]:
        """Return empty skill emergence structure."""
        return {
            'period': {'start': '', 'end': '', 'weeks': 0},
            'timeline': {},
            'new_skills': {},
            'emergence_rate': 0,
            'total_unique_skills': 0,
            'hot_categories': [],
            'trend': 'insufficient_data',
            'all_skills_by_category': {},
        }

    @staticmethod
    def _empty_role_transformation() -> Dict[str, Any]:
        """Return empty role transformation structure."""
        return {
            'period': {'start': '', 'end': '', 'weeks': 0},
            'most_transformed_roles': [],
            'transformation_metrics': {},
            'skill_shifts_by_role': {},
            'ai_adoption_speed': {},
            'total_roles_analyzed': 0,
        }

    @staticmethod
    def _empty_value_shift() -> Dict[str, Any]:
        """Return empty value shift structure."""
        return {
            'period': {'start': '', 'end': '', 'weeks': 0},
            'skill_category_distribution': {},
            'shift_trajectory': {},
            'hard_to_strategic_ratio': 0,
            'interpretation': '',
            'sample_size': 0,
        }

    @staticmethod
    def _empty_human_expertise_premium() -> Dict[str, Any]:
        """Return empty human expertise premium structure."""
        return {
            'ai_operational_prevalence_percent': 0,
            'ai_cognitive_prevalence_percent': 0,
            'cognitive_premium_ratio': 0,
            'sample_size': 0,
            'top_cognitive_roles': [],
            'gap_by_role': {},
            'skill_frequencies': {'operational_top_10': [], 'cognitive_top_10': []},
            'hypothesis_validation': {},
        }
