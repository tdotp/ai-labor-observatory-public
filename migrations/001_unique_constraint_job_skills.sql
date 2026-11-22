-- Migration: 001 - UNIQUE constraint on job_skills to prevent duplicates
-- Date: 2026-05-22
-- Context: After cleaning 2,072 duplicate skills caused by re-extraction loops (the
--          "1000-row query bug" made resume scripts re-process the same vacancies
--          multiple times), we add a UNIQUE constraint to prevent this from
--          happening again at the database level.
--
-- IMPORTANT: Run this AFTER cleaning all existing duplicates. If duplicates still
--            exist, this migration will fail. The cleanup was completed on
--            2026-05-22 — backup is at:
--              /opt/observatory/backups/duplicates_backup_20260522_073406.json
--
-- How to apply:
--   1. Open Supabase Dashboard → SQL Editor
--   2. Paste this script
--   3. Click "Run"
--   4. Verify with:
--        SELECT conname FROM pg_constraint WHERE conname = 'unique_skill_per_vacancy';
--   5. Test by trying to insert a known duplicate — should be rejected.

-- ============================================================
-- STEP 1: Pre-flight check — confirm no duplicates exist
-- ============================================================
-- If this returns ANY rows, DO NOT proceed. Clean duplicates first.
SELECT
    vacancy_id,
    LOWER(TRIM(skill)) AS skill_normalized,
    category,
    COUNT(*) AS dup_count
FROM job_skills
GROUP BY vacancy_id, LOWER(TRIM(skill)), category
HAVING COUNT(*) > 1
LIMIT 10;
-- Expected result: 0 rows (no duplicates remain after cleanup)

-- ============================================================
-- STEP 2: Add the UNIQUE constraint
-- ============================================================
-- This prevents (vacancy_id, skill, category) tuples from being inserted twice.
-- NOTE: PostgreSQL's UNIQUE constraint is case-sensitive and whitespace-sensitive.
-- We rely on the code-level check in classification/skills_extractor.py to also
-- normalize skill text before insert (defense in depth).
ALTER TABLE job_skills
ADD CONSTRAINT unique_skill_per_vacancy
UNIQUE (vacancy_id, skill, category);

-- ============================================================
-- STEP 3: Verify the constraint was added
-- ============================================================
SELECT
    conname AS constraint_name,
    contype AS constraint_type,
    pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'job_skills'::regclass
  AND conname = 'unique_skill_per_vacancy';
-- Expected: 1 row showing the new UNIQUE constraint

-- ============================================================
-- ROLLBACK (only if needed)
-- ============================================================
-- If you need to remove the constraint:
--   ALTER TABLE job_skills DROP CONSTRAINT unique_skill_per_vacancy;
