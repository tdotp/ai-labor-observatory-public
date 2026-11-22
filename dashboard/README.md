# Metabase Dashboard Queries

This directory contains SQL queries designed for Metabase dashboard visualization on the VPS.

## Overview

The dashboard provides 7 core analytics queries to visualize AI adoption patterns in job postings:

1. **Q1: Vacancies by AI Level** - Distribution of job postings across AI skill requirements (0-5 scale)
2. **Q2: Top Skills by Category** - Most frequently requested skills organized by category
3. **Q3: Role Family Transformation** - Shows which job families are adopting AI skills most rapidly
4. **Q4: AI Skills Emergence** - AI-specific skills broken down by seniority level
5. **Q5: Timeline of AI Adoption** - Weekly trends showing AI adoption growth over time
6. **Q6: Company Type Analysis** - Compares AI adoption across different company types (holdings, startups, etc.)
7. **Q7: Geographic Distribution** - Geographic breakdown of job opportunities with AI requirements

## How to Use

### In Metabase UI:
1. Open Metabase at `http://YOUR_VPS_IP:3000`
2. Click "New Dashboard"
3. For each query:
   - Click "New Question" > "Native Query"
   - Copy the SQL from `queries.sql`
   - Run the query
   - Save as a card and add to dashboard

### Important Notes:
- These queries assume the Supabase PostgreSQL schema with tables: `vacantes` and `job_skills`
- Metabase runs on port 3000
- Queries are templates - modify WHERE clauses and date ranges as needed
- AI Level scale: 0 = No AI, 1 = Low, 2 = Medium, 3 = High, 4 = Very High, 5 = Expert-only

## Database Schema

### vacantes table:
- `ai_level` - Integer 0-5 indicating AI skill requirement
- `role_family` - Job family classification
- `company_type` - Type of company (holding, startup, etc.)
- `country` - Geographic location
- `classification_confidence` - Confidence score of AI classification
- `scraped_at` - Timestamp of data collection

### job_skills table:
- `skill` - Name of the skill
- `category` - Skill category (ai_operational_skills, ai_cognitive_skills, etc.)
- `seniority` - Required seniority level
- `role_family` - Associated job family

## Maintenance

- Update queries monthly to reflect latest data
- Monitor Metabase performance if dataset grows beyond 100k records
- Archive old dashboard snapshots for trend analysis
