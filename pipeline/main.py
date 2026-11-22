#!/usr/bin/env python3
"""Main orchestrator for the Observatory Pipeline."""

import sys
import argparse
import logging
import asyncio
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime

from pipeline.config import Config
from pipeline.extractor import ApifyExtractor
from pipeline.cleaner import DataCleaner
from pipeline.loader import SupabaseLoader
from classification.openrouter_classifier import OpenRouterClassifier
from classification.skills_extractor import SkillsExtractor
from monitoring.alert_system import AlertManager


class ObservatoryPipeline:
    """Orchestrate the full data pipeline: extract -> clean -> load -> classify."""

    def __init__(self, test_mode: bool = False, source: Optional[str] = None):
        """
        Initialize the Observatory Pipeline.

        Args:
            test_mode: If True, process only a sample of data (BATCH_SIZE_FIRST items)
            source: Job source ('linkedin_jobs' or 'indeed'). If None, processes all.

        Raises:
            ValueError: If source is not valid
        """
        self.test_mode = test_mode
        self.source = source
        self.logger = logging.getLogger(__name__)

        # Validate source
        valid_sources = ['linkedin_jobs', 'indeed']
        if self.source and self.source not in valid_sources:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {', '.join(valid_sources)}")

        # Initialize pipeline components
        try:
            self.extractor = ApifyExtractor(Config.APIFY_TOKEN)
            self.cleaner = DataCleaner()
            # UPDATE operations (classification, skills insert) require the
            # service-role key to bypass RLS. Falling back to the anon key
            # is kept for local/dev runs where the service key isn't set;
            # production MUST configure SUPABASE_SERVICE_ROLE_KEY.
            supabase_key = (
                Config.SUPABASE_SERVICE_ROLE_KEY or Config.SUPABASE_ANON_KEY
            )
            if not Config.SUPABASE_SERVICE_ROLE_KEY:
                self.logger.warning(
                    "Using SUPABASE_ANON_KEY for loader — UPDATEs may silently "
                    "fail under RLS. Set SUPABASE_SERVICE_ROLE_KEY in production."
                )
            self.loader = SupabaseLoader(Config.SUPABASE_URL, supabase_key)
            self.classifier = OpenRouterClassifier(Config.OPENROUTER_API_KEY)
            self.skills_extractor = SkillsExtractor(Config.OPENROUTER_API_KEY)
        except Exception as e:
            self.logger.error(f"Failed to initialize pipeline components: {e}")
            raise

        # Statistics tracking
        self.stats = {
            'extracted': 0,
            'cleaned': 0,
            'loaded': 0,
            'classified': 0,
            'skills_extracted': 0,
            'skills_vacancies_processed': 0,
            'errors': 0,
            'duplicates': 0,
            'start_time': datetime.now(),
            'end_time': None,
            'llm_calls': 0,
            'estimated_cost_usd': 0.0,
        }
        # Budget enforcement counters (shared across classify + skills phases)
        self._total_llm_calls = 0
        self._total_tokens = 0

        self.logger.info(f"ObservatoryPipeline initialized (test_mode={test_mode}, source={source})")

    def extract(self) -> List[Dict[str, Any]]:
        """
        Extract job vacancies from configured sources via Apify.

        Returns:
            List of extracted vacancy dictionaries

        Raises:
            Exception: If extraction fails
        """
        self.logger.info("=== STARTING EXTRACTION PHASE ===")
        extracted_vacancies = []

        try:
            sources_to_process = [self.source] if self.source else list(Config.APIFY_ACTORS.keys())
            # Load search inputs that get passed to each Apify actor.
            # If `inputs` for a source exists, the extractor triggers a NEW run
            # with those params. Otherwise it falls back to reading the latest run.
            apify_inputs = Config.get_apify_inputs()

            def _shrink_for_test(d):
                if not d:
                    return d
                d = dict(d)
                if 'count' in d:
                    d['count'] = min(d['count'], 15)
                if 'maxRows' in d:
                    d['maxRows'] = min(d['maxRows'], 15)
                return d

            # Reverse mapping Indeed code → name (for fallback country on "Remote" vacancies)
            _indeed_code_to_name = {code: name for name, code in Config.LATAM_COUNTRIES_INDEED.items()}

            for src in sources_to_process:
                if src not in Config.APIFY_ACTORS:
                    self.logger.warning(f"Skipping unknown source: {src}")
                    continue

                self.logger.info(f"Extracting from {src}...")
                actor_id = Config.APIFY_ACTORS[src]
                input_data = apify_inputs.get(src)

                # Normalize: accept both single dict (LinkedIn) and list of dicts (Indeed multi-country)
                input_list = input_data if isinstance(input_data, list) else [input_data]
                src_vacancies = []

                if len(input_list) > 1:
                    self.logger.info(f"  → {src}: triggering {len(input_list)} runs (multi-country)")

                for run_idx, single_input in enumerate(input_list, start=1):
                    if self.test_mode:
                        single_input = _shrink_for_test(single_input)

                    # Determine fallback country for ambiguous "Remote" / empty location:
                    # - Indeed: exactly 1 country per run → use its country name
                    # - LinkedIn: 1 run covers 10 LatAm countries → use generic 'LATAM'
                    if src == 'indeed' and single_input and single_input.get('country'):
                        fallback_country = _indeed_code_to_name.get(single_input['country'])
                    elif src == 'linkedin_jobs':
                        fallback_country = 'LATAM'
                    else:
                        fallback_country = None

                    if len(input_list) > 1:
                        country_label = single_input.get('country') if single_input else '?'
                        self.logger.info(
                            f"  Run {run_idx}/{len(input_list)} for {src} "
                            f"(country={country_label}, fallback={fallback_country})..."
                        )

                    vacancies = self.extractor.run_extraction(
                        actor_id, src,
                        input_data=single_input,
                        fallback_country=fallback_country,
                    )
                    src_vacancies.extend(vacancies)
                    self.logger.info(f"    Extracted {len(vacancies)} vacancies in run {run_idx}/{len(input_list)}")

                if self.test_mode:
                    src_vacancies = src_vacancies[:Config.TEST_MODE_SAMPLE_SIZE]

                extracted_vacancies.extend(src_vacancies)
                self.logger.info(f"Extracted {len(src_vacancies)} total vacancies from {src}")

            self.stats['extracted'] = len(extracted_vacancies)
            self.logger.info(f"Extraction complete: {self.stats['extracted']} total vacancies")
            return extracted_vacancies

        except Exception as e:
            self.logger.error(f"Extraction failed: {e}", exc_info=True)
            self.stats['errors'] += 1
            raise

    def clean(self, vacancies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Clean and deduplicate extracted vacancies.

        Args:
            vacancies: List of raw vacancy dictionaries

        Returns:
            List of cleaned vacancy dictionaries

        Raises:
            Exception: If cleaning fails
        """
        self.logger.info("=== STARTING CLEANING PHASE ===")

        try:
            # Save to temp file for batch processing
            temp_input = Config.DATA_PATH / f"raw_{datetime.now().timestamp()}.jsonl"

            import json
            with open(temp_input, 'w', encoding='utf-8') as f:
                for vacancy in vacancies:
                    f.write(json.dumps(vacancy) + '\n')

            # Run cleaner
            temp_output = Config.DATA_PATH / f"cleaned_{datetime.now().timestamp()}.jsonl"
            stats = self.cleaner.clean_batch(str(temp_input), str(temp_output))

            # Read cleaned vacancies
            cleaned = []
            with open(temp_output, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        cleaned.append(json.loads(line))

            self.stats['cleaned'] = len(cleaned)
            self.stats['duplicates'] = stats.get('duplicates_removed', 0)

            self.logger.info(f"Cleaning complete: {self.stats['cleaned']} vacancies retained, "
                           f"{self.stats['duplicates']} duplicates removed")

            # Cleanup temp files
            try:
                temp_input.unlink()
                temp_output.unlink()
            except Exception as e:
                self.logger.warning(f"Failed to cleanup temp files: {e}")

            return cleaned

        except Exception as e:
            self.logger.error(f"Cleaning failed: {e}", exc_info=True)
            self.stats['errors'] += 1
            raise

    def load_to_db(self, vacancies: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Load cleaned vacancies into Supabase database.

        Args:
            vacancies: List of cleaned vacancy dictionaries

        Returns:
            Dictionary with load statistics (inserted, duplicates, errors)

        Raises:
            Exception: If loading fails
        """
        self.logger.info("=== STARTING LOAD PHASE ===")

        try:
            if not self.loader.client:
                self.logger.warning("Supabase client not initialized, skipping load")
                return {'inserted': 0, 'duplicates': 0, 'errors': 0}

            result = self.loader.load_vacancies(vacancies)
            self.stats['loaded'] = result.get('inserted', 0)
            self.stats['duplicates'] += result.get('duplicates', 0)

            self.logger.info(f"Load complete: {result.get('inserted', 0)} inserted, "
                           f"{result.get('duplicates', 0)} duplicates, "
                           f"{result.get('errors', 0)} errors")

            return result

        except Exception as e:
            self.logger.error(f"Load failed: {e}", exc_info=True)
            self.stats['errors'] += 1
            raise

    async def classify(self, vacancies: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Classify vacancies using OpenRouter API.

        Args:
            vacancies: Optional list of vacancies to classify.
                      If None, fetches unclassified from database.

        Returns:
            Dictionary with classification results and statistics

        Raises:
            Exception: If classification fails
        """
        self.logger.info("=== STARTING CLASSIFICATION PHASE ===")

        # Batch size based on test mode
        batch_size = (Config.TEST_MODE_SAMPLE_SIZE if self.test_mode
                     else Config.BATCH_SIZE_FIRST)

        classified_count = 0
        error_count = 0

        async def _classify_list(vlist):
            """Classify a list of vacancies in sub-batches, updating outer counters."""
            nonlocal classified_count, error_count
            for i in range(0, len(vlist), batch_size):
                batch = vlist[i:i + batch_size]
                batch_num = i // batch_size + 1
                self.logger.info(f"Classifying batch {batch_num} ({len(batch)} items)...")

                # Budget pre-check before each batch
                if (Config.MAX_LLM_CALLS_PER_RUN > 0
                        and self._total_llm_calls >= Config.MAX_LLM_CALLS_PER_RUN):
                    self.logger.warning(
                        f"Budget: MAX_LLM_CALLS_PER_RUN={Config.MAX_LLM_CALLS_PER_RUN} "
                        f"reached. Stopping classification."
                    )
                    break
                est_cost = (self._total_tokens / 1000) * Config.APPROX_COST_PER_1K_TOKENS_USD
                if Config.RUN_BUDGET_USD > 0 and est_cost >= Config.RUN_BUDGET_USD:
                    self.logger.warning(
                        f"Budget: estimated cost ${est_cost:.4f} >= "
                        f"RUN_BUDGET_USD=${Config.RUN_BUDGET_USD}. Stopping."
                    )
                    break

                try:
                    results = await self.classifier.classify_batch(batch, batch_name=f"batch_{batch_num}")
                    # Accumulate budget counters from classifier
                    self._total_llm_calls += self.classifier.total_calls
                    self._total_tokens += self.classifier.total_tokens_used
                    # Reset per-batch counters on classifier
                    self.classifier.total_calls = 0
                    self.classifier.total_tokens_used = 0

                    # Update database with results
                    for vacancy_id, classification in zip([v.get('id') for v in batch], results):
                        if classification and vacancy_id:
                            success = self.loader.update_classification(vacancy_id, classification)
                            if success:
                                classified_count += 1
                            else:
                                error_count += 1

                except Exception as e:
                    self.logger.error(f"Batch classification failed: {e}")
                    error_count += len(batch)

        try:
            if vacancies is not None:
                # Explicit list provided — classify exactly those.
                if not vacancies:
                    self.logger.info("No vacancies to classify")
                    return {'classified': 0, 'errors': 0}
                await _classify_list(vacancies)
                total_processed = len(vacancies)
            else:
                # DB mode — loop fetch+classify until the queue is drained.
                # update_classification() sets the `classification` column to a
                # non-null marker, so each classified row drops out of the
                # is.null filter on the next fetch; the loop terminates naturally.
                # MAX_ITERATIONS is a safety cap so a persistent update failure
                # (e.g. RLS regression) can't spin forever and burn OpenRouter.
                MAX_ITERATIONS = 100  # 100 x BATCH_SIZE_FIRST = up to 10,000/run
                total_processed = 0
                for iteration in range(1, MAX_ITERATIONS + 1):
                    self.logger.info(
                        f"Fetching unclassified vacancies from database "
                        f"(iteration {iteration})..."
                    )
                    fetched = self.loader.get_vacancies_for_classification(
                        limit=Config.BATCH_SIZE_FIRST
                    )
                    self.logger.info(f"Fetched {len(fetched)} unclassified vacancies")

                    if not fetched:
                        self.logger.info(
                            "Classification queue drained — no more pending vacancies"
                        )
                        break

                    total_processed += len(fetched)
                    await _classify_list(fetched)
                else:
                    self.logger.warning(
                        f"Reached MAX_ITERATIONS={MAX_ITERATIONS} — stopping classification "
                        f"loop (pending vacancies may remain; check for update failures)"
                    )

                if total_processed == 0:
                    self.logger.info("No vacancies to classify")
                    return {'classified': 0, 'errors': 0}

            self.stats['classified'] = classified_count

            result = {
                'classified': classified_count,
                'errors': error_count,
                'total_processed': total_processed,
            }

            self.logger.info(f"Classification complete: {classified_count} classified, "
                           f"{error_count} errors")

            return result

        except Exception as e:
            self.logger.error(f"Classification failed: {e}", exc_info=True)
            self.stats['errors'] += 1
            raise

    @staticmethod
    def _classification_is_other(vacancy: Dict[str, Any]) -> bool:
        """
        True if a vacancy was classified as OTHER (out-of-domain).

        Out-of-domain vacancies don't need the (expensive) skills pass — they
        wouldn't contribute meaningful signal to the observatory. The
        classifier may use `role_family` or `category` for the label
        depending on the prompt version, so we check both.
        """
        cl = vacancy.get('classification')
        if not isinstance(cl, dict):
            return False
        label = cl.get('role_family') or cl.get('category') or ''
        return str(label).strip().upper() == 'OTHER'

    async def extract_skills_for_pending(
        self,
        max_vacancies: Optional[int] = None,
        concurrency: int = 8,
    ) -> Dict[str, int]:
        """
        Phase 5: Extract skills for vacancies that don't yet have any.

        Uses `loader.get_vacancies_pending_skills()` to find vacancies WITHOUT
        existing skills (avoids reprocessing — protected by check + UNIQUE
        constraint), filters out OTHER-classified ones to avoid wasting LLM
        calls on out-of-domain roles, then processes the remaining in
        parallel (asyncio.gather + Semaphore).

        Args:
            max_vacancies: Optional cap on vacancies processed (cost control).
                           In test mode, automatically capped at
                           TEST_MODE_SAMPLE_SIZE.
            concurrency: Max parallel skills-extraction calls.

        Returns:
            Dict with: skills_vacancies_processed, skills_extracted,
            skills_errors, skills_skipped_other
        """
        self.logger.info("=== STARTING SKILLS EXTRACTION PHASE ===")

        try:
            limit = max_vacancies
            if self.test_mode:
                limit = min(limit or Config.TEST_MODE_SAMPLE_SIZE, Config.TEST_MODE_SAMPLE_SIZE)

            pending = self.loader.get_vacancies_pending_skills(limit=limit)
            self.logger.info(f"Found {len(pending)} vacancies pending skill extraction")

            # Skip OTHER-classified vacancies (out of domain) before spending
            # any tokens — they're noise from the observatory's perspective.
            before = len(pending)
            pending = [v for v in pending if not self._classification_is_other(v)]
            skipped_other = before - len(pending)
            if skipped_other:
                self.logger.info(
                    f"Skipped {skipped_other} OTHER-classified vacancies "
                    f"(no skills extraction needed)"
                )

            if not pending:
                await self.skills_extractor.aclose()
                return {
                    'skills_vacancies_processed': 0,
                    'skills_extracted': 0,
                    'skills_errors': 0,
                    'skills_skipped_other': skipped_other,
                }

            semaphore = asyncio.Semaphore(max(1, concurrency))
            total = len(pending)

            async def _process_one(vac: Dict[str, Any]) -> Dict[str, int]:
                """Extract + insert skills for one vacancy. Returns small stat
                dict so the caller can sum results without shared mutation."""
                vid = vac.get('id')
                async with semaphore:
                    try:
                        skills = await self.skills_extractor.extract_skills({
                            'vacancy_id': vid,
                            'raw_title': vac.get('raw_title'),
                            'raw_description': vac.get('raw_description'),
                            'raw_requirements': vac.get('raw_requirements'),
                        })
                    except Exception as e:
                        self.logger.error(
                            f"Skill extraction failed for vacancy {vid}: {e}"
                        )
                        return {'processed': 0, 'inserted': 0, 'errors': 1}

                if not skills:
                    self.logger.warning(f"No skills extracted for vacancy {vid}")
                    return {'processed': 0, 'inserted': 0, 'errors': 0}

                # insert_skills is sync but fast — running it inside the
                # semaphore-guarded coroutine is fine.
                ins = self.loader.insert_skills(vid, skills)
                return {
                    'processed': 1,
                    'inserted': ins.get('inserted', 0),
                    'errors': ins.get('errors', 0),
                }

            self.logger.info(
                f"Parallel skills extraction: {total} vacancies, "
                f"concurrency={concurrency}"
            )
            per_vacancy = await asyncio.gather(*(_process_one(v) for v in pending))

            processed = sum(r['processed'] for r in per_vacancy)
            total_skills = sum(r['inserted'] for r in per_vacancy)
            errors = sum(r['errors'] for r in per_vacancy)

            # Close the async client to release connections
            await self.skills_extractor.aclose()

            self.stats['skills_vacancies_processed'] = processed
            self.stats['skills_extracted'] = total_skills

            self.logger.info(
                f"Skills extraction complete: {processed}/{total} vacancies, "
                f"{total_skills} skills inserted, {errors} errors, "
                f"{skipped_other} OTHER skipped"
            )
            return {
                'skills_vacancies_processed': processed,
                'skills_extracted': total_skills,
                'skills_errors': errors,
                'skills_skipped_other': skipped_other,
            }

        except Exception as e:
            self.logger.error(f"Skills extraction phase failed: {e}", exc_info=True)
            self.stats['errors'] += 1
            return {
                'skills_vacancies_processed': 0,
                'skills_extracted': 0,
                'skills_errors': 1,
                'skills_skipped_other': 0,
            }

    def run(
        self,
        skip_classification: bool = False,
        classify_only: bool = False,
        skip_skills: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the full pipeline: extract -> clean -> load -> classify -> skills.

        Args:
            skip_classification: If True, skip the classification phase
            classify_only: If True, skip extraction/cleaning/loading and only classify
            skip_skills: If True, skip the skills extraction phase

        Returns:
            Dictionary with final pipeline statistics

        Raises:
            Exception: If any phase fails critically
        """
        self.logger.info(Config.get_summary())
        self.logger.info("Starting Observatory Pipeline execution...")

        try:
            if classify_only:
                self.logger.info("Running in CLASSIFY_ONLY mode (skipping extraction, cleaning, loading)")
                classification_result = asyncio.run(self.classify())
                self.stats.update(classification_result)
                self.stats['end_time'] = datetime.now()
                self.logger.info("Classification phase completed successfully")
                return self.stats

            # Phase 1: Extract
            vacancies = self.extract()

            if not vacancies:
                self.logger.warning("No vacancies extracted, aborting pipeline")
                return self.stats

            # Phase 2: Clean
            cleaned_vacancies = self.clean(vacancies)

            if not cleaned_vacancies:
                self.logger.warning("No vacancies survived cleaning, aborting pipeline")
                return self.stats

            # Phase 3: Load
            self.load_to_db(cleaned_vacancies)

            # Phase 4: Classify (optional)
            if not skip_classification:
                classification_result = asyncio.run(self.classify())
                self.stats.update(classification_result)

            # Phase 5: Extract skills (optional)
            # This MUST run after Phase 3 (vacancies need to exist in DB first)
            if not skip_skills:
                skills_result = asyncio.run(self.extract_skills_for_pending())
                self.stats.update(skills_result)

            self.stats['end_time'] = datetime.now()
            self.stats['llm_calls'] = self._total_llm_calls
            self.stats['estimated_cost_usd'] = round(
                (self._total_tokens / 1000) * Config.APPROX_COST_PER_1K_TOKENS_USD, 4
            )
            self.logger.info(
                f"Pipeline execution completed. LLM calls: {self._total_llm_calls}, "
                f"estimated cost: ${self.stats['estimated_cost_usd']:.4f}"
            )

            # Run monitoring checks (non-blocking — failures are logged, not raised)
            try:
                alert_mgr = AlertManager(Config.SUPABASE_URL, Config.SUPABASE_ANON_KEY)
                alerts = alert_mgr.check_all_thresholds()
                if alerts:
                    self.logger.warning(f"Monitoring: {len(alerts)} alert(s) triggered: {alerts}")
            except Exception as monitor_err:
                self.logger.warning(f"Monitoring check failed (non-critical): {monitor_err}")

            return self.stats

        except Exception as e:
            self.logger.error(f"Pipeline execution failed: {e}", exc_info=True)
            self.stats['end_time'] = datetime.now()
            raise

    def print_summary(self) -> None:
        """Print a formatted summary of pipeline execution statistics."""
        if self.stats['end_time'] is None:
            duration = 0
        else:
            duration = (self.stats['end_time'] - self.stats['start_time']).total_seconds()

        summary = f"""
        ========================================
        PIPELINE EXECUTION SUMMARY
        ========================================
        Start Time: {self.stats['start_time'].isoformat()}
        End Time: {self.stats['end_time'].isoformat() if self.stats['end_time'] else 'N/A'}
        Duration: {duration:.2f} seconds

        STATISTICS:
        -----------
        Extracted: {self.stats['extracted']} vacancies
        Cleaned: {self.stats['cleaned']} vacancies
        Loaded: {self.stats['loaded']} vacancies
        Classified: {self.stats['classified']} vacancies
        Skills extracted: {self.stats.get('skills_extracted', 0)} skills from {self.stats.get('skills_vacancies_processed', 0)} vacancies
        Duplicates: {self.stats['duplicates']}
        Errors: {self.stats['errors']}

        TEST MODE: {'Yes' if self.test_mode else 'No'}
        SOURCE: {self.source if self.source else 'All'}
        ========================================
        """

        self.logger.info(summary)
        print(summary)


def main():
    """Main entry point for the pipeline."""
    parser = argparse.ArgumentParser(
        description='Observatory Pipeline: Extract, Clean, Load, and Classify job vacancies'
    )

    parser.add_argument(
        '--test',
        action='store_true',
        help=f'Run in test mode (processes first {Config.TEST_MODE_SAMPLE_SIZE} vacancies)'
    )

    parser.add_argument(
        '--source',
        type=str,
        choices=['linkedin_jobs', 'indeed'],
        default=None,
        help='Job source to process (default: all sources)'
    )

    parser.add_argument(
        '--skip-classification',
        action='store_true',
        help='Skip the classification phase'
    )

    parser.add_argument(
        '--skip-skills',
        action='store_true',
        help='Skip the skills extraction phase (Phase 5)'
    )

    parser.add_argument(
        '--classify-only',
        action='store_true',
        help='Only classify existing unclassified vacancies (skip extraction, cleaning, loading)'
    )

    parser.add_argument(
        '--log-level',
        type=str,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='Logging level (default: INFO)'
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format=Config.LOG_FORMAT,
        handlers=[
            logging.FileHandler(Config.LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ]
    )

    logger = logging.getLogger(__name__)

    try:
        # Validate configuration
        Config.validate()

        # Create and run pipeline
        pipeline = ObservatoryPipeline(test_mode=args.test, source=args.source)
        pipeline.run(
            skip_classification=args.skip_classification,
            classify_only=args.classify_only,
            skip_skills=args.skip_skills,
        )
        pipeline.print_summary()

        sys.exit(0)

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
