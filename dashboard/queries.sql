-- DASHBOARD QUERIES FOR METABASE

-- Q1: Vacancies by AI Level
SELECT
  ai_level,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as percentage
FROM vacantes
GROUP BY ai_level
ORDER BY ai_level DESC;

-- Q2: Top Skills by Category
SELECT
  category,
  skill,
  COUNT(*) as frequency,
  ARRAY_AGG(DISTINCT role_family) as roles
FROM job_skills
GROUP BY category, skill
ORDER BY frequency DESC
LIMIT 30;

-- Q3: Role Family Transformation
SELECT
  role_family,
  COUNT(*) as total_vacancies,
  COUNT(CASE WHEN ai_level >= 2 THEN 1 END) as with_ai,
  ROUND(COUNT(CASE WHEN ai_level >= 2 THEN 1 END) * 100.0 / COUNT(*), 1) as pct_with_ai,
  AVG(classification_confidence) as avg_confidence
FROM vacantes
WHERE role_family IS NOT NULL
GROUP BY role_family
ORDER BY pct_with_ai DESC;

-- Q4: AI Skills Emergence (by seniority)
SELECT
  seniority,
  skill,
  COUNT(*) as mentions,
  STRING_AGG(DISTINCT role_family, ', ') as roles
FROM job_skills
WHERE category IN ('ai_operational_skills', 'ai_cognitive_skills')
GROUP BY seniority, skill
ORDER BY seniority, mentions DESC;

-- Q5: Timeline of AI Adoption
SELECT
  DATE_TRUNC('week', scraped_at)::date as week,
  COUNT(*) as vacancies,
  ROUND(COUNT(CASE WHEN ai_level >= 2 THEN 1 END) * 100.0 / COUNT(*), 1) as pct_with_ai
FROM vacantes
GROUP BY DATE_TRUNC('week', scraped_at)
ORDER BY week DESC;

-- Q6: Company Type Analysis
SELECT
  company_type,
  COUNT(*) as vacancies,
  AVG(classification_confidence) as avg_confidence,
  COUNT(CASE WHEN ai_level >= 2 THEN 1 END) as with_ai
FROM vacantes
GROUP BY company_type
ORDER BY vacancies DESC;

-- Q7: Geographic Distribution
SELECT
  country,
  COUNT(*) as vacancies,
  COUNT(DISTINCT company_name) as companies,
  ROUND(AVG(classification_confidence), 3) as avg_confidence
FROM vacantes
WHERE country IS NOT NULL
GROUP BY country
ORDER BY vacancies DESC;
